"""End-to-end automated video pipeline (flowCreationAgent).

One async job does everything: create project -> AI start frame -> agent session ->
negotiate + approve (1 video, Veo 3.1 Lite) -> wait for the render -> navigate the
Flow tab to the project + harvest the video media_id -> get_media returns the bytes
(base64 encodedVideo) -> save the .mp4 into the system. Poll GET /video-job/{id}.
"""
import asyncio
import base64
import json
import os
import re
import time
from uuid import uuid4
from urllib.parse import unquote

from agent.config import OUTPUT_DIR, DIRECT_VIDEO_MODEL_KEYS
from agent.services.flow_client import get_flow_client, resolve_video_model_key
from agent.services import agent_video
from agent.services import video_models

_JOBS: dict = {}

# Single-flight video lane: the extension drives ONE Flow tab, so at most one video
# job may be in flight at a time. IMG is exempt. (Locked patch H.)
_VIDEO_LANE_JOB = None
_JOB_TTL = 1800  # seconds — GC finished jobs after this.
_GENERATION_TERMINAL_STATUSES = frozenset({
    "DONE",
    "FAILED",
    "REJECTED",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
})


def _job_active(job_id) -> bool:
    j = _JOBS.get(job_id)
    return bool(j) and j.get("status") not in _GENERATION_TERMINAL_STATUSES


def _gc_jobs():
    now = time.time()
    for jid in [k for k, v in _JOBS.items()
                if v.get("status") in _GENERATION_TERMINAL_STATUSES
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
    job["artifact_persist_attempted"] = True
    job["artifact_persisted_count"] = 0
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
            job["artifact_persisted_count"] += 1
    except Exception as e:  # noqa: BLE001
        job["artifact_record_error"] = str(e)


def _image_provider_operation_reference(response: dict) -> dict[str, str | None]:
    """Extract provider correlation evidence without inventing an operation id.

    The current Flow image response is known to expose media names, while an
    operation id is not yet part of the proven response contract. Keep both
    facts explicit so a live benchmark can promote the status only when the
    provider actually returns an operation identifier.
    """
    data = response.get("data", response) if isinstance(response, dict) else response
    provider_operation_id = _deep(
        data, "operationId", "operation_id", "requestId", "request_id"
    )
    transport_batch_id = _deep(data, "batchId", "batch_id")
    return {
        "provider_operation_id": str(provider_operation_id)
        if provider_operation_id
        else None,
        "transport_batch_id": str(transport_batch_id) if transport_batch_id else None,
        "operation_id_status": "OBSERVED"
        if provider_operation_id
        else "UNPROVEN_PROVIDER_OPERATION_ID",
    }


async def start_generate(mode: str, prompt: str, project_id: str = None,
                         image_media_ids: list = None, image_prompt: str = None,
                         aspect: str = "9:16", tier: str = "PAYGATE_TIER_ONE",
                         model: str = None, duration_s: int = None,
                         num_videos: int = 1, image_model: str = None,
                         max_image_attempts: int = 8,
                         collect_image_variants: bool = False,
                         product_id: str = None, source_mode: str = None,
                         copy_execution_binding: dict | None = None) -> dict:
    """THE one door. mode = IMG | T2V | I2V | F2V. Returns a job_id; poll get_job.
    num_videos is the USER's count setting (1–4) — honoured end-to-end: the
    negotiation demands exactly that many and retrieval collects them all.
    source_mode (HYBRID | FRAMES | INGREDIENTS, optional) is the logical lane —
    it selects the direct-lane RPC (HYBRID composes references; FRAMES anchors
    start/end frames) and is recorded on the job. Under DIRECT_VIDEO_LANE_ENABLED
    eligible video jobs run the DOM-free direct batchAsync lane; everything else
    (and every declined job, with its reason recorded) keeps the locked agent
    lane — never a silent downgrade."""
    global _VIDEO_LANE_JOB
    _gc_jobs()
    mode = (mode or "").upper()
    num_videos = max(1, min(4, int(num_videos or 1)))
    max_image_attempts = max(1, min(8, int(max_image_attempts or 1)))
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
                     "provider_operation_ids": [],
                     "max_image_attempts": max_image_attempts,
                     "collect_image_variants": bool(collect_image_variants),
                     "product_id": product_id, "source_mode": source_mode,
                     "error": None, "created": time.time()}
    if copy_execution_binding is not None:
        _JOBS[job_id]["copy_execution_binding"] = copy_execution_binding
    if mode in _VIDEO_MODES:
        _VIDEO_LANE_JOB = job_id  # claim the lane synchronously to avoid a race
    lane = None
    if mode in _VIDEO_MODES:
        plan = _direct_lane_plan(mode, source_mode, model, duration_s, aspect,
                                 ref_count=_ref_count, num_videos=num_videos)
        if plan["eligible"]:
            lane = "DIRECT_API"
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_direct(job_id, mode, prompt, project_id,
                                     image_media_ids, aspect, tier, model,
                                     duration_s, num_videos, product_id, plan))
            return {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                    "lane": lane}
        lane = "AGENT"
        _JOBS[job_id]["lane"] = lane
        if direct_video_lane_enabled():
            # The flag is on but THIS job could not provably run direct — record
            # why, so the routing decision is auditable per job.
            _JOBS[job_id]["direct_decline_reason"] = plan["reason"]
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_generate(job_id, mode, prompt, project_id, image_media_ids, image_prompt,
                      aspect, tier, model, duration_s, num_videos, image_model,
                      max_image_attempts, collect_image_variants, product_id,
                      copy_execution_binding))
    return {"job_id": job_id, "status": "SUBMITTED", "mode": mode, "lane": lane}


def _reference_run_dropped_reference(refs, model_used):
    """True when a REFERENCE run verifiably fired a TEXT-ONLY generation tool
    (the attached image was dropped) — NOT merely a different image-based engine.

    Captured contract:
      - g_09ced57d5d4b: an attached start image on a T2V-style run fires the r2v
        variant (model_used veo_3_1_r2v_lite); a text-only run fires the plain
        veo_3_1_* key.
      - g_7b29b837c259 (first live F2V, 2026-07-18): a genuine first-frame F2V run
        fires the i2v variant (model_used veo_3_1_i2v_lite).
    BOTH r2v (reference-to-video) and i2v (image-to-video) CONSUME the attached
    image — neither dropped it — so only a plain/t2v veo_3_1 key is a text-only
    fallback. Flagging i2v as "dropped" was a false positive that fail-closed a
    valid F2V generation. Only the veo_3_1 family is captured — other engines
    return None (unverified, flagged upstream) rather than guessed. No refs → None.
    """
    if not refs or not isinstance(model_used, str) or not model_used:
        return None
    mu = model_used.lower()
    if not mu.startswith("veo_3_1"):
        return None  # contract not captured for this engine — never guess
    return not ("r2v" in mu or "i2v" in mu)


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


def _is_flow_media_redirect_url(url: str) -> bool:
    """True for the authenticated Flow tRPC delivery URL, not a signed asset URL."""
    value = str(url or "").strip()
    return value.startswith("/fx/api/trpc/media.getMediaUrlRedirect") or value.startswith(
        "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect"
    )


async def _resolve_media_download_url(client, media_id: str, url: str) -> str:
    """Resolve a Flow-relative image URL through the authenticated extension relay."""
    if url and not _is_flow_media_redirect_url(url):
        return str(url or "")
    resolver = getattr(client, "get_media_download_url", None)
    if not callable(resolver):
        raise RuntimeError("MEDIA_REDIRECT_UNAVAILABLE: extension relay lacks MEDIA_URL_REDIRECT")
    redirect_media_id = str(media_id or "")
    match = re.search(r"[?&]name=([^&#]+)", str(url or ""))
    if match:
        redirect_media_id = unquote(match.group(1))
    resolved = await resolver(redirect_media_id)
    if not isinstance(resolved, dict) or not resolved.get("ok") or not resolved.get("url"):
        status = resolved.get("status") if isinstance(resolved, dict) else None
        raise RuntimeError(
            f"MEDIA_REDIRECT_FAILED: media {media_id} status={status or 'unknown'}"
        )
    return str(resolved["url"])


