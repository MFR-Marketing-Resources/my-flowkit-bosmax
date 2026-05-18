from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.db import crud
from agent.services.approved_product_package_service import (
    get_approved_product_package,
    normalize_mode,
)
from agent.services.claim_safe_rewrite_service import get_stored_claim_safe_package
from agent.services.product_intelligence import enrich_product
from agent.services.production_prompt_approval_service import scan_prompt_text
from agent.services.prompt_compiler_runtime_config_service import get_runtime_config
from agent.services.ugc_video_prompt_compiler_service import (
    compile_ugc_video_prompt,
)


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _workspace_execution_package_id(
    product_id: str,
    mode: str,
    prompt_fingerprint: str,
    duration_seconds: int,
    aspect_ratio: str,
    model: str,
    manual_override: bool,
    generation_mode: str,
    target_language: str,
    camera_style: str,
    character_presence: str,
) -> str:
    digest = _fingerprint(
        product_id,
        mode,
        prompt_fingerprint,
        str(duration_seconds),
        aspect_ratio,
        model,
        str(manual_override).lower(),
        generation_mode,
        target_language,
        camera_style,
        character_presence,
    )
    return f"wep_{digest[:16]}"


def _resolved_assets(asset_slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [slot["resolved_asset"] for slot in asset_slots if slot.get("resolved_asset")]


def _default_model_for_mode(mode: str) -> str:
    if mode == "IMG":
        return "Nano Banana 2"
    if mode == "T2V":
        return "Veo 3.1 - Pro"
    return "Veo 3.1 - Lite"


async def create_workspace_execution_package(
    product_id: str,
    mode: str,
    duration_seconds: int,
    aspect_ratio: str,
    model: str,
    manual_override: bool,
    generation_mode: str = "SINGLE",
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
    blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    package = await get_approved_product_package(product_id, mode)
    normalized_mode = normalize_mode(mode)
    resolved_model = model or _default_model_for_mode(normalized_mode)
    compiler_result = await compile_workspace_prompt_preview(
        product_id=product_id,
        mode=normalized_mode,
        duration_seconds=duration_seconds,
        generation_mode=generation_mode,
        target_language=target_language,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        blocks=blocks or [],
        approved_package=package,
    )
    prompt_fingerprint = compiler_result["prompt_fingerprint"]
    total_duration_seconds = int(compiler_result["total_duration_seconds"])
    execution_package_id = _workspace_execution_package_id(
        product_id,
        normalized_mode,
        prompt_fingerprint,
        total_duration_seconds,
        aspect_ratio,
        resolved_model,
        manual_override,
        compiler_result["generation_mode"],
        compiler_result["target_language"],
        compiler_result["camera_style"],
        compiler_result["character_presence"],
    )
    resolved_assets = _resolved_assets(package["asset_slots"])
    asset_fingerprints = [asset["asset_fingerprint"] for asset in resolved_assets if asset.get("asset_fingerprint")]
    request_lineage_payload = {
        "product_id": product_id,
        "mode": normalized_mode,
        "prompt_package_snapshot_id": package["prompt_package_snapshot_id"],
        "workspace_execution_package_id": execution_package_id,
        "prompt_fingerprint": prompt_fingerprint,
        "asset_fingerprints": asset_fingerprints,
        "compiler": {
            "compiler_version": compiler_result["compiler_version"],
            "generation_mode": compiler_result["generation_mode"],
            "total_duration_seconds": compiler_result["total_duration_seconds"],
            "camera_style": compiler_result["camera_style"],
            "character_presence": compiler_result["character_presence"],
            "creator_persona": compiler_result["creator_persona"],
            "target_language": compiler_result["target_language"],
            "dialogue_word_budget_per_block": compiler_result["dialogue_word_budget_per_block"],
            "prompt_blocks": compiler_result["prompt_blocks"],
            "shot_plan": compiler_result["shot_plan"],
            "continuation_lineage": compiler_result["continuation_lineage"],
            "warnings": compiler_result["warnings"],
        },
    }
    readiness = "READY" if not package["blockers"] else "BLOCKED"
    execution_allowed = readiness == "READY"

    await crud.create_or_replace_workspace_execution_package(
        workspace_execution_package_id=execution_package_id,
        product_id=product_id,
        mode=normalized_mode,
        duration_seconds=total_duration_seconds,
        aspect_ratio=aspect_ratio,
        model=resolved_model,
        manual_override=manual_override,
        prompt_package_snapshot_id=package["prompt_package_snapshot_id"],
        prompt_fingerprint=prompt_fingerprint,
        prompt_text=compiler_result["final_compiled_prompt_text"],
        asset_slots=_json(package["asset_slots"]),
        resolved_assets=_json(resolved_assets),
        readiness=readiness,
        execution_allowed=execution_allowed,
        production_generation_allowed=package["production_generation_allowed"],
        manual_fallback=_json(package["manual_fallback"]),
        blockers=_json(package["blockers"]),
        request_lineage_payload=_json(request_lineage_payload),
        source_of_truth_notes=_json(
            [
                *package["source_of_truth_notes"],
                *compiler_result["source_of_truth_notes"],
            ],
        ),
    )

    return {
        "workspace_execution_package_id": execution_package_id,
        "product_id": product_id,
        "product_name": package["product_name"],
        "mode": normalized_mode,
        "duration_seconds": total_duration_seconds,
        "aspect_ratio": aspect_ratio,
        "model": resolved_model,
        "manual_override": manual_override,
        "prompt_text": compiler_result["final_compiled_prompt_text"],
        "prompt_fingerprint": prompt_fingerprint,
        "prompt_package_snapshot_id": package["prompt_package_snapshot_id"],
        "asset_slots": package["asset_slots"],
        "resolved_assets": resolved_assets,
        "readiness": readiness,
        "execution_allowed": execution_allowed,
        "production_generation_allowed": package["production_generation_allowed"],
        "manual_fallback": package["manual_fallback"],
        "blockers": package["blockers"],
        "request_lineage_payload": request_lineage_payload,
        "source_of_truth_notes": [
            *package["source_of_truth_notes"],
            *compiler_result["source_of_truth_notes"],
        ],
        "compiler_version": compiler_result["compiler_version"],
        "generation_mode": compiler_result["generation_mode"],
        "total_duration_seconds": compiler_result["total_duration_seconds"],
        "camera_style": compiler_result["camera_style"],
        "character_presence": compiler_result["character_presence"],
        "creator_persona": compiler_result["creator_persona"],
        "target_language": compiler_result["target_language"],
        "shot_plan": compiler_result["shot_plan"],
        "dialogue_word_budget_per_block": compiler_result["dialogue_word_budget_per_block"],
        "prompt_blocks": compiler_result["prompt_blocks"],
        "warnings": compiler_result["warnings"],
        "compiler_blockers": compiler_result["blockers"],
        "continuation_lineage": compiler_result["continuation_lineage"],
        "runtime_config_snapshot": compiler_result["runtime_config_snapshot"],
    }


async def compile_workspace_prompt_preview(
    *,
    product_id: str,
    mode: str,
    duration_seconds: int,
    generation_mode: str = "SINGLE",
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
    blocks: list[dict[str, Any]] | None = None,
    approved_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    enriched_product = await enrich_product(product, persist=False)
    package = approved_package or await get_approved_product_package(product_id, mode)
    safe_package = await get_stored_claim_safe_package(product_id) or {}
    compiler_result = compile_ugc_video_prompt(
        product=enriched_product,
        approved_package=package,
        mode=mode,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        target_language=target_language,
        generation_mode=generation_mode,
        duration_seconds=duration_seconds,
        blocks=blocks or [],
        engine_target=mode,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        claim_safe_rewrite=package.get("claim_safe_rewrite"),
        safe_hook_angles=list(safe_package.get("safe_hook_angles") or []),
        safe_cta_angles=list(safe_package.get("safe_cta_angles") or []),
    )
    prompt_scan = scan_prompt_text(
        compiler_result["final_compiled_prompt_text"],
        product_id=product_id,
    )
    if any(prompt_scan.values()):
        raise ValueError("PACKAGE_SCAN_FAILED")
    compiler_result["runtime_config_snapshot"] = get_runtime_config()
    compiler_result["product_id"] = product_id
    compiler_result["mode"] = normalize_mode(mode)
    return compiler_result


async def list_workspace_execution_packages(
    *,
    product_id: str | None = None,
    mode: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = await crud.list_workspace_execution_packages(product_id=product_id, mode=normalize_mode(mode) if mode else None, limit=limit)
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "workspace_execution_package_id": row["workspace_execution_package_id"],
                "product_id": row["product_id"],
                "mode": row["mode"],
                "prompt_package_snapshot_id": row.get("prompt_package_snapshot_id"),
                "prompt_fingerprint": row.get("prompt_fingerprint"),
                "readiness": row.get("readiness"),
                "execution_allowed": bool(row.get("execution_allowed")),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "manual_override": bool(row.get("manual_override")),
                "asset_slots": json.loads(row.get("asset_slots") or "[]"),
                "resolved_assets": json.loads(row.get("resolved_assets") or "[]"),
                "manual_fallback": json.loads(row.get("manual_fallback") or "{}"),
                "blockers": json.loads(row.get("blockers") or "[]"),
                "request_lineage_payload": json.loads(row.get("request_lineage_payload") or "{}"),
                "source_of_truth_notes": json.loads(row.get("source_of_truth_notes") or "[]"),
                "prompt_preview": str(row.get("prompt_text") or "")[:240],
                "prompt_text": row.get("prompt_text") or "",
            }
        )
    return items
