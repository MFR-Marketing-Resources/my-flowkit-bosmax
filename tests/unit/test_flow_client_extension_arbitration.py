import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from agent import main as agent_main
from agent.services.flow_client import FlowClient


class _Socket:
    def __init__(self):
        self.sent: list[dict] = []
        self.sent_event = asyncio.Event()

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))
        self.sent_event.set()

    async def next_message(self) -> dict:
        await asyncio.wait_for(self.sent_event.wait(), timeout=1)
        self.sent_event.clear()
        return self.sent[-1]


def _register(client: FlowClient, socket: _Socket, name: str) -> str:
    return client.register_extension_connection(
        socket,
        connection_id=f"connection-{name}",
        callback_secret=f"secret-{name}",
        installation_id=f"installation-{name}",
        extension_session_id=f"session-{name}",
    )


@pytest.mark.asyncio
async def test_one_connection_routes_request_to_owner():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")

    request = asyncio.create_task(client._send("get_status", {}, timeout=1))
    outbound = await owner.next_message()

    assert await client.handle_message(
        {"id": outbound["id"], "result": {"state": "idle"}},
        connection_id=owner_id,
    ) is True
    assert await request == {"id": outbound["id"], "result": {"state": "idle"}}


@pytest.mark.asyncio
async def test_later_connection_cannot_steal_pending_request():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    lease = client.acquire_operation_lease(connection_id=owner_id)

    with client.activate_operation_lease(lease):
        first = asyncio.create_task(client._send("first", {}, timeout=1))
        first_outbound = await owner.next_message()
        assert await client.handle_message(
            {"id": first_outbound["id"], "result": {"step": 1}},
            connection_id=owner_id,
        ) is True
        assert (await first)["result"] == {"step": 1}

        later = _Socket()
        _register(client, later, "b")
        second = asyncio.create_task(client._send("second", {}, timeout=1))
        second_outbound = await owner.next_message()

        assert [message["method"] for message in owner.sent] == ["first", "second"]
        assert later.sent == []
        assert await client.handle_message(
            {"id": second_outbound["id"], "result": {"step": 2}},
            connection_id=owner_id,
        ) is True
        assert (await second)["result"] == {"step": 2}

    assert client.release_operation_lease(lease) is True


@pytest.mark.asyncio
async def test_cross_connection_reply_is_rejected():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")

    request = asyncio.create_task(
        client._send_on_connection(owner_id, "get_status", {}, timeout=1)
    )
    outbound = await owner.next_message()
    other = _Socket()
    other_id = _register(client, other, "b")

    assert await client.handle_message(
        {"id": outbound["id"], "result": {"state": "wrong-owner"}},
        connection_id=other_id,
    ) is False
    assert request.done() is False

    assert await client.handle_message(
        {"id": outbound["id"], "result": {"state": "idle"}},
        connection_id=owner_id,
    ) is True
    assert (await request)["result"]["state"] == "idle"


@pytest.mark.asyncio
async def test_callback_secret_is_connection_scoped():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    other = _Socket()
    _register(client, other, "b")

    request = asyncio.create_task(
        client._send_on_connection(owner_id, "get_status", {}, timeout=1)
    )
    outbound = await owner.next_message()
    callback = {"id": outbound["id"], "result": {"state": "idle"}}

    wrong = client.resolve_extension_callback("secret-b", callback)
    assert wrong["authenticated"] is True
    assert wrong["resolved"] is False
    assert wrong["reason"] == "request_owner_mismatch"
    assert request.done() is False

    unknown = client.resolve_extension_callback("not-a-secret", callback)
    assert unknown["authenticated"] is False
    assert unknown["resolved"] is False

    correct = client.resolve_extension_callback("secret-a", callback)
    assert correct["authenticated"] is True
    assert correct["resolved"] is True
    assert (await request)["result"]["state"] == "idle"


