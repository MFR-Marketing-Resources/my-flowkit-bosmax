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
    page_diag_fn = getattr(client, "flow_page_state_diagnostic", None)
    if callable(page_diag_fn):
        page_diag = await page_diag_fn("F2V")
        error_markers = [
            str(item).strip()
            for item in (page_diag.get("visible_error_markers") or [])
            if str(item).strip()
        ] if isinstance(page_diag, dict) else []
        if error_markers:
            # A marker on an otherwise-healthy editor is a failed media TILE or a
            # stale toast, not a broken page (live: d80e72fd listed every artifact
            # plus one errored tile, and binding was wrongly refused). Only fail
            # closed when the editor surface itself is not usable.
            editor_usable = bool(
                isinstance(page_diag, dict)
                and (page_diag.get("editor_capability_ready")
                     or (page_diag.get("composer_found") and page_diag.get("composer_editable")))
            )
            if not editor_usable:
                raise RuntimeError(
                    "BROKEN_EDITOR_PAGE: the bound Flow editor shows error markers — "
                    + ", ".join(error_markers)
                )
        if isinstance(page_diag, dict) and page_diag.get("build_match") is False:
            raise RuntimeError(
                "CONTENT_BUILD_MISMATCH: reload the Flow tab so the content script matches the background build"
            )
    if requested_project_id and requested_project_id != project_id:
        raise RuntimeError(
            f"PROJECT_TAB_MISMATCH: requested {requested_project_id} but the open editor is {project_id}")
    return {"project_id": project_id, "flow_tab_id": flow_tab_id, "flow_project_url": flow_url}


async def _bind_with_recovery(client, requested_project_id=None, job=None) -> dict:
    """Bind to the OPEN Flow editor, self-healing ONCE if Google Flow has drifted the controlled
    tab back to the home shell (NO_OPEN_EDITOR — observed: Flow navigates the editor tab to home
    on its own). Recovery RE-OPENS the project the user was working in — the explicitly requested
    project, else the last stored editor URL — and NEVER mints a new project, then re-binds once.
    A BROKEN_EDITOR_PAGE / CONTENT_BUILD_MISMATCH / PROJECT_TAB_MISMATCH still fails closed."""
    try:
        return await _bind_editor_session(client, requested_project_id)
    except RuntimeError as e:
        if "NO_OPEN_EDITOR" not in str(e):
            raise
        target = (f"https://labs.google/fx/tools/flow/project/{requested_project_id}"
                  if requested_project_id else None)
        if not target:
            diag_fn = getattr(client, "flow_page_state_diagnostic", None)
            if callable(diag_fn):
                try:
                    pd = await diag_fn("F2V")
                    target = pd.get("stored_flow_project_url") if isinstance(pd, dict) else None
                except Exception:  # noqa: BLE001
                    target = None
        if not target:
            raise  # no known project to restore → stay fail-closed
        if job is not None:
            job["stage"] = "editor drifted to home — re-opening the project"
        opener = getattr(client, "open_target_flow_project", None)
        if callable(opener):
            try:
                await opener(target)  # navigate; ignore its readiness false-negative
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(3)  # let the editor settle, then re-bind exactly once
        return await _bind_editor_session(client, requested_project_id)


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
            if res.get("error_class") == agent_video.RATE_LIMITED:
                raise RuntimeError(str(res.get("error")))  # honest 0-credit rate-limit label
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


async def _record_artifacts(job, mode, artifacts):
    """Persist every finished artifact into the system library (generated_artifact
    table) so completed videos/images survive restarts and are listable/downloadable
    from the dashboard. Best-effort: a DB hiccup must never fail a finished job."""
    try:
        from agent.db import crud
        for art in artifacts:
            await crud.insert_generated_artifact(
                media_id=art["media_id"],
                job_id=job.get("job_id"),
                mode=mode,
                artifact_kind=("image" if mode == "IMG" else "video"),
                local_path=art.get("local_path"),
                size_mb=art.get("size_mb"),
                project_id=job.get("project_id"),
                model_used=job.get("model_used"),
                duration_used=job.get("duration_used"),
            )
    except Exception as e:  # noqa: BLE001
        job["artifact_record_error"] = str(e)


