"""COPY-CORRECTIVE-B02/B03 — single shared, FAIL-CLOSED Copy-Set validity authority.

Product-level COPY_ELIGIBLE (copy_eligibility_service) answers:
  "may this product enter a copy lane at all?"

Copy-Set-level VALIDITY answers:
  "is THIS specific Copy Set a valid current approved production asset?"

Reporting, readiness, rotation, selection, binding, and package creation MUST
share this predicate. "Has any non-archived copy_set row" is NOT validity.

FAIL-CLOSED CONTRACT (COPY-CORRECTIVE): a Copy Set is valid ONLY when every
applicable piece of evidence is PRESENT and passes. Missing completeness, missing
safety, missing semantic-review receipt, missing/mismatched PI lineage, an open
formula/sales gate, or detectable generic/synthetic filler each fail the set.
Absence of evidence is NOT success. Overrides are per-gate and never bypass safety.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from agent.db import get_db
from agent.models.copy_set import STATUS_COPY_APPROVED
from agent.services.copy_eligibility_service import (
    BLOCKED,
    NEEDS_REVALIDATION,
    PI_INELIGIBLE,
    copy_eligibility,
)

# ── Product-level classifications (deterministic precedence). ──────────────────
CLASS_APPROVED_COPY_VALID = "APPROVED_COPY_VALID"
CLASS_APPROVED_COPY_STALE = "APPROVED_COPY_STALE"
CLASS_APPROVED_COPY_UNSAFE = "APPROVED_COPY_UNSAFE"
CLASS_APPROVED_COPY_INCOMPLETE = "APPROVED_COPY_INCOMPLETE"
CLASS_APPROVED_COPY_GENERIC = "APPROVED_COPY_GENERIC"
CLASS_APPROVED_COPY_MISSING_REVIEW = "APPROVED_COPY_MISSING_REVIEW"
CLASS_APPROVED_COPY_FORMULA_REVIEW = "APPROVED_COPY_FORMULA_REVIEW"
CLASS_APPROVED_COPY_SALES_CLARITY_REVIEW = "APPROVED_COPY_SALES_CLARITY_REVIEW"
CLASS_APPROVED_COPY_INVALID_LINEAGE = "APPROVED_COPY_INVALID_LINEAGE"
CLASS_COPY_REVIEW_REQUIRED_ONLY = "COPY_REVIEW_REQUIRED_ONLY"
CLASS_DRAFT_COPY_ONLY = "DRAFT_COPY_ONLY"
CLASS_REJECTED_COPY_ONLY = "REJECTED_COPY_ONLY"
CLASS_MISSING_COPY = "MISSING_COPY"
CLASS_BLOCKED_WITH_REASON = "BLOCKED_WITH_REASON"

# Explicit signal that the evaluator itself could not run (NEVER report success).
CLASS_VALIDITY_EVALUATION_FAILED = "VALIDITY_EVALUATION_FAILED"

ACTION_PRESERVE_VALID_APPROVED = "PRESERVE_VALID_APPROVED"
ACTION_REVALIDATE_APPROVED = "REVALIDATE_APPROVED"
ACTION_SEMANTIC_REVIEW = "SEMANTIC_REVIEW_REQUIRED"
ACTION_REVIEW_EXISTING = "REVIEW_EXISTING"
ACTION_REPAIR_EXISTING = "REPAIR_EXISTING"
ACTION_REPLACE_COPY = "REPLACE_COPY"
ACTION_GENERATE_MISSING = "GENERATE_MISSING"
ACTION_BLOCK_WITH_REASON = "BLOCK_WITH_REASON"
ACTION_READY = "READY"

QUARANTINE_BAD = {PI_INELIGIBLE, NEEDS_REVALIDATION, BLOCKED, "BLOCKED"}

# Canonical failure tokens ranked by recoverability (lower = closer to valid).
# Used to pick a product's most-recoverable approved set and to classify by its
# dominant (worst) blocker without collapsing everything into STALE (defect #7).
SEV_STALE = 10
SEV_INVALID_LINEAGE = 15
SEV_SALES_CLARITY = 20
SEV_FORMULA = 25
SEV_MISSING_REVIEW = 30
SEV_INCOMPLETE = 40
SEV_GENERIC = 50
SEV_UNSAFE = 60

_PRIMARY_SEVERITY = {
    "STALE": SEV_STALE,
    "INVALID_LINEAGE": SEV_INVALID_LINEAGE,
    "SALES_CLARITY_REVIEW": SEV_SALES_CLARITY,
    "FORMULA_REVIEW": SEV_FORMULA,
    "MISSING_REVIEW": SEV_MISSING_REVIEW,
    "INCOMPLETE": SEV_INCOMPLETE,
    "GENERIC": SEV_GENERIC,
    "UNSAFE": SEV_UNSAFE,
}

_PRIMARY_TO_CLASS = {
    "STALE": (CLASS_APPROVED_COPY_STALE, ACTION_REVALIDATE_APPROVED),
    "INVALID_LINEAGE": (CLASS_APPROVED_COPY_INVALID_LINEAGE, ACTION_REVALIDATE_APPROVED),
    "SALES_CLARITY_REVIEW": (CLASS_APPROVED_COPY_SALES_CLARITY_REVIEW, ACTION_REVIEW_EXISTING),
    "FORMULA_REVIEW": (CLASS_APPROVED_COPY_FORMULA_REVIEW, ACTION_REVIEW_EXISTING),
    "MISSING_REVIEW": (CLASS_APPROVED_COPY_MISSING_REVIEW, ACTION_SEMANTIC_REVIEW),
    "INCOMPLETE": (CLASS_APPROVED_COPY_INCOMPLETE, ACTION_REPAIR_EXISTING),
    "GENERIC": (CLASS_APPROVED_COPY_GENERIC, ACTION_REPLACE_COPY),
    "UNSAFE": (CLASS_APPROVED_COPY_UNSAFE, ACTION_REPLACE_COPY),
}


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def pi_authority_digest(snapshot_row: dict[str, Any] | Any) -> str:
    """Stable digest of the current approved PI authority used for lineage."""
    get = snapshot_row.get if isinstance(snapshot_row, dict) else snapshot_row.__getitem__
    payload = {
        "snapshot_id": get("snapshot_id"),
        "version": get("version"),
        "claim_gate": get("claim_gate"),
        "product_description": get("product_description"),
        "benefits_json": get("benefits_json"),
        "usp_json": get("usp_json"),
        "target_customer_text": get("target_customer_text"),
        "allowed_claims_json": get("allowed_claims_json"),
        "buyer_persona_snapshot_json": get("buyer_persona_snapshot_json"),
        "copy_strategy_summary_json": get("copy_strategy_summary_json"),
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Generic / synthetic filler detector (auditable). ──────────────────────────
# COPY-CORRECTIVE-B03. These are the exact families the Cursor Copy-Final holdout
# scripts emitted to force closure, plus structural name-only USP detection. A hit
# quarantines the set (GENERIC); it never deletes.
_GENERIC_PATTERN_SOURCES = [
    r"kelebihan\b[^\n]{0,40}#\s*\d+",       # "Kelebihan <product> #1"
    r"kelebihan tersendiri",
    r"identiti jelas",
    r"nilai yang mudah difahami",
    r"rutin harian dengan",
    r"bukti harian untuk",
    r"dibina untuk keperluan(?: sebenar)?",
    r"pilihan praktikal untuk keluarga",
    r"fokus pada kualiti dan kejelasan nilai",
    r"sesuai untuk rutin harian",
    r"cuba sekarang dan rasai bezanya",
]
_GENERIC_RX = re.compile("|".join(_GENERIC_PATTERN_SOURCES), re.IGNORECASE)
# Low-specificity USP: nothing product-specific beyond the product name / a number.
_TRIVIAL_USP_TAIL = re.compile(r"^[\W\d_]*$")


def _usp_list(copy_set: dict[str, Any]) -> list[str]:
    usp = copy_set.get("usp_set")
    if usp is None:
        usp = _parse_json(copy_set.get("usp_set_json"))
    if isinstance(usp, dict):
        usp = list(usp.values())
    if not isinstance(usp, list):
        return []
    return [str(u) for u in usp if _clean(u)]


def detect_generic_copy(
    *,
    angle: str = "",
    hook: str = "",
    subhook: str = "",
    usp_list: list[str] | None = None,
    cta: str = "",
    product_name: str = "",
) -> dict[str, Any]:
    """Return {'generic': bool, 'hits': [...]} — deterministic, explainable."""
    usp_list = usp_list or []
    hits: list[str] = []
    haystack = "\n".join([angle, hook, subhook, " ".join(usp_list), cta])
    for m in {m.group(0).strip().lower() for m in _GENERIC_RX.finditer(haystack)}:
        hits.append(f"FILLER_PATTERN:{m[:48]}")
    pn = _clean(product_name).lower()
    for u in usp_list:
        us = _clean(u).lower()
        if not us:
            continue
        tail = us.replace(pn, "").strip() if pn else us
        if pn and (us == pn or _TRIVIAL_USP_TAIL.match(tail) or len(tail) <= 3):
            hits.append(f"USP_NAME_ONLY:{_clean(u)[:48]}")
    return {"generic": bool(hits), "hits": hits}


# ── Semantic review receipt validation (COPY-CORRECTIVE-B03). ─────────────────
def validate_semantic_review_receipt(
    receipt: Any,
    *,
    current_snapshot_id: str | None,
    current_authority_digest: str | None,
) -> dict[str, Any]:
    """A strict-valid Copy Set must carry a durable semantic-review receipt that
    an independent auditor can read: an identified reviewer approved THIS copy
    against the CURRENT PI authority. Missing/short receipt fails closed."""
    reasons: list[str] = []
    if not isinstance(receipt, dict) or not receipt:
        return {"ok": False, "reasons": ["SEMANTIC_REVIEW_MISSING"]}
    if _clean(receipt.get("decision")).upper() != "APPROVED":
        reasons.append("SEMANTIC_REVIEW_NOT_APPROVED")
    if not _clean(receipt.get("reviewer")):
        reasons.append("SEMANTIC_REVIEW_NO_REVIEWER")
    if not _clean(receipt.get("reviewed_at")):
        reasons.append("SEMANTIC_REVIEW_NO_TIMESTAMP")
    if not _clean(receipt.get("rationale")):
        reasons.append("SEMANTIC_REVIEW_NO_RATIONALE")
    # Receipt must be bound to the CURRENT authority (fail-closed on drift).
    r_snap = _clean(receipt.get("pi_snapshot_id"))
    if current_snapshot_id:
        if not r_snap:
            reasons.append("SEMANTIC_REVIEW_NO_LINEAGE")
        elif r_snap != _clean(current_snapshot_id):
            reasons.append("SEMANTIC_REVIEW_STALE_LINEAGE")
        r_dig = _clean(receipt.get("authority_digest"))
        if current_authority_digest and r_dig and r_dig != _clean(current_authority_digest):
            reasons.append("SEMANTIC_REVIEW_DIGEST_MISMATCH")
    # COPY-CORRECTIVE-B1: field-level grounding evidence is MANDATORY — a reviewer
    # name + rationale are not semantic evidence.
    grounding = receipt.get("grounding")
    if not isinstance(grounding, dict) or grounding.get("grounded") is not True:
        reasons.append("SEMANTIC_REVIEW_NOT_GROUNDED")
    else:
        usp_g = grounding.get("usp_grounding") or receipt.get("usp_grounding") or []
        hook_ok = bool(grounding.get("hook_grounded"))
        usp_ok = any(bool(u.get("grounded")) for u in usp_g if isinstance(u, dict))
        if not (hook_ok or usp_ok):
            reasons.append("SEMANTIC_REVIEW_NO_GROUNDED_ATTRIBUTE")
        if not usp_g:
            reasons.append("SEMANTIC_REVIEW_NO_USP_GROUNDING")
    gen = receipt.get("genericness")
    if not (isinstance(gen, dict) and gen.get("generic") is False):
        reasons.append("SEMANTIC_REVIEW_GENERICNESS_UNVERIFIED")
    return {"ok": not reasons, "reasons": reasons}


def _primary_reason(reasons: list[str]) -> Optional[str]:
    """Collapse a set's raw reason list into its single worst recoverable token."""
    tokens: set[str] = set()
    for r in reasons:
        if r.startswith("UNSAFE") or r.startswith("SAFETY"):
            tokens.add("UNSAFE")
        elif r.startswith("GENERIC"):
            tokens.add("GENERIC")
        elif r.startswith("INCOMPLETE") or r.startswith("COMPLETENESS"):
            tokens.add("INCOMPLETE")
        # Stale PI lineage on the receipt is STALE, not "missing review" — the
        # receipt exists; it is bound to a superseded authority (#688).
        elif r in {
            "SEMANTIC_REVIEW_STALE_LINEAGE",
            "SEMANTIC_REVIEW_DIGEST_MISMATCH",
        } or r.startswith("SEMANTIC_REVIEW_STALE"):
            tokens.add("STALE")
        elif r.startswith("SEMANTIC_REVIEW"):
            tokens.add("MISSING_REVIEW")
        elif r.startswith("FORMULA"):
            tokens.add("FORMULA_REVIEW")
        elif r.startswith("SALES_CLARITY"):
            tokens.add("SALES_CLARITY_REVIEW")
        elif r == "MISSING_PI_LINEAGE":
            tokens.add("INVALID_LINEAGE")
        elif r.startswith("PI_") and r.endswith("MISMATCH"):
            tokens.add("STALE")
        elif r.startswith("QUARANTINED"):
            # Bare quarantine without a stronger token recovers via revalidation.
            tokens.add("STALE")
    if not tokens:
        return None
    return max(tokens, key=lambda t: _PRIMARY_SEVERITY.get(t, 0))