@pytest.mark.asyncio
async def test_owner_disconnect_fails_only_owner_pending():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    other = _Socket()
    other_id = _register(client, other, "b")

    owner_request = asyncio.create_task(
        client._send_on_connection(owner_id, "owner", {}, timeout=1)
    )
    other_request = asyncio.create_task(
        client._send_on_connection(other_id, "other", {}, timeout=1)
    )
    await owner.next_message()
    other_outbound = await other.next_message()

    assert client.unregister_extension_connection(owner_id, websocket=owner) is True
    owner_result = await owner_request
    assert owner_result["error"] == "ERR_EXTENSION_CONNECTION_CLOSED"
    assert other_request.done() is False

    assert await client.handle_message(
        {"id": other_outbound["id"], "result": {"state": "idle"}},
        connection_id=other_id,
    ) is True
    assert (await other_request)["result"]["state"] == "idle"
    assert client.ws_stats["connections"] == 1


@pytest.mark.asyncio
async def test_multiple_unselected_connections_fail_ambiguous():
    client = FlowClient()
    first = _Socket()
    second = _Socket()
    _register(client, first, "a")
    _register(client, second, "b")

    result = await client._send("get_status", {}, timeout=1)

    assert result == {
        "error": "ERR_EXTENSION_CONNECTION_AMBIGUOUS",
        "connection_count": 2,
    }
    assert first.sent == []
    assert second.sent == []


@pytest.mark.asyncio
async def test_compatibility_clear_preserves_real_owner_pending_and_lease():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    lease = client.acquire_operation_lease(connection_id=owner_id)
    owner_request = asyncio.create_task(
        client._send_on_connection(owner_id, "owner", {}, timeout=1)
    )
    outbound = await owner.next_message()

    synthetic = _Socket()
    synthetic_id = client.set_extension(synthetic)
    assert client.clear_extension() is True

    assert client._connection_record(synthetic_id) is None
    assert client._connection_record(owner_id)["websocket"] is owner
    assert owner_request.done() is False
    assert client._operation_leases[lease["lease_id"]]["released"] is False

    assert await client.handle_message(
        {"id": outbound["id"], "result": {"state": "idle"}},
        connection_id=owner_id,
    ) is True
    assert (await owner_request)["result"]["state"] == "idle"
    assert client.release_operation_lease(lease) is True


@pytest.mark.asyncio
async def test_legacy_callback_secret_cannot_resolve_live_pending_request(monkeypatch):
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    pending = asyncio.create_task(
        client._send_on_connection(owner_id, "owner", {}, timeout=1)
    )
    outbound = await owner.next_message()
    callback = {"id": outbound["id"], "result": {"state": "wrong-authority"}}
    body = json.dumps(callback).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ext/callback",
            "headers": [
                (b"x-callback-secret", agent_main._CALLBACK_SECRET.encode())
            ],
        },
        receive,
    )
    monkeypatch.setattr(agent_main, "get_flow_client", lambda: client)

    response = await agent_main.ext_callback(request)

    assert response.status_code == 401
    assert pending.done() is False
    assert client.resolve_extension_callback("secret-a", callback)["resolved"] is True
    assert (await pending)["result"]["state"] == "wrong-authority"


@pytest.mark.asyncio
async def test_tier_sync_skips_db_mutation_when_connection_becomes_ambiguous(monkeypatch):
    from agent.db import crud

    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    lease = client.acquire_operation_lease(connection_id=owner_id)
    update_project = AsyncMock()

    async def list_projects(*, status):
        assert status == "ACTIVE"
        _register(client, _Socket(), "b")
        return [{"id": "project-a", "user_paygate_tier": "PAYGATE_TIER_ONE"}]

    monkeypatch.setattr(crud, "list_projects", list_projects)
    monkeypatch.setattr(crud, "update_project", update_project)

    async def get_credits():
        return {"data": {"userPaygateTier": "PAYGATE_TIER_TWO"}}

    monkeypatch.setattr(client, "get_credits", get_credits)
    with client.activate_operation_lease(lease):
        await client._sync_tier()

    update_project.assert_not_awaited()
    assert client.release_operation_lease(lease) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity_override",
    [
        {"connection_id": "connection-changed"},
        {"installation_id": "installation-changed"},
        {"extension_session_id": "session-changed"},
    ],
)
async def test_live_identity_rotation_closes_only_changed_owner(identity_override):
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    other = _Socket()
    other_id = _register(client, other, "b")
    pending = asyncio.create_task(
        client._send_on_connection(owner_id, "owner", {}, timeout=1)
    )
    await owner.next_message()
    ready = {
        "type": "extension_ready",
        "connection_id": owner_id,
        "installation_id": "installation-a",
        "extension_session_id": "session-a",
    }
    ready.update(identity_override)

    assert await client.handle_message(ready, connection_id=owner_id) is False
    assert (await pending)["error"] == "ERR_EXTENSION_CONNECTION_CLOSED"
    assert client._connection_record(owner_id) is None
    assert client._connection_record(other_id)["websocket"] is other
    assert client.ws_stats["connections"] == 1


