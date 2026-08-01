"""Derived Product-Intelligence stage for one product.

WHY THIS EXISTS
The `missing_intelligence` KPI predicate is
`NOT EXISTS (SELECT 1 FROM product_intelligence_snapshot WHERE product_id = p.id)` —
it counts APPROVED SNAPSHOTS. That is the truthful definition of "this product has no
approved Product Truth" and it is deliberately NOT changed here.

The consequence is that preparation work is invisible: creating 194 review drafts and
rewriting every blocked claim moves the headline by zero, because none of that produces a
snapshot (only a human approval does). Operators then cannot tell "nothing has happened"
from "everything is prepared and waiting for me". This module derives the intermediate
stage so the UI can show progress WITHOUT redefining the headline.

Every stage is read off EXISTING contracts — the review-draft row, its claim gate and the
snapshot table. Nothing new is persisted and no new DB state is invented.

STAGE LADDER (first match wins)
    NO_DRAFT              no review draft row at all
    CLAIM_BLOCKED         the claim gate blocked it, or blocked claims are recorded
    CLAIM_REVIEW_REQUIRED draft exists, claims need a human ruling (NEEDS_REVISION)
    DRAFT_INCOMPLETE      draft exists but required Product Truth fields are still empty
    READY_FOR_REVIEW      draft is complete and claim-clean, awaiting human approval
    APPROVED_SNAPSHOT     an approved snapshot exists — no longer missing intelligence

`REQUIRED_FIELDS` mirrors PRODUCT_INTELLIGENCE_REQUIRED_FIELDS in
dashboard/src/pages/ProductsSalesAnalyzerPage.tsx so the backend and the review panel
agree on what "missing" means. Keep the two in sync.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

STAGE_NO_DRAFT = "NO_DRAFT"
STAGE_CLAIM_BLOCKED = "CLAIM_BLOCKED"
STAGE_CLAIM_REVIEW_REQUIRED = "CLAIM_REVIEW_REQUIRED"
STAGE_DRAFT_INCOMPLETE = "DRAFT_INCOMPLETE"
STAGE_READY_FOR_REVIEW = "READY_FOR_REVIEW"
STAGE_APPROVED_SNAPSHOT = "APPROVED_SNAPSHOT"

# Ordered worst -> best. The UI renders the progress breakdown in this order.
INTELLIGENCE_STAGES: tuple[str, ...] = (
    STAGE_NO_DRAFT,
    STAGE_CLAIM_BLOCKED,
    STAGE_CLAIM_REVIEW_REQUIRED,
    STAGE_DRAFT_INCOMPLETE,
    STAGE_READY_FOR_REVIEW,
    STAGE_APPROVED_SNAPSHOT,
)

# Mirrors the review panel's required-field contract.
REQUIRED_FIELDS: tuple[str, ...] = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
    "source_urls_json",
    "image_evidence_json",
    "claim_gate",
    "claim_risk_level",
)

# `claim_gate` is the AUTHORITATIVE claim verdict, written by
# `_evaluate_validation_payload`. It is the only thing that decides between blocked and
# review-required.
#
# `blocked_claims_json` must NOT be used to infer "blocked": a CLAIM_REVIEW_REQUIRED draft
# can also carry entries there (2 live rows do), and treating that list as the verdict
# mislabels review-required products as blocked — which would send them to a paid rewrite
# they do not need. The list is carried through as human-readable REASONS only.
_BLOCKED_GATES = {"BLOCKED", "CLAIM_BLOCKED", "FAIL", "FAILED"}
_REVIEW_GATES = {"CLAIM_REVIEW_REQUIRED", "REVIEW_REQUIRED"}
# review_status values that mean the draft is not finished yet.
_UNFINISHED_REVIEW_STATUSES = {"DRAFT", "NEEDS_REVISION"}


def _decoded(value: Any) -> Any:
    """JSON columns arrive as text. Decode leniently; bad JSON is treated as absent."""
    if isinstance(value, (str, bytes)) and str(value).strip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def _has_value(value: Any) -> bool:
    """Mirror of the panel's hasSnapshotValue: empty string / [] / {} / null are absent."""
    decoded = _decoded(value)
    if decoded is None:
        return False
    if isinstance(decoded, str):
        return decoded.strip() != ""
    if isinstance(decoded, (list, tuple, set, dict)):
        return len(decoded) > 0
    return True


