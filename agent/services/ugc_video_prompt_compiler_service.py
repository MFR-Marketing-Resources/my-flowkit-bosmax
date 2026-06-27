from __future__ import annotations

import hashlib
import re
from typing import Any

from agent.services.prompt_compiler_runtime_config_service import (
    DEFAULT_CREATOR_PERSONA,
    DEFAULT_TARGET_LANGUAGE,
    PERSONA_REGISTRY,
    dialogue_word_budget,
    get_engine_mode_capability,
    get_runtime_config,
    get_shot_policy,
    normalize_camera_style,
    normalize_character_presence,
    normalize_creator_persona,
    normalize_generation_mode,
    normalize_target_language,
    validate_duration_seconds,
)
from agent.services.wps_chaining_policy_service import (
    LEGACY_UI_MAX_BLOCKS,
    WPS_STATUS_OVER_BUDGET,
    evaluate_block_wps,
    normalize_engine_duration_target,
    resolve_block_chain,
)


COMPILER_VERSION = "ugc_video_prompt_compiler_v1"
SUPPORTED_MODES = {"T2V", "F2V", "I2V", "IMG"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _title(product: dict[str, Any]) -> str:
    return _clean(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or product.get("product_short_name")
        or "the product"
    )


def _first_nonempty(values: list[str], fallback: str) -> str:
    for value in values:
        if _clean(value):
            return _clean(value)
    return fallback


def _handling_line(product: dict[str, Any], mode: str) -> str:
    handling = _clean(product.get("section_5_product_physics_prompt"))
    if handling:
        return _rewrite_physics_for_engine(handling)
    grip = _clean(product.get("recommended_grip"))
    if grip:
        return f"Product handling must remain believable with {grip} and clear label visibility."
    if mode == "F2V":
        return "Handle the product carefully with label visibility, honest scale, and clean HOI continuity."
    return "Keep product handling believable, steady, and true to the product form factor."


def _camera_profile(camera_style: str) -> dict[str, str]:
    if camera_style == "CINEMATIC_PRO":
        return {
            "style_line": "Use a vertical cinematic commercial look with controlled lighting, cleaner camera movement, and premium product handling.",
            "lens_line": "Prefer a premium vertical lens language with shallow depth when appropriate and stabilized premium motion.",
        }
    return {
        "style_line": "Use a vertical 9:16 handheld iPhone raw style with natural indoor light, micro-jitter, and believable UGC pacing.",
        "lens_line": "Prefer 24mm or 26mm wide-equivalent creator framing with natural handheld motion and imperfect human movement.",
    }


def _presence_line(character_presence: str, creator_persona: str) -> str:
    if character_presence == "FACELESS":
        return (
            "Faceless mode is explicit-only. Keep human presence indirect, but preserve coherent hand-object interaction and believable product handling."
        )
    persona = creator_persona or DEFAULT_CREATOR_PERSONA
    return (
        f"Use one visible creator persona ({persona}) and preserve the same face, wardrobe, body language, and delivery tone across all shots."
    )


def _mode_anchor_line(mode: str, product: dict[str, Any]) -> str:
    if mode == "F2V":
        return "Start from the verified product image as the visual anchor and preserve the same product truth across all shots."
    if mode == "I2V":
        return "Use the verified subject image as the anchor and keep any optional scene or style reference subordinate to product truth."
    if mode == "IMG":
        return "Generate a premium vertical image concept grounded in verified product truth and a believable commercial framing."
    return "Generate a text-driven commercial sequence grounded in verified product truth without inventing unsupported product claims."


def _dialogue_instruction(target_language: str, budget: int, *, dialogue_enabled: bool) -> str:
    if not dialogue_enabled:
        return "Do not include spoken dialogue. Allow visual storytelling and safe overlay only."
    return (
        f"Any spoken dialogue must stay in {target_language} and remain within about {budget} words total for this block."
    )


def _overlay_instruction(cta: str, *, overlay_enabled: bool) -> str:
    if not overlay_enabled:
        return "Do not force on-screen overlay. Keep the frame clean unless a minimal claim-safe label is necessary."
    return f"Use claim-safe on-screen overlay or CTA wording only where natural: {cta}"


_OVERLAY_MAX_WORDS = 5
_COMPACT_OVERLAY_ANCHORS: tuple[tuple[str, str], ...] = (
    ("link in bio", "Link in bio"),
    ("order now", "Order now"),
    ("shop now", "Shop now"),
    ("beli sekarang", "Beli sekarang"),
    ("dapatkan sekarang", "Dapatkan sekarang"),
    ("boleh dapatkan", "Dapatkan sekarang"),
    ("dapatkan di", "Dapatkan sekarang"),
    ("cuba sekarang", "Cuba sekarang"),
    ("boleh la try", "Cuba ni"),
    ("boleh try", "Cuba ni"),
    ("boleh cuba", "Cuba ni"),
    ("try la", "Cuba ni"),
    ("cuba ni", "Cuba ni"),
    ("try now", "Try now"),
    ("tengok sendiri", "Tengok sendiri"),
)


def _compact_overlay(cta: str) -> str | None:
    """Derive a short visual overlay phrase from spoken CTA copy.

    Overlay is never a verbatim copy of the full spoken sentence.
    Returns None (fail-closed) when no safe compact form can be produced —
    specifically when the CTA is already short enough that any truncation
    would be identical to the source or meaninglessly short.

    Rules:
    - CTA must have more than _OVERLAY_MAX_WORDS words — otherwise fail-closed.
    - First checks for known compact action-anchor phrases.
    - Falls back to first _OVERLAY_MAX_WORDS words of the CTA.
    """
    if not cta or _is_direction_text(cta):
        return None
    clean = _clean_name_for_dialog(cta)
    if not clean or clean.startswith("["):
        return None
    words = clean.split()
    # Fail-closed: short CTA cannot be made shorter without being identical or
    # meaninglessly truncated — omit overlay entirely.
    if len(words) <= _OVERLAY_MAX_WORDS:
        return None
    # Prefer embedded compact action anchors
    lowered = clean.lower()
    for needle, result in _COMPACT_OVERLAY_ANCHORS:
        if needle in lowered:
            return result
    # Fallback: first _OVERLAY_MAX_WORDS words (always shorter than full CTA)
    return " ".join(words[:_OVERLAY_MAX_WORDS])


# ── Engine-prompt helpers ──────────────────────────────────────────────────────

def _persona_visual_description(creator_persona: str) -> str:
    """Return the visual description text for the given persona ID from PERSONA_REGISTRY."""
    for p in PERSONA_REGISTRY:
        if p["id"] == creator_persona:
            return p.get("visual_description", "")
    return ""


def _is_direction_text(text: str) -> bool:
    """Return True if the text is a workflow direction rather than actual spoken copy.

    Catches English and Malay imperative/direction patterns so they are never
    sent to the video engine as scripted dialog or overlay text.
    """
    lowered = _clean(text).lower()
    if not lowered:
        return True

    # Bracket-enclosed tags anywhere in the text = internal product metadata, not dialog
    if re.search(r'\[.+?\]', text):
        return True

    # English direction prefixes
    en_prefixes = (
        "open with", "close with", "use ", "keep ", "generate ",
        "any spoken", "do not", "avoid ", "start with", "end with",
        "make sure", "ensure ", "follow ", "include a",
        "highlight ", "showcase ", "present ", "show how",
        "demonstrate ", "emphasize ", "focus on", "frame ",
        "capture ", "transition ", "cut to", "add ",
    )
    # Malay imperative/direction prefixes
    ms_prefixes = (
        "tonjolkan ", "tunjukkan ", "pastikan ", "gunakan ",
        "elakkan ", "mulakan ", "tamatkan ", "lihat bagaimana",
        "tumpukan ", "ketengahkan ", "perlihatkan ",
        "sertakan ", "tambahkan ", "hapuskan ", "buka dengan",
        "tutup dengan", "tunjuk ", "guna ", "papar ",
        "rakam ", "fokus pada", "ikut ", "masukkan ",
    )
    return any(lowered.startswith(p) for p in en_prefixes + ms_prefixes)


# ── Physics DNA → engine keyword mapping ──────────────────────────────────────

_SCALE_SIZE_MAP: dict[str, str] = {
    "SMALL_OBJECT": "product is small — fits naturally in one hand, fingers wrap fully around it.",
    "MICRO_OBJECT": "product is tiny — barely larger than a fingertip, handle with index and thumb only.",
    "MEDIUM_OBJECT": "product is medium palm-sized — two-hand or relaxed full-hand grip.",
    "LARGE_OBJECT": "product is full-size large — two-handed handling for honest visual scale.",
    "OVERSIZED": "product is oversized — keep both hands in frame for credible scale.",
    "SMALL_CONTAINER": "product is a small container — side hold with label facing camera.",
    "SMALL_TO_MEDIUM_OBJECT": "product fits in one or two hands — front label or face always readable.",
    "SMALL_FLAT_OBJECT": "product is flat and card-sized — light edge pinch, face fully readable.",
    "SOFT_PACK": "product is a soft pack — two-hand flat hold, front panel and seal readable.",
    "MEDIUM_PACK": "product is a medium soft pack — two-hand front-facing presentation.",
    "LIQUID_BOTTLE_OR_REFILL_PACK": "product is a liquid bottle or refill pouch — firm two-hand support, label and cap visible.",
    "PAIR_OBJECT": "product is a footwear pair — heel hold or sole support, profile and upper clearly shown.",
    "GARMENT": "product is a garment — two-hand spread or hang, silhouette and fabric fall readable.",
    "LARGE_SOFT_GOOD": "product is a large soft textile — two-hand spread or drape, thickness and weave visible.",
}

_PHYSICS_TYPE_SIZE_HINT: dict[str, str] = {
    # ── Beauty & skincare (most common) ────────────────────────────────────
    "BEAUTY_BOTTLE_OR_TUBE": "EXACTLY beauty bottle or tube size. Fits naturally in one hand — hold upright with label facing camera.",
    "SKINCARE_JAR_OR_TUBE": "EXACTLY skincare jar or tube size. Palm-cupped or two-finger side pinch, keep seal and label readable.",
    # ── Body spray / fragrance (legacy class A) ─────────────────────────
    "A": "EXACTLY perfume or body spray bottle size. Elegant pinch or side hold, label and nozzle clearly visible.",
    # ── Health & supplements ────────────────────────────────────────────
    "SUPPLEMENT_BOTTLE": "EXACTLY supplement bottle size. Upright single-hand hold with cap and label facing camera.",
    "MEDICAL_TEST_KIT": "EXACTLY slim test kit size. Mid-body pinch, test window and branding unobstructed.",
    # ── Food & beverage ─────────────────────────────────────────────────
    "FOOD_PACK_OR_JAR": "EXACTLY food jar or pack size. Side hold with label forward, sealed and food-safe appearance.",
    "B": "EXACTLY food jar or sachet size. Side hold with label facing camera, sealed appearance maintained.",
    # ── Household & cleaning ────────────────────────────────────────────
    "HOUSEHOLD_PACKAGED_GOODS": "EXACTLY household product pack size. Two-hand carry grip or one-hand side hold with label forward.",
    "LAUNDRY_LIQUID_REFILL": "EXACTLY liquid detergent bottle or refill pouch size. Firm two-hand support, label and pour edge visible.",
    "FABRIC_SOFTENER_LIQUID": "EXACTLY fabric softener bottle or refill pouch size. Firm two-hand support, cap and label visible.",
    "RIGID_CONTAINER": "EXACTLY storage container size. Side grip or lid-edge hold, lid open-close action clearly visible.",
    # ── Kitchen ─────────────────────────────────────────────────────────
    "KITCHEN_TOOL": "EXACTLY kitchen utensil or tool size. Handle grip, working surface and functional details facing camera.",
    # ── Electronics ─────────────────────────────────────────────────────
    "ELECTRONICS_SMALL_DEVICE": "EXACTLY small consumer device size. Balanced side grip, controls, screen, and ports clearly visible.",
    # ── Stationery & paper ──────────────────────────────────────────────
    "STATIONERY_PACK": "EXACTLY stationery pack size. Edge pinch with printed face fully readable and unobstructed.",
    "PAPER_GOODS": "EXACTLY paper goods size. Light corner or edge pinch, printed face clearly visible.",
    # ── Toys ────────────────────────────────────────────────────────────
    "TOY_BOX_OR_PACK": "EXACTLY toy or craft pack size. Light two-hand hold with front panel facing camera.",
    # ── Decor & accessories ─────────────────────────────────────────────
    "SMALL_RIGID_DECOR": "EXACTLY small decorative object size. Front face forward, slow controlled turns.",
    "FASHION_ACCESSORY_SMALL_OBJECT": "EXACTLY small fashion accessory size. Light edge pinch with decorative face and clasp detail fully visible.",
    # ── Soft goods & wipes ──────────────────────────────────────────────
    "WIPES_SOFT_PACK": "EXACTLY soft wipes pack size. Two-hand flat hold, front panel and seal clearly readable.",
    "SOFT_PACKAGED_GOODS": "EXACTLY soft goods pack size. Two-hand front-facing hold with label forward.",
    # ── Garments / textiles ─ no size-keyword needed, camera notes cover it
}


def _rewrite_physics_for_engine(raw: str) -> str:
    """Convert raw Physics DNA text into a clean, engine-ready product handling directive.

    Strips all internal metadata labels (Physics DNA, Scale, Material behavior, etc.).
    Maps Scale/Type to concise size keywords. Preserves camera handling notes and avoid-list.
    """
    if not raw or "Physics DNA:" not in raw:
        return raw

    physics_type = ""
    m = re.search(r"Physics DNA:\s*([A-Z_]+)", raw)
    if m:
        physics_type = m.group(1).strip()

    scale = ""
    m = re.search(r"Scale:\s*([A-Z_]+)", raw)
    if m:
        scale = m.group(1).strip()

    camera_notes = ""
    m = re.search(r"Camera handling notes:\s*(.+?)(?=\.\s*(?:Avoid:|$))", raw, re.DOTALL)
    if m:
        camera_notes = re.sub(r"\.\.+", ".", m.group(1).strip().rstrip("."))
    if not camera_notes:
        m = re.search(r"Camera handling notes:\s*(.+?)$", raw, re.DOTALL)
        if m:
            camera_notes = re.sub(r"\.\.+", ".", m.group(1).strip().rstrip("."))

    avoid_notes = ""
    m = re.search(r"Avoid:\s*(.+?)$", raw, re.DOTALL)
    if m:
        avoid_notes = m.group(1).strip().rstrip(".")

    parts: list[str] = []
    if physics_type in _PHYSICS_TYPE_SIZE_HINT:
        parts.append(_PHYSICS_TYPE_SIZE_HINT[physics_type])
    elif scale in _SCALE_SIZE_MAP:
        parts.append(f"Product size: {_SCALE_SIZE_MAP[scale]}")

    if camera_notes:
        parts.append(camera_notes + ".")

    if avoid_notes:
        parts.append(f"Avoid: {avoid_notes}.")

    return " ".join(parts) if parts else raw


def _clean_dialog_line(text: str) -> str:
    """Strip TTS-hostile symbols from a dialog line.

    Removes (parenthesis) variant tags and replaces dash sentence-separators with comma.
    """
    cleaned = _clean_name_for_dialog(text)
    cleaned = re.sub(r"\s+-\s+", ", ", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    return cleaned.strip()


def _trim_to_word_budget(text: str, max_words: int) -> str:
    """Trim dialog copy to fit within max_words, cutting at a natural boundary."""
    if not text:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words])
    last_punct = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind(","), trimmed.rfind("?"))
    if last_punct > len(trimmed) // 2:
        return trimmed[:last_punct + 1]
    return trimmed


