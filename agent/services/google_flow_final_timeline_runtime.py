"""Final TIMELINE orchestration — ONE full-duration video from native-Extend segments.

Captured authority (concat_completion_smoke_20260711_100555):
  submit  POST /v1:runVideoFxConcatenation
          {"inputVideos":[{"mediaGenerationId", "length":"<ns>",
                           "startTimeOffset":"0.000000000s",
                           "endTimeOffset":"<s>.000000000s"}, ...]}
       -> {"operation":{"operation":{"name":"projects/<n>/locations/us-central1/jobs/<id>"}}}
  poll    POST /v1:runVideoFxCheckConcatenationStatus  (body = submit response VERBATIM)
       -> {"status":"MEDIA_GENERATION_STATUS_ACTIVE", ...}                (non-terminal)
       -> {"status":"MEDIA_GENERATION_STATUS_SUCCESSFUL",
           "inputsCount":N, "encodedVideo":"<base64 mp4>"}                (terminal)
  The ONE combined MP4 is delivered INLINE in ``encodedVideo`` (observed ~19.9M base64
  chars for a 16s timeline); ``mediaGenerationId``/``outputUri`` were empty.

Identity discipline (never interchangeable):
  * segment media/operation id  — a clip's ``media.name`` (== workflow metadata
    ``primaryMediaId``); what Extend binds as ``videoInput.mediaId`` and what the
    concat submit binds as ``inputVideos[].mediaGenerationId``.
  * workflow id                 — the scene-workflow record (``workflow.name``).
  * scene id                    — the timeline container.
  * concat job name             — ``projects/.../jobs/<uuid>`` (full resource path).
  * final artifact identity     — OUR saved file (sha256 + local path); the inline
    delivery carries no media id, so provenance = concat job name.

Credit posture: DRY-RUN by default. A live render requires the same explicit
confirm contract as native Extend (never silently downgraded, never auto-retried
after an uncertain submit). The Download-Project ZIP is NEVER a substitute.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import struct
import uuid
from pathlib import Path
from typing import Any, Optional

from agent.db import crud as _crud

# ── job states (Mission E) ───────────────────────────────────────────────────
JOB_PREPARING = "PREPARING"
JOB_INITIAL_READY = "INITIAL_SEGMENT_READY"
JOB_BINDING_EXTEND = "BINDING_EXTEND_CONTEXT"
JOB_EXTENDING = "EXTENDING_TIMELINE"
JOB_SEGMENTS_READY = "TIMELINE_SEGMENTS_READY"
JOB_FINALIZING = "FINALIZING_TIMELINE"
JOB_POLLING_FINAL = "POLLING_FINAL_RENDER"
JOB_RETRIEVING = "RETRIEVING_FINAL_VIDEO"
JOB_SAVING = "SAVING_FINAL_ASSET"
JOB_COMPLETE = "COMPLETE"

FAIL_SOURCE_CONTEXT = "SOURCE_CONTEXT_FAILED"
FAIL_EXTEND = "EXTEND_FAILED"
FAIL_FINAL_SUBMIT_UNCERTAIN = "FINAL_SUBMIT_UNCERTAIN"
FAIL_FINAL_RENDER = "FINAL_RENDER_FAILED"
FAIL_FINAL_MEDIA_MISSING = "FINAL_MEDIA_ID_MISSING"
FAIL_FINAL_DOWNLOAD = "FINAL_DOWNLOAD_FAILED"
FAIL_FINAL_DURATION = "FINAL_DURATION_MISMATCH"
# Pre-concat segment-duration preflight (uniform 8s contract, verified before submit).
SEGMENT_DURATION_UNAVAILABLE = "SEGMENT_DURATION_UNAVAILABLE"
SEGMENT_DURATION_MISMATCH = "SEGMENT_DURATION_MISMATCH"
SEGMENT_TOTAL_DURATION_MISMATCH = "SEGMENT_TOTAL_DURATION_MISMATCH"
SEGMENT_COUNT_MISMATCH = "SEGMENT_COUNT_MISMATCH"

LIVE_CONFIRMATION_REQUIRED = "LIVE_CREDIT_CONFIRMATION_REQUIRED"
FINAL_TIMELINE_DISABLED = "FINAL_TIMELINE_DISABLED"
FINAL_DUPLICATE_SUBMISSION_BLOCKED = "FINAL_DUPLICATE_SUBMISSION_BLOCKED"

STATUS_ACTIVE = "MEDIA_GENERATION_STATUS_ACTIVE"
STATUS_SUCCESSFUL = "MEDIA_GENERATION_STATUS_SUCCESSFUL"
STATUS_FAILED = "MEDIA_GENERATION_STATUS_FAILED"

CAPTURE_EVIDENCE_CONCAT = "CAPTURE_20260711_100555:rid=9924.2526/2540/2542"

# duration tolerance: engine block boundaries wobble slightly; an 8s-vs-16s
# substitution is the failure this exists to catch, so keep it tight.
DURATION_TOLERANCE_SECONDS = 1.5

_SEGMENT_SECONDS = 8  # uniform native-extend block duration (proven)


class FinalTimelineError(RuntimeError):
    """Machine-readable final-timeline failure (code + offending context)."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def final_timeline_enabled() -> bool:
    """Kill-switch mirrors native Extend: env flag must be explicitly on."""
    return os.environ.get("NATIVE_EXTEND_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


# ── concat request/response contract ────────────────────────────────────────
def build_concat_input(segment_media_ids: list[str],
                       segment_seconds: int = _SEGMENT_SECONDS) -> list[dict]:
    """Build ``inputVideos`` exactly as captured — ns length + second offsets."""
    if not segment_media_ids or len(segment_media_ids) < 2:
        raise FinalTimelineError(
            FAIL_FINAL_SUBMIT_UNCERTAIN,
            f"need >=2 segment media ids, got {len(segment_media_ids or [])}")
    ns = int(segment_seconds) * 1_000_000_000
    return [{
        "mediaGenerationId": mid,
        "length": str(ns),
        "startTimeOffset": "0.000000000s",
        "endTimeOffset": f"{int(segment_seconds)}.000000000s",
    } for mid in segment_media_ids]


def _deep_find_encoded_video(obj: object) -> Optional[str]:
    """Find the first ``encodedVideo`` base64 string in a media response."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if key == "encodedVideo" and isinstance(val, str) and val:
                    return val
                stack.append(val)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _decode_segment_to_probe(encoded_video_b64: str, out_dir: Path, mid: str) -> Optional[float]:
    """Decode an inline-base64 segment to a scratch file and probe its duration."""
    try:
        data = base64.b64decode(encoded_video_b64)
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None
    scratch = Path(out_dir) / f".probe_{mid}.mp4"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_bytes(data)
    try:
        return probe_mp4_duration_seconds(scratch)
    finally:
        try:
            scratch.unlink()
        except OSError:
            pass


async def preflight_segment_durations(
    client, segment_media_ids: list[str], requested_seconds: int, out_dir: Path,
    segment_seconds: int = _SEGMENT_SECONDS,
    tolerance: float = DURATION_TOLERANCE_SECONDS,
) -> dict:
    """Measure EVERY segment's real duration BEFORE the concat submit (zero credit).

    The native-Extend contract is uniform ``segment_seconds`` blocks; this proves it
    per clip instead of assuming it (build_concat_input hard-codes the length). Reuses
    the on-disk retrieved clip when present, else fetches media (get_media, free).
    Fails closed — a concat is never submitted when a duration is unknown or off.
    """
    expected_count = max(2, int(requested_seconds) // int(segment_seconds))
    if len(segment_media_ids) != expected_count:
        raise FinalTimelineError(
            SEGMENT_COUNT_MISMATCH,
            f"expected {expected_count} segments for {requested_seconds}s, "
            f"got {len(segment_media_ids)}")
    measured: list[float] = []
    for mid in segment_media_ids:
        dur: Optional[float] = None
        local = Path(out_dir) / f"{mid}.mp4"
        if local.is_file():
            dur = probe_mp4_duration_seconds(local)
        if dur is None:
            media = await client.get_media(mid)
            mdata = media.get("data", media) if isinstance(media, dict) else media
            enc = _deep_find_encoded_video(mdata)
            if enc:
                dur = _decode_segment_to_probe(enc, out_dir, mid)
        if dur is None:
            raise FinalTimelineError(
                SEGMENT_DURATION_UNAVAILABLE,
                f"segment {mid} duration could not be measured — refusing to concat "
                "with an unverified segment length")
        if abs(dur - float(segment_seconds)) > tolerance:
            raise FinalTimelineError(
                SEGMENT_DURATION_MISMATCH,
                f"segment {mid} measured {dur:.3f}s, expected ~{segment_seconds}s "
                f"(±{tolerance}s) — native-Extend blocks must be uniform")
        measured.append(round(dur, 3))
    total = round(sum(measured), 3)
    if abs(total - float(requested_seconds)) > tolerance:
        raise FinalTimelineError(
            SEGMENT_TOTAL_DURATION_MISMATCH,
            f"segments total {total}s != requested {requested_seconds}s "
            f"(±{tolerance}s)")
    return {"segment_durations_s": measured, "total_duration_s": total,
            "segment_count": len(measured)}


def _unwrap(resp: object) -> dict:
    if isinstance(resp, dict) and isinstance(resp.get("data"), dict):
        return resp["data"]
    return resp if isinstance(resp, dict) else {}


def extract_concat_job(submit_response: dict) -> dict:
    """Return the poll envelope (the submit response body VERBATIM) + job name."""
    data = _unwrap(submit_response)
    name = (((data.get("operation") or {}).get("operation") or {}).get("name")) or ""
    if not name or "/jobs/" not in name:
        raise FinalTimelineError(
            FAIL_FINAL_SUBMIT_UNCERTAIN,
            f"no concat job name in submit response: {str(data)[:200]}")
    return {"envelope": {"operation": {"operation": {"name": name}}}, "job_name": name}


def parse_concat_poll(poll_response: dict) -> dict:
    data = _unwrap(poll_response)
    status = data.get("status") or ""
    return {
        "status": status,
        "terminal": status in (STATUS_SUCCESSFUL, STATUS_FAILED),
        "successful": status == STATUS_SUCCESSFUL,
        "encoded_video": data.get("encodedVideo") or "",
        "media_generation_id": data.get("mediaGenerationId") or "",
        "output_uri": data.get("outputUri") or "",
        "inputs_count": data.get("inputsCount"),
    }


# ── final asset persistence + validation (Mission F) ────────────────────────
def save_final_video(encoded_video_b64: str, out_dir: Path,
                     job_id: str) -> dict:
    """Decode the inline MP4, persist it, and return identity evidence."""
    if not encoded_video_b64:
        raise FinalTimelineError(FAIL_FINAL_MEDIA_MISSING, "encodedVideo empty")
    try:
        raw = base64.b64decode(encoded_video_b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise FinalTimelineError(FAIL_FINAL_DOWNLOAD, f"base64: {exc}") from exc
    if len(raw) < 50_000:  # a real multi-segment MP4 is megabytes, not bytes
        raise FinalTimelineError(
            FAIL_FINAL_DOWNLOAD, f"implausible final size {len(raw)} bytes")
    out_dir.mkdir(parents=True, exist_ok=True)
    media_id = f"final_{job_id}"
    path = out_dir / f"{media_id}.mp4"
    path.write_bytes(raw)
    return {
        "final_media_id": media_id,
        "local_path": str(path),
        "size_mb": round(len(raw) / 1024 / 1024, 2),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def probe_mp4_duration_seconds(path: str | Path) -> Optional[float]:
    """Read the MP4 ``moov/mvhd`` duration without external tools.

    Returns None when the structure cannot be parsed (caller fails closed).
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None

    def find_box(buf: bytes, name: bytes, start: int = 0, end: int | None = None):
        end = len(buf) if end is None else end
        i = start
        while i + 8 <= end:
            size = struct.unpack(">I", buf[i:i + 4])[0]
            typ = buf[i + 4:i + 8]
            if size == 1:  # 64-bit box size
                if i + 16 > end:
                    return None
                size = struct.unpack(">Q", buf[i + 8:i + 16])[0]
                payload = i + 16
            else:
                payload = i + 8
            if size < 8:
                return None
            if typ == name:
                return payload, min(i + size, end)
            i += size
        return None

    moov = find_box(data, b"moov")
    if not moov:
        return None
    mvhd = find_box(data, b"mvhd", moov[0], moov[1])
    if not mvhd:
        return None
    p = mvhd[0]
    version = data[p]
    try:
        if version == 1:
            timescale = struct.unpack(">I", data[p + 20:p + 24])[0]
            duration = struct.unpack(">Q", data[p + 24:p + 32])[0]
        else:
            timescale = struct.unpack(">I", data[p + 12:p + 16])[0]
            duration = struct.unpack(">I", data[p + 16:p + 20])[0]
    except struct.error:
        return None
    if not timescale:
        return None
    return duration / timescale


def validate_final_duration(path: str | Path, requested_seconds: int,
                            tolerance: float = DURATION_TOLERANCE_SECONDS) -> float:
    """Fail closed unless the saved file is the FULL timeline duration.

    A 16s request that yields ~8s means a single segment was substituted for the
    combined timeline — the exact defect this gate exists to catch.
    """
    measured = probe_mp4_duration_seconds(path)
    if measured is None:
        raise FinalTimelineError(FAIL_FINAL_DURATION, "duration unreadable (fail closed)")
    if abs(measured - float(requested_seconds)) > tolerance:
        raise FinalTimelineError(
            FAIL_FINAL_DURATION,
            f"measured {measured:.2f}s vs requested {requested_seconds}s "
            f"(tolerance {tolerance}s)")
    return measured


# ── the finalize orchestration (submit → poll → save → validate) ────────────
async def finalize_timeline(client, *, job_id: str, segment_media_ids: list[str],
                            requested_seconds: int, out_dir: Path,
                            dry_run: bool = True,
                            confirm_live_credit_burn: bool = False,
                            poll_timeout_s: int = 600,
                            poll_interval_s: int = 10) -> dict:
    """Render the ONE final full-duration video for a logical video job.

    DRY-RUN returns the exact planned submit body and spends nothing. A live run
    requires the kill-switch AND explicit confirmation; an uncertain submit is
    never auto-retried (resume uses the persisted concat job name instead).
    """
    input_videos = build_concat_input(segment_media_ids,
                                      segment_seconds=_SEGMENT_SECONDS)
    plan = {
        "job_id": job_id,
        "planned_request": {"endpoint": "/v1:runVideoFxConcatenation",
                            "inputVideos": input_videos},
        "planned_render_operation_count": 1,
        "requested_seconds": requested_seconds,
        "capture_evidence": CAPTURE_EVIDENCE_CONCAT,
    }
    if dry_run:
        return {**plan, "dry_run": True, "status": JOB_SEGMENTS_READY}

    if not confirm_live_credit_burn:
        raise FinalTimelineError(LIVE_CONFIRMATION_REQUIRED, "finalize")
    if not final_timeline_enabled():
        raise FinalTimelineError(FINAL_TIMELINE_DISABLED, "NATIVE_EXTEND_ENABLED!=1")

    job = await _crud.get_video_production_job(job_id)
    if job and job.get("final_concat_job_name"):
        # A submit already happened — NEVER double-submit; resume polling instead.
        envelope = {"operation": {"operation": {"name": job["final_concat_job_name"]}}}
        job_name = job["final_concat_job_name"]
        resumed = True
        preflight = None
    else:
        # Duration preflight (zero credit) — prove every segment is a real ~8s block
        # and the total matches BEFORE submitting the concat. Fails closed.
        preflight = await preflight_segment_durations(
            client, segment_media_ids, requested_seconds, out_dir)
        await _crud.update_video_production_job(job_id, status=JOB_FINALIZING)
        submit = await client.run_video_concatenation(input_videos)
        if submit.get("error") or (isinstance(submit.get("status"), int)
                                   and submit["status"] >= 400):
            raise FinalTimelineError(
                FAIL_FINAL_SUBMIT_UNCERTAIN, str(submit)[:300])
        extracted = extract_concat_job(submit)
        envelope, job_name = extracted["envelope"], extracted["job_name"]
        await _crud.update_video_production_job(
            job_id, status=JOB_POLLING_FINAL, final_concat_job_name=job_name)
        resumed = False

    deadline = asyncio.get_event_loop().time() + poll_timeout_s
    last = None
    while asyncio.get_event_loop().time() < deadline:
        poll = await client.check_video_concatenation_status(envelope)
        last = parse_concat_poll(poll)
        if last["terminal"]:
            break
        await asyncio.sleep(poll_interval_s)
    if not last or not last["terminal"]:
        raise FinalTimelineError(
            FAIL_FINAL_RENDER, f"no terminal status within {poll_timeout_s}s "
            f"(last={last and last['status']}); job {job_name} resumes safely")
    if not last["successful"]:
        await _crud.update_video_production_job(
            job_id, status=FAIL_FINAL_RENDER, error_code=FAIL_FINAL_RENDER)
        raise FinalTimelineError(FAIL_FINAL_RENDER, last["status"])

    await _crud.update_video_production_job(job_id, status=JOB_RETRIEVING)
    saved = save_final_video(last["encoded_video"], out_dir, job_id)
    measured = validate_final_duration(saved["local_path"], requested_seconds)
    await _crud.update_video_production_job(
        job_id, status=JOB_COMPLETE,
        final_media_id=saved["final_media_id"],
        final_local_path=saved["local_path"],
        final_sha256=saved["sha256"],
        final_duration_s=measured)
    return {
        **plan, "dry_run": False, "resumed": resumed,
        "final_concat_job_name": job_name,
        **saved, "measured_duration_s": measured,
        "segment_preflight": preflight,
        "status": JOB_COMPLETE,
    }
