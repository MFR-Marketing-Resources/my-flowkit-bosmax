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


def test_final_concat_export_fails_closed():
    assert R.capability_authority("GOOGLE_FLOW_FINAL_CONCAT_EXPORT") == R.AUTHORITY_MISSING
    with pytest.raises(R.CapabilityAuthorityMissing) as exc:
        R.require_capability("GOOGLE_FLOW_FINAL_CONCAT_EXPORT")
    assert exc.value.error_code == "FINAL_CONCAT_EXPORT_AUTHORITY_MISSING"


def test_unknown_capability_raises():
    with pytest.raises(ValueError) as exc:
        R.capability_authority("SOMETHING_ELSE")
    assert "UNKNOWN_NATIVE_EXTEND_CAPABILITY" in str(exc.value)


def test_two_axis_invariant_route_veo_extend_still_authority_missing():
    # Proving a transport CAPABILITY must NOT flip the ROUTE flag: the public-API
    # 8+7n route stays fail-closed even though native-extend transport is AUTHORIZED.
    assert R.ROUTE_REGISTRY["GOOGLE_FLOW_VEO_EXTEND"]["authority"] == R.AUTHORITY_MISSING
