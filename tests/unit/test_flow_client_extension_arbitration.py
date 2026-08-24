"""Provider-free proofs for multi-instance Flow extension arbitration."""

from __future__ import annotations

import json

import pytest

from agent.services.flow_client import FlowClient


PROJECT_A = "project-a"
PROJECT_B = "project-b"
BUILD = "flowkit-canonical-dom-guard-2026-07-13a"


@pytest.fixture(autouse=True)
def db_setup():
    """This matrix is transport-only and must not acquire the shared DB fixture."""
    yield


class _FakeSocket:
    def __init__(self, client: FlowClient, session_id: str, *, project_id: str | None,
                 tab_id: int, build: str = BUILD, content_build: str = BUILD,
                 challenge_ok: bool = True, content_alive: bool = True,
                 protocol: str = "FLOWKIT_DOM_V1"):
        self.client = client
        self.session_id = session_id
        self.project_id = project_id
        self.tab_id = tab_id
        self.build = build
        self.content_build = content_build
        self.challenge_ok = challenge_ok
        self.content_alive = content_alive
        self.protocol = protocol
        self.messages: list[dict] = []

    async def send(self, raw: str):
        message = json.loads(raw)
        self.messages.append(message)
        method = message.get("method")
        if method == "FLOW_PROVIDER_SESSION_CHALLENGE":
            params = message.get("params") or {}
            project_id = self.project_id
            result = {
                "ok": self.challenge_ok,
                "extension_session_id": self.session_id,
                "extension_id": f"extension-{self.session_id}",
                "extension_version": "0.2.0",
                "extension_build": self.build,
                "flow_tab_found": bool(project_id),
                "flow_tab_id": self.tab_id if project_id else None,
                "flow_url": f"https://labs.google/fx/tools/flow/project/{project_id}"
                if project_id else "https://labs.google/fx/tools/flow",
                "flow_project_url": f"https://labs.google/fx/tools/flow/project/{project_id}"
                if project_id else None,
                "flow_project_id": project_id,
                "content_script_alive": self.content_alive,
                "content_script_loaded": self.content_alive,
                "content_build_id": self.content_build,
                "content_script_protocol_version": self.protocol,
                "extension_build_match": self.build == self.content_build,
                "challenge_nonce": params.get("nonce"),
                "challenge_verified": self.challenge_ok,
                "same_extension_session": True,
                "same_flow_tab": bool(project_id),
            }
            await self.client.handle_message(
                {"id": message["id"], "result": result}, websocket=self
            )
        elif method == "get_status":
            await self.client.handle_message(
                {
                    "id": message["id"],
                    "result": {
                        "connected": True,
                        "flowKeyPresent": True,
                        "extension_session_id": self.session_id,
                        "extension_id": f"extension-{self.session_id}",
                        "extension_build": self.build,
                    },
                },
                websocket=self,
            )


async def _register(client: FlowClient, socket: _FakeSocket):
    client.set_extension(socket)
    client.register_extension_identity(
        socket,
        {
            "extension_session_id": socket.session_id,
            "extension_id": f"extension-{socket.session_id}",
            "extension_version": "0.2.0",
            "extension_build": socket.build,
            "background_build_id": socket.build,
            "flowKeyPresent": True,
        },
    )


@pytest.mark.asyncio
async def test_one_healthy_instance_is_selected_and_reports_identity():
    client = FlowClient()
    socket = _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11)
    await _register(client, socket)

    status = await client.get_status()
    assert status["extension_session_id"] == "session-a"
    assert client.ws_stats["active_extension_session_id"] == "session-a"
    assert len(socket.messages) == 1


@pytest.mark.asyncio
async def test_target_project_selects_a_and_b_cannot_steal_it():
    client = FlowClient()
    socket_a = _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11)
    socket_b = _FakeSocket(client, "session-b", project_id=PROJECT_A, tab_id=22)
    await _register(client, socket_a)
    binding = await client.bind_flow_session(project_id=PROJECT_A)
    await _register(client, socket_b)

    assert binding["ok"] is True
    assert binding["extension_session_id"] == "session-a"
    assert client.ws_stats["pinned_extension_session_id"] == "session-a"
    result = await client.get_status()
    assert result["extension_session_id"] == "session-a"
    assert not any(message.get("method") == "get_status" for message in socket_b.messages)


