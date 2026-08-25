"""Durable generation_result record (Results Hub) — crud behavior.

Video artifact FILEs are purged at 48h; image artifact FILEs are manual-delete.
The generation_result record and social captions are NOT purged, so the
prompt/settings/caption stay reachable for manual Google Flow fallback +
publishing after a video file is gone.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from agent.db import crud


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


async def test_insert_get_roundtrip():
    await crud.insert_generation_result(
        "media-1",
        job_id="g_1", request_id="req_1", mode="T2V", artifact_kind="video",
        product_id=None, product_name="Bosmax",
        final_prompt_text="a cinematic hero shot",
        aspect_ratio="9:16", model_label="Omni Flash", duration_s=8,
        count_setting=2, reference_media_ids=["ref-a", "ref-b"],
        workspace_generation_package_id="wgp_1", project_id="proj_1",
    )
    row = await crud.get_generation_result("media-1")
    assert row is not None
    assert row["final_prompt_text"] == "a cinematic hero shot"
    assert row["aspect_ratio"] == "9:16"
    assert row["model_label"] == "Omni Flash"
    assert row["duration_s"] == 8
    assert row["count_setting"] == 2
    assert json.loads(row["reference_media_ids_json"]) == ["ref-a", "ref-b"]


async def test_upsert_updates_snapshot_but_preserves_created_at():
    await crud.insert_generation_result("media-2", final_prompt_text="first")
    first = await crud.get_generation_result("media-2")
    await crud.insert_generation_result("media-2", final_prompt_text="second")
    second = await crud.get_generation_result("media-2")
    assert second["final_prompt_text"] == "second"       # snapshot updated
    assert second["created_at"] == first["created_at"]   # ordering stays stable


async def test_staff_and_surface_provenance_survive_idempotent_rerecord():
    await crud.insert_generated_artifact(
        "provenance-artifact",
        job_id="g-provenance",
        staff_id="staff_faris",
        staff_display_name_snapshot="<faris>",
        mode="F2V",
        surface_lane="HYBRID",
        transport_mode="F2V",
        source_mode="HYBRID",
        provider_generation_type="reference_frame_2_video",
        artifact_kind="video",
    )
    await crud.insert_generated_artifact(
        "provenance-artifact",
        job_id="g-provenance",
        mode="F2V",
        artifact_kind="video",
    )
    artifact = await crud.get_generated_artifact("provenance-artifact")
    assert artifact["staff_id"] == "staff_faris"
    assert artifact["staff_display_name_snapshot"] == "<faris>"
    assert artifact["surface_lane"] == "HYBRID"
    assert artifact["transport_mode"] == "F2V"

    await crud.insert_generation_result(
        "provenance-result",
        job_id="g-provenance",
        staff_id="staff_faris",
        staff_display_name_snapshot="<faris>",
        mode="F2V",
        surface_lane="HYBRID",
        transport_mode="F2V",
        source_mode="HYBRID",
        provider_generation_type="reference_frame_2_video",
    )
    await crud.insert_generation_result(
        "provenance-result",
        job_id="g-provenance",
        mode="F2V",
        product_visual_custody={"product_id": "p-provenance"},
    )
    result = await crud.get_generation_result("provenance-result")
    assert result["staff_id"] == "staff_faris"
    assert result["staff_display_name_snapshot"] == "<faris>"
    assert result["surface_lane"] == "HYBRID"
    assert result["transport_mode"] == "F2V"
    assert result["source_mode"] == "HYBRID"


async def test_record_survives_video_artifact_purge():
    """Purging a 48h video file removes only its artifact row; the durable
    record (prompt/settings) stays reachable."""
    await crud.insert_generation_result(
        "media-3", mode="T2V", artifact_kind="video",
        final_prompt_text="a cinematic product scene")
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            """INSERT OR REPLACE INTO generated_artifact
               (media_id, job_id, mode, artifact_kind, local_path, size_mb,
                project_id, model_used, duration_used, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("media-3", "g_3", "T2V", "video", None, 0.5, None, None, None, _ts(49)))
        await db.commit()

    purged = await crud.purge_expired_artifacts(retention_hours=48)
    assert purged["purged_rows"] >= 1
    assert await crud.get_generated_artifact("media-3") is None      # file row gone
    survived = await crud.get_generation_result("media-3")
    assert survived is not None                                      # record stays
    assert survived["final_prompt_text"] == "a cinematic product scene"


