"""API contract tests for the Copy Set router (Copy Strategy Studio Phase 1).

These assert the HTTP surface and error mapping. The service's DB-backed behavior
(resolver chain, dedupe, fail-closed approval) is covered in
tests/unit/test_copy_set_service.py.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_sets import router
from agent.models.copy_set import APPROVAL_PHRASE
from agent.services import copy_set_service as svc


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _sample_copy_set(**over):
    base = {
        "copy_set_id": "cs-001",
        "product_id": "prod-001",
        "angle": "Segar sepanjang hari",
        "hook": "Nak kulit nampak segar?",
        "subhook": "",
        "usp_set": ["Senang guna"],
        "cta": "Cuba hari ni.",
        "platform": "TIKTOK",
        "language": "BM_MS",
        "route_type": "DIRECT",
        "formula_family": "HSO",
        "status": "DRAFT_COPY",
        "dedupe_key": "k",
        "source": "COPY_SIGNAL_GENERATOR",
        "provenance": {},
        "claim_review": {},
        "reviewer_note": None,
        "approved_at": None,
        "approved_by": None,
        "created_at": "2026-07-03T00:00:00Z",
        "updated_at": "2026-07-03T00:00:00Z",
    }
    base.update(over)
    return base


def test_generate_returns_copy_set(monkeypatch):
    async def fake_generate(request):
        return {"copy_set": _sample_copy_set(), "created": True, "dedupe_match": False}

    monkeypatch.setattr(svc, "generate_copy_set", fake_generate)
    response = _client().post("/api/copy-sets/generate", json={"product_id": "prod-001"})
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["copy_set"]["copy_set_id"] == "cs-001"


def test_generate_product_not_found(monkeypatch):
    async def fake_generate(request):
        raise svc.CopySetError("PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": "x"})

    monkeypatch.setattr(svc, "generate_copy_set", fake_generate)
    response = _client().post("/api/copy-sets/generate", json={"product_id": "x"})
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "PRODUCT_NOT_FOUND"


def test_get_copy_set_not_found(monkeypatch):
    async def fake_get(copy_set_id):
        return None

    monkeypatch.setattr(svc, "get_copy_set", fake_get)
    response = _client().get("/api/copy-sets/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "COPY_SET_NOT_FOUND"


def test_list_for_product(monkeypatch):
    async def fake_list(product_id):
        return [_sample_copy_set()]

    monkeypatch.setattr(svc, "list_copy_sets", fake_list)
    response = _client().get("/api/copy-sets/product/prod-001")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == "prod-001"
    assert len(body["items"]) == 1


def test_approve_wrong_phrase_returns_400(monkeypatch):
    async def fake_approve(copy_set_id, request):
        raise svc.CopySetPermissionError("INVALID_APPROVAL_PHRASE", expected=APPROVAL_PHRASE)

    monkeypatch.setattr(svc, "approve_copy_set", fake_approve)
    response = _client().post(
        "/api/copy-sets/cs-001/approve", json={"approval_phrase": "WRONG"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["approval_phrase"] == APPROVAL_PHRASE


def test_approve_unsafe_returns_422(monkeypatch):
    async def fake_approve(copy_set_id, request):
        raise svc.CopySetError(
            "COPY_SET_UNSAFE", status_code=422, detail={"violations": ["MEDICAL_CLAIM"]}
        )

    monkeypatch.setattr(svc, "approve_copy_set", fake_approve)
    response = _client().post(
        "/api/copy-sets/cs-001/approve", json={"approval_phrase": APPROVAL_PHRASE}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "COPY_SET_UNSAFE"


def test_approve_success_returns_200(monkeypatch):
    async def fake_approve(copy_set_id, request):
        return _sample_copy_set(status="COPY_APPROVED", approved_at="2026-07-03T01:00:00Z", approved_by="faris")

    monkeypatch.setattr(svc, "approve_copy_set", fake_approve)
    response = _client().post(
        "/api/copy-sets/cs-001/approve",
        json={"approval_phrase": APPROVAL_PHRASE, "reviewer_note": "ok"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "COPY_APPROVED"


def test_patch_and_reject_and_regenerate(monkeypatch):
    async def fake_patch(copy_set_id, request):
        return _sample_copy_set(hook="Hook baru", status="DRAFT_COPY")

    async def fake_reject(copy_set_id, request):
        return _sample_copy_set(status="COPY_REJECTED", reviewer_note="angle salah")

    async def fake_regen(copy_set_id, request):
        return _sample_copy_set(status="DRAFT_COPY")

    monkeypatch.setattr(svc, "patch_copy_set", fake_patch)
    monkeypatch.setattr(svc, "reject_copy_set", fake_reject)
    monkeypatch.setattr(svc, "regenerate_copy_set", fake_regen)

    client = _client()
    patched = client.patch("/api/copy-sets/cs-001", json={"hook": "Hook baru"})
    assert patched.status_code == 200
    assert patched.json()["hook"] == "Hook baru"

    rejected = client.post("/api/copy-sets/cs-001/reject", json={"reviewer_note": "angle salah"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "COPY_REJECTED"

    regenerated = client.post("/api/copy-sets/cs-001/regenerate", json={"angle": "Angle baru"})
    assert regenerated.status_code == 200
    assert regenerated.json()["status"] == "DRAFT_COPY"

    # Regenerate also works with no body (product is derived from the Copy Set).
    regenerated_empty = client.post("/api/copy-sets/cs-001/regenerate")
    assert regenerated_empty.status_code == 200
