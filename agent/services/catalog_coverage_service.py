"""Authoritative P5.7 catalog coverage matrix and P6 cohort boundary."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from agent.authority.catalog_product_type_truth import (
    P58_INSUFFICIENT_PRODUCT_TRUTH_REASONS,
    P58_PRODUCT_AUTHORITY_BLOCKERS,
    catalog_product_type_truth_provenance,
    resolve_catalog_product_type_truth,
)
from agent.authority.product_type_copy_strategy_registry import (
    PRODUCT_TYPE_COPY_STRATEGY_KEYS,
)
from agent.db import crud
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.models.product_type_copy_strategy import (
    CatalogAuthorityMatrixProduct,
    CatalogAuthorityMatrixReport,
    CatalogCoverageMatrixGroup,
    CatalogCoverageMatrixProduct,
    CatalogCoverageMatrixReport,
)
from agent.services.product_strategy_taxonomy_service import (
    attach_product_strategy_taxonomies,
    list_product_strategy_type_registry,
)
from agent.services.copywriting_taxonomy_service import (
    resolve_product_copywriting_taxonomy,
)


_UNKNOWN_PRODUCT_TYPE = "unknown_product_type"


async def _resolve_insufficient_product_truth_reason(
    product_id: str,
) -> str | None:
    """Resolve legacy P5.8 truth blockers against the current PI evidence.

    P5.8 records the reason that originally kept a product out of authority.  The
    approved Product Intelligence snapshot is the durable operator decision that
    can satisfy the specific ``...DESCRIPTION_ABSENT`` blocker.  Keep the other
    reason-specific blockers unchanged: an approved description alone must not
    silently override a sample-size or title-only ruling.
    """

    reason = P58_INSUFFICIENT_PRODUCT_TRUTH_REASONS.get(product_id)
    if reason != "APPROVED_PRODUCT_TRUTH_DESCRIPTION_ABSENT":
        return reason

    snapshot = await crud.get_latest_approved_product_intelligence_snapshot(
        product_id
    )
    if snapshot and str(snapshot.get("product_description") or "").strip():
        return None
    return reason


_P58_AUTHORITY_CLAIM_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "allowed_claims_json",
)
_P58_QUANTIFIED_SAVINGS_RE = re.compile(
    r"(?i)"
    r"(?:\b\d+(?:[.,]\d+)?\s*%(?!\w)|\b(?:rm|myr)\s*\d[\d,]*(?:\.\d+)?\b|"
    r"\b(?:save|savings?|jimat|penjimatan)\b[^.!?\n]{0,80}"
    r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|per cent|rm|myr)\b)"
)
_P58_LIGHT_OUTPUT_RUNTIME_RE = re.compile(
    r"(?i)\b\d[\d,]*(?:\.\d+)?\s*"
    r"(?:w|watt(?:s)?|wh|mah|lm|lumen(?:s)?|hour(?:s)?|hr(?:s)?|jam)\b"
)


def _snapshot_json_value(
    snapshot: dict[str, object],
    field_name: str,
    expected_type: type[list] | type[dict],
) -> list[object] | dict[str, object]:
    raw = snapshot.get(field_name)
    if isinstance(raw, expected_type):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return [] if expected_type is list else {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return [] if expected_type is list else {}
    return parsed if isinstance(parsed, expected_type) else (
        [] if expected_type is list else {}
    )


def _snapshot_claim_text(snapshot: dict[str, object]) -> str:
    parts: list[str] = []
    for field_name in _P58_AUTHORITY_CLAIM_FIELDS:
        raw = snapshot.get(field_name)
        values: list[object]
        if field_name.endswith("_json"):
            values = list(_snapshot_json_value(snapshot, field_name, list))
        else:
            values = [raw]
        parts.extend(str(value).strip() for value in values if str(value or "").strip())
    return " ".join(parts)


def _snapshot_is_approved_and_claim_safe(snapshot: dict[str, object] | None) -> bool:
    if not snapshot or str(snapshot.get("status") or "").upper() != "APPROVED":
        return False
    if str(snapshot.get("claim_gate") or "").upper() != "CLAIM_SAFE":
        return False
    if str(snapshot.get("claim_risk_level") or "").upper() != "LOW":
        return False
    if not str(snapshot.get("product_description") or "").strip():
        return False
    return not _snapshot_json_value(snapshot, "blocked_claims_json", list)


def _snapshot_has_review_evidence(snapshot: dict[str, object]) -> bool:
    source_urls = _snapshot_json_value(snapshot, "source_urls_json", dict)
    image_evidence = _snapshot_json_value(snapshot, "image_evidence_json", dict)
    return bool(source_urls or image_evidence)


async def _resolve_product_authority_blockers(
    product_id: str,
) -> tuple[str, ...]:
    """Release P5.8 claim blockers only after a current approved PI review.

    The P5.8 map is intentionally the fail-closed baseline.  A Product Intelligence
    *draft* must not change the launch cohort, and an approved snapshot that still
    publishes the original quantitative claim must not erase its blocker.  The
    resolver only retires a named blocker when the approved snapshot is claim-safe,
    low-risk, evidenced, and its published fields no longer contain the specific
    unverified claim that triggered the exception.
    """

    reasons = P58_PRODUCT_AUTHORITY_BLOCKERS.get(product_id, ())
    if not reasons:
        return ()
    snapshot = await crud.get_latest_approved_product_intelligence_snapshot(
        product_id
    )
    if not _snapshot_is_approved_and_claim_safe(snapshot):
        return reasons
    assert snapshot is not None
    claim_text = _snapshot_claim_text(snapshot)
    remaining: list[str] = []
    for reason in reasons:
        if reason == "UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM":
            if _P58_QUANTIFIED_SAVINGS_RE.search(claim_text):
                remaining.append(reason)
            continue
        if reason == "ELECTRICAL_SAFETY_REVIEW_REQUIRED":
            if not (
                str(snapshot.get("warnings_text") or "").strip()
                and _snapshot_has_review_evidence(snapshot)
            ):
                remaining.append(reason)
            continue
        if reason == "UNVERIFIED_LIGHT_OUTPUT_AND_RUNTIME_CLAIMS":
            if _P58_LIGHT_OUTPUT_RUNTIME_RE.search(claim_text):
                remaining.append(reason)
            continue
        remaining.append(reason)
    return tuple(remaining)


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


async def build_catalog_coverage_matrix(
    *,
    _attached_products: list[dict[str, object]] | None = None,
) -> CatalogCoverageMatrixReport:
    """Return every catalog product; this report is never sample-bounded."""

    if any(
        key[1] == _UNKNOWN_PRODUCT_TYPE
        for key in PRODUCT_TYPE_COPY_STRATEGY_KEYS
    ):
        raise RuntimeError("UNKNOWN_PRODUCT_TYPE_MUST_NOT_HAVE_P4_STRATEGY")

    if _attached_products is None:
        products = await crud.list_products(include_archived=True)
        attached = await attach_product_strategy_taxonomies(products)
    else:
        attached = _attached_products
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
        copywriting_mapping = resolve_product_copywriting_taxonomy(product)
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
                    copywriting_mapping is not None
                    or resolve_catalog_product_type_truth(product) is not None
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


async def build_catalog_authority_matrix() -> CatalogAuthorityMatrixReport:
    """Return the final P5.8 terminal state for every catalog product."""

    products = await crud.list_products(include_archived=True)
    attached = await attach_product_strategy_taxonomies(products)
    coverage = await build_catalog_coverage_matrix(
        _attached_products=attached,
    )
    product_by_id = {
        str(product.get("id") or product.get("product_id") or ""): product
        for product in attached
    }

    rows: list[CatalogAuthorityMatrixProduct] = []
    blocked_counts: Counter[str] = Counter()
    for coverage_row in coverage.products:
        product = product_by_id[coverage_row.product_id]
        taxonomy = ProductStrategyTaxonomy.model_validate(
            product["strategy_taxonomy"]
        )
        truth_mapping = resolve_catalog_product_type_truth(product)
        copywriting_mapping = resolve_product_copywriting_taxonomy(product)
        manual_taxonomy_authority = bool(
            taxonomy.authority_source == "MANUAL_OVERRIDE"
            and taxonomy.review_status == "VERIFIED"
            and taxonomy.consumer_status == "READY"
            and not taxonomy.is_stale
            and taxonomy.product_type_group != _UNKNOWN_PRODUCT_TYPE
            and taxonomy.matched_scene_strategy_id != "GENERIC_FALLBACK"
        )
        authority_mapped = (
            copywriting_mapping is not None
            or truth_mapping is not None
            or manual_taxonomy_authority
        )
        authority_blockers = list(
            await _resolve_product_authority_blockers(coverage_row.product_id)
        )
        blockers = list(
            dict.fromkeys([*coverage_row.blockers, *authority_blockers])
        )
        p6_ready = bool(
            authority_mapped
            and coverage_row.p6_launch_cohort
            and not authority_blockers
        )
        insufficient_reason = await _resolve_insufficient_product_truth_reason(
            coverage_row.product_id
        )
        if coverage_row.lifecycle_status != "ACTIVE":
            terminal_state = "ARCHIVED_NOT_IN_SCOPE"
            terminal_reasons = ["PRODUCT_LIFECYCLE_ARCHIVED"]
        elif insufficient_reason is not None:
            terminal_state = "INSUFFICIENT_PRODUCT_TRUTH"
            terminal_reasons = [insufficient_reason]
        elif not authority_mapped:
            terminal_state = "INSUFFICIENT_PRODUCT_TRUTH"
            terminal_reasons = [
                "NO_EXACT_SOURCE_OR_REVIEWED_PRODUCT_TRUTH_MAPPING"
            ]
        elif p6_ready:
            terminal_state = "P6_READY"
            terminal_reasons = []
        else:
            terminal_state = "REVIEW_BLOCKED_WITH_EXACT_REASON"
            terminal_reasons = blockers or ["P6_READINESS_GATE_NOT_SATISFIED"]
        mapping_provenance = (
            "SOURCE_TAXONOMY"
            if copywriting_mapping is not None
            else catalog_product_type_truth_provenance(product)
        )
        if (
            copywriting_mapping is None
            and truth_mapping is None
            and manual_taxonomy_authority
        ):
            mapping_provenance = "MANUAL_TAXONOMY_REVIEW"
        blocked_counts.update(terminal_reasons)
        rows.append(
            CatalogAuthorityMatrixProduct(
                **coverage_row.model_dump(
                    exclude={
                        "blockers",
                        "p6_launch_cohort",
                        "product_truth_mapped",
                    }
                ),
                blockers=blockers,
                p6_launch_cohort=terminal_state == "P6_READY",
                product_truth_mapped=authority_mapped,
                mapping_provenance=mapping_provenance,
                mapping_reviewer_id=(
                    truth_mapping.reviewer_id
                    if truth_mapping is not None
                    else taxonomy.reviewer_id
                ),
                mapping_reviewer_note=(
                    truth_mapping.reviewer_note
                    if truth_mapping is not None
                    else taxonomy.reviewer_note
                ),
                taxonomy_reviewer_id=taxonomy.reviewer_id,
                taxonomy_reviewed_at=taxonomy.reviewed_at,
                terminal_state=terminal_state,
                terminal_reasons=terminal_reasons,
            )
        )

    rows.sort(
        key=lambda row: (
            row.terminal_state,
            row.product_type_group,
            row.product_name.casefold(),
            row.product_id,
        )
    )
    matrix_payload = json.dumps(
        [row.model_dump(mode="json") for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    p6_product_ids = sorted(
        row.product_id for row in rows if row.terminal_state == "P6_READY"
    )
    terminal_state_counts = Counter(row.terminal_state for row in rows)
    return CatalogAuthorityMatrixReport(
        report_version="p5.8_final_catalog_authority_v1",
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
        terminal_state_counts=dict(sorted(terminal_state_counts.items())),
        p6_launch_cohort_count=len(p6_product_ids),
        p6_launch_cohort_product_ids=p6_product_ids,
        blocked_by_reason=dict(
            sorted(
                blocked_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        coverage_groups=coverage.coverage_groups,
        products=rows,
        matrix_sha256=hashlib.sha256(matrix_payload).hexdigest(),
    )


__all__ = [
    "build_catalog_authority_matrix",
    "build_catalog_coverage_matrix",
]

