import json
import subprocess

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.api import local_agent


def test_inspect_autostart_metadata_parses_scheduled_task_and_stale_shortcut(monkeypatch):
    monkeypatch.setattr(local_agent.os, "name", "nt", raising=False)

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "enabled": True,
                    "mode": "SCHEDULED_TASK",
                    "warning": "STALE_STARTUP_SHORTCUT_PRESENT",
                    "scheduled_task_name": "BOSMAX Flow Kit Local Agent Watchdog",
                    "startup_shortcut_exists": True,
                    "startup_shortcut_matches": False,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(local_agent.subprocess, "run", _fake_run)

    result = local_agent._inspect_autostart_metadata()

    assert result["enabled"] is True
    assert result["mode"] == "SCHEDULED_TASK"
    assert result["warning"] == "STALE_STARTUP_SHORTCUT_PRESENT"
    assert result["scheduled_task_name"] == "BOSMAX Flow Kit Local Agent Watchdog"


def test_inspect_autostart_metadata_fails_closed_on_subprocess_error(monkeypatch):
    monkeypatch.setattr(local_agent.os, "name", "nt", raising=False)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=10)

    monkeypatch.setattr(local_agent.subprocess, "run", _raise_timeout)

    result = local_agent._inspect_autostart_metadata()

    assert result == local_agent._autostart_metadata_defaults()


@pytest.mark.asyncio
async def test_get_local_agent_status_surfaces_autostart_warning(monkeypatch):
    class _FakeFlowClient:
        connected = True

        async def get_status(self, probe_timeout=5):
            return {"state": "idle"}

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client",
        lambda: _FakeFlowClient(),
    )
    async def _fake_autostart_metadata():
        return {
            "enabled": True,
            "mode": "SCHEDULED_TASK",
            "warning": "STALE_STARTUP_SHORTCUT_PRESENT",
            "scheduled_task_name": "BOSMAX Flow Kit Local Agent Watchdog",
        }

    monkeypatch.setattr(
        local_agent,
        "_get_autostart_metadata_cached",
        _fake_autostart_metadata,
    )
    monkeypatch.setattr(local_agent, "load_registration", local_agent._default_registration)

    status = await local_agent.get_local_agent_status()

    assert status.auto_start_enabled is True
    assert status.auto_start_mode == "SCHEDULED_TASK"
    assert status.auto_start_warning == "STALE_STARTUP_SHORTCUT_PRESENT"
    assert status.task_name == "BOSMAX Flow Kit Local Agent Watchdog"


@pytest.mark.asyncio
async def test_extension_self_test_endpoint_surfaces_backend_dashboard_and_extension_payload(
    monkeypatch,
    tmp_path,
):
    class _FakeFlowClient:
        connected = True

        async def get_status(self, probe_timeout=5):
            return {"state": "idle", "flowKeyPresent": True}

        async def get_extension_self_test(self, mode="F2V", attempt_open_project=False):
            return {
                "ok": True,
                "extension_id": "flowkit-test-extension-id",
                "runner_loaded": True,
                "runner_api_keys": ["runFlowJob"],
                "page_diagnostic": {
                    "content_build_id": "flowkit-google-flow-phase1a-2026-05-23",
                },
                "mode": mode,
                "attempt_open_project": attempt_open_project,
            }

    dist_dir = tmp_path / "dashboard" / "dist"
    dist_dir.mkdir(parents=True)
    index_file = dist_dir / "index.html"
    index_file.write_text("<html><body>Flow Kit</body></html>", encoding="utf-8")
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "index-audit.js").write_text("console.log('audit');", encoding="utf-8")

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client",
        lambda: _FakeFlowClient(),
    )
    monkeypatch.setattr(
        local_agent,
        "get_dashboard_paths",
        lambda: (dist_dir, index_file),
    )
    monkeypatch.setattr(
        local_agent,
        "get_dashboard_serving_mode",
        lambda: "BACKEND_SERVED_STATIC",
    )

    payload = await local_agent.get_local_agent_extension_self_test(
        mode="F2V",
        attempt_open_project=True,
    )

    assert payload["backend"]["base_dir"]
    assert payload["backend"]["db_path"].endswith(".db")
    assert payload["dashboard"]["index_exists"] is True
    assert payload["dashboard"]["index_sha1"]
    assert payload["dashboard"]["asset_manifest"][0]["name"] == "index-audit.js"
    assert payload["extension_status"]["state"] == "idle"
    assert payload["extension_self_test"]["runner_loaded"] is True
    assert payload["extension_self_test"]["attempt_open_project"] is True


class _FakeBuildProofFlowClient:
    connected = True

    async def get_extension_self_test(self, mode="F2V", attempt_open_project=False):
        return {
            "connected": True,
            "agentConnected": True,
            "flow_tab_found": True,
            "background_build_id": "flowkit-test-build",
            "content_build_id": "flowkit-test-build",
            "build_match": True,
            "timestamp": "2026-06-28T15:13:06Z",
        }

    async def execute_flow_job(self, _job):
        raise AssertionError("live dispatch must not run in gate tests")


