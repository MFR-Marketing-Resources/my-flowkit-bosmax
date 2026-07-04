"""Copy Set → compiler binding resolver (Copy Selection & Compiler Binding V1).

This module is the ONE controlled door by which an operator-selected approved
Copy Set reaches the deterministic final 9-section UGC video prompt compiler as
`copy_intelligence`. It resolves a selected `copy_set_id` into a clean compiler
copy dict and produces SAFE audit lineage.

Fail-closed law: when the operator explicitly selects a `copy_set_id` it MUST
exist, belong to the product, and be `COPY_APPROVED`. Otherwise the bind FAILS
CLOSED (never a silent fallback substitution). When no `copy_set_id` is selected
the compiler's existing fallback (product landbank -> claim-safe angles) still
runs, but the lineage records `COPY_SET_NOT_SELECTED` so nothing pretends that
fallback copy is approved copy.

Safety:
- No AI provider calls, no credit spend — this only reads a persisted Copy Set.
- Only `agent.models.copy_set.to_compiler_copy` fields cross into the compiler.
  copy_set_id / status / provenance / dedupe key / reviewer notes NEVER cross
  into the compiler and therefore never reach the final engine-facing prompt.
- Lineage carries safe audit metadata only (ids allowed in lineage JSON, never in
  prompt text; the raw dedupe key is hashed to a short fingerprint).
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from agent.db import crud
from agent.models.copy_set import (
    STATUS_COPY_APPROVED,
    serialize_copy_set,
    to_compiler_copy,
)

# ─── Copy source tags (lineage only) ────────────────────────
COPY_SOURCE_SELECTED = "selected_copy_set"
COPY_SOURCE_LANDBANK_FALLBACK = "landbank_fallback"
COPY_SOURCE_CLAIM_SAFE_FALLBACK = "claim_safe_fallback"

# ─── Binding status (lineage only) ──────────────────────────
BINDING_BOUND = "BOUND"
BINDING_NOT_SELECTED = "NOT_SELECTED"
BINDING_REJECTED = "REJECTED"

# ─── Fail-closed error codes ────────────────────────────────
ERR_NOT_FOUND = "COPY_SET_NOT_FOUND"
ERR_PRODUCT_MISMATCH = "COPY_SET_PRODUCT_MISMATCH"
ERR_NOT_APPROVED = "COPY_SET_NOT_APPROVED"
ERR_BINDING_FAILED = "COPY_SET_BINDING_FAILED"
# Explicit-Fallback-Confirmation V1: final generation (not preview) with no
# approved Copy Set selected must be intentionally confirmed by the operator.
ERR_FALLBACK_CONFIRMATION_REQUIRED = "COPY_SET_FALLBACK_CONFIRMATION_REQUIRED"

# ─── Degraded-mode warning (no explicit selection) ──────────
WARN_NOT_SELECTED = "COPY_SET_NOT_SELECTED"

# ─── Fallback confirmation policy (lineage audit) ───────────
COPY_FALLBACK_POLICY = "explicit_confirmation_v1"
COPY_FALLBACK_CONFIRMATION_SOURCE = "operator"


class CopyBindingError(Exception):
    """Raised when an EXPLICITLY selected Copy Set cannot be bound. Fail-closed —
    callers must surface this, never swallow it into a silent fallback."""

    def __init__(self, code: str, status_code: int = 422, detail: Any = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.detail = detail


def _hook_preview(hook: Any, limit: int = 80) -> str:
    text = " ".join(str(hook or "").split())
    return text[:limit]


def _fingerprint(dedupe_key: Any) -> Optional[str]:
    """Hash the Copy Set dedupe key into a short, opaque reference for lineage.
    The raw dedupe key embeds product id + copy text, so it is never surfaced
    verbatim — only this stable fingerprint is."""
    key = str(dedupe_key or "").strip()
    if not key:
        return None
    return "cs_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def not_selected_lineage() -> dict[str, Any]:
    """Lineage block for the degraded (no-selection) path. copy_source starts as
    landbank_fallback; the compiler may downgrade to claim-safe internally, but
    from the operator's controlled-selection standpoint no Copy Set was bound."""
    return {
        "copy_source": COPY_SOURCE_LANDBANK_FALLBACK,
        "copy_binding_status": BINDING_NOT_SELECTED,
        "copy_set_id": None,
        "copy_set_status": None,
        "copy_set_fingerprint": None,
        "copy_set_angle": None,
        "copy_set_hook_preview": None,
        "warning": WARN_NOT_SELECTED,
    }


async def resolve_compiler_copy_intelligence(
    product_id: str,
    copy_set_id: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve a selected Copy Set for compiler use.

    Returns::

        {
            "copy_intelligence": dict | None,  # clean compiler copy, or None
            "lineage": {...},                  # safe audit lineage (never in prompt)
            "warning": str | None,             # COPY_SET_NOT_SELECTED in degraded mode
        }

    `copy_intelligence` is None when no Copy Set is selected — the compiler then
    applies its own existing fallback. Raises `CopyBindingError` (fail-closed)
    when a provided `copy_set_id` is missing, product-mismatched, or not approved.
    """
    if not copy_set_id:
        return {
            "copy_intelligence": None,
            "lineage": not_selected_lineage(),
            "warning": WARN_NOT_SELECTED,
        }

    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise CopyBindingError(
            ERR_NOT_FOUND, status_code=404, detail={"copy_set_id": copy_set_id}
        )
    copy_set = serialize_copy_set(row)

    if str(copy_set.get("product_id")) != str(product_id):
        raise CopyBindingError(
            ERR_PRODUCT_MISMATCH,
            status_code=409,
            detail={
                "copy_set_id": copy_set_id,
                "expected_product_id": product_id,
                "actual_product_id": copy_set.get("product_id"),
            },
        )

    if copy_set.get("status") != STATUS_COPY_APPROVED:
        raise CopyBindingError(
            ERR_NOT_APPROVED,
            status_code=409,
            detail={"copy_set_id": copy_set_id, "status": copy_set.get("status")},
        )

    copy_intelligence = to_compiler_copy(copy_set)
    # An approved Copy Set is guaranteed complete (hook + usp + cta) by the Copy
    # Set approval gate; if the adapter yields nothing usable, fail closed rather
    # than hand an empty copy dict to the compiler.
    if not (
        copy_intelligence.get("hook")
        or copy_intelligence.get("usps")
        or copy_intelligence.get("cta")
    ):
        raise CopyBindingError(
            ERR_BINDING_FAILED, status_code=422, detail={"copy_set_id": copy_set_id}
        )

    lineage = {
        "copy_source": COPY_SOURCE_SELECTED,
        "copy_binding_status": BINDING_BOUND,
        "copy_set_id": copy_set_id,
        "copy_set_status": copy_set.get("status"),
        "copy_set_fingerprint": _fingerprint(copy_set.get("dedupe_key")),
        "copy_set_angle": copy_intelligence.get("angle") or None,
        "copy_set_hook_preview": _hook_preview(copy_intelligence.get("hook")) or None,
        "warning": None,
    }
    return {"copy_intelligence": copy_intelligence, "lineage": lineage, "warning": None}
