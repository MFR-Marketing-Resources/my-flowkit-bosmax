"""End-to-end provider-free UAT for the Final Prompt Approval Gate + Approved
Generation Manifest.

Reaches the REAL approval boundary — ``make_video.start_generate`` (the exact
credit-bearing dispatch choke ``/api/flow/generate`` forwards to, after its
product/copy baseline validation) — plus the HTTP manifest lifecycle and the
FlowClient provider-boundary backstop. Nothing here ever calls a provider or
spends a credit: enforcement is ON, ``_run_generate`` is stubbed to a no-op, and
the FlowClient runs disconnected/mock.

Proves the whole contract directly:

    NO-APPROVAL           -> BLOCK   (DISPATCH_NOT_APPROVED)     [video + IMG]
    APPROVED-EXACT        -> PASS    (SUBMITTED)
    CHANGED-PROMPT        -> BLOCK
    CHANGED-SETTING       -> BLOCK
    STALE (invalidated)   -> BLOCK
    MANIFEST (unapproved) -> BLOCK ; (approved) -> PASS
    PROVIDER BACKSTOP     -> unauthorised video _send is refused, never reaching
                             the transport, even if a lane forgot the gate.

Why this boundary and not the /api/flow/generate HTTP wrapper: that wrapper
first runs copy-register-v2 product-truth resolution, which requires a fully
seeded product + copy binding unrelated to this gate. The gate itself lives in
start_generate; driving it directly is the faithful, fixture-free proof that the
approval boundary blocks and passes exactly as specified.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from agent.main import app
from agent.services import execution_approval_service as eas
from agent.services import make_video
from agent.services.flow_client import FlowClient


_ASSET = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _provider_free(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas._DISPATCH_AUTH.set(None)

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(make_video, "_run_generate", _noop)
    monkeypatch.setattr(make_video, "_VIDEO_LANE_JOB", None, raising=False)
    yield


def _client() -> TestClient:
    return TestClient(app)


async def _review_video(prompt: str, **ov) -> dict:
    spec = dict(surface="uat", logical_mode="F2V", final_prompt_text=prompt,
                product_id="uat_prod", source_mode="HYBRID", model="Veo 3.1 Lite",
                aspect="9:16", duration_s=8, count=1, asset_media_ids=[_ASSET])
    spec.update(ov)
    snap = await eas.create_review_snapshot(**spec)
    return await eas.approve_snapshot(snap["snapshot_id"], approved_by="uat")


async def _dispatch_video(prompt: str, **ov) -> dict:
    """Fire the REAL video dispatch choke (provider-free). Same envelope inputs a
    UI Hybrid dispatch hands make_video."""
    kw = dict(mode="F2V", prompt=prompt,
              image_media_ids=[_ASSET], aspect="9:16", model="Veo 3.1 Lite",
              duration_s=8, num_videos=1, product_id="uat_prod",
              source_mode="HYBRID")
    kw.update(ov)
    return await make_video.start_generate(**kw)


# --------------------------------------------------------------------------- #
# Single-dispatch matrix at the real boundary
# --------------------------------------------------------------------------- #

async def test_uat_no_approval_blocks_video():
    res = await _dispatch_video("UAT_noapproval a clean video prompt")
    assert res["status"] == "REJECTED"
    assert res["error"] == "DISPATCH_NOT_APPROVED"


async def test_uat_no_approval_blocks_img():
    # IMG is enforced too (credit-free != approval-optional).
    res = await make_video.start_generate(
        mode="IMG", prompt="UAT_noapproval_img clean image prompt",
        aspect="1:1", num_videos=1, image_model="GEM_PIX_2",
    )
    assert res["status"] == "REJECTED"
    assert res["error"] == "DISPATCH_NOT_APPROVED"


async def test_uat_approved_exact_passes():
    prompt = "UAT_exact an approved clean video prompt"
    await _review_video(prompt)
    res = await _dispatch_video(prompt)
    await asyncio.sleep(0)
    assert res["status"] == "SUBMITTED"


async def test_uat_changed_prompt_blocks():
    await _review_video("UAT_cp approved baseline video prompt")
    res = await _dispatch_video("UAT_cp a DIFFERENT prompt never approved")
    assert res["status"] == "REJECTED"
    assert res["error"] == "DISPATCH_NOT_APPROVED"


async def test_uat_changed_setting_blocks():
    prompt = "UAT_cs approved baseline video prompt"
    await _review_video(prompt, aspect="9:16")
    # Same approved prompt, changed provider-affecting setting (aspect).
    res = await _dispatch_video(prompt, aspect="16:9")
    assert res["status"] == "REJECTED"


async def test_uat_stale_invalidated_blocks():
    prompt = "UAT_stale approved then invalidated video prompt"
    approved = await _review_video(prompt)
    await eas.invalidate_snapshot(approved["snapshot_id"], reason="asset changed")
    res = await _dispatch_video(prompt)
    assert res["status"] == "REJECTED"


# --------------------------------------------------------------------------- #
# Approved Generation Manifest — HTTP lifecycle + real dispatch resolution
# --------------------------------------------------------------------------- #

def test_uat_manifest_unapproved_blocks_then_approved_passes():
    client = _client()
    prompt = "UAT_manifest a clean scene video prompt"
    manifest = client.post("/api/execution-approval/manifest", json={
        "surface": "uat_run", "run_ref": "uat_manifest_run", "product_id": "uat_prod",
        "items": [dict(item_key="scene1", mode="F2V", final_prompt_text=prompt,
                       product_id="uat_prod", model="Veo 3.1 Lite", aspect="9:16",
                       duration_s=8, count=1)],
    }).json()
    mid = manifest["manifest_id"]

    async def _fire():
        # Mirrors a montage scene dispatch: source_mode is None (the manifest item
        # is derived with the same None), so the envelope hashes match.
        return await make_video.start_generate(
            mode="F2V", prompt=prompt, image_media_ids=[_ASSET], aspect="9:16",
            model="Veo 3.1 Lite", duration_s=8, num_videos=1, product_id="uat_prod",
            manifest_id=mid,
        )

    # Manifest created but NOT approved -> dispatch by manifest_id BLOCKS.
    eas._DISPATCH_AUTH.set(None)
    blocked = asyncio.get_event_loop().run_until_complete(_fire())
    assert blocked["status"] == "REJECTED"
    assert blocked["error"] == "DISPATCH_NOT_APPROVED"

    # Human approves the manifest over HTTP -> the exact item resolves by hash.
    assert client.post(
        f"/api/execution-approval/manifest/{mid}/approve", json={"approved_by": "uat"}
    ).status_code == 200
    ok = asyncio.get_event_loop().run_until_complete(_fire())
    assert ok["status"] == "SUBMITTED"


# --------------------------------------------------------------------------- #
# Provider-boundary backstop — the net if a lane ever forgot the gate
# --------------------------------------------------------------------------- #

async def test_uat_provider_backstop_refuses_unauthorized_video():
    eas._DISPATCH_AUTH.set(None)  # unauthorised context
    client = FlowClient()
    client._extension_ws = None
    client._mock_connected = True
    res = await client._send("api_request", {
        "url": "https://labs.google/fx/api/video:batchAsyncGenerateVideo",
        "method": "POST", "headers": {}, "body": {},
        "captchaAction": "VIDEO_GENERATION",
    })
    assert res.get("error") == "PROVIDER_DISPATCH_UNAUTHORIZED"
