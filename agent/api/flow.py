"""Direct Flow API endpoints — for manual operations outside the queue."""
import base64
import copy
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Optional
from agent.services.flow_client import get_flow_client
from agent.db import crud
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled

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
        and (
            asset.get("localFilePath")
            or asset.get("local_file_path")
            or asset.get("localPath")
            or asset.get("local_path")
        )
    )


# A REAL Flow media id is a bare UUID. The dashboard also sends composite BOSMAX
# asset ids like "product-image:<uuid>:start_frame" in assetId — those are NOT
# Flow media ids and must never short-circuit materialization/upload (live:
# manual_259f0ab1 failed ERR_START_MEDIA_NOT_FOUND because the composite id was
# mistaken for a media id and the remote downloadUrl was never materialized).
_FLOW_MEDIA_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Final concat deliverable ids are minted as `final_{job_id}` (not a Flow UUID);
# the pattern is path-traversal-safe (alphanumerics + underscore only).
_FINAL_MEDIA_ID_RE = re.compile(r"^final_[A-Za-z0-9_]+$")


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
        or asset.get("url")
        or asset.get("image_url")
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
                out.append({
                    "media_id": mid,
                    "delivery_media_id": gi.get("mediaId") or mid,
                    "url": gi.get("fifeUrl"),
                })
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


_UNCORRELATED_WARNING = (
    "UNCORRELATED_DIAGNOSTIC: this media was taken from the Flow tab with no identity check and may belong to an older or unrelated run — it is NOT proof of any job's output and must never be registered as one.")


@router.get("/harvest-video")
async def harvest_video():
    """DIAGNOSTIC ONLY — download the first finished video URL visible in the Flow tab.

    This performs NO output correlation. It takes whatever media the tab exposes,
    which on a project with history is very often OLDER media from an unrelated
    run (live: a hand-call against a dirty project returned an r2v clip while the
    job under investigation was text-only T2V). It cannot know which job a clip
    belongs to and it registers nothing.

    It is NOT the retrieval path. Job output binding goes through
    make_video._accept_correlated_output, which matches candidates against the
    submission's identity anchors and refuses foreign media. Never present this
    endpoint's output as a job's artifact — every response is tagged
    correlated=false to make that impossible to miss.
    """
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
                    "local_path": str(vpath), "size_mb": round(len(vbytes) / 1024 / 1024, 2),
                    "correlated": False, "warning": _UNCORRELATED_WARNING}
        url = _find_gcs_url(mdata)
    if not url:
        return {"ok": False, "urls": [], "media_ids": media_ids, "diag": inner,
                "correlated": False, "warning": _UNCORRELATED_WARNING,
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
            "found": len(urls),
            "correlated": False, "warning": _UNCORRELATED_WARNING}


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
    # Product identity is resolved server-side.  It is a lineage key, never a
    # client-authorized image path/hash or truth status.
    product_id: Optional[str] = None
    visual_lane_id: Optional[str] = None
    source_mode: Optional[str] = None       # HYBRID | FRAMES | INGREDIENTS
    workspace_execution_package_id: Optional[str] = None
    image_media_ids: Optional[list] = None     # existing/uploaded refs (I2V/F2V)
    image_prompt: Optional[str] = None         # auto start-frame if no refs (I2V/F2V)
    aspect: str = "9:16"
    model: Optional[str] = None                # video model (ui_label or key); default Veo 3.1 - Lite
    image_model: Optional[str] = None          # IMG image model key/ui_label; default Nano Banana Pro
    duration_s: Optional[int] = None           # default = the model's default duration
    count: int = 1                             # USER count setting (1-4): negotiate AND retrieve N videos
    # Non-UI callers (Montage / bulk / queue / scheduler) firing an ALREADY
    # human-approved multi-op run set this to the run's APPROVED Generation
    # Manifest id. The dispatch boundary RESOLVES the approved manifest item whose
    # execution-envelope hash matches — it never manufactures approval. UI callers
    # leave it None; they create + approve their own explicit review snapshot.
    manifest_id: Optional[str] = None
    manifest_item_key: Optional[str] = None
    # IMG WYSIWYG: when true, ``prompt`` is the human-APPROVED final provider-ready
    # prompt (product-truth grounding already applied server-side during review via
    # /api/execution-approval/prepare). The IMG gate still resolves product assets
    # but does NOT re-ground the prompt — what the operator approved is dispatched
    # EXACT (contract: no post-approval grounding rewrite).
    final_prompt_pre_approved: bool = False
    refs: Optional[dict] = None
    startAsset: Optional[dict] = None
    endAsset: Optional[dict] = None             # optional F2V end frame
    # Operator-surface capability declaration (Step-1). When `engine` is present
    # with SINGLE generation_mode, the tuple is validated fail-closed against the
    # capability matrix. Bare programmatic callers omit these and keep the
    # registry-only validation lane (ADR-007 transport truth).
    engine: Optional[str] = None
    generation_mode: Optional[str] = None
    capability_matrix_version: Optional[str] = None
    # Creative Campaign contract.  These fields are ignored by the proven
    # video lanes and are required only when the opt-in creative IMG lane is
    # explicitly enabled and bounded.
    image_contract_version: Optional[str] = None
    reference_pack_id: Optional[str] = None
    poster_copy_set_id: Optional[str] = None
    output_intent: Optional[str] = None
    creative_mode: Optional[str] = None
    confirm_live_credit_burn: bool = False
    maximum_provider_operations: Optional[int] = None
    max_retry_operations: int = 0
    copy_v2_context: Optional[dict] = None
    # Faceless V1: server-persisted actor/opening/choreography/product identity.
    # The generate route compares this receipt with the referenced workspace
    # execution package before any provider-adjacent work begins.
    execution_identity: Optional[dict[str, Any]] = None


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
# then product, subject, scene, style, image. Single source of truth for both the
# one-door /generate lane and the manual lane (was duplicated inline in each).
REF_SLOT_ORDER: tuple[tuple[str, str], ...] = (
    ("productAsset", "Product"),
    ("productLabelAsset", "ProductLabel"),
    ("productLogoAsset", "ProductLogo"),
    ("productScaleAsset", "ProductScale"),
    ("productCutoutAsset", "ProductCutout"),
    ("subjectAsset", "Subject"),
    ("sceneAsset", "Scene"),
    ("styleAsset", "Style"),
    ("imageAsset", "Image"),
)


def ordered_ref_slots(start_asset, refs, end_asset=None) -> list[tuple[str, dict]]:
    """Return the ORDERED [(slot_label, asset_dict), ...] the execution lane will
    upload, WITHOUT resolving/uploading anything — startAsset first, then the
    F2V END frame (previously materialized but silently DROPPED here — a 2-image
    frames job lost its user-selected end frame), then subject, scene, style,
    image. Pure and deterministic: this is the dry-run proof seam for
    execution-payload reference ordering (no live Flow upload).
    """
    slots: list[tuple[str, dict]] = []
    if isinstance(start_asset, dict) and start_asset:
        slots.append(("Start", start_asset))
    if isinstance(end_asset, dict) and end_asset:
        slots.append(("End", end_asset))
    if isinstance(refs, dict):
        for ref_key, slot_label in REF_SLOT_ORDER:
            asset = refs.get(ref_key)
            if isinstance(asset, dict) and asset:
                slots.append((slot_label, asset))
    return slots


_BLOCK_HEADER_MARKER = "SECTION 1 - ROLE & OBJECTIVE"


def _is_multi_block_prompt(prompt: str) -> bool:
    """True when a prompt carries MORE THAN ONE compiled 9-section block.

    One generation = ONE block. Submitting the full multi-block compiled document
    (`final_compiled_prompt_text`) makes the Flow agent propose one generation per
    block (live incident: 2 blocks → '2 video generations, 30 credits' → the
    count-mismatch steer → the agent dropped the reference image and compressed
    both blocks' dialogue into one clip). Block 2+ text belongs to the native
    Extend step on the FINISHED video 1, never to the initial submission.
    """
    return (prompt or "").count(_BLOCK_HEADER_MARKER) > 1


async def _provider_safety_stale_prompt_error(
    product_id: str | None,
    prompt: str,
) -> str | None:
    """Fail closed on an old package that still carries a known creator byline.

    New packages are normalized by the canonical compiler.  This zero-credit guard
    protects already-persisted packages at the final API boundary so deploying the
    fix cannot accidentally resend the exact prompt Google already rejected.
    """
    normalized_product_id = str(product_id or "").strip()
    if not normalized_product_id:
        return None
    product = await crud.get_product(normalized_product_id)
    if not product:
        return None
    from agent.services.ugc_video_prompt_compiler_service import _provider_safe_product

    _projected, safety = _provider_safe_product(product)
    original = str(safety.get("original_name") or "").strip()
    if (
        safety.get("applied")
        and original
        and original.casefold() in str(prompt or "").casefold()
    ):
        return "ERR_PROVIDER_SAFETY_PACKAGE_STALE_RECOMPILE_REQUIRED"
    return None


def _is_product_reference_asset(
    asset: object,
    slot_key: str,
    *,
    product_id: str,
    product: dict[str, Any],
) -> bool:
    """Identify product bytes before the provider reference list is built."""
    normalized_slot = str(slot_key or "").lower()
    if normalized_slot in {
        "productasset",
        "productreference",
        "productcutoutasset",
        "productlabelasset",
        "productlogoasset",
        "productscaleasset",
    }:
        return True
    if not isinstance(asset, dict):
        return False
    asset_product_id = str(asset.get("productId") or asset.get("product_id") or "")
    role = str(asset.get("semanticRole") or asset.get("semantic_role") or "").upper()
    source = str(asset.get("assetSource") or asset.get("asset_source") or "").upper()
    if asset_product_id == product_id or role == "PRODUCT_REFERENCE":
        return True
    if source.startswith(("PRODUCT_IMAGE", "PRODUCT_VISUAL", "PRODUCT_TRUTH", "PRODUCT_REFERENCE_PACK")):
        return True

    # Older dashboard payloads did not carry productId/semanticRole.  Match
    # their row-owned paths/URLs so a stale catalog image cannot survive merely
    # because it used the generic subjectAsset key.
    row_values = {
        str(product.get("media_id") or "").strip(),
        str(product.get("local_image_path") or "").strip(),
        str(product.get("image_url") or "").strip(),
    }
    asset_values = {
        str(asset.get("mediaId") or asset.get("media_id") or "").strip(),
        str(asset.get("localFilePath") or asset.get("local_file_path") or "").strip(),
        str(asset.get("downloadUrl") or asset.get("download_url") or asset.get("image_url") or "").strip(),
    }
    return bool((row_values - {""}) & (asset_values - {""}))


