"""Durable full-video job — the credit-safety core (PR315 final wiring).

Proves (zero-credit; the three credit-consuming side effects are injected/mocked):
job-before-initial, durable logical identity, COMPLETE production authority +
INCOMPLETE_PRODUCTION_PLAN fail-closed, whole-plan fingerprint authorization bound
to the reviewed prompts, DB-atomic idempotency for INITIAL/EXTEND/CONCAT, exact
per-segment continuation prompts (no generic fallback), resume-after-expiry without
a live token, structured credit truth (SPENT only with debit evidence), fail-closed
8s-vs-16s duration.

Every test uses a UNIQUE nonce so its idempotency keys never collide in the shared
module DB.
"""
import asyncio
import base64
import json
import struct
from contextlib import contextmanager

import pytest

from agent.db import crud
from agent.services.flow_client import FlowClient
from agent.services import make_video as mv
from agent.services import product_release_service
from agent.services import video_production_orchestrator as orch


def _mp4(seconds: float, pad=60_000) -> bytes:
    def box(t, p):
        return struct.pack(">I", 8 + len(p)) + t + p
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", 0, 0)
               + struct.pack(">I", 1000) + struct.pack(">I", int(seconds * 1000)) + b"\x00" * 80)
    # media-data mdat (proportional to duration) so the concat output passes the
    # final-render honesty gate (verify_final_media_payload); preflight ignores it.
    mdat = box(b"mdat", b"\x11" * int(max(1, seconds) * 20_000))
    return ftyp + box(b"moov", mvhd) + mdat


