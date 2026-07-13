"""Final timeline runtime — captured-contract fixtures, gates, and fail-closed
duration validation (a 16s request must NEVER complete with an 8s segment)."""
import asyncio
import base64
import json
import os
import struct

import pytest

from agent.services import google_flow_final_timeline_runtime as ft

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures",
                   "google_flow_final_concat")


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


# ── synthetic MP4 (ftyp + moov/mvhd) so duration probing needs no ffmpeg ─────
def _mp4_bytes(duration_seconds: float, timescale: int = 1000,
               pad_to: int = 60_000) -> bytes:
    def box(typ: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + typ + payload

    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd_payload = (
        b"\x00" + b"\x00\x00\x00"          # version 0 + flags
        + struct.pack(">II", 0, 0)          # creation/modification
        + struct.pack(">I", timescale)
        + struct.pack(">I", int(duration_seconds * timescale))
        + b"\x00" * 80)
    moov = box(b"moov", box(b"mvhd", mvhd_payload))
    blob = ftyp + moov
    return blob + b"\x00" * max(0, pad_to - len(blob))  # plausible file size


# ── contract shapes (captured fixtures) ──────────────────────────────────────
def test_build_concat_input_matches_captured_shape():
    built = ft.build_concat_input(
        ["69051c7b-1a50-4560-89a8-50795e12ff5c",
         "164c65b0-5e58-48dd-a019-80a8ed461b4f"])
    assert built == _fx("concat_submit_request.sanitized.json")["inputVideos"]


def test_build_concat_input_needs_two_segments():
    with pytest.raises(ft.FinalTimelineError):
        ft.build_concat_input(["only-one"])


def test_extract_concat_job_from_captured_submit_response():
    out = ft.extract_concat_job(_fx("concat_submit_response.sanitized.json"))
    assert out["job_name"].endswith("/jobs/b5eaf875-0405-4d3f-85d6-8156d8b5661f")
    # the poll envelope is the submit response VERBATIM (captured contract)
    assert out["envelope"] == _fx("concat_submit_response.sanitized.json")


def test_extract_concat_job_fails_closed_without_job_name():
    with pytest.raises(ft.FinalTimelineError):
        ft.extract_concat_job({"operation": {}})


def test_parse_concat_poll_active_and_successful():
    active = ft.parse_concat_poll(_fx("concat_poll_active.sanitized.json"))
    assert active["terminal"] is False and active["successful"] is False
    done = ft.parse_concat_poll(_fx("concat_poll_successful.sanitized.json"))
    assert done["terminal"] is True and done["successful"] is True
    assert done["encoded_video"].startswith("<BASE64_MP4_REDACTED")


# ── identity discipline (Mission B) ──────────────────────────────────────────
def test_identities_stay_distinct():
    req = _fx("concat_submit_request.sanitized.json")
    resp = _fx("concat_submit_response.sanitized.json")
    scene = _fx("create_scene_response.sanitized.json")
    segment_media = {v["mediaGenerationId"] for v in req["inputVideos"]}
    job_name = resp["operation"]["operation"]["name"]
    workflow_id = scene["sceneWorkflows"][0]["workflow"]["name"]
    scene_id = scene["scene"]["sceneId"]
    # concat job / workflow / scene ids never collide with segment media ids
    assert job_name not in segment_media and "/jobs/" in job_name
    assert workflow_id not in segment_media
    assert scene_id not in segment_media
    # the segment media id IS the workflow's primaryMediaId (op-id equivalence)
    assert scene["sceneWorkflows"][0]["workflow"]["metadata"]["primaryMediaId"] \
        in segment_media


# ── final asset save + duration validation (Mission F) ──────────────────────
def test_save_final_video_and_duration_probe(tmp_path):
    blob = _mp4_bytes(16.0)
    saved = ft.save_final_video(base64.b64encode(blob).decode(), tmp_path, "vj_t1")
    assert saved["final_media_id"] == "final_vj_t1"
    assert os.path.exists(saved["local_path"])
    assert saved["sha256"]
    measured = ft.probe_mp4_duration_seconds(saved["local_path"])
    assert measured == pytest.approx(16.0, abs=0.01)
    assert ft.validate_final_duration(saved["local_path"], 16) == pytest.approx(16.0, abs=0.01)


def test_eight_second_output_fails_closed_for_sixteen_request(tmp_path):
    p = tmp_path / "seg.mp4"
    p.write_bytes(_mp4_bytes(8.0))
    with pytest.raises(ft.FinalTimelineError) as exc:
        ft.validate_final_duration(p, 16)
    assert exc.value.code == ft.FAIL_FINAL_DURATION


def test_unreadable_duration_fails_closed(tmp_path):
    p = tmp_path / "junk.mp4"
    p.write_bytes(b"\x00" * 80_000)
    with pytest.raises(ft.FinalTimelineError) as exc:
        ft.validate_final_duration(p, 16)
    assert exc.value.code == ft.FAIL_FINAL_DURATION


def test_save_rejects_implausibly_small_video(tmp_path):
    with pytest.raises(ft.FinalTimelineError) as exc:
        ft.save_final_video(base64.b64encode(b"tiny").decode(), tmp_path, "vj_t2")
    assert exc.value.code == ft.FAIL_FINAL_DOWNLOAD


# ── finalize orchestration: gates + happy path + resume ─────────────────────
class _Client:
    def __init__(self, poll_sequence, submit=None):
        self.submits = []
        self.polls = 0
        self._submit = submit or _fx("concat_submit_response.sanitized.json")
        self._seq = poll_sequence

    async def run_video_concatenation(self, input_videos):
        self.submits.append(input_videos)
        return self._submit

    async def check_video_concatenation_status(self, envelope):
        resp = self._seq[min(self.polls, len(self._seq) - 1)]
        self.polls += 1
        return resp

    async def get_media(self, media_id):
        # Each segment is a real ~8s block for the duration preflight.
        return {"data": {"encodedVideo":
                         base64.b64encode(_mp4_bytes(8.0)).decode()}}


def _patch_job_store(monkeypatch, existing=None):
    store = {"job": dict(existing or {})}

    async def _get(job_id):
        return store["job"] or None

    async def _update(job_id, **fields):
        store["job"].update(fields)

    monkeypatch.setattr(ft._crud, "get_video_production_job", _get, raising=False)
    monkeypatch.setattr(ft._crud, "update_video_production_job", _update,
                        raising=False)
    return store


SEGS = ["69051c7b-1a50-4560-89a8-50795e12ff5c",
        "164c65b0-5e58-48dd-a019-80a8ed461b4f"]


def test_finalize_dry_run_spends_nothing_and_shows_exact_plan(monkeypatch):
    _patch_job_store(monkeypatch)
    client = _Client([])
    out = asyncio.run(ft.finalize_timeline(
        client, job_id="vj_dry", segment_media_ids=SEGS, requested_seconds=16,
        out_dir=None, dry_run=True))
    assert out["dry_run"] is True
    assert out["planned_render_operation_count"] == 1
    assert out["planned_request"]["inputVideos"] == \
        _fx("concat_submit_request.sanitized.json")["inputVideos"]
    assert client.submits == []          # nothing fired


def test_finalize_live_requires_confirmation(monkeypatch):
    _patch_job_store(monkeypatch)
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.finalize_timeline(
            _Client([]), job_id="vj_conf", segment_media_ids=SEGS,
            requested_seconds=16, out_dir=None, dry_run=False))
    assert exc.value.code == ft.LIVE_CONFIRMATION_REQUIRED


