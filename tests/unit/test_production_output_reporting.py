from datetime import date
import json

import pytest

from agent.services import production_output_reporting_service as svc


def _record(**values):
    return svc._base_record(
        output_id=values.get("output_id", "out-1"),
        media_type=values.get("media_type", "VIDEO"),
        production_recipe=values.get("production_recipe", "HYBRID"),
        origin_surface=values.get("origin_surface", "PRODUCTION_STUDIO"),
        staff_id=values.get("staff_id"),
        staff_display_name=values.get("staff_display_name"),
        operator_id=values.get("operator_id"),
        product_id=values.get("product_id", "prod-1"),
        product_name=values.get("product_name", "Real Product"),
        attempt_id=values.get("attempt_id", values.get("output_id", "out-1") + "-attempt"),
        attempt_number=values.get("attempt_number", 1),
        status=values.get("status", "SUCCESS"),
        qa_status=values.get("qa_status", "UNKNOWN"),
        artifact_media_id=values.get("artifact_media_id", "media-1" if values.get("success", True) else None),
        created_at=values.get("created_at", "2026-08-01T16:00:00Z"),
        completed_at=values.get("completed_at", "2026-08-01T16:01:00Z"),
        retry_count=values.get("retry_count", max(values.get("attempt_number", 1) - 1, 0)),
        success=values.get("success", True),
        failed=values.get("failed", False),
    )


def test_reporting_window_uses_inclusive_kuala_lumpur_calendar_boundaries():
    window = svc.reporting_window("2026-08-01", "2026-08-01", today=date(2026, 8, 22))

    assert window["start_utc"] == "2026-07-31T16:00:00Z"
    assert window["end_utc"] == "2026-08-01T16:00:00Z"
    assert window["days"] == 1


def test_recipe_lineage_never_maps_transport_mode_to_business_recipe():
    assert svc._lineage_recipe({"mode": "F2V"}) is None
    assert svc._lineage_recipe({"source_mode": "FRAMES"}) is None
    assert svc._lineage_recipe({"source_mode": "HYBRID"}) == "HYBRID"
    assert svc._lineage_recipe({"faceless_execution_identity": {"lane": "FACELESS"}}) == "FACELESS"


def test_metrics_deduplicate_retries_but_preserve_attempt_and_failure_counts():
    records = [
        _record(output_id="out-1", attempt_id="a-1", attempt_number=1, success=False, failed=True, status="FAILED", artifact_media_id=None),
        _record(output_id="out-1", attempt_id="a-2", attempt_number=2, success=True, operator_id="alice", qa_status="QA_APPROVED"),
        _record(output_id="out-2", attempt_id="a-3", attempt_number=1, success=True, operator_id=None),
    ]

    metrics = svc._metric_block(records)

    assert metrics["total_attempts"] == 3
    assert metrics["successful_outputs"] == 2
    assert metrics["failed_attempts"] == 1
    assert metrics["retry_attempts"] == 1
    assert metrics["qa_approved"] == 1
    assert metrics["success_rate"] == pytest.approx(2 / 3, abs=0.0001)


def test_staff_metrics_exclude_unattributed_rows_and_do_not_rank_attempts():
    records = [
        _record(output_id="out-1", attempt_id="a-1", attempt_number=1, operator_id="alice", success=False, failed=True, status="FAILED", artifact_media_id=None),
        _record(output_id="out-1", attempt_id="a-2", attempt_number=2, operator_id="alice", success=True, qa_status="QA_APPROVED"),
        _record(output_id="out-2", attempt_id="a-3", operator_id=None, success=True),
    ]

    rows = svc._staff_performance(records)

    assert len(rows) == 1
    assert rows[0]["staff"] == "alice"
    assert rows[0]["successful_outputs"] == 1
    assert rows[0]["failed_attempts"] == 1
    assert rows[0]["hybrid"] == 1


def test_reporting_prefers_canonical_staff_identity_and_name_snapshot():
    record = _record(
        staff_id="staff_aisha",
        staff_display_name="Aisha Rahman",
        operator_id="system",
    )

    assert record["staff_id"] == "staff_aisha"
    assert record["staff_display_name"] == "Aisha Rahman"
    assert record["operator_id"] == "staff_aisha"
    assert record["operator_display_name"] == "Aisha Rahman"
    assert svc._staff_performance([record])[0]["staff"] == "staff_aisha"
    assert svc._staff_performance([record])[0]["staff_display_name"] == "Aisha Rahman"