async def test_list_filters_by_kind_and_mode():
    # NOTE: the Windows test DB is not always wiped between tests (locked file),
    # so assert on membership + filter correctness, never on the global set.
    await crud.insert_generation_result("gr-v1", mode="T2V", artifact_kind="video")
    await crud.insert_generation_result("gr-i1", mode="IMG", artifact_kind="image")
    videos = await crud.list_generation_results(kind="video", limit=200)
    vids = {r["media_id"] for r in videos}
    assert "gr-v1" in vids
    assert "gr-i1" not in vids
    assert all(r["artifact_kind"] == "video" for r in videos)
    imgs = await crud.list_generation_results(mode="IMG", limit=200)
    assert "gr-i1" in {r["media_id"] for r in imgs}
    assert all(r["mode"] == "IMG" for r in imgs)


async def test_caption_summary_rollup_counts_and_approved():
    await crud.insert_generated_artifact(
        "m-cap", job_id="j", mode="IMG", artifact_kind="image")
    await crud.create_social_copy_package(
        "scp_a", artifact_media_id="m-cap", platform="tiktok", status="DRAFT")
    await crud.create_social_copy_package(
        "scp_b", artifact_media_id="m-cap", platform="instagram", status="APPROVED")
    summary = await crud.caption_summary_for_media_ids(["m-cap", "absent"])
    assert summary["m-cap"] == {"count": 2, "approved": 1}
    assert "absent" not in summary


async def test_caption_summary_empty_input():
    assert await crud.caption_summary_for_media_ids([]) == {}
    assert await crud.caption_summary_for_media_ids(None) == {}


def _delivery_payload(media_id: str) -> dict:
    return {
        "media_id": media_id,
        "artifact": {
            "job_id": f"job-{media_id}", "mode": "F2V", "artifact_kind": "video",
            "local_path": f"/tmp/{media_id}.mp4", "file_size_bytes": 123,
            "file_sha256": "a" * 64, "readback_verified": True,
        },
        "generation_result": {
            "job_id": f"job-{media_id}", "mode": "F2V", "artifact_kind": "video",
            "final_prompt_text": "final prompt",
        },
    }


async def test_final_video_delivery_commits_artifact_and_result_atomically():
    payload = _delivery_payload("atomic-final")
    delivery = await crud.insert_final_video_delivery(**payload)

    assert delivery["complete"] is True
    assert delivery["artifact"]["file_sha256"] == "a" * 64
    assert delivery["generation_result"]["final_prompt_text"] == "final prompt"


async def test_final_video_delivery_rolls_back_when_result_write_fails():
    db = await crud.get_db()
    await db.execute(
        """CREATE TRIGGER fail_final_result BEFORE INSERT ON generation_result
           WHEN NEW.media_id='atomic-rollback'
           BEGIN SELECT RAISE(FAIL, 'forced result failure'); END"""
    )
    await db.commit()

    with pytest.raises(Exception, match="forced result failure"):
        await crud.insert_final_video_delivery(**_delivery_payload("atomic-rollback"))

    assert await crud.get_generated_artifact("atomic-rollback") is None
    assert await crud.get_generation_result("atomic-rollback") is None


async def test_incomplete_delivery_query_never_selects_provider_work():
    await crud.create_video_production_job_full(
        "local-repair", logical_job_key="local-repair-key", status="DELIVERY_PENDING"
    )
    await crud.update_video_production_job_full(
        "local-repair", final_media_id="local-final", final_local_path="/tmp/local.mp4"
    )
    await crud.create_video_production_job_full(
        "provider-work", logical_job_key="provider-work-key", status="INITIAL_POLLING",
        stage_state_json='{"provider_generation_submit_count":1}',
    )

    rows = await crud.list_incomplete_final_video_deliveries()
    assert {row["job_id"] for row in rows} == {"local-repair"}


