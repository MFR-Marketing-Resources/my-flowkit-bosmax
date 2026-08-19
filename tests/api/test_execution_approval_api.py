"""HTTP contract for the Final Prompt Approval Gate lifecycle (provider-free)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from agent.main import app


@pytest.fixture(autouse=True)
def _mock_canonical_pv(monkeypatch):
    async def _mock_fp(product_id: str, slot_key: str = "start_frame"):
        return f"PRODUCT_VISUAL|{product_id}|{slot_key}|fake_canonical_sha256"

    monkeypatch.setattr(
        "agent.services.product_visual_grounding_resolver.get_canonical_product_visual_fingerprint",
        _mock_fp,
    )


def _client() -> TestClient:
    return TestClient(app)


def _review_body(prompt: str, **ov) -> dict:
    body = {
        "surface": "hybrid",
        "logical_mode": "F2V",
        "final_prompt_text": prompt,
        "source_mode": "HYBRID",
        "model": "Veo 3.1 Lite",
        "aspect": "9:16",
        "duration_s": 8,
        "count": 1,
        "asset_media_ids": ["550e8400-e29b-41d4-a716-446655440000"],
        "created_by": "faris",
    }
    body.update(ov)
    return body


def test_review_then_approve_then_get():
    client = _client()
    r = client.post("/api/execution-approval/review",
                    json=_review_body("A_api clean provider-ready prompt"))
    assert r.status_code == 200, r.text
    snap = r.json()
    assert snap["approval_state"] == "REVIEW_REQUIRED"
    assert snap["scan_clean"] == 1
    sid = snap["snapshot_id"]

    r = client.post(f"/api/execution-approval/{sid}/approve",
                    json={"approved_by": "faris"})
    assert r.status_code == 200, r.text
    approved = r.json()
    assert approved["approval_state"] == "APPROVED"
    assert approved["approved_execution_envelope_sha256"] == snap["execution_envelope_sha256"]

    r = client.get(f"/api/execution-approval/{sid}")
    assert r.status_code == 200
    assert r.json()["approval_state"] == "APPROVED"


def test_edit_returns_to_edited_and_can_reapprove():
    client = _client()
    sid = client.post("/api/execution-approval/review",
                      json=_review_body("B_api original prompt")).json()["snapshot_id"]
    client.post(f"/api/execution-approval/{sid}/approve", json={"approved_by": "faris"})

    r = client.post(f"/api/execution-approval/{sid}/edit",
                    json={"edited_prompt_text": "B_api edited provider-ready prompt"})
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["approval_state"] == "EDITED"
    assert edited["approved_execution_envelope_sha256"] is None

    r = client.post(f"/api/execution-approval/{sid}/approve", json={"approved_by": "faris"})
    assert r.status_code == 200
    assert r.json()["approval_state"] == "APPROVED"


def test_invalidate_sets_state():
    client = _client()
    sid = client.post("/api/execution-approval/review",
                      json=_review_body("C_api prompt")).json()["snapshot_id"]
    client.post(f"/api/execution-approval/{sid}/approve", json={"approved_by": "faris"})
    r = client.post(f"/api/execution-approval/{sid}/invalidate",
                    json={"reason": "asset changed"})
    assert r.status_code == 200
    assert r.json()["approval_state"] == "INVALIDATED"


def test_approve_refused_when_scan_not_clean():
    client = _client()
    sid = client.post(
        "/api/execution-approval/review",
        json=_review_body("D_api leaks prod_leak_1", product_id="prod_leak_1"),
    ).json()["snapshot_id"]
    r = client.post(f"/api/execution-approval/{sid}/approve", json={"approved_by": "faris"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "SNAPSHOT_SCAN_NOT_CLEAN"


def test_unknown_snapshot_is_404():
    client = _client()
    assert client.get("/api/execution-approval/eas_does_not_exist").status_code == 404
    r = client.post("/api/execution-approval/eas_does_not_exist/approve",
                    json={"approved_by": "faris"})
    assert r.status_code == 404
