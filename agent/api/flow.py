"""Direct Flow API endpoints — for manual operations outside the queue."""
import base64
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


async def _generate_image_with_recovery(client, prompt, project_id, aspect, tier, refs, max_tries=8):
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
            user_paygate_tier=tier, character_media_ids=refs or None)
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


@router.post("/make-video-existing")
async def make_video_existing(body: MakeVideoExistingRequest):
    """Generate a video in an EXISTING project from an EXISTING image, then save it.
    Poll GET /api/flow/video-job/{id}."""
    from agent.services import make_video as _mv
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    # Route the legacy endpoint through the guarded one door (patch #3): inherits the
    # single-flight lane, bound-editor session, and drift/loss invariants instead of the
    # unguarded start_on_existing path.
    result = await _mv.start_generate(
        "I2V", body.prompt, project_id=body.project_id,
        image_media_ids=[body.image_media_id])
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
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    tier = "PAYGATE_TIER_ONE"
    if mode in ("T2V", "I2V", "F2V"):  # video modes need Pro/Ultra
        cred = await client.get_credits()
        tier = (cred.get("data", cred) or {}).get("userPaygateTier", "") if isinstance(cred, dict) else ""
        if tier not in ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"):
            raise HTTPException(500, f"Account tier '{tier}' cannot generate video — needs Pro/Ultra")
    result = await _mv.start_generate(
        mode, body.prompt, project_id=body.project_id,
        image_media_ids=body.image_media_ids, image_prompt=body.image_prompt,
        aspect=body.aspect, tier=tier)
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
        return {"bound": True, "binding": binding, "shape": shape}
    except Exception as e:  # noqa: BLE001
        return {"bound": False, "error": str(e), "shape": shape}


class NegotiateJobRequest(BaseModel):
    prompt: str = "Vertical 9:16 cinematic product video. Slow push-in on the product, soft light, subtle motion. Make 1 video."
    image_prompt: str = "A premium product on a clean surface, soft studio light, vertical 9:16. No text, no labels, no watermark."
    dry: bool = True


@router.post("/negotiate-job")
async def negotiate_job(body: NegotiateJobRequest):
    """Async negotiation (captures full transcript). dry=True → 0 video credits."""
    from agent.services import make_video as _mv
    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "Extension not connected")
    return await _mv.start_negotiate(body.prompt, body.image_prompt, body.dry)


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
    if _is_upload_only_lane and isinstance(_start_asset, dict) and not _has_local_start:

        async def _fail_closed_materialize(stage_message: str, error_code: str):
            await crud.add_stage_event(
                body["request_id"],
                "BACKEND_START_ASSET_MATERIALIZE_FAILED",
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
                body["request_id"], "FAILED", "FAILED", error_code, "backend",
                fail_code=error_code, first_fail_stage="BACKEND_START_ASSET_MATERIALIZE_FAILED",
            )
            raise HTTPException(422, error_code)

        _remote_url = (
            _start_asset.get("downloadUrl")
            or _start_asset.get("download_url")
            or _start_asset.get("previewUrl")
            or _start_asset.get("preview_url")
        )
        if not _remote_url:
            await _fail_closed_materialize(
                "startAsset is remote-only with no usable URL to materialize",
                "ERR_PACKAGE_START_LOCAL_FILE_REQUIRED",
            )
        try:
            _materialized = await _materialize_remote_url_to_staging(
                str(_remote_url),
                _start_asset.get("fileName") or _start_asset.get("file_name") or "Start.png",
            )
        except Exception as exc:
            await _fail_closed_materialize(
                str(exc), "ERR_PACKAGE_START_MATERIALIZE_FAILED"
            )
        _local_path = _materialized["local_file_path"]
        # Set both camelCase and snake_case; preserve all other startAsset fields
        # (fileName / mediaId / previewUrl / downloadUrl) by mutating in place.
        _start_asset["localFilePath"] = _local_path
        _start_asset["local_file_path"] = _local_path
        body["startAsset"] = _start_asset
        _source_type = (
            "workspace_package_start"
            if body.get("workspace_execution_package_id")
            or body.get("prompt_package_snapshot_id")
            else "start_asset"
        )
        await crud.add_stage_event(
            body["request_id"],
            "BACKEND_START_ASSET_MATERIALIZED",
            "WAITING_FLOW",
            _build_materialized_stage_message(_local_path, _source_type),
            "backend",
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
