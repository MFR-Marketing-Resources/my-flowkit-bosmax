"""Operator-gated trigger logic for the GFV2_POST_SUBMIT_DOWNLOAD lane.

Pure, side-effect-free assembly + gating so it is fully unit-testable without a
live extension. The FastAPI endpoint (agent/api/local_agent.py) supplies the live
inputs (build-proof verdict, active-job count, DB rows) and performs the actual
dispatch only in LIVE mode behind an explicit confirm flag.

Safety model:
- DRY_RUN (default): assemble and return the exact job JSON. No dispatch, no POST,
  no credit.
- LIVE: only when confirm_live_credit_burn is true AND every gate passes.
- Gates apply to BOTH modes (a malformed/unsafe context never even assembles a
  "ready" verdict): build-proof must be PASS, no active GFV2 job, package+product
  present and matched, request_id not a duplicate.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from agent.services.system_avatar_contract import (
    assert_system_avatar_contract,
    package_has_system_avatar,
)

LANE = "GFV2_POST_SUBMIT_DOWNLOAD"

# Reject reasons
REJECT_MISSING_PACKAGE = "MISSING_PACKAGE"
REJECT_MISSING_PRODUCT = "MISSING_PRODUCT"
REJECT_PRODUCT_MISMATCH = "PRODUCT_MISMATCH"
REJECT_DUPLICATE_REQUEST_ID = "DUPLICATE_REQUEST_ID"
REJECT_BUILD_PROOF_NOT_PASS = "BUILD_PROOF_NOT_PASS"
REJECT_ACTIVE_JOB_EXISTS = "ACTIVE_JOB_EXISTS"

ACTION_REJECT = "REJECT"
ACTION_DRY_RUN = "DRY_RUN"
ACTION_LIVE = "LIVE"


def _coerce(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


def _resolved_start_asset(package: dict) -> dict:
    """Pull the resolved start-frame asset (the upload source) from the package."""
    data = _coerce(package.get("resolved_assets")) or _coerce(package.get("asset_slots"))
    if not isinstance(data, list):
        return {}
    # Prefer the start_frame slot; fall back to the first asset carrying a source.
    candidates = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        asset = entry.get("resolved_asset") if isinstance(entry.get("resolved_asset"), dict) else entry
        if not isinstance(asset, dict):
            continue
        candidates.append(asset)
    for asset in candidates:
        if asset.get("slot_key") == "start_frame" and (asset.get("preview_url") or asset.get("file_name")):
            return asset
    for asset in candidates:
        if asset.get("preview_url") or asset.get("file_name"):
            return asset
    return {}


def assemble_job(package: dict, product: Optional[dict], request_id: str) -> dict:
    """Build the exact EXECUTE_FLOW_JOB payload for the GFV2_POST_SUBMIT_DOWNLOAD lane.

    Field names match what the extension reads (background.js / content-flow-dom.js):
    job.lane / job.gfv2 / job.postSubmitDownload, job.prompt, job.aspectRatio,
    job.count, job.modelLabel, job.startAsset (upload source), job.product_id,
    job.workspace_execution_package_id.
    """
    asset = _resolved_start_asset(package)
    start_source = asset.get("preview_url") or asset.get("file_path") or asset.get("file_name")
    return {
        "request_id": request_id,
        "lane": LANE,
        "gfv2": True,
        "postSubmitDownload": True,
        "mode": package.get("mode") or "F2V",
        "prompt": package.get("prompt_text"),
        "aspectRatio": package.get("aspect_ratio") or "9:16",
        "count": "1x",
        "modelLabel": package.get("model") or "Veo 3.1 - Lite",
        "durationSeconds": package.get("duration_seconds"),
        "startAsset": start_source,
        "product_id": package.get("product_id") or (product or {}).get("id"),
        "workspace_execution_package_id": package.get("workspace_execution_package_id"),
        "prompt_package_snapshot_id": package.get("prompt_package_snapshot_id"),
        "prompt_fingerprint": package.get("prompt_fingerprint"),
        "asset_fingerprint": asset.get("asset_fingerprint"),
    }


def evaluate_trigger(
    *,
    confirm_live: bool,
    build_proof_pass: bool,
    active_job_count: int,
    package: Optional[dict],
    product: Optional[dict],
    request_id: str,
    request_id_exists: bool,
) -> dict:
    """Fail-closed gate decision. Returns {action, reason}.

    action is REJECT (with reason), DRY_RUN, or LIVE. Gates are evaluated before
    the dry-run/live split so an unsafe context can never reach LIVE — and a
    BLOCKED build or active job is reported as REJECT even for a dry-run request.
    """
    def reject(reason: str) -> dict:
        return {"action": ACTION_REJECT, "reason": reason, "request_id": request_id}

    if not package:
        return reject(REJECT_MISSING_PACKAGE)
    if not product:
        return reject(REJECT_MISSING_PRODUCT)
    pkg_product = package.get("product_id")
    prod_id = product.get("id")
    if pkg_product and prod_id and pkg_product != prod_id:
        return reject(REJECT_PRODUCT_MISMATCH)
    if request_id_exists:
        return reject(REJECT_DUPLICATE_REQUEST_ID)
    if not build_proof_pass:
        return reject(REJECT_BUILD_PROOF_NOT_PASS)
    if active_job_count and active_job_count > 0:
        return reject(REJECT_ACTIVE_JOB_EXISTS)

    # System-avatar contract (operator mandate): never let Google Flow invent an
    # uncontrolled human. If the package prompt demands a visible creator / AI
    # avatar but the package carries no system avatar reference, fail closed.
    avatar_error = assert_system_avatar_contract(
        package.get("prompt_text"),
        package_has_system_avatar(
            _coerce(package.get("resolved_assets")) or _coerce(package.get("asset_slots")),
            avatar_id=package.get("avatar_id"),
        ),
    )
    if avatar_error:
        return reject(avatar_error)

    return {
        "action": ACTION_LIVE if confirm_live else ACTION_DRY_RUN,
        "reason": None,
        "request_id": request_id,
    }