@pytest.mark.asyncio
async def test_build_and_content_build_must_match_on_same_session():
    client = FlowClient()
    socket = _FakeSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
        content_build="wrong-content-build",
    )
    await _register(client, socket)

    result = await client.bind_flow_session(project_id=PROJECT_A)
    assert result["ok"] is False
    assert result["primary_blocker"] == "EXTENSION_BUILD_MISMATCH"
    assert client.ws_stats["pinned_extension_session_id"] is None


@pytest.mark.asyncio
async def test_two_matching_instances_fail_closed_as_ambiguous():
    client = FlowClient()
    await _register(client, _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11))
    await _register(client, _FakeSocket(client, "session-b", project_id=PROJECT_A, tab_id=22))

    result = await client.bind_flow_session(project_id=PROJECT_A)
    assert result["ok"] is False
    assert result["primary_blocker"] == "AMBIGUOUS"
    assert client.ws_stats["active_extension_session_id"] is None
    assert client.ws_stats["pinned_extension_session_id"] is None


@pytest.mark.asyncio
async def test_no_open_editor_is_not_recovered_by_another_socket():
    client = FlowClient()
    socket = _FakeSocket(client, "session-a", project_id=None, tab_id=11)
    await _register(client, socket)

    result = await client.bind_flow_session(project_id=PROJECT_A)
    assert result["ok"] is False
    assert result["primary_blocker"] == "NO_OPEN_EDITOR"
    assert client.ws_stats["pinned_extension_session_id"] is None


@pytest.mark.asyncio
async def test_pinned_a_disconnects_fail_closed_without_promoting_b():
    client = FlowClient()
    socket_a = _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11)
    socket_b = _FakeSocket(client, "session-b", project_id=PROJECT_B, tab_id=22)
    await _register(client, socket_a)
    binding = await client.bind_flow_session(project_id=PROJECT_A)
    await _register(client, socket_b)
    client.clear_extension_socket(socket_a)

    result = await client.get_status()
    rebound = await client.bind_flow_session(project_id=PROJECT_A)
    assert result["error"] == "PINNED_EXTENSION_SESSION_DISCONNECTED"
    assert rebound["primary_blocker"] == "PINNED_EXTENSION_SESSION_DISCONNECTED"
    assert client.ws_stats["pinned_extension_session_id"] == "session-a"
    assert not any(message.get("method") == "get_status" for message in socket_b.messages)
    assert not any(
        message.get("method") == "FLOW_PROVIDER_SESSION_CHALLENGE"
        for message in socket_b.messages
    )
    assert binding["extension_session_id"] == "session-a"


@pytest.mark.asyncio
async def test_stale_socket_for_same_session_cannot_clear_reconnected_pin():
    client = FlowClient()
    socket_old = _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11)
    await _register(client, socket_old)
    binding = await client.bind_flow_session(project_id=PROJECT_A)

    socket_new = _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11)
    await _register(client, socket_new)
    client.clear_extension_socket(socket_old)

    result = await client.get_status()
    assert result["extension_session_id"] == "session-a"
    assert client.ws_stats["pinned_extension_session_id"] == "session-a"
    assert client.ws_stats["last_arbitration_error"] is None
    assert any(message.get("method") == "get_status" for message in socket_new.messages)
    assert binding["extension_session_id"] == "session-a"


@pytest.mark.asyncio
async def test_provider_free_arbitration_emits_only_challenges_not_provider_calls():
    client = FlowClient()
    socket = _FakeSocket(client, "session-a", project_id=PROJECT_A, tab_id=11)
    await _register(client, socket)

    result = await client.bind_flow_session(project_id=PROJECT_A)
    assert result["ok"] is True
    methods = [message.get("method") for message in socket.messages]
    assert methods == ["FLOW_PROVIDER_SESSION_CHALLENGE"]
    assert all(method not in {"generate_video", "generate_video_extend"} for method in methods)
