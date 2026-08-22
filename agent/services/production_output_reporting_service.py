"""Authoritative, read-only management reporting for actual production output.

This module is deliberately a projection over existing ledgers.  It does not own
mutable reporting state and it never dispatches a provider job.  The projection is
fail-closed: a transport mode is not enough evidence for a business recipe.
"""

from __future__ import annotations

import json
import re
import asyncio
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.db.schema import get_db

REPORTING_TIMEZONE = "Asia/Kuala_Lumpur"
try:
    _REPORTING_ZONE = ZoneInfo(REPORTING_TIMEZONE)
except ZoneInfoNotFoundError:
    # Kuala Lumpur has a fixed UTC+08 offset and no DST.  Keep the canonical
    # reporting label usable on Windows runners that do not bundle IANA tzdata.
    _REPORTING_ZONE = timezone(timedelta(hours=8), name=REPORTING_TIMEZONE)
_MAX_WINDOW_DAYS = 366

VIDEO_RECIPES = ("HYBRID", "FACELESS", "MONTAGE")
REPORTING_RECIPES = (*VIDEO_RECIPES, "POSTER_BUILDER")
MEDIA_TYPES = ("VIDEO", "IMAGE", "POSTER")
ORIGIN_SURFACES = ("PRODUCTION_STUDIO", "STANDALONE", "POSTER_BUILDER")

# These are historical model labels.  They remain in their source ledgers but are
# never current management-report rows or filter options.
_RETIRED_MODEL_MARKERS = (
    "wan26",
    "kling30",
    "seedance20",
    "sora2",
)
_UNKNOWN_STAFF = {
    "",
    "unknown",
    "unattributed",
    "operator",
    "system",
    "p6_system",
    "p6-production-operator",
    "dashboard-operator",
    "dashboard_operator",
    "dashboard operator",
    "none",
    "null",
}
_TEST_PRODUCT_MARKERS = (
    "test product",
    "test item",
    "fixture product",
    "smoke ",
    "smoke approve",
    "smoke reject",
    "smoke claim review",
    "codex pi ",
)
_MONTAGE_ACTUAL_STATUSES = {
    "SUBMITTED",
    "RUNNING",
    "GENERATED",
    "DOWNLOADED",
    "REGISTERED",
    "FAILED",
    "CANCELLED",
    "VIDEO_SUBMITTED",
    "VIDEO_READY",
    "GENERATE_RETURNED",
    "GENERATE_FAILED",
    "RESULT_BOUND",
    "BLOCKED",
}
_MONTAGE_SUCCESS_STATUSES = {
    "GENERATED",
    "DOWNLOADED",
    "REGISTERED",
    "VIDEO_READY",
    "GENERATE_RETURNED",
    "RESULT_BOUND",
}
_FAILED_STATES = {"FAILED", "GENERATE_FAILED"}


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _clean_staff(value: Any) -> str | None:
    result = _text(value)
    if result is None or result.casefold() in _UNKNOWN_STAFF:
        return None
    return result


def _resolve_staff(*candidates: tuple[Any, Any]) -> tuple[str | None, str | None]:
    """Prefer persisted canonical staff columns, then use explicit legacy evidence."""

    for staff_id, display_name in candidates:
        canonical_id = _clean_staff(staff_id)
        if canonical_id:
            return canonical_id, _text(display_name) or canonical_id
    return None, None


def _is_test_product(product_id: Any, *names: Any) -> bool:
    pid = str(product_id or "").strip().casefold()
    if pid.startswith("test_") or pid.startswith("fixture_"):
        return True
    for name in names:
        value = str(name or "").strip().casefold()
        if value in {"test product", "test item", "fixture product"}:
            return True
        if any(marker in value for marker in _TEST_PRODUCT_MARKERS):
            return True
    return False


def _model_is_retired(value: Any) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    return any(marker in compact for marker in _RETIRED_MODEL_MARKERS)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_day(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.astimezone(_REPORTING_ZONE).date().isoformat() if parsed else None


def reporting_window(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    today: date | None = None,
) -> dict[str, str | int]:
    """Return inclusive Malaysia dates plus UTC half-open query boundaries."""

    local_today = today or datetime.now(_REPORTING_ZONE).date()
    try:
        end = date.fromisoformat(end_date) if end_date else local_today
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=29)
    except ValueError as exc:
        raise ValueError("DATES_MUST_USE_YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("START_DATE_AFTER_END_DATE")
    span = (end - start).days + 1
    if span > _MAX_WINDOW_DAYS:
        raise ValueError(f"DATE_WINDOW_TOO_LARGE_MAX_{_MAX_WINDOW_DAYS}_DAYS")

    start_local = datetime.combine(start, time.min, tzinfo=_REPORTING_ZONE)
    end_local = datetime.combine(end + timedelta(days=1), time.min, tzinfo=_REPORTING_ZONE)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "start_utc": _iso_z(start_local),
        "end_utc": _iso_z(end_local),
        "days": span,
    }


