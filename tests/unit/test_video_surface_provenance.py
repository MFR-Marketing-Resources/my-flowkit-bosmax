import pytest

from agent.services.video_surface_provenance import (
    VideoSurfaceProvenanceError,
    build_video_surface_provenance,
    resolve_surface_lane,
    surface_display_label,
)


def test_hybrid_surface_is_separate_from_f2v_transport():
    provenance = build_video_surface_provenance(
        surface_lane="HYBRID",
        transport_mode="F2V",
        source_mode="HYBRID",
        mode="F2V",
    )

    assert provenance == {
        "surface_lane": "HYBRID",
        "transport_mode": "F2V",
        "source_mode": "HYBRID",
        "provider_generation_type": "reference_frame_2_video",
    }


def test_internal_transport_is_never_accepted_as_an_active_surface():
    with pytest.raises(VideoSurfaceProvenanceError, match="ACTIVE_SURFACE_LANE_REQUIRED"):
        resolve_surface_lane(explicit="F2V", mode="F2V")


def test_montage_and_p6_preserve_their_own_surface_labels():
    montage = build_video_surface_provenance(
        surface_lane="MONTAGE", transport_mode="F2V", source_mode="FRAMES"
    )
    p6 = build_video_surface_provenance(
        surface_lane="P6", transport_mode="MONTAGE", mode="MONTAGE"
    )

    assert montage["surface_lane"] == "MONTAGE"
    assert montage["provider_generation_type"] == "reference_frame_2_video"
    assert p6["surface_lane"] == "PRODUCTION_STUDIO_P6"
    assert surface_display_label("FACELESS") == "Faceless Video"
    assert surface_display_label("P6", mode="MONTAGE") == "Production Studio / P6"


def test_untyped_legacy_rows_are_not_falsely_remapped():
    assert surface_display_label(None, mode="F2V") == "Legacy/Internal"
    assert surface_display_label(None) == "Unknown Surface"


def test_existing_durable_surface_wins_over_internal_mode():
    provenance = build_video_surface_provenance(
        mode="F2V",
        transport_mode="F2V",
        existing={"surface_lane": "HYBRID", "initial_mode": "F2V"},
    )
    assert provenance["surface_lane"] == "HYBRID"
