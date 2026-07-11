"""Native-extend orchestrator: dry-run planning, live submit->child->poll->harvest,
parent->child chaining, idempotency/resume, duplicate-in-flight block, gates."""
import uuid

import pytest

from agent.db import crud
from agent.services import google_flow_native_extend_runtime as nx


class FakeClient:
    connected = True

    def __init__(self, child_ids):
        self._child_ids = list(child_ids)
        self.submits = []
        self.polls = []
        self.gets = []

    async def generate_video_extend(self, **kw):
        self.submits.append(kw)
        cid = self._child_ids.pop(0)
        return {
            "remainingCredits": 1610,
            "workflows": [{"name": f"wf-{cid}",
                           "metadata": {"primaryMediaId": cid, "batchId": "b"}}],
            "media": [{"name": cid, "projectId": kw["project_id"],
                       "workflowId": f"wf-{cid}",
                       "mediaMetadata": {"mediaStatus": {
                           "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SCHEDULED"}}}],
        }

    async def check_video_status_by_media(self, media):
        self.polls.append(media)
        return {"media": [{"name": media[0]["name"], "mediaStatus": {
            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}}]}

    async def get_media(self, mid):
        self.gets.append(mid)
        return {"fifeUrl": f"https://flow-content.google/video/{mid}"}


def _blocks(n, tag=""):
    # `tag` keeps prompt text (hence the idempotency key) unique per test so
    # cross-test collisions can't occur even if the sqlite file isolation is
    # imperfect on Windows (WAL unlink can fail — see conftest).
    return [nx.ExtendBlock(block_index=i + 2, position=i + 1,
                           prompt=f"block {i + 2} full structured prompt {tag}",
                           is_final=(i == n - 1)) for i in range(n)]


def _req(blocks, pid="p"):
    return nx.ExtendChainRequest(project_id=pid, scene_id=f"s-{pid}",
                                 source_operation_id="op1", blocks=blocks)


async def test_dry_run_plans_without_firing():
    client = FakeClient(["c2", "c3"])
    out = await nx.run_native_extend_chain(
        client, _req(_blocks(2, "dry"), pid="p-dry"), dry_run=True)
    assert out["dry_run"] is True
    assert client.submits == []          # nothing fired — no credit spend
    assert all(b["polling_state"] == "SOURCE_READY" for b in out["blocks"])
    assert out["blocks"][0]["planned_request"]["videoModelKey"] == "veo_3_1_extension_lite"


async def test_live_chain_block2_uses_source_block3_uses_child(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    client = FakeClient(["c2", "c3"])
    out = await nx.run_native_extend_chain(
        client, _req(_blocks(2, "live"), pid="p-live"), dry_run=False,
        confirm_live_credit_burn=True, poll_interval_s=0)
    assert [b["child_operation_id"] for b in out["blocks"]] == ["c2", "c3"]
    assert client.submits[0]["source_media_id"] == "op1"   # block 2 parent = source
    assert client.submits[1]["source_media_id"] == "c2"    # block 3 parent = prev child
    assert out["chain"] == ["op1", "c2", "c3"]
    assert client.gets == ["c2", "c3"]                     # each child harvested
    assert all(b["polling_state"] == "EXTEND_SUCCEEDED" for b in out["blocks"])
    # lineage persisted, child != parent
    row = await crud.get_extend_lineage_by_child("c3")
    assert row["parent_operation_id"] == "c2"
    assert row["child_operation_id"] != row["parent_operation_id"]


async def test_disabled_gate_blocks_live(monkeypatch):
    monkeypatch.delenv("NATIVE_EXTEND_ENABLED", raising=False)
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(
            FakeClient(["c2"]), _req(_blocks(1, "dis"), pid="p-dis"), dry_run=False,
            confirm_live_credit_burn=True, poll_interval_s=0)
    assert exc.value.code == nx.NATIVE_EXTEND_DISABLED


async def test_resume_when_already_succeeded(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    req = _req(_blocks(1, "resume"), pid="p-resume")
    await nx.run_native_extend_chain(FakeClient(["c2"]), req, dry_run=False,
                                     confirm_live_credit_burn=True, poll_interval_s=0)
    # identical re-run resumes the SUCCEEDED block — no new submit
    client2 = FakeClient(["cX"])
    out2 = await nx.run_native_extend_chain(client2, req, dry_run=False,
                                            confirm_live_credit_burn=True, poll_interval_s=0)
    assert out2["blocks"][0].get("resumed") is True
    assert client2.submits == []


async def test_in_flight_duplicate_submission_blocked(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    pid, sid = "p-inflight", "s-p-inflight"  # sid must match _req's f"s-{pid}"
    block = nx.ExtendBlock(block_index=2, position=1, prompt="dup prompt inflight")
    idem = nx._idempotency_key(pid, sid, 1, nx._prompt_hash("dup prompt inflight"))
    await crud.insert_extend_lineage(
        str(uuid.uuid4()), project_id=pid, scene_id=sid, block_index=2,
        block_position=1, idempotency_key=idem, polling_state="EXTEND_SUBMITTED")
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(
            FakeClient(["cZ"]), _req([block], pid=pid), dry_run=False,
            confirm_live_credit_burn=True, poll_interval_s=0)
    assert exc.value.code == nx.EXTEND_DUPLICATE_SUBMISSION_BLOCKED


async def test_lineage_mismatch_when_child_equals_parent(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")

    class Echo(FakeClient):
        async def generate_video_extend(self, **kw):
            return {"media": [{"name": kw["source_media_id"], "mediaMetadata": {
                "mediaStatus": {"mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SCHEDULED"}}}],
                "workflows": []}

    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(
            Echo(["x"]), _req(_blocks(1, "mismatch"), pid="p-mismatch"), dry_run=False,
            confirm_live_credit_burn=True, poll_interval_s=0)
    assert exc.value.code == nx.EXTEND_LINEAGE_MISMATCH


async def test_missing_source_operation_id():
    req = nx.ExtendChainRequest(project_id="p-missing", scene_id="s-missing",
                                source_operation_id="", blocks=_blocks(1, "missing"))
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(FakeClient(["c2"]), req, dry_run=True)
    assert exc.value.code == nx.EXTEND_PARENT_MEDIA_ID_MISSING
