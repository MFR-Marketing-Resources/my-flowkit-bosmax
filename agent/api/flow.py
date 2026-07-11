"""Direct Flow API endpoints — for manual operations outside the queue."""
import base64
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from agent.services.flow_client import get_flow_client
from agent.db import crud

__all__ = ["router", "cleanup_old_staging_files"]

router = APIRouter(prefix="/flow", tags=["flow"])
_ERROR_CODE_RE = re.compile(r"\b(ERR_[A-Z0-9_]+)\b")
_UPLOAD_STAGING_DIR = Path(tempfile.gettempdir()) / "flowkit-upload-staging"


def cleanup_old_staging_files(max_age_seconds: int = 3600) -> int:
    """Remove stale files from the local CDP upload staging directory."""
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    if not _UPLOAD_STAGING_DIR.exists():
        return 0

    cutoff_time = time.time() - max_age_seconds
    removed_count = 0
    for entry in _UPLOAD_STAGING_DIR.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime > cutoff_time:
                continue
            entry.unlink()
            removed_count += 1
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed_count


class GenerateImageRequest(BaseModel):
    prompt: str
    project_id: str
    aspect_ratio: str = "IMAGE_ASPECT_RATIO_PORTRAIT"
    user_paygate_tier: str = "PAYGATE_TIER_ONE"
    character_media_ids: Optional[list[str]] = None


class GenerateVideoRequest(BaseModel):
    start_image_media_id: str
    prompt: str
    project_id: str
    scene_id: str
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    end_image_media_id: Optional[str] = None
    user_paygate_tier: str = "PAYGATE_TIER_ONE"


class GenerateVideoRefsRequest(BaseModel):
    reference_media_ids: list[str]
    prompt: str
    project_id: str
    scene_id: str
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    user_paygate_tier: str = "PAYGATE_TIER_ONE"


class UpscaleVideoRequest(BaseModel):
    media_id: str
    scene_id: str
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    resolution: str = "VIDEO_RESOLUTION_4K"


class ExtendBlockModel(BaseModel):
    block_index: int
    position: int
    prompt: str
    is_final: bool = False
    start_frame_index: int = 1
    end_frame_index: int = 24


class ExtendRunRequest(BaseModel):
    """Native Flow Extend CHAIN — THE single authoritative execution surface.
    DRY_RUN by default; a live run requires explicit confirm + bounded op count."""
    project_id: str
    scene_id: str
    source_operation_id: str
    blocks: list[ExtendBlockModel]
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    workspace_generation_package_id: Optional[str] = None
    seed: Optional[int] = None
    user_paygate_tier: str = "PAYGATE_TIER_ONE"
    dry_run: bool = True
    confirm_live_credit_burn: bool = False
    # Bounded live-credit authorization: MUST equal the resume-aware planned submit
    # count (from a prior dry-run's planned_operation_count) or the live run is rejected.
    confirmed_extend_operation_count: Optional[int] = None
    # Process-local, single-use authorization issued only after the operator accepts
    # the exact planned operation count. It is never persisted or logged.
    live_authorization_token: Optional[str] = None


class ExtendResolveRequest(BaseModel):
    """Central native-extend execution-decision query (readiness/blockers) for the UI."""
    project_id: Optional[str] = None
    scene_id: Optional[str] = None
    source_operation_id: Optional[str] = None
    planned_block_count: int = 0
    total_duration_seconds: Optional[int] = None


class UploadImageRequest(BaseModel):
    file_path: str  # absolute path to local image file
    project_id: str = ""
    file_name: str = "image.png"


class UploadImageBase64Request(BaseModel):
    image_base64: str
    mime_type: str = "image/png"
    project_id: str = ""
    file_name: str = "image.png"


class MaterializeLocalFileRequest(BaseModel):
    image_base64: str
    mime_type: str = "image/png"
    file_name: str = "asset.png"


class CheckStatusRequest(BaseModel):
    operations: list[dict]


class EditImageRequest(BaseModel):
    prompt: str
    source_media_id: str
    project_id: str
    aspect_ratio: str = "IMAGE_ASPECT_RATIO_PORTRAIT"
    user_paygate_tier: str = "PAYGATE_TIER_ONE"


class CreateProjectRawRequest(BaseModel):
    project_title: str
    tool_name: str = "PINHOLE"


def _extract_error_code(text: object) -> Optional[str]:
    candidate = str(text or "").strip()
    if not candidate:
        return None
    match = _ERROR_CODE_RE.search(candidate)
    if match:
        return match.group(1)
    return None


def _parse_json_text(value: object) -> Optional[dict]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_json_after_marker(text: object, marker: str) -> Optional[dict]:
    source = str(text or "")
    marker_index = source.find(marker)
    if marker_index < 0:
        return None
    start = source.find("{", marker_index + len(marker))
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(source)):
        ch = source[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(source[start : idx + 1])
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _parse_stage_message_dict(message: object) -> Optional[dict]:
    parsed = _parse_json_text(message)
    if parsed:
        return parsed
    return _extract_json_after_marker(message, "detail=")


def _safe_stage_basename(value: object) -> str:
    candidate = Path(str(value or "")).name.strip()
    return (candidate or "asset").strip()[:80]


def _build_materialized_stage_message(
    local_file_path: str,
    source_type: str,
) -> str:
    dir_label = (
        "flowkit-upload-staging"
        if "flowkit-upload-staging" in str(local_file_path or "").lower()
        else "staged_local_file"
    )
    return (
        f"source_type={source_type} "
        f"name={_safe_stage_basename(local_file_path)} "
        f"dir={dir_label}"
    )


def _asset_payload_has_local_file(asset: object) -> bool:
    return bool(
        isinstance(asset, dict)
        and (asset.get("localFilePath") or asset.get("local_file_path"))
    )


# A REAL Flow media id is a bare UUID. The dashboard also sends composite BOSMAX
# asset ids like "product-image:<uuid>:start_frame" in assetId — those are NOT
# Flow media ids and must never short-circuit materialization/upload (live:
# manual_259f0ab1 failed ERR_START_MEDIA_NOT_FOUND because the composite id was
# mistaken for a media id and the remote downloadUrl was never materialized).
_FLOW_MEDIA_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _extract_flow_media_id(asset: object) -> str | None:
    """Return the asset's Flow media id ONLY if it is a real bare UUID."""
    if not isinstance(asset, dict):
        return None
    for key in ("mediaId", "media_id", "assetId", "asset_id"):
        value = str(asset.get(key) or "").strip()
        if value and _FLOW_MEDIA_UUID_RE.match(value):
            return value
    return None


def _asset_payload_remote_url(asset: object) -> str | None:
    if not isinstance(asset, dict):
        return None
    return (
        asset.get("downloadUrl")
        or asset.get("download_url")
        or asset.get("previewUrl")
        or asset.get("preview_url")
    )


def _asset_payload_file_name(asset: object, fallback_name: str) -> str:
    if not isinstance(asset, dict):
        return fallback_name
    return (
        asset.get("fileName")
        or asset.get("file_name")
        or asset.get("label")
        or fallback_name
    )


async def _build_manual_flow_failure_report(request_id: str, result: dict) -> dict:
    stages = await crud.get_stage_history(request_id)
    latest_extension_fail = next(
        (
            stage
            for stage in reversed(stages)
            if stage.get("source") == "extension"
            and str(stage.get("status") or "").upper() == "FAIL"
        ),
        None,
    )
    target_resolution = next(
        (stage for stage in reversed(stages) if stage.get("stage") == "F2V_SOP_TARGET_TAB_RESOLVED"),
        None,
    )
    opener_scan = next(
        (stage for stage in reversed(stages) if stage.get("stage") == "F2V_SOP_SETTINGS_OPENER_SCAN"),
        None,
    )

    target_payload = _parse_stage_message_dict(target_resolution.get("message")) if target_resolution else None
    scan_payload = _parse_stage_message_dict(opener_scan.get("message")) if opener_scan else None
    detail_payload = _parse_json_text(result.get("detail")) or {}
    if not detail_payload and latest_extension_fail:
        detail_payload = _parse_stage_message_dict(latest_extension_fail.get("message")) or {}

    report: dict = {
        "error": result.get("error") or _extract_error_code(latest_extension_fail.get("message") if latest_extension_fail else None),
        "error_code": (
            _extract_error_code(result.get("error"))
            or _extract_error_code(result.get("detail"))
            or _extract_error_code(latest_extension_fail.get("message") if latest_extension_fail else None)
        ),
        "latest_extension_stage": latest_extension_fail.get("stage") if latest_extension_fail else None,
        "latest_extension_status": latest_extension_fail.get("status") if latest_extension_fail else None,
        "selected_tab": (
            target_payload.get("selected_tab")
            if isinstance(target_payload, dict)
            else None
        ),
        "candidate_tabs": result.get("candidate_tabs")
        or (
            target_payload.get("candidate_tabs")
            if isinstance(target_payload, dict)
            else []
        ),
    }

    if isinstance(scan_payload, dict):
        for key in (
            "target_tab_url",
            "document_title",
            "composer_present",
            "prompt_field_present",
            "candidate_settings_launchers_found",
            "attempted_strategies",
        ):
            if key in scan_payload and report.get(key) is None:
                report[key] = scan_payload[key]

    if isinstance(detail_payload, dict):
        report.update(detail_payload)

    if not report.get("target_tab_url"):
        selected_tab = report.get("selected_tab") or {}
        report["target_tab_url"] = selected_tab.get("url")

    if latest_extension_fail and latest_extension_fail.get("message"):
        report["extension_fail_message"] = latest_extension_fail["message"]

    return report


@router.get("/status")
async def extension_status():
    """Check if extension is connected."""
    client = get_flow_client()
    return {
        "connected": client.connected,
        "flow_key_present": client._flow_key is not None,
    }


@router.get("/credits")
async def get_credits():
    """Get user credits from Google Flow."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.get_credits()
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return result.get("data", result)


@router.post("/generate-image")
async def generate_image(body: GenerateImageRequest):
    """Generate image directly (bypasses queue)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.generate_images(**body.model_dump())
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    return result.get("data", result)


# ── Image one-shot: text-to-image OR image-to-image blend, via the API path ──

_IMG_ASPECT_MAP = {
    "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "3:4": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "4:3": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
}


class GenerateImageOneshotRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "9:16"            # UI format; mapped to the API enum
    user_paygate_tier: str = "PAYGATE_TIER_TWO"
    reference_media_ids: list[str] = []   # blend refs (from /upload-image-base64)
    project_id: str = ""                  # minted if empty


def _extract_project_id(obj) -> str:
    m = re.search(r'"projectId"\s*:\s*"([^"]+)"', json.dumps(obj))
    return m.group(1) if m else ""


def _extract_images(data) -> list[dict]:
    out = []
    media = data.get("media") if isinstance(data, dict) else None
    if isinstance(media, list):
        for m in media:
            mid = m.get("name")
            gi = (m.get("image") or {}).get("generatedImage") or {}
            if mid:
                out.append({"media_id": mid, "url": gi.get("fifeUrl")})
    return out


async def _generate_image_with_recovery(client, prompt, project_id, aspect, tier, refs, max_tries=8, image_model="NANO_BANANA_PRO"):
    """Generate an image with the proven recovery recipe.

    The Flow tab is often stale after idle / a backend restart, so reload it ONCE up
    front and let it settle, then retry. A reCAPTCHA cold-start timeout after that is a
    warm-up — just retry (do NOT reload again, which resets the warm-up). Reload a
    second time only for the host-access failure class.
    """
    import asyncio

    # Proactive single reload + settle (matches the manual recipe that works).
    try:
        await client.reload_flow_tab()
        await asyncio.sleep(7)
    except Exception:
        pass

    last = None
    did_host_reload = False
    for _ in range(max_tries):
        result = await client.generate_images(
            prompt=prompt, project_id=project_id, aspect_ratio=aspect,
            user_paygate_tier=tier, character_media_ids=refs or None,
            image_model=image_model)
        if not (result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400)):
            return result
        last = result
        blob = str(result.get("error") or result.get("data") or "")
        if "CAPTCHA_FAILED" not in blob:
            return result  # non-recoverable error → stop
        host_access = "Cannot access contents" in blob or "must request permission" in blob
        if host_access and not did_host_reload:
            try:
                await client.reload_flow_tab()
            except Exception:
                pass
            did_host_reload = True
            await asyncio.sleep(8)
        else:
            await asyncio.sleep(2)  # cold-start warm-up → just retry
    return last


