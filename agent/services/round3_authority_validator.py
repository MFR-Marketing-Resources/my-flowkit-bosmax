"""Macro Round 3 — ONE shared current-production-authority validator.

Round 3 P6 selection, allocation, compile, queue, and provider-start must all
gate on the SAME full Copy Register V2 authority the interactive lanes use — not
a shallow ``status == PRODUCTION_VALID`` + digest check.  This module is the
single authoritative helper: it reuses the existing V2 validation
(``get_blueprint_current_authority_validation`` + ``validate_copy_blueprint_v2``)
so a historically-PRODUCTION_VALID blueprint whose CURRENT authority drifted
(stale Product Truth, taxonomy/current-authority drift, missing/stale/mutated
evidence, approval-artifact mutation, approval-snapshot mismatch, formula-version
drift, duration invalidity) FAILS CLOSED everywhere Round 3 consumes copy.

It NEVER mutates the product-global activation pointer and NEVER spends provider
credit — it is a pure read + validate boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.authority.copy_blueprint_v2_authority import formula_version as v2_formula_version
from agent.models.copy_blueprint_v2 import EvidenceRegistry
from agent.services import copy_register_v2_service as v2svc
from agent.services.copy_blueprint_v2_service import validate_copy_blueprint_v2


@dataclass(frozen=True)
class Round3AuthorityResult:
    valid: bool
    reason_codes: tuple[str, ...] = ()
    blueprint: Any = None
    current_approval_snapshot_id: str | None = None
    approved_execution_text: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason_codes": list(self.reason_codes),
            "v2_approval_snapshot_id": self.current_approval_snapshot_id,
        }


def _dedupe(codes: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(code for code in codes if code))


async def revalidate_round3_v2_authority(
    *,
    blueprint_id: str,
    revision: int,
    expected_approval_snapshot_id: str | None = None,
    expected_truth_digest: str | None = None,
    expected_formula: str | None = None,
) -> Round3AuthorityResult:
    """Full current-production-authority revalidation for one exact V2 blueprint.

    Loads the exact blueprint revision + CURRENT Product Truth + CURRENT approved
    evidence registry and runs BOTH the PR #790 current-authority projection and
    the full ``validate_copy_blueprint_v2`` production gate.  Returns the original
    precise V2 reason codes on failure.  Never touches the global active pointer.
    """

    reasons: list[str] = []

    try:
        blueprint = await v2svc.get_blueprint(blueprint_id, revision)
    except v2svc.CopyRegisterV2Error as exc:
        return Round3AuthorityResult(False, (getattr(exc, "code", None) or "V2_BLUEPRINT_MISSING",))
    if blueprint is None:
        return Round3AuthorityResult(False, ("V2_BLUEPRINT_MISSING",))

    current_snapshot_id = (
        blueprint.approval_snapshot.approval_snapshot_id
        if blueprint.approval_snapshot is not None
        else None
    )
    approved_text = tuple(
        {"stage_key": entry.stage_key, "text": entry.text}
        for entry in blueprint.approved_execution_text
    )

    # (1) PR #790 current-authority projection (truth/taxonomy/blockers).
    try:
        truth = await v2svc.get_product_truth_proof(blueprint.product_id)
    except v2svc.CopyRegisterV2Error as exc:
        return Round3AuthorityResult(
            False,
            (getattr(exc, "code", None) or "PRODUCT_TRUTH_UNAVAILABLE",),
            blueprint=blueprint,
            current_approval_snapshot_id=current_snapshot_id,
        )
    authority = v2svc.get_blueprint_current_authority_validation(blueprint, truth)
    if not authority.get("activation_allowed"):
        reason = authority.get("reason")
        if reason:
            reasons.extend(part.strip() for part in str(reason).split(",") if part.strip())
        else:
            reasons.append("CURRENT_AUTHORITY_INVALID")

    # (2) Full V2 production gate: evidence lineage/digest/kind/approval, stage
    # digests, approval-artifact mutation, duration authority. Reuses the exact
    # rules the interactive V2 approve/bind boundary enforces.
    product, snapshot = await v2svc._product_truth_rows(blueprint.product_id)
    if product is None or snapshot is None:
        reasons.append("PRODUCT_TRUTH_UNAVAILABLE")
    else:
        current_lineage = v2svc._lineage(product, snapshot)
        registry = EvidenceRegistry(facts=tuple(v2svc._fact_candidates(product, snapshot)))
        result = validate_copy_blueprint_v2(
            blueprint,
            current_product_truth=current_lineage,
            evidence_registry=registry,
            require_approval=True,
            require_duration_target=blueprint.target_duration_seconds is not None,
        )
        if not result.production_valid:
            reasons.extend(result.error_codes)
        # (3) Explicit expectations from the recorded selection/link/manifest.
        if expected_truth_digest and expected_truth_digest != v2svc._truth_digest(snapshot):
            reasons.append("PRODUCT_TRUTH_ADVANCED")

    # (4) Approval-snapshot equality — never execute copy the selection was not
    # approved against, even though the blueprint revision itself is immutable.
    if expected_approval_snapshot_id and expected_approval_snapshot_id != (current_snapshot_id or ""):
        reasons.append("APPROVAL_SNAPSHOT_MISMATCH")

    # (5) Formula authority drift.
    if blueprint.formula_version != v2_formula_version(blueprint.formula_id):
        reasons.append("FORMULA_VERSION_ADVANCED")
    if expected_formula and expected_formula != blueprint.formula_id:
        reasons.append("FORMULA_IDENTITY_MISMATCH")

    codes = _dedupe(reasons)
    return Round3AuthorityResult(
        valid=not codes,
        reason_codes=codes,
        blueprint=blueprint,
        current_approval_snapshot_id=current_snapshot_id,
        approved_execution_text=approved_text,
    )
