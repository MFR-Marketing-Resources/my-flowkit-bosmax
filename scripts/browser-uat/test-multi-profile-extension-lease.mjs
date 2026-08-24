#!/usr/bin/env node

import { spawnSync } from "node:child_process";

const scenario = String.raw`
import asyncio
import json

from agent.db import crud
from agent.services.flow_client import FlowClient
from agent.services import make_video


class QueueWebSocket:
    def __init__(self, name):
        self.name = name
        self.sent = asyncio.Queue()
        self.methods = []

    async def send(self, payload):
        message = json.loads(payload)
        self.methods.append(message.get("method"))
        await self.sent.put(message)


def check(condition, code):
    if not condition:
        raise AssertionError(code)


async def mark_ready(client, connection_id, installation_id, session_id, build):
    accepted = await client.handle_message(
        {
            "type": "extension_ready",
            "connection_id": connection_id,
            "installation_id": installation_id,
            "extension_session_id": session_id,
            "extension_build": build,
            "extension_id": "provider-free-extension",
            "flowKeyPresent": False,
        },
        connection_id=connection_id,
    )
    check(accepted is True, "EXTENSION_READY_REJECTED")
    await asyncio.sleep(0)


def response_payload(method, params, identity):
    project_id = identity["project_id"]
    flow_tab_id = identity["flow_tab_id"]
    flow_url = f"https://labs.google/fx/tools/flow/project/{project_id}"
    if method == "get_status":
        return {
            "connected": True,
            "connection_id": identity["connection_id"],
            "installation_id": identity["installation_id"],
            "extension_session_id": identity["extension_session_id"],
            "extension_build": identity["extension_build"],
            "flowKeyPresent": True,
        }
    if method == "HARVEST_VIDEO_URLS":
        return {
            "ok": True,
            "connection_id": identity["connection_id"],
            "installation_id": identity["installation_id"],
            "extension_session_id": identity["extension_session_id"],
            "flow_tab_found": True,
            "flow_tab_id": flow_tab_id,
            "flow_url": flow_url,
            "flow_project_id": project_id,
            "handled_flow_tab_id": flow_tab_id,
            "handled_flow_url": flow_url,
            "handled_flow_project_id": project_id,
            "envelope_flow_tab_id": flow_tab_id,
            "envelope_flow_url": flow_url,
            "diag": {
                "projectId": project_id,
                "flowUrl": flow_url,
                "videoIds": [],
                "imageIds": [],
                "mediaIds": [],
            },
        }
    if method == "FLOW_PAGE_STATE_DIAGNOSTIC":
        return {
            "ok": True,
            "content_script_loaded": True,
            "content_script_alive": True,
            "same_extension_session": True,
            "visible_error_markers": [],
            "build_match": True,
            "editor_capability_ready": True,
        }
    if method == "FLOW_PROVIDER_SESSION_CHALLENGE":
        return {
            "ok": True,
            "challenge_nonce": params.get("nonce"),
            "extension_session_id": identity["extension_session_id"],
            "extension_build": identity["extension_build"],
            "extension_build_match": True,
            "flow_tab_id": flow_tab_id,
            "flow_project_id": project_id,
            "flow_project_url": flow_url,
            "content_script_alive": True,
            "same_flow_tab": True,
        }
    raise AssertionError(f"UNEXPECTED_OUTBOUND_METHOD:{method}")


async def service_exact_messages(client, websocket, connection_id, identity, task, count=4):
    seen = []
    for _ in range(count):
        message = await asyncio.wait_for(websocket.sent.get(), timeout=2)
        method = message.get("method")
        seen.append(method)
        accepted = await client.handle_message(
            {
                "id": message["id"],
                "result": response_payload(method, message.get("params") or {}, identity),
            },
            connection_id=connection_id,
        )
        check(accepted is True, f"OWNED_REPLY_REJECTED:{method}")
    result = await asyncio.wait_for(task, timeout=2)
    return result, seen


async def main():
    client = FlowClient()

    async def provider_free_tier_sync():
        return None

    client._sync_tier = provider_free_tier_sync
    websocket_a = QueueWebSocket("profile-a")
    websocket_b = QueueWebSocket("profile-b")
    secret_a = "provider-free-secret-a"
    secret_b = "provider-free-secret-b"
    connection_a = client.register_extension_connection(
        websocket_a,
        connection_id="connection-a1",
        callback_secret=secret_a,
        installation_id="installation-a",
        extension_session_id="session-a1",
    )
    await mark_ready(
        client, connection_a, "installation-a", "session-a1", "build-lease-v1"
    )
    lease_a = client.acquire_operation_lease(installation_id="installation-a")

    connection_b = client.register_extension_connection(
        websocket_b,
        connection_id="connection-b1",
        callback_secret=secret_b,
        installation_id="installation-b",
        extension_session_id="session-b1",
    )
    await mark_ready(
        client, connection_b, "installation-b", "session-b1", "build-lease-v1"
    )

    async def send_owned_probe():
        with client.activate_operation_lease(lease_a):
            return await client._send("get_status", {}, timeout=2)

    probe_task = asyncio.create_task(send_owned_probe())
    probe_message = await asyncio.wait_for(websocket_a.sent.get(), timeout=2)
    check(websocket_b.sent.empty(), "PROFILE_B_RECEIVED_PROFILE_A_PROBE")
    cross_ws_accepted = await client.handle_message(
        {"id": probe_message["id"], "result": {"ok": True}},
        connection_id=connection_b,
    )
    check(cross_ws_accepted is False, "PROFILE_B_WS_REPLY_ACCEPTED")
    wrong_callback = client.resolve_extension_callback(
        secret_b,
        {"id": probe_message["id"], "result": {"ok": True}},
    )
    check(
        wrong_callback.get("reason") == "request_owner_mismatch",
        "PROFILE_B_CALLBACK_REPLY_ACCEPTED",
    )
    right_callback = client.resolve_extension_callback(
        secret_a,
        {
            "id": probe_message["id"],
            "result": response_payload(
                "get_status",
                {},
                {
                    "connection_id": connection_a,
                    "installation_id": "installation-a",
                    "extension_session_id": "session-a1",
                    "extension_build": "build-lease-v1",
                    "flow_tab_id": 41,
                    "project_id": "project-a",
                },
            ),
        },
    )
    check(right_callback.get("resolved") is True, "PROFILE_A_CALLBACK_NOT_RESOLVED")
    await asyncio.wait_for(probe_task, timeout=2)

    identity_a = {
        "connection_id": connection_a,
        "installation_id": "installation-a",
        "extension_session_id": "session-a1",
        "extension_build": "build-lease-v1",
        "flow_tab_id": 41,
        "project_id": "project-a",
    }

    async def bind_profile_a():
        with client.activate_operation_lease(lease_a):
            return await make_video._bind_editor_session(
                client,
                "project-a",
                bridge_lease=lease_a,
            )

    bind_task = asyncio.create_task(bind_profile_a())
    binding_a, bind_methods = await service_exact_messages(
        client, websocket_a, connection_a, identity_a, bind_task
    )
    bound_a = binding_a["bridge_lease"]
    check(bound_a.get("connection_id") == connection_a, "PROFILE_A_CONNECTION_NOT_BOUND")
    check(bound_a.get("installation_id") == "installation-a", "PROFILE_A_INSTALLATION_NOT_BOUND")
    check(bound_a.get("extension_session_id") == "session-a1", "PROFILE_A_SESSION_NOT_BOUND")
    check(bound_a.get("flow_tab_id") == 41, "PROFILE_A_TAB_NOT_BOUND")
    check(bound_a.get("flow_project_id") == "project-a", "PROFILE_A_PROJECT_NOT_BOUND")
    try:
        client.bind_operation_lease(bound_a, installation_id="installation-b")
    except ValueError as exc:
        check(
            "ERR_OPERATION_LEASE_BINDING_MISMATCH:installation_id" in str(exc),
            "WRONG_BINDING_MISMATCH_ERROR",
        )
    else:
        raise AssertionError("PROFILE_B_TUPLE_BOUND_TO_PROFILE_A_LEASE")

    sent_a_before_ambiguity = websocket_a.sent.qsize()
    sent_b_before_ambiguity = websocket_b.sent.qsize()
    ambiguous = await client._send("get_status", {}, timeout=0.1)
    check(
        ambiguous.get("error") == "ERR_EXTENSION_CONNECTION_AMBIGUOUS",
        "UNQUALIFIED_MULTI_PROFILE_REQUEST_DID_NOT_FAIL_AMBIGUOUS",
    )
    check(websocket_a.sent.qsize() == sent_a_before_ambiguity, "AMBIGUOUS_REQUEST_SENT_TO_A")
    check(websocket_b.sent.qsize() == sent_b_before_ambiguity, "AMBIGUOUS_REQUEST_SENT_TO_B")

    persisted_lease = dict(bound_a)
    client.release_operation_lease(bound_a)
    check(
        client.unregister_extension_connection(connection_a, websocket=websocket_a),
        "PROFILE_A_DISCONNECT_FAILED",
    )
    try:
        client.acquire_operation_lease(installation_id="installation-a")
    except ConnectionError as exc:
        check(
            str(exc) == "ERR_EXTENSION_CONNECTION_NOT_FOUND",
            "PROFILE_A_ABSENCE_WRONG_ERROR",
        )
    else:
        raise AssertionError("PROFILE_B_TAKEN_OVER_FOR_MISSING_PROFILE_A")

    websocket_a2 = QueueWebSocket("profile-a-reconnect")
    connection_a2 = client.register_extension_connection(
        websocket_a2,
        connection_id="connection-a2",
        callback_secret="provider-free-secret-a2",
        installation_id="installation-a",
        extension_session_id="session-a2",
    )
    await mark_ready(
        client, connection_a2, "installation-a", "session-a2", "build-lease-v1"
    )
    identity_a2 = {
        "connection_id": connection_a2,
        "installation_id": "installation-a",
        "extension_session_id": "session-a2",
        "extension_build": "build-lease-v1",
        "flow_tab_id": 73,
        "project_id": "project-a",
    }

    job_id = "g_provider_free_reconnect"
    state = {
        "job_id": job_id,
        "status": "GENERATED_BUT_UNRETRIEVED",
        "mode": "T2V",
        "project_id": "project-a",
        "provider_operation_ids": ["operations/provider-free-handle"],
        "provider_generation_submit_count": 1,
        "bridge_lease": {**persisted_lease, "released": True},
    }
    row = {
        "job_id": job_id,
        "status": state["status"],
        "project_id": "project-a",
        "initial_operation_id": "operations/provider-free-handle",
        "stage_state_json": json.dumps(state),
    }
    persisted_snapshots = []
    provider_boundary_invocations = 0

    async def get_video_job(actual_job_id):
        check(actual_job_id == job_id, "WRONG_DURABLE_JOB_READ")
        return row

    async def sync_video_job(job):
        snapshot = make_video._durable_single_snapshot(job)
        persisted_snapshots.append(snapshot)
        row["status"] = job.get("status")
        row["stage_state_json"] = json.dumps(snapshot)
        return True

    async def provider_free_poll_boundary(bound_client, handles):
        nonlocal provider_boundary_invocations
        provider_boundary_invocations += 1
        active_lease_id = bound_client._active_operation_lease_id.get()
        active_lease = bound_client._operation_leases.get(str(active_lease_id or ""))
        check(active_lease is not None, "PROVIDER_BOUNDARY_HAS_NO_ACTIVE_LEASE")
        check(
            active_lease.get("installation_id") == "installation-a",
            "PROVIDER_BOUNDARY_ROTATED_INSTALLATION",
        )
        check(
            active_lease.get("connection_id") == connection_a2,
            "PROVIDER_BOUNDARY_ROTATED_CONNECTION",
        )
        check(
            handles == [{"operation": {"name": "operations/provider-free-handle"}}],
            "DURABLE_PROVIDER_HANDLE_CHANGED",
        )
        return {"state": "PENDING", "data": {}}

    original_get = crud.get_video_production_job
    original_sync = make_video._sync_durable_single_job
    original_client = make_video.get_flow_client
    original_poll = make_video._check_direct_operations_once
    crud.get_video_production_job = get_video_job
    make_video._sync_durable_single_job = sync_video_job
    make_video.get_flow_client = lambda: client
    make_video._check_direct_operations_once = provider_free_poll_boundary
    make_video._DURABLE_RECOVERY_LOCKS.clear()
    try:
        reconcile_task = asyncio.create_task(
            make_video.reconcile_durable_single_job(job_id)
        )
        recovered, reconnect_methods = await service_exact_messages(
            client, websocket_a2, connection_a2, identity_a2, reconcile_task
        )
    finally:
        crud.get_video_production_job = original_get
        make_video._sync_durable_single_job = original_sync
        make_video.get_flow_client = original_client
        make_video._check_direct_operations_once = original_poll
        make_video._DURABLE_RECOVERY_LOCKS.clear()

    check(provider_boundary_invocations == 1, "RECOVERY_BOUNDARY_NOT_REACHED_ONCE")
    check(recovered.get("status") == "RECOVERY_REQUIRED", "PENDING_RECOVERY_STATUS_CHANGED")
    check(websocket_b.sent.empty(), "PROFILE_B_RECEIVED_PROFILE_A_RECOVERY_COMMAND")
    check(
        any(
            snapshot.get("bridge_lease", {}).get("connection_id") == connection_a2
            and snapshot.get("bridge_lease", {}).get("extension_session_id") == "session-a2"
            and snapshot.get("bridge_lease", {}).get("flow_tab_id") == 73
            and snapshot.get("bridge_lease", {}).get("flow_project_id") == "project-a"
            for snapshot in persisted_snapshots
        ),
        "RECONNECTED_LEASE_NOT_DURABLE_BEFORE_PROVIDER_BOUNDARY",
    )

    allowed_methods = {
        "get_status",
        "HARVEST_VIDEO_URLS",
        "FLOW_PAGE_STATE_DIAGNOSTIC",
        "FLOW_PROVIDER_SESSION_CHALLENGE",
    }
    all_methods = [
        method
        for method in (
            websocket_a.methods + websocket_b.methods + websocket_a2.methods
        )
        if method
    ]
    provider_methods = [method for method in all_methods if method not in allowed_methods]
    check(provider_methods == [], f"PROVIDER_METHOD_EMITTED:{provider_methods}")
    check(
        bind_methods == [
            "HARVEST_VIDEO_URLS",
            "FLOW_PAGE_STATE_DIAGNOSTIC",
            "get_status",
            "FLOW_PROVIDER_SESSION_CHALLENGE",
        ],
        f"INITIAL_BIND_SEQUENCE_CHANGED:{bind_methods}",
    )
    check(
        reconnect_methods == bind_methods,
        f"RECONNECT_BIND_SEQUENCE_CHANGED:{reconnect_methods}",
    )

    report = {
        "schema": "bosmax-extension-lease-harness/1",
        "verdict": "PASS",
        "marker": "PROVIDER_FREE_EXTENSION_LEASE_HARNESS_PASS",
        "provider_call_delta": 0,
        "credit_spend": False,
        "cases": {
            "profile_a_profile_b_isolation": "PASS",
            "cross_connection_ws_reply_rejected": "PASS",
            "cross_connection_callback_rejected": "PASS",
            "unqualified_ambiguity_fails_closed": "PASS",
            "missing_installation_does_not_fall_through": "PASS",
            "same_installation_reconnect_rechallenged": "PASS",
            "restart_lease_persisted_before_provider_boundary": "PASS",
            "provider_methods_emitted": 0,
        },
    }
    print(json.dumps(report, sort_keys=True))


asyncio.run(main())
`;

