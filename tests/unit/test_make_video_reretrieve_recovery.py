"""Unit tests for session-pinned provider-media RE-RETRIEVAL recovery.

Covers ``make_video.reretrieve_provider_media_delivery``: for a durable job whose
provider media was ALREADY rendered but whose ORIGINAL local delivery failed
(``FINAL_ARTIFACT_DELIVERY_FAILED``), the recovery must

  * pin exactly one Flow session to the job's project,
  * acquire (and release) the single-flight video lane,
  * re-fetch the KNOWN media id's bytes and write them to the CURRENT
    ``config.OUTPUT_DIR`` retrieved path (never the stale stored ``local_path``),
  * record ``generated_artifact`` + ``generation_result`` via the shared seam,
  * mark the job COMPLETE,
  * and NEVER call a generation-submit method.

Pure logic — no network, no credits. The FlowClient double relays a known media
id's bytes and asserts if any generation-submit surface is touched.
"""
import base64
import json

import agent.services.make_video as mv
from agent.db import crud


_MEDIA_ID = "86e5a494-3c52-42b5-91c4-acfa34960543"
_PROJECT_ID = "proj-hybrid-10s"
_JOB_ID = "g_b27cf5602909"
# The failed job stored a local_path under a STALE base; recovery must ignore it.
_STALE_LOCAL = r"C:\stale\_ref_flowkit\output\retrieved\86e5a494.mp4"
_FAKE_BYTES = b"FAKE_MP4_BYTES" * 128  # > 1 KiB


class _ReretrieveClient:
    """Fake FlowClient double: relays a known media id's bytes; never submits."""

    connected = True

    def __init__(self):
        self.get_media_calls = []
        self.submit_calls = []

    async def get_media(self, media_id, media_generation_id=None):
        self.get_media_calls.append((media_id, media_generation_id))
        return {"data": {"encodedVideo": base64.b64encode(_FAKE_BYTES).decode()}}

    # Any generation-submit surface must NEVER be reached by a re-retrieval.
    async def create_agent_session(self, *a, **k):
        self.submit_calls.append("create_agent_session")
        raise AssertionError("recovery must not open an agent session")

    async def generate_video_with_references(self, *a, **k):
        self.submit_calls.append("generate_video_with_references")
        raise AssertionError("recovery must not submit a generation")

    async def start_generate(self, *a, **k):
        self.submit_calls.append("start_generate")
        raise AssertionError("recovery must not submit a generation")


def _durable_row(status="FINAL_ARTIFACT_DELIVERY_FAILED"):
    state = {
        "job_id": _JOB_ID,
        "status": status,
        "mode": "F2V",
        "source_mode": "HYBRID",
        "surface_lane": "HYBRID",
        "project_id": _PROJECT_ID,
        "request_id": "req-reretrieve",
        "num_videos": 1,
        "duration_s": 10,
        "artifacts": [
            {"media_id": _MEDIA_ID, "local_path": _STALE_LOCAL, "size_mb": 1.2},
        ],
    }
    return {"job_id": _JOB_ID, "status": status,
            "stage_state_json": json.dumps(state)}


def _install_crud_doubles(monkeypatch, *, result_row=None, acquired=True):
    generated = []
    results = []
    lease_calls = {"acquired": [], "released": []}

    async def get_job(job_id):
        assert job_id == _JOB_ID
        return _durable_row()

    async def get_generation_result(media_id):
        return result_row

    async def acquire_lease(job_id, **k):
        lease_calls["acquired"].append(job_id)
        row = {"job_id": job_id} if acquired else {"job_id": "g_other_owner"}
        return {"acquired": acquired, "row": row}

    async def release_lease(job_id, **k):
        lease_calls["released"].append(job_id)
        return True

    async def insert_generated_artifact(**kwargs):
        generated.append(kwargs)
        # Mimic the real readback: return the row with a matching local_path so
        # the seam's readback-path check passes.
        return {"local_path": kwargs.get("local_path")}

    async def insert_generation_result(media_id, **kwargs):
        results.append({"media_id": media_id, **kwargs})
        return {"media_id": media_id}

    monkeypatch.setattr(crud, "get_video_production_job", get_job)
    monkeypatch.setattr(crud, "get_generation_result", get_generation_result)
    monkeypatch.setattr(crud, "acquire_video_generation_lane_lease", acquire_lease)
    monkeypatch.setattr(crud, "release_video_generation_lane_lease", release_lease)
    monkeypatch.setattr(crud, "insert_generated_artifact", insert_generated_artifact)
    monkeypatch.setattr(crud, "insert_generation_result", insert_generation_result)
    return lease_calls, generated, results


