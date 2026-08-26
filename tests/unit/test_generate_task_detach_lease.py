"""Regression: an operation-lease id inherited via asyncio context copy from a
parent request (e.g. faceless profile certification) must not leak into a
dispatched generation task. `_run_generate_task` detaches it up front so the
task establishes its own lease instead of failing on the parent's released one.
"""
from agent.services.flow_client import FlowClient


async def test_inherited_released_lease_blocks_bind_without_detach():
    client = FlowClient()
    # Simulate inheritance: the parent request activated this lease id, then
    # released the lease before this task runs (no live lease record remains).
    client._active_operation_lease_id.set("inherited-released-lease")
    sel = await client.bind_flow_session(project_id=None)
    assert sel["ok"] is False
    assert sel["primary_blocker"] == "ERR_OPERATION_LEASE_NOT_ACTIVE"


async def test_detach_clears_inherited_lease_so_bind_proceeds():
    client = FlowClient()
    client._active_operation_lease_id.set("inherited-released-lease")
    client.detach_inherited_operation_lease()
    # The inherited id is cleared...
    assert (client._active_operation_lease_id.get() or "") == ""
    # ...so bind no longer trips the stale-lease guard; with no registered
    # connections it falls through to the transport blocker instead.
    sel = await client.bind_flow_session(project_id=None)
    assert sel["primary_blocker"] != "ERR_OPERATION_LEASE_NOT_ACTIVE"
    assert sel["primary_blocker"] == "EXTENSION_BRIDGE_NOT_CONNECTED"