const candidates = process.platform === "win32"
  ? [
      { command: "python", args: ["-"] },
      { command: "py", args: ["-3", "-"] },
    ]
  : [
      { command: "python3", args: ["-"] },
      { command: "python", args: ["-"] },
    ];

let execution = null;
for (const candidate of candidates) {
  const attempt = spawnSync(candidate.command, candidate.args, {
    cwd: process.cwd(),
    input: scenario,
    encoding: "utf8",
    maxBuffer: 8 * 1024 * 1024,
  });
  if (!attempt.error || attempt.error.code !== "ENOENT") {
    execution = attempt;
    break;
  }
}

if (!execution) {
  throw new Error("Python runtime not found for provider-free lease harness");
}
if (execution.status !== 0) {
  process.stderr.write(execution.stderr || "");
  process.stderr.write(execution.stdout || "");
  process.exit(execution.status ?? 1);
}

const lines = (execution.stdout || "")
  .split(/\r?\n/u)
  .map((line) => line.trim())
  .filter(Boolean);
const report = JSON.parse(lines.at(-1));
if (
  report.verdict !== "PASS" ||
  report.marker !== "PROVIDER_FREE_EXTENSION_LEASE_HARNESS_PASS" ||
  report.provider_call_delta !== 0 ||
  report.credit_spend !== false
) {
  throw new Error(`Lease harness reported a non-green result: ${JSON.stringify(report)}`);
}

console.log(JSON.stringify(report, null, 2));
console.log("PROVIDER_FREE_EXTENSION_LEASE_HARNESS_PASS");
