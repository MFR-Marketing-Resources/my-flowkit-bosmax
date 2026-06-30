"""One-shot async Google Flow video pipeline (envelope → video URL).

Wraps the proven flow_client chain (create project → start frame → generate_video →
poll → download) behind an async job model, so the web/OTAK side makes ONE call and
polls `GET /job/{id}` instead of blocking ~6-7 min on a single HTTP request.

Contract: docs/INTEGRATION_CONTRACT.md §4-5. Reference CLI: scripts/api_shoot_video.py.

Design notes (locked with the OTAK side):
  - This endpoint MINTS its own project_id (create-project) and scene_id — the OTAK
    envelope must NOT carry them.
  - The signed GCS video URL EXPIRES; on success we download the bytes to local
    storage and return both `video_url` (fresh) and `local_path` (stable) + `media_id`.
  - reCAPTCHA cold-start: the first generate call after idle often times out; retry.
"""
import asyncio
import base64
import time
from pathlib import Path
from uuid import uuid4

import aiohttp

from agent.config import OUTPUT_DIR
from agent.services.flow_client import get_flow_client

PAID_TIERS = ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO")
CAPTCHA_RETRIES = 5
POLL_INTERVAL = 10
POLL_TIMEOUT = 420
_ONESHOT_DIR = OUTPUT_DIR / "oneshot"

# ── status values (mirror INTEGRATION_CONTRACT.md §4.2) ──────
SUBMITTED = "SUBMITTED"
RUNNING_FRAME = "RUNNING_FRAME"
SUBMITTED_VIDEO = "SUBMITTED_VIDEO"
POLLING = "POLLING"
SUCCESSFUL = "SUCCESSFUL"
FAILED = "FAILED"

# job_id -> state dict. In-memory is fine for the local single-operator tool;
# swap for a persistent store when this moves to a hosted box.
_JOBS: dict[str, dict] = {}


# ── helpers ──────────────────────────────────────────────────

def _find(obj, *keys):
    """Recursively find the first truthy value for any of `keys`."""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and v:
                    return v
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
    return None


def _find_operations(obj) -> list:
    ops = _find(obj, "operations")
    return ops if isinstance(ops, list) else []


def _is_captcha_fail(result: dict) -> bool:
    blob = str(result.get("error") or result.get("data") or "")
    return "CAPTCHA_FAILED" in blob


def _is_error(result: dict) -> bool:
    if result.get("error"):
        return True
    status = result.get("status")
    return isinstance(status, int) and status >= 400


async def _call_with_captcha_retry(make_coro, label: str, job: dict):
    """Run a flow_client coroutine, retrying past reCAPTCHA cold-start timeouts."""
    last = None
    for attempt in range(1, CAPTCHA_RETRIES + 1):
        result = await make_coro()
        if not _is_error(result):
            return result
        last = result
        if _is_captcha_fail(result):
            job["stage"] = f"{label}: reCAPTCHA warm-up (try {attempt})"
            await asyncio.sleep(2)
            continue
        return result  # non-captcha error (e.g. Google 500 entitlement) — stop
    return last


def get_job(job_id: str):
    """Return the public view of a job (no internal task handle)."""
    job = _JOBS.get(job_id)
    if not job:
        return None
    return {k: v for k, v in job.items() if k != "_task"}


async def start_job(envelope: dict, effective_tier: str) -> dict:
    """Mint a job, spawn the background pipeline, return immediately (§4.1)."""
    job_id = "j_" + uuid4().hex[:12]
    job = {
        "job_id": job_id, "status": SUBMITTED, "stage": "queued",
        "video_url": None, "local_path": None, "media_id": None, "error": None,
        "created_at": int(time.time()),
    }
    _JOBS[job_id] = job
    job["_task"] = asyncio.create_task(_run(job, envelope, effective_tier))
    return {"job_id": job_id, "status": SUBMITTED}


# ── the pipeline ─────────────────────────────────────────────

