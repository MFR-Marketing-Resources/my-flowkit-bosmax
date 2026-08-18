"""Read-only Product Truth operator projection for Smart Registration catalog.

Derives catalog-wide Product Truth status EXCLUSIVELY from Product Intelligence
authority tables:

  * product_intelligence_snapshot (current APPROVED snapshot)
  * product_intelligence_review_draft (non-terminal actionable drafts)

Never reads copy_evidence_fact_v2, Copy Register, landbank, or visual readiness.
No writes, no recompute, no AI.
"""

from __future__ import annotations

from typing import Any, Mapping

# Operator-facing primary statuses (projection, not persisted enums).
PRODUCT_TRUTH_APPROVED = "APPROVED"
PRODUCT_TRUTH_NEEDS_REVIEW = "NEEDS_REVIEW"
PRODUCT_TRUTH_ACTION_REQUIRED = "ACTION_REQUIRED"
PRODUCT_TRUTH_NOT_STARTED = "NOT_STARTED"

PRODUCT_TRUTH_STATUSES = frozenset(
    {
        PRODUCT_TRUTH_APPROVED,
        PRODUCT_TRUTH_NEEDS_REVIEW,
        PRODUCT_TRUTH_ACTION_REQUIRED,
        PRODUCT_TRUTH_NOT_STARTED,
    }
)

# Filter tokens accepted by GET /api/products?product_truth=...
FILTER_ALL = "ALL"
FILTER_APPROVED = "APPROVED"
FILTER_APPROVED_UPDATE_PENDING = "APPROVED_UPDATE_PENDING"
FILTER_NEEDS_REVIEW = "NEEDS_REVIEW"
FILTER_ACTION_REQUIRED = "ACTION_REQUIRED"
FILTER_NOT_STARTED = "NOT_STARTED"

FILTER_VALUES = frozenset(
    {
        FILTER_ALL,
        FILTER_APPROVED,
        FILTER_APPROVED_UPDATE_PENDING,
        FILTER_NEEDS_REVIEW,
        FILTER_ACTION_REQUIRED,
        FILTER_NOT_STARTED,
    }
)

# Non-terminal PI review draft statuses that can still require operator action.
_NON_TERMINAL_DRAFT_STATUSES = frozenset(
    {
        "DRAFT",
        "READY_FOR_REVIEW",
        "NEEDS_REVISION",
    }
)

# Terminal draft statuses never become the catalog's "current" actionable draft.
_TERMINAL_DRAFT_STATUSES = frozenset(
    {
        "APPROVED",
        "REJECTED",
        "SUPERSEDED",
        "COMMITTED",  # legacy alias if present
    }
)

# Hard blockers that prevent approval without operator remediation.
_HARD_BLOCK_REVIEW_STATUSES = frozenset({"NEEDS_REVISION"})
_HARD_BLOCK_CLAIM_GATES = frozenset({"CLAIM_BLOCKED"})
_HARD_BLOCK_READINESS = frozenset(
    {
        "CLAIM_BLOCKED",
        "MISSING_REQUIRED_FIELDS",
    }
)

_ACTION_LABELS = {
    (PRODUCT_TRUTH_APPROVED, False): "View Product Truth",
    (PRODUCT_TRUTH_APPROVED, True): "Review Update",
    (PRODUCT_TRUTH_NEEDS_REVIEW, False): "Review Product Truth",
    (PRODUCT_TRUTH_NEEDS_REVIEW, True): "Review Product Truth",
    (PRODUCT_TRUTH_ACTION_REQUIRED, False): "Fix Product Truth",
    (PRODUCT_TRUTH_ACTION_REQUIRED, True): "Fix Product Truth",
    (PRODUCT_TRUTH_NOT_STARTED, False): "Set Up Product Truth",
    (PRODUCT_TRUTH_NOT_STARTED, True): "Set Up Product Truth",
}


def is_non_terminal_review_status(status: str | None) -> bool:
    return str(status or "").strip().upper() in _NON_TERMINAL_DRAFT_STATUSES


def is_hard_blocked_draft(draft: Mapping[str, Any] | None) -> bool:
    """True when the actionable draft cannot be approved without operator fix."""
    if not draft:
        return False
    review_status = str(draft.get("review_status") or "").strip().upper()
    claim_gate = str(draft.get("claim_gate") or "").strip().upper()
    readiness = str(draft.get("readiness_status") or "").strip().upper()
    if review_status in _HARD_BLOCK_REVIEW_STATUSES:
        return True
    if claim_gate in _HARD_BLOCK_CLAIM_GATES:
        return True
    if readiness in _HARD_BLOCK_READINESS:
        return True
    return False


def _ts(value: Any) -> str:
    return str(value or "").strip()