def _continuations(nonce, duration):
    segs = max(2, duration // 8)
    extend_ops = segs - 1
    return [
        {"position": p, "block_index": p + 1,
         "prompt": f"continuation {p} for {nonce}: extend from the exact ending, "
                   "same product identity and palm scale, no cut, no reset",
         "is_final": p == extend_ops}
        for p in range(1, extend_ops + 1)
    ]


def _intent(nonce, duration=16):
    """A COMPLETE production authority (explicit → the resolver never touches DB)."""
    return {
        "product_id": "6483d624", "product_name": "MWTCB 25ml",
        "execution_package_id": "wep_1", "approved_asset_id": "product-image:6483d624:subject",
        "approved_asset_sha256": "hashA", "initial_asset_media_id": f"asset-{nonce}",
        "requested_duration_seconds": duration, "engine": "GOOGLE_FLOW",
        "model": "veo_3_1_extension_lite", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "initial_mode": "I2V",
        "initial_prompt_text": f"block-1 product-truth prompt for {nonce}",
        "continuation_prompts": _continuations(nonce, duration),
        "execution_mode": "HYBRID_EXTEND", "client_request_nonce": nonce,
    }


class FakeClient:
    """The extend + finalize runtimes call this; counts real submits. Optional
    credit ledger simulates an authoritative debit for the credit-truth test."""
    def __init__(self, nonce, *, final_seconds=16.0, balance=None):
        self.extend_submits = 0
        self.concat_submits = 0
        self._child = f"child-{nonce}"
        self._concat_job = f"projects/1/locations/us/jobs/cj-{nonce}"
        self._encoded = base64.b64encode(_mp4(final_seconds)).decode()
        self._balance = balance

    async def get_credits(self):
        return {"remainingCredits": self._balance} if self._balance is not None else {}

    async def generate_video_extend(self, **kw):
        self.extend_submits += 1
        cid = self._child
        return {"remainingCredits": 1, "workflows": [{"name": f"wf-{cid}",
                "metadata": {"primaryMediaId": cid, "batchId": "b"}}],
                "media": [{"name": cid, "projectId": kw["project_id"],
                           "workflowId": f"wf-{cid}", "mediaMetadata": {"mediaStatus": {
                               "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SCHEDULED"}}}]}

    async def check_video_status_by_media(self, media):
        return {"media": [{"name": media[0]["name"], "mediaStatus": {
            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}}]}

    async def get_media(self, mid):
        # Each segment is a real ~8s block for the pre-concat duration preflight.
        return {"encodedVideo": base64.b64encode(_mp4(8.0)).decode(),
                "fifeUrl": f"https://flow-content/{mid}"}

    async def run_video_concatenation(self, input_videos):
        self.concat_submits += 1
        return {"operation": {"operation": {"name": self._concat_job}}}

    async def check_video_concatenation_status(self, envelope):
        return {"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "outputUri": "",
                "mediaGenerationId": "", "inputsCount": 3, "encodedVideo": self._encoded}


def _released_binding(*, installation="installation-a", build="build-current",
                      project="proj-root", session="session-a1"):
    return {
        "project_id": project,
        "bridge_lease": {
            "lease_id": f"preflight-{session}",
            "connection_id": f"connection-{session}",
            "connection_epoch": 1,
            "installation_id": installation,
            "extension_session_id": session,
            "extension_build": build,
            "flow_tab_id": 91,
            "flow_url": f"https://labs.google/fx/tools/flow/project/{project}",
            "flow_project_id": project,
            "released": True,
            "released_at": 1.0,
            "receipt_state": "PREFLIGHT_RELEASED",
        },
    }


class LeaseClient(FakeClient, FlowClient):
    """FlowClient-typed provider-free fixture for production-only lineage gates."""

    def __init__(self, nonce, *, installation="installation-a",
                 build="build-current", project="proj-root", **kwargs):
        FakeClient.__init__(self, nonce, **kwargs)
        self.installation = installation
        self.build = build
        self.project = project
        self.active_installation = None
        self.acquired = []
        self.released = []
        self.credit_probe = None

    def acquire_operation_lease(self, *, installation_id=None, **_kwargs):
        if installation_id and installation_id != self.installation:
            raise ConnectionError("ERR_EXTENSION_CONNECTION_NOT_FOUND")
        lease = {
            "lease_id": f"phase-{len(self.acquired) + 1}",
            "connection_id": f"connection-{self.installation}",
            "connection_epoch": len(self.acquired) + 1,
            "installation_id": self.installation,
            "extension_session_id": f"session-{len(self.acquired) + 1}",
        }
        self.acquired.append((installation_id, dict(lease)))
        return lease

    @contextmanager
    def activate_operation_lease(self, lease):
        previous = self.active_installation
        self.active_installation = lease["installation_id"]
        try:
            yield lease
        finally:
            self.active_installation = previous

    def release_operation_lease(self, lease):
        self.released.append(dict(lease))
        return True

    async def get_credits(self):
        assert self.active_installation == self.installation
        if self.credit_probe is not None:
            await self.credit_probe()
        return await FakeClient.get_credits(self)

    async def generate_video_extend(self, **kw):
        assert self.active_installation == self.installation
        return await FakeClient.generate_video_extend(self, **kw)

    async def check_video_status_by_media(self, media):
        assert self.active_installation == self.installation
        return await FakeClient.check_video_status_by_media(self, media)

    async def get_media(self, mid):
        assert self.active_installation == self.installation
        return await FakeClient.get_media(self, mid)

    async def run_video_concatenation(self, input_videos):
        assert self.active_installation == self.installation
        return await FakeClient.run_video_concatenation(self, input_videos)

    async def check_video_concatenation_status(self, envelope):
        assert self.active_installation == self.installation
        return await FakeClient.check_video_concatenation_status(self, envelope)


def _wire_rooted_binder(monkeypatch):
    async def bind(client, requested_project_id=None, *, bridge_lease=None, **_kwargs):
        lease = {
            **dict(bridge_lease or {}),
            "extension_build": client.build,
            "flow_tab_id": 92,
            "flow_url": (
                "https://labs.google/fx/tools/flow/project/" + client.project
            ),
            "flow_project_id": client.project,
        }
        return {"project_id": client.project, "bridge_lease": lease}

    monkeypatch.setattr(mv, "_bind_editor_session", bind)


def _initial_gen(calls, nonce, *, credit_after=None):
    async def gen(job):
        calls.append(job["job_id"])
        out = {"operation_id": f"init-{nonce}", "media_id": f"init-{nonce}",
               "workflow_id": f"wf-{nonce}", "project_id": f"proj-{nonce}",
               "scene_id": f"scene-{nonce}"}
        if credit_after is not None:
            out["credit_balance_after"] = credit_after
        return out
    return gen


async def _plan_authorize(monkeypatch, nonce, duration=16):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    planned = await orch.plan_job(_intent(nonce, duration), trust_client_authority=True)
    job = await crud.get_video_production_job(planned["job_id"])
    # Mission 1: job exists BEFORE any credit-consuming operation.
    assert job["status"] == orch.S_CREATED
    assert job["initial_operation_id"] is None
    # Mission 3: exact reviewed continuation prompts persisted before authorization.
    assert json.loads(job["continuation_prompts_json"])
    auth = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    return planned, auth


async def _expire(job_id):
    await crud.update_video_production_job_full(job_id, authorization_expires_at="1.0")


def test_extend_aspect_ratio_maps_ui_ratio_to_captured_enum():
    # Live regression vj_2502426e7791: the package stores the operator aspect as
    # "9:16" while EXTEND_VIDEO_MODELS is keyed by the captured enum — the
    # orchestrator maps at its boundary; enum passes through; unknown values
    # stay fail-closed in the runtime.
    assert orch.extend_aspect_ratio("9:16") == "VIDEO_ASPECT_RATIO_PORTRAIT"
    assert orch.extend_aspect_ratio("16:9") == "VIDEO_ASPECT_RATIO_LANDSCAPE"
    assert orch.extend_aspect_ratio("1:1") == "VIDEO_ASPECT_RATIO_SQUARE"
    assert (orch.extend_aspect_ratio("VIDEO_ASPECT_RATIO_PORTRAIT")
            == "VIDEO_ASPECT_RATIO_PORTRAIT")
    assert orch.extend_aspect_ratio(None) == "VIDEO_ASPECT_RATIO_PORTRAIT"
    assert orch.extend_aspect_ratio("4:3") == "4:3"  # unknown → runtime fails closed


# ── identity + plan authority (Mission 1 / 2 / 3) ────────────────────────────
async def test_job_created_before_initial_generation(monkeypatch, tmp_path):
    planned, _ = await _plan_authorize(monkeypatch, "created")
    assert planned["job_id"].startswith("vj_")
    assert planned["plan"]["operation_counts"] == {
        "initial_generation": 1, "extend": 1, "final_render": 1, "total": 3}
    assert planned["plan"]["credit_estimate"]["final_render"] == "unknown"


async def test_incomplete_plan_is_rejected(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    # product id only, no execution package + no explicit authority → cannot resolve
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.plan_job({"product_id": "px", "requested_duration_seconds": 16,
                             "client_request_nonce": "incomplete"})
    assert exc.value.code == "INCOMPLETE_PRODUCTION_PLAN"
    assert "approved_asset" in exc.value.detail or "continuation" in exc.value.detail


async def test_same_intent_reuses_one_logical_job(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    a = await orch.plan_job(_intent("same"), trust_client_authority=True)
    b = await orch.plan_job(_intent("same"), trust_client_authority=True)
    assert a["job_id"] == b["job_id"] and b["reused"] is True


async def test_invalid_duration_rejected(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.plan_job(_intent("dur", duration=20), trust_client_authority=True)
    assert exc.value.code == "INVALID_DURATION_PLAN"


async def test_production_ssot_ignores_client_prompt_override(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    # a client tries to swap the reviewed prompt; production planning must NOT honor it
    tampered = _intent("ssot")
    tampered["initial_prompt_text"] = "TAMPERED prompt not from the package"
    # trust=False (production) → client authority is stripped; with no execution
    # package to resolve from, the plan is INCOMPLETE rather than honoring the override
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.plan_job(tampered, trust_client_authority=False)
    assert exc.value.code == "INCOMPLETE_PRODUCTION_PLAN"


async def test_changed_prompt_rejects_authorization(monkeypatch, tmp_path):
    planned, _ = await _plan_authorize(monkeypatch, "chg")
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.authorize_job(planned["job_id"], confirmed_plan_fingerprint="tampered")
    assert exc.value.code == "PLAN_FINGERPRINT_MISMATCH"


async def test_advance_requires_valid_authorization(monkeypatch, tmp_path):
    planned, _ = await _plan_authorize(monkeypatch, "wa")
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.advance_job(FakeClient("wa"), planned["job_id"],
                               authorization_token="wrong",
                               generate_initial=_initial_gen([], "wa"), out_dir=tmp_path)
    assert exc.value.code == orch.F_AUTH


async def test_bridge_lineage_root_persisted_before_initial_provider_touch(
    monkeypatch, tmp_path
):
    _wire_rooted_binder(monkeypatch)
    planned, auth = await _plan_authorize(monkeypatch, "root-before-touch")
    client = LeaseClient("root-before-touch", project="proj-root-before-touch")
    events = []

    async def prepare(job):
        events.append("prepare")
        binding = _released_binding(project=client.project)
        await orch.persist_bridge_lineage_root(job["job_id"], binding)
        return binding

    async def credit_probe():
        persisted = await crud.get_video_production_job(planned["job_id"])
        root = orch.bridge_lineage_root(persisted)
        assert root["installation_id"] == "installation-a"
        assert root["extension_build"] == "build-current"
        assert root["flow_project_id"] == client.project
        events.append("credits")

    async def stop_after_probe(_job):
        events.append("generate")
        raise RuntimeError("STOP_AFTER_ROOT_ORDER")

    client.credit_probe = credit_probe
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client,
            planned["job_id"],
            authorization_token=auth["authorization_token"],
            prepare_initial=prepare,
            generate_initial=stop_after_probe,
            out_dir=tmp_path,
        )

    assert events == ["prepare", "credits", "generate"]
    assert len(client.released) == 1


async def test_initial_preflight_interruption_reenters_without_stranded_reservation(
    monkeypatch, tmp_path
):
    """A cancellation after root persistence but before INITIAL reservation leaves
    no side-effect owner; re-entry submits exactly once instead of polling forever."""
    _wire_rooted_binder(monkeypatch)
    nonce = "preflight-interrupt"
    planned, auth = await _plan_authorize(monkeypatch, nonce)
    client = LeaseClient(nonce, project=f"proj-{nonce}")
    prepare_calls = []
    initial_calls = []

    async def allow_product(*_args, **_kwargs):
        return {"operational": True}

    monkeypatch.setattr(
        product_release_service, "require_product_operational_visibility", allow_product
    )

    async def prepare(job):
        prepare_calls.append(job["job_id"])
        binding = _released_binding(
            project=client.project,
            session=f"preflight-{len(prepare_calls)}",
        )
        await orch.persist_bridge_lineage_root(job["job_id"], binding)
        if len(prepare_calls) == 1:
            raise asyncio.CancelledError()
        return binding

    with pytest.raises(asyncio.CancelledError):
        await orch.advance_job(
            client,
            planned["job_id"],
            authorization_token=auth["authorization_token"],
            prepare_initial=prepare,
            generate_initial=_initial_gen(initial_calls, nonce),
            out_dir=tmp_path,
            poll_interval_s=0,
        )

    interrupted_job = await crud.get_video_production_job(planned["job_id"])
    initial_key = orch._stage_key(
        interrupted_job, "INITIAL", interrupted_job["logical_job_key"]
    )
    assert await crud.get_video_job_side_effect(initial_key) is None

    status = await orch.advance_job(
        client,
        planned["job_id"],
        authorization_token=auth["authorization_token"],
        prepare_initial=prepare,
        generate_initial=_initial_gen(initial_calls, nonce),
        out_dir=tmp_path,
        poll_interval_s=0,
    )

    assert status["complete"] is True
    assert initial_calls == [planned["job_id"]]
    row = await crud.get_video_job_side_effect(initial_key)
    assert row["submission_state"] == orch.SUB_TERMINAL
    assert int(row["effective_submit_count"]) == 1


async def test_initial_credit_probe_interruption_reenters_before_atomic_claim(
    monkeypatch, tmp_path
):
    """Cancellation during rooted binding/credit probing occurs before the atomic
    submit claim, so re-entry remains provider-safe and submits exactly once."""
    _wire_rooted_binder(monkeypatch)
    nonce = "credit-interrupt"
    planned, auth = await _plan_authorize(monkeypatch, nonce)
    client = LeaseClient(nonce, project=f"proj-{nonce}")
    initial_calls = []
    credit_calls = 0

    async def allow_product(*_args, **_kwargs):
        return {"operational": True}

    monkeypatch.setattr(
        product_release_service, "require_product_operational_visibility", allow_product
    )

    async def prepare(job):
        binding = _released_binding(project=client.project)
        await orch.persist_bridge_lineage_root(job["job_id"], binding)
        return binding

    async def interrupt_first_credit_probe():
        nonlocal credit_calls
        credit_calls += 1
        if credit_calls == 1:
            raise asyncio.CancelledError()

    client.credit_probe = interrupt_first_credit_probe
    with pytest.raises(asyncio.CancelledError):
        await orch.advance_job(
            client,
            planned["job_id"],
            authorization_token=auth["authorization_token"],
            prepare_initial=prepare,
            generate_initial=_initial_gen(initial_calls, nonce),
            out_dir=tmp_path,
            poll_interval_s=0,
        )

    interrupted_job = await crud.get_video_production_job(planned["job_id"])
    initial_key = orch._stage_key(
        interrupted_job, "INITIAL", interrupted_job["logical_job_key"]
    )
    assert await crud.get_video_job_side_effect(initial_key) is None

    status = await orch.advance_job(
        client,
        planned["job_id"],
        authorization_token=auth["authorization_token"],
        prepare_initial=prepare,
        generate_initial=_initial_gen(initial_calls, nonce),
        out_dir=tmp_path,
        poll_interval_s=0,
    )

    assert status["complete"] is True
    assert initial_calls == [planned["job_id"]]
    row = await crud.get_video_job_side_effect(initial_key)
    assert row["submission_state"] == orch.SUB_TERMINAL
    assert int(row["effective_submit_count"]) == 1


async def test_bridge_lineage_cas_preserves_concurrent_stage_state(
    monkeypatch,
):
    planned, _auth = await _plan_authorize(monkeypatch, "root-cas")
    await crud.update_video_production_job_full(
        planned["job_id"],
        stage_state_json=json.dumps({"owner_recovery_hold": {"version": 1}}),
    )
    root = {
        "version": 1,
        "installation_id": "installation-a",
        "extension_build": "build-current",
        "flow_project_id": "proj-root-cas",
    }
    original_cas = crud.compare_and_swap_video_production_job_stage_state
    injected_conflict = False

    async def lose_first_cas(
        job_id, *, expected_stage_state_json, stage_state_json
    ):
        nonlocal injected_conflict
        if not injected_conflict:
            injected_conflict = True
            concurrent = json.loads(expected_stage_state_json)
            concurrent["concurrent_audit"] = {"writer": "b"}
            await crud.update_video_production_job_full(
                job_id,
                stage_state_json=json.dumps(
                    concurrent, separators=(",", ":"), sort_keys=True
                ),
            )
            return False
        return await original_cas(
            job_id,
            expected_stage_state_json=expected_stage_state_json,
            stage_state_json=stage_state_json,
        )

    monkeypatch.setattr(
        crud, "compare_and_swap_video_production_job_stage_state", lose_first_cas
    )
    await orch.merge_video_production_job_stage_state(
        planned["job_id"], {"bridge_lineage_v1": root}
    )

    persisted = await crud.get_video_production_job(planned["job_id"])
    state = json.loads(persisted["stage_state_json"])
    assert state["owner_recovery_hold"] == {"version": 1}
    assert state["bridge_lineage_v1"] == root
    assert state["concurrent_audit"] == {"writer": "b"}


@pytest.mark.parametrize(
    ("field", "observed"),
    [
        ("installation_id", "installation-b"),
        ("extension_build", "build-rotated"),
        ("flow_project_id", "proj-rotated"),
    ],
)
async def test_outer_lineage_rejects_installation_build_or_project_rotation(
    monkeypatch, field, observed
):
    _wire_rooted_binder(monkeypatch)
    planned, _auth = await _plan_authorize(monkeypatch, f"root-rotate-{field}")
    await orch.persist_bridge_lineage_root(
        planned["job_id"], _released_binding(project="proj-root")
    )
    kwargs = {"installation": "installation-a", "build": "build-current",
              "project": "proj-root"}
    kwargs[{"installation_id": "installation", "extension_build": "build",
            "flow_project_id": "project"}[field]] = observed
    client = LeaseClient(f"rotate-{field}", **kwargs)
    reached = False

    async def forbidden(_binding):
        nonlocal reached
        reached = True

    with pytest.raises((orch.OrchestratorError, ConnectionError)):
        await orch.bridge_lineage_phase(
            client, planned["job_id"], "ROTATION_TEST", forbidden
        )
    assert reached is False
    if field != "installation_id":
        assert len(client.released) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_outer_phase_lease_released_on_failure_and_cancellation(
    monkeypatch, error_type
):
    _wire_rooted_binder(monkeypatch)
    planned, _auth = await _plan_authorize(
        monkeypatch, f"root-release-{error_type.__name__}"
    )
    await orch.persist_bridge_lineage_root(
        planned["job_id"], _released_binding(project="proj-root")
    )
    client = LeaseClient("release", project="proj-root")

    async def fail(_binding):
        raise error_type("phase interrupted")

    with pytest.raises(error_type):
        await orch.bridge_lineage_phase(
            client, planned["job_id"], "RELEASE_TEST", fail
        )
    assert len(client.released) == 1
    assert client.active_installation is None


# ── full happy path CREATED → COMPLETE ──────────────────────────────────────
async def test_full_lifecycle_created_to_complete(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "full")
    client = FakeClient("full", final_seconds=16.0)
    calls = []
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "full"), out_dir=tmp_path, poll_interval_s=0)
    assert status["complete"] is True
    assert status["human_stage"] == "Video ready"
    assert calls == [planned["job_id"]]           # initial generated once, by the job
    assert client.extend_submits == 1
    assert client.concat_submits == 1
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] == "init-full"
    assert job["extend_child_operation_id"] == "child-full"
    assert job["final_media_id"] and job["final_duration_s"] == pytest.approx(16.0, abs=0.05)
    assert json.loads(job["segment_media_ids_json"]) == ["init-full", "child-full"]


async def test_concat_uses_rooted_installation(monkeypatch, tmp_path):
    _wire_rooted_binder(monkeypatch)
    planned, auth = await _plan_authorize(monkeypatch, "rooted-concat")
    await orch.persist_bridge_lineage_root(
        planned["job_id"],
        _released_binding(project="proj-rooted-concat"),
    )
    await crud.update_video_production_job_full(
        planned["job_id"],
        status=orch.S_EXTEND_READY,
        project_id="proj-rooted-concat",
        scene_id="scene-rooted-concat",
        initial_operation_id="init-rooted-concat",
        initial_media_id="init-rooted-concat",
        segment_media_ids_json=json.dumps(
            ["init-rooted-concat", "child-rooted-concat"]
        ),
        extend_child_operation_id="child-rooted-concat",
    )
    client = LeaseClient(
        "rooted-concat", project="proj-rooted-concat", final_seconds=16.0
    )

    async def forbidden_initial(_job):
        raise AssertionError("initial must not run")

    status = await orch.advance_job(
        client,
        planned["job_id"],
        authorization_token=auth["authorization_token"],
        generate_initial=forbidden_initial,
        out_dir=tmp_path,
        poll_interval_s=0,
    )

    assert status["complete"] is True
    assert client.concat_submits == 1
    assert [item[0] for item in client.acquired] == ["installation-a"]
    assert len(client.released) == 1


# ── idempotency: re-advance never double-submits any side effect ────────────
async def test_reentry_never_double_submits(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "idem")
    client = FakeClient("idem")
    calls = []
    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=_initial_gen(calls, "idem"), out_dir=tmp_path, poll_interval_s=0)
    await orch.advance_job(client, planned["job_id"], **args)
    status2 = await orch.advance_job(client, planned["job_id"], **args)   # duplicate start
    assert status2["complete"] is True
    assert len(calls) == 1
    assert client.extend_submits == 1
    assert client.concat_submits == 1              # the critical guarantee
    job = await crud.get_video_production_job(planned["job_id"])
    for stage, payload in (("INITIAL", planned["logical_job_key"]),
                           ("CONCAT", "+".join(sorted(["init-idem", "child-idem"])))):
        se = await crud.get_video_job_side_effect(orch._stage_key(job, stage, payload))
        assert se["effective_submit_count"] == 1
        assert se["submission_state"] == orch.SUB_TERMINAL


