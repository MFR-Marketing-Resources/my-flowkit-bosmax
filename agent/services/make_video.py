"""End-to-end automated video pipeline (flowCreationAgent).

One async job does everything: create project -> AI start frame -> agent session ->
negotiate + approve (1 video, Veo 3.1 Lite) -> wait for the render -> navigate the
Flow tab to the project + harvest the video media_id -> get_media returns the bytes
(base64 encodedVideo) -> save the .mp4 into the system. Poll GET /video-job/{id}.
"""
import asyncio
import base64
import json
import re
import time
from uuid import uuid4

from agent.config import OUTPUT_DIR
from agent.services.flow_client import get_flow_client
from agent.services import agent_video
from agent.services import video_models

_JOBS: dict = {}

# Single-flight video lane: the extension drives ONE Flow tab, so at most one video
# job may be in flight at a time. IMG is exempt. (Locked patch H.)
_VIDEO_LANE_JOB = None
_JOB_TTL = 1800  # seconds — GC finished jobs after this.


def _job_active(job_id) -> bool:
    j = _JOBS.get(job_id)
    return bool(j) and j.get("status") not in ("DONE", "FAILED", "REJECTED")


def _gc_jobs():
    now = time.time()
    for jid in [k for k, v in _JOBS.items()
                if v.get("status") in ("DONE", "FAILED", "REJECTED")
                and (now - v.get("created", now)) > _JOB_TTL]:
        _JOBS.pop(jid, None)


async def _bind_editor_session(client, requested_project_id=None) -> dict:
    """Bind a video job to the OPEN Flow editor → {project_id, flow_tab_id, flow_project_url}.
    Fail-closed (locked patch A/G): raise if no editor project is open, or if the open editor
    differs from a requested project_id. Never mint a hidden project; never use the wrong tab."""
    h = await client.harvest_video_urls()
    inner = h.get("result", h) if isinstance(h, dict) else {}
    if (not isinstance(inner, dict) or inner.get("error") == "NO_FLOW_TAB"
            or inner.get("flow_tab_found") is False):
        raise RuntimeError("NO_OPEN_EDITOR: open the target Flow project in the controlled tab first")
    flow_url = inner.get("flow_url") or ""
    flow_tab_id = inner.get("flow_tab_id")
    diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
    project_id = diag.get("projectId") if isinstance(diag, dict) else None
    if not project_id or "/project/" not in str(flow_url):
        raise RuntimeError("NO_OPEN_EDITOR: the Flow tab is not on a project editor — open the project first")
    if requested_project_id and requested_project_id != project_id:
        raise RuntimeError(
            f"PROJECT_TAB_MISMATCH: requested {requested_project_id} but the open editor is {project_id}")
    return {"project_id": project_id, "flow_tab_id": flow_tab_id, "flow_project_url": flow_url}


def get_job(job_id: str):
    j = _JOBS.get(job_id)
    if not j:
        return None
    return {k: v for k, v in j.items() if k != "_task"}


def _pid(obj) -> str:
    m = re.search(r'"projectId"\s*:\s*"([^"]+)"', json.dumps(obj))
    return m.group(1) if m else ""


def _deep(obj, *keys):
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


async def start(prompt: str, image_prompt: str) -> dict:
    job_id = "v_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                     "project_id": None, "local_path": None, "video_media_id": None,
                     "size_mb": None, "error": None}
    _JOBS[job_id]["_task"] = asyncio.create_task(_run(job_id, prompt, image_prompt))
    return {"job_id": job_id, "status": "SUBMITTED"}


async def start_negotiate(prompt: str, image_prompt: str = None, dry: bool = True,
                          model: str = None, duration_s: int = None,
                          project_id: str = None) -> dict:
    """Async negotiation job — captures the FULL transcript (so a client timeout never
    loses it). dry=True stops before approving (0 video credits). model/duration steer the
    agent (patch I4a); project_id reuses an existing project (minimise junk); image_prompt=None
    skips the start frame (pure T2V dry capture)."""
    job_id = "n_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                     "project_id": project_id, "dry": dry, "model": model,
                     "result": None, "transcript": None, "error": None,
                     "created": time.time()}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_negotiate(job_id, prompt, image_prompt, dry, model, duration_s, project_id))
    return {"job_id": job_id, "status": "SUBMITTED"}


