from __future__ import annotations

import hashlib
from typing import Any

from agent.services.prompt_compiler_runtime_config_service import (
    DEFAULT_CREATOR_PERSONA,
    DEFAULT_TARGET_LANGUAGE,
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


def _shot_blueprint(
    shot_count: int,
    *,
    mode: str,
    block_role: str,
    product_name: str,
) -> list[str]:
    templates = [
        f"Shot 1: MCU visible creator enters naturally, establishes the product context, and reveals {product_name} with believable hand-object interaction.",
        f"Shot 2: CU product handling close-up with label-safe framing, honest scale, and tactile HOI emphasis.",
        f"Shot 3: Medium or product close-up continuation that reinforces product truth, safe hook, and clear commercial pacing.",
        f"Shot 4: Alternate angle or movement beat that keeps the same creator, product state, and commercial tone.",
        f"Shot 5: Tight product close-up with premium handling, clean lighting, and stable product truth.",
        f"Shot 6: Resolution beat with safe CTA and continued creator or product continuity.",
    ]
    if mode == "IMG":
        templates = [
            f"Shot 1: Compose a single premium hero framing around {product_name} with visible creator presence where selected and clean product truth.",
            f"Shot 2: Use an optional supporting angle only if required by the image concept, while preserving the same creator and product continuity.",
        ]
    if block_role == "CONTINUATION":
        templates[0] = (
            f"Shot 1: Continue immediately from the previous block with the same creator, same wardrobe, same product state, and coherent camera logic around {product_name}."
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
    camera_profile = _camera_profile(camera_style)
    shots = _shot_blueprint(
        shot_count,
        mode=mode,
        block_role=block_role,
        product_name=product_name,
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
    return {
        "block_id": f"block_{block_index}",
        "block_index": block_index,
        "block_role": block_role,
        "duration_seconds": duration_seconds,
        "shot_count": shot_count,
        "dialogue_word_budget": word_budget,
        "continuation_from_block_id": continuation_from_block_id,
        "compiled_prompt_text": "\n".join(lines),
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

    final_compiled_prompt_text = "\n\n".join(
        block["compiled_prompt_text"] for block in compiled_blocks
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

