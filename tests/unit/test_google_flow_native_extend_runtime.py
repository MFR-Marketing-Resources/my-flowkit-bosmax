"""Native-extend orchestrator — the single authoritative path:
explicit live/dry-run gates, bounded credit confirmation, parent-aware idempotency,
resume + partial-chain, crash-after-submit safety, lineage."""
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
    return [nx.ExtendBlock(block_index=i + 2, position=i + 1,
                           prompt=f"block {i + 2} full structured prompt {tag}",
                           is_final=(i == n - 1)) for i in range(n)]


def _req(blocks, pid="p", source="op1"):
    return nx.ExtendChainRequest(project_id=pid, scene_id=f"s-{pid}",
                                 source_operation_id=source, blocks=blocks)


async def _live(client, req, count, **kw):
    return await nx.run_native_extend_chain(
        client, req, dry_run=False, confirm_live_credit_burn=True,
        confirmed_extend_operation_count=count, poll_interval_s=0, **kw)


# ── dry-run + planning ──────────────────────────────────────────────────────
async def test_dry_run_plans_without_firing_and_reports_count():
    client = FakeClient(["c2", "c3"])
    out = await nx.run_native_extend_chain(
        client, _req(_blocks(2, "dry"), pid="p-dry"), dry_run=True)
    assert out["dry_run"] is True
    assert client.submits == []                       # zero credit
    assert out["planned_operation_count"] == 2        # explicit, both blocks fresh
    assert all(b["polling_state"] == "SOURCE_READY" for b in out["blocks"])
    assert out["blocks"][0]["planned_request"]["videoModelKey"] == "veo_3_1_extension_lite"


async def test_plan_is_resume_aware():
    plan = await nx.plan_native_extend_chain(_req(_blocks(3, "plan"), pid="p-plan"))
    assert plan["planned_operation_count"] == 3
    assert [s["needs_submit"] for s in plan["steps"]] == [True, True, True]


# ── explicit live/dry-run contract (no silent downgrade) ────────────────────
async def test_live_without_confirmation_fails_explicitly():
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(
            FakeClient(["c2"]), _req(_blocks(1, "noconf"), pid="p-noconf"),
            dry_run=False, confirm_live_credit_burn=False)
    assert exc.value.code == nx.LIVE_CREDIT_CONFIRMATION_REQUIRED


async def test_live_with_confirm_but_flag_off_fails(monkeypatch):
    monkeypatch.delenv("NATIVE_EXTEND_ENABLED", raising=False)
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(
            FakeClient(["c2"]), _req(_blocks(1, "flag"), pid="p-flag"),
            dry_run=False, confirm_live_credit_burn=True,
            confirmed_extend_operation_count=1)
    assert exc.value.code == nx.NATIVE_EXTEND_DISABLED