async def test_concurrent_advance_single_concat(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "conc")
    client = FakeClient("conc")
    calls = []

    async def allow_product(*_args, **_kwargs):
        return {"operational": True}

    monkeypatch.setattr(
        product_release_service, "require_product_operational_visibility", allow_product
    )
    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=_initial_gen(calls, "conc"), out_dir=tmp_path, poll_interval_s=0)
    await asyncio.gather(
        orch.advance_job(client, planned["job_id"], **args),
        orch.advance_job(client, planned["job_id"], **args),
    )
    assert len(calls) == 1
    assert client.extend_submits == 1
    assert client.concat_submits == 1

    # The same race against an existing SAFE retry row must also have one owner.
    retry_plan, _ = await _drive_to_initial(monkeypatch, tmp_path, "conc-safe")
    retry_job = await crud.get_video_production_job(retry_plan["job_id"])
    retry_cont = json.loads(retry_job["continuation_prompts_json"])[0]
    retry_key = orch._stage_key(
        retry_job,
        "EXTEND",
        "init-conc-safe|"
        f"{orch._nx._prompt_hash(retry_cont['prompt'])}|pos1",
    )
    await crud.reserve_video_job_side_effect(
        retry_key, job_id=retry_job["job_id"], stage="EXTEND"
    )
    await crud.increment_side_effect_submit_count(retry_key)
    await crud.update_video_job_side_effect(
        retry_key,
        submission_state=orch.SUB_NOT_ATTEMPTED,
        credit_state=orch.CR_NOT_SPENT,
        retry_safety=orch.RS_SAFE,
        detail="provider-free SAFE retry fixture",
    )
    await crud.update_video_production_job_full(
        retry_job["job_id"], status=orch.F_EXTEND, error_code=orch.F_EXTEND
    )
    retry_auth = await orch.authorize_job(
        retry_job["job_id"],
        confirmed_plan_fingerprint=retry_plan["plan_fingerprint"],
    )
    retry_client = FakeClient("conc-safe")
    retry_args = dict(
        authorization_token=retry_auth["authorization_token"],
        generate_initial=_initial_gen([], "conc-safe"),
        out_dir=tmp_path,
        poll_interval_s=0,
    )
    await asyncio.gather(
        orch.advance_job(retry_client, retry_job["job_id"], **retry_args),
        orch.advance_job(retry_client, retry_job["job_id"], **retry_args),
    )
    retry_row = await crud.get_video_job_side_effect(retry_key)
    assert retry_client.extend_submits == 1
    assert retry_client.concat_submits == 1
    assert retry_row["submission_state"] == orch.SUB_TERMINAL
    assert int(retry_row["effective_submit_count"]) == 2

    # A caller that read a fresh candidate but then fails rooted binding must
    # not downgrade the concurrent winner's active SUBMITTED ownership.
    race_plan, race_auth = await _drive_to_initial(
        monkeypatch, tmp_path, "conc-preclaim-fail"
    )
    race_job = await crud.get_video_production_job(race_plan["job_id"])
    race_cont = json.loads(race_job["continuation_prompts_json"])[0]
    race_key = orch._stage_key(
        race_job,
        "EXTEND",
        "init-conc-preclaim-fail|"
        f"{orch._nx._prompt_hash(race_cont['prompt'])}|pos1",
    )
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    winner_active = asyncio.Event()
    release_winner = asyncio.Event()
    original_phase = orch.bridge_lineage_phase
    extend_entries = 0

    class _BlockingExtend(FakeClient):
        async def generate_video_extend(self, **kwargs):
            result = await super().generate_video_extend(**kwargs)
            winner_active.set()
            await release_winner.wait()
            return result

    async def controlled_phase(client_arg, job_id, phase, action):
        nonlocal extend_entries
        if job_id == race_job["job_id"] and phase == "EXTEND_1":
            extend_entries += 1
            if extend_entries == 1:
                first_entered.set()
                await second_entered.wait()
                return await action(None)
            second_entered.set()
            await winner_active.wait()
            raise RuntimeError("provider-free preclaim binding failure")
        return await original_phase(client_arg, job_id, phase, action)

    monkeypatch.setattr(orch, "bridge_lineage_phase", controlled_phase)
    race_client = _BlockingExtend("conc-preclaim-fail")
    race_args = dict(
        authorization_token=race_auth["authorization_token"],
        generate_initial=_initial_gen([], "conc-preclaim-fail"),
        out_dir=tmp_path,
        poll_interval_s=0,
    )
    winner = asyncio.create_task(
        orch.advance_job(race_client, race_job["job_id"], **race_args)
    )
    await first_entered.wait()
    loser = asyncio.create_task(
        orch.advance_job(race_client, race_job["job_id"], **race_args)
    )
    await winner_active.wait()
    with pytest.raises(orch.OrchestratorError, match="preclaim binding failure"):
        await loser

    active_row = await crud.get_video_job_side_effect(race_key)
    assert active_row["submission_state"] == orch.SUB_SUBMITTED
    assert active_row["credit_state"] == orch.CR_MAY_HAVE_SPENT
    assert active_row["retry_safety"] == orch.RS_RESUME_ONLY
    assert int(active_row["effective_submit_count"]) == 1
    assert race_client.extend_submits == 1

    release_winner.set()
    completed = await winner
    final_row = await crud.get_video_job_side_effect(race_key)
    assert completed["complete"] is True
    assert race_client.extend_submits == 1
    assert final_row["submission_state"] == orch.SUB_TERMINAL
    assert int(final_row["effective_submit_count"]) == 1


