"""Single-transaction P5.8 registry and taxonomy authority application."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.authority.catalog_product_type_truth import (
    P58_INSUFFICIENT_PRODUCT_TRUTH_REASONS,
    P58_PRODUCT_AUTHORITY_BLOCKERS,
    resolve_catalog_product_type_truth,
)
from agent.authority.product_type_copy_strategy_registry import (
    PRODUCT_TYPE_COPY_STRATEGY_KEYS,
)
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.services.product_strategy_scouting_service import (
    product_strategy_type_registry_seed_entries,
)
from agent.services.product_strategy_taxonomy_service import (
    build_product_strategy_taxonomy_candidate,
)


P58_APPLY_CONFIRMATION = "APPLY_P58_FINAL_CATALOG_AUTHORITY"
P58_APPLY_REVIEWER_ID = "owner-mission:P5.8"
P58_APPLY_REVIEWER_NOTE = (
    "Exact source taxonomy or explicit approved Product Truth decision "
    "reviewed under "
    "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
)

_REGISTRY_COLUMNS = (
    "cluster",
    "product_type_group",
    "display_name",
    "matched_scene_strategy_id",
    "scene_coverage_status",
    "registry_status",
    "auto_classification_enabled",
    "authority_source",
    "reviewer_id",
    "reviewer_note",
    "reviewed_at",
    "updated_at",
)
_TAXONOMY_COLUMNS = (
    "product_id",
    "taxonomy_version",
    "product_fingerprint",
    "cluster",
    "product_type_group",
    "matched_scene_strategy_id",
    "scene_coverage_status",
    "fallback_used",
    "specific_strategy",
    "classification_confidence",
    "review_status",
    "consumer_status",
    "authority_source",
    "materialization_status",
    "review_reasons_json",
    "reviewer_id",
    "reviewer_note",
    "derived_at",
    "reviewed_at",
    "updated_at",
)
_REGISTRY_COMPARE_COLUMNS = tuple(
    column for column in _REGISTRY_COLUMNS if column not in {"reviewed_at", "updated_at"}
)
_TAXONOMY_COMPARE_COLUMNS = tuple(
    column
    for column in _TAXONOMY_COLUMNS
    if column not in {"derived_at", "reviewed_at", "updated_at"}
)
_MUTABLE_AUTHORITY_TABLES = {
    "product_strategy_type_registry",
    "product_strategy_taxonomy",
}


class CatalogAuthorityApplyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["DRY_RUN", "APPLY"]
    mutation_performed: bool
    database_path: str
    product_count: int = Field(ge=0)
    registry_insert_count: int = Field(ge=0)
    registry_update_count: int = Field(ge=0)
    registry_unchanged_count: int = Field(ge=0)
    registry_manual_preserved_count: int = Field(ge=0)
    taxonomy_insert_count: int = Field(ge=0)
    taxonomy_update_count: int = Field(ge=0)
    taxonomy_unchanged_count: int = Field(ge=0)
    taxonomy_manual_preserved_count: int = Field(ge=0)
    taxonomy_verified_count: int = Field(ge=0)
    taxonomy_review_required_count: int = Field(ge=0)
    state_fingerprint_before: str = Field(pattern=r"^[a-f0-9]{64}$")
    state_fingerprint_after: str = Field(pattern=r"^[a-f0-9]{64}$")
    protected_state_fingerprint_before: str = Field(
        pattern=r"^[a-f0-9]{64}$"
    )
    protected_state_fingerprint_after: str = Field(
        pattern=r"^[a-f0-9]{64}$"
    )
    integrity_check: Literal["ok"]
    confirmation_required: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rows(
    connection: sqlite3.Connection,
    query: str,
) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(query).fetchall()]


def _state_fingerprint(connection: sqlite3.Connection) -> str:
    payload = {
        "registry": _rows(
            connection,
            "SELECT * FROM product_strategy_type_registry "
            "ORDER BY cluster, product_type_group",
        ),
        "taxonomy": _rows(
            connection,
            "SELECT * FROM product_strategy_taxonomy ORDER BY product_id",
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _protected_state_fingerprint(connection: sqlite3.Connection) -> str:
    """Hash every table outside the two authorized authority targets."""

    digest = hashlib.sha256()
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if str(row[0]) not in _MUTABLE_AUTHORITY_TABLES
    ]
    for table in tables:
        quoted_table = table.replace('"', '""')
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        digest.update(table.encode("utf-8"))
        digest.update(str(schema[0] if schema else "").encode("utf-8"))
        for row in connection.execute(f'SELECT * FROM "{quoted_table}"'):
            for value in row:
                if value is None:
                    encoded = b"null"
                elif isinstance(value, bytes):
                    encoded = value
                else:
                    encoded = str(value).encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
    return digest.hexdigest()


def _comparable(
    record: dict[str, object],
    columns: tuple[str, ...],
) -> tuple[object, ...]:
    return tuple(record.get(column) for column in columns)


def _taxonomy_record(taxonomy: ProductStrategyTaxonomy) -> dict[str, object]:
    payload = taxonomy.model_dump(mode="json")
    payload["fallback_used"] = int(taxonomy.fallback_used)
    payload["specific_strategy"] = int(taxonomy.specific_strategy)
    payload["review_reasons_json"] = json.dumps(
        taxonomy.review_reasons,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload.pop("review_reasons", None)
    payload.pop("created_at", None)
    payload.pop("is_stale", None)
    return payload


def _verified_taxonomy(
    product: dict[str, object],
    candidate: ProductStrategyTaxonomy,
    now: str,
) -> ProductStrategyTaxonomy:
    truth_mapping = resolve_catalog_product_type_truth(product)
    if truth_mapping is None or truth_mapping.specific_scene_strategy_id is None:
        raise RuntimeError("P58_VERIFIED_TAXONOMY_REQUIRES_PRODUCT_TRUTH")
    return ProductStrategyTaxonomy.model_validate(
        {
            **candidate.model_dump(mode="json"),
            "cluster": truth_mapping.cluster,
            "product_type_group": truth_mapping.product_type_group,
            "matched_scene_strategy_id": truth_mapping.specific_scene_strategy_id,
            "scene_coverage_status": "COVERED",
            "fallback_used": False,
            "specific_strategy": True,
            "review_status": "VERIFIED",
            "consumer_status": "READY",
            "authority_source": "MANUAL_OVERRIDE",
            "materialization_status": "MATERIALIZED",
            "review_reasons": [],
            "reviewer_id": P58_APPLY_REVIEWER_ID,
            "reviewer_note": P58_APPLY_REVIEWER_NOTE,
            "reviewed_at": now,
            "updated_at": now,
        }
    )


def _build_registry_plan(
    existing_rows: list[dict[str, object]],
    now: str,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    existing_by_key = {
        (str(row["cluster"]), str(row["product_type_group"])): row
        for row in existing_rows
    }
    writes: list[dict[str, object]] = []
    counts = {"insert": 0, "update": 0, "unchanged": 0, "manual_preserved": 0}
    for seed in product_strategy_type_registry_seed_entries():
        key = (str(seed["cluster"]), str(seed["product_type_group"]))
        existing = existing_by_key.get(key)
        if existing and existing.get("authority_source") == "MANUAL_REGISTRATION":
            counts["manual_preserved"] += 1
            continue
        record = {
            **seed,
            "auto_classification_enabled": int(
                bool(seed["auto_classification_enabled"])
            ),
            "reviewed_at": (
                now if seed.get("reviewer_id") is not None else None
            ),
            "updated_at": now,
        }
        if existing is None:
            counts["insert"] += 1
            writes.append(record)
        elif _comparable(existing, _REGISTRY_COMPARE_COLUMNS) == _comparable(
            record, _REGISTRY_COMPARE_COLUMNS
        ):
            counts["unchanged"] += 1
        else:
            counts["update"] += 1
            writes.append(record)
    return writes, counts


def _build_taxonomy_plan(
    products: list[dict[str, object]],
    existing_rows: list[dict[str, object]],
    now: str,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    existing_by_id = {str(row["product_id"]): row for row in existing_rows}
    writes: list[dict[str, object]] = []
    counts = {
        "insert": 0,
        "update": 0,
        "unchanged": 0,
        "manual_preserved": 0,
        "verified": 0,
        "review_required": 0,
    }
    for product in products:
        product_id = str(product["id"])
        lifecycle_status = str(
            product.get("lifecycle_status") or "ACTIVE"
        ).upper()
        existing = existing_by_id.get(product_id)
        candidate = build_product_strategy_taxonomy_candidate(
            product,
            materialization_status="MATERIALIZED",
        )
        truth_mapping = resolve_catalog_product_type_truth(product)
        eligible_for_review = bool(
            lifecycle_status == "ACTIVE"
            and truth_mapping is not None
            and truth_mapping.specific_scene_strategy_id is not None
            and (
                truth_mapping.cluster,
                truth_mapping.product_type_group,
                truth_mapping.specific_scene_strategy_id,
            )
            in PRODUCT_TYPE_COPY_STRATEGY_KEYS
            and product_id not in P58_INSUFFICIENT_PRODUCT_TRUTH_REASONS
            and product_id not in P58_PRODUCT_AUTHORITY_BLOCKERS
        )
        if eligible_for_review:
            desired = _taxonomy_record(
                _verified_taxonomy(product, candidate, now)
            )
        elif existing and existing.get("authority_source") == "MANUAL_OVERRIDE":
            counts["manual_preserved"] += 1
            if str(existing.get("review_status")) == "VERIFIED":
                counts["verified"] += 1
            else:
                counts["review_required"] += 1
            continue
        else:
            desired = _taxonomy_record(candidate)

        if desired["review_status"] == "VERIFIED":
            counts["verified"] += 1
        else:
            counts["review_required"] += 1
        if existing is None:
            counts["insert"] += 1
            writes.append(desired)
        elif _comparable(existing, _TAXONOMY_COMPARE_COLUMNS) == _comparable(
            desired, _TAXONOMY_COMPARE_COLUMNS
        ):
            counts["unchanged"] += 1
        else:
            counts["update"] += 1
            writes.append(desired)
    return writes, counts


def apply_catalog_authority(
    database_path: Path,
    *,
    expected_product_count: int,
    apply: bool = False,
    confirmation: str | None = None,
    canonical_database_path: Path | None = None,
    allow_canonical: bool = False,
) -> CatalogAuthorityApplyResult:
    """Plan or transactionally apply the full registry and taxonomy authority."""

    resolved_path = database_path.resolve()
    if canonical_database_path is not None:
        resolved_canonical = canonical_database_path.resolve()
        if (
            apply
            and resolved_path == resolved_canonical
            and not allow_canonical
        ):
            raise RuntimeError("P58_CANONICAL_DATABASE_APPLY_NOT_AUTHORIZED")
    if apply and confirmation != P58_APPLY_CONFIRMATION:
        raise RuntimeError("P58_APPLY_CONFIRMATION_REQUIRED")
    if not resolved_path.is_file():
        raise FileNotFoundError(resolved_path)

    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"P58_DATABASE_INTEGRITY_FAILED:{integrity}")
        product_count = int(
            connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        )
        if product_count != expected_product_count:
            raise RuntimeError(
                f"P58_PRODUCT_COUNT_MISMATCH:{product_count}:"
                f"{expected_product_count}"
            )
        before = _state_fingerprint(connection)
        protected_before = _protected_state_fingerprint(connection)
        products = _rows(connection, "SELECT * FROM product ORDER BY id")
        registry_existing = _rows(
            connection,
            "SELECT * FROM product_strategy_type_registry "
            "ORDER BY cluster, product_type_group",
        )
        taxonomy_existing = _rows(
            connection,
            "SELECT * FROM product_strategy_taxonomy ORDER BY product_id",
        )
        now = _now()
        registry_writes, registry_counts = _build_registry_plan(
            registry_existing, now
        )
        taxonomy_writes, taxonomy_counts = _build_taxonomy_plan(
            products, taxonomy_existing, now
        )

        if apply and (registry_writes or taxonomy_writes):
            registry_placeholders = ", ".join("?" for _ in _REGISTRY_COLUMNS)
            registry_updates = ", ".join(
                f"{column}=excluded.{column}"
                for column in _REGISTRY_COLUMNS
                if column not in {"cluster", "product_type_group", "authority_source"}
            )
            taxonomy_placeholders = ", ".join("?" for _ in _TAXONOMY_COLUMNS)
            taxonomy_updates = ", ".join(
                f"{column}=excluded.{column}"
                for column in _TAXONOMY_COLUMNS
                if column != "product_id"
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                if _state_fingerprint(connection) != before:
                    raise RuntimeError("P58_CONCURRENT_AUTHORITY_CHANGE_DETECTED")
                if (
                    _protected_state_fingerprint(connection)
                    != protected_before
                ):
                    raise RuntimeError("P58_CONCURRENT_PROTECTED_CHANGE_DETECTED")
                for record in registry_writes:
                    connection.execute(
                        "INSERT INTO product_strategy_type_registry "
                        f"({', '.join(_REGISTRY_COLUMNS)}) "
                        f"VALUES ({registry_placeholders}) "
                        "ON CONFLICT(cluster, product_type_group) DO UPDATE SET "
                        f"{registry_updates} "
                        "WHERE product_strategy_type_registry."
                        "authority_source='SYSTEM_SEED'",
                        [record.get(column) for column in _REGISTRY_COLUMNS],
                    )
                for record in taxonomy_writes:
                    connection.execute(
                        "INSERT INTO product_strategy_taxonomy "
                        f"({', '.join(_TAXONOMY_COLUMNS)}) "
                        f"VALUES ({taxonomy_placeholders}) "
                        "ON CONFLICT(product_id) DO UPDATE SET "
                        f"{taxonomy_updates}",
                        [record.get(column) for column in _TAXONOMY_COLUMNS],
                    )
                protected_after = _protected_state_fingerprint(connection)
                if protected_after != protected_before:
                    raise RuntimeError("P58_PROTECTED_STATE_MUTATION_DETECTED")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        else:
            protected_after = _protected_state_fingerprint(connection)
        after = _state_fingerprint(connection)
        mutation_performed = before != after
        if not apply and mutation_performed:
            raise RuntimeError("P58_DRY_RUN_MUTATED_DATABASE")
        return CatalogAuthorityApplyResult(
            mode="APPLY" if apply else "DRY_RUN",
            mutation_performed=mutation_performed,
            database_path=str(resolved_path),
            product_count=product_count,
            registry_insert_count=registry_counts["insert"],
            registry_update_count=registry_counts["update"],
            registry_unchanged_count=registry_counts["unchanged"],
            registry_manual_preserved_count=registry_counts[
                "manual_preserved"
            ],
            taxonomy_insert_count=taxonomy_counts["insert"],
            taxonomy_update_count=taxonomy_counts["update"],
            taxonomy_unchanged_count=taxonomy_counts["unchanged"],
            taxonomy_manual_preserved_count=taxonomy_counts[
                "manual_preserved"
            ],
            taxonomy_verified_count=taxonomy_counts["verified"],
            taxonomy_review_required_count=taxonomy_counts["review_required"],
            state_fingerprint_before=before,
            state_fingerprint_after=after,
            protected_state_fingerprint_before=protected_before,
            protected_state_fingerprint_after=protected_after,
            integrity_check="ok",
            confirmation_required=(None if apply else P58_APPLY_CONFIRMATION),
        )
    finally:
        connection.close()


__all__ = [
    "CatalogAuthorityApplyResult",
    "P58_APPLY_CONFIRMATION",
    "apply_catalog_authority",
]