def evaluate_copy_set_validity(
    *,
    copy_set: dict[str, Any],
    product_eligible: bool,
    product_eligibility_reasons: list[str] | None,
    current_snapshot_id: str | None,
    current_snapshot_version: int | None,
    current_authority_digest: str | None,
    product_name: str = "",
    require_lineage_match: bool = True,
    require_semantic_review: bool = True,
) -> dict[str, Any]:
    """Pure asset-level validity. No I/O. FAIL-CLOSED.

    A valid production Copy Set must be:
    - COPY_APPROVED, not archived, not quarantined, on a COPY_ELIGIBLE product
    - complete (completeness verdict PRESENT and complete)
    - safe (safety verdict PRESENT and safe)
    - formula-clear (or per-gate override) and sales-clear (or per-gate override)
    - free of generic/synthetic filler
    - carrying a semantic-review receipt bound to the current PI authority
    - grounded on the current approved PI snapshot/version/digest
    """
    reasons: list[str] = []
    status = _clean(copy_set.get("status")).upper()
    archived = bool(copy_set.get("archived"))
    quar = _clean(copy_set.get("pi_eligibility_status")).upper() or None

    if status != STATUS_COPY_APPROVED:
        reasons.append(f"STATUS_NOT_APPROVED:{status or 'UNKNOWN'}")
    if archived:
        reasons.append("ARCHIVED")
    if quar in QUARANTINE_BAD:
        reasons.append(f"QUARANTINED:{quar}")
    if not product_eligible:
        reasons.append(
            "PRODUCT_INELIGIBLE:" + ",".join(product_eligibility_reasons or ["UNKNOWN"])
        )

    claim = copy_set.get("claim_review")
    if claim is None:
        claim = _parse_json(copy_set.get("claim_review_json")) or {}
    if not isinstance(claim, dict):
        claim = {}

    # Completeness — PRESENT and complete (missing verdict fails closed).
    completeness = claim.get("completeness")
    if not isinstance(completeness, dict) or "complete" not in completeness:
        reasons.append("INCOMPLETE:MISSING_COMPLETENESS_VERDICT")
    elif completeness.get("complete") is not True:
        reasons.append("INCOMPLETE")

    # Safety — PRESENT and safe (missing verdict fails closed).
    safety = claim.get("safety")
    if not isinstance(safety, dict) or "safe" not in safety:
        reasons.append("UNSAFE:MISSING_SAFETY_VERDICT")
    elif safety.get("safe") is not True:
        reasons.append("UNSAFE")

    # Formula / sales clarity — per-gate override ONLY (defect #4). The mere
    # existence of an approval_override object must NOT bypass a gate; only the
    # exact flag for that exact gate may, and neither ever bypasses safety.
    override = claim.get("approval_override")
    override = override if isinstance(override, dict) else {}
    # COPY-CORRECTIVE-B2: a formula / sales-clarity verdict must be PRESENT and be
    # either passing, a durable NOT_APPLICABLE verdict, or covered by the exact
    # per-gate override. A MISSING verdict no longer silently passes.
    if not _verdict_ok(claim.get("formula_validation"), "valid", override, "formula_review_overridden"):
        reasons.append("FORMULA_MISSING_OR_OPEN")
    if not _verdict_ok(claim.get("sales_clarity"), "clear", override, "sales_clarity_overridden"):
        reasons.append("SALES_CLARITY_MISSING_OR_OPEN")

    # Generic / synthetic filler.
    gen = detect_generic_copy(
        angle=_clean(copy_set.get("angle")),
        hook=_clean(copy_set.get("hook")),
        subhook=_clean(copy_set.get("subhook")),
        usp_list=_usp_list(copy_set),
        cta=_clean(copy_set.get("cta")),
        product_name=product_name,
    )
    if gen["generic"]:
        reasons.append("GENERIC:" + ";".join(gen["hits"])[:120])

    # Semantic review receipt (fail-closed).
    receipt = claim.get("semantic_review")
    if require_semantic_review:
        rr = validate_semantic_review_receipt(
            receipt,
            current_snapshot_id=current_snapshot_id,
            current_authority_digest=current_authority_digest,
        )
        if not rr["ok"]:
            reasons.extend(rr["reasons"])

    # Lineage / freshness against current PI authority.
    cs_snap = _clean(copy_set.get("pi_snapshot_id")) or None
    cs_ver = copy_set.get("pi_snapshot_version")
    try:
        cs_ver_i = int(cs_ver) if cs_ver is not None and str(cs_ver).strip() != "" else None
    except (TypeError, ValueError):
        cs_ver_i = None
    cs_digest = _clean(copy_set.get("pi_grounding_digest")) or None
    if not cs_snap or not cs_digest:
        prov = copy_set.get("provenance")
        if prov is None:
            prov = _parse_json(copy_set.get("provenance_json")) or {}
        if isinstance(prov, dict):
            lineage = prov.get("pi_lineage") or prov.get("product_intelligence") or {}
            if isinstance(lineage, dict):
                cs_snap = cs_snap or _clean(lineage.get("snapshot_id")) or None
                if cs_ver_i is None and lineage.get("version") is not None:
                    try:
                        cs_ver_i = int(lineage.get("version"))
                    except (TypeError, ValueError):
                        pass
                cs_digest = cs_digest or _clean(lineage.get("authority_digest")) or None

    stale = False
    if require_lineage_match and current_snapshot_id:
        if not cs_snap and not cs_digest:
            stale = True
            reasons.append("MISSING_PI_LINEAGE")
        else:
            if cs_snap and cs_snap != current_snapshot_id:
                stale = True
                reasons.append("PI_SNAPSHOT_MISMATCH")
            if (
                cs_ver_i is not None
                and current_snapshot_version is not None
                and cs_ver_i != int(current_snapshot_version)
            ):
                stale = True
                reasons.append("PI_VERSION_MISMATCH")
            if cs_digest and current_authority_digest and cs_digest != current_authority_digest:
                stale = True
                reasons.append("PI_DIGEST_MISMATCH")

    valid = not reasons
    return {
        "valid": valid,
        "stale": stale and not valid,
        "reasons": reasons,
        "primary_reason": None if valid else _primary_reason(reasons),
        "generic": gen["generic"],
        "generic_hits": gen["hits"],
        "copy_set_id": copy_set.get("copy_set_id"),
        "status": status,
        "pi_eligibility_status": quar,
        "pi_snapshot_id": cs_snap,
        "pi_snapshot_version": cs_ver_i,
        "pi_grounding_digest": cs_digest,
        "current_snapshot_id": current_snapshot_id,
        "current_snapshot_version": current_snapshot_version,
        "current_authority_digest": current_authority_digest,
    }


