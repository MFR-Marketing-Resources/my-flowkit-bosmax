"""Results Hub API — durable deliverable list + detail.

Exercises the route handlers directly (no HTTP server), the same way
tests/api/test_social_copy_api.py does. The hub composes three sources by Flow
media_id: the durable generation_result snapshot (manual Flow fallback), the
video 48h/image persistent artifact file (download), and the social captions
(publish).
"""
import pytest
from fastapi import HTTPException

from agent.api import results as api
from agent.db import crud


async def _seed_result_with_file(
    media_id, *, mode="T2V", kind="video", prompt="hero shot",
    job_id: str | None = None, request_id: str | None = None,
    surface_lane: str | None = None, staff_id: str | None = None,
):
    job_id = job_id or f"job-{media_id}"
    await crud.insert_generation_result(
        media_id, job_id=job_id, request_id=request_id, mode=mode,
        artifact_kind=kind, product_name="Bosmax", surface_lane=surface_lane,
        staff_id=staff_id,
        final_prompt_text=prompt, aspect_ratio="9:16", model_label="Omni Flash",
        duration_s=8, count_setting=1, reference_media_ids=["ref-1"])
    await crud.insert_generated_artifact(
        media_id, job_id=job_id, mode=mode, artifact_kind=kind,
        surface_lane=surface_lane, staff_id=staff_id,
        local_path="/tmp/x", size_mb=1.2)
    if kind == "video":
        await crud.create_video_production_job_full(
            job_id, logical_job_key=f"key-{job_id}", status="COMPLETE"
        )
        await crud.update_video_production_job_full(job_id, final_media_id=media_id)


async def test_list_returns_record_with_file_available():
    # The Windows test DB may carry rows from sibling tests; look up by id
    # rather than asserting the global count.
    await _seed_result_with_file("m1")
    resp = await api.list_results(limit=200, mode=None, kind=None)
    item = next(r for r in resp["results"] if r["media_id"] == "m1")
    assert item["has_record"] is True
    assert item["file_available"] is True
    assert item["retrieved_url"] == "/api/flow/retrieved/m1"
    assert item["caption_summary"] == {"count": 0, "approved": 0}


async def test_list_shows_record_after_file_expired():
    # Durable record, but NO artifact row (file gone) → still listed, no download.
    await crud.insert_generation_result(
        "m2", mode="IMG", artifact_kind="image", final_prompt_text="marble")
    resp = await api.list_results(limit=60, mode=None, kind=None)
    by_id = {r["media_id"]: r for r in resp["results"]}
    assert "m2" in by_id
    assert by_id["m2"]["file_available"] is False
    assert by_id["m2"]["retrieved_url"] is None


async def test_list_includes_file_only_artifact_without_record():
    # Older artifact / direct programmatic lane: file exists, no durable record.
    await crud.insert_generated_artifact(
        "m3", job_id="g", mode="F2V", artifact_kind="video", size_mb=2.0)
    await crud.create_video_production_job_full(
        "g", logical_job_key="key-m3", status="COMPLETE"
    )
    await crud.update_video_production_job_full("g", final_media_id="m3")
    resp = await api.list_results(limit=60, mode=None, kind=None)
    by_id = {r["media_id"]: r for r in resp["results"]}
    assert "m3" in by_id
    assert by_id["m3"]["has_record"] is False
    assert by_id["m3"]["file_available"] is True
    assert by_id["m3"]["surface_label"] == "Legacy/Internal"


async def test_active_surface_label_is_not_replaced_by_transport_mode():
    await crud.insert_generation_result(
        "hybrid-provenance",
        mode="F2V",
        surface_lane="HYBRID",
        transport_mode="F2V",
        source_mode="HYBRID",
        provider_generation_type="reference_frame_2_video",
        artifact_kind="video",
    )
    await crud.insert_generated_artifact(
        "hybrid-provenance",
        job_id="g-hybrid",
        mode="F2V",
        surface_lane="HYBRID",
        transport_mode="F2V",
        source_mode="HYBRID",
        provider_generation_type="reference_frame_2_video",
        artifact_kind="video",
    )
    await crud.create_video_production_job_full(
        "g-hybrid", logical_job_key="key-hybrid-provenance", status="COMPLETE"
    )
    await crud.update_video_production_job_full(
        "g-hybrid", final_media_id="hybrid-provenance"
    )
    resp = await api.list_results(limit=200, surface_lane="HYBRID")
    item = next(row for row in resp["results"] if row["media_id"] == "hybrid-provenance")
    assert item["surface_label"] == "Hybrid"
    assert item["surface_lane"] == "HYBRID"
    assert item["transport_mode"] == "F2V"


