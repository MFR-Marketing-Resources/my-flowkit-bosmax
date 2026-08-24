"""Unit tests for the bound-editor-session + single-flight logic (patches A/G/H).

Pure logic — no network, no credits. Exercises _bind_editor_session fail-closed paths
and the single-flight video lane in start_generate via a fake client.
"""
import asyncio
import json
from contextlib import nullcontext

import agent.services.make_video as mv


class _FakeClient:
    def __init__(self, harvest, page_diag=None):
        self._harvest = harvest
        self._page_diag = page_diag

    async def harvest_video_urls(self, tab_id=None):
        return self._harvest

    async def flow_page_state_diagnostic(self, mode=None):
        return self._page_diag or {}


def _run(coro):
    return asyncio.run(coro)


def _harvest(project_id=None, url=None, tab_id=1, found=True, error=None):
    inner = {"flow_tab_found": found, "flow_tab_id": tab_id,
             "flow_url": url, "diag": {"projectId": project_id}}
    if error:
        inner = {"error": error}
    return {"result": inner}


def _owned_harvest(
    project_id="project-a",
    *,
    tab_id=41,
    connection_id="connection-a",
    installation_id="installation-a",
    extension_session_id="session-a",
    canonical_tab_id=None,
    envelope_tab_id=None,
):
    url = f"https://labs.google/fx/tools/flow/project/{project_id}"
    return {
        "result": {
            "connection_id": connection_id,
            "installation_id": installation_id,
            "extension_session_id": extension_session_id,
            "flow_tab_found": True,
            "flow_tab_id": tab_id if canonical_tab_id is None else canonical_tab_id,
            "flow_url": url,
            "flow_project_id": project_id,
            "handled_flow_tab_id": tab_id,
            "handled_flow_url": url,
            "handled_flow_project_id": project_id,
            "envelope_flow_tab_id": (
                tab_id if envelope_tab_id is None else envelope_tab_id
            ),
            "envelope_flow_url": url,
            "diag": {"projectId": project_id, "flowUrl": url},
        }
    }


class _LeaseClient(_FakeClient):
    connected = True

    def __init__(self, harvest=None, *, connection_id="connection-a"):
        super().__init__(harvest or _owned_harvest(connection_id=connection_id))
        self.lease = {
            "lease_id": "lease-a",
            "connection_id": connection_id,
            "connection_epoch": 7,
            "installation_id": "installation-a",
            "extension_session_id": "session-a",
            "released": False,
        }
        self.acquire_filters = []
        self.released = []

    def acquire_operation_lease(self, **filters):
        self.acquire_filters.append(filters)
        return dict(self.lease)

    def activate_operation_lease(self, lease):
        assert lease["lease_id"] == self.lease["lease_id"]
        return nullcontext(dict(self.lease))

    def bind_operation_lease(self, lease, **bindings):
        assert lease["lease_id"] == self.lease["lease_id"]
        for key, value in bindings.items():
            if value is None:
                continue
            current = self.lease.get(key)
            if current is not None and current != value:
                raise ValueError(f"ERR_OPERATION_LEASE_BINDING_MISMATCH:{key}")
            self.lease[key] = value
        return dict(self.lease)

    def release_operation_lease(self, lease):
        self.released.append(lease["lease_id"])
        return True

    async def get_status(self, timeout=5):
        return {
            "connected": True,
            "connection_id": self.lease["connection_id"],
            "connection_epoch": self.lease["connection_epoch"],
            "installation_id": self.lease["installation_id"],
            "extension_session_id": self.lease["extension_session_id"],
            "extension_build": "build-a",
        }

    async def verify_provider_session_challenge(self, flow_tab_id=None, timeout=15):
        project_id = (
            self._harvest.get("result", {}).get("handled_flow_project_id")
            or "project-a"
        )
        url = f"https://labs.google/fx/tools/flow/project/{project_id}"
        return {
            "ok": True,
            "session_challenge_verified": True,
            "extension_build_match": True,
            "extension_build": "build-a",
            "backend_connection_id": self.lease["connection_id"],
            "backend_connection_epoch": self.lease["connection_epoch"],
            "backend_installation_id": self.lease["installation_id"],
            "backend_extension_session_id": self.lease["extension_session_id"],
            "flow_tab_id": flow_tab_id,
            "flow_project_id": project_id,
            "flow_project_url": url,
            "content_script_alive": True,
            "same_extension_session": True,
            "same_flow_tab": True,
        }


class _ProductionTypedLeaseClient(_LeaseClient, mv.FlowClient):
    """FlowClient-typed double: production guards must remain active."""


def test_bind_ok():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    b = _run(mv._bind_editor_session(_FakeClient(_harvest("abc-123", url, 42))))
    assert b == {"project_id": "abc-123", "flow_tab_id": 42, "flow_project_url": url}


def test_binding_rejects_mixed_wrapper_and_handled_tab():
    client = _FakeClient(_owned_harvest(canonical_tab_id=99))
    try:
        _run(mv._bind_editor_session(client))
        assert False, "expected wrapper/handled tab mismatch"
    except RuntimeError as exc:
        assert "FLOW_BRIDGE_TAB_IDENTITY_MISMATCH" in str(exc)


def test_binding_rejects_lease_project_mismatch():
    client = _LeaseClient(_owned_harvest(project_id="project-b"))
    lease = {**client.lease, "flow_project_id": "project-a"}
    try:
        _run(mv._bind_editor_session(client, bridge_lease=lease))
        assert False, "expected lease/project mismatch"
    except RuntimeError as exc:
        assert "FLOW_BRIDGE_PROJECT_IDENTITY_MISMATCH" in str(exc)


def test_bridge_lease_persisted_before_provider_touch(monkeypatch):
    events = []
    client = _LeaseClient()
    job_id = "g_bridge_lease_persist"
    mv._JOBS.clear()
    mv._JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "stage": "queued",
        "mode": "T2V",
        "project_id": "project-a",
        "durable": True,
        "bridge_lease_required": True,
        "provider_generation_submit_count": 0,
    }

    async def sync(job):
        events.append((
            "sync",
            dict(job.get("bridge_lease") or {}),
            job.get("bridge_lease_state"),
        ))
        return True

    async def runner(actual_job_id):
        assert actual_job_id == job_id
        lease = mv._JOBS[job_id]["bridge_lease"]
        assert lease["installation_id"] == "installation-a"
        assert lease["connection_id"] == "connection-a"
        assert lease["flow_tab_id"] == 41
        assert lease["flow_project_id"] == "project-a"
        events.append(("provider", dict(lease)))

    runner.__module__ = mv.__name__

    async def release_lane(_job_id):
        return None

    monkeypatch.setattr(mv, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)
    monkeypatch.setattr(
        "agent.db.crud.release_video_generation_lane_lease", release_lane
    )
    try:
        _run(mv._run_generate_task(job_id, runner))
        provider_index = next(
            index for index, event in enumerate(events) if event[0] == "provider"
        )
        acquired_index = next(
            index for index, event in enumerate(events[:provider_index])
            if event[0] == "sync"
            and event[2] == "ACQUIRED"
            and event[1].get("connection_id") == "connection-a"
            and "extension_build" not in event[1]
        )
        connection_bound_index = next(
            index for index, event in enumerate(events[:provider_index])
            if event[0] == "sync"
            and event[2] == "CONNECTION_BOUND"
            and event[1].get("extension_build") == "build-a"
        )
        editor_bound_index = next(
            index for index, event in enumerate(events[:provider_index])
            if event[0] == "sync"
            and event[2] == "BOUND"
            and event[1].get("flow_tab_id") == 41
            and event[1].get("flow_project_id") == "project-a"
        )
        assert acquired_index < connection_bound_index < editor_bound_index < provider_index
        assert client.released == ["lease-a"]
    finally:
        mv._JOBS.clear()


