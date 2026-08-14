"""Phase 4: deterministic, zero-credit activation proof for Copy Architecture V2.

This file is intentionally test-only.  The fixture is synthetic and immutable;
no provider, browser generation door, or production database is reachable from
these tests.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from agent.authority.copy_lane_matrix import (
    ALL_COPY_LANES,
    IMAGE_LANES,
    LANE_MATRIX,
    VIDEO_LANES,
    get_lane_descriptor,
)
from agent.models.copy_blueprint_v2 import (
    ImageCopyProjection,
    ProductTruthLineage,
    VideoCopyProjection,
)
from agent.services.copy_blueprint_v2_service import approve_copy_blueprint_v2
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_copy_execution_binding,
)
from tests.unit.test_copy_blueprint_v2_contract import (
    _blueprint,
    _flags,
    _lineage,
    _registry,
)


PRODUCT_ID = "product-1"
FIXTURE_BOUND_AT = "2026-08-14T04:00:00Z"
FIXTURE_COMPILER_VERSION = "phase4-copy-execution-binding-v2"
REQUIRED_LANES = set(VIDEO_LANES) | {"POSTER_BUILDER"}
COPY_FREE_LANES = set(IMAGE_LANES) - {"POSTER_BUILDER"}


@pytest.fixture(scope="module")
def phase4_context() -> dict:
    """One deterministic approved envelope shared by every lane proof."""

    approved = approve_copy_blueprint_v2(
        _blueprint(
            blueprint_id="bp-phase4-synthetic-001",
            copy_set_id="v2-phase4-synthetic-copy-set",
        ),
        approved_by="phase4-synthetic-reviewer",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        approved_at=FIXTURE_BOUND_AT,
    )
    flags = _flags().model_copy(
        update={
            "scope": "phase4-synthetic",
            "pilot_scope": ("phase4-synthetic",),
            "state": "PILOT",
        }
    )
    return {
        "current_product_truth": _lineage().model_dump(mode="json"),
        "evidence_facts": [
            fact.model_dump(mode="json") for fact in _registry().facts
        ],
        "feature_flags": flags.model_dump(mode="json"),
        "blueprint": approved.model_dump(mode="json"),
        "readiness_validated": True,
        "provenance_validated": True,
        "safety_validated": True,
        "semantic_review_validated": True,
        "compiler_binding_version": FIXTURE_COMPILER_VERSION,
        "bound_at": FIXTURE_BOUND_AT,
    }


def _context_for_lane(base: dict, lane: str) -> dict:
    context = copy.deepcopy(base)
    if lane in COPY_FREE_LANES:
        context.pop("blueprint", None)
    return context


def _approved_dialogue(context: dict) -> str:
    stages = context["blueprint"]["stages"]
    return " ".join(stage["authored_text"] for stage in stages)


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_matrix_declares_all_lanes_and_current_seams(lane):
    descriptor = get_lane_descriptor(lane)
    assert descriptor is LANE_MATRIX[lane]
    assert descriptor.lane_id == lane
    assert descriptor.adapter in {"VideoCopyProjection", "ImageCopyProjection"}
    assert descriptor.current_api_entry_point
    assert descriptor.current_service_entry_point
    assert descriptor.current_page_entry_point
    if lane in VIDEO_LANES:
        assert descriptor.media_kind == "VIDEO"
        assert descriptor.copy_policy == "REQUIRED"
        assert descriptor.adapter == "VideoCopyProjection"
    else:
        assert descriptor.media_kind == "IMAGE"
        assert descriptor.adapter == "ImageCopyProjection"
        assert descriptor.copy_policy == (
            "REQUIRED" if lane == "POSTER_BUILDER" else "NOT_REQUIRED"
        )


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_positive_path_propagates_one_immutable_identity(lane, phase4_context):
    context = _context_for_lane(phase4_context, lane)
    before = copy.deepcopy(context)
    result = resolve_copy_execution_binding(PRODUCT_ID, lane, context)

    assert result.v2_enabled is True
    assert result.status == "READY"
    assert result.copy_policy == LANE_MATRIX[lane].copy_policy
    assert result.metadata["policy_source"] == "copy_architecture_v2"
    assert context == before

    if lane in REQUIRED_LANES:
        assert isinstance(result.projection, (VideoCopyProjection, ImageCopyProjection))
        assert isinstance(result.projection, VideoCopyProjection) == (lane in VIDEO_LANES)
        assert isinstance(result.projection, ImageCopyProjection) == (lane == "POSTER_BUILDER")
        assert result.binding is not None
        binding = result.binding
        blueprint = context["blueprint"]
        assert binding.blueprint_id == blueprint["blueprint_id"]
        assert binding.revision == blueprint["revision"]
        assert binding.formula_id == blueprint["formula_id"] == "PAS"
        assert binding.formula_version == blueprint["formula_version"]
        assert binding.approval_snapshot_id == blueprint["approval_snapshot"]["approval_snapshot_id"]
        assert binding.product_truth_lineage.snapshot_id == "pi-snapshot-1"
        assert binding.evidence_lineage.fact_ids == ("fact-benefit-001",)
        assert binding.evidence_lineage.references[0].fact_id == "fact-benefit-001"
        assert binding.evidence_lineage.references[0].text_digest
        assert binding.evidence_lineage.references[0].fact_kind == "benefit"
        assert binding.compiler_binding_version == FIXTURE_COMPILER_VERSION
        assert binding.feature_flag_state.state == "PILOT"
        assert result.approved_dialogue == _approved_dialogue(context)
        assert result.metadata["approved_copy_immutable"] is True
        assert result.metadata["compiler_mutation_allowed"] is False
        assert result.compiler_copy_intelligence["blueprint_id"] == binding.blueprint_id
        assert result.compiler_copy_intelligence["revision"] == binding.revision
        assert result.compiler_copy_intelligence["formula_version"] == binding.formula_version
    else:
        assert isinstance(result.projection, ImageCopyProjection)
        assert result.projection.copy_required is False
        assert result.projection.binding is None
        assert result.metadata["copy_free_explicit"] is True
        assert result.metadata["readiness_validated"] is True
        assert result.metadata["provenance_validated"] is True
        assert result.metadata["safety_validated"] is True


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_missing_binding_is_explicit_for_every_lane(lane, phase4_context):
    context = copy.deepcopy(phase4_context)
    context.pop("blueprint", None)
    if lane in REQUIRED_LANES:
        with pytest.raises(CopyExecutionResolutionError) as exc:
            resolve_copy_execution_binding(PRODUCT_ID, lane, context)
        assert exc.value.code == "COPY_V2_BLUEPRINT_REQUIRED"
        assert exc.value.code != "LEGACY_FALLBACK"
    else:
        result = resolve_copy_execution_binding(PRODUCT_ID, lane, context)
        assert result.status == "READY"
        assert result.copy_policy == "NOT_REQUIRED"
        assert result.metadata["copy_free_explicit"] is True


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_stale_product_truth_blocks_every_lane(lane, phase4_context):
    context = _context_for_lane(phase4_context, lane)
    stale = _lineage(snapshot_id="phase4-stale-snapshot").model_copy(
        update={"snapshot_version": 99, "snapshot_status": "REJECTED"}
    )
    context["current_product_truth"] = stale.model_dump(mode="json")
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding(PRODUCT_ID, lane, context)
    assert exc.value.code == "COPY_V2_PRODUCT_TRUTH_STALE"


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_malformed_evidence_blocks_every_lane(lane, phase4_context):
    context = _context_for_lane(phase4_context, lane)
    context["evidence_facts"] = [{"fact_id": "missing-required-fields"}]
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding(PRODUCT_ID, lane, context)
    assert exc.value.code == "COPY_V2_EVIDENCE_INVALID"


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_semantic_review_policy_is_explicit_for_every_lane(lane, phase4_context):
    context = _context_for_lane(phase4_context, lane)
    context.pop("semantic_review_validated", None)
    if lane in REQUIRED_LANES:
        with pytest.raises(CopyExecutionResolutionError) as exc:
            resolve_copy_execution_binding(PRODUCT_ID, lane, context)
        assert exc.value.code == "COPY_V2_SEMANTIC_REVIEW_REQUIRED"
    else:
        result = resolve_copy_execution_binding(PRODUCT_ID, lane, context)
        assert result.status == "READY"
        assert result.metadata["copy_free_explicit"] is True


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_unknown_formula_or_copy_policy_violation_fails_closed(lane, phase4_context):
    context = _context_for_lane(phase4_context, lane)
    if lane in REQUIRED_LANES:
        context["blueprint"]["formula_id"] = "FORMULA_NOT_REGISTERED"
        with pytest.raises(CopyExecutionResolutionError) as exc:
            resolve_copy_execution_binding(PRODUCT_ID, lane, context)
        assert exc.value.code == "COPY_V2_UNKNOWN_FORMULA"
    else:
        # A copy-free lane must reject an accidental blueprint rather than
        # consuming it or silently falling back to legacy/HSO behavior.
        context = copy.deepcopy(phase4_context)
        context["blueprint"]["formula_id"] = "FORMULA_NOT_REGISTERED"
        with pytest.raises(CopyExecutionResolutionError) as exc:
            resolve_copy_execution_binding(PRODUCT_ID, lane, context)
        assert exc.value.code == "COPY_V2_BINDING_NOT_REQUIRED"
    assert "HSO" not in str(exc.value)


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_phase4_flag_off_is_byte_stable_legacy_compatible(lane, phase4_context):
    context = _context_for_lane(phase4_context, lane)
    context["feature_flags"] = _flags().model_copy(
        update={"enabled": False, "state": "OFF"}
    ).model_dump(mode="json")
    context["blueprint"] = {"not": "validated when the flag is off"}
    result = resolve_copy_execution_binding(PRODUCT_ID, lane, context)
    assert result.status == "LEGACY_COMPATIBLE"
    assert result.v2_enabled is False
    assert result.metadata == {
        "policy_source": "copy_architecture_v2",
        "legacy_fallback": True,
        "legacy_path_unchanged": True,
    }


def test_phase4_poster_routes_are_exact_and_copy_aware():
    from agent.api.poster_compose import router as compose_router
    from agent.api.poster_prompt import router as prompt_router

    compose_paths = {route.path for route in compose_router.routes}
    prompt_paths = {route.path for route in prompt_router.routes}
    assert "/poster/compose" in compose_paths
    assert "/poster/prompt-draft" in prompt_paths
    assert LANE_MATRIX["POSTER_BUILDER"].copy_policy == "REQUIRED"
    assert LANE_MATRIX["POSTER_BUILDER"].adapter == "ImageCopyProjection"


@pytest.mark.asyncio
async def test_phase4_p6_binding_survives_compile_scheduler_queue_and_item(
    monkeypatch, phase4_context
):
    """Synthetic P6 proof: one binding survives every local handoff boundary."""

    import agent.services.creative_production_compile_service as compile_service
    import agent.services.creative_production_scheduler_service as scheduler_service

    context = copy.deepcopy(phase4_context)
    treatment = {
        "treatment_id": "treatment-phase4-001",
        "treatment_sha256": "a" * 64,
        "visual_fingerprint_sha256": "b" * 64,
        "dependency_hashes": [],
        "variation_group": "phase4-group",
        "format": "9:16",
        "generation_mode": "SINGLE",
        "segment_plan": {
            "segment_plan_sha256": "c" * 64,
            "ordered_segment_sha256s": ["d" * 64],
        },
        "shot_grammar": "synthetic-shot-grammar",
    }

    async def fake_treatment(*_args, **_kwargs):
        return copy.deepcopy(treatment)

    monkeypatch.setattr(compile_service, "resolve_item_treatment", fake_treatment)
    captured_compile: dict = {}

    async def fake_t2v_package(**kwargs):
        captured_compile.update(kwargs)
        resolved = resolve_copy_execution_binding(
            PRODUCT_ID,
            "PRODUCTION_STUDIO_P6",
            kwargs["copy_v2_context"],
        )
        return {
            "workspace_generation_package_id": "wgp-phase4-001",
            "prompt_fingerprint": "e" * 64,
            "status": "READY",
            "final_prompt_text": _approved_dialogue(context),
            "resolver_output_json": json.dumps(
                resolved.to_metadata(
                    consumer_context=kwargs["copy_v2_context"]
                )
            ),
            "copy_architecture_v2": resolved.to_metadata(
                consumer_context=kwargs["copy_v2_context"]
            ),
            "copy_execution_binding": resolved.binding.model_dump(mode="json"),
        }

    monkeypatch.setattr(
        compile_service.wgp_service,
        "create_t2v_generation_package",
        fake_t2v_package,
    )
    plan = {
        "plan_id": "plan-phase4-001",
        "product_id": PRODUCT_ID,
        "logical_mode": "T2V",
        "execution_policy_json": json.dumps({"aspect": "9:16"}),
        "pool_snapshot_json": json.dumps({"copy_v2_context": context}),
    }
    item = {
        "item_id": "item-phase4-001",
        "product_id": PRODUCT_ID,
        "creative_dna_sha256": "f" * 64,
    }
    dimensions = {
        "duration_seconds": 8,
        "engine_block_duration_seconds": 8,
        "generation_mode": "SINGLE",
        "model_key": "Veo 3.1 - Lite",
        "segment_count": 1,
    }

    _wgp_id, _fingerprint, compiled_package = await compile_service._compile_video(
        item, plan, dimensions
    )
    assert captured_compile["copy_v2_context"]["lane"] == "PRODUCTION_STUDIO_P6"
    binding = compiled_package["copy_execution_binding"]
    assert binding["blueprint_id"] == context["blueprint"]["blueprint_id"]
    assert binding["revision"] == context["blueprint"]["revision"]
    assert binding["approval_snapshot_id"] == context["blueprint"]["approval_snapshot"]["approval_snapshot_id"]
    assert compiled_package["copy_architecture_v2"]["binding"] == binding

    scheduler_item = {
        **item,
        "media_type": "VIDEO",
        "logical_mode": "T2V",
        "workspace_generation_package_id": "wgp-phase4-001",
        "prompt_package_json": json.dumps(
            {
                **compiled_package,
                "treatment_lineage": compiled_package["treatment_lineage"],
            }
        ),
        "creative_dimensions_json": json.dumps(dimensions),
    }
    monkeypatch.setattr(
        scheduler_service,
        "resolve_item_treatment",
        fake_treatment,
    )

    async def fake_get_wgp(_wgp_id):
        return {
            "workspace_generation_package_id": "wgp-phase4-001",
            "product_id": PRODUCT_ID,
            "logical_mode": "T2V",
            "generation_mode": "SINGLE",
            "final_prompt_text": _approved_dialogue(context),
            "resolver_output_json": json.dumps(compiled_package["copy_architecture_v2"]),
        }

    monkeypatch.setattr(scheduler_service.crud, "get_workspace_generation_package", fake_get_wgp)
    payload, blockers = await scheduler_service._build_item_payload(
        scheduler_item,
        plan,
        aspect="9:16",
    )
    assert blockers == []
    assert payload["copy_execution_binding"] == binding
    assert payload["copy_architecture_v2"]["binding"] == binding
    assert payload["logical_mode"] == "T2V"

    # This is the durable production-item shape: serialization must not lose
    # the same binding before the live queue gate (which is not called here).
    production_item = json.loads(json.dumps(payload))
    assert production_item["copy_execution_binding"] == binding
    assert production_item["copy_architecture_v2"]["binding"] == binding


@pytest.mark.asyncio
async def test_phase4_montage_uses_one_binding_across_all_scenes(
    phase4_context,
):
    from agent.services.montage_scene_orchestrator import orchestrate_montage_scenes
    from agent.services.montage_scene_reference_policy import SceneReferencePolicy

    captured_contexts: list[dict] = []

    async def fake_package_factory(**kwargs):
        captured_contexts.append(copy.deepcopy(kwargs["copy_v2_context"]))
        resolved = resolve_copy_execution_binding(
            PRODUCT_ID,
            "MONTAGE",
            kwargs["copy_v2_context"],
        )
        return {
            "workspace_execution_package_id": "wep-phase4-montage",
            "prompt_text": _approved_dialogue(phase4_context),
            "execution_allowed": True,
            "copy_architecture_v2": resolved.to_metadata(
                consumer_context=kwargs["copy_v2_context"]
            ),
        }

    story_beats = [
        SimpleNamespace(beat_id="scene-a", objective="hook", visual_action="open"),
        SimpleNamespace(beat_id="scene-b", objective="proof", visual_action="show"),
    ]
    report = await orchestrate_montage_scenes(
        product_id=PRODUCT_ID,
        story_beats=story_beats,
        package_factory=fake_package_factory,
        default_policy=SceneReferencePolicy.NONE,
        model="Veo 3.1 - Lite",
        duration_seconds=8,
        copy_v2_context=copy.deepcopy(phase4_context),
    )

    assert report.ok is True
    assert report.credit_spend is False
    assert len(report.scenes) == 2
    assert all(scene.status == "PACKAGE_READY" for scene in report.scenes)
    binding_ids = {
        scene.copy_architecture_v2["binding"]["binding_id"]
        for scene in report.scenes
    }
    assert len(binding_ids) == 1
    assert len(captured_contexts) == 2
    assert all(ctx["lane"] == "MONTAGE" for ctx in captured_contexts)
    assert {ctx["bound_at"] for ctx in captured_contexts} == {FIXTURE_BOUND_AT}