async def _apply_img_product_truth_gate(
    *, product_id: str, visual_lane_id: str | None, prompt: str,
    request_refs: dict[str, Any], start_asset: object = None,
    reference_pack_id: str | None = None, creative_mode: str | None = None,
) -> tuple[str, dict[str, Any], bool]:
    """Apply the server product resolver to every API-first IMG entry point.

    ``/generate`` and the workspace compatibility wrapper both feed the same
    provider lane. Keeping this gate at the shared seam prevents the workspace
    path from silently uploading a stale/client-selected product reference.
    """
    from agent.services.exact_product_compositor_service import (
        ExactProductCompositeError,
        augment_prompt_scene_only,
        validate_canonical_or_raise,
    )
    from agent.services.product_visual_grounding_resolver import (
        ProductTruthLockRequiredError,
        ProductVisualReferenceRequiredError,
        resolve_generation_strategy,
        resolve_product_visual_grounding,
    )

    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(404, f"PRODUCT_NOT_FOUND: {product_id}")
    refs = dict(request_refs or {})
    lane = (visual_lane_id or "").upper()
    creative_lane = (
        lane == "POSTER_BUILDER_CREATIVE_CAMPAIGN"
        or str(creative_mode or "").upper() == "CREATIVE_CAMPAIGN"
    )
    if creative_lane:
        from agent import config
        from agent.services.product_reference_pack_service import (
            ProductReferencePackError,
            ensure_product_reference_pack,
            get_reference_pack,
        )

        if not config.CREATIVE_CAMPAIGN_POSTER_ENABLED:
            raise HTTPException(409, "CREATIVE_CAMPAIGN_FEATURE_DISABLED")
        pack = await get_reference_pack(product_id)
        if pack is None:
            try:
                pack = await ensure_product_reference_pack(product_id)
            except ProductReferencePackError as exc:
                raise HTTPException(422, f"{exc.code}: {exc.message}") from exc
        if reference_pack_id and reference_pack_id != pack.pack_id:
            raise HTTPException(422, "REFERENCE_PACK_ID_MISMATCH")
        try:
            # Approval and every bound byte are checked before any Flow upload.
            from agent.services.product_reference_pack_service import transport_reference_ids

            transport_reference_ids(pack)
        except ProductReferencePackError as exc:
            raise HTTPException(422, f"{exc.code}: {exc.message}") from exc
        # The pack remains an approval/evidence gate, but its product images
        # are not provider references.  Product Registration owns the one
        # image that reaches generation, so a pack's canonical/label/logo/
        # scale/cutout roles cannot reintroduce cosmetic pixels.
        from agent.services.product_visual_grounding_resolver import (
            ProductVisualReferenceRequiredError,
            build_official_product_visual_asset,
        )

        try:
            official = build_official_product_visual_asset(
                product,
                slot_key="productAsset",
                label="Official product visual",
            )
        except ProductVisualReferenceRequiredError as exc:
            raise HTTPException(422, str(exc)) from exc

        bound_refs: dict[str, Any] = {
            "productAsset": {
                "productId": product_id,
                "mediaId": official.get("media_id"),
                "localFilePath": official.get("local_file_path"),
                "downloadUrl": official.get("download_url") or official.get("preview_url"),
                "previewUrl": official.get("preview_url"),
                "fileName": official.get("file_name"),
                "semanticRole": "PRODUCT_REFERENCE",
                "assetSource": official.get("asset_source"),
                "officialVisual": True,
                "officialVisualSha256": official.get("official_visual_sha256"),
            },
        }
        role_slots = {
            "PRODUCT_CANONICAL": "productAsset",
            "PRODUCT_LABEL_CROP": "productLabelAsset",
            "PRODUCT_LOGO_CROP": "productLogoAsset",
            "PRODUCT_SCALE_EVIDENCE": "productScaleAsset",
            "PRODUCT_CUTOUT": "productCutoutAsset",
        }
        # Optional approved character/scene/style references remain operator
        # controls. Deny both Product Reference Pack role names and the
        # concrete product slot keys so a client cannot overwrite the official
        # visual after this server binding.
        product_reference_keys = set(role_slots.values()) | {
            "productAsset",
            "product_asset",
            "productReference",
            "product_reference",
            "subjectAsset",
            "subject_asset",
            "startAsset",
            "start_asset",
        }
        for key, asset in refs.items():
            if (
                key not in product_reference_keys
                and not _is_product_reference_asset(
                    asset,
                    key,
                    product_id=product_id,
                    product=product,
                )
                and isinstance(asset, dict)
            ):
                bound_refs[key] = asset
        return prompt, bound_refs, False
    has_avatar = bool(
        refs.get("characterAsset")
        or refs.get("avatarAsset")
        or any(token in lane for token in ("AVATAR", "UGC", "MODEL", "HYBRID"))
    )
    is_poster = "POSTER" in lane
    is_product_only = "PRODUCT_ONLY" in lane or ("HERO" in lane and not has_avatar)
    strategy = resolve_generation_strategy(
        lane_id=visual_lane_id,
        product_id=product_id,
        has_avatar=has_avatar,
        is_product_only=is_product_only,
        is_poster=is_poster,
    )
    exact_strategy = strategy in (
        "PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE",
        "FIXED_HERO_POSTER",
    )

    if exact_strategy:
        exact_product = dict(product)
        exact_product["_exact_product_required"] = True
        try:
            validate_canonical_or_raise(exact_product)
        except ExactProductCompositeError as exc:
            raise HTTPException(exc.status_code, f"{exc.code}: {exc.message}") from exc
        if any(
            _is_product_reference_asset(
                asset,
                slot_key,
                product_id=product_id,
                product=product,
            )
            for slot_key, asset in refs.items()
        ) or _is_product_reference_asset(
            start_asset,
            "startAsset",
            product_id=product_id,
            product=product,
        ):
            raise HTTPException(
                422,
                "PRODUCT_REFERENCE_FORBIDDEN_EXACT_MODE: exact IMG sends a scene-only plate; the immutable product is inserted after Flow.",
            )
        return augment_prompt_scene_only(prompt), refs, True

    try:
        grounded = resolve_product_visual_grounding(
            product_id,
            lane_id=visual_lane_id,
            has_avatar=has_avatar,
            is_product_only=is_product_only,
            is_poster=is_poster,
        )
    except (ProductVisualReferenceRequiredError, ProductTruthLockRequiredError) as exc:
        code = getattr(exc, "code", "PRODUCT_VISUAL_REFERENCE_REQUIRED")
        raise HTTPException(422, f"{code}: {exc}") from exc

    # Remove every client-selected product asset, then bind the resolver's
    # server-owned bytes in the canonical product slot. Human/avatar lanes stay
    # reference-conditioned and therefore remain PENDING_REVIEW downstream.
    refs = {
        key: asset
        for key, asset in refs.items()
        if not _is_product_reference_asset(
            asset,
            key,
            product_id=product_id,
            product=product,
        )
    }
    product_ref = grounded.product_reference
    refs["productAsset"] = {
        "productId": product_id,
        "mediaId": product_ref.get("media_id"),
        "localFilePath": product_ref.get("local_path"),
        "downloadUrl": product_ref.get("image_url"),
        "fileName": f"{product_id}_product_reference",
        "semanticRole": "PRODUCT_REFERENCE",
        "assetSource": (
            "PRODUCT_VISUAL_OFFICIAL_CUTOUT"
            if product_ref.get("source_type") == "PRODUCT_TRUTH_LOCK_CUTOUT"
            else "PRODUCT_VISUAL_OFFICIAL_SOURCE"
            if product_ref.get("source_type") == "PRODUCT_TRUTH_LOCK"
            else "PRODUCT_DATABASE_RECORD"
        ),
        "officialVisual": True,
        "officialVisualSha256": product_ref.get("sha256"),
    }
    return prompt, refs, False