async def _rows(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(sql, tuple(params))
    return [dict(row) for row in await cursor.fetchall()]


def _product_name(row: dict[str, Any]) -> str | None:
    return _text(
        row.get("product_name")
        or row.get("product_display_name")
        or row.get("product_short_name")
        or row.get("product_raw_title")
        or row.get("product_id")
    )


def _base_record(**values: Any) -> dict[str, Any]:
    staff_id, staff_display_name = _resolve_staff(
        (
            values.get("staff_id"),
            values.get("staff_display_name") or values.get("staff_display_name_snapshot"),
        ),
        (values.get("operator_id"), values.get("operator_display_name")),
    )
    record = {
        "output_id": _text(values.get("output_id")),
        "media_type": _text(values.get("media_type")),
        "production_recipe": _text(values.get("production_recipe")),
        "origin_surface": _text(values.get("origin_surface")),
        "staff_id": staff_id,
        "staff_display_name": staff_display_name,
        # Keep the reporting API's established aliases while sourcing them from
        # canonical StaffProfile lineage whenever it is present.
        "operator_id": staff_id,
        "operator_display_name": staff_display_name,
        "product_id": _text(values.get("product_id")),
        "product_name": _text(values.get("product_name")),
        "plan_or_run_id": _text(values.get("plan_or_run_id")),
        "production_item_id": _text(values.get("production_item_id")),
        "attempt_id": _text(values.get("attempt_id")),
        "attempt_number": int(values.get("attempt_number") or 1),
        "provider": _text(values.get("provider")),
        "model_key": _text(values.get("model_key")),
        "status": _text(values.get("status")) or "UNKNOWN",
        "artifact_media_id": _text(values.get("artifact_media_id")),
        "qa_status": _text(values.get("qa_status")) or "UNKNOWN",
        "created_at": _text(values.get("created_at")),
        "completed_at": _text(values.get("completed_at")),
        "failure_code": _text(values.get("failure_code")),
        "retry_count": max(int(values.get("retry_count") or 0), 0),
        "_success": bool(values.get("success")),
        "_failed": bool(values.get("failed")),
        "_actual_at": _text(values.get("completed_at") or values.get("created_at")),
        "_authority": _text(values.get("authority")),
    }
    return record


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


async def _load_product_names() -> dict[str, str]:
    rows = await _rows(
        """SELECT id AS product_id, product_display_name, product_short_name,
                  raw_product_title
           FROM product"""
    )
    return {str(row["product_id"]): _product_name(row) or str(row["product_id"]) for row in rows}


async def _production_studio_records(start: str, end: str, product_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = await _rows(
        """SELECT a.attempt_id, a.item_id, a.attempt_number, a.attempt_state,
                  a.provider, a.engine, a.model_key, a.last_actor_id,
                  a.staff_id AS attempt_staff_id,
                  a.staff_display_name_snapshot AS attempt_staff_name,
                  a.artifact_media_id, a.failure_code, a.created_at,
                  a.generated_at, a.retrieved_at, a.registered_at, a.completed_at,
                  item.plan_id, item.product_id, item.media_type,
                  item.production_recipe AS item_recipe, item.status AS item_status,
                  item.output_media_id, plan.created_by,
                  item.staff_id AS item_staff_id,
                  item.staff_display_name_snapshot AS item_staff_name,
                  plan.staff_id AS plan_staff_id,
                  plan.staff_display_name_snapshot AS plan_staff_name,
                  qa.status AS qa_status,
                  qa.staff_id AS qa_staff_id,
                  qa.staff_display_name_snapshot AS qa_staff_name,
                  p.product_display_name, p.product_short_name, p.raw_product_title
           FROM creative_generation_attempt a
           JOIN creative_production_item item ON item.item_id = a.item_id
           JOIN creative_production_plan plan ON plan.plan_id = item.plan_id
           LEFT JOIN creative_output_qa qa
             ON qa.item_id = item.item_id AND qa.attempt_id = a.attempt_id
           LEFT JOIN product p ON p.id = item.product_id
           WHERE item.media_type = 'VIDEO'
             AND item.production_recipe IN ('HYBRID','FACELESS','MONTAGE')
             AND COALESCE(a.completed_at, a.registered_at, a.retrieved_at,
                          a.generated_at, a.created_at, item.updated_at) >= ?
             AND COALESCE(a.completed_at, a.registered_at, a.retrieved_at,
                          a.generated_at, a.created_at, item.updated_at) < ?
           ORDER BY COALESCE(a.completed_at, a.created_at) DESC, a.attempt_id DESC""",
        (start, end),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        product_id = row.get("product_id")
        if _is_test_product(product_id, row.get("product_display_name"), row.get("product_short_name"), row.get("raw_product_title")):
            continue
        model = row.get("model_key") or row.get("engine")
        if _model_is_retired(model):
            continue
        staff_id, staff_name = _resolve_staff(
            (row.get("attempt_staff_id"), row.get("attempt_staff_name")),
            (row.get("item_staff_id"), row.get("item_staff_name")),
            (row.get("plan_staff_id"), row.get("plan_staff_name")),
            (row.get("qa_staff_id"), row.get("qa_staff_name")),
            (row.get("last_actor_id"), None),
            (row.get("created_by"), None),
        )
        state = str(row.get("attempt_state") or "").upper()
        item_status = str(row.get("item_status") or "").upper()
        artifact = row.get("artifact_media_id") or row.get("output_media_id")
        failed = state in _FAILED_STATES or item_status == "FAILED"
        success = bool(artifact) and state not in {"FAILED", "CANCELLED", "SUPERSEDED", "QA_REJECTED"} and item_status not in {"FAILED", "CANCELLED", "SUPERSEDED", "QA_REJECTED"}
        records.append(
            _base_record(
                output_id=row.get("item_id"),
                media_type=row.get("media_type"),
                production_recipe=row.get("item_recipe"),
                origin_surface="PRODUCTION_STUDIO",
                staff_id=staff_id,
                staff_display_name=staff_name,
                product_id=product_id,
                product_name=product_names.get(str(product_id)) if product_id else _product_name(row),
                plan_or_run_id=row.get("plan_id"),
                production_item_id=row.get("item_id"),
                attempt_id=row.get("attempt_id"),
                attempt_number=row.get("attempt_number"),
                provider=row.get("provider"),
                model_key=model,
                status="FAILED" if failed else ("SUCCESS" if success else state or item_status or "UNKNOWN"),
                artifact_media_id=artifact,
                qa_status=row.get("qa_status") or ("QA_APPROVED" if item_status == "QA_APPROVED" else "UNKNOWN"),
                created_at=row.get("created_at"),
                completed_at=row.get("completed_at") or row.get("registered_at") or row.get("retrieved_at"),
                failure_code=row.get("failure_code"),
                retry_count=max(int(row.get("attempt_number") or 1) - 1, 0),
                success=success,
                failed=failed,
                authority="P6_PRODUCTION_STUDIO",
            )
        )
    return records


def _lineage_recipe(*payloads: Any) -> str | None:
    """Resolve only explicit business-lineage evidence; never infer from transport mode."""

    tokens: set[str] = set()
    faceless_evidence = False

    def visit(value: Any, key: str | None = None) -> None:
        nonlocal faceless_evidence
        if isinstance(value, dict):
            for child_key, child in value.items():
                normalized_key = str(child_key).casefold()
                if normalized_key in {
                    "faceless_resolution",
                    "faceless_execution_identity",
                    "faceless_execution",
                } and child:
                    faceless_evidence = True
                if normalized_key in {
                    "production_recipe",
                    "business_recipe",
                    "recipe",
                    "source_mode",
                    "source_lane",
                    "lane",
                    "surface",
                    "origin_surface",
                }:
                    if isinstance(child, str):
                        tokens.add(child.strip().upper())
                visit(child, normalized_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    for payload in payloads:
        if isinstance(payload, str) and payload.strip().upper() in VIDEO_RECIPES:
            tokens.add(payload.strip().upper())
        visit(_json(payload))
        if isinstance(payload, str):
            visit(payload)
    if faceless_evidence or "FACELESS" in tokens:
        return "FACELESS"
    if "MONTAGE" in tokens:
        return "MONTAGE"
    if "HYBRID" in tokens:
        return "HYBRID"
    return None


def _lineage_staff(*payloads: Any) -> tuple[str | None, str | None]:
    canonical: list[tuple[Any, Any]] = []
    legacy: list[tuple[Any, Any]] = []
    keys = {"operator_id", "operator", "actor_id", "created_by"}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).casefold()
                if normalized_key == "staff_id" and isinstance(child, (str, int)):
                    canonical.append(
                        (
                            child,
                            value.get("staff_display_name_snapshot") or value.get("staff_display_name"),
                        )
                    )
                elif normalized_key in keys and isinstance(child, (str, int)):
                    legacy.append((child, value.get("operator_display_name")))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for payload in payloads:
        visit(_json(payload))
    return _resolve_staff(*canonical, *legacy)


def _package_columns(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        {"staff_id": row.get("gr_staff_id"), "staff_display_name_snapshot": row.get("gr_staff_name")},
        {"staff_id": row.get("ga_staff_id"), "staff_display_name_snapshot": row.get("ga_staff_name")},
        {"staff_id": row.get("rt_staff_id"), "staff_display_name_snapshot": row.get("rt_staff_name")},
        {"staff_id": row.get("wgp_staff_id"), "staff_display_name_snapshot": row.get("wgp_staff_name")},
        {"staff_id": row.get("wep_staff_id"), "staff_display_name_snapshot": row.get("wep_staff_name")},
        row.get("rt_lineage"),
        row.get("wgp_source_lane"),
        row.get("wgp_mode"),
        row.get("wgp_generation_identity"),
        row.get("wgp_resolver_output"),
        row.get("wep_lineage"),
        row.get("wep_mode"),
    )


def _standalone_record(row: dict[str, Any], product_names: dict[str, str], *, failed: bool = False) -> dict[str, Any] | None:
    recipe = _lineage_recipe(*_package_columns(row))
    if recipe not in VIDEO_RECIPES:
        return None
    if row.get("linked_p6_item_id"):
        return None
    product_id = row.get("product_id") or row.get("rt_product_id")
    product_name = row.get("product_name") or product_names.get(str(product_id))
    if _is_test_product(product_id, product_name):
        return None
    model = row.get("model_label") or row.get("artifact_model") or row.get("wgp_model")
    if _model_is_retired(model):
        return None
    operator_id, operator_name = _lineage_staff(*_package_columns(row))
    output_id = row.get("media_id") or row.get("artifact_media_id") or row.get("request_id")
    artifact = (row.get("media_id") or row.get("artifact_media_id")) if not failed else None
    status = "FAILED" if failed else "SUCCESS"
    attempt_number = int(row.get("request_retry_count") or 0) + 1
    return _base_record(
        output_id=output_id,
        media_type="VIDEO",
        production_recipe=recipe,
        origin_surface="STANDALONE",
        staff_id=operator_id,
        staff_display_name=operator_name,
        product_id=product_id,
        product_name=product_name,
        plan_or_run_id=row.get("workspace_generation_package_id") or row.get("job_id") or row.get("request_id"),
        attempt_id=row.get("request_id") or row.get("job_id") or output_id,
        attempt_number=attempt_number,
        provider=row.get("provider") or "GOOGLE_FLOW",
        model_key=model,
        status=status,
        artifact_media_id=artifact,
        qa_status="UNKNOWN",
        created_at=row.get("actual_created_at") or row.get("created_at"),
        completed_at=row.get("completed_at") or row.get("failed_at"),
        failure_code=row.get("error_code"),
        retry_count=int(row.get("request_retry_count") or 0),
        success=not failed and bool(artifact),
        failed=failed,
        authority="STANDALONE_VIDEO_RECEIPT",
    )


_STANDALONE_SELECT = """SELECT gr.media_id, ga.media_id AS artifact_media_id,
             gr.job_id, gr.request_id, gr.mode,
             gr.staff_id AS gr_staff_id,
             gr.staff_display_name_snapshot AS gr_staff_name,
             gr.product_id, gr.product_name, gr.workspace_generation_package_id,
             gr.created_at AS gr_created_at,
             ga.staff_id AS ga_staff_id,
             ga.staff_display_name_snapshot AS ga_staff_name,
             ga.model_used AS artifact_model, ga.created_at AS artifact_created_at,
             rt.product_id AS rt_product_id,
             rt.staff_id AS rt_staff_id,
             rt.staff_display_name_snapshot AS rt_staff_name,
             rt.request_lineage_payload AS rt_lineage,
             rt.provider, rt.model_label, rt.completed_at, rt.failed_at,
             rt.error_code, rt.mode AS rt_mode,
             req.retry_count AS request_retry_count,
             wgp.source_lane AS wgp_source_lane, wgp.mode AS wgp_mode,
             wgp.staff_id AS wgp_staff_id,
             wgp.staff_display_name_snapshot AS wgp_staff_name,
             wgp.generation_identity_json AS wgp_generation_identity,
             wgp.resolver_output_json AS wgp_resolver_output,
             wep.mode AS wep_mode,
             wep.staff_id AS wep_staff_id,
             wep.staff_display_name_snapshot AS wep_staff_name,
             wep.request_lineage_payload AS wep_lineage,
             linked_item.item_id AS linked_p6_item_id,
             COALESCE(gr.created_at, ga.created_at, rt.completed_at, rt.failed_at) AS actual_created_at
      FROM generation_result gr
      LEFT JOIN generated_artifact ga ON ga.media_id = gr.media_id
      LEFT JOIN request_telemetry rt ON rt.request_id = gr.request_id
      LEFT JOIN request req ON req.id = gr.request_id
      LEFT JOIN workspace_generation_package wgp
        ON wgp.workspace_generation_package_id = gr.workspace_generation_package_id
      LEFT JOIN workspace_execution_package wep
        ON wep.workspace_execution_package_id = COALESCE(
             wgp.workspace_execution_package_id, gr.workspace_generation_package_id)
      LEFT JOIN creative_production_item linked_item
        ON linked_item.workspace_generation_package_id = wgp.workspace_generation_package_id
      WHERE gr.artifact_kind = 'video'
        AND COALESCE(gr.created_at, ga.created_at) >= ?
        AND COALESCE(gr.created_at, ga.created_at) < ?"""


async def _standalone_success_records(start: str, end: str, product_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = await _rows(_STANDALONE_SELECT, (start, end))
    records: list[dict[str, Any]] = []
    for row in rows:
        record = _standalone_record(
            {**row, "created_at": row.get("gr_created_at") or row.get("artifact_created_at")},
            product_names,
        )
        if record:
            records.append(record)

    # Durable artifact receipts can outlive generation_result creation in older
    # deployments.  They are included only when the same media id was not already
    # represented above; lineage still has to prove an exact current recipe.
    artifact_rows = await _rows(
        _STANDALONE_SELECT.replace(
            "FROM generation_result gr\n      LEFT JOIN generated_artifact ga ON ga.media_id = gr.media_id",
            "FROM generated_artifact ga\n      LEFT JOIN generation_result gr ON gr.media_id = ga.media_id",
        ).replace(
            "WHERE gr.artifact_kind = 'video'",
            "WHERE ga.artifact_kind = 'video'",
        ),
        (start, end),
    )
    existing = {record.get("output_id") for record in records}
    for row in artifact_rows:
        if (row.get("media_id") or row.get("artifact_media_id")) in existing:
            continue
        row["gr_created_at"] = row.get("artifact_created_at") or row.get("actual_created_at")
        record = _standalone_record({**row, "created_at": row.get("gr_created_at")}, product_names)
        if record:
            records.append(record)
    return records


async def _standalone_failed_records(start: str, end: str, product_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = await _rows(
        """SELECT rt.request_id, rt.product_id,
                  rt.staff_id AS rt_staff_id,
                  rt.staff_display_name_snapshot AS rt_staff_name,
                  rt.request_lineage_payload AS rt_lineage,
                  rt.provider, rt.model_label, rt.mode AS rt_mode, rt.created_at,
                  rt.completed_at, rt.failed_at, rt.error_code,
                  rt.workspace_generation_package_id,
                  req.retry_count AS request_retry_count,
                  wgp.source_lane AS wgp_source_lane, wgp.mode AS wgp_mode,
                  wgp.staff_id AS wgp_staff_id,
                  wgp.staff_display_name_snapshot AS wgp_staff_name,
                  wgp.generation_identity_json AS wgp_generation_identity,
                  wgp.resolver_output_json AS wgp_resolver_output,
                  wep.mode AS wep_mode,
                  wep.staff_id AS wep_staff_id,
                  wep.staff_display_name_snapshot AS wep_staff_name,
                  wep.request_lineage_payload AS wep_lineage,
                  NULL AS media_id, NULL AS job_id,
                  COALESCE(rt.failed_at, rt.completed_at, rt.created_at) AS actual_created_at
           FROM request_telemetry rt
           LEFT JOIN request req ON req.id = rt.request_id
           LEFT JOIN workspace_generation_package wgp
             ON wgp.workspace_generation_package_id = rt.workspace_generation_package_id
           LEFT JOIN workspace_execution_package wep
             ON wep.workspace_execution_package_id = COALESCE(
                  wgp.workspace_execution_package_id, rt.workspace_execution_package_id)
           WHERE UPPER(COALESCE(rt.status,'')) = 'FAILED'
             AND COALESCE(rt.failed_at, rt.completed_at, rt.created_at) >= ?
             AND COALESCE(rt.failed_at, rt.completed_at, rt.created_at) < ?""",
        (start, end),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        record = _standalone_record(row, product_names, failed=True)
        if record:
            records.append(record)
    return records


async def _montage_records(start: str, end: str, product_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = await _rows(
        """SELECT r.bulk_run_id, r.status AS run_status, r.config_json,
                  r.staff_id AS run_staff_id,
                  r.staff_display_name_snapshot AS run_staff_name,
                  r.created_at AS run_created_at, r.updated_at AS run_updated_at,
                  i.bulk_item_id, i.status AS item_status, i.job_id, i.media_id,
                  i.staff_id AS item_staff_id,
                  i.staff_display_name_snapshot AS item_staff_name,
                  i.payload_json, i.error, i.retry_count, i.started_at,
                  i.completed_at, i.created_at AS item_created_at
           FROM bulk_generation_run r
           LEFT JOIN bulk_generation_item i ON i.bulk_run_id = r.bulk_run_id
           WHERE r.kind = 'MONTAGE_DISCRETE'
             AND COALESCE(i.completed_at, i.updated_at, r.updated_at, r.created_at) >= ?
             AND COALESCE(i.completed_at, i.updated_at, r.updated_at, r.created_at) < ?
           ORDER BY COALESCE(i.completed_at, i.created_at, r.updated_at) DESC""",
        (start, end),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        config = _json(row.get("config_json"))
        payload = _json(row.get("payload_json"))
        product_id = config.get("product_id") or payload.get("product_id")
        product_name = config.get("product_name") or payload.get("product_name") or product_names.get(str(product_id))
        if _is_test_product(product_id, product_name):
            continue
        model = config.get("model") or config.get("model_key") or payload.get("model")
        if _model_is_retired(model):
            continue
        run_status = str(row.get("run_status") or "").upper()
        status = str(row.get("item_status") or run_status or "").upper()
        if row.get("bulk_item_id") and status not in _MONTAGE_ACTUAL_STATUSES:
            continue
        assembly = config.get("assembly") if isinstance(config.get("assembly"), dict) else {}
        concat = assembly.get("concat") if isinstance(assembly.get("concat"), dict) else {}
        artifact = (
            row.get("media_id")
            or payload.get("video_media_id")
            or payload.get("artifact_media_id")
            or assembly.get("final_media_id")
            or concat.get("final_media_id")
        )
        failed = status in _FAILED_STATES or bool(row.get("error"))
        success = bool(artifact) and (
            status in _MONTAGE_SUCCESS_STATUSES
            or (not row.get("bulk_item_id") and run_status in {"COMPLETE", "ASSEMBLY_READY"})
        ) and not failed
        staff_id, staff_name = _resolve_staff(
            (row.get("run_staff_id"), row.get("run_staff_name")),
            (row.get("item_staff_id"), row.get("item_staff_name")),
            (
                config.get("staff_id"),
                config.get("staff_display_name_snapshot") or config.get("staff_display_name"),
            ),
            (
                payload.get("staff_id"),
                payload.get("staff_display_name_snapshot") or payload.get("staff_display_name"),
            ),
            (config.get("operator_id"), None),
            (payload.get("operator_id"), None),
        )
        records.append(
            _base_record(
                output_id=row.get("bulk_run_id"),
                media_type="VIDEO",
                production_recipe="MONTAGE",
                origin_surface="STANDALONE",
                staff_id=staff_id,
                staff_display_name=staff_name,
                product_id=product_id,
                product_name=product_name,
                plan_or_run_id=row.get("bulk_run_id"),
                production_item_id=None,
                attempt_id=row.get("bulk_item_id") or row.get("bulk_run_id"),
                attempt_number=int(row.get("retry_count") or 0) + 1,
                provider=config.get("provider") or "GOOGLE_FLOW",
                model_key=model,
                status="FAILED" if failed else ("SUCCESS" if success else status or "UNKNOWN"),
                artifact_media_id=artifact,
                qa_status="UNKNOWN",
                created_at=row.get("item_created_at") or row.get("run_created_at"),
                completed_at=row.get("completed_at") or row.get("run_updated_at"),
                failure_code=row.get("error"),
                retry_count=row.get("retry_count"),
                success=success,
                failed=failed,
                authority="MONTAGE_RUN",
            )
        )
    return records


def _poster_qa_status(value: Any) -> str:
    payload = _json(value)
    block_count = payload.get("block_count")
    try:
        has_blocks = int(block_count or 0) > 0
    except (TypeError, ValueError):
        has_blocks = bool(payload.get("blockers"))
    if (payload.get("ok") is True or str(payload.get("status") or "").upper() in {"PASS", "PASSED", "APPROVED", "QA_APPROVED"}) and not has_blocks:
        return "QA_APPROVED"
    if payload:
        return "QA_REJECTED" if has_blocks or payload.get("ok") is False else "QA_PENDING"
    return "UNKNOWN"


async def _poster_records(start: str, end: str, product_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = await _rows(
        """SELECT d.poster_deliverable_id, d.product_id, d.output_path,
                  d.staff_id, d.staff_display_name_snapshot,
                  d.output_sha256, d.creative_asset_id, d.qa_report_json,
                  d.settings_json, d.status, d.recipe_id, d.created_at, d.updated_at,
                  p.product_display_name, p.product_short_name, p.raw_product_title
           FROM poster_deliverable d
           LEFT JOIN product p ON p.id = d.product_id
           WHERE d.status IN ('POSTER_COMPOSED','POSTER_SAVED')
             AND (COALESCE(d.output_path,'') <> '' OR COALESCE(d.output_sha256,'') <> ''
                  OR COALESCE(d.creative_asset_id,'') <> '')
             AND COALESCE(d.updated_at, d.created_at) >= ?
             AND COALESCE(d.updated_at, d.created_at) < ?
           ORDER BY COALESCE(d.updated_at, d.created_at) DESC""",
        (start, end),
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        if _is_test_product(row.get("product_id"), row.get("product_display_name"), row.get("product_short_name"), row.get("raw_product_title")):
            continue
        settings = _json(row.get("settings_json"))
        model = settings.get("image_model") or settings.get("model_key")
        if _model_is_retired(model):
            continue
        staff_id, staff_name = _resolve_staff(
            (row.get("staff_id"), row.get("staff_display_name_snapshot")),
            (
                settings.get("staff_id"),
                settings.get("staff_display_name_snapshot") or settings.get("staff_display_name"),
            ),
            (settings.get("operator_id"), None),
            (settings.get("created_by"), None),
        )
        artifact = row.get("creative_asset_id") or row.get("output_sha256") or row.get("output_path")
        records.append(
            _base_record(
                output_id=row.get("poster_deliverable_id"),
                media_type="POSTER",
                production_recipe="POSTER_BUILDER",
                origin_surface="POSTER_BUILDER",
                staff_id=staff_id,
                staff_display_name=staff_name,
                product_id=row.get("product_id"),
                product_name=product_names.get(str(row.get("product_id"))) or _product_name(row),
                plan_or_run_id=row.get("poster_deliverable_id"),
                attempt_id=row.get("poster_deliverable_id"),
                provider=None,
                model_key=model,
                status="SUCCESS",
                artifact_media_id=row.get("creative_asset_id"),
                qa_status=_poster_qa_status(row.get("qa_report_json")),
                created_at=row.get("created_at"),
                completed_at=row.get("updated_at"),
                retry_count=0,
                success=bool(artifact),
                failed=False,
                authority="POSTER_DELIVERABLE",
            )
        )
    return records


def _matches(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    if (
        record.get("media_type") not in MEDIA_TYPES
        or record.get("production_recipe") not in REPORTING_RECIPES
        or record.get("origin_surface") not in ORIGIN_SURFACES
    ):
        return False
    pairs = {
        "staff": "operator_id",
        "media_type": "media_type",
        "production_recipe": "production_recipe",
        "origin_surface": "origin_surface",
        "product_id": "product_id",
        "provider": "provider",
        "model_key": "model_key",
        "status": "status",
        "qa_status": "qa_status",
    }
    for filter_key, record_key in pairs.items():
        requested = _text(filters.get(filter_key))
        if requested and str(record.get(record_key) or "") != requested:
            return False
    return True


def _success_outputs(records: Iterable[dict[str, Any]]) -> set[str]:
    return {str(record["output_id"]) for record in records if record.get("_success") and record.get("output_id")}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _metric_block(records: list[dict[str, Any]]) -> dict[str, Any]:
    successful = _success_outputs(records)
    video = _success_outputs([r for r in records if r.get("media_type") == "VIDEO"])
    image_poster = _success_outputs([r for r in records if r.get("media_type") in {"IMAGE", "POSTER"}])
    qa = {
        str(r["output_id"])
        for r in records
        if r.get("_success") and r.get("qa_status") == "QA_APPROVED" and r.get("output_id")
    }
    failed = sum(1 for record in records if record.get("_failed"))
    retries = sum(1 for record in records if int(record.get("retry_count") or 0) > 0)
    return {
        "total_attempts": len(records),
        "successful_outputs": len(successful),
        "successful_video_outputs": len(video),
        "successful_image_poster_outputs": len(image_poster),
        "qa_approved": len(qa),
        "failed_attempts": failed,
        "retry_attempts": retries,
        "success_rate": _rate(len(successful), len(records)),
        "retry_rate": _rate(retries, len(records)),
        "active_staff": len({r.get("operator_id") for r in records if r.get("operator_id")}),
        "unique_products": len({r.get("product_id") for r in records if r.get("product_id")}),
    }


def _breakdown(records: list[dict[str, Any]], recipes: Iterable[str]) -> list[dict[str, Any]]:
    result = []
    for recipe in recipes:
        subset = [record for record in records if record.get("production_recipe") == recipe]
        metrics = _metric_block(subset)
        result.append({"production_recipe": recipe, **metrics})
    return result


def _staff_performance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_staff: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("operator_id"):
            by_staff[str(record["operator_id"])].append(record)
    result: list[dict[str, Any]] = []
    for staff, staff_records in by_staff.items():
        successful_by_recipe: dict[str, set[str]] = defaultdict(set)
        successful: set[str] = set()
        qa: set[str] = set()
        for record in staff_records:
            output_id = record.get("output_id")
            if record.get("_success") and output_id:
                successful.add(str(output_id))
                successful_by_recipe[str(record.get("production_recipe"))].add(str(output_id))
                if record.get("qa_status") == "QA_APPROVED":
                    qa.add(str(output_id))
        retries = sum(1 for record in staff_records if int(record.get("retry_count") or 0) > 0)
        result.append(
            {
                "staff": staff,
                "staff_display_name": next((r.get("operator_display_name") for r in staff_records if r.get("operator_display_name")), staff),
                "hybrid": len(successful_by_recipe.get("HYBRID", set())),
                "faceless": len(successful_by_recipe.get("FACELESS", set())),
                "montage": len(successful_by_recipe.get("MONTAGE", set())),
                "poster": len(successful_by_recipe.get("POSTER_BUILDER", set())),
                "successful_outputs": len(successful),
                "qa_approved": len(qa),
                "failed_attempts": sum(1 for record in staff_records if record.get("_failed")),
                "retry_attempts": retries,
                "retry_rate": _rate(retries, len(staff_records)),
                "success_rate": _rate(len(successful), len(staff_records)),
                "unique_products": len({r.get("product_id") for r in staff_records if r.get("product_id")}),
            }
        )
    return sorted(result, key=lambda row: (-row["successful_outputs"], row["staff_display_name"].casefold()))


def _daily_trend(records: list[dict[str, Any]], window: dict[str, str | int]) -> list[dict[str, Any]]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        day = _local_day(record.get("_actual_at") or record.get("completed_at") or record.get("created_at"))
        if day:
            by_day[day].append(record)
    start = date.fromisoformat(str(window["start_date"]))
    end = date.fromisoformat(str(window["end_date"]))
    result = []
    current = start
    while current <= end:
        day = current.isoformat()
        day_records = by_day.get(day, [])
        result.append(
            {
                "date": day,
                "successful_video": len(_success_outputs([r for r in day_records if r.get("media_type") == "VIDEO"])),
                "successful_image_poster": len(_success_outputs([r for r in day_records if r.get("media_type") in {"IMAGE", "POSTER"}])),
                "failed_attempts": sum(1 for r in day_records if r.get("_failed")),
            }
        )
        current += timedelta(days=1)
    return result


def _filter_options(records: list[dict[str, Any]]) -> dict[str, list[dict[str, str]] | list[str]]:
    # Defense in depth: adapters are already fail-closed, but option generation
    # must never echo a legacy/internal value even if a future adapter regresses.
    records = [
        record
        for record in records
        if record.get("media_type") in MEDIA_TYPES
        and record.get("production_recipe") in REPORTING_RECIPES
        and record.get("origin_surface") in ORIGIN_SURFACES
    ]

    def values(key: str) -> list[str]:
        return sorted({str(r[key]) for r in records if r.get(key)}, key=str.casefold)

    products = sorted(
        {
            (str(r.get("product_id")), str(r.get("product_name") or r.get("product_id")))
            for r in records
            if r.get("product_id")
        },
        key=lambda item: item[1].casefold(),
    )
    staff_labels = {
        str(record["operator_id"]): str(record.get("operator_display_name") or record["operator_id"])
        for record in records
        if record.get("operator_id")
    }
    return {
        "staff": [
            {"value": value, "label": staff_labels.get(value, value)}
            for value in values("operator_id")
        ],
        "media_types": list(MEDIA_TYPES),
        "production_recipes": list(REPORTING_RECIPES),
        "origin_surfaces": list(ORIGIN_SURFACES),
        "products": [{"value": value, "label": label} for value, label in products],
        "providers": values("provider"),
        "models": values("model_key"),
        "statuses": values("status"),
        "qa_statuses": values("qa_status"),
    }


async def _all_records(window: dict[str, str | int]) -> list[dict[str, Any]]:
    product_names = await _load_product_names()
    start, end = str(window["start_utc"]), str(window["end_utc"])
    batches = await asyncio.gather(
        _production_studio_records(start, end, product_names),
        _standalone_success_records(start, end, product_names),
        _standalone_failed_records(start, end, product_names),
        _montage_records(start, end, product_names),
        _poster_records(start, end, product_names),
    )
    records: list[dict[str, Any]] = []
    seen_failures: set[tuple[str, str]] = set()
    for batch in batches:
        for record in batch:
            key = (str(record.get("attempt_id")), str(record.get("status")))
            if record.get("_failed") and key in seen_failures:
                continue
            if record.get("_failed"):
                seen_failures.add(key)
            records.append(record)
    return records


async def get_production_report(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    window = reporting_window(start_date, end_date)
    all_records = [record for record in await _all_records(window) if _matches(record, {})]
    active_filters = filters or {}
    records = [record for record in all_records if _matches(record, active_filters)]
    overview = _metric_block(records)
    return {
        "reporting_timezone": REPORTING_TIMEZONE,
        "window": window,
        "metric_definitions": {
            "successful_outputs": "Distinct output_id values with a genuine artifact/output.",
            "success_rate": "successful_outputs divided by total_attempts; null means zero attempts.",
            "retry_rate": "retry_attempts divided by total_attempts; null means zero attempts.",
            "qa_approved": "Distinct successful output_id values with authoritative QA approval.",
            "staff_performance": "Unattributed rows remain in overall reporting but are excluded from staff metrics.",
        },
        "filters": _filter_options(all_records),
        "overview": overview,
        "video_breakdown": _breakdown(records, VIDEO_RECIPES),
        "poster_breakdown": _breakdown(records, ("POSTER_BUILDER",)),
        "staff_performance": _staff_performance(records),
        "daily_trend": _daily_trend(records, window),
    }


async def get_production_ledger(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise ValueError("LEDGER_LIMIT_MUST_BE_1_TO_200")
    if offset < 0:
        raise ValueError("LEDGER_OFFSET_MUST_BE_NON_NEGATIVE")
    window = reporting_window(start_date, end_date)
    all_records = [record for record in await _all_records(window) if _matches(record, {})]
    records = [record for record in all_records if _matches(record, filters or {})]
    records.sort(
        key=lambda record: (
            str(record.get("_actual_at") or record.get("created_at") or ""),
            str(record.get("attempt_id") or ""),
        ),
        reverse=True,
    )
    items = [_public_record(record) for record in records[offset : offset + limit]]
    return {
        "reporting_timezone": REPORTING_TIMEZONE,
        "window": window,
        "items": items,
        "total": len(records),
        "limit": limit,
        "offset": offset,
    }


def validate_filter_value(name: str, value: str | None) -> None:
    if not value:
        return
    allowed = {
        "media_type": MEDIA_TYPES,
        "production_recipe": REPORTING_RECIPES,
        "origin_surface": ORIGIN_SURFACES,
    }.get(name)
    if allowed and value not in allowed:
        raise ValueError(f"UNKNOWN_CURRENT_{name.upper()}")