async def start_generate(mode: str, prompt: str, project_id: str = None,
                         image_media_ids: list = None, image_prompt: str = None,
                         aspect: str = "9:16", tier: str = "PAYGATE_TIER_ONE",
                         model: str = None, duration_s: int = None,
                         num_videos: int = 1, image_model: str = None) -> dict:
    """THE one door. mode = IMG | T2V | I2V | F2V. Returns a job_id; poll get_job.
    num_videos is the USER's count setting (1–4) — honoured end-to-end: the
    negotiation demands exactly that many and retrieval collects them all."""
    global _VIDEO_LANE_JOB
    _gc_jobs()
    mode = (mode or "").upper()
    num_videos = max(1, min(4, int(num_videos or 1)))
    # ONE-DOOR reference contract (transport hard caps): T2V is text-only —
    # attached references are NEVER inherited/forwarded; F2V carries at most 2
    # frames, I2V at most 3 ingredient refs. Rejected synchronously, before the
    # lane is claimed or any credit-adjacent work starts. Lower bounds live at
    # the operator layers (see flow_mode_reference_contract).
    from agent.services import flow_mode_reference_contract as _refc
    _ref_count = len([m for m in (image_media_ids or []) if m])
    _violation = _refc.service_hard_violation(mode, _ref_count)
    if _violation:
        return {"status": "REJECTED", "error": _violation}
    # Single-flight (patch H): one video job at a time on the shared Flow tab. IMG exempt.
    if mode in _VIDEO_MODES and _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"status": "REJECTED", "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "g_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                     "stage": "queued", "project_id": project_id, "local_path": None,
                     "media_id": None, "size_mb": None, "artifact": None,
                     "approved": None, "binding": None, "model": model,
                     "num_videos": num_videos, "artifacts": [],
                     "error": None, "created": time.time()}
    if mode in _VIDEO_MODES:
        _VIDEO_LANE_JOB = job_id  # claim the lane synchronously to avoid a race
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_generate(job_id, mode, prompt, project_id, image_media_ids, image_prompt,
                      aspect, tier, model, duration_s, num_videos, image_model))
    return {"job_id": job_id, "status": "SUBMITTED", "mode": mode}


def _reference_run_dropped_reference(refs, model_used):
    """True when a REFERENCE run verifiably fired a TEXT-ONLY generation tool.

    Captured contract (live g_09ced57d5d4b): an attached start image fires the
    r2v variant (model_used veo_3_1_r2v_lite); a text-only run fires the plain
    veo_3_1_* key. Only the veo_3_1 family is captured — other engines return
    None (unverified, flagged upstream) rather than guessed. No refs → None.
    """
    if not refs or not isinstance(model_used, str) or not model_used:
        return None
    mu = model_used.lower()
    if not mu.startswith("veo_3_1"):
        return None  # contract not captured for this engine — never guess
    return "r2v" not in mu


async def _durable_media_exclusion() -> set:
    """Every media id BOSMAX has ever recorded (artifacts / results / extend lineage).

    A freshly generated clip can never be in this set, so it is the DOM-independent
    freshness authority for retrieval (SEV-0 fix). Fail-soft: a DB error returns an
    empty set — the DOM snapshot + stale/ref excludes still apply."""
    from agent.db import crud
    try:
        return await crud.list_known_media_ids()
    except Exception:  # noqa: BLE001
        return set()