def test_bridge_lease_missing_durable_row_blocks_provider(monkeypatch):
    client = _LeaseClient()
    job_id = "g_bridge_lease_missing_row"
    provider_calls = []
    mv._JOBS.clear()
    mv._JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "stage": "queued",
        "mode": "T2V",
        "project_id": "project-a",
        "durable": False,
        "bridge_lease_required": True,
        "provider_generation_submit_count": 0,
    }

    async def missing_sync(_job):
        return False

    async def runner(_actual_job_id):
        provider_calls.append("provider")

    runner.__module__ = mv.__name__

    async def release_lane(_job_id):
        return None

    monkeypatch.setattr(mv, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "_sync_durable_single_job", missing_sync)
    monkeypatch.setattr(
        "agent.db.crud.release_video_generation_lane_lease", release_lane
    )
    try:
        _run(mv._run_generate_task(job_id, runner))
        assert provider_calls == []
        assert mv._JOBS[job_id]["status"] == "FAILED"
        assert "BRIDGE_LEASE_DURABILITY_FAILED" in mv._JOBS[job_id]["error"]
        assert mv._JOBS[job_id]["bridge_lease_error"]["provider_calls"] == 0
        assert mv._JOBS[job_id]["bridge_lease_error"]["credit_spend"] is False
    finally:
        mv._JOBS.clear()


def test_external_runner_cannot_bypass_production_flow_client_lease(monkeypatch):
    class _UnavailableProductionClient(_ProductionTypedLeaseClient):
        def acquire_operation_lease(self, **_filters):
            raise ConnectionError("ERR_EXTENSION_CONNECTION_NOT_FOUND")

    client = _UnavailableProductionClient()
    job_id = "g_external_runner_production_guard"
    runner_calls = []
    mv._JOBS.clear()
    mv._JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "stage": "queued",
        "mode": "T2V",
        "project_id": "project-a",
        "durable": True,
        "bridge_lease_required": True,
        "provider_generation_submit_count": 0,
    }

    async def sync(_job):
        return True

    async def external_runner(_actual_job_id):
        runner_calls.append("provider")

    async def release_lane(_job_id):
        return None

    monkeypatch.setattr(mv, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)
    monkeypatch.setattr(
        "agent.db.crud.release_video_generation_lane_lease", release_lane
    )
    try:
        _run(mv._run_generate_task(job_id, external_runner))
        assert runner_calls == []
        assert "bridge_lease_test_seam" not in mv._JOBS[job_id]
        assert "ERR_EXTENSION_CONNECTION_NOT_FOUND" in mv._JOBS[job_id]["error"]
    finally:
        mv._JOBS.clear()


def test_legacy_extension_build_blocks_provider_before_runner(monkeypatch):
    class _LegacyBuildClient(_LeaseClient):
        async def get_status(self, timeout=5):
            status = await super().get_status(timeout=timeout)
            status["extension_build"] = "legacy"
            return status

    client = _LegacyBuildClient()
    job_id = "g_legacy_build_guard"
    runner_calls = []
    mv._JOBS.clear()
    mv._JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "stage": "queued",
        "mode": "T2V",
        "project_id": "project-a",
        "durable": True,
        "bridge_lease_required": True,
        "provider_generation_submit_count": 0,
    }

    async def sync(_job):
        return True

    async def runner(_actual_job_id):
        runner_calls.append("provider")

    runner.__module__ = mv.__name__

    async def release_lane(_job_id):
        return None

    monkeypatch.setattr(mv, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)
    monkeypatch.setattr(
        "agent.db.crud.release_video_generation_lane_lease", release_lane
    )
    try:
        _run(mv._run_generate_task(job_id, runner))
        assert runner_calls == []
        assert "FLOW_BRIDGE_BUILD_IDENTITY_INVALID" in mv._JOBS[job_id]["error"]
        assert mv._JOBS[job_id]["bridge_lease_error"] == {
            "classification": "PRE_PROVIDER",
            "provider_calls": 0,
            "credit_spend": False,
            "detail": mv._JOBS[job_id]["error"],
        }
    finally:
        mv._JOBS.clear()


def test_active_task_cancellation_during_cleanup_releases_bridge_lease(monkeypatch):
    client = _LeaseClient()
    job_id = "g_active_cleanup_cancel"
    sync_calls = 0
    runner_calls = []
    mv._JOBS.clear()
    mv._JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "stage": "queued",
        "mode": "T2V",
        "project_id": "project-a",
        "durable": True,
        "bridge_lease_required": True,
        "provider_generation_submit_count": 0,
    }

    async def sync(_job):
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 4:
            raise asyncio.CancelledError()
        return True

    async def runner(_actual_job_id):
        runner_calls.append("provider-boundary")

    runner.__module__ = mv.__name__

    async def reconcile_profile(_job):
        return None

    async def release_lane(_job_id):
        return None

    monkeypatch.setattr(mv, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)
    monkeypatch.setattr(
        mv, "_reconcile_profile_certification_task", reconcile_profile
    )
    monkeypatch.setattr(
        "agent.db.crud.release_video_generation_lane_lease", release_lane
    )
    try:
        try:
            _run(mv._run_generate_task(job_id, runner))
            assert False, "expected cleanup cancellation to propagate"
        except asyncio.CancelledError:
            pass
        assert runner_calls == ["provider-boundary"]
        assert client.released == ["lease-a"]
        assert mv._JOBS[job_id]["bridge_lease_state"] == "RELEASED"
    finally:
        mv._JOBS.clear()