async def _apply_video_product_visual_gate(
    *,
    product_id: str,
    mode: str,
    source_mode: str | None,
    request_refs: dict[str, Any],
    start_asset: object = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
    """Bind the Product Registration visual at the API-first video seam.

    HYBRID (the default F2V product lane) gets exactly the selected official
    product visual as its start anchor. I2V gets that same visual in
    ``productAsset`` while character/scene/style references remain independent.
    FRAMES is the explicit finished-frame continuation lane and is therefore
    allowed to keep its operator-selected frame.
    """
    normalized_mode = str(mode or "").upper()
    normalized_source = str(source_mode or "").upper()
    if normalized_mode not in {"F2V", "I2V"} or (
        normalized_mode == "F2V" and normalized_source == "FRAMES"
    ):
        return (
            dict(start_asset) if isinstance(start_asset, dict) else None,
            dict(request_refs or {}),
            False,
        )

    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(404, f"PRODUCT_NOT_FOUND: {product_id}")
    from agent.services.product_visual_grounding_resolver import (
        ProductVisualReferenceRequiredError,
        build_official_product_visual_asset,
    )

    try:
        official = build_official_product_visual_asset(
            product,
            slot_key="start_frame" if normalized_mode == "F2V" else "subject",
            label="Official product visual",
        )
    except ProductVisualReferenceRequiredError as exc:
        raise HTTPException(422, str(exc)) from exc

    provider_asset = {
        "productId": product_id,
        "mediaId": official.get("media_id"),
        "localFilePath": official.get("local_file_path"),
        "downloadUrl": official.get("download_url") or official.get("preview_url"),
        "previewUrl": official.get("preview_url"),
        "fileName": official.get("file_name"),
        "semanticRole": "PRODUCT_REFERENCE",
        "assetSource": official.get("asset_source"),
        "officialVisual": True,
        "officialVisualSha256": official.get("official_visual_sha256"),
    }
    refs = {
        key: asset
        for key, asset in dict(request_refs or {}).items()
        if not _is_product_reference_asset(
            asset,
            key,
            product_id=product_id,
            product=product,
        )
    }
    if normalized_mode == "F2V":
        # HYBRID has one product anchor, never a second client-selected image.
        return provider_asset, {}, True
    refs["productAsset"] = provider_asset
    return None, refs, True


async def _effective_video_source_mode(
    source_mode: str | None,
    workspace_execution_package_id: str | None,
) -> str | None:
    """Resolve the source lane before product-image authority is applied.

    Direct callers may omit ``source_mode`` while still sending a persisted
    execution package.  In that case HYBRID must not be guessed for a compiled
    FRAMES package; the package lineage is the server-owned authority.
    """
    from agent.services import flow_mode_reference_contract as _refc

    declared = _refc.normalize_source_mode(source_mode)
    if declared:
        return declared
    package_id = str(workspace_execution_package_id or "").strip()
    if package_id:
        package = await crud.get_workspace_execution_package(package_id)
        derived = _refc.derive_package_source_mode(package)
        if derived:
            return derived
    return source_mode


async def _run_creative_campaign_pre_provider_lint(
    *,
    product_id: str,
    poster_copy_set_id: str | None,
    copy_v2_resolution: object | None = None,
    prompt: str,
    image_model: str | None,
    output_intent: str | None,
    maximum_provider_operations: int | None,
    max_retry_operations: int,
) -> None:
    """Run the typed Campaign gate immediately before the provider boundary.

    The Poster Prompt Draft endpoint is a useful earlier check, but it is not
    the final transport authority. This read-only gate re-resolves the approved
    V2 binding (or the maintenance-only historical copy set), campaign brief
    and reference pack at the same request boundary so a stale or hand-crafted
    IMG payload cannot bypass Campaign governance.
    """
    from agent import config
    from agent.services.poster_campaign_design_service import (
        build_campaign_design_brief,
        score_campaign_copy_route,
    )
    from agent.services.poster_campaign_qa_service import build_pre_provider_lint
    from agent.services.product_reference_pack_service import get_reference_pack

    copy_id = str(poster_copy_set_id or "").strip()
    if not legacy_copy_maintenance_enabled():
        if copy_id:
            raise HTTPException(410, "LEGACY_POSTER_COPY_INPUT_DISABLED")
        resolution = copy_v2_resolution
        binding = getattr(resolution, "binding", None)
        projection = getattr(resolution, "projection", None)
        derived = getattr(projection, "derived_copy", None)
        if binding is None or derived is None or getattr(resolution, "lane", "") != "POSTER_BUILDER":
            raise HTTPException(409, "COPY_V2_POSTER_BINDING_REQUIRED")
        copy_id = str(binding.binding_id)
        copy_set = {
            "objective": "Product Hero",
            "angle": str(getattr(derived, "hook", "") or ""),
            "primary_message": str(getattr(derived, "hook", "") or ""),
            "support_message": str(getattr(derived, "body", "") or ""),
            "proof_points": [str(getattr(derived, "body", "") or "")],
            "cta": str(getattr(derived, "cta", "") or ""),
            "campaign_copy_route_id": copy_id,
        }
    else:
        from agent.models.poster_copy_set import (
            STATUS_POSTER_COPY_APPROVED,
            serialize_poster_copy_set,
        )

        if not copy_id:
            raise HTTPException(422, "POSTER_COPY_SET_REQUIRED_FOR_CREATIVE_CAMPAIGN")
        copy_row = await crud.get_poster_copy_set(copy_id)
        if not copy_row:
            raise HTTPException(404, "POSTER_COPY_SET_NOT_FOUND")
        if str(copy_row.get("product_id") or "").strip() != str(product_id).strip():
            raise HTTPException(422, "POSTER_COPY_SET_PRODUCT_MISMATCH")
        if copy_row.get("status") != STATUS_POSTER_COPY_APPROVED:
            raise HTTPException(409, "POSTER_COPY_SET_APPROVAL_REQUIRED")
        copy_set = serialize_poster_copy_set(copy_row)
    brief = await build_campaign_design_brief(
        product_id,
        objective=str(copy_set.get("objective") or "Product Hero"),
        selected_angle=str(copy_set.get("angle") or ""),
        copy_layout={
            "primary_message": str(copy_set.get("primary_message") or ""),
            "support_message": str(copy_set.get("support_message") or ""),
            "cta": str(copy_set.get("cta") or ""),
        },
    )
    candidate = {
        "route_id": str(copy_set.get("campaign_copy_route_id") or copy_id),
        "singular_proposition": str(copy_set.get("angle") or ""),
        "primary_message": str(copy_set.get("primary_message") or ""),
        "support_message": str(copy_set.get("support_message") or ""),
        "approved_proof_points": list(copy_set.get("proof_points") or []),
        "cta": str(copy_set.get("cta") or ""),
    }
    score, rejected_reasons = score_campaign_copy_route(candidate, brief)
    candidate["score"] = score.model_dump(mode="json")
    candidate["production_eligible"] = (
        not rejected_reasons
        and score.total >= 72
        and not brief.missing_field_blockers
    )
    lint = build_pre_provider_lint(
        product_id=product_id,
        reference_pack=await get_reference_pack(product_id),
        brief=brief,
        candidate=candidate,
        compiled_prompt=prompt,
        model=image_model or "NANO_BANANA_PRO",
        output_intent=output_intent or "",
        max_provider_operations=maximum_provider_operations or 0,
        max_retry_operations=max_retry_operations,
        live=True,
        feature_enabled=config.CREATIVE_CAMPAIGN_POSTER_ENABLED,
        live_authorized=config.CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZED,
    )
    if not lint.allowed:
        raise HTTPException(
            422,
            "CAMPAIGN_PRE_PROVIDER_LINT_BLOCKED:" + "|".join(lint.blockers),
        )


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
    if body.execution_identity is not None:
        if (
            not isinstance(body.execution_identity, dict)
            or str(body.execution_identity.get("lane") or "").upper() != "FACELESS"
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "FACELESS_EXECUTION_IDENTITY_INVALID",
                    "detail": "Execution identity is reserved for the Faceless lane.",
                },
            )
        if not body.workspace_execution_package_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "FACELESS_EXECUTION_IDENTITY_REQUIRED",
                    "detail": "The Faceless execution identity must reference its prepared package.",
                },
            )
    _package = None
    _package_lineage: dict[str, Any] = {}
    _package_exact_route = False
    _package_exact_custody: dict[str, Any] | None = None
    # Faceless packages carry a server-authoritative receipt that binds the exact
    # product anchor, actor resolution, opening truth decision, choreography, and
    # provider settings reviewed by the operator. Resolve it before Copy V2,
    # connectivity, asset transport, credits, or the dispatch approval gate.
    if mode in ("F2V", "T2V") and body.workspace_execution_package_id:
        _package = await crud.get_workspace_execution_package(
            body.workspace_execution_package_id
        )
        if _package is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "FACELESS_EXECUTION_IDENTITY_REQUIRED",
                    "detail": "The Faceless workspace execution package was not found.",
                },
            )
        _lineage = _package.get("request_lineage_payload") or {}
        if isinstance(_lineage, str):
            try:
                _lineage = json.loads(_lineage)
            except (TypeError, ValueError):
                _lineage = {}
        if isinstance(_lineage, dict):
            _package_lineage = _lineage
            _package_exact_custody = _lineage.get("product_visual_custody")
            _faceless_lineage = _lineage.get("faceless_resolution") or {}
            _exact_plan = (
                _faceless_lineage.get("exact_product_video")
                if isinstance(_faceless_lineage, dict)
                else None
            ) or _lineage.get("exact_product_video")
            _package_exact_route = bool(
                isinstance(_package_exact_custody, dict)
                and _package_exact_custody.get("provider_route")
                == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
            ) or bool(
                isinstance(_exact_plan, dict)
                and _exact_plan.get("selected_execution_route")
                == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
            )
            if _package_exact_route:
                expected_product_id = str(
                    _lineage.get("product_id")
                    or (_package_exact_custody or {}).get("product_id")
                    or ""
                ).strip()
                if not expected_product_id or str(body.product_id or "").strip() != expected_product_id:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "EXACT_PRODUCT_PACKAGE_PRODUCT_MISMATCH",
                            "detail": "Exact Product Truth package and generate product_id must match.",
                            "package_product_id": expected_product_id,
                            "request_product_id": body.product_id,
                        },
                    )
                if mode != "T2V":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "EXACT_PRODUCT_ROUTE_MODE_INVALID",
                            "detail": "Exact Faceless product packages dispatch only as a text-only scene scaffold (T2V).",
                        },
                    )
                if str(body.source_mode or "").strip().upper() not in {"", "T2V"}:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "EXACT_PRODUCT_SOURCE_MODE_INVALID",
                            "detail": "Exact deterministic composite requires T2V scene-scaffold lineage.",
                        },
                    )
                if body.image_media_ids or body.refs or body.startAsset or body.endAsset:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error": "EXACT_PRODUCT_PROVIDER_REFERENCE_FORBIDDEN",
                            "detail": "Exact Product Truth is inserted server-side; provider product/reference media are forbidden.",
                        },
                    )
        _expected_identity = (
            _package.get("faceless_execution_identity")
            or (
                _lineage.get("faceless_execution_identity")
                if isinstance(_lineage, dict)
                else None
            )
        )
        if _expected_identity is not None:
            if body.execution_identity is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "FACELESS_EXECUTION_IDENTITY_REQUIRED",
                        "detail": "The persisted Faceless execution identity is required for dispatch.",
                    },
                )
            if json.dumps(
                body.execution_identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ) != json.dumps(
                _expected_identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "FACELESS_EXECUTION_IDENTITY_MISMATCH",
                        "detail": "The Faceless execution identity no longer matches the prepared package.",
                    },
                )
    v2_resolution = None
    try:
        from agent.services.copy_execution_resolver import (
            CopyExecutionResolutionError,
            lane_for_request,
            resolve_persisted_copy_execution_binding,
        )

        requested_v2_lane = str((body.copy_v2_context or {}).get("lane") or "")
        v2_resolution = await resolve_persisted_copy_execution_binding(
            body.product_id or "request-product",
            requested_v2_lane
            or lane_for_request(
                mode,
                source_mode=body.source_mode,
                visual_lane_id=body.visual_lane_id,
            ),
            body.copy_v2_context,
        )
    except CopyExecutionResolutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.details or str(exc)},
        ) from exc
    if _is_multi_block_prompt(body.prompt):
        raise HTTPException(
            422, "MULTI_BLOCK_PROMPT_REJECTED: one generation carries ONE block's "
            "prompt; block 2+ text belongs to the Extend step on the finished video")
    if mode in ("T2V", "I2V", "F2V"):
        stale_prompt_error = await _provider_safety_stale_prompt_error(
            body.product_id,
            body.prompt,
        )
        if stale_prompt_error:
            raise HTTPException(409, stale_prompt_error)

    generation_prompt = body.prompt
    request_refs = dict(body.refs or {})
    effective_start_asset = body.startAsset
    exact_img = False
    drop_legacy_video_media_ids = False
    creative_campaign = mode == "IMG" and (
        (body.visual_lane_id or "").upper() == "POSTER_BUILDER_CREATIVE_CAMPAIGN"
        or (body.creative_mode or "").upper() == "CREATIVE_CAMPAIGN"
    )
    if creative_campaign:
        from agent import config
        if not config.CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZED:
            raise HTTPException(403, "CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZATION_REQUIRED")
        if not body.product_id:
            raise HTTPException(422, "CREATIVE_CAMPAIGN_PRODUCT_ID_REQUIRED")
        if not body.confirm_live_credit_burn:
            raise HTTPException(409, "IMAGE_LIVE_CREDIT_CONFIRMATION_REQUIRED")
        if body.image_contract_version != "image_prompt_compiler_v1":
            raise HTTPException(422, "IMAGE_CONTRACT_VERSION_REQUIRED")
        if body.max_retry_operations != 0:
            raise HTTPException(422, "HIDDEN_RETRY_DISABLED_FOR_CREATIVE_CAMPAIGN")
        if int(body.count) < 1 or int(body.count) > 3:
            raise HTTPException(422, "CREATIVE_CAMPAIGN_MAX_THREE_VARIANTS")
        expected_operations = max(1, int(body.count)) + body.max_retry_operations
        if body.maximum_provider_operations != expected_operations:
            raise HTTPException(422, "PROVIDER_OPERATION_BUDGET_MISMATCH")
        if (body.output_intent or "").upper() != "CLEAN_KEY_VISUAL":
            raise HTTPException(
                422,
                "CREATIVE_CAMPAIGN_CLEAN_KEY_VISUAL_REQUIRED",
            )
        requested_image_model = (body.image_model or "NANO_BANANA_PRO").upper()
        if requested_image_model != "NANO_BANANA_PRO":
            raise HTTPException(
                422,
                "CREATIVE_CAMPAIGN_FINAL_MODEL_REQUIRED:NANO_BANANA_PRO",
            )
    if mode == "IMG" and body.product_id:
        # Product-aware IMG requests pass this server gate before extension
        # connectivity or provider work. The workspace wrapper calls the same
        # helper so both routes have identical product-byte authority.
        generation_prompt, request_refs, exact_img = await _apply_img_product_truth_gate(
            product_id=body.product_id,
            visual_lane_id=body.visual_lane_id,
            prompt=body.prompt,
            request_refs=request_refs,
            start_asset=body.startAsset,
            reference_pack_id=body.reference_pack_id,
            creative_mode=body.creative_mode,
        )
        if body.final_prompt_pre_approved:
            # The prompt was grounded server-side BEFORE human review (/prepare) and
            # approved. Keep asset resolution above, but dispatch the approved text
            # VERBATIM — never re-ground an approved prompt (no post-approval rewrite).
            generation_prompt = body.prompt
        if not exact_img:
            # Product-aware IMG lanes accept typed refs only.  A legacy
            # startAsset is untyped transport and could be the old catalog
            # image (or a cosmetic composition), so the server-owned
            # productAsset above is the sole product input.
            effective_start_asset = None
        if creative_campaign:
            await _run_creative_campaign_pre_provider_lint(
                product_id=body.product_id,
                poster_copy_set_id=body.poster_copy_set_id,
                copy_v2_resolution=v2_resolution,
                prompt=generation_prompt,
                image_model=body.image_model,
                output_intent=body.output_intent,
                maximum_provider_operations=body.maximum_provider_operations,
                max_retry_operations=body.max_retry_operations,
            )
    if _package_exact_route:
        # Exact Faceless uses a text-only provider scene scaffold.  The
        # canonical product asset never enters refs/startAsset and is carried
        # only as server-side custody for deterministic final compositing.
        effective_source_mode = "T2V"
        effective_start_asset = None
        request_refs = {}
        drop_legacy_video_media_ids = True
    elif mode in ("I2V", "F2V") and body.product_id:
        effective_source_mode = await _effective_video_source_mode(
            body.source_mode,
            body.workspace_execution_package_id,
        )
        (
            effective_start_asset,
            request_refs,
            drop_legacy_video_media_ids,
        ) = await _apply_video_product_visual_gate(
            product_id=body.product_id,
            mode=mode,
            source_mode=effective_source_mode,
            request_refs=request_refs,
            start_asset=body.startAsset,
        )
    else:
        effective_source_mode = body.source_mode

    product_visual_custody = (
        copy.deepcopy(_package_exact_custody)
        if _package_exact_route and isinstance(_package_exact_custody, dict)
        else None
    )
    if (
        mode in ("I2V", "F2V")
        and body.product_id
        and effective_source_mode != "FRAMES"
    ):
        from agent.services.product_visual_custody_service import (
            ProductVisualCustodyError,
            build_product_visual_custody_receipt,
            exact_product_required,
            validate_pre_dispatch_route,
        )

        product_row = await crud.get_product(str(body.product_id))
        official_asset = (
            effective_start_asset
            if isinstance(effective_start_asset, dict)
            else (request_refs.get("productAsset") if isinstance(request_refs, dict) else None)
        )
        try:
            if not product_row:
                raise ProductVisualCustodyError(
                    "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                    "The product row is unavailable for product-visual custody.",
                )
            product_visual_custody = build_product_visual_custody_receipt(
                product_row,
                official_asset,
                mode=mode,
                source_mode=effective_source_mode,
                prompt=body.prompt,
                provider_route="API_FIRST_GENERATIVE_REFERENCE",
                generation_type="reference_frame_2_video",
                execution_identity=body.execution_identity,
            )
            validate_pre_dispatch_route(
                product_visual_custody,
                provider_route="API_FIRST_GENERATIVE_REFERENCE",
                generation_type=product_visual_custody["generation_type"],
            )
            if (
                exact_product_required(product_row)
                and not product_visual_custody["prompt_lock"].get(
                    "all_required_markers_present"
                )
            ):
                raise ProductVisualCustodyError(
                    "ERR_PRODUCT_PROMPT_LOCK_INCOMPLETE",
                    "Exact-product video prompt is missing one or more required Product Lock sections.",
                )
        except ProductVisualCustodyError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": exc.code,
                    "message": exc.message,
                    "details": {
                        **(exc.details or {}),
                        "product_visual_custody": product_visual_custody,
                    },
                },
            ) from exc
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
        import os
        if os.environ.get("ENABLE_MOCK_FLOW") == "1" or os.environ.get("UAT_TEST_MODE") == "1":
            client._mock_connected = True
        else:
            raise HTTPException(503, "Extension not connected")

    # Resolve visual assets from refs / startAsset to live Flow media IDs, in the
    # canonical slot order (startAsset, subject, scene, style, image). IMG and
    # product-aware video lanes have already been normalized through the
    # Product Registration authority above; FRAMES keeps its explicit frame IDs.
    resolved_ids = (
        []
        if mode == "IMG" or drop_legacy_video_media_ids
        else list(body.image_media_ids or [])
    )
    official_provider_media_id = None
    for slot_label, ref_asset in ordered_ref_slots(
        effective_start_asset, request_refs, end_asset=body.endAsset
    ):
        media_id = await _resolve_asset_to_media_id(client, ref_asset, slot_label)
        if media_id and media_id not in resolved_ids:
            resolved_ids.append(media_id)
        asset_source = str(
            ref_asset.get("assetSource")
            or ref_asset.get("asset_source")
            or ref_asset.get("source")
            or ""
        ).upper()
        if media_id and (
            ref_asset.get("officialVisual") is True
            or ref_asset.get("official_visual") is True
            or asset_source.startswith("PRODUCT_VISUAL_OFFICIAL")
        ):
            official_provider_media_id = str(media_id)
    if mode == "IMG" and (not body.product_id or exact_img):
        # Product-aware non-exact IMG requests deliberately do not merge the
        # caller's untyped image_media_ids.  Those IDs have no slot/lineage and
        # can reintroduce the stale product image after the official gate.
        for media_id in body.image_media_ids or []:
            if media_id and media_id not in resolved_ids:
                resolved_ids.append(media_id)

    if _package_exact_route:
        if not isinstance(product_visual_custody, dict):
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                    "message": "Exact deterministic composite package has no custody receipt.",
                },
            )
        from agent.services.product_visual_custody_service import (
            ProductVisualCustodyError,
            validate_pre_dispatch_route,
        )

        try:
            validate_pre_dispatch_route(
                product_visual_custody,
                provider_route="EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                generation_type=str(
                    product_visual_custody.get("generation_type")
                    or "scene_video_scaffold_then_deterministic_composite"
                ),
            )
        except ProductVisualCustodyError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error_code": exc.code, "message": exc.message, "details": exc.details},
            ) from exc
    elif product_visual_custody is not None:
        from agent.services.product_visual_custody_service import (
            bind_provider_reference_transport,
        )

        if not official_provider_media_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                    "message": "The official product visual did not produce an observed provider reference id.",
                },
            )
        product_visual_custody = bind_provider_reference_transport(
            product_visual_custody,
            provider_reference_media_ids=resolved_ids,
            official_provider_media_id=official_provider_media_id,
            provider_route="API_FIRST_GENERATIVE_REFERENCE",
            generation_type="reference_frame_2_video",
        )

    tier = "PAYGATE_TIER_ONE"
    if mode in ("T2V", "I2V", "F2V"):  # video modes need Pro/Ultra
        cred = await client.get_credits()
        tier = (cred.get("data", cred) or {}).get("userPaygateTier", "") if isinstance(cred, dict) else ""
        if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            raise HTTPException(500, f"Account tier '{tier}' cannot generate video — needs Pro/Ultra")
    result = await _mv.start_generate(
        mode, generation_prompt, project_id=body.project_id,
        image_media_ids=resolved_ids, image_prompt=body.image_prompt,
        aspect=body.aspect, tier=tier, model=body.model, duration_s=body.duration_s,
        num_videos=body.count, image_model=body.image_model,
        max_image_attempts=1 if creative_campaign else 8,
        collect_image_variants=creative_campaign,
        product_id=body.product_id,
        source_mode=effective_source_mode,
        product_visual_custody=product_visual_custody,
        copy_execution_binding=(
            v2_resolution.to_metadata(
                consumer_context=body.copy_v2_context
            ) if v2_resolution and v2_resolution.v2_enabled else None
        ),
        manifest_id=body.manifest_id,
        execution_identity=body.execution_identity,
    )
    if isinstance(result, dict) and result.get("status") == "REJECTED":
        # single-flight video lane busy (patch H)
        error = result.get("error") or "rejected"
        content = {
            "detail": result.get("detail") or error,
            "error": error,
            "active_job": result.get("active_job"),
        }
        if result.get("routing_receipt") is not None:
            # Keep the provider-free routing proof visible to the operator. In
            # particular, a Faceless reference request must show that it was
            # blocked before provider approval rather than silently entering the
            # text-only agent lane.
            content["routing_receipt"] = result["routing_receipt"]
        if result.get("product_visual_custody") is not None:
            content["product_visual_custody"] = result["product_visual_custody"]
        return JSONResponse(
            status_code=409,
            content=content,
        )
    if v2_resolution is not None and v2_resolution.v2_enabled:
        result["copy_architecture_v2"] = v2_resolution.to_metadata(
            consumer_context=body.copy_v2_context
        )
        if v2_resolution.binding is not None:
            result["copy_execution_binding"] = v2_resolution.binding.model_dump(mode="json")
    return result


