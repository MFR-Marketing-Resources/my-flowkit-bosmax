"""Read-only aggregation logic for the BOSMAX Command Centre (Tier A).

ALL reporting aggregation / filtering / KPI calculation / drill-down selection lives
here (the service layer), not in the router and never in the frontend. The router
(`agent/api/reporting.py`) is a thin transport wrapper; the frontend chart components
are pure views. This keeps the chart library swappable and the logic unit-testable.

Everything here is read-only SQL over the live DB — no writes, no credit, no side
effects. Functions accept the cross-filter + pagination seam params
(lifecycle_status / cluster / product_type_group / limit / offset) and apply them
server-side, so those capabilities can light up later without an API change.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from agent.db.schema import get_db

# Base relation for product-scoped queries: product LEFT JOIN its taxonomy sidecar
# (1:1 via a DB trigger; LEFT JOIN keeps a product with no taxonomy row visible as
# "missing cluster" instead of dropping it).
_PRODUCT_BASE = (
    "FROM product p "
    "LEFT JOIN product_strategy_taxonomy t ON t.product_id = p.id"
)

_DISPLAY_NAME = (
    "COALESCE(p.product_display_name, p.product_short_name, p.raw_product_title, p.id)"
)

# Exception kind -> product-scoped WHERE predicate. `failed_generation` is
# request-telemetry scoped and handled separately in list_exceptions().
_EXCEPTION_PREDICATES: dict[str, str] = {
    "missing_cluster": "(t.cluster IS NULL OR t.cluster = 'generic_unclassified')",
    "missing_product_type": "(t.product_type_group IS NULL OR t.product_type_group = 'unknown_product_type')",
    "mapping_blocked": "p.mapping_status = 'BLOCKED'",
    "missing_copy": "NOT EXISTS (SELECT 1 FROM copy_set c WHERE c.product_id = p.id AND COALESCE(c.archived, 0) = 0)",
    "missing_intelligence": "NOT EXISTS (SELECT 1 FROM product_intelligence_snapshot s WHERE s.product_id = p.id)",
    "missing_image": "p.asset_status = 'UNRESOLVED'",
    "prompt_not_ready": "p.prompt_readiness_status = 'MISSING_FIELDS'",
}
EXCEPTION_KINDS: tuple[str, ...] = tuple(_EXCEPTION_PREDICATES.keys()) + ("failed_generation",)


def _product_filters(
    lifecycle_status: Optional[str],
    cluster: Optional[str],
    product_type_group: Optional[str],
) -> tuple[str, list]:
    """Return an ' AND ...'-prefixed SQL fragment + params for the seam filters.

    lifecycle_status defaults to ACTIVE (management KPIs care about live products);
    pass 'ALL' to include archived.
    """
    frags: list[str] = []
    params: list = []
    ls = (lifecycle_status or "ACTIVE").strip().upper()
    if ls != "ALL":
        frags.append("p.lifecycle_status = ?")
        params.append(ls)
    if cluster:
        frags.append("t.cluster = ?")
        params.append(cluster)
    if product_type_group:
        frags.append("t.product_type_group = ?")
        params.append(product_type_group)
    where = "" if not frags else " AND " + " AND ".join(frags)
    return where, params


def _scope(lifecycle_status, cluster, product_type_group) -> dict:
    return {
        "lifecycle_status": (lifecycle_status or "ACTIVE").strip().upper(),
        "cluster": cluster,
        "product_type_group": product_type_group,
    }


async def _scalar(db, sql: str, params: list) -> int:
    cur = await db.execute(sql, params)
    row = await cur.fetchone()
    await cur.close()
    return int(row[0]) if row and row[0] is not None else 0


async def copywriting_coverage(
    lifecycle_status: str = "ACTIVE",
    cluster: Optional[str] = None,
    product_type_group: Optional[str] = None,
) -> dict:
    """Authored-copy coverage: in-scope products with >=1 non-archived copy_set.

    This is the '646/659 missing copywriting' metric — distinct from the existing
    catalog-coverage endpoint (P4-support / P6-launch readiness, not authored copy).
    """
    db = await get_db()
    where, params = _product_filters(lifecycle_status, cluster, product_type_group)
    total = await _scalar(db, f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{where}", params)
    with_copy = await _scalar(
        db,
        f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{where} "
        "AND EXISTS (SELECT 1 FROM copy_set c WHERE c.product_id = p.id AND COALESCE(c.archived, 0) = 0)",
        params,
    )
    with_approved = await _scalar(
        db,
        f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{where} "
        "AND EXISTS (SELECT 1 FROM copy_set c WHERE c.product_id = p.id "
        "AND c.status = 'COPY_APPROVED' AND COALESCE(c.archived, 0) = 0)",
        params,
    )
    total_sets = await _scalar(
        db,
        "SELECT COUNT(*) FROM copy_set c JOIN product p ON p.id = c.product_id "
        "LEFT JOIN product_strategy_taxonomy t ON t.product_id = p.id "
        f"WHERE COALESCE(c.archived, 0) = 0{where}",
        params,
    )
    cur = await db.execute(
        "SELECT c.status AS status, COUNT(*) AS n "
        "FROM copy_set c JOIN product p ON p.id = c.product_id "
        "LEFT JOIN product_strategy_taxonomy t ON t.product_id = p.id "
        f"WHERE COALESCE(c.archived, 0) = 0{where} GROUP BY c.status",
        params,
    )
    by_status = {r["status"]: int(r["n"]) for r in await cur.fetchall()}
    await cur.close()
    return {
        "scope": _scope(lifecycle_status, cluster, product_type_group),
        "total_products": total,
        "products_with_copy": with_copy,
        "products_missing_copy": total - with_copy,
        "products_with_approved_copy": with_approved,
        "coverage_pct": round(100.0 * with_copy / total, 1) if total else 0.0,
        "total_copy_sets": total_sets,
        "avg_sets_per_covered_product": round(total_sets / with_copy, 2) if with_copy else 0.0,
        "copy_set_by_status": by_status,
    }


async def product_intelligence_coverage(
    lifecycle_status: str = "ACTIVE",
    cluster: Optional[str] = None,
    product_type_group: Optional[str] = None,
) -> dict:
    """Product-intelligence snapshot coverage: in-scope products with >=1 snapshot."""
    db = await get_db()
    where, params = _product_filters(lifecycle_status, cluster, product_type_group)
    total = await _scalar(db, f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{where}", params)
    with_snapshot = await _scalar(
        db,
        f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{where} "
        "AND EXISTS (SELECT 1 FROM product_intelligence_snapshot s WHERE s.product_id = p.id)",
        params,
    )
    return {
        "scope": _scope(lifecycle_status, cluster, product_type_group),
        "total_products": total,
        "with_snapshot": with_snapshot,
        "missing_snapshot": total - with_snapshot,
        "coverage_pct": round(100.0 * with_snapshot / total, 1) if total else 0.0,
    }


async def prompt_readiness_histogram(
    lifecycle_status: str = "ACTIVE",
    cluster: Optional[str] = None,
    product_type_group: Optional[str] = None,
) -> dict:
    """Prompt-readiness histogram. NULL is surfaced honestly as 'not_evaluated'
    (most products are not yet evaluated), never hidden."""
    db = await get_db()
    where, params = _product_filters(lifecycle_status, cluster, product_type_group)
    cur = await db.execute(
        "SELECT COALESCE(p.prompt_readiness_status, 'not_evaluated') AS status, COUNT(*) AS n "
        f"{_PRODUCT_BASE} WHERE 1=1{where} GROUP BY p.prompt_readiness_status",
        params,
    )
    raw = {r["status"]: int(r["n"]) for r in await cur.fetchall()}
    await cur.close()
    return {
        "scope": _scope(lifecycle_status, cluster, product_type_group),
        "total_products": sum(raw.values()),
        "READY": raw.get("READY", 0),
        "NEEDS_REVIEW": raw.get("NEEDS_REVIEW", 0),
        "MISSING_FIELDS": raw.get("MISSING_FIELDS", 0),
        "not_evaluated": raw.get("not_evaluated", 0),
    }


async def list_exceptions(
    kind: str,
    lifecycle_status: str = "ACTIVE",
    cluster: Optional[str] = None,
    product_type_group: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Filtered, paginated drill-down list for one exception kind. Raises ValueError
    on an unknown kind (the router maps it to 422)."""
    if kind not in EXCEPTION_KINDS:
        raise ValueError(f"UNKNOWN_EXCEPTION_KIND: {kind}")
    db = await get_db()

    if kind == "failed_generation":
        # request-telemetry scoped; product/lifecycle filters do not cleanly apply
        # (telemetry rows may have no product_id), so only paging is honoured.
        total = await _scalar(db, "SELECT COUNT(*) FROM request_telemetry WHERE status = 'FAILED'", [])
        cur = await db.execute(
            "SELECT rt.request_id AS request_id, rt.product_id AS product_id, "
            "COALESCE(p.product_display_name, p.product_short_name, p.raw_product_title, rt.product_id) AS product_display_name, "
            "rt.mode AS mode, rt.status AS status, rt.error_code AS error_code, "
            "rt.error_message AS error_message, rt.created_at AS created_at, rt.failed_at AS failed_at "
            "FROM request_telemetry rt LEFT JOIN product p ON p.id = rt.product_id "
            "WHERE rt.status = 'FAILED' "
            "ORDER BY COALESCE(rt.failed_at, rt.created_at) DESC LIMIT ? OFFSET ?",
            [limit, offset],
        )
        items = [dict(r) for r in await cur.fetchall()]
        await cur.close()
        return {"kind": kind, "total": total, "limit": limit, "offset": offset, "items": items}

    predicate = _EXCEPTION_PREDICATES[kind]
    where, params = _product_filters(lifecycle_status, cluster, product_type_group)
    total = await _scalar(db, f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE {predicate}{where}", params)
    cur = await db.execute(
        f"SELECT p.id AS product_id, {_DISPLAY_NAME} AS product_display_name, "
        "p.category AS category, p.product_type AS product_type, "
        "t.cluster AS cluster, t.product_type_group AS product_type_group, "
        "p.mapping_status AS mapping_status, p.prompt_readiness_status AS prompt_readiness_status, "
        "p.image_asset_status AS image_asset_status, p.asset_status AS asset_status, "
        "p.lifecycle_status AS lifecycle_status "
        f"{_PRODUCT_BASE} WHERE {predicate}{where} "
        "ORDER BY p.updated_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    items = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return {
        "kind": kind,
        "scope": _scope(lifecycle_status, cluster, product_type_group),
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


# ── failed-generation reporting honesty ──────────────────────────────────────
# A single all-time FAILED count reads as "N active incidents". It is not: most are
# historical, and a large share are the ADR-007 dead DOM-clicking F2V lane (frozen,
# delete-only, never repaired). This report adds honest time windows + error/mode
# grouping and CLASSIFIES the dead-lane rows without deleting or rewriting any history.
_DEAD_DOM_PREFIXES = ("ERR_F2V_", "ERR_CDP_FILE_CHOOSER")
_DEAD_DOM_EXACT = ("ERR_FLOW_EDITOR_REQUIRED",)


def is_dead_dom_lane_error(error_code: Optional[str]) -> bool:
    """True if the error_code belongs to the ADR-007 dead DOM-clicking lane. Pure
    classification — nothing is deleted or reactivated."""
    if not error_code:
        return False
    return error_code.startswith(_DEAD_DOM_PREFIXES) or error_code in _DEAD_DOM_EXACT


async def failed_generation_report() -> dict:
    db = await get_db()
    now = datetime.now(timezone.utc)

    def _cut(days: int) -> str:
        return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    windows = {}
    for label, days in (("last_24h", 1), ("last_7d", 7), ("last_30d", 30)):
        windows[label] = await _scalar(
            db,
            "SELECT COUNT(*) FROM request_telemetry WHERE status='FAILED' AND created_at >= ?",
            [_cut(days)],
        )
    windows["all_time"] = await _scalar(
        db, "SELECT COUNT(*) FROM request_telemetry WHERE status='FAILED'", []
    )
    distinct_products = await _scalar(
        db,
        "SELECT COUNT(DISTINCT product_id) FROM request_telemetry WHERE status='FAILED' AND product_id IS NOT NULL",
        [],
    )
    cur = await db.execute("SELECT MIN(created_at) mn, MAX(created_at) mx FROM request_telemetry WHERE status='FAILED'")
    span_row = await cur.fetchone()
    await cur.close()

    cur = await db.execute(
        "SELECT COALESCE(error_code,'(none)') ec, COUNT(*) n "
        "FROM request_telemetry WHERE status='FAILED' GROUP BY ec ORDER BY n DESC"
    )
    by_error_code = []
    dead = 0
    for r in await cur.fetchall():
        ec = r["ec"]
        n = int(r["n"])
        d = is_dead_dom_lane_error(None if ec == "(none)" else ec)
        if d:
            dead += n
        by_error_code.append({"error_code": ec, "count": n, "dead_dom_lane": d})
    await cur.close()

    cur = await db.execute(
        "SELECT COALESCE(mode,'(none)') m, COUNT(*) n "
        "FROM request_telemetry WHERE status='FAILED' GROUP BY m ORDER BY n DESC"
    )
    by_mode = [{"mode": r["m"], "count": int(r["n"])} for r in await cur.fetchall()]
    await cur.close()

    return {
        "windows": windows,
        "window_labels": {"last_24h": "last 24h", "last_7d": "last 7d",
                          "last_30d": "last 30d", "all_time": "all-time (historical)"},
        "distinct_products_all_time": distinct_products,
        "time_span": {"min": span_row["mn"], "max": span_row["mx"]},
        "dead_dom_lane_count": dead,
        "non_dead_lane_count": windows["all_time"] - dead,
        "dead_dom_lane_note": (
            "ADR-007: the DOM-clicking F2V lane is dead/frozen (delete-only). "
            "These rows are historical archaeology, NOT active incidents — classified, "
            "never deleted or rewritten."
        ),
        "by_error_code": by_error_code,
        "by_mode": by_mode,
    }