def test_restart_rebinds_only_same_installation(monkeypatch):
    from agent.db import crud

    job_id = "g_bridge_restart"
    old_lease = {
        "lease_id": "old-process-lease",
        "connection_id": "connection-a1",
        "connection_epoch": 3,
        "installation_id": "installation-a",
        "extension_session_id": "session-a1",
        "extension_build": "build-a",
        "flow_tab_id": 17,
        "flow_url": "https://labs.google/fx/tools/flow/project/project-a",
        "flow_project_id": "project-a",
    }
    state = {
        "job_id": job_id,
        "status": "GENERATED_BUT_UNRETRIEVED",
        "mode": "T2V",
        "project_id": "project-a",
        "provider_operation_ids": ["operations/provider-a"],
        "provider_generation_submit_count": 1,
        "bridge_lease": old_lease,
    }
    row = {
        "job_id": job_id,
        "status": state["status"],
        "project_id": "project-a",
        "initial_operation_id": "operations/provider-a",
        "stage_state_json": json.dumps(state),
    }
    persisted = []

    class _ReconnectClient(_LeaseClient):
        def __init__(self):
            super().__init__(
                _owned_harvest(
                    connection_id="connection-a2",
                    extension_session_id="session-a2",
                ),
                connection_id="connection-a2",
            )
            self.lease["extension_session_id"] = "session-a2"
            self.poll_calls = 0

        def acquire_operation_lease(self, **filters):
            assert filters == {"installation_id": "installation-a"}
            return super().acquire_operation_lease(**filters)

        async def check_video_status(self, operations):
            self.poll_calls += 1
            assert operations == [{"operation": {"name": "operations/provider-a"}}]
            return {
                "data": {
                    "operations": [{"status": "MEDIA_GENERATION_STATUS_ACTIVE"}]
                }
            }

    client = _ReconnectClient()

    class _WrongProfileOnlyClient(_LeaseClient):
        def __init__(self):
            super().__init__(
                _owned_harvest(
                    connection_id="connection-b",
                    installation_id="installation-b",
                    extension_session_id="session-b",
                ),
                connection_id="connection-b",
            )
            self.lease["installation_id"] = "installation-b"
            self.lease["extension_session_id"] = "session-b"
            self.poll_calls = 0

        def acquire_operation_lease(self, **filters):
            self.acquire_filters.append(filters)
            raise ConnectionError("ERR_EXTENSION_CONNECTION_NOT_FOUND")

        async def check_video_status(self, _operations):
            self.poll_calls += 1
            raise AssertionError("wrong-profile provider poll must not run")

    wrong_profile = _WrongProfileOnlyClient()
    active_client = {"value": wrong_profile}

    async def get_row(actual_job_id):
        assert actual_job_id == job_id
        return row

    async def sync(job):
        snapshot = mv._durable_single_snapshot(job)
        persisted.append(snapshot)
        row["status"] = job["status"]
        row["stage_state_json"] = json.dumps(snapshot)
        return True

    monkeypatch.setattr(crud, "get_video_production_job", get_row)
    monkeypatch.setattr(mv, "get_flow_client", lambda: active_client["value"])
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)

    async def reconcile_missing_then_reconnected():
        missing = await mv.reconcile_durable_single_job(job_id)
        active_client["value"] = client
        reconnected = await mv.reconcile_durable_single_job(job_id)
        return missing, reconnected

    missing, reconnected = _run(reconcile_missing_then_reconnected())

    assert missing["status"] == "RECOVERY_REQUIRED"
    assert missing["provider_reconciliation"]["state"] == "BRIDGE_LEASE_BLOCKED"
    assert wrong_profile.acquire_filters == [
        {"installation_id": "installation-a"}
    ]
    assert wrong_profile.poll_calls == 0
    assert client.acquire_filters == [{"installation_id": "installation-a"}]
    assert client.poll_calls == 1
    assert reconnected["provider_reconciliation"]["provider_calls"] == 1
    assert any(
        snapshot.get("bridge_lease", {}).get("connection_id") == "connection-a2"
        and snapshot.get("bridge_lease", {}).get("flow_project_id") == "project-a"
        for snapshot in persisted
    )
    assert client.released == ["lease-a"]


def test_restart_rejects_cross_project_provider_handle_before_poll(monkeypatch):
    from agent.db import crud

    job_id = "g_bridge_project_custody"
    state = {
        "job_id": job_id,
        "status": "GENERATED_BUT_UNRETRIEVED",
        "mode": "F2V",
        "project_id": "project-a",
        "direct_media_targets": [
            {"name": "media-a", "projectId": "project-b"}
        ],
        "provider_generation_submit_count": 1,
        "bridge_lease": {
            "lease_id": "old-lease",
            "connection_id": "connection-a1",
            "connection_epoch": 3,
            "installation_id": "installation-a",
            "extension_session_id": "session-a1",
            "extension_build": "build-a",
            "flow_tab_id": 17,
            "flow_url": "https://labs.google/fx/tools/flow/project/project-a",
            "flow_project_id": "project-a",
        },
    }
    row = {
        "job_id": job_id,
        "status": state["status"],
        "project_id": "project-a",
        "initial_media_id": "media-a",
        "stage_state_json": json.dumps(state),
    }

    class _ProductionRecoveryClient(_ProductionTypedLeaseClient):
        def __init__(self):
            super().__init__()
            self.poll_calls = 0

        async def check_video_status(self, _operations):
            self.poll_calls += 1
            raise AssertionError("cross-project provider poll must not run")

    client = _ProductionRecoveryClient()

    async def get_row(actual_job_id):
        assert actual_job_id == job_id
        return row

    async def sync(job):
        snapshot = mv._durable_single_snapshot(job)
        row["status"] = job["status"]
        row["stage_state_json"] = json.dumps(snapshot)
        return True

    monkeypatch.setattr(crud, "get_video_production_job", get_row)
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)

    result = _run(
        mv.reconcile_durable_single_job(job_id, provider_client=client)
    )

    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["error"] == "DURABLE_PROVIDER_PROJECT_CUSTODY_MISMATCH"
    assert result["provider_reconciliation"]["provider_calls"] == 0
    assert result["provider_reconciliation"]["media_target_projects"] == [
        "project-b"
    ]
    assert client.acquire_filters == []
    assert client.poll_calls == 0


def test_restart_cancellation_releases_lease_without_reclassifying_handle(monkeypatch):
    from agent.db import crud

    job_id = "g_bridge_cancelled_recovery"
    original_status = "GENERATED_BUT_UNRETRIEVED"
    operation_id = "operations/provider-cancelled"
    state = {
        "job_id": job_id,
        "status": original_status,
        "mode": "T2V",
        "project_id": "project-a",
        "provider_operation_ids": [operation_id],
        "provider_generation_submit_count": 1,
        "bridge_lease": {
            "lease_id": "old-process-lease",
            "connection_id": "connection-a1",
            "connection_epoch": 3,
            "installation_id": "installation-a",
            "extension_session_id": "session-a1",
            "extension_build": "build-a",
            "flow_tab_id": 17,
            "flow_url": "https://labs.google/fx/tools/flow/project/project-a",
            "flow_project_id": "project-a",
        },
    }
    row = {
        "job_id": job_id,
        "status": original_status,
        "project_id": "project-a",
        "initial_operation_id": operation_id,
        "stage_state_json": json.dumps(state),
    }

    class _CancelledRecoveryClient(_ProductionTypedLeaseClient):
        async def check_video_status(self, _operations):
            raise asyncio.CancelledError()

    client = _CancelledRecoveryClient()

    async def get_row(actual_job_id):
        assert actual_job_id == job_id
        return row

    async def sync(job):
        snapshot = mv._durable_single_snapshot(job)
        row["status"] = job["status"]
        row["stage_state_json"] = json.dumps(snapshot)
        return True

    monkeypatch.setattr(crud, "get_video_production_job", get_row)
    monkeypatch.setattr(mv, "_sync_durable_single_job", sync)

    try:
        _run(mv.reconcile_durable_single_job(job_id, provider_client=client))
        assert False, "expected cancellation to propagate"
    except asyncio.CancelledError:
        pass

    persisted = json.loads(row["stage_state_json"])
    assert row["status"] == original_status
    assert [
        mv._provider_operation_name(value)
        for value in persisted["provider_operation_ids"]
    ] == [operation_id]
    assert row["initial_operation_id"] == operation_id
    assert client.released == ["lease-a"]


