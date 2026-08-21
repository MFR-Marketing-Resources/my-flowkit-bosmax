"""Provider-free Reporting maintenance views over the canonical V3 Landbank.

This module is intentionally a read/maintenance surface.  It does not create
or alter Product Truth, formulas, components, projections, approvals,
materialization links, or production records.  Manual copy edits are appended
as a new DRAFT Master revision through the existing V3 repository.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from agent.db.schema import _db_lock, get_db
from agent.models.storyboard_landbank_v3 import (
    V3MasterStoryboard,
    V3RevisionRef,
    digest_text,
    exact_resolved_content_fingerprint,
    master_content_digest,
    normalized_text,
    word_count,
)
from agent.services import production_copy_supply_service as supply_service
from agent.services.storyboard_landbank_v3_factory import (
    MAX_PAGE_SIZE,
    V3CopyFactoryService,
    V3FactoryError,
)
from agent.services.storyboard_landbank_v3_round2 import V3CopyRegisterRound2Service


MAINTENANCE_SOURCE = "COPYWRITING_LANDBANK_DATABASE_MAINTENANCE"
MAINTENANCE_MAX_PAGE = 100
_EDITABLE_STATUSES = {"DRAFT", "REVIEW_REQUIRED", "VALIDATED", "APPROVED"}
_REJECTABLE_STATUSES = {"DRAFT", "REVIEW_REQUIRED", "VALIDATED"}
_ACTIVE_COMPONENT_STATUSES = {"DRAFT", "REVIEW_REQUIRED", "VALIDATED", "APPROVED", "FROZEN"}
_DEFAULT_SORT_BY = "created_at"
_DEFAULT_SORT_DIR = "desc"
_SORT_COLUMNS = {
    "created_at": "m.created_at",
    "product_name": "LOWER(COALESCE(p.product_display_name, p.raw_product_title, p.id))",
    "status": "m.status",
    "formula": "m.formula_id",
    "revision": "m.revision",
}
_SORT_DIRECTIONS = {"asc": "ASC", "desc": "DESC"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _product_name(row: Mapping[str, Any] | None, product_id: str) -> str:
    if not row:
        return product_id
    for key in ("product_display_name", "raw_product_title", "product_short_name", "name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return product_id


class V3CopywritingLandbankMaintenanceService:
    """All-product, exact-revision maintenance access to canonical V3 rows."""

    def __init__(self, *, factory: V3CopyFactoryService | None = None) -> None:
        self.factory = factory or V3CopyFactoryService()
        # The Round 2 object is used only for its deterministic quality read.
        # No provider is injected or invoked by this Reporting surface.
        self.round2 = V3CopyRegisterRound2Service(factory=self.factory, provider=None)

    async def _rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        db = await get_db()
        cursor = await db.execute(query, tuple(params))
        return [dict(row) for row in await cursor.fetchall()]

    async def _row(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        db = await get_db()
        row = await (await db.execute(query, tuple(params))).fetchone()
        return dict(row) if row else None

    async def _products(self) -> dict[str, dict[str, Any]]:
        rows = await self._rows("SELECT * FROM product ORDER BY id")
        return {str(row["id"]): row for row in rows}

    async def _current_truth(self) -> dict[str, dict[str, Any]]:
        rows = await self._rows(
            """
            SELECT s.product_id, s.snapshot_id, s.version
            FROM product_intelligence_snapshot s
            WHERE s.status='APPROVED'
              AND NOT EXISTS (
                  SELECT 1
                  FROM product_intelligence_snapshot newer
                  WHERE newer.product_id=s.product_id
                    AND newer.status='APPROVED'
                    AND (
                        newer.version > s.version
                        OR (newer.version = s.version AND newer.snapshot_id > s.snapshot_id)
                    )
              )
            """
        )
        return {str(row["product_id"]): row for row in rows}

    async def _all_master_rows(self) -> list[dict[str, Any]]:
        return await self._rows(
            "SELECT * FROM master_storyboard_v3 ORDER BY created_at DESC, master_id DESC, revision DESC"
        )

    @staticmethod
    def _stale_info(
        master: V3MasterStoryboard,
        current_truth: Mapping[str, Mapping[str, Any]],
        projection_statuses: Sequence[str] = (),
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        current = current_truth.get(master.product_id)
        if current is None:
            reasons.append("PRODUCT_TRUTH_UNAVAILABLE")
        elif (
            str(current.get("snapshot_id")) != master.product_truth.snapshot_id
            or int(current.get("version") or 0) != master.product_truth.snapshot_version
        ):
            reasons.append("PRODUCT_TRUTH_ADVANCED")
        if "STALE" in projection_statuses:
            reasons.append("PROJECTION_REVALIDATION_REQUIRED")
        return bool(reasons), list(dict.fromkeys(reasons))

    @staticmethod
    def _stale_sql() -> str:
        return "(truth.snapshot_id IS NULL OR truth.snapshot_id <> m.product_truth_snapshot_id OR truth.version <> m.product_truth_snapshot_version)"

    def _where(
        self,
        *,
        product_id: str | None,
        status: str | None,
        formula_id: str | None,
        angle_id: str | None,
        search: str | None,
        production_ready: bool | None,
        stale: bool | None,
    ) -> tuple[list[str], list[Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if product_id:
            clauses.append("m.product_id=?")
            params.append(product_id)
        if status:
            clauses.append("m.status=?")
            params.append(str(status).upper())
        if formula_id:
            clauses.append("m.formula_id=?")
            params.append(formula_id)
        if angle_id:
            clauses.append("m.angle_id=?")
            params.append(angle_id)
        if search and normalized_text(search):
            needle = f"%{normalized_text(search).casefold()}%"
            clauses.append(
                "LOWER(COALESCE(m.master_id,'') || ' ' || COALESCE(m.product_id,'') || ' ' || "
                "COALESCE(m.formula_id,'') || ' ' || COALESCE(m.angle_id,'') || ' ' || "
                "COALESCE(m.storyline_family_id,'') || ' ' || COALESCE(m.ordered_stage_plan_json,'') || ' ' || "
                "COALESCE(m.exact_stage_texts_json,'') || ' ' || "
                "COALESCE(p.product_display_name,'') || ' ' || COALESCE(p.raw_product_title,'')) LIKE ?"
            )
            params.append(needle)
        if production_ready is True:
            clauses.append(
                "EXISTS (SELECT 1 FROM materialization_link_v3 ml "
                "WHERE ml.master_id=m.master_id AND ml.master_revision=m.revision "
                "AND ml.status='PRODUCTION_VALID')"
            )
        elif production_ready is False:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM materialization_link_v3 ml "
                "WHERE ml.master_id=m.master_id AND ml.master_revision=m.revision "
                "AND ml.status='PRODUCTION_VALID')"
            )
        if stale is True:
            clauses.append(self._stale_sql())
        elif stale is False:
            clauses.append(f"NOT {self._stale_sql()}")
        return clauses, params

    @staticmethod
    def _order_by(sort_by: str | None, sort_dir: str | None) -> tuple[str, str, str]:
        normalized_sort_by = str(sort_by or _DEFAULT_SORT_BY).strip().lower()
        normalized_sort_dir = str(sort_dir or _DEFAULT_SORT_DIR).strip().lower()
        if normalized_sort_by not in _SORT_COLUMNS:
            raise V3FactoryError(
                "MAINTENANCE_SORT_INVALID",
                "sort_by must be one of: created_at, product_name, status, formula, revision.",
                status_code=422,
                details={"sort_by": normalized_sort_by, "allowed": sorted(_SORT_COLUMNS)},
            )
        if normalized_sort_dir not in _SORT_DIRECTIONS:
            raise V3FactoryError(
                "MAINTENANCE_SORT_DIRECTION_INVALID",
                "sort_dir must be asc or desc.",
                status_code=422,
                details={"sort_dir": normalized_sort_dir, "allowed": sorted(_SORT_DIRECTIONS)},
            )
        # Every SQL fragment here is selected from the constants above. Query
        # values never enter ORDER BY directly.
        order_by = (
            f"{_SORT_COLUMNS[normalized_sort_by]} {_SORT_DIRECTIONS[normalized_sort_dir]}, "
            "m.created_at DESC, m.master_id DESC, m.revision DESC"
        )
        return normalized_sort_by, normalized_sort_dir, order_by

    async def _projection_rows(self, product_id: str, master_id: str, revision: int) -> list[Any]:
        rows = await self.factory.repository.list(
            "DURATION_PROJECTION",
            product_id=product_id,
            limit=MAX_PAGE_SIZE,
            offset=0,
            latest_only=False,
        )
        return [
            row
            for row in rows
            if row.master.entity_id == master_id and row.master.revision == int(revision)
        ]

    async def _approval_receipt(self, master_id: str, revision: int) -> dict[str, Any] | None:
        return await self._row(
            """
            SELECT * FROM v3_human_approval_receipt
            WHERE target_type='MASTER_STORYBOARD' AND target_id=? AND target_revision=?
            ORDER BY created_at DESC, receipt_id DESC LIMIT 1
            """,
            (master_id, int(revision)),
        )

    async def _review_events(self, master_id: str, revision: int) -> list[dict[str, Any]]:
        rows = await self._rows(
            """
            SELECT * FROM review_event_v3
            WHERE entity_type='MASTER_STORYBOARD' AND entity_id=? AND entity_revision=?
            ORDER BY created_at ASC, event_id ASC
            """,
            (master_id, int(revision)),
        )
        for row in rows:
            row["payload"] = _loads(row.pop("payload_json", "{}"), {})
        return rows

    async def _quality(self, master: V3MasterStoryboard, projections: Sequence[Any]) -> dict[str, Any]:
        try:
            signal = await self.round2.quality_signal(master, projections)
            return signal.model_dump(mode="json")
        except Exception as exc:  # Reporting must fail closed for a malformed row.
            return {
                "hard_pass": False,
                "formula_valid": False,
                "evidence_valid": False,
                "bridge_valid": False,
                "claim_safety_valid": False,
                "truth_current": False,
                "wps_valid": False,
                "issue_codes": ["QUALITY_UNAVAILABLE", type(exc).__name__],
                "novelty_signal": "NOVEL",
                "novelty_score": 0.0,
                "quality_dimensions": {},
                "quality_score": 0.0,
            }

    async def _production_state(self, master: V3MasterStoryboard, projections: Sequence[Any]) -> tuple[str, list[dict[str, Any]]]:
        projection_payload = [item.model_dump(mode="json") for item in projections]
        payload: dict[str, Any] = {
            "items": [{
                "master": master.model_dump(mode="json"),
                "projections": projection_payload,
            }]
        }
        try:
            enriched = await supply_service.enrich_landbank_payload(payload)
            item = (enriched.get("items") or [{}])[0]
            return str(item.get("v2_materialization") or "NOT_MATERIALIZED"), list(item.get("projections") or [])
        except Exception:
            # A status read may never imply readiness when enrichment cannot
            # prove the existing V2/materialization lineage.
            return "NOT_MATERIALIZED", [
                {**item, "materialization": {"status": "BLOCKED", "reason": "STATUS_ENRICHMENT_UNAVAILABLE"}}
                for item in projection_payload
            ]

    async def _draft_delete_blockers(self, master_id: str, revision: int) -> list[str]:
        checks = (
            ("DURATION_PROJECTION", "SELECT 1 FROM duration_projection_v3 WHERE master_id=? AND master_revision=? LIMIT 1"),
            ("SUPERSEDING_REVISION", "SELECT 1 FROM master_storyboard_v3 WHERE supersedes_master_id=? AND supersedes_master_revision=? LIMIT 1"),
            ("MATERIALIZATION_LINK", "SELECT 1 FROM materialization_link_v3 WHERE master_id=? AND master_revision=? LIMIT 1"),
            ("MANIFEST_ITEM", "SELECT 1 FROM manifest_item_v3 WHERE master_id=? AND master_revision=? LIMIT 1"),
            ("LANDBANK_USAGE", "SELECT 1 FROM landbank_usage_v3 WHERE master_id=? AND master_revision=? LIMIT 1"),
        )
        blockers: list[str] = []
        for label, query in checks:
            if await self._row(query, (master_id, int(revision))):
                blockers.append(label)
        return blockers

    async def _actions(self, master: V3MasterStoryboard) -> dict[str, Any]:
        status = str(master.status).upper()
        can_delete = False
        delete_reason = "Only an unreferenced DRAFT can be deleted."
        blockers: list[str] = []
        if status == "DRAFT":
            blockers = await self._draft_delete_blockers(master.master_id, master.revision)
            can_delete = not blockers
            if blockers:
                delete_reason = "Draft is referenced by: " + ", ".join(blockers) + "."
        return {
            "can_edit": status in _EDITABLE_STATUSES,
            "edit_mode": "CREATE_NEW_DRAFT" if status == "APPROVED" else "EDIT_DRAFT_REVISION",
            "can_reject": status in _REJECTABLE_STATUSES,
            "can_delete": can_delete,
            "delete_reason": delete_reason,
            "delete_blockers": blockers,
        }

    async def _render_item(
        self,
        master: V3MasterStoryboard,
        *,
        product: Mapping[str, Any] | None,
        current_truth: Mapping[str, Mapping[str, Any]],
        include_detail: bool = False,
    ) -> dict[str, Any]:
        projections = await self._projection_rows(master.product_id, master.master_id, master.revision)
        quality = await self._quality(master, projections)
        production_status, enriched_projections = await self._production_state(master, projections)
        projection_statuses = [
            str((item.get("materialization") or {}).get("status") or "NOT_MATERIALIZED")
            for item in enriched_projections
        ]
        stale, stale_reasons = self._stale_info(master, current_truth, projection_statuses)
        by_class: dict[str, list[str]] = defaultdict(list)
        for stage in master.stages:
            by_class[str(stage.semantic_class)].append(stage.authored_text)
        item: dict[str, Any] = {
            "product": {
                "id": master.product_id,
                "name": _product_name(product, master.product_id),
            },
            "master_id": master.master_id,
            "revision": master.revision,
            "status": master.status,
            "master": master.model_dump(mode="json"),
            "formula": master.formula.model_dump(mode="json"),
            "angle": master.angle.model_dump(mode="json"),
            "storyline_family": master.storyline_family.model_dump(mode="json"),
            "stages": [stage.model_dump(mode="json") for stage in master.stages],
            "previews": {
                "HOOK": " ".join(by_class.get("HOOK", [])),
                "BODY_CORE": " ".join(by_class.get("BODY_CORE", [])),
                "CTA": " ".join(by_class.get("CTA", [])),
            },
            "quality": quality,
            "projection_count": len(projections),
            "projections": enriched_projections,
            "projection_status": production_status,
            "v2_materialization": production_status,
            "production_ready": production_status == "MATERIALIZED",
            "stale": stale,
            "stale_reasons": stale_reasons,
            "approval_receipt": await self._approval_receipt(master.master_id, master.revision),
            "created_at": master.created_at,
            "created_by": master.created_by,
            "actions": await self._actions(master),
            "provider_calls": 0,
            "mutations": 0,
        }
        if include_detail:
            item["review_events"] = await self._review_events(master.master_id, master.revision)
            item["integrity"] = {
                "exact_content_digest": master.exact_content_digest,
                "duplicate_fingerprint": master.duplicate_fingerprint,
                "product_truth": master.product_truth.model_dump(mode="json"),
                "supersedes": master.supersedes.model_dump(mode="json") if master.supersedes else None,
            }
        return item

    async def _coverage(
        self,
        products: Mapping[str, Mapping[str, Any]],
        masters: Sequence[V3MasterStoryboard],
        current_truth: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        coverage: dict[str, dict[str, Any]] = {
            product_id: {
                "product_id": product_id,
                "product_name": _product_name(row, product_id),
                "copy_sets": set(),
                "angles": set(),
                "hooks": 0,
                "body_core": 0,
                "cta": 0,
                "approved": 0,
                "production_ready": 0,
                "stale": 0,
            }
            for product_id, row in products.items()
        }
        latest_by_master: dict[str, V3MasterStoryboard] = {}
        for master in masters:
            previous = latest_by_master.get(master.master_id)
            if previous is None or master.revision > previous.revision:
                latest_by_master[master.master_id] = master
        for master in latest_by_master.values():
            entry = coverage.setdefault(
                master.product_id,
                {
                    "product_id": master.product_id,
                    "product_name": _product_name(None, master.product_id),
                    "copy_sets": set(), "angles": set(), "hooks": 0,
                    "body_core": 0, "cta": 0, "approved": 0,
                    "production_ready": 0, "stale": 0,
                },
            )
            entry["copy_sets"].add(master.master_id)
            entry["angles"].add(master.angle.entity_id)
            if master.status == "APPROVED":
                entry["approved"] += 1
            stale, _ = self._stale_info(master, current_truth)
            if stale:
                entry["stale"] += 1
        component_rows = await self._rows(
            """
            SELECT c.* FROM storyboard_component_v3 c
            JOIN (
                SELECT component_id, MAX(revision) AS latest_revision
                FROM storyboard_component_v3 GROUP BY component_id
            ) latest ON latest.component_id=c.component_id AND latest.latest_revision=c.revision
            """
        )
        for row in component_rows:
            if str(row.get("status") or "").upper() not in _ACTIVE_COMPONENT_STATUSES:
                continue
            product_id = str(row.get("product_id") or "")
            entry = coverage.get(product_id)
            if not entry:
                continue
            semantic_class = str(row.get("semantic_class") or "").upper()
            if semantic_class == "HOOK":
                entry["hooks"] += 1
            elif semantic_class == "BODY_CORE":
                entry["body_core"] += 1
            elif semantic_class == "CTA":
                entry["cta"] += 1
        projection_rows = await self._rows(
            """
            SELECT d.master_id, d.master_revision, COUNT(DISTINCT d.projection_id) AS projection_count,
                   COUNT(DISTINCT CASE WHEN EXISTS (
                       SELECT 1 FROM materialization_link_v3 ml
                       WHERE ml.projection_id=d.projection_id
                         AND ml.projection_revision=d.revision
                         AND ml.status='PRODUCTION_VALID'
                   ) THEN d.projection_id END) AS ready_count
            FROM duration_projection_v3 d
            GROUP BY d.master_id, d.master_revision
            """
        )
        ready_by_master = {
            (str(row["master_id"]), int(row["master_revision"])): int(row["projection_count"] or 0) > 0
            and int(row["ready_count"] or 0) >= int(row["projection_count"] or 0)
            for row in projection_rows
        }
        for master in latest_by_master.values():
            if ready_by_master.get((master.master_id, master.revision), False):
                coverage[master.product_id]["production_ready"] += 1
        result: list[dict[str, Any]] = []
        for product_id in sorted(coverage):
            entry = coverage[product_id]
            result.append({
                **entry,
                "copy_sets": len(entry["copy_sets"]),
                "angles": len(entry["angles"]),
            })
        return result

    async def _filter_options(self) -> dict[str, list[str]]:
        rows = await self._rows(
            "SELECT DISTINCT formula_id, angle_id FROM master_storyboard_v3 ORDER BY formula_id, angle_id"
        )
        return {
            "formulas": sorted({str(row["formula_id"]) for row in rows if row.get("formula_id")}),
            "angles": sorted({str(row["angle_id"]) for row in rows if row.get("angle_id")}),
        }

    @staticmethod
    def _filter_product_coverage(
        coverage: Sequence[Mapping[str, Any]],
        *,
        product_id: str | None,
        search: str | None,
    ) -> list[dict[str, Any]]:
        """Narrow the visible catalog without changing authoritative counts.

        ``product_coverage`` is the all-product catalog, including products
        with no V3 Master rows.  Product selection and product-name/ID search
        must operate on that catalog independently of the Master-row query.
        The full catalog remains available as ``product_options`` for the
        bounded UI picker.
        """

        visible = list(coverage)
        if product_id:
            visible = [item for item in visible if str(item.get("product_id") or "") == product_id]
        normalized_search = normalized_text(search or "").casefold()
        if normalized_search:
            visible = [
                item
                for item in visible
                if normalized_search in str(item.get("product_id") or "").casefold()
                or normalized_search in str(item.get("product_name") or "").casefold()
            ]
        return [dict(item) for item in visible]

    async def list_records(
        self,
        *,
        product_id: str | None = None,
        status: str | None = None,
        formula_id: str | None = None,
        angle_id: str | None = None,
        search: str | None = None,
        production_ready: bool | None = None,
        stale: bool | None = None,
        sort_by: str = _DEFAULT_SORT_BY,
        sort_dir: str = _DEFAULT_SORT_DIR,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = min(MAINTENANCE_MAX_PAGE, max(1, int(limit)))
        offset = max(0, int(offset))
        normalized_sort_by, normalized_sort_dir, order_by = self._order_by(sort_by, sort_dir)
        clauses, params = self._where(
            product_id=product_id,
            status=status,
            formula_id=formula_id,
            angle_id=angle_id,
            search=search,
            production_ready=production_ready,
            stale=stale,
        )
        where = " AND ".join(clauses)
        cte = """
            WITH current_truth AS (
                SELECT s.product_id, s.snapshot_id, s.version
                FROM product_intelligence_snapshot s
                WHERE s.status='APPROVED'
                  AND NOT EXISTS (
                      SELECT 1 FROM product_intelligence_snapshot newer
                      WHERE newer.product_id=s.product_id AND newer.status='APPROVED'
                        AND (newer.version > s.version OR (newer.version=s.version AND newer.snapshot_id>s.snapshot_id))
                  )
            )
        """
        count_row = await self._row(
            cte + "SELECT COUNT(*) AS n FROM master_storyboard_v3 m "
            "LEFT JOIN product p ON p.id=m.product_id "
            "LEFT JOIN current_truth truth ON truth.product_id=m.product_id WHERE " + where,
            params,
        )
        total = int((count_row or {}).get("n") or 0)
        rows = await self._rows(
            cte + "SELECT m.* FROM master_storyboard_v3 m "
            "LEFT JOIN product p ON p.id=m.product_id "
            "LEFT JOIN current_truth truth ON truth.product_id=m.product_id WHERE " + where +
            f" ORDER BY {order_by} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        products = await self._products()
        current_truth = await self._current_truth()
        items: list[dict[str, Any]] = []
        for row in rows:
            master = await self.factory.repository.get("MASTER_STORYBOARD", str(row["master_id"]), int(row["revision"]))
            if isinstance(master, V3MasterStoryboard):
                items.append(await self._render_item(master, product=products.get(master.product_id), current_truth=current_truth))
        masters = await self._all_master_rows()
        typed_masters: list[V3MasterStoryboard] = []
        for row in masters:
            try:
                typed = await self.factory.repository.get("MASTER_STORYBOARD", str(row["master_id"]), int(row["revision"]))
                if isinstance(typed, V3MasterStoryboard):
                    typed_masters.append(typed)
            except Exception:
                continue
        status_counts = Counter(str(master.status) for master in typed_masters)
        coverage = await self._coverage(products, typed_masters, current_truth)
        latest_masters = {master.master_id: master for master in typed_masters}
        visible_coverage = self._filter_product_coverage(
            coverage,
            product_id=product_id,
            search=search,
        )
        # The distinct Master-ID count is deliberately separated from the exact
        # revision count so operators do not mistake lineage rows for copy sets.
        return {
            "source": "V3_COPY_REGISTER_MAINTENANCE",
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort_by": normalized_sort_by,
            "sort_dir": normalized_sort_dir,
            "has_more": offset + len(items) < total,
            "summary": {
                "total_products": len(products),
                "products_with_copy": sum(1 for item in coverage if item["copy_sets"] > 0),
                "products_without_copy": sum(1 for item in coverage if item["copy_sets"] == 0),
                "total_copy_masters": len(latest_masters),
                "total_master_revisions": len(typed_masters),
                "draft": status_counts.get("DRAFT", 0),
                "review_required": status_counts.get("REVIEW_REQUIRED", 0),
                "validated": status_counts.get("VALIDATED", 0),
                "approved": status_counts.get("APPROVED", 0),
                "production_ready": sum(item["production_ready"] for item in coverage),
                "stale": sum(item["stale"] for item in coverage),
            },
            "count_basis": {
                "total_copy_masters": "distinct master_id across canonical V3 revisions",
                "total_master_revisions": "all exact master_storyboard_v3 rows",
                "production_ready": "latest product Master IDs with every projection PRODUCTION_VALID",
                "stale": "latest product Master IDs requiring Product Truth or projection revalidation",
            },
            "product_coverage": visible_coverage,
            "product_options": [
                {
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                }
                for item in coverage
            ],
            "filter_options": await self._filter_options(),
            "provider_calls": 0,
            "mutations": 0,
        }

    async def get_detail(self, master_id: str, revision: int) -> dict[str, Any]:
        master = await self.factory.repository.get("MASTER_STORYBOARD", master_id, int(revision))
        if not isinstance(master, V3MasterStoryboard):
            raise V3FactoryError("MASTER_NOT_FOUND", "The requested exact Master Storyboard revision was not found.", status_code=404)
        products = await self._products()
        current_truth = await self._current_truth()
        item = await self._render_item(
            master,
            product=products.get(master.product_id),
            current_truth=current_truth,
            include_detail=True,
        )
        item["exact_revision"] = {"master_id": master.master_id, "revision": master.revision}
        item["maintenance"] = {
            "editable_fields": ["stages[].authored_text"],
            "immutable_fields": ["product_id", "product_truth", "recipe", "objective", "angle", "storyline_family", "formula", "stages[].stage_key", "stages[].semantic_class", "evidence_map"],
            "approved_edit_behavior": "new DRAFT revision; approval and production authority are not carried forward",
        }
        return item

    async def create_manual_revision(
        self,
        master_id: str,
        *,
        source_revision: int,
        stages: Sequence[Mapping[str, Any]],
        actor_id: str,
        request_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if not actor_id or not request_id:
            raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id and request_id are required.", status_code=422)
        if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
            raise V3FactoryError("MAINTENANCE_STAGES_REQUIRED", "stages must be an ordered array.", status_code=422)
        async with _db_lock:
            latest = await self.factory.repository.get("MASTER_STORYBOARD", master_id)
            current = await self.factory.repository.get("MASTER_STORYBOARD", master_id, int(source_revision))
            if not isinstance(latest, V3MasterStoryboard):
                raise V3FactoryError("MASTER_NOT_FOUND", "The Master Storyboard was not found.", status_code=404)
            if not isinstance(current, V3MasterStoryboard):
                raise V3FactoryError("MASTER_REVISION_NOT_FOUND", "The requested source revision was not found.", status_code=404)
            if latest.revision != int(source_revision):
                raise V3FactoryError(
                    "V3_MAINTENANCE_REVISION_CONFLICT",
                    "The Master changed after it was loaded. Reload the exact current revision before saving.",
                    status_code=409,
                    details={"expected_revision": int(source_revision), "current_revision": latest.revision},
                )
            if current.status not in _EDITABLE_STATUSES:
                raise V3FactoryError("TERMINAL_REVISION_IMMUTABLE", "This terminal Master revision cannot be edited.", status_code=409)
            expected_keys = [stage.stage_key for stage in current.stages]
            received_keys: list[str] = []
            next_stages = []
            for raw in stages:
                if not isinstance(raw, Mapping):
                    raise V3FactoryError("MAINTENANCE_STAGE_INVALID", "Each stage must be an object.", status_code=422)
                unexpected = set(raw) - {"stage_key", "authored_text"}
                if unexpected:
                    raise V3FactoryError(
                        "MAINTENANCE_STAGE_FIELDS_IMMUTABLE",
                        "Only authored_text may be changed; stage structure is immutable.",
                        status_code=422,
                        details={"fields": sorted(str(item) for item in unexpected)},
                    )
                key = str(raw.get("stage_key") or "")
                received_keys.append(key)
            if received_keys != expected_keys:
                raise V3FactoryError(
                    "MAINTENANCE_STAGE_STRUCTURE_IMMUTABLE",
                    "Stage keys and order must exactly match the source revision.",
                    status_code=409,
                    details={"expected_stage_keys": expected_keys, "received_stage_keys": received_keys},
                )
            for stage, raw in zip(current.stages, stages):
                text = normalized_text(str(raw.get("authored_text") or ""))
                if not text:
                    raise V3FactoryError("MAINTENANCE_STAGE_TEXT_REQUIRED", "Every formula stage needs authored text.", status_code=422)
                next_stages.append(stage.model_copy(update={"authored_text": text, "text_digest": digest_text(text)}))
            revised = current.model_copy(update={
                "revision": current.revision + 1,
                "stages": tuple(next_stages),
                "status": "DRAFT",
                "source": MAINTENANCE_SOURCE,
                "supersedes": V3RevisionRef(entity_id=current.master_id, revision=current.revision),
                "created_at": _now(),
                "created_by": actor_id,
                "word_count": sum(word_count(stage.authored_text) for stage in next_stages),
            })
            revised = revised.model_copy(update={
                "exact_content_digest": master_content_digest(revised),
                "duplicate_fingerprint": exact_resolved_content_fingerprint(revised),
            })
            saved = await self.factory.repository.insert(
                revised,
                actor_id=actor_id,
                request_id=request_id,
                source=MAINTENANCE_SOURCE,
                event_type="EDITED_AS_NEW_REVISION",
                reason=reason or "MANUAL_COPY_MAINTENANCE",
                from_status=current.status,
            )
        return {
            "master": saved.model_dump(mode="json"),
            "source_revision": current.revision,
            "new_revision": saved.revision,
            "automatic_approval": False,
            "approval_carried_forward": False,
            "production_authority_carried_forward": False,
            "projection_refresh_required": True,
            "provider_calls": 0,
            "credit_spend": 0,
        }

    async def delete_draft(
        self,
        master_id: str,
        revision: int,
        *,
        actor_id: str,
        request_id: str,
    ) -> bool:
        async with _db_lock:
            master = await self.factory.repository.get("MASTER_STORYBOARD", master_id, int(revision))
            if not isinstance(master, V3MasterStoryboard):
                raise V3FactoryError("MASTER_NOT_FOUND", "The requested exact Master Storyboard revision was not found.", status_code=404)
            if master.status != "DRAFT":
                raise V3FactoryError("DRAFT_DELETE_ONLY", "Only a DRAFT Master revision can be deleted.", status_code=409)
            blockers = await self._draft_delete_blockers(master_id, int(revision))
            if blockers:
                raise V3FactoryError(
                    "V3_DRAFT_REFERENCED",
                    "The DRAFT is referenced and cannot be deleted.",
                    status_code=409,
                    details={"blockers": blockers},
                )
            deleted = await self.factory.delete_draft(
                "MASTER_STORYBOARD",
                master_id,
                int(revision),
                actor_id=actor_id,
                request_id=request_id,
                source=MAINTENANCE_SOURCE,
            )
            return bool(deleted)


__all__ = ["MAINTENANCE_SOURCE", "V3CopywritingLandbankMaintenanceService"]
