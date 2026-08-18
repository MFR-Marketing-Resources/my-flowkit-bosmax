"""Canonical Product Truth -> EvidenceFact derivation (shared, pure seam).

This is the SINGLE source of truth for turning an APPROVED Product Truth snapshot
into its deterministic current EvidenceFact set. Both the Copy Register V2 authority
path (`copy_register_v2_service._fact_candidates`) and the Storyboard Landbank V3
read model (`ProductTruthEvidenceAdapter.current`) consume this same function, so the
two subsystems can never drift on the fact-generation contract.

Hard rules:
- Provider-free and I/O-free: takes already-loaded ``product`` and ``snapshot``
  dicts and returns EvidenceFact objects. No DB, no network, no mutation.
- Deterministic: identical inputs -> identical fact_id / fact_kind / text /
  text_digest / snapshot_id / snapshot_version / snapshot_status / approved /
  source_ref / ordering.
- Behavior-preserving: this is a verbatim extraction of the pre-existing V2
  ``_fact_candidates`` derivation, NOT a redesign. Do not "improve" the shapes
  here without re-proving V2<->V3 parity and V2 authority behavior.
"""

from __future__ import annotations

import json
from typing import Any

from agent.models.copy_blueprint_v2 import EvidenceFact, digest_evidence_text


def _loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return value


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_list(value: Any) -> list[str]:
    parsed = _loads(value, value if isinstance(value, list) else [])
    if not isinstance(parsed, list):
        return []
    return [_clean(item) for item in parsed if _clean(item)]


def derive_product_truth_evidence_facts(
    product: dict[str, Any], snapshot: dict[str, Any]
) -> list[EvidenceFact]:
    """Derive the canonical current EvidenceFact set from an approved snapshot.

    Verbatim extraction of the V2 ``_fact_candidates`` derivation. The caller owns
    loading ``product`` and ``snapshot``; this function performs zero I/O.
    """
    product_id = str(product["id"])
    snapshot_id = str(snapshot["snapshot_id"])
    version = int(snapshot["version"])
    specs: list[tuple[str, str, Any]] = [
        ("product_description", "PRODUCT_DESCRIPTION", snapshot.get("product_description")),
        ("benefits_json", "BENEFIT", _parse_list(snapshot.get("benefits_json"))),
        ("usp_json", "USP", _parse_list(snapshot.get("usp_json"))),
        ("allowed_claims_json", "ALLOWED_CLAIM", _parse_list(snapshot.get("allowed_claims_json"))),
        ("target_customer_text", "TARGET_CUSTOMER", snapshot.get("target_customer_text")),
        ("pain_points_json", "PAIN_POINT", _parse_list(snapshot.get("pain_points_json"))),
        ("usage_text", "USAGE", snapshot.get("usage_text")),
    ]
    facts: list[EvidenceFact] = []
    for field_name, fact_kind, raw in specs:
        values = raw if isinstance(raw, list) else [raw]
        for index, value in enumerate(values):
            text = _clean(value)
            if not text:
                continue
            fact_id = f"fact:{product_id}:{field_name}:{index}"
            facts.append(
                EvidenceFact(
                    snapshot_id=snapshot_id,
                    fact_id=fact_id,
                    product_id=product_id,
                    fact_kind=fact_kind,
                    text=text,
                    text_digest=digest_evidence_text(text),
                    snapshot_version=version,
                    snapshot_status="APPROVED",
                    approved=True,
                    source_ref=f"product-intelligence:{snapshot_id}:{field_name}[{index}]",
                )
            )
    return facts
