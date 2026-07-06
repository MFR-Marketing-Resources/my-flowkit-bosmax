"""API + behavioral tests for POST /api/copy-sets/generate-batch — Phase 2.

Tests that monkeypatch ``generate_ai_copy_candidates_batch`` test the ROUTER
(error mapping, response shape).  Tests that monkeypatch only the PROVIDER
ADAPTER test real batch service behavior (ledger, dedupe, similarity, angle/hook
override, dry_run).

No live AI provider calls — provider adapter is always mocked.
"""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_sets import router
from agent.db import crud
from agent.services import ai_copy_assist_service as ai_svc
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_set_service as svc
from agent.models.copy_set import serialize_copy_set


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


# ═══════════════════════════════════════════════════════════
# Router-level tests (monkeypatch the whole service function)
# These prove error mapping and response shape.
# ═══════════════════════════════════════════════════════════

def test_router_rejects_count_below_min():
    response = _client().post("/api/copy-sets/generate-batch",
        json={"product_id": "x", "requested_count": 2})
    assert response.status_code == 422


def test_router_rejects_count_above_max():
    response = _client().post("/api/copy-sets/generate-batch",
        json={"product_id": "x", "requested_count": 11})
    assert response.status_code == 422


def test_router_rejects_missing_product_id():
    response = _client().post("/api/copy-sets/generate-batch",
        json={"requested_count": 5})
    assert response.status_code == 422


def test_router_default_count_is_5():
    from agent.models.copy_set import AICopyAssistBatchRequest
    req = AICopyAssistBatchRequest(product_id="test-id")
    assert req.requested_count == 5
    assert req.dry_run is False


def test_router_dry_run_default_false():
    from agent.models.copy_set import AICopyAssistBatchRequest
    req = AICopyAssistBatchRequest(product_id="test-id")
    assert req.dry_run is False


