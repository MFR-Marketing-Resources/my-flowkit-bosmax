import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.api import flow
from agent.api import faceless
from agent.services import product_visual_custody_service as custody
from agent.services import product_visual_grounding_resolver as grounding


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


def test_faceless_exact_product_route_prepares_without_provider_reference(monkeypatch):
    calls = {"package": 0}

    async def fake_product(_product_id):
        return _product()

    async def fake_scene_authority(**_kwargs):
        return {}

    def fake_resolution(**_kwargs):
        return {
            "source_mode": "T2V",
            "transport_mode": "T2V",
            "actor_profile": {},
            "opening_strategy": {},
            "hook": {},
            "background": {},
            "scene_strategy": {},
            "choreography": {},
            "faceless_resolution": {},
            "exact_product_video": {
                "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                "generate_eligibility": True,
                "choreography": {"choreography_id": "PRODUCT_PRESENT_TO_CAMERA"},
            },
        }

    async def create_package(**_kwargs):
        calls["package"] += 1
        return {
            "workspace_execution_package_id": "wep_exact",
            "prompt_text": "SCENE-ONLY PLATE",
            "execution_allowed": True,
            "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
            "generate_eligibility": True,
            "exact_product_video": {
                "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                "generate_eligibility": True,
            },
            "asset_slots": [],
            "resolved_assets": [],
            "product_visual_custody": custody_receipt,
        }

    custody_receipt = {
        "exact_product_required": True,
        "fidelity_policy": custody.EXACT_PRODUCT_REQUIRED,
    }

    monkeypatch.setattr(
        faceless.fl,
        "validate_faceless_inputs",
        lambda **_kwargs: (True, None, None),
    )
    monkeypatch.setattr(
        faceless.fl,
        "resolve_faceless_video_configuration",
        lambda **_kwargs: (
            True,
            None,
            None,
            {"engine_block_duration_seconds": 8, "generation_mode": "SINGLE"},
        ),
    )
    monkeypatch.setattr(faceless.fl, "resolve_faceless_scene_authority", fake_scene_authority)
    monkeypatch.setattr(faceless.fl, "build_faceless_resolution", fake_resolution)
    monkeypatch.setattr(faceless.fl, "build_faceless_scene_context", lambda _resolution: "scene")
    monkeypatch.setattr(faceless.crud, "get_product", fake_product)
    monkeypatch.setattr(custody, "exact_product_required", lambda _product: True)
    monkeypatch.setattr(
        grounding,
        "build_official_product_visual_asset",
        lambda *_args, **_kwargs: {"official_visual": True},
    )
    monkeypatch.setattr(
        custody,
        "build_product_visual_custody_receipt",
        lambda *_args, **_kwargs: custody_receipt,
    )
    monkeypatch.setattr(
        faceless,
        "create_workspace_execution_package",
        create_package,
    )

    response = _run(
        faceless.faceless_prepare(
            faceless.FacelessPrepareRequest(
                product_id=PRODUCT_ID,
                model="Veo 3.1 - Lite",
                duration_seconds=8,
            )
        )
    )

    assert response["selected_execution_route"] == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    assert response["debug"]["transport_mode"] == "T2V"
    assert response["debug"]["provider_product_reference_forbidden"] is True
    assert calls == {"package": 1}


async def _none():
    return None
