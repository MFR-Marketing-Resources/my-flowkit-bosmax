import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.api import flow
from agent.services import product_visual_custody_service as custody


PRODUCT_ID = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"


def _run(coro):
    return asyncio.run(coro)


def _product():
    return {
        "id": PRODUCT_ID,
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
        "raw_product_title": "Minyak Warisan Cap Burung 25ml",
    }


def _official_asset():
    path = Path(__file__)
    return {
        "productId": PRODUCT_ID,
        "assetSource": "PRODUCT_VISUAL_OFFICIAL_CUTOUT",
        "officialVisual": True,
        "officialVisualSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "localFilePath": str(path),
        "mediaId": "old-opaque-flow-id",
    }


def test_exact_hybrid_gate_blocks_before_flow_client_or_credits(monkeypatch):
    async def fake_copy_resolution(*_args, **_kwargs):
        return SimpleNamespace(v2_enabled=False)

    async def fake_product(_product_id):
        return _product()

    async def fake_gate(**_kwargs):
        return _official_asset(), {}, True

    monkeypatch.setattr(
        "agent.services.copy_execution_resolver.resolve_persisted_copy_execution_binding",
        fake_copy_resolution,
    )
    monkeypatch.setattr(flow.crud, "get_product", fake_product)
    monkeypatch.setattr(flow, "_provider_safety_stale_prompt_error", lambda *_args: _none())
    monkeypatch.setattr(flow, "_apply_video_product_visual_gate", fake_gate)
    monkeypatch.setattr(
        custody,
        "_truth_lock_snapshot",
        lambda _product_id: {
            "status": "PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE",
            "review_status": "APPROVED",
            "lock_present": True,
            "lock_valid": True,
            "schema_version": "PRODUCT_TRUTH_LOCK_V1",
            "canonical_sha256": "b" * 64,
            "canonical_cutout_sha256": "a" * 64,
            "failure_state": "",
        },
    )

    def should_not_open_provider():
        raise AssertionError("provider client must not be opened before exact route gate")

    monkeypatch.setattr(flow, "get_flow_client", should_not_open_provider)

    with pytest.raises(HTTPException) as exc:
        _run(
            flow.generate(
                flow.GenerateRequest(
                    mode="F2V",
                    prompt="MWCB product video",
                    product_id=PRODUCT_ID,
                    source_mode="HYBRID",
                    model="Veo 3.1 - Lite",
                    duration_s=8,
                )
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == custody.ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN


def test_official_existing_media_id_is_not_accepted_as_byte_custody(monkeypatch):
    calls = {"get_media": 0, "upload": 0}
    path = Path(__file__)

    class Client:
        async def get_media(self, _media_id):
            calls["get_media"] += 1
            return {"status": 200}

        async def upload_image(self, *_args, **_kwargs):
            calls["upload"] += 1
            return {"_mediaId": "fresh-official-upload"}

    media_id = _run(
        flow._resolve_asset_to_media_id(
            Client(),
            {
                "mediaId": "old-opaque-flow-id",
                "officialVisual": True,
                "assetSource": "PRODUCT_VISUAL_OFFICIAL_CUTOUT",
                "localFilePath": str(path),
            },
            "Start",
        )
    )

    assert media_id == "fresh-official-upload"
    assert calls == {"get_media": 0, "upload": 1}


async def _none():
    return None