# ── restart / resume: resume_only never fresh-submits ───────────────────────
async def test_resume_only_waits_before_fresh_submit(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "ro")
    client = FakeClient("ro")
    calls = []
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "ro"), out_dir=tmp_path, resume_only=True)
    assert calls == [] and client.extend_submits == 0 and client.concat_submits == 0
    assert status["complete"] is False


async def test_restart_sweep_adds_no_new_credit(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "sweep")
    client = FakeClient("sweep")
    calls = []
    await orch.advance_job(client, planned["job_id"],
                           authorization_token=auth["authorization_token"],
                           generate_initial=_initial_gen(calls, "sweep"), out_dir=tmp_path,
                           poll_interval_s=0)
    before = (client.extend_submits, client.concat_submits)
    resumed = await orch.resume_in_flight_jobs(
        client, generate_initial=_initial_gen(calls, "sweep"), out_dir=tmp_path)
    assert isinstance(resumed, list)
    assert (client.extend_submits, client.concat_submits) == before


async def test_owner_recovery_hold_is_atomic_auditable_and_idempotent(
    monkeypatch,
    tmp_path,
):
    first, _ = await _plan_authorize(monkeypatch, "hold-first")
    second, _ = await _plan_authorize(monkeypatch, "hold-second")
    uncertain, _ = await _plan_authorize(monkeypatch, "hold-uncertain")
    await crud.update_video_production_job_full(
        first["job_id"],
        status=orch.S_AUTH_EXPIRED,
        error_code=orch.S_AUTH_EXPIRED,
        stage_state_json=json.dumps({"existing": "first"}),
    )
    await crud.update_video_production_job_full(
        second["job_id"],
        status=orch.S_AUTH_EXPIRED,
        error_code=orch.S_AUTH_EXPIRED,
        stage_state_json=json.dumps({"existing": "second"}),
    )
    uncertain_job = await crud.get_video_production_job(uncertain["job_id"])
    uncertain_key = orch._stage_key(
        uncertain_job,
        "INITIAL",
        uncertain_job["logical_job_key"],
    )
    await crud.reserve_video_job_side_effect(
        uncertain_key,
        job_id=uncertain["job_id"],
        stage="INITIAL",
    )
    await crud.increment_side_effect_submit_count(uncertain_key)
    await crud.update_video_job_side_effect(
        uncertain_key,
        submission_state=orch.SUB_UNCERTAIN,
        credit_state=orch.CR_MAY_HAVE_SPENT,
        retry_safety=orch.RS_BLOCKED,
        detail="provider acceptance unknown",
    )
    side_effect_before = await crud.get_video_job_side_effect(uncertain_key)

    result = await orch.contain_restart_recovery_jobs(
        [first["job_id"], second["job_id"], uncertain["job_id"]],
        authorized_by="owner:Faris",
        authorization_note=(
            "BOSMAX-P5-CANONICAL-CLOSURE-AND-PRODUCT-ACTIVATION-20260729"
        ),
    )

    assert result["changed_count"] == 3
    assert result["startup_recovery_candidates_remaining"] == 0
    for planned in (first, second, uncertain):
        row = await crud.get_video_production_job(planned["job_id"])
        assert row["status"] == orch.S_AUTH_EXPIRED
        assert row["authorization_token"] is None
        audit = json.loads(row["stage_state_json"])["owner_recovery_hold"]
        assert audit["authorized_by"] == "owner:Faris"
        assert audit["provider_polling_allowed"] is False
        assert audit["generation_resubmission_allowed"] is False
        assert audit["side_effect_ledger_preserved"] is True
    assert await crud.get_video_job_side_effect(uncertain_key) == side_effect_before

    async def forbidden_generate(_job):
        raise AssertionError("contained restart must not submit generation")

    resumed = await orch.resume_in_flight_jobs(
        FakeClient("contained"),
        generate_initial=forbidden_generate,
        out_dir=tmp_path,
    )
    assert resumed == []

    reapplied = await orch.contain_restart_recovery_jobs(
        [first["job_id"], second["job_id"], uncertain["job_id"]],
        authorized_by="owner:Faris",
        authorization_note=(
            "BOSMAX-P5-CANONICAL-CLOSURE-AND-PRODUCT-ACTIVATION-20260729"
        ),
    )
    assert reapplied["changed_count"] == 0
    assert reapplied["startup_recovery_candidates_remaining"] == 0
    assert await crud.get_video_job_side_effect(uncertain_key) == side_effect_before