@router.get("/generate-job/{job_id}")
async def generate_job(job_id: str):
    from agent.services import make_video as _mv
    j = _mv.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/direct-capture/recover")
async def recover_direct_capture(body: dict):
    """Recover an already-submitted direct media target without resubmitting it."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    if body.get("confirm_recovery") is not True:
        raise HTTPException(409, "DIRECT_RECOVERY_CONFIRMATION_REQUIRED")
    media_id = str(body.get("media_id") or "").strip()
    project_id = str(body.get("project_id") or "").strip()
    if not media_id or not project_id:
        raise HTTPException(422, "DIRECT_RECOVERY_TARGET_REQUIRED")
    from agent.services import make_video as _mv
    result = await _mv.start_direct_media_recovery(
        media_id=media_id,
        project_id=project_id,
        mode=body.get("mode") or "F2V",
        source_mode=body.get("source_mode") or "HYBRID",
        model_key=body.get("model_key"),
        duration_s=body.get("duration_s", 8),
        seed=body.get("seed"),
        recovery_of=body.get("recovery_of") or body.get("request_id"),
        confirm_recovery=True,
    )
    if not result.get("ok"):
        raise HTTPException(409, result.get("error") or "DIRECT_RECOVERY_REJECTED")
    return {"lane": "DIRECT_CAPTURE_RECOVERY", **result}


@router.get("/product/{product_id}/visual-grounding")
async def get_product_visual_grounding_endpoint(product_id: str):
    from agent.services.product_visual_grounding_resolver import (
        resolve_product_visual_grounding,
        ProductTruthLockRequiredError,
        ProductVisualReferenceRequiredError,
    )
    try:
        bundle = resolve_product_visual_grounding(product_id)
        return bundle.to_dict()
    except ProductVisualReferenceRequiredError as e:
        raise HTTPException(422, str(e))
    except ProductTruthLockRequiredError as e:
        raise HTTPException(422, f"{e.code}: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Error resolving visual grounding: {str(e)}")


class GroundedPayloadRequest(BaseModel):
    prompt: str = ""
    lane_id: str | None = None
    has_avatar: bool = False
    is_product_only: bool = False
    is_poster: bool = False


@router.post("/product/{product_id}/grounded-payload")
async def get_grounded_payload_endpoint(product_id: str, body: GroundedPayloadRequest):
    from agent.services.product_visual_grounding_resolver import (
        get_grounded_generation_payload,
        ProductTruthLockRequiredError,
        ProductVisualReferenceRequiredError,
    )
    try:
        payload = get_grounded_generation_payload(
            product_id,
            body.prompt,
            lane_id=body.lane_id,
            has_avatar=body.has_avatar,
            is_product_only=body.is_product_only,
            is_poster=body.is_poster,
        )
        return payload
    except ProductVisualReferenceRequiredError as e:
        raise HTTPException(422, str(e))
    except ProductTruthLockRequiredError as e:
        raise HTTPException(422, f"{e.code}: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Error building grounded payload: {str(e)}")



ARTIFACT_RETENTION_HOURS = 48  # retention law: results auto-delete after 48h


@router.get("/artifacts")
async def list_artifacts(limit: int = 50, mode: str = None, kind: str = None):
    """System library of finished generations — newest first, for the Library
    pages. kind = video | image. Video retention is 48h and is enforced lazily
    on every listing; image artifacts remain until manual deletion.
    Each entry is playable/downloadable via /api/flow/retrieved/{media_id}."""
    from datetime import datetime, timedelta, timezone
    purged = await crud.purge_expired_artifacts(ARTIFACT_RETENTION_HOURS)
    items = await crud.list_generated_artifacts(limit=limit, mode=mode, kind=kind)
    for item in items:
        if str(item.get("artifact_kind") or "").lower() != "video":
            item["expires_at"] = None
            item["expires_in_hours"] = None
            continue
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
            "retention_hours": ARTIFACT_RETENTION_HOURS,
            "retention_policy": {"video": "48h", "image": "manual_delete"},
            "purged": purged}


@router.delete("/artifacts/{media_id}")
async def delete_image_artifact(media_id: str):
    """Manually delete one image artifact (row + local file).

    Video retention remains governed by the 48h sweep. Durable Creative Library
    assets are separate records and are not touched by this endpoint.
    """
    artifact = await crud.get_generated_artifact(media_id)
    if artifact is None:
        raise HTTPException(404, "GENERATED_ARTIFACT_NOT_FOUND")
    if str(artifact.get("artifact_kind") or "").lower() != "image":
        raise HTTPException(409, "ONLY_IMAGE_ARTIFACTS_HAVE_MANUAL_DELETE")
    return await crud.delete_generated_artifact(media_id)


@router.get("/retrieved/{media_id}")
async def get_retrieved_artifact(media_id: str):
    """Serve a retrieved artifact (mp4/jpg/png) so the dashboard can preview the
    result inline the moment a job completes — no back-button/reload hunting.

    Also serves registered exact-composite finals whose files live outside
    output/retrieved/ (e.g. output/exact-product-finals/) via generated_artifact.
    """
    from fastapi.responses import FileResponse
    from agent.config import OUTPUT_DIR
    from agent.db import crud as _crud
    mid = str(media_id or "")
    if not (_FLOW_MEDIA_UUID_RE.match(mid) or _FINAL_MEDIA_ID_RE.match(mid)):
        raise HTTPException(422, "media_id must be a bare UUID or final_<job_id>")
    base = OUTPUT_DIR / "retrieved"
    for ext, mime in ((".mp4", "video/mp4"), (".jpg", "image/jpeg"), (".png", "image/png")):
        candidate = base / f"{media_id}{ext}"
        if candidate.exists():
            return FileResponse(candidate, media_type=mime)
    # Fallback: durable registered artifacts (exact composite finals, etc.)
    art = await _crud.get_generated_artifact(mid)
    if art:
        local = str(art.get("local_path") or "").strip()
        if local:
            path = Path(local)
            if path.exists() and path.is_file():
                # path must remain under OUTPUT_DIR
                try:
                    path.resolve().relative_to(OUTPUT_DIR.resolve())
                except ValueError as exc:
                    raise HTTPException(403, "artifact path outside output root") from exc
                suffix = path.suffix.lower()
                mime = {
                    ".mp4": "video/mp4",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                }.get(suffix, "application/octet-stream")
                return FileResponse(path, media_type=mime)
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


@router.post("/native-extend/materialize-approval-manifest")
async def native_extend_materialize_approval_manifest(body: ExtendRunRequest):
    """Freeze the per-block continuation prompts of a native Extend chain into an
    Approved Generation Manifest (run_ref = the package id — the key each block
    dispatch resolves against). The operator reviews + approves before /extend-run;
    each block then matches its approved item by envelope hash (GAP 4 — no generic
    Extend exemption). Provider-free: nothing is planned, submitted, or spent."""
    from agent.services import execution_approval_service as _eas
    from agent.services import google_flow_native_extend_runtime as _nx

    chain_req = _native_extend_chain_request(body, _nx)
    try:
        derived = _nx.build_extend_manifest_items(chain_req)
    except _nx.NativeExtendError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not derived["items"]:
        raise HTTPException(422, "EXTEND_NO_BLOCKS")
    return await _eas.create_manifest(
        surface="native_extend",
        run_ref=derived["run_ref"],
        logical_mode="EXTEND",
        items=derived["items"],
        created_by="operator",
    )


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


# ── Owner Phase-2: CURRENT-UI driver (targeted, kill-switched) ──────────────
class UiExtendBlockRequest(BaseModel):
    """Drive ONE Extend block through the current Flow UI (dry-run default)."""
    job_id: str
    parent_media_operation_id: str = ""
    parent_media_resource_id: str = ""
    block_index: int
    position: int
    prompt: str
    model_label: str = "Veo 3.1 - Lite"
    dry_run: bool = True
    confirm_live_credit_burn: bool = False


class UiVerifyReferencesRequest(BaseModel):
    media_ids: list
    expected_count: int


class UiDownloadProjectRequest(BaseModel):
    job_id: Optional[str] = None
    project_id: Optional[str] = None
    register: bool = True
    require_final_lineage: bool = True


class UiHybridOneProbeRequest(BaseModel):
    local_file_path: str


class UiOpenVideoProbeRequest(BaseModel):
    parent_media_resource_id: str
    expected_project_id: Optional[str] = None


@router.get("/ui-driver/state")
async def ui_driver_state():
    """Observe the current Flow UI view (zero credit, read-only)."""
    from agent.services import google_flow_ui_driver as _ui
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client.flowui_state()
    return {"enabled": _ui.ui_driver_enabled(),
            "state": res.get("result", res)}


@router.get("/ui-driver/live-media-ids")
async def ui_driver_live_media_ids():
    """Zero-credit DOM harvest of visible media ids on the active Flow tab."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client.harvest_video_urls()
    inner = res.get("result", res) if isinstance(res, dict) else {}
    diag = inner.get("diag") or inner
    ids = (
        list(diag.get("videoIds") or diag.get("mediaIds") or [])
        if isinstance(diag, dict)
        else []
    )
    return {
        "ok": True,
        "video_ids": ids,
        "project_id": diag.get("projectId") if isinstance(diag, dict) else None,
        "flow_tab_id": inner.get("flow_tab_id"),
    }


@router.post("/ui-driver/verify-references")
async def ui_driver_verify_references(body: UiVerifyReferencesRequest):
    """Reference-first visibility gate (zero credit): every reference must be
    VISIBLY present and the count must equal the mode contract."""
    from agent.services import google_flow_ui_driver as _ui
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        return await _ui.verify_references_visible(
            client, body.media_ids, body.expected_count)
    except _ui.FlowUiDriverError as exc:
        raise HTTPException(422, f"{exc.code}: {exc.detail}")


