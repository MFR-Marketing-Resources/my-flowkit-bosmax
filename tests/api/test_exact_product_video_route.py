import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.api import flow
from agent.services.make_video import _pre_dispatch_generation_type


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
    monkeypatch.setattr(
        "agent.services.staff_identity_service.resolve_staff_identity",
        AsyncMock(
            return_value={
                "staff_id": "staff_test",
                "display_name": "Test Operator",
                "active": True,
            }
        ),
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
                staff_id="staff_test",
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


def test_exact_product_hybrid_routes_to_composite_with_zero_provider_refs(monkeypatch):
    # Owner regression: an exact-product HYBRID (F2V transport, presenter-visible)
    # must run the deterministic composite route — NOT the generative reference
    # route — reusing the SAME compositor as Faceless.  The presenter stays HYBRID
    # (mode F2V, prompt untouched here), no provider product reference is
    # dispatched, and the compositor plan travels on the custody.
    import agent.services.product_visual_custody_service as pvc
    import agent.services.exact_product_video_compositor_service as evc

    calls = {}

    monkeypatch.setattr(
        "agent.services.copy_execution_resolver.resolve_persisted_copy_execution_binding",
        AsyncMock(return_value=SimpleNamespace(v2_enabled=False)),
    )
    monkeypatch.setattr(
        flow, "_provider_safety_stale_prompt_error", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "agent.services.execution_approval_service.verify_and_bind_dispatch",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "agent.services.staff_identity_service.resolve_staff_identity",
        AsyncMock(
            return_value={
                "staff_id": "staff_test",
                "display_name": "Test Operator",
                "active": True,
            }
        ),
    )
    monkeypatch.setattr(
        flow.crud, "get_product", AsyncMock(return_value={"id": "p1", "_exact_product_required": True})
    )
    # HYBRID F2V product-visual gate (official asset resolution) — return no
    # client refs so no reference id is resolved; the exact route clears them too.
    monkeypatch.setattr(
        flow, "_effective_video_source_mode", AsyncMock(return_value="HYBRID")
    )
    monkeypatch.setattr(
        flow,
        "_apply_video_product_visual_gate",
        AsyncMock(return_value=(None, {}, True)),
    )
    # Exact-required product; custody receipt echoes the route the caller chose.
    monkeypatch.setattr(pvc, "exact_product_required", lambda _product: True)

    def fake_receipt(product, official_asset, **kwargs):
        return {
            "product_id": "p1",
            "exact_product_required": True,
            "provider_route": kwargs.get("provider_route"),
            "generation_type": kwargs.get("generation_type"),
            "prompt_lock": {"all_required_markers_present": False},
            "product_fidelity_qc_required": True,
        }

    monkeypatch.setattr(pvc, "build_product_visual_custody_receipt", fake_receipt)
    monkeypatch.setattr(
        evc,
        "build_exact_product_video_plan",
        lambda _product, _choreo: {
            "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
            "generate_eligibility": True,
            "provider_product_reference_forbidden": True,
            "product_truth": {"canonical_cutout_sha256": "b" * 64},
        },
    )

    class Client:
        connected = True

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

    monkeypatch.setattr(flow, "get_flow_client", lambda: Client())

    async def fake_start_generate(mode, prompt, **kwargs):
        calls.update({"mode": mode, "prompt": prompt, **kwargs})
        return {"job_id": "g_hybrid_exact", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr("agent.services.make_video.start_generate", fake_start_generate)

    result = _run(
        flow.generate(
            flow.GenerateRequest(
                mode="F2V",
                prompt="Presenter to camera; reserved product box empty. SCENE-ONLY PLATE.",
                product_id="p1",
                staff_id="staff_test",
                source_mode="HYBRID",
                surface_lane="HYBRID",
                model="Veo 3.1 - Lite",
                duration_s=8,
                image_media_ids=[],
            )
        )
    )

    assert result["job_id"] == "g_hybrid_exact"
    # HYBRID stays HYBRID transport (F2V), never downgraded to Faceless/T2V here.
    assert calls["mode"] == "F2V"
    custody = calls["product_visual_custody"]
    # Composite route — the generative reference route is forbidden for exact.
    assert custody["provider_route"] == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    assert custody["provider_product_reference_forbidden"] is True
    # Final product custody preserved: the compositor plan travels with the job.
    assert custody["exact_product_video"]["selected_execution_route"] == (
        "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    )
    # No provider product reference is dispatched.
    assert calls["image_media_ids"] == []


def test_exact_product_route_uses_scaffold_generation_type_from_custody():
    custody = {
        "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
        "generation_type": "scene_video_scaffold_then_deterministic_composite",
    }
    declined_t2v_plan = {
        "eligible": False,
        "reason": "EXACT_PRODUCT_SCENE_SCAFFOLD_AGENT_T2V",
    }

    assert _pre_dispatch_generation_type(custody, declined_t2v_plan) == (
        "scene_video_scaffold_then_deterministic_composite"
    )


def test_reference_route_keeps_direct_plan_generation_type():
    custody = {"provider_route": "API_FIRST_GENERATIVE_REFERENCE"}
    direct_plan = {"gen_type": "reference_frame_2_video"}

    assert _pre_dispatch_generation_type(custody, direct_plan) == (
        "reference_frame_2_video"
    )