def test_router_fails_when_provider_not_configured(monkeypatch):
    async def fake_batch(request):
        raise ai_provider.AICopyProviderNotConfigured(ai_provider.ERR_NOT_CONFIGURED)
    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    resp = _client().post("/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "requested_count": 5})
    assert resp.status_code == 409


def test_router_provider_error_returns_502(monkeypatch):
    async def fake_batch(request):
        raise ai_provider.AICopyProviderError(ai_provider.ERR_CALL_FAILED, detail="timeout")
    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    resp = _client().post("/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "requested_count": 5})
    assert resp.status_code == 502


def test_router_product_not_found(monkeypatch):
    async def fake_batch(request):
        raise svc.CopySetError("PRODUCT_NOT_FOUND", status_code=404)
    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    resp = _client().post("/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "requested_count": 5})
    assert resp.status_code == 404


def test_router_success_response_shape(monkeypatch):
    """Router passes through service response correctly."""
    async def fake_batch(request):
        return {
            "batch_id": "batch-abc", "product_id": "p1",
            "requested_count": 5, "created_count": 2, "deduped_count": 1, "rejected_count": 0,
            "provider": {}, "candidates": [], "ledger": {"batch_id": "batch-abc"},
            "warnings": [], "dry_run": False,
        }
    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    resp = _client().post("/api/copy-sets/generate-batch",
        json={"product_id": "p1", "requested_count": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["batch_id"] == "batch-abc"
    assert "ledger" in body


# ═══════════════════════════════════════════════════════════
# Behavioral tests — real service, monkeypatched provider only.
# These prove ledger consistency, dedupe, similarity, dry_run.
# ═══════════════════════════════════════════════════════════

def _make_fake_provider_output(angle="Test Angle", hook="Test Hook",
                                subhook="", usp_set=None, cta="Buy now",
                                formula_family="HSO"):
    """Controlled provider output for deterministic testing."""
    return {
        "angle": angle, "hook": hook, "subhook": subhook,
        "usp_set": usp_set or ["USP A", "USP B"], "cta": cta,
        "formula_family": formula_family,
        "rationale": "test", "risk_notes": [],
    }


@pytest.mark.asyncio
async def test_behavioral_batch_creates_ledger_and_copy_sets(monkeypatch):
    """Real batch service: ledger row exists, candidates persisted, not auto-approved."""
    # 1. Create product
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Batch Behavioral Product",
        product_display_name="Batch Behavioral", product_short_name="Batch Behavioral",
    )
    # 2. Mock provider
    fake_out = _make_fake_provider_output(angle="Value Angle", hook="Value Hook", cta="Value CTA")
    calls_b1 = [0]
    def fake_gen_b1(brief):
        idx = calls_b1[0]
        calls_b1[0] += 1
        return _make_fake_provider_output(angle=f"Angle {idx}", hook=f"Hook {idx}", cta=f"CTA {idx}")

    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", fake_gen_b1)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "text_assist", "configured": True, "provider_id": "test", "model_id": "test-model"})

    # 3. Call the real service
    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=3))

    # 4. Verify response
    assert result["requested_count"] == 3
    assert result["created_count"] == 3
    assert result["deduped_count"] == 0
    batch_id = result["batch_id"]
    assert batch_id is not None
    assert result["ledger"]["batch_id"] == batch_id
    assert result["dry_run"] is False

    # 5. Verify ledger persisted
    batches = await crud.list_copy_generation_batches(product_id=product["id"])
    assert len(batches) == 1
    assert batches[0]["batch_id"] == batch_id
    assert batches[0]["requested_count"] == 3
    assert batches[0]["created_count"] == 3

    # 6. Verify Copy Sets persisted and NOT auto-approved
    cs_list = await crud.list_copy_sets_for_product(product["id"])
    assert len(cs_list) == 3
    for cs in cs_list:
        assert cs["status"] == "COPY_REVIEW_REQUIRED"
        assert cs["status"] != "COPY_APPROVED"


@pytest.mark.asyncio
async def test_behavioral_batch_id_matches_persisted_ledger(monkeypatch):
    """response batch_id == persisted ledger batch_id exactly."""
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Batch ID Test",
        product_display_name="Batch ID Test", product_short_name="Batch ID Test",
    )
    fake_out = _make_fake_provider_output()
    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", lambda brief: fake_out)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=3))

    resp_batch_id = result["batch_id"]
    ledger_batch_id = result["ledger"]["batch_id"]
    assert resp_batch_id == ledger_batch_id

    batches = await crud.list_copy_generation_batches(product_id=product["id"])
    assert batches[0]["batch_id"] == resp_batch_id


@pytest.mark.asyncio
async def test_behavioral_angle_hook_override(monkeypatch):
    """Operator-supplied angle/hook override provider output."""
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Override Test",
        product_display_name="Override Test", product_short_name="Override Test",
    )
    # Provider returns generic values
    fake_out = _make_fake_provider_output(angle="Provider Angle", hook="Provider Hook")
    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", lambda brief: fake_out)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(
            product_id=product["id"], requested_count=3,
            angle="OPERATOR_ANGLE", hook="OPERATOR_HOOK"))

    c = result["candidates"][0]
    # The existing AICopyAssistRequest passes angle/hook as overrides,
    # and _merge_candidate_fields prefers explicit operator fields over provider output.
    assert c["angle"] == "OPERATOR_ANGLE"
    assert c["hook"] == "OPERATOR_HOOK"


@pytest.mark.asyncio
async def test_behavioral_dry_run_persists_nothing(monkeypatch):
    """dry_run=True does NOT create Copy Sets or ledger rows."""
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Dry Run Test",
        product_display_name="Dry Run Test", product_short_name="Dry Run Test",
    )
    # Provider shouldn't be called in dry_run
    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=5, dry_run=True))

    assert result["dry_run"] is True
    assert result["created_count"] == 0
    assert result["batch_id"] is None
    assert result["ledger"] is None

    # Nothing persisted
    cs_list = await crud.list_copy_sets_for_product(product["id"])
    assert len(cs_list) == 0
    batches = await crud.list_copy_generation_batches(product_id=product["id"])
    assert len(batches) == 0


@pytest.mark.asyncio
async def test_behavioral_exact_duplicate_increments_deduped(monkeypatch):
    """Same provider output twice = second is exact dedupe match."""
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Dedup Test",
        product_display_name="Dedup Test", product_short_name="Dedup Test",
    )
    # Same output every time → first is created, rest are exact dupes
    def fake_dedup(brief):
        return _make_fake_provider_output(angle="Dedup Angle", hook="Dedup Hook")
    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", fake_dedup)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=3))

    # First is created, rest are exact dupes (same provider output → same dedupe_key)
    assert result["created_count"] >= 1
    assert result["deduped_count"] > 0
    assert result["created_count"] + result["deduped_count"] == 3


