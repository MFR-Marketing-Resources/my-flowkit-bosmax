"""Universal eleven-lane adapter matrix tests."""
from __future__ import annotations

import pytest

from agent.authority.copy_lane_matrix import (
    ALL_COPY_LANES,
    IMAGE_LANES,
    LANE_MATRIX,
    VIDEO_LANES,
    producer_consumer_matrix,
)
from agent.models.copy_blueprint_v2 import AdapterContext
from agent.services.copy_blueprint_v2_service import (
    CopyBlueprintV2Error,
    approve_copy_blueprint_v2,
    bind_copy_blueprint_v2,
    project_image_copy,
    project_video_copy,
)
from tests.unit.test_copy_blueprint_v2_contract import _blueprint, _flags, _lineage, _registry


def _approved():
    return approve_copy_blueprint_v2(
        _blueprint(),
        approved_by="operator-1",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        approved_at="2026-08-14T01:00:00Z",
    )


def _context():
    return AdapterContext(
        product_id="product-1",
        product_truth_lineage=_lineage(),
        readiness_validated=True,
        provenance_validated=True,
        safety_validated=True,
    )


def test_matrix_covers_exactly_all_required_lanes_and_current_seams():
    assert len(ALL_COPY_LANES) == 11
    assert set(VIDEO_LANES) | set(IMAGE_LANES) == set(ALL_COPY_LANES)
    assert set(LANE_MATRIX) == set(ALL_COPY_LANES)
    rows = producer_consumer_matrix()
    assert len(rows) == 11
    for row in rows:
        assert row["current_api_entry_point"]
        assert row["current_service_entry_point"]
        assert row["current_page_entry_point"]
        assert row["copy_policy"] in {"REQUIRED", "NOT_REQUIRED"}
        assert row["adapter"] in {"VideoCopyProjection", "ImageCopyProjection"}
    poster = LANE_MATRIX["POSTER_BUILDER"]
    assert "/api/poster/prompt-draft" in poster.current_api_entry_point


@pytest.mark.parametrize("lane", VIDEO_LANES)
def test_all_video_lanes_require_the_same_lineage_complete_adapter(lane):
    blueprint = _approved()
    binding = bind_copy_blueprint_v2(
        blueprint,
        lane=lane,
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        feature_flags=_flags(),
        bound_at="2026-08-14T03:00:00Z",
    )
    projection = project_video_copy(binding, blueprint, context=_context())
    assert projection.lane == lane
    assert projection.copy_policy == "REQUIRED"
    assert projection.binding.approval_snapshot_id == blueprint.approval_snapshot.approval_snapshot_id
    assert projection.derived_copy.source_version == "copy-blueprint-v2"


@pytest.mark.parametrize("lane", ("IMAGE_GEN", "IMG_FASTLANE", "IMG_COCKPIT"))
def test_copy_free_image_lanes_are_explicit_and_still_require_gate_proof(lane):
    projection = project_image_copy(lane, context=_context())
    assert projection.copy_policy == "NOT_REQUIRED"
    assert projection.copy_required is False
    assert projection.binding is None
    assert projection.derived_copy is None

    with pytest.raises(CopyBlueprintV2Error) as missing_gate:
        project_image_copy(
            lane,
            context=_context().model_copy(update={"safety_validated": False}),
        )
    assert missing_gate.value.code == "COPY_V2_GATE_NOT_PROVEN"


def test_poster_builder_is_copy_aware_and_never_uses_video_adapter():
    blueprint = _approved()
    binding = bind_copy_blueprint_v2(
        blueprint,
        lane="POSTER_BUILDER",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        feature_flags=_flags(),
        bound_at="2026-08-14T03:00:00Z",
    )
    projection = project_image_copy(
        "POSTER_BUILDER",
        context=_context(),
        binding=binding,
        blueprint=blueprint,
    )
    assert projection.copy_required is True
    assert projection.copy_policy == "REQUIRED"
    assert projection.derived_copy is not None

    with pytest.raises(CopyBlueprintV2Error) as wrong_adapter:
        project_video_copy(binding, blueprint, context=_context())
    assert wrong_adapter.value.code == "COPY_V2_LANE_POLICY_MISMATCH"


def test_adapter_never_silently_bypasses_readiness_provenance_or_safety():
    blueprint = _approved()
    binding = bind_copy_blueprint_v2(
        blueprint,
        lane="HYBRID",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        feature_flags=_flags(),
    )
    for field in ("readiness_validated", "provenance_validated", "safety_validated"):
        with pytest.raises(CopyBlueprintV2Error) as error:
            project_video_copy(
                binding,
                blueprint,
                context=_context().model_copy(update={field: False}),
            )
        assert error.value.code == "COPY_V2_GATE_NOT_PROVEN"
