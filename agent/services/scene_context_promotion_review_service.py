"""Round 3 product-first owner review, isolated from scene registry activation."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from agent.db import crud
from agent.services import product_scene_suitability_service as _suitability
from agent.services import scene_context_promotion_service as _promotion

ALLOWED_DECISIONS = {"PENDING", "APPROVED_FOR_FUTURE_PROMOTION", "REJECTED"}
MAX_BULK = 25


class ReviewError(ValueError):
    pass


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    row = candidate["row"]
    payload = {
        "source_template_id": candidate["source_template_id"], "cluster": candidate["cluster"],
        "source_category": candidate.get("source_category"), "setting": " ".join(candidate.get("setting", "").split()),
        "SceneCode": row["SceneCode"], "SceneName": row["SceneName"], "BackgroundPrompt": row["BackgroundPrompt"],
        "PromptV1": row["PromptV1"], "SafetyBlock": row["SafetyBlock"], "usage_tags": row["usage_tags"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def product_review(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ReviewError("PRODUCT_NOT_FOUND")
    suitability = await _suitability.recommend_scene_suitability_for_product(product_id)
    cluster = suitability["cluster"]
    base = {"dry_run": True, "activation_allowed": False, "product_id": product_id,
            "product_name": suitability.get("product_name"), "category": product.get("category"),
            "cluster": cluster, "cluster_source": suitability["cluster_source"],
            "review_required": suitability.get("review_required", False),
            "product_suitability_template_count": suitability["template_count"]}
    if cluster is None:
        return {**base, "registry_mutations": 0, "candidate_count": 0, "quarantine_count": 0, "decision_counts": {key: 0 for key in ("PENDING", "APPROVED_FOR_FUTURE_PROMOTION", "REJECTED", "STALE_REVIEW_REQUIRED")}, "candidates": [], "quarantine": [],
                "message": "PRODUCT CATEGORY REVIEW REQUIRED: correct the product category before reviewing promotion candidates."}
    preview = _promotion.preview_scene_context_promotion(cluster)
    allowed = {item["template_id"] for item in suitability["recommendations"]}
    candidates = [c for c in preview["candidates"] if c["source_template_id"] in allowed]
    quarantine = [q for q in preview["quarantine"] if q["source_template_id"] in allowed]
    history = await crud.get_scene_context_promotion_reviews([c["source_template_id"] for c in candidates])
    by_template: dict[str, list[dict]] = {}
    for record in history:
        by_template.setdefault(record["source_template_id"], []).append(record)
    rendered = []
    for candidate in candidates:
        fingerprint = candidate_fingerprint(candidate)
        records = by_template.get(candidate["source_template_id"], [])
        record = next((r for r in records if r["candidate_fingerprint"] == fingerprint), None)
        stale = record is None and bool(records)
        decision = "STALE_REVIEW_REQUIRED" if stale else (record["decision"] if record else "PENDING")
        row = candidate["row"]
        rendered.append({"source_template_id": candidate["source_template_id"], "source_category": candidate.get("source_category"), "setting": candidate.get("setting"),
                         "candidate_fingerprint": fingerprint, "proposed_scene_code": row["SceneCode"], "proposed_scene_name": row["SceneName"],
                         "background_prompt": row["BackgroundPrompt"], "prompt_v1": row["PromptV1"], "safety_block": row["SafetyBlock"], "usage_tags": row["usage_tags"], "decision": decision,
                         "reviewer_note": record.get("reviewer_note") if record and not stale else None,
                         "reviewed_at": record.get("reviewed_at") if record else None,
                         "stale_review_required": stale, "activation_status": "NOT_ACTIVATED"})
    counts = Counter(c["decision"] for c in rendered)
    decision_counts = {key: counts.get(key, 0) for key in ("PENDING", "APPROVED_FOR_FUTURE_PROMOTION", "REJECTED", "STALE_REVIEW_REQUIRED")}
    return {**base, "registry_mutations": 0, "candidate_count": len(rendered), "quarantine_count": len(quarantine), "decision_counts": decision_counts,
            "candidates": rendered, "quarantine": quarantine, "source": preview["source"]}


async def record_reviews(product_id: str, items: list[dict]) -> dict:
    if not items or len(items) > MAX_BULK:
        raise ReviewError("INVALID_REVIEW_BATCH")
    template_ids = [str(item.get("source_template_id") or "") for item in items]
    if len(template_ids) != len(set(template_ids)):
        raise ReviewError("DUPLICATE_REVIEW_BATCH_ITEM")
    review = await product_review(product_id)
    if review["review_required"]:
        raise ReviewError("PRODUCT_CLUSTER_REVIEW_REQUIRED")
    current = {c["source_template_id"]: c for c in review["candidates"]}
    preview = _promotion.preview_scene_context_promotion(review["cluster"])
    quarantined = {q["source_template_id"] for q in preview["quarantine"]}
    suitable = {item["template_id"] for item in (await _suitability.recommend_scene_suitability_for_product(product_id))["recommendations"]}
    library = {item["template_id"] for item in _suitability._scene_prompts.library_templates()}
    prepared = []
    for item in items:
        template_id = str(item.get("source_template_id") or "")
        if template_id not in library:
            raise ReviewError("UNKNOWN_SOURCE_TEMPLATE")
        if template_id in quarantined:
            raise ReviewError("CANDIDATE_QUARANTINED")
        candidate = current.get(template_id)
        if not candidate:
            raise ReviewError("PRODUCT_TEMPLATE_MISMATCH" if template_id in suitable else "CANDIDATE_NOT_CURRENTLY_PROMOTABLE")
        if item.get("candidate_fingerprint") != candidate["candidate_fingerprint"]:
            raise ReviewError("STALE_CANDIDATE_FINGERPRINT")
        decision = item.get("decision")
        if decision not in ALLOWED_DECISIONS:
            raise ReviewError("INVALID_REVIEW_DECISION")
        note = str(item.get("reviewer_note") or "")
        if len(note) > 2000:
            raise ReviewError("REVIEW_NOTE_TOO_LONG")
        prepared.append({"source_template_id": template_id, "candidate_fingerprint": candidate["candidate_fingerprint"],
                         "cluster": review["cluster"], "decision": decision, "reviewer_note": note or None,
                         "reviewed_via_product_id": product_id})
    await crud.record_scene_context_promotion_reviews(prepared)
    return await product_review(product_id)