async def test_kind_filter():
    await _seed_result_with_file("kf-v", mode="T2V", kind="video")
    await _seed_result_with_file("kf-i", mode="IMG", kind="image")
    resp = await api.list_results(limit=200, mode=None, kind="image")
    ids = {r["media_id"] for r in resp["results"]}
    assert "kf-i" in ids
    assert "kf-v" not in ids
    assert all(r["artifact_kind"] == "image" for r in resp["results"])


async def test_caption_rollup_in_list():
    await _seed_result_with_file("mc")
    await crud.create_social_copy_package(
        "scp_1", artifact_media_id="mc", platform="tiktok", status="APPROVED")
    resp = await api.list_results(limit=60, mode=None, kind=None)
    item = next(r for r in resp["results"] if r["media_id"] == "mc")
    assert item["caption_summary"] == {"count": 1, "approved": 1}


async def test_detail_exposes_prompt_snapshot_and_parsed_captions():
    await _seed_result_with_file("md", prompt="a cinematic dawn shot")
    await crud.create_social_copy_package(
        "scp_x", artifact_media_id="md", platform="tiktok", source_mode="T2V",
        hashtags_json='["#fyp"]', status="APPROVED")
    detail = await api.get_result("md")
    assert detail["has_record"] is True
    assert detail["snapshot"]["final_prompt_text"] == "a cinematic dawn shot"
    assert detail["snapshot"]["reference_media_ids"] == ["ref-1"]
    assert detail["file_available"] is True
    assert detail["retrieved_url"] == "/api/flow/retrieved/md"
    assert len(detail["captions"]) == 1
    assert detail["captions"][0]["hashtags_json"] == ["#fyp"]  # parsed to array


async def test_detail_for_file_only_artifact_has_no_snapshot():
    await crud.insert_generated_artifact(
        "mf", job_id="g", mode="IMG", artifact_kind="image", size_mb=0.5)
    detail = await api.get_result("mf")
    assert detail["has_record"] is False
    assert detail["snapshot"] is None
    assert detail["file_available"] is True


async def test_detail_unknown_media_raises_404():
    with pytest.raises(HTTPException) as exc:
        await api.get_result("nope")
    assert exc.value.status_code == 404
    assert exc.value.detail == "RESULT_NOT_FOUND"


async def test_results_exposes_same_final_identity_as_library():
    await _seed_result_with_file("same-final")

    results = await api.list_results(limit=200)
    library = await crud.list_generated_artifacts(
        limit=200, kind="video", final_only=True
    )
    assert "same-final" in {row["media_id"] for row in results["results"]}
    assert "same-final" in {row["media_id"] for row in library}


async def test_session_recovery_filters_staff_surface_job_request_without_history_leak():
    await _seed_result_with_file(
        "session-final", job_id="session-job", request_id="session-request",
        surface_lane="HYBRID", staff_id="staff-session",
    )
    await _seed_result_with_file(
        "other-final", job_id="other-job", request_id="other-request",
        surface_lane="FACELESS", staff_id="staff-other",
    )

    recovered = await api.recover_results(
        request_id="session-request", job_id="session-job",
        surface_lane="HYBRID", staff_id="staff-session", limit=60,
    )
    assert [row["media_id"] for row in recovered["results"]] == ["session-final"]


async def test_request_filtered_list_never_merges_unrelated_file_only_history():
    await _seed_result_with_file(
        "filtered-final", job_id="filtered-job", request_id="filtered-request",
        surface_lane="HYBRID", staff_id="staff-filtered",
    )
    await crud.insert_generated_artifact(
        "history-file-only", job_id="history-job", mode="F2V",
        artifact_kind="video", surface_lane="HYBRID", staff_id="staff-filtered",
    )
    await crud.create_video_production_job_full(
        "history-job", logical_job_key="history-file-only-key", status="COMPLETE"
    )
    await crud.update_video_production_job_full(
        "history-job", final_media_id="history-file-only"
    )

    listed = await api.list_results(
        request_id="filtered-request", surface_lane="HYBRID",
        staff_id="staff-filtered", limit=60,
    )
    assert [row["media_id"] for row in listed["results"]] == ["filtered-final"]


async def test_non_final_video_is_hidden_from_results():
    await crud.insert_generation_result(
        "intermediate-video", job_id="segment-job", mode="F2V", artifact_kind="video"
    )
    await crud.insert_generated_artifact(
        "intermediate-video", job_id="segment-job", mode="F2V", artifact_kind="video"
    )
    with pytest.raises(HTTPException) as exc:
        await api.get_result("intermediate-video")
    assert exc.value.status_code == 404
