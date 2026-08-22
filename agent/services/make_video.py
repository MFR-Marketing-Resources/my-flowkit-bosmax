"""End-to-end automated video pipeline (flowCreationAgent).

One async job does everything: create project -> AI start frame -> agent session ->
negotiate + approve (1 video, Veo 3.1 Lite) -> wait for the render -> navigate the
Flow tab to the project + harvest the video media_id -> get_media returns the bytes
(base64 encodedVideo) -> save the .mp4 into the system. Poll GET /video-job/{id}.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
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
    "PRODUCT_FIDELITY_REVIEW_REQUIRED",
    "FAILED",
    "REJECTED",
    "ARTIFACT_PERSISTENCE_FAILED",
    "DURABILITY_SYNC_FAILED",
    "RECOVERY_REQUIRED",
    "RECOVERY_UNRECOVERABLE",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
})

# These states have stopped the process-local task, but the durable row still
# owns a provider handle or a retrieved file that can be reconciled without a
# second generation submit.  Keep them separate from the terminal set used by
# the in-memory lane GC: a backend restart must revisit these rows.
_DURABLE_RECOVERY_STATUSES = frozenset({
    "SUBMITTED",
    "SETUP",
    "GENERATING",
    "RECOVERY_REQUIRED",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
    "ARTIFACT_PERSISTING",
    "ARTIFACT_PERSISTENCE_FAILED",
    "RETRIEVED_NOT_REGISTERED",
})

_DURABLE_RECOVERY_LOCKS: dict[str, asyncio.Lock] = {}

# Owner-authorized, one-shot transport discovery.  This is deliberately a
# separate capture boundary: normal Hybrid 10s production continues to fail
# closed on DIRECT_10S_CONTRACT_NOT_CERTIFIED until a captured contract is
# reviewed and released.
HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS = (
    "HYBRID_REFERENCE_OMNI_10S_CONTRACT_CAPTURE"
)
HYBRID_REFERENCE_OMNI_10S_CAPTURE_PRODUCT_ID = (
    "243bf466-8a42-40b3-a75b-e3068cc430f6"
)


def hybrid_reference_omni10_capture_enabled() -> bool:
    return os.environ.get("HYBRID_REFERENCE_OMNI_10S_CAPTURE_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _capture_contract_reject(reason: str) -> dict:
    return {
        "status": "REJECTED",
        "error": reason,
        "capture_class": HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS,
        "pre_provider": {
            "classification": "BLOCKED",
            "provider_calls": 0,
            "credit_spend": False,
            "blocker_code": reason.split(":", 1)[0],
        },
    }


def _capture_reference_routing_receipt(reference_media_ids: list[str]) -> dict:
    refs = [str(media_id) for media_id in (reference_media_ids or []) if media_id]
    return {
        "logical_mode": "F2V",
        "surface_lane": "HYBRID",
        "source_mode": "HYBRID",
        "reference_requested": True,
        "has_reference": bool(refs),
        "reference_uploaded": bool(refs),
        "reference_count": len(refs),
        "reference_media_ids": refs,
        "reference_contract": "valid",
        "reference_contract_code": None,
        "reference_contract_detail": "owner-authorized capture-only boundary",
        "reference_mode_authorized": True,
        "selected_execution_route": "CAPTURE_AGENT_DISCOVERY",
        "text_only_allowed": False,
        "TEXT_ONLY_TOOL_ALLOWED": False,
        "approval_allowed": True,
        "capture_only": True,
        "pre_provider": {
            "classification": "READY",
            "provider_calls": 0,
            "credit_spend": False,
            "selected_route": "CAPTURE_AGENT_DISCOVERY",
            "blocker_code": None,
        },
    }


def _capture_credit_balance(response: dict | None):
    """Extract only a numeric balance from the credits response."""
    if not isinstance(response, dict):
        return None
    candidates = []
    stack = [response]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                token = str(key).lower().replace("_", "")
                if token in {"credits", "creditbalance", "remainingcredits", "balance"}:
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        candidates.append(value)
                    elif isinstance(value, dict):
                        stack.append(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return candidates[0] if candidates else None


def _measure_video_duration(local_path: str | None):
    if not local_path:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(local_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        value = float((result.stdout or "").strip())
        return round(value, 3) if value >= 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _classify_reference_contract_capture(job: dict) -> str:
    evidence = job.get("capture_contract_evidence") or {}
    if job.get("approved") is not True:
        return "CAPTURE_FAILED_PRE_PROVIDER"
    if evidence.get("text_only_tool_observed"):
        return "WRONG_TRANSPORT"
    if not evidence.get("reference_aware_tool_observed") or not evidence.get(
        "reference_forwarded_to_generation"
    ):
        return "REFERENCE_DROPPED"
    if job.get("model_ok") is False:
        return "CAPTURE_WRONG_MODEL_AFTER_APPROVAL"
    if job.get("duration_ok") is False:
        return "CAPTURE_WRONG_DURATION_AFTER_APPROVAL"
    if job.get("model_ok") is not True or job.get("duration_ok") is not True:
        return "PROVIDER_OUTCOME_UNCERTAIN"
    if job.get("status") not in {"DONE", "PRODUCT_FIDELITY_REVIEW_REQUIRED"}:
        return "PROVIDER_OUTCOME_UNCERTAIN"
    return "REFERENCE_OMNI_10S_CONTRACT_CAPTURED"


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


def _single_logical_job_key(job_id: str, idempotency_key: str | None = None) -> str:
    """Stable identity for the standard one-door SINGLE lane.

    The existing ``video_production_job`` ledger is also the recovery index for
    short jobs.  A caller-provided idempotency key deduplicates a replay; when a
    caller has no key, the generated job id intentionally makes the request a
    distinct logical intent.
    """
    material = str(idempotency_key or job_id).strip()
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"ljk_single_{digest}"


def _durable_single_snapshot(job: dict) -> dict:
    """JSON-safe state used for restart/readiness/retry recovery."""
    return json.loads(json.dumps(
        {k: v for k, v in job.items() if k != "_task"},
        ensure_ascii=False,
        default=str,
    ))


async def _prepare_durable_single_job(
    job: dict,
    *,
    idempotency_key: str | None = None,
    strict: bool = False,
) -> tuple[dict | None, bool]:
    """Create the standard SINGLE lifecycle row before its task can run.

    ``strict`` is used by the HTTP generation boundary.  Unit/programmatic
    callers that intentionally exercise the isolated in-memory lane may omit a
    request key; those callers retain their existing fixture behaviour, while a
    real API request fails closed before provider work if the ledger is down.
    """
    from agent.db import crud

    key = _single_logical_job_key(job["job_id"], idempotency_key)
    try:
        existing = await crud.get_video_production_job_by_logical_key(key)
        if existing:
            return existing, existing.get("job_id") == job.get("job_id")
        snapshot = _durable_single_snapshot(job)
        await crud.create_video_production_job_full(
            job["job_id"],
            logical_job_key=key,
            status="SUBMITTED",
            project_id=job.get("project_id"),
            requested_duration_seconds=int(job.get("duration_s") or 8),
            product_id=job.get("product_id"),
            staff_id=job.get("staff_id"),
            staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
            engine="GOOGLE_FLOW_API_FIRST",
            model=job.get("model"),
            aspect_ratio=job.get("aspect"),
            plan_fingerprint=hashlib.sha256(
                json.dumps(
                    {
                        "mode": job.get("mode"),
                        "prompt": job.get("prompt"),
                        "source_mode": job.get("source_mode"),
                        "production_recipe": job.get("production_recipe"),
                        "references": job.get("reference_media_ids")
                        or job.get("image_media_ids")
                        or [],
                        "model": job.get("model"),
                        "duration_s": job.get("duration_s"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            whole_plan_json=json.dumps(
                {
                    "execution_mode": "SINGLE",
                    "lane": "MAKE_VIDEO_ONE_DOOR",
                    "request_id": idempotency_key,
                    "mode": job.get("mode"),
                    "source_mode": job.get("source_mode"),
                    "production_recipe": job.get("production_recipe"),
                    "product_id": job.get("product_id"),
                    "project_id": job.get("project_id"),
                    "staff_id": job.get("staff_id"),
                    "staff_display_name": job.get("staff_display_name_snapshot"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            initial_mode=job.get("mode"),
            initial_prompt_text=job.get("prompt") or "",
            initial_asset_media_id=(job.get("image_media_ids") or [None])[0],
            initial_reference_media_ids_json=json.dumps(
                job.get("image_media_ids") or [],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            initial_source_mode=job.get("source_mode"),
            surface_lane=job.get("surface_lane"),
            transport_mode=job.get("transport_mode") or job.get("mode"),
            source_mode=job.get("source_mode"),
            provider_generation_type=job.get("provider_generation_type"),
            initial_lane_job_id=job.get("job_id"),
            initial_lane_project_id=job.get("project_id"),
            stage_state_json=json.dumps(snapshot, ensure_ascii=False),
        )
        row = await crud.get_video_production_job(job["job_id"])
        if not row:
            raise RuntimeError("DURABLE_SINGLE_LEDGER_ROW_MISSING")
        return row, True
    except Exception as exc:  # noqa: BLE001 — caller decides strictness
        job["durable_ledger_error"] = str(exc)
        if strict:
            raise RuntimeError(
                "DURABLE_SINGLE_LEDGER_UNAVAILABLE:" + str(exc)[:240]
            ) from exc
        return None, True


async def _sync_durable_single_job(job: dict | None) -> None:
    """Mirror terminal/in-flight state into the existing lifecycle ledger."""
    if not job or not str(job.get("job_id") or "").startswith("g_"):
        return
    from agent.db import crud

    try:
        row = await crud.get_video_production_job(job["job_id"])
        if not row:
            return
        media_id = job.get("media_id") or job.get("video_media_id")
        local_path = job.get("local_path")
        file_sha256 = None
        file_size_bytes = None
        evidence = job.get("artifact_file_evidence") or {}
        if media_id and isinstance(evidence, dict):
            media_evidence = evidence.get(str(media_id)) or evidence.get("default")
            if isinstance(media_evidence, dict):
                file_sha256 = media_evidence.get("sha256")
                file_size_bytes = media_evidence.get("size_bytes")
        if media_id and not file_sha256 and local_path:
            try:
                from agent.services.video_artifact_delivery_service import (
                    file_delivery_evidence,
                )

                media_evidence = file_delivery_evidence(str(local_path))
                file_sha256 = media_evidence["sha256"]
                file_size_bytes = media_evidence["size_bytes"]
                job.setdefault("artifact_file_evidence", {})[str(media_id)] = media_evidence
            except Exception:
                # The persisted lifecycle still records the output identity; the
                # artifact delivery state remains retryable and non-green.
                pass
        provider_operation_ids = job.get("provider_operation_ids") or []
        first_operation_id = None
        for value in provider_operation_ids:
            if isinstance(value, dict):
                value = (
                    value.get("operation_id")
                    or value.get("operation_name")
                    or value.get("name")
                    or value.get("provider_operation_id")
                )
            if value:
                first_operation_id = str(value)
                break
        if not first_operation_id:
            identity = job.get("generation_identity") or {}
            if isinstance(identity, dict):
                names = identity.get("operation_names") or []
                if names:
                    first_operation_id = str(names[0])
        targets = job.get("direct_media_targets") or []
        first_workflow_id = None
        if targets and isinstance(targets[0], dict):
            first_workflow_id = (
                targets[0].get("workflow_id")
                or targets[0].get("workflowId")
            )
        state = _durable_single_snapshot(job)
        if first_operation_id or targets:
            state.setdefault("provider_generation_submit_count", 1)
            state["provider_resubmission"] = False
            state["resubmission_allowed"] = False
        terminal_with_output = {
            "DONE",
            "PRODUCT_FIDELITY_REVIEW_REQUIRED",
            "ARTIFACT_PERSISTENCE_FAILED",
        }
        await crud.update_video_production_job_full(
            job["job_id"],
            status=job.get("status") or "UNKNOWN",
            error_code=(
                (job.get("error") or job.get("artifact_record_error"))
                if job.get("status") != "DONE"
                else None
            ),
            project_id=job.get("project_id") or row.get("project_id"),
            initial_media_id=media_id,
            initial_operation_id=first_operation_id,
            initial_workflow_id=str(first_workflow_id) if first_workflow_id else None,
            final_media_id=media_id if media_id and job.get("status") in terminal_with_output else None,
            final_local_path=(str(local_path) if local_path and job.get("status") in terminal_with_output else None),
            final_sha256=file_sha256 if job.get("status") in terminal_with_output else None,
            final_duration_s=job.get("duration_used") or job.get("duration_s"),
            initial_lane_job_id=job.get("job_id"),
            initial_lane_project_id=job.get("project_id") or row.get("project_id"),
            surface_lane=job.get("surface_lane") or row.get("surface_lane"),
            transport_mode=job.get("transport_mode") or row.get("transport_mode") or job.get("mode"),
            source_mode=job.get("source_mode") or row.get("source_mode") or row.get("initial_source_mode"),
            provider_generation_type=(
                job.get("provider_generation_type")
                or row.get("provider_generation_type")
            ),
            stage_state_json=json.dumps(state, ensure_ascii=False),
            initial_correlation_json=json.dumps(
                job.get("output_correlation")
                or job.get("generation_identity")
                or None,
                ensure_ascii=False,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — a terminal success needs honest state
        job["status"] = "DURABILITY_SYNC_FAILED"
        job["durability_sync_error"] = str(exc)
        job["error"] = str(exc)


def _durable_state_from_row(row: dict) -> dict:
    try:
        state = json.loads(row.get("stage_state_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    return state if isinstance(state, dict) else {}


def _durable_public_state(row: dict, state: dict, *, status: str | None = None) -> dict:
    """Merge the DB lifecycle row and its JSON snapshot for API/status readers."""
    merged = dict(state or {})
    effective_status = str(status or row.get("status") or "UNKNOWN")
    merged.update({
        "job_id": row.get("job_id"),
        "status": effective_status,
        "error": row.get("error_code") or merged.get("error"),
        "media_id": row.get("final_media_id")
        or row.get("initial_media_id")
        or merged.get("media_id"),
        "local_path": row.get("final_local_path") or merged.get("local_path"),
        "project_id": row.get("project_id") or merged.get("project_id"),
        "recovery_required": bool(
            merged.get("recovery_required")
            or effective_status in _DURABLE_RECOVERY_STATUSES
        ),
        "durable": True,
        "provider_generation_submit_count": int(
            merged.get("provider_generation_submit_count")
            or (1 if (
                merged.get("provider_operation_ids")
                or merged.get("direct_media_targets")
                or row.get("initial_operation_id")
                or row.get("initial_media_id")
            ) else 0)
        ),
        "provider_generation_submits": 0,
        "provider_resubmission": False,
        "resubmission_allowed": False,
    })
    # Historical Phase-B rows used PROVIDER_REJECTED for a generation that was
    # approved and then proved to use the wrong settings. Do not rewrite the
    # stored artifact: expose a deterministic derived primary classification with
    # the legacy value and source fields retained for provenance.
    if merged.get("capture_contract_verdict") == "PROVIDER_REJECTED":
        derived = _classify_reference_contract_capture(merged)
        if derived != "PROVIDER_REJECTED":
            merged["capture_contract_verdict_legacy"] = "PROVIDER_REJECTED"
            merged["capture_contract_verdict"] = derived
            merged["capture_contract_verdict_provenance"] = {
                "kind": "DERIVED_VIEW_NO_HISTORICAL_REWRITE",
                "reason": "approved generation has explicit post-approval model/duration mismatch",
                "source_fields": {
                    "approved": merged.get("approved"),
                    "model_ok": merged.get("model_ok"),
                    "duration_ok": merged.get("duration_ok"),
                    "error": merged.get("error"),
                },
            }
    return merged


def _provider_operation_name(value) -> str | None:
    if isinstance(value, dict):
        operation = value.get("operation")
        if isinstance(operation, dict):
            value = operation.get("name") or operation.get("operation_id")
        else:
            value = (
                value.get("operation_id")
                or value.get("operation_name")
                or value.get("provider_operation_id")
                or value.get("name")
            )
    value = str(value or "").strip()
    return value or None


def _durable_provider_handles(row: dict, state: dict) -> tuple[str | None, list, str | None]:
    """Resolve only identities persisted before/at provider acceptance.

    Direct media targets are preferred because they are the current Flow status
    contract. Legacy operation handles remain supported for older rows.  No
    value is manufactured from a prompt, project URL, or process-local map.
    """
    project_id = str(
        row.get("project_id") or state.get("project_id") or ""
    ).strip()
    raw_targets = state.get("direct_media_targets")
    if isinstance(raw_targets, list):
        targets = []
        for raw in raw_targets:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or raw.get("media_id") or "").strip()
            target_project = str(
                raw.get("projectId")
                or raw.get("project_id")
                or project_id
                or ""
            ).strip()
            if name and target_project:
                targets.append({"name": name, "projectId": target_project})
        if targets:
            return "media", targets, None

    # A synced row carries initial_media_id even when an older snapshot did not
    # retain the list-shaped direct target.  This is still safe only with the
    # exact provider project id.
    media_id = str(
        state.get("media_id")
        or row.get("initial_media_id")
        or ""
    ).strip()
    if media_id and project_id:
        return "media", [{"name": media_id, "projectId": project_id}], None

    raw_operations = state.get("provider_operation_ids")
    if not isinstance(raw_operations, list):
        identity = state.get("generation_identity")
        raw_operations = identity.get("operation_names") if isinstance(identity, dict) else []
    if not isinstance(raw_operations, list):
        raw_operations = []
    if row.get("initial_operation_id"):
        raw_operations = [row["initial_operation_id"], *raw_operations]
    operations = []
    seen = set()
    for raw in raw_operations:
        name = _provider_operation_name(raw)
        if name and name not in seen:
            seen.add(name)
            operations.append({"operation": {"name": name}})
    if operations:
        return "operation", operations, None

    if (state.get("direct_media_targets") or media_id) and not project_id:
        return None, [], "DURABLE_PROVIDER_PROJECT_ID_MISSING"
    return None, [], "DURABLE_PROVIDER_IDENTITY_INSUFFICIENT"


def _durable_recovery_job(row: dict, state: dict) -> dict:
    """Rebuild the poll/retrieve job envelope without inventing a submit."""
    job = dict(state)
    job.update({
        "job_id": row.get("job_id"),
        "durable": True,
        "mode": state.get("mode") or row.get("initial_mode") or "F2V",
        "source_mode": state.get("source_mode") or row.get("initial_source_mode"),
        "surface_lane": state.get("surface_lane") or row.get("surface_lane"),
        "transport_mode": state.get("transport_mode") or row.get("transport_mode") or state.get("mode") or row.get("initial_mode"),
        "provider_generation_type": state.get("provider_generation_type") or row.get("provider_generation_type"),
        "prompt": state.get("prompt") or row.get("initial_prompt_text") or "",
        "model": state.get("model") or row.get("model"),
        "aspect": state.get("aspect") or row.get("aspect_ratio") or "9:16",
        "duration_s": state.get("duration_s") or row.get("requested_duration_seconds") or 8,
        "project_id": state.get("project_id") or row.get("project_id"),
        "product_id": state.get("product_id") or row.get("product_id"),
        "request_id": state.get("request_id"),
        "num_videos": int(state.get("num_videos") or 1),
        "strict_artifact_delivery": True,
        "resubmission_allowed": False,
        "provider_resubmission": False,
        "provider_generation_submit_count": int(
            state.get("provider_generation_submit_count") or 1
        ),
    })
    return job


async def _check_direct_media_targets_once(client, targets: list[dict]) -> dict:
    """Make one provider status call; a scheduler tick must never hold 15 min."""
    try:
        result = await client.check_video_status_by_media(targets)
    except Exception as exc:  # noqa: BLE001 — retain the handle for a later tick
        return {"state": "POLL_ERROR", "error": str(exc)[:400]}
    if not isinstance(result, dict) or result.get("error"):
        return {"state": "POLL_ERROR", "error": str((result or {}).get("error") or "empty status response")[:400]}
    entries = _direct_media_entries(result)
    by_name = {str(m.get("name")): m for m in entries if m.get("name")}
    names = {str(t.get("name")) for t in targets if t.get("name")}
    failed = [
        (name, _direct_media_status(by_name[name]))
        for name in names
        if name in by_name
        and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_FAILED"
    ]
    if failed:
        return {"state": "FAILED", "error": f"Media generation failed: {failed[0][0]}", "data": result}
    if names and all(
        name in by_name
        and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        for name in names
    ):
        return {"state": "SUCCESS", "data": result}
    return {"state": "PENDING", "data": result}


async def _check_direct_operations_once(client, operations: list[dict]) -> dict:
    """Make one legacy operation status call for restart reconciliation."""
    try:
        result = await client.check_video_status(operations)
    except Exception as exc:  # noqa: BLE001 — retain the handle for a later tick
        return {"state": "POLL_ERROR", "error": str(exc)[:400]}
    if not isinstance(result, dict) or result.get("error"):
        return {"state": "POLL_ERROR", "error": str((result or {}).get("error") or "empty status response")[:400]}
    data = _direct_response_data(result)
    ops = data.get("operations") if isinstance(data, dict) else []
    if not ops:
        return {"state": "PENDING", "data": result}
    statuses = [str(op.get("status") or "") for op in ops if isinstance(op, dict)]
    if any(status == "MEDIA_GENERATION_STATUS_FAILED" for status in statuses):
        return {"state": "FAILED", "error": "Provider operation failed", "data": result}
    if statuses and all(status == "MEDIA_GENERATION_STATUS_SUCCESSFUL" for status in statuses):
        return {"state": "SUCCESS", "data": result}
    return {"state": "PENDING", "data": result}


async def _reconcile_artifacts_only(job: dict) -> bool:
    """Retry a retrieved file/library registration without touching the provider."""
    artifacts = job.get("artifacts") or []
    if not artifacts and job.get("media_id") and job.get("local_path"):
        artifacts = [{
            "media_id": job.get("media_id"),
            "local_path": job.get("local_path"),
            "size_mb": job.get("size_mb"),
        }]
        job["artifacts"] = artifacts
    if not artifacts:
        return False
    job["status"] = "ARTIFACT_PERSISTING"
    await _record_artifacts(job, job.get("mode") or "F2V", artifacts)
    return True


async def reconcile_durable_single_job(
    job_id: str,
    *,
    provider_client=None,
) -> dict | None:
    """Resume one persisted SINGLE job using its exact provider identity.

    This function is deliberately submit-free.  It performs at most one status
    call per invocation, retrieves only a provider-terminal target, and then
    registers the local artifact.  A pending/error response leaves the exact
    handle in the ledger for the next scheduler/startup tick.
    """
    from agent.db import crud

    row = await crud.get_video_production_job(job_id)
    if not row or not str(row.get("job_id") or "").startswith("g_"):
        return None
    lock = _DURABLE_RECOVERY_LOCKS.setdefault(job_id, asyncio.Lock())
    async with lock:
        row = await crud.get_video_production_job(job_id)
        if not row:
            return None
        state = _durable_state_from_row(row)
        status = str(row.get("status") or "UNKNOWN")
        if status not in _DURABLE_RECOVERY_STATUSES:
            return _durable_public_state(row, state)

        job = _durable_recovery_job(row, state)
        job["recovery_required"] = True
        job["recovery_attempts"] = int(state.get("recovery_attempts") or 0) + 1
        job["provider_generation_submit_count"] = max(
            1,
            int(state.get("provider_generation_submit_count") or 0),
        )
        job["provider_reconciliation"] = {
            **(
                state.get("provider_reconciliation")
                if isinstance(state.get("provider_reconciliation"), dict)
                else {}
            ),
            "provider_generation_submits": 0,
            "provider_resubmission": False,
            "last_attempt": time.time(),
        }

        # A process can die after retrieval and before the two library writes.
        # The artifact list is enough to repair locally; no provider poll is
        # needed and no provider identity is required for this branch.
        if status in {"ARTIFACT_PERSISTING", "ARTIFACT_PERSISTENCE_FAILED", "RETRIEVED_NOT_REGISTERED"} or (
            state.get("provider_terminal") is True and state.get("artifacts")
        ):
            try:
                if await _reconcile_artifacts_only(job):
                    await _sync_durable_single_job(job)
                    fresh = await crud.get_video_production_job(job_id)
                    return _durable_public_state(
                        fresh or row,
                        _durable_state_from_row(fresh or row),
                    )
            except Exception as exc:  # noqa: BLE001 — preserve retryable evidence
                job["status"] = "ARTIFACT_PERSISTENCE_FAILED"
                job["artifact_record_error"] = str(exc)
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )

        handle_kind, handles, identity_error = _durable_provider_handles(row, state)
        if not handle_kind:
            job.update(
                status="RECOVERY_UNRECOVERABLE",
                stage="recovery_unrecoverable",
                recovery_unrecoverable=True,
                error=identity_error,
                recovery_hint=(
                    "The durable row has no complete provider operation/media identity "
                    "and cannot be resumed safely. No provider resubmission is allowed."
                ),
            )
            job["provider_reconciliation"].update({
                "state": "UNRECOVERABLE",
                "error_code": identity_error,
            })
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )

        if handle_kind == "media":
            job["direct_media_targets"] = handles
            job["provider_operation_ids"] = [str(t["name"]) for t in handles]
        else:
            job["provider_operation_ids"] = handles
            job["generation_identity"] = {
                **(
                    state.get("generation_identity")
                    if isinstance(state.get("generation_identity"), dict)
                    else {}
                ),
                "operation_names": [
                    str((op.get("operation") or {}).get("name"))
                    for op in handles
                    if (op.get("operation") or {}).get("name")
                ],
                "provider_generation_submit_count": 1,
            }

        client = provider_client
        if client is None:
            client = get_flow_client()
        if handle_kind == "media":
            poll = await _check_direct_media_targets_once(client, handles)
        else:
            poll = await _check_direct_operations_once(client, handles)
        job["provider_reconciliation"].update({
            "state": poll.get("state"),
            "error": poll.get("error"),
            "handle_kind": handle_kind,
            "provider_handle_count": len(handles),
        })
        if poll.get("state") == "PENDING":
            job.update(
                status="RECOVERY_REQUIRED",
                stage="provider_poll_pending",
                error="DURABLE_PROVIDER_POLL_PENDING",
                recovery_hint=(
                    "Provider operation is still rendering. The persisted handle will "
                    "be polled again; no provider resubmission is allowed."
                ),
            )
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )
        if poll.get("state") != "SUCCESS":
            job.update(
                status="GENERATED_BUT_UNRETRIEVED",
                stage="provider_reconciliation_error",
                error=poll.get("error") or "DURABLE_PROVIDER_POLL_FAILED",
                recovery_hint=(
                    "The provider handle remains durable and can be polled again. "
                    "Do not resubmit the generation."
                ),
            )
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )

        job["provider_terminal"] = True
        job["provider_status"] = "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        plan = state.get("direct_plan") if isinstance(state.get("direct_plan"), dict) else {
            "gen_type": (state.get("generation_identity") or {}).get("gen_type")
            if isinstance(state.get("generation_identity"), dict)
            else "reference_frame_2_video",
            "aspect_enum": "VIDEO_ASPECT_RATIO_PORTRAIT",
        }
        seed = (state.get("generation_identity") or {}).get("seed", 0)
        try:
            if handle_kind == "media":
                await _direct_media_retrieve_from_poll(
                    job,
                    client,
                    job.get("mode") or "F2V",
                    handles,
                    plan,
                    seed,
                    int(job.get("num_videos") or 1),
                    poll.get("data") or {},
                )
            else:
                await _direct_operation_retrieve_from_poll(
                    job,
                    client,
                    job.get("mode") or "F2V",
                    poll.get("data") or {},
                    plan,
                    seed,
                    int(job.get("num_videos") or 1),
                )
        except Exception as exc:  # noqa: BLE001 — retain provider terminal identity
            job.update(
                status="GENERATED_BUT_UNRETRIEVED",
                stage="provider_terminal_retrieval_failed",
                error=str(exc),
                recovery_hint=(
                    "Provider is terminal but retrieval failed. Keep polling/retrieving "
                    "the persisted identity; never resubmit."
                ),
            )
        await _sync_durable_single_job(job)
        fresh = await crud.get_video_production_job(job_id)
        return _durable_public_state(
            fresh or row,
            _durable_state_from_row(fresh or row),
        )


async def get_durable_job(
    job_id: str,
    *,
    reconcile: bool = True,
    provider_client=None,
) -> dict | None:
    """Read/resume a standard job after the process-local map is gone."""
    from agent.db import crud

    row = await crud.get_video_production_job(job_id)
    if not row or not str(row.get("job_id") or "").startswith("g_"):
        return None
    state = _durable_state_from_row(row)
    status = str(row.get("status") or "UNKNOWN")
    if reconcile and status in _DURABLE_RECOVERY_STATUSES:
        return await reconcile_durable_single_job(
            job_id,
            provider_client=provider_client,
        )
    return _durable_public_state(row, state)


async def recover_durable_single_jobs(*, provider_client=None) -> dict:
    """Startup sweep: poll/retrieve/register persisted SINGLE identities once."""
    from agent.db import crud

    candidates = 0
    recovered = 0
    unrecoverable = 0
    provider_calls = 0
    for row in await crud.list_video_production_jobs(limit=1000):
        job_id = str(row.get("job_id") or "")
        if not job_id.startswith("g_"):
            continue
        status = str(row.get("status") or "")
        if status not in _DURABLE_RECOVERY_STATUSES:
            continue
        candidates += 1
        try:
            result = await reconcile_durable_single_job(
                job_id,
                provider_client=provider_client,
            )
            if isinstance(result, dict):
                reconciliation = result.get("provider_reconciliation") or {}
                if reconciliation.get("state") not in (None, "UNRECOVERABLE"):
                    provider_calls += 1
                if result.get("status") == "DONE":
                    recovered += 1
                if result.get("status") == "RECOVERY_UNRECOVERABLE":
                    unrecoverable += 1
        except Exception as exc:  # noqa: BLE001 — preserve a retryable row
            state = _durable_state_from_row(row)
            state.update({
                "recovery_required": True,
                "recovery_hint": (
                    "Provider reconciliation raised a transient error. The persisted "
                    "identity remains the only allowed retry target; no resubmission."
                ),
                "provider_reconciliation": {
                    "state": "POLL_ERROR",
                    "error": str(exc)[:400],
                    "provider_generation_submits": 0,
                },
            })
            await crud.update_video_production_job_full(
                job_id,
                status="RECOVERY_REQUIRED",
                error_code="DURABLE_RECOVERY_ATTEMPT_FAILED",
                stage_state_json=json.dumps(state, ensure_ascii=False),
            )
    return {
        "candidates": candidates,
        "recovered": recovered,
        "unrecoverable": unrecoverable,
        "provider_calls": provider_calls,
        "provider_generation_submits": 0,
        "marked_recovery_required": 0,
    }


async def _run_generate_task(job_id: str, runner, *args) -> None:
    """Run a process-local task while keeping the durable lifecycle mirror current."""
    try:
        await runner(job_id, *args)
    finally:
        await _sync_durable_single_job(_JOBS.get(job_id))
        try:
            from agent.db import crud as _single_crud

            await _single_crud.release_video_generation_lane_lease(job_id)
        except Exception:  # noqa: BLE001 - cleanup must not mask lifecycle evidence
            pass


async def _run_reference_contract_capture(
    job_id, mode, prompt, project_id, image_media_ids,
    image_prompt, aspect, tier, model=None, duration_s=None,
    num_videos=1, image_model=None, max_image_attempts=8,
    collect_image_variants=False, product_id=None, copy_execution_binding=None,
):
    """Run the existing API-first agent lane behind the temporary capture gate."""
    await _run_generate(
        job_id, mode, prompt, project_id, image_media_ids, image_prompt,
        aspect, tier, model, duration_s, num_videos, image_model,
        max_image_attempts, collect_image_variants, product_id,
        copy_execution_binding,
    )
    job = _JOBS.get(job_id)
    if not job:
        return
    client = get_flow_client()
    after = None
    try:
        after = _capture_credit_balance(await client.get_credits())
    except Exception as exc:  # noqa: BLE001 - accounting stays explicit/unknown
        job["credit_balance_after_error"] = str(exc)[:240]
    job["credit_balance_after"] = after
    before = (job.get("capture_subject") or {}).get("credit_balance_before")
    delta = None
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        delta = before - after
    job["credit_accounting"] = {
        "balance_before": before,
        "balance_after": after,
        "delta": delta,
        "generation_submit_count": int(job.get("provider_generation_submit_count") or 0),
        "actual_cost_observed": delta is not None,
    }
    media_evidence = {}
    for artifact in job.get("artifacts") or []:
        media_id = str(artifact.get("media_id") or "")
        path = artifact.get("local_path")
        if not media_id or not path:
            continue
        try:
            from agent.services.video_artifact_delivery_service import file_delivery_evidence

            evidence = file_delivery_evidence(str(path))
        except Exception as exc:  # noqa: BLE001 - keep capture evidence honest
            media_evidence[media_id] = {"error": str(exc)[:240]}
            continue
        measured = _measure_video_duration(str(path))
        evidence["measured_duration_s"] = measured
        evidence["provider_duration_s"] = job.get("duration_used")
        media_evidence[media_id] = evidence
        artifact["measured_duration_s"] = measured
    job["capture_media_evidence"] = media_evidence
    job["capture_contract_verdict"] = _classify_reference_contract_capture(job)
    await _sync_durable_single_job(job)


async def retry_artifact_delivery(job_id: str) -> dict:
    """Retry only local artifact registration; never re-submit a provider job."""
    job = _JOBS.get(job_id)
    if job is None:
        from agent.db import crud

        row = await crud.get_video_production_job(job_id)
        if not row:
            raise KeyError(job_id)
        try:
            job = json.loads(row.get("stage_state_json") or "{}")
        except (TypeError, ValueError):
            job = {}
        if not isinstance(job, dict):
            job = {}
        job["job_id"] = job_id
    artifacts = job.get("artifacts") or []
    if not artifacts:
        raise RuntimeError("ARTIFACT_DELIVERY_RETRY_DATA_MISSING")
    await _record_artifacts(job, job.get("mode") or "F2V", artifacts)
    if job_id in _JOBS:
        _JOBS[job_id].update(job)
    await _sync_durable_single_job(job)
    return _durable_single_snapshot(job)


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


async def start(prompt: str, image_prompt: str, product_id: str | None = None) -> dict:
    job_id = "v_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                     "project_id": None, "product_id": product_id,
                     "local_path": None, "video_media_id": None,
                     "size_mb": None, "error": None}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run(job_id, prompt, image_prompt, product_id)
    )
    return {"job_id": job_id, "status": "SUBMITTED"}


async def start_negotiate(prompt: str, image_prompt: str = None, dry: bool = True,
                          model: str = None, duration_s: int = None,
                          project_id: str = None,
                          reference_media_ids: list[str] | None = None) -> dict:
    """Async negotiation job — captures the FULL transcript (so a client timeout never
    loses it). dry=True stops before approving (0 video credits). model/duration steer the
    agent (patch I4a); project_id reuses an existing project (minimise junk); image_prompt=None
    skips the start frame (pure T2V dry capture). Existing reference_media_ids are passed
    through unchanged so a dry negotiation can audit the real reference contract without
    creating or uploading a new media target."""
    job_id = "n_" + uuid4().hex[:12]
    refs = [str(media_id) for media_id in (reference_media_ids or []) if media_id]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                      "project_id": project_id, "dry": dry, "model": model,
                      "duration_s": duration_s, "reference_media_ids": refs,
                      "result": None, "transcript": None, "error": None,
                      "created": time.time()}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_negotiate(job_id, prompt, image_prompt, dry, model, duration_s,
                       project_id, refs))
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
ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL = (
    "ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL"
)
DIRECT_10S_CONTRACT_NOT_CERTIFIED = "DIRECT_10S_CONTRACT_NOT_CERTIFIED"
DIRECT_VIDEO_READINESS_CONTRACT_VERSION = "direct-video-readiness-v1"


def _pre_dispatch_generation_type(
    product_visual_custody: dict | None,
    direct_plan: dict | None,
) -> str:
    """Resolve the generation type used by the product-custody route guard.

    Exact-product T2V deliberately declines the direct reference plan and uses
    the agent scene-scaffold lane. That declined plan has no ``gen_type``;
    custody remains the authority for the required scaffold/composite contract.
    """
    if (
        isinstance(product_visual_custody, dict)
        and product_visual_custody.get("provider_route")
        == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    ):
        return str(
            product_visual_custody.get("generation_type")
            or "scene_video_scaffold_then_deterministic_composite"
        )
    return str((direct_plan or {}).get("gen_type") or "reference_frame_2_video")


def _build_reference_routing_receipt(
    mode: str,
    source_mode: str | None,
    image_media_ids: list | None,
    plan: dict | None,
) -> dict:
    """Build the provider-free routing proof for the one-door video service.

    A reference-bearing request is safe only when the selected route is the
    captured direct reference-aware lane.  The conversational agent does not
    expose enough pre-approval protocol evidence to prove which generation tool
    it will fire, so it is deliberately not an eligible fallback for references.
    Pure T2V remains on the captured agent lane and explicitly permits its
    text-only tool.
    """
    mode = (mode or "").upper()
    normalized_source_mode = str(source_mode or "").strip().upper() or None
    reference_media_ids = [str(media_id) for media_id in (image_media_ids or []) if media_id]
    has_reference = bool(reference_media_ids)
    reference_requested = mode in ("F2V", "I2V") or has_reference

    from agent.services import flow_mode_reference_contract as _refc

    contract_ok, contract_code, contract_detail = _refc.validate_reference_count(
        mode, len(reference_media_ids), source_mode=normalized_source_mode
    )
    reference_contract = "valid" if contract_ok else "invalid"
    direct_eligible = bool(plan and plan.get("eligible"))
    text_only_allowed = not reference_requested
    reference_mode_authorized = (
        not reference_requested or (contract_ok and direct_eligible)
    )
    if reference_requested:
        selected_route = "DIRECT_API" if direct_eligible and contract_ok else "BLOCKED_REFERENCE_ROUTE"
    elif mode == "T2V":
        selected_route = "AGENT_T2V"
    else:
        selected_route = "NON_VIDEO"

    reference_fingerprint = None
    if reference_media_ids:
        reference_fingerprint = hashlib.sha256(
            json.dumps(
                reference_media_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    return {
        "logical_mode": mode,
        "source_mode": normalized_source_mode,
        "reference_requested": reference_requested,
        "has_reference": has_reference,
        "reference_uploaded": has_reference,
        "reference_count": len(reference_media_ids),
        "reference_media_ids": reference_media_ids,
        "reference_fingerprint": reference_fingerprint,
        "reference_contract": reference_contract,
        "reference_contract_code": contract_code,
        "reference_contract_detail": contract_detail,
        "reference_mode_authorized": reference_mode_authorized,
        "selected_execution_route": selected_route,
        "text_only_allowed": text_only_allowed,
        "TEXT_ONLY_TOOL_ALLOWED": text_only_allowed,
        "approval_allowed": reference_mode_authorized,
        "route_reason": (plan or {}).get("reason"),
        "pre_provider": {
            "classification": "READY" if reference_mode_authorized else "BLOCKED",
            "provider_calls": 0,
            "credit_spend": False,
            "selected_route": selected_route,
            "blocker_code": (
                None
                if reference_mode_authorized
                else (
                    contract_code
                    or (plan or {}).get("reason")
                    or ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL
                )
            ),
        },
    }


async def _record_artifacts(job, mode, artifacts):
    """Persist every finished artifact into the system library (generated_artifact
    table) and durable Results Hub so completed videos/images survive restarts and
    are listable/downloadable from the dashboard. A delivery failure is terminal
    and retryable locally; it must never be reported as a provider-complete DONE."""
    job["artifact_persist_attempted"] = True
    job["artifact_persisted_count"] = 0
    from agent.services.video_surface_provenance import (
        build_video_surface_provenance,
    )
    provenance = build_video_surface_provenance(
        surface_lane=job.get("surface_lane"),
        transport_mode=job.get("transport_mode") or mode,
        source_mode=job.get("source_mode"),
        provider_type=job.get("provider_generation_type"),
        mode=mode,
        copy_lane=(job.get("copy_execution_binding") or {}).get("lane"),
        execution_identity=job.get("execution_identity"),
        routing_receipt=job.get("routing_receipt"),
        direct_plan=job.get("direct_plan"),
    )
    job.update(provenance)
    prior_status = job.get("status")
    delivery_retry = prior_status in {
        "DONE",
        "ARTIFACT_PERSISTING",
        "ARTIFACT_PERSISTENCE_FAILED",
        "RETRIEVED_NOT_REGISTERED",
    }
    if delivery_retry:
        job["status"] = "ARTIFACT_PERSISTING"
    custody = job.get("product_visual_custody")
    exact_route = bool(
        isinstance(custody, dict)
        and custody.get("exact_product_required")
        and custody.get("provider_route") == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    )
    if exact_route and mode in _VIDEO_MODES:
        # The retrieved provider scene is an internal scaffold.  Register only
        # deterministic final videos whose product pixels came from the
        # approved Product Truth cutout.
        try:
            from agent.services import exact_product_video_compositor_service as _exact_video
            from agent.db import crud

            product = await crud.get_product(str(custody.get("product_id") or job.get("product_id") or ""))
            if not product:
                raise _exact_video.ExactProductVideoCompositeError(
                    "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                    "Exact video compositor could not resolve the server product row.",
                )
            plan = custody.get("exact_product_video")
            if not isinstance(plan, dict):
                raise _exact_video.ExactProductVideoCompositeError(
                    "EXACT_COMPOSITE_PLAN_MISSING",
                    "Exact video custody has no compositor plan.",
                )
            final_artifacts = []
            for raw_artifact in artifacts:
                final_artifacts.append(
                    _exact_video.compose_exact_product_video_artifact(
                        product=product,
                        plan=plan,
                        scene_artifact=raw_artifact,
                        product_visual_custody=custody,
                        job_id=job.get("job_id"),
                        foreground_masks=(raw_artifact.get("foreground_masks") or []),
                    )
                )
            if not final_artifacts:
                raise _exact_video.ExactProductVideoCompositeError(
                    "EXACT_COMPOSITE_FINAL_MISSING",
                    "The provider returned no scene artifact for exact compositing.",
                )
            artifacts = final_artifacts
            job["artifacts"] = list(final_artifacts)
            job["media_id"] = final_artifacts[0].get("media_id")
            job["local_path"] = final_artifacts[0].get("local_path")
            job["size_mb"] = final_artifacts[0].get("size_mb")
            job["product_fidelity_qc_evidence"] = final_artifacts[0].get(
                "product_fidelity_qc_evidence"
            )
            custody = {
                **custody,
                "exact_video_composite": final_artifacts[0].get(
                    "exact_product_lineage"
                ),
            }
            job["product_visual_custody"] = custody
        except Exception as exc:  # noqa: BLE001 — exact output must fail closed
            job["status"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"
            job["product_fidelity_qc_status"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"
            job["generated_output_review_state"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"
            job["error"] = str(exc)
            job["exact_composite_error"] = getattr(exc, "code", "EXACT_COMPOSITE_FAILED")
            return
    try:
        from agent.db import crud
        from agent.services.video_artifact_delivery_service import file_delivery_evidence

        artifact_evidence: dict[str, dict] = {}
        strict_delivery = bool(
            job.get("strict_artifact_delivery")
            or job.get("request_id")
            or job.get("durable")
        )
        for art in artifacts:
            media_id = str(art.get("media_id") or "").strip()
            if not media_id:
                raise RuntimeError("ARTIFACT_MEDIA_ID_MISSING")
            local_path = str(art.get("local_path") or "").strip()
            try:
                evidence = file_delivery_evidence(local_path)
            except Exception:
                if strict_delivery:
                    raise
                # Legacy unit/programmatic callers may use a synthetic path;
                # real API jobs always carry strict_artifact_delivery/request_id.
                evidence = {
                    "local_path": local_path,
                    "size_bytes": None,
                    "sha256": None,
                    "unverified": True,
                }
            artifact_evidence[media_id] = evidence
        job["artifact_file_evidence"] = artifact_evidence
        for art in artifacts:
            evidence = artifact_evidence[str(art["media_id"])]
            readback = await crud.insert_generated_artifact(
                media_id=art["media_id"],
                job_id=job.get("job_id"),
                mode=mode,
                surface_lane=provenance["surface_lane"],
                transport_mode=provenance["transport_mode"],
                source_mode=provenance["source_mode"],
                provider_generation_type=provenance["provider_generation_type"],
                artifact_kind=("image" if mode == "IMG" else "video"),
                local_path=art.get("local_path"),
                size_mb=art.get("size_mb"),
                project_id=job.get("project_id"),
                model_used=job.get("model_used") or job.get("model"),
                duration_used=job.get("duration_used") or job.get("duration_s"),
                file_size_bytes=evidence["size_bytes"],
                file_sha256=evidence["sha256"],
                delivery_status="REGISTERED",
                readback_verified=True,
                staff_id=job.get("staff_id"),
                staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
            )
            if readback is not None and str(readback.get("local_path") or "") != str(art.get("local_path") or ""):
                raise RuntimeError(
                    f"ARTIFACT_READBACK_PATH_MISMATCH:{art['media_id']}"
                )
            job["artifact_persisted_count"] += 1
        # The generated_artifact row is the file/library index; generation_result
        # is the durable operator recovery record. Both are idempotent on media_id.
        for art in artifacts:
            await crud.insert_generation_result(
                art["media_id"],
                job_id=job.get("job_id"),
                request_id=job.get("request_id"),
                staff_id=job.get("staff_id"),
                staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
                mode=mode,
                artifact_kind=("image" if mode == "IMG" else "video"),
                 surface_lane=provenance["surface_lane"],
                 transport_mode=provenance["transport_mode"],
                 source_mode=provenance["source_mode"],
                 provider_generation_type=provenance["provider_generation_type"],
                product_id=job.get("product_id"),
                final_prompt_text=job.get("prompt") or "",
                aspect_ratio=job.get("aspect"),
                model_label=job.get("model_used") or job.get("model"),
                duration_s=job.get("duration_used") or job.get("duration_s"),
                count_setting=job.get("num_videos"),
                reference_media_ids=(job.get("routing_receipt") or {}).get(
                    "reference_media_ids"
                ) or [],
                project_id=job.get("project_id"),
                product_visual_custody=job.get("product_visual_custody") or {},
            )
    except Exception as e:  # noqa: BLE001 — delivery must be honest and retryable
        job["artifact_record_error"] = str(e)
        job["artifact_delivery_failed"] = True
        job["recovery_required"] = True
        job["recovery_hint"] = (
            "Provider output was retrieved but local artifact delivery failed. "
            "Retry artifact registration only; do not resubmit the provider job."
        )
        job["status"] = "ARTIFACT_PERSISTENCE_FAILED"
        return
    if delivery_retry:
        job["status"] = "DONE"
    custody = job.get("product_visual_custody") or custody
    if custody and mode in _VIDEO_MODES:
        from agent.services.product_visual_custody_service import (
            evaluate_product_fidelity_qc,
            exact_output_ready,
        )

        evidence = job.get("product_fidelity_qc_evidence")
        if evidence is None and artifacts:
            # Reuse the existing Product Reference Pack machine check as an
            # explicit review signal. It intentionally reports WARN/UNVERIFIED
            # for generated pixels; it must never be promoted to PASS here.
            evidence = {
                "status": "REVIEW_REQUIRED",
                "verified": False,
                "dimensions": {},
                "source": "product_reference_pack_machine_check",
            }
            try:
                from agent.services.product_reference_pack_service import (
                    get_reference_pack,
                    machine_check_generated_output,
                )

                pack = await get_reference_pack(str(custody.get("product_id") or ""))
                if pack is not None:
                    evidence["machine_qa"] = [
                        machine_check_generated_output(
                            str(artifact.get("media_id") or ""), pack
                        ).model_dump(mode="json")
                        for artifact in artifacts
                    ]
            except Exception as exc:  # noqa: BLE001 - QC remains review-required
                evidence["machine_qa_error"] = str(exc)

        qc = evaluate_product_fidelity_qc(
            custody,
            evidence=evidence,
            artifact_available=bool(artifacts),
        )
        job["product_fidelity_qc"] = qc
        job["product_fidelity_qc_status"] = qc.get("status")
        job["generated_output_review_state"] = qc.get("status")
        custody_result = {
            **custody,
            "product_fidelity_qc": qc,
            "product_fidelity_qc_status": qc.get("status"),
        }
        try:
            from agent.db import crud

            routing_receipt = job.get("routing_receipt") or {}
            for artifact in artifacts:
                artifact_custody_result = custody_result
                if artifact.get("exact_product_lineage"):
                    artifact_custody_result = {
                        **custody_result,
                        "exact_video_composite": artifact.get("exact_product_lineage"),
                    }
                await crud.insert_generation_result(
                    artifact["media_id"],
                    job_id=job.get("job_id"),
                    request_id=job.get("request_id"),
                    staff_id=job.get("staff_id"),
                    staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
                    mode=mode,
                    surface_lane=provenance["surface_lane"],
                    transport_mode=provenance["transport_mode"],
                    source_mode=provenance["source_mode"],
                    provider_generation_type=provenance["provider_generation_type"],
                    artifact_kind="video",
                    product_id=job.get("product_id") or custody.get("product_id"),
                    product_name=custody.get("product_name"),
                    final_prompt_text=job.get("prompt") or "",
                    aspect_ratio=job.get("aspect"),
                    model_label=job.get("model"),
                    duration_s=job.get("duration_s"),
                    count_setting=job.get("num_videos"),
                    reference_media_ids=routing_receipt.get("reference_media_ids") or [],
                    project_id=job.get("project_id"),
                    product_visual_custody=artifact_custody_result,
                )
        except Exception as exc:  # noqa: BLE001 - lineage must not fail retrieval
            job["product_visual_custody_record_error"] = str(exc)
        if not exact_output_ready(custody, qc) and job.get("status") == "DONE":
            # Keep a returned artifact auditable, but never expose an exact
            # product as READY without explicit fidelity evidence.
            job["status"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"


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


async def _verify_generation_approval(
    *, mode, prompt, source_mode, model, aspect, duration_s, num_videos,
    image_model, asset_fingerprints, image_media_ids, product_id,
    manifest_id, execution_identity,
):
    """Run the normal WYSIWYG approval gate for non-capture dispatches."""
    from agent.services import execution_approval_service as _eas

    _assets = [] if manifest_id else list(image_media_ids or [])
    _pinned_snapshot_id = None
    if manifest_id:
        _resolved = await _eas.resolve_manifest_approved_snapshot(
            manifest_id=manifest_id, mode=mode, final_prompt_text=prompt,
            source_mode=source_mode, model=model, aspect=aspect,
            duration_s=duration_s, count=num_videos, image_model=image_model,
            asset_fingerprints=asset_fingerprints, asset_media_ids=_assets,
            product_id=product_id, execution_identity=execution_identity,
        )
        _pinned_snapshot_id = (_resolved or {}).get("snapshot_id")
    await _eas.verify_and_bind_dispatch(
        mode=mode, final_prompt_text=prompt, source_mode=source_mode,
        model=model, aspect=aspect, duration_s=duration_s,
        count=num_videos, image_model=image_model,
        asset_fingerprints=asset_fingerprints, asset_media_ids=_assets,
        product_id=product_id, snapshot_id=_pinned_snapshot_id,
        execution_identity=execution_identity,
    )


async def start_generate(mode: str, prompt: str, project_id: str = None,
                         image_media_ids: list = None, image_prompt: str = None,
                         aspect: str = "9:16", tier: str = "PAYGATE_TIER_ONE",
                         model: str = None, duration_s: int = None,
                         num_videos: int = 1, image_model: str = None,
                         max_image_attempts: int = 8,
                         collect_image_variants: bool = False,
                         product_id: str = None, source_mode: str = None,
                         staff_id: str | None = None,
                         staff_display_name_snapshot: str | None = None,
                         copy_execution_binding: dict | None = None,
                         manifest_id: str | None = None,
                         asset_fingerprints: list[str] | None = None,
                         execution_identity: dict | None = None,
                         product_visual_custody: dict | None = None,
                         request_id: str | None = None,
                         idempotency_key: str | None = None,
                         production_recipe: str | None = None,
                         surface_lane: str | None = None,
                         capture_class: str | None = None,
                         capture_subject: dict | None = None,
                         capture_confirmed: bool = False) -> dict:
    """THE one door. mode = IMG | T2V | I2V | F2V. Returns a job_id; poll get_job.
    num_videos is the USER's count setting (1–4) — honoured end-to-end: the
    negotiation demands exactly that many and retrieval collects them all.
    source_mode (HYBRID | FRAMES | INGREDIENTS, optional) is the logical lane —
    it selects the direct-lane RPC (HYBRID composes references; FRAMES anchors
    start/end frames) and is recorded on the job. Under DIRECT_VIDEO_LANE_ENABLED
    eligible reference-bearing video jobs run the DOM-free direct batchAsync
    lane. A reference-bearing job that cannot prove that route is rejected before
    provider approval; only pure T2V remains on the conversational agent lane."""
    global _VIDEO_LANE_JOB
    _gc_jobs()
    mode = (mode or "").upper()
    capture_requested = bool(capture_class)
    if capture_requested:
        if capture_class != HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS:
            return _capture_contract_reject("CAPTURE_CLASS_UNSUPPORTED")
        if not hybrid_reference_omni10_capture_enabled():
            return _capture_contract_reject("CAPTURE_FEATURE_DISABLED")
        if capture_confirmed is not True:
            return _capture_contract_reject("CAPTURE_LIVE_CREDIT_CONFIRMATION_REQUIRED")
        if mode != "F2V":
            return _capture_contract_reject("CAPTURE_MODE_MUST_BE_F2V")
        if str(surface_lane or "").strip().upper() != "HYBRID":
            return _capture_contract_reject("CAPTURE_SURFACE_LANE_MUST_BE_HYBRID")
        if str(source_mode or "").strip().upper() != "HYBRID":
            return _capture_contract_reject("CAPTURE_SOURCE_MODE_MUST_BE_HYBRID")
        try:
            resolved_model = video_models.resolve(model)
        except (TypeError, ValueError):
            return _capture_contract_reject("CAPTURE_MODEL_MUST_BE_OMNI_FLASH")
        if resolved_model.get("key") != "omni_flash":
            return _capture_contract_reject("CAPTURE_MODEL_MUST_BE_OMNI_FLASH")
        if duration_s != 10:
            return _capture_contract_reject("CAPTURE_DURATION_MUST_BE_10")
        if str(aspect or "").strip() != "9:16":
            return _capture_contract_reject("CAPTURE_ASPECT_MUST_BE_9_16")
        if int(num_videos or 0) != 1:
            return _capture_contract_reject("CAPTURE_COUNT_MUST_BE_1")
        if len([media_id for media_id in (image_media_ids or []) if media_id]) != 1:
            return _capture_contract_reject("CAPTURE_REFERENCE_COUNT_MUST_BE_1")
        if str(product_id or "") != HYBRID_REFERENCE_OMNI_10S_CAPTURE_PRODUCT_ID:
            return _capture_contract_reject("CAPTURE_PRODUCT_NOT_AUTHORIZED")
    production_recipe = str(production_recipe or "").strip().upper() or None
    from agent.security.access_control import get_current_auth_context, resolve_request_staff
    if production_recipe or get_current_auth_context() is not None:
        if production_recipe not in {"HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"}:
            if production_recipe:
                return {
                    "status": "REJECTED",
                    "error": "PRODUCTION_RECIPE_UNSUPPORTED",
                    "pre_provider": {"provider_calls": 0, "credit_spend": False},
                }
        from agent.services.staff_identity_service import StaffIdentityError

        try:
            profile = await resolve_request_staff(staff_id)
        except StaffIdentityError as exc:
            return {
                "status": "REJECTED",
                "error": exc.code,
                "detail": exc.message,
                "pre_provider": {"provider_calls": 0, "credit_spend": False},
            }
        staff_id = profile["staff_id"]
        staff_display_name_snapshot = profile["display_name"]
    idempotency_key = idempotency_key or request_id
    strict_durable = bool(request_id or idempotency_key)
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
        return {
            "status": "REJECTED",
            "error": _violation,
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": _violation.split(":", 1)[0],
            },
        }
    # A replay must resolve to the existing logical job before the process-local
    # single-flight check.  This is a read-only DB lookup and never resubmits a
    # provider operation, even when the old process-local map has been cleared.
    if idempotency_key:
        from agent.db import crud as _single_crud

        try:
            _existing = await _single_crud.get_video_production_job_by_logical_key(
                _single_logical_job_key("pending", idempotency_key)
            )
        except Exception as _exc:  # noqa: BLE001 — API callers fail closed
            if strict_durable:
                return {
                    "status": "REJECTED",
                    "error": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
                    "detail": str(_exc),
                    "pre_provider": {
                        "classification": "BLOCKED",
                        "provider_calls": 0,
                        "credit_spend": False,
                        "blocker_code": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
                    },
                }
            _existing = None
        if _existing:
            _memory_existing = get_job(_existing.get("job_id"))
            if _memory_existing:
                return {**_memory_existing, "request_id": request_id, "durable": True}
            _recovered_existing = await get_durable_job(_existing["job_id"])
            if _recovered_existing:
                return {**_recovered_existing, "request_id": request_id, "durable": True}
    # Single-flight (patch H): one video job at a time on the shared Flow tab. IMG exempt.
    if mode in _VIDEO_MODES and _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"status": "REJECTED", "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    _direct_plan = None
    _routing_receipt = None
    if mode in _VIDEO_MODES:
        if capture_requested:
            _direct_plan = {
                "eligible": False,
                "reason": "CAPTURE_ONLY_AGENT_DISCOVERY",
                "rpc": "agent_stream_chat",
                "gen_type": None,
                "aspect_enum": "VIDEO_ASPECT_RATIO_PORTRAIT",
                "video_model_key": None,
                "model_key_source": "provider_capture_only",
            }
            _routing_receipt = _capture_reference_routing_receipt(
                image_media_ids or []
            )
        else:
            _direct_plan = _direct_lane_plan(
                mode, source_mode, model, duration_s, aspect,
                ref_count=_ref_count, num_videos=num_videos,
            )
            _routing_receipt = _build_reference_routing_receipt(
                mode, source_mode, image_media_ids, _direct_plan,
            )
        _exact_video_route = bool(
            isinstance(product_visual_custody, dict)
            and product_visual_custody.get("exact_product_required")
            and product_visual_custody.get("provider_route")
            == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
        )
        if _exact_video_route:
            # Exact finalization consumes a text-only scene scaffold.  Keep it
            # on the agent T2V scaffold lane until a separate captured direct
            # scaffold contract exists; never reinterpret the route as a
            # reference-bearing direct operation.
            _direct_plan = {
                **(_direct_plan or {}),
                "eligible": False,
                "reason": "EXACT_PRODUCT_SCENE_SCAFFOLD_AGENT_T2V",
            }
        if product_visual_custody and not capture_requested:
            from agent.services.product_visual_custody_service import (
                ProductVisualCustodyError,
                validate_pre_dispatch_route,
            )

            exact_route = _exact_video_route
            selected_route = (
                "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
                if exact_route
                else (
                    "DIRECT_API"
                    if _direct_plan.get("eligible")
                    else "API_FIRST_GENERATIVE_REFERENCE"
                )
            )
            if exact_route:
                _routing_receipt.update(
                    {
                        "selected_execution_route": selected_route,
                        "provider_product_reference_forbidden": True,
                        "scene_scaffold_route": "AGENT_T2V",
                    }
                )
            try:
                validate_pre_dispatch_route(
                    product_visual_custody,
                    provider_route=selected_route,
                    generation_type=_pre_dispatch_generation_type(
                        product_visual_custody, _direct_plan
                    ),
                )
            except ProductVisualCustodyError as exc:
                return {
                    "status": "REJECTED",
                    "error": exc.code,
                    "detail": exc.message,
                    "routing_receipt": _routing_receipt,
                    "product_visual_custody": product_visual_custody,
                }
        if (
            not capture_requested
            and
            _routing_receipt["reference_requested"]
            and not _routing_receipt["reference_mode_authorized"]
        ):
            reason = (
                _routing_receipt.get("reference_contract_detail")
                or _routing_receipt.get("route_reason")
                or "reference-aware execution route is not proven"
            )
            return {
                "status": "REJECTED",
                "error": ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL,
                "detail": f"Reference-bearing video blocked before provider approval: {reason}",
                "routing_receipt": _routing_receipt,
                "pre_provider": (_routing_receipt or {}).get("pre_provider"),
            }
    from agent.services.video_surface_provenance import build_video_surface_provenance
    _surface_provenance = build_video_surface_provenance(
        surface_lane=surface_lane,
        transport_mode=mode,
        source_mode=source_mode,
        mode=mode,
        copy_lane=(copy_execution_binding or {}).get("lane"),
        execution_identity=execution_identity,
        routing_receipt=_routing_receipt,
        direct_plan=_direct_plan,
    )
    # Provider-bound jobs must carry a current released/readiness-approved product.
    # Legacy direct service tests without an HTTP AuthContext remain provider-free
    # compatibility calls; every real route and worker supplies the identity.
    from agent.security.access_control import get_current_auth_context
    if product_id or get_current_auth_context() is not None:
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                product_id, lane="MAKE_VIDEO_PROVIDER"
            )
        except ProductOperationalVisibilityError as exc:
            return {
                "status": "REJECTED",
                "error": exc.code,
                "detail": str(exc),
                "pre_provider": {"provider_calls": 0, "credit_spend": False},
            }
    # Final Prompt Approval Gate (WYSIWYG dispatch verification) is intentionally
    # skipped only for the owner-authorized capture boundary above.  That boundary
    # has its own exact class/flag/confirmation checks and is not reachable through
    # the normal /generate request model.
    if not capture_requested:
        from agent.services import execution_approval_service as _eas
        try:
            await _verify_generation_approval(
                mode=mode, prompt=prompt, source_mode=source_mode,
                model=model, aspect=aspect, duration_s=duration_s,
                num_videos=num_videos, image_model=image_model,
                asset_fingerprints=asset_fingerprints,
                image_media_ids=image_media_ids, product_id=product_id,
                manifest_id=manifest_id, execution_identity=execution_identity,
            )
        except _eas.ExecutionApprovalError as _gate_err:
            return {"status": "REJECTED", "error": _gate_err.code,
                    "detail": _gate_err.message, "approval": _gate_err.details}
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
                     "production_recipe": production_recipe,
                     "staff_id": staff_id,
                     "staff_display_name_snapshot": staff_display_name_snapshot,
                     "prompt": prompt, "aspect": aspect, "duration_s": duration_s,
                     "image_media_ids": [media_id for media_id in (image_media_ids or []) if media_id],
                     "reference_media_ids": [media_id for media_id in (image_media_ids or []) if media_id],
                      **_surface_provenance,
                      "transport_mode": _surface_provenance["transport_mode"] or mode,
                      "direct_plan": _direct_plan,
                     "execution_identity": execution_identity,
                     "product_visual_custody": product_visual_custody,
                     "capture_only": capture_requested,
                     "capture_class": capture_class,
                     "capture_subject": capture_subject,
                     "provider_generation_submit_count": 0,
                     "provider_resubmission": False,
                     "resubmission_allowed": False,
                     "error": None, "created": time.time(),
                     "request_id": request_id, "idempotency_key": idempotency_key,
                     "durable": False}
    if _routing_receipt is not None:
        _JOBS[job_id]["routing_receipt"] = _routing_receipt
    if capture_requested:
        _JOBS[job_id]["surface_lane"] = "HYBRID"
        _JOBS[job_id]["transport_mode"] = "F2V"
        _JOBS[job_id]["provider_generation_type"] = None
    if copy_execution_binding is not None:
        _JOBS[job_id]["copy_execution_binding"] = copy_execution_binding
    try:
        _durable_row, _durable_owner = await _prepare_durable_single_job(
            _JOBS[job_id], idempotency_key=idempotency_key, strict=strict_durable
        )
    except RuntimeError as _exc:
        _JOBS.pop(job_id, None)
        return {
            "status": "REJECTED",
            "error": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
            "detail": str(_exc),
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
            },
        }
    if _durable_row and not _durable_owner:
        _JOBS.pop(job_id, None)
        _recovered = await get_durable_job(_durable_row["job_id"])
        return {
            **(_recovered or {"job_id": _durable_row["job_id"], "status": "RECOVERY_REQUIRED"}),
            "request_id": request_id,
            "durable": True,
        }
    if _durable_row:
        _JOBS[job_id]["durable"] = True
        _JOBS[job_id]["logical_job_key"] = _durable_row.get("logical_job_key")
    if mode in _VIDEO_MODES:
        from agent.db import crud as _lane_crud

        try:
            _lane_lease = await _lane_crud.acquire_video_generation_lane_lease(job_id)
        except Exception as _exc:  # noqa: BLE001 - real API requests fail closed
            if strict_durable:
                _JOBS.pop(job_id, None)
                return {
                    "status": "REJECTED",
                    "error": "DURABLE_SINGLE_LANE_UNAVAILABLE",
                    "detail": str(_exc),
                    "pre_provider": {
                        "classification": "BLOCKED",
                        "provider_calls": 0,
                        "credit_spend": False,
                        "blocker_code": "DURABLE_SINGLE_LANE_UNAVAILABLE",
                    },
                }
            _lane_lease = None
        if _lane_lease is not None and not _lane_lease.get("acquired"):
            _owner_row = _lane_lease.get("row") or {}
            _JOBS.pop(job_id, None)
            return {
                "status": "REJECTED",
                "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _owner_row.get("job_id"),
                "pre_provider": {
                    "classification": "BLOCKED",
                    "provider_calls": 0,
                    "credit_spend": False,
                    "blocker_code": "VIDEO_JOB_IN_FLIGHT",
                },
            }
        if _lane_lease is not None:
            _JOBS[job_id]["lane_lease"] = _lane_lease.get("row")
        _VIDEO_LANE_JOB = job_id  # cache; the DB lease is the source of truth
    lane = None
    if mode in _VIDEO_MODES:
        plan = _direct_plan
        if capture_requested:
            lane = "CAPTURE_AGENT_DISCOVERY"
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["capture_only"] = True
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_task(
                    job_id, _run_reference_contract_capture, mode, prompt,
                    project_id, image_media_ids, image_prompt, aspect, tier,
                    model, duration_s, num_videos, image_model,
                    max_image_attempts, collect_image_variants, product_id,
                    copy_execution_binding,
                )
            )
            return {
                "job_id": job_id, "status": "SUBMITTED", "mode": mode,
                "lane": lane, "capture_class": capture_class,
                "routing_receipt": _routing_receipt,
                "request_id": request_id, "durable": bool(_durable_row),
            }
        if plan["eligible"]:
            lane = "DIRECT_API"
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_task(
                    job_id, _run_generate_direct, mode, prompt, project_id,
                    image_media_ids, aspect, tier, model, duration_s, num_videos,
                    product_id, plan,
                )
            )
            return {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                    "lane": lane, "routing_receipt": _routing_receipt,
                    "product_visual_custody": product_visual_custody,
                    "request_id": request_id, "durable": bool(_durable_row)}
        lane = "AGENT"
        _JOBS[job_id]["lane"] = lane
        if direct_video_lane_enabled():
            # The flag is on but THIS job could not provably run direct — record
            # why, so the T2V routing decision is auditable per job. Reference
            # jobs are rejected above instead of reaching this fallback.
            _JOBS[job_id]["direct_decline_reason"] = plan["reason"]
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_generate_task(
            job_id, _run_generate, mode, prompt, project_id, image_media_ids,
            image_prompt, aspect, tier, model, duration_s, num_videos, image_model,
            max_image_attempts, collect_image_variants, product_id,
            copy_execution_binding,
        )
    )
    return {
        "job_id": job_id,
        "status": "SUBMITTED",
        "mode": mode,
        "lane": lane,
        "routing_receipt": _routing_receipt,
        "product_visual_custody": product_visual_custody,
        "request_id": request_id,
        "durable": bool(_durable_row),
    }


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
    resource structurally proves it belongs to THIS submission. Two captured
    live contracts carry the same identity fields: legacy
    ``GET /v1/media/{generation-key}``, and current
    ``flow.projectInitialData`` when ``/v1/media/{delivery UUID}`` returns 400.
    Both expose the generation prompt (XML envelope, inner <prompt> == the exact
    input prompt), model and seed. The current contract then delivers bytes via
    the authenticated ``media.getMediaUrlRedirect`` endpoint.

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
    project_id = (
        correlation.get("_project_id") if isinstance(correlation, dict) else None
    )
    stats.setdefault("media_fetch_errors", 0)
    stats.setdefault("media_fetch_error_ids", [])
    stats.setdefault("media_fetch_error_statuses", {})
    stats.setdefault("media_not_ready", 0)
    stats.setdefault("media_not_ready_ids", [])
    stats.setdefault("project_metadata_fallbacks", 0)
    stats.setdefault("project_metadata_fallback_ids", [])
    stats.setdefault("media_download_errors", 0)
    stats.setdefault("media_download_error_ids", [])
    stats["round_rejected_ids"] = []  # per-call: completed-but-identity-rejected
    project_media_by_id = None
    for mid in dict.fromkeys(candidates):  # de-dupe, keep order
        if mid in exclude:
            continue
        media_error_status = None
        try:
            media = await client.get_media(mid)
        except Exception:
            media = None
            media_error_status = "exception"
        media_status = media.get("status") if isinstance(media, dict) else None
        if ((isinstance(media, dict) and media.get("error"))
                or (isinstance(media_status, int) and media_status >= 400)):
            media_error_status = (
                media_status if isinstance(media_status, int) else "error")
        from_project_metadata = False
        if media_error_status is not None:
            # Preserve a compact retrieval trace without storing response bodies
            # or signed URLs in job telemetry.
            stats["media_fetch_errors"] += 1
            if mid not in stats["media_fetch_error_ids"]:
                stats["media_fetch_error_ids"].append(mid)
            stats["media_fetch_error_statuses"][mid] = media_error_status

            # Current Flow agent clips are delivery UUIDs. Their exact identity
            # lives in the authenticated project payload even though the legacy
            # /v1/media lookup rejects that UUID. Read the project once per poll,
            # keep the same prompt/model/seed guard, and never accept freshness
            # alone as correlation.
            lister = getattr(client, "list_project_media", None)
            if project_id and callable(lister):
                if project_media_by_id is None:
                    try:
                        snapshot = await lister(project_id)
                    except Exception:  # noqa: BLE001 — keep polling with telemetry
                        snapshot = {"media": [], "error": "exception"}
                    observed_project_id = str(snapshot.get("project_id") or "").strip()
                    if observed_project_id and observed_project_id != str(project_id):
                        stats["project_metadata_error"] = "PROJECT_DRIFT"
                        project_media_by_id = {}
                    else:
                        project_media_by_id = {
                            str(item.get("name")): item
                            for item in (snapshot.get("media") or [])
                            if isinstance(item, dict) and item.get("name")
                        }
                        if snapshot.get("error"):
                            stats["project_metadata_error"] = str(snapshot["error"])
                fallback = project_media_by_id.get(str(mid))
                if fallback:
                    media = {"status": 200, "data": fallback}
                    from_project_metadata = True
                    stats["project_metadata_fallbacks"] += 1
                    if mid not in stats["project_metadata_fallback_ids"]:
                        stats["project_metadata_fallback_ids"].append(mid)
            if not from_project_metadata:
                continue
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        generation_status = _deep(mdata, "mediaGenerationStatus")
        if from_project_metadata and generation_status != "MEDIA_GENERATION_STATUS_SUCCESSFUL":
            stats["media_not_ready"] += 1
            if mid not in stats["media_not_ready_ids"]:
                stats["media_not_ready_ids"].append(mid)
            continue
        video_meta = mdata.get("video") if isinstance(mdata, dict) else None
        video_meta = video_meta if isinstance(video_meta, dict) else {}
        if isinstance(video_meta.get("generatedVideo"), dict):
            video_meta = video_meta["generatedVideo"]
        if not enc and not from_project_metadata:
            stats["media_not_ready"] += 1
            if mid not in stats["media_not_ready_ids"]:
                stats["media_not_ready_ids"].append(mid)
            continue  # not a finished video (or not a video resource at all)
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
        retrieval_source = "get_media"
        if enc:
            vbytes = base64.b64decode(enc)
        else:
            try:
                vbytes, retrieval_source = await _download_video_bytes(
                    client, mid, None)
            except Exception:  # noqa: BLE001 — keep the bounded retrieval trace
                stats["media_download_errors"] += 1
                if mid not in stats["media_download_error_ids"]:
                    stats["media_download_error_ids"].append(mid)
                continue
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
            "metadata_source": ("project_initial_data" if from_project_metadata
                                else "get_media"),
            "retrieval_source": retrieval_source,
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


def _terminal_agent_failure_error(classification: str | None) -> str | None:
    """Map a terminal Flow-agent reply to one stable operator-facing error."""
    if classification == "REFERENCE_IMAGE_MISSING":
        return (
            "FAILED_REFERENCE_IMAGE_MISSING: the Flow agent cannot access the start "
            "image — re-upload the product image and resubmit (do NOT just regenerate)"
        )
    if classification == agent_video.SAFETY_FILTERED:
        return (
            "FAILED_PROVIDER_SAFETY_FILTER: Google Flow rejected the prompt under its "
            "prominent-people safety policy. Recompile with the creator attribution "
            "removed; do not auto-retry the same prompt"
        )
    if classification == "RENDER_FAILED":
        return (
            "FAILED_RENDER_REPORTED_BY_AGENT: the Flow agent reports the generation "
            "failed server-side — safe to resubmit only after the prompt/cause is fixed"
        )
    return None


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
    if (stats.get("round_rejected_ids") or stats.get("unverifiable_ids")
            or stats.get("media_fetch_errors")):
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
# rejects a reference-bearing request before provider approval; pure T2V alone may
# continue on the conversational lane (USER SETTINGS ARE LAW).

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
    r"^https://(?:storage\.googleapis\.com|lh3\.googleusercontent\.com|"
    r"(?:[a-z0-9-]+\.)?flow-content\.google)/", re.I)


def _direct_lane_plan(mode, source_mode, model, duration_s, aspect,
                      ref_count, num_videos, require_flag=True) -> dict:
    """Decide whether a job may run on the direct batchAsync lane.

    Fail-closed: any setting the direct lane cannot PROVABLY honor returns an
    explicit reason. ``start_generate`` rejects reference-bearing declines
    before provider approval; only pure T2V may use the agent lane. Returns
    {"eligible": bool, "reason": str|None, "rpc": "r2v"|"start_frame",
     "gen_type": str, "aspect_enum": str, "video_model_key": str|None,
     "model_key_source": str}.
    """
    def _decline(reason):
        return {"eligible": False, "reason": reason}

    if mode not in _VIDEO_MODES:
        return _decline("NOT_A_VIDEO_MODE")
    if mode in ("F2V", "I2V") and ref_count >= 1:
        try:
            if int(duration_s) == 10:
                # Certification truth must win over the feature flag: a 10s
                # reference request is never allowed to degrade to an 8s
                # agent/default route when direct transport is disabled.
                return _decline(DIRECT_10S_CONTRACT_NOT_CERTIFIED)
        except (TypeError, ValueError):
            pass
    if require_flag and not direct_video_lane_enabled():
        return _decline("DIRECT_LANE_DISABLED")
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
        # do not thread source_mode (bulk/queue lanes) are rejected before
        # provider approval.
        return _decline("DIRECT_F2V_SOURCE_MODE_UNKNOWN")
    else:  # I2V — ingredient references compose the video (r2v)
        rpc, gen_type = "r2v", "reference_frame_2_video"
    video_model_key = None
    model_key_source = "models.json default (tier, gen_type, aspect)"
    if model:
        try:
            spec = video_models.resolve(model)
        except ValueError:
            # Unknown model must surface through the canonical fail-closed path;
            # never fire an unproven direct request.
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
        if normalized_duration == 10:
            # The direct submit contract has never captured a 10s request.  Keep
            # this as a stable machine-readable readiness blocker instead of
            # treating the provider's 8s default as a silent 10s success.
            return _decline(DIRECT_10S_CONTRACT_NOT_CERTIFIED)
        if normalized_duration != 8:
            # The captured submit contract carries no duration field; only the
            # Veo 8s default is provably delivered. Anything else is rejected
            # for a reference-bearing request before provider approval.
            return _decline(f"DIRECT_DURATION_UNPROVEN:{duration_s}")
    return {"eligible": True, "reason": None, "rpc": rpc, "gen_type": gen_type,
            "aspect_enum": aspect_enum, "video_model_key": video_model_key,
            "model_key_source": model_key_source}


def direct_video_readiness(
    mode: str | None = None,
    *,
    source_mode: str | None = None,
    model: str | None = None,
    duration_s: int | None = None,
    aspect: str = "9:16",
    ref_count: int = 1,
    num_videos: int = 1,
) -> dict:
    """Return the provider-free direct-lane contract decision.

    This is deliberately a pure readiness surface: it does not bind Flow,
    inspect the extension, resolve a project, or call a provider.  A readiness
    response may therefore be safely shown before approval.  Unknown model keys,
    unproven durations, and a disabled lane remain explicit blockers; no value is
    guessed from the registry or from the provider's default duration.
    """
    normalized_mode = (mode or "F2V").strip().upper()
    normalized_duration = duration_s
    plan = _direct_lane_plan(
        normalized_mode,
        source_mode,
        model,
        normalized_duration,
        aspect,
        ref_count=max(0, int(ref_count or 0)),
        num_videos=max(1, int(num_videos or 1)),
        require_flag=False,
    )
    blockers: list[dict[str, str]] = []
    reason = str(plan.get("reason") or "")
    if reason:
        blockers.append({
            "code": reason.split(":", 1)[0],
            "detail": reason,
            "stage": "PRE_PROVIDER",
        })
    if not direct_video_lane_enabled():
        blockers.append({
            "code": "DIRECT_LANE_DISABLED",
            "detail": "DIRECT_VIDEO_LANE_ENABLED is not enabled",
            "stage": "PRE_PROVIDER",
        })
    # Always publish the independent 10s certification state.  A caller asking
    # for another duration must not make the 10s contract appear certified.
    ten_second_plan = _direct_lane_plan(
        normalized_mode,
        source_mode,
        model,
        10,
        aspect,
        ref_count=max(0, int(ref_count or 0)),
        num_videos=max(1, int(num_videos or 1)),
        require_flag=False,
    )
    # This is an explicit certification boundary, independent of incidental
    # input validation (missing source mode, disabled flag, etc.). The captured
    # direct submit contract contains no 10s request, so 10s stays blocked until
    # a future owner-authorized capture records it.
    ten_second_blocker = DIRECT_10S_CONTRACT_NOT_CERTIFIED
    return {
        "contract_version": DIRECT_VIDEO_READINESS_CONTRACT_VERSION,
        "provider_calls": 0,
        "credit_spend": False,
        "live_capture_required": True,
        "mode": normalized_mode,
        "source_mode": str(source_mode or "").strip().upper() or None,
        "model": model,
        "duration_s": normalized_duration,
        "aspect": aspect,
        "reference_count": max(0, int(ref_count or 0)),
        "num_videos": max(1, int(num_videos or 1)),
        "eligible": bool(plan.get("eligible")) and direct_video_lane_enabled(),
        "selected_route": "DIRECT_API" if plan.get("eligible") and direct_video_lane_enabled() else "BLOCKED",
        "plan": plan,
        "blockers": blockers,
        "ten_second": {
            "duration_s": 10,
            "status": "NOT_CERTIFIED",
            "blocker_code": ten_second_blocker,
            "provider_calls": 0,
        },
    }


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


async def _direct_operation_retrieve_from_poll(
        job, client, mode, polled, plan, seed, num_videos) -> None:
    """Retrieve/register a successful legacy-operation poll response."""
    from agent.worker._parsing import _extract_uuid_from_url

    data = _direct_response_data(polled)
    final_ops = data.get("operations", []) if isinstance(data, dict) else []
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for op in final_ops:
        if not isinstance(op, dict):
            continue
        op_name = (op.get("operation") or {}).get("name")
        video_meta = ((op.get("operation") or {}).get("metadata") or {}).get("video") or {}
        mid = str(video_meta.get("mediaId") or "").strip()
        fife = video_meta.get("fifeUrl")
        if not mid and fife:
            mid = _extract_uuid_from_url(str(fife))
        if not mid:
            skipped.append({"operation": op_name, "reason": "NO_MEDIA_ID_IN_METADATA"})
            continue
        data_bytes, source = await _download_video_bytes(client, mid, fife)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data_bytes)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data_bytes) / 1024 / 1024, 2),
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
            "DIRECT_RETRIEVAL_EMPTY: provider terminal operation exposed no retrievable media"
        )
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(
        status="DONE",
        stage="done",
        media_id=first["media_id"],
        local_path=first["local_path"],
        size_mb=first["size_mb"],
        artifact="video",
        artifacts=list(collected),
    )
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = f"retrieved {len(collected)}/{num_videos} requested videos"
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


async def _direct_media_retrieve_from_poll(
        job, client, mode, targets, plan, seed, num_videos, polled) -> None:
    """Retrieve/register a successful current media-target poll response."""
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
        data_bytes, source = await _download_video_bytes(
            client,
            mid,
            _direct_media_url(media),
            media_generation_id=generation_id,
        )
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data_bytes)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data_bytes) / 1024 / 1024, 2),
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
            "DIRECT_RETRIEVAL_EMPTY: provider terminal media status exposed no retrievable media"
        )
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(
        status="DONE",
        stage="done",
        media_id=first["media_id"],
        local_path=first["local_path"],
        size_mb=first["size_mb"],
        artifact="video",
        artifacts=list(collected),
    )
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = f"retrieved {len(collected)}/{num_videos} requested videos"
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


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
    if product_id:
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                product_id, lane="MAKE_VIDEO_DIRECT_PROVIDER"
            )
        except ProductOperationalVisibilityError as exc:
            job["status"] = "REJECTED"
            job["error"] = f"{exc.code}:{exc}"
            return
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
            "provider_generation_submit_count": 1,
        }
        job["provider_generation_submit_count"] = 1
        job["provider_resubmission"] = False
        job["identity_captured"] = True  # the operation handle IS the binding
        # Provider identity is durable before the long poll/retrieval window.
        await _sync_durable_single_job(job)
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
                               confirm_live_credit_burn: bool = False,
                               product_visual_custody: dict | None = None,
                               execution_identity: dict | None = None,
                               request_id: str | None = None,
                               staff_id: str | None = None,
                               staff_display_name_snapshot: str | None = None,
                               production_recipe: str | None = None) -> dict:
    """LIVE-CAPTURE GATE (owner-authorized, DIRECT_VIDEO_CAPTURE_ENABLED): fire
    ONE direct batchAsync submit, return the RAW submit response for contract
    capture, and poll/retrieve/persist in the background so the spent credit
    still yields a real artifact. Single-flight like every video job. The
    confirmation flag is mandatory; explicit model and duration settings are
    forwarded and fail closed when their direct contract is unproven."""
    global _VIDEO_LANE_JOB
    production_recipe = str(production_recipe or "").strip().upper() or None
    from agent.security.access_control import get_current_auth_context, resolve_request_staff
    if production_recipe or get_current_auth_context() is not None:
        if production_recipe not in {"HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"}:
            if production_recipe:
                return {"ok": False, "error": "PRODUCTION_RECIPE_UNSUPPORTED", "provider_submit": False}
        from agent.services.staff_identity_service import StaffIdentityError

        try:
            profile = await resolve_request_staff(staff_id)
        except StaffIdentityError as exc:
            return {"ok": False, "error": exc.code, "detail": exc.message, "provider_submit": False}
        staff_id = profile["staff_id"]
        staff_display_name_snapshot = profile["display_name"]
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
    if product_visual_custody:
        from agent.services.product_visual_custody_service import (
            ProductVisualCustodyError,
            validate_pre_dispatch_route,
        )

        try:
            validate_pre_dispatch_route(
                product_visual_custody,
                provider_route="DIRECT_API",
                generation_type=str(plan.get("gen_type") or "reference_frame_2_video"),
            )
        except ProductVisualCustodyError as exc:
            return {"ok": False, "error": exc.code, "detail": exc.message}
    _gc_jobs()
    if _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"ok": False, "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "g_" + uuid4().hex[:12]
    from agent.db import crud as _capture_crud

    try:
        _capture_lease = await _capture_crud.acquire_video_generation_lane_lease(job_id)
    except Exception as exc:  # noqa: BLE001 - capture must fail closed
        return {
            "ok": False,
            "error": "DURABLE_SINGLE_LANE_UNAVAILABLE",
            "detail": str(exc),
            "provider_submit": False,
        }
    if not _capture_lease.get("acquired"):
        return {
            "ok": False,
            "error": "VIDEO_JOB_IN_FLIGHT",
            "active_job": (_capture_lease.get("row") or {}).get("job_id"),
            "provider_submit": False,
        }
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                     "stage": "direct capture submit", "project_id": project_id,
                     "local_path": None, "media_id": None, "size_mb": None,
                     "artifact": None, "approved": None, "binding": None,
                     "model": model, "duration_s": duration_s,
                     "prompt": prompt, "aspect": aspect,
                     "num_videos": 1, "artifacts": [],
                     "provider_operation_ids": [], "product_id": (
                         product_visual_custody or {}
                     ).get("product_id"),
                     "lane": "DIRECT_CAPTURE", "source_mode": source_mode,
                     "staff_id": staff_id,
                     "staff_display_name_snapshot": staff_display_name_snapshot,
                     "production_recipe": production_recipe,
                     "product_visual_custody": product_visual_custody,
                     "execution_identity": execution_identity,
                     "request_id": request_id,
                     "idempotency_key": request_id or job_id,
                     "strict_artifact_delivery": True,
                     "error": None, "created": time.time()}
    try:
        _durable_row, _durable_owner = await _prepare_durable_single_job(
            _JOBS[job_id],
            idempotency_key=request_id or job_id,
            strict=True,
        )
    except RuntimeError as exc:
        _JOBS.pop(job_id, None)
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {
            "ok": False,
            "error": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
            "detail": str(exc),
            "provider_submit": False,
        }
    if _durable_row and not _durable_owner:
        _JOBS.pop(job_id, None)
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {
            **(await get_durable_job(_durable_row["job_id"]) or {}),
            "ok": True,
            "provider_submit": False,
            "request_id": request_id,
            "replayed": True,
        }
    _JOBS[job_id]["durable"] = bool(_durable_row)
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
        await _capture_crud.release_video_generation_lane_lease(job_id)
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
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {"ok": False, "job_id": job_id, "fired": fired,
                "submit_response": submit, "error": job["error"]}
    operations, media_targets, op_names = _direct_submit_handles(
        submit, project_id)
    job["provider_operation_ids"] = op_names
    job["approved"] = bool(op_names)
    job["direct_media_targets"] = media_targets
    job["model_used"] = fired_model_key
    job["generation_identity"] = {"seed": seed, "expected_model": fired_model_key,
                                  "operation_names": op_names,
                                  "provider_generation_submit_count": 1}
    job["provider_generation_submit_count"] = 1
    job["provider_resubmission"] = False
    job["identity_captured"] = bool(op_names)
    await _sync_durable_single_job(job)

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
            await _capture_crud.release_video_generation_lane_lease(job_id)

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
        "strict_artifact_delivery": True,
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
        if product_id:
            from agent.services.product_release_service import (
                ProductOperationalVisibilityError,
                require_product_operational_visibility,
            )
            try:
                await require_product_operational_visibility(
                    product_id, lane="MAKE_VIDEO_AGENT_PROVIDER"
                )
            except ProductOperationalVisibilityError as exc:
                raise RuntimeError(f"{exc.code}:{exc}") from exc
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
        job["negotiation_state"] = nres.get("negotiation_state") or {}
        if job.get("capture_only"):
            job["capture_contract_evidence"] = agent_video.build_reference_contract_capture_evidence(
                nres, refs, project_id=project_id
            )
            observed_types = [
                item.get("value")
                for item in (job["capture_contract_evidence"].get("generation_type_fields") or [])
                if isinstance(item, dict) and item.get("value") not in (None, "")
            ]
            if observed_types:
                job["provider_generation_type"] = str(observed_types[0])
        # Approval may already have triggered provider work.  Every subsequent failure
        # is therefore credit-uncertain, including a safety rejection inside the approve
        # stream; never stamp it as NOT_SPENT merely because retrieval did not begin.
        if job["approved"] is True:
            generating = True
            # This is the single logical provider submit.  Persist the count before
            # any long render/retrieval wait; recovery must never infer a second
            # submit from a lost process-local task.
            job["provider_generation_submit_count"] = 1
            job["provider_resubmission"] = False
            job["resubmission_allowed"] = False
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
            if job.get("capture_only"):
                # The capture evidence is sanitized; never persist raw SSE as a
                # fallback because it can contain provider/session material.
                job["identity_gap_sse"] = None
            else:
                job["identity_gap_sse"] = _last_approve_sse(nres)
        # Persist the approved provider/correlation envelope before any long
        # render wait. A restart can therefore reconcile this same attempt.
        await _sync_durable_single_job(job)
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
        # The render can die inside the approve stream itself.  Treat every known
        # terminal reply as terminal now so the shared video lock is released in the
        # finally block instead of holding every lane until the retrieval timeout.
        terminal_error = _terminal_agent_failure_error(
            nres.get("failure_classification")
        )
        if terminal_error:
            raise RuntimeError(terminal_error)

        job["status"], job["stage"] = "GENERATING", "rendering + retrieving"
        generating = True  # also true for legacy responses that omitted approved=True
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
        # Retrieval-only context, deliberately added after the durable identity
        # snapshot so the existing five-argument correlation helper contract stays
        # compatible with harnesses and downstream overrides.
        correlation["_project_id"] = project_id
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
            if job.get("capture_only"):
                job["identity_gap_sse"] = None
            else:
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
            if i in (0, 8, 20) and not collected:
                probe = await agent_video.probe_render_failure(
                    client, project_id, sid, probe_turn)
                probe_turn = probe.get("turn_number", probe_turn + 1)
                job["render_probe"] = probe
                terminal_error = _terminal_agent_failure_error(
                    probe.get("classification")
                )
                if terminal_error:
                    raise RuntimeError(terminal_error)
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
                         model=None, duration_s=None, project_id=None,
                         reference_media_ids=None):
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
        media_ids = [str(media_id) for media_id in (reference_media_ids or []) if media_id]
        # Preserve the established pure-T2V adapter contract (`None` means no
        # media field) while carrying an existing reference list unchanged.
        media = media_ids or None
        if image_prompt and media:
            raise RuntimeError(
                "NEGOTIATION_REFERENCE_INPUT_AMBIGUOUS: use reference_media_ids "
                "or image_prompt, not both"
            )
        if image_prompt:  # optional start frame (skip for a pure T2V dry capture)
            job["stage"] = "start frame"
            img = await _generate_image_with_recovery(
                client, image_prompt, project_id, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
            mid = _deep(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
            if mid:
                media = [mid]
        job["reference_media_ids"] = list(media or [])
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


async def _run(job_id: str, prompt: str, image_prompt: str, product_id: str | None = None):
    from agent.api.flow import _generate_image_with_recovery  # lazy (avoid circular)
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                product_id, lane="FLOW_MAKE_VIDEO_WORKER"
            )
        except ProductOperationalVisibilityError as exc:
            raise RuntimeError(f"{exc.code}:{exc}") from exc
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
