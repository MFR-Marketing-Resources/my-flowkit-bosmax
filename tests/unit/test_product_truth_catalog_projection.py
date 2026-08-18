"""Unit tests for Product Truth catalog operator projection (PI authority only)."""

from __future__ import annotations

from agent.services.product_truth_catalog_projection import (
    FILTER_APPROVED,
    FILTER_APPROVED_UPDATE_PENDING,
    FILTER_ACTION_REQUIRED,
    FILTER_NEEDS_REVIEW,
    FILTER_NOT_STARTED,
    PRODUCT_TRUTH_ACTION_REQUIRED,
    PRODUCT_TRUTH_APPROVED,
    PRODUCT_TRUTH_NEEDS_REVIEW,
    PRODUCT_TRUTH_NOT_STARTED,
    attach_product_truth_projections,
    is_hard_blocked_draft,
    matches_product_truth_filter,
    project_product_truth_status,
    summarize_product_truth,
)


def test_a_approved_snapshot_no_open_draft():
    out = project_product_truth_status(
        approved_snapshot={
            "version": 3,
            "approved_at": "2026-04-01T00:00:00Z",
            "created_at": "2026-04-01T00:00:00Z",
        },
        actionable_draft=None,
    )
    assert out["product_truth_status"] == PRODUCT_TRUTH_APPROVED
    assert out["product_truth_update_pending"] is False
    assert out["product_truth_approved_snapshot_version"] == 3
    assert out["product_truth_action_label"] == "View Product Truth"


def test_b_approved_plus_newer_non_terminal_revision():
    out = project_product_truth_status(
        approved_snapshot={
            "version": 2,
            "approved_at": "2026-04-01T00:00:00Z",
            "created_at": "2026-04-01T00:00:00Z",
        },
        actionable_draft={
            "review_status": "READY_FOR_REVIEW",
            "updated_at": "2026-04-02T00:00:00Z",
            "created_at": "2026-04-02T00:00:00Z",
            "revision_of_snapshot_id": "snap-1",
        },
    )
    assert out["product_truth_status"] == PRODUCT_TRUTH_APPROVED
    assert out["product_truth_update_pending"] is True
    assert out["product_truth_action_label"] == "Review Update"


def test_c_no_approved_normal_actionable_draft():
    out = project_product_truth_status(
        approved_snapshot=None,
        actionable_draft={
            "review_status": "READY_FOR_REVIEW",
            "claim_gate": "CLAIM_CLEAR",
            "readiness_status": "READY",
        },
    )
    assert out["product_truth_status"] == PRODUCT_TRUTH_NEEDS_REVIEW
    assert out["product_truth_update_pending"] is False
    assert out["product_truth_action_label"] == "Review Product Truth"


def test_d_no_approved_blocked_draft_action_required():
    out = project_product_truth_status(
        approved_snapshot=None,
        actionable_draft={
            "review_status": "NEEDS_REVISION",
            "claim_gate": "CLAIM_CLEAR",
            "readiness_status": "READY",
        },
    )
    assert out["product_truth_status"] == PRODUCT_TRUTH_ACTION_REQUIRED
    assert out["product_truth_action_label"] == "Fix Product Truth"

    out2 = project_product_truth_status(
        approved_snapshot=None,
        actionable_draft={
            "review_status": "DRAFT",
            "claim_gate": "CLAIM_BLOCKED",
            "readiness_status": "READY",
        },
    )
    assert out2["product_truth_status"] == PRODUCT_TRUTH_ACTION_REQUIRED


def test_e_not_started():
    out = project_product_truth_status(approved_snapshot=None, actionable_draft=None)
    assert out["product_truth_status"] == PRODUCT_TRUTH_NOT_STARTED
    assert out["product_truth_action_label"] == "Set Up Product Truth"