def test_finalize_live_requires_kill_switch(monkeypatch):
    _patch_job_store(monkeypatch)
    monkeypatch.delenv("NATIVE_EXTEND_ENABLED", raising=False)
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.finalize_timeline(
            _Client([]), job_id="vj_flag", segment_media_ids=SEGS,
            requested_seconds=16, out_dir=None, dry_run=False,
            confirm_live_credit_burn=True))
    assert exc.value.code == ft.FINAL_TIMELINE_DISABLED


def test_finalize_live_happy_path_saves_and_validates(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    store = _patch_job_store(monkeypatch)
    encoded = base64.b64encode(_mp4_bytes(16.0)).decode()
    client = _Client([
        _fx("concat_poll_active.sanitized.json"),
        {"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "outputUri": "",
         "mediaGenerationId": "", "inputsCount": 3, "encodedVideo": encoded},
    ])
    out = asyncio.run(ft.finalize_timeline(
        client, job_id="vj_live", segment_media_ids=SEGS, requested_seconds=16,
        out_dir=tmp_path, dry_run=False, confirm_live_credit_burn=True,
        poll_interval_s=0))
    assert out["status"] == ft.JOB_COMPLETE
    assert out["measured_duration_s"] == pytest.approx(16.0, abs=0.01)
    assert out["final_media_id"] == "final_vj_live"
    assert len(client.submits) == 1
    assert store["job"]["final_concat_job_name"].endswith(
        "/jobs/b5eaf875-0405-4d3f-85d6-8156d8b5661f")
    assert store["job"]["status"] == ft.JOB_COMPLETE


def test_finalize_resumes_existing_job_without_resubmitting(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    _patch_job_store(monkeypatch, existing={
        "job_id": "vj_res",
        "final_concat_job_name":
            "projects/365941595420/locations/us-central1/jobs/b5eaf875-0405-4d3f-85d6-8156d8b5661f",
    })
    encoded = base64.b64encode(_mp4_bytes(16.0)).decode()
    client = _Client([
        {"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "outputUri": "",
         "mediaGenerationId": "", "inputsCount": 3, "encodedVideo": encoded},
    ])
    out = asyncio.run(ft.finalize_timeline(
        client, job_id="vj_res", segment_media_ids=SEGS, requested_seconds=16,
        out_dir=tmp_path, dry_run=False, confirm_live_credit_burn=True,
        poll_interval_s=0))
    assert out["resumed"] is True
    assert client.submits == []          # NEVER double-submit after a prior submit


def test_finalize_failed_render_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    _patch_job_store(monkeypatch)
    client = _Client([
        {"status": "MEDIA_GENERATION_STATUS_FAILED", "outputUri": "",
         "mediaGenerationId": "", "inputsCount": 0},
    ])
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.finalize_timeline(
            client, job_id="vj_fail", segment_media_ids=SEGS,
            requested_seconds=16, out_dir=tmp_path, dry_run=False,
            confirm_live_credit_burn=True, poll_interval_s=0))
    assert exc.value.code == ft.FAIL_FINAL_RENDER


# ── pre-concat segment-duration preflight ───────────────────────────────────
class _DurClient:
    """Client whose get_media returns a segment of a declared duration (or none)."""

    def __init__(self, durations: dict):
        self.durations = durations
        self.submits = []

    async def get_media(self, media_id):
        secs = self.durations.get(media_id)
        if secs is None:
            return {"data": {}}  # no encodedVideo → duration unavailable
        return {"data": {"encodedVideo": base64.b64encode(_mp4_bytes(secs)).decode()}}

    async def run_video_concatenation(self, input_videos):
        self.submits.append(input_videos)
        return _fx("concat_submit_response.sanitized.json")

    async def check_video_concatenation_status(self, envelope):
        return {"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "inputsCount": 2,
                "encodedVideo": base64.b64encode(_mp4_bytes(16.0)).decode()}


def test_preflight_two_8s_segments_pass(tmp_path):
    out = asyncio.run(ft.preflight_segment_durations(
        _DurClient({"a": 8.0, "b": 8.0}), ["a", "b"], 16, tmp_path))
    assert out["segment_count"] == 2
    assert out["total_duration_s"] == pytest.approx(16.0, abs=0.05)


def test_preflight_10s_plus_8s_fails_before_submit(tmp_path):
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.preflight_segment_durations(
            _DurClient({"a": 10.0, "b": 8.0}), ["a", "b"], 16, tmp_path))
    assert exc.value.code == ft.SEGMENT_DURATION_MISMATCH