def _enforce_segment_budget(segments: list[str], word_budget: int) -> list[str]:
    """Hard-cap spoken segments so their combined word count never exceeds budget.

    Distributes ``word_budget`` across the non-empty (spoken) segments only, so
    visual-beat slots never consume budget. Each spoken segment is trimmed to its
    allotment; segments whose allotment rounds to zero are dropped. Because the
    per-segment caps sum to exactly ``word_budget``, the total spoken word count
    is guaranteed ``<= word_budget`` — including the BM_MS fallback path.
    """
    if word_budget <= 0:
        return segments
    spoken_positions = [i for i, seg in enumerate(segments) if seg]
    spoken_count = len(spoken_positions)
    if spoken_count == 0:
        return segments
    base, remainder = divmod(word_budget, spoken_count)
    out = list(segments)
    for rank, position in enumerate(spoken_positions):
        cap = base + (1 if rank < remainder else 0)
        out[position] = _trim_to_word_budget(out[position], cap) if cap > 0 else ""
    return out


def _clean_name_for_dialog(product_name: str) -> str:
    """Strip bracket/parenthesis-enclosed store/listing tags from product name.

    Passes:
    - Strip properly closed [tag] patterns (marketplace listing tags)
    - Strip properly closed (tag) patterns (variant descriptors like "(Mix Berry)")
    - Strip any trailing unclosed bracket/paren tag (truncated marketplace listing)
    - Collapse multiple spaces and clean up orphaned hyphens/dashes
    Returns the original string if nothing remains after cleaning.
    """
    cleaned = product_name
    # Strip [square bracket] tags
    cleaned = re.sub(r'\s*\[[^\]]*\]\s*', ' ', cleaned).strip()
    cleaned = re.sub(r'\s*\[[^\]]*$', '', cleaned).strip()
    # Strip (parenthesis) tags — variant flavours/colours like "(Mix Berry)"
    cleaned = re.sub(r'\s*\([^)]*\)\s*', ' ', cleaned).strip()
    cleaned = re.sub(r'\s*\([^)]*$', '', cleaned).strip()
    # Clean up orphaned leading/trailing hyphens and extra spaces left after stripping
    cleaned = re.sub(r'(\s*-\s*)+$', '', cleaned).strip()
    cleaned = re.sub(r'^(\s*-\s*)+', '', cleaned).strip()
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned if cleaned else product_name