def test_nested_lease_cannot_select_different_installation_or_session():
    client = FlowClient()
    owner_id = _register(client, _Socket(), "a")
    _register(client, _Socket(), "b")
    lease = client.acquire_operation_lease(connection_id=owner_id)

    with client.activate_operation_lease(lease):
        with pytest.raises(
            ConnectionError,
            match="ERR_OPERATION_LEASE_IDENTITY_MISMATCH",
        ):
            client.acquire_operation_lease(installation_id="installation-b")
        with pytest.raises(
            ConnectionError,
            match="ERR_OPERATION_LEASE_IDENTITY_MISMATCH",
        ):
            client.acquire_operation_lease(extension_session_id="session-b")

    assert client.release_operation_lease(lease) is True


def test_diagnostics_compatibility_is_projected_from_active_lease():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    record = client._connection_record(owner_id)
    record["ready"] = True
    record["metadata"].update({
        "extension_id": "extension-a",
        "extension_version": "0.2.0",
        "extension_build": "build-a",
        "build_stamped": True,
        "build_dirty": False,
        "extension_root_url": "chrome-extension://extension-a/",
        "content_build_id": "build-a",
        "flow_tab_id": 17,
        "flow_project_id": "project-a",
        "runtime_ready": True,
        "flow_tab_found": True,
        "last_updated_at": "2026-08-25T00:00:00Z",
        "flowKeyPresent": False,
        "challenge_verified": True,
        "same_flow_tab": True,
    })
    lease = client.acquire_operation_lease(connection_id=owner_id)
    lease = client.bind_operation_lease(
        lease,
        extension_build="build-a",
        flow_tab_id=17,
        flow_project_id="project-a",
    )

    with client.activate_operation_lease(lease):
        diagnostics = client.extension_diagnostics

    assert diagnostics["ws_counts"] == {"connects": 1, "disconnects": 0}
    assert diagnostics["connects"] == 1
    assert diagnostics["disconnects"] == 0
    assert diagnostics["active_extension_session_id"] == "session-a"
    assert diagnostics["pinned_extension_session_id"] == "session-a"
    assert diagnostics["pinned_binding"] == {
        "extension_session_id": "session-a",
        "extension_id": "extension-a",
        "extension_build": "build-a",
        "content_build_id": "build-a",
        "flow_tab_id": 17,
        "project_id": "project-a",
        "flow_project_id": "project-a",
        "challenge_verified": True,
        "same_flow_tab": True,
    }
    assert diagnostics["extension_sessions"][0]["connection_id"] == owner_id
    assert diagnostics["extension_sessions"][0]["connected"] is True
    assert diagnostics["extension_sessions"][0]["build_stamped"] is True
    assert diagnostics["extension_sessions"][0]["build_dirty"] is False
    assert diagnostics["extension_sessions"][0]["extension_root_url"] == (
        "chrome-extension://extension-a/"
    )
    assert diagnostics["extension_sessions"][0]["runtime_ready"] is True
    assert diagnostics["extension_sessions"][0]["flow_tab_found"] is True
    assert diagnostics["extension_sessions"][0]["last_updated_at"] == (
        "2026-08-25T00:00:00Z"
    )
    assert diagnostics["extension_sessions"][0]["flow_key_present"] is False
    assert "secret-a" not in json.dumps(diagnostics)

    assert client.release_operation_lease(lease) is True
    released = client.extension_diagnostics
    assert released["active_extension_session_id"] == "session-a"
    assert released["pinned_extension_session_id"] is None
    assert released["pinned_binding"] == {}
    assert not hasattr(client, "_extension_sessions")
    assert client.ws_stats["connections"] == 1
    assert client.ws_stats["extension_sessions"] == released["extension_sessions"]


