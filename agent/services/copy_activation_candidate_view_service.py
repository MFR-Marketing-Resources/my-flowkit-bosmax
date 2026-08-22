"""Read-only projections for the Copy Authority candidate discovery payload.

The review-queue service remains the authority for discovering and validating
activation candidates.  This module only projects that authoritative payload
for the two operator surfaces; it does not read or write the database and does
not change activation eligibility.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping

from agent.services.copy_register_review_queue_service import CopyRegisterReviewQueueError


ActivationCandidateView = Literal["all", "activation", "diagnostics"]
_VIEWS: set[str] = {"all", "activation", "diagnostics"}


def _is_activation_ready(item: Mapping[str, Any]) -> bool:
    return (
        item.get("status") == "PRODUCTION_VALID"
        and item.get("activatable") is True
        and item.get("current_authority_state") == "NONE"
    )


def _is_diagnostic(item: Mapping[str, Any]) -> bool:
    # Diagnostics are every non-actionable, non-current row.  The current
    # backend normally projects these as STALE, but retaining the explicit
    # activatable check also keeps blocked/invalid projections visible if a
    # future authority reason uses another state label.
    return item.get("current_authority_state") != "CURRENT" and not _is_activation_ready(item)


def project_activation_candidate_view(
    response: Mapping[str, Any],
    *,
    view: str = "all",
) -> dict[str, Any]:
    """Return a surface-specific, metadata-preserving candidate projection.

    ``all`` preserves the complete discovery result for internal governance;
    ``activation`` is the operator's actionable queue; ``diagnostics`` is the
    read-only Reporting attention list.  Unknown views fail closed.
    """

    if view not in _VIEWS:
        raise CopyRegisterReviewQueueError(
            "COPY_V2_ACTIVATION_VIEW_INVALID",
            "The copy-authority candidate view is not supported.",
            details={"view": view, "allowed_views": sorted(_VIEWS)},
        )

    source_items = response.get("items") or []
    if view == "activation":
        items = [item for item in source_items if _is_activation_ready(item)]
    elif view == "diagnostics":
        items = [item for item in source_items if _is_diagnostic(item)]
    else:
        items = list(source_items)

    projected = dict(response)
    projected["view"] = view
    projected["items"] = items
    projected["total"] = len(items)
    return projected
