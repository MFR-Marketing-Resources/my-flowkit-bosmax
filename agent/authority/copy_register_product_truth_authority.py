"""Canonical Product Truth authority contract for Copy Register V2.

The Copy Register consumes several independent authorities.  This module keeps
their meanings separate and provides one deterministic fingerprint for the
values that a V2 blueprint or binding is allowed to consume.

``product.silo`` is intentionally not part of the copywriting taxonomy or the
fingerprint.  The current product-mapping profile is a legacy visual/internal
route with no independently verified visual-silo registry, so it is exposed as
forensic metadata only.

Precedence is explicit: the active copywriting taxonomy registry owns the
category/subcategory/type/product-type-code/copy-cluster fields; the reviewed,
materialized product-strategy row owns strategy lineage; the BOSMAX resolver
owns the broad family dimension; and the stored mapping-rule silo is never a
Copy Register cluster authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.copywriting_taxonomy_service import canonical_category
from agent.services.product_strategy_taxonomy_service import product_strategy_fingerprint


COPY_REGISTER_AUTHORITY_VERSION = "copy-register-product-truth-authority-v1"
NO_CANONICAL_VISUAL_SILO_AUTHORITY = "NO_CANONICAL_VISUAL_SILO_AUTHORITY"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalized_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _text(value).casefold()).strip("_")


def _row_value(row: Mapping[str, Any] | None, key: str) -> Any:
    return row.get(key) if row is not None else None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CopyRegisterProductTruthAuthority:
    """Read-only resolved authority envelope used by Product Truth V2."""

    authority_version: str
    canonical_category: str
    canonical_subcategory: str
    canonical_type: str
    canonical_product_type_code: str
    canonical_copy_cluster: str
    copywriting_authority_version: str
    copywriting_source_sha256: str
    strategy_taxonomy_version: str
    strategy_taxonomy_fingerprint: str
    strategy_current_product_fingerprint: str
    strategy_cluster: str
    strategy_product_type_group: str
    strategy_scene_strategy_id: str
    strategy_review_status: str
    strategy_consumer_status: str
    strategy_materialization_status: str
    strategy_authority_source: str
    bosmax_product_family: str
    bosmax_product_family_reason: str
    visual_internal_silo: str
    visual_internal_silo_source: str
    visual_internal_silo_status: str
    authority_fingerprint: str | None
    copywriting_taxonomy_status: str
    strategy_taxonomy_status: str
    family_status: str
    blockers: tuple[str, ...]
    blocker_details: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    @property
    def ready_for_copy(self) -> bool:
        return not self.blockers

    def model_dump(self) -> dict[str, Any]:
        """Return an API-safe, semantically grouped representation."""

        return {
            "authority_version": self.authority_version,
            "authority_fingerprint": self.authority_fingerprint,
            "status": "COHERENT" if self.ready_for_copy else "BLOCKED",
            "canonical_taxonomy": {
                "category": self.canonical_category,
                "subcategory": self.canonical_subcategory,
                "type": self.canonical_type,
                "product_type_code": self.canonical_product_type_code,
                "copy_cluster": self.canonical_copy_cluster,
                "registry_authority_version": self.copywriting_authority_version,
                "registry_source_sha256": self.copywriting_source_sha256,
                "status": self.copywriting_taxonomy_status,
            },
            "strategy_taxonomy": {
                "taxonomy_version": self.strategy_taxonomy_version,
                "fingerprint": self.strategy_taxonomy_fingerprint,
                "current_product_fingerprint": self.strategy_current_product_fingerprint,
                "cluster": self.strategy_cluster,
                "product_type_group": self.strategy_product_type_group,
                "matched_scene_strategy_id": self.strategy_scene_strategy_id,
                "review_status": self.strategy_review_status,
                "consumer_status": self.strategy_consumer_status,
                "materialization_status": self.strategy_materialization_status,
                "authority_source": self.strategy_authority_source,
                "status": self.strategy_taxonomy_status,
            },
            "bosmax_family": {
                "value": self.bosmax_product_family,
                "reason": self.bosmax_product_family_reason,
                "status": self.family_status,
            },
            "visual_internal_silo": {
                "value": self.visual_internal_silo,
                "source": self.visual_internal_silo_source,
                "status": self.visual_internal_silo_status,
                "canonical_copy_cluster": False,
            },
            "blockers": list(self.blockers),
            "blocker_details": list(self.blocker_details),
            "warnings": list(self.warnings),
        }


def build_copy_register_product_truth_authority(
    product: Mapping[str, Any],
    *,
    copywriting_registry_row: Mapping[str, Any] | None,
    strategy_taxonomy_row: Mapping[str, Any] | None,
) -> CopyRegisterProductTruthAuthority:
    """Resolve current canonical authorities without writing or normalizing data."""

    code = _text(
        product.get("copywriting_product_type_code")
        or product.get("product_type_code")
        or product.get("type_code")
    )
    registry_code = _text(_row_value(copywriting_registry_row, "product_type_code"))
    registry_category = _text(_row_value(copywriting_registry_row, "category"))
    registry_subcategory = _text(_row_value(copywriting_registry_row, "subcategory"))
    registry_type = _text(_row_value(copywriting_registry_row, "type"))
    registry_cluster = _text(_row_value(copywriting_registry_row, "cluster_name"))

    canonical_fields = {
        "category": canonical_category(product.get("category")),
        "subcategory": _text(product.get("subcategory")),
        "type": _text(product.get("type")),
        "product_type_code": code,
    }
    taxonomy_blockers: list[str] = []
    taxonomy_details: list[dict[str, Any]] = []
    if not code or copywriting_registry_row is None:
        taxonomy_blockers.append("V2_PRODUCT_TRUTH_TAXONOMY_AUTHORITY_UNRESOLVED")
        taxonomy_details.append(
            {
                "code": "V2_PRODUCT_TRUTH_TAXONOMY_AUTHORITY_UNRESOLVED",
                "product_type_code": code or None,
                "reason": "No active copywriting taxonomy registry row resolved for the stored product type code.",
            }
        )
        taxonomy_status = "UNRESOLVED"
    else:
        expected = {
            "category": canonical_category(registry_category),
            "subcategory": registry_subcategory,
            "type": registry_type,
            "product_type_code": registry_code,
        }
        for field, observed in canonical_fields.items():
            if observed != expected[field]:
                taxonomy_details.append(
                    {
                        "code": "V2_PRODUCT_TRUTH_TAXONOMY_DRIFT",
                        "field": field,
                        "observed": observed,
                        "expected": expected[field],
                    }
                )
        stored_angle = _text(product.get("copywriting_angle"))
        expected_angle = _text(_row_value(copywriting_registry_row, "copywriting_angle"))
        if stored_angle and expected_angle and stored_angle != expected_angle:
            taxonomy_details.append(
                {
                    "code": "V2_PRODUCT_TRUTH_TAXONOMY_DRIFT",
                    "field": "copywriting_angle",
                    "observed": stored_angle,
                    "expected": expected_angle,
                }
            )
        if taxonomy_details:
            taxonomy_blockers.append("V2_PRODUCT_TRUTH_TAXONOMY_DRIFT")
            taxonomy_status = "DRIFT"
        else:
            taxonomy_status = "EXACT"

    observed_cluster = _text(
        product.get("copywriting_cluster")
        or product.get("cluster_name")
        or product.get("cluster")
    )
    if observed_cluster and registry_cluster and _normalized_token(observed_cluster) != _normalized_token(registry_cluster):
        taxonomy_blockers.append("V2_PRODUCT_TRUTH_CLUSTER_DRIFT")
        taxonomy_details.append(
            {
                "code": "V2_PRODUCT_TRUTH_CLUSTER_DRIFT",
                "field": "copywriting_cluster",
                "observed": observed_cluster,
                "expected": registry_cluster,
            }
        )

    strategy_fingerprint_raw = _text(_row_value(strategy_taxonomy_row, "product_fingerprint"))
    strategy_fingerprint = (
        strategy_fingerprint_raw
        if re.fullmatch(r"[0-9a-f]{64}", strategy_fingerprint_raw)
        else ""
    )
    current_strategy_fingerprint = product_strategy_fingerprint(dict(product))
    strategy_cluster = _text(_row_value(strategy_taxonomy_row, "cluster"))
    strategy_status = "EXACT"
    strategy_details: list[dict[str, Any]] = []
    if strategy_taxonomy_row is None:
        strategy_status = "UNRESOLVED"
        strategy_details.append(
            {
                "code": "V2_PRODUCT_TRUTH_STRATEGY_AUTHORITY_STALE",
                "reason": "No product strategy taxonomy row is materialized for this product.",
            }
        )
    else:
        required_strategy_values = {
            "materialization_status": "MATERIALIZED",
            "review_status": "VERIFIED",
            "consumer_status": "READY",
            "authority_source": "MANUAL_OVERRIDE",
        }
        for field, expected_value in required_strategy_values.items():
            observed_value = _text(_row_value(strategy_taxonomy_row, field))
            if observed_value != expected_value:
                strategy_details.append(
                    {
                        "code": "V2_PRODUCT_TRUTH_STRATEGY_AUTHORITY_STALE",
                        "field": field,
                        "observed": observed_value,
                        "expected": expected_value,
                    }
                )
        if not strategy_fingerprint or strategy_fingerprint != current_strategy_fingerprint:
            strategy_details.append(
                {
                    "code": "V2_PRODUCT_TRUTH_STRATEGY_AUTHORITY_STALE",
                    "field": "product_fingerprint",
                    "observed": strategy_fingerprint or None,
                    "expected": current_strategy_fingerprint,
                }
            )
        if registry_cluster and strategy_cluster and _normalized_token(strategy_cluster) != _normalized_token(registry_cluster):
            strategy_details.append(
                {
                    "code": "V2_PRODUCT_TRUTH_CLUSTER_DRIFT",
                    "field": "strategy_cluster",
                    "observed": strategy_cluster,
                    "expected": registry_cluster,
                }
            )
        if strategy_details:
            strategy_status = "STALE"

    family_resolution = derive_bosmax_product_family(dict(product))
    derived_family = _text(family_resolution.get("bosmax_product_family"))
    stored_family = _text(product.get("bosmax_product_family"))
    family = stored_family or derived_family
    family_status = "EXACT" if not stored_family or stored_family == derived_family else "DRIFT"
    family_details: list[dict[str, Any]] = []
    if stored_family and derived_family not in {"", "GENERIC_UNCLASSIFIED", stored_family}:
        family_details.append(
            {
                "code": "V2_PRODUCT_TRUTH_FAMILY_DRIFT",
                "field": "bosmax_product_family",
                "observed": stored_family,
                "expected": derived_family,
            }
        )

    blockers = list(dict.fromkeys([*taxonomy_blockers, *[item["code"] for item in strategy_details], *[item["code"] for item in family_details]]))
    blocker_details = tuple([*taxonomy_details, *strategy_details, *family_details])
    visual_silo = _text(product.get("silo"))
    warnings = (NO_CANONICAL_VISUAL_SILO_AUTHORITY,) if visual_silo else ()

    fingerprint_payload = {
        "authority_version": COPY_REGISTER_AUTHORITY_VERSION,
        "copywriting_taxonomy": {
            "authority_version": _text(_row_value(copywriting_registry_row, "authority_version")),
            "source_sha256": _text(_row_value(copywriting_registry_row, "source_sha256")),
            "category": registry_category,
            "subcategory": registry_subcategory,
            "type": registry_type,
            "product_type_code": registry_code,
            "cluster": registry_cluster,
        },
        "observed_product_copy_taxonomy": canonical_fields,
        "strategy_taxonomy": {
            "taxonomy_version": _text(_row_value(strategy_taxonomy_row, "taxonomy_version")),
            "product_fingerprint": strategy_fingerprint,
            "current_product_fingerprint": current_strategy_fingerprint,
            "cluster": strategy_cluster,
            "product_type_group": _text(_row_value(strategy_taxonomy_row, "product_type_group")),
            "matched_scene_strategy_id": _text(_row_value(strategy_taxonomy_row, "matched_scene_strategy_id")),
            "scene_coverage_status": _text(_row_value(strategy_taxonomy_row, "scene_coverage_status")),
            "review_status": _text(_row_value(strategy_taxonomy_row, "review_status")),
            "consumer_status": _text(_row_value(strategy_taxonomy_row, "consumer_status")),
            "materialization_status": _text(_row_value(strategy_taxonomy_row, "materialization_status")),
            "authority_source": _text(_row_value(strategy_taxonomy_row, "authority_source")),
        },
        "bosmax_family": {
            "stored": stored_family,
            "derived": derived_family,
        },
    }
    authority_fingerprint = _sha256(fingerprint_payload) if copywriting_registry_row and strategy_taxonomy_row else None

    return CopyRegisterProductTruthAuthority(
        authority_version=COPY_REGISTER_AUTHORITY_VERSION,
        canonical_category=registry_category,
        canonical_subcategory=registry_subcategory,
        canonical_type=registry_type,
        canonical_product_type_code=registry_code,
        canonical_copy_cluster=registry_cluster,
        copywriting_authority_version=_text(_row_value(copywriting_registry_row, "authority_version")),
        copywriting_source_sha256=_text(_row_value(copywriting_registry_row, "source_sha256")),
        strategy_taxonomy_version=_text(_row_value(strategy_taxonomy_row, "taxonomy_version")),
        strategy_taxonomy_fingerprint=strategy_fingerprint,
        strategy_current_product_fingerprint=current_strategy_fingerprint,
        strategy_cluster=strategy_cluster,
        strategy_product_type_group=_text(_row_value(strategy_taxonomy_row, "product_type_group")),
        strategy_scene_strategy_id=_text(_row_value(strategy_taxonomy_row, "matched_scene_strategy_id")),
        strategy_review_status=_text(_row_value(strategy_taxonomy_row, "review_status")),
        strategy_consumer_status=_text(_row_value(strategy_taxonomy_row, "consumer_status")),
        strategy_materialization_status=_text(_row_value(strategy_taxonomy_row, "materialization_status")),
        strategy_authority_source=_text(_row_value(strategy_taxonomy_row, "authority_source")),
        bosmax_product_family=family,
        bosmax_product_family_reason=_text(
            product.get("bosmax_product_family_reason")
            or family_resolution.get("bosmax_product_family_reason")
        ),
        visual_internal_silo=visual_silo,
        visual_internal_silo_source="legacy_product_mapping_rules" if visual_silo else "NOT_SET",
        visual_internal_silo_status="LEGACY_UNVERIFIED" if visual_silo else "NOT_SET",
        authority_fingerprint=authority_fingerprint,
        copywriting_taxonomy_status=taxonomy_status,
        strategy_taxonomy_status=strategy_status,
        family_status=family_status,
        blockers=tuple(blockers),
        blocker_details=blocker_details,
        warnings=warnings,
    )


__all__ = [
    "COPY_REGISTER_AUTHORITY_VERSION",
    "NO_CANONICAL_VISUAL_SILO_AUTHORITY",
    "CopyRegisterProductTruthAuthority",
    "build_copy_register_product_truth_authority",
]