@pytest.mark.asyncio
async def test_get_status_failures_include_bridge_diagnostics():
    client = FlowClient()

    offline = await client.get_status()

    assert offline["bridge_diagnostics"] == client.extension_diagnostics

    _register(client, _Socket(), "a")
    client._send = AsyncMock(side_effect=[
        {"error": "ERR_TEST_STATUS"},
        {"result": "invalid"},
    ])

    errored = await client.get_status()
    invalid = await client.get_status()

    assert errored["error"] == "ERR_TEST_STATUS"
    assert errored["bridge_diagnostics"]["pinned_extension_session_id"] == "session-a"
    assert invalid["error"] == "invalid extension status payload"
    assert invalid["bridge_diagnostics"]["pinned_extension_session_id"] == "session-a"


@pytest.mark.asyncio
async def test_token_capture_updates_boolean_diagnostics_without_exposing_token():
    client = FlowClient()
    owner = _Socket()
    owner_id = _register(client, owner, "a")
    client._connection_record(owner_id)["metadata"]["flowKeyPresent"] = False
    client._sync_tier = AsyncMock()

    await client.handle_message(
        {"type": "token_captured", "flowKey": "sensitive-token"},
        connection_id=owner_id,
    )
    await asyncio.sleep(0)
    captured = client.extension_diagnostics["extension_sessions"][0]

    assert captured["flowKeyPresent"] is True
    assert captured["flow_key_present"] is True
    assert "sensitive-token" not in json.dumps(client.extension_diagnostics)

    await client.handle_message(
        {"type": "token_captured", "flowKey": ""},
        connection_id=owner_id,
    )
    await asyncio.sleep(0)
    cleared = client.extension_diagnostics["extension_sessions"][0]

    assert cleared["flowKeyPresent"] is False
    assert cleared["flow_key_present"] is False


@pytest.mark.asyncio
async def test_ambiguous_and_identity_mismatch_diagnostics_have_no_false_owner():
    ambiguous = FlowClient()
    first_id = _register(ambiguous, _Socket(), "a")
    second_id = _register(ambiguous, _Socket(), "b")
    ambiguous._connection_record(first_id)["ready"] = True
    ambiguous._connection_record(second_id)["ready"] = True

    ambiguous_status = await ambiguous.get_status()

    assert ambiguous_status["error"] == "ERR_EXTENSION_CONNECTION_AMBIGUOUS"
    assert ambiguous_status["bridge_diagnostics"]["active_connection_id"] is None
    assert ambiguous_status["bridge_diagnostics"]["pinned_binding"] == {}
    assert ambiguous.ws_stats["connections"] == 2

    mismatched = FlowClient()
    owner_id = _register(mismatched, _Socket(), "owner")
    mismatched._send = AsyncMock(return_value={
        "result": {"connection_id": "wrong-connection"}
    })

    mismatch_status = await mismatched.get_status()

    assert mismatch_status["error"] == "ERR_EXTENSION_CONNECTION_IDENTITY_MISMATCH"
    assert mismatch_status["bridge_diagnostics"]["active_connection_id"] == owner_id
    assert mismatch_status["bridge_diagnostics"]["pinned_extension_session_id"] == "session-owner"
    assert mismatch_status["bridge_diagnostics"]["connection_count"] == 1
    assert mismatched._connection_record(owner_id) is not None


