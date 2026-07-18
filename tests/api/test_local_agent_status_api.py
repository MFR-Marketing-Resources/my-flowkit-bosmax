import asyncio
import json
import subprocess
import time

import pytest

from agent import main as agent_main
from agent.api import local_agent


@pytest.fixture(autouse=True)
def _reset_autostart_cache():
    """The autostart metadata cache is module-level; reset it around every test so a
    value cached by one test never leaks into another."""
    local_agent._AUTOSTART_CACHE.update({"value": None, "expires_at": 0.0})
    yield
    local_agent._AUTOSTART_CACHE.update({"value": None, "expires_at": 0.0})


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

        async def get_status(self, timeout=5):
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


@pytest.mark.asyncio
async def test_get_local_agent_status_uses_fail_fast_extension_timeout(monkeypatch):
    observed = {"timeout": None}

    class _FakeFlowClient:
        connected = True

        async def get_status(self, timeout=5):
            observed["timeout"] = timeout
            return {"state": "idle"}

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client",
        lambda: _FakeFlowClient(),
    )
    monkeypatch.setattr(local_agent, "_inspect_autostart_metadata", lambda: local_agent._autostart_metadata_defaults())
    monkeypatch.setattr(local_agent, "load_registration", local_agent._default_registration)

    await local_agent.get_local_agent_status()

    assert observed["timeout"] == local_agent.LOCAL_AGENT_EXTENSION_STATUS_TIMEOUT_SECONDS


def test_superseded_socket_disconnect_preserves_current_extension_bridge():
    class _FakeClient:
        def __init__(self, active_socket):
            self._extension_ws = active_socket
            self.clear_calls = 0

        def clear_extension(self):
            self.clear_calls += 1
            self._extension_ws = None

    stale_socket = object()
    active_socket = object()
    client = _FakeClient(active_socket)

    assert agent_main._clear_extension_if_current(client, stale_socket) is False
    assert client._extension_ws is active_socket
    assert client.clear_calls == 0

    assert agent_main._clear_extension_if_current(client, active_socket) is True
    assert client._extension_ws is None
    assert client.clear_calls == 1


# ── Event-loop safety: the autostart inspector must never block the loop ───
#
# /api/local-agent/status is polled by the dashboard. The inspector spawns
# PowerShell (~1-3s); running it synchronously on the event loop starved every
# other request (incl. /health) and made the dashboard read the agent offline.
# The route now offloads it via asyncio.to_thread and caches the result.


@pytest.mark.asyncio
async def test_autostart_metadata_is_cached_within_ttl(monkeypatch):
    calls = {"n": 0}

    def _counting_inspect():
        calls["n"] += 1
        return {"enabled": True, "mode": "SCHEDULED_TASK", "warning": None,
                "scheduled_task_name": "X"}

    monkeypatch.setattr(local_agent, "_inspect_autostart_metadata", _counting_inspect)

    first = await local_agent._get_autostart_metadata_cached()
    second = await local_agent._get_autostart_metadata_cached()

    assert first == second
    assert calls["n"] == 1  # second poll served from cache — no second PowerShell spawn


@pytest.mark.asyncio
async def test_autostart_cache_refreshes_after_expiry(monkeypatch):
    calls = {"n": 0}

    def _counting_inspect():
        calls["n"] += 1
        return local_agent._autostart_metadata_defaults()

    monkeypatch.setattr(local_agent, "_inspect_autostart_metadata", _counting_inspect)

    await local_agent._get_autostart_metadata_cached()
    local_agent._AUTOSTART_CACHE["expires_at"] = 0.0  # force expiry
    await local_agent._get_autostart_metadata_cached()

    assert calls["n"] == 2  # expired cache re-inspects


@pytest.mark.asyncio
async def test_status_route_keeps_event_loop_responsive_during_slow_inspect(monkeypatch):
    """A slow (blocking) inspector must NOT stall the event loop — a concurrent
    heartbeat keeps ticking because the inspect runs in a worker thread."""
    class _FakeFlowClient:
        connected = True

        async def get_status(self, timeout=5):
            return {"state": "idle"}

    monkeypatch.setattr(
        "agent.services.flow_client.get_flow_client", lambda: _FakeFlowClient()
    )
    monkeypatch.setattr(local_agent, "load_registration", local_agent._default_registration)

    def _slow_inspect():
        time.sleep(0.3)  # blocking, like the real PowerShell spawn
        return local_agent._autostart_metadata_defaults()

    monkeypatch.setattr(local_agent, "_inspect_autostart_metadata", _slow_inspect)

    ticks = {"n": 0}

    async def _heartbeat():
        for _ in range(10):
            await asyncio.sleep(0.03)
            ticks["n"] += 1

    hb = asyncio.ensure_future(_heartbeat())
    status = await local_agent.get_local_agent_status()
    await hb

    # If the route had blocked the loop for the full 0.3s inspect, the heartbeat
    # could not have ticked during it. Offloaded → the loop kept running.
    assert ticks["n"] >= 3
    assert status.auto_start_mode == "DISABLED"