def missing_required_fields(draft: Mapping[str, Any] | None) -> list[str]:
    if not draft:
        return list(REQUIRED_FIELDS)
    return [f for f in REQUIRED_FIELDS if not _has_value(draft.get(f))]


def blocked_claim_reasons(draft: Mapping[str, Any] | None) -> list[str]:
    if not draft:
        return []
    decoded = _decoded(draft.get("blocked_claims_json")) or []
    if isinstance(decoded, dict):
        decoded = list(decoded.values())
    reasons: list[str] = []
    for entry in decoded if isinstance(decoded, (list, tuple)) else []:
        if isinstance(entry, Mapping):
            reasons.append(str(entry.get("reason") or entry.get("claim")
                               or entry.get("token") or entry))
        else:
            reasons.append(str(entry))
    # preserve order, drop duplicates
    return list(dict.fromkeys(r for r in reasons if r))


def evaluate_intelligence_stage(
    draft: Mapping[str, Any] | None,
    *,
    has_snapshot: bool = False,
) -> dict[str, Any]:
    """Pure evaluation of one product's intelligence stage. Reads and writes nothing."""
    missing = missing_required_fields(draft)
    reasons = blocked_claim_reasons(draft)
    gate = str((draft or {}).get("claim_gate") or "").strip().upper()
    review_status = str((draft or {}).get("review_status") or "").strip().upper()

    if has_snapshot:
        stage = STAGE_APPROVED_SNAPSHOT
    elif draft is None:
        stage = STAGE_NO_DRAFT
    elif gate in _BLOCKED_GATES:
        stage = STAGE_CLAIM_BLOCKED
    elif gate in _REVIEW_GATES:
        stage = STAGE_CLAIM_REVIEW_REQUIRED
    elif missing:
        stage = STAGE_DRAFT_INCOMPLETE
    elif review_status in _UNFINISHED_REVIEW_STATUSES:
        stage = STAGE_DRAFT_INCOMPLETE
    else:
        stage = STAGE_READY_FOR_REVIEW

    return {
        "intelligence_stage": stage,
        "draft_status": review_status or None,
        "draft_id": (draft or {}).get("draft_id"),
        "missing_fields": missing,
        "missing_field_count": len(missing),
        "claim_gate": (draft or {}).get("claim_gate"),
        "claim_risk_level": (draft or {}).get("claim_risk_level"),
        "claim_reasons": reasons,
        "approved_snapshot": bool(has_snapshot),
        # Copy grounding needs an APPROVED snapshot; without one the copy lane fails
        # closed with COPY_GROUNDING_INSUFFICIENT. Stated per row so the operator can see
        # which products the copy phase will reject before it is started.
        "copy_blocked": not has_snapshot,
    }


def stage_sql_case(draft_alias: str = "d", snapshot_alias: str = "s") -> str:
    """SQL mirror of the ladder, for server-side FILTERING and the breakdown COUNT.

    Kept deliberately close to `evaluate_intelligence_stage`. It intentionally does NOT
    reproduce the DRAFT_INCOMPLETE required-field scan (that needs per-field emptiness
    checks over JSON columns); SQL collapses those rows into READY_FOR_REVIEW and the
    Python evaluator refines the visible page. The two agree on every other stage, and
    the covered stages are the ones the breakdown and filters are used for.
    """
    blocked = ", ".join(f"'{g}'" for g in sorted(_BLOCKED_GATES))
    review = ", ".join(f"'{g}'" for g in sorted(_REVIEW_GATES))
    unfinished = ", ".join(f"'{s}'" for s in sorted(_UNFINISHED_REVIEW_STATUSES))
    return (
        "CASE"
        f" WHEN {snapshot_alias}.product_id IS NOT NULL THEN '{STAGE_APPROVED_SNAPSHOT}'"
        f" WHEN {draft_alias}.product_id IS NULL THEN '{STAGE_NO_DRAFT}'"
        f" WHEN UPPER(COALESCE({draft_alias}.claim_gate, '')) IN ({blocked})"
        f"   THEN '{STAGE_CLAIM_BLOCKED}'"
        f" WHEN UPPER(COALESCE({draft_alias}.claim_gate, '')) IN ({review})"
        f"   THEN '{STAGE_CLAIM_REVIEW_REQUIRED}'"
        f" WHEN UPPER(COALESCE({draft_alias}.review_status, '')) IN ({unfinished})"
        f"   THEN '{STAGE_DRAFT_INCOMPLETE}'"
        f" ELSE '{STAGE_READY_FOR_REVIEW}' END"
    )
