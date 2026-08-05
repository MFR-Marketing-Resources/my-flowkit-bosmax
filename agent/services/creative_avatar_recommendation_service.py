"""Creative Intelligence — Round 1: product/category -> recommended AI avatar.

READ-FIRST, non-generative, review/config-only. This service:
  * resolves a raw product category into one of the 12 canonical creative
    clusters (from the workbook CATEGORY_MAP + keyword fallback + a deterministic
    ``Home & Living`` fallback);
  * seeds the EXISTING ``avatar_product_fit`` table from a curated, pool-validated
    cluster -> ``BOS_`` avatar crosswalk (idempotent, provenance in the notes);
  * returns recommended avatars for a product/category by REUSING the existing
    ``avatar_fit_service`` (no new recommendation engine).

Safety: it never writes Product Truth, Copy Sets, Copy Registry, Copy
Intelligence, or any generation/asset table. Every seeded ``avatar_code`` is
validated against the live ``avatar_registry`` pool before insertion; workbook
``AV01-AV08`` codes are never used (they are not in the live pool).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.services import avatar_fit_service
from agent.services import avatar_registry

_AUTHORITY = Path(__file__).resolve().parents[1] / "authority"
_CATEGORY_MAP_FILE = _AUTHORITY / "creative_category_cluster_map.json"
_CROSSWALK_FILE = _AUTHORITY / "creative_avatar_cluster_crosswalk.json"

CROSSWALK_SOURCE = "CREATIVE_AVATAR_CROSSWALK_v1"


@lru_cache(maxsize=1)
def _category_map() -> dict[str, Any]:
    return json.loads(_CATEGORY_MAP_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _crosswalk() -> dict[str, Any]:
    return json.loads(_CROSSWALK_FILE.read_text(encoding="utf-8"))


def canonical_clusters() -> list[str]:
    return list(_category_map().get("clusters", []))


def fallback_cluster() -> str:
    return str(_category_map().get("fallback_cluster") or "Home & Living")


REVIEW_REQUIRED_SOURCES = (
    "REVIEW_REQUIRED_NO_CATEGORY",
    "REVIEW_REQUIRED_UNKNOWN_CATEGORY",
)


def is_review_required(resolved: dict[str, Any]) -> bool:
    """True when a resolved cluster is review-required (no proven mapping)."""
    return resolved.get("cluster") is None


def resolve_cluster(
    category: str | None, *, allow_fallback: bool = False
) -> dict[str, str | None]:
    """Resolve a raw product category into a canonical cluster.

    Deterministic order: exact CATEGORY_MAP match -> first-segment match ->
    keyword rule. Returns ``{"cluster", "cluster_source"}``.

    FAIL-CLOSED by default: an empty or unresolved category returns
    ``cluster=None`` with a ``REVIEW_REQUIRED_*`` source, so the product-first
    creative flow never silently inherits the Home & Living fallback and then
    auto-plans an unsuitable avatar. A proven, explicit mapping
    (EXACT / PREFIX / KEYWORD) is always honoured. Legacy callers that
    intentionally want the deterministic Home & Living fallback for an
    unknown/blank category must opt in explicitly with ``allow_fallback=True``.
    """
    cfg = _category_map()
    table: dict[str, str] = cfg.get("category_to_cluster", {})
    raw = str(category or "").strip()
    if not raw:
        if allow_fallback:
            return {"cluster": fallback_cluster(), "cluster_source": "FALLBACK_EMPTY"}
        return {"cluster": None, "cluster_source": "REVIEW_REQUIRED_NO_CATEGORY"}

    key = avatar_fit_service.normalise_category(raw)
    if key in table:
        return {"cluster": table[key], "cluster_source": "EXACT"}

    first = avatar_fit_service.normalise_category(raw.split(">")[0])
    if first in table:
        return {"cluster": table[first], "cluster_source": "PREFIX"}

    for rule in cfg.get("keyword_rules", []):
        tokens = rule.get("any", [])
        cluster = rule.get("cluster")
        if cluster and any(tok in key for tok in tokens):
            return {"cluster": cluster, "cluster_source": "KEYWORD"}

    if allow_fallback:
        return {"cluster": fallback_cluster(), "cluster_source": "FALLBACK"}
    return {"cluster": None, "cluster_source": "REVIEW_REQUIRED_UNKNOWN_CATEGORY"}


def _project_dual_source(
    verified_taxonomy: Any, category: str | None, *, allow_fallback: bool = False
) -> dict[str, str | None]:
    """Project a product's creative cluster from its stored, VERIFIED strategy
    taxonomy (the authority) when available, else fall back to the legacy
    category derivation — tagged, never silent.

    ``verified_taxonomy`` is a ``ProductStrategyTaxonomy`` ONLY when it has passed
    the full VERIFIED gate; otherwise ``None``. Returns the ``resolve_cluster``
    shape plus an additive ``cluster_provenance`` marker, so downstream consumers
    (which read only ``cluster`` / ``cluster_source``) are unchanged.
    """
    from agent.services.product_cluster_grouping import resolve_creative_cluster

    if verified_taxonomy is not None:
        creative = resolve_creative_cluster(verified_taxonomy.cluster)
        if creative is not None:
            return {
                "cluster": creative,
                "cluster_source": "STRATEGY_CLUSTER_VERIFIED",
                "cluster_provenance": "STRATEGY_CLUSTER_VERIFIED",
            }
        # Verified, but the stored cluster has no crosswalk bucket (unreachable via
        # the legit review flow, which refuses generic/unmapped clusters). Fail
        # closed — NEVER silently revert a verified product to category derivation.
        return {
            "cluster": None,
            "cluster_source": "STRATEGY_CLUSTER_UNMAPPED",
            "cluster_provenance": "STRATEGY_CLUSTER_VERIFIED",
        }

    # allow_fallback lets a LEGACY lane (creative_direction) keep its long-standing
    # opt-in Home & Living fallback for a blank/unknown category; product-first
    # surfaces stay fail-closed (the default).
    legacy = resolve_cluster(category, allow_fallback=allow_fallback)
    return {**legacy, "cluster_provenance": "LEGACY_CATEGORY_DERIVATION"}


async def resolve_product_cluster(
    product_id: str | None, category: str | None
) -> dict[str, str | None]:
    """Async dual-source resolver for product-bearing creative surfaces.

    Projects the product's VERIFIED strategy taxonomy via the SSOT crosswalk when
    present; otherwise the tagged legacy category derivation. A missing
    ``product_id`` or an unverified taxonomy both take the legacy path.
    """
    from agent.services.product_strategy_taxonomy_service import (
        ProductStrategyTaxonomyError,
        require_verified_product_strategy_taxonomy,
    )

    verified = None
    if product_id:
        try:
            verified = await require_verified_product_strategy_taxonomy(str(product_id))
        except ProductStrategyTaxonomyError:
            verified = None
    return _project_dual_source(verified, category)


def resolve_product_cluster_sync(
    product: dict[str, Any] | None, category: str | None, *, allow_fallback: bool = False
) -> dict[str, str | None]:
    """Sync twin of ``resolve_product_cluster`` for the synchronous
    ``creative_direction`` lane. Reads the VERIFIED taxonomy without an event
    loop; any unverified / absent / stale taxonomy falls through to tagged legacy.
    """
    from agent.services.product_strategy_taxonomy_service import (
        read_verified_product_strategy_taxonomy_sync,
    )

    verified = read_verified_product_strategy_taxonomy_sync(product or {})
    return _project_dual_source(verified, category, allow_fallback=allow_fallback)


def _live_avatar_codes() -> set[str]:
    return {str(a.get("avatar_code")) for a in avatar_registry.list_pool()}


async def seed_avatar_product_fit(*, dry_run: bool = True) -> dict[str, Any]:
    """Populate ``avatar_product_fit`` from the pool-validated crosswalk.

    Idempotent (``upsert`` keyed on avatar_code+product_category). Every code is
    re-validated against the live avatar pool before insertion; unresolvable codes
    are skipped and reported (never inserted). ``dry_run`` writes nothing.
    """
    from agent.db import crud

    live = _live_avatar_codes()
    crosswalk = _crosswalk().get("crosswalk", {})
    written = 0
    skipped_invalid: list[dict[str, str]] = []
    per_cluster: dict[str, int] = {}

    for cluster, rows in crosswalk.items():
        product_category = avatar_fit_service.normalise_category(cluster)
        count = 0
        for row in rows:
            code = str(row.get("avatar_code") or "")
            if code not in live:
                skipped_invalid.append({"cluster": cluster, "avatar_code": code})
                continue
            count += 1
            if dry_run:
                continue
            await crud.upsert_avatar_product_fit(
                avatar_code=code,
                product_category=product_category,
                fit_score=row.get("fit_score", 0.8),
                suitability_notes=row.get("suitability_notes")
                or f"{cluster} [src:{CROSSWALK_SOURCE}]",
            )
            written += 1
        per_cluster[cluster] = count

    return {
        "dry_run": dry_run,
        "source": CROSSWALK_SOURCE,
        "clusters": len(crosswalk),
        "mappings_valid": sum(per_cluster.values()),
        "written": 0 if dry_run else written,
        "skipped_invalid": skipped_invalid,
        "per_cluster": per_cluster,
    }


async def reconcile_avatar_product_fit(*, dry_run: bool = True) -> dict[str, Any]:
    """Deterministic reconciliation of ``avatar_product_fit`` to committed crosswalk.

    - upserts every expected (live-pool) crosswalk row
    - removes only rows that carry the managed crosswalk provenance marker and
      are no longer expected (stale managed mappings)
    - preserves unrelated manually managed mappings (notes without the marker)

    Affects only ``avatar_product_fit`` in one transaction. Dry-run reports the
    diff without writing; an applied run uses a separate connection for read-back.
    """
    from agent.db import crud

    live = _live_avatar_codes()
    crosswalk = _crosswalk().get("crosswalk", {})
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    orphan_codes: list[str] = []
    for cluster, rows in crosswalk.items():
        product_category = avatar_fit_service.normalise_category(cluster)
        for row in rows:
            code = str(row.get("avatar_code") or "")
            if code not in live:
                orphan_codes.append(code)
                continue
            expected[(code, product_category)] = {
                "avatar_code": code,
                "product_category": product_category,
                "fit_score": row.get("fit_score", 0.8),
                "suitability_notes": row.get("suitability_notes")
                or f"{cluster} [src:{CROSSWALK_SOURCE}]",
                "cluster": cluster,
            }

    current_rows = await crud.list_avatar_product_fits(limit=10_000)
    current_keys = {
        (str(r.get("avatar_code") or ""), str(r.get("product_category") or "")): r
        for r in current_rows
    }

    missing = [v for k, v in expected.items() if k not in current_keys]
    changed: list[dict[str, Any]] = []
    for key, exp in expected.items():
        cur = current_keys.get(key)
        if not cur:
            continue
        cur_score = float(cur.get("fit_score") or 0)
        exp_score = float(exp.get("fit_score") or 0)
        cur_notes = str(cur.get("suitability_notes") or "")
        exp_notes = str(exp.get("suitability_notes") or "")
        if abs(cur_score - exp_score) > 1e-9 or cur_notes != exp_notes:
            changed.append({"key": {"avatar_code": key[0], "product_category": key[1]},
                            "from": {"fit_score": cur_score, "suitability_notes": cur_notes},
                            "to": {"fit_score": exp_score, "suitability_notes": exp_notes}})

    marker = f"[src:{CROSSWALK_SOURCE}]"
    stale_managed: list[dict[str, str]] = []
    preserved_manual = 0
    for key, row in current_keys.items():
        if key in expected:
            continue
        notes = str(row.get("suitability_notes") or "")
        if marker in notes or CROSSWALK_SOURCE in notes:
            stale_managed.append({
                "avatar_code": key[0],
                "product_category": key[1],
            })
        else:
            preserved_manual += 1

    written = 0
    removed = 0
    if not dry_run:
        result = await crud.reconcile_avatar_product_fits(
            list(expected.values()), stale_managed
        )
        written = result["written"]
        removed = result["removed"]

    # Fresh read-back for parity proof.
    after = (
        await crud.list_avatar_product_fits(limit=10_000)
        if dry_run
        else await crud.list_avatar_product_fits_fresh(limit=10_000)
    )
    after_managed = [
        r for r in after
        if marker in str(r.get("suitability_notes") or "")
        or CROSSWALK_SOURCE in str(r.get("suitability_notes") or "")
    ]
    after_keys = {
        (str(r.get("avatar_code") or ""), str(r.get("product_category") or ""))
        for r in after_managed
    }
    expected_keys = set(expected.keys())
    parity = after_keys == expected_keys if not dry_run else None

    return {
        "dry_run": dry_run,
        "source": CROSSWALK_SOURCE,
        "expected_count": len(expected),
        "current_count": len(current_rows),
        "missing": [
            {"avatar_code": m["avatar_code"], "product_category": m["product_category"]}
            for m in missing
        ],
        "changed": changed,
        "stale_managed": stale_managed,
        "orphan_avatar_codes": sorted(set(orphan_codes)),
        "preserved_manual_count": preserved_manual,
        "written": 0 if dry_run else written,
        "removed": 0 if dry_run else removed,
        "parity_ok": parity,
        "clusters": sorted(crosswalk.keys()),
    }


async def recommend_avatars_for_category(
    category: str | None, *, _resolved: dict[str, str | None] | None = None
) -> dict[str, Any]:
    """Read-only avatar recommendation for a raw category. Never mutates.

    Fail-closed: a blank or unresolved category returns no recommendation and
    ``review_required=True`` with ``cluster=None``, so the product-first flow
    never auto-plans or auto-links an avatar for an un-categorised product.
    """
    # _resolved: product-first dual-source bypass passed by the _for_product wrapper.
    resolved = _resolved or resolve_cluster(category)
    cluster = resolved["cluster"]
    if cluster is None:
        return {
            "category": category,
            "cluster": None,
            "cluster_source": resolved["cluster_source"],
            "review_required": True,
            "avatar_count": 0,
            "avatars": [],
        }
    avatars = await avatar_fit_service.get_suitable_avatars(
        cluster, include_all_fallback=True
    )
    return {
        "category": category,
        "cluster": cluster,
        "cluster_source": resolved["cluster_source"],
        "review_required": False,
        "avatar_count": len(avatars),
        "avatars": avatars,
    }


async def recommend_avatars_for_product(product_id: str) -> dict[str, Any]:
    """Read-only avatar recommendation for a product (manual or imported)."""
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    resolved = await resolve_product_cluster(product_id, product.get("category"))
    result = await recommend_avatars_for_category(
        product.get("category"), _resolved=resolved
    )
    result["product_id"] = product_id
    result["product_name"] = (
        product.get("product_display_name") or product.get("raw_product_title")
    )
    return result


async def audit_product_cluster_coverage() -> dict[str, Any]:
    """Read-only inventory of the registered product catalogue by creative cluster.

    Blank categories are deliberately reported as ``UNKNOWN_REVIEW_REQUIRED``;
    they must never silently inherit the legacy Home & Living fallback and then
    receive an unsuitable avatar plan.
    """
    from agent.db import crud
    from agent.services.product_cluster_grouping import resolve_creative_cluster
    from agent.services.product_strategy_taxonomy_service import (
        attach_product_strategy_taxonomies,
    )
    from agent.services.reporting_service import is_non_product_row

    # Quarantine test fixtures + merged-alias duplicates (non-products), exactly as
    # the reporting coverage/exception authorities do — otherwise archived smoke
    # fixtures (blank category) inflate UNKNOWN_REVIEW_REQUIRED and the Executive
    # "Uncategorised" KPI reads non-zero when the real catalogue is fully clustered.
    products = [
        p for p in await crud.list_products(limit=5000) if not is_non_product_row(p)
    ]
    # SSOT: a product with a VERIFIED strategy taxonomy is counted under its stored
    # cluster (projected via the crosswalk); only unverified rows fall back to the
    # legacy category derivation. One bulk sidecar read attaches the taxonomies.
    products = await attach_product_strategy_taxonomies(products)
    cluster_counts: dict[str, int] = {cluster: 0 for cluster in canonical_clusters()}
    unknown_samples: list[dict[str, str]] = []
    raw_categories: dict[str, int] = {}
    unknown_count = 0
    for product in products:
        raw_category = str(product.get("category") or "").strip()
        tax = product.get("strategy_taxonomy") or {}
        verified = (
            tax.get("materialization_status") == "MATERIALIZED"
            and tax.get("review_status") == "VERIFIED"
            and tax.get("consumer_status") == "READY"
            and not tax.get("is_stale")
        )
        if verified:
            resolved_cluster = resolve_creative_cluster(tax.get("cluster"))
        else:
            resolved_cluster = (
                resolve_cluster(raw_category)["cluster"] if raw_category else None
            )
        if resolved_cluster is not None:
            cluster_counts[resolved_cluster] = cluster_counts.get(resolved_cluster, 0) + 1
            if raw_category:
                raw_categories[raw_category] = raw_categories.get(raw_category, 0) + 1
            continue
        # blank / unresolved / unverified-unmapped -> review required, never auto-planned
        unknown_count += 1
        if len(unknown_samples) < 25:
            unknown_samples.append({
                "product_id": str(product.get("id") or ""),
                "product_name": str(product.get("product_display_name") or product.get("raw_product_title") or ""),
            })
    return {
        "product_total": len(products),
        "canonical_clusters": canonical_clusters(),
        "cluster_counts": cluster_counts,
        "unknown_review_required": unknown_count,
        "unknown_samples": unknown_samples,
        "raw_category_counts": raw_categories,
        "note": "Read-only audit. Products with blank category are not auto-planned.",
    }