def _valid_override(override: dict[str, Any], gate_flag: str) -> bool:
    """A gate override is honoured only when the EXACT flag is truthy AND the
    override carries an auditable reviewer + reason (never a bare object)."""
    if not isinstance(override, dict):
        return False
    if not override.get(gate_flag):
        return False
    return bool(_clean(override.get("reason")) and _clean(override.get("by")))


def _verdict_ok(verdict: Any, pass_key: str, override: dict[str, Any], gate_flag: str) -> bool:
    """COPY-CORRECTIVE-B2: a formula / sales-clarity gate passes only when a verdict
    is PRESENT and passing, is a durable NOT_APPLICABLE verdict, or the exact
    per-gate override is supplied. A MISSING verdict fails closed."""
    if _valid_override(override, gate_flag):
        return True
    if not isinstance(verdict, dict) or not verdict:
        return False
    if verdict.get("applicable") is False:
        return bool(
            _clean(verdict.get("reason"))
            and _clean(verdict.get("evaluator"))
            and _clean(verdict.get("evaluated_at"))
            and _clean(verdict.get("route") or verdict.get("lane"))
        )
    return bool(verdict.get(pass_key)) and not bool(verdict.get("review_required"))


def build_not_applicable_verdict(
    *, reason: str, route: str, evaluator: str, evaluated_at: str | None = None
) -> dict[str, Any]:
    """A durable NOT_APPLICABLE formula/sales verdict for an authorized deterministic
    (non-formula) route — NEVER inferred merely because the object is absent."""
    return {"applicable": False, "reason": reason, "route": route,
            "evaluator": evaluator, "evaluated_at": evaluated_at or _now()}


