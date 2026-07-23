"""One-shot upload + Flow video submission contract endpoints."""
import asyncio
import base64
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.config import VIDEO_MODELS
from agent.db import crud
from agent.db.crud import add_stage_event, upsert_request_telemetry
from agent.services.flow_client import get_flow_client

router = APIRouter(tags=["oneshot"])

REQUEST_TYPE = "MANUAL_FLOW_JOB"
DEFAULT_ASPECT_RATIO = "VIDEO_ASPECT_RATIO_PORTRAIT"
DEFAULT_PAYGATE_TIER = "PAYGATE_TIER_ONE"

ERROR_EXTENSION_DISCONNECTED = "EXTENSION_DISCONNECTED"
ERROR_MISSING_FLOW_KEY = "MISSING_FLOW_KEY"
ERROR_NO_MODEL = "NO_MODEL"
ERROR_INVALID_IMAGE = "INVALID_IMAGE"
ERROR_JOB_FAILED = "JOB_FAILED"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_JOB_NOT_FOUND = "JOB_NOT_FOUND"


class ShootOneShotRequest(BaseModel):
    image_base64: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    scene_id: Optional[str] = None
    file_name: str = "oneshot.png"
    mime_type: str = "image/png"
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    user_paygate_tier: str = DEFAULT_PAYGATE_TIER
    timeout_seconds: int = Field(default=120, ge=10, le=600)


class ShootOneShotResponse(BaseModel):
    job_id: str
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    request_type: Optional[str] = None
    project_id: Optional[str] = None
    scene_id: Optional[str] = None
    uploaded_media_id: Optional[str] = None
    output_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    report: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _raise_contract_error(status_code: int, error_code: str, message: str, details: dict[str, Any] | None = None):
    raise HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": message,
            "details": details or {},
        },
    )


def _normalize_image_base64(image_base64: str) -> str:
    raw = image_base64.strip()
    if not raw:
        _raise_contract_error(400, ERROR_INVALID_IMAGE, "image_base64 is required")

    if raw.startswith("data:"):
        try:
            _, raw = raw.split(",", 1)
        except ValueError:
            _raise_contract_error(400, ERROR_INVALID_IMAGE, "Invalid data URL image payload")

    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        _raise_contract_error(400, ERROR_INVALID_IMAGE, "image_base64 must be valid base64")

    if not decoded:
        _raise_contract_error(400, ERROR_INVALID_IMAGE, "Decoded image payload is empty")

    return raw


def _model_available(user_paygate_tier: str, aspect_ratio: str) -> bool:
    model_key = VIDEO_MODELS.get(user_paygate_tier, {}).get("frame_2_video", {}).get(aspect_ratio)
    return bool(model_key)


def _is_timeout(message: str) -> bool:
    return "timeout" in message.lower()


def _classify_flow_error(message: str) -> str:
    normalized = message.lower()
    if "extension not connected" in normalized or "extension disconnected" in normalized:
        return ERROR_EXTENSION_DISCONNECTED
    if "no model" in normalized:
        return ERROR_NO_MODEL
    if _is_timeout(message):
        return ERROR_TIMEOUT
    return ERROR_JOB_FAILED


def _error_message_from_result(result: dict[str, Any]) -> Optional[str]:
    error = result.get("error")
    if error:
        return str(error)
    status = result.get("status")
    if isinstance(status, int) and status >= 400:
        return json.dumps(result, default=str)
    return None


async def _record_stage(
    job_id: str,
    stage: str,
    status: str,
    message: str | None = None,
    *,
    error_code: str | None = None,
):
    now = crud._now()
    telemetry_updates = {
        "request_type": REQUEST_TYPE,
        "worker_stage": stage,
        "status": status,
        "last_heartbeat_at": now,
    }
    if status in {"PROCESSING", "RUNNING"}:
        telemetry_updates["started_at"] = now
    if status == "COMPLETED":
        telemetry_updates["completed_at"] = now
    if status == "FAILED":
        telemetry_updates["failed_at"] = now
        telemetry_updates["error_code"] = error_code
        telemetry_updates["error_message"] = message

    await upsert_request_telemetry(job_id, **telemetry_updates)
    await add_stage_event(
        job_id,
        stage,
        status,
        message,
        source="backend",
        fail_code=error_code,
    )


async def _fail_job(
    job_id: str,
    body: ShootOneShotRequest,
    error_code: str,
    message: str,
    report: dict[str, Any] | None = None,
):
    payload = {
        "contract": "shoot-oneshot",
        "error_code": error_code,
        "error_message": message,
        **(report or {}),
    }
    await crud.update_request(
        job_id,
        status="FAILED",
        error_message=f"{error_code}: {message}",
        automation_report=json.dumps(payload, default=str),
    )
    await _record_stage(job_id, "failed", "FAILED", message, error_code=error_code)


