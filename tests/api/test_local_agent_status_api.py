import json
import subprocess

import pytest

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