def test_historical_generic_identity_is_not_fabricated_into_staff_performance():
    record = _record(operator_id="p6-production-operator")

    assert record["staff_id"] is None
    assert record["operator_id"] is None
    assert svc._staff_performance([record]) == []


def test_filter_options_cannot_echo_internal_or_retired_values():
    options = svc._filter_options(
        [
            _record(production_recipe="HYBRID"),
            _record(production_recipe="T2V", origin_surface="LEGACY", model_key="Wan 2.6"),
        ]
    )

    assert options["production_recipes"] == ["HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"]
    assert "T2V" not in options["production_recipes"]
    assert "LEGACY" not in options["origin_surfaces"]


def test_poster_machine_qa_is_counted_only_with_zero_blockers():
    assert svc._poster_qa_status('{"ok":true,"block_count":0}') == "QA_APPROVED"
    assert svc._poster_qa_status('{"ok":true,"block_count":1}') == "QA_REJECTED"


@pytest.mark.asyncio
async def test_report_is_server_aggregated_and_ledger_is_paginated(monkeypatch):
    records = [
        _record(output_id="out-1", attempt_id="a-1", operator_id="alice"),
        _record(output_id="out-2", attempt_id="a-2", production_recipe="POSTER_BUILDER", media_type="POSTER", origin_surface="POSTER_BUILDER", operator_id="alice"),
    ]
    monkeypatch.setattr(svc, "_all_records", lambda _window: _async_records(records))

    report = await svc.get_production_report(start_date="2026-08-01", end_date="2026-08-01")
    ledger = await svc.get_production_ledger(start_date="2026-08-01", end_date="2026-08-01", limit=1, offset=1)

    assert report["overview"]["successful_outputs"] == 2
    assert report["overview"]["successful_video_outputs"] == 1
    assert report["overview"]["successful_image_poster_outputs"] == 1
    assert len(ledger["items"]) == 1
    assert ledger["total"] == 2
    assert all(not key.startswith("_") for key in ledger["items"][0])


@pytest.mark.asyncio
async def test_empty_authoritative_ledgers_are_a_valid_zero_report():
    report = await svc.get_production_report(start_date="2026-08-01", end_date="2026-08-01")

    assert report["overview"]["total_attempts"] == 0
    assert report["overview"]["success_rate"] is None
    assert report["video_breakdown"]
    assert report["poster_breakdown"][0]["production_recipe"] == "POSTER_BUILDER"