# Known stale video id from an earlier project — must never be accepted as "the new video".
_STALE_VIDEO_IDS = {"b267d480-a516-4d00-a7a4-ac39bdae479d"}


async def start_on_existing(project_id: str, image_media_id: str, prompt: str) -> dict:
    """DEPRECATED — superseded by start_generate("I2V", ...). The /make-video-existing
    endpoint now routes through the guarded one door; this legacy path has NO single-flight
    lane, bound-session, or drift invariants. Do not call it for new work.

    Generate a video in an EXISTING project using an EXISTING (user-uploaded) image,
    then retrieve the real new video and save it. The Flow tab must be on this project."""
    job_id = "x_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                     "project_id": project_id, "image_media_id": image_media_id,
                     "local_path": None, "video_media_id": None, "size_mb": None,
                     "approved": None, "generation_started": None, "error": None}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_on_existing(job_id, project_id, image_media_id, prompt))
    return {"job_id": job_id, "status": "SUBMITTED"}


async def _run_on_existing(job_id: str, project_id: str, image_media_id: str, prompt: str):
    import base64
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        job["status"], job["stage"] = "NEGOTIATING", "agent session"
        sess = await client.create_agent_session(project_id)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        job["stage"] = "negotiating (approve 1 video, Veo Lite)"
        res = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, [image_media_id])
        job["approved"] = res.get("approved")
        job["generation_started"] = res.get("generation_started")
        if not res.get("approved"):
            raise RuntimeError("agent did not approve a video: " + str(res.get("error") or res))

        # Retrieve the NEW video. Harvest the (user's) tab — already on this project, no drift.
        # Accept only a media_id whose get_media returns video.encodedVideo (a real video),
        # excluding the start image and any known stale id.
        job["status"], job["stage"] = "GENERATING", "rendering + retrieving"
        exclude = set(_STALE_VIDEO_IDS) | {image_media_id}
        await asyncio.sleep(120)
        for i in range(36):
            job["stage"] = f"checking for finished video (try {i + 1})"
            h = await client.harvest_video_urls()
            inner = h.get("result", h) if isinstance(h, dict) else {}
            diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
            cands = []
            for k in ("videoIds", "imageIds", "mediaIds"):
                cands += (diag.get(k) or []) if isinstance(diag, dict) else []
            for mid in dict.fromkeys(cands):  # de-dupe, keep order
                if mid in exclude:
                    continue
                media = await client.get_media(mid)
                mdata = media.get("data", media) if isinstance(media, dict) else media
                enc = _deep(mdata, "encodedVideo")
                if enc:
                    vbytes = base64.b64decode(enc)
                    outdir = OUTPUT_DIR / "retrieved"
                    outdir.mkdir(parents=True, exist_ok=True)
                    path = outdir / f"{mid}.mp4"
                    path.write_bytes(vbytes)
                    job["status"], job["stage"] = "DONE", "done"
                    job["local_path"] = str(path)
                    job["video_media_id"] = mid
                    job["size_mb"] = round(len(vbytes) / 1024 / 1024, 2)
                    return
            await asyncio.sleep(18)
        job["status"], job["error"] = "FAILED", "video not found/retrieved in time"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"], job["stage"] = "FAILED", str(e), "failed"


_VIDEO_MODES = ("T2V", "I2V", "F2V")
_ALL_MODES = ("IMG",) + _VIDEO_MODES