def test_startup_recovery_counts_only_explicit_provider_calls(monkeypatch):
    from agent.db import crud

    rows = [
        {
            "job_id": "g_bridge_blocked_sweep",
            "status": "RECOVERY_REQUIRED",
        },
        {
            "job_id": "g_bridge_polled_sweep",
            "status": "RECOVERY_REQUIRED",
        },
    ]

    async def list_rows(limit=1000):
        assert limit == 1000
        return rows

    async def reconcile(job_id, provider_client=None):
        assert provider_client is None
        provider_calls = 1 if job_id.endswith("polled_sweep") else 0
        return {
            "job_id": job_id,
            "status": "RECOVERY_REQUIRED",
            "provider_reconciliation": {
                "state": (
                    "PENDING" if provider_calls else "BRIDGE_LEASE_BLOCKED"
                ),
                "provider_calls": provider_calls,
            },
        }

    monkeypatch.setattr(crud, "list_video_production_jobs", list_rows)
    monkeypatch.setattr(mv, "reconcile_durable_single_job", reconcile)

    result = _run(mv.recover_durable_single_jobs())

    assert result["candidates"] == 2
    assert result["provider_calls"] == 1


def test_bind_no_editor_url_raises():
    # tab on Flow home (no /project/) → fail-closed
    h = _harvest("abc", "https://labs.google/fx/tools/flow")
    try:
        _run(mv._bind_editor_session(_FakeClient(h)))
        assert False, "expected NO_OPEN_EDITOR"
    except RuntimeError as e:
        assert "NO_OPEN_EDITOR" in str(e)


def test_bind_no_tab_raises():
    try:
        _run(mv._bind_editor_session(_FakeClient(_harvest(error="NO_FLOW_TAB"))))
        assert False, "expected NO_OPEN_EDITOR"
    except RuntimeError as e:
        assert "NO_OPEN_EDITOR" in str(e)


def test_bind_project_mismatch_raises():
    url = "https://labs.google/fx/tools/flow/project/real"
    try:
        _run(mv._bind_editor_session(_FakeClient(_harvest("real", url)),
                                     requested_project_id="other"))
        assert False, "expected PROJECT_TAB_MISMATCH"
    except RuntimeError as e:
        assert "PROJECT_TAB_MISMATCH" in str(e)


def test_bind_broken_editor_page_raises():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"visible_error_markers": ["Something went wrong"], "build_match": True},
    )
    try:
        _run(mv._bind_editor_session(client))
        assert False, "expected BROKEN_EDITOR_PAGE"
    except RuntimeError as e:
        assert "BROKEN_EDITOR_PAGE" in str(e)


def test_bind_tolerates_error_marker_on_usable_editor():
    # Live d80e72fd: one failed media TILE renders "Something went wrong" inside an
    # otherwise fully usable editor (composer present + editable). Binding must
    # proceed — only an UNUSABLE surface with markers is a broken page.
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"visible_error_markers": ["Something went wrong"], "build_match": True,
                   "editor_capability_ready": True,
                   "composer_found": True, "composer_editable": True},
    )
    b = _run(mv._bind_editor_session(client))
    assert b["project_id"] == "abc-123"


def test_bind_content_build_mismatch_raises():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"visible_error_markers": [], "build_match": False},
    )
    try:
        _run(mv._bind_editor_session(client))
        assert False, "expected CONTENT_BUILD_MISMATCH"
    except RuntimeError as e:
        assert "CONTENT_BUILD_MISMATCH" in str(e)


def test_bind_missing_content_script_fails_closed():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"content_script_loaded": False, "build_match": True},
    )
    try:
        _run(mv._bind_editor_session(client))
        assert False, "expected CONTENT_SCRIPT_NOT_READY"
    except RuntimeError as e:
        assert "CONTENT_SCRIPT_NOT_READY" in str(e)


def test_bind_with_recovery_opens_official_new_project_from_root():
    url = "https://labs.google/fx/tools/flow/project/new-1"
    state = {"opened": False}

    class _NewProjectClient:
        connected = True

        async def harvest_video_urls(self, tab_id=None):
            if state["opened"]:
                return _harvest("new-1", url, 11)
            return _harvest(None, "https://labs.google/fx/tools/flow", 11)

        async def flow_page_state_diagnostic(self, mode=None):
            return {"visible_error_markers": [], "build_match": True}

        async def open_flow_new_project(self, mode=None):
            assert mode == "T2V"
            state["opened"] = True
            return {"ok": True, "editor_ready": True, "flow_url": url}

    b = _run(mv._bind_with_recovery(_NewProjectClient()))
    assert b["project_id"] == "new-1"
    assert b["recovered_officially"] is True
    assert state["opened"] is True


def test_pre_provider_reconciliation_preserves_source_error_and_side_effect_proof(monkeypatch):
    from agent.db import crud

    row = {
        "job_id": "g_reconcile",
        "status": "FAILED",
        "error_code": "NO_OPEN_EDITOR: the Flow tab is not on a project editor",
        "logical_job_key": "ljk-reconcile",
        "initial_operation_id": None,
        "initial_media_id": None,
        "final_media_id": None,
        "stage_state_json": json.dumps(
            {
                "job_id": "g_reconcile",
                "status": "FAILED",
                "stage": "failed",
                "request_id": "request-reconcile",
                "provider_generation_submit_count": 0,
                "provider_operation_ids": [],
                "artifacts": [],
                "credit_state": "NOT_SPENT",
            }
        ),
    }
    updates = []
    released = []

    async def get_job(job_id):
        assert job_id == "g_reconcile"
        return row

    async def update_job(job_id, **fields):
        updates.append((job_id, fields))

    async def release(job_id):
        released.append(job_id)

    monkeypatch.setattr(crud, "get_video_production_job", get_job)
    monkeypatch.setattr(crud, "update_video_production_job_full", update_job)
    monkeypatch.setattr(crud, "release_video_generation_lane_lease", release)

    result = _run(
        mv.reconcile_pre_provider_failure(
            "g_reconcile",
            classification_code="FLOW_EDITOR_BINDING_REQUIRED",
            detail="NO_OPEN_EDITOR: the Flow tab is not on a project editor",
            request_id="request-reconcile",
        )
    )

    assert result["status"] == "FAILED"
    assert result["pre_provider_failure"]["provider_dispatch_reached"] is False
    assert result["provider_evidence"]["credit_state"] == "NOT_SPENT"
    assert released == ["g_reconcile"]
    assert updates[0][1]["status"] == "FAILED"
    persisted = json.loads(updates[0][1]["stage_state_json"])
    assert persisted["pre_provider_failure"]["error_code"] == "FLOW_EDITOR_BINDING_REQUIRED"
    assert persisted["pre_provider_failure"]["original_error_code"].startswith("NO_OPEN_EDITOR")