def _extract_provider_prompt(raw) -> tuple:
    """Normalize the provider-stored media prompt to its EFFECTIVE prompt text.

    Captured live contract (incident manual_faf40cf6 output f0f865d6 + extend
    child 12b526c5 — two independent captures, one consistent envelope): Google
    Flow stores `media.video.prompt` as an XML envelope

        <root><context>…</context><instruction><prompt>{INPUT PROMPT}</prompt>…

    whose inner <prompt> equals the submitted/tool prompt VERBATIM (proven
    lossless). This helper extracts that inner value with REAL XML parsing
    (entity escaping handled by the parser — never string surgery):

      * plain text (no XML envelope)      → ("PLAIN", stripped text)
      * proven envelope, ONE <prompt>     → ("XML_INNER_PROMPT", inner text)
      * malformed XML                     → ("MALFORMED_XML", None)  fail-safe
      * zero or >1 CONFLICTING <prompt>s  → ("AMBIGUOUS_PROMPT_NODES", None)
        (never silently choose between different values)

    No fuzzy matching, no content rewriting — exact text in, exact text out.
    """
    if raw is None:
        return "ABSENT", None
    text = str(raw)
    if "<prompt" not in text or "<instruction" not in text:
        return "PLAIN", text.strip()
    import xml.etree.ElementTree as _ET
    try:
        root = _ET.fromstring(text)
    except _ET.ParseError:
        return "MALFORMED_XML", None
    nodes = root.findall(".//prompt")
    values = {("".join(n.itertext())).strip() for n in nodes}
    values.discard("")
    if len(values) != 1:
        return "AMBIGUOUS_PROMPT_NODES", None
    return "XML_INNER_PROMPT", next(iter(values))


async def _accept_correlated_output(client, candidates, exclude, correlation,
                                    stats) -> tuple:
    """DETERMINISTIC current-run output binding (PR321/322/323 + Owner Phase-1).

    A candidate media id becomes this run's output ONLY when its OWN media
    resource structurally proves it belongs to THIS submission. Captured live
    contract (zero-credit GET /v1/media/{generation-key}, clips 12b526c5 + f0f865d6):
    {name, video{prompt, model, seed, aspectRatio, encodedVideo}} — the resource
    carries the generation prompt (XML envelope, inner <prompt> == the exact
    input prompt, proven lossless), the model key and the seed.

    Acceptance = the proven composite (Owner-approved contract):
      * current bound project + PROJECT_DRIFT guard (enforced by the caller);
      * candidate absent from the pre-submit snapshot and every stale/reference/
        DB-known exclusion (defensive prefilter — never the sole authority);
      * NORMALIZED provider prompt (see _extract_provider_prompt) equals the
        exact prompt THIS run fired — the SSE tool prompt when captured, else
        the submitted block-1 prompt. Raw XML markup is NEVER compared;
      * a CONFIRMED model mismatch (both sides known) rejects the candidate;
      * seed must match ONLY when BOTH sides expose a usable seed (live SSE may
        omit it — the media seed is then recorded as evidence, never used to
        manufacture a link the submit never exposed, and never a reason to
        reject the otherwise-proven composite).

    A finished video with NO prompt metadata, malformed XML or ambiguous
    prompt nodes is counted `unverifiable` with the precise normalization path
    recorded — never accepted, never guessed.

    Returns (media_id, mp4_path, size_mb, evidence) or (None, None, None, None).
    """
    import base64
    anchors = [str(a).strip() for a in (correlation.get("sse_prompt"),
                                        correlation.get("submitted_prompt")) if a]
    gen_seed = _seed_value(correlation.get("seed"))
    stats.setdefault("media_fetch_errors", 0)
    stats.setdefault("media_fetch_error_ids", [])
    stats.setdefault("media_fetch_error_statuses", {})
    stats.setdefault("media_not_ready", 0)
    stats.setdefault("media_not_ready_ids", [])
    stats["round_rejected_ids"] = []  # per-call: completed-but-identity-rejected
    for mid in dict.fromkeys(candidates):  # de-dupe, keep order
        if mid in exclude:
            continue
        try:
            media = await client.get_media(mid)
        except Exception:
            # Preserve a compact retrieval trace without storing response bodies
            # or signed URLs in job telemetry.
            stats["media_fetch_errors"] += 1
            if mid not in stats["media_fetch_error_ids"]:
                stats["media_fetch_error_ids"].append(mid)
            stats["media_fetch_error_statuses"][mid] = "exception"
            continue
        media_status = media.get("status") if isinstance(media, dict) else None
        if ((isinstance(media, dict) and media.get("error"))
                or (isinstance(media_status, int) and media_status >= 400)):
            stats["media_fetch_errors"] += 1
            if mid not in stats["media_fetch_error_ids"]:
                stats["media_fetch_error_ids"].append(mid)
            stats["media_fetch_error_statuses"][mid] = (
                media_status if isinstance(media_status, int) else "error")
            continue
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        if not enc:
            stats["media_not_ready"] += 1
            if mid not in stats["media_not_ready_ids"]:
                stats["media_not_ready_ids"].append(mid)
            continue  # not a finished video (or not a video resource at all)
        video_meta = mdata.get("video") if isinstance(mdata, dict) else None
        video_meta = video_meta if isinstance(video_meta, dict) else {}
        norm_path, vprompt = _extract_provider_prompt(video_meta.get("prompt"))
        vmodel = video_meta.get("model")
        if vprompt is None:
            # No usable prompt metadata (absent / malformed XML / ambiguous
            # nodes) — it can NEVER be bound to this run; record the precise
            # normalization evidence so the job fails closed with proof.
            stats["unverifiable"] += 1
            if mid not in stats["unverifiable_ids"]:
                stats["unverifiable_ids"].append(mid)
            stats.setdefault("normalization_failures", {})[mid] = norm_path
            stats["round_rejected_ids"].append(mid)
            continue
        if vprompt not in anchors:
            stats["prompt_mismatched"] += 1  # another run's output — never ours
            stats["round_rejected_ids"].append(mid)
            continue
        expected_model = correlation.get("expected_model")
        if expected_model and vmodel and str(vmodel) != str(expected_model):
            stats["model_mismatched"] += 1
            stats["round_rejected_ids"].append(mid)
            continue
        media_seed = _seed_value(video_meta.get("seed"))
        if gen_seed is not None:
            # Both sides must agree when the approved SSE exposed a seed.
            if media_seed is None or media_seed != gen_seed:
                stats["seed_mismatched"] += 1
                stats["round_rejected_ids"].append(mid)
                continue
        vbytes = base64.b64decode(enc)
        outdir = OUTPUT_DIR / "retrieved"
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(vbytes)
        sse_anchor = str(correlation.get("sse_prompt") or "").strip()
        evidence = {
            "media_id": mid,
            "matched_on": ("sse_tool_prompt" if sse_anchor and vprompt == sse_anchor
                           else "submitted_prompt"),
            "prompt_normalization": norm_path,
            "media_model": vmodel,
            "media_seed": video_meta.get("seed"),
            "gen_seed": correlation.get("seed"),
            "seed_matched": (True if gen_seed is not None
                             else "EVIDENCE_ONLY_SSE_SEED_ABSENT"),
            "tool_call_id": correlation.get("tool_call_id"),
            "response_id": correlation.get("response_id"),
        }
        return mid, str(path), round(len(vbytes) / 1024 / 1024, 2), evidence
    return None, None, None, None