async def start_generate(mode: str, prompt: str, project_id: str = None,
                         image_media_ids: list = None, image_prompt: str = None,
                         aspect: str = "9:16", tier: str = "PAYGATE_TIER_ONE",
                         model: str = None, duration_s: int = None) -> dict:
    """THE one door. mode = IMG | T2V | I2V | F2V. Returns a job_id; poll get_job."""
    global _VIDEO_LANE_JOB
    _gc_jobs()
    mode = (mode or "").upper()
    # Single-flight (patch H): one video job at a time on the shared Flow tab. IMG exempt.
    if mode in _VIDEO_MODES and _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"status": "REJECTED", "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "g_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                     "stage": "queued", "project_id": project_id, "local_path": None,
                     "media_id": None, "size_mb": None, "artifact": None,
                     "approved": None, "binding": None, "model": model,
                     "error": None, "created": time.time()}
    if mode in _VIDEO_MODES:
        _VIDEO_LANE_JOB = job_id  # claim the lane synchronously to avoid a race
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_generate(job_id, mode, prompt, project_id, image_media_ids, image_prompt,
                      aspect, tier, model, duration_s))
    return {"job_id": job_id, "status": "SUBMITTED", "mode": mode}


async def _save_video_by_get_media(client, candidates, exclude) -> tuple:
    """Return (media_id, mp4_path, size_mb) for the first candidate whose get_media
    yields a real video (encodedVideo), excluding stale/reference ids. Else (None,..)."""
    import base64
    for mid in dict.fromkeys(candidates):  # de-dupe, keep order
        if mid in exclude:
            continue
        media = await client.get_media(mid)
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        if enc:
            vbytes = base64.b64decode(enc)
            outdir = OUTPUT_DIR / "retrieved"
            outdir.mkdir(parents=True, exist_ok=True)
            path = outdir / f"{mid}.mp4"
            path.write_bytes(vbytes)
            return mid, str(path), round(len(vbytes) / 1024 / 1024, 2)
    return None, None, None


