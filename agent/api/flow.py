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
        await crud.add_stage_event(
            body["request_id"],
            "BACKEND_START_ASSET_MATERIALIZED",
            "WAITING_FLOW",
            f"local_file_path={_local_path} source={str(_remote_url)[:80]}",
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