def test_stale_reconnect_diagnostics_keep_highest_connection_epoch():
    client = FlowClient()
    old = _Socket()
    old_id = client.register_extension_connection(
        old,
        connection_id="connection-old",
        callback_secret="secret-old",
        installation_id="installation-a",
        extension_session_id="session-a",
    )
    new = _Socket()
    new_id = client.register_extension_connection(
        new,
        connection_id="connection-new",
        callback_secret="secret-new",
        installation_id="installation-a",
        extension_session_id="session-a",
    )
    client._connection_record(old_id)["ready"] = True
    client._connection_record(new_id)["ready"] = True

    diagnostics = client.extension_diagnostics

    assert len(diagnostics["connections"]) == 2
    assert len(diagnostics["extension_sessions"]) == 1
    assert diagnostics["extension_sessions"][0]["connection_id"] == new_id
    assert diagnostics["active_connection_id"] is None
    assert client.unregister_extension_connection(old_id, websocket=old) is True
    assert client.extension_diagnostics["active_connection_id"] == new_id


@pytest.mark.asyncio
async def test_challenge_failure_includes_bridge_diagnostics():
    client = FlowClient()

    disconnected = await client.verify_provider_session_challenge()

    assert disconnected["primary_blocker"] == "EXTENSION_BRIDGE_NOT_CONNECTED"
    assert disconnected["bridge_diagnostics"] == client.extension_diagnostics


# ---------------------------------------------------------------------------
# Project-aware PR #904 arbitration on the operation-lease registry
# ---------------------------------------------------------------------------

PROJECT_A = "project-a"
PROJECT_B = "project-b"
BUILD = "flowkit-canonical-dom-guard-2026-07-13a"