async def _run_generate(job_id, mode, prompt, project_id, image_media_ids,
                        image_prompt, aspect, tier, model=None, duration_s=None):
    from agent.api.flow import (_generate_image_with_recovery, _extract_images,
                                 _extract_project_id, _IMG_ASPECT_MAP)
    import aiohttp
    global _VIDEO_LANE_JOB
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        if mode not in _ALL_MODES:
            raise RuntimeError(f"unknown mode '{mode}' (use IMG/T2V/I2V/F2V)")
        aspect_key = _IMG_ASPECT_MAP.get(aspect, "IMAGE_ASPECT_RATIO_PORTRAIT")

        # 1) project: IMG may mint a fresh project; video modes BIND to the OPEN editor
        #    (patch A/G — never mint a hidden project; fail-closed if no editor is open).
        if mode == "IMG":
            if not project_id:
                job["status"], job["stage"] = "SETUP", "creating project"
                proj = await client.create_project(f"{mode.lower()} auto")
                project_id = _extract_project_id(proj)
                if not project_id:
                    raise RuntimeError("create_project returned no projectId")
        else:
            job["status"], job["stage"] = "SETUP", "binding to open Flow editor"
            binding = await _bind_editor_session(client, project_id)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id

        # 2) IMG — direct image API, no agent, no video credits
        if mode == "IMG":
            job["status"], job["stage"] = "GENERATING", "generating image"
            res = await _generate_image_with_recovery(
                client, prompt, project_id, aspect_key, tier, image_media_ids or [])
            if not res or res.get("error"):
                raise RuntimeError("image gen failed: " + str((res or {}).get("error")))
            imgs = _extract_images(res.get("data", res))
            if not imgs or not imgs[0].get("url"):
                raise RuntimeError("no image/url returned")
            mid, url = imgs[0]["media_id"], imgs[0]["url"]
            outdir = OUTPUT_DIR / "retrieved"
            outdir.mkdir(parents=True, exist_ok=True)
            path = outdir / f"{mid}.jpg"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                async with s.get(url) as r:
                    if r.status != 200:
                        raise RuntimeError(f"image download HTTP {r.status}")
                    data = await r.read()
            path.write_bytes(data)
            job.update(status="DONE", stage="done", media_id=mid, local_path=str(path),
                       size_mb=round(len(data) / 1024 / 1024, 2), artifact="image")
            return

        # 3) T2V / I2V / F2V — agent video
        refs = [m for m in (image_media_ids or []) if m]
        if mode in ("I2V", "F2V") and not refs:
            if image_prompt:
                job["status"], job["stage"] = "SETUP", "generating start frame"
                ires = await _generate_image_with_recovery(
                    client, image_prompt, project_id, aspect_key, tier, [])
                imgs = _extract_images((ires or {}).get("data", ires or {}))
                if imgs:
                    refs = [imgs[0]["media_id"]]
            if not refs:
                raise RuntimeError(f"{mode} needs a reference image (image_media_ids or image_prompt)")

        job["status"], job["stage"] = "NEGOTIATING", "agent session"
        sess = await client.create_agent_session(project_id)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        job["stage"] = f"negotiating (approve 1 video, {video_models.resolve(model)['ui_label']})"
        nres = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, refs,
            target_model=model, target_duration_s=duration_s)
        job["approved"] = nres.get("approved")
        # Expose the FULL post-approve verification status on the job (the API returns the job
        # dict verbatim), so an unverified generation is NEVER presented as fully verified.
        job["model_used"] = nres.get("model_used")
        job["model_ok"] = nres.get("model_ok")
        job["duration_used"] = nres.get("duration_used")
        job["duration_ok"] = nres.get("duration_ok")
        # Post-approve verification (Layer A): a CONFIRMED model OR duration mismatch hard-fails.
        if nres.get("model_ok") is False:
            raise RuntimeError(
                f"FAILED_WRONG_MODEL: expected {model or 'default'}, got {nres.get('model_used')}")
        if nres.get("duration_ok") is False:
            raise RuntimeError(
                f"FAILED_WRONG_DURATION: expected {duration_s or 'default'}s, got {nres.get('duration_used')}s")
        # Evidence ABSENT from the approved SSE (e.g. an unrecognized generation tool) → unknown,
        # NOT a hard fail, but FLAGGED so it is never reported as verified. A None model_used means
        # the fired tool was unrecognized, in which case duration is absent too (both flags set).
        if nres.get("approved"):
            if nres.get("model_ok") is None:
                job["model_unverified"] = True
            if nres.get("duration_ok") is None:
                job["duration_unverified"] = True
        if not nres.get("approved"):
            raise RuntimeError("agent did not approve a video: " + str(nres.get("error") or nres))

        job["status"], job["stage"] = "GENERATING", "rendering + retrieving"
        exclude = set(_STALE_VIDEO_IDS) | set(refs)
        await asyncio.sleep(120)
        for i in range(36):
            job["stage"] = f"checking for finished video (try {i + 1})"
            bound_tab = (job.get("binding") or {}).get("flow_tab_id")
            h = await client.harvest_video_urls(tab_id=bound_tab)
            inner = h.get("result", h) if isinstance(h, dict) else {}
            # Fail-closed harvest (patch A/G): abort on a lost/bound-gone tab or a drifted
            # project instead of polling into a generic late timeout.
            if (not isinstance(inner, dict)
                    or inner.get("error") in ("NO_FLOW_TAB", "BOUND_TAB_GONE")
                    or inner.get("flow_tab_found") is False):
                raise RuntimeError("EDITOR_TAB_LOST: the bound Flow tab/editor is gone")
            diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
            seen_pid = diag.get("projectId") if isinstance(diag, dict) else None
            if seen_pid and seen_pid != project_id:
                raise RuntimeError(
                    f"PROJECT_DRIFT: tab moved to {seen_pid}, expected {project_id}")
            seen_tab = inner.get("flow_tab_id")
            if bound_tab is not None and seen_tab is not None and seen_tab != bound_tab:
                raise RuntimeError(
                    f"TAB_DRIFT: harvest tab {seen_tab} != bound {bound_tab}")
            cands = []
            for k in ("videoIds", "imageIds", "mediaIds"):
                cands += (diag.get(k) or []) if isinstance(diag, dict) else []
            mid, path, size = await _save_video_by_get_media(client, cands, exclude)
            if mid:
                job.update(status="DONE", stage="done", media_id=mid, local_path=path,
                           size_mb=size, artifact="video")
                return
            await asyncio.sleep(18)
        job.update(status="FAILED", error="video not found/retrieved in time")
    except Exception as e:  # noqa: BLE001
        job.update(status="FAILED", error=str(e), stage="failed")
    finally:
        # Release the single-flight video lane (patch H).
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None