def classify_product_copy(
    *,
    product_eligible: bool,
    product_eligibility_reasons: list[str] | None,
    set_verdicts: list[dict[str, Any]],
    raw_sets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic, REASON-AWARE product-level classification (defect #7).

    An invalid approved set is classified by its dominant blocker (unsafe /
    generic / incomplete / missing-review / formula / sales / lineage / stale),
    never collapsed into STALE. When a product has several invalid approved sets,
    the most-recoverable one drives the recommended action.
    """
    if not product_eligible:
        return {
            "classification": CLASS_BLOCKED_WITH_REASON,
            "recommended_next_action": ACTION_BLOCK_WITH_REASON,
            "valid_copy_set_id": None,
            "block_reasons": list(product_eligibility_reasons or []),
            "invalid_copy_set_ids": [str(v.get("copy_set_id")) for v in set_verdicts],
        }

    valid = [v for v in set_verdicts if v.get("valid")]
    raw_approved_ids = {
        _clean(s.get("copy_set_id"))
        for s in raw_sets
        if _clean(s.get("status")).upper() == STATUS_COPY_APPROVED and not bool(s.get("archived"))
    }
    if valid:
        invalid_ids = sorted(raw_approved_ids - {_clean(v.get("copy_set_id")) for v in valid})
        return {
            "classification": CLASS_APPROVED_COPY_VALID,
            "recommended_next_action": ACTION_READY,
            "valid_copy_set_id": valid[0].get("copy_set_id"),
            "valid_approved_count": len(valid),
            "raw_approved_count": len(raw_approved_ids),
            "block_reasons": [],
            "invalid_copy_set_ids": invalid_ids,
        }

    # Approved-but-invalid sets: classify by the MOST RECOVERABLE dominant blocker.
    approved_ids = {
        _clean(s.get("copy_set_id"))
        for s in raw_sets
        if _clean(s.get("status")).upper() == STATUS_COPY_APPROVED and not bool(s.get("archived"))
    }
    approved_verdicts = [
        v for v in set_verdicts if _clean(v.get("copy_set_id")) in approved_ids
    ] or [v for v in set_verdicts if not v.get("valid")]
    scored: list[tuple[int, str, dict]] = []
    for v in approved_verdicts:
        pr = v.get("primary_reason") or _primary_reason(list(v.get("reasons") or []))
        if pr is None:
            # Approved set with no decodable blocker but not valid → treat as
            # missing semantic review (fail-closed, never silently valid).
            pr = "MISSING_REVIEW"
        scored.append((_PRIMARY_SEVERITY.get(pr, SEV_MISSING_REVIEW), pr, v))

    if scored and approved_ids:
        scored.sort(key=lambda t: t[0])  # most recoverable first
        _, pr, best = scored[0]
        klass, action = _PRIMARY_TO_CLASS.get(
            pr, (CLASS_APPROVED_COPY_MISSING_REVIEW, ACTION_SEMANTIC_REVIEW)
        )
        return {
            "classification": klass,
            "recommended_next_action": action,
            "valid_copy_set_id": None,
            "valid_approved_count": 0,
            "raw_approved_count": len(approved_ids),
            "primary_blocker": pr,
            "best_recoverable_copy_set_id": best.get("copy_set_id"),
            "block_reasons": list(best.get("reasons") or []),
            "invalid_copy_set_ids": sorted(approved_ids),
        }

    if any(
        _clean(s.get("status")).upper() == "COPY_REVIEW_REQUIRED" and not bool(s.get("archived"))
        for s in raw_sets
    ):
        return _simple_class(CLASS_COPY_REVIEW_REQUIRED_ONLY, ACTION_REVIEW_EXISTING)
    if any(
        _clean(s.get("status")).upper() == "DRAFT_COPY" and not bool(s.get("archived"))
        for s in raw_sets
    ):
        return _simple_class(CLASS_DRAFT_COPY_ONLY, ACTION_REPAIR_EXISTING)
    if raw_sets:
        return _simple_class(CLASS_REJECTED_COPY_ONLY, ACTION_GENERATE_MISSING)
    return _simple_class(CLASS_MISSING_COPY, ACTION_GENERATE_MISSING)


def _simple_class(klass: str, action: str) -> dict[str, Any]:
    return {
        "classification": klass,
        "recommended_next_action": action,
        "valid_copy_set_id": None,
        "block_reasons": [],
        "invalid_copy_set_ids": [],
    }


async def _latest_approved_snapshot(product_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT snapshot_id, version, claim_gate, claim_risk_level, "
        "product_description, benefits_json, usp_json, target_customer_text, "
        "allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "approved_at, created_at, status "
        "FROM product_intelligence_snapshot "
        "WHERE product_id = ? AND status = 'APPROVED' "
        "ORDER BY version DESC LIMIT 1",
        (product_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


async def _product_name(product_id: str) -> str:
    db = await get_db()
    cur = await db.execute("PRAGMA table_info(product)")
    cols = {r[1] for r in await cur.fetchall()}
    await cur.close()
    # Canonical schema exposes the product identity as raw_product_title (there is
    # no short `name` column); fall back through the known name-bearing columns.
    col = next(
        (c for c in ("product_name", "canonical_name", "name", "raw_product_title", "title") if c in cols),
        None,
    )
    if not col:
        return ""
    cur = await db.execute(f"SELECT {col} AS n FROM product WHERE id = ?", (product_id,))
    row = await cur.fetchone()
    await cur.close()
    return _clean(row["n"]) if row else ""


async def evaluate_copy_set_id(
    copy_set_id: str, *, require_semantic_review: bool = True
) -> dict[str, Any]:
    """DB-backed validity for one Copy Set (FAIL-CLOSED)."""
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_set WHERE copy_set_id = ?", (copy_set_id,))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return {"valid": False, "reasons": ["COPY_SET_NOT_FOUND"], "copy_set_id": copy_set_id}
    cs = dict(row)
    cs["claim_review"] = _parse_json(cs.get("claim_review_json")) or {}
    cs["provenance"] = _parse_json(cs.get("provenance_json")) or {}
    elig = await copy_eligibility(str(cs["product_id"]))
    snap = await _latest_approved_snapshot(str(cs["product_id"]))
    digest = pi_authority_digest(snap) if snap else None
    return evaluate_copy_set_validity(
        copy_set=cs,
        product_eligible=bool(elig.get("eligible")),
        product_eligibility_reasons=list(elig.get("reasons") or []),
        current_snapshot_id=str(snap["snapshot_id"]) if snap else None,
        current_snapshot_version=int(snap["version"]) if snap else None,
        current_authority_digest=digest,
        product_name=await _product_name(str(cs["product_id"])),
        require_semantic_review=require_semantic_review,
    )


async def product_copy_classification(product_id: str) -> dict[str, Any]:
    """Full product-level classification + per-set verdicts (FAIL-CLOSED)."""
    elig = await copy_eligibility(product_id)
    snap = await _latest_approved_snapshot(product_id)
    digest = pi_authority_digest(snap) if snap else None
    pname = await _product_name(product_id)
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_set WHERE product_id = ? ORDER BY created_at DESC",
        (product_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    verdicts = []
    for cs in rows:
        cs["claim_review"] = _parse_json(cs.get("claim_review_json")) or {}
        cs["provenance"] = _parse_json(cs.get("provenance_json")) or {}
        verdicts.append(
            evaluate_copy_set_validity(
                copy_set=cs,
                product_eligible=bool(elig.get("eligible")),
                product_eligibility_reasons=list(elig.get("reasons") or []),
                current_snapshot_id=str(snap["snapshot_id"]) if snap else None,
                current_snapshot_version=int(snap["version"]) if snap else None,
                current_authority_digest=digest,
                product_name=pname,
            )
        )
    classified = classify_product_copy(
        product_eligible=bool(elig.get("eligible")),
        product_eligibility_reasons=list(elig.get("reasons") or []),
        set_verdicts=verdicts,
        raw_sets=rows,
    )
    by_status: dict[str, int] = {}
    by_quar: dict[str, int] = {}
    for cs in rows:
        if bool(cs.get("archived")):
            by_status["ARCHIVED"] = by_status.get("ARCHIVED", 0) + 1
        else:
            st = _clean(cs.get("status")) or "UNKNOWN"
            by_status[st] = by_status.get(st, 0) + 1
        q = _clean(cs.get("pi_eligibility_status")) or "NULL"
        by_quar[q] = by_quar.get(q, 0) + 1
    return {
        "product_id": product_id,
        "product_name": pname,
        "copy_eligible": bool(elig.get("eligible")),
        "copy_eligibility_reasons": list(elig.get("reasons") or []),
        "current_pi_snapshot_id": str(snap["snapshot_id"]) if snap else None,
        "current_pi_version": int(snap["version"]) if snap else None,
        "current_pi_authority_digest": digest,
        "current_claim_gate": snap["claim_gate"] if snap else None,
        "total_copy_sets": len(rows),
        "copy_sets_by_status": by_status,
        "copy_sets_by_quarantine": by_quar,
        "set_verdicts": verdicts,
        **classified,
    }


async def assert_copy_set_valid(copy_set_id: str) -> dict[str, Any]:
    """Fail-closed guard for selection/binding/execution."""
    v = await evaluate_copy_set_id(copy_set_id)
    if not v.get("valid"):
        raise ValueError("COPY_SET_INVALID:" + ",".join(v.get("reasons") or ["UNKNOWN"]))
    return v


async def valid_copy_set_ids_for_product(product_id: str) -> set[str]:
    """Strict-valid copy_set_ids for a product right now (single evaluation).

    Selection / rotation / recommendation surfaces filter their approved
    candidates through this so a stale / generic / unsafe / incomplete /
    unreviewed / invalid-lineage set is never offered for execution - the same
    authority that binding enforces at the compiler boundary.
    """
    c = await product_copy_classification(product_id)
    return {
        str(v.get("copy_set_id"))
        for v in c.get("set_verdicts", [])
        if v.get("valid") and v.get("copy_set_id") is not None
    }


# ── Deterministic semantic grounding (COPY-CORRECTIVE-B03/B04, free-first) ─────
# A NO-PROVIDER proxy for semantic review: copy genuinely derived from the current
# approved Product Intelligence shares its vocabulary; generic/fabricated copy does
# not. This revalidates salvageable pre-existing copy WITHOUT spending provider
# credits — only the residual that fails this deterministic bar goes to paid rewrite.
_GROUNDING_STOPWORDS = {
    "yang", "untuk", "dengan", "dalam", "pada", "dari", "dan", "atau", "ini", "itu",
    "adalah", "akan", "tidak", "juga", "boleh", "kami", "anda", "kau", "hari", "tanpa",
    "lebih", "satu", "sangat", "semua", "kepada", "secara", "supaya", "agar", "kerana",
    "serta", "oleh", "buat", "guna", "nak", "dah", "kena", "rasa", "bila", "lagi",
    "the", "and", "for", "with", "from", "this", "that", "your", "you", "are", "our",
    "have", "not", "can", "all", "any", "use", "using", "made", "real", "need", "daily",
    "every", "more", "just", "now", "get", "who", "why", "how", "what", "when",
}


def _content_tokens(text: Any) -> set[str]:
    if isinstance(text, (list, dict)):
        text = json.dumps(text, ensure_ascii=False)
    toks = re.findall(r"[a-zA-ZÀ-ɏ]+", str(text or "").lower())
    return {t for t in toks if len(t) >= 4 and t not in _GROUNDING_STOPWORDS}


_GROUNDING_PI_FIELDS = (
    ("product_description", "product_description"),
    ("benefits", "benefits_json"),
    ("usp", "usp_json"),
    ("target_customer", "target_customer_text"),
    ("persona", "buyer_persona_snapshot_json"),
    ("strategy", "copy_strategy_summary_json"),
)


def assess_semantic_grounding(
    *,
    hook: str = "",
    subhook: str = "",
    usp_list: list[str] | None = None,
    cta: str = "",
    snapshot: dict[str, Any] | Any,
    product_title: str = "",
    min_overlap: int = 2,
) -> dict[str, Any]:
    """Deterministic SET-LEVEL PI grounding (cross-language tolerant).

    Vocabulary = current PI fields + the product title (brand / model / attribute
    tokens — often the only cross-language anchors when PI is English but the copy
    is Malay, e.g. microfiber/mikrofiber, viral, tahan-lama, a brand/model name).
    A set is grounded when the WHOLE copy shares >= ``min_overlap`` significant
    tokens with that vocabulary. This keeps genuinely product-specific copy
    (revalidate free) and quarantines generic/off-topic filler (paid rewrite),
    WITHOUT false-quarantining good copy that mixes attribute USPs with emotional
    ones. Fail-closed on no USP or an empty authority.
    """
    usp_list = [u for u in (usp_list or []) if _clean(u)]
    get = snapshot.get if isinstance(snapshot, dict) else (lambda _k: None)
    pi_fields: dict[str, set[str]] = {name: _content_tokens(get(col)) for name, col in _GROUNDING_PI_FIELDS}
    title_tokens = _content_tokens(product_title)
    vocab: set[str] = (
        set().union(*pi_fields.values(), title_tokens) if (pi_fields or title_tokens) else set()
    )

    def _match(text: str) -> tuple[str | None, int]:
        toks = _content_tokens(text)
        best_field, best = None, 0
        for fname, ftoks in list(pi_fields.items()) + [("product_title", title_tokens)]:
            ov = len(toks & ftoks)
            if ov > best:
                best, best_field = ov, fname
        return best_field, best

    usp_grounding: list[dict[str, Any]] = []
    for u in usp_list:
        fld, ov = _match(u)
        usp_grounding.append(
            {"usp": u, "grounded": ov >= 1, "supporting_pi_field": fld, "overlap": ov}
        )

    combined = _content_tokens(" ".join([hook, subhook, " ".join(usp_list), cta]))
    overlap = combined & vocab
    hook_fld, hook_ov = _match(f"{hook} {subhook}")

    reasons: list[str] = []
    if not vocab:
        reasons.append("EMPTY_PI_AUTHORITY")
    if not usp_list:
        reasons.append("NO_USP")
    if vocab and usp_list and len(overlap) < min_overlap:
        reasons.append("WEAK_GROUNDING")

    grounded = bool(vocab) and bool(usp_list) and len(overlap) >= min_overlap
    return {
        "grounded": grounded,
        "overlap_count": len(overlap),
        "overlap_tokens": sorted(overlap)[:12],
        "hook_grounded": hook_ov >= 1,
        "hook_supporting_pi_field": hook_fld,
        "usp_grounding": usp_grounding,
        "reasons": reasons,
    }


async def revalidate_copy_set(
    copy_set_id: str,
    *,
    reviewer: str,
    rationale: str,
    decision: str = "APPROVED",
) -> dict[str, Any]:
    """Atomically RE-STAMP an ALREADY-approved set as strict-valid (no provider).

    Recomputes field-level PI grounding + genericness from the copy itself, writes a
    receipt carrying that ACTUAL evidence (B1), ensures a formula/sales verdict
    (preserve existing; a deterministic non-AI lane with none gets a DURABLE
    NOT_APPLICABLE — route-gated, B2), stamps lineage, clears quarantine — one write.
    Raises COPY_SET_UNGROUNDED / COPY_SET_GENERIC when the copy genuinely fails, so
    the caller QUARANTINES instead of re-stamping.
    """
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_set WHERE copy_set_id = ?", (copy_set_id,))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        raise ValueError("COPY_SET_NOT_FOUND")
    cs = dict(row)
    if _clean(cs.get("status")).upper() != STATUS_COPY_APPROVED:
        raise ValueError("COPY_SET_NOT_APPROVED")
    snap = await _latest_approved_snapshot(str(cs["product_id"]))
    if not snap:
        raise ValueError("NO_APPROVED_PI_SNAPSHOT")
    title = await _product_name(str(cs["product_id"]))
    usp = _usp_list(cs)
    # B1: real grounding evidence, computed from the copy against current PI.
    gen = detect_generic_copy(
        angle=_clean(cs.get("angle")), hook=_clean(cs.get("hook")),
        subhook=_clean(cs.get("subhook")), usp_list=usp, cta=_clean(cs.get("cta")),
        product_name=title,
    )
    if gen["generic"]:
        raise ValueError("COPY_SET_GENERIC:" + ";".join(gen["hits"])[:120])
    grounding = assess_semantic_grounding(
        hook=_clean(cs.get("hook")), subhook=_clean(cs.get("subhook")),
        usp_list=usp, cta=_clean(cs.get("cta")), snapshot=snap, product_title=title,
    )
    if not grounding.get("grounded"):
        raise ValueError("COPY_SET_UNGROUNDED:" + ",".join(grounding.get("reasons") or []))
    digest = pi_authority_digest(snap)
    now = _now()
    claim = _parse_json(cs.get("claim_review_json")) or {}
    if not isinstance(claim, dict):
        claim = {}
    # B2: ensure a formula/sales verdict — preserve any existing; a deterministic
    # (non-AI) generation lane that carries none gets a DURABLE NOT_APPLICABLE.
    source = _clean(cs.get("source"))
    is_ai = "AI" in source.upper()
    route = source or "UNSPECIFIED_DETERMINISTIC_LANE"
    fv = claim.get("formula_validation")
    sc = claim.get("sales_clarity")
    if not (isinstance(fv, dict) and fv) and not is_ai:
        claim["formula_validation"] = build_not_applicable_verdict(
            reason="non-formula (deterministic) generation lane", route=route,
            evaluator=reviewer, evaluated_at=now)
    if not (isinstance(sc, dict) and sc) and not is_ai:
        claim["sales_clarity"] = build_not_applicable_verdict(
            reason="non-formula (deterministic) generation lane", route=route,
            evaluator=reviewer, evaluated_at=now)
    # B2: the set must actually PASS the formula / sales gate now — present + passing,
    # a durable NOT_APPLICABLE, or the exact per-gate override. A legacy formula-lane
    # set that carries no verdict (and no override) fails here so the caller
    # QUARANTINES it rather than re-stamping a missing-QA set as valid.
    _ov = claim.get("approval_override") if isinstance(claim.get("approval_override"), dict) else {}
    if not _verdict_ok(claim.get("formula_validation"), "valid", _ov, "formula_review_overridden"):
        raise ValueError("COPY_SET_FORMULA_OPEN")
    if not _verdict_ok(claim.get("sales_clarity"), "clear", _ov, "sales_clarity_overridden"):
        raise ValueError("COPY_SET_SALES_OPEN")
    claim["semantic_review"] = build_semantic_review_receipt(
        reviewer=reviewer, decision=decision, rationale=rationale,
        pi_snapshot_id=str(snap["snapshot_id"]), pi_snapshot_version=int(snap["version"]),
        authority_digest=digest, platform=_clean(cs.get("platform")),
        language=_clean(cs.get("language")), route=_clean(cs.get("route_type")),
        formula=_clean(cs.get("formula_family")), grounding=grounding, genericness=gen,
        product_title=title, reviewed_at=now,
    )
    prov = _parse_json(cs.get("provenance_json")) or {}
    if not isinstance(prov, dict):
        prov = {}
    prov["pi_lineage"] = {
        "snapshot_id": snap["snapshot_id"],
        "version": snap["version"],
        "authority_digest": digest,
        "grounded_at": now,
        "grounding_source": "APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT",
        "revalidated_at": now,
        "revalidated_by": reviewer,
        "decision": "REVALIDATED_GROUNDED",
        "rationale": rationale,
    }
    await db.execute(
        "UPDATE copy_set SET claim_review_json = ?, provenance_json = ?, "
        "pi_snapshot_id = ?, pi_snapshot_version = ?, pi_grounding_digest = ?, "
        "grounded_at = ?, revalidated_at = ?, revalidated_by = ?, "
        "revalidation_decision = ?, pi_eligibility_status = NULL, "
        "pi_ineligible_reasons = NULL, updated_at = ? WHERE copy_set_id = ?",
        (
            json.dumps(claim, ensure_ascii=False),
            json.dumps(prov, ensure_ascii=False),
            snap["snapshot_id"],
            int(snap["version"]),
            digest,
            now,
            now,
            reviewer,
            "REVALIDATED",
            now,
            copy_set_id,
        ),
    )
    await db.commit()
    return {
        "copy_set_id": copy_set_id,
        "pi_snapshot_id": str(snap["snapshot_id"]),
        "pi_snapshot_version": int(snap["version"]),
        "grounded_at": now,
        "grounding": grounding,
    }


async def quarantine_copy_set(
    copy_set_id: str,
    *,
    reason: str,
    status: str = NEEDS_REVALIDATION,
) -> dict[str, Any]:
    """Durable, auditable containment marking for an invalid asset (never deletes)."""
    db = await get_db()
    now = _now()
    await db.execute(
        "UPDATE copy_set SET pi_eligibility_status = ?, pi_ineligible_reasons = ?, "
        "updated_at = ? WHERE copy_set_id = ?",
        (status, reason, now, copy_set_id),
    )
    await db.commit()
    return {"copy_set_id": copy_set_id, "pi_eligibility_status": status, "reason": reason}


def build_semantic_review_receipt(
    *,
    reviewer: str,
    decision: str,
    rationale: str,
    pi_snapshot_id: str | None,
    pi_snapshot_version: int | None,
    authority_digest: str | None,
    platform: str = "",
    language: str = "",
    route: str = "",
    formula: str = "",
    usp_grounding: list[dict[str, Any]] | None = None,
    hook_review: str = "",
    subhook_review: str = "",
    cta_review: str = "",
    genericness: dict[str, Any] | None = None,
    grounding: dict[str, Any] | None = None,
    product_title: str = "",
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Durable, auditor-readable semantic-review receipt for a Copy Set.

    COPY-CORRECTIVE-B1: the receipt carries the ACTUAL field-level grounding
    evidence (overlap tokens/count, hook grounding, per-USP grounding, the PI
    authority used) — a reviewer name + rationale alone are not semantic evidence.
    """
    grounding = grounding or {}
    usp_g = usp_grounding if usp_grounding is not None else grounding.get("usp_grounding") or []
    return {
        "reviewer": reviewer,
        "reviewed_at": reviewed_at or _now(),
        "decision": (decision or "").upper(),
        "rationale": rationale,
        "pi_snapshot_id": pi_snapshot_id,
        "pi_version": pi_snapshot_version,
        "authority_digest": authority_digest,
        "platform": platform,
        "language": language,
        "route": route,
        "formula": formula,
        "usp_grounding": usp_g,
        "hook_review": hook_review or (grounding.get("hook_supporting_pi_field") or ""),
        "subhook_review": subhook_review,
        "cta_review": cta_review,
        "genericness": genericness or {},
        "grounding": {
            "grounded": bool(grounding.get("grounded")),
            "overlap_count": grounding.get("overlap_count"),
            "overlap_tokens": grounding.get("overlap_tokens") or [],
            "hook_grounded": bool(grounding.get("hook_grounded")),
            "hook_supporting_pi_field": grounding.get("hook_supporting_pi_field"),
            "usp_grounding": usp_g,
            "product_title_used": product_title,
            "pi_snapshot_id": pi_snapshot_id,
            "authority_digest": authority_digest,
        },
    }


async def stamp_copy_set_pi_lineage(
    copy_set_id: str,
    *,
    product_id: str | None = None,
    revalidated_by: str | None = None,
    clear_quarantine: bool = True,
    decision: str = "GROUNDED",
    rationale: str = "",
    db: Any | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Write current PI lineage onto a Copy Set (approval or revalidation).

    When ``db`` is supplied the caller owns the transaction (atomic approval);
    pass ``commit=False`` to defer the commit to the caller.
    """
    own_db = db is None
    db = db or await get_db()
    cur = await db.execute(
        "SELECT product_id, provenance_json FROM copy_set WHERE copy_set_id = ?",
        (copy_set_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        raise ValueError("COPY_SET_NOT_FOUND")
    pid = product_id or str(row["product_id"])
    snap = await _latest_approved_snapshot(pid)
    if not snap:
        raise ValueError("NO_APPROVED_PI_SNAPSHOT")
    digest = pi_authority_digest(snap)
    now = _now()
    prov = _parse_json(row["provenance_json"]) or {}
    if not isinstance(prov, dict):
        prov = {}
    prov["pi_lineage"] = {
        "snapshot_id": snap["snapshot_id"],
        "version": snap["version"],
        "authority_digest": digest,
        "grounded_at": now,
        "grounding_source": "APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT",
        "revalidated_at": now if revalidated_by else prov.get("pi_lineage", {}).get("revalidated_at"),
        "revalidated_by": revalidated_by or (prov.get("pi_lineage") or {}).get("revalidated_by"),
        "decision": decision,
        "rationale": rationale or (prov.get("pi_lineage") or {}).get("rationale") or "",
    }
    cur = await db.execute("PRAGMA table_info(copy_set)")
    cols = {r[1] for r in await cur.fetchall()}
    await cur.close()
    sets = ["provenance_json = ?", "updated_at = ?"]
    params: list[Any] = [json.dumps(prov, ensure_ascii=False), now]
    if "pi_snapshot_id" in cols:
        sets.append("pi_snapshot_id = ?")
        params.append(snap["snapshot_id"])
    if "pi_snapshot_version" in cols:
        sets.append("pi_snapshot_version = ?")
        params.append(int(snap["version"]))
    if "pi_grounding_digest" in cols:
        sets.append("pi_grounding_digest = ?")
        params.append(digest)
    if "grounded_at" in cols:
        sets.append("grounded_at = ?")
        params.append(now)
    if revalidated_by:
        if "revalidated_at" in cols:
            sets.append("revalidated_at = ?")
            params.append(now)
        if "revalidated_by" in cols:
            sets.append("revalidated_by = ?")
            params.append(revalidated_by)
        if "revalidation_decision" in cols:
            sets.append("revalidation_decision = ?")
            params.append(decision)
    if clear_quarantine and "pi_eligibility_status" in cols:
        sets.append("pi_eligibility_status = NULL")
        sets.append("pi_ineligible_reasons = NULL")
    params.append(copy_set_id)
    await db.execute(f"UPDATE copy_set SET {', '.join(sets)} WHERE copy_set_id = ?", params)
    if commit and own_db:
        await db.commit()
    return {
        "copy_set_id": copy_set_id,
        "pi_snapshot_id": snap["snapshot_id"],
        "pi_snapshot_version": int(snap["version"]),
        "pi_grounding_digest": digest,
        "grounded_at": now,
    }


async def mark_stale_copy_sets_for_product(
    product_id: str,
    *,
    current_snapshot_id: str,
    except_copy_set_ids: set[str] | None = None,
    db: Any | None = None,
    commit: bool = True,
) -> int:
    """Fail-closed: approved sets not grounded on current snapshot → NEEDS_REVALIDATION.

    Caller may pass an open ``db`` to make this part of the PI-approval transaction.
    """
    own_db = db is None
    db = db or await get_db()
    except_copy_set_ids = except_copy_set_ids or set()
    cur = await db.execute(
        "SELECT copy_set_id, pi_snapshot_id, provenance_json, status, archived, "
        "pi_eligibility_status FROM copy_set WHERE product_id = ?",
        (product_id,),
    )
    rows = await cur.fetchall()
    await cur.close()
    n = 0
    for r in rows:
        if str(r["status"]) != STATUS_COPY_APPROVED:
            continue
        if int(r["archived"] or 0):
            continue
        cid = str(r["copy_set_id"])
        if cid in except_copy_set_ids:
            continue
        snap_id = _clean(r["pi_snapshot_id"]) if "pi_snapshot_id" in r.keys() else ""
        if not snap_id:
            prov = _parse_json(r["provenance_json"]) or {}
            if isinstance(prov, dict):
                snap_id = _clean((prov.get("pi_lineage") or {}).get("snapshot_id"))
        if snap_id == current_snapshot_id:
            continue
        await db.execute(
            "UPDATE copy_set SET pi_eligibility_status = ?, "
            "pi_ineligible_reasons = ?, updated_at = ? WHERE copy_set_id = ?",
            (
                NEEDS_REVALIDATION,
                f"PI_SNAPSHOT_STALE:expected={current_snapshot_id},got={snap_id or 'NONE'}",
                _now(),
                cid,
            ),
        )
        n += 1
    if n and commit and own_db:
        await db.commit()
    return n


async def copywriting_validity_coverage(
    *,
    lifecycle_status: str = "ACTIVE",
) -> dict[str, Any]:
    """Cohort rollup for reporting — ACTIVE canonical non-fixture non-alias.

    FAIL-CLOSED: production readiness is driven by strict validity only. Raw row
    coverage stays available for diagnostics but never substitutes for validity.
    """
    from agent.services.reporting_service import (
        _MERGED_ALIAS_PREDICATE,
        _PRODUCT_BASE,
        _TEST_FIXTURE_PREDICATE,
        _product_filters,
        _scalar,
    )

    db = await get_db()
    where, params = _product_filters(lifecycle_status, None, None)
    real = f"{where} AND NOT {_TEST_FIXTURE_PREDICATE} AND NOT {_MERGED_ALIAS_PREDICATE}"
    total = await _scalar(db, f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{real}", params)
    cur = await db.execute(f"SELECT p.id AS id {_PRODUCT_BASE} WHERE 1=1{real}", params)
    ids = [str(r["id"]) for r in await cur.fetchall()]
    await cur.close()

    buckets: dict[str, int] = {
        CLASS_APPROVED_COPY_VALID: 0,
        CLASS_APPROVED_COPY_STALE: 0,
        CLASS_APPROVED_COPY_UNSAFE: 0,
        CLASS_APPROVED_COPY_INCOMPLETE: 0,
        CLASS_APPROVED_COPY_GENERIC: 0,
        CLASS_APPROVED_COPY_MISSING_REVIEW: 0,
        CLASS_APPROVED_COPY_FORMULA_REVIEW: 0,
        CLASS_APPROVED_COPY_SALES_CLARITY_REVIEW: 0,
        CLASS_APPROVED_COPY_INVALID_LINEAGE: 0,
        CLASS_COPY_REVIEW_REQUIRED_ONLY: 0,
        CLASS_DRAFT_COPY_ONLY: 0,
        CLASS_REJECTED_COPY_ONLY: 0,
        CLASS_MISSING_COPY: 0,
        CLASS_BLOCKED_WITH_REASON: 0,
        CLASS_VALIDITY_EVALUATION_FAILED: 0,
    }
    for pid in ids:
        try:
            c = await product_copy_classification(pid)
            klass = c["classification"]
        except Exception:
            klass = CLASS_VALIDITY_EVALUATION_FAILED
        buckets[klass] = buckets.get(klass, 0) + 1

    valid = buckets[CLASS_APPROVED_COPY_VALID]
    return {
        "scope": {"lifecycle_status": lifecycle_status},
        "total_products": total,
        "products_with_valid_approved_copy": valid,
        "products_without_valid_approved_copy": total - valid,
        "classification_counts": buckets,
        "coverage_pct": round(100.0 * valid / total, 1) if total else 0.0,
    }


# ── Shared validity contract for API / UI consumers (#688) ───────────────────
# Workflow status (COPY_APPROVED) is NOT production-valid by itself. Every list/
# detail/readiness surface must expose these fields from the same authority.

VALIDITY_UI_LABEL = {
    CLASS_APPROVED_COPY_VALID: "VALID",
    CLASS_APPROVED_COPY_STALE: "STALE PI",
    CLASS_APPROVED_COPY_INVALID_LINEAGE: "INVALID LINEAGE",
    CLASS_APPROVED_COPY_MISSING_REVIEW: "MISSING REVIEW",
    CLASS_APPROVED_COPY_FORMULA_REVIEW: "FORMULA REVIEW",
    CLASS_APPROVED_COPY_SALES_CLARITY_REVIEW: "SALES CLARITY",
    CLASS_APPROVED_COPY_INCOMPLETE: "INCOMPLETE",
    CLASS_APPROVED_COPY_GENERIC: "GENERIC",
    CLASS_APPROVED_COPY_UNSAFE: "UNSAFE",
}


def build_validity_contract(*, copy_set: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    """Map an evaluate_copy_set_validity verdict into the shared API contract."""
    status = _clean(copy_set.get("status") or verdict.get("status")).upper()
    valid = bool(verdict.get("valid"))
    reasons = list(verdict.get("reasons") or [])
    pr = verdict.get("primary_reason")
    if pr is None and reasons:
        pr = _primary_reason(reasons)
    if valid:
        klass = CLASS_APPROVED_COPY_VALID
        action = ACTION_READY
    elif status != STATUS_COPY_APPROVED:
        klass = f"WORKFLOW_{status or 'UNKNOWN'}"
        action = ACTION_REVIEW_EXISTING
    else:
        klass, action = _PRIMARY_TO_CLASS.get(
            pr or "MISSING_REVIEW",
            (CLASS_APPROVED_COPY_MISSING_REVIEW, ACTION_SEMANTIC_REVIEW),
        )
    return {
        "workflow_status": status or None,
        "production_valid": valid,
        "validity_class": klass,
        "validity_class_label": VALIDITY_UI_LABEL.get(
            klass, klass.replace("APPROVED_COPY_", "").replace("_", " ")
        ),
        "validity_reasons": reasons,
        "recommended_action": action,
        "validity_primary_reason": pr,
        "validity_stale": bool(verdict.get("stale")),
    }


def merge_validity_contract(copy_set: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    """Return copy_set dict with top-level validity contract fields merged in."""
    out = dict(copy_set)
    out.update(build_validity_contract(copy_set=copy_set, verdict=verdict))
    return out


async def enrich_copy_sets_with_validity(
    product_id: str, copy_sets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach production-validity contract fields to serialized Copy Sets (one PI load)."""
    if not copy_sets:
        return []
    from agent.services.copy_eligibility_service import copy_eligibility

    elig = await copy_eligibility(product_id)
    snap = await _latest_approved_snapshot(product_id)
    digest = pi_authority_digest(snap) if snap else None
    pname = await _product_name(product_id)
    out: list[dict[str, Any]] = []
    for cs in copy_sets:
        row = dict(cs)
        if "claim_review" not in row or row.get("claim_review") is None:
            row["claim_review"] = _parse_json(row.get("claim_review_json")) or {}
        if "provenance" not in row or row.get("provenance") is None:
            row["provenance"] = _parse_json(row.get("provenance_json")) or {}
        verdict = evaluate_copy_set_validity(
            copy_set=row,
            product_eligible=bool(elig.get("eligible")),
            product_eligibility_reasons=list(elig.get("reasons") or []),
            current_snapshot_id=str(snap["snapshot_id"]) if snap else None,
            current_snapshot_version=int(snap["version"]) if snap else None,
            current_authority_digest=digest,
            product_name=pname,
        )
        out.append(merge_validity_contract(cs, verdict))
    return out


async def enrich_copy_set_with_validity(copy_set: dict[str, Any]) -> dict[str, Any]:
    """Single-set enrichment (detail / get)."""
    pid = _clean(copy_set.get("product_id"))
    if not pid:
        return merge_validity_contract(
            copy_set,
            {
                "valid": False,
                "reasons": ["COPY_SET_MISSING_PRODUCT"],
                "stale": False,
                "primary_reason": None,
                "status": copy_set.get("status"),
            },
        )
    enriched = await enrich_copy_sets_with_validity(pid, [copy_set])
    return enriched[0]