def test_f_terminal_draft_statuses_ignored():
    for status in ("APPROVED", "REJECTED", "SUPERSEDED", "COMMITTED"):
        out = project_product_truth_status(
            approved_snapshot=None,
            actionable_draft={"review_status": status},
        )
        assert out["product_truth_status"] == PRODUCT_TRUTH_NOT_STARTED, status


def test_hard_block_helpers():
    assert is_hard_blocked_draft({"review_status": "NEEDS_REVISION"}) is True
    assert is_hard_blocked_draft({"review_status": "DRAFT", "claim_gate": "CLAIM_BLOCKED"}) is True
    assert is_hard_blocked_draft(
        {"review_status": "DRAFT", "readiness_status": "MISSING_REQUIRED_FIELDS"}
    ) is True
    assert is_hard_blocked_draft({"review_status": "READY_FOR_REVIEW"}) is False


def test_g_filter_and_summary_over_full_scope():
    products = [
        {"id": "a", **project_product_truth_status(approved_snapshot={"version": 1}, actionable_draft=None)},
        {
            "id": "b",
            **project_product_truth_status(
                approved_snapshot={"version": 1, "approved_at": "2026-01-01T00:00:00Z"},
                actionable_draft={
                    "review_status": "DRAFT",
                    "updated_at": "2026-02-01T00:00:00Z",
                    "revision_of_snapshot_id": "x",
                },
            ),
        },
        {
            "id": "c",
            **project_product_truth_status(
                approved_snapshot=None,
                actionable_draft={"review_status": "READY_FOR_REVIEW"},
            ),
        },
        {
            "id": "d",
            **project_product_truth_status(
                approved_snapshot=None,
                actionable_draft={"review_status": "NEEDS_REVISION"},
            ),
        },
        {"id": "e", **project_product_truth_status(approved_snapshot=None, actionable_draft=None)},
    ]
    summary = summarize_product_truth(products)
    assert summary == {
        "APPROVED": 2,
        "NEEDS_REVIEW": 1,
        "ACTION_REQUIRED": 1,
        "NOT_STARTED": 1,
        "UPDATE_PENDING": 1,
    }

    assert matches_product_truth_filter(products[0], FILTER_APPROVED)
    assert not matches_product_truth_filter(products[0], FILTER_APPROVED_UPDATE_PENDING)
    assert matches_product_truth_filter(products[1], FILTER_APPROVED)
    assert matches_product_truth_filter(products[1], FILTER_APPROVED_UPDATE_PENDING)
    assert matches_product_truth_filter(products[2], FILTER_NEEDS_REVIEW)
    assert matches_product_truth_filter(products[3], FILTER_ACTION_REQUIRED)
    assert matches_product_truth_filter(products[4], FILTER_NOT_STARTED)


def test_attach_batch_set_based_shape():
    rows = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]
    approved = {
        "p1": {"version": 5, "approved_at": "2026-01-01T00:00:00Z", "created_at": "2026-01-01T00:00:00Z"},
    }
    drafts = {
        "p2": {"review_status": "READY_FOR_REVIEW", "claim_gate": "CLAIM_CLEAR"},
        "p3": {"review_status": "NEEDS_REVISION"},
    }
    attach_product_truth_projections(
        rows, approved_by_product=approved, drafts_by_product=drafts
    )
    assert rows[0]["product_truth_status"] == PRODUCT_TRUTH_APPROVED
    assert rows[1]["product_truth_status"] == PRODUCT_TRUTH_NEEDS_REVIEW
    assert rows[2]["product_truth_status"] == PRODUCT_TRUTH_ACTION_REQUIRED


def test_projection_module_never_imports_copy_evidence():
    import agent.services.product_truth_catalog_projection as mod
    import ast
    from pathlib import Path

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    joined = " ".join(imported).lower()
    assert "copy_evidence" not in joined
    assert "copy_register" not in joined
    assert "landbank" not in joined
    # Runtime surface must only project PI snapshot/draft authority.
    assert not hasattr(mod, "copy_evidence_fact_v2")