async def _accept_correlated_output(client, candidates, exclude, correlation,
                                    stats) -> tuple:
    """DETERMINISTIC current-run output binding (PR321 closure, Defect 2).

    A candidate media id becomes this run's output ONLY when its OWN media
    resource structurally proves it belongs to THIS submission. Captured live
    contract (zero-credit GET /v1/media/{id}, clip 12b526c5, 2026-07-12):
    {name, video{prompt, model, seed, aspectRatio, encodedVideo}} — the resource
    carries the EXACT generation prompt and model key that produced it.

    Acceptance requires:
      * media.video.prompt equals (stripped) the exact prompt THIS run fired —
        the agent-tool prompt captured from the approved SSE when present,
        else the submitted block-1 prompt;
      * a CONFIRMED model mismatch (both sides known) rejects the candidate.

    The exclusion set (stale/refs/DOM-snapshot/DB-known) remains a DEFENSIVE
    prefilter and diagnostic only — it is never the acceptance authority, and a
    finished video that exposes NO prompt metadata is counted `unverifiable`
    (the caller fails closed OUTPUT_CORRELATION_UNAVAILABLE), never accepted.

    Returns (media_id, mp4_path, size_mb, evidence) or (None, None, None, None).
    """
    import base64
    anchors = [str(a).strip() for a in (correlation.get("sse_prompt"),
                                        correlation.get("submitted_prompt")) if a]
    for mid in dict.fromkeys(candidates):  # de-dupe, keep order
        if mid in exclude:
            continue
        media = await client.get_media(mid)
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        if not enc:
            continue  # not a finished video (or not a video resource at all)
        video_meta = mdata.get("video") if isinstance(mdata, dict) else None
        video_meta = video_meta if isinstance(video_meta, dict) else {}
        vprompt = video_meta.get("prompt")
        vmodel = video_meta.get("model")
        if vprompt is None:
            # finished video whose resource exposes no generation prompt — it can
            # NEVER be bound to this run; count it so the job fails closed.
            stats["unverifiable"] += 1
            if mid not in stats["unverifiable_ids"]:
                stats["unverifiable_ids"].append(mid)
            continue
        if str(vprompt).strip() not in anchors:
            stats["prompt_mismatched"] += 1  # another run's output — never ours
            continue
        expected_model = correlation.get("expected_model")
        if expected_model and vmodel and str(vmodel) != str(expected_model):
            stats["model_mismatched"] += 1
            continue
        vbytes = base64.b64decode(enc)
        outdir = OUTPUT_DIR / "retrieved"
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(vbytes)
        sse_anchor = str(correlation.get("sse_prompt") or "").strip()
        evidence = {
            "media_id": mid,
            "matched_on": ("sse_tool_prompt" if sse_anchor
                           and str(vprompt).strip() == sse_anchor
                           else "submitted_prompt"),
            "media_model": vmodel,
            "media_seed": video_meta.get("seed"),
            "tool_call_id": correlation.get("tool_call_id"),
            "response_id": correlation.get("response_id"),
        }
        return mid, str(path), round(len(vbytes) / 1024 / 1024, 2), evidence
    return None, None, None, None


# Retrieval-phase failure markers (false-negative fix). A failure carrying one of these AFTER the
# agent approved a video and rendering started is a RETRIEVAL/harvest failure: the video was
# likely generated (credits likely spent) but could not be fetched locally. Such a job must be
# reported as GENERATED_BUT_UNRETRIEVED, never as a plain generation FAILED.
_RETRIEVAL_PHASE_MARKERS = (
    "EDITOR_TAB_LOST", "TAB_DRIFT", "PROJECT_DRIFT", "OUTPUT_CORRELATION_UNAVAILABLE",
    "video not found/retrieved in time")


def _is_retrieval_phase_error(msg) -> bool:
    return any(m in (msg or "") for m in _RETRIEVAL_PHASE_MARKERS)