def _best_product_dialog_name(product: dict[str, Any]) -> str:
    """Get the best bracket-free product name for dialog / anchor text.

    Tries product_display_name → raw_product_title → product_short_name.
    Returns the first result that is non-empty and does not start with a
    bracket tag (meaning it's a real product name, not leftover listing junk).
    Falls back to "produk ini" if no clean name can be extracted.
    """
    for field in ("product_display_name", "raw_product_title", "product_short_name"):
        raw = _clean(product.get(field) or "")
        if not raw:
            continue
        cleaned = _clean_name_for_dialog(raw)
        # Accept only if non-empty and no residual bracket tag at the start
        if cleaned and not cleaned.startswith("["):
            return cleaned
    return "produk ini"


def _split_dialog_segments(
    safe_hook: str,
    claim_safe_rewrite: str,
    safe_cta: str,
    shot_count: int,
    *,
    dialogue_enabled: bool,
    word_budget: int = 0,
) -> list[str]:
    """Distribute available copy across shots as scripted spoken dialog lines.

    Returns a list of length ``shot_count``. Empty strings mean no scripted
    line for that shot (visual beat only).
    Lines are cleaned of TTS-hostile symbols and trimmed to word budget per shot.
    """
    if not dialogue_enabled or shot_count == 0:
        return [""] * shot_count

    hook_line = _clean_dialog_line(_clean(safe_hook)) if (safe_hook and not _is_direction_text(safe_hook)) else ""
    cta_line = _clean_dialog_line(_clean(safe_cta)) if (safe_cta and not _is_direction_text(safe_cta)) else ""

    # Split the rewrite into individual sentences for middle shots.
    # Each sentence is also filtered through _is_direction_text — directions
    # and bracket-tagged strings must never become spoken lines.
    raw_sentences = [
        _clean_dialog_line(s.strip())
        for s in _clean(claim_safe_rewrite).replace("!", ".").replace("?", ".").split(".")
        if s.strip() and not _is_direction_text(s.strip())
    ]

    segments: list[str] = []
    for i in range(shot_count):
        if i == 0 and hook_line:
            segments.append(hook_line)
        elif i == shot_count - 1 and cta_line:
            segments.append(cta_line)
        else:
            if raw_sentences:
                mid_index = min(i, len(raw_sentences) - 1)
                segments.append(raw_sentences[mid_index] + ".")
            else:
                segments.append("")

    # Enforce WPS word budget: trim each line to its per-shot allocation
    if word_budget > 0 and shot_count > 0:
        budget_per_shot = max(6, word_budget // shot_count)
        segments = [_trim_to_word_budget(s, budget_per_shot) if s else s for s in segments]

    return segments


def _build_engine_prompt_text(
    *,
    product: dict[str, Any],
    mode: str,
    block_role: str,
    camera_style: str,
    character_presence: str,
    creator_persona: str,
    target_language: str,
    dialogue_enabled: bool,
    overlay_enabled: bool,
    safe_hook: str,
    claim_safe_rewrite: str,
    safe_cta: str,
    shots: list[str],
    continuation_from_block_id: str | None,
    word_budget: int = 0,
) -> str:
    """Build a clean, engine-ready prompt text.

    ALL structural text is in English.
    Dialog lines (DIALOG SCRIPT) are in the user's target_language.
    No internal directives, metadata, or bracket-tagged product names are emitted.

    Sections:
      1.  Visual style — concrete framing, movement, and lighting directives (English)
      2.  CHARACTER or SUBJECT — full persona description + mode annotation (English)
      3.  Mode anchor (English, F2V / I2V only) — uses bracket-stripped product ref
      4.  Continuation note (English, CONTINUATION blocks only)
      5.  Product handling (English)
      6.  AUDIO section — DIALOG SCRIPT once only, no internal policy notes
              • Lines that are workflow directions are filtered out.
              • When NO valid scripted copy exists a BM_MS fallback is used.
              • When dialogue_enabled=False: AUDIO: SILENT note only.
      7.  Shot breakdown — visual descriptions only (no repeated dialog lines)
      8.  OVERLAY — compact derived phrase (≤5 words), ABSENT when overlay_enabled=False
              or when no safe compact form can be produced from the CTA.
    """
    # Use the best available bracket-free product name (tries multiple fields,
    # handles both closed [tag] and truncated unclosed [tag patterns)
    dialog_product_ref = _best_product_dialog_name(product)
    parts: list[str] = []

    # ── 1. VISUAL STYLE — concrete camera directives (English) ────────────
    if camera_style == "CINEMATIC_PRO":
        parts.append(
            "Vertical 9:16 cinematic. MCU to CU framing with clean stable composition. "
            "Minimal camera drift — no intentional shake. Shallow depth of field where appropriate. "
            "Controlled soft studio lighting with consistent exposure across shots."
        )
    else:
        parts.append(
            "Vertical 9:16 handheld. MCU to CU framing, eye-level angle with natural low-angle product reveals. "
            "24–26mm wide-equivalent; intentional micro-jitter and organic human sway. "
            "Soft ambient or window light — no flash, no hard fill. Consistent room lighting across all shots."
        )

    # ── 2. CHARACTER / SUBJECT (English description) ──────────────────────
    if character_presence == "AVATAR_AI":
        visual_desc = _persona_visual_description(creator_persona or DEFAULT_CREATOR_PERSONA)
        base = visual_desc if visual_desc else "Consistent on-screen AI avatar."
        parts.append(
            f"CHARACTER (AI AVATAR — LIP-SYNC): {base} "
            "AI-generated avatar throughout. Mouth movements must be perfectly lip-synced "
            "to every spoken dialog line. Maintain identical avatar appearance, lighting, "
            "and wardrobe across all shots."
        )
    elif character_presence == "FACELESS":
        parts.append(
            f"SUBJECT (FACELESS): Product and hands only — {dialog_product_ref}. "
            "No face or avatar shown on screen. Believable hand-object interaction, "
            "clear label visibility, honest product scale. "
            "Creator voice is heard as narration/voiceover but never seen. "
            "Brief avatar cameo allowed at a single natural moment if it improves product credibility."
        )
    else:
        # VISIBLE_CREATOR (default)
        visual_desc = _persona_visual_description(creator_persona or DEFAULT_CREATOR_PERSONA)
        if visual_desc:
            parts.append(f"CHARACTER: {visual_desc}")
        else:
            parts.append(
                "CHARACTER: One visible creator on screen. Consistent appearance, "
                "natural delivery and body language throughout."
            )

    # ── 3. MODE-SPECIFIC ANCHOR (English) — bracket-stripped product ref ─
    if mode == "F2V":
        parts.append(
            f"ANCHOR: Reference image of {dialog_product_ref} is the visual anchor. "
            "Preserve exact product appearance — colour, label, cap, size — across all shots."
        )
    elif mode == "I2V":
        parts.append(
            f"ANCHOR: Subject image of {dialog_product_ref}. "
            "Scene and style references are subordinate to verified product appearance."
        )

    # ── 4. CONTINUATION (English) ─────────────────────────────────────────
    if block_role == "CONTINUATION" and continuation_from_block_id:
        parts.append(
            "CONTINUATION: Continue directly from the previous scene — "
            "same character, same product state, same setting, same camera logic. No discontinuity."
        )

    # ── 5. PRODUCT HANDLING (English) ─────────────────────────────────────
    parts.append(_handling_line(product, mode))

    # ── 6. AUDIO / DIALOG SCRIPT (target_language) ───────────────────────
    dialog_segments = _split_dialog_segments(
        safe_hook, claim_safe_rewrite, safe_cta,
        len(shots), dialogue_enabled=dialogue_enabled, word_budget=word_budget,
    )
    # Final WPS guard: guarantee total spoken words <= per-block budget.
    dialog_segments = _enforce_segment_budget(dialog_segments, word_budget)

    if not dialogue_enabled:
        parts.append("AUDIO: Silent — no spoken dialogue. Visual storytelling only.")
    else:
        valid_lines = [ln for ln in dialog_segments if ln]
        if valid_lines:
            script_lines = [f"DIALOG SCRIPT ({target_language}):"]
            for i, line in enumerate(dialog_segments, start=1):
                if line:
                    script_lines.append(f'  Shot {i}: "{line}"')
                else:
                    script_lines.append(f"  Shot {i}: (visual beat — no spoken line)")
            if character_presence == "AVATAR_AI":
                script_lines.append(
                    "  LIP-SYNC REQUIREMENT: AI avatar mouth must match every word precisely. "
                    "Do not generate avatar speaking without a scripted line."
                )
            parts.append("\n".join(script_lines))
        else:
            # No valid copy found — emit a BM_MS generic fallback so the engine
            # has actual spoken lines instead of a WARNING placeholder.
            fallback_hook = f"Cuba {dialog_product_ref} ni — memang sesuai untuk rutin harian."
            fallback_cta = f"Tengok sendiri perbezaan dia dengan {dialog_product_ref}."
            fallback_mid = f"Aku rasa {dialog_product_ref} ni okay je untuk guna hari-hari."
            fallback_segments: list[str] = []
            for i in range(len(shots)):
                if i == 0:
                    fallback_segments.append(fallback_hook)
                elif i == len(shots) - 1:
                    fallback_segments.append(fallback_cta)
                else:
                    fallback_segments.append(fallback_mid)
            # Fallback copy must respect the same per-block WPS budget.
            fallback_segments = _enforce_segment_budget(fallback_segments, word_budget)
            script_lines = [f"DIALOG SCRIPT ({target_language}):"]
            for i, line in enumerate(fallback_segments, start=1):
                if line:
                    script_lines.append(f'  Shot {i}: "{line}"')
                else:
                    script_lines.append(f"  Shot {i}: (visual beat — no spoken line)")
            parts.append("\n".join(script_lines))
            dialog_segments = fallback_segments  # use for shot breakdown below

    # ── 7. SHOT BREAKDOWN — visual descriptions only, no repeated dialog lines ──
    for shot in shots:
        parts.append(shot)

    # ── 8. OVERLAY — compact derived phrase only, COMPLETELY ABSENT when overlay_enabled=False ──
    if overlay_enabled:
        overlay_text = _compact_overlay(_clean(safe_cta))
        if overlay_text:
            parts.append(f"OVERLAY TEXT: {overlay_text}")

    return "\n".join(p for p in parts if p)


def _shot_blueprint(
    shot_count: int,
    *,
    mode: str,
    block_role: str,
    product_name: str,
    product_name_clean: str | None = None,
) -> list[str]:
    # Use bracket-stripped name in shot descriptions to avoid metadata leaking into the engine prompt
    display_name = product_name_clean if product_name_clean else product_name
    templates = [
        f"Shot 1: MCU visible creator enters naturally, establishes the product context, and reveals {display_name} with believable hand-object interaction.",
        f"Shot 2: CU product handling close-up with label-safe framing, honest scale, and tactile HOI emphasis.",
        f"Shot 3: Medium or product close-up continuation that reinforces product truth, safe hook, and clear commercial pacing.",
        f"Shot 4: Alternate angle or movement beat that keeps the same creator, product state, and commercial tone.",
        f"Shot 5: Tight product close-up with premium handling, clean lighting, and stable product truth.",
        f"Shot 6: Resolution beat with safe CTA and continued creator or product continuity.",
    ]
    if mode == "IMG":
        templates = [
            f"Shot 1: Compose a single premium hero framing around {display_name} with visible creator presence where selected and clean product truth.",
            f"Shot 2: Use an optional supporting angle only if required by the image concept, while preserving the same creator and product continuity.",
        ]
    if block_role == "CONTINUATION":
        templates[0] = (
            f"Shot 1: Continue immediately from the previous block with the same creator, same wardrobe, same product state, and coherent camera logic around {display_name}."
        )
    return templates[:shot_count]


def _compile_block(
    *,
    product: dict[str, Any],
    mode: str,
    block_index: int,
    block_role: str,
    duration_seconds: int,
    camera_style: str,
    character_presence: str,
    creator_persona: str,
    target_language: str,
    claim_safe_rewrite: str,
    safe_hook: str,
    safe_cta: str,
    dialogue_enabled: bool,
    overlay_enabled: bool,
    continuation_from_block_id: str | None,
) -> dict[str, Any]:
    shot_policy = get_shot_policy(duration_seconds)
    shot_count = shot_policy["recommended"]
    word_budget = dialogue_word_budget(
        duration_seconds,
        target_language,
        dialogue_enabled=dialogue_enabled,
    )
    product_name = _title(product)
    product_name_clean = _clean_name_for_dialog(product_name)
    camera_profile = _camera_profile(camera_style)
    shots = _shot_blueprint(
        shot_count,
        mode=mode,
        block_role=block_role,
        product_name=product_name,
        product_name_clean=product_name_clean,
    )
    lines = [
        f"Block {block_index} ({block_role})",
        camera_profile["style_line"],
        camera_profile["lens_line"],
        _presence_line(character_presence, creator_persona),
        _mode_anchor_line(mode, product),
        f"Duration: {duration_seconds} seconds. Recommended shot count: {shot_count}.",
        f"Safe hook direction: {safe_hook}",
        f"Claim-safe copy anchor: {claim_safe_rewrite}",
        _dialogue_instruction(
            target_language,
            word_budget,
            dialogue_enabled=dialogue_enabled,
        ),
        _overlay_instruction(safe_cta, overlay_enabled=overlay_enabled),
        _handling_line(product, mode),
        "Keep the same creator identity, same product truth, same scene logic where possible, and no unsafe medical or sexual-performance claims.",
        *shots,
    ]
    if continuation_from_block_id:
        lines.insert(
            5,
            f"Continuation requirement: continue from {continuation_from_block_id} with the same narrative, dialogue, creator look, product state, and camera logic.",
        )

    # Engine-ready text: clean visual description only — no internal directives or metadata
    engine_prompt_text = _build_engine_prompt_text(
        product=product,
        mode=mode,
        block_role=block_role,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        target_language=target_language,
        dialogue_enabled=dialogue_enabled,
        overlay_enabled=overlay_enabled,
        safe_hook=safe_hook,
        claim_safe_rewrite=claim_safe_rewrite,
        safe_cta=safe_cta,
        shots=shots,
        continuation_from_block_id=continuation_from_block_id,
        word_budget=word_budget,
    )

    return {
        "block_id": f"block_{block_index}",
        "block_index": block_index,
        "block_role": block_role,
        "duration_seconds": duration_seconds,
        "shot_count": shot_count,
        "dialogue_word_budget": word_budget,
        "continuation_from_block_id": continuation_from_block_id,
        "compiled_prompt_text": "\n".join(lines),    # full internal directive view (debug/display)
        "engine_prompt_text": engine_prompt_text,     # clean engine-ready text (sent to AI engine)
        "shot_plan": shots,
    }


def _normalize_blocks(
    *,
    generation_mode: str,
    duration_seconds: int,
    blocks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if generation_mode == "SINGLE":
        return [
            {
                "block_index": 1,
                "block_role": "ANCHOR",
                "duration_seconds": validate_duration_seconds(duration_seconds),
            }
        ]
    normalized: list[dict[str, Any]] = []
    source_blocks = list(blocks or [])[:2]
    if not source_blocks:
        source_blocks = [
            {"block_index": 1, "duration_seconds": duration_seconds},
            {"block_index": 2, "duration_seconds": duration_seconds},
        ]
    for idx, block in enumerate(source_blocks, start=1):
        normalized.append(
            {
                "block_index": idx,
                "block_role": "ANCHOR" if idx == 1 else "CONTINUATION",
                "duration_seconds": validate_duration_seconds(
                    int(block.get("duration_seconds") or duration_seconds),
                ),
            }
        )
    if len(normalized) == 1:
        normalized.append(
            {
                "block_index": 2,
                "block_role": "CONTINUATION",
                "duration_seconds": validate_duration_seconds(duration_seconds),
            }
        )
    return normalized[:2]


def _blocks_from_chain(block_chain: list[int]) -> list[dict[str, Any]]:
    """Build N normalized blocks from a resolved engine duration chain.

    The first block is the ANCHOR; every subsequent block is a CONTINUATION.
    Each block duration is validated individually (chains only use 6/8/10s,
    all members of ALLOWED_BLOCK_DURATIONS_SECONDS). This deliberately bypasses
    the legacy 2-block cap so WPS chaining can produce 3+ blocks.
    """
    return [
        {
            "block_index": index,
            "block_role": "ANCHOR" if index == 1 else "CONTINUATION",
            "duration_seconds": validate_duration_seconds(duration),
        }
        for index, duration in enumerate(block_chain, start=1)
    ]


def compile_ugc_video_prompt(
    *,
    product: dict[str, Any],
    approved_package: dict[str, Any],
    mode: str,
    camera_style: str | None = None,
    character_presence: str | None = None,
    creator_persona: str | None = None,
    target_language: str | None = None,
    generation_mode: str | None = None,
    duration_seconds: int = 8,
    blocks: list[dict[str, Any]] | None = None,
    engine_target: str | None = None,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
    claim_safe_rewrite: str | None = None,
    safe_hook_angles: list[str] | None = None,
    safe_cta_angles: list[str] | None = None,
) -> dict[str, Any]:
    normalized_mode = str(mode or "").strip().upper()
    if normalized_mode not in SUPPORTED_MODES:
        raise ValueError(f"UNSUPPORTED_MODE:{normalized_mode}")
    resolved_generation_mode = normalize_generation_mode(generation_mode)
    resolved_camera_style = normalize_camera_style(camera_style)
    resolved_character_presence = normalize_character_presence(character_presence)
    resolved_creator_persona = normalize_creator_persona(creator_persona)
    resolved_target_language = normalize_target_language(target_language)
    capability = get_engine_mode_capability(normalized_mode)
    if resolved_generation_mode not in capability.get("supports_generation_modes", []):
        raise ValueError(
            f"GENERATION_MODE_NOT_SUPPORTED_FOR_MODE:{normalized_mode}:{resolved_generation_mode}",
        )

    resolved_claim_safe_rewrite = _clean(claim_safe_rewrite or approved_package.get("claim_safe_rewrite"))
    safe_hook = _first_nonempty(
        list(safe_hook_angles or []),
        "Open with a believable creator-led commercial hook that keeps the product context clear and claim-safe.",
    )
    safe_cta = _first_nonempty(
        list(safe_cta_angles or []),
        "Close with a calm, claim-safe CTA that stays product-first and commercially credible.",
    )
    # ── Engine duration → block-chain resolution (WPS Blocking Template) ──
    # Active only when BOTH the engine vendor and a requested total are given.
    # When absent, the legacy SINGLE/EXTEND block path is byte-for-byte unchanged.
    resolved_engine_duration_target: str | None = None
    resolved_block_chain: list[int] | None = None
    if engine_duration_target is not None and requested_total_duration_seconds is not None:
        resolved_engine_duration_target = normalize_engine_duration_target(
            engine_duration_target,
        )
        # Raises ValueError on an invalid engine/total combination (rejected, not silent).
        resolved_block_chain = resolve_block_chain(
            resolved_engine_duration_target,
            requested_total_duration_seconds,
        )

    if resolved_block_chain is not None:
        normalized_blocks = _blocks_from_chain(resolved_block_chain)
    else:
        normalized_blocks = _normalize_blocks(
            generation_mode=resolved_generation_mode,
            duration_seconds=duration_seconds,
            blocks=blocks,
        )
    compiled_blocks: list[dict[str, Any]] = []
    continuation_lineage: list[dict[str, Any]] = []
    for block in normalized_blocks:
        previous_block_id = (
            compiled_blocks[-1]["block_id"]
            if block["block_role"] == "CONTINUATION" and compiled_blocks
            else None
        )
        compiled = _compile_block(
            product=product,
            mode=normalized_mode,
            block_index=block["block_index"],
            block_role=block["block_role"],
            duration_seconds=block["duration_seconds"],
            camera_style=resolved_camera_style,
            character_presence=resolved_character_presence,
            creator_persona=resolved_creator_persona,
            target_language=resolved_target_language,
            claim_safe_rewrite=resolved_claim_safe_rewrite,
            safe_hook=safe_hook,
            safe_cta=safe_cta,
            dialogue_enabled=dialogue_enabled,
            overlay_enabled=overlay_enabled,
            continuation_from_block_id=previous_block_id,
        )
        compiled_blocks.append(compiled)
        if previous_block_id:
            continuation_lineage.append(
                {
                    "block_index": compiled["block_index"],
                    "continuation_from_block_id": previous_block_id,
                    "continuation_strategy": "SAME_CREATOR_PRODUCT_SCENE_CAMERA_COPY_ROUTE",
                }
            )

    # `compiled_prompt_text` (with internal directives) is preserved per-block for debugging.
    # `engine_prompt_text` is the clean engine-ready text sent to the AI video engine.
    final_compiled_prompt_text = "\n\n".join(
        block["engine_prompt_text"] for block in compiled_blocks
    )
    warnings: list[str] = []
    blockers: list[str] = []
    if resolved_character_presence == "FACELESS":
        warnings.append("FACELESS_MODE_REQUIRES_EXPLICIT_OPERATOR_CHOICE")

    # ── WPS enforcement: count actual spoken words and grade each block ──
    for block in compiled_blocks:
        wps = evaluate_block_wps(
            engine_prompt_text=block["engine_prompt_text"],
            dialogue_word_budget=block["dialogue_word_budget"],
        )
        block["actual_dialogue_word_count"] = wps["actual_dialogue_word_count"]
        block["wps_status"] = wps["wps_status"]
        if wps["wps_status"] == WPS_STATUS_OVER_BUDGET:
            blockers.append(
                "WPS_OVER_BUDGET:block_{index}:{actual}>{budget}".format(
                    index=block["block_index"],
                    actual=wps["actual_dialogue_word_count"],
                    budget=block["dialogue_word_budget"],
                )
            )

    # Resolved chain reflects what was actually compiled, regardless of path.
    compiled_block_chain = [block["duration_seconds"] for block in compiled_blocks]
    if resolved_block_chain is not None:
        resolved_block_chain_source = "ENGINE_DURATION_POLICY"
        # Backend enforces N blocks even though the current 2-block UI cannot
        # represent them — surface a clear blocker for that unsupported UI path.
        if len(resolved_block_chain) > LEGACY_UI_MAX_BLOCKS:
            blockers.append(
                "CHAIN_REQUIRES_MULTI_BLOCK_UI:{n}_BLOCKS".format(
                    n=len(resolved_block_chain),
                )
            )
    else:
        resolved_block_chain_source = "LEGACY_BLOCKS"

    return {
        "final_compiled_prompt_text": final_compiled_prompt_text,
        "prompt_blocks": compiled_blocks,
        "compiler_version": COMPILER_VERSION,
        "generation_mode": resolved_generation_mode,
        "total_duration_seconds": sum(block["duration_seconds"] for block in compiled_blocks),
        "camera_style": resolved_camera_style,
        "character_presence": resolved_character_presence,
        "creator_persona": resolved_creator_persona,
        "target_language": resolved_target_language,
        "shot_plan": [
            {
                "block_index": block["block_index"],
                "shot_count": block["shot_count"],
                "shots": block["shot_plan"],
            }
            for block in compiled_blocks
        ],
        "dialogue_word_budget_per_block": [
            block["dialogue_word_budget"] for block in compiled_blocks
        ],
        "actual_dialogue_word_count_per_block": [
            block["actual_dialogue_word_count"] for block in compiled_blocks
        ],
        "wps_status_per_block": [
            block["wps_status"] for block in compiled_blocks
        ],
        "engine_duration_target": resolved_engine_duration_target,
        "requested_total_duration_seconds": (
            int(requested_total_duration_seconds)
            if requested_total_duration_seconds is not None
            else None
        ),
        "resolved_block_chain": compiled_block_chain,
        "resolved_block_chain_source": resolved_block_chain_source,
        "prompt_fingerprint": _fingerprint(final_compiled_prompt_text),
        "warnings": warnings,
        "blockers": blockers,
        "source_of_truth_notes": [
            "Compiler v1 uses internal product intelligence + claim-safe package + central compiler config.",
            "Sovereign/Satellite pack ingestion is future work.",
        ],
        "continuation_lineage": continuation_lineage,
        "runtime_config_snapshot": get_runtime_config(),
        "engine_target": _clean(engine_target) or _clean(approved_package.get("mode")) or normalized_mode,
    }