class _ProjectSocket:
    def __init__(
        self,
        client: FlowClient,
        session_id: str,
        *,
        project_id: str | None,
        tab_id: int,
        build: str = BUILD,
        content_build: str = BUILD,
        challenge_ok: bool = True,
        content_alive: bool = True,
        protocol: str = "FLOWKIT_DOM_V1",
    ):
        self.client = client
        self.session_id = session_id
        self.project_id = project_id
        self.tab_id = tab_id
        self.build = build
        self.content_build = content_build
        self.challenge_ok = challenge_ok
        self.content_alive = content_alive
        self.protocol = protocol
        self.connection_id: str | None = None
        self.messages: list[dict] = []

    async def send(self, raw: str):
        message = json.loads(raw)
        self.messages.append(message)
        method = message.get("method")
        if method == "get_status":
            result = {
                "connected": True,
                "flowKeyPresent": True,
                "connection_id": self.connection_id,
                "installation_id": f"installation-{self.session_id}",
                "extension_session_id": self.session_id,
                "extension_id": f"extension-{self.session_id}",
                "extension_version": "0.2.0",
                "extension_build": self.build,
            }
        elif method == "FLOW_PROVIDER_SESSION_CHALLENGE":
            params = message.get("params") or {}
            project_id = self.project_id
            result = {
                "ok": self.challenge_ok,
                "connection_id": self.connection_id,
                "installation_id": f"installation-{self.session_id}",
                "extension_session_id": self.session_id,
                "extension_id": f"extension-{self.session_id}",
                "extension_version": "0.2.0",
                "extension_build": self.build,
                "flow_tab_found": bool(project_id),
                "flow_tab_id": self.tab_id if project_id else None,
                "flow_url": (
                    f"https://labs.google/fx/tools/flow/project/{project_id}"
                    if project_id
                    else "https://labs.google/fx/tools/flow"
                ),
                "flow_project_url": (
                    f"https://labs.google/fx/tools/flow/project/{project_id}"
                    if project_id
                    else None
                ),
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
        else:
            return
        await self.client.handle_message(
            {"id": message["id"], "result": result},
            connection_id=self.connection_id,
        )


def _register_project_socket(client: FlowClient, socket: _ProjectSocket) -> str:
    connection_id = client.register_extension_connection(
        socket,
        connection_id=f"project-connection-{socket.session_id}-{id(socket)}",
        callback_secret=f"project-secret-{socket.session_id}-{id(socket)}",
        installation_id=f"installation-{socket.session_id}",
        extension_session_id=socket.session_id,
    )
    socket.connection_id = connection_id
    record = client._connection_record(connection_id)
    record["ready"] = True
    record["metadata"].update({
        "extension_id": f"extension-{socket.session_id}",
        "extension_version": "0.2.0",
        "extension_build": socket.build,
    })
    return connection_id


@pytest.mark.asyncio
async def test_project_aware_single_instance_returns_lease_identity():
    client = FlowClient()
    socket = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    connection_id = _register_project_socket(client, socket)

    binding = await client.bind_flow_session(project_id=PROJECT_A)

    assert binding["ok"] is True
    assert binding["connection_id"] == connection_id
    assert binding["installation_id"] == "installation-session-a"
    assert binding["extension_session_id"] == "session-a"
    assert binding["flow_tab_id"] == 11
    assert binding["flow_project_id"] == PROJECT_A


@pytest.mark.asyncio
async def test_target_project_selects_one_connection_and_lease_prevents_steal():
    client = FlowClient()
    socket_a = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    socket_b = _ProjectSocket(
        client,
        "session-b",
        project_id=PROJECT_B,
        tab_id=22,
    )
    connection_a = _register_project_socket(client, socket_a)
    _register_project_socket(client, socket_b)

    binding = await client.bind_flow_session(project_id=PROJECT_A)
    before_b = len(socket_b.messages)
    lease = client.acquire_operation_lease(
        connection_id=binding["connection_id"]
    )
    try:
        with client.activate_operation_lease(lease):
            status = await client.get_status()
    finally:
        client.release_operation_lease(lease)

    assert binding["connection_id"] == connection_a
    assert status["extension_session_id"] == "session-a"
    assert len(socket_b.messages) == before_b


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "socket_overrides",
    (
        {"content_build": "wrong-content-build"},
        {"protocol": "WRONG_PROTOCOL"},
    ),
)
async def test_project_aware_build_or_protocol_mismatch_fails_closed(
    socket_overrides,
):
    client = FlowClient()
    _register_project_socket(
        client,
        _ProjectSocket(
            client,
            "session-a",
            project_id=PROJECT_A,
            tab_id=11,
            **socket_overrides,
        ),
    )

    result = await client.bind_flow_session(project_id=PROJECT_A)

    assert result["ok"] is False
    assert result["primary_blocker"] == "EXTENSION_BUILD_MISMATCH"


@pytest.mark.asyncio
async def test_two_matching_project_connections_fail_closed_as_ambiguous():
    client = FlowClient()
    _register_project_socket(
        client,
        _ProjectSocket(client, "session-a", project_id=PROJECT_A, tab_id=11),
    )
    _register_project_socket(
        client,
        _ProjectSocket(client, "session-b", project_id=PROJECT_A, tab_id=22),
    )

    result = await client.bind_flow_session(project_id=PROJECT_A)

    assert result["ok"] is False
    assert result["primary_blocker"] == "AMBIGUOUS"


@pytest.mark.asyncio
async def test_project_aware_no_open_editor_fails_closed():
    client = FlowClient()
    _register_project_socket(
        client,
        _ProjectSocket(client, "session-a", project_id=None, tab_id=11),
    )

    result = await client.bind_flow_session(project_id=PROJECT_A)

    assert result["ok"] is False
    assert result["primary_blocker"] == "NO_OPEN_EDITOR"