def test_preflight_unknown_duration_fails(tmp_path):
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.preflight_segment_durations(
            _DurClient({"a": 8.0}), ["a", "b"], 16, tmp_path))
    assert exc.value.code == ft.SEGMENT_DURATION_UNAVAILABLE


def test_preflight_wrong_segment_count_fails(tmp_path):
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.preflight_segment_durations(
            _DurClient({"a": 8.0}), ["a"], 16, tmp_path))
    assert exc.value.code == ft.SEGMENT_COUNT_MISMATCH


def test_preflight_total_mismatch_fails(tmp_path):
    # each 9.4s is within ±1.5 of 8, but the total 18.8 != 16 (±1.5)
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.preflight_segment_durations(
            _DurClient({"a": 9.4, "b": 9.4}), ["a", "b"], 16, tmp_path))
    assert exc.value.code == ft.SEGMENT_TOTAL_DURATION_MISMATCH


def test_no_concat_submit_after_failed_preflight(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    _patch_job_store(monkeypatch)
    client = _DurClient({"a": 10.0, "b": 8.0})  # bad segment
    with pytest.raises(ft.FinalTimelineError) as exc:
        asyncio.run(ft.finalize_timeline(
            client, job_id="vj_pf", segment_media_ids=["a", "b"],
            requested_seconds=16, out_dir=tmp_path, dry_run=False,
            confirm_live_credit_burn=True, poll_interval_s=0))
    assert exc.value.code == ft.SEGMENT_DURATION_MISMATCH
    assert client.submits == []  # concat never fired after a failed preflight


def test_preflight_prefers_ondisk_segment(tmp_path):
    # a real retrieved clip on disk is probed directly (no get_media fetch needed)
    (tmp_path / "a.mp4").write_bytes(_mp4_bytes(8.0))
    (tmp_path / "b.mp4").write_bytes(_mp4_bytes(8.0))
    out = asyncio.run(ft.preflight_segment_durations(
        _DurClient({}), ["a", "b"], 16, tmp_path))  # empty client → must use disk
    assert out["segment_count"] == 2
