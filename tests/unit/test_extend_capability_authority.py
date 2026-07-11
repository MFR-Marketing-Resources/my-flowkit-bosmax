"""Native-extend CAPABILITY authority — an axis SEPARATE from route authority."""
import pytest

from agent.services import extend_route_planner as R


def test_five_runtime_capabilities_authorized():
    for cap in [
        "GOOGLE_FLOW_NATIVE_EXTEND_REQUEST",
        "GOOGLE_FLOW_EXTEND_CHILD_POLLING",
        "GOOGLE_FLOW_EXTEND_LINEAGE",
        "GOOGLE_FLOW_PER_BLOCK_MEDIA_RETRIEVAL",
        "GOOGLE_FLOW_DOWNLOAD_PROJECT_ZIP",
    ]:
        assert R.capability_authority(cap) == R.AUTHORIZED
        assert R.require_capability(cap)["authority"] == R.AUTHORIZED


def test_final_concat_export_authorized_by_captured_terminal_contract():
    # CAPTURE_20260711_100555 rid=9924.2526/2540/2542 closed the loop: submit ->
    # job name -> ACTIVE -> SUCCESSFUL with the combined MP4 inline (encodedVideo).
    assert R.capability_authority("GOOGLE_FLOW_FINAL_CONCAT_EXPORT") == R.AUTHORIZED
    entry = R.require_capability("GOOGLE_FLOW_FINAL_CONCAT_EXPORT")
    assert "runVideoFxConcatenation" in entry["rpc"]
    assert "encodedVideo" in entry["rpc"]
    assert "CAPTURE_20260711_100555" in entry["evidence"]


def test_unknown_capability_raises():
    with pytest.raises(ValueError) as exc:
        R.capability_authority("SOMETHING_ELSE")
    assert "UNKNOWN_NATIVE_EXTEND_CAPABILITY" in str(exc.value)


def test_two_axis_invariant_route_veo_extend_still_authority_missing():
    # Proving a transport CAPABILITY must NOT flip the ROUTE flag: the public-API
    # 8+7n route stays fail-closed even though native-extend transport is AUTHORIZED.
    assert R.ROUTE_REGISTRY["GOOGLE_FLOW_VEO_EXTEND"]["authority"] == R.AUTHORITY_MISSING
