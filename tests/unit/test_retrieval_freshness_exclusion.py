"""SEV-0 retrieval-freshness + steer-wording regression guards.

Live incident g_09ced57d5d4b (2026-07-11 17:08Z): the shared initial-generation lane
uploaded the approved product image (fresh media id + sha256 recorded), negotiated
correctly (model veo_3_1_r2v_lite, 8s, count 1, approved), and Google Flow generated
a real reference-anchored video — but RETRIEVAL delivered OLD clip 0af072c9 (recorded
in our own DB since 10:23Z) as the run's result, because the DOM-diff freshness
snapshot under-reports in a history-laden project: it saw 2 ids pre-poll, then the
periodic tab reload surfaced older project media that were never in the snapshot.

These tests pin the durable, DOM-independent exclusion: every media id BOSMAX has
EVER recorded (artifacts / results / extend lineage) can never be accepted as a
fresh run's output — a genuinely new clip mints a brand-new Flow id.

Also pins the steer-wording law (Mission 8): a correction must never say "no images"
(the previous incident proved the agent reads that as "drop the attached reference").
"""
import base64

import pytest

from agent.db import crud
from agent.services import agent_video as av
from agent.services import make_video as mv

OLD_CLIP = "0af072c9-270a-48dc-8811-fe6f4a968e08"


# ── durable DB exclusion set ─────────────────────────────────────────────────
async def test_known_media_ids_cover_artifacts_results_and_lineage():
    await crud.insert_generated_artifact("art-media-1", job_id="g_a", mode="F2V",
                                         artifact_kind="video", local_path="x.mp4")
    await crud.insert_generation_result(OLD_CLIP, job_id="g_old", mode="F2V")
    await crud.insert_extend_lineage(
        "el_test1", parent_operation_id="parent-op-1", child_operation_id="child-op-1",
        parent_primary_media_id="parent-pm-1", child_primary_media_id="child-pm-1")
    known = await crud.list_known_media_ids()
    assert {"art-media-1", OLD_CLIP, "parent-op-1", "child-op-1",
            "parent-pm-1", "child-pm-1"} <= known
    # a brand-new Flow id can never be pre-known
    assert "freshly-minted-new-clip" not in known


async def test_durable_exclusion_helper_fail_soft(monkeypatch):
    async def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(crud, "list_known_media_ids", boom)
    assert await mv._durable_media_exclusion() == set()


async def test_durable_exclusion_helper_passthrough():
    await crud.insert_generation_result(OLD_CLIP, job_id="g_old2", mode="F2V")
    assert OLD_CLIP in await mv._durable_media_exclusion()


# ── the incident scenario: an OLD harvestable clip must never be accepted ────
class _OldClipClient:
    """get_media serves a real finished video for the OLD clip — exactly what the
    reloaded editor DOM exposed in the incident."""
    def __init__(self):
        self.fetched = []

    async def get_media(self, mid):
        self.fetched.append(mid)
        return {"encodedVideo": base64.b64encode(b"\x00" * 2048).decode()}


async def test_incident_old_clip_is_skipped_when_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _OldClipClient()
    # incident shape: harvest offers ONLY the old clip; it is DB-known → excluded
    mid, path, size = await mv._save_video_by_get_media(
        client, [OLD_CLIP], exclude={OLD_CLIP})
    assert mid is None and path is None
    assert client.fetched == []          # never even fetched, let alone accepted


async def test_fresh_clip_is_accepted_next_to_old_one(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _OldClipClient()
    mid, path, size = await mv._save_video_by_get_media(
        client, [OLD_CLIP, "fresh-new-clip"], exclude={OLD_CLIP})
    assert mid == "fresh-new-clip"       # the old clip is skipped, the new one lands
    assert client.fetched == ["fresh-new-clip"]


# ── steer wording law (Mission 8) ────────────────────────────────────────────
def _perm(cost, nv=1, ni=0):
    return {"num_videos": nv, "num_images": ni, "total_cost": cost}


def test_steer_never_says_no_images():
    for perm in (None, _perm(10, nv=0, ni=4), _perm(10, nv=2), _perm(10, ni=2)):
        kind, msg, _ = av.decide(perm, "veo_3_1_lite", 8, 1, has_reference=True)
        assert "no images" not in (msg or "")


def test_steer_preserves_attached_reference():
    _, msg, _ = av.decide(None, "veo_3_1_lite", 8, 1, has_reference=True)
    assert "using the attached reference image" in msg
    # image-only proposal: rejected AND the correction keeps the reference
    kind, msg, _ = av.decide(_perm(8, nv=0, ni=4), "veo_3_1_lite", 8, 1, has_reference=True)
    assert kind == "reject"
    assert "using the attached reference image" in msg


def test_steer_t2v_without_reference_makes_no_reference_claim():
    _, msg, _ = av.decide(None, "veo_3_1_lite", 8, 1, has_reference=False)
    assert "attached reference" not in msg
    assert "no images" not in msg


def test_decisions_unchanged_by_wording_fix():
    # the proven cap-gate decisions stay byte-identical in KIND
    assert av.decide(_perm(10), "veo_3_1_lite", 8, 1, has_reference=True)[0] == "approve"
    assert av.decide(_perm(10, nv=2), "veo_3_1_lite", 8, 1)[0] == "reject"
    assert av.decide(_perm(8, nv=0, ni=4), "veo_3_1_lite", 8, 1)[0] == "reject"
    assert av.decide(_perm(15), "veo_3_1_lite", 8, 1)[0] == "reject"  # over ceiling


# ── T2V-fallback detection (Mission 11, captured veo_3_1 contract) ───────────
def test_reference_run_t2v_fallback_detected():
    # refs attached but a plain (text-only) veo key fired → the image was dropped
    assert mv._reference_run_dropped_reference(["m1"], "veo_3_1_lite") is True
    # the captured reference key from the live incident → correct reference run
    assert mv._reference_run_dropped_reference(["m1"], "veo_3_1_r2v_lite") is False


def test_reference_run_fallback_never_guessed():
    assert mv._reference_run_dropped_reference([], "veo_3_1_lite") is None       # T2V run
    assert mv._reference_run_dropped_reference(["m1"], None) is None             # no evidence
    assert mv._reference_run_dropped_reference(["m1"], "abra_fast") is None      # uncaptured engine