def draft_is_newer_than_approved(
    draft: Mapping[str, Any] | None,
    approved: Mapping[str, Any] | None,
) -> bool:
    """Deterministic newer-draft check for update_pending."""
    if not draft or not approved:
        return False
    # Explicit revision lineage always means an open revision after approval.
    if draft.get("revision_of_snapshot_id") or draft.get("revision_of_draft_id"):
        return True
    approved_anchor = _ts(approved.get("approved_at")) or _ts(approved.get("created_at"))
    draft_anchor = _ts(draft.get("updated_at")) or _ts(draft.get("created_at"))
    if not approved_anchor or not draft_anchor:
        # Fail open to "pending" only when a non-terminal draft coexists with
        # an approved snapshot and timestamps are missing — safer for operators.
        return True
    return draft_anchor > approved_anchor


def product_truth_action_label(status: str, update_pending: bool) -> str:
    return _ACTION_LABELS.get(
        (str(status or "").strip().upper(), bool(update_pending)),
        "Set Up Product Truth",
    )


def project_product_truth_status(
    *,
    approved_snapshot: Mapping[str, Any] | None,
    actionable_draft: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Pure operator projection for one product.

    Precedence:
      1. current APPROVED snapshot → APPROVED
         (+ update_pending if newer non-terminal draft)
      2. hard-blocked actionable draft → ACTION_REQUIRED
      3. actionable non-terminal draft → NEEDS_REVIEW
      4. else → NOT_STARTED

    Superseded/rejected/approved drafts are ignored when selecting actionable_draft
    (caller must pass only non-terminal drafts).
    """
    approved = approved_snapshot if approved_snapshot else None
    draft = actionable_draft if actionable_draft else None
    if draft and not is_non_terminal_review_status(str(draft.get("review_status") or "")):
        draft = None

    update_pending = False
    if approved:
        update_pending = bool(draft) and draft_is_newer_than_approved(draft, approved)
        status = PRODUCT_TRUTH_APPROVED
        version = approved.get("version")
        try:
            version_out = int(version) if version is not None else None
        except (TypeError, ValueError):
            version_out = None
        return {
            "product_truth_status": status,
            "product_truth_update_pending": update_pending,
            "product_truth_approved_snapshot_version": version_out,
            "product_truth_action_label": product_truth_action_label(status, update_pending),
        }

    if draft and is_hard_blocked_draft(draft):
        status = PRODUCT_TRUTH_ACTION_REQUIRED
    elif draft:
        status = PRODUCT_TRUTH_NEEDS_REVIEW
    else:
        status = PRODUCT_TRUTH_NOT_STARTED

    return {
        "product_truth_status": status,
        "product_truth_update_pending": False,
        "product_truth_approved_snapshot_version": None,
        "product_truth_action_label": product_truth_action_label(status, False),
    }


def empty_product_truth_summary() -> dict[str, int]:
    return {
        "APPROVED": 0,
        "NEEDS_REVIEW": 0,
        "ACTION_REQUIRED": 0,
        "NOT_STARTED": 0,
        "UPDATE_PENDING": 0,
    }


def summarize_product_truth(products: list[Mapping[str, Any]]) -> dict[str, int]:
    """Full-scope counts (pre-pagination). UPDATE_PENDING is secondary under APPROVED."""
    summary = empty_product_truth_summary()
    for product in products:
        status = str(product.get("product_truth_status") or "").strip().upper()
        if status in summary and status != "UPDATE_PENDING":
            summary[status] += 1
        if product.get("product_truth_update_pending"):
            summary["UPDATE_PENDING"] += 1
    return summary


def matches_product_truth_filter(product: Mapping[str, Any], product_truth: str | None) -> bool:
    token = str(product_truth or "").strip().upper()
    if not token or token == FILTER_ALL:
        return True
    status = str(product.get("product_truth_status") or "").strip().upper()
    pending = bool(product.get("product_truth_update_pending"))
    if token == FILTER_APPROVED_UPDATE_PENDING:
        return status == PRODUCT_TRUTH_APPROVED and pending
    if token == FILTER_APPROVED:
        return status == PRODUCT_TRUTH_APPROVED
    if token == FILTER_NEEDS_REVIEW:
        return status == PRODUCT_TRUTH_NEEDS_REVIEW
    if token == FILTER_ACTION_REQUIRED:
        return status == PRODUCT_TRUTH_ACTION_REQUIRED
    if token == FILTER_NOT_STARTED:
        return status == PRODUCT_TRUTH_NOT_STARTED
    return True


def attach_product_truth_projections(
    products: list[dict[str, Any]],
    *,
    approved_by_product: Mapping[str, Mapping[str, Any]],
    drafts_by_product: Mapping[str, Mapping[str, Any]],
) -> None:
    """Mutate product rows in place with lightweight Product Truth fields."""
    for product in products:
        pid = str(product.get("id") or "").strip()
        projection = project_product_truth_status(
            approved_snapshot=approved_by_product.get(pid),
            actionable_draft=drafts_by_product.get(pid),
        )
        product.update(projection)