async def _run(job: dict, envelope: dict, tier: str):
    client = get_flow_client()
    try:
        aspect = envelope.get("aspect_ratio", "VIDEO_ASPECT_RATIO_PORTRAIT")
        img_aspect = aspect.replace("VIDEO_", "IMAGE_")
        prompt = envelope.get("prompt") or ""
        if not prompt.strip():
            raise ValueError("envelope.prompt is empty")
        frame = envelope.get("start_frame") or {}

        # 1) project (minted here — not from OTAK)
        job["status"] = RUNNING_FRAME
        job["stage"] = "creating project"
        proj = await client.create_project("oneshot " + time.strftime("%Y%m%d-%H%M%S"))
        if _is_error(proj):
            raise RuntimeError(f"create_project: {proj.get('error')}")
        project_id = _find(proj, "projectId", "project_id", "id")
        if not project_id:
            raise RuntimeError("create_project returned no projectId")
        scene_id = "oneshot-" + uuid4().hex[:8]   # minted here too

        # 2) start frame — AI generate OR product upload
        job["stage"] = "preparing start frame"
        mode = (frame.get("mode") or "ai").lower()
        if mode == "upload":
            b64 = (frame.get("image_base64") or "").strip()
            if not b64:
                raise ValueError("start_frame.mode=upload but image_base64 is empty")
            if b64.startswith("data:") and "," in b64:
                b64 = b64.split(",", 1)[1]
            up = await client.upload_image(
                b64, mime_type=frame.get("mime_type", "image/png"),
                project_id=project_id, file_name="product.png")
            if _is_error(up):
                raise RuntimeError(f"upload_image: {up.get('error')}")
            start_media = up.get("_mediaId") or _find(up, "media_id", "name")
        else:
            img_prompt = frame.get("image_prompt") or prompt
            img = await _call_with_captcha_retry(
                lambda: client.generate_images(
                    prompt=img_prompt, project_id=project_id,
                    aspect_ratio=img_aspect, user_paygate_tier=tier),
                "frame", job)
            if _is_error(img):
                raise RuntimeError(f"generate_images: {img.get('error') or img.get('data')}")
            start_media = _find(img, "mediaId", "name")
        if not start_media:
            raise RuntimeError("no start-frame media_id produced")

        # 3) submit video
        job["status"] = SUBMITTED_VIDEO
        job["stage"] = "submitting video"
        sub = await _call_with_captcha_retry(
            lambda: client.generate_video(
                start_image_media_id=start_media, prompt=prompt,
                project_id=project_id, scene_id=scene_id,
                aspect_ratio=aspect, user_paygate_tier=tier),
            "video", job)
        if _is_error(sub):
            raise RuntimeError(f"generate_video: {sub.get('error') or sub.get('data')}")
        ops = _find_operations(sub)
        if not ops:
            raise RuntimeError("generate_video returned no operations")

        # 4) poll
        job["status"] = POLLING
        elapsed = 0
        current = ops
        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            st = await client.check_video_status(current)
            if _is_error(st):
                continue
            new_ops = _find_operations(st)
            if new_ops:
                current = new_ops
            statuses = [o.get("status", "") for o in current]
            if any(s == "MEDIA_GENERATION_STATUS_FAILED" for s in statuses):
                raise RuntimeError("Google reported operation FAILED")
            done = sum(s == "MEDIA_GENERATION_STATUS_SUCCESSFUL" for s in statuses)
            job["stage"] = f"rendering ({done}/{len(current)}, {elapsed}s)"
            if done == len(current) and current:
                url = _find(st, "fifeUrl", "servingUri", "servingUrl", "url")
                video_media = _find(st, "mediaId", "name")
                job["video_url"] = url
                job["media_id"] = video_media
                job["local_path"] = await _download(url, job["job_id"]) if url else None
                job["status"] = SUCCESSFUL
                job["stage"] = "done"
                return
        raise TimeoutError(f"poll timeout after {POLL_TIMEOUT}s")
    except Exception as e:  # noqa: BLE001 — surface any failure to the job state
        job["status"] = FAILED
        job["error"] = str(e)
        job["stage"] = "failed"


async def _download(url: str, job_id: str):
    """Download the (expiring) signed video URL to stable local storage."""
    try:
        _ONESHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = _ONESHOT_DIR / f"{job_id}.mp4"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                path.write_bytes(await resp.read())
        return str(path)
    except Exception:  # noqa: BLE001 — download is best-effort; URL still returned
        return None
