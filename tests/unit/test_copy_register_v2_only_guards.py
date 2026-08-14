"""Production-only guard proof for the formula-native Copy Register cutover."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.api.copy_architecture_v2 import get_copy_architecture_v2_consumer_status
from agent.api.legacy_copy_guard import require_legacy_copy_maintenance
from agent.models.copy_blueprint_v2 import CopyBlueprintV2FeatureFlagState
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_copy_execution_binding,
)
from agent.services.copy_binding_service import CopyBindingError
from agent.services import copy_rotation_service
from agent.services import workspace_execution_package_service as workspace_execution
from agent.services import workspace_generation_package_service as workspace_generation
from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services.poster_prompt_draft_service import (
    PosterPromptDraftService,
    PosterPromptDraftValidationError,
)


def _production_environment(monkeypatch) -> None:
    monkeypatch.delenv("COPY_LEGACY_MAINTENANCE_MODE", raising=False)
    # Historical flag values cannot switch normal production back to legacy.
    monkeypatch.setenv("COPY_BLUEPRINT_V2_ENABLED", "0")
    monkeypatch.setenv("COPY_BLUEPRINT_V2_SHADOW_MODE", "1")


def test_normal_runtime_forces_global_v2_on(monkeypatch):
    _production_environment(monkeypatch)
    flags = CopyBlueprintV2FeatureFlagState.from_environment()
    assert flags.enabled is True
    assert flags.shadow_mode is False
    assert flags.scope == "global"
    assert flags.state == "ON"


@pytest.mark.asyncio
async def test_normal_runtime_reports_v2_only_and_no_legacy_storage(monkeypatch):
    _production_environment(monkeypatch)
    status = await get_copy_architecture_v2_consumer_status()
    assert status["v2_only"] is True
    assert status["legacy_storage_enabled"] is False
    assert status["legacy_path_unchanged"] is False


def test_caller_cannot_force_flag_off_or_legacy_fallback(monkeypatch):
    _production_environment(monkeypatch)
    with pytest.raises(CopyExecutionResolutionError) as blocked:
        resolve_copy_execution_binding(
            "product-1",
            "T2V",
            {
                "feature_flags": {
                    "enabled": False,
                    "shadow_mode": False,
                    "scope": "",
                    "pilot_scope": [],
                    "state": "OFF",
                }
            },
        )
    assert blocked.value.code == "COPY_V2_ONLY_REQUIRED"


def test_legacy_routes_return_permanent_explicit_cutover_error(monkeypatch):
    _production_environment(monkeypatch)
    with pytest.raises(HTTPException) as blocked:
        require_legacy_copy_maintenance()
    assert blocked.value.status_code == 410
    assert blocked.value.detail["error"] == "LEGACY_COPY_STORAGE_DISABLED"
    assert "/api/copy-register/v2" in blocked.value.detail["detail"]


def _persisted_resolution(*, lane: str = "T2V", dialogue: str = "Hook. Body. CTA."):
    binding = SimpleNamespace(
        binding_id="bind-v2-only",
        blueprint_id="blueprint-v2-only",
        revision=4,
        formula_id="PAS",
        formula_version="1.0.0",
        approval_snapshot_id="approval-v2-only",
        bound_at="2026-08-14T00:00:00Z",
    )
    return SimpleNamespace(
        lane=lane,
        copy_policy="REQUIRED",
        binding=binding,
        approved_dialogue=dialogue,
        projection=SimpleNamespace(
            derived_copy=SimpleNamespace(hook="Hook.")
        ),
        v2_enabled=True,
    )


@pytest.mark.asyncio
async def test_normal_quantity_paths_use_one_v2_binding_and_never_rotate_copysets(
    monkeypatch,
):
    _production_environment(monkeypatch)
    resolution = _persisted_resolution()
    compile_calls: list[dict] = []

    async def resolve_v2(*_args, **_kwargs):
        return resolution

    async def compile_v2(**kwargs):
        compile_calls.append(kwargs)
        return {
            "planner_result": {
                "full_dialogue_plan": {"full_dialogue_text": resolution.approved_dialogue}
            },
            "prompt_blocks": [
                {"exact_dialogue_slice": resolution.approved_dialogue}
            ],
        }

    async def forbidden_rotation(*_args, **_kwargs):
        raise AssertionError("normal V2 runtime reached legacy CopySet rotation")

    monkeypatch.setattr(workspace_generation, "_resolve_v2_package_context", resolve_v2)
    monkeypatch.setattr(
        workspace_execution, "compile_workspace_prompt_preview", compile_v2
    )
    monkeypatch.setattr(
        copy_rotation_service, "list_eligible_copy_sets", forbidden_rotation
    )
    monkeypatch.setattr(
        copy_rotation_service, "select_rotation_copy_sets", forbidden_rotation
    )

    readiness = await workspace_generation.evaluate_copy_pool_readiness(
        product_id="product-v2-only",
        logical_mode="T2V",
        quantity=2,
    )
    preview = await workspace_generation.preview_quantity_copy_plans(
        product_id="product-v2-only",
        logical_mode="T2V",
        quantity=2,
    )

    assert readiness["copy_authority"] == "COPY_BLUEPRINT_V2"
    assert readiness["binding_id"] == resolution.binding.binding_id
    assert readiness["shortage_count"] == 1
    assert readiness["next_action"] == "V2_MULTI_BLUEPRINT_ROTATION_REQUIRED"
    assert preview["copy_source"] == "COPY_BLUEPRINT_V2"
    assert preview["preview_ready"] is False
    assert preview["binding_id"] == resolution.binding.binding_id
    assert {item["copy_variant_id"] for item in preview["items"]} == {
        resolution.binding.binding_id
    }
    assert any(
        blocker.startswith("V2_MULTI_BLUEPRINT_ROTATION_REQUIRED")
        for blocker in preview["blockers"]
    )
    assert len(compile_calls) == 2
    assert all(call["copy_set_id"] is None for call in compile_calls)
    assert all(call["copy_v2_context"]["lane"] == "T2V" for call in compile_calls)


@pytest.mark.asyncio
async def test_v2_batch_prompt_rejects_unapproved_hook_before_creating_run(monkeypatch):
    _production_environment(monkeypatch)
    resolution = _persisted_resolution()

    async def get_product(_product_id):
        return {
            "id": "product-v2-only",
            "product_display_name": "V2 Product",
            "image_url": "https://example.invalid/product.png",
        }

    async def eligible(_product_id):
        return {"eligible": True, "reasons": []}

    async def resolve_v2(*_args, **_kwargs):
        return resolution

    async def forbidden_create(*_args, **_kwargs):
        raise AssertionError("batch run was created before V2 copy validation")

    monkeypatch.setattr(workspace_generation.crud, "get_product", get_product)
    monkeypatch.setattr(
        "agent.services.copy_eligibility_service.assert_copy_eligible", eligible
    )
    monkeypatch.setattr(workspace_generation, "_resolve_v2_package_context", resolve_v2)
    monkeypatch.setattr(
        workspace_generation.crud, "create_batch_generation_run", forbidden_create
    )

    with pytest.raises(CopyBindingError) as blocked:
        await workspace_generation.start_batch_prompt_run(
            product_id="product-v2-only",
            logical_mode="T2V",
            quantity=1,
            interval_seconds=0,
            duration_seconds=8,
            avatar_codes=["BOS_A"],
            hook_angles=["unapproved caller wording"],
        )
    assert blocked.value.code == "COPY_V2_UNAPPROVED_TEXT_INPUT"


@pytest.mark.asyncio
async def test_batch_generation_preflights_every_v2_binding_before_run_write(monkeypatch):
    _production_environment(monkeypatch)
    resolved_lanes: list[tuple[str, str]] = []

    async def eligible(product_id):
        return {"product_id": product_id, "eligible": True, "reasons": []}

    async def resolve_v2(product_id, *, mode, **_kwargs):
        resolved_lanes.append((product_id, mode))
        if product_id == "product-b" and mode == "HYBRID":
            raise CopyBindingError("COPY_V2_BLUEPRINT_REQUIRED", status_code=409)
        return _persisted_resolution(lane=mode)

    async def forbidden_create(*_args, **_kwargs):
        raise AssertionError("batch run was written before all V2 bindings passed")

    monkeypatch.setattr(
        "agent.services.copy_eligibility_service.copy_eligibility", eligible
    )
    monkeypatch.setattr(workspace_generation, "_resolve_v2_package_context", resolve_v2)
    monkeypatch.setattr(
        workspace_generation.crud, "create_batch_generation_run", forbidden_create
    )

    with pytest.raises(CopyBindingError) as blocked:
        await workspace_generation.start_batch_generation(
            product_id="product-a",
            product_ids=["product-a", "product-b"],
            modes=["T2V", "HYBRID"],
            quantity_per_mode=1,
            interval_seconds=0,
        )
    assert blocked.value.code == "COPY_V2_BLUEPRINT_REQUIRED"
    assert resolved_lanes == [
        ("product-a", "T2V"),
        ("product-a", "HYBRID"),
        ("product-b", "T2V"),
        ("product-b", "HYBRID"),
    ]


@pytest.mark.asyncio
async def test_poster_service_rejects_legacy_identifier_before_database_read(monkeypatch):
    _production_environment(monkeypatch)

    async def forbidden_read(*_args, **_kwargs):
        raise AssertionError("legacy poster identifier reached a database read")

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        forbidden_read,
    )
    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_poster_copy_set",
        forbidden_read,
    )

    with pytest.raises(PosterPromptDraftValidationError, match="LEGACY_COPY_STORAGE_DISABLED"):
        await PosterPromptDraftService.build_draft(
            PosterPromptDraftRequest(
                product_id="product-v2-only",
                poster_copy_set_id="legacy-poster-copy",
            )
        )
