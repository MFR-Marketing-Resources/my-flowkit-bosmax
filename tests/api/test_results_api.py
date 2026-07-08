"""Results Hub API — durable deliverable list + detail.

Exercises the route handlers directly (no HTTP server), the same way
tests/api/test_social_copy_api.py does. The hub composes three sources by Flow
media_id: the durable generation_result snapshot (manual Flow fallback), the
48h artifact file (download), and the social captions (publish).
"""
import pytest
from fastapi import HTTPException

from agent.api import results as api
from agent.db import crud


async def _seed_result_with_file(
    media_id, *, mode="T2V", kind="video", prompt="hero shot"
):
    await crud.insert_generation_result(
        media_id, mode=mode, artifact_kind=kind, product_name="Bosmax",
        final_prompt_text=prompt, aspect_ratio="9:16", model_label="Omni Flash",
        duration_s=8, count_setting=1, reference_media_ids=["ref-1"])
    await crud.insert_generated_artifact(
        media_id, job_id="g", mode=mode, artifact_kind=kind,
        local_path="/tmp/x", size_mb=1.2)


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
    resp = await api.list_results(limit=60, mode=None, kind=None)
    by_id = {r["media_id"]: r for r in resp["results"]}
    assert "m3" in by_id
    assert by_id["m3"]["has_record"] is False
    assert by_id["m3"]["file_available"] is True


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
