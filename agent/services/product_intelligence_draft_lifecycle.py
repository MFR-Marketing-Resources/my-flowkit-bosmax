"""ONE canonical answer to "is this review draft still open?".

WHY THIS MODULE EXISTS
B-586-04 asks for a database-enforced "one open draft per product" rule. A DB constraint
and the application code that reads drafts must agree on *which rows are open*, or the
constraint protects a set the code never queries. Before this module the predicate was
written out by hand in four places with three different spellings:

    _latest_open_draft          NOT IN ('APPROVED','REJECTED')   ORDER BY updated_at DESC, draft_id DESC
    _resolve_duplicate_open_drafts  NOT IN ('APPROVED','REJECTED')   ORDER BY draft_id ASC
    product_intake_service._TERMINAL = {"APPROVED", "REJECTED"}
    (no database constraint at all)

The two orderings CONTRADICT each other: the reader returns the newest draft, the
deduplicator kept the lexicographically smallest and deleted the rest — so the dedup could
delete precisely the draft every reader would have returned. Both now import from here.

SUPERSEDED
Converging duplicates needs a terminal state that is TRUE. `REJECTED` would assert a human
rejected the draft and `APPROVED` that a human ratified it; both are fabricated review
decisions. `SUPERSEDED` says only what actually happened — another draft for this product
became canonical — and carries no reviewer identity, no approved_at and no rejected_at.
"""
from __future__ import annotations

# Terminal = the review is closed; the row is retained forever as evidence but is no longer
# the product's live draft. Adding to this set widens what the UNIQUE index permits, so it
# must stay in lockstep with SQL_OPEN_PREDICATE below.
TERMINAL_REVIEW_STATUSES: frozenset[str] = frozenset({"APPROVED", "REJECTED", "SUPERSEDED"})

# Written by convergence only. Never a human decision.
SUPERSEDED = "SUPERSEDED"

# The SQL spelling of "still open", used verbatim by the partial UNIQUE index, by the
# convergence migration and by every runtime query. Kept as one string so the index and the
# queries cannot drift apart.
SQL_OPEN_PREDICATE = (
    "UPPER(COALESCE(review_status,'')) NOT IN ('APPROVED','REJECTED','SUPERSEDED')"
)

# Recency authority. `_latest_open_draft` already defined "which open draft is the live
# one" this way; convergence MUST use the identical ordering so the row that survives is the
# row the application would have served.
SQL_CANONICAL_ORDER = "COALESCE(updated_at, created_at) DESC, draft_id DESC"

UNIQUE_OPEN_DRAFT_INDEX = "ux_product_intelligence_review_draft_one_open_per_product"


def is_terminal(review_status: object) -> bool:
    return str(review_status or "").strip().upper() in TERMINAL_REVIEW_STATUSES


def is_open(review_status: object) -> bool:
    return not is_terminal(review_status)