async def test_live_missing_count_fails(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(
            FakeClient(["c2"]), _req(_blocks(1, "nocount"), pid="p-nocount"),
            dry_run=False, confirm_live_credit_burn=True,
            confirmed_extend_operation_count=None)
    assert exc.value.code == nx.LIVE_CREDIT_CONFIRMATION_REQUIRED


async def test_live_count_must_match_plan(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    client = FakeClient(["c2", "c3"])
    with pytest.raises(nx.NativeExtendError) as exc:
        await _live(client, _req(_blocks(2, "cnt"), pid="p-cnt"), count=1)  # plan=2
    assert exc.value.code == nx.EXTEND_CONFIRMATION_COUNT_MISMATCH
    assert client.submits == []   # rejected before any submit


# ── live chaining + retrieval + lineage ─────────────────────────────────────
async def test_live_chain_block2_source_block3_child(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    client = FakeClient(["c2", "c3"])
    out = await _live(client, _req(_blocks(2, "live"), pid="p-live"), count=2)
    assert [b["child_operation_id"] for b in out["blocks"]] == ["c2", "c3"]
    assert client.submits[0]["source_operation_id"] == "op1"   # block2 parent = source
    assert client.submits[1]["source_operation_id"] == "c2"    # block3 parent = prev child
    assert out["chain"] == ["op1", "c2", "c3"]
    assert client.gets == ["c2", "c3"]
    row = await crud.get_extend_lineage_by_child("c3")
    assert row["parent_operation_id"] == "c2"
    assert row["child_operation_id"] != row["parent_operation_id"]


# ── idempotency / resume / partial chain ────────────────────────────────────
async def test_resume_does_not_resubmit_succeeded_block(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    req = _req(_blocks(1, "resume"), pid="p-resume")
    await _live(FakeClient(["c2"]), req, count=1)
    # everything succeeded -> plan now 0 submits; confirm 0
    client2 = FakeClient(["cX"])
    out2 = await _live(client2, req, count=0)
    assert out2["blocks"][0].get("resumed") is True
    assert client2.submits == []


async def test_partial_chain_resumes_at_next_block(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    req = _req(_blocks(2, "partial"), pid="p-partial")
    # first run: only enough children for block2 to succeed, block3 fails to harvest?
    # simpler: run block2 alone first (as a 1-block req sharing the same idem inputs)
    one = _req([req.blocks[0]], pid="p-partial")
    await _live(FakeClient(["c2"]), one, count=1)   # block2 SUCCEEDED, child c2
    # now the 2-block run: block2 resumes (no submit), block3 submits with parent c2
    client = FakeClient(["c3"])
    out = await _live(client, req, count=1)          # plan = 1 (only block3)
    assert out["blocks"][0].get("resumed") is True
    assert out["blocks"][1]["child_operation_id"] == "c3"
    assert len(client.submits) == 1
    assert client.submits[0]["source_operation_id"] == "c2"


async def test_parent_change_invalidates_old_idempotency(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    blocks = _blocks(1, "parentchg")
    # succeed against source opA
    await _live(FakeClient(["cA"]), _req(blocks, pid="p-pc", source="opA"), count=1)
    # same prompt/position but DIFFERENT parent opB -> new idem -> must submit anew
    client = FakeClient(["cB"])
    plan = await nx.plan_native_extend_chain(_req(blocks, pid="p-pc", source="opB"))
    assert plan["planned_operation_count"] == 1     # not reused
    out = await _live(client, _req(blocks, pid="p-pc", source="opB"), count=1)
    assert out["blocks"][0]["child_operation_id"] == "cB"   # fresh child, not cA
    assert client.submits[0]["source_operation_id"] == "opB"


async def test_in_flight_or_crashed_submit_blocks_duplicate(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    pid, sid, source = "p-inflight", "s-p-inflight", "op1"
    block = nx.ExtendBlock(block_index=2, position=1, prompt="dup prompt inflight")
    idem = nx._idempotency_key(pid, sid, 1, nx._prompt_hash("dup prompt inflight"), source)
    # simulate crash-after-submit: a row in EXTEND_SUBMITTED with NO child
    await crud.insert_extend_lineage(
        str(uuid.uuid4()), project_id=pid, scene_id=sid, block_index=2,
        block_position=1, parent_operation_id=source, idempotency_key=idem,
        polling_state="EXTEND_SUBMITTED")
    with pytest.raises(nx.NativeExtendError) as exc:
        await _live(FakeClient(["cZ"]), _req([block], pid=pid, source=source), count=1)
    assert exc.value.code == nx.EXTEND_DUPLICATE_SUBMISSION_BLOCKED


async def test_lineage_mismatch_when_child_equals_parent(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")

    class Echo(FakeClient):
        async def generate_video_extend(self, **kw):
            self.submits.append(kw)
            return {"media": [{"name": kw["source_operation_id"], "mediaMetadata": {
                "mediaStatus": {"mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SCHEDULED"}}}],
                "workflows": []}

    with pytest.raises(nx.NativeExtendError) as exc:
        await _live(Echo(["x"]), _req(_blocks(1, "mismatch"), pid="p-mismatch"), count=1)
    assert exc.value.code == nx.EXTEND_LINEAGE_MISMATCH


async def test_missing_source_operation_id():
    req = nx.ExtendChainRequest(project_id="p-missing", scene_id="s-missing",
                                source_operation_id="", blocks=_blocks(1, "missing"))
    with pytest.raises(nx.NativeExtendError) as exc:
        await nx.run_native_extend_chain(FakeClient(["c2"]), req, dry_run=True)
    assert exc.value.code == nx.EXTEND_PARENT_MEDIA_ID_MISSING


def test_extract_extend_child_live_response_shape():
    # Live response shape wrapped in envelope
    resp = {
        "status": 200,
        "data": {
            "remainingCredits": 1600,
            "workflows": [
                {
                    "name": "d7557fa6-6efe-4710-91d1-26ac17972a73",
                    "metadata": {
                        "displayName": "Product slow push-in soft light",
                        "createTime": "2026-07-11T05:47:41.754381Z",
                        "primaryMediaId": "12b526c5-5ea6-4120-ba53-e120eab6d242",
                        "batchId": "3aa6a033-1d1e-4881-88ee-d1abfed9fe5a"
                    }
                }
            ]
        }
    }
    child = nx.extract_extend_child(resp)
    assert child is not None
    assert child["child_operation_id"] == "12b526c5-5ea6-4120-ba53-e120eab6d242"
    assert child["child_primary_media_id"] == "12b526c5-5ea6-4120-ba53-e120eab6d242"
    assert child["child_workflow_id"] == "d7557fa6-6efe-4710-91d1-26ac17972a73"
    assert child["batch_id"] == "3aa6a033-1d1e-4881-88ee-d1abfed9fe5a"
    assert child["status"] == "MEDIA_GENERATION_STATUS_SCHEDULED"