def test_profile_certification_marks_submitted_only_after_provider_acceptance(monkeypatch):
    events = []

    class _C:
        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "diag": {"projectId": "p1", "videoIds": ["vid-1"]}}}

        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self, tab_id=None):
            return {"ok": True}

    async def fake_bind(client, requested_project_id=None, job=None):
        events.append("binding")
        return {"project_id": "p1", "flow_tab_id": 1,
                "flow_project_url": "https://labs.google/fx/tools/flow/project/p1"}

    async def fake_approval(**kwargs):
        events.append("approval")
        assert kwargs["snapshot_id"] == "snap-profile"
        return {"pass": True, "reason": "APPROVED_ENVELOPE_MATCH"}

    async def fake_negotiate(*a, **k):
        events.append("provider")
        return {
            "approved": True,
            "model_used": "veo_3_1_lite",
            "model_ok": True,
            "duration_used": 8,
            "duration_ok": True,
            "gen_prompt": "prompt",
            "tool_call_id": "tool-1",
            "response_id": "response-1",
            "gen_seed": 1,
            "tools_seen": [],
            "gen_tool_matched": True,
        }

    async def fake_accept(*a, **k):
        return ("vid-1", "/tmp/vid-1.mp4", 1.0, {"media_id": "vid-1"})

    async def fake_record(*a, **k):
        return None

    async def fake_exclusion():
        return set()

    async def fake_submit(certification_id, *, job_id, snapshot_id):
        events.append("certification_submitted")
        assert certification_id == "pec-profile"
        assert snapshot_id == "snap-profile"
        return {"certification_id": certification_id, "status": "SUBMITTED"}

    original = (
        mv.get_flow_client,
        mv._bind_with_recovery,
        mv._verify_generation_approval,
        mv.agent_video.negotiate_and_generate,
        mv._accept_correlated_output,
        mv._record_artifacts,
        mv._durable_media_exclusion,
        mv._sync_durable_single_job,
        mv.asyncio,
    )
    from agent.services import provider_certification_service as certifications
    original_submit = certifications.mark_submitted
    mv.get_flow_client = lambda: _C()
    mv._bind_with_recovery = fake_bind
    mv._verify_generation_approval = fake_approval
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_accept
    mv._record_artifacts = fake_record
    mv._durable_media_exclusion = fake_exclusion
    mv._sync_durable_single_job = fake_record
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    certifications.mark_submitted = fake_submit
    mv._JOBS.clear()
    mv._JOBS["g_profile"] = {
        "job_id": "g_profile",
        "status": mv.PROFILE_CERTIFICATION_PRE_PROVIDER_STATUS,
        "profile_certification_capture": True,
        "profile_certification_id": "pec-profile",
        "execution_snapshot_id": "snap-profile",
        "profile_certification_context": {},
        "execution_identity": {},
        "provider_profile": None,
        "provider_operation_ids": [],
        "artifacts": [],
        "provider_generation_submit_count": 0,
        "num_videos": 1,
    }
    try:
        _run(
            mv._run_generate(
                "g_profile", "T2V", "prompt", None, None, None,
                "9:16", None, model="veo_3_1_lite", duration_s=8,
            )
        )
        assert events.index("binding") < events.index("approval") < events.index("provider")
        assert events.index("provider") < events.index("certification_submitted")
        assert mv._JOBS["g_profile"]["provider_generation_submit_count"] == 1
        assert mv._JOBS["g_profile"]["status"] == "DONE"
    finally:
        (
            mv.get_flow_client,
            mv._bind_with_recovery,
            mv._verify_generation_approval,
            mv.agent_video.negotiate_and_generate,
            mv._accept_correlated_output,
            mv._record_artifacts,
            mv._durable_media_exclusion,
            mv._sync_durable_single_job,
            mv.asyncio,
        ) = original
        certifications.mark_submitted = original_submit
        mv._JOBS.clear()


def test_bind_with_recovery_reopens_stored_project_on_drift():
    # Flow drifted the tab to home (NO_OPEN_EDITOR). Recovery re-opens the STORED project the
    # user was working in, then re-binds successfully — it must NOT mint a new project.
    url = "https://labs.google/fx/tools/flow/project/heal-1"
    state = {"opened": False}

    class _DriftClient:
        async def harvest_video_urls(self, tab_id=None):
            if state["opened"]:
                return _harvest("heal-1", url, 7)
            return _harvest(None, "https://labs.google/fx/tools/flow", 7)  # root → NO_OPEN_EDITOR

        async def flow_page_state_diagnostic(self, mode=None):
            return {"stored_flow_project_url": url, "visible_error_markers": [], "build_match": True}

        async def open_target_flow_project(self, flow_project_url):
            assert flow_project_url == url
            state["opened"] = True  # the tab navigates back to the project
            return {"ok": False, "error": "FLOW_PROJECT_EDITOR_NOT_READY"}  # false-negative, ignored

    orig = mv.asyncio
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    try:
        b = _run(mv._bind_with_recovery(_DriftClient()))
        assert b["project_id"] == "heal-1" and b["flow_project_url"] == url
        assert state["opened"] is True
    finally:
        mv.asyncio = orig


def test_bind_with_recovery_fails_closed_on_broken_editor():
    # A broken editor (not a drift) must NOT trigger re-open recovery — fail closed.
    url = "https://labs.google/fx/tools/flow/project/abc"
    client = _FakeClient(
        _harvest("abc", url, 1),
        page_diag={"visible_error_markers": ["Something went wrong"], "build_match": True},
    )
    try:
        _run(mv._bind_with_recovery(client))
        assert False, "expected BROKEN_EDITOR_PAGE (no recovery)"
    except RuntimeError as e:
        assert "BROKEN_EDITOR_PAGE" in str(e)


def test_bind_with_recovery_passthrough_when_already_bound():
    # Already on a healthy editor → bind succeeds first try, no recovery needed.
    url = "https://labs.google/fx/tools/flow/project/ok-1"
    b = _run(mv._bind_with_recovery(_FakeClient(_harvest("ok-1", url, 5))))
    assert b == {"project_id": "ok-1", "flow_tab_id": 5, "flow_project_url": url}