@pytest.mark.asyncio
async def test_disconnected_selected_owner_is_not_replaced_inside_active_lease():
    client = FlowClient()
    socket_a = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    socket_b = _ProjectSocket(
        client,
        "session-b",
        project_id=PROJECT_B,
        tab_id=22,
    )
    connection_a = _register_project_socket(client, socket_a)
    _register_project_socket(client, socket_b)
    binding = await client.bind_flow_session(project_id=PROJECT_A)
    lease = client.acquire_operation_lease(
        connection_id=binding["connection_id"]
    )
    client.unregister_extension_connection(connection_a, websocket=socket_a)
    before_b = len(socket_b.messages)
    try:
        with client.activate_operation_lease(lease):
            status = await client.get_status()
    finally:
        client.release_operation_lease(lease)

    assert status["error"] == "ERR_EXTENSION_CONNECTION_CLOSED"
    assert len(socket_b.messages) == before_b


@pytest.mark.asyncio
async def test_stale_socket_cannot_clear_reconnected_same_identity():
    client = FlowClient()
    socket_old = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    old_connection = _register_project_socket(client, socket_old)
    first = await client.bind_flow_session(project_id=PROJECT_A)
    socket_new = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    new_connection = _register_project_socket(client, socket_new)

    assert client.unregister_extension_connection(
        old_connection,
        websocket=socket_old,
    ) is True
    rebound = await client.bind_flow_session(project_id=PROJECT_A)

    assert first["connection_id"] == old_connection
    assert rebound["ok"] is True
    assert rebound["connection_id"] == new_connection
    assert rebound["installation_id"] == "installation-session-a"


@pytest.mark.asyncio
async def test_project_arbitration_is_provider_free():
    client = FlowClient()
    socket = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    _register_project_socket(client, socket)

    result = await client.bind_flow_session(project_id=PROJECT_A)

    assert result["ok"] is True
    methods = [message.get("method") for message in socket.messages]
    assert set(methods) <= {"get_status", "FLOW_PROVIDER_SESSION_CHALLENGE"}
    assert "FLOW_PROVIDER_SESSION_CHALLENGE" in methods
    assert all(
        method not in {"generate_video", "generate_video_extend"}
        for method in methods
    )


@pytest.mark.asyncio
async def test_faceless_certification_style_operation_pins_target_and_never_touches_other():
    """Certification session-pin invariant proven at the FlowClient level.

    Mirrors what ``faceless_profile_certification`` now does: bind ONE
    project-aware owner, then run every provider-affecting call under a single
    operation lease so the non-selected connection is never touched, and fail
    closed (no provider spend) when no lease uniquely resolves the target.
    """
    client = FlowClient()
    socket_a = _ProjectSocket(
        client,
        "session-a",
        project_id=PROJECT_A,
        tab_id=11,
    )
    socket_b = _ProjectSocket(
        client,
        "session-b",
        project_id=PROJECT_B,
        tab_id=22,
    )
    connection_a = _register_project_socket(client, socket_a)
    _register_project_socket(client, socket_b)

    # 1) Project-aware selection binds exactly the target owner A.
    sel = await client.bind_flow_session(project_id=PROJECT_A)
    assert sel["ok"] is True
    assert sel["connection_id"] == connection_a
    assert sel["flow_project_id"] == PROJECT_A

    # 2) Under A's single lease a representative provider call reaches ONLY A;
    #    the other connection never receives it.
    before_b = len(socket_b.messages)
    lease = client.acquire_operation_lease(connection_id=sel["connection_id"])
    try:
        with client.activate_operation_lease(lease):
            result = await client._send(
                "upload_image",
                {"payload": "cert-representative"},
                timeout=0.1,
            )
    finally:
        client.release_operation_lease(lease)

    assert isinstance(result, dict)
    assert any(
        message.get("method") == "upload_image" for message in socket_a.messages
    )
    assert len(socket_b.messages) == before_b

    # 3) Fail closed: with both connections and no lease that uniquely resolves,
    #    the un-leased provider path refuses to pick one (no provider spend).
    a_before = len(socket_a.messages)
    b_before = len(socket_b.messages)
    ambiguous = await client._send("get_status", {}, timeout=1)
    assert ambiguous == {
        "error": "ERR_EXTENSION_CONNECTION_AMBIGUOUS",
        "connection_count": 2,
    }
    assert len(socket_a.messages) == a_before
    assert len(socket_b.messages) == b_before