async def test_reretrieve_downloads_and_completes_without_submit(monkeypatch, tmp_path):
    mv._JOBS.pop(_JOB_ID, None)
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(mv, "_measure_video_duration", lambda p: 10.0)

    client = _ReretrieveClient()
    monkeypatch.setattr(mv, "get_flow_client", lambda: client)

    pinned = {}

    async def fake_bind(client_arg, *, requested_project_id=None, mode=None):
        # Prove the recovery delegates to the canonical session-pin helper with
        # the job's project/mode. The lease protocol itself is covered by
        # test_make_video_binding.py.
        assert client_arg is client
        pinned["project_id"] = requested_project_id
        pinned["mode"] = mode
        return {"project_id": requested_project_id, "flow_tab_id": 7,
                "bridge_lease": {"connection_id": "conn-a", "released": True}}

    monkeypatch.setattr(mv, "ensure_editor_binding", fake_bind)

    synced = {}

    async def fake_sync(job):
        synced["status"] = (job or {}).get("status")
        return True

    monkeypatch.setattr(mv, "_sync_durable_single_job", fake_sync)

    lease_calls, generated, results = _install_crud_doubles(
        monkeypatch, result_row=None)

    snap = await mv.reretrieve_provider_media_delivery(_JOB_ID)

    # Session pinned to the job's project + mode.
    assert pinned == {"project_id": _PROJECT_ID, "mode": "F2V"}
    # Bytes re-fetched from the KNOWN media id, with NO generation submit.
    assert client.get_media_calls == [(_MEDIA_ID, None)]
    assert client.submit_calls == []
    # Written to the CURRENT OUTPUT_DIR, not the stale stored local_path.
    written = tmp_path / "retrieved" / f"{_MEDIA_ID}.mp4"
    assert written.exists()
    assert written.read_bytes() == _FAKE_BYTES
    assert str(written) != _STALE_LOCAL
    # Recorded via the shared delivery seam, with the FRESH path.
    assert len(generated) == 1
    assert generated[0]["media_id"] == _MEDIA_ID
    assert generated[0]["local_path"] == str(written)
    assert [r["media_id"] for r in results] == [_MEDIA_ID]
    # Single-flight lane acquired AND released.
    assert lease_calls["acquired"] == [_JOB_ID]
    assert lease_calls["released"] == [_JOB_ID]
    # COMPLETE, bytes-only recovery.
    assert snap["status"] == "DONE"
    assert snap["local_path"] == str(written)
    assert snap["reretrieve_recovery"]["state"] == "RERETRIEVED"
    assert snap["reretrieve_recovery"]["provider_generation_submits"] == 0
    assert synced["status"] == "DONE"


async def test_reretrieve_idempotent_when_bytes_and_result_present(monkeypatch, tmp_path):
    mv._JOBS.pop(_JOB_ID, None)
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(mv, "_measure_video_duration", lambda p: 10.0)
    # Bytes already persisted at the CURRENT path.
    (tmp_path / "retrieved").mkdir(parents=True, exist_ok=True)
    (tmp_path / "retrieved" / f"{_MEDIA_ID}.mp4").write_bytes(_FAKE_BYTES)

    client = _ReretrieveClient()
    monkeypatch.setattr(mv, "get_flow_client", lambda: client)

    binds = []

    async def fake_bind(*a, **k):
        binds.append(True)
        return {"project_id": _PROJECT_ID}

    monkeypatch.setattr(mv, "ensure_editor_binding", fake_bind)

    async def fake_sync(job):
        return True

    monkeypatch.setattr(mv, "_sync_durable_single_job", fake_sync)

    lease_calls, generated, results = _install_crud_doubles(
        monkeypatch, result_row={"media_id": _MEDIA_ID})

    snap = await mv.reretrieve_provider_media_delivery(_JOB_ID)

    # Short-circuit: no re-fetch, no session pin, no lease, no re-register.
    assert client.get_media_calls == []
    assert binds == []
    assert lease_calls["acquired"] == []
    assert generated == []
    assert snap["status"] == "DONE"
    assert snap["reretrieve_recovery"]["state"] == "ALREADY_COMPLETE"


async def test_reretrieve_fails_closed_and_releases_lease_when_unpinnable(monkeypatch, tmp_path):
    mv._JOBS.pop(_JOB_ID, None)
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(mv, "_measure_video_duration", lambda p: 10.0)

    client = _ReretrieveClient()
    monkeypatch.setattr(mv, "get_flow_client", lambda: client)

    async def fake_bind(*a, **k):
        raise mv.FlowEditorBindingError(
            "NO_OPEN_EDITOR: the target session cannot be pinned")

    monkeypatch.setattr(mv, "ensure_editor_binding", fake_bind)

    async def fake_sync(job):
        return True

    monkeypatch.setattr(mv, "_sync_durable_single_job", fake_sync)

    lease_calls, generated, results = _install_crud_doubles(
        monkeypatch, result_row=None)

    raised = None
    try:
        await mv.reretrieve_provider_media_delivery(_JOB_ID)
    except RuntimeError as exc:
        raised = exc

    # Fail closed: structured RuntimeError, no bytes fetched, no submit, and the
    # single-flight lane is released in the finally block.
    assert isinstance(raised, mv.FlowEditorBindingError)
    assert client.get_media_calls == []
    assert client.submit_calls == []
    assert generated == []
    assert lease_calls["acquired"] == [_JOB_ID]
    assert lease_calls["released"] == [_JOB_ID]