@pytest.mark.asyncio
async def test_behavioral_similarity_metadata_populated(monkeypatch):
    """Near-duplicate candidate has similarity_score, similar_to_copy_set_id, uniqueness_score."""
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Similarity Test",
        product_display_name="Similarity Test", product_short_name="Similarity Test",
    )
    # Provider returns very similar hooks (1 char/word differs, rest identical)
    # so combined_similarity > 0.80 on the second candidate vs the first.
    calls = [0]
    def fake_gen(brief):
        idx = calls[0]
        calls[0] += 1
        # Only the last character varies — hook is otherwise identical
        suffix = ["a", "b", "c"]
        return _make_fake_provider_output(
            hook=f"Kulit cerah glowing selepas guna produk ni dengan hasil yang sangat memuaskan dan terbukti berkesan untuk semua jenis kulit wajah {suffix[idx % 3]}",
            cta="Beli sekarang sebelum habis stok promosi terhad ini",
            usp_set=["Vitamin C premium", "Kolagen marin", "SPF perlindungan"])

    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", fake_gen)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=3))

    # First candidate has similarity=None (nothing to compare against),
    # second and third should have similarity populated against the first.
    found = False
    for i, c in enumerate(result["candidates"]):
        if i == 0:
            continue  # first has no comparison baseline
        assert c.get("similarity_score") is not None, f"Candidate {i} has no similarity_score"
        assert c.get("similar_to_copy_set_id") is not None, f"Candidate {i} has no similar_to_copy_set_id"
        assert c.get("uniqueness_score") is not None, f"Candidate {i} has no uniqueness_score"
        found = True
        # Near-duplicate warning should fire when score >= 0.80
        has_near_dup = any("NEAR_DUPLICATE" in w for w in c.get("warnings", []))
        if c.get("similarity_score", 0) >= 0.80:
            assert has_near_dup, f"Expected NEAR_DUPLICATE warning for score {c['similarity_score']}"
    assert found, "Candidates 1 and 2 must have similarity metadata against candidate 0"


@pytest.mark.asyncio
async def test_behavioral_no_live_provider_calls(monkeypatch):
    """Confirm provider is never called at import time or during test setup."""
    called = [False]
    def fake_gen(brief):
        called[0] = True
        return _make_fake_provider_output()

    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", fake_gen)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    product = await crud.create_product(
        source="MANUAL", raw_product_title="No Live Call Test",
        product_display_name="No Live Call Test", product_short_name="No Live Call Test",
    )

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=3))

    assert called[0] is True  # Our fake was called, not live provider
    assert result["created_count"] >= 1

@pytest.mark.asyncio
async def test_behavioral_dedupe_threshold_zero_is_honored(monkeypatch):
    """dedupe_threshold=0.0 is passed through, not silently replaced with 0.80."""
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Threshold Zero Test",
        product_display_name="Threshold Zero Test", product_short_name="Threshold Zero Test",
    )
    captured_threshold = []

    # Wrap find_nearest to capture the threshold argument
    from agent.services import copy_similarity_service as sim_svc
    original_find_nearest = sim_svc.find_nearest

    def wrap_find_nearest(candidate, existing, threshold=0.80):
        captured_threshold.append(threshold)
        return original_find_nearest(candidate, existing, threshold=threshold)

    monkeypatch.setattr(sim_svc, "find_nearest", wrap_find_nearest)

    fake_out = _make_fake_provider_output()
    calls = [0]
    def fake_gen(brief):
        idx = calls[0]; calls[0] += 1
        return _make_fake_provider_output(hook=f"Hook variant {idx}", cta=f"CTA {idx}")

    monkeypatch.setattr(ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "generate_candidate", fake_gen)
    monkeypatch.setattr(ai_provider, "provider_status",
                        lambda: {"lane": "test", "configured": True, "provider_id": "t", "model_id": "m"})

    from agent.models.copy_set import AICopyAssistBatchRequest
    result = await ai_svc.generate_ai_copy_candidates_batch(
        AICopyAssistBatchRequest(product_id=product["id"], requested_count=3, dedupe_threshold=0.0))

    assert result["created_count"] >= 1
    assert len(captured_threshold) > 0, "find_nearest was never called"
    for t in captured_threshold:
        assert t == 0.0, f"Expected threshold 0.0, got {t}"

