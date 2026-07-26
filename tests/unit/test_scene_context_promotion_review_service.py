"""Round 3 owner-review service contracts: read-only promotion decisions."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.services import scene_context_promotion_review_service as svc


def _candidate(setting: str = "Soft daylight vanity alcove") -> dict:
    return {
        "source_template_id": "SCN-BEAUTY-01",
        "cluster": "Beauty",
        "source_category": "Beauty & Personal Care",
        "setting": setting,
        "row": {
            "SceneCode": "SCN_BEAUTY_01",
            "SceneName": "Beauty — vanity alcove",
            "BackgroundPrompt": "Background: soft daylight vanity alcove",
            "PromptV1": "Empty background plate.",
            "SafetyBlock": "EMPTY_BACKGROUND_ONLY",
            "usage_tags": "scene_context|cluster:beauty",
        },
    }


def _known_suitability(template_id: str = "SCN-BEAUTY-01") -> dict:
    return {
        "cluster": "Beauty",
        "cluster_source": "EXACT",
        "review_required": False,
        "template_count": 1,
        "recommendations": [{"template_id": template_id}],
        "product_name": "Serum",
    }


def test_candidate_fingerprint_is_deterministic_and_tracks_candidate_content():
    candidate = _candidate()

    assert svc.candidate_fingerprint(candidate) == svc.candidate_fingerprint(candidate)
    assert svc.candidate_fingerprint(candidate) != svc.candidate_fingerprint(
        _candidate("Different empty daylight studio")
    )


@pytest.mark.asyncio
async def test_unknown_category_product_review_has_full_zero_contract(monkeypatch):
    async def product(_product_id):
        return {"id": "p-unknown", "category": "Unmapped Nebula Equipment"}

    async def suitability(_product_id):
        return {
            "cluster": None,
            "cluster_source": "REVIEW_REQUIRED_UNKNOWN_CATEGORY",
            "review_required": True,
            "template_count": 0,
            "recommendations": [],
            "product_name": "Unknown Product",
        }

    monkeypatch.setattr(svc.crud, "get_product", product)
    monkeypatch.setattr(svc._suitability, "recommend_scene_suitability_for_product", suitability)

    result = await svc.product_review("p-unknown")

    assert result["activation_allowed"] is False
    assert result["registry_mutations"] == 0
    assert result["candidate_count"] == result["quarantine_count"] == 0
    assert result["candidates"] == result["quarantine"] == []
    assert result["decision_counts"] == {
        "PENDING": 0,
        "APPROVED_FOR_FUTURE_PROMOTION": 0,
        "REJECTED": 0,
        "STALE_REVIEW_REQUIRED": 0,
    }


@pytest.mark.asyncio
async def test_product_review_resolves_exact_current_fingerprint_before_stale(monkeypatch):
    candidate = _candidate()
    fingerprint = svc.candidate_fingerprint(candidate)

    async def product(_product_id):
        return {"id": "p1", "category": "Beauty & Personal Care"}

    async def history(_template_ids):
        return [
            {"source_template_id": candidate["source_template_id"], "candidate_fingerprint": "older", "decision": "REJECTED", "reviewer_note": "old", "reviewed_at": "2026-01-01T00:00:00Z"},
            {"source_template_id": candidate["source_template_id"], "candidate_fingerprint": fingerprint, "decision": "APPROVED_FOR_FUTURE_PROMOTION", "reviewer_note": "current", "reviewed_at": "2026-01-02T00:00:00Z"},
        ]

    monkeypatch.setattr(svc.crud, "get_product", product)
    monkeypatch.setattr(svc.crud, "get_scene_context_promotion_reviews", history)
    monkeypatch.setattr(svc._suitability, "recommend_scene_suitability_for_product", lambda _: _await(_known_suitability()))
    monkeypatch.setattr(svc._promotion, "preview_scene_context_promotion", lambda _: {"candidates": [candidate], "quarantine": [], "source": "TEST"})

    result = await svc.product_review("p1")

    assert result["candidates"][0]["decision"] == "APPROVED_FOR_FUTURE_PROMOTION"
    assert result["candidates"][0]["stale_review_required"] is False


@pytest.mark.asyncio
async def test_product_review_marks_only_older_fingerprint_stale(monkeypatch):
    candidate = _candidate()

    async def product(_product_id):
        return {"id": "p1", "category": "Beauty & Personal Care"}

    async def history(_template_ids):
        return [{"source_template_id": candidate["source_template_id"], "candidate_fingerprint": "older", "decision": "REJECTED", "reviewer_note": "old", "reviewed_at": "2026-01-01T00:00:00Z"}]

    monkeypatch.setattr(svc.crud, "get_product", product)
    monkeypatch.setattr(svc.crud, "get_scene_context_promotion_reviews", history)
    monkeypatch.setattr(svc._suitability, "recommend_scene_suitability_for_product", lambda _: _await(_known_suitability()))
    monkeypatch.setattr(svc._promotion, "preview_scene_context_promotion", lambda _: {"candidates": [candidate], "quarantine": [], "source": "TEST"})

    result = await svc.product_review("p1")

    assert result["candidates"][0]["decision"] == "STALE_REVIEW_REQUIRED"
    assert result["candidates"][0]["stale_review_required"] is True


async def _await(value):
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("template_id", "library", "suitable", "quarantined", "current", "fingerprint", "expected"),
    (
        ("unknown", {"known"}, {"known"}, {"known"}, {}, "fp", "UNKNOWN_SOURCE_TEMPLATE"),
        ("known", {"known"}, set(), {"known"}, {}, "fp", "PRODUCT_TEMPLATE_MISMATCH"),
        ("known", {"known"}, {"known"}, {"known"}, {}, "fp", "CANDIDATE_QUARANTINED"),
        ("known", {"known"}, {"known"}, set(), {}, "fp", "CANDIDATE_NOT_CURRENTLY_PROMOTABLE"),
        ("known", {"known"}, {"known"}, set(), {"known": {"source_template_id": "known", "candidate_fingerprint": "current"}}, "stale", "STALE_CANDIDATE_FINGERPRINT"),
    ),
)
async def test_review_validation_precedence(monkeypatch, template_id, library, suitable, quarantined, current, fingerprint, expected):
    async def product_review(_product_id):
        return {"review_required": False, "cluster": "Beauty", "candidates": list(current.values())}

    async def suitability(_product_id):
        return {"recommendations": [{"template_id": value} for value in suitable]}

    monkeypatch.setattr(svc, "product_review", product_review)
    monkeypatch.setattr(svc._suitability, "recommend_scene_suitability_for_product", suitability)
    monkeypatch.setattr(svc._scene_prompts, "library_templates", lambda: [{"template_id": value} for value in library])
    monkeypatch.setattr(svc._promotion, "preview_scene_context_promotion", lambda _: {"quarantine": [{"source_template_id": value} for value in quarantined]})

    with pytest.raises(svc.ReviewError, match=expected):
        await svc.record_reviews("p1", [{"source_template_id": template_id, "candidate_fingerprint": fingerprint, "decision": "PENDING"}])


@pytest.mark.asyncio
async def test_duplicate_bulk_item_is_rejected_before_any_write(monkeypatch):
    called = False

    async def unexpected_product_review(_product_id):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(svc, "product_review", unexpected_product_review)

    with pytest.raises(svc.ReviewError, match="DUPLICATE_REVIEW_BATCH_ITEM"):
        await svc.record_reviews("p1", [
            {"source_template_id": "same"},
            {"source_template_id": "same"},
        ])
    assert called is False


def test_review_service_has_no_seed_bridge_registry_provider_or_generation_side_effects():
    source = Path(svc.__file__).read_text(encoding="utf-8")
    forbidden = (
        "sync_pool_csv", "add_scene", "seed_scene", "make_video",
        "start_generate", "provider", "credit",
    )
    assert not any(token in source for token in forbidden)


@pytest.mark.asyncio
async def test_review_submission_only_calls_the_review_ledger_and_preserves_csv_bridge(tmp_path, monkeypatch):
    seed = Path(__file__).resolve().parents[2] / "agent" / "authority" / "SCENE_CONTEXT_POOL.csv"
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    bridge = tmp_path / "SCENE_CONTEXT_POOL.bridge.csv"
    recorded = []

    async def product_review(_product_id):
        return {
            "review_required": False,
            "cluster": "Beauty",
            "candidates": [{
                "source_template_id": "SCN-BEAUTY-01",
                "candidate_fingerprint": "fp",
            }],
        }

    async def suitability(_product_id):
        return {"recommendations": [{"template_id": "SCN-BEAUTY-01"}]}

    async def record(items):
        recorded.extend(items)

    monkeypatch.setattr(svc, "product_review", product_review)
    monkeypatch.setattr(svc._suitability, "recommend_scene_suitability_for_product", suitability)
    monkeypatch.setattr(svc._scene_prompts, "library_templates", lambda: [{"template_id": "SCN-BEAUTY-01"}])
    monkeypatch.setattr(svc._promotion, "preview_scene_context_promotion", lambda _: {"quarantine": []})
    monkeypatch.setattr(svc.crud, "record_scene_context_promotion_reviews", record)

    monkeypatch.setattr("agent.services.scene_context_registry._BRIDGE_FILE", bridge)

    await svc.record_reviews("p1", [{
        "source_template_id": "SCN-BEAUTY-01",
        "candidate_fingerprint": "fp",
        "decision": "PENDING",
    }])

    assert recorded == [{
        "source_template_id": "SCN-BEAUTY-01",
        "candidate_fingerprint": "fp",
        "cluster": "Beauty",
        "decision": "PENDING",
        "reviewer_note": None,
        "reviewed_via_product_id": "p1",
    }]
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == digest
    assert bridge.exists() is False
