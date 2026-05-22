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
        return handling
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


def _clean_name_for_dialog(product_name: str) -> str:
    """Strip bracket-enclosed store/listing tags from product name.

    Two-pass approach:
    - Pass 1: remove properly closed [tag] patterns
    - Pass 2: remove any trailing unclosed bracket tag (truncated marketplace listing)
    Returns the original string if nothing remains after cleaning, so callers
    can detect the failure and try another field.
    """
    # Pass 1: strip properly closed [tag] patterns
    cleaned = re.sub(r'\s*\[[^\]]*\]\s*', ' ', product_name).strip()
    # Pass 2: strip a trailing unclosed bracket tag (e.g. "[Buy 3 Free 1" at end of string)
    cleaned = re.sub(r'\s*\[[^\]]*$', '', cleaned).strip()
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
) -> list[str]:
    """Distribute available copy across shots as scripted spoken dialog lines.

    Returns a list of length ``shot_count``. Empty strings mean no scripted
    line for that shot (visual beat only).
    """
    if not dialogue_enabled or shot_count == 0:
        return [""] * shot_count

    hook_line = _clean(safe_hook) if (safe_hook and not _is_direction_text(safe_hook)) else ""
    cta_line = _clean(safe_cta) if (safe_cta and not _is_direction_text(safe_cta)) else ""

    # Split the rewrite into individual sentences for middle shots.
    # Each sentence is also filtered through _is_direction_text — directions
    # and bracket-tagged strings must never become spoken lines.
    raw_sentences = [
        s.strip()
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
    word_budget: int,
    continuation_from_block_id: str | None,
) -> str:
    """Build a clean, engine-ready prompt text.

    ALL structural text is in English.
    Dialog lines (DIALOG SCRIPT) are in the user's target_language.
    No internal directives, metadata, or bracket-tagged product names are emitted.

    Sections:
      1.  Visual style (English)
      2.  CHARACTER or SUBJECT — full persona description + mode annotation (English)
      3.  Mode anchor (English, F2V / I2V only) — uses bracket-stripped product ref
      4.  Continuation note (English, CONTINUATION blocks only)
      5.  Product handling (English)
      6.  AUDIO section — DIALOG SCRIPT with per-shot scripted lines (target_language)
              • Lines that are workflow directions are filtered out.
              • When NO valid scripted copy exists a BM_MS fallback is used so the
                operator does not see a WARNING for unconfigured products.
              • When dialogue_enabled=False: AUDIO: SILENT note only.
      7.  Shot breakdown with inline dialog annotations (English shot desc + target_language line)
      8.  OVERLAY — clean CTA copy only (target_language), COMPLETELY ABSENT when overlay_enabled=False
    """
    # Use the best available bracket-free product name (tries multiple fields,
    # handles both closed [tag] and truncated unclosed [tag patterns)
    dialog_product_ref = _best_product_dialog_name(product)
    parts: list[str] = []

    # ── 1. VISUAL STYLE (English) ──────────────────────────────────────────
    if camera_style == "CINEMATIC_PRO":
        parts.append(
            "Vertical cinematic commercial style. Controlled studio lighting, "
            "premium product handling, stabilised camera movement."
        )
    else:
        parts.append(
            "Vertical 9:16 handheld iPhone-style video. Natural indoor lighting, "
            "authentic UGC feel with organic pacing."
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
        len(shots), dialogue_enabled=dialogue_enabled,
    )

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
            script_lines.append(
                f"  Total spoken budget: ~{word_budget} words. "
                "Deliver lines in natural colloquial Malay (bahasa perbualan harian) — "
                "casual first-person experience sharing, as if a friend is talking about something "
                "they personally use. NOT a sales pitch. NOT formal Bahasa Malaysia. "
                "Use everyday vocabulary: 'aku', 'ni', 'tu', 'tak', 'dah', 'lah', 'kan', 'je'. "
                "Sound like personal sharing, not an advertisement."
            )
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
            script_lines = [f"DIALOG SCRIPT ({target_language}):"]
            for i, line in enumerate(fallback_segments, start=1):
                script_lines.append(f'  Shot {i}: "{line}"')
            script_lines.append(
                f"  Total spoken budget: ~{word_budget} words. "
                "Deliver lines in natural colloquial Malay (bahasa perbualan harian). "
                "Use everyday vocabulary: 'aku', 'ni', 'tu', 'tak', 'dah', 'lah', 'kan', 'je'. "
                "Sound like personal sharing, not an advertisement."
            )
            parts.append("\n".join(script_lines))
            dialog_segments = fallback_segments  # use for shot breakdown below

    # ── 7. SHOT BREAKDOWN with inline dialog (English shots, target_language lines) ──
    for shot, line in zip(shots, dialog_segments):
        if line:
            parts.append(f'{shot} | Audio: "{line}"')
        else:
            parts.append(shot)

    # ── 8. OVERLAY — only when overlay_enabled=True AND copy is valid (not a direction) ──
    #    Completely absent when overlay_enabled=False — no placeholder, no comment.
    if overlay_enabled:
        cta_copy = _clean(safe_cta)
        if cta_copy and not _is_direction_text(cta_copy):
            # Strip bracket tags from CTA copy before emitting (two-pass, handles unclosed)
            clean_cta = _clean_name_for_dialog(cta_copy)
            if clean_cta and not clean_cta.startswith("["):
                parts.append(f"OVERLAY TEXT: {clean_cta}")

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
        word_budget=word_budget,
        continuation_from_block_id=continuation_from_block_id,
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
    if resolved_character_presence == "FACELESS":
        warnings.append("FACELESS_MODE_REQUIRES_EXPLICIT_OPERATOR_CHOICE")

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
        "prompt_fingerprint": _fingerprint(final_compiled_prompt_text),
        "warnings": warnings,
        "blockers": [],
        "source_of_truth_notes": [
            "Compiler v1 uses internal product intelligence + claim-safe package + central compiler config.",
            "Sovereign/Satellite pack ingestion is future work.",
        ],
        "continuation_lineage": continuation_lineage,
        "runtime_config_snapshot": get_runtime_config(),
        "engine_target": _clean(engine_target) or _clean(approved_package.get("mode")) or normalized_mode,
    }