@router.post("/generate-image-oneshot")
async def generate_image_oneshot(body: GenerateImageOneshotRequest):
    """Generate an image via the proven aisandbox API path (NOT DOM automation).

    Two-way:
      - text-to-image  : prompt only, no reference (button works with free text)
      - image-to-image : pass reference_media_ids to blend uploaded references
    Mints a project if none supplied; self-heals reCAPTCHA cold-start / stale tab.
    """
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    if not body.prompt.strip():
        raise HTTPException(422, "prompt is required")

    aspect = _IMG_ASPECT_MAP.get(body.aspect_ratio, "IMAGE_ASPECT_RATIO_PORTRAIT")
    project_id = body.project_id
    if not project_id:
        proj = await client.create_project("img " + time.strftime("%Y%m%d-%H%M%S"))
        if proj.get("error"):
            raise HTTPException(502, proj["error"])
        project_id = _extract_project_id(proj)
        if not project_id:
            raise HTTPException(502, "create_project returned no projectId")

    refs = [m for m in (body.reference_media_ids or []) if m]
    result = await _generate_image_with_recovery(
        client, body.prompt, project_id, aspect, body.user_paygate_tier, refs)
    if result is None or result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        r = result or {}
        code = r.get("status") if isinstance(r.get("status"), int) else 502
        raise HTTPException(code, r.get("error") or r.get("data") or "image generation failed")
    images = _extract_images(result.get("data", result))
    if not images:
        raise HTTPException(502, "no image returned")
    return {"project_id": project_id, "images": images, "mode": "blend" if refs else "text"}


def _deep_find(obj, *keys):
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


class AgentDebugRequest(BaseModel):
    prompt: str = "Vertical 9:16 handheld. Slow push-in on the product, soft natural light, subtle motion."
    image_prompt: str = "A premium product on a clean surface, soft studio light, vertical 9:16. No text, no labels."


@router.post("/agent-debug-turn1")
async def agent_debug_turn1(body: AgentDebugRequest):
    """DEBUG: drive flowCreationAgent turn 1 and return raw responses to learn the SSE format."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    proj = await client.create_project("agent-debug")
    project_id = _extract_project_id(proj)
    if not project_id:
        raise HTTPException(502, f"no project: {json.dumps(proj)[:200]}")
    img = await _generate_image_with_recovery(
        client, body.image_prompt, project_id, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
    media_id = _deep_find(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
    sess = await client.create_agent_session(project_id)
    session_data = sess.get("data", sess) if isinstance(sess, dict) else sess
    session_id = _deep_find(session_data, "agentSessionId", "sessionId") or _deep_find(session_data, "name")
    chat_raw = None
    if session_id:
        chat = await client.agent_stream_chat(session_id, project_id, 1, body.prompt,
                                              media_ids=[media_id] if media_id else None)
        chat_raw = chat.get("data", chat) if isinstance(chat, dict) else chat
    return {
        "project_id": project_id,
        "media_id": media_id,
        "session_response": session_data,
        "session_id": session_id,
        "chat_response": chat_raw,
    }


class AgentNegotiateRequest(BaseModel):
    prompt: str = "Vertical 9:16 handheld. Slow push-in on the product, soft natural light, subtle motion."
    image_prompt: str = "A premium product on a clean surface, soft studio light, vertical 9:16. No text, no labels."
    dry: bool = True


@router.post("/agent-negotiate")
async def agent_negotiate(body: AgentNegotiateRequest):
    """Drive the full flowCreationAgent negotiation (AI start frame for now).

    dry=True  → negotiate to the correct config WITHOUT approving (no credits).
    dry=False → approve → the agent generates the video (~10 credits, Veo 3.1 Lite).
    """
    from agent.services import agent_video
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    proj = await client.create_project("agent-negotiate")
    project_id = _extract_project_id(proj)
    if not project_id:
        raise HTTPException(502, "no project")
    img = await _generate_image_with_recovery(
        client, body.image_prompt, project_id, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
    media_id = _deep_find(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
    if not media_id:
        raise HTTPException(502, "no start-frame media")
    sess = await client.create_agent_session(project_id)
    session_id = _deep_find(sess.get("data", sess) if isinstance(sess, dict) else sess, "agentSessionId")
    if not session_id:
        raise HTTPException(502, "no agent session")
    result = await agent_video.negotiate_and_generate(
        client, project_id, session_id, body.prompt, [media_id], approve=not body.dry)
    result["project_id"] = project_id
    result["media_id"] = media_id
    return result


@router.get("/captured-media")
async def captured_media():
    """Media URLs harvested from the Flow UI's TRPC responses (video retrieval)."""
    from agent.services.flow_client import _CAPTURED_MEDIA_URLS
    vids = {k: v for k, v in _CAPTURED_MEDIA_URLS.items() if v.get("type") == "video"}
    return {"videos": vids, "video_count": len(vids), "all_count": len(_CAPTURED_MEDIA_URLS)}


@router.get("/harvest-video")
async def harvest_video():
    """Scan the Flow tab DOM for the finished video URL and download it into the system."""
    from agent.config import OUTPUT_DIR
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client.harvest_video_urls()
    inner = res.get("result", res) if isinstance(res, dict) else {}
    def _find_gcs_url(obj):
        stack = [obj]
        while stack:
            o = stack.pop()
            if isinstance(o, str) and ("ai-sandbox-videofx" in o or
                                       ("storage.googleapis.com" in o and "/video/" in o)):
                return o.replace("\\u0026", "&").replace("\\", "")
            if isinstance(o, dict):
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
        return None

    data = inner.get("diag", inner) if isinstance(inner, dict) else {}
    urls = (data.get("urls") if isinstance(data, dict) else None) or inner.get("urls") or []
    media_ids = (data.get("mediaIds") if isinstance(data, dict) else None) or inner.get("mediaIds") or []
    url = urls[0] if urls else None
    mid = None
    if not url and media_ids:
        mid = media_ids[0]
        media = await client.get_media(mid)
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep_find(mdata, "encodedVideo")
        if enc:
            import base64
            vbytes = base64.b64decode(enc)
            outdir = OUTPUT_DIR / "retrieved"
            outdir.mkdir(parents=True, exist_ok=True)
            vpath = outdir / f"{mid}.mp4"
            vpath.write_bytes(vbytes)
            return {"ok": True, "media_id": mid, "via": "get_media.encodedVideo",
                    "local_path": str(vpath), "size_mb": round(len(vbytes) / 1024 / 1024, 2)}
        url = _find_gcs_url(mdata)
    if not url:
        return {"ok": False, "urls": [], "media_ids": media_ids, "diag": inner,
                "note": "no video URL resolved (try get_media or play the video)"}
    if not mid:
        m = re.search(r"/video/([0-9a-f-]{36})", url)
        mid = m.group(1) if m else "video"
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{mid}.mp4"
    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url) as r:
            if r.status != 200:
                raise HTTPException(502, f"download failed HTTP {r.status}")
            data = await r.read()
    path.write_bytes(data)
    return {"ok": True, "media_id": mid, "url": url,
            "local_path": str(path), "size_mb": round(len(data) / 1024 / 1024, 2),
            "found": len(urls)}


class MakeVideoRequest(BaseModel):
    prompt: str = "Vertical 9:16 handheld. Slow push-in on the product, soft natural light, subtle motion, premium feel."
    image_prompt: str = "A premium product on a clean surface, soft studio light, vertical 9:16. No text, no labels, no watermark."


