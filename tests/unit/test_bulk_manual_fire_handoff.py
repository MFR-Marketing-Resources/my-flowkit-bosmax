"""Unit contracts for operator-assisted, non-firing bulk result reconciliation."""
import asyncio
import json

import pytest

from agent.services import workspace_generation_package_service as svc


def _row(index: int, *, status: str = "QUEUED", job_id: str | None = None, result: dict | None = None):
    identity = {
        "bulk_fanout_item": {
            "bulk_run_id": "bulk_1", "item_index": index,
            "copy_variant_id": f"copy_{index}", "dialogue_fingerprint": f"fp_{index}",
            "logical_mode": "T2V", "source_mode": "T2V",
        }
    }
    if result:
        identity["operator_manual_fire_result"] = result
    return {
        "workspace_generation_package_id": f"wgp_{index}", "production_status": status,
        "production_job_id": job_id, "generation_identity_json": json.dumps(identity),
        "manual_handoff_json": json.dumps({"final_prompt_text": f"prompt {index}", "upload_order": []}),
        "selected_assets_json": "{}", "mode": "T2V", "source_lane": "T2V",
    }


def _install(monkeypatch, rows, *, duration_in_config: int | None = 8, dry_duration: int | None = None):
    config = {
        "model": "Veo 3.1 - Lite", "aspect": "9:16",
        "last_dry_run_report": {"ready": len(rows), "blocked": 0, "items": [
            {"package_id": row["workspace_generation_package_id"], "ok": True,
             **({"duration_s": dry_duration} if dry_duration is not None else {})}
            for row in rows
        ]},
    }
    if duration_in_config is not None:
        config["duration_seconds"] = duration_in_config
    run = {
        "production_run_id": "prun_1",
        "config_json": json.dumps(config),
    }
    writes = []

    async def _run(_): return run
    async def _rows(**_): return rows
    async def _update_wgp(wgp_id, **kw): writes.append(("wgp", wgp_id, kw))
    async def _update_run(run_id, **kw): writes.append(("run", run_id, kw))
    monkeypatch.setattr(svc.crud, "get_production_run", _run)
    monkeypatch.setattr(svc.crud, "list_production_queue_packages", _rows)
    monkeypatch.setattr(svc.crud, "update_workspace_generation_package", _update_wgp)
    monkeypatch.setattr(svc.crud, "update_production_run", _update_run)
    return writes


def test_handoff_exposes_exact_per_item_manual_instructions(monkeypatch):
    _install(monkeypatch, [_row(0), _row(1)])
    out = asyncio.run(svc.get_bulk_manual_fire_handoff("prun_1"))
    assert out["state"] == "MANUAL_FIRE_HANDOFF_READY"
    assert out["automated_bulk_live"] == "DISABLED"
    assert out["provider_calls"] == out["flow_calls"] == 0
    assert out["items"][1]["workspace_generation_package_id"] == "wgp_1"
    assert out["items"][1]["copy_variant_id"] == "copy_1"
    assert out["items"][1]["prompt"] == "prompt 1"
    assert out["items"][1]["expected"]["duration_seconds"] == 8


def test_handoff_uses_dry_run_duration_when_queue_config_omits_it(monkeypatch):
    _install(monkeypatch, [_row(0), _row(1)], duration_in_config=None, dry_duration=8)
    out = asyncio.run(svc.get_bulk_manual_fire_handoff("prun_1"))
    assert [item["expected"]["duration_seconds"] for item in out["items"]] == [8, 8]


def test_result_binding_requires_matching_identity_and_persists_evidence(monkeypatch):
    writes = _install(monkeypatch, [_row(0), _row(1)])
    out = asyncio.run(svc.bind_bulk_manual_fire_result(
        production_run_id="prun_1", workspace_generation_package_id="wgp_0",
        copy_variant_id="copy_0", dialogue_fingerprint="fp_0", provider_job_id="job_0",
        flow_media_id=None, result_url="https://example.test/video", result_file_id=None, notes="checked",
    ))
    assert out["status"] == "MANUAL_RESULT_REPORTED"
    assert out["provider_calls"] == out["flow_calls"] == 0
    assert writes[0][2]["production_status"] == "MANUAL_RESULT_REPORTED"
    assert json.loads(writes[0][2]["generation_identity_json"])["operator_manual_fire_result"]["provider_job_id"] == "job_0"


def test_result_binding_preserves_omitted_optional_evidence_as_null(monkeypatch):
    writes = _install(monkeypatch, [_row(0), _row(1)])
    asyncio.run(svc.bind_bulk_manual_fire_result(
        production_run_id="prun_1", workspace_generation_package_id="wgp_0",
        copy_variant_id="copy_0", dialogue_fingerprint="fp_0", provider_job_id="job_0",
        flow_media_id=None, result_url=None, result_file_id=None, notes=None,
    ))
    evidence = json.loads(writes[0][2]["generation_identity_json"])["operator_manual_fire_result"]
    assert evidence["provider_job_id"] == "job_0"
    for field in ("flow_media_id", "result_url", "result_file_id", "notes"):
        assert evidence[field] is None


def test_result_binding_rejects_wrong_item_duplicate_and_missing_result(monkeypatch):
    _install(monkeypatch, [_row(0), _row(1, result={"provider_job_id": "job_taken"})])
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        asyncio.run(svc.bind_bulk_manual_fire_result(
            production_run_id="prun_1", workspace_generation_package_id="wgp_0",
            copy_variant_id="copy_1", dialogue_fingerprint="fp_1", provider_job_id="job_x",
            flow_media_id=None, result_url=None, result_file_id=None, notes=None,
        ))
    with pytest.raises(ValueError, match="DUPLICATE_PROVIDER_JOB"):
        asyncio.run(svc.bind_bulk_manual_fire_result(
            production_run_id="prun_1", workspace_generation_package_id="wgp_0",
            copy_variant_id="copy_0", dialogue_fingerprint="fp_0", provider_job_id="job_taken",
            flow_media_id=None, result_url=None, result_file_id=None, notes=None,
        ))
    with pytest.raises(ValueError, match="RESULT_ID_REQUIRED"):
        asyncio.run(svc.bind_bulk_manual_fire_result(
            production_run_id="prun_1", workspace_generation_package_id="wgp_0",
            copy_variant_id="copy_0", dialogue_fingerprint="fp_0", provider_job_id=None,
            flow_media_id=None, result_url=None, result_file_id=None, notes=None,
        ))
