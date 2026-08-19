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


# --------------------------------------------------------------------------- #
# Approved Generation Manifest — HTTP contract (multi-op explicit approval)
# --------------------------------------------------------------------------- #

def _manifest_body(run_ref: str, **ov) -> dict:
    body = {
        "surface": "montage",
        "run_ref": run_ref,
        "created_by": "faris",
        "items": [
            {"item_key": "scene_1", "mode": "F2V",
             "final_prompt_text": f"{run_ref} scene one clean prompt",
             "model": "Veo 3.1 Lite", "aspect": "9:16", "duration_s": 8, "count": 1},
            {"item_key": "scene_2", "mode": "F2V",
             "final_prompt_text": f"{run_ref} scene two clean prompt",
             "model": "Veo 3.1 Lite", "aspect": "9:16", "duration_s": 8, "count": 1},
        ],
    }
    body.update(ov)
    return body


def test_manifest_create_review_approve_and_lookup():
    client = _client()
    r = client.post("/api/execution-approval/manifest", json=_manifest_body("api_run_1"))
    assert r.status_code == 200, r.text
    manifest = r.json()
    assert manifest["state"] == "REVIEW_REQUIRED"
    assert manifest["item_count"] == 2
    assert len(manifest["items"]) == 2
    mid = manifest["manifest_id"]

    # get with items
    assert client.get(f"/api/execution-approval/manifest/{mid}").json()["state"] == "REVIEW_REQUIRED"

    # approve atomically
    r = client.post(f"/api/execution-approval/manifest/{mid}/approve",
                    json={"approved_by": "faris"})
    assert r.status_code == 200, r.text
    approved = r.json()
    assert approved["state"] == "APPROVED"
    assert all(i["approval_state"] == "APPROVED" for i in approved["items"])

    # dispatch-side lookup by run_ref finds the approved manifest
    r = client.get("/api/execution-approval/manifest",
                   params={"run_ref": "api_run_1", "surface": "montage"})
    ids = [m["manifest_id"] for m in r.json()["items"]]
    assert mid in ids


def test_manifest_approve_refused_when_item_dirty():
    client = _client()
    body = _manifest_body("api_run_dirty", product_id="prod_api_dirty")
    body["items"][1]["final_prompt_text"] = "scene leaking prod_api_dirty into text"
    body["items"][1]["product_id"] = "prod_api_dirty"
    mid = client.post("/api/execution-approval/manifest", json=body).json()["manifest_id"]
    r = client.post(f"/api/execution-approval/manifest/{mid}/approve",
                    json={"approved_by": "faris"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "MANIFEST_SCAN_NOT_CLEAN"


def test_manifest_item_edit_then_approve():
    client = _client()
    manifest = client.post(
        "/api/execution-approval/manifest", json=_manifest_body("api_run_edit"),
    ).json()
    mid = manifest["manifest_id"]
    sid = manifest["items"][0]["snapshot_id"]
    r = client.post(
        f"/api/execution-approval/manifest/{mid}/item/{sid}/edit",
        json={"edited_prompt_text": "api_run_edit scene one REVISED clean prompt"},
    )
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["snapshot_id"] == sid)
    assert item["approval_state"] == "EDITED"
    assert client.post(
        f"/api/execution-approval/manifest/{mid}/approve", json={"approved_by": "faris"},
    ).json()["state"] == "APPROVED"


def test_approved_manifest_is_immutable_to_item_edit():
    client = _client()
    manifest = client.post(
        "/api/execution-approval/manifest", json=_manifest_body("api_run_immut"),
    ).json()
    mid = manifest["manifest_id"]
    sid = manifest["items"][0]["snapshot_id"]
    client.post(f"/api/execution-approval/manifest/{mid}/approve", json={"approved_by": "faris"})
    r = client.post(
        f"/api/execution-approval/manifest/{mid}/item/{sid}/edit",
        json={"edited_prompt_text": "trying to edit an approved manifest item"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "MANIFEST_IMMUTABLE"


def test_prepare_video_freezes_provided_prompt():
    client = _client()
    r = client.post("/api/execution-approval/prepare", json={
        "surface": "hybrid", "logical_mode": "F2V",
        "prompt": "PREP_api video passes through unchanged",
        "model": "Veo 3.1 Lite", "aspect": "9:16", "duration_s": 8, "count": 1,
        "created_by": "faris",
    })
    assert r.status_code == 200, r.text
    snap = r.json()
    assert snap["approval_state"] == "REVIEW_REQUIRED"
    # Video is pass-through (no product grounding): final == provided prompt.
    assert snap["final_prompt_text"] == "PREP_api video passes through unchanged"


def test_manifest_fail_closed_on_unresolvable_product_visual(monkeypatch):
    # PR #816: a product-backed HYBRID/F2V materialize whose canonical product
    # visual cannot resolve fails CLOSED (never a silent fallback) and surfaces as
    # a clean 4xx — not a 500. Overrides the autouse success-mock to raise.
    async def _raise(product_id, slot_key="start_frame"):
        raise RuntimeError("no canonical visual for " + product_id)

    monkeypatch.setattr(
        "agent.services.product_visual_grounding_resolver.get_canonical_product_visual_fingerprint",
        _raise,
    )
    client = _client()
    r = client.post("/api/execution-approval/manifest", json={
        "surface": "montage", "run_ref": "run_failclosed", "product_id": "prod_novisual",
        "items": [dict(item_key="s1", mode="F2V", final_prompt_text="a clean scene prompt",
                       product_id="prod_novisual", source_mode="HYBRID",
                       model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1)],
    })
    assert r.status_code == 409, r.text
    assert "PRODUCT_VISUAL_REFERENCE_REQUIRED" in str(r.json())