async def test_final_projection_includes_single_extend_montage_and_p6_finals():
    db = await crud.get_db()
    for job_id, media_id in (("single-job", "single-final"), ("extend-job", "extend-final")):
        await crud.create_video_production_job_full(
            job_id, logical_job_key=f"key-{job_id}", status="COMPLETE"
        )
        await crud.update_video_production_job_full(job_id, final_media_id=media_id)
    stamp = "2026-08-25T00:00:00Z"
    await db.execute(
        """INSERT INTO bulk_generation_run
           (bulk_run_id, kind, status, config_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        ("montage-final-run", "MONTAGE_DISCRETE", "COMPLETE",
         json.dumps({"assembly": {"final_media_id": "montage-final"}}), stamp, stamp),
    )
    await db.execute(
        """INSERT OR IGNORE INTO product
           (id, source, raw_product_title, product_display_name,
            product_short_name, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("product-p6", "MANUAL", "P6 real serum", "P6 Real Serum",
         "Real Serum", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_production_plan
           (plan_id, request_id, created_by, name, p58_cohort_sha256,
            p58_cohort_count, production_recipe, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("p6-plan", "p6-request", "staff", "P6", "sha", 1, "HYBRID", "APPROVED", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_production_item
           (item_id, plan_id, item_ordinal, product_id, media_type,
            production_recipe, creative_dna_sha256, dedupe_guard_key, status,
            output_media_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("p6-item", "p6-plan", 1, "product-p6", "VIDEO", "HYBRID", "dna",
         "guard-p6", "QA_APPROVED", "p6-final", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_generation_attempt
           (attempt_id, item_id, attempt_number, idempotency_key, action_request_id,
            attempt_state, payload_sha256, artifact_media_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("p6-attempt", "p6-item", 1, "p6-idem", "p6-action", "REGISTERED",
         "payload", "p6-final", stamp),
    )
    await db.commit()

    assert {"single-final", "extend-final", "montage-final", "p6-final"}.issubset(
        set(await crud.list_final_video_media_ids())
    )


async def test_final_projection_excludes_segments_scenes_and_rejected_attempts():
    db = await crud.get_db()
    await crud.create_video_production_job_full(
        "segments-job", logical_job_key="segments-key", status="COMPLETE",
        segment_media_ids_json='["segment-only"]',
    )
    stamp = "2026-08-25T00:00:00Z"
    await db.execute(
        """INSERT INTO bulk_generation_run
           (bulk_run_id, kind, status, config_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        ("scene-run", "MONTAGE_DISCRETE", "PARTIAL", "{}", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO bulk_generation_item
           (bulk_item_id, bulk_run_id, item_type, source_ref, status, media_id,
            created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        ("scene-item", "scene-run", "MONTAGE_SCENE", "scene", "RESULT_BOUND",
         "scene-only", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO product
           (id, source, raw_product_title, product_display_name,
            product_short_name, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("product-p6-rejection", "MANUAL", "Real toner", "Real Toner",
         "Toner", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_production_plan
           (plan_id, request_id, created_by, name, p58_cohort_sha256,
            p58_cohort_count, production_recipe, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("rejection-plan", "rejection-request", "staff", "Real P6 plan",
         "sha-rejection", 1, "HYBRID", "APPROVED", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_production_item
           (item_id, plan_id, item_ordinal, product_id, media_type,
            production_recipe, creative_dna_sha256, dedupe_guard_key, status,
            output_media_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("rejection-item", "rejection-plan", 1, "product-p6-rejection",
         "VIDEO", "HYBRID", "dna-rejection", "guard-rejection",
         "QA_APPROVED", "accepted-p6-final", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_generation_attempt
           (attempt_id, item_id, attempt_number, idempotency_key, action_request_id,
            attempt_state, payload_sha256, artifact_media_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("rejected-attempt", "rejection-item", 1, "rejected-idem",
         "rejected-action", "QA_REJECTED", "rejected-payload",
         "rejected-p6-media", stamp),
    )
    await db.execute(
        """INSERT INTO creative_generation_attempt
           (attempt_id, item_id, attempt_number, idempotency_key, action_request_id,
            attempt_state, payload_sha256, artifact_media_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("accepted-attempt", "rejection-item", 2, "accepted-idem",
         "accepted-action", "REGISTERED", "accepted-payload",
         "accepted-p6-final", stamp),
    )
    await db.commit()

    finals = set(await crud.list_final_video_media_ids())
    assert "accepted-p6-final" in finals
    assert "segment-only" not in finals
    assert "scene-only" not in finals
    assert "rejected-p6-media" not in finals


async def test_result_only_retained_final_remains_caption_eligible():
    await crud.create_video_production_job_full(
        "retained-job", logical_job_key="retained-key", status="COMPLETE"
    )
    await crud.update_video_production_job_full(
        "retained-job", final_media_id="retained-final"
    )
    await crud.insert_generation_result(
        "retained-final", job_id="retained-job", mode="F2V", artifact_kind="video"
    )

    rows = await crud.list_generation_results(kind="video", final_only=True)
    assert "retained-final" in {row["media_id"] for row in rows}
