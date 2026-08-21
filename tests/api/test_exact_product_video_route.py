import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.api import flow


def _run(coro):
    return asyncio.run(coro)


def test_exact_faceless_package_dispatches_t2v_with_zero_provider_refs(monkeypatch):
    identity = {
        "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
        "lane": "FACELESS",
        "transport_mode": "T2V",
        "source_mode": "T2V",
        "product_id": "p1",
    }
    custody = {
        "product_id": "p1",
        "exact_product_required": True,
        "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
        "generation_type": "scene_video_scaffold_then_deterministic_composite",
        "product_fidelity_qc_required": True,
    }
    package = {
        "request_lineage_payload": json.dumps(
            {
                "product_id": "p1",
                "faceless_execution_identity": identity,
                "faceless_resolution": {
                    "exact_product_video": {
                        "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                        "generate_eligibility": True,
                    }
                },
                "product_visual_custody": custody,
            }
        )
    }
    calls = {}

    monkeypatch.setattr(
        flow.crud,
        "get_workspace_execution_package",
        AsyncMock(return_value=package),
    )
    monkeypatch.setattr(
        "agent.services.copy_execution_resolver.resolve_persisted_copy_execution_binding",
        AsyncMock(return_value=SimpleNamespace(v2_enabled=False)),
    )
    monkeypatch.setattr(
        flow,
        "_provider_safety_stale_prompt_error",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "agent.services.execution_approval_service.verify_and_bind_dispatch",
        AsyncMock(return_value=None),
    )

    class Client:
        connected = True

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

    monkeypatch.setattr(flow, "get_flow_client", lambda: Client())

    async def fake_start_generate(mode, prompt, **kwargs):
        calls.update({"mode": mode, "prompt": prompt, **kwargs})
        return {"job_id": "g_exact", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr("agent.services.make_video.start_generate", fake_start_generate)

    result = _run(
        flow.generate(
            flow.GenerateRequest(
                mode="T2V",
                prompt="SCENE-ONLY PLATE",
                product_id="p1",
                source_mode="T2V",
                model="Veo 3.1 - Lite",
                duration_s=8,
                image_media_ids=[],
                workspace_execution_package_id="wep_exact",
                execution_identity=identity,
            )
        )
    )

    assert result["job_id"] == "g_exact"
    assert calls["mode"] == "T2V"
    assert calls["source_mode"] == "T2V"
    assert calls["image_media_ids"] == []
    assert calls["product_visual_custody"]["provider_route"] == (
        "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    )
