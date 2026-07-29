"""Authoritative P5.7 catalog coverage matrix and P6 cohort boundary."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from agent.authority.catalog_product_type_truth import (
    resolve_catalog_product_type_truth,
)
from agent.authority.product_type_copy_strategy_registry import (
    PRODUCT_TYPE_COPY_STRATEGY_KEYS,
)
from agent.db import crud
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.models.product_type_copy_strategy import (
    CatalogCoverageMatrixGroup,
    CatalogCoverageMatrixProduct,
    CatalogCoverageMatrixReport,
)
from agent.services.product_strategy_taxonomy_service import (
    attach_product_strategy_taxonomies,
    list_product_strategy_type_registry,
)


_UNKNOWN_PRODUCT_TYPE = "unknown_product_type"


def _product_name(product: dict[str, object]) -> str:
    for field in (
        "product_display_name",
        "product_short_name",
        "raw_product_title",
    ):
        value = str(product.get(field) or "").strip()
        if value:
            return value
    return "Unnamed product"


def _launch_blockers(
    *,
    lifecycle_status: str,
    taxonomy: ProductStrategyTaxonomy,
    registry_status: str,
    registry_binding_matches: bool,
    p4_supported: bool,
) -> list[str]:
    blockers: list[str] = []
    if lifecycle_status != "ACTIVE":
        blockers.append("PRODUCT_NOT_ACTIVE")
    if taxonomy.review_status != "VERIFIED":
        blockers.append("TAXONOMY_NOT_VERIFIED")
    if taxonomy.consumer_status != "READY":
        blockers.append("TAXONOMY_NOT_READY")
    if taxonomy.scene_coverage_status != "COVERED":
        blockers.append("COVERAGE_NOT_COVERED")
    if taxonomy.is_stale:
        blockers.append("TAXONOMY_STALE")
    if taxonomy.fallback_used:
        blockers.append("FALLBACK_NOT_ALLOWED")
    if not taxonomy.specific_strategy:
        blockers.append("SPECIFIC_STRATEGY_REQUIRED")
    if registry_status != "ACTIVE":
        blockers.append("TYPE_REGISTRY_NOT_ACTIVE")
    elif not registry_binding_matches:
        blockers.append("TYPE_REGISTRY_SCENE_MISMATCH")
    if not p4_supported:
        blockers.append("P4_NOT_SUPPORTED")
    if taxonomy.product_type_group == _UNKNOWN_PRODUCT_TYPE:
        blockers.append("UNKNOWN_PRODUCT_TYPE")
    return list(dict.fromkeys(blockers))


async def build_catalog_coverage_matrix() -> CatalogCoverageMatrixReport:
    """Return every catalog product; this report is never sample-bounded."""

    if any(
        key[1] == _UNKNOWN_PRODUCT_TYPE
        for key in PRODUCT_TYPE_COPY_STRATEGY_KEYS
    ):
        raise RuntimeError("UNKNOWN_PRODUCT_TYPE_MUST_NOT_HAVE_P4_STRATEGY")

    products = await crud.list_products(include_archived=True)
    attached = await attach_product_strategy_taxonomies(products)
    type_registry = await list_product_strategy_type_registry()
    registry_by_pair = {
        (item.cluster, item.product_type_group): item
        for item in type_registry.items
    }

    rows: list[CatalogCoverageMatrixProduct] = []
    blocked_counts: Counter[str] = Counter()
    for product in attached:
        taxonomy = ProductStrategyTaxonomy.model_validate(
            product["strategy_taxonomy"]
        )
        lifecycle_status = str(
            product.get("lifecycle_status") or "ACTIVE"
        ).upper()
        strategy_key = (
            taxonomy.cluster,
            taxonomy.product_type_group,
            taxonomy.matched_scene_strategy_id,
        )
        p4_supported = strategy_key in PRODUCT_TYPE_COPY_STRATEGY_KEYS
        registry_entry = registry_by_pair.get(
            (taxonomy.cluster, taxonomy.product_type_group)
        )
        registry_status = (
            registry_entry.registry_status
            if registry_entry is not None
            else "UNREGISTERED"
        )
        registry_binding_matches = bool(
            registry_entry is not None
            and registry_entry.matched_scene_strategy_id
            == taxonomy.matched_scene_strategy_id
            and registry_entry.scene_coverage_status
            == taxonomy.scene_coverage_status
        )
        blockers = _launch_blockers(
            lifecycle_status=lifecycle_status,
            taxonomy=taxonomy,
            registry_status=registry_status,
            registry_binding_matches=registry_binding_matches,
            p4_supported=p4_supported,
        )
        blocked_counts.update(blockers)
        rows.append(
            CatalogCoverageMatrixProduct(
                product_id=taxonomy.product_id,
                product_name=_product_name(product),
                lifecycle_status=lifecycle_status,
                source_category=(
                    str(product.get("category"))
                    if product.get("category") is not None
                    else None
                ),
                source_subcategory=(
                    str(product.get("subcategory"))
                    if product.get("subcategory") is not None
                    else None
                ),
                source_product_type=(
                    str(product.get("type"))
                    if product.get("type") is not None
                    else None
                ),
                product_truth_mapped=(
                    resolve_catalog_product_type_truth(product) is not None
                ),
                cluster=taxonomy.cluster,
                product_type_group=taxonomy.product_type_group,
                scene_strategy_id=taxonomy.matched_scene_strategy_id,
                registry_status=registry_status,
                review_status=taxonomy.review_status,
                consumer_status=taxonomy.consumer_status,
                scene_coverage_status=taxonomy.scene_coverage_status,
                taxonomy_stale=taxonomy.is_stale,
                fallback_used=taxonomy.fallback_used,
                specific_strategy=taxonomy.specific_strategy,
                p4_support_status=(
                    "P4_SUPPORTED" if p4_supported else "P4_UNSUPPORTED"
                ),
                p6_launch_cohort=not blockers,
                blockers=blockers,
            )
        )

    rows.sort(
        key=lambda row: (
            row.product_type_group,
            row.product_name.casefold(),
            row.product_id,
        )
    )
    group_counts: Counter[
        tuple[str, str, str, str, str, str, str]
    ] = Counter()
    launch_group_counts: Counter[
        tuple[str, str, str, str, str, str, str]
    ] = Counter()
    for row in rows:
        group_key = (
            row.lifecycle_status,
            row.cluster,
            row.product_type_group,
            row.scene_strategy_id,
            row.registry_status,
            row.scene_coverage_status,
            row.p4_support_status,
        )
        group_counts[group_key] += 1
        if row.p6_launch_cohort:
            launch_group_counts[group_key] += 1

    coverage_groups = [
        CatalogCoverageMatrixGroup(
            lifecycle_status=key[0],
            cluster=key[1],
            product_type_group=key[2],
            scene_strategy_id=key[3],
            registry_status=key[4],
            scene_coverage_status=key[5],
            p4_support_status=key[6],
            product_count=count,
            p6_launch_count=launch_group_counts[key],
        )
        for key, count in sorted(group_counts.items())
    ]
    matrix_payload = json.dumps(
        [row.model_dump(mode="json") for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    p6_product_ids = sorted(
        row.product_id for row in rows if row.p6_launch_cohort
    )
    return CatalogCoverageMatrixReport(
        report_version="p5.7_catalog_coverage_v1",
        total_products=len(rows),
        active_products=sum(
            row.lifecycle_status == "ACTIVE" for row in rows
        ),
        archived_products=sum(
            row.lifecycle_status == "ARCHIVED" for row in rows
        ),
        product_truth_mapped_count=sum(
            row.product_truth_mapped for row in rows
        ),
        p4_supported_count=sum(
            row.p4_support_status == "P4_SUPPORTED" for row in rows
        ),
        unknown_product_type_count=sum(
            row.product_type_group == _UNKNOWN_PRODUCT_TYPE for row in rows
        ),
        unknown_product_type_p4_supported_count=sum(
            row.product_type_group == _UNKNOWN_PRODUCT_TYPE
            and row.p4_support_status == "P4_SUPPORTED"
            for row in rows
        ),
        p6_launch_cohort_count=len(p6_product_ids),
        p6_launch_cohort_product_ids=p6_product_ids,
        blocked_by_reason=dict(
            sorted(
                blocked_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        coverage_groups=coverage_groups,
        products=rows,
        matrix_sha256=hashlib.sha256(matrix_payload).hexdigest(),
    )


__all__ = ["build_catalog_coverage_matrix"]

