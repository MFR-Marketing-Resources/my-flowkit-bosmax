"""Phase 3 universal consumer-boundary tests (synthetic, no DB/provider)."""
from __future__ import annotations

import pytest

from agent.authority.copy_lane_matrix import ALL_COPY_LANES, IMAGE_LANES, VIDEO_LANES
from agent.models.copy_blueprint_v2 import ProductTruthLineage
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    copy_v2_handoff_context,
    resolve_copy_execution_binding,
)
from agent.services.copy_blueprint_v2_service import approve_copy_blueprint_v2
from tests.unit.test_copy_blueprint_v2_contract import (
    _blueprint,
    _flags,
    _lineage,
    _registry,
)

REQUIRED_LANES = tuple(VIDEO_LANES) + ("POSTER_BUILDER",)


def _approved():
    return approve_copy_blueprint_v2(
        _blueprint(),
        approved_by="phase3-test-operator",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        approved_at="2026-08-14T04:00:00Z",
    )


def _context(*, include_blueprint: bool = True, **gates):
    context = {
        "current_product_truth": _lineage().model_dump(mode="json"),
        "evidence_facts": [fact.model_dump(mode="json") for fact in _registry().facts],
        "feature_flags": _flags().model_dump(mode="json"),
        "readiness_validated": gates.get("readiness_validated", True),
        "provenance_validated": gates.get("provenance_validated", True),
        "safety_validated": gates.get("safety_validated", True),
        "semantic_review_validated": gates.get("semantic_review_validated", True),
    }
    if include_blueprint:
        context["blueprint"] = _approved().model_dump(mode="json")
    return context


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_every_lane_resolves_through_one_boundary(lane):
    context = _context(include_blueprint=lane in set(VIDEO_LANES) | {"POSTER_BUILDER"})
    result = resolve_copy_execution_binding("product-1", lane, context)
    assert result.v2_enabled is True
    assert result.status == "READY"
    assert result.copy_policy == (
        "REQUIRED" if lane in set(VIDEO_LANES) | {"POSTER_BUILDER"} else "NOT_REQUIRED"
    )
    if lane in set(IMAGE_LANES) - {"POSTER_BUILDER"}:
        assert result.binding is None
        assert result.projection.copy_required is False
    else:
        assert result.binding is not None
        assert result.binding.lane == lane


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_required_binding_preserves_approval_and_evidence_lineage(lane):
    blueprint = _approved()
    result = resolve_copy_execution_binding("product-1", lane, _context())
    assert result.binding is not None
    assert result.binding.blueprint_id == blueprint.blueprint_id
    assert result.binding.revision == blueprint.revision
    assert result.binding.formula_id == blueprint.formula_id
    assert result.binding.formula_version == blueprint.formula_version
    assert result.binding.approval_snapshot_id == blueprint.approval_snapshot.approval_snapshot_id
    assert result.binding.product_truth_lineage == blueprint.product_truth_lineage
    assert result.binding.evidence_lineage.fact_ids == tuple(
        ref.fact_id for ref in blueprint.evidence_refs
    )


@pytest.mark.parametrize("lane", ALL_COPY_LANES)
def test_flag_off_is_legacy_compatible_and_does_not_validate_v2_input(lane):
    result = resolve_copy_execution_binding(
        "product-1",
        lane,
        {"blueprint": {"not": "a V2 blueprint"}},
    )
    assert result.status == "LEGACY_COMPATIBLE"
    assert result.v2_enabled is False
    assert result.metadata["legacy_path_unchanged"] is True


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_missing_blueprint_fails_closed_when_required_lane_is_on(lane):
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding("product-1", lane, _context(include_blueprint=False))
    assert exc.value.code == "COPY_V2_BLUEPRINT_REQUIRED"


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_missing_semantic_review_fails_closed_when_required_lane_is_on(lane):
    context = _context()
    context.pop("semantic_review_validated")
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding("product-1", lane, context)
    assert exc.value.code == "COPY_V2_SEMANTIC_REVIEW_REQUIRED"


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_failed_semantic_review_fails_closed_when_required_lane_is_on(lane):
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding(
            "product-1", lane, _context(semantic_review_validated=False)
        )
    assert exc.value.code == "COPY_V2_SEMANTIC_REVIEW_REQUIRED"


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_stale_product_truth_lineage_fails_closed(lane):
    stale = ProductTruthLineage(
        product_id="product-1",
        snapshot_id="truth-snapshot-stale",
        snapshot_version=99,
        snapshot_digest="a" * 64,
        snapshot_status="APPROVED",
    )
    context = _context()
    context["current_product_truth"] = stale.model_dump(mode="json")
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding("product-1", lane, context)
    assert exc.value.code == "COPY_V2_EVIDENCE_STALE"


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_invalid_evidence_fails_closed(lane):
    context = _context()
    context["evidence_facts"] = []
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding("product-1", lane, context)
    assert exc.value.code in {"COPY_V2_EVIDENCE_NOT_FOUND", "COPY_V2_EVIDENCE_MISSING"}


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_unknown_formula_fails_closed_without_hso_or_legacy_fallback(lane):
    context = _context()
    blueprint = _approved().model_copy(update={"formula_id": "UNKNOWN_FORMULA"})
    context["blueprint"] = blueprint.model_dump(mode="json")
    with pytest.raises(CopyExecutionResolutionError) as exc:
        resolve_copy_execution_binding("product-1", lane, context)
    assert exc.value.code == "COPY_V2_UNKNOWN_FORMULA"


@pytest.mark.parametrize("lane", ("IMAGE_GEN", "IMG_FASTLANE", "IMG_COCKPIT"))
def test_copy_free_lanes_refuse_accidental_blueprint_and_require_all_gates(lane):
    with pytest.raises(CopyExecutionResolutionError) as accidental:
        resolve_copy_execution_binding("product-1", lane, _context())
    assert accidental.value.code == "COPY_V2_BINDING_NOT_REQUIRED"

    with pytest.raises(CopyExecutionResolutionError) as missing_gate:
        resolve_copy_execution_binding(
            "product-1",
            lane,
            _context(include_blueprint=False, safety_validated=False),
        )
    assert missing_gate.value.code == "COPY_V2_GATE_NOT_PROVEN"


def test_approved_dialogue_is_ordered_and_exposed_as_immutable_execution_input():
    result = resolve_copy_execution_binding("product-1", "T2V", _context())
    expected = " ".join(item.text for item in _approved().approved_execution_text)
    assert result.approved_dialogue == expected
    assert result.metadata["approved_copy_immutable"] is True
    assert result.metadata["compiler_mutation_allowed"] is False


def test_durable_handoff_preserves_the_same_binding_identity_and_context():
    result = resolve_copy_execution_binding("product-1", "T2V", _context())
    handoff = copy_v2_handoff_context(_context(), result)
    assert handoff["lane"] == "T2V"
    assert handoff["bound_at"] == result.binding.bound_at
    metadata = result.to_metadata(consumer_context=handoff)
    assert metadata["consumer_context"]["bound_at"] == result.binding.bound_at
    assert metadata["binding"]["binding_id"] == result.binding.binding_id
