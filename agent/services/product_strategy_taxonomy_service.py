"""Durable, review-gated product-strategy taxonomy.

This service materializes the existing P2 scouting result into a sidecar table.
It never mutates Product Truth, Copy Registry, scene strategies, or generation
state. Unknown, partial, fallback, stale, and low-confidence classifications
remain explicitly blocked for downstream copy consumers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from agent.authority.catalog_product_type_truth import (
    resolve_catalog_product_type_truth,
)
from agent.config import DB_PATH
from agent.db import crud
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomy,
    ProductStrategyTaxonomyBackfillRequest,
    ProductStrategyTaxonomyBackfillResponse,
    ProductStrategyTaxonomyReviewRequest,
    ProductStrategyTypeRegistrationRequest,
    ProductStrategyTypeRegistryEntry,
    ProductStrategyTypeRegistryListResponse,
    ProductStrategyTypeRegistrySeedRequest,
    ProductStrategyTypeRegistrySeedResponse,
)
from agent.services.product_intelligence_service import (
    resolve_product_intelligence_profile,
)
from agent.services.product_strategy_scouting_service import (
    SCOUTING_CLUSTER_ORDER,
    classify_product_strategy_tag,
    product_strategy_type_registry_seed_entries,
)
from agent.services.scene_strategy_library import SCENE_STRATEGIES


TAXONOMY_VERSION = "product_strategy_taxonomy_v1"
BACKFILL_CONFIRMATION = "MATERIALIZE_PRODUCT_STRATEGY_TAXONOMY"
REGISTRY_SEED_CONFIRMATION = "SEED_PRODUCT_STRATEGY_TYPE_REGISTRY"
_FINGERPRINT_FIELDS = (
    "id",
    "product_id",
    "raw_product_title",
    "product_display_name",
    "product_short_name",
    "category",
    "subcategory",
    "type",
    "product_type",
    "product_type_id",
    "silo",
)


class ProductStrategyTaxonomyError(ValueError):
    """Stable service error surfaced by Product and Creative Intelligence APIs."""


def lookup_product_strategy_type_registry_entry(
    cluster: str,
    product_type_group: str,
    *,
    db_path: Path | None = None,
) -> dict[str, object] | None:
    """Read one exact registry pair from the authoritative SQLite database."""

    resolved_path = Path(db_path or DB_PATH).resolve()
    if not resolved_path.is_file() or not cluster or not product_type_group:
        return None
    try:
        with sqlite3.connect(
            f"{resolved_path.as_uri()}?mode=ro",
            uri=True,
        ) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM product_strategy_type_registry "
                "WHERE cluster=? AND product_type_group=?",
                (cluster, product_type_group),
            ).fetchone()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def product_strategy_fingerprint(product: Mapping[str, object]) -> str:
    payload = {
        field: product.get(field)
        for field in _FINGERPRINT_FIELDS
        if product.get(field) is not None
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strategy_binding(
    product: Mapping[str, object],
) -> dict[str, object]:
    """Resolve only the classifier fields required for binding-staleness checks."""

    tag = classify_product_strategy_tag(product)
    if tag["fallback_used"]:
        coverage_status = "FALLBACK_ONLY"
    elif tag["specific_strategy"]:
        coverage_status = "COVERED"
    else:
        coverage_status = "PARTIAL"
    return {
        "cluster": tag["cluster"],
        "product_type_group": tag["product_type_group"],
        "matched_scene_strategy_id": tag["matched_scene_strategy_id"],
        "scene_coverage_status": coverage_status,
        "fallback_used": bool(tag["fallback_used"]),
        "specific_strategy": bool(tag["specific_strategy"]),
    }


def build_product_strategy_taxonomy_candidate(
    product: Mapping[str, object],
    *,
    materialization_status: str = "PREVIEW",
) -> ProductStrategyTaxonomy:
    """Build one deterministic taxonomy candidate without writing anything."""

    binding = _strategy_binding(product)
    intelligence = resolve_product_intelligence_profile(dict(product))

    confidence = str(intelligence.get("confidence") or "LOW").upper()
    if confidence not in {"HIGH", "MEDIUM", "LOW"}:
        confidence = "LOW"
    intelligence_status = str(
        intelligence.get("intelligence_status") or "NEEDS_REVIEW"
    ).upper()

    # Existing catalog mapping review did not review this exact cluster/type/scene
    # contract. Even a HIGH/COVERED resolver result therefore starts fail-closed
    # until an admin reviews this fingerprinted taxonomy explicitly.
    review_reasons: list[str] = ["AUTO_DERIVED_REVIEW_REQUIRED"]
    if binding["scene_coverage_status"] != "COVERED":
        review_reasons.append(f"SCENE_{binding['scene_coverage_status']}")
    if binding["cluster"] == "generic_unclassified":
        review_reasons.append("GENERIC_UNCLASSIFIED")
    if confidence != "HIGH":
        review_reasons.append(f"INTELLIGENCE_{confidence}")
    if intelligence_status != "READY":
        review_reasons.append("INTELLIGENCE_NEEDS_REVIEW")
    if bool(intelligence.get("taxonomy_conflict")):
        review_reasons.append("TAXONOMY_CONFLICT")

    review_status = "REVIEW_REQUIRED"
    now = _now()
    return ProductStrategyTaxonomy(
        product_id=str(product.get("id") or product.get("product_id") or ""),
        taxonomy_version=TAXONOMY_VERSION,
        product_fingerprint=product_strategy_fingerprint(product),
        cluster=str(binding["cluster"]),
        product_type_group=str(binding["product_type_group"]),
        matched_scene_strategy_id=str(
            binding["matched_scene_strategy_id"]
        ),
        scene_coverage_status=str(binding["scene_coverage_status"]),
        fallback_used=bool(binding["fallback_used"]),
        specific_strategy=bool(binding["specific_strategy"]),
        classification_confidence=confidence,
        review_status=review_status,
        consumer_status=(
            "READY" if review_status == "VERIFIED" else "BLOCKED_REVIEW_REQUIRED"
        ),
        authority_source="AUTO_DERIVED",
        materialization_status=materialization_status,
        review_reasons=_unique(review_reasons),
        derived_at=now,
        updated_at=now,
    )


def _row_to_taxonomy(row: Mapping[str, object]) -> ProductStrategyTaxonomy:
    try:
        review_reasons = json.loads(str(row.get("review_reasons_json") or "[]"))
    except json.JSONDecodeError:
        review_reasons = ["INVALID_REVIEW_REASONS_JSON"]
    return ProductStrategyTaxonomy(
        product_id=str(row.get("product_id") or ""),
        taxonomy_version=str(row.get("taxonomy_version") or TAXONOMY_VERSION),
        product_fingerprint=str(row.get("product_fingerprint") or ""),
        cluster=str(row.get("cluster") or "generic_unclassified"),
        product_type_group=str(
            row.get("product_type_group") or "unknown_product_type"
        ),
        matched_scene_strategy_id=str(
            row.get("matched_scene_strategy_id") or "GENERIC_FALLBACK"
        ),
        scene_coverage_status=str(
            row.get("scene_coverage_status") or "FALLBACK_ONLY"
        ),
        fallback_used=bool(row.get("fallback_used")),
        specific_strategy=bool(row.get("specific_strategy")),
        classification_confidence=str(
            row.get("classification_confidence") or "LOW"
        ),
        review_status=str(row.get("review_status") or "REVIEW_REQUIRED"),
        consumer_status=str(
            row.get("consumer_status") or "BLOCKED_REVIEW_REQUIRED"
        ),
        authority_source=str(row.get("authority_source") or "AUTO_DERIVED"),
        materialization_status=str(
            row.get("materialization_status") or "PLACEHOLDER"
        ),
        review_reasons=[
            str(value) for value in review_reasons if str(value).strip()
        ],
        reviewer_id=(
            str(row["reviewer_id"]) if row.get("reviewer_id") is not None else None
        ),
        reviewer_note=(
            str(row["reviewer_note"])
            if row.get("reviewer_note") is not None
            else None
        ),
        derived_at=(
            str(row["derived_at"]) if row.get("derived_at") is not None else None
        ),
        reviewed_at=(
            str(row["reviewed_at"]) if row.get("reviewed_at") is not None else None
        ),
        created_at=(
            str(row["created_at"]) if row.get("created_at") is not None else None
        ),
        updated_at=(
            str(row["updated_at"]) if row.get("updated_at") is not None else None
        ),
    )


def _taxonomy_to_record(taxonomy: ProductStrategyTaxonomy) -> dict[str, object]:
    return {
        "product_id": taxonomy.product_id,
        "taxonomy_version": taxonomy.taxonomy_version,
        "product_fingerprint": taxonomy.product_fingerprint,
        "cluster": taxonomy.cluster,
        "product_type_group": taxonomy.product_type_group,
        "matched_scene_strategy_id": taxonomy.matched_scene_strategy_id,
        "scene_coverage_status": taxonomy.scene_coverage_status,
        "fallback_used": int(taxonomy.fallback_used),
        "specific_strategy": int(taxonomy.specific_strategy),
        "classification_confidence": taxonomy.classification_confidence,
        "review_status": taxonomy.review_status,
        "consumer_status": taxonomy.consumer_status,
        "authority_source": taxonomy.authority_source,
        "materialization_status": taxonomy.materialization_status,
        "review_reasons_json": json.dumps(
            taxonomy.review_reasons,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "reviewer_id": taxonomy.reviewer_id,
        "reviewer_note": taxonomy.reviewer_note,
        "derived_at": taxonomy.derived_at,
        "reviewed_at": taxonomy.reviewed_at,
        "updated_at": taxonomy.updated_at or _now(),
    }


def _row_to_registry_entry(
    row: Mapping[str, object],
) -> ProductStrategyTypeRegistryEntry:
    return ProductStrategyTypeRegistryEntry(
        cluster=str(row.get("cluster") or ""),
        product_type_group=str(row.get("product_type_group") or ""),
        display_name=str(row.get("display_name") or ""),
        matched_scene_strategy_id=str(
            row.get("matched_scene_strategy_id") or "GENERIC_FALLBACK"
        ),
        scene_coverage_status=str(
            row.get("scene_coverage_status") or "FALLBACK_ONLY"
        ),
        registry_status=str(row.get("registry_status") or "REVIEW_REQUIRED"),
        auto_classification_enabled=bool(
            row.get("auto_classification_enabled")
        ),
        authority_source=str(row.get("authority_source") or "SYSTEM_SEED"),
        reviewer_id=(
            str(row["reviewer_id"])
            if row.get("reviewer_id") is not None
            else None
        ),
        reviewer_note=(
            str(row["reviewer_note"])
            if row.get("reviewer_note") is not None
            else None
        ),
        reviewed_at=(
            str(row["reviewed_at"])
            if row.get("reviewed_at") is not None
            else None
        ),
        created_at=(
            str(row["created_at"])
            if row.get("created_at") is not None
            else None
        ),
        updated_at=(
            str(row["updated_at"])
            if row.get("updated_at") is not None
            else None
        ),
    )


async def list_product_strategy_type_registry(
    cluster: str | None = None,
) -> ProductStrategyTypeRegistryListResponse:
    rows = await crud.list_product_strategy_type_registry(cluster)
    return ProductStrategyTypeRegistryListResponse(
        items=[_row_to_registry_entry(row) for row in rows],
        clusters=list(SCOUTING_CLUSTER_ORDER),
        scene_strategy_ids=sorted(SCENE_STRATEGIES),
    )


def _validate_registry_binding(
    *,
    cluster: str,
    product_type_group: str,
    matched_scene_strategy_id: str,
    scene_coverage_status: str,
    registry_status: str,
) -> None:
    if cluster not in SCOUTING_CLUSTER_ORDER:
        raise ProductStrategyTaxonomyError("INVALID_STRATEGY_CLUSTER")
    if matched_scene_strategy_id not in SCENE_STRATEGIES:
        raise ProductStrategyTaxonomyError("INVALID_SCENE_STRATEGY_ID")
    if (
        matched_scene_strategy_id == "GENERIC_FALLBACK"
    ) != (scene_coverage_status == "FALLBACK_ONLY"):
        raise ProductStrategyTaxonomyError("INVALID_FALLBACK_SCENE_COVERAGE_BINDING")
    if registry_status == "ACTIVE" and (
        cluster == "generic_unclassified"
        or product_type_group == "unknown_product_type"
        or matched_scene_strategy_id == "GENERIC_FALLBACK"
        or scene_coverage_status == "FALLBACK_ONLY"
    ):
        raise ProductStrategyTaxonomyError(
            "GENERIC_OR_FALLBACK_REGISTRY_PAIR_CANNOT_BE_ACTIVE"
        )


async def register_product_strategy_type(
    request: ProductStrategyTypeRegistrationRequest,
) -> ProductStrategyTypeRegistryEntry:
    """Register one exact pair without changing classifier rules or product rows."""

    if request.cluster == "generic_unclassified":
        raise ProductStrategyTaxonomyError(
            "NEW_PRODUCT_TYPE_REQUIRES_CONCRETE_CLUSTER"
        )
    if request.auto_classification_enabled:
        raise ProductStrategyTaxonomyError(
            "AUTO_CLASSIFICATION_RULE_REQUIRED"
        )
    _validate_registry_binding(
        cluster=request.cluster,
        product_type_group=request.product_type_group,
        matched_scene_strategy_id=request.matched_scene_strategy_id,
        scene_coverage_status=request.scene_coverage_status,
        registry_status=request.registry_status,
    )
    existing = await crud.get_product_strategy_type_registry_entry(
        request.cluster,
        request.product_type_group,
    )
    if existing:
        raise ProductStrategyTaxonomyError(
            "PRODUCT_STRATEGY_TYPE_ALREADY_REGISTERED"
        )
    now = _now()
    row = await crud.create_product_strategy_type_registry_entry(
        {
            **request.model_dump(mode="json"),
            "auto_classification_enabled": int(
                request.auto_classification_enabled
            ),
            "authority_source": "MANUAL_REGISTRATION",
            "reviewed_at": now,
            "updated_at": now,
        }
    )
    return _row_to_registry_entry(row)


async def seed_product_strategy_type_registry(
    request: ProductStrategyTypeRegistrySeedRequest,
) -> ProductStrategyTypeRegistrySeedResponse:
    """Preview by default; apply only behind an exact confirmation token."""

    seed_records = product_strategy_type_registry_seed_entries()
    existing_rows = await crud.list_product_strategy_type_registry()
    existing_by_key = {
        (str(row["cluster"]), str(row["product_type_group"])): row
        for row in existing_rows
    }
    now = _now()
    records_to_write: list[dict[str, object]] = []
    planned_insert_count = 0
    planned_update_count = 0
    preserved_manual_registration_count = 0
    comparable_fields = (
        "display_name",
        "matched_scene_strategy_id",
        "scene_coverage_status",
        "registry_status",
        "auto_classification_enabled",
        "authority_source",
        "reviewer_id",
        "reviewer_note",
    )
    for record in seed_records:
        key = (str(record["cluster"]), str(record["product_type_group"]))
        existing = existing_by_key.get(key)
        if existing:
            if existing.get("authority_source") == "MANUAL_REGISTRATION":
                preserved_manual_registration_count += 1
                continue
            normalized_record = {
                **record,
                "auto_classification_enabled": int(
                    bool(record["auto_classification_enabled"])
                ),
            }
            if all(
                existing.get(field) == normalized_record.get(field)
                for field in comparable_fields
            ):
                continue
            planned_update_count += 1
        else:
            planned_insert_count += 1
        records_to_write.append(
            {
                **record,
                "auto_classification_enabled": int(
                    bool(record["auto_classification_enabled"])
                ),
                "reviewer_id": record.get("reviewer_id"),
                "reviewer_note": record.get("reviewer_note"),
                "reviewed_at": (
                    now if record.get("reviewer_id") is not None else None
                ),
                "updated_at": now,
            }
        )
    response = ProductStrategyTypeRegistrySeedResponse(
        dry_run=True,
        mutation_performed=False,
        seed_count=len(seed_records),
        planned_insert_count=planned_insert_count,
        planned_update_count=planned_update_count,
        unchanged_count=len(seed_records) - len(records_to_write),
        preserved_manual_registration_count=preserved_manual_registration_count,
        active_count=sum(
            record["registry_status"] == "ACTIVE" for record in seed_records
        ),
        review_required_count=sum(
            record["registry_status"] == "REVIEW_REQUIRED"
            for record in seed_records
        ),
        confirmation_required=REGISTRY_SEED_CONFIRMATION,
    )
    if request.dry_run:
        return response
    if request.confirm_apply != REGISTRY_SEED_CONFIRMATION:
        raise ProductStrategyTaxonomyError("REGISTRY_SEED_CONFIRMATION_REQUIRED")
    changed = await crud.seed_product_strategy_type_registry(records_to_write)
    response.dry_run = False
    response.mutation_performed = changed > 0
    response.confirmation_required = None
    return response


async def reconcile_existing_system_product_strategy_type_registry(
) -> ProductStrategyTypeRegistrySeedResponse | None:
    """Refresh an initialized system registry from source authority.

    Fresh databases still require the explicit seed command. Once system seed
    rows exist, startup may safely refresh them because the existing upsert
    preserves every manual registration and is idempotent.
    """

    existing_rows = await crud.list_product_strategy_type_registry()
    if not any(
        row.get("authority_source") == "SYSTEM_SEED"
        for row in existing_rows
    ):
        return None
    return await seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=REGISTRY_SEED_CONFIRMATION,
        )
    )


async def validate_product_strategy_assignment(
    *,
    cluster: str,
    product_type_group: str,
    matched_scene_strategy_id: str,
    scene_coverage_status: str,
    review_status: str,
) -> ProductStrategyTypeRegistryEntry:
    row = await crud.get_product_strategy_type_registry_entry(
        cluster,
        product_type_group,
    )
    if row is None:
        raise ProductStrategyTaxonomyError(
            "UNREGISTERED_PRODUCT_STRATEGY_TYPE"
        )
    entry = _row_to_registry_entry(row)
    if entry.matched_scene_strategy_id != matched_scene_strategy_id:
        raise ProductStrategyTaxonomyError(
            "SCENE_STRATEGY_DOES_NOT_MATCH_REGISTRY"
        )
    if entry.scene_coverage_status != scene_coverage_status:
        raise ProductStrategyTaxonomyError(
            "SCENE_COVERAGE_DOES_NOT_MATCH_REGISTRY"
        )
    if review_status == "VERIFIED" and entry.registry_status != "ACTIVE":
        raise ProductStrategyTaxonomyError(
            "PRODUCT_STRATEGY_TYPE_NOT_ACTIVE"
        )
    return entry


def _read_model_from_row(
    product: Mapping[str, object],
    row: Mapping[str, object] | None,
) -> ProductStrategyTaxonomy:
    if row is None:
        preview = build_product_strategy_taxonomy_candidate(product)
        preview.review_status = "REVIEW_REQUIRED"
        preview.consumer_status = "BLOCKED_REVIEW_REQUIRED"
        preview.review_reasons = _unique(
            [*preview.review_reasons, "NOT_MATERIALIZED"]
        )
        return preview

    taxonomy = _row_to_taxonomy(row)
    current_fingerprint = product_strategy_fingerprint(product)
    if taxonomy.materialization_status == "PLACEHOLDER":
        taxonomy.product_fingerprint = current_fingerprint
        taxonomy.is_stale = False
        taxonomy.review_status = "REVIEW_REQUIRED"
        taxonomy.consumer_status = "BLOCKED_REVIEW_REQUIRED"
        taxonomy.review_reasons = _unique(
            [
                reason
                for reason in taxonomy.review_reasons
                if reason
                not in {
                    "STALE_PRODUCT_FINGERPRINT",
                    "STALE_TAXONOMY_BINDING",
                }
            ]
            + ["NOT_MATERIALIZED"]
        )
    else:
        current_binding = _strategy_binding(product)
        binding_changed = any(
            getattr(taxonomy, field) != value
            for field, value in current_binding.items()
        )
        binding_is_stale = binding_changed and (
            taxonomy.authority_source == "AUTO_DERIVED"
            or resolve_catalog_product_type_truth(product) is not None
        )
        stale_reasons: list[str] = []
        if taxonomy.product_fingerprint != current_fingerprint:
            stale_reasons.append("STALE_PRODUCT_FINGERPRINT")
        if binding_is_stale:
            stale_reasons.append("STALE_TAXONOMY_BINDING")
        if stale_reasons:
            taxonomy.is_stale = True
            taxonomy.review_status = "REVIEW_REQUIRED"
            taxonomy.consumer_status = "BLOCKED_REVIEW_REQUIRED"
            taxonomy.review_reasons = _unique(
                [*taxonomy.review_reasons, *stale_reasons]
            )
    return taxonomy


async def get_product_strategy_taxonomy_read_model(
    product_id: str,
) -> ProductStrategyTaxonomy:
    product = await crud.get_product(product_id)
    if not product:
        raise ProductStrategyTaxonomyError("PRODUCT_NOT_FOUND")
    row = await crud.get_product_strategy_taxonomy(product_id)
    return _read_model_from_row(product, row)


async def require_verified_product_strategy_taxonomy(
    product_id: str,
) -> ProductStrategyTaxonomy:
    """Stable fail-closed read contract reserved for future P3 consumers."""

    taxonomy = await get_product_strategy_taxonomy_read_model(product_id)
    if (
        taxonomy.materialization_status != "MATERIALIZED"
        or taxonomy.review_status != "VERIFIED"
        or taxonomy.consumer_status != "READY"
        or taxonomy.is_stale
    ):
        raise ProductStrategyTaxonomyError("TAXONOMY_NOT_VERIFIED")
    await validate_product_strategy_assignment(
        cluster=taxonomy.cluster,
        product_type_group=taxonomy.product_type_group,
        matched_scene_strategy_id=taxonomy.matched_scene_strategy_id,
        scene_coverage_status=taxonomy.scene_coverage_status,
        review_status=taxonomy.review_status,
    )
    return taxonomy


async def attach_product_strategy_taxonomies(
    products: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach taxonomy read models with one bulk sidecar query."""

    product_ids = [
        str(product.get("id") or product.get("product_id") or "")
        for product in products
    ]
    rows = await crud.list_product_strategy_taxonomies(product_ids)
    stored_products = await crud.list_product_rows_for_strategy_taxonomy(
        product_ids
    )
    by_product_id = {str(row["product_id"]): row for row in rows}
    stored_by_product_id = {
        str(product["id"]): product for product in stored_products
    }
    attached: list[dict[str, object]] = []
    for product in products:
        item = dict(product)
        product_id = str(item.get("id") or item.get("product_id") or "")
        fingerprint_product = stored_by_product_id.get(product_id, item)
        taxonomy = _read_model_from_row(
            fingerprint_product,
            by_product_id.get(product_id),
        )
        item["strategy_taxonomy"] = taxonomy.model_dump(mode="json")
        attached.append(item)
    return attached