@router.post("/make-video")
async def make_video(body: MakeVideoRequest):
    """Full auto pipeline (negotiate → approve → render → harvest → download). → job_id."""
    from agent.services import make_video as _mv
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    cred = await client.get_credits()
    tier = (cred.get("data", cred) or {}).get("userPaygateTier", "") if isinstance(cred, dict) else ""
    if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
        raise HTTPException(500, f"Account tier '{tier}' cannot generate video — needs Pro/Ultra")
    return await _mv.start(body.prompt, body.image_prompt)


@router.get("/video-job/{job_id}")
async def video_job(job_id: str):
    from agent.services import make_video as _mv
    j = _mv.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


class MakeVideoExistingRequest(BaseModel):
    project_id: str
    image_media_id: str
    prompt: str = "Cinematic vertical 9:16 product video. Slow push-in on the product, soft natural light, gentle motion, premium feel. Make 1 video."
    model: Optional[str] = None
    duration_s: Optional[int] = None


@router.post("/make-video-existing")
async def make_video_existing(body: MakeVideoExistingRequest):
    """Generate a video in an EXISTING project from an EXISTING image, then save it.
    Poll GET /api/flow/video-job/{id}."""
    from agent.services import make_video as _mv
    from agent.services import video_models as _vm
    # Same fail-closed model+duration validation as /generate (patch I2a/I5), BEFORE the
    # connectivity check so 422 stays deterministic on this legacy lane too.
    try:
        _vm.expected_cost(body.model or _vm.DEFAULT_MODEL, body.duration_s)
    except ValueError as e:
        raise HTTPException(422, str(e))
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    # Route the legacy endpoint through the guarded one door (patch #3): inherits the
    # single-flight lane, bound-editor session, and drift/loss invariants instead of the
    # unguarded start_on_existing path.
    result = await _mv.start_generate(
        "I2V", body.prompt, project_id=body.project_id,
        image_media_ids=[body.image_media_id], model=body.model, duration_s=body.duration_s)
    if isinstance(result, dict) and result.get("status") == "REJECTED":
        raise HTTPException(409, result.get("error") or "rejected")
    return result


class GenerateRequest(BaseModel):
    mode: str                                  # IMG | T2V | I2V | F2V
    prompt: str
    project_id: Optional[str] = None
    image_media_ids: Optional[list] = None     # existing/uploaded refs (I2V/F2V)
    image_prompt: Optional[str] = None         # auto start-frame if no refs (I2V/F2V)
    aspect: str = "9:16"
    model: Optional[str] = None                # video model (ui_label or key); default Veo 3.1 - Lite
    image_model: Optional[str] = None          # IMG image model key/ui_label; default Nano Banana Pro
    duration_s: Optional[int] = None           # default = the model's default duration
    count: int = 1                             # USER count setting (1-4): negotiate AND retrieve N videos
    refs: Optional[dict] = None
    startAsset: Optional[dict] = None
    # Operator-surface capability declaration (Step-1). When `engine` is present
    # with SINGLE generation_mode, the tuple is validated fail-closed against the
    # capability matrix. Bare programmatic callers omit these and keep the
    # registry-only validation lane (ADR-007 transport truth).
    engine: Optional[str] = None
    generation_mode: Optional[str] = None
    capability_matrix_version: Optional[str] = None


@router.get("/video-models")
async def video_models_list():
    """SSOT video-model registry for the dashboard dropdown (patch I3)."""
    from agent.services import video_models as _vm
    return {"models": _vm.public_list(), "default": _vm.DEFAULT_MODEL}


@router.get("/video-capability-matrix")
async def video_capability_matrix():
    """Canonical operator-policy capability matrix (engine → model → SINGLE
    duration). The dashboard derives every Step-1 engine/model/duration option
    from this — the single source, no parallel hard-coded frontend list. It is
    a versioned policy layer ABOVE the video_models registry, not a replacement.
    """
    from agent.services import video_capability_matrix as _cm
    return _cm.public_matrix()


# Canonical reference-slot ORDER for the execution lane. The engine receives
# refs positionally, so this tuple IS the ordering contract: startAsset first,
# then subject, scene, style, image. Single source of truth for both the
# one-door /generate lane and the manual lane (was duplicated inline in each).
REF_SLOT_ORDER: tuple[tuple[str, str], ...] = (
    ("subjectAsset", "Subject"),
    ("sceneAsset", "Scene"),
    ("styleAsset", "Style"),
    ("imageAsset", "Image"),
)


def ordered_ref_slots(start_asset, refs) -> list[tuple[str, dict]]:
    """Return the ORDERED [(slot_label, asset_dict), ...] the execution lane will
    upload, WITHOUT resolving/uploading anything — startAsset first, then
    subject, scene, style, image. Pure and deterministic: this is the dry-run
    proof seam for execution-payload reference ordering (no live Flow upload).
    """
    slots: list[tuple[str, dict]] = []
    if isinstance(start_asset, dict) and start_asset:
        slots.append(("Start", start_asset))
    if isinstance(refs, dict):
        for ref_key, slot_label in REF_SLOT_ORDER:
            asset = refs.get(ref_key)
            if isinstance(asset, dict) and asset:
                slots.append((slot_label, asset))
    return slots


@router.post("/generate")
async def generate(body: GenerateRequest):
    """THE one door for all four modes. mode = IMG | T2V | I2V | F2V → job_id.
    Poll GET /api/flow/generate-job/{id}."""
    from agent.services import make_video as _mv
    mode = (body.mode or "").upper()
    if mode not in ("IMG", "T2V", "I2V", "F2V"):
        raise HTTPException(422, f"unknown mode '{body.mode}' (use IMG/T2V/I2V/F2V)")
    if not body.prompt.strip():
        raise HTTPException(422, "prompt is required")
    # Validate model+duration BEFORE connectivity so 422 stays deterministic (patch I2a);
    # always resolve against the EFFECTIVE model (defaults to Lite) so a bad duration_s with
    # no model (e.g. 10s on default Lite) is caught here, not late inside the job.
    if mode in ("T2V", "I2V", "F2V"):
        from agent.services import video_models as _vm
        # Operator-surface capability gate (fail-closed) runs FIRST when the caller
        # declares an engine + SINGLE generation_mode (the Step-1 operator surface
        # always does) so stable capability error codes take precedence. It is
        # stricter than the registry check (also enforces operator policy ∩ model).
        # Bare programmatic callers omit `engine` and keep the registry-only lane.
        if body.engine and (body.generation_mode or "SINGLE").upper() == "SINGLE":
            from agent.services import video_capability_matrix as _cm
            if (
                body.capability_matrix_version
                and body.capability_matrix_version != _cm.CAPABILITY_MATRIX_VERSION
            ):
                raise HTTPException(422, _cm.ERR_CAPABILITY_MATRIX_VERSION_MISMATCH)
            ok, code = _cm.validate_single(
                body.engine, body.model or _vm.DEFAULT_MODEL, body.duration_s
            )
            if not ok:
                raise HTTPException(422, code)
        else:
            try:
                _vm.expected_cost(body.model or _vm.DEFAULT_MODEL, body.duration_s)
            except ValueError as e:
                raise HTTPException(422, str(e))
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")

    # Resolve visual assets from refs / startAsset to live Flow media IDs, in the
    # canonical slot order (startAsset, subject, scene, style, image).
    resolved_ids = list(body.image_media_ids or [])
    for slot_label, ref_asset in ordered_ref_slots(body.startAsset, body.refs):
        media_id = await _resolve_asset_to_media_id(client, ref_asset, slot_label)
        if media_id and media_id not in resolved_ids:
            resolved_ids.append(media_id)

    tier = "PAYGATE_TIER_ONE"
    if mode in ("T2V", "I2V", "F2V"):  # video modes need Pro/Ultra
        cred = await client.get_credits()
        tier = (cred.get("data", cred) or {}).get("userPaygateTier", "") if isinstance(cred, dict) else ""
        if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            raise HTTPException(500, f"Account tier '{tier}' cannot generate video — needs Pro/Ultra")
    result = await _mv.start_generate(
        mode, body.prompt, project_id=body.project_id,
        image_media_ids=resolved_ids, image_prompt=body.image_prompt,
        aspect=body.aspect, tier=tier, model=body.model, duration_s=body.duration_s,
        num_videos=body.count, image_model=body.image_model)
    if isinstance(result, dict) and result.get("status") == "REJECTED":
        # single-flight video lane busy (patch H)
        raise HTTPException(409, result.get("error") or "rejected")
    return result


@router.get("/generate-job/{job_id}")
async def generate_job(job_id: str):
    from agent.services import make_video as _mv
    j = _mv.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


ARTIFACT_RETENTION_HOURS = 48  # retention law: results auto-delete after 48h