def _seed_value(raw):
    """Normalize a generation seed for exact comparison (int when possible;
    None for absent/unusable values — never a coincidental string match)."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        s = str(raw).strip()
        return s or None


# Retrieval-phase failure markers (false-negative fix). A failure carrying one of these AFTER the
# agent approved a video and rendering started is a RETRIEVAL/harvest failure: the video was
# likely generated (credits likely spent) but could not be fetched locally. Such a job must be
# reported as GENERATED_BUT_UNRETRIEVED, never as a plain generation FAILED.
_RETRIEVAL_PHASE_MARKERS = (
    "EDITOR_TAB_LOST", "TAB_DRIFT", "PROJECT_DRIFT", "OUTPUT_CORRELATION_UNAVAILABLE",
    "CURRENT_OUTPUT_IDENTITY_MISMATCH", "OUTPUT_IDENTITY_NOT_CAPTURED",
    "video not found/retrieved in time")

# Fast-failure bound (Owner Phase-1): once the SAME non-empty set of COMPLETED
# candidates has been rejected for deterministic identity reasons this many polls
# in a row (their stored metadata can never change), stop early with precise
# evidence instead of blind-polling to the 12-minute ceiling. Rendering-in-
# progress never trips this: a still-rendering output is not a completed
# candidate, and any NEW completed candidate changes the set and resets the run.
_IDENTITY_MISMATCH_FASTFAIL_ROUNDS = 3
_IDENTITY_MISMATCH_MIN_TRIES = 6  # never before ~4.5 min total (120s + 6 polls)


def _is_retrieval_phase_error(msg) -> bool:
    return any(m in (msg or "") for m in _RETRIEVAL_PHASE_MARKERS)


def _zero_completed_candidates(stats) -> bool:
    """True only when the poll window PROVABLY evaluated no completed candidate.

    Every completed candidate the retrieval loop examines leaves a trace in
    corr_stats (a deterministic-mismatch counter, an unverifiable entry, or a
    round_rejected id). All traces empty ⇒ nothing finished ever appeared.
    Unknown/absent stats ⇒ False — the conservative caller keeps the
    credits-likely-spent classification.
    """
    if not isinstance(stats, dict):
        return False
    if stats.get("round_rejected_ids") or stats.get("unverifiable_ids"):
        return False
    return not any(stats.get(k) for k in (
        "prompt_mismatched", "model_mismatched", "seed_mismatched", "unverifiable"))


# C-4: ONE structured credit vocabulary, shared verbatim with
# video_production_orchestrator (NOT_SPENT / MAY_HAVE_SPENT / SPENT / UNKNOWN) so
# the two lanes can never disagree about what a word means. Mirrored rather than
# imported to keep make_video free of orchestrator imports.
CREDIT_NOT_SPENT, CREDIT_MAY_HAVE_SPENT, CREDIT_SPENT, CREDIT_UNKNOWN = (
    "NOT_SPENT", "MAY_HAVE_SPENT", "SPENT", "UNKNOWN")


def _stamp_credit(job: dict, state: str) -> None:
    """Record the credit verdict on a TERMINAL job, truthfully.

    C-4: `credit_spent_likely` used to be written in exactly ONE place — the
    GENERATED_BUT_UNRETRIEVED recovery path — so every other terminal state
    (including a DONE job that delivered a real paid video) reported the field
    as False. Read as a ledger that produced a flat lie: live job
    g_edf503991e7c bound an 8s 720x1280 mp4 and still reported
    credit_spent_likely=False.

    Every terminal outcome now carries an explicit `credit_state`, and
    `credit_spent_likely` is DERIVED from it so existing readers (the queue's
    binding outcome, OperatorPage) stay correct instead of silently wrong.
    `SPENT` is still reserved for authoritative debit evidence (a real balance
    decrease), exactly as the orchestrator defines it — a delivered artifact
    proves the provider did the work, not what the account was charged.
    """
    job["credit_state"] = state
    job["credit_spent_likely"] = state in (CREDIT_SPENT, CREDIT_MAY_HAVE_SPENT)


def _apply_post_approval_failure(job: dict, msg: str) -> None:
    """Terminal classification of a post-approval, retrieval-phase failure.

    B-15: GENERATED_BUT_UNRETRIEVED exists so a paid, completed video is never
    presented as "no video" — but it also fired when the render never
    materialized at all (live g_99daae472362: zero completed candidates in the
    whole window, no media with this run's dialogue 15+ min later), claiming
    credit_spent_likely=True and promising a harvest of a video that does not
    exist. The plain not-found timeout with a provably-empty candidate record
    is now RENDER_NOT_MATERIALIZED with credit UNCERTAIN. Any evidence a
    completed candidate existed — or no stats at all (e.g. tab lost mid-poll)
    — keeps the existing conservative classification.
    """
    if "CURRENT_OUTPUT_IDENTITY_MISMATCH" in (msg or ""):
        # The candidates were deterministically rejected as stale/foreign. They
        # are not evidence that THIS run rendered, so they cannot use the
        # GENERATED_BUT_UNRETRIEVED success-like accounting contract.
        job.update(status="STALE_OR_FOREIGN_CANDIDATES_ONLY",
                   stage="stale_or_foreign_candidates_only",
                   artifact=None, media_id=None, local_path=None,
                   recovery_required=True,
                   recovery_hint=("verify the Flow project media list — only stale or "
                                  "foreign completed candidates were observed; do not "
                                  "assume this run produced a video"),
                   original_error=msg, error=msg)
        _stamp_credit(job, CREDIT_UNKNOWN)
        return
    if ("video not found/retrieved in time" in (msg or "")
            and _zero_completed_candidates(job.get("correlation_stats"))):
        job.update(status="RENDER_NOT_MATERIALIZED", stage="render_not_materialized",
                   artifact=None, media_id=None, local_path=None,
                   recovery_required=True,
                   recovery_hint=("verify the Flow project media list — no completed "
                                  "candidate for this run ever appeared; do not assume "
                                  "a video exists"),
                   original_error=msg, error=msg)
        _stamp_credit(job, CREDIT_UNKNOWN)
        return
    job.update(status="GENERATED_BUT_UNRETRIEVED", stage="generated_but_unretrieved",
               artifact=None, media_id=None, local_path=None,
               recovery_required=True,
               recovery_hint="open Flow project and harvest/download existing video",
               original_error=msg, error=msg)
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)


# The anchors _accept_correlated_output can actually bind an output with. Any ONE
# of them is enough to make a candidate decidable; NONE of them means the run is
# unverifiable no matter what is retrieved.
_IDENTITY_ANCHORS = ("sse_prompt", "seed", "expected_model", "tool_call_id")


_IDENTITY_GAP_SSE_LIMIT = 20000


def _last_approve_sse(nres) -> str | None:
    """The raw SSE of the LAST negotiation turn (the approve stream).

    negotiate_and_generate returns a transcript carrying raw_sse per turn, but the
    generate lane discarded it — so when identity capture failed there was nothing
    left to diagnose from and the only way forward was another paid run. Truncated:
    this is a breadcrumb, not an archive.
    """
    transcript = nres.get("transcript") if isinstance(nres, dict) else None
    if not isinstance(transcript, list) or not transcript:
        return None
    last = transcript[-1]
    raw = last.get("raw_sse") if isinstance(last, dict) else None
    return str(raw)[:_IDENTITY_GAP_SSE_LIMIT] if raw else None


def _identity_captured(identity) -> bool:
    """True when the submission exposed at least one correlation anchor.

    False is not a failure of retrieval — it means binding was impossible from the
    moment the generation fired, so the run must fail closed with
    OUTPUT_IDENTITY_NOT_CAPTURED rather than blame the polling window.
    """
    if not isinstance(identity, dict):
        return False
    return any(identity.get(k) not in (None, "") for k in _IDENTITY_ANCHORS)


# ─── Direct API-first video lane (ADR-007 recommit, flag-gated) ─────────────
#
# The agent lane's retrieval is DOM-blind: it detects a finished video ONLY via
# the extension's DOM harvest, so a labs.google React crash (error boundary,
# tiles unmounted) makes a finished, PAID video unretrievable and the job times
# out with empty results. This lane re-commits to the direct batchAsync RPCs the
# SDK/worker already runs: submit -> operation handles -> poll
# batchCheckAsyncVideoGenerationStatus -> mediaId/fifeUrl from the poll's OWN
# metadata -> bytes -> generated_artifact. Zero DOM after submit; the operation
# handle deterministically binds the output to THIS run (no prompt-matching
# heuristics needed). Kill-switch defaults OFF; anything the direct lane cannot
# PROVABLY honor (explicit model without a captured key, unproven count/duration)
# declines to the locked agent lane — never a silent downgrade (USER SETTINGS
# ARE LAW).

def direct_video_lane_enabled() -> bool:
    """Kill-switch for routing canonical video jobs onto the direct lane
    (default OFF), mirroring the NATIVE_EXTEND_ENABLED pattern."""
    return os.environ.get("DIRECT_VIDEO_LANE_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


def direct_capture_enabled() -> bool:
    """Kill-switch for the one-shot live-capture branch (default OFF). Separate
    from the routing flag so the contract capture can run while general routing
    stays off."""
    return os.environ.get("DIRECT_VIDEO_CAPTURE_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


def _direct_poll_timeout() -> int:
    """Seconds to poll batchCheckAsyncVideoGenerationStatus before declaring the
    render unretrieved (operations stay re-pollable for recovery)."""
    try:
        return max(60, int(os.environ.get("DIRECT_VIDEO_POLL_TIMEOUT", "900")))
    except (TypeError, ValueError):
        return 900


_DIRECT_VIDEO_ASPECT = {
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
}

# fifeUrl delivery hosts proven for Flow media (mirrors FlowClient._SAFE_URL_RE);
# anything else falls back to the authenticated zero-credit get_media fetch.
_DIRECT_FIFE_URL_RE = re.compile(
    r"^https://(storage\.googleapis\.com|lh3\.googleusercontent\.com)/")


def _direct_lane_plan(mode, source_mode, model, duration_s, aspect,
                      ref_count, num_videos, require_flag=True) -> dict:
    """Decide whether a job may run on the direct batchAsync lane.

    Fail-closed: any setting the direct lane cannot PROVABLY honor declines to
    the agent lane with an explicit reason (never a silent downgrade). Returns
    {"eligible": bool, "reason": str|None, "rpc": "r2v"|"start_frame",
     "gen_type": str, "aspect_enum": str, "video_model_key": str|None,
     "model_key_source": str}.
    """
    def _decline(reason):
        return {"eligible": False, "reason": reason}

    if require_flag and not direct_video_lane_enabled():
        return _decline("DIRECT_LANE_DISABLED")
    if mode not in _VIDEO_MODES:
        return _decline("NOT_A_VIDEO_MODE")
    if mode == "T2V":
        # No direct text-only RPC has been captured (no batchAsync T2V endpoint
        # exists in config); T2V stays on the conversational agent lane.
        return _decline("NO_DIRECT_T2V_RPC")
    aspect_enum = _DIRECT_VIDEO_ASPECT.get(str(aspect or "").strip())
    if not aspect_enum:
        return _decline(f"DIRECT_ASPECT_UNSUPPORTED:{aspect}")
    if int(num_videos or 1) != 1:
        # requests[] batch replication is not yet live-captured; a multi-count
        # job must keep its full count on the agent lane, never be clamped.
        return _decline("DIRECT_COUNT_UNPROVEN")
    if ref_count < 1:
        return _decline("DIRECT_NEEDS_REFERENCE")
    sm = str(source_mode or "").strip().upper()
    if mode == "F2V" and sm == "HYBRID":
        # HYBRID = one product reference composed into a new scene (r2v) — NOT a
        # start frame; there is no separate "Hybrid" RPC.
        rpc, gen_type = "r2v", "reference_frame_2_video"
    elif mode == "F2V" and sm == "FRAMES":
        rpc = "start_frame"
        gen_type = "start_end_frame_2_video" if ref_count >= 2 else "frame_2_video"
    elif mode == "F2V":
        # F2V without a declared source_mode is ambiguous: a logical-HYBRID job
        # routed to the start-frame RPC would CHANGE semantics (the product
        # photo becomes frame 1 instead of a composed reference). Callers that
        # do not thread source_mode (bulk/queue lanes) keep the agent lane.
        return _decline("DIRECT_F2V_SOURCE_MODE_UNKNOWN")
    else:  # I2V — ingredient references compose the video (r2v)
        rpc, gen_type = "r2v", "reference_frame_2_video"
    video_model_key = None
    model_key_source = "models.json default (tier, gen_type, aspect)"
    if model:
        try:
            spec = video_models.resolve(model)
        except ValueError:
            # Unknown model must surface through the canonical fail-closed path
            # (agent lane raises ERR_UNKNOWN_MODEL semantics), never die here.
            return _decline(f"DIRECT_MODEL_UNKNOWN:{model}")
        table = DIRECT_VIDEO_MODEL_KEYS.get(spec["key"]) or {}
        video_model_key = (table.get(gen_type) or {}).get(aspect_enum)
        if not video_model_key:
            return _decline(f"DIRECT_MODEL_KEY_UNPROVEN:{spec['key']}")
        model_key_source = f"direct_video_model_keys[{spec['key']}]"
    if duration_s is not None:
        try:
            normalized_duration = int(duration_s)
        except (TypeError, ValueError):
            return _decline(f"DIRECT_DURATION_UNPROVEN:{duration_s}")
        if normalized_duration != 8:
            # The captured submit contract carries no duration field; only the
            # Veo 8s default is provably delivered. Anything else keeps the
            # agent lane.
            return _decline(f"DIRECT_DURATION_UNPROVEN:{duration_s}")
    return {"eligible": True, "reason": None, "rpc": rpc, "gen_type": gen_type,
            "aspect_enum": aspect_enum, "video_model_key": video_model_key,
            "model_key_source": model_key_source}


async def _direct_submit(client, plan, refs, prompt, project_id, tier, seed,
                         scene_id) -> dict:
    """Fire the ONE direct submit the plan selected. Returns the raw response."""
    if plan["rpc"] == "r2v":
        return await client.generate_video_from_references(
            refs, prompt, project_id, scene_id,
            aspect_ratio=plan["aspect_enum"], user_paygate_tier=tier,
            video_model_key=plan.get("video_model_key"), seed=seed)
    return await client.generate_video(
        refs[0], prompt, project_id, scene_id,
        aspect_ratio=plan["aspect_enum"],
        end_image_media_id=(refs[1] if len(refs) > 1 else None),
        user_paygate_tier=tier,
        video_model_key=plan.get("video_model_key"), seed=seed)


def _direct_response_data(response: dict) -> dict:
    """Unwrap relay/provider data envelopes without assuming one fixed depth."""
    data = response if isinstance(response, dict) else {}
    # The extension relay may return ``{id,status,data:<provider>}``, while
    # provider responses can themselves carry ``data:{media/workflows}``.
    # Unwrap only bounded dictionaries; never walk arbitrary response values.
    for _ in range(3):
        nested = data.get("data") if isinstance(data, dict) else None
        if not isinstance(nested, dict):
            break
        data = nested
    return data


def _direct_media_status(media: dict) -> str:
    """Read the current media-generation status from either known nesting."""
    if not isinstance(media, dict):
        return ""
    status = media.get("mediaStatus")
    if not isinstance(status, dict):
        status = (media.get("mediaMetadata") or {}).get("mediaStatus")
    return str((status or {}).get("mediaGenerationStatus") or "")


def _direct_media_entries(response: dict) -> list[dict]:
    data = _direct_response_data(response)
    return [m for m in (data.get("media") or []) if isinstance(m, dict)]


def _extract_direct_media_targets(response: dict, project_id: str) -> list[dict]:
    """Extract the current Flow media-status poll targets from a submit.

    Current ``batchAsyncGenerateVideoReferenceImages`` responses expose
    ``data.media[].name`` and ``data.workflows[].metadata.primaryMediaId``;
    they do not expose the legacy ``data.operations`` list.  The status RPC
    accepts only the media name and project id, so keep this target deliberately
    small and free of provider response payloads.
    """
    data = _direct_response_data(response)
    media = data.get("media") if isinstance(data.get("media"), list) else []
    workflows = data.get("workflows") if isinstance(data.get("workflows"), list) else []

    targets = []
    seen = set()
    for item in media:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            workflow_id = item.get("workflowId")
            name = next(
                (
                    (w.get("metadata") or {}).get("primaryMediaId")
                    for w in workflows
                    if isinstance(w, dict) and w.get("name") == workflow_id
                ),
                None,
            )
        name = str(name or "").strip()
        pid = str(item.get("projectId") or project_id or "").strip()
        if not name or not pid or name in seen:
            continue
        seen.add(name)
        targets.append({"name": name, "projectId": pid})

    # A future response may expose only workflows.  The primary media id is
    # still a valid status target, so preserve it when there is no media list.
    if not targets:
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            name = str((workflow.get("metadata") or {}).get("primaryMediaId") or "").strip()
            pid = str(project_id or "").strip()
            if name and pid and name not in seen:
                seen.add(name)
                targets.append({"name": name, "projectId": pid})
    return targets


def _extract_direct_submission(response: dict, project_id: str) -> tuple[list[dict], list[dict]]:
    """Return legacy operation handles and/or current media poll targets."""
    from agent.sdk.services.operations import _extract_operations
    operations = _extract_operations(response)
    return operations, _extract_direct_media_targets(response, project_id)


async def _poll_direct_media_targets(client, targets: list[dict], timeout: int) -> dict:
    """Poll the current Flow ``{"media": [...]}`` status contract.

    This path is intentionally separate from ``_poll_operations``: sending a
    media target through the legacy ``{"operations": [...]}`` body returns an
    empty/non-terminal response from the provider and loses the accepted render.
    """
    if not targets:
        return {"error": "No media targets to poll"}
    from agent.sdk.services import operations as sdk_operations

    try:
        interval = max(0.0, float(sdk_operations.VIDEO_POLL_INTERVAL))
    except (TypeError, ValueError):
        interval = 15.0
    elapsed = 0.0
    target_names = {str(t.get("name")) for t in targets if t.get("name")}
    while elapsed < timeout:
        if interval:
            await asyncio.sleep(interval)
            elapsed += interval
        else:
            # Test/failsafe configurations may set a zero interval.  Advance a
            # logical second so a permanently pending provider cannot spin.
            elapsed += 1.0
        try:
            status_result = await client.check_video_status_by_media(targets)
        except Exception:  # noqa: BLE001 — transient relay failures stay pollable
            continue
        if not isinstance(status_result, dict) or status_result.get("error"):
            continue
        entries = _direct_media_entries(status_result)
        by_name = {str(m.get("name")): m for m in entries if m.get("name")}
        failed = [
            (name, _direct_media_status(by_name[name]))
            for name in target_names
            if name in by_name
            and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_FAILED"
        ]
        if failed:
            return {"error": f"Media generation failed: {failed[0][0]}"}
        if target_names and all(
                name in by_name
                and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
                for name in target_names):
            return {"data": _direct_response_data(status_result)}
    return {"error": f"Polling timeout after {timeout}s"}


def _direct_media_url(media: dict) -> str | None:
    """Find a provider delivery URL without trusting it until host validation."""
    if not isinstance(media, dict):
        return None
    for key in ("fifeUrl", "servingUri", "downloadUrl", "url", "servingUrl"):
        value = _deep(media, key)
        if value:
            return str(value).strip()
    return None


def _direct_media_generation_id(media: dict) -> str | None:
    """Extract the v1 media resource key when the status payload exposes it."""
    if not isinstance(media, dict):
        return None
    for key in ("mediaGenerationId", "media_generation_id", "generationId", "clipId"):
        value = _deep(media, key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("id")
        if value:
            return str(value).strip()
    return None


async def _download_from_direct_url(url: str, source: str) -> tuple | None:
    if not url or not _DIRECT_FIFE_URL_RE.match(url):
        return None
    try:
        import aiohttp
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.read()
                    if data and len(data) > 1024:
                        return data, source
    except Exception:  # noqa: BLE001 — authenticated fallbacks remain available
        pass
    return None


async def _download_video_bytes(client, media_id, fife_url,
                                media_generation_id=None) -> tuple:
    """DOM-free byte retrieval with current Flow tile fallbacks.

    Prefer a trusted signed URL from the status response, then the authenticated
    generation-resource ``get_media`` endpoint, and finally the authenticated
    tile redirect used by the current Flow Library.  None of these paths submits
    or retries a generation.
    """
    direct = await _download_from_direct_url(str(fife_url or "").strip(), "fifeUrl")
    if direct:
        return direct

    media = None
    media_error = None
    try:
        media = await client.get_media(media_id, media_generation_id=media_generation_id)
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        if enc:
            return base64.b64decode(enc), "get_media"
    except Exception as exc:  # noqa: BLE001 — try the tile redirect next
        media_error = str(exc)

    redirect_fn = getattr(client, "get_media_download_url", None)
    if callable(redirect_fn):
        try:
            redirect = await redirect_fn(media_id)
            redirect_url = _deep(redirect, "downloadUrl", "url", "servingUri", "servingUrl")
            direct = await _download_from_direct_url(str(redirect_url or "").strip(),
                                                     "media_redirect")
            if direct:
                return direct
        except Exception:  # noqa: BLE001 — report one bounded retrieval error
            pass

    status = media.get("status") if isinstance(media, dict) else None
    detail = f"status={status}"
    if media_error:
        detail += f" get_media_error={media_error[:160]}"
    raise RuntimeError(
        f"DIRECT_MEDIA_BYTES_UNAVAILABLE: media {media_id} returned no "
        f"encodedVideo ({detail}) and signed delivery failed")


async def _direct_poll_retrieve_finish(job, client, mode, operations, plan,
                                       seed, num_videos) -> None:
    """Poll the operation handles to terminal, download every finished video,
    persist generated_artifact rows and mark the job DONE. DOM-free end to end;
    raises on failure (caller classifies)."""
    from agent.sdk.services.operations import _poll_operations
    from agent.worker._parsing import _extract_uuid_from_url
    job["stage"] = f"polling render status ({len(operations)} operation(s))"
    polled = await _poll_operations(client, operations,
                                    timeout=_direct_poll_timeout())
    if not isinstance(polled, dict) or polled.get("error"):
        emsg = str((polled or {}).get("error") or "empty poll result")
        if "timeout" in emsg.lower():
            # Exact marker string: classifies as a retrieval-phase failure
            # (GENERATED_BUT_UNRETRIEVED) — the operations stay re-pollable.
            raise RuntimeError(
                "video not found/retrieved in time (direct poll timeout; "
                f"operations {job.get('provider_operation_ids')} remain re-pollable)")
        raise RuntimeError(f"DIRECT_RENDER_FAILED: {emsg}")
    final_ops = (polled.get("data") or {}).get("operations", [])
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for op in final_ops:
        op_name = (op.get("operation") or {}).get("name")
        video_meta = ((op.get("operation") or {}).get("metadata") or {}).get("video") or {}
        mid = str(video_meta.get("mediaId") or "").strip()
        fife = video_meta.get("fifeUrl")
        if not mid and fife:
            mid = _extract_uuid_from_url(str(fife))
        if not mid:
            skipped.append({"operation": op_name, "reason": "NO_MEDIA_ID_IN_METADATA"})
            continue
        job["stage"] = f"downloading finished video {mid[:12]}"
        data, source = await _download_video_bytes(client, mid, fife)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data) / 1024 / 1024, 2),
            "correlation": {
                "media_id": mid,
                "matched_on": "operation_handle",
                "operation_name": op_name,
                "retrieval_source": source,
                "gen_seed": seed,
            },
        })
    job["direct_retrieval_skipped"] = skipped
    if not collected:
        raise RuntimeError(
            "DIRECT_RETRIEVAL_EMPTY: the poll reported success but exposed no "
            f"retrievable mediaId (skipped={skipped}) — do not assume no video "
            "exists; re-poll the recorded operations")
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(status="DONE", stage="done", media_id=first["media_id"],
               local_path=first["local_path"], size_mb=first["size_mb"],
               artifact="video", artifacts=list(collected))
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = (
            f"retrieved {len(collected)}/{num_videos} requested videos")
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


async def _direct_media_poll_retrieve_finish(job, client, mode, targets,
                                             plan, seed, num_videos) -> None:
    """Poll current Flow media targets, retrieve bytes, and persist artifacts."""
    job["stage"] = f"polling media render status ({len(targets)} target(s))"
    polled = await _poll_direct_media_targets(
        client, targets, timeout=_direct_poll_timeout())
    if not isinstance(polled, dict) or polled.get("error"):
        emsg = str((polled or {}).get("error") or "empty media poll result")
        if "timeout" in emsg.lower():
            raise RuntimeError(
                "video not found/retrieved in time (direct media poll timeout; "
                f"media targets {job.get('provider_operation_ids')} remain re-pollable)")
        raise RuntimeError(f"DIRECT_RENDER_FAILED: {emsg}")

    entries = _direct_media_entries(polled)
    by_name = {str(m.get("name")): m for m in entries if m.get("name")}
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for target in targets:
        mid = str(target.get("name") or "").strip()
        media = by_name.get(mid)
        if not mid or not media:
            skipped.append({"media_id": mid, "reason": "NO_MEDIA_IN_SUCCESS_POLL"})
            continue
        generation_id = _direct_media_generation_id(media)
        if generation_id and hasattr(client, "_media_generation_ids"):
            client._media_generation_ids[mid] = generation_id
        job["stage"] = f"downloading finished video {mid[:12]}"
        data, source = await _download_video_bytes(
            client, mid, _direct_media_url(media),
            media_generation_id=generation_id)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data) / 1024 / 1024, 2),
            "correlation": {
                "media_id": mid,
                "matched_on": "media_status",
                "operation_name": mid,
                "retrieval_source": source,
                "gen_seed": seed,
                "media_generation_id": generation_id,
            },
        })
    job["direct_retrieval_skipped"] = skipped
    if not collected:
        raise RuntimeError(
            "DIRECT_RETRIEVAL_EMPTY: the media poll reported success but exposed "
            f"no retrievable media (skipped={skipped}) — re-poll the recorded targets")
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(status="DONE", stage="done", media_id=first["media_id"],
               local_path=first["local_path"], size_mb=first["size_mb"],
               artifact="video", artifacts=list(collected))
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = (
            f"retrieved {len(collected)}/{num_videos} requested videos")
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


def _direct_submit_handles(submit: dict, project_id: str) -> tuple[list[dict], list[dict], list[str]]:
    """Choose the poll contract without treating an accepted media response as empty."""
    operations, media_targets = _extract_direct_submission(submit, project_id)
    operation_names = [
        str(name)
        for name in ((o.get("operation") or {}).get("name") for o in operations)
        if name
    ]
    media_names = [str(target["name"]) for target in media_targets if target.get("name")]
    # Current Flow returns media targets; legacy captures return operation
    # handles. Prefer media targets when present because their status endpoint
    # is the contract paired with the current response.
    handles = media_names or operation_names
    return operations, media_targets, handles


async def _run_generate_direct(job_id, mode, prompt, project_id, image_media_ids,
                               aspect, tier, model, duration_s, num_videos,
                               product_id, plan):
    """API-first direct video lane: submit -> poll -> retrieve -> persist.

    The Flow tab's DOM is never consulted after submit, so a labs.google React
    crash cannot lose a finished, paid video (the root cause of the empty
    results/library incidents). The only DOM touch is the optional pre-submit
    editor binding when no project_id was provided."""
    global _VIDEO_LANE_JOB
    job = _JOBS[job_id]
    client = get_flow_client()
    generating = False
    try:
        refs = [m for m in (image_media_ids or []) if m]
        job["direct_plan"] = {k: plan.get(k) for k in
                              ("rpc", "gen_type", "aspect_enum", "model_key_source")}
        # 1) project context: explicit id wins; else bind to the OPEN editor
        # (read-only DOM touch, pre-submit and pre-credits — fail-closed).
        if not project_id:
            job["status"], job["stage"] = "SETUP", "binding to open Flow editor"
            binding = await _bind_with_recovery(client, None, job)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id

        seed = int(time.time()) % 100000
        fired_model_key = resolve_video_model_key(
            tier, plan["gen_type"], plan["aspect_enum"],
            override=plan.get("video_model_key"))
        if not fired_model_key:
            raise RuntimeError(
                f"DIRECT_MODEL_KEY_MISSING: no captured videoModelKey for "
                f"tier={tier} gen_type={plan['gen_type']} aspect={plan['aspect_enum']}")
        job["status"] = "GENERATING"
        job["stage"] = f"submitting direct render ({plan['gen_type']})"
        submit = await _direct_submit(client, plan, refs, prompt, project_id,
                                      tier, seed, str(uuid4()))
        if (not isinstance(submit, dict) or submit.get("error")
                or (isinstance(submit.get("status"), int) and submit["status"] >= 400)):
            detail = (submit or {}).get("error") or submit
            raise RuntimeError(f"DIRECT_SUBMIT_REJECTED: {str(detail)[:300]}")
        operations, media_targets, op_names = _direct_submit_handles(
            submit, project_id)
        if not op_names:
            raise RuntimeError(
                f"DIRECT_SUBMIT_NO_OPERATIONS: {str(submit)[:300]}")
        job["provider_operation_ids"] = op_names
        job["direct_media_targets"] = media_targets
        # The submit acceptance IS this lane's approval: the provider accepted
        # the render request (credits may be charged from here on).
        job["approved"] = True
        generating = True
        job["model_used"] = fired_model_key
        job["model_ok"] = True if model else None
        job["model_key_source"] = plan.get("model_key_source")
        # Duration is not expressible in the captured submit contract; the Veo
        # default (8s) is expected but not asserted — flagged, never invented.
        job["duration_unverified"] = True
        job["generation_identity"] = {
            "seed": seed,
            "expected_model": fired_model_key,
            "operation_names": op_names,
        }
        job["identity_captured"] = True  # the operation handle IS the binding
        if media_targets:
            await _direct_media_poll_retrieve_finish(
                job, client, mode, media_targets, plan, seed, num_videos)
        else:
            await _direct_poll_retrieve_finish(
                job, client, mode, operations, plan, seed, num_videos)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if job.get("approved") is True and generating and _is_retrieval_phase_error(msg):
            _apply_post_approval_failure(job, msg)
        else:
            job.update(status="FAILED", error=msg, stage="failed")
            _stamp_credit(
                job,
                CREDIT_MAY_HAVE_SPENT
                if (job.get("approved") is True and generating)
                else CREDIT_NOT_SPENT,
            )
    finally:
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None


async def start_direct_capture(mode: str, prompt: str, project_id: str,
                               refs: list, aspect: str = "9:16",
                               tier: str = "PAYGATE_TIER_ONE",
                               source_mode: str = None, model: str = None,
                               duration_s: int = None,
                               confirm_live_credit_burn: bool = False) -> dict:
    """LIVE-CAPTURE GATE (owner-authorized, DIRECT_VIDEO_CAPTURE_ENABLED): fire
    ONE direct batchAsync submit, return the RAW submit response for contract
    capture, and poll/retrieve/persist in the background so the spent credit
    still yields a real artifact. Single-flight like every video job. The
    confirmation flag is mandatory; explicit model and duration settings are
    forwarded and fail closed when their direct contract is unproven."""
    global _VIDEO_LANE_JOB
    if not direct_capture_enabled():
        return {"ok": False, "error": "DIRECT_CAPTURE_DISABLED: set "
                                      "DIRECT_VIDEO_CAPTURE_ENABLED=1"}
    if confirm_live_credit_burn is not True:
        return {"ok": False, "error":
                "DIRECT_CAPTURE_CONFIRMATION_REQUIRED: explicit credit "
                "authorization is required before the live submit"}
    refs = [m for m in (refs or []) if m]
    plan = _direct_lane_plan(mode, source_mode, model, duration_s, aspect,
                             ref_count=len(refs), num_videos=1,
                             require_flag=False)
    if not plan["eligible"]:
        return {"ok": False, "error": f"DIRECT_CAPTURE_INELIGIBLE: {plan['reason']}"}
    _gc_jobs()
    if _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"ok": False, "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "g_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                     "stage": "direct capture submit", "project_id": project_id,
                     "local_path": None, "media_id": None, "size_mb": None,
                     "artifact": None, "approved": None, "binding": None,
                     "model": model, "duration_s": duration_s,
                     "num_videos": 1, "artifacts": [],
                     "provider_operation_ids": [], "product_id": None,
                     "lane": "DIRECT_CAPTURE", "source_mode": source_mode,
                     "error": None, "created": time.time()}
    _VIDEO_LANE_JOB = job_id
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        if not project_id:
            job["status"], job["stage"] = "SETUP", "binding to open Flow editor"
            binding = await _bind_with_recovery(client, None, job)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id
        seed = int(time.time()) % 100000
        fired_model_key = resolve_video_model_key(
            tier, plan["gen_type"], plan["aspect_enum"],
            override=plan.get("video_model_key"))
        job["status"], job["stage"] = "GENERATING", "direct capture submit"
        submit = await _direct_submit(client, plan, refs, prompt, project_id,
                                      tier, seed, str(uuid4()))
    except Exception as e:  # noqa: BLE001
        job.update(status="FAILED", error=str(e), stage="failed")
        _stamp_credit(job, CREDIT_NOT_SPENT)
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None
        return {"ok": False, "job_id": job_id, "error": str(e)}
    fired = {"rpc": plan["rpc"], "gen_type": plan["gen_type"],
             "aspect_enum": plan["aspect_enum"], "video_model_key": fired_model_key,
             "seed": seed, "refs": refs, "project_id": project_id, "tier": tier,
             "model": model, "duration_s": duration_s}
    job["direct_capture_fired"] = fired
    if (not isinstance(submit, dict) or submit.get("error")
            or (isinstance(submit.get("status"), int) and submit["status"] >= 400)):
        job.update(status="FAILED", stage="failed",
                   error=f"DIRECT_SUBMIT_REJECTED: {str((submit or {}).get('error') or submit)[:300]}")
        _stamp_credit(job, CREDIT_NOT_SPENT)
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None
        return {"ok": False, "job_id": job_id, "fired": fired,
                "submit_response": submit, "error": job["error"]}
    operations, media_targets, op_names = _direct_submit_handles(
        submit, project_id)
    job["provider_operation_ids"] = op_names
    job["approved"] = bool(op_names)
    job["direct_media_targets"] = media_targets
    job["model_used"] = fired_model_key
    job["generation_identity"] = {"seed": seed, "expected_model": fired_model_key,
                                  "operation_names": op_names}
    job["identity_captured"] = bool(op_names)

    async def _finish():
        global _VIDEO_LANE_JOB
        try:
            if not op_names:
                raise RuntimeError(
                    f"DIRECT_SUBMIT_NO_OPERATIONS: {str(submit)[:300]}")
            if media_targets:
                await _direct_media_poll_retrieve_finish(
                    job, client, mode, media_targets, plan, seed, 1)
            else:
                await _direct_poll_retrieve_finish(
                    job, client, mode, operations, plan, seed, 1)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if job.get("approved") is True and _is_retrieval_phase_error(msg):
                _apply_post_approval_failure(job, msg)
            else:
                job.update(status="FAILED", error=msg, stage="failed")
                _stamp_credit(job, CREDIT_MAY_HAVE_SPENT if job.get("approved")
                              else CREDIT_NOT_SPENT)
        finally:
            if _VIDEO_LANE_JOB == job_id:
                _VIDEO_LANE_JOB = None

    job["_task"] = asyncio.create_task(_finish())
    return {"ok": True, "job_id": job_id, "fired": fired,
            "operations": op_names, "submit_response": submit}


async def start_direct_media_recovery(
        media_id: str, project_id: str, mode: str = "F2V",
        source_mode: str = "HYBRID", model_key: str | None = None,
        duration_s: int | None = 8, seed: int | None = None,
        recovery_of: str | None = None,
        confirm_recovery: bool = False) -> dict:
    """Recover one already-accepted media target without a provider submit.

    This is deliberately a separate entrypoint from ``start_direct_capture``:
    it has no generation flag and no submit call.  The explicit recovery
    confirmation prevents an operator from confusing a status/retrieval repair
    with a new credit-bearing capture.
    """
    global _VIDEO_LANE_JOB
    if confirm_recovery is not True:
        return {"ok": False,
                "error": "DIRECT_RECOVERY_CONFIRMATION_REQUIRED"}
    media_id = str(media_id or "").strip()
    project_id = str(project_id or "").strip()
    if not media_id or not project_id:
        return {"ok": False, "error": "DIRECT_RECOVERY_TARGET_REQUIRED"}
    _gc_jobs()
    if _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"ok": False, "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "r_" + uuid4().hex[:12]
    target = {"name": media_id, "projectId": project_id}
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "mode": str(mode or "F2V").upper(),
        "source_mode": source_mode,
        "stage": "direct media recovery",
        "project_id": project_id,
        "local_path": None,
        "media_id": None,
        "size_mb": None,
        "artifact": None,
        "approved": True,
        "binding": None,
        "model": model_key,
        "model_used": model_key,
        "duration_s": duration_s,
        "num_videos": 1,
        "artifacts": [],
        "provider_operation_ids": [media_id],
        "direct_media_targets": [target],
        "product_id": None,
        "lane": "DIRECT_CAPTURE_RECOVERY",
        "direct_recovery": True,
        "recovery_of": recovery_of,
        "generation_identity": {
            "seed": seed,
            "expected_model": model_key,
            "operation_names": [media_id],
        },
        "identity_captured": True,
        "error": None,
        "created": time.time(),
    }
    _VIDEO_LANE_JOB = job_id
    job = _JOBS[job_id]
    client = get_flow_client()
    plan = {"gen_type": "reference_frame_2_video"}

    async def _finish():
        global _VIDEO_LANE_JOB
        try:
            await _direct_media_poll_retrieve_finish(
                job, client, job["mode"], [target], plan, seed, 1)
        except Exception as exc:  # noqa: BLE001 — preserve accepted-credit truth
            msg = str(exc)
            if _is_retrieval_phase_error(msg):
                _apply_post_approval_failure(job, msg)
            else:
                job.update(status="FAILED", error=msg, stage="failed")
                _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
        finally:
            if _VIDEO_LANE_JOB == job_id:
                _VIDEO_LANE_JOB = None

    job["_task"] = asyncio.create_task(_finish())
    return {
        "ok": True,
        "job_id": job_id,
        "media_id": media_id,
        "operations": [media_id],
        "provider_submit": False,
        "credit_action": "NO_PROVIDER_SUBMIT",
        "recovery_of": recovery_of,
    }


async def _run_generate(job_id, mode, prompt, project_id, image_media_ids,
                        image_prompt, aspect, tier, model=None, duration_s=None,
                        num_videos=1, image_model=None, max_image_attempts=8,
                        collect_image_variants=False, product_id=None,
                        copy_execution_binding=None):
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
            outdir = OUTPUT_DIR / "retrieved"
            outdir.mkdir(parents=True, exist_ok=True)
            variant_count = num_videos if collect_image_variants else 1
            collected: list[dict] = []
            provider_operation_ids: list[dict] = []
            for variant_index in range(variant_count):
                job["stage"] = (
                    f"generating image variant {variant_index + 1}/{variant_count}"
                    if collect_image_variants
                    else "generating image"
                )
                res = await _generate_image_with_recovery(
                    client,
                    prompt,
                    project_id,
                    aspect_key,
                    tier,
                    image_media_ids or [],
                    max_tries=max_image_attempts,
                    image_model=image_model or "NANO_BANANA_PRO",
                )
                evidence = _image_provider_operation_reference(res or {})
                imgs = _extract_images(
                    (res or {}).get("data", res or {})
                    if isinstance(res or {}, dict)
                    else {}
                )
                provider_media_id = imgs[0].get("media_id") if imgs else None
                response_status = (
                    "ERROR"
                    if not res or res.get("error")
                    else "MEDIA_RETURNED"
                    if provider_media_id
                    else "NO_MEDIA_RETURNED"
                )
                if collect_image_variants:
                    from agent.db import crud as _crud

                    try:
                        operation = await _crud.record_image_generation_operation(
                            job_id=job_id,
                            product_id=product_id,
                            model=image_model or "NANO_BANANA_PRO",
                            variant_index=variant_index,
                            provider_operation_id=evidence.get("provider_operation_id"),
                            transport_batch_id=evidence.get("transport_batch_id"),
                            operation_id_status=str(
                                evidence.get("operation_id_status")
                                or "UNPROVEN_PROVIDER_OPERATION_ID"
                            ),
                            provider_media_id=provider_media_id,
                            response_status=response_status,
                        )
                    except Exception as exc:  # noqa: BLE001 - provenance is mandatory
                        job["operation_provenance_error"] = str(exc)
                        raise RuntimeError(
                            "IMAGE_OPERATION_PROVENANCE_PERSIST_FAILED: "
                            f"{exc}"
                        ) from exc
                    evidence.update(operation)
                evidence["variant_index"] = str(variant_index)
                provider_operation_ids.append(evidence)
                if not res or res.get("error"):
                    job["provider_operation_ids"] = provider_operation_ids
                    raise RuntimeError("image gen failed: " + str((res or {}).get("error")))
                if not imgs:
                    job["provider_operation_ids"] = provider_operation_ids
                    raise RuntimeError("no image returned")
                mid, url = imgs[0]["media_id"], imgs[0].get("url")
                download_media_id = imgs[0].get("delivery_media_id") or mid
                download_url = await _resolve_media_download_url(
                    client, download_media_id, url
                )
                if not download_url:
                    job["provider_operation_ids"] = provider_operation_ids
                    raise RuntimeError("no image/url returned")
                path = outdir / f"{mid}.jpg"
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                    async with s.get(download_url) as r:
                        if r.status != 200:
                            job["provider_operation_ids"] = provider_operation_ids
                            raise RuntimeError(f"image download HTTP {r.status}")
                        data = await r.read()
                path.write_bytes(data)
                collected.append({
                    "media_id": mid,
                    "local_path": str(path),
                    "size_mb": round(len(data) / 1024 / 1024, 2),
                    "url": url,
                    "variant_index": variant_index,
                    "provider_operation_id": evidence.get("provider_operation_id"),
                    "transport_batch_id": evidence.get("transport_batch_id"),
                })
                await _record_artifacts(job, mode, [collected[-1]])
            if not collected:
                raise RuntimeError("no image artifact returned")
            first = collected[0]
            job["provider_operation_ids"] = provider_operation_ids
            job["artifacts"] = collected
            if collect_image_variants and product_id:
                try:
                    from agent.services.product_reference_pack_service import (
                        get_reference_pack,
                        machine_check_generated_output,
                    )

                    pack = await get_reference_pack(product_id)
                    if pack is not None:
                        job["generated_output_machine_qa"] = [
                            machine_check_generated_output(
                                artifact["media_id"], pack
                            ).model_dump(mode="json")
                            for artifact in collected
                        ]
                        job["generated_output_review_state"] = (
                            "GENERATED_OUTPUT_MACHINE_CHECKED"
                        )
                    else:
                        job["generated_output_machine_qa"] = []
                        job["generated_output_review_state"] = "UNPROVEN"
                except Exception as exc:  # noqa: BLE001 - QA cannot corrupt retrieval
                    job["generated_output_machine_qa_error"] = str(exc)
            job.update(status="DONE", stage="done", media_id=first["media_id"],
                       local_path=first["local_path"], size_mb=first["size_mb"],
                       artifact="image", url=first["url"])
            # The direct image API does not consume Google Flow video credits.
            # Keep the explicit IMG verdict separate from the paid video lane.
            _stamp_credit(job, CREDIT_NOT_SPENT)
            await _record_artifacts(job, mode, collected)
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

        # False-DONE guard: take the project media snapshot after any required
        # start-frame resolution but BEFORE agent negotiation can mint this run's
        # output.  A snapshot taken after approval can classify a freshly created
        # tile as pre-existing and exclude the only valid result.
        preexisting = set()
        try:
            h0 = await client.harvest_video_urls(
                tab_id=(job.get("binding") or {}).get("flow_tab_id"))
            inner0 = h0.get("result", h0) if isinstance(h0, dict) else {}
            diag0 = inner0.get("diag", inner0) if isinstance(inner0, dict) else {}
            for k in ("videoIds", "imageIds", "mediaIds"):
                preexisting |= set((diag0.get(k) or []) if isinstance(diag0, dict) else [])
        except Exception:  # noqa: BLE001 — stale/ref excludes still apply
            pass
        job["preexisting_media_excluded"] = len(preexisting)
        # SEV-0 durable exclusion: the DOM snapshot can under-report history-laden
        # projects, while every DB-known id is guaranteed not to be freshly minted.
        known = await _durable_media_exclusion()
        job["db_known_media_excluded"] = len(known)
        exclude = set(_STALE_VIDEO_IDS) | set(refs) | preexisting | known

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
        # DIAGNOSABILITY: persist the captured identity (toolNames seen, anchors, and
        # the raw approve SSE on a gap) HERE — before any post-approve guard below can
        # raise — so a REJECTED run still reveals what tool/model it fired instead of
        # forcing another paid capture. (F2V live g_7b29b837c259: the agent fired
        # veo_3_1_i2v_lite, the reference-dropped guard rejected it, and every
        # persisted anchor came back empty ONLY because this capture used to run after
        # the guard.) Idempotent: the success path re-confirms the same values below.
        job["generation_identity"] = {
            "sse_prompt": nres.get("gen_prompt"),
            "expected_model": nres.get("model_used"),
            "tool_call_id": nres.get("tool_call_id"),
            "response_id": nres.get("response_id"),
            "seed": nres.get("gen_seed"),
        }
        job["identity_captured"] = _identity_captured(job["generation_identity"])
        job["tools_seen"] = list(nres.get("tools_seen") or [])
        job["gen_tool_matched"] = bool(nres.get("gen_tool_matched"))
        if not job["identity_captured"]:
            job["identity_gap_sse"] = _last_approve_sse(nres)
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
        # Identity-capture status (PR392 follow-up). Anchors are only captured for
        # toolNames in agent_video._GEN_TOOLS; a generation firing under any other
        # name leaves EVERY anchor None, and retrieval can then never bind an
        # output — the run is unverifiable before a single poll runs. Record that
        # as a first-class fact (with the toolNames actually seen) instead of
        # letting it surface later as a generic "not found in time".
        job["identity_captured"] = _identity_captured(job["generation_identity"])
        job["tools_seen"] = list(nres.get("tools_seen") or [])
        job["gen_tool_matched"] = bool(nres.get("gen_tool_matched"))
        if not job["identity_captured"]:
            # IDENTITY-GAP CAPTURE. tools_seen only names a tool if the stream
            # actually carried a toolInvocation. T2V's post-approve stream reports
            # "started" via soft TEXT (_STARTED_PHRASES), not started_tool, so it
            # may carry no invocation at all — in which case tools_seen is empty
            # and the paid run reveals nothing. Keep the raw approve stream so the
            # real identity source can be found from THIS run instead of buying
            # another. Diagnostic only: never parsed, never an anchor.
            job["identity_gap_sse"] = _last_approve_sse(nres)
        corr_stats = {"unverifiable": 0, "prompt_mismatched": 0,
                      "model_mismatched": 0, "seed_mismatched": 0,
                      "unverifiable_ids": [], "normalization_failures": {},
                      "round_rejected_ids": [], "media_fetch_errors": 0,
                      "media_fetch_error_ids": [], "media_fetch_error_statuses": {},
                      "media_not_ready": 0, "media_not_ready_ids": []}
        # Fast-failure trackers (Owner Phase-1): consecutive polls in which the
        # SAME completed candidates were rejected for deterministic identity reasons.
        identity_reject_sig, identity_reject_rounds = None, 0
        identity_reject_epoch = None
        reload_epoch = 0
        probe_turn = int(nres.get("turns_used") or 0) + 1  # next agent turn for status probes
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
                    await client.reload_flow_tab(tab_id=bound_tab)
                    await asyncio.sleep(8)
                    reload_epoch += 1
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
            job["correlation_stats"] = dict(corr_stats)
            job["retrieval_telemetry"] = {
                "try": i + 1,
                "candidate_count": len(cands),
                "collected_count": len(collected),
                "media_fetch_errors": corr_stats.get("media_fetch_errors", 0),
                "media_not_ready": corr_stats.get("media_not_ready", 0),
                "artifact_persist_attempted": bool(job.get("artifact_persist_attempted")),
                "artifact_persisted_count": job.get("artifact_persisted_count", 0),
            }
            if len(collected) >= num_videos:
                first = collected[0]
                job.update(status="DONE", stage="done", media_id=first["media_id"],
                           local_path=first["local_path"], size_mb=first["size_mb"],
                           artifact="video", artifacts=list(collected))
                _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
                await _record_artifacts(job, mode, collected)
                return
            # FAST FAILURE (Owner Phase-1): completed candidates rejected for
            # deterministic identity reasons have IMMUTABLE stored metadata — no
            # future poll changes them. When the SAME non-empty rejected set
            # repeats _IDENTITY_MISMATCH_FASTFAIL_ROUNDS polls in a row (and the
            # run is past the minimum window so an in-flight render still gets
            # its chance), stop with precise evidence instead of the blind
            # 12-minute loop the incident suffered (31 identical rejections).
            round_sig = tuple(sorted(corr_stats.get("round_rejected_ids") or []))
            if round_sig and round_sig == identity_reject_sig and not collected:
                identity_reject_rounds += 1
            else:
                identity_reject_sig = round_sig or None
                identity_reject_rounds = 1 if round_sig else 0
                identity_reject_epoch = reload_epoch if round_sig else None
            if (identity_reject_rounds >= _IDENTITY_MISMATCH_FASTFAIL_ROUNDS
                    and i >= _IDENTITY_MISMATCH_MIN_TRIES and not collected
                    and reload_epoch > (identity_reject_epoch or 0)):
                job["correlation_stats"] = dict(corr_stats)
                raise RuntimeError(
                    "CURRENT_OUTPUT_IDENTITY_MISMATCH: completed candidate(s) "
                    f"{list(round_sig)[:4]} were rejected {identity_reject_rounds} "
                    "consecutive polls for deterministic identity reasons "
                    f"(prompt_mismatched={corr_stats['prompt_mismatched']}, "
                    f"model_mismatched={corr_stats['model_mismatched']}, "
                    f"seed_mismatched={corr_stats['seed_mismatched']}, "
                    f"unverifiable={corr_stats['unverifiable']}, "
                    f"normalization={corr_stats.get('normalization_failures') or {} }, "
                    f"sse_seed={'present' if _seed_value(correlation.get('seed')) is not None else 'absent'}) "
                    "— their stored metadata cannot change; refusing to blind-poll")
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
            _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
            await _record_artifacts(job, mode, collected)
            return
        # Finished video(s) exist but expose no generation prompt to bind them to
        # THIS run — refuse the uncorrelated candidate(s) instead of guessing
        # (never a false success; credits may have been spent).
        if corr_stats["unverifiable"] and not collected:
            job["correlation_stats"] = dict(corr_stats)
            raise RuntimeError(
                "OUTPUT_CORRELATION_UNAVAILABLE: finished media "
                f"{corr_stats['unverifiable_ids'][:4]} cannot be deterministically "
                "bound (no usable prompt metadata; normalization="
                f"{corr_stats.get('normalization_failures') or {} }) — refusing an "
                "uncorrelated candidate as this run's output")
        # Render started but no mp4 harvested in the polling window.
        job["correlation_stats"] = dict(corr_stats)
        # Distinguish "we could not find it" from "we could never have bound it".
        # With no anchors, no amount of polling could have produced a bindable
        # output — reporting a timeout there sends the operator hunting a
        # retrieval bug that does not exist (live g_e71cd329b524).
        if not job.get("identity_captured"):
            raise RuntimeError(
                "OUTPUT_IDENTITY_NOT_CAPTURED: the generation fired but exposed no "
                "correlation anchor (seed/sse_prompt/model/tool_call_id all absent), "
                "so no retrieved media can be deterministically bound to this run. "
                f"toolNames seen={job.get('tools_seen') or []}; "
                "add the generation toolName to agent_video._GEN_TOOLS")
        raise RuntimeError("video not found/retrieved in time")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # False-negative fix: a retrieval-phase failure AFTER approval + render start means the
        # video was likely generated (credits likely spent) but could not be harvested locally.
        # Report GENERATED_BUT_UNRETRIEVED (never plain FAILED) so a paid, completed video is not
        # presented as "no video". Pre-approval / pre-render errors stay FAILED.
        if job.get("approved") is True and generating and _is_retrieval_phase_error(msg):
            # B-15: split "video exists but could not be bound/retrieved" from
            # "no completed candidate ever materialized" — see the helper.
            _apply_post_approval_failure(job, msg)
        else:
            job.update(status="FAILED", error=msg, stage="failed")
            # C-4: a failure BEFORE approval never reached generation (the lane
            # refuses locally, or Google's anti-abuse layer rejects pre-approval —
            # e.g. RATE_LIMITED). After approval the provider may already have
            # charged, so it must never be reported as free.
            _stamp_credit(
                job,
                CREDIT_MAY_HAVE_SPENT
                if (job.get("approved") is True and generating)
                else CREDIT_NOT_SPENT,
            )
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