async def test_owner_recovery_hold_rejects_unknown_scope_before_mutation(
    monkeypatch,
):
    planned, _ = await _plan_authorize(monkeypatch, "hold-atomic-reject")
    before = await crud.get_video_production_job(planned["job_id"])

    with pytest.raises(orch.OrchestratorError, match="VIDEO_JOB_NOT_FOUND"):
        await orch.contain_restart_recovery_jobs(
            [planned["job_id"], "vj_missing"],
            authorized_by="owner:Faris",
            authorization_note="Exact owner-authorized containment.",
        )

    after = await crud.get_video_production_job(planned["job_id"])
    assert after["authorization_token"] == before["authorization_token"]
    assert after["status"] == before["status"]


# ── restart-after-expiry recovery (Mission 5) ───────────────────────────────
async def test_expiry_before_initial_stops_and_reauth_resumes(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "exp0")
    await _expire(planned["job_id"])
    client, calls = FakeClient("exp0"), []
    gen = _initial_gen(calls, "exp0")
    # not-yet-submitted stage after expiry → stop safely, no auto-submit
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=gen, out_dir=tmp_path, poll_interval_s=0)
    assert status["status"] == orch.S_AUTH_EXPIRED
    assert calls == [] and client.extend_submits == 0
    # a new reviewed authorization → the job runs to completion
    auth2 = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    done = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth2["authorization_token"],
        generate_initial=gen, out_dir=tmp_path, poll_interval_s=0)
    assert done["complete"] is True and len(calls) == 1