def test_single_flight_rejects_second_video_job():
    mv._JOBS.clear()
    mv._JOBS["g_active"] = {"status": "GENERATING", "created": mv.time.time()}
    mv._VIDEO_LANE_JOB = "g_active"
    try:
        res = _run(mv.start_generate("T2V", "x"))
        assert res.get("status") == "REJECTED"
        assert res.get("error") == "VIDEO_JOB_IN_FLIGHT"
        assert res.get("active_job") == "g_active"
    finally:
        mv._VIDEO_LANE_JOB = None
        mv._JOBS.clear()


def test_img_not_blocked_by_video_lane():
    # IMG is exempt from single-flight; it must NOT be rejected even if the lane is busy.
    # (We can't run the full IMG job without network, so assert the guard only fires for video.)
    mv._JOBS.clear()
    mv._JOBS["g_active"] = {"status": "GENERATING", "created": mv.time.time()}
    mv._VIDEO_LANE_JOB = "g_active"
    try:
        assert "IMG" not in mv._VIDEO_MODES
        assert mv._job_active("g_active") is True
    finally:
        mv._VIDEO_LANE_JOB = None
        mv._JOBS.clear()


def test_terminal_agent_failure_messages_are_stable_and_actionable():
    safety = mv._terminal_agent_failure_error(mv.agent_video.SAFETY_FILTERED)
    assert safety.startswith("FAILED_PROVIDER_SAFETY_FILTER:")
    assert "creator attribution" in safety
    assert "do not auto-retry" in safety
    assert mv._terminal_agent_failure_error("REFERENCE_IMAGE_MISSING").startswith(
        "FAILED_REFERENCE_IMAGE_MISSING:"
    )
    assert mv._terminal_agent_failure_error("RENDER_FAILED").startswith(
        "FAILED_RENDER_REPORTED_BY_AGENT:"
    )
    assert mv._terminal_agent_failure_error(None) is None


def test_gc_drops_old_finished_jobs():
    mv._JOBS.clear()
    mv._JOBS["old"] = {"status": "DONE", "created": mv.time.time() - (mv._JOB_TTL + 10)}
    mv._JOBS["fresh"] = {"status": "DONE", "created": mv.time.time()}
    mv._JOBS["running"] = {"status": "GENERATING", "created": mv.time.time() - 99999}
    mv._gc_jobs()
    assert "old" not in mv._JOBS
    assert "fresh" in mv._JOBS
    assert "running" in mv._JOBS  # never GC an active job
    mv._JOBS.clear()


def test_run_negotiate_image_prompt_branching():
    """image_prompt=None -> pure T2V dry (no start frame, media=None);
    image_prompt=<text> -> start frame generated (media=[id]). (patch I4a contract)"""
    import agent.api.flow as flowmod
    cap = {}

    async def fake_negotiate(client, pid, sid, prompt, media, **kw):
        cap["media"] = media
        return {"transcript": [], "approved": False}

    async def fake_img(*a, **k):
        cap["img_called"] = True
        return {"media": [{"name": "img-123"}]}

    class _C:
        async def create_project(self, *a):
            return {"projectId": "p1"}

        async def create_agent_session(self, *a):
            return {"sessionInfo": {"agentSessionId": "s1"}}

    orig = (mv.agent_video.negotiate_and_generate,
            flowmod._generate_image_with_recovery, mv.get_flow_client)
    mv.agent_video.negotiate_and_generate = fake_negotiate
    flowmod._generate_image_with_recovery = fake_img
    mv.get_flow_client = lambda: _C()
    try:
        mv._JOBS.clear()
        mv._JOBS["jn"] = {"status": "SUBMITTED"}
        cap.clear()
        _run(mv._run_negotiate("jn", "p", None, True, None, None, "p1"))
        assert cap.get("media") is None and "img_called" not in cap

        mv._JOBS["jt"] = {"status": "SUBMITTED"}
        cap.clear()
        _run(mv._run_negotiate("jt", "p", "make image", True, None, None, "p1"))
        assert cap.get("img_called") is True and cap.get("media") == ["img-123"]
    finally:
        (mv.agent_video.negotiate_and_generate,
         flowmod._generate_image_with_recovery, mv.get_flow_client) = orig
        mv._JOBS.clear()


class _ShimAsyncio:
    """Delegates to real asyncio but makes sleep() instant — skips the 120s render wait."""
    def __init__(self, real):
        self._real = real

    async def sleep(self, *a, **k):
        return None

    def __getattr__(self, n):
        return getattr(self._real, n)


def _setup_generate_mocks(nres):
    """Patch make_video deps so _run_generate reaches the post-approve verification without
    network or the render wait. negotiate returns `nres`; retrieval finds a video instantly."""
    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self, tab_id=None):
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "diag": {"projectId": "p1", "videoIds": ["vid-1"]}}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return nres

    async def fake_save(client, cands, exclude, correlation, stats):
        return ("vid-1", "/out/vid-1.mp4", 1.0,
                {"media_id": "vid-1", "matched_on": "submitted_prompt"})

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._accept_correlated_output, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_save
    mv.asyncio = _ShimAsyncio(mv.asyncio)

    def restore():
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._accept_correlated_output, mv.asyncio) = orig
    return restore


