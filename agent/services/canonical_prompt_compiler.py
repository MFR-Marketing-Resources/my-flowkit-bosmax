"""THE canonical final prompt compiler — single engine-facing authority (ADR-008).

One deterministic, section-driven, source-mode-aware, WPS-governed renderer for
every final engine-facing prompt across T2V / HYBRID / FRAMES / INGREDIENTS /
IMAGES. Authority = the retained pack files vendored under agent/authority/:

- VIDEO_PROMPT_COMPILER_TEMPLATES.yaml   canonical 9 sections + source-mode law
- BOSMAX_CUSTOM_INSTRUCTION.txt          prompt language lock + scrub law
- wps_blocking_authority.json            block plans (1-7) + per-language WPS
- AVATAR_POOL_NORMALIZED.csv             presenter registry (via avatar_registry)
- COPYWRITING_FRAMEWORK_UNIVERSAL.yaml   copy intelligence (secondary reference)

Contract highlights (retained law):
- exactly one complete 9-section set per block, canonical order;
- Sections 1,2,3,4,5,7,8,9 = English instruction prose; Section 6 = target
  language spoken dialogue ONLY;
- SafeWPS default, SweetWPS deliberate mode (Malay Sweet = 2.7 from workbook);
- dialogue budget is per block, never whole-prompt filler;
- CTA lands only in the final block;
- NO_OVERLAY default;
- no leakage: no source-mode taxonomy, WPS numbers, block plans, debug JSON,
  avatar-pool references, or generic placeholder presenter wording.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.services import avatar_registry

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"

CANONICAL_SECTIONS = (
    "SECTION 1 - ROLE & OBJECTIVE",
    "SECTION 2 - PRODUCT TRUTH LOCK",
    "SECTION 3 - CONTINUITY & STATE LOCK",
    "SECTION 4 - VISUAL STORY",
    "SECTION 5 - SHOT & CAMERA RULES",
    "SECTION 6 - SPOKEN DIALOGUE",
    "SECTION 7 - VOICE & DELIVERY",
    "SECTION 8 - CTA & END FRAME",
    "SECTION 9 - NO_OVERLAY",
)

SOURCE_MODES = ("T2V", "HYBRID", "FRAMES", "INGREDIENTS", "IMAGES")

_LANGUAGE_NAMES = {
    "BM_MS": "Malay", "MALAY": "Malay", "MS": "Malay",
    "EN": "English", "ENGLISH": "English",
    "ID": "Indonesian", "INDONESIAN": "Indonesian",
    "ZH": "Mandarin", "MANDARIN": "Mandarin",
    "TA": "Tamil", "TAMIL": "Tamil",
    "TH": "Thai", "THAI": "Thai",
}

_FORMULA_FAMILIES = ("PAS", "AIDA", "HSO", "BAB", "PESTA", "PASTOR")


@lru_cache(maxsize=1)
def _wps_authority() -> dict:
    with open(_AUTHORITY_DIR / "wps_blocking_authority.json", encoding="utf-8") as f:
        return json.load(f)


def language_name(target_language: str | None) -> str:
    key = str(target_language or "BM_MS").strip().upper()
    return _LANGUAGE_NAMES.get(key, "Malay")


def wps_profile(target_language: str | None) -> dict:
    profile = _wps_authority()["language_wps"].get(language_name(target_language))
    if not profile:
        raise ValueError(f"LANGUAGE_WPS_MISSING:{target_language}")
    return profile


def dialogue_word_budget(
    block_seconds: int, target_language: str | None, *, wps_mode: str = "SAFE",
) -> int:
    """Per-block dialogue budget from WORKBOOK authority. SafeWPS default;
    SweetWPS is the deliberate dialogue-targeting mode (Malay Sweet = 2.7)."""
    profile = wps_profile(target_language)
    rate = profile["sweet_wps"] if str(wps_mode).upper() == "SWEET" else profile["safe_wps"]
    return max(4, round(block_seconds * float(rate)))


def resolve_block_plan(
    engine: str, duration_seconds: int, *, preferred_lane: str | None = None,
) -> list[int]:
    """Block plan from workbook authority ONLY (1-7 blocks). Never accept a
    manual block plan. Google Flow 40s requires a preferred lane choice."""
    eng = str(engine or "GOOGLE_FLOW").strip().upper().replace(" ", "_")
    matches = [
        p for p in _wps_authority()["block_plans"]
        if p["engine"] == eng and p["duration_seconds"] == int(duration_seconds)
    ]
    if not matches:
        raise ValueError(f"UNSUPPORTED_ENGINE_DURATION:{eng}:{duration_seconds}")
    if len(matches) > 1:
        if not preferred_lane:
            raise ValueError(f"PREFERRED_LANE_REQUIRED:{eng}:{duration_seconds}")
        lane = str(preferred_lane).strip().lower()
        for p in matches:
            row_lane = str(p.get("preferred_lane") or "").strip().lower()
            aliases = {
                row_lane,                          # "lane a"
                row_lane.split()[-1] if row_lane else "",  # "a"
                f"{p['blocks'][0]}s",              # "10s" / "8s" (block size lane)
            }
            if lane in aliases:
                return list(p["blocks"])
        raise ValueError(f"UNKNOWN_PREFERRED_LANE:{preferred_lane}")
    return list(matches[0]["blocks"])


# ── copy intelligence ─────────────────────────────────────────────────────────

def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_copy_intelligence(copy: dict[str, Any] | None) -> dict:
    """Structured copywriting fields (angle/hook/subhook/usp/cta/formula).
    The copy bank is a SECONDARY reference that keeps dialogue from going mute —
    missing fields degrade gracefully, they never fail the compile."""
    copy = copy or {}
    formula = _clean(copy.get("formula_family") or copy.get("formula")).upper() or "HSO"
    if formula not in _FORMULA_FAMILIES:
        formula = "HSO"
    usps = [
        _clean(u) for u in (
            copy.get("usps")
            or [copy.get("usp1"), copy.get("usp2"), copy.get("usp3"), copy.get("usp")]
        ) if _clean(u)
    ]
    return {
        "angle": _clean(copy.get("angle")),
        "hook": _clean(copy.get("hook")),
        "subhook": _clean(copy.get("subhook")),
        "usps": usps,
        "cta": _clean(copy.get("cta")),
        "formula_family": formula,
    }


def _product_name(product: dict[str, Any]) -> str:
    raw = (
        _clean(
            product.get("name")
            or product.get("product_name")
            or product.get("product_display_name")
            or product.get("raw_product_title")
            or product.get("product_short_name")
        )
        or "the product"
    )
    cleaned = re.sub(r"\s*\[[^\]]*\]\s*", " ", raw)
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\s+-\s+", " - ", cleaned).strip(" -")
    return cleaned or raw


def _product_category(product: dict[str, Any]) -> str:
    return _clean(
        product.get("category")
        or product.get("product_category")
        or product.get("subcategory")
        or product.get("type")
    )


def _humanize_label(value: str) -> str:
    return _clean(value).replace("_", " ")


def _trim_to_budget(text: str, budget: int) -> str:
    words = _clean(text).split()
    if len(words) <= budget:
        return " ".join(words)
    trimmed = " ".join(words[:budget])
    return re.sub(r"[,;:\-]+$", "", trimmed).strip()


def _split_clauses(text: str) -> list[str]:
    cleaned = _clean(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\s*[;:]\s+|\s+[—-]\s+", cleaned)
    clauses: list[str] = []
    seen: set[str] = set()
    for part in parts:
        clause = _clean(part).strip(" ,;:")
        if not clause:
            continue
        if clause[-1] not in ".!?":
            clause = f"{clause}."
        key = re.sub(r"[^a-z0-9]+", "", clause.lower())
        if key and key not in seen:
            seen.add(key)
            clauses.append(clause)
    return clauses


def _finalize_dialogue_text(text: str) -> str:
    cleaned = _clean(text).strip(" ,;:-")
    terminal_punct = cleaned[-1] if cleaned and cleaned[-1] in ".!?" else "."
    cleaned = cleaned.rstrip(".!?").strip(" ,;:-")
    cleaned = re.sub(
        r"\b(and|or|dan|atau|sebab|because|kalau|if|bila|when|supaya|untuk|rasa|tak|yang|pun|je|memang)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")
    if cleaned and cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}{terminal_punct}"
    return cleaned


def _pack_dialogue_clauses(clauses: list[str], budget: int) -> str:
    if budget <= 0:
        return ""
    chosen: list[str] = []
    used_words = 0
    for clause in clauses:
        words = clause.split()
        if not words:
            continue
        if not chosen and len(words) > budget:
            return _finalize_dialogue_text(_trim_to_budget(clause, budget))
        if used_words + len(words) <= budget:
            chosen.append(clause)
            used_words += len(words)
            continue
        remaining = budget - used_words
        if chosen and remaining >= 5:
            chosen.append(_finalize_dialogue_text(_trim_to_budget(clause, remaining)))
            used_words = budget
            break
    if not chosen and clauses:
        return _finalize_dialogue_text(_trim_to_budget(clauses[0], budget))
    return _finalize_dialogue_text(" ".join(chosen))


def _usp_slice(usps: list[str], block_index: int, total_blocks: int) -> list[str]:
    if not usps:
        return []
    if total_blocks <= 1:
        return usps[:2]
    if block_index == 1:
        return usps[:1]
    if block_index == total_blocks:
        return usps[-1:]
    middle_slots = max(1, total_blocks - 2)
    pointer = min(len(usps) - 1, ((block_index - 2) * len(usps)) // middle_slots)
    return usps[pointer:pointer + 1]


def _formula_dialogue_clauses(copy: dict, block_index: int, total_blocks: int) -> list[str]:
    formula = copy.get("formula_family") or "HSO"
    hooks = _split_clauses(copy.get("hook"))
    subhooks = _split_clauses(copy.get("subhook"))
    angle = _split_clauses(copy.get("angle"))
    usps = [clause for usp in (copy.get("usps") or []) for clause in _split_clauses(usp)]
    ctas = _split_clauses(copy.get("cta"))
    chosen_usps = _usp_slice(usps, block_index, total_blocks)
    if total_blocks <= 1:
        single_block_map = {
            "PAS": hooks + subhooks[:1] + chosen_usps[:1] + ctas[:1],
            "AIDA": hooks + chosen_usps[:2] + ctas[:1],
            "HSO": hooks + subhooks[:1] + chosen_usps[:1] + ctas[:1],
            "BAB": subhooks[:1] + chosen_usps[:2] + ctas[:1],
            "PESTA": hooks + angle[:1] + chosen_usps[:1] + ctas[:1],
            "PASTOR": hooks + subhooks[:1] + angle[:1] + ctas[:1],
        }
        return single_block_map.get(formula, hooks + subhooks[:1] + chosen_usps[:1] + ctas[:1])
    if block_index == 1:
        opening_map = {
            "PAS": hooks + subhooks[:1],
            "AIDA": hooks + chosen_usps[:1],
            "HSO": hooks + subhooks[:1],
            "BAB": subhooks[:1] + hooks[:1],
            "PESTA": hooks + angle[:1],
            "PASTOR": hooks + subhooks[:1],
        }
        return opening_map.get(formula, hooks + subhooks[:1]) or hooks or subhooks
    if block_index == total_blocks:
        closing_map = {
            "PAS": chosen_usps[:1] + ctas[:1],
            "AIDA": chosen_usps[:1] + ctas[:1],
            "HSO": chosen_usps[:1] + ctas[:1],
            "BAB": chosen_usps[:1] + ctas[:1],
            "PESTA": chosen_usps[:1] + ctas[:1],
            "PASTOR": angle[:1] + ctas[:1],
        }
        return closing_map.get(formula, chosen_usps[:1] + ctas[:1]) or ctas or chosen_usps
    middle_map = {
        "PAS": subhooks[:1] + chosen_usps[:1],
        "AIDA": chosen_usps[:2] or angle[:1],
        "HSO": subhooks[:1] + chosen_usps[:1],
        "BAB": chosen_usps[:1] + angle[:1],
        "PESTA": angle[:1] + chosen_usps[:1],
        "PASTOR": subhooks[:1] + chosen_usps[:1],
    }
    return middle_map.get(formula, chosen_usps[:1] + angle[:1]) or chosen_usps or subhooks or angle


def build_block_dialogue(
    *,
    copy: dict,
    block_index: int,
    total_blocks: int,
    budget: int,
    approved_dialogue: str | None = None,
) -> str:
    """Per-block target-language dialogue from the structured copy fields.

    Layout law: hook opens block 1; subhook + USPs fill the middle; the CTA
    lands ONLY in the final block. Approved dialogue (operator-supplied) is
    never rewritten — only placed and, at most, split across blocks."""
    if approved_dialogue:
        # Approved dialogue law: place, never rewrite. Split evenly across blocks.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean(approved_dialogue)) if s.strip()]
        if sentences:
            per_block = max(1, len(sentences) // total_blocks)
            start = (block_index - 1) * per_block
            chunk = sentences[start:start + per_block] if block_index < total_blocks else sentences[start:]
            if chunk:
                return _pack_dialogue_clauses(_split_clauses(" ".join(chunk)), budget)
    clauses = _formula_dialogue_clauses(copy, block_index, total_blocks)
    if not clauses:
        clauses = _split_clauses(copy.get("hook") or copy.get("cta") or "")
    return _pack_dialogue_clauses(clauses, budget)


# ── source-mode section renderers ─────────────────────────────────────────────

def _product_line(product: dict[str, Any]) -> str:
    return _product_name(product)


def _default_shot_plan(
    source_mode: str,
    *,
    product: dict[str, Any],
    shot_count: int,
    block_index: int,
    total_blocks: int,
    formula_family: str,
) -> list[str]:
    pname = _product_name(product)
    formula_hint = _humanize_label(formula_family).lower()
    is_final = block_index == total_blocks
    if source_mode == "HYBRID":
        templates = [
            f"Creator-led opening beat with {pname} already in hand, matching the uploaded product image exactly while the first spoken hook lands.",
            f"Tight handling close-up of {pname} with the label readable, controlled reflections, and tactile movement that supports the {formula_hint} angle.",
            f"Reaction or routine beat that keeps the same presenter and lets {pname} stay visible in-frame while the main benefit is spoken naturally.",
            f"Steady closing beat with {pname} held at chest level, eye contact to camera, and enough stillness for the final CTA line to land cleanly.",
        ]
    elif source_mode == "FRAMES":
        templates = [
            "Continue from the exact pose, grip, and camera distance already visible in the uploaded finished frame. The first beat is motion continuation only, not a new reveal.",
            f"Ease into one believable motion-delta beat that keeps {pname} in the same position family, with no restyle, no jump cut, and no scene rebuild.",
            f"Add a subtle expression or hand adjustment while keeping {pname} readable and the finished-frame lighting unchanged.",
            f"Let the motion settle into a clean held frame with {pname} still truthful to the uploaded frame, ready for the closing CTA line or a seam-safe stop.",
        ]
    elif source_mode == "INGREDIENTS":
        templates = [
            f"Reference-led opening beat: the presenter must match the avatar reference while introducing {pname} exactly as shown by the product reference.",
            f"Product truth beat: move closer to {pname} for readable packaging, honest scale, and natural hand-object interaction without overpowering the presenter reference.",
            "Environment beat: preserve the supplied scene or style direction only at the background and mood level while the product remains the visual authority.",
            f"Final hold beat with presenter and {pname} in the same frame, balanced and believable, so the CTA can land without any fake demonstration.",
        ]
    elif source_mode == "IMAGES":
        templates = [
            f"One polished commercial still of {pname} with honest scale, clean packaging readability, and a premium but believable composition."
        ]
    else:  # T2V
        templates = [
            f"Open inside the lived-in scene first, then let the presenter bring {pname} into the frame naturally so the hook feels native, not staged.",
            f"Routine-context beat that shows why {pname} belongs in the moment, with the packaging readable and the action grounded in normal human behaviour.",
            f"Confidence or payoff beat where the presenter stays on camera, keeps {pname} visible, and sells the main benefit through expression and handling rather than hard claims.",
            f"Clean closing beat with {pname} held clearly to camera, the presenter steady, and enough pause for the final CTA line to feel intentional.",
        ]
    if block_index > 1 and source_mode != "IMAGES":
        templates[0] = (
            f"Continue immediately from the previous block with the same presenter, same grip on {pname}, same lighting, and the same camera path already in progress."
        )
    selected = templates[: max(1, shot_count)]
    if is_final and source_mode != "IMAGES":
        selected[-1] = templates[-1]
    return selected


def _section_3_continuity(
    source_mode: str,
    *,
    product: dict[str, Any],
    presenter_prose: str | None,
    asset_role_map: dict | None,
    style_scene_source: str | None,
    is_continuation: bool,
    scene_context: str,
) -> str:
    """Naturalized source-mode prose — NO taxonomy labels, per retained law."""
    lines: list[str] = []
    pname = _product_line(product)
    if source_mode == "HYBRID":
        lines.append(
            f"Use the uploaded product image as the exact visual reference for {pname}: "
            "match its colour, label, cap, shape, material, and scale precisely in every shot."
        )
        if presenter_prose:
            lines.append(presenter_prose)
    elif source_mode == "FRAMES":
        lines.append(
            "Use the uploaded finished frame as the single visual reference. Continue only "
            "from the visible frame state: the same subject, the same product position, the "
            "same environment, and the same lighting. Animate forward with motion only — do "
            "not rebuild, restyle, or reintroduce the subject, the product, or the scene."
        )
    elif source_mode == "INGREDIENTS":
        lines.append(
            "Use the uploaded reference images exactly as provided: the product reference "
            "controls the product's true appearance, and the person reference controls the "
            "presenter's identity, face, and styling."
        )
        if style_scene_source == "SCENE_CONTEXT_ONLY" or not (asset_role_map or {}).get("STYLE_SCENE_REFERENCE"):
            env = scene_context or "a clean, believable everyday setting"
            lines.append(f"The environment comes from this description only: {env}.")
        else:
            lines.append("The style reference controls the environment and mood only — never the product or the presenter.")
        lines.append("The product's true appearance outranks every other reference if they conflict.")
    elif source_mode == "T2V":
        if presenter_prose:
            lines.append(presenter_prose)
        lines.append(
            f"Build the scene from this description: {scene_context or 'a bright, believable everyday setting'}. "
            f"Keep {pname} visually consistent in every shot."
        )
    else:  # IMAGES
        lines.append(
            f"Compose a single still image. Keep {pname} exactly true to its real packaging, "
            "label, and proportions."
        )
        if presenter_prose:
            lines.append(presenter_prose)
    if is_continuation:
        lines.append(
            "This block continues the previous clip. Start from the exact final visible state "
            "of the previous block: same presenter, same grip on the product, same camera "
            "distance, same lighting, same emotional tone, and same motion direction. The "
            "first half second must contain active continuation with no pause, dead air, or freeze."
        )
    return "\n".join(lines)


_LEAK_PATTERNS = (
    r"\bHYBRID\b", r"\bFRAMES MODE\b", r"\bINGREDIENTS\b", r"\bT2V\b", r"\bI2V\b", r"\bF2V\b",
    r"\bWPS\b", r"\bblock_plan\b", r"\bprompt_set_count\b", r"\bavatar pool\b",
    r"\bAVATAR_POOL\b", r"\bsource.mode\b", r"\bintake.mode\b", r"one visible creator",
    r"\bBOS_[MF]_", r"\{.*\"", r"\[camera, background, action\]",
)


def scrub_check(engine_text: str) -> list[str]:
    """QA fail conditions from retained authority: return leak violations."""
    violations = []
    for pattern in _LEAK_PATTERNS:
        if re.search(pattern, engine_text, flags=re.IGNORECASE):
            violations.append(pattern)
    return violations


def render_block(
    *,
    source_mode: str,
    engine: str,
    block_index: int,
    total_blocks: int,
    block_seconds: int,
    product: dict[str, Any],
    scene_context: str = "",
    copy: dict[str, Any] | None = None,
    approved_dialogue: str | None = None,
    presenter_profile: dict | None = None,
    asset_role_map: dict | None = None,
    style_scene_source: str | None = None,
    target_language: str = "BM_MS",
    wps_mode: str = "SAFE",
    overlay_allowed: bool = False,
    overlay_text: str | None = None,
    camera_notes: str = "",
    handling_notes: str = "",
    shot_plan: list[str] | None = None,
    shot_count_hint: int | None = None,
) -> dict[str, Any]:
    """Render ONE complete canonical 9-section engine-facing prompt block."""
    mode = str(source_mode or "").strip().upper()
    if mode not in SOURCE_MODES:
        raise ValueError(f"UNSUPPORTED_SOURCE_MODE:{source_mode}")
    lang = language_name(target_language)
    is_final = block_index == total_blocks
    is_continuation = block_index > 1
    budget = 0 if mode == "IMAGES" else dialogue_word_budget(
        block_seconds, target_language, wps_mode=wps_mode,
    )
    norm_copy = normalize_copy_intelligence(copy)
    presenter = None
    presenter_text = None
    if mode in ("HYBRID", "T2V") or (mode == "IMAGES" and presenter_profile):
        presenter = presenter_profile or avatar_registry.resolve_presenter(
            seed=_clean(product.get("id") or product.get("name") or "bosmax"),
        )
        presenter_text = avatar_registry.presenter_prose(presenter)
    pname = _product_line(product)
    category = _product_category(product)
    angle_hint = _humanize_label(norm_copy.get("angle", "")).lower()

    s1 = (
        f"You are generating {'a single commercial product image' if mode == 'IMAGES' else f'an {block_seconds}-second vertical commercial video block'} "
        f"({'final block' if is_final and total_blocks > 1 else ('continuation block' if is_continuation else 'opening block')}"
        f"{f' {block_index} of {total_blocks}' if total_blocks > 1 else ''}). "
        f"The objective is a believable, native-feeling social commerce shot that keeps {pname} "
        "credible and desirable without exaggerated claims."
    )
    if category:
        s1 += f" Treat it as a real {category.lower()} product, not a generic prop."
    if angle_hint:
        s1 += f" The commercial angle is {angle_hint}."
    s2_lines = [
        f"Preserve the exact real-world appearance of {pname}: label, cap, shape, scale, "
        "material, colour, and any readable text must match the true product in every frame.",
    ]
    if handling_notes:
        s2_lines.append(handling_notes)
    s2_lines.append("Never redesign, restyle, resize, or invent packaging.")
    s2 = "\n".join(s2_lines)
    s3 = _section_3_continuity(
        mode, product=product, presenter_prose=presenter_text,
        asset_role_map=asset_role_map, style_scene_source=style_scene_source,
        is_continuation=is_continuation, scene_context=_clean(scene_context),
    )
    shots = list(shot_plan or [])
    if not shots:
        shot_count = shot_count_hint or (1 if mode == "IMAGES" else 2)
        shots = _default_shot_plan(
            mode,
            product=product,
            shot_count=shot_count,
            block_index=block_index,
            total_blocks=total_blocks,
            formula_family=norm_copy.get("formula_family", "HSO"),
        )
    s4 = "\n".join(f"Shot {i + 1}: {s}" for i, s in enumerate(shots))
    s5_lines = [
        "Handheld vertical 9:16 framing with natural micro-jitter and organic human sway."
        if mode != "IMAGES" else "Clean commercial framing with the product sharply in focus.",
        camera_notes or "Eye-level medium close-up to close-up range; soft natural light; no flash, no hard fill.",
    ]
    if is_continuation:
        s5_lines.append(
            "For the first half second, continue the exact motion already in progress. For the "
            "first one to two seconds, keep the presenter's face and mouth clearly visible and "
            "synchronized to every spoken word — the product may stay near chest level, but "
            "there is no product-only shot during the opening spoken line."
        )
    s5 = "\n".join(s5_lines)
    dialogue = "" if mode == "IMAGES" else build_block_dialogue(
        copy=norm_copy, block_index=block_index, total_blocks=total_blocks,
        budget=budget, approved_dialogue=approved_dialogue,
    )
    s6 = dialogue if dialogue else "(No spoken dialogue in this block.)"
    s7 = (
        f"The presenter speaks {lang} only, direct to camera, in a warm, confident, "
        "conversational tone with short, punchy, speakable phrasing — a real person recommending something they use, not a narrator. "
        "No voice-over. No narration. No off-camera speech. No audio-only dialogue."
    ) if mode != "IMAGES" else "Not applicable — still image output."
    if mode == "IMAGES":
        s8 = f"The final composition holds {pname} clearly readable as the visual anchor."
    elif mode == "FRAMES" and is_final:
        s8 = (
            f"End by easing the existing motion into a clean held frame: {pname} stays truthful to the uploaded finished frame, "
            "the presenter remains in the same scene state, and the closing CTA line lands without any new reveal."
        )
    elif mode == "INGREDIENTS" and is_final:
        s8 = (
            f"End on a balanced two-subject hold: the presenter stays faithful to the avatar reference while {pname} remains clearly readable and dominant as the product truth anchor."
        )
    elif mode == "HYBRID" and is_final:
        s8 = (
            f"End on a confident creator-to-camera hold with {pname} upright, label readable, and the exact uploaded-product packaging still matching perfectly as the CTA lands."
        )
    elif is_final:
        s8 = (
            f"End on a steady hold: the presenter keeps {pname} at chest level with the label "
            "readable to camera while the closing line lands, then a beat of calm confidence."
        )
    else:
        s8 = (
            "End on a seam-ready hold: the presenter mid-gesture with the product in grip, face "
            "toward camera, motion direction preserved so the next block can continue exactly "
            "from this state. Do not close the commercial arc yet."
        )
    if overlay_allowed and overlay_text:
        s9 = f"On-screen text is permitted for this block only: '{_clean(overlay_text)}'. No other captions, subtitles, price text, or sticker text."
    else:
        s9 = (
            "No on-screen text of any kind: no captions, no subtitles, no lower-thirds, no "
            "sticker text, no price text, no watermarks. Everything persuasive is spoken."
        )

    bodies = (s1, s2, s3, s4, s5, s6, s7, s8, s9)
    engine_text = "\n\n".join(
        f"{header}\n{body}" for header, body in zip(CANONICAL_SECTIONS, bodies)
    )
    violations = scrub_check(engine_text)
    return {
        "block_index": block_index,
        "block_seconds": block_seconds,
        "is_final": is_final,
        "engine_prompt_text": engine_text,
        "dialogue": dialogue,
        "dialogue_word_budget": budget,
        "dialogue_word_count": len(dialogue.split()) if dialogue else 0,
        "presenter": presenter,
        "scrub_violations": violations,
        "sections": dict(zip(CANONICAL_SECTIONS, bodies)),
    }


def compile_prompt_set(
    *,
    source_mode: str,
    engine: str = "GOOGLE_FLOW",
    duration_seconds: int = 8,
    preferred_lane: str | None = None,
    product: dict[str, Any],
    scene_context: str = "",
    copy: dict[str, Any] | None = None,
    approved_dialogue: str | None = None,
    avatar_id: str | None = None,
    presenter_profile: dict | None = None,
    asset_role_map: dict | None = None,
    style_scene_source: str | None = None,
    target_language: str = "BM_MS",
    wps_mode: str = "SAFE",
    overlay_allowed: bool = False,
    overlay_text: str | None = None,
    camera_notes: str = "",
    handling_notes: str = "",
) -> dict[str, Any]:
    """Compile the full MULTI-PROMPT SET: one complete 9-section block per
    workbook-derived block (1-7). This is THE canonical entrypoint."""
    mode = str(source_mode or "").strip().upper()
    if mode not in SOURCE_MODES:
        raise ValueError(f"UNSUPPORTED_SOURCE_MODE:{source_mode}")
    if mode == "IMAGES":
        plan = [0]
    else:
        plan = resolve_block_plan(engine, duration_seconds, preferred_lane=preferred_lane)
    # HYBRID law: resolve ONE concrete presenter BEFORE rendering, reuse across blocks.
    resolved_profile = presenter_profile
    if mode in ("HYBRID", "T2V") and not resolved_profile:
        resolved_profile = avatar_registry.resolve_presenter(
            avatar_id,
            usage_context=_clean(product.get("category")),
            seed=_clean(product.get("id") or product.get("name") or "bosmax"),
        )
    if mode == "INGREDIENTS":
        roles = {str(k).upper(): v for k, v in (asset_role_map or {}).items()}
        if not (roles.get("PRODUCT_REFERENCE") and roles.get("AVATAR_REFERENCE")):
            raise ValueError("INGREDIENTS_ASSET_ROLE_MAP_INCOMPLETE: PRODUCT_REFERENCE + AVATAR_REFERENCE required")
        if not roles.get("STYLE_SCENE_REFERENCE"):
            style_scene_source = "SCENE_CONTEXT_ONLY"
        asset_role_map = roles
    total = len(plan)
    blocks = []
    for i, seconds in enumerate(plan, start=1):
        blocks.append(render_block(
            source_mode=mode, engine=engine, block_index=i, total_blocks=total,
            block_seconds=seconds or duration_seconds, product=product,
            scene_context=scene_context, copy=copy, approved_dialogue=approved_dialogue,
            presenter_profile=resolved_profile, asset_role_map=asset_role_map,
            style_scene_source=style_scene_source, target_language=target_language,
            wps_mode=wps_mode, overlay_allowed=overlay_allowed, overlay_text=overlay_text,
            camera_notes=camera_notes, handling_notes=handling_notes,
            shot_count_hint=1 if mode == "IMAGES" else min(4, max(2, round((seconds or duration_seconds) / 4))),
        ))
    all_violations = [v for b in blocks for v in b["scrub_violations"]]
    if all_violations:
        raise ValueError(f"ENGINE_OUTPUT_SCRUB_FAILED:{sorted(set(all_violations))}")
    return {
        "compiler_authority": "canonical_prompt_compiler_v1",
        "source_mode": mode,
        "engine": str(engine).strip().upper().replace(" ", "_"),
        "block_plan": plan if mode != "IMAGES" else [],
        "total_blocks": total,
        "wps_mode": str(wps_mode).upper(),
        "target_language": target_language,
        "presenter": resolved_profile,
        "blocks": blocks,
    }