async def _drive_to_initial(monkeypatch, tmp_path, nonce):
    """Reach the checkpoint where INITIAL is submitted+terminal but EXTEND is not."""
    planned, auth = await _plan_authorize(monkeypatch, nonce)
    job = await crud.get_video_production_job(planned["job_id"])
    idem = orch._stage_key(job, "INITIAL", job["logical_job_key"])
    await crud.reserve_video_job_side_effect(idem, job_id=job["job_id"], stage="INITIAL")
    await crud.increment_side_effect_submit_count(idem)
    await crud.update_video_job_side_effect(
        idem, submission_state=orch.SUB_TERMINAL, credit_state=orch.CR_MAY_HAVE_SPENT,
        operation_ref=f"init-{nonce}")
    await crud.update_video_production_job_full(
        job["job_id"], status=orch.S_INITIAL_READY, initial_operation_id=f"init-{nonce}",
        initial_media_id=f"init-{nonce}", project_id=f"proj-{nonce}", scene_id=f"scene-{nonce}",
        segment_media_ids_json=json.dumps([f"init-{nonce}"]))
    return planned, auth


async def test_expiry_after_initial_submitted_resumes_without_token(monkeypatch, tmp_path):
    planned, _ = await _drive_to_initial(monkeypatch, tmp_path, "exp1")
    await _expire(planned["job_id"])
    client, calls = FakeClient("exp1"), []
    # resume_only after expiry: polls the already-submitted job, NEVER a fresh submit
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token="expired-ignored",
        generate_initial=_initial_gen(calls, "exp1"), out_dir=tmp_path, resume_only=True)
    assert client.extend_submits == 0 and calls == []
    assert status["status"] != orch.S_AUTH_EXPIRED  # already-submitted work isn't stranded


async def test_expiry_after_extend_submitted_finalizes_on_resume(monkeypatch, tmp_path):
    planned, auth = await _drive_to_initial(monkeypatch, tmp_path, "exp2")
    job = await crud.get_video_production_job(planned["job_id"])
    conts = json.loads(job["continuation_prompts_json"])
    from agent.services import google_flow_native_extend_runtime as _nx
    parent = "init-exp2"
    idem = orch._stage_key(
        job, "EXTEND", f"{parent}|{_nx._prompt_hash(conts[0]['prompt'])}|pos1")
    await crud.reserve_video_job_side_effect(idem, job_id=job["job_id"], stage="EXTEND")
    await crud.update_video_job_side_effect(
        idem, submission_state=orch.SUB_TERMINAL, operation_ref="child-exp2")
    await crud.update_video_production_job_full(
        job["job_id"], status=orch.S_EXTEND_READY, extend_child_operation_id="child-exp2",
        segment_media_ids_json=json.dumps([parent, "child-exp2"]))
    await _expire(planned["job_id"])
    # CONCAT is the only unsubmitted stage: normal advance with an expired token stops
    client = FakeClient("exp2")
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen([], "exp2"), out_dir=tmp_path, poll_interval_s=0)
    assert status["status"] == orch.S_AUTH_EXPIRED and client.concat_submits == 0
    # re-authorize → the final render completes; no new extend
    auth2 = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    done = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth2["authorization_token"],
        generate_initial=_initial_gen([], "exp2"), out_dir=tmp_path, poll_interval_s=0)
    assert done["complete"] is True
    assert client.extend_submits == 0 and client.concat_submits == 1


async def test_safe_not_attempted_extend_is_retryable_on_resume(monkeypatch, tmp_path):
    """A pre-submit fail-closed EXTEND (NOT_ATTEMPTED / NOT_SPENT / SAFE, no
    operation_ref — live: vj_2502426e7791 EXTEND_UNSUPPORTED_MODEL) must be
    retryable under a fresh authorization: exactly ONE new submit, never a
    stranded job. UNCERTAIN rows stay non-retryable."""
    planned, _ = await _drive_to_initial(monkeypatch, tmp_path, "saferetry")
    job = await crud.get_video_production_job(planned["job_id"])
    conts = json.loads(job["continuation_prompts_json"])
    from agent.services import google_flow_native_extend_runtime as _nx
    parent = "init-saferetry"
    idem = orch._stage_key(
        job, "EXTEND", f"{parent}|{_nx._prompt_hash(conts[0]['prompt'])}|pos1")
    await crud.reserve_video_job_side_effect(idem, job_id=job["job_id"], stage="EXTEND")
    await crud.increment_side_effect_submit_count(idem)
    await crud.update_video_job_side_effect(
        idem, submission_state=orch.SUB_NOT_ATTEMPTED, credit_state=orch.CR_NOT_SPENT,
        retry_safety=orch.RS_SAFE, detail="EXTEND_UNSUPPORTED_MODEL:9:16")
    await crud.update_video_production_job_full(
        job["job_id"], status=orch.F_EXTEND, error_code=orch.F_EXTEND)
    auth2 = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    client = FakeClient("saferetry")
    done = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth2["authorization_token"],
        generate_initial=_initial_gen([], "saferetry"), out_dir=tmp_path,
        poll_interval_s=0)
    assert done["complete"] is True
    assert client.extend_submits == 1  # exactly one controlled retry
    row = next(r for r in await crud.list_video_job_side_effects(planned["job_id"])
               if r["idempotency_key"] == idem)
    assert row["submission_state"] == orch.SUB_TERMINAL
    assert int(row["effective_submit_count"]) == 2  # honest audit of the retry


async def test_extend_child_missing_is_provider_touched_not_safe(monkeypatch, tmp_path):
    """EXTEND_CHILD_MEDIA_ID_MISSING is raised AFTER generate_video_extend — the
    provider was touched, so credit must be UNCERTAIN/MAY_HAVE_SPENT/BLOCKED, NOT
    NOT_ATTEMPTED/NOT_SPENT/SAFE (live: vj_bb28f65c189e was wrongly SAFE). Concat
    must not be called and the job must not reach COMPLETE."""
    planned, auth = await _plan_authorize(monkeypatch, "extchild")

    class _EmptyExtend(FakeClient):
        async def generate_video_extend(self, **kw):
            self.extend_submits += 1
            return {"remainingCredits": 1, "media": [], "workflows": []}  # no child

    client = _EmptyExtend("extchild")
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=_initial_gen([], "extchild"), out_dir=tmp_path,
            poll_interval_s=0)

    row = next(r for r in await crud.list_video_job_side_effects(planned["job_id"])
               if r["stage"] == "EXTEND")
    assert row["submission_state"] == orch.SUB_UNCERTAIN
    assert row["credit_state"] == orch.CR_MAY_HAVE_SPENT
    assert row["retry_safety"] == orch.RS_BLOCKED
    # fail-closed: the extend RPC fired once, concat NEVER, no COMPLETE, no final id
    assert client.extend_submits == 1
    assert client.concat_submits == 0
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["status"] == orch.F_EXTEND
    assert job["status"] != orch.S_COMPLETE
    assert job.get("final_media_id") is None


