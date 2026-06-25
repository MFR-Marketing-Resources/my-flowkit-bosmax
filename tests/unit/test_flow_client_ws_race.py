from unittest.mock import MagicMock

import pytest

from agent.services.flow_client import FlowClient


@pytest.mark.asyncio
async def test_stale_disconnect_error_clears_after_extension_ready():
    client = FlowClient()
    stale_ws = MagicMock(name="stale_ws")
    healthy_ws = MagicMock(name="healthy_ws")

    client.set_extension(stale_ws)
    client.clear_extension(stale_ws)

    stale_snapshot = client._build_status_snapshot()
    assert stale_snapshot["error"] == "Extension disconnected"

    client.set_extension(healthy_ws)
    await client.handle_message({"type": "extension_ready", "flowKeyPresent": True})

    healed_snapshot = client._build_status_snapshot()
    assert healed_snapshot["connected"] is True
    assert healed_snapshot["ws_connected"] is True
    assert healed_snapshot["state"] == "idle"
    assert "error" not in healed_snapshot


@pytest.mark.asyncio
async def test_stale_disconnect_error_clears_after_token_captured():
    client = FlowClient()
    stale_ws = MagicMock(name="stale_ws")
    healthy_ws = MagicMock(name="healthy_ws")

    client.set_extension(stale_ws)
    client.clear_extension(stale_ws)

    stale_snapshot = client._build_status_snapshot()
    assert stale_snapshot["error"] == "Extension disconnected"

    client.set_extension(healthy_ws)
    await client.handle_message({"type": "token_captured", "flowKey": "fk_test"})

    healed_snapshot = client._build_status_snapshot()
    assert healed_snapshot["connected"] is True
    assert healed_snapshot["ws_connected"] is True
    assert healed_snapshot["state"] == "idle"
    assert healed_snapshot["flowKeyPresent"] is True
    assert "error" not in healed_snapshot