@router.get("/artifacts")
async def list_artifacts(limit: int = 50, mode: str = None, kind: str = None):
    """System library of finished generations — newest first, for the Library
    pages. kind = video | image. Retention: 48h, enforced lazily on every
    listing (expired files + rows are purged before results are returned).
    Each entry is playable/downloadable via /api/flow/retrieved/{media_id}."""
    from datetime import datetime, timedelta, timezone
    purged = await crud.purge_expired_artifacts(ARTIFACT_RETENTION_HOURS)
    items = await crud.list_generated_artifacts(limit=limit, mode=mode, kind=kind)
    for item in items:
        try:
            created = datetime.strptime(item["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc)
            expires = created + timedelta(hours=ARTIFACT_RETENTION_HOURS)
            item["expires_at"] = expires.strftime("%Y-%m-%dT%H:%M:%SZ")
            item["expires_in_hours"] = max(
                0, round((expires - datetime.now(timezone.utc)).total_seconds() / 3600, 1))
        except (ValueError, TypeError):
            item["expires_at"] = None
            item["expires_in_hours"] = None
    return {"artifacts": items, "count": len(items),
            "retention_hours": ARTIFACT_RETENTION_HOURS, "purged": purged}


@router.get("/retrieved/{media_id}")
async def get_retrieved_artifact(media_id: str):
    """Serve a retrieved artifact (mp4/jpg/png) so the dashboard can preview the
    result inline the moment a job completes — no back-button/reload hunting."""
    from fastapi.responses import FileResponse
    from agent.config import OUTPUT_DIR
    if not _FLOW_MEDIA_UUID_RE.match(str(media_id or "")):
        raise HTTPException(422, "media_id must be a bare UUID")
    base = OUTPUT_DIR / "retrieved"
    for ext, mime in ((".mp4", "video/mp4"), (".jpg", "image/jpeg"), (".png", "image/png")):
        candidate = base / f"{media_id}{ext}"
        if candidate.exists():
            return FileResponse(candidate, media_type=mime)
    raise HTTPException(404, "artifact not found")


@router.get("/bind-check")
async def bind_check():
    """0-credit diagnostic: does the live harvest expose the bind inputs, and does
    _bind_editor_session() succeed? Settles whether the binder matches the real bridge shape."""
    from agent.services import make_video as _mv
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    raw = await client.harvest_video_urls()
    inner = raw.get("result", raw) if isinstance(raw, dict) else {}
    shape = {
        "top_keys": list(raw.keys()) if isinstance(raw, dict) else None,
        "inner_keys": list(inner.keys()) if isinstance(inner, dict) else None,
        "has_flow_url": bool(isinstance(inner, dict) and inner.get("flow_url")),
        "has_flow_tab_id": isinstance(inner, dict) and inner.get("flow_tab_id") is not None,
        "flow_tab_found": isinstance(inner, dict) and inner.get("flow_tab_found"),
    }
    try:
        binding = await _mv._bind_editor_session(client)
        # Verify the tab-targeted harvest reads the SAME bound tab (patch #2).
        h2 = await client.harvest_video_urls(tab_id=binding["flow_tab_id"])
        i2 = h2.get("result", h2) if isinstance(h2, dict) else {}
        d2 = i2.get("diag", i2) if isinstance(i2, dict) else {}
        targeted = {
            "error": i2.get("error"),
            "flow_tab_id": i2.get("flow_tab_id"),
            "projectId": d2.get("projectId") if isinstance(d2, dict) else None,
        }
        targeted["matches_bound"] = (
            i2.get("flow_tab_id") == binding["flow_tab_id"]
            and targeted["projectId"] == binding["project_id"])
        return {"bound": True, "binding": binding, "shape": shape,
                "targeted_harvest": targeted}
    except Exception as e:  # noqa: BLE001
        return {"bound": False, "error": str(e), "shape": shape}


class NegotiateJobRequest(BaseModel):
    prompt: str = "Vertical 9:16 cinematic product video. Slow push-in on the product, soft light, subtle motion. Make 1 video."
    image_prompt: Optional[str] = None  # None → pure T2V dry capture (no start frame)
    dry: bool = True
    model: Optional[str] = None         # steer the agent to this model (patch I4a)
    duration_s: Optional[int] = None
    project_id: Optional[str] = None    # reuse an existing project (minimise junk)


@router.post("/negotiate-job")
async def negotiate_job(body: NegotiateJobRequest):
    """Async negotiation (captures full transcript). dry=True → 0 video credits."""
    from agent.services import make_video as _mv
    from agent.services import video_models as _vm
    # Fail-closed model+duration validation BEFORE start (matches /generate + /make-video-
    # existing) so an invalid request 422s instead of spawning a job + a junk project.
    try:
        _vm.expected_cost(body.model or _vm.DEFAULT_MODEL, body.duration_s)
    except ValueError as e:
        raise HTTPException(422, str(e))
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    return await _mv.start_negotiate(
        body.prompt, body.image_prompt, body.dry,
        model=body.model, duration_s=body.duration_s, project_id=body.project_id)


@router.get("/negotiate-job/{job_id}")
async def negotiate_job_status(job_id: str):
    from agent.services import make_video as _mv
    j = _mv.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/create-project-raw")
async def create_project_raw(body: CreateProjectRawRequest):
    """Debug helper: return raw Google Flow createProject response."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.create_project(body.project_title, body.tool_name)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return result


@router.post("/generate-video")
async def generate_video(body: GenerateVideoRequest):
    """Submit video generation (returns operations for polling)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.generate_video(**body.model_dump(exclude_none=True))
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    return result.get("data", result)


@router.post("/generate-video-refs")
async def generate_video_refs(body: GenerateVideoRefsRequest):
    """Submit r2v video generation from reference images."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.generate_video_from_references(**body.model_dump())
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    return result.get("data", result)


@router.post("/upscale-video")
async def upscale_video(body: UpscaleVideoRequest):
    """Submit video upscale (returns operations for polling)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.upscale_video(**body.model_dump())
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    return result.get("data", result)


def _native_extend_chain_request(body: ExtendRunRequest, runtime):
    return runtime.ExtendChainRequest(
        project_id=body.project_id, scene_id=body.scene_id,
        source_operation_id=body.source_operation_id,
        blocks=[runtime.ExtendBlock(
            block_index=b.block_index, position=b.position, prompt=b.prompt,
            is_final=b.is_final, start_frame_index=b.start_frame_index,
            end_frame_index=b.end_frame_index) for b in body.blocks],
        aspect_ratio=body.aspect_ratio,
        workspace_generation_package_id=body.workspace_generation_package_id,
        seed=body.seed, user_paygate_tier=body.user_paygate_tier)


@router.post("/native-extend/live-authorization")
async def native_extend_live_authorization(body: ExtendRunRequest):
    """Issue one bounded, expiring authorization after explicit operator confirmation.

    This route only resolves the existing chain plan. It never calls Google Flow or
    spends credits; the resulting token is valid for one matching /extend-run call.
    """
    from agent.services import extend_route_planner as _routes
    from agent.services import google_flow_native_extend_runtime as _nx
    if body.dry_run or not body.confirm_live_credit_burn:
        raise HTTPException(409, _nx.LIVE_CREDIT_CONFIRMATION_REQUIRED)
    try:
        authorization = await _nx.issue_live_authorization(
            _native_extend_chain_request(body, _nx),
            confirmed_operation_count=body.confirmed_extend_operation_count,
        )
        return {
            "authorization_token": authorization["token"],
            "planned_operation_count": authorization["planned_operation_count"],
            "expires_in_seconds": authorization["expires_in_seconds"],
        }
    except _routes.CapabilityAuthorityMissing as exc:
        raise HTTPException(403, str(exc))
    except _nx.NativeExtendError as exc:
        raise HTTPException(422 if exc.code in {
            _nx.EXTEND_PARENT_MEDIA_ID_MISSING, _nx.EXTEND_PROJECT_CONTEXT_MISSING,
            _nx.EXTEND_SCENE_CONTEXT_MISSING, _nx.EXTEND_RUNTIME_CONTRACT_MISSING,
            _nx.EXTEND_UNSUPPORTED_MODEL, _nx.EXTEND_UNSUPPORTED_DURATION,
        } else 409, str(exc))


@router.post("/extend-run")
async def extend_run(body: ExtendRunRequest):
    """Native Flow Extend CHAIN — THE single authoritative execution surface.

    Every production native-extend submission goes through this one path (validation
    -> capability -> bounded confirmation -> persistence -> idempotency -> submit ->
    child extraction -> polling -> lineage -> resume). There is NO direct-submit
    bypass. Explicit live/dry-run contract (caller intent is never silently rewritten):
      * dry_run=true  -> plan + persist SOURCE_READY, spend nothing.
      * dry_run=false + no confirm             -> 409 LIVE_CREDIT_CONFIRMATION_REQUIRED
      * dry_run=false + confirm + flag OFF      -> 409 NATIVE_EXTEND_DISABLED
      * dry_run=false + confirm + no/!=count    -> 409 (confirmation / count mismatch)
      * dry_run=false + confirm + flag ON + count==plan -> live execution.
    """
    from agent.services import extend_route_planner as _routes
    from agent.services import google_flow_native_extend_runtime as _nx
    # NOTE: no connection pre-check here — the runtime runs ALL fail-closed gates
    # (capability -> confirm -> flag -> bounded count) FIRST, so an unauthorized live
    # request is rejected with its precise 4xx regardless of extension state. A genuine
    # disconnect surfaces from the submit path as EXTEND_REQUEST_REJECTED.
    client = get_flow_client()
    chain_req = _native_extend_chain_request(body, _nx)
    try:
        return await _nx.run_native_extend_chain(
            client, chain_req, dry_run=body.dry_run,
            confirm_live_credit_burn=body.confirm_live_credit_burn,
            confirmed_extend_operation_count=body.confirmed_extend_operation_count,
            live_authorization_token=body.live_authorization_token)
    except _routes.CapabilityAuthorityMissing as exc:
        raise HTTPException(403, str(exc))
    except _nx.NativeExtendError as exc:
        code_422 = {
            _nx.EXTEND_PARENT_MEDIA_ID_MISSING, _nx.EXTEND_PROJECT_CONTEXT_MISSING,
            _nx.EXTEND_SCENE_CONTEXT_MISSING, _nx.EXTEND_RUNTIME_CONTRACT_MISSING,
            _nx.EXTEND_UNSUPPORTED_MODEL, _nx.EXTEND_UNSUPPORTED_DURATION,
        }
        raise HTTPException(422 if exc.code in code_422 else 409, str(exc))


@router.post("/native-extend/resolve")
async def native_extend_resolve(body: ExtendResolveRequest):
    """Central native-extend execution decision (readiness / blockers / route) for the
    Operator UI. Pure resolution — no submit, no credit. The exact resume-aware
    planned_operation_count comes from an /extend-run dry_run (real prompts); this
    resolver reports readiness + full block count so the UI can gate coherently."""
    from agent.services import extend_route_planner as _routes
    return _routes.resolve_native_extend_execution(
        parent_operation_id=body.source_operation_id, project_id=body.project_id,
        scene_id=body.scene_id, planned_block_count=body.planned_block_count,
        total_duration_seconds=body.total_duration_seconds)


@router.get("/native-extend/lineage")
async def native_extend_lineage(project_id: str = None,
                                workspace_generation_package_id: str = None):
    """Durable parent->child lineage + polling state for the operator surface."""
    rows = await crud.list_extend_lineage(
        workspace_generation_package_id=workspace_generation_package_id,
        project_id=project_id)
    # Flow media URLs can be signed and short-lived. They remain server-side lineage
    # metadata only and are never returned to the operator/browser surface.
    safe_rows = [{key: value for key, value in row.items() if key != "output_url"} for row in rows]
    return {"lineage": safe_rows, "count": len(safe_rows)}


@router.get("/native-extend/source-candidates")
async def native_extend_source_candidates(limit: int = 8):
    """Finished Block-1 clips usable as Extend parents (newest first, zero credit).

    SEV-1 UX repair: the operator never pastes raw ids — the panel offers these
    candidates and /native-extend/resolve-source completes the scene context."""
    rows = await crud.list_extend_source_candidates(limit=limit)
    return {"candidates": rows, "count": len(rows)}


class ExtendResolveSourceRequest(BaseModel):
    """Resolve one finished clip into a verified Extend parent context."""
    media_id: str
    project_id: str


@router.post("/native-extend/resolve-source")
async def native_extend_resolve_source(body: ExtendResolveSourceRequest):
    """Auto-resolve {project, scene, source operation} from a finished clip.

    Read-only Flow GETs (scenes + workflows listings); fail-closed 404 when the
    clip cannot be verified inside the project — never guesses a scene id."""
    from agent.services import google_flow_native_extend_runtime as _nx
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        return await _nx.resolve_extend_source_context(
            client, media_id=body.media_id, project_id=body.project_id)
    except _nx.NativeExtendError as exc:
        raise HTTPException(404, str(exc))



# ─── ONE logical full-video job (Mission C/E/F) ──────────────────────────────
class VideoJobCreateRequest(BaseModel):
    """Bind one logical full-duration video job to a verified source clip."""
    source_media_id: str
    project_id: str
    requested_total_duration_seconds: int = 16
    product_id: Optional[str] = None
    product_name: Optional[str] = None


class VideoJobFinalizeRequest(BaseModel):
    """Render the ONE final MP4. DRY-RUN default; live needs explicit confirm."""
    dry_run: bool = True
    confirm_live_credit_burn: bool = False


@router.post("/video-jobs")
async def create_video_job(body: VideoJobCreateRequest):
    """Create the logical job: verified source + already-proven Extend children.

    Segments are INTERNAL: the user deliverable is one final full-duration MP4.
    Fail-closed at every identity step; spends nothing."""
    import json as _json
    from agent.services import google_flow_native_extend_runtime as _nx
    from agent.services import google_flow_final_timeline_runtime as _ft
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        ctx = await _nx.resolve_extend_source_context(
            client, media_id=body.source_media_id, project_id=body.project_id)
    except _nx.NativeExtendError as exc:
        raise HTTPException(404, str(exc))
    # Successful Extend children of this source, in position order (scene-matched).
    rows = await crud.list_extend_lineage(project_id=body.project_id)
    children = sorted(
        [r for r in rows
         if r.get("parent_operation_id") == body.source_media_id
         and r.get("polling_state") == "EXTEND_SUCCEEDED"
         and r.get("child_operation_id")
         and (not r.get("scene_id") or r.get("scene_id") == ctx["scene_id"])],
        key=lambda r: (r.get("block_position") or 0))
    segments = [body.source_media_id] + [r["child_operation_id"] for r in children]
    needed = max(2, int(body.requested_total_duration_seconds // 8))
    status = (_ft.JOB_SEGMENTS_READY if len(segments) >= needed
              else _ft.JOB_BINDING_EXTEND)
    job_id = f"vj_{uuid4().hex[:12]}"
    await crud.create_video_production_job(
        job_id, project_id=body.project_id, scene_id=ctx["scene_id"],
        requested_duration_seconds=body.requested_total_duration_seconds,
        status=status, initial_media_id=body.source_media_id,
        segment_media_ids_json=_json.dumps(segments),
        product_id=body.product_id, product_name=body.product_name)
    return {
        "job_id": job_id, "status": status, "scene_id": ctx["scene_id"],
        "segments": segments, "segments_needed": needed,
        "next": ("finalize" if status == _ft.JOB_SEGMENTS_READY
                 else "run native Extend for the missing continuation block(s)"),
    }


@router.get("/video-jobs")
async def list_video_jobs(limit: int = 20):
    return {"jobs": await crud.list_video_production_jobs(limit=limit)}


@router.get("/video-jobs/{job_id}")
async def get_video_job(job_id: str):
    job = await crud.get_video_production_job(job_id)
    if not job:
        raise HTTPException(404, "VIDEO_JOB_NOT_FOUND")
    return job


@router.post("/video-jobs/{job_id}/finalize")
async def finalize_video_job(job_id: str, body: VideoJobFinalizeRequest):
    """Final timeline render → ONE full-duration MP4 (captured concat contract).

    DRY-RUN returns the exact planned submit and spends nothing. Live requires
    the kill-switch AND explicit confirmation; duration is validated fail-closed
    (a 16s request must never complete with an 8s segment)."""
    import json as _json
    from agent.services import google_flow_final_timeline_runtime as _ft
    from agent.config import OUTPUT_DIR
    job = await crud.get_video_production_job(job_id)
    if not job:
        raise HTTPException(404, "VIDEO_JOB_NOT_FOUND")
    segments = _json.loads(job.get("segment_media_ids_json") or "[]")
    client = get_flow_client()
    if not body.dry_run and not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        result = await _ft.finalize_timeline(
            client, job_id=job_id, segment_media_ids=segments,
            requested_seconds=int(job.get("requested_duration_seconds") or 16),
            out_dir=OUTPUT_DIR / "retrieved",
            dry_run=body.dry_run,
            confirm_live_credit_burn=body.confirm_live_credit_burn)
    except _ft.FinalTimelineError as exc:
        code_409 = {_ft.LIVE_CONFIRMATION_REQUIRED, _ft.FINAL_TIMELINE_DISABLED,
                    _ft.FINAL_DUPLICATE_SUBMISSION_BLOCKED}
        raise HTTPException(409 if exc.code in code_409 else 422, str(exc))
    if not body.dry_run and result.get("status") == _ft.JOB_COMPLETE:
        # Register the ONE final deliverable in the system library so the existing
        # /retrieved/{media_id} route serves it (per-block files stay diagnostics).
        await crud.insert_generated_artifact(
            result["final_media_id"], job_id=job_id, mode="EXTEND",
            artifact_kind="video", local_path=result["local_path"],
            size_mb=result.get("size_mb"), project_id=job.get("project_id"),
            duration_used=int(result.get("measured_duration_s") or 0))
    return result


@router.post("/check-status")
async def check_status(body: CheckStatusRequest):
    """Check video generation status."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.check_video_status(body.operations)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return result.get("data", result)


@router.post("/refresh-urls/{project_id}")
async def refresh_project_urls(project_id: str):
    """Bulk refresh all media URLs for a project via per-media get_media calls."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.refresh_project_urls(project_id)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return result


@router.get("/media/{media_id}")
async def get_media(media_id: str):
    """Get media metadata + fresh signed URL from Google Flow.

    Returns the raw response which should contain a fresh fifeUrl/servingUri.
    Use this to refresh expired GCS signed URLs.
    """
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.get_media(media_id)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    status = result.get("status", 200)
    if isinstance(status, int) and status >= 400:
        raise HTTPException(status, result.get("data", "Media not found"))
    return result.get("data", result)


@router.post("/edit-image")
async def edit_image(body: EditImageRequest):
    """Edit an existing image using IMAGE_INPUT_TYPE_BASE_IMAGE (bypasses queue)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    result = await client.edit_image(
        body.prompt, body.source_media_id, body.project_id,
        aspect_ratio=body.aspect_ratio,
        user_paygate_tier=body.user_paygate_tier,
    )
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    return result.get("data", result)


@router.post("/upload-image")
async def upload_image(body: UploadImageRequest):
    """Upload a local image file to Google Flow and get a media_id."""
    import base64, mimetypes
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        with open(body.file_path, "rb") as f:
            image_bytes = f.read()
    except FileNotFoundError:
        raise HTTPException(404, f"File not found: {body.file_path}")
    b64 = base64.b64encode(image_bytes).decode()
    mime = mimetypes.guess_type(body.file_path)[0] or "image/png"
    result = await client.upload_image(b64, mime_type=mime, project_id=body.project_id, file_name=body.file_name)
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    media_id = result.get("_mediaId")
    return {"media_id": media_id, "raw": result.get("data", result)}


@router.post("/upload-image-base64")
async def upload_image_base64(body: UploadImageBase64Request):
    """Upload a browser-selected image to Google Flow and get a media_id."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")

    image_base64 = body.image_base64.strip()
    if "," in image_base64 and image_base64.startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]

    ext = "png"
    file_name = Path(body.file_name or "image.png").name
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower() or "png"
    _UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    temp_file_path = _UPLOAD_STAGING_DIR / f"{uuid4().hex}.{ext}"
    temp_file_path.write_bytes(base64.b64decode(image_base64))

    result = await client.upload_image(
        image_base64,
        mime_type=body.mime_type,
        project_id=body.project_id,
        file_name=body.file_name,
    )
    if result.get("error") or (isinstance(result.get("status"), int) and result["status"] >= 400):
        raise HTTPException(result.get("status", 502), result.get("error", result.get("data")))
    media_id = result.get("_mediaId")
    return {
        "media_id": media_id,
        "file_name": file_name,
        "mime_type": body.mime_type,
        "local_file_path": str(temp_file_path),
        "raw": result.get("data", result),
    }


class ShootOneshotRequest(BaseModel):
    """OTAK envelope — INTEGRATION_CONTRACT.md §5. (project_id/scene_id minted here.)"""
    prompt: str
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    user_paygate_tier: str = "PAYGATE_TIER_ONE"
    start_frame: dict = {}


@router.post("/shoot-oneshot")
async def shoot_oneshot(body: ShootOneshotRequest):
    """Async one-shot video: envelope -> job_id. Poll GET /flow/job/{id}. Contract §4.1."""
    from agent.services import shoot_oneshot as _os
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    # Precondition: real account tier must be paid. Read it live (don't trust the
    # envelope), and pass the real tier downstream to avoid a tier-mismatch 500.
    cred = await client.get_credits()
    if cred.get("error"):
        raise HTTPException(502, cred["error"])
    real_tier = (cred.get("data", cred) or {}).get("userPaygateTier", "")
    if real_tier not in _os.PAID_TIERS:
        raise HTTPException(
            500,
            f"Account tier '{real_tier}' cannot generate video — "
            "needs a paid (Pro/Ultra) subscription.",
        )
    return await _os.start_job(body.model_dump(), real_tier)


@router.get("/job/{job_id}")
async def get_oneshot_job(job_id: str):
    """Poll a one-shot video job. Contract §4.2."""
    from agent.services import shoot_oneshot as _os
    job = _os.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.post("/materialize-local-file")
async def materialize_local_file(body: MaterializeLocalFileRequest):
    """Write a base64 image to a temp staging file and return its absolute disk path.

    Phase 2 CDP upload helper: the extension service worker cannot write to disk, and
    CDP `DOM.setFileInputFiles` needs a real file path. This materializes the asset bytes
    to flowkit-upload-staging/<uuid>.<ext> WITHOUT uploading to Google Flow (unlike
    /upload-image-base64, which also performs the Flow upload).
    """
    image_base64 = body.image_base64.strip()
    if "," in image_base64 and image_base64.startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]

    file_name = Path(body.file_name or "asset.png").name
    ext = "png"
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower() or "png"

    _UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    temp_file_path = _UPLOAD_STAGING_DIR / f"{uuid4().hex}.{ext}"
    try:
        temp_file_path.write_bytes(base64.b64decode(image_base64))
    except Exception as e:
        raise HTTPException(400, f"ERR_MATERIALIZE_DECODE_FAILED: {e}")

    return {
        "ok": True,
        "local_file_path": str(temp_file_path),
        "file_name": file_name,
        "mime_type": body.mime_type,
    }


async def _materialize_remote_url_to_staging(
    source_url: str, file_name: str = "asset.png"
) -> dict:
    """Fetch a remote image server-side and stage it on disk for CDP upload.

    The strict F2V_PACKAGE_UPLOAD_ONLY lane's CDP file chooser needs a real local
    file, so a remote-only package Start asset is materialized to a local path
    before dispatch. Returns {local_file_path, file_name, mime_type}.
    """
    source_url = str(source_url or "").strip()
    if not re.match(r"^https?://", source_url, re.IGNORECASE):
        raise ValueError("ERR_REMOTE_MATERIALIZE_BAD_URL")
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(source_url) as resp:
            if resp.status >= 400:
                raise ValueError(f"ERR_REMOTE_MATERIALIZE_FETCH_FAILED: HTTP_{resp.status}")
            raw_bytes = await resp.read()
            if not raw_bytes:
                raise ValueError("ERR_REMOTE_MATERIALIZE_FETCH_FAILED: EMPTY_BODY")
            mime_type = (
                (resp.headers.get("Content-Type") or "image/png").split(";", 1)[0].strip()
                or "image/png"
            )
    parsed = urlparse(source_url)
    default_name = Path(parsed.path).name or "asset"
    file_name = Path(file_name or default_name).name
    if "." not in file_name:
        ext = (mime_type.split("/", 1)[-1] or "png").lower().replace("jpeg", "jpg")
        file_name = f"{file_name}.{ext}"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "png"
    _UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    temp_file_path = _UPLOAD_STAGING_DIR / f"{uuid4().hex}.{ext}"
    temp_file_path.write_bytes(raw_bytes)
    return {"local_file_path": str(temp_file_path), "file_name": file_name, "mime_type": mime_type}


async def _fail_manual_request(request_id: str, stage: str, message: str, error_code: str):
    """Fail-closed telemetry writer for the manual lane (mirrors _fail_closed_materialize)."""
    await crud.add_stage_event(request_id, stage, "FAIL", message, "backend")
    await crud.upsert_request_telemetry(
        request_id, status="FAILED", failed_at=crud._now(),
        error_message=error_code, error_code=error_code,
        last_heartbeat_at=crud._now(),
    )
    await crud.add_stage_event(
        request_id, "FAILED", "FAILED", error_code, "backend",
        fail_code=error_code, first_fail_stage=stage,
    )
    raise HTTPException(422, error_code)


async def _persist_generation_results(snapshot, job, all_ids):
    """Best-effort: write the DURABLE Results Hub record for every finished media
    id, enriched with the product display name. Telemetry has already resolved
    COMPLETED, so a DB hiccup here must NEVER fail the job (wrapped, swallowed)."""
    if not snapshot:
        return
    try:
        media_ids = list(all_ids) or (
            [job.get("media_id")] if job.get("media_id") else [])
        if not media_ids:
            return
        product_name = None
        pid = snapshot.get("product_id")
        if pid:
            try:
                prod = await crud.get_product(pid)
                if prod:
                    product_name = (prod.get("product_display_name")
                                    or prod.get("raw_product_title")
                                    or prod.get("name"))
            except Exception:  # noqa: BLE001 — display enrichment is non-critical
                product_name = None
        for mid in media_ids:
            await crud.insert_generation_result(
                mid,
                job_id=snapshot.get("job_id"),
                request_id=snapshot.get("request_id"),
                mode=snapshot.get("mode"),
                artifact_kind=snapshot.get("artifact_kind") or "video",
                product_id=pid,
                product_name=product_name,
                final_prompt_text=snapshot.get("final_prompt_text") or "",
                aspect_ratio=snapshot.get("aspect_ratio"),
                model_label=snapshot.get("model_label"),
                duration_s=snapshot.get("duration_s"),
                count_setting=snapshot.get("count_setting"),
                reference_media_ids=snapshot.get("reference_media_ids") or [],
                workspace_generation_package_id=snapshot.get(
                    "workspace_generation_package_id"),
                project_id=snapshot.get("project_id"),
            )
    except Exception:  # noqa: BLE001 — durable record is best-effort, never fatal
        pass


async def _bridge_generate_job_telemetry(request_id: str, job_id: str,
                                         result_snapshot: dict = None):
    """Mirror a make_video job's progress into request telemetry so the dashboard
    poll loop (which watches the request row) resolves to COMPLETED/FAILED. On
    DONE it also persists the durable Results Hub record(s) for the artifact."""
    import asyncio
    from agent.services import make_video as _mv
    last_stage = None
    for _ in range(240):  # up to ~40 min
        job = _mv.get_job(job_id) or {}
        stage = str(job.get("stage") or "")
        status = str(job.get("status") or "")
        if stage and stage != last_stage:
            last_stage = stage
            await crud.add_stage_event(
                request_id, "API_GENERATE_PROGRESS", "WAITING_FLOW",
                f"job={job_id} status={status} stage={stage}", "backend",
            )
            await crud.upsert_request_telemetry(request_id, last_heartbeat_at=crud._now())
        if status == "DONE":
            all_ids = [a.get("media_id") for a in (job.get("artifacts") or []) if a.get("media_id")]
            await crud.add_stage_event(
                request_id, "COMPLETED", "PASS",
                f"job={job_id} media_id={job.get('media_id')} size_mb={job.get('size_mb')} "
                f"artifacts={len(all_ids) or 1} all_media_ids={','.join(all_ids)} "
                f"{'PARTIAL: ' + str(job.get('partial_detail')) if job.get('partial') else ''} "
                f"local_path={job.get('local_path')}", "backend",
            )
            await crud.upsert_request_telemetry(
                request_id, status="COMPLETED", completed_at=crud._now(),
                last_heartbeat_at=crud._now(),
            )
            await crud.update_request(request_id, status="COMPLETED", updated_at=crud._now())
            await _persist_generation_results(result_snapshot, job, all_ids)
            return
        if status in ("FAILED", "GENERATED_BUT_UNRETRIEVED"):
            code = str(job.get("error") or status)
            await crud.upsert_request_telemetry(
                request_id, status="FAILED", failed_at=crud._now(),
                error_message=code, error_code=code, last_heartbeat_at=crud._now(),
            )
            await crud.add_stage_event(
                request_id, "FAILED", "FAIL", f"job={job_id} {code}", "backend",
                fail_code=code, first_fail_stage="API_GENERATE_PROGRESS",
            )
            await crud.update_request(
                request_id, status="FAILED", error_message=code, updated_at=crud._now(),
            )
            return
        await asyncio.sleep(10)


async def _resolve_asset_to_media_id(client, asset: dict, slot: str, request_id: str | None = None) -> str:
    """Resolve ONE dashboard asset (startAsset or refs.*) to a LIVE Flow media id.
    Priority: valid UUID media id (validated pre-credits, self-heals if stale) →
    local file upload → remote downloadUrl materialize + upload. Fails closed."""
    import mimetypes
    import os
    token = re.sub(r"[^A-Z0-9]+", "_", slot.upper()).strip("_")
    media_id = _extract_flow_media_id(asset)
    local_path = asset.get("localFilePath") or asset.get("local_file_path")
    if media_id:
        check = await client.get_media(str(media_id))
        check_status = check.get("status") if isinstance(check, dict) else None
        media_alive = bool(
            isinstance(check, dict) and not check.get("error")
            and (check_status is None or (isinstance(check_status, int) and check_status < 400)))
        if media_alive:
            if request_id:
                await crud.add_stage_event(
                    request_id, f"API_{token}_ASSET_RESOLVED", "WAITING_FLOW",
                    f"source_type=existing_flow_media media_id={media_id}", "backend")
            return str(media_id)
        if request_id:
            await crud.add_stage_event(
                request_id, f"API_{token}_ASSET_STALE", "WAITING_FLOW",
                f"media_id={media_id} is dead (status={check_status}); "
                f"self-healing via re-upload", "backend")
    if not local_path:
        remote_url = _asset_payload_remote_url(asset)
        if remote_url:
            try:
                materialized = await _materialize_remote_url_to_staging(
                    str(remote_url), _asset_payload_file_name(asset, f"{slot}.png"))
                local_path = materialized["local_file_path"]
                if request_id:
                    await crud.add_stage_event(
                        request_id, f"API_{token}_ASSET_MATERIALIZED", "WAITING_FLOW",
                        f"source_type=remote_url local={local_path}", "backend")
            except Exception as exc:
                if request_id:
                    await _fail_manual_request(
                        request_id, f"API_{token}_ASSET_MATERIALIZE_FAILED",
                        f"cannot download {slot} asset url: {exc}",
                        f"ERR_{token}_MATERIALIZE_FAILED")
                raise HTTPException(422, f"ERR_{token}_MATERIALIZE_FAILED") from exc
    if not local_path:
        if request_id:
            await _fail_manual_request(
                request_id, f"API_{token}_ASSET_STALE",
                f"{slot} asset has no live media id, no local file and no remote url — "
                f"re-attach the image",
                f"ERR_{token}_MEDIA_NOT_FOUND")
        raise HTTPException(422, f"ERR_{token}_MEDIA_NOT_FOUND")
    try:
        with open(local_path, "rb") as f:
            image_bytes = f.read()
    except OSError as exc:
        if request_id:
            await _fail_manual_request(
                request_id, f"API_{token}_ASSET_UPLOAD_FAILED",
                f"cannot read {slot} asset: {exc}", f"ERR_{token}_UPLOAD_API_FAILED")
        raise HTTPException(422, f"ERR_{token}_UPLOAD_API_FAILED") from exc
    b64 = base64.b64encode(image_bytes).decode()
    # Asset-authority evidence (SEV-1): hash the EXACT bytes being uploaded so the
    # request's durable stage history proves which file became the Flow reference.
    asset_sha256 = hashlib.sha256(image_bytes).hexdigest()
    mime = mimetypes.guess_type(str(local_path))[0] or "image/png"
    up = await client.upload_image(
        b64, mime_type=mime, project_id="",
        file_name=os.path.basename(str(local_path)))
    uploaded_id = up.get("_mediaId") if isinstance(up, dict) else None
    if not uploaded_id:
        if request_id:
            await _fail_manual_request(
                request_id, f"API_{token}_ASSET_UPLOAD_FAILED",
                f"upload_image returned no media id: {str(up)[:300]}",
                f"ERR_{token}_UPLOAD_API_FAILED")
        raise HTTPException(422, f"ERR_{token}_UPLOAD_API_FAILED")
    if request_id:
        await crud.add_stage_event(
            request_id, f"API_{token}_ASSET_UPLOADED", "WAITING_FLOW",
            f"source_type=api_upload media_id={uploaded_id} "
            f"file={os.path.basename(str(local_path))} sha256={asset_sha256}",
            "backend")
    return str(uploaded_id)


async def _run_manual_job_via_generate(body: dict, mode: str, start_asset):
    """ADR-007 API-first lane for manual workspace jobs: resolve the start asset to a
    Flow media id (existing id, or API upload of the materialized local file), then run
    the proven unified pipeline (make_video.start_generate). No DOM automation."""
    import asyncio
    from agent.services import make_video as _mv
    client = get_flow_client()
    request_id = body["request_id"]
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED", "manual job has no prompt", "ERR_PROMPT_REQUIRED")

    # Collect EVERY image the dashboard sent: F2V uses startAsset; I2V/IMG send
    # refs.{subjectAsset,sceneAsset,styleAsset} (previously DROPPED here — I2V died
    # ERR_START_ASSET_REQUIRED and IMG silently ignored its reference images).
    slot_assets = ordered_ref_slots(start_asset, body.get("refs"))
    refs = []
    for slot_label, asset in slot_assets:
        resolved = await _resolve_asset_to_media_id(client, asset, slot_label, request_id)
        if resolved and resolved not in refs:
            refs.append(resolved)

    if mode in ("I2V", "F2V") and not refs:
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED",
            f"{mode} needs a start/reference image", "ERR_START_ASSET_REQUIRED")

    tier = "PAYGATE_TIER_ONE"
    if mode in ("T2V", "I2V", "F2V"):
        cred = await client.get_credits()
        tier = (cred.get("data", cred) or {}).get("userPaygateTier", "") if isinstance(cred, dict) else ""
        if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            await _fail_manual_request(
                request_id, "API_LANE_REJECTED",
                f"account tier '{tier}' cannot generate video", "ERR_ACCOUNT_TIER_NO_VIDEO")

    # Ensure an editor project is OPEN before the video bind. The video lane itself
    # fail-closes and never mints hidden projects (patch A/G) — correct for the
    # automated queue, but a user-initiated dashboard job may legitimately start
    # with NO project open (user cleaned up Flow; live: manual_1fb86ffd died
    # NO_OPEN_EDITOR after the user deleted every project). Create + open one
    # EXPLICITLY, with telemetry, and pin the bind to it.
    created_project_id = None
    if mode in ("T2V", "I2V", "F2V"):
        h = await client.harvest_video_urls()
        inner = h.get("result", h) if isinstance(h, dict) else {}
        diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
        on_editor = bool(
            isinstance(diag, dict) and diag.get("projectId")
            and "/project/" in str((inner or {}).get("flow_url") or ""))
        if not on_editor:
            proj = await client.create_project(f"bosmax {mode.lower()} manual")
            created_project_id = _extract_project_id(proj)
            if not created_project_id:
                await _fail_manual_request(
                    request_id, "API_PROJECT_CREATE_FAILED",
                    f"create_project returned no projectId: {str(proj)[:200]}",
                    "ERR_PROJECT_CREATE_FAILED")
            await crud.add_stage_event(
                request_id, "API_PROJECT_CREATED", "WAITING_FLOW",
                f"project_id={created_project_id} (no editor was open)", "backend")
            try:
                await client.open_target_flow_project(
                    f"https://labs.google/fx/tools/flow/project/{created_project_id}")
            except Exception:  # noqa: BLE001 — bind re-verifies; opener readiness is noisy
                pass
            await asyncio.sleep(5)

    # ── USER SETTINGS ARE LAW (production contract): whatever the operator set in
    # BOSMAX — aspect, count, model, duration — is EXACTLY what reaches Google Flow.
    # The dashboard modules send `aspectRatio` (IMG) or `orientation` (T2V/I2V/F2V),
    # not `aspect` — honour all three (previously everything silently became 9:16).
    aspect = str(body.get("aspect") or body.get("aspectRatio") or "").strip()
    if aspect not in ("9:16", "16:9"):
        aspect = ("16:9" if str(body.get("orientation") or "").strip().upper() == "HORIZONTAL"
                  else "9:16")
    # Count: x2 means TWO videos negotiated AND retrieved (clamped to Flow's 1–4).
    try:
        count = max(1, min(4, int(body.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    # Duration: honour an explicit setting; None → the model's default.
    duration_s = None
    raw_duration = body.get("duration_s") or body.get("duration_seconds")
    if raw_duration:
        try:
            duration_s = int(raw_duration)
        except (TypeError, ValueError):
            duration_s = None
    # Model: the dashboard sends the ui_label ("Omni Flash", "Veo 3.1 - Lite").
    # An unknown model FAILS CLOSED — never silently downgrade the user's choice.
    model_key = None
    if mode in ("T2V", "I2V", "F2V") and body.get("model"):
        from agent.services import video_models as _vm
        try:
            model_key = _vm.resolve(body["model"])["key"]
        except ValueError:
            valid = ", ".join(s["ui_label"] for s in _vm.VIDEO_MODELS.values())
            await _fail_manual_request(
                request_id, "API_LANE_REJECTED",
                f"unknown model '{body.get('model')}' — valid: {valid}",
                "ERR_UNKNOWN_MODEL")
        if duration_s is not None:
            try:
                _vm.expected_cost(model_key, duration_s)
            except ValueError as exc:
                await _fail_manual_request(
                    request_id, "API_LANE_REJECTED", str(exc), "ERR_UNSUPPORTED_DURATION")
    await crud.add_stage_event(
        request_id, "API_USER_SETTINGS_APPLIED", "WAITING_FLOW",
        f"aspect={aspect} count={count} model={model_key or 'default'} "
        f"duration_s={duration_s or 'default'}", "backend")

    res = await _mv.start_generate(
        mode, prompt, project_id=created_project_id,
        image_media_ids=refs or None,
        aspect=aspect, tier=tier, model=model_key,
        duration_s=duration_s, num_videos=count)
    if not isinstance(res, dict) or not res.get("job_id"):
        code = str((res or {}).get("error") or "VIDEO_JOB_IN_FLIGHT")
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED", f"start_generate rejected: {code}", code)
    job_id = res["job_id"]
    await crud.add_stage_event(
        request_id, "API_LANE_ACCEPTED", "WAITING_FLOW",
        f"lane=API_FIRST_GENERATE job={job_id} mode={mode} refs={len(refs)}", "backend")
    # Durable deliverable snapshot (Results Hub): capture the EXACT prompt +
    # settings the operator fired so they survive the 48h artifact purge and can
    # be copied to manually re-drive Flow if automation breaks. The finished
    # media ids are attached on completion inside the telemetry bridge.
    result_snapshot = {
        "request_id": request_id,
        "job_id": job_id,
        "mode": mode,
        "artifact_kind": "image" if mode == "IMG" else "video",
        "product_id": body.get("product_id"),
        "final_prompt_text": prompt,
        "aspect_ratio": aspect,
        "model_label": body.get("model"),
        "duration_s": duration_s,
        "count_setting": count,
        "reference_media_ids": refs,
        "workspace_generation_package_id": (
            body.get("workspace_execution_package_id")
            or body.get("workspace_generation_package_id")),
        "project_id": created_project_id,
    }
    asyncio.create_task(
        _bridge_generate_job_telemetry(request_id, job_id, result_snapshot))
    return {
        "ok": True,
        "accepted": True,
        "lane": "API_FIRST_GENERATE",
        "request_id": request_id,
        "job_id": job_id,
        "mode": mode,
        "status": "SUBMITTED",
    }


@router.post("/execute-flow-job")
async def execute_flow_job(body: dict):
    """Trigger manual DOM automation in the extension for a generation job."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    
    # Ensure request_id exists for tracking
    import uuid
    if "request_id" not in body:
        body["request_id"] = f"manual_{uuid.uuid4().hex[:8]}"

    request_row = await crud.get_request(body["request_id"])
    if not request_row:
        now = crud._now()
        db = await crud.get_db()
        async with crud._db_lock:
            await db.execute(
                """INSERT INTO request (id, type, status, created_at, updated_at)
                   VALUES (?,?,?,?,?)""",
                (body["request_id"], "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now),
            )
            await db.commit()

    await crud.upsert_request_telemetry(
        body["request_id"],
        product_id=body.get("product_id"),
        request_type="MANUAL_FLOW_JOB",
        mode=body.get("mode"),
        prompt_package_snapshot_id=body.get("prompt_package_snapshot_id"),
        workspace_execution_package_id=body.get("workspace_execution_package_id"),
        prompt_fingerprint=body.get("prompt_fingerprint"),
        asset_fingerprints=json.dumps(body.get("asset_fingerprints", [])),
        request_lineage_payload=json.dumps(body.get("request_lineage_payload", {})),
        status="WAITING_FLOW",
        queued_at=crud._now(),
        last_heartbeat_at=crud._now(),
    )
    await crud.add_stage_event(
        body["request_id"],
        "MANUAL_SUBMIT_ACCEPTED",
        "WAITING_FLOW",
        "Operator workspace submitted manual Flow job.",
        "dashboard",
    )

    # Dispatch-wiring proof: record exactly which lane/flags the dashboard sent,
    # so a missing F2V_PACKAGE_UPLOAD_ONLY flag is visible in telemetry rather
    # than silently falling back to the broad F2V SOP path.
    _start_asset = body.get("startAsset") or {}
    _start_asset_present = isinstance(body.get("startAsset"), dict)
    _has_local_start = bool(
        isinstance(_start_asset, dict)
        and (_start_asset.get("localFilePath") or _start_asset.get("local_file_path"))
    )
    await crud.add_stage_event(
        body["request_id"],
        "BACKEND_FLOW_JOB_BUILT",
        "WAITING_FLOW",
        (
            f"lane={body.get('lane')} upload_only={body.get('upload_only')} "
            f"mode={body.get('mode')} "
            f"request_id={'yes' if body.get('request_id') else 'no'} "
            f"workspace_execution_package_id={'yes' if body.get('workspace_execution_package_id') else 'no'} "
            f"prompt={'yes' if body.get('prompt') else 'no'} "
            f"start_local_file={'yes' if _has_local_start else 'no'}"
        ),
        "backend",
    )

    async def _fail_closed_materialize(
        stage_name: str,
        stage_message: str,
        error_code: str,
    ):
        await crud.add_stage_event(
            body["request_id"],
            stage_name,
            "FAIL",
            stage_message,
            "backend",
        )
        await crud.upsert_request_telemetry(
            body["request_id"],
            status="FAILED",
            failed_at=crud._now(),
            error_message=error_code,
            error_code=error_code,
            last_heartbeat_at=crud._now(),
        )
        await crud.add_stage_event(
            body["request_id"],
            "FAILED",
            "FAILED",
            error_code,
            "backend",
            fail_code=error_code,
            first_fail_stage=stage_name,
        )
        raise HTTPException(422, error_code)

    async def _materialize_slot_asset(
        asset: object,
        *,
        slot_label: str,
        source_type: str,
        missing_error_code: str,
        failed_error_code: str,
    ) -> None:
        if not isinstance(asset, dict) or _asset_payload_has_local_file(asset):
            return
        remote_url = _asset_payload_remote_url(asset)
        stage_token = re.sub(r"[^A-Z0-9]+", "_", slot_label.upper()).strip("_")
        if not remote_url:
            await _fail_closed_materialize(
                f"BACKEND_{stage_token}_ASSET_MATERIALIZE_FAILED",
                f"{slot_label} asset is remote-only with no usable URL to materialize",
                missing_error_code,
            )
        try:
            materialized = await _materialize_remote_url_to_staging(
                str(remote_url),
                _asset_payload_file_name(asset, f"{slot_label}.png"),
            )
        except Exception as exc:
            await _fail_closed_materialize(
                f"BACKEND_{stage_token}_ASSET_MATERIALIZE_FAILED",
                str(exc),
                failed_error_code,
            )
        local_path = materialized["local_file_path"]
        asset["localFilePath"] = local_path
        asset["local_file_path"] = local_path
        await crud.add_stage_event(
            body["request_id"],
            f"BACKEND_{stage_token}_ASSET_MATERIALIZED",
            "WAITING_FLOW",
            _build_materialized_stage_message(local_path, source_type),
            "backend",
        )

    # Strict upload-only lane needs a real local file for the CDP file chooser.
    # When the package Start asset is remote-only (no localFilePath/local_file_path),
    # materialize it to a local staging file BEFORE dispatching to the extension.
    # If materialization is impossible/fails, FAIL CLOSED here rather than dispatch
    # a remote-only asset that the lane would only reject.
    _is_upload_only_lane = (
        body.get("lane") == "F2V_PACKAGE_UPLOAD_ONLY"
        or body.get("lane") == "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE"
        or body.get("upload_only") is True
        or body.get("gfv2") is True
    )
    # An asset that already carries a REAL Flow media id (bare UUID) needs no local
    # materialization: the API-first lane references it directly. Composite BOSMAX
    # asset ids (product-image:<uuid>:start_frame) do NOT count — those assets are
    # remote-URL-only and MUST be materialized so the API lane can upload them.
    _has_flow_media_id = bool(_extract_flow_media_id(_start_asset))
    if (_start_asset_present and isinstance(_start_asset, dict)
            and not _has_local_start and not _has_flow_media_id):
        await _materialize_slot_asset(
            _start_asset,
            slot_label="Start",
            source_type=(
                "workspace_package_start"
                if body.get("workspace_execution_package_id")
                or body.get("prompt_package_snapshot_id")
                else "start_asset"
            ),
            missing_error_code=(
                "ERR_PACKAGE_START_LOCAL_FILE_REQUIRED"
                if _is_upload_only_lane
                else "ERR_START_LOCAL_FILE_REQUIRED"
            ),
            failed_error_code=(
                "ERR_PACKAGE_START_MATERIALIZE_FAILED"
                if _is_upload_only_lane
                else "ERR_START_MATERIALIZE_FAILED"
            ),
        )
        body["startAsset"] = _start_asset

    _end_asset = body.get("endAsset")
    if isinstance(_end_asset, dict):
        await _materialize_slot_asset(
            _end_asset,
            slot_label="End",
            source_type="end_asset",
            missing_error_code="ERR_END_LOCAL_FILE_REQUIRED",
            failed_error_code="ERR_END_MATERIALIZE_FAILED",
        )
        body["endAsset"] = _end_asset

    _refs = body.get("refs")
    if isinstance(_refs, dict):
        for ref_key, slot_label in (
            ("subjectAsset", "Subject"),
            ("sceneAsset", "Scene"),
            ("styleAsset", "Style"),
            ("imageAsset", "Image"),
        ):
            ref_asset = _refs.get(ref_key)
            if not isinstance(ref_asset, dict):
                continue
            await _materialize_slot_asset(
                ref_asset,
                slot_label=slot_label,
                source_type="workspace_ref_asset",
                missing_error_code=f"ERR_{slot_label.upper()}_LOCAL_FILE_REQUIRED",
                failed_error_code=f"ERR_{slot_label.upper()}_MATERIALIZE_FAILED",
            )
            _refs[ref_key] = ref_asset
        body["refs"] = _refs

    # ── ADR-007 API-first reroute ─────────────────────────────────────────────
    # The GFV2/F2V DOM-clicking lane is DEAD (fail-closed root_shell_no_project,
    # live: manual_c2560a76). Manual workspace jobs for the four canonical modes
    # now run through the proven unified pipeline (make_video.start_generate);
    # the extension stays transport-only. The DOM dispatch below survives only
    # for any legacy non-mode payloads and will be deleted with the frozen lane.
    _api_mode = str(body.get("mode") or "").upper()
    if _api_mode in ("IMG", "T2V", "I2V", "F2V"):
        return await _run_manual_job_via_generate(
            body, _api_mode, _start_asset if _start_asset_present else None)

    result = await client.execute_flow_job(body)
    if result.get("error"):
        failure_report = await _build_manual_flow_failure_report(body["request_id"], result)
        error_code = failure_report.get("error_code") or _extract_error_code(result["error"])
        request_error_message = error_code or result["error"]
        await crud.upsert_request_telemetry(
            body["request_id"],
            status="FAILED",
            failed_at=crud._now(),
            error_message=request_error_message,
            error_code=error_code,
            last_heartbeat_at=crud._now(),
        )
        await crud.update_request(
            body["request_id"],
            status="FAILED",
            error_message=request_error_message,
            automation_report=json.dumps(failure_report, ensure_ascii=False),
            updated_at=crud._now(),
        )
        await crud.add_stage_event(
            body["request_id"],
            "FAILED",
            "FAILED",
            request_error_message,
            "backend",
            fail_code=error_code,
            first_fail_stage=failure_report.get("latest_extension_stage"),
        )
        raise HTTPException(502, request_error_message)
    return result