@router.post("/ui-driver/reload-flow-tab")
async def ui_driver_reload_flow_tab():
    """Reload Flow tab to pick up updated content scripts (zero credit)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client._send("RELOAD_FLOW_TAB", {}, timeout=45)
    return res.get("result", res)


@router.get("/ui-driver/composer-reference")
async def ui_driver_composer_reference():
    """Zero-credit composer container + thumbnail count from live Flow tab."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client._send("FLOWUI_COMPOSER_REFERENCE_STATE", {}, timeout=30)
    return res.get("result", res)


@router.post("/ui-driver/submit-boundary-probe")
async def ui_driver_submit_boundary_probe():
    """Reach Create control with intercept_only (zero credit)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    await client.flowui_set_composer_prompt(
        "BOSMAX Phase-2D zero-credit validation probe — not for generation")
    res = await client.flowui_submit_composer_create(
        confirm=True, intercept_only=True)
    return res.get("result", res)


@router.post("/ui-driver/clear-composer-references")
async def ui_driver_clear_composer_references():
    """Remove composer reference thumbnails via captured remove controls (zero credit)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client._send("FLOWUI_CLEAR_COMPOSER_REFERENCES", {}, timeout=60)
    return res.get("result", res)


@router.post("/ui-driver/hybrid-one-probe")
async def ui_driver_hybrid_one_probe(body: UiHybridOneProbeRequest):
    """Attach one approved local image, verify exact-one, clear, verify zero (zero credit)."""
    from agent.services import google_flow_ui_driver as _ui
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    path = body.local_file_path.strip()
    if not path:
        raise HTTPException(400, "local_file_path required")
    try:
        one = await _ui.ensure_composer_references(
            client, media_ids=[], local_file_paths=[path], expected_count=1)
        cleared = await client._send("FLOWUI_CLEAR_COMPOSER_REFERENCES", {}, timeout=60)
        zero = await _ui.verify_references_visible(client, [], 0)
        return {
            "ok": True,
            "hybrid_one": one,
            "cleared": cleared.get("result", cleared),
            "zero_after_clear": zero,
        }
    except _ui.FlowUiDriverError as exc:
        raise HTTPException(422, f"{exc.code}: {exc.detail}")


@router.post("/ui-driver/open-video-probe")
async def ui_driver_open_video_probe(body: UiOpenVideoProbeRequest):
    """Open timeline card by exact media resource ID (zero credit)."""
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    res = await client.flowui_open_video(
        body.parent_media_resource_id,
        expected_project_id=body.expected_project_id)
    return res.get("result", res)


@router.post("/ui-driver/extend-block")
async def ui_driver_extend_block(body: UiExtendBlockRequest):
    """Owner timeline-Extend for ONE block. dry_run walks to
    EXTEND_READY_TO_SUBMIT and stops (zero credit). Live requires the
    FLOW_UI_DRIVER_ENABLED kill switch AND explicit confirmation AND the
    per-block route lock shared with direct-RPC (no double submit ever)."""
    from agent.services import google_flow_ui_driver as _ui
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        return await _ui.extend_block_via_ui(
            client, job_id=body.job_id,
            parent_media_operation_id=body.parent_media_operation_id,
            parent_media_resource_id=body.parent_media_resource_id,
            block_index=body.block_index, position=body.position,
            prompt=body.prompt, model_label=body.model_label,
            confirm_live_credit_burn=body.confirm_live_credit_burn,
            dry_run=body.dry_run)
    except _ui.FlowUiDriverError as exc:
        status = 409 if exc.code in (_ui.ERR_ROUTE_LOCKED, _ui.ERR_CONFIRM,
                                     _ui.ERR_DISABLED) else 422
        raise HTTPException(status, f"{exc.code}: {exc.detail}")


@router.post("/ui-driver/download-project")
async def ui_driver_download_project(body: UiDownloadProjectRequest):
    """Owner Download Project: capture the REAL browser download, hash and
    inspect it, register honestly (ZIP = project archive). Zero credit."""
    from agent.services import google_flow_ui_driver as _ui
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    try:
        return await _ui.download_project_via_ui(
            client, job_id=body.job_id, project_id=body.project_id,
            register=body.register,
            require_final_lineage=body.require_final_lineage)
    except _ui.FlowUiDriverError as exc:
        raise HTTPException(422, f"{exc.code}: {exc.detail}")


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


class VideoJobPlanRequest(BaseModel):
    """Plan the ONE logical full-video job BEFORE any credit operation."""
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    execution_package_id: Optional[str] = None
    approved_asset_id: Optional[str] = None
    approved_asset_sha256: Optional[str] = None
    requested_total_duration_seconds: int = 16
    engine: Optional[str] = None
    model: Optional[str] = None
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    initial_prompt_fingerprint: Optional[str] = None
    execution_mode: str = "HYBRID_EXTEND"
    client_request_nonce: Optional[str] = None
    # Optional explicit authority — normally resolved server-side from the
    # execution package; supplying these skips resolution (e.g. re-plan from a
    # fully-specified reviewed plan).
    initial_mode: Optional[str] = None
    initial_asset_media_id: Optional[str] = None
    initial_reference_media_ids: Optional[list] = None
    initial_prompt_text: Optional[str] = None
    continuation_prompts: Optional[list] = None


class VideoJobAuthorizeRequest(BaseModel):
    confirmed_plan_fingerprint: str


def _job_intent(body: "VideoJobPlanRequest") -> dict:
    return {
        "product_id": body.product_id, "product_name": body.product_name,
        "execution_package_id": body.execution_package_id,
        "approved_asset_id": body.approved_asset_id,
        "approved_asset_sha256": body.approved_asset_sha256,
        "requested_duration_seconds": body.requested_total_duration_seconds,
        "engine": body.engine, "model": body.model, "aspect_ratio": body.aspect_ratio,
        "initial_prompt_fingerprint": body.initial_prompt_fingerprint,
        "execution_mode": body.execution_mode,
        "client_request_nonce": body.client_request_nonce,
        "initial_mode": body.initial_mode,
        "initial_asset_media_id": body.initial_asset_media_id,
        "initial_reference_media_ids": body.initial_reference_media_ids,
        "initial_prompt_text": body.initial_prompt_text,
        "continuation_prompts": body.continuation_prompts,
    }


_PLAN_422_CODES = {
    "INCOMPLETE_PRODUCTION_PLAN", "INVALID_DURATION_PLAN", "PROMPT_FINGERPRINT_MISMATCH",
}


async def _plan_video_job(body: "VideoJobPlanRequest", *, trust_client_authority: bool):
    from agent.services import video_production_orchestrator as _orch
    try:
        return await _orch.plan_job(
            _job_intent(body), trust_client_authority=trust_client_authority)
    except _orch.OrchestratorError as exc:
        if exc.code in _PLAN_422_CODES:
            raise HTTPException(422, {"code": exc.code, "detail": exc.detail})
        raise HTTPException(409, str(exc))


@router.post("/video-jobs/plan")
async def plan_video_job(body: VideoJobPlanRequest):
    """Create-or-reuse the lifecycle-owning job + return the ONE reviewed plan.

    Server-side SSOT: the client CANNOT override product/asset/prompt authority — all
    of it is resolved from the execution package. Spends nothing; the job exists
    BEFORE the initial segment. Incomplete/invalid-duration/fingerprint-mismatch plans
    are rejected with a structured 422 — no authorization is ever issued for them."""
    return await _plan_video_job(body, trust_client_authority=False)


@router.post("/video-jobs/plan-recovery")
async def plan_video_job_recovery(body: VideoJobPlanRequest):
    """RECOVERY/admin plan path — accepts explicit reviewed authority overrides (kept
    OUT of the normal production endpoint). Still recomputes every fingerprint
    server-side and rejects a supplied fingerprint that contradicts its prompt."""
    return await _plan_video_job(body, trust_client_authority=True)


@router.post("/video-jobs/lookup")
async def lookup_video_job(body: VideoJobPlanRequest):
    """READ-ONLY logical-job lookup for page mount / refresh restore.

    Computes the SAME logical job key as /video-jobs/plan from the client intent
    and returns the existing job's reviewed plan + status WITHOUT creating a job,
    resolving authority, or writing anything. A fresh page therefore performs
    zero plan writes on mount; the ONE plan POST happens only on the deliberate
    Generate action."""
    from agent.services import video_production_orchestrator as _orch
    key = _orch.compute_logical_job_key(_job_intent(body))
    job = await crud.get_video_production_job_by_logical_key(key)
    if not job:
        return {"found": False, "logical_job_key": key}
    plan = None
    if job.get("whole_plan_json"):
        try:
            plan = json.loads(job["whole_plan_json"])
        except (TypeError, ValueError):
            plan = None
    return {
        "found": True, "job_id": job["job_id"], "status": job["status"],
        "plan_fingerprint": job.get("plan_fingerprint"), "plan": plan,
        "logical_job_key": key,
    }


@router.post("/video-jobs/{job_id}/authorize")
async def authorize_video_job(job_id: str, body: VideoJobAuthorizeRequest):
    """Issue ONE expiring, single-use, job-bound, fingerprint-bound authorization for
    the whole reviewed plan. A changed plan (product/asset/prompt/duration/count) is
    rejected with 409."""
    from agent.services import video_production_orchestrator as _orch
    try:
        return await _orch.authorize_job(
            job_id, confirmed_plan_fingerprint=body.confirmed_plan_fingerprint)
    except _orch.OrchestratorError as exc:
        raise HTTPException(
            404 if exc.code == "VIDEO_JOB_NOT_FOUND" else 409, str(exc))


_VIDEO_ASPECT_TO_RATIO = {
    "VIDEO_ASPECT_RATIO_PORTRAIT": "9:16",
    "VIDEO_ASPECT_RATIO_LANDSCAPE": "16:9",
    "VIDEO_ASPECT_RATIO_SQUARE": "1:1",
}
_INITIAL_GEN_TERMINAL = {
    "DONE",
    "PRODUCT_FIDELITY_REVIEW_REQUIRED",
    "FAILED",
    "REJECTED",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
}


class InitialGenerationError(RuntimeError):
    """Fail-closed initial-segment generation error (no durable identity)."""


def _find_key(obj, key, _depth=0):
    """Best-effort recursive lookup of the first non-empty value for `key`."""
    if _depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        if obj.get(key) not in (None, "", []):
            return obj.get(key)
        for v in obj.values():
            r = _find_key(v, key, _depth + 1)
            if r not in (None, "", []):
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key, _depth + 1)
            if r not in (None, "", []):
                return r
    return None


def _initial_gen_preconditions(job: dict) -> tuple[str, str, list, str]:
    """Fail-closed authority check for the initial segment. Returns the ORDERED
    reference media-id list the one-door service receives — the SAME per-mode
    reference contract every one-block generation obeys (F2V 1-2 · I2V 2-3 ·
    T2V 0); the multi-block initial is not a special transport."""
    from agent.services import flow_mode_reference_contract as _refc
    prompt = (job.get("initial_prompt_text") or "").strip()
    if not prompt:
        raise InitialGenerationError("initial prompt not bound to job")
    if _is_multi_block_prompt(prompt):
        raise InitialGenerationError(
            "initial prompt carries more than one compiled block — block 1 only")
    mode = (job.get("initial_mode") or "I2V").upper()
    if mode == "T2V":
        # Text-only: product authority still applies; asset authority does not.
        if not job.get("product_id"):
            raise InitialGenerationError("product authority missing on job")
    elif not (job.get("product_id") and job.get("approved_asset_id")
              and job.get("approved_asset_sha256")):
        raise InitialGenerationError("product/asset authority missing on job")
    # Ordered reference list persisted at plan time; legacy rows (planned before
    # the column existed) fall back to the single initial asset.
    try:
        refs = json.loads(job.get("initial_reference_media_ids_json") or "null")
    except (TypeError, ValueError):
        refs = None
    if refs is None:
        refs = [job["initial_asset_media_id"]] if job.get("initial_asset_media_id") else []
    refs = [str(m) for m in refs if m]
    if mode == "T2V" and refs:
        raise InitialGenerationError(
            "T2V initial must carry ZERO reference images — stale image state is "
            "never inherited into a text-only generation")
    if mode in ("I2V", "F2V") and not refs:
        raise InitialGenerationError(f"{mode} initial requires an approved product asset media id")
    # Execution-boundary contract re-validation. A TYPED job carries the canonical
    # source_mode (persisted by the plan resolver) — enforce the FULL per-source-mode
    # bounds (min AND max), so HYBRID = exactly 1 is enforced here, not just the
    # transport upper-cap. A LEGACY_UNTYPED job (no persisted source_mode) keeps the
    # lenient transport hard-cap only: it cannot certify a mode and must not be
    # rejected by min-bounds it never declared.
    source_mode = job.get("initial_source_mode")
    if source_mode:
        ref_ok, ref_code, ref_detail = _refc.validate_reference_count(
            mode, len(refs), source_mode=source_mode)
        if not ref_ok:
            raise InitialGenerationError(ref_detail or ref_code)
    else:
        violation = _refc.service_hard_violation(mode, len(refs))
        if violation:
            raise InitialGenerationError(violation)
    aspect = _VIDEO_ASPECT_TO_RATIO.get(job.get("aspect_ratio") or "", "9:16")
    return prompt, mode, refs, aspect