async def _run_negotiate(job_id, prompt, image_prompt=None, dry=True,
                         model=None, duration_s=None, project_id=None):
    from agent.api.flow import _generate_image_with_recovery  # lazy
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        if not project_id:
            job["status"], job["stage"] = "SETUP", "creating project"
            proj = await client.create_project("nego-test")
            project_id = _pid(proj)
            if not project_id:
                raise RuntimeError("no project")
        job["project_id"] = project_id
        media = None
        if image_prompt:  # optional start frame (skip for a pure T2V dry capture)
            job["stage"] = "start frame"
            img = await _generate_image_with_recovery(
                client, image_prompt, project_id, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
            mid = _deep(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
            if mid:
                media = [mid]
        job["stage"] = "session"
        sess = await client.create_agent_session(project_id)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        job["status"], job["stage"] = "NEGOTIATING", "negotiating"
        res = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, media,
            target_model=model, target_duration_s=duration_s, approve=not dry)
        job["transcript"] = res.get("transcript")
        job["result"] = {k: v for k, v in res.items() if k != "transcript"}
        job["status"], job["stage"] = "DONE", "done"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"], job["stage"] = "FAILED", str(e), "failed"


async def _run(job_id: str, prompt: str, image_prompt: str):
    from agent.api.flow import _generate_image_with_recovery  # lazy (avoid circular)
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        # 1) project
        job["status"], job["stage"] = "SETUP", "creating project"
        proj = await client.create_project("auto-video")
        pid = _pid(proj)
        if not pid:
            raise RuntimeError("no project")
        job["project_id"] = pid

        # 2) AI start frame
        job["stage"] = "generating start frame"
        img = await _generate_image_with_recovery(
            client, image_prompt, pid, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
        media_id = _deep(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
        if not media_id:
            raise RuntimeError("no start frame")

        # 3) agent session + negotiate + approve
        job["status"], job["stage"] = "NEGOTIATING", "agent negotiation"
        sess = await client.create_agent_session(pid)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        res = await agent_video.negotiate_and_generate(client, pid, sid, prompt, [media_id])
        if not res.get("ok"):
            raise RuntimeError("negotiation: " + str(res.get("error")))
        job["approved"] = True

        # 4) wait for the render, then navigate + harvest until the bytes are ready
        job["status"], job["stage"] = "GENERATING", "rendering (~5-8 min)"
        project_url = f"https://labs.google/fx/tools/flow/project/{pid}"
        await asyncio.sleep(150)  # the video takes minutes; don't poll too early
        for i in range(30):
            job["stage"] = f"checking for finished video (try {i + 1})"
            try:
                await client.open_target_flow_project(project_url)
            except Exception:
                pass
            await asyncio.sleep(12)
            h = await client.harvest_video_urls()
            inner = h.get("result", h) if isinstance(h, dict) else {}
            diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
            mids = (diag.get("mediaIds") if isinstance(diag, dict) else None) or []
            for mid in mids:
                media = await client.get_media(mid)
                enc = _deep(media.get("data", media) if isinstance(media, dict) else {}, "encodedVideo")
                if enc:
                    vbytes = base64.b64decode(enc)
                    outdir = OUTPUT_DIR / "retrieved"
                    outdir.mkdir(parents=True, exist_ok=True)
                    path = outdir / f"{mid}.mp4"
                    path.write_bytes(vbytes)
                    job["status"], job["stage"] = "DONE", "done"
                    job["local_path"] = str(path)
                    job["video_media_id"] = mid
                    job["size_mb"] = round(len(vbytes) / 1024 / 1024, 2)
                    return
            await asyncio.sleep(18)
        job["status"], job["error"] = "FAILED", "video not ready/found in time"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"], job["stage"] = "FAILED", str(e), "failed"
