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
