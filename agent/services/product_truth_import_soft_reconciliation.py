"""Governed SAFE import soft-field reconciliation for Product Truth.

Closes AA-AH MATERIAL_CHANGE_SAFE import revisions by SUPERSEDING the open
review draft while leaving the current APPROVED Product Truth snapshot untouched.

Does NOT:
  - approve import drafts into Product Truth
  - delete history
  - auto-close CLAIM_CONFLICT or elevated claim/review gates
  - touch copy_evidence / Copy Authority / Landbank
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.db.schema import get_db

REASON_CODE = "SAFE_IMPORT_SOFT_FIELD_RECONCILIATION"
SAFE_CREATED_BY = "codex-aa-ah-import"
EXPECTED_SAFE_COUNT = 549

ACTIONABLE = frozenset({"DRAFT", "READY_FOR_REVIEW", "NEEDS_REVISION"})
ELEVATED_GATES = frozenset(
    {
        "CLAIM_BLOCKED",
        "CLAIM_REVIEW_REQUIRED",
    }
)
ELEVATED_READINESS = frozenset(
    {
        "CLAIM_BLOCKED",
        "CLAIM_REVIEW_REQUIRED",
        "MISSING_REQUIRED_FIELDS",
    }
)

CORE_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "allowed_claims_json",
    "blocked_claims_json",
    "claim_gate",
    "claim_risk_level",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
)

SOFT_FIELDS = (
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
    "hook_angles_json",
    "cta_angles_json",
    "pain_points_json",
    "subhook_json",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    s = str(value).strip()
    if not s:
        return None
    if s[0] in "{[":
        try:
            return json.loads(s)
        except Exception:
            return s
    return s


def _norm(value: Any) -> Any:
    v = _loads(value)
    if v is None:
        return None
    if isinstance(v, str):
        s = re.sub(r"[ \t]+", " ", v.strip())
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s or None
    if isinstance(v, list):
        out = []
        for item in v:
            n = _norm(item)
            if n in (None, "", {}, []):
                continue
            out.append(n)
        return out
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for k in sorted(v.keys(), key=lambda x: str(x)):
            n = _norm(v[k])
            if n in (None, "", {}, []):
                continue
            out[str(k)] = n
        return out or None
    return v


def fields_equal(a: Any, b: Any) -> bool:
    return _norm(a) == _norm(b)


def core_product_truth_equal(draft: dict[str, Any], snap: dict[str, Any]) -> bool:
    for key in CORE_FIELDS:
        if not fields_equal(draft.get(key), snap.get(key)):
            return False
    return True


def snapshot_identity(snap: dict[str, Any]) -> dict[str, Any]:
    payload = {k: snap.get(k) for k in (*CORE_FIELDS, *SOFT_FIELDS, "version", "status")}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "snapshot_id": snap.get("snapshot_id"),
        "version": snap.get("version"),
        "approved_at": snap.get("approved_at"),
        "digest": digest,
    }


def _row(cur_row: Any) -> dict[str, Any]:
    return dict(cur_row) if cur_row is not None else {}


async def _latest_approved_by_product() -> dict[str, dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        """
        SELECT *
        FROM product_intelligence_snapshot
        WHERE status='APPROVED'
        ORDER BY version DESC, approved_at DESC, created_at DESC, snapshot_id DESC
        """
    )
    rows = await cur.fetchall()
    await cur.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rec = _row(row)
        pid = str(rec.get("product_id") or "")
        if pid and pid not in out:
            out[pid] = rec
    return out


async def _actionable_import_drafts() -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        """
        SELECT d.*, p.lifecycle_status, p.product_display_name, p.raw_product_title
        FROM product_intelligence_review_draft d
        JOIN product p ON p.id = d.product_id
        WHERE p.lifecycle_status = 'ACTIVE'
          AND d.created_by = ?
          AND d.review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION')
        ORDER BY d.updated_at DESC, d.created_at DESC, d.draft_id DESC
        """,
        (SAFE_CREATED_BY,),
    )
    rows = await cur.fetchall()
    await cur.close()
    # latest actionable per product
    by_pid: dict[str, dict[str, Any]] = {}
    for row in rows:
        rec = _row(row)
        pid = str(rec.get("product_id") or "")
        if pid and pid not in by_pid:
            by_pid[pid] = rec
    return list(by_pid.values())


def classify_candidate(draft: dict[str, Any], approved: dict[str, Any] | None) -> tuple[str, str]:
    """Return (bucket, reason). bucket in SAFE|REVIEW_REQUIRED|INELIGIBLE."""
    if not approved:
        return "INELIGIBLE", "NO_APPROVED_SNAPSHOT"
    if str(draft.get("created_by") or "") != SAFE_CREATED_BY:
        return "INELIGIBLE", "WRONG_CREATED_BY"
    status = str(draft.get("review_status") or "").upper()
    if status not in ACTIONABLE:
        return "INELIGIBLE", f"NOT_ACTIONABLE:{status or 'EMPTY'}"
    rev_snap = str(draft.get("revision_of_snapshot_id") or "").strip()
    cur_snap = str(approved.get("snapshot_id") or "").strip()
    if not rev_snap or rev_snap != cur_snap:
        return "INELIGIBLE", "REVISION_NOT_CURRENT_APPROVED"
    gate = str(draft.get("claim_gate") or "").upper()
    readiness = str(draft.get("readiness_status") or "").upper()
    if status == "NEEDS_REVISION" or gate in ELEVATED_GATES or readiness in ELEVATED_READINESS:
        return "REVIEW_REQUIRED", f"ELEVATED:{status}|{gate}|{readiness}"
    if not core_product_truth_equal(draft, approved):
        return "INELIGIBLE", "CORE_PRODUCT_TRUTH_DIFFERS"
    return "SAFE", "CORE_EQUAL_CLAIM_SAFE"


async def preview_import_soft_reconciliation() -> dict[str, Any]:
    approved = await _latest_approved_by_product()
    drafts = await _actionable_import_drafts()
    safe: list[dict[str, Any]] = []
    review_required: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    for d in drafts:
        pid = str(d.get("product_id") or "")
        snap = approved.get(pid)
        bucket, why = classify_candidate(d, snap)
        item = {
            "product_id": pid,
            "product_name": d.get("product_display_name") or d.get("raw_product_title"),
            "draft_id": d.get("draft_id"),
            "review_status": d.get("review_status"),
            "claim_gate": d.get("claim_gate"),
            "readiness_status": d.get("readiness_status"),
            "revision_of_snapshot_id": d.get("revision_of_snapshot_id"),
            "approved_snapshot_id": (snap or {}).get("snapshot_id"),
            "approved_version": (snap or {}).get("version"),
            "bucket": bucket,
            "reason": why,
            "snapshot_identity": snapshot_identity(snap) if snap else None,
        }
        if bucket == "SAFE":
            safe.append(item)
        elif bucket == "REVIEW_REQUIRED":
            review_required.append(item)
        else:
            ineligible.append(item)

    # Hub claim conflicts (separate source) — count only for operator surface
    db = await get_db()
    cur = await db.execute(
        """
        SELECT COUNT(DISTINCT d.product_id) AS c
        FROM product_intelligence_review_draft d
        JOIN product p ON p.id = d.product_id
        WHERE p.lifecycle_status='ACTIVE'
          AND d.created_by = 'copywriting_hub_rev2_import'
          AND d.review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION')
        """
    )
    hub_row = await cur.fetchone()
    await cur.close()
    hub_claim_open = int(hub_row["c"] if hub_row else 0)

    return {
        "created_by_filter": SAFE_CREATED_BY,
        "reason_code": REASON_CODE,
        "policy": {
            "default_action": "KEEP_APPROVED_PRODUCT_TRUTH_AND_SUPERSEDE_IMPORT_REVISION",
            "approves_import_into_product_truth": False,
            "deletes_history": False,
            "excludes_review_required": True,
            "excludes_claim_conflict": True,
        },
        "safe_candidate_count": len(safe),
        "review_required_count": len(review_required),
        "ineligible_count": len(ineligible),
        "hub_claim_conflict_open_count": hub_claim_open,
        "expected_safe_count": EXPECTED_SAFE_COUNT,
        "matches_expected_safe_count": len(safe) == EXPECTED_SAFE_COUNT,
        "safe_candidates": safe,
        "review_required": review_required,
        "ineligible_sample": ineligible[:20],
    }


def resolve_db_path() -> Path:
    """Canonical DB path used by runtime."""
    import os

    override = (
        os.environ.get("FLOW_AGENT_DB_PATH")
        or os.environ.get("BOSMAX_DB_PATH")
        or ""
    ).strip()
    if override:
        return Path(override)
    # Prefer external canonical path used by :8100
    external = Path(r"C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db")
    if external.is_file():
        return external
    return Path(__file__).resolve().parents[2] / "flow_agent.db"


def resolve_receipt_dir() -> Path:
    base = Path(r"C:\Users\USER\Desktop\_bosmax_runtime\governance_receipts")
    base.mkdir(parents=True, exist_ok=True)
    return base


def backup_canonical_db(*, label: str) -> dict[str, Any]:
    db_path = resolve_db_path()
    if not db_path.is_file():
        raise FileNotFoundError(f"DB_NOT_FOUND:{db_path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db_path.with_name(f"{db_path.name}.pre-import-soft-recon-{label}-{stamp}")
    shutil.copy2(db_path, backup)
    h = hashlib.sha256()
    with backup.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {
        "db_path": str(db_path),
        "backup_path": str(backup),
        "sha256": h.hexdigest(),
        "size_bytes": backup.stat().st_size,
    }


async def _supersede_one_draft(
    *,
    draft_id: str,
    existing_note: str | None,
    actor: str,
    batch_id: str,
    reason: str,
) -> bool:
    """Transition one open draft to SUPERSEDED. Returns True if a row was updated."""
    db = await get_db()
    now = _now_iso()
    audit = (
        f"[{REASON_CODE} at {now}: {reason} by {actor}; batch_id={batch_id}; "
        "KEEP_APPROVED_PRODUCT_TRUTH; import soft values NOT promoted; "
        "content and provenance preserved]"
    )
    note = "\n".join(part for part in (str(existing_note or "").strip(), audit) if part)
    cur = await db.execute(
        """
        UPDATE product_intelligence_review_draft
        SET review_status='SUPERSEDED',
            reviewer_note=?,
            reviewed_by=?,
            updated_at=?
        WHERE draft_id=?
          AND review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION')
        """,
        (note, actor, now, draft_id),
    )
    await db.commit()
    return int(cur.rowcount or 0) > 0


async def close_safe_import_soft_revisions(
    *,
    confirm: bool,
    actor: str = "operator",
    confirm_phrase: str | None = None,
    expected_count: int | None = EXPECTED_SAFE_COUNT,
    implementation_sha: str | None = None,
) -> dict[str, Any]:
    """Governed batch close. Requires confirm=True and exact confirmation phrase."""
    required_phrase = "CLOSE SAFE IMPORT REVISIONS"
    if not confirm:
        raise ValueError("CONFIRMATION_REQUIRED")
    if (confirm_phrase or "").strip().upper() != required_phrase:
        raise ValueError("CONFIRM_PHRASE_MISMATCH")

    preview = await preview_import_soft_reconciliation()
    safe = preview["safe_candidates"]
    if expected_count is not None and len(safe) != int(expected_count):
        return {
            "status": "ABORTED_COUNT_MISMATCH",
            "expected_count": expected_count,
            "actual_safe_count": len(safe),
            "preview": {
                "safe_candidate_count": preview["safe_candidate_count"],
                "review_required_count": preview["review_required_count"],
                "hub_claim_conflict_open_count": preview["hub_claim_conflict_open_count"],
                "matches_expected_safe_count": preview["matches_expected_safe_count"],
            },
            "mutations": 0,
        }

    batch_id = str(uuid.uuid4())
    backup = backup_canonical_db(label=batch_id[:8])
    started = _now_iso()

    # Pre-capture snapshot identities for invariance proof
    pre_identities = {
        c["product_id"]: c.get("snapshot_identity") for c in safe if c.get("product_id")
    }

    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skipped_idempotent: list[dict[str, Any]] = []

    # Re-load approved map for race-safe revalidation
    approved = await _latest_approved_by_product()
    db = await get_db()

    for cand in safe:
        pid = cand["product_id"]
        draft_id = str(cand["draft_id"])
        try:
            cur = await db.execute(
                "SELECT * FROM product_intelligence_review_draft WHERE draft_id=?",
                (draft_id,),
            )
            row = await cur.fetchone()
            await cur.close()
            if row is None:
                failures.append(
                    {
                        "product_id": pid,
                        "draft_id": draft_id,
                        "error": "DRAFT_MISSING",
                    }
                )
                continue
            draft = _row(row)
            snap = approved.get(pid)
            # refresh snap from DB in case approved map stale
            if snap is None:
                failures.append(
                    {
                        "product_id": pid,
                        "draft_id": draft_id,
                        "error": "NO_APPROVED_SNAPSHOT",
                    }
                )
                continue
            bucket, why = classify_candidate(draft, snap)
            if bucket != "SAFE":
                if str(draft.get("review_status") or "").upper() == "SUPERSEDED":
                    skipped_idempotent.append(
                        {
                            "product_id": pid,
                            "draft_id": draft_id,
                            "status": "ALREADY_SUPERSEDED",
                        }
                    )
                    continue
                failures.append(
                    {
                        "product_id": pid,
                        "draft_id": draft_id,
                        "error": f"REVALIDATION_FAILED:{why}",
                    }
                )
                continue

            pre_status = draft.get("review_status")
            ok = await _supersede_one_draft(
                draft_id=draft_id,
                existing_note=draft.get("reviewer_note"),
                actor=actor,
                batch_id=batch_id,
                reason=REASON_CODE,
            )
            if not ok:
                # concurrent close
                cur2 = await db.execute(
                    "SELECT review_status FROM product_intelligence_review_draft WHERE draft_id=?",
                    (draft_id,),
                )
                after = await cur2.fetchone()
                await cur2.close()
                st = str((after["review_status"] if after else "") or "").upper()
                if st == "SUPERSEDED":
                    skipped_idempotent.append(
                        {
                            "product_id": pid,
                            "draft_id": draft_id,
                            "status": "ALREADY_SUPERSEDED",
                        }
                    )
                else:
                    failures.append(
                        {
                            "product_id": pid,
                            "draft_id": draft_id,
                            "error": f"UPDATE_NO_ROW status={st}",
                        }
                    )
                continue

            successes.append(
                {
                    "product_id": pid,
                    "draft_id": draft_id,
                    "previous_status": pre_status,
                    "new_status": "SUPERSEDED",
                    "approved_snapshot_id": snap.get("snapshot_id"),
                    "approved_version": snap.get("version"),
                    "pre_snapshot_identity": pre_identities.get(pid),
                }
            )
        except Exception as exc:  # noqa: BLE001 — batch partial failure reporting
            failures.append(
                {
                    "product_id": pid,
                    "draft_id": draft_id,
                    "error": str(exc)[:300],
                }
            )

    # Post: snapshot identity invariance for successes
    approved_after = await _latest_approved_by_product()
    identity_mismatches: list[dict[str, Any]] = []
    for item in successes:
        pid = item["product_id"]
        snap = approved_after.get(pid)
        after_id = snapshot_identity(snap) if snap else None
        before_id = item.get("pre_snapshot_identity")
        item["post_snapshot_identity"] = after_id
        if before_id and after_id and before_id.get("digest") != after_id.get("digest"):
            identity_mismatches.append(
                {"product_id": pid, "before": before_id, "after": after_id}
            )

    finished = _now_iso()
    receipt = {
        "batch_id": batch_id,
        "status": "COMPLETED" if not failures else "COMPLETED_WITH_FAILURES",
        "started_at": started,
        "finished_at": finished,
        "reason": REASON_CODE,
        "actor": actor,
        "implementation_sha": implementation_sha,
        "confirm_phrase": required_phrase,
        "backup": backup,
        "candidate_count": len(safe),
        "success_count": len(successes),
        "failure_count": len(failures),
        "idempotent_skip_count": len(skipped_idempotent),
        "successes": successes,
        "failures": failures,
        "skipped_idempotent": skipped_idempotent,
        "snapshot_identity_mismatches": identity_mismatches,
        "excluded": {
            "review_required_count": preview["review_required_count"],
            "hub_claim_conflict_open_count": preview["hub_claim_conflict_open_count"],
            "ineligible_count": preview["ineligible_count"],
        },
        "policy": preview["policy"],
    }

    receipt_dir = resolve_receipt_dir()
    receipt_path = receipt_dir / f"import-soft-recon-{batch_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def core_equal_for_import_guard(draft_fields: dict[str, Any], approved: dict[str, Any]) -> bool:
    """Public helper for importers: core PT equal after soft-field import."""
    return core_product_truth_equal(draft_fields, approved)
