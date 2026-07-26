"""Round 3 product-first owner review, isolated from scene registry activation."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from agent.db import crud
from agent.services import creative_avatar_recommendation_service as _clusters
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
        return {**base, "candidate_count": 0, "quarantine_count": 0, "decision_counts": {}, "candidates": [], "quarantine": [],
                "message": "PRODUCT CATEGORY REVIEW REQUIRED: correct the product category before reviewing promotion candidates."}
    preview = _promotion.preview_scene_context_promotion(cluster)
    allowed = {item["template_id"] for item in suitability["recommendations"]}
    candidates = [c for c in preview["candidates"] if c["source_template_id"] in allowed]
    quarantine = [q for q in preview["quarantine"] if q["source_template_id"] in allowed]
    history = await crud.get_scene_context_promotion_reviews([c["source_template_id"] for c in candidates])
    latest: dict[str, dict] = {}
    for record in history:
        latest.setdefault(record["source_template_id"], record)
    rendered = []
    for candidate in candidates:
        fingerprint = candidate_fingerprint(candidate)
        record = latest.get(candidate["source_template_id"])
        stale = bool(record and record["candidate_fingerprint"] != fingerprint)
        decision = "STALE_REVIEW_REQUIRED" if stale else (record["decision"] if record else "PENDING")
        rendered.append({**candidate, "candidate_fingerprint": fingerprint, "decision": decision,
                         "reviewer_note": record.get("reviewer_note") if record and not stale else None,
                         "reviewed_at": record.get("reviewed_at") if record else None,
                         "stale_review_required": stale, "activation_status": "NOT_ACTIVATED"})
    counts = Counter(c["decision"] for c in rendered)
    return {**base, "candidate_count": len(rendered), "quarantine_count": len(quarantine), "decision_counts": dict(counts),
            "candidates": rendered, "quarantine": quarantine, "source": preview["source"]}


async def record_reviews(product_id: str, items: list[dict]) -> dict:
    if not items or len(items) > MAX_BULK:
        raise ReviewError("INVALID_REVIEW_BATCH")
    review = await product_review(product_id)
    if review["review_required"]:
        raise ReviewError("PRODUCT_CLUSTER_REVIEW_REQUIRED")
    current = {c["source_template_id"]: c for c in review["candidates"]}
    prepared = []
    for item in items:
        template_id = str(item.get("source_template_id") or "")
        candidate = current.get(template_id)
        if not candidate:
            raise ReviewError("CANDIDATE_NOT_REVIEWABLE")
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