async def _build_backfill_plan(
    *,
    limit: int,
) -> tuple[ProductStrategyTaxonomyBackfillResponse, list[dict[str, object]]]:
    products = await crud.list_products(
        limit=limit,
        include_archived=True,
    )
    product_ids = [str(product.get("id") or "") for product in products]
    existing_rows = await crud.list_product_strategy_taxonomies(product_ids)
    existing_by_id = {str(row["product_id"]): row for row in existing_rows}

    planned_insert_count = 0
    planned_update_count = 0
    unchanged_count = 0
    preserved_manual_override_count = 0
    records_to_write: list[dict[str, object]] = []
    final_taxonomies: list[ProductStrategyTaxonomy] = []

    for product in products:
        product_id = str(product.get("id") or "")
        candidate = build_product_strategy_taxonomy_candidate(
            product,
            materialization_status="MATERIALIZED",
        )
        existing_row = existing_by_id.get(product_id)
        if existing_row and existing_row.get("authority_source") == "MANUAL_OVERRIDE":
            preserved_manual_override_count += 1
            final_taxonomies.append(
                _read_model_from_row(product, existing_row)
            )
            continue

        if existing_row is None:
            planned_insert_count += 1
        elif (
            str(existing_row.get("taxonomy_version") or "") == TAXONOMY_VERSION
            and str(existing_row.get("product_fingerprint") or "")
            == candidate.product_fingerprint
            and str(existing_row.get("materialization_status") or "")
            == "MATERIALIZED"
            and str(existing_row.get("cluster") or "") == candidate.cluster
            and str(existing_row.get("product_type_group") or "")
            == candidate.product_type_group
            and str(existing_row.get("matched_scene_strategy_id") or "")
            == candidate.matched_scene_strategy_id
            and str(existing_row.get("scene_coverage_status") or "")
            == candidate.scene_coverage_status
            and bool(existing_row.get("fallback_used"))
            == candidate.fallback_used
            and bool(existing_row.get("specific_strategy"))
            == candidate.specific_strategy
        ):
            unchanged_count += 1
            final_taxonomies.append(_read_model_from_row(product, existing_row))
            continue
        else:
            planned_update_count += 1

        records_to_write.append(_taxonomy_to_record(candidate))
        final_taxonomies.append(candidate)

    coverage_counts = Counter(
        taxonomy.scene_coverage_status for taxonomy in final_taxonomies
    )
    cluster_counts = Counter(taxonomy.cluster for taxonomy in final_taxonomies)
    review_reason_counts: Counter[str] = Counter()
    for taxonomy in final_taxonomies:
        review_reason_counts.update(taxonomy.review_reasons)

    response = ProductStrategyTaxonomyBackfillResponse(
        dry_run=True,
        mutation_performed=False,
        product_count=len(products),
        planned_insert_count=planned_insert_count,
        planned_update_count=planned_update_count,
        unchanged_count=unchanged_count,
        preserved_manual_override_count=preserved_manual_override_count,
        verified_count=sum(
            taxonomy.review_status == "VERIFIED" for taxonomy in final_taxonomies
        ),
        review_required_count=sum(
            taxonomy.review_status == "REVIEW_REQUIRED"
            for taxonomy in final_taxonomies
        ),
        coverage_counts=dict(sorted(coverage_counts.items())),
        cluster_counts=dict(sorted(cluster_counts.items())),
        review_reason_counts=dict(sorted(review_reason_counts.items())),
        sample_review_required=[
            taxonomy
            for taxonomy in final_taxonomies
            if taxonomy.review_status == "REVIEW_REQUIRED"
        ][:20],
        confirmation_required=BACKFILL_CONFIRMATION,
    )
    return response, records_to_write


