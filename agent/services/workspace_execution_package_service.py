from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.db import crud
from agent.services.approved_product_package_service import (
    get_approved_product_package,
    normalize_mode,
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
) -> str:
    digest = _fingerprint(
        product_id,
        mode,
        prompt_fingerprint,
        str(duration_seconds),
        aspect_ratio,
        model,
        str(manual_override).lower(),
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
) -> dict[str, Any]:
    package = await get_approved_product_package(product_id, mode)
    normalized_mode = normalize_mode(mode)
    resolved_model = model or _default_model_for_mode(normalized_mode)
    prompt_fingerprint = package["prompt_fingerprint"]
    execution_package_id = _workspace_execution_package_id(
        product_id,
        normalized_mode,
        prompt_fingerprint,
        duration_seconds,
        aspect_ratio,
        resolved_model,
        manual_override,
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
    }
    readiness = "READY" if not package["blockers"] else "BLOCKED"
    execution_allowed = readiness == "READY"

    await crud.create_or_replace_workspace_execution_package(
        workspace_execution_package_id=execution_package_id,
        product_id=product_id,
        mode=normalized_mode,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        model=resolved_model,
        manual_override=manual_override,
        prompt_package_snapshot_id=package["prompt_package_snapshot_id"],
        prompt_fingerprint=prompt_fingerprint,
        prompt_text=package["prompt_text"],
        asset_slots=_json(package["asset_slots"]),
        resolved_assets=_json(resolved_assets),
        readiness=readiness,
        execution_allowed=execution_allowed,
        production_generation_allowed=package["production_generation_allowed"],
        manual_fallback=_json(package["manual_fallback"]),
        blockers=_json(package["blockers"]),
        request_lineage_payload=_json(request_lineage_payload),
        source_of_truth_notes=_json(package["source_of_truth_notes"]),
    )

    return {
        "workspace_execution_package_id": execution_package_id,
        "product_id": product_id,
        "product_name": package["product_name"],
        "mode": normalized_mode,
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "model": resolved_model,
        "manual_override": manual_override,
        "prompt_text": package["prompt_text"],
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
        "source_of_truth_notes": package["source_of_truth_notes"],
    }


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
            }
        )
    return items