async def _run_generate(job_id, mode, prompt, project_id, image_media_ids,
                        image_prompt, aspect, tier, model=None, duration_s=None,
                        num_videos=1, image_model=None):
    from agent.api.flow import (_generate_image_with_recovery, _extract_images,
                                 _extract_project_id, _IMG_ASPECT_MAP)
    import aiohttp
    global _VIDEO_LANE_JOB
    job = _JOBS[job_id]
    client = get_flow_client()
    generating = False  # set True once we pass approval into the render/retrieve phase
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
            binding = await _bind_with_recovery(client, project_id, job)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id

        # 2) IMG — direct image API, no agent, no video credits
        if mode == "IMG":
            job["status"], job["stage"] = "GENERATING", "generating image"
            res = await _generate_image_with_recovery(
                client, prompt, project_id, aspect_key, tier, image_media_ids or [],
                image_model=image_model or "NANO_BANANA_PRO")
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
                       size_mb=round(len(data) / 1024 / 1024, 2), artifact="image", url=url)
            await _record_artifacts(job, mode, [{
                "media_id": mid, "local_path": str(path),
                "size_mb": job["size_mb"]}])
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
        job["stage"] = (f"negotiating (approve {num_videos} video"
                        f"{'s' if num_videos > 1 else ''}, "
                        f"{video_models.resolve(model)['ui_label']})")
        nres = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, refs,
            target_model=model, target_duration_s=duration_s,
            desired_num=num_videos)
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
        # SEV-0 Mission 11: a reference run must fire a REFERENCE generation tool.
        # The proposal carries no tool/model (fixture-proven), so this is the earliest
        # honest boundary — fail LOUD instead of reporting a text-only fallback (image
        # silently dropped) as a successful reference generation.
        if _reference_run_dropped_reference(refs, nres.get("model_used")) is True:
            raise RuntimeError(
                "INITIAL_T2V_FALLBACK_REJECTED: references were attached but the agent "
                f"fired a text-only generation tool ({nres.get('model_used')}) — the "
                "product image was dropped; do not treat this output as reference-anchored")
        # Evidence ABSENT from the approved SSE (e.g. an unrecognized generation tool) → unknown,
        # NOT a hard fail, but FLAGGED so it is never reported as verified. A None model_used means
        # the fired tool was unrecognized, in which case duration is absent too (both flags set).
        if nres.get("approved"):
            if nres.get("model_ok") is None:
                job["model_unverified"] = True
            if nres.get("duration_ok") is None:
                job["duration_unverified"] = True
        if not nres.get("approved"):
            if nres.get("error_class") == agent_video.RATE_LIMITED:
                raise RuntimeError(str(nres.get("error")))  # honest 0-credit rate-limit label
            raise RuntimeError("agent did not approve a video: " + str(nres.get("error") or nres))
        # The render can die inside the approve stream itself (agent knowledge:
        # "trouble accessing the reference image" → stale/deleted start media).
        if nres.get("failure_classification") == "REFERENCE_IMAGE_MISSING":
            raise RuntimeError(
                "FAILED_REFERENCE_IMAGE_MISSING: the Flow agent cannot access the start "
                "image — re-upload the product image and resubmit (do NOT just regenerate)")

        job["status"], job["stage"] = "GENERATING", "rendering + retrieving"
        generating = True  # past approval: any failure below is RETRIEVAL-phase, not generation
        # DETERMINISTIC current-run binding (PR321 closure): the exact identities of
        # THIS submission — the acceptance authority for every retrieved artifact.
        correlation = {
            "submitted_prompt": prompt,
            "sse_prompt": nres.get("gen_prompt"),
            "expected_model": nres.get("model_used"),
            "tool_call_id": nres.get("tool_call_id"),
            "response_id": nres.get("response_id"),
            "seed": nres.get("gen_seed"),
        }
        job["generation_identity"] = {
            k: v for k, v in correlation.items() if k != "submitted_prompt"}
        corr_stats = {"unverifiable": 0, "prompt_mismatched": 0,
                      "model_mismatched": 0, "unverifiable_ids": []}
        probe_turn = int(nres.get("turns_used") or 0) + 1  # next agent turn for status probes
        # False-DONE fix (live: g_745e95ede679 claimed the PREVIOUS run's mp4 at try 1):
        # snapshot every media id already visible in the project BEFORE polling, so
        # retrieval can only ever accept media that appears AFTER this job's render.
        preexisting = set()
        try:
            h0 = await client.harvest_video_urls(
                tab_id=(job.get("binding") or {}).get("flow_tab_id"))
            inner0 = h0.get("result", h0) if isinstance(h0, dict) else {}
            diag0 = inner0.get("diag", inner0) if isinstance(inner0, dict) else {}
            for k in ("videoIds", "imageIds", "mediaIds"):
                preexisting |= set((diag0.get(k) or []) if isinstance(diag0, dict) else [])
        except Exception:  # noqa: BLE001 — snapshot is best-effort; stale/ref excludes still apply
            pass
        job["preexisting_media_excluded"] = len(preexisting)
        # SEV-0 durable exclusion (live incident g_09ced57d5d4b): the DOM snapshot
        # above under-reports in a history-laden project — it saw only 2 ids, then
        # the periodic tab reload surfaced OLD clip 0af072c9 (known to our own DB
        # for hours) which was accepted and reported as this run's output. A fresh
        # clip mints a brand-new Flow id, so it can NEVER be in our DB — every
        # DB-known media id is excluded unconditionally, independent of DOM state.
        known = await _durable_media_exclusion()
        job["db_known_media_excluded"] = len(known)
        exclude = set(_STALE_VIDEO_IDS) | set(refs) | preexisting | known
        collected = []  # user's count setting: retrieval collects num_videos artifacts
        await asyncio.sleep(120)
        for i in range(36):
            job["stage"] = f"checking for finished video (try {i + 1})"
            bound_tab = (job.get("binding") or {}).get("flow_tab_id")
            # Omni/V2 editor DOM does NOT live-update: a finished video never becomes
            # harvestable until the tab reloads (live proof g_01b041b563dc — the mp4 only
            # appeared, filed under imageIds, after a manual reload). Refresh the bound
            # tab every 6 polls so harvest can see newly finished media.
            if i and i % 6 == 0:
                try:
                    await client.reload_flow_tab()
                    await asyncio.sleep(8)
                except Exception:  # noqa: BLE001 — refresh is best-effort, harvest re-checks
                    pass
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
            # NOTE: inner["flow_tab_id"] is GLOBAL envelope metadata (the WS wrapper's
            # best-flow-tab snapshot), NOT the tab the harvest actually read. With a
            # second Flow tab open it differs from bound_tab and used to raise a FALSE
            # "TAB_DRIFT" (live: g_b9fce39bbc46). The exact-tab guarantee already comes
            # from the extension (chrome.tabs.get(bound) -> BOUND_TAB_GONE fail-close)
            # plus the PROJECT_DRIFT check on diag.projectId below — so no envelope
            # tab comparison here.
            cands = []
            for k in ("videoIds", "imageIds", "mediaIds"):
                cands += (diag.get(k) or []) if isinstance(diag, dict) else []
            # Collect up to num_videos fresh artifacts (user count setting = x2 means
            # TWO videos must come home, not just the first one found).
            while True:
                mid, path, size, evidence = await _accept_correlated_output(
                    client, cands, exclude, correlation, corr_stats)
                if not mid:
                    break
                exclude.add(mid)
                collected.append({"media_id": mid, "local_path": path,
                                  "size_mb": size, "correlation": evidence})
                job["output_correlation"] = evidence
                job["artifacts"] = list(collected)
                job["stage"] = (f"retrieved {len(collected)}/{num_videos} video(s)"
                                f" (try {i + 1})")
                if len(collected) >= num_videos:
                    break
            if len(collected) >= num_videos:
                first = collected[0]
                job.update(status="DONE", stage="done", media_id=first["media_id"],
                           local_path=first["local_path"], size_mb=first["size_mb"],
                           artifact="video", artifacts=list(collected))
                await _record_artifacts(job, mode, collected)
                return
            # Empty project after minutes of polling can mean the render died
            # server-side (agent posts "Failed / missing reference image" in chat,
            # invisible to harvest). Ask the agent directly — a zero-credit turn —
            # instead of blind-polling to a 12-minute timeout.
            if i in (8, 20) and not collected:
                probe = await agent_video.probe_render_failure(
                    client, project_id, sid, probe_turn)
                probe_turn = probe.get("turn_number", probe_turn + 1)
                job["render_probe"] = probe
                if probe.get("classification") == "REFERENCE_IMAGE_MISSING":
                    raise RuntimeError(
                        "FAILED_REFERENCE_IMAGE_MISSING: the Flow agent cannot access the "
                        "start image — re-upload the product image and resubmit "
                        "(do NOT just regenerate)")
                if probe.get("classification") == "RENDER_FAILED":
                    raise RuntimeError(
                        "FAILED_RENDER_REPORTED_BY_AGENT: the Flow agent reports the "
                        "generation failed server-side — safe to resubmit")
            await asyncio.sleep(18)
        # Timeout with SOME videos home but fewer than requested → honest partial DONE
        # (the user gets what exists; the shortfall is flagged, never hidden).
        if collected:
            first = collected[0]
            job.update(status="DONE", stage="done_partial", media_id=first["media_id"],
                       local_path=first["local_path"], size_mb=first["size_mb"],
                       artifact="video", artifacts=list(collected),
                       partial=True,
                       partial_detail=f"retrieved {len(collected)}/{num_videos} requested videos")
            await _record_artifacts(job, mode, collected)
            return
        # Finished video(s) exist but expose no generation prompt to bind them to
        # THIS run — refuse the uncorrelated candidate(s) instead of guessing
        # (never a false success; credits may have been spent).
        if corr_stats["unverifiable"] and not collected:
            job["correlation_stats"] = dict(corr_stats)
            raise RuntimeError(
                "OUTPUT_CORRELATION_UNAVAILABLE: finished media "
                f"{corr_stats['unverifiable_ids'][:4]} exposes no generation-prompt "
                "metadata — refusing an uncorrelated candidate as this run's output")
        # Render started but no mp4 harvested in the polling window — treat as a retrieval-phase
        # failure (classified below as GENERATED_BUT_UNRETRIEVED), not a generation failure.
        job["correlation_stats"] = dict(corr_stats)
        raise RuntimeError("video not found/retrieved in time")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # False-negative fix: a retrieval-phase failure AFTER approval + render start means the
        # video was likely generated (credits likely spent) but could not be harvested locally.
        # Report GENERATED_BUT_UNRETRIEVED (never plain FAILED) so a paid, completed video is not
        # presented as "no video". Pre-approval / pre-render errors stay FAILED.
        if job.get("approved") is True and generating and _is_retrieval_phase_error(msg):
            job.update(status="GENERATED_BUT_UNRETRIEVED", stage="generated_but_unretrieved",
                       artifact=None, media_id=None, local_path=None,
                       credit_spent_likely=True, recovery_required=True,
                       recovery_hint="open Flow project and harvest/download existing video",
                       original_error=msg, error=msg)
        else:
            job.update(status="FAILED", error=msg, stage="failed")
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
        # Defense-in-depth: a dry capture MUST end on a would_approve proposal. If it instead
        # short-circuited to generation_started (no would_approve), fail loud rather than report
        # a clean DONE — that result is the wrong shape for I4a.
        if dry and "would_approve" not in res and res.get("generation_started"):
            job["status"], job["error"], job["stage"] = (
                "FAILED", "DRY_SHORT_CIRCUIT: generation_started without would_approve", "failed")
        else:
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