def _gen(job_id, nres):
    mv._JOBS.clear()
    mv._JOBS[job_id] = {"status": "SUBMITTED"}
    restore = _setup_generate_mocks(nres)
    try:
        _run(mv._run_generate(job_id, "T2V", "p", "p1", None, None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        return dict(mv._JOBS[job_id])
    finally:
        restore()
        mv._JOBS.clear()


def test_duration_mismatch_hard_fails():  # DUR-3
    job = _gen("jd", {"approved": True, "model_ok": True, "duration_ok": False,
                      "model_used": "veo_3_1_r2v_lite", "duration_used": 4})
    assert job["status"] == "FAILED"
    assert "FAILED_WRONG_DURATION" in job["error"]


def test_duration_match_completes():  # DUR-2
    job = _gen("jm", {"approved": True, "model_ok": True, "duration_ok": True,
                      "model_used": "veo_3_1_r2v_lite", "duration_used": 8})
    assert job["status"] == "DONE"
    assert job.get("duration_used") == 8
    assert job.get("model_ok") is True and job.get("duration_ok") is True   # fully exposed
    assert "duration_unverified" not in job and "model_unverified" not in job


def test_duration_absent_marks_unverified_not_fail():  # DUR-4
    job = _gen("ju", {"approved": True, "model_ok": True, "duration_ok": None,
                      "model_used": "veo_3_1_r2v_lite", "duration_used": None})
    assert job["status"] == "DONE"               # absent duration is NOT a hard fail
    assert job.get("duration_unverified") is True
    assert "model_unverified" not in job         # model WAS verified, only duration absent


def test_unrecognized_tool_marks_both_unverified():
    # An unrecognized generation tool → model AND duration both unknown (None). NOT a hard fail,
    # but both flags are set + model_ok/duration_ok exposed, so it is never reported as verified.
    job = _gen("jx", {"approved": True, "model_ok": None, "duration_ok": None,
                      "model_used": None, "duration_used": None})
    assert job["status"] == "DONE"
    assert job.get("model_unverified") is True and job.get("duration_unverified") is True
    assert job.get("model_ok") is None and job.get("duration_ok") is None


def test_wrong_model_still_hard_fails():  # regression: FAILED_WRONG_MODEL preserved
    job = _gen("jw", {"approved": True, "model_ok": False, "duration_ok": True,
                      "model_used": "omni", "duration_used": 8})
    assert job["status"] == "FAILED"
    assert "FAILED_WRONG_MODEL" in job["error"]


# --- GENERATED_BUT_UNRETRIEVED false-negative fix ---------------------------------------------

def _setup_generate_mocks_custom(nres, harvest_result, save_result=(None, None, None)):
    """Like _setup_generate_mocks but with a CUSTOM harvest result and save outcome, so we can
    drive the retrieval phase into a lost-tab (EDITOR_TAB_LOST) vs a successful harvest."""
    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def harvest_video_urls(self, tab_id=None):
            return harvest_result

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return nres

    async def fake_save(client, cands, exclude, correlation, stats):
        return (*save_result, {"media_id": save_result[0],
                               "matched_on": "submitted_prompt"} if save_result[0] else None)

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._accept_correlated_output, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_save
    mv.asyncio = _ShimAsyncio(mv.asyncio)

    def restore():
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._accept_correlated_output, mv.asyncio) = orig
    return restore


def _gen2(job_id, nres, harvest_result, save_result=(None, None, None)):
    mv._JOBS.clear()
    mv._JOBS[job_id] = {"status": "SUBMITTED"}
    restore = _setup_generate_mocks_custom(nres, harvest_result, save_result)
    try:
        _run(mv._run_generate(job_id, "T2V", "p", "p1", None, None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        return dict(mv._JOBS[job_id])
    finally:
        restore()
        mv._JOBS.clear()


def test_generate_marks_generated_but_unretrieved_on_editor_tab_lost_after_approval():
    # approved + reached GENERATING, then harvest reports the bound tab is gone → the video was
    # likely generated (credits likely spent) but unretrieved. Must NOT be a plain FAILED.
    nres = {"approved": True, "model_ok": True, "duration_ok": True,
            "model_used": "veo_3_1_r2v_lite", "duration_used": 8}
    job = _gen2("jg", nres, {"result": {"error": "BOUND_TAB_GONE"}})
    assert job["status"] == "GENERATED_BUT_UNRETRIEVED"
    assert job.get("media_id") is None
    assert job.get("local_path") is None
    assert job.get("artifact") is None
    assert job.get("credit_spent_likely") is True
    assert job.get("recovery_required") is True
    assert job.get("recovery_hint")
    assert "EDITOR_TAB_LOST" in (job.get("original_error") or "")


def test_generate_keeps_failed_for_preapproval_error():
    # The agent did not approve → failure happens BEFORE rendering. Stays plain FAILED.
    nres = {"approved": False, "error": "agent declined"}
    job = _gen2("jf", nres,
                {"result": {"flow_tab_found": True, "flow_tab_id": 1, "diag": {"projectId": "p1"}}})
    assert job["status"] == "FAILED"
    assert job["status"] != "GENERATED_BUT_UNRETRIEVED"
    # C-4: a pre-approval failure now AFFIRMS no credit instead of leaving the
    # field absent (absence was the ambiguity that made this unreadable).
    assert job.get("credit_spent_likely") is False
    assert job.get("credit_state") == "NOT_SPENT"
    assert "approve" in (job.get("error") or "").lower()


def test_generate_done_when_video_retrieved():
    # Successful harvest + saved mp4 → DONE preserved with real media_id / local_path.
    nres = {"approved": True, "model_ok": True, "duration_ok": True,
            "model_used": "veo_3_1_r2v_lite", "duration_used": 8}
    harvest = {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                          "diag": {"projectId": "p1", "videoIds": ["vid-1"]}}}
    job = _gen2("jd2", nres, harvest, save_result=("vid-1", "/out/vid-1.mp4", 1.0))
    assert job["status"] == "DONE"
    assert job.get("media_id") == "vid-1"
    assert job.get("local_path") == "/out/vid-1.mp4"
    assert job.get("artifact") == "video"


def test_retrieval_reloads_stale_tab_and_never_claims_preexisting_video():
    # Two live-proven retrieval invariants in one flow:
    # 1. Omni/V2 editor DOM does not live-update (g_01b041b563dc): the finished video
    #    only becomes harvestable after a tab reload — filed under imageIds — so the
    #    loop must reload the bound tab periodically.
    # 2. A video that ALREADY existed in the project before this job (g_745e95ede679
    #    false-DONE: claimed the previous run's mp4 at try 1) must NEVER be accepted —
    #    the pre-poll snapshot puts it in the exclude set.
    state = {"reloads": 0}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self, tab_id=None):
            state["reloads"] += 1
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            # 'old-video' is visible from the very first (snapshot) harvest; the fresh
            # render only surfaces after a reload — and lands in imageIds, not videoIds.
            diag = {"projectId": "p1", "videoIds": [], "mediaIds": [],
                    "imageIds": ["old-video"]}
            if state["reloads"]:
                diag["imageIds"] = ["old-video", "fresh-video"]
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1, "diag": diag}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return {"approved": True, "model_ok": True, "duration_ok": True,
                "model_used": "veo_3_1_r2v_lite", "duration_used": 8}

    async def fake_save(client, cands, exclude, correlation, stats):
        usable = [m for m in cands if m not in exclude]
        assert "old-video" not in usable, "pre-existing video must be excluded from retrieval"
        if "fresh-video" in usable:
            return ("fresh-video", "/out/v.mp4", 1.9,
                    {"media_id": "fresh-video", "matched_on": "submitted_prompt"})
        return (None, None, None, None)

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._accept_correlated_output, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_save
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["jr"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("jr", "T2V", "p", "p1", None, None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        job = dict(mv._JOBS["jr"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._accept_correlated_output, mv.asyncio) = orig
        mv._JOBS.clear()

    assert state["reloads"] >= 1          # the loop refreshed the stale tab
    assert job["status"] == "DONE"        # and retrieved the video that surfaced after it
    assert job.get("media_id") == "fresh-video"
    assert job.get("media_id") != "old-video"   # never the pre-existing one
    assert job.get("preexisting_media_excluded") == 1
    assert job.get("artifact") == "video"


def test_retrieval_probe_fails_fast_on_reference_image_missing():
    # A dead start media gets APPROVED but the render dies server-side; the project
    # stays empty and the agent explains only in chat (live: Faris' screenshots).
    # The retrieval loop must probe the agent session and fail FAST with the true
    # cause instead of blind-polling to the 12-minute timeout.
    probes = {"count": 0}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self, tab_id=None):
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "diag": {"projectId": "p1", "videoIds": [],
                                        "imageIds": [], "mediaIds": []}}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return {"approved": True, "model_ok": True, "duration_ok": True,
                "model_used": "veo_3_1_r2v_lite", "duration_used": 8, "turns_used": 4}

    async def fake_save(client, cands, exclude, correlation, stats):
        return (None, None, None, None)

    async def fake_probe(client, project_id, session_id, turn_number):
        probes["count"] += 1
        assert session_id == "s1" and turn_number >= 5
        return {"classification": "REFERENCE_IMAGE_MISSING",
                "agent_text": "trouble accessing the reference image",
                "turn_number": turn_number + 1}

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._accept_correlated_output,
            mv.agent_video.probe_render_failure, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_save
    mv.agent_video.probe_render_failure = fake_probe
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["jp"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("jp", "F2V", "p", "p1", ["ref-1"], None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        job = dict(mv._JOBS["jp"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._accept_correlated_output,
         mv.agent_video.probe_render_failure, mv.asyncio) = orig
        mv._JOBS.clear()

    assert probes["count"] == 1                       # probed at try 9, not after timeout
    assert job["status"] == "FAILED"                  # honest fail-fast, not UNRETRIEVED
    assert "FAILED_REFERENCE_IMAGE_MISSING" in (job.get("error") or "")
    assert "re-upload" in (job.get("error") or "")


def test_retrieval_collects_user_count_videos():
    # count=2: retrieval must bring home BOTH videos, expose them on job.artifacts,
    # and only then report DONE. Artifact records must be written for each.
    recorded = []

    state = {"reloads": 0}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self, tab_id=None):
            state["reloads"] += 1
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            # Empty at snapshot time; both fresh renders surface after a reload.
            ids = ["vid-A", "vid-B"] if state["reloads"] else []
            diag = {"projectId": "p1", "videoIds": ids, "imageIds": [], "mediaIds": []}
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1, "diag": diag}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        assert k.get("desired_num") == 2, "user count must reach the negotiation"
        return {"approved": True, "model_ok": True, "duration_ok": True,
                "model_used": "veo_3_1_r2v_lite", "duration_used": 8}

    async def fake_save(client, cands, exclude, correlation, stats):
        usable = [m for m in cands if m not in exclude]
        if usable:
            return (usable[0], f"/out/{usable[0]}.mp4", 1.5,
                    {"media_id": usable[0], "matched_on": "submitted_prompt"})
        return (None, None, None, None)

    async def fake_record(job, mode, artifacts):
        recorded.extend(a["media_id"] for a in artifacts)

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._accept_correlated_output,
            mv._record_artifacts, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_save
    mv._record_artifacts = fake_record
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["jc"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("jc", "F2V", "p", "p1", ["ref-1"], None, "16:9", None,
                              model="veo_3_1_lite", duration_s=8, num_videos=2))
        job = dict(mv._JOBS["jc"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._accept_correlated_output,
         mv._record_artifacts, mv.asyncio) = orig
        mv._JOBS.clear()

    assert job["status"] == "DONE"
    ids = [a["media_id"] for a in job.get("artifacts") or []]
    assert ids == ["vid-A", "vid-B"]          # BOTH videos retrieved
    assert recorded == ["vid-A", "vid-B"]     # and registered in the system library
    assert job.get("partial") is not True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")


def test_fastfail_identity_mismatch_waits_for_a_reload_then_fails_non_successfully():
    """Owner Phase-1: a completed candidate rejected for the SAME deterministic
    identity reason every poll (immutable stored metadata — the incident's 31
    identical rejections) must exit early as CURRENT_OUTPUT_IDENTITY_MISMATCH,
    classified GENERATED_BUT_UNRETRIEVED, instead of blind-polling 36 rounds."""
    calls = {"accept": 0}
    nres = {"ok": True, "approved": True, "generation_started": True,
            "model_used": "veo_3_1_r2v_lite", "model_ok": True,
            "duration_used": 8, "duration_ok": True, "turns_used": 2,
            "agent_text": "ok", "gen_prompt": "tool prompt", "gen_seed": None,
            "tool_call_id": "t", "response_id": "r"}

    async def fake_accept(client, cands, exclude, correlation, stats):
        calls["accept"] += 1
        stats["round_rejected_ids"] = ["decoy-completed-clip"]
        stats["prompt_mismatched"] += 1
        return (None, None, None, None)

    mv._JOBS.clear()
    mv._JOBS["g_ff"] = {"status": "SUBMITTED"}
    restore = _setup_generate_mocks(nres)
    orig_accept = mv._accept_correlated_output
    mv._accept_correlated_output = fake_accept
    try:
        _run(mv._run_generate("g_ff", "F2V", "p", "p1",
                              ["aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"], None,
                              "9:16", None, model="veo_3_1_lite", duration_s=8))
        job = dict(mv._JOBS["g_ff"])
    finally:
        mv._accept_correlated_output = orig_accept
        restore()
        mv._JOBS.clear()

    assert job["status"] == "STALE_OR_FOREIGN_CANDIDATES_ONLY"
    assert "CURRENT_OUTPUT_IDENTITY_MISMATCH" in str(job.get("original_error"))
    assert "prompt_mismatched" in str(job.get("original_error"))
    # It only exits after the completed set survived a later tab reload, still
    # well below the 36-poll blind ceiling.
    assert calls["accept"] < 12
    assert job.get("correlation_stats", {}).get("prompt_mismatched", 0) >= 3


def test_fastfail_waits_through_the_reload_blind_band():
    """A stale candidate first exposed by reload one cannot stop polling before reload two."""
    state = {"reloads": 0, "rejections": 0}
    nres = {"ok": True, "approved": True, "generation_started": True,
            "model_used": "veo_3_1_r2v_lite", "model_ok": True,
            "duration_used": 8, "duration_ok": True, "turns_used": 2,
            "gen_prompt": "tool prompt", "tool_call_id": "t", "response_id": "r"}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self, tab_id=None):
            state["reloads"] += 1
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            ids = ["foreign-completed"] if state["reloads"] else []
            return {"result": {"flow_tab_found": True, "diag": {
                "projectId": "p1", "videoIds": ids, "imageIds": [], "mediaIds": []}}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return nres

    async def fake_accept(client, cands, exclude, correlation, stats):
        if "foreign-completed" in cands:
            state["rejections"] += 1
            stats["round_rejected_ids"] = ["foreign-completed"]
            stats["prompt_mismatched"] += 1
        return (None, None, None, None)

    async def fake_probe(*a, **k):
        return {"classification": None}

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._accept_correlated_output,
            mv.agent_video.probe_render_failure, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._accept_correlated_output = fake_accept
    mv.agent_video.probe_render_failure = fake_probe
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["g_blind"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("g_blind", "T2V", "p", "p1", None, None, "9:16", None,
                               model="veo_3_1_lite", duration_s=8))
        job = dict(mv._JOBS["g_blind"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._accept_correlated_output,
         mv.agent_video.probe_render_failure, mv.asyncio) = orig
        mv._JOBS.clear()

    assert state["rejections"] >= 3
    assert state["reloads"] >= 2
    assert job["status"] == "STALE_OR_FOREIGN_CANDIDATES_ONLY"
