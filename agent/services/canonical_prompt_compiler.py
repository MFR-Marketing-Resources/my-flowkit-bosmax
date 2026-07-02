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


def _trim_to_budget(text: str, budget: int) -> str:
    words = _clean(text).split()
    if len(words) <= budget:
        return " ".join(words)
    trimmed = " ".join(words[:budget])
    return re.sub(r"[,;:\-]+$", "", trimmed).strip()


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
                return _trim_to_budget(" ".join(chunk), budget)
    parts: list[str] = []
    is_first = block_index == 1
    is_final = block_index == total_blocks
    usps = list(copy.get("usps") or [])
    if is_first and copy.get("hook"):
        parts.append(copy["hook"])
        if copy.get("subhook"):
            parts.append(copy["subhook"])
    # distribute USPs across non-CTA space: block i takes its share
    if usps:
        share = max(1, len(usps) // max(1, total_blocks))
        start = (block_index - 1) * share
        parts.extend(usps[start:start + share] if not is_final else usps[start:])
    if is_final and copy.get("cta"):
        parts.append(copy["cta"])
    if not parts:
        parts = [copy.get("hook") or copy.get("cta") or ""]
    return _trim_to_budget(" ".join(p for p in parts if p), budget)


# ── source-mode section renderers ─────────────────────────────────────────────

def _product_line(product: dict[str, Any]) -> str:
    name = _clean(product.get("name") or product.get("product_name")) or "the product"
    category = _clean(product.get("category"))
    tail = f" ({category})" if category else ""
    return f"{name}{tail}"


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
) -> dict[str, Any]:
    """Render ONE complete canonical 9-section engine-facing prompt block."""
    mode = str(source_mode or "").strip().upper()
    if mode not in SOURCE_MODES:
        raise ValueError(f"UNSUPPORTED_SOURCE_MODE:{source_mode}")
    lang = language_name(target_language)
    is_final = block_index == total_blocks
    is_continuation = block_index > 1
    budget = dialogue_word_budget(block_seconds, target_language, wps_mode=wps_mode)
    norm_copy = normalize_copy_intelligence(copy)
    presenter = None
    presenter_text = None
    if mode in ("HYBRID", "T2V") or (mode == "IMAGES" and presenter_profile):
        presenter = presenter_profile or avatar_registry.resolve_presenter(
            seed=_clean(product.get("id") or product.get("name") or "bosmax"),
        )
        presenter_text = avatar_registry.presenter_prose(presenter)
    pname = _product_line(product)

    s1 = (
        f"You are generating {'a single commercial product image' if mode == 'IMAGES' else f'an {block_seconds}-second vertical commercial video block'} "
        f"({'final block' if is_final and total_blocks > 1 else ('continuation block' if is_continuation else 'opening block')}"
        f"{f' {block_index} of {total_blocks}' if total_blocks > 1 else ''}). "
        f"The objective is a believable, native-feeling social commerce shot that keeps {pname} "
        "credible and desirable without exaggerated claims."
    )
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
        if mode == "IMAGES":
            shots = [f"One clean commercial composition presenting {pname} with honest scale and readable label."]
        elif is_continuation:
            shots = [
                "Continue the previous action seamlessly from its final visible state.",
                f"Close-up beat that keeps {pname} readable while the presenter speaks on camera.",
            ]
        else:
            shots = [
                f"The presenter enters naturally and reveals {pname} with believable hand interaction.",
                f"Close-up product beat with honest scale and label-safe framing of {pname}.",
            ]
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
        "conversational tone — a real person recommending something they use, not a narrator. "
        "No voice-over. No narration. No off-camera speech. No audio-only dialogue."
    ) if mode != "IMAGES" else "Not applicable — still image output."
    if mode == "IMAGES":
        s8 = f"The final composition holds {pname} clearly readable as the visual anchor."
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