async def _ensure_scene_membership(client, op_id: str, project_id: str,
                                   workflow_id: str | None) -> tuple[str, str | None, str]:
    """Guarantee the initial clip is a VERIFIED member of a scene/timeline before any
    Extend (Mission 5). Order: (1) already a member of a known scene? (2) otherwise
    deterministically create a scene from the clip's workflow id and VERIFY the
    createScene response lists our clip. Fail closed if membership cannot be proven —
    the Extend never runs against an unattached clip."""
    from agent.services import google_flow_native_extend_runtime as _nx
    # 1) already attached (make_video's own flow may have created the scene)
    try:
        ctx = await _nx.resolve_extend_source_context(
            client, media_id=op_id, project_id=project_id)
        if ctx.get("scene_id"):
            return ctx["scene_id"], ctx.get("workflow_id") or workflow_id, op_id
    except _nx.NativeExtendError:
        pass
    # 2) deterministic attach — need the clip's workflow id
    wf = workflow_id
    if not wf:
        try:
            media = await client.get_media(op_id)
            wf = _find_key(media, "workflowId") or _find_key(media, "workflow")
        except Exception:  # noqa: BLE001
            wf = None
    if not wf:
        # get_media returns the ENCODED VIDEO for a finished clip but omits the
        # workflowId; the media-shape status poll carries it (captured live contract,
        # record 608: check_video_status_by_media -> media[{name,projectId,workflowId}]).
        # This is the golden scene-bootstrap bridge: without the workflow id the very
        # first Extend in a fresh project can never create its scene.
        try:
            st = await client.check_video_status_by_media(
                [{"name": op_id, "projectId": project_id}])
            sdata = st.get("data", st) if isinstance(st, dict) else {}
            media_list = sdata.get("media") or []
            match = (next((m for m in media_list if m.get("name") == op_id), None)
                     or next((m for m in media_list if m.get("workflowId")), None))
            if match:
                wf = match.get("workflowId")
        except Exception:  # noqa: BLE001
            pass
    if not wf:
        raise InitialGenerationError(
            "INITIAL_SCENE_UNRESOLVED: initial clip has no scene and no workflow id to attach one")
    resp = await client.create_scene(project_id, [wf])
    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    scene_id = _find_key(data, "sceneId")
    member_ids = []
    for m in (data.get("sceneWorkflows") if isinstance(data, dict) else None) or []:
        pmid = _find_key(m, "primaryMediaId")
        if pmid and pmid not in member_ids:
            member_ids.append(pmid)
    # The scene was created from the clip's OWN authoritative workflow id (obtained from
    # the clip's status poll), so its member IS this clip. Flow re-issues a fresh timeline
    # primaryMediaId per created scene, so the harvest op_id will often NOT equal the scene
    # member id — that is expected (createScene copies the workflow into a new timeline
    # entry, verified live: op not in listing, primary in listing). Require a real scene
    # with a real member; adopt the exact op_id when it IS the member (golden case: harvest
    # id == primaryMediaId) else the scene's canonical member id as the Extend parent. This
    # is verified attachment from the clip's own workflow — never a title/order heuristic.
    if not scene_id or not member_ids:
        raise InitialGenerationError(
            "INITIAL_SCENE_ATTACH_UNVERIFIED: created scene has no verifiable member media")
    canonical = op_id if op_id in member_ids else member_ids[0]
    try:
        await crud.set_artifact_scene(canonical, scene_id)  # durable evidence for resolves
        if canonical != op_id:
            await crud.set_artifact_scene(op_id, scene_id)
    except Exception:  # noqa: BLE001
        pass
    return scene_id, wf, canonical


async def _map_lane_to_identity(client, lane: dict, job: dict) -> dict:
    op_id = lane.get("video_media_id") or lane.get("media_id")
    project_id = lane.get("project_id") or job.get("project_id") or job.get("initial_lane_project_id")
    if not op_id or not project_id:
        raise InitialGenerationError("initial clip missing operation/project id")
    scene_id, wf, canonical = await _ensure_scene_membership(
        client, op_id, project_id, lane.get("workflow_id"))
    if not scene_id:
        raise InitialGenerationError("initial clip has no scene id")
    # canonical is the clip's VERIFIED timeline media id inside the bootstrapped scene —
    # equal to op_id in the golden case, or the scene's re-issued primaryMediaId when Flow
    # copied the workflow into a fresh timeline entry. It is what the Extend must parent to.
    return {
        "operation_id": canonical, "media_id": canonical, "workflow_id": wf,
        "project_id": project_id, "scene_id": scene_id,
        "credit_balance_after": lane.get("remaining_credits"),
        # Exact-output correlation evidence bound by the one-door lane (PR321
        # closure) — persisted on the job for diagnostics + audit.
        "correlation": lane.get("output_correlation")
                       or lane.get("generation_identity"),
    }


async def _production_initial_generator(job: dict) -> dict:
    """LIVE initial block-1 generation through the proven one-door lane.

    Runs the exact reviewed authority persisted on the job (product-truth prompt,
    approved product asset, engine/model/aspect) via `make_video.start_generate`
    (the ONE door — never the frozen DOM lane). The one-door lane handle is PERSISTED
    the instant the submit is accepted, before the long poll, so a mid-flight crash
    never loses a (possibly credit-spending) job. Polls to terminal, guarantees
    verified scene membership, maps the real identities. Reached only under
    NATIVE_EXTEND_ENABLED + a consumed whole-job authorization.
    """
    from agent.services import make_video as _mv
    import asyncio as _asyncio
    prompt, mode, refs, aspect = _initial_gen_preconditions(job)

    client = get_flow_client()
    if not getattr(client, "connected", False):
        raise InitialGenerationError("Extension not connected")

    submit = await _mv.start_generate(
        mode=mode, prompt=prompt, project_id=job.get("project_id") or None,
        image_media_ids=refs or None,
        aspect=aspect, model=job.get("model"), duration_s=8, num_videos=1)
    if not isinstance(submit, dict) or submit.get("status") == "REJECTED":
        raise InitialGenerationError(
            f"one-door lane rejected initial: {submit.get('error') if isinstance(submit, dict) else submit}")
    lane_job_id = submit.get("job_id")
    if not lane_job_id:
        raise InitialGenerationError("one-door lane returned no job id")

    # DURABLE HANDLE (Mission 1): persist the lane identity NOW — before the minutes-
    # long poll — so a crash after submit never loses the job. Resume polls this, never
    # re-submits.
    await crud.update_video_production_job_full(
        job["job_id"], initial_lane_job_id=lane_job_id,
        initial_lane_project_id=(job.get("project_id") or ""))

    lane = None
    for _ in range(240):  # ~20 min ceiling at 5s; the durable driver owns this wait
        lane = _mv.get_job(lane_job_id)
        if lane and lane.get("status") in _INITIAL_GEN_TERMINAL:
            break
        await _asyncio.sleep(5)
    if not lane or lane.get("status") not in _INITIAL_GEN_TERMINAL:
        raise InitialGenerationError("initial generation did not reach a terminal state")
    if lane.get("status") != "DONE":
        raise InitialGenerationError(
            f"initial generation {lane.get('status')}: {lane.get('error') or ''}".strip())
    return await _map_lane_to_identity(client, lane, job)


async def _resume_initial_generation(job: dict) -> dict:
    """Poll-ONLY resume of a persisted in-flight initial lane. NEVER submits.

    Returns a structured state so the orchestrator never has to guess:
      {"state": "DONE", "identity": {...}}   lane finished — map identities
      {"state": "INFLIGHT"}                    still generating (or handle not yet recorded)
      {"state": "RECOVERY", "detail": ...}     lane handle gone after a restart (make_video's
                                               job map is in-memory) — credit MAY have been
                                               spent; reconcile, NEVER re-submit
      {"state": "FAILED", "detail": ...}       lane reached a non-DONE terminal state
    """
    from agent.services import make_video as _mv
    lane_job_id = job.get("initial_lane_job_id")
    if not lane_job_id:
        return {"state": "INFLIGHT"}  # submit not yet durably recorded; caller waits
    lane = _mv.get_job(lane_job_id)
    if lane is None:
        return {"state": "RECOVERY",
                "detail": f"initial lane {lane_job_id} lost after restart "
                          f"(project {job.get('initial_lane_project_id') or job.get('project_id')})"}
    if lane.get("status") not in _INITIAL_GEN_TERMINAL:
        return {"state": "INFLIGHT"}  # still generating; poll again later
    if lane.get("status") != "DONE":
        return {"state": "FAILED",
                "detail": f"initial generation {lane.get('status')}: {lane.get('error') or ''}".strip()}
    client = get_flow_client()
    if not getattr(client, "connected", False):
        return {"state": "INFLIGHT"}
    try:
        identity = await _map_lane_to_identity(client, lane, job)
    except InitialGenerationError as exc:
        return {"state": "FAILED", "detail": str(exc)}
    return {"state": "DONE", "identity": identity}


async def _drive_video_job(job_id: str, token: str):
    """Background durable driver — resume-safe; correctness is guaranteed by the DB
    idempotency table, not by this task surviving."""
    from agent.services import video_production_orchestrator as _orch
    from agent.config import OUTPUT_DIR
    client = get_flow_client()
    try:
        await _orch.advance_job(
            client, job_id, authorization_token=token,
            generate_initial=_production_initial_generator,
            resume_initial=_resume_initial_generation,
            out_dir=OUTPUT_DIR / "retrieved")
    except Exception:  # noqa: BLE001 — state is persisted; never crash the loop
        pass


@router.post("/video-jobs/{job_id}/start")
async def start_video_job(job_id: str, background_tasks: BackgroundTasks):
    """Start the durable job and return immediately. The single-use authorization is
    CONSUMED atomically here: the first start wins and enqueues the driver; a replayed
    start with the same token returns the existing status and never creates another
    job or authorizes another side effect."""
    from agent.services import video_production_orchestrator as _orch
    import time as _time
    job = await crud.get_video_production_job(job_id)
    if not job:
        raise HTTPException(404, "VIDEO_JOB_NOT_FOUND")
    token = job.get("authorization_token")
    if not token:
        raise HTTPException(409, "VIDEO_JOB_NOT_AUTHORIZED")
    consumed = await crud.consume_job_authorization(
        job_id, token, plan_fingerprint=job.get("plan_fingerprint") or "",
        now=str(_time.time()))
    if consumed["consumed"]:
        background_tasks.add_task(_drive_video_job, job_id, token)  # first start only
    elif not consumed["already"]:
        raise HTTPException(409, "VIDEO_JOB_AUTHORIZATION_ROTATED")
    return await _orch.get_job_status(job_id)


@router.get("/video-jobs/{job_id}/status")
async def video_job_status(job_id: str):
    """Structured, refresh-safe status the UI restores on mount (never auto-starts)."""
    from agent.services import video_production_orchestrator as _orch
    try:
        return await _orch.get_job_status(job_id)
    except _orch.OrchestratorError:
        raise HTTPException(404, "VIDEO_JOB_NOT_FOUND")