async def _seed_package_and_product():
    db = await get_db()
    product_id = "de3ee6bd-592b-4228-bf96-f2cdcf15e78c"
    await db.execute(
        "INSERT OR IGNORE INTO product "
        "(id, raw_product_title, product_display_name, product_short_name, image_url, asset_status, "
        "category, subcategory, type, product_type, silo, trigger_id, formula, copywriting_angle, claim_risk_level, "
        "physics_class, recommended_grip, handling_notes, camera_handling_notes, scene_context, camera_style, "
        "camera_behavior, camera_shot, section_4_hint, section_5_physics_hint, section_6_copy_hint, section_9_overlay_hint) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            product_id,
            "Test Diaper Pack",
            "Test Diaper Pack",
            "Diapers",
            "http://example.com/test.jpg",
            "DOWNLOADED",
            "Baby Care",
            "Diapering",
            "Pants",
            "STEALTH",
            "baby_care_universal_01",
            "TRUST_01",
            "PAS",
            "Trust-led framing",
            "LOW",
            "soft_pack",
            "two-hand hold",
            "stable handling",
            "clean reveal",
            "nursery shelf",
            "product close-up",
            "slow push-in",
            "hero shot",
            "reveal hint",
            "physics hint",
            "copy hint",
            "overlay hint",
        ),
    )
    await db.commit()
    await crud.create_or_replace_workspace_execution_package(
        "wep_1fc9b182d3b352e6",
        product_id=product_id,
        mode="F2V",
        duration_seconds=8,
        aspect_ratio="9:16",
        model="Veo 3.1 - Lite",
        manual_override=False,
        prompt_text="Vertical 9:16 prompt",
        prompt_fingerprint="fp-test",
        prompt_package_snapshot_id="pps-test",
        asset_slots=json.dumps([]),
        resolved_assets=json.dumps([]),
        readiness="READY",
        execution_allowed=True,
        production_generation_allowed=False,
        manual_fallback="[]",
        blockers="[]",
        request_lineage_payload=json.dumps({}),
        source_of_truth_notes="test",
    )
    return product_id


async def _insert_request_and_telemetry(
    request_id: str,
    *,
    request_status: str,
    request_type: str = "MANUAL_FLOW_JOB",
    telemetry_status: str | None = None,
    google_flow_stage: str | None = None,
    extension_stage: str | None = None,
    failed_at: str | None = None,
    completed_at: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
):
    db = await get_db()
    now = crud._now()
    await db.execute(
        "INSERT INTO request (id, type, status, error_message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, request_type, request_status, None, now, now),
    )
    if telemetry_status:
        await db.execute(
            """
            INSERT INTO request_telemetry (
                request_id, request_type, status, google_flow_stage, extension_stage,
                failed_at, completed_at, error_code, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                request_type,
                telemetry_status,
                google_flow_stage,
                extension_stage,
                failed_at,
                completed_at,
                error_code,
                error_message,
            ),
        )
    await db.commit()


@pytest.mark.asyncio
async def test_gfv2_trigger_dry_run_reconciles_stale_failed_row(monkeypatch):
    product_id = await _seed_package_and_product()
    await _insert_request_and_telemetry(
        "gfv2psd-legacy-failed",
        request_status="PROCESSING",
        telemetry_status="FAILED",
        google_flow_stage="FAILED",
        extension_stage="FAILED",
        failed_at="2026-06-28T14:30:50Z",
        error_code="ERR_F2V_OPTION_VIDEO_NOT_FOUND",
        error_message="ERR_F2V_OPTION_VIDEO_NOT_FOUND",
    )

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client",
        lambda: _FakeBuildProofFlowClient(),
    )
    monkeypatch.setattr(
        "agent.services.build_proof.read_canonical_build_id",
        lambda _base_dir: "flowkit-test-build",
    )
    monkeypatch.setattr(
        "agent.services.build_proof.evaluate_build_proof",
        lambda *_args, **_kwargs: type(
            "_Verdict",
            (),
            {"ok": True, "verdict": "PASS", "reason": None},
        )(),
    )

    payload = await local_agent.post_gfv2_post_submit_download(
        local_agent.Gfv2PostSubmitDownloadRequest(
            workspace_execution_package_id="wep_1fc9b182d3b352e6",
            product_id=product_id,
            confirm_live_credit_burn=False,
        )
    )

    assert payload["verdict"] == "DRY_RUN"
    assert payload["active_job_count"] == 0
    assert payload["reconciliation"]["reconciled_count"] == 1
    assert (
        payload["reconciliation"]["reconciled_rows"][0]["request_id"]
        == "gfv2psd-legacy-failed"
    )


@pytest.mark.asyncio
async def test_gfv2_trigger_gate_still_blocks_real_active_row(monkeypatch):
    product_id = await _seed_package_and_product()
    await _insert_request_and_telemetry(
        "gfv2psd-real-active",
        request_status="PROCESSING",
        telemetry_status="PROCESSING",
        google_flow_stage="GFV2_POST_SUBMIT_DOWNLOAD_DISPATCHED",
        extension_stage="GFV2_POST_SUBMIT_DOWNLOAD_DISPATCHED",
    )

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client",
        lambda: _FakeBuildProofFlowClient(),
    )
    monkeypatch.setattr(
        "agent.services.build_proof.read_canonical_build_id",
        lambda _base_dir: "flowkit-test-build",
    )
    monkeypatch.setattr(
        "agent.services.build_proof.evaluate_build_proof",
        lambda *_args, **_kwargs: type(
            "_Verdict",
            (),
            {"ok": True, "verdict": "PASS", "reason": None},
        )(),
    )

    payload = await local_agent.post_gfv2_post_submit_download(
        local_agent.Gfv2PostSubmitDownloadRequest(
            workspace_execution_package_id="wep_1fc9b182d3b352e6",
            product_id=product_id,
            confirm_live_credit_burn=False,
        )
    )

    assert payload["verdict"] == "REJECT"
    assert payload["reason"] == "ACTIVE_JOB_EXISTS"
    assert payload["active_job_count"] == 1