async def run_product_strategy_taxonomy_backfill(
    request: ProductStrategyTaxonomyBackfillRequest,
) -> ProductStrategyTaxonomyBackfillResponse:
    """Preview by default; apply only behind an exact confirmation token."""

    response, records_to_write = await _build_backfill_plan(limit=request.limit)
    if request.dry_run:
        return response
    if request.confirm_apply != BACKFILL_CONFIRMATION:
        raise ProductStrategyTaxonomyError("BACKFILL_CONFIRMATION_REQUIRED")

    await crud.materialize_product_strategy_taxonomies(records_to_write)
    response.dry_run = False
    response.mutation_performed = bool(records_to_write)
    response.confirmation_required = None
    return response


async def review_product_strategy_taxonomy(
    product_id: str,
    request: ProductStrategyTaxonomyReviewRequest,
) -> ProductStrategyTaxonomy:
    """Apply an explicit admin review without permitting later auto-overwrite."""

    product = await crud.get_product(product_id)
    if not product:
        raise ProductStrategyTaxonomyError("PRODUCT_NOT_FOUND")
    current_fingerprint = product_strategy_fingerprint(product)
    if request.expected_product_fingerprint != current_fingerprint:
        raise ProductStrategyTaxonomyError("STALE_PRODUCT_FINGERPRINT")
    await validate_product_strategy_assignment(
        cluster=request.cluster,
        product_type_group=request.product_type_group,
        matched_scene_strategy_id=request.matched_scene_strategy_id,
        scene_coverage_status=request.scene_coverage_status,
        review_status=request.review_status,
    )
    if request.review_status == "VERIFIED" and (
        request.cluster == "generic_unclassified"
        or request.product_type_group == "unknown_product_type"
        or request.matched_scene_strategy_id == "GENERIC_FALLBACK"
        or request.scene_coverage_status == "FALLBACK_ONLY"
    ):
        raise ProductStrategyTaxonomyError(
            "GENERIC_OR_FALLBACK_TAXONOMY_CANNOT_BE_VERIFIED"
        )

    current_candidate = build_product_strategy_taxonomy_candidate(
        product,
        materialization_status="MATERIALIZED",
    )
    now = _now()
    reviewed = ProductStrategyTaxonomy.model_validate(
        {
            **current_candidate.model_dump(),
            "cluster": request.cluster,
            "product_type_group": request.product_type_group,
            "matched_scene_strategy_id": request.matched_scene_strategy_id,
            "scene_coverage_status": request.scene_coverage_status,
            "fallback_used": request.scene_coverage_status == "FALLBACK_ONLY",
            "specific_strategy": request.scene_coverage_status == "COVERED",
            "review_status": request.review_status,
            "consumer_status": (
                "READY"
                if request.review_status == "VERIFIED"
                else "BLOCKED_REVIEW_REQUIRED"
            ),
            "authority_source": "MANUAL_OVERRIDE",
            "review_reasons": (
                []
                if request.review_status == "VERIFIED"
                else ["MANUAL_REVIEW_REQUIRED"]
            ),
            "reviewer_id": request.reviewer_id,
            "reviewer_note": request.reviewer_note,
            "reviewed_at": now,
            "updated_at": now,
        }
    )
    row = await crud.upsert_manual_product_strategy_taxonomy(
        _taxonomy_to_record(reviewed)
    )
    return _row_to_taxonomy(row)
