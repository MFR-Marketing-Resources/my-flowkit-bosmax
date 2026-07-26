"""Round 4 controlled, explicitly confirmed promotion into the active scene pool."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.db import crud
from agent.services import creative_scene_prompt_service as _scene_prompts
from agent.services import product_scene_suitability_service as _suitability
from agent.services import scene_context_promotion_review_service as _review
from agent.services import scene_context_promotion_service as _promotion
from agent.services import scene_context_registry as _registry

CONFIRMATION = "PROMOTE_TO_ACTIVE_REGISTRY"
MAX_BULK = 25
_activation_lock = asyncio.Lock()


class ActivationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()


def _content_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalise_item(item: dict[str, Any]) -> dict[str, Any]:
    template_id = str(item.get("source_template_id") or "").strip()
    fingerprint = str(item.get("candidate_fingerprint") or "").strip()
    if not template_id or not fingerprint:
        raise ActivationError("INVALID_ACTIVATION_BATCH")
    return {"source_template_id": template_id, "candidate_fingerprint": fingerprint}


def _allocate_scene_code(scene_name: str, used_codes: set[str]) -> str:
    base = f"SCN_{_slug(scene_name)}"
    if not base or base == "SCN_":
        raise ActivationError("CANDIDATE_NOT_CURRENTLY_PROMOTABLE")
    code, suffix = base, 2
    while code.casefold() in used_codes:
        code = f"{base}_{suffix:02d}"
        suffix += 1
    used_codes.add(code.casefold())
    return code


def _active_raw_rows() -> tuple[list[str], list[dict[str, str]]]:
    with _registry._active_pool_file().open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def _render_pool_bytes(headers: list[str], rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({header: str(row.get(header, "") or "") for header in headers})
    return output.getvalue().encode("utf-8")


async def _resolve_candidate(product_id: str, item: dict[str, Any]) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ActivationError("PRODUCT_NOT_FOUND")
    template_id = str(item.get("source_template_id") or "").strip()
    library = {str(row.get("template_id")): row for row in _scene_prompts.library_templates()}
    if template_id not in library:
        raise ActivationError("UNKNOWN_SOURCE_TEMPLATE")
    suitability = await _suitability.recommend_scene_suitability_for_product(product_id)
    cluster = suitability.get("cluster")
    suitable = {str(row.get("template_id")) for row in suitability.get("recommendations", [])}
    if template_id not in suitable:
        raise ActivationError("PRODUCT_TEMPLATE_MISMATCH")
    preview = _promotion.preview_scene_context_promotion(cluster)
    quarantined = {str(row.get("source_template_id")) for row in preview.get("quarantine", [])}
    if template_id in quarantined:
        raise ActivationError("CANDIDATE_QUARANTINED")
    candidate = next((row for row in preview.get("candidates", []) if row.get("source_template_id") == template_id), None)
    if candidate is None:
        raise ActivationError("CANDIDATE_NOT_CURRENTLY_PROMOTABLE")
    fingerprint = _review.candidate_fingerprint(candidate)
    if str(item.get("candidate_fingerprint") or "") != fingerprint:
        raise ActivationError("STALE_CANDIDATE_FINGERPRINT")
    review = await crud.get_scene_context_promotion_review_exact(template_id, fingerprint)
    if not review or review.get("decision") != "APPROVED_FOR_FUTURE_PROMOTION":
        raise ActivationError("CANDIDATE_NOT_APPROVED")
    return {
        "product_id": product_id,
        "cluster": cluster,
        "candidate": candidate,
        "fingerprint": fingerprint,
        "review": review,
    }


def _candidate_row(resolved: dict[str, Any], scene_code: str, activation_id: str) -> dict[str, str]:
    candidate, cluster = resolved["candidate"], resolved["cluster"]
    source = candidate["row"]
    return {
        "SceneName": source["SceneName"], "SceneCode": scene_code,
        "BackgroundPrompt": source["BackgroundPrompt"], "RouteFit": source["RouteFit"],
        "SafetyBlock": source["SafetyBlock"], "PromptV1": source["PromptV1"],
        "approved_flag": "TRUE", "usage_tags": source["usage_tags"],
        "PrimaryCluster": cluster, "CompatibleClusters": cluster,
        "SourceTemplateId": candidate["source_template_id"],
        "CandidateFingerprint": resolved["fingerprint"], "ActivationId": activation_id,
    }


def _result(event: dict[str, Any], registry_scene_count: int, *, idempotent: bool, mutations: int) -> dict[str, Any]:
    return {
        "activation_id": event["activation_id"], "source_template_id": event["source_template_id"],
        "candidate_fingerprint": event["candidate_fingerprint"], "product_id": event["reviewed_via_product_id"],
        "cluster": event["cluster"], "scene_code": event["scene_code"], "scene_name": event["scene_name"],
        "activation_status": "ACTIVE_IN_REGISTRY", "generation_status": "NOT_GENERATED",
        "idempotent": idempotent, "registry_scene_count": registry_scene_count,
        "registry_mutations": mutations, "provider_calls": 0, "generation_jobs": 0, "credits_used": 0,
    }


async def activation_eligibility(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ActivationError("PRODUCT_NOT_FOUND")
    review = await _review.product_review(product_id)
    if review.get("review_required"):
        return {"product_id": product_id, "cluster": None, "candidate_count": 0, "registry_mutations": 0, "candidates": []}
    rendered = []
    for candidate in review.get("candidates", []):
        fingerprint, template_id = candidate["candidate_fingerprint"], candidate["source_template_id"]
        event = await crud.get_scene_context_promotion_activation_exact(template_id, fingerprint)
        if event:
            status, blocker, code = "ACTIVE_IN_REGISTRY", None, event["scene_code"]
        elif candidate["stale_review_required"]:
            status, blocker, code = "STALE_REVIEW_REQUIRED", "STALE_REVIEW_REQUIRED", None
        elif candidate["decision"] != "APPROVED_FOR_FUTURE_PROMOTION":
            status, blocker, code = "NOT_APPROVED", "CANDIDATE_NOT_APPROVED", None
        else:
            duplicate = _registry.find_duplicate_scene(candidate["proposed_scene_name"], candidate["background_prompt"])
            if duplicate:
                status, blocker, code = "BLOCKED", "SCENE_DUPLICATE", duplicate["scene_code"]
            else:
                status, blocker, code = "ELIGIBLE_FOR_CONTROLLED_PROMOTION", None, None
        rendered.append({
            "source_template_id": template_id, "candidate_fingerprint": fingerprint, "cluster": review["cluster"],
            "current_review_decision": candidate["decision"], "stale_review_required": candidate["stale_review_required"],
            "activation_eligible": status == "ELIGIBLE_FOR_CONTROLLED_PROMOTION", "activation_blocker": blocker,
            "activation_status": status, "existing_scene_code": code,
            "proposed_scene_code": candidate["proposed_scene_code"] if status == "ELIGIBLE_FOR_CONTROLLED_PROMOTION" else None,
            "generation_status": "NOT_GENERATED",
        })
    return {"product_id": product_id, "cluster": review["cluster"], "candidate_count": len(rendered), "registry_mutations": 0, "candidates": rendered}


async def activate(product_id: str, items: list[dict[str, Any]], confirmation: str, activated_by: str, activation_note: str | None = None) -> dict[str, Any]:
    if confirmation != CONFIRMATION:
        raise ActivationError("ACTIVATION_CONFIRMATION_REQUIRED")
    if not items or len(items) > MAX_BULK:
        raise ActivationError("INVALID_ACTIVATION_BATCH")
    normalized_items = [_normalise_item(item) for item in items]
    template_ids = [item["source_template_id"] for item in normalized_items]
    if len(template_ids) != len(set(template_ids)):
        raise ActivationError("DUPLICATE_ACTIVATION_BATCH_ITEM")
    if not str(activated_by or "").strip():
        raise ActivationError("ACTIVATED_BY_REQUIRED")
    async with _activation_lock:
        idempotent = []
        new_items = []
        for item in normalized_items:
            existing = await crud.get_scene_context_promotion_activation_exact(item["source_template_id"], item["candidate_fingerprint"])
            if existing:
                idempotent.append(existing)
            else:
                new_items.append(item)
        if not new_items:
            count = len(_registry.list_pool())
            return _bulk_result([_result(event, count, idempotent=True, mutations=0) for event in idempotent], 0)
        resolved = [await _resolve_candidate(product_id, item) for item in new_items]
        headers, current_rows = _active_raw_rows()
        existing_codes = {str(row.get("SceneCode") or "").casefold() for row in current_rows}
        new: list[dict[str, Any]] = []
        for item in resolved:
            previous = await crud.get_scene_context_promotion_activation_exact(item["candidate"]["source_template_id"], item["fingerprint"], product_id)
            if previous:
                idempotent.append(previous)
                continue
            any_previous = await crud.get_scene_context_promotion_activation_exact(item["candidate"]["source_template_id"], item["fingerprint"])
            if any_previous:
                raise ActivationError("SCENE_ALREADY_ACTIVE")
            new.append(item)
        names: set[str] = set()
        backgrounds: set[str] = set()
        for item in new:
            row = item["candidate"]["row"]
            name, background = _content_key(row["SceneName"]), _content_key(row["BackgroundPrompt"])
            if name in names or background in backgrounds:
                raise ActivationError("SCENE_DUPLICATE")
            names.add(name)
            backgrounds.add(background)
        for item in new:
            duplicate = _registry.find_duplicate_scene(item["candidate"]["row"]["SceneName"], item["candidate"]["row"]["BackgroundPrompt"])
            if duplicate:
                raise ActivationError("SCENE_DUPLICATE")
        if not new:
            count = len(_registry.list_pool())
            return _bulk_result([_result(event, count, idempotent=True, mutations=0) for event in idempotent], 0)
        for field in ("PrimaryCluster", "CompatibleClusters", "SourceTemplateId", "CandidateFingerprint", "ActivationId"):
            if field not in headers:
                headers.append(field)
        previous_exists = _registry._BRIDGE_FILE.exists()
        previous_bytes = _registry._BRIDGE_FILE.read_bytes() if previous_exists else None
        before_digest = _digest(previous_bytes)
        events = []
        for item in new:
            activation_id = str(uuid.uuid4())
            code = _allocate_scene_code(item["candidate"]["row"]["SceneName"], existing_codes)
            row = _candidate_row(item, code, activation_id)
            current_rows.append(row)
            events.append({
                "activation_id": activation_id, "source_template_id": item["candidate"]["source_template_id"],
                "candidate_fingerprint": item["fingerprint"], "review_id": item["review"]["review_id"],
                "reviewed_via_product_id": product_id, "cluster": item["cluster"], "scene_code": code,
                "scene_name": row["SceneName"], "activated_by": activated_by, "activation_note": activation_note or None,
                "bridge_digest_before": before_digest, "activated_at": _now(),
            })
        proposed = _render_pool_bytes(headers, current_rows)
        try:
            sync = _registry.sync_pool_csv(proposed)
            after_digest = _digest(_registry._BRIDGE_FILE.read_bytes())
            for event in events:
                event["bridge_digest_after"] = after_digest
            await crud.append_scene_context_promotion_activation_events(events)
        except sqlite3.IntegrityError:
            _registry.restore_bridge_snapshot(previous_exists, previous_bytes)
            raced = [await crud.get_scene_context_promotion_activation_exact(event["source_template_id"], event["candidate_fingerprint"]) for event in events]
            if all(raced):
                count = len(_registry.list_pool())
                return _bulk_result([_result(event, count, idempotent=True, mutations=0) for event in raced], 0)
            raise
        except Exception:
            _registry.restore_bridge_snapshot(previous_exists, previous_bytes)
            raise
        count = sync["approved_loaded"]
        results = [_result(event, count, idempotent=False, mutations=1) for event in events]
        results.extend(_result(event, count, idempotent=True, mutations=0) for event in idempotent)
        return _bulk_result(results, len(events))


def _bulk_result(items: list[dict[str, Any]], mutations: int) -> dict[str, Any]:
    return {
        "requested_count": len(items), "activated_count": sum(not item["idempotent"] for item in items),
        "idempotent_count": sum(item["idempotent"] for item in items),
        "registry_scene_count": items[0]["registry_scene_count"] if items else len(_registry.list_pool()),
        "items": items, "registry_mutations": mutations, "provider_calls": 0,
        "generation_jobs": 0, "credits_used": 0,
    }


async def activation_history(product_id: str | None = None, source_template_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    history = await crud.list_scene_context_promotion_activation_history(product_id, source_template_id, limit)
    return {"count": len(history), "events": history, "registry_mutations": 0, "provider_calls": 0, "generation_jobs": 0, "credits_used": 0}