@pytest.mark.asyncio
async def test_authoritative_ledgers_exclude_legacy_rows_and_deduplicate_real_outputs():
    from agent.db.schema import get_db

    db = await get_db()
    stamp = "2026-08-01T01:00:00Z"
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name) VALUES (?,?,?,?)",
        ("prod-reporting", "Real serum", "Real Serum", "Serum"),
    )
    await db.execute(
        """INSERT INTO creative_production_plan
           (plan_id, request_id, created_by, name, p58_cohort_sha256, p58_cohort_count,
            production_recipe, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("plan-reporting", "req-plan-reporting", "alice", "Reporting plan", "sha", 1, "HYBRID", "APPROVED", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_production_item
           (item_id, plan_id, item_ordinal, product_id, media_type, production_recipe,
            creative_dna_sha256, dedupe_guard_key, status, output_media_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("item-reporting", "plan-reporting", 1, "prod-reporting", "VIDEO", "HYBRID", "dna", "guard-reporting", "QA_APPROVED", "media-p6", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO creative_generation_attempt
           (attempt_id, item_id, attempt_number, idempotency_key, action_request_id,
            attempt_state, payload_sha256, provider, model_key, last_actor_id,
            failure_code, created_at, completed_at, artifact_media_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("attempt-p6-failed", "item-reporting", 1, "idem-p6-failed", "action-p6-failed", "FAILED", "payload", "GOOGLE_FLOW", "veo-3.1", "bob", "PROVIDER_TIMEOUT", stamp, stamp, None),
    )
    await db.execute(
        """INSERT INTO creative_generation_attempt
           (attempt_id, item_id, attempt_number, idempotency_key, action_request_id,
            attempt_state, payload_sha256, provider, model_key, last_actor_id,
            created_at, completed_at, artifact_media_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("attempt-p6-success", "item-reporting", 2, "idem-p6-success", "action-p6-success", "REGISTERED", "payload", "GOOGLE_FLOW", "veo-3.1", "alice", stamp, stamp, "media-p6"),
    )
    await db.execute(
        """INSERT INTO creative_output_qa
           (qa_id, item_id, attempt_id, artifact_media_id, status, reviewer_id, reviewed_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("qa-reporting", "item-reporting", "attempt-p6-success", "media-p6", "QA_APPROVED", "reviewer", stamp),
    )
    await db.execute(
        """INSERT INTO workspace_generation_package
           (workspace_generation_package_id, mode, product_id, source_lane, status)
           VALUES (?,?,?,?,?)""",
        ("wgp-reporting-hybrid", "F2V", "prod-reporting", "HYBRID", "READY_MANUAL"),
    )
    await db.execute(
        """INSERT INTO generation_result
           (media_id, job_id, request_id, mode, artifact_kind, product_id, product_name,
            workspace_generation_package_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("media-standalone", "job-standalone", "req-standalone", "F2V", "video", "prod-reporting", "Real Serum", "wgp-reporting-hybrid", stamp),
    )
    await db.execute(
        """INSERT INTO generation_result
           (media_id, job_id, request_id, mode, artifact_kind, product_id, product_name, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("media-legacy", "job-legacy", "req-legacy", "T2V", "video", "prod-reporting", "Real Serum", stamp),
    )
    await db.execute(
        """INSERT INTO request (id, type, status, retry_count, created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        ("req-standalone-failed", "GENERATE_VIDEO", "FAILED", 1, stamp, stamp),
    )
    await db.execute(
        """INSERT INTO request_telemetry
           (request_id, product_id, request_type, mode, request_lineage_payload,
            status, failed_at, created_at, error_code)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("req-standalone-failed", "prod-reporting", "GENERATE_VIDEO", "F2V", json.dumps({"source_mode": "HYBRID"}), "FAILED", stamp, stamp, "NO_ARTIFACT"),
    )
    await db.execute(
        """INSERT INTO poster_deliverable
           (poster_deliverable_id, product_id, output_path, output_sha256,
            qa_report_json, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("poster-reporting", "prod-reporting", "poster.png", "sha256", json.dumps({"ok": True, "block_count": 0}), "POSTER_SAVED", stamp, stamp),
    )
    await db.execute(
        """INSERT INTO bulk_generation_run
           (bulk_run_id, kind, status, config_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        ("montage-reporting", "MONTAGE_DISCRETE", "COMPLETE", json.dumps({"product_id": "prod-reporting", "model": "veo-3.1"}), stamp, stamp),
    )
    await db.execute(
        """INSERT INTO bulk_generation_item
           (bulk_item_id, bulk_run_id, item_type, source_ref, status, media_id, created_at, completed_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("montage-item-reporting", "montage-reporting", "MONTAGE_SCENE", "scene-1", "RESULT_BOUND", "media-montage", stamp, stamp),
    )
    await db.commit()

    report = await svc.get_production_report(start_date="2026-08-01", end_date="2026-08-01")
    ledger = await svc.get_production_ledger(start_date="2026-08-01", end_date="2026-08-01", limit=200)

    assert report["overview"]["successful_video_outputs"] == 3  # P6, exact standalone, Montage
    assert report["overview"]["successful_image_poster_outputs"] == 1
    assert report["overview"]["failed_attempts"] == 2  # P6 failed retry + exact standalone failure
    assert report["overview"]["retry_attempts"] == 2  # P6 retry + failed standalone retry
    assert report["overview"]["qa_approved"] == 2  # P6 + Poster Builder machine QA
    assert report["overview"]["successful_outputs"] == 4
    assert all(row["production_recipe"] != "T2V" for row in ledger["items"])
    assert all(row["model_key"] != "Wan 2.6" for row in ledger["items"])
    assert {row["production_recipe"] for row in ledger["items"]} == {"HYBRID", "MONTAGE", "POSTER_BUILDER"}


async def _async_records(records):
    return records