async def _run_shoot_oneshot(job_id: str, body: ShootOneShotRequest, normalized_image_base64: str):
    client = get_flow_client()
    report: dict[str, Any] = {
        "contract": "shoot-oneshot",
        "project_id": body.project_id,
        "scene_id": body.scene_id,
        "file_name": body.file_name,
        "mime_type": body.mime_type,
        "aspect_ratio": body.aspect_ratio,
        "user_paygate_tier": body.user_paygate_tier,
    }

    try:
        await crud.update_request(job_id, status="PROCESSING")
        await _record_stage(job_id, "upload_image", "PROCESSING")

        upload_result = await asyncio.wait_for(
            client.upload_image(
                normalized_image_base64,
                mime_type=body.mime_type,
                project_id=body.project_id,
                file_name=body.file_name,
            ),
            timeout=body.timeout_seconds,
        )
        report["upload_result"] = upload_result

        upload_error = _error_message_from_result(upload_result)
        if upload_error:
            await _fail_job(job_id, body, _classify_flow_error(upload_error), upload_error, report)
            return

        media_id = upload_result.get("_mediaId")
        if not media_id:
            await _fail_job(job_id, body, ERROR_JOB_FAILED, "Upload completed without a media id", report)
            return

        await crud.update_request(job_id, media_id=media_id, automation_report=json.dumps(report, default=str))
        await _record_stage(job_id, "submit_video", "PROCESSING")

        video_result = await asyncio.wait_for(
            client.generate_video(
                start_image_media_id=media_id,
                prompt=body.prompt,
                project_id=body.project_id,
                scene_id=body.scene_id or job_id,
                aspect_ratio=body.aspect_ratio,
                user_paygate_tier=body.user_paygate_tier,
            ),
            timeout=body.timeout_seconds,
        )
        report["video_result"] = video_result

        video_error = _error_message_from_result(video_result)
        if video_error:
            await _fail_job(job_id, body, _classify_flow_error(video_error), video_error, report)
            return

        await crud.update_request(
            job_id,
            status="WAITING_FLOW",
            media_id=media_id,
            request_id=video_result.get("name") or video_result.get("operation") or video_result.get("id"),
            automation_report=json.dumps(report, default=str),
        )
        await _record_stage(
            job_id,
            "waiting_flow",
            "COMPLETED",
            "One-shot upload submitted to Flow; use job status for stored result and Flow status polling for operation progress.",
        )
    except asyncio.TimeoutError:
        await _fail_job(job_id, body, ERROR_TIMEOUT, "One-shot job timed out", report)
    except Exception as exc:
        await _fail_job(job_id, body, ERROR_JOB_FAILED, str(exc), report)


@router.post("/shoot-oneshot", response_model=ShootOneShotResponse)
async def shoot_oneshot(body: ShootOneShotRequest):
    client = get_flow_client()
    if not client.connected:
        _raise_contract_error(503, ERROR_EXTENSION_DISCONNECTED, "Chrome extension is not connected")

    extension_status = await client.get_status()
    flow_key_present = bool(extension_status.get("flowKeyPresent") or getattr(client, "_flow_key", None))
    if not flow_key_present:
        _raise_contract_error(503, ERROR_MISSING_FLOW_KEY, "Flow key is missing from the connected extension")

    normalized_image_base64 = _normalize_image_base64(body.image_base64)

    if not _model_available(body.user_paygate_tier, body.aspect_ratio):
        _raise_contract_error(
            422,
            ERROR_NO_MODEL,
            "No Flow video model is configured for the requested tier and aspect ratio",
            {"user_paygate_tier": body.user_paygate_tier, "aspect_ratio": body.aspect_ratio},
        )

    request = await crud.create_request(REQUEST_TYPE)
    job_id = request["id"]
    await _record_stage(job_id, "queued", "QUEUED")

    asyncio.create_task(_run_shoot_oneshot(job_id, body, normalized_image_base64))

    return ShootOneShotResponse(
        job_id=job_id,
        status="PENDING",
        status_url=f"/job/{job_id}",
    )


@router.get("/job/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    request = await crud.get_request(job_id)
    if not request:
        _raise_contract_error(404, ERROR_JOB_NOT_FOUND, "Job was not found")

    report: dict[str, Any] = {}
    raw_report = request.get("automation_report")
    if raw_report:
        try:
            parsed = json.loads(raw_report)
            if isinstance(parsed, dict):
                report = parsed
        except json.JSONDecodeError:
            report = {"raw": raw_report}

    error_code = report.get("error_code")
    error_message = request.get("error_message")
    if error_message and ":" in error_message and not error_code:
        maybe_code, maybe_message = error_message.split(":", 1)
        if maybe_code.startswith("ERROR_") or maybe_code.isupper():
            error_code = maybe_code.strip()
            error_message = maybe_message.strip()

    return JobStatusResponse(
        job_id=request["id"],
        status=request.get("status"),
        request_type=request.get("type"),
        project_id=request.get("project_id") or report.get("project_id"),
        scene_id=request.get("scene_id") or report.get("scene_id"),
        uploaded_media_id=request.get("media_id"),
        output_url=request.get("output_url"),
        error_code=error_code,
        error_message=error_message,
        report=report,
        created_at=request.get("created_at"),
        updated_at=request.get("updated_at"),
    )
