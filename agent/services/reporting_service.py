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

# Harness rows that live in canonical data but are not products: PR223 smoke fixtures and
# Codex verification rows. They carry no image_url / source_url / tiktok_product_url, so
# they can never be "completed" — counting them as products overstates real catalogue debt.
# SQL mirror of `product_intelligence.is_test_product` (same names + the harness titles it
# predates). They are EXCLUDED from real-product totals and REPORTED separately, never
# deleted and never silently folded into the denominator.
_TEST_FIXTURE_PREDICATE = (
    "("
    "LOWER(TRIM(COALESCE(p.raw_product_title,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(TRIM(COALESCE(p.product_short_name,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE 'test product%'"
    " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE 'smoke %'"
    " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE '%smoke approve%'"
    " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE '%smoke reject%'"
    " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE '%smoke claim review%'"
    " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE 'codex pi %verification%'"
    " OR LOWER(COALESCE(p.id,'')) LIKE 'test|_%' ESCAPE '|'"
    " OR LOWER(COALESCE(p.id,'')) LIKE 'fixture|_%' ESCAPE '|'"
    ")"
)

# Sortable columns for the drill-down. An allowlist, so a user-supplied value can never
# reach SQL as an identifier. Every sort gets `p.id` appended as a tie-breaker, otherwise
# rows with equal sort keys can repeat or vanish across pages.
_SORTABLE: dict[str, str] = {
    "product_display_name": _DISPLAY_NAME,
    "category": "p.category",
    "product_type": "p.product_type",
    "cluster": "t.cluster",
    "product_type_group": "t.product_type_group",
    "mapping_status": "p.mapping_status",
    "prompt_readiness_status": "p.prompt_readiness_status",
    "asset_status": "p.asset_status",
    "lifecycle_status": "p.lifecycle_status",
    "updated_at": "p.updated_at",
}


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
    q: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = "desc",
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

    # Free-text search runs in SQL over the WHOLE cohort, not over a fetched page.
    search = (q or "").strip()
    search_sql, search_params = "", []
    if search:
        search_sql = (
            f" AND ({_DISPLAY_NAME} LIKE ? COLLATE NOCASE"
            " OR p.raw_product_title LIKE ? COLLATE NOCASE"
            " OR p.id LIKE ? COLLATE NOCASE)"
        )
        like = f"%{search}%"
        search_params = [like, like, like]

    scope = f"{where}{search_sql}"
    scope_params = params + search_params
    total = await _scalar(db, f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE {predicate}{scope}", scope_params)

    # Explicit accounting so the UI never has to infer a headline. `total` keeps its exact
    # previous meaning (every row matching the predicate in the requested scope).
    #   active_missing   - live products, actionable now
    #   archived_missing - real products, ARCHIVED_NOT_IN_SCOPE for production (P5.8) but
    #                      still real catalogue debt; NOT hidden
    #   test_fixture_*   - harness rows that are not products at all
    # Both counts describe the REQUESTED scope, so they always reconcile against `total`.
    # Under lifecycle_status=ACTIVE the archived figure is naturally 0.
    active_missing = await _scalar(
        db,
        f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE {predicate}{scope}"
        f" AND p.lifecycle_status = 'ACTIVE' AND NOT {_TEST_FIXTURE_PREDICATE}",
        scope_params)
    archived_missing = await _scalar(
        db,
        f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE {predicate}{scope}"
        f" AND p.lifecycle_status <> 'ACTIVE' AND NOT {_TEST_FIXTURE_PREDICATE}",
        scope_params)
    fixtures_in_scope = await _scalar(
        db,
        f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE {predicate}{scope} AND {_TEST_FIXTURE_PREDICATE}",
        scope_params)

    order_col = _SORTABLE.get((sort_by or "").strip(), "p.updated_at")
    direction = "ASC" if str(sort_dir).strip().lower() == "asc" else "DESC"
    order_sql = f"ORDER BY {order_col} {direction}, p.id ASC"
    cur = await db.execute(
        f"SELECT p.id AS product_id, {_DISPLAY_NAME} AS product_display_name, "
        "p.category AS category, p.product_type AS product_type, "
        "t.cluster AS cluster, t.product_type_group AS product_type_group, "
        "p.mapping_status AS mapping_status, p.prompt_readiness_status AS prompt_readiness_status, "
        "p.image_asset_status AS image_asset_status, p.asset_status AS asset_status, "
        "p.lifecycle_status AS lifecycle_status, "
        f"{_TEST_FIXTURE_PREDICATE} AS is_test_fixture "
        f"{_PRODUCT_BASE} WHERE {predicate}{scope} "
        f"{order_sql} LIMIT ? OFFSET ?",
        scope_params + [limit, offset],
    )
    items = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return {
        "kind": kind,
        "scope": _scope(lifecycle_status, cluster, product_type_group),
        "total": total,
        "applicability": {
            # real-product debt, split by lifecycle. Archived is NOT hidden — it is real
            # catalogue debt that simply must not enter production.
            "active_missing": active_missing,
            "archived_missing": archived_missing,
            "real_product_missing": active_missing + archived_missing,
            # harness rows that are not products; excluded from the real-product totals
            # above and disclosed here rather than folded into the denominator.
            "test_fixture_excluded": fixtures_in_scope,
            "documented_na_reason": "PRODUCT_LIFECYCLE_ARCHIVED",
            # retained for the previous consumer contract
            "required_missing": active_missing,
            "documented_na_archived": archived_missing,
        },
        "limit": limit,
        "offset": offset,
        "q": search or None,
        "sort_by": sort_by if (sort_by or "") in _SORTABLE else None,
        "sort_dir": "asc" if direction == "ASC" else "desc",
        "items": items,
    }


# ── failed-generation reporting honesty ──────────────────────────────────────
# A single all-time FAILED count reads as "N active incidents". It is not: most are
# historical. Some are the ADR-007 dead DOM-clicking F2V lane — but a matching error
# PREFIX is not provenance. Only exact error codes that name a DOM UI element the frozen
# lane drove are asserted "dead DOM". Codes that merely match a legacy pattern — including
# CDP (which ADR-007 still permits as an upload transport) and generic F2V — are labelled
# "provenance unverified", NOT dead DOM. No telemetry is deleted or rewritten.
DEAD_DOM_LANE = "dead_dom_lane"
LEGACY_UNVERIFIED = "legacy_pattern_provenance_unverified"
OTHER = "other"

# Provable frozen-lane codes: each names a DOM UI element the dead DOM-clicking lane drove.
_PROVEN_DEAD_DOM_LANE = frozenset({
    "ERR_F2V_OPTION_RATIO_9_16_NOT_FOUND",
    "ERR_F2V_SETTINGS_PANEL_NOT_OPEN",
    "ERR_F2V_START_BUTTON_NOT_FOUND",
    "ERR_F2V_SOP_RUNNER_THREW",
})
# Loose legacy pattern — matched but NOT provable (upload/CDP/generic). Labelled unverified.
_LEGACY_PATTERN_PREFIXES = ("ERR_F2V_", "ERR_CDP_FILE_CHOOSER")
_LEGACY_PATTERN_EXACT = ("ERR_FLOW_EDITOR_REQUIRED",)


def classify_error_provenance(error_code: Optional[str]) -> str:
    """dead_dom_lane (provable) | legacy_pattern_provenance_unverified | other. Pure
    classification — nothing is deleted or reactivated."""
    if not error_code:
        return OTHER
    if error_code in _PROVEN_DEAD_DOM_LANE:
        return DEAD_DOM_LANE
    if error_code.startswith(_LEGACY_PATTERN_PREFIXES) or error_code in _LEGACY_PATTERN_EXACT:
        return LEGACY_UNVERIFIED
    return OTHER


def is_dead_dom_lane_error(error_code: Optional[str]) -> bool:
    """True only for PROVABLE frozen-lane codes (not loose-pattern matches)."""
    return classify_error_provenance(error_code) == DEAD_DOM_LANE


async def failed_generation_report() -> dict:
    db = await get_db()
    now = datetime.now(timezone.utc)

    def _cut(days: int) -> str:
        return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    windows = {}
    for label, days in (("last_24h", 1), ("last_7d", 7), ("last_30d", 30)):
        # count by WHEN it failed (failed_at), falling back to created_at when NULL —
        # consistent with the drill-down ordering and the existing telemetry contract.
        windows[label] = await _scalar(
            db,
            "SELECT COUNT(*) FROM request_telemetry WHERE status='FAILED' "
            "AND COALESCE(failed_at, created_at) >= ?",
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
    cur = await db.execute(
        "SELECT MIN(COALESCE(failed_at, created_at)) mn, MAX(COALESCE(failed_at, created_at)) mx "
        "FROM request_telemetry WHERE status='FAILED'"
    )
    span_row = await cur.fetchone()
    await cur.close()

    cur = await db.execute(
        "SELECT COALESCE(error_code,'(none)') ec, COUNT(*) n "
        "FROM request_telemetry WHERE status='FAILED' GROUP BY ec ORDER BY n DESC"
    )
    by_error_code = []
    counts = {DEAD_DOM_LANE: 0, LEGACY_UNVERIFIED: 0, OTHER: 0}
    for r in await cur.fetchall():
        ec = r["ec"]
        n = int(r["n"])
        cls = classify_error_provenance(None if ec == "(none)" else ec)
        counts[cls] += n
        by_error_code.append({"error_code": ec, "count": n, "classification": cls})
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
        "windows_counted_by": "COALESCE(failed_at, created_at)",
        "distinct_products_all_time": distinct_products,
        "time_span": {"min": span_row["mn"], "max": span_row["mx"]},
        "dead_dom_lane_count": counts[DEAD_DOM_LANE],
        "provenance_unverified_count": counts[LEGACY_UNVERIFIED],
        "other_count": counts[OTHER],
        "classification_note": (
            "Only exact frozen-lane DOM-UI error codes are labelled dead DOM. Legacy-pattern "
            "codes without provable provenance (incl. CDP, an ADR-007-permitted upload "
            "transport) are 'provenance unverified', not asserted dead. No telemetry deleted."
        ),
        "by_error_code": by_error_code,
        "by_mode": by_mode,
    }