async def test_extend_child_missing_persists_sanitized_shape_to_lineage(monkeypatch, tmp_path):
    """Proves the sanitized shape is actually PERSISTED to extend_lineage on
    EXTEND_CHILD_MEDIA_ID_MISSING (not merely produced by the helper)."""
    planned, auth = await _plan_authorize(monkeypatch, "extpersist")

    class _EmptyExtend(FakeClient):
        async def generate_video_extend(self, **kw):
            self.extend_submits += 1
            return {"remainingCredits": 1, "media": [], "workflows": []}

    client = _EmptyExtend("extpersist")
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=_initial_gen([], "extpersist"), out_dir=tmp_path,
            poll_interval_s=0)

    rows = await crud.list_extend_lineage(project_id="proj-extpersist")
    assert rows, "expected an extend_lineage row"
    msgs = " ".join(str(r.get("error_message") or "") for r in rows)
    assert "shape=" in msgs                 # the sanitized shape landed
    assert "no child in response" in msgs
    assert "workflow_count" in msgs         # a real structural field of the shape


async def test_extend_error_body_secret_never_reaches_lineage(monkeypatch, tmp_path):
    """A provider error body carrying tokens must NOT be persisted anywhere —
    only safe code/status/shape metadata (the B-01 blocker)."""
    planned, auth = await _plan_authorize(monkeypatch, "extsecret")

    class _SecretErr(FakeClient):
        async def generate_video_extend(self, **kw):
            self.extend_submits += 1
            return {"error": {"code": 403, "status": "PERMISSION_DENIED",
                              "message": "token=SECRET_TOKEN_QQ recaptcha=SECRET_CAP",
                              "details": {"sessionId": "SECRET_SESSION_ZZ"}}}

    client = _SecretErr("extsecret")
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=_initial_gen([], "extsecret"), out_dir=tmp_path,
            poll_interval_s=0)

    lineage = await crud.list_extend_lineage(project_id="proj-extsecret")
    side_effects = await crud.list_video_job_side_effects(planned["job_id"])
    blob = json.dumps([dict(r) for r in lineage] + [dict(r) for r in side_effects])
    assert "SECRET_TOKEN_QQ" not in blob
    assert "SECRET_CAP" not in blob
    assert "SECRET_SESSION_ZZ" not in blob
    # the safe structural metadata IS retained for diagnosis
    assert "PERMISSION_DENIED" in blob and "403" in blob


async def test_initial_pre_submit_rejection_is_safe_and_retryable(monkeypatch, tmp_path):
    """INITIAL-stage mirror of the EXTEND SAFE contract (live: vj_efed7c24d9cc
    stuck AUTHORIZED forever after a rate-limiter rejection). A rejection with
    NO persisted lane handle is provably zero-side-effect: the row records
    NOT_ATTEMPTED / NOT_SPENT / SAFE and a fresh authorization may submit
    again — exactly one controlled retry, never a stranded job."""
    planned, auth = await _plan_authorize(monkeypatch, "initsafe")

    async def rejected(job):
        # One-door lane rejection BEFORE any lane handle exists (CAPTCHA /
        # rate limiter): nothing persisted, nothing spent.
        raise RuntimeError("one-door lane rejected initial: RATE_LIMITED")

    client = FakeClient("initsafe")
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=rejected, out_dir=tmp_path, poll_interval_s=0)

    job = await crud.get_video_production_job(planned["job_id"])
    assert job["status"] == orch.F_INITIAL
    idem = orch._stage_key(job, "INITIAL", job["logical_job_key"])
    row = next(r for r in await crud.list_video_job_side_effects(planned["job_id"])
               if r["idempotency_key"] == idem)
    assert row["submission_state"] == orch.SUB_NOT_ATTEMPTED
    assert row["credit_state"] == orch.CR_NOT_SPENT
    assert row["retry_safety"] == orch.RS_SAFE

    # Fresh authorization → the SAFE row submits again and the job completes.
    auth2 = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    calls = []
    done = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth2["authorization_token"],
        generate_initial=_initial_gen(calls, "initsafe"), out_dir=tmp_path,
        poll_interval_s=0)
    assert done["complete"] is True
    assert calls == [planned["job_id"]]  # exactly one controlled retry
    row = next(r for r in await crud.list_video_job_side_effects(planned["job_id"])
               if r["idempotency_key"] == idem)
    assert row["submission_state"] == orch.SUB_TERMINAL
    assert int(row["effective_submit_count"]) == 2  # honest audit of the retry


async def test_initial_zero_credit_signature_is_safe_despite_lane_handle(monkeypatch, tmp_path):
    """A lane-terminal failure carrying a known zero-credit rejection signature
    (NO_OPEN_EDITOR / CAPTCHA / RATE_LIMITED...) is provably pre-generation
    even though the lane handle was persisted — the row stays SAFE-retryable
    (live: vj_bda8259b2780 stranded on NO_OPEN_EDITOR)."""
    planned, auth = await _plan_authorize(monkeypatch, "initsig")

    async def editor_closed(job):
        await crud.update_video_production_job_full(
            job["job_id"], initial_lane_job_id="lane-initsig")
        raise RuntimeError(
            "initial generation FAILED: NO_OPEN_EDITOR: the Flow tab is not an editor")

    client = FakeClient("initsig")
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=editor_closed, out_dir=tmp_path, poll_interval_s=0)

    job = await crud.get_video_production_job(planned["job_id"])
    idem = orch._stage_key(job, "INITIAL", job["logical_job_key"])
    row = next(r for r in await crud.list_video_job_side_effects(planned["job_id"])
               if r["idempotency_key"] == idem)
    assert row["submission_state"] == orch.SUB_NOT_ATTEMPTED
    assert row["credit_state"] == orch.CR_NOT_SPENT
    assert row["retry_safety"] == orch.RS_SAFE

    # Editor repaired -> a fresh authorization completes the job.
    auth2 = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    calls = []
    done = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth2["authorization_token"],
        generate_initial=_initial_gen(calls, "initsig"), out_dir=tmp_path,
        poll_interval_s=0)
    assert done["complete"] is True
    assert calls == [planned["job_id"]]


async def test_initial_post_submit_failure_stays_blocked(monkeypatch, tmp_path):
    """A failure AFTER the lane handle was persisted (submission accepted —
    credits may have been spent) keeps the conservative UNCERTAIN / BLOCKED
    row: re-authorization must NOT trigger a second submit."""
    planned, auth = await _plan_authorize(monkeypatch, "initblocked")

    async def failed_after_submit(job):
        await crud.update_video_production_job_full(
            job["job_id"], initial_lane_job_id="lane-initblocked")
        raise RuntimeError("initial generation FAILED: engine error mid-flight")

    client = FakeClient("initblocked")
    with pytest.raises(orch.OrchestratorError):
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=failed_after_submit, out_dir=tmp_path, poll_interval_s=0)

    job = await crud.get_video_production_job(planned["job_id"])
    idem = orch._stage_key(job, "INITIAL", job["logical_job_key"])
    row = next(r for r in await crud.list_video_job_side_effects(planned["job_id"])
               if r["idempotency_key"] == idem)
    assert row["submission_state"] == orch.SUB_UNCERTAIN
    assert row["retry_safety"] == orch.RS_BLOCKED

    auth2 = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    calls = []
    await orch.advance_job(
        client, planned["job_id"], authorization_token=auth2["authorization_token"],
        generate_initial=_initial_gen(calls, "initblocked"), out_dir=tmp_path,
        poll_interval_s=0)
    assert calls == []  # UNCERTAIN row: surfaced, never resubmitted