@router.post("/video-jobs")
async def create_video_job(body: VideoJobCreateRequest):
    """Create the logical job: verified source + already-proven Extend children.

    Segments are INTERNAL: the user deliverable is one final full-duration MP4.
    Fail-closed at every identity step; spends nothing."""
    import json as _json
    from agent.services import google_flow_native_extend_runtime as _nx
    from agent.services import google_flow_final_timeline_runtime as _ft
    from agent.services import flow_mode_reference_contract as _refc
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    # src_media is the operation/media id the timeline recognises as the Extend parent.
    # After a scene bootstrap Flow may RE-ISSUE it (createScene copies the workflow into a
    # fresh timeline entry), so it can differ from the caller-supplied harvest id.
    src_media = body.source_media_id
    try:
        ctx = await _nx.resolve_extend_source_context(
            client, media_id=src_media, project_id=body.project_id)
    except _nx.NativeExtendError as exc:
        # Golden scene-bootstrap bridge (adoption of an already-generated initial): a
        # freshly generated clip in a fresh project has no scene evidence yet, so the
        # first resolve fails. Deterministically bootstrap the scene from the clip's
        # workflow id (captured via the status poll), adopt the scene's VERIFIED member
        # id, persist durable scene evidence, then resolve ONCE more. Scene-create is
        # read/create only — spends no generation credit. If the workflow id genuinely
        # cannot be obtained, keep the original fail-closed 404.
        try:
            scene_id, _wf, canonical = await _ensure_scene_membership(
                client, src_media, body.project_id, None)
        except InitialGenerationError:
            raise HTTPException(404, str(exc)) from exc
        src_media = canonical
        try:
            ctx = await _nx.resolve_extend_source_context(
                client, media_id=src_media, project_id=body.project_id)
        except _nx.NativeExtendError:
            # scene created + membership verified inside _ensure_scene_membership;
            # use it directly if the read-only resolve still cannot re-confirm.
            ctx = {"project_id": body.project_id, "scene_id": scene_id,
                   "source_operation_id": src_media}
    # Successful Extend children of this source, in position order (scene-matched).
    rows = await crud.list_extend_lineage(project_id=body.project_id)
    children = sorted(
        [r for r in rows
         if r.get("parent_operation_id") == src_media
         and r.get("polling_state") == "EXTEND_SUCCEEDED"
         and r.get("child_operation_id")
         and (not r.get("scene_id") or r.get("scene_id") == ctx["scene_id"])],
        key=lambda r: (r.get("block_position") or 0))
    segments = [src_media] + [r["child_operation_id"] for r in children]
    needed = max(2, int(body.requested_total_duration_seconds // 8))
    status = (_ft.JOB_SEGMENTS_READY if len(segments) >= needed
              else _ft.JOB_BINDING_EXTEND)
    job_id = f"vj_{uuid4().hex[:12]}"
    await crud.create_video_production_job(
        job_id, project_id=body.project_id, scene_id=ctx["scene_id"],
        requested_duration_seconds=body.requested_total_duration_seconds,
        status=status, initial_media_id=src_media,
        segment_media_ids_json=_json.dumps(segments),
        product_id=body.product_id, product_name=body.product_name)
    # A System-B assembly job binds pre-existing clips; the source-mode
    # certification belongs to whatever ORIGINAL generation produced the source,
    # so this job is honestly LEGACY_UNTYPED and is never per-mode certification.
    return {
        "job_id": job_id, "status": status, "scene_id": ctx["scene_id"],
        "segments": segments, "segments_needed": needed,
        "source_mode": None,
        "source_mode_certification": _refc.certify_source_mode(None),
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
        custody_payload = (
            snapshot.get("product_visual_custody")
            or job.get("product_visual_custody")
            or {}
        )
        if isinstance(custody_payload, dict) and job.get("product_fidelity_qc") is not None:
            custody_payload = {
                **custody_payload,
                "product_fidelity_qc": job.get("product_fidelity_qc"),
                "product_fidelity_qc_status": job.get("product_fidelity_qc_status"),
            }
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
                product_visual_custody=custody_payload,
            )
    except Exception:  # noqa: BLE001 — durable record is best-effort, never fatal
        pass


def _telemetry_cost_kwargs(result_snapshot: dict = None) -> dict:
    """Non-null cost/engine instrumentation fields from a result snapshot, for the
    request_telemetry ledger. crud filters to allowed columns; None values are dropped
    so a snapshot without instrumentation simply leaves the columns untouched."""
    instr = (result_snapshot or {}).get("instrumentation") or {}
    return {k: v for k, v in instr.items() if v is not None}


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
            await _persist_output_correlation_evidence(request_id, job_id, job)
            await crud.upsert_request_telemetry(
                request_id, status="COMPLETED", completed_at=crud._now(),
                last_heartbeat_at=crud._now(),
                **_telemetry_cost_kwargs(result_snapshot),
            )
            await crud.update_request(request_id, status="COMPLETED", updated_at=crud._now())
            await _persist_generation_results(result_snapshot, job, all_ids)
            return
        if status in (_INITIAL_GEN_TERMINAL - {"DONE"}):
            code = str(job.get("error") or status)
            await crud.upsert_request_telemetry(
                request_id, status="FAILED", failed_at=crud._now(),
                error_message=code, error_code=code, last_heartbeat_at=crud._now(),
                **_telemetry_cost_kwargs(result_snapshot),
            )
            await crud.add_stage_event(
                request_id, "FAILED", "FAIL", f"job={job_id} {code}", "backend",
                fail_code=code, first_fail_stage="API_GENERATE_PROGRESS",
            )
            await _persist_output_correlation_evidence(request_id, job_id, job)
            await _persist_generation_results(
                result_snapshot,
                job,
                [
                    artifact.get("media_id")
                    for artifact in (job.get("artifacts") or [])
                    if artifact.get("media_id")
                ],
            )
            await crud.update_request(
                request_id, status="FAILED", error_message=code, updated_at=crud._now(),
            )
            return
        await asyncio.sleep(10)


async def _persist_output_correlation_evidence(request_id: str, job_id: str, job: dict):
    """Durably persist the run's output-correlation evidence as a stage event
    (Owner Phase-1). The incident (manual_faf40cf6) proved the in-memory
    correlation_stats/generation_identity vanish on restart — the exact evidence
    needed to diagnose a paid false-negative. Uses the EXISTING telemetry
    mechanism; no schema change. Best-effort: evidence must never fail a job."""
    import json as _json
    try:
        # Order matters: the compact decision evidence first so the tail-truncation
        # below can only ever clip the long sse_prompt inside generation_identity.
        evidence = {
            "correlation_stats": job.get("correlation_stats"),
            "output_correlation": job.get("output_correlation"),
            "generation_identity": job.get("generation_identity"),
        }
        if not any(evidence.values()):
            return
        await crud.add_stage_event(
            request_id, "API_OUTPUT_CORRELATION", "WAITING_FLOW",
            f"job={job_id} " + _json.dumps(evidence, ensure_ascii=False)[:1800],
            "backend",
        )
    except Exception:  # noqa: BLE001 — evidence is best-effort by contract
        pass


async def _resolve_asset_to_media_id(client, asset: dict, slot: str, request_id: str | None = None) -> str:
    """Resolve ONE dashboard asset (startAsset or refs.*) to a LIVE Flow media id.
    Priority: valid UUID media id (validated pre-credits, self-heals if stale) →
    local file upload → remote downloadUrl materialize + upload. Fails closed."""
    import mimetypes
    import os
    token = re.sub(r"[^A-Z0-9]+", "_", slot.upper()).strip("_")
    media_id = _extract_flow_media_id(asset)
    local_path = asset.get("localFilePath") or asset.get("local_file_path")
    asset_source = str(
        asset.get("assetSource") or asset.get("asset_source") or asset.get("source") or ""
    ).upper()
    official_visual = bool(
        asset.get("officialVisual") is True
        or asset.get("official_visual") is True
        or asset_source.startswith("PRODUCT_VISUAL_OFFICIAL")
    )
    # An opaque pre-existing Flow id is not custody proof for an official
    # product visual. Official assets must be uploaded from the byte-verified
    # server-owned path on this dispatch; otherwise an old/stale media id can
    # silently survive a Product Truth cutout replacement.
    if media_id and not official_visual:
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
    uploaded_id = None
    if isinstance(up, dict):
        uploaded_id = (
            up.get("_mediaId")
            or up.get("media_id")
            or (up.get("data") or {}).get("media", {}).get("name")
            or (up.get("data") or {}).get("name")
            or up.get("name")
        )
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
    v2_resolution = None
    try:
        from agent.services.copy_execution_resolver import (
            CopyExecutionResolutionError,
            lane_for_request,
            resolve_persisted_copy_execution_binding,
        )

        requested_lane = str((body.get("copy_v2_context") or {}).get("lane") or "")
        v2_resolution = await resolve_persisted_copy_execution_binding(
            str(body.get("product_id") or "request-product"),
            requested_lane
            or lane_for_request(
                mode,
                source_mode=body.get("source_mode"),
                visual_lane_id=body.get("visual_lane_id") or body.get("lane"),
            ),
            body.get("copy_v2_context"),
        )
    except CopyExecutionResolutionError as exc:
        await _fail_manual_request(
            request_id,
            "API_LANE_REJECTED",
            str(exc),
            exc.code,
        )
    prompt = str(body.get("prompt") or "").strip()
    creative_campaign = (
        mode == "IMG"
        and (
            str(body.get("visual_lane_id") or body.get("lane") or "").upper()
            == "POSTER_BUILDER_CREATIVE_CAMPAIGN"
            or str(body.get("creative_mode") or "").upper() == "CREATIVE_CAMPAIGN"
        )
    )
    if not prompt:
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED", "manual job has no prompt", "ERR_PROMPT_REQUIRED")
    if creative_campaign and not body.get("product_id"):
        await _fail_manual_request(
            request_id,
            "API_LANE_REJECTED",
            "creative campaign requires a server-bound product reference pack",
            "ERR_CREATIVE_CAMPAIGN_PRODUCT_ID_REQUIRED",
        )
    # ONE generation = ONE block. The full multi-block compiled document must never
    # reach the agent (live incident: 2 blocks → 2-video proposal → count steer →
    # reference image dropped). Block 2+ runs as native Extend on the finished clip.
    if _is_multi_block_prompt(prompt):
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED",
            "prompt carries more than one compiled block — submit block 1 only; "
            "block 2+ belongs to the Extend step", "ERR_MULTI_BLOCK_PROMPT")
    if mode in ("T2V", "I2V", "F2V"):
        stale_prompt_error = await _provider_safety_stale_prompt_error(
            body.get("product_id"),
            prompt,
        )
        if stale_prompt_error:
            await _fail_manual_request(
                request_id,
                "API_LANE_REJECTED",
                "The persisted prompt package contains a creator attribution that "
                "Google Flow rejects. Recompile the package before generation.",
                stale_prompt_error,
            )

    if mode in ("I2V", "F2V") and body.get("product_id"):
        # Apply the same server-owned visual authority used by /generate.  The
        # package path normally already carries this asset; this guard also
        # protects direct/manual API callers from injecting a stale catalog
        # image into the API-first lane.
        effective_source_mode = await _effective_video_source_mode(
            body.get("source_mode"),
            body.get("workspace_execution_package_id"),
        )
        body["source_mode"] = effective_source_mode
        start_asset, gated_refs, _ = await _apply_video_product_visual_gate(
            product_id=str(body["product_id"]),
            mode=mode,
            source_mode=effective_source_mode,
            request_refs=dict(body.get("refs") or {}),
            start_asset=start_asset,
        )
        body["refs"] = gated_refs
        # Product visual custody is a pre-credit gate. The official asset is
        # the only product reference allowed into the shared API-first lane;
        # exact-policy products cannot use the current generative R2V/I2V
        # semantics until a deterministic exact route is proven.
        if effective_source_mode != "FRAMES":
            from agent.services.product_visual_custody_service import (
                ProductVisualCustodyError,
                build_product_visual_custody_receipt,
                exact_product_required,
                validate_pre_dispatch_route,
            )

            product_row = await crud.get_product(str(body["product_id"]))
            official_asset = (
                start_asset
                if isinstance(start_asset, dict)
                else (gated_refs.get("productAsset") if isinstance(gated_refs, dict) else None)
            )
            try:
                if not product_row:
                    raise ProductVisualCustodyError(
                        "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                        "The product row is unavailable for product-visual custody.",
                    )
                receipt = build_product_visual_custody_receipt(
                    product_row,
                    official_asset,
                    mode=mode,
                    source_mode=effective_source_mode,
                    prompt=prompt,
                    provider_route="API_FIRST_GENERATIVE_REFERENCE",
                    generation_type="reference_frame_2_video",
                    execution_identity=body.get("execution_identity"),
                )
                validate_pre_dispatch_route(
                    receipt,
                    provider_route="API_FIRST_GENERATIVE_REFERENCE",
                    generation_type=receipt["generation_type"],
                )
                if (
                    exact_product_required(product_row)
                    and not receipt["prompt_lock"].get("all_required_markers_present")
                ):
                    raise ProductVisualCustodyError(
                        "ERR_PRODUCT_PROMPT_LOCK_INCOMPLETE",
                        "Exact-product video prompt is missing one or more required Product Lock sections.",
                    )
                body["product_visual_custody"] = receipt
            except ProductVisualCustodyError as exc:
                await _fail_manual_request(
                    request_id,
                    "API_PRODUCT_VISUAL_CUSTODY_GATE",
                    str(exc),
                    exc.code,
                )

    if mode == "IMG" and body.get("product_id"):
        if creative_campaign:
            from agent import config
            if not config.CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZED:
                await _fail_manual_request(
                    request_id, "API_LANE_REJECTED",
                    "creative campaign live benchmark authorization is required",
                    "ERR_CREATIVE_CAMPAIGN_AUTH_REQUIRED",
                )
            if not body.get("confirm_live_credit_burn"):
                await _fail_manual_request(
                    request_id, "API_LANE_REJECTED",
                    "explicit image credit confirmation is required",
                    "ERR_IMAGE_LIVE_CREDIT_CONFIRMATION_REQUIRED",
                )
            if body.get("image_contract_version") != "image_prompt_compiler_v1":
                await _fail_manual_request(
                    request_id, "API_LANE_REJECTED",
                    "image contract version is required",
                    "ERR_IMAGE_CONTRACT_VERSION_REQUIRED",
                )
            if int(body.get("max_retry_operations") or 0) != 0:
                await _fail_manual_request(
                    request_id,
                    "API_LANE_REJECTED",
                    "creative campaign hidden retries are disabled",
                    "ERR_HIDDEN_RETRY_DISABLED",
                )
            try:
                requested_count = int(body.get("count") or 1)
            except (TypeError, ValueError):
                requested_count = 0
            if requested_count < 1 or requested_count > 3:
                await _fail_manual_request(
                    request_id,
                    "API_LANE_REJECTED",
                    "creative campaign is bounded to at most three provider outputs",
                    "ERR_CREATIVE_CAMPAIGN_MAX_THREE_VARIANTS",
                )
            if str(body.get("output_intent") or "").upper() != "CLEAN_KEY_VISUAL":
                await _fail_manual_request(
                    request_id,
                    "API_LANE_REJECTED",
                    "creative campaign requires a clean key visual provider output",
                    "ERR_CREATIVE_CAMPAIGN_CLEAN_KEY_VISUAL_REQUIRED",
                )
            requested_image_model = str(
                body.get("image_model") or "NANO_BANANA_PRO"
            ).upper()
            if requested_image_model != "NANO_BANANA_PRO":
                await _fail_manual_request(
                    request_id,
                    "API_LANE_REJECTED",
                    "creative campaign final model must be NANO_BANANA_PRO",
                    "ERR_CREATIVE_CAMPAIGN_FINAL_MODEL_REQUIRED",
                )
        prompt, gated_refs, exact_img = await _apply_img_product_truth_gate(
            product_id=str(body["product_id"]),
            visual_lane_id=body.get("visual_lane_id") or body.get("lane"),
            prompt=prompt,
            request_refs=dict(body.get("refs") or {}),
            start_asset=start_asset,
            reference_pack_id=body.get("reference_pack_id"),
            creative_mode=body.get("creative_mode"),
        )
        if not exact_img:
            # The official Product Registration visual is the only product
            # input for this IMG lane.  Drop the untyped legacy start asset;
            # scene/avatar/style references remain available through refs.*.
            start_asset = None
        body["prompt"] = prompt
        body["refs"] = gated_refs
        if creative_campaign:
            try:
                await _run_creative_campaign_pre_provider_lint(
                    product_id=str(body["product_id"]),
                    poster_copy_set_id=body.get("poster_copy_set_id"),
                    copy_v2_resolution=v2_resolution,
                    prompt=prompt,
                    image_model=body.get("image_model"),
                    output_intent=body.get("output_intent"),
                    maximum_provider_operations=body.get("maximum_provider_operations"),
                    max_retry_operations=int(body.get("max_retry_operations") or 0),
                )
            except HTTPException as exc:
                await _fail_manual_request(
                    request_id,
                    "API_CAMPAIGN_PRE_PROVIDER_LINT",
                    str(exc.detail),
                    "ERR_CAMPAIGN_PRE_PROVIDER_LINT_BLOCKED",
                )

    # Collect EVERY image the dashboard sent: F2V uses startAsset (+ optional
    # endAsset — previously materialized then silently DROPPED here, losing the
    # user's 2nd frame); I2V/IMG send refs.{subjectAsset,sceneAsset,styleAsset}
    # (previously DROPPED here — I2V died ERR_START_ASSET_REQUIRED and IMG
    # silently ignored its reference images).
    slot_assets = ordered_ref_slots(start_asset, body.get("refs"),
                                    end_asset=body.get("endAsset"))
    refs = []
    local_paths = []
    official_provider_media_id = None
    for slot_label, asset in slot_assets:
        resolved = await _resolve_asset_to_media_id(client, asset, slot_label, request_id)
        if resolved and resolved not in refs:
            refs.append(resolved)
            lp = asset.get("localFilePath") or asset.get("local_file_path")
            if lp:
                local_paths.append(str(lp))
        asset_source = str(
            asset.get("assetSource") or asset.get("asset_source") or asset.get("source") or ""
        ).upper()
        if resolved and (
            asset.get("officialVisual") is True
            or asset.get("official_visual") is True
            or asset_source.startswith("PRODUCT_VISUAL_OFFICIAL")
        ):
            official_provider_media_id = str(resolved)

    if mode in ("I2V", "F2V") and not refs:
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED",
            f"{mode} needs a start/reference image", "ERR_START_ASSET_REQUIRED")

    # ── USER MODE REFERENCE CONTRACT (fail-closed, zero credit) ──────────────
    # F2V/FRAMES 1-2 · HYBRID exactly 1 (the product image) · I2V 2-3 · T2V 0.
    # SERVER-OWNED authority (PR321 closure): when the job runs a persisted
    # execution package, the canonical source mode is DERIVED from that
    # package's compiler lineage — a contradicting client declaration is
    # rejected, and the derived mode (never a silent F2V transport fallback)
    # is the contract authority. Without a package the dashboard declaration /
    # transport bounds apply as before. Wrong counts are rejected BEFORE any
    # settings/generation work — never silently dropped, padded, or converted
    # to a text-only run.
    from agent.services import flow_mode_reference_contract as _refc
    _authority_source_mode = body.get("source_mode")
    _pkg_id = str(body.get("workspace_execution_package_id") or "").strip()
    if _pkg_id:
        _pkg = await crud.get_workspace_execution_package(_pkg_id)
        _derived = _refc.derive_package_source_mode(_pkg)
        if _derived:
            _declared = _refc.normalize_source_mode(body.get("source_mode"))
            if _declared and _declared != _derived:
                await _fail_manual_request(
                    request_id, "API_LANE_REJECTED",
                    f"client source_mode '{body.get('source_mode')}' contradicts the "
                    f"execution package's compiled lineage '{_derived}' — the package "
                    "authority is server-owned",
                    _refc.ERR_SOURCE_MODE_AUTHORITY_MISMATCH)
            _authority_source_mode = _derived
    _ref_ok, _ref_code, _ref_detail = _refc.validate_reference_count(
        mode, len(refs), source_mode=_authority_source_mode)
    if not _ref_ok:
        await _fail_manual_request(
            request_id, "API_LANE_REJECTED", _ref_detail, _ref_code)

    if body.get("product_visual_custody") is not None:
        from agent.services.product_visual_custody_service import (
            ProductVisualCustodyError,
            bind_provider_reference_transport,
        )

        if not official_provider_media_id:
            await _fail_manual_request(
                request_id,
                "API_PRODUCT_VISUAL_CUSTODY_GATE",
                "The official product visual did not produce an observed provider reference id.",
                "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
            )
        try:
            body["product_visual_custody"] = bind_provider_reference_transport(
                body["product_visual_custody"],
                provider_reference_media_ids=refs,
                official_provider_media_id=official_provider_media_id,
                provider_route="API_FIRST_GENERATIVE_REFERENCE",
                generation_type="reference_frame_2_video",
            )
        except (KeyError, TypeError, ProductVisualCustodyError) as exc:
            await _fail_manual_request(
                request_id,
                "API_PRODUCT_VISUAL_CUSTODY_GATE",
                str(exc),
                "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
            )

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
    if creative_campaign:
        expected_operations = count + int(body.get("max_retry_operations") or 0)
        if body.get("maximum_provider_operations") != expected_operations:
            await _fail_manual_request(
                request_id,
                "API_LANE_REJECTED",
                "creative campaign provider operation budget mismatch",
                "ERR_PROVIDER_OPERATION_BUDGET_MISMATCH",
            )
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

    # ── Owner Phase-2B: composer-driven initial lane (mutually exclusive) ───
    from agent.services import google_flow_ui_driver as _ui_drv
    if (_ui_drv.ui_driver_enabled() and mode in ("T2V", "I2V", "F2V")
            and body.get("_direct_capture") is not True):
        try:
            ui_initial = await _ui_drv.run_initial_block1_via_composer(
                client,
                prompt=prompt,
                media_ids=refs,
                local_file_paths=local_paths,
                expected_count=len(refs),
                dry_run=body.get("confirm_live_credit_burn") is not True,
                confirm_live_credit_burn=bool(body.get("confirm_live_credit_burn")),
                request_id=request_id,
                intercept_submit=body.get("confirm_live_credit_burn") is not True,
            )
            await crud.add_stage_event(
                request_id, "UI_COMPOSER_INITIAL_READY", "WAITING_FLOW",
                f"lane=UI_COMPOSER_INITIAL count={len(refs)} mode={mode}",
                "backend")
            return {
                "ok": True,
                "accepted": True,
                "lane": "UI_COMPOSER_INITIAL",
                "request_id": request_id,
                "mode": mode,
                "status": "READY_FOR_NEGOTIATION",
                "ui_driver": ui_initial,
            }
        except _ui_drv.FlowUiDriverError as exc:
            await _fail_manual_request(
                request_id, "API_LANE_REJECTED",
                f"{exc.code}: {exc.detail}", exc.code)

    # ── LIVE-CAPTURE GATE (owner-fired, DIRECT_VIDEO_CAPTURE_ENABLED): fire ONE
    # direct batchAsync submit with the resolved refs/project/settings and return
    # the RAW submit response so the real contract (operation handles, accepted
    # videoModelKey/aspect shape) is captured; poll+retrieve+persist continue in
    # the background so the spent credit still yields an artifact.  An explicit
    # capture request is terminal: it must never fall through to normal
    # start_generate when disabled, unconfirmed, or otherwise ineligible.
    if body.get("_direct_capture") is True:
        capture_project_id = created_project_id or (
            diag.get("projectId") if isinstance(diag, dict) else None)
        cap = await _mv.start_direct_capture(
            mode, prompt, capture_project_id, refs, aspect=aspect, tier=tier,
            source_mode=_authority_source_mode, model=model_key,
            duration_s=duration_s,
            confirm_live_credit_burn=bool(body.get("confirm_live_credit_burn")),
            product_visual_custody=body.get("product_visual_custody"),
            execution_identity=body.get("execution_identity"),
        )
        await crud.add_stage_event(
            request_id,
            "API_DIRECT_CAPTURE_FIRED" if cap.get("ok")
            else "API_DIRECT_CAPTURE_REJECTED",
            "WAITING_FLOW" if cap.get("ok") else "FAILED",
            f"ok={cap.get('ok')} error={cap.get('error')} job={cap.get('job_id')} "
            f"fired={json.dumps(cap.get('fired') or {})[:400]} "
            f"operations={cap.get('operations')}", "backend")
        return {"ok": bool(cap.get("ok")), "lane": "DIRECT_CAPTURE",
                "request_id": request_id, "mode": mode,
                "source_mode": _authority_source_mode, **cap}

    res = await _mv.start_generate(
        mode, prompt, project_id=created_project_id,
        image_media_ids=refs or None,
        aspect=aspect, tier=tier, model=model_key,
        duration_s=duration_s, num_videos=count,
        max_image_attempts=1 if creative_campaign else 8,
        collect_image_variants=creative_campaign,
        image_model=body.get("image_model") if creative_campaign else None,
        product_id=body.get("product_id"),
        source_mode=_authority_source_mode,
        product_visual_custody=body.get("product_visual_custody"),
        execution_identity=body.get("execution_identity"),
        copy_execution_binding=(
            v2_resolution.to_metadata(
                consumer_context=body.get("copy_v2_context")
            )
            if v2_resolution is not None and v2_resolution.v2_enabled
            else None
        ),
    )
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
    # Cost/engine instrumentation (best-effort; NULL on any failure — NEVER blocks
    # generation). The bridge persists these onto the durable telemetry ledger.
    _instr: dict = {"provider": "google_flow", "engine": model_key, "model_label": body.get("model")}
    try:
        if model_key:
            from agent.services import video_models as _vm_instr
            _instr["estimated_credits"] = _vm_instr.expected_cost(model_key, duration_s)
    except Exception:  # noqa: BLE001 — telemetry is best-effort, never fatal
        pass
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
        "product_visual_custody": body.get("product_visual_custody") or {},
        "copy_architecture_v2": (
            v2_resolution.to_metadata(
                consumer_context=body.get("copy_v2_context")
            )
            if v2_resolution is not None and v2_resolution.v2_enabled
            else None
        ),
        "instrumentation": _instr,
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
        for ref_key, slot_label in REF_SLOT_ORDER:
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

    # ── ADR-007 defense-in-depth: no canonical production job may reach the dead
    # DOM lane. The reroute above already returns for IMG/T2V/I2V/F2V; this fails
    # closed for any canonical/source-canonical payload that slipped past it
    # (e.g. an aliased/missing transport mode carrying only a source_mode),
    # turning a silent DOM-lane JOB_PROMPT_EMPTY into a loud, actionable error
    # instead of a DOM dispatch. Genuinely legacy non-mode payloads (no canonical
    # mode AND no canonical source_mode) still fall through to the frozen lane.
    _src_mode = str(body.get("source_mode") or "").upper()
    _CANONICAL_SOURCE_MODES = {
        "IMG", "T2V", "I2V", "F2V", "HYBRID", "FRAMES", "INGREDIENTS",
    }
    if (not body.get("smoke_test")) and (
        _api_mode in ("IMG", "T2V", "I2V", "F2V") or _src_mode in _CANONICAL_SOURCE_MODES
    ):
        raise HTTPException(
            422,
            "ERR_CANONICAL_MODE_LEGACY_DOM_ROUTE_FORBIDDEN: "
            f"mode={_api_mode or 'n/a'} source_mode={_src_mode or 'n/a'} "
            "must run API-first (make_video.start_generate), never the DOM lane.",
        )

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
