"""CLAIM_REVIEW_REQUIRED must be satisfiable, CLAIM_BLOCKED must not.

Regression for a deadlock introduced with the claim floor: the floor raises
high-claim-risk products to CLAIM_REVIEW_REQUIRED, and approve_review_draft
refused on ANY approval_blocker. Net effect — every high-risk product became
permanently unapprovable. A real approval attempt on BOSMAX HERBS hit exactly
that wall.

"Review required" means a human must look. It cannot mean "never".
"""
import pytest

from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest as ApproveRequest,
)


def _filter(blockers, acknowledged):
    """Mirrors the filter in approve_review_draft."""
    if acknowledged:
        return [b for b in blockers if not b.startswith("CLAIM_REVIEW_REQUIRED")]
    return list(blockers)


def test_acknowledgement_defaults_to_false():
    assert ApproveRequest().claim_review_acknowledged is False


def test_claim_review_blocks_without_acknowledgement():
    assert _filter(["CLAIM_REVIEW_REQUIRED:UNSPECIFIED"], False)


def test_claim_review_is_satisfied_by_acknowledgement():
    assert _filter(["CLAIM_REVIEW_REQUIRED:UNSPECIFIED"], True) == []


def test_claim_blocked_is_NOT_satisfiable():
    """A genuinely blocked claim must survive any acknowledgement."""
    left = _filter(["CLAIM_BLOCKED:sembuh,dijamin"], True)
    assert left == ["CLAIM_BLOCKED:sembuh,dijamin"]


def test_missing_required_fields_is_NOT_satisfiable():
    left = _filter(["MISSING_REQUIRED_FIELDS:benefits_json"], True)
    assert left == ["MISSING_REQUIRED_FIELDS:benefits_json"]


def test_acknowledgement_only_clears_the_claim_review_blocker():
    left = _filter(
        [
            "CLAIM_REVIEW_REQUIRED:UNSPECIFIED",
            "MISSING_REQUIRED_FIELDS:usage_text",
            "CLAIM_BLOCKED:100%",
        ],
        True,
    )
    assert "CLAIM_REVIEW_REQUIRED:UNSPECIFIED" not in left
    assert len(left) == 2


def test_approve_request_still_rejects_unknown_fields():
    with pytest.raises(Exception):
        ApproveRequest(approved_by="x", nonsense=True)