# ── mid-flight INITIAL restart recovery via persisted lane (Mission 1 / item 1) ─
async def _submit_initial_no_terminal(monkeypatch, nonce, lane="lane-x"):
    """Reach: INITIAL reserved + SUBMITTED (credit MAY be spent), lane handle
    persisted, but NOT terminal and initial_operation_id still null."""
    planned, auth = await _plan_authorize(monkeypatch, nonce)
    job = await crud.get_video_production_job(planned["job_id"])
    idem = orch._stage_key(job, "INITIAL", job["logical_job_key"])
    await crud.reserve_video_job_side_effect(idem, job_id=job["job_id"], stage="INITIAL")
    await crud.increment_side_effect_submit_count(idem)
    await crud.update_video_job_side_effect(
        idem, submission_state=orch.SUB_SUBMITTED, credit_state=orch.CR_MAY_HAVE_SPENT,
        credit_balance_before=1000.0)
    await crud.update_video_production_job_full(
        job["job_id"], status=orch.S_INITIAL_SUBMITTING,
        initial_lane_job_id=lane, initial_lane_project_id=f"proj-{nonce}")
    return planned, auth, idem


def _resumer(*states):
    seq = list(states)
    calls = {"n": 0}
    async def resume(job):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]
    return resume, calls


async def test_restart_midflight_initial_resumes_without_resubmit(monkeypatch, tmp_path):
    planned, auth, idem = await _submit_initial_no_terminal(monkeypatch, "mfdone")
    client = FakeClient("mfdone")
    calls = []
    resume, rc = _resumer({"state": "DONE", "identity": {
        "operation_id": "init-mfdone", "media_id": "init-mfdone", "workflow_id": "wf",
        "project_id": "proj-mfdone", "scene_id": "scene-mfdone",
        "credit_balance_after": 990.0}})
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "mfdone"), resume_initial=resume,
        out_dir=tmp_path, poll_interval_s=0)
    assert calls == []          # the fresh generator was NEVER called (no re-submit)
    assert rc["n"] == 1         # it resumed via the persisted lane
    assert status["complete"] is True
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] == "init-mfdone"
    se = await crud.get_video_job_side_effect(idem)
    assert se["credit_state"] == orch.CR_SPENT   # 1000 -> 990 proven, from before+after


async def test_restart_midflight_initial_still_inflight_waits(monkeypatch, tmp_path):
    planned, auth, idem = await _submit_initial_no_terminal(monkeypatch, "mfwait")
    client = FakeClient("mfwait")
    calls = []
    resume, _ = _resumer({"state": "INFLIGHT"})
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "mfwait"), resume_initial=resume,
        out_dir=tmp_path, poll_interval_s=0)
    assert calls == [] and client.extend_submits == 0
    assert status["complete"] is False
    se = await crud.get_video_job_side_effect(idem)
    assert se["submission_state"] == orch.SUB_SUBMITTED   # still in flight, not lost


async def test_restart_midflight_initial_lane_lost_goes_recovery(monkeypatch, tmp_path):
    planned, auth, idem = await _submit_initial_no_terminal(monkeypatch, "mflost")
    client = FakeClient("mflost")
    calls = []
    resume, _ = _resumer({"state": "RECOVERY", "detail": "lane gone after restart"})
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "mflost"), resume_initial=resume,
        out_dir=tmp_path, poll_interval_s=0)
    assert calls == []                       # never re-submitted
    assert status["status"] == orch.S_INITIAL_RECOVERY
    se = await crud.get_video_job_side_effect(idem)
    assert se["submission_state"] == orch.SUB_UNCERTAIN
    assert se["credit_state"] == orch.CR_MAY_HAVE_SPENT   # honest: may have spent
    assert se["retry_safety"] == orch.RS_BLOCKED          # not auto-retried


async def test_restart_sweep_recovers_midflight_initial(monkeypatch, tmp_path):
    planned, auth, idem = await _submit_initial_no_terminal(monkeypatch, "mfsweep")
    client = FakeClient("mfsweep")
    resume, _ = _resumer({"state": "DONE", "identity": {
        "operation_id": "init-mfsweep", "media_id": "init-mfsweep", "workflow_id": "wf",
        "project_id": "proj-mfsweep", "scene_id": "scene-mfsweep"}})
    resumed = await orch.resume_in_flight_jobs(
        client, generate_initial=_initial_gen([], "mfsweep"), resume_initial=resume,
        out_dir=tmp_path)
    assert isinstance(resumed, list)
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] == "init-mfsweep"   # recovered, no re-submit
    assert client.extend_submits == 0                       # resume_only: no new credit


async def test_expiry_after_complete_is_inert(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "exp3")
    client = FakeClient("exp3")
    await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen([], "exp3"), out_dir=tmp_path, poll_interval_s=0)
    await _expire(planned["job_id"])
    before = (client.extend_submits, client.concat_submits)
    again = await orch.advance_job(
        client, planned["job_id"], authorization_token="expired",
        generate_initial=_initial_gen([], "exp3"), out_dir=tmp_path, poll_interval_s=0)
    assert again["complete"] is True
    assert (client.extend_submits, client.concat_submits) == before


# ── credit truth (Mission 6) ────────────────────────────────────────────────
async def test_credit_spent_only_with_debit_evidence(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "credit")
    client = FakeClient("credit", balance=1000.0)  # before = 1000
    await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen([], "credit", credit_after=990.0),  # proven -10
        out_dir=tmp_path, poll_interval_s=0)
    job = await crud.get_video_production_job(planned["job_id"])
    se = await crud.get_video_job_side_effect(
        orch._stage_key(job, "INITIAL", job["logical_job_key"]))
    assert se["credit_state"] == orch.CR_SPENT
    assert se["credit_balance_before"] == 1000.0 and se["credit_balance_after"] == 990.0


async def test_credit_may_have_spent_without_evidence(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "credit2")
    client = FakeClient("credit2")  # no balance ledger
    await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen([], "credit2"), out_dir=tmp_path, poll_interval_s=0)
    job = await crud.get_video_production_job(planned["job_id"])
    se = await crud.get_video_job_side_effect(
        orch._stage_key(job, "INITIAL", job["logical_job_key"]))
    assert se["credit_state"] == orch.CR_MAY_HAVE_SPENT  # never SPENT on success alone


# ── completed job returns the existing asset ────────────────────────────────
async def test_completed_job_returns_existing_asset(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "done")
    client = FakeClient("done")
    calls = []
    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=_initial_gen(calls, "done"), out_dir=tmp_path, poll_interval_s=0)
    first = await orch.advance_job(client, planned["job_id"], **args)
    again = await orch.advance_job(client, planned["job_id"], **args)
    assert first["final_media_id"] == again["final_media_id"]
    assert client.concat_submits == 1


# ── fail-closed 8s output for a 16s request ─────────────────────────────────
async def test_eight_second_final_fails_closed(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "short", duration=16)
    client = FakeClient("short", final_seconds=8.0)
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=_initial_gen([], "short"), out_dir=tmp_path, poll_interval_s=0)
    assert exc.value.code == orch.F_FINAL
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["status"] == orch.F_FINAL
    assert job["final_media_id"] is None
