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

        async def get_status(self):
            return {"state": "idle"}

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client",
        lambda: _FakeFlowClient(),
    )
    monkeypatch.setattr(
        local_agent,
        "_inspect_autostart_metadata",
        lambda: {
            "enabled": True,
            "mode": "SCHEDULED_TASK",
            "warning": "STALE_STARTUP_SHORTCUT_PRESENT",
            "scheduled_task_name": "BOSMAX Flow Kit Local Agent Watchdog",
        },
    )
    monkeypatch.setattr(local_agent, "load_registration", local_agent._default_registration)

    status = await local_agent.get_local_agent_status()

    assert status.auto_start_enabled is True
    assert status.auto_start_mode == "SCHEDULED_TASK"
    assert status.auto_start_warning == "STALE_STARTUP_SHORTCUT_PRESENT"
    assert status.task_name == "BOSMAX Flow Kit Local Agent Watchdog"
