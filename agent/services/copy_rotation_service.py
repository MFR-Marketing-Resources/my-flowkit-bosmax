"""Copy Rotation service — the Script Library's selection engine.

Owner scale contract (2026-07-19): up to 200 contents/day (~6000/month) with NO
duplicate CONTENT on-platform. The uniqueness law is the COMBINATION
(script x avatar x scene), not the script alone: one approved script may be
REUSED with different visuals up to ``REUSE_CAP`` times (owner decision: 15),
which is what makes the library token-cheap — 251 avatars x 20 scenes gives a
single script thousands of visually-unique presentations, so the DeepSeek call
is paid once and amortised across reuses.

Scripts are PER-PRODUCT. Similar products (owner's example: two vanilla car
perfumes) share scripts only via an EXPLICIT clone — the clone re-enters review
against the TARGET product's claim safety, never auto-approved, because copy
that is claim-safe for one product is not automatically safe for another.

Selection is DETERMINISTIC (repeatable, never random), least-recently-used
first so fatigue spreads evenly:
  order: never-used first -> oldest last_used_at -> lowest usage_count ->
         oldest created_at -> copy_set_id (total order tiebreak)
Round-robin wrap-around applies when the batch is larger than the pool — every
slot is still filled, and the per-use cap is enforced at usage-record time.

This service is pure library logic: it never calls a provider and never
approves anything. Reuses copy_set (NO parallel DB — repo law #257) and the
Phase-1 usage/fatigue columns (usage_count / last_used_at / archived).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from agent.db import crud
from agent.services.copy_set_service import (
    STATUS_COPY_APPROVED,
    STATUS_COPY_REVIEW_REQUIRED,
    _dedupe_key_for,
    scan_copy_safety,
    serialize_copy_set,
)
from agent.services.copy_usage_service import increment_copy_usage

logger = logging.getLogger(__name__)

# Owner decision 2026-07-19: one script may be reused (with different visuals)
# at most this many times before rotation retires it.
REUSE_CAP = 15

SOURCE_CLONE = "CLONE_FROM_SIMILAR_PRODUCT"


def _usage_count(row: dict) -> int:
    try:
        return int(row.get("usage_count") or 0)
    except (TypeError, ValueError):
        return 0


def _eligible(row: dict) -> bool:
    return (
        row.get("status") == STATUS_COPY_APPROVED
        and not int(row.get("archived") or 0)
        and _usage_count(row) < REUSE_CAP
    )


def _rotation_sort_key(row: dict):
    last_used = str(row.get("last_used_at") or "")
    return (
        0 if not last_used else 1,          # never-used first
        last_used,                           # then oldest last use
        _usage_count(row),                   # then least-used
        str(row.get("created_at") or ""),    # then oldest
        str(row.get("copy_set_id") or ""),   # total order
    )


async def list_eligible_copy_sets(product_id: str) -> list[dict]:
    """The rotation-eligible approved pool, in deterministic rotation order.

    ONE definition of "usable approved copy" shared by rotation and by copy-pool
    readiness, so the readiness report can never disagree with what rotation will
    actually hand out. Eligible = COPY_APPROVED, not archived, under REUSE_CAP.
    """
    rows = await crud.list_copy_sets_for_product(product_id)
    return sorted((r for r in rows if _eligible(r)), key=_rotation_sort_key)


async def select_rotation_copy_sets(product_id: str, count: int) -> dict[str, Any]:
    """Pick ``count`` approved copy sets for a batch, deterministically.

    Returns {"items": [copy_set...], "pool_size": N, "warnings": [...]} —
    items has EXACTLY ``count`` entries via wrap-around when the pool is
    smaller (each wrap repetition is a legitimate reuse against the cap), or
    is EMPTY with NO_APPROVED_COPY_AVAILABLE when nothing is eligible: the
    caller must then generate + approve new scripts (fail-closed, never a
    silent fallback to duplicate or unapproved copy).
    """
    count = max(1, int(count or 1))
    pool = await list_eligible_copy_sets(product_id)
    warnings: list[str] = []
    if not pool:
        return {
            "items": [],
            "pool_size": 0,
            "warnings": ["NO_APPROVED_COPY_AVAILABLE:generate_and_approve_scripts_first"],
        }
    if len(pool) < count:
        warnings.append(
            f"POOL_SMALLER_THAN_BATCH:{len(pool)}<{count}:scripts_repeat_with_different_visuals"
        )
    items = [pool[i % len(pool)] for i in range(count)]
    return {"items": items, "pool_size": len(pool), "warnings": warnings}


async def record_rotation_usage(copy_set_id: str, mode: str) -> dict[str, Any]:
    """Record one real use (a package was actually created from this script)."""
    return await increment_copy_usage(copy_set_id, mode)


# ── Similarity backfill (P3) ──────────────────────────────────────────────
# The near-dup door (ai_copy_assist) only annotates NEW candidates; scripts
# created before the door existed carry no similarity metadata. This scan
# recomputes it for one product's whole pool. ANNOTATION ONLY — it never
# touches status (the review decision stays human).


def _similarity_fields(row: dict) -> dict[str, Any]:
    """Normalize a raw copy_set row to the fields dict the similarity
    service compares (raw rows carry usp_set_json; the comparator reads
    usp_set as a list)."""
    try:
        usp = json.loads(row.get("usp_set_json") or "[]")
    except (TypeError, ValueError):
        usp = []
    return {
        "copy_set_id": row.get("copy_set_id"),
        "angle": row.get("angle") or "",
        "hook": row.get("hook") or "",
        "subhook": row.get("subhook") or "",
        "usp_set": usp if isinstance(usp, list) else [],
        "cta": row.get("cta") or "",
    }


async def backfill_similarity_scan(
    product_id: str, *, threshold: float = 0.80, apply: bool = False
) -> dict[str, Any]:
    """Recompute near-dup + uniqueness metadata for a product's script pool.

    Directional: each row is compared for NEAR-DUP against rows created
    BEFORE it (the earliest of a duplicate pair is the original and stays
    unflagged; the later one points back). uniqueness_score is measured
    against ALL OTHER approved rows — how unique the script is in the pool
    as it stands today.

    Dry-run by default: ``apply=False`` reports without writing; ``apply=True``
    persists uniqueness_score / similar_to_copy_set_id / similarity_score.
    """
    from agent.services.copy_similarity_service import (
        compute_uniqueness_score,
        find_nearest,
    )

    threshold = float(threshold)
    rows = await crud.list_copy_sets_for_product(product_id)
    rows = sorted(
        rows,
        key=lambda r: (str(r.get("created_at") or ""), str(r.get("copy_set_id") or "")),
    )
    fields = [_similarity_fields(r) for r in rows]
    approved = [
        f for f, r in zip(fields, rows) if r.get("status") == STATUS_COPY_APPROVED
    ]

    items: list[dict[str, Any]] = []
    flagged = 0
    updated = 0
    for idx, (row, f) in enumerate(zip(rows, fields)):
        nearest, score = find_nearest(f, fields[:idx], threshold=threshold)
        others_approved = [a for a in approved if a is not f]
        uniqueness = round(compute_uniqueness_score(f, others_approved), 4)
        nearest_id = nearest.get("copy_set_id") if nearest else None
        similarity = round(score, 4) if nearest else None
        if nearest_id:
            flagged += 1

        changed = (
            (row.get("similar_to_copy_set_id") or None) != nearest_id
            or row.get("similarity_score") != similarity
            or row.get("uniqueness_score") != uniqueness
        )
        entry: dict[str, Any] = {
            "copy_set_id": row.get("copy_set_id"),
            "status": row.get("status"),
            "hook": row.get("hook") or "",
            "similar_to_copy_set_id": nearest_id,
            "similarity_score": similarity,
            "uniqueness_score": uniqueness,
            "flagged": nearest_id is not None,
            "changed": changed,
            "applied": False,
        }
        if apply and changed:
            await crud.update_copy_set(
                row["copy_set_id"],
                uniqueness_score=uniqueness,
                similar_to_copy_set_id=nearest_id,
                similarity_score=similarity,
            )
            updated += 1
            entry["applied"] = True
        items.append(entry)

    return {
        "product_id": product_id,
        "scanned": len(rows),
        "flagged": flagged,
        "updated": updated,
        "apply": apply,
        "threshold": threshold,
        "items": items,
    }


# ── Content combination ledger (P2) ───────────────────────────────────────
# The on-platform uniqueness law: a CONTENT is the combination
# (script x visual identity x scene). Each produced combination is recorded
# once under a UNIQUE fingerprint; producing the same combination again is
# refused — that is the mathematical anti-duplicate guarantee behind bulk.


def visual_key_for_plan(plan: dict) -> dict[str, str]:
    """The visual identity of one planner item, per logical mode.

    T2V/HYBRID: the avatar face. I2V: character + scene + style references.
    F2V: the finished frame IS the visual. All modes include the scene
    context, because the same avatar in a different setting is a different
    visual on-platform.
    """
    mode = str(plan.get("logical_mode") or "").upper()
    key: dict[str, str] = {
        "scene_context": str(plan.get("scene_context_override") or ""),
    }
    if mode in ("T2V", "HYBRID"):
        key["avatar_code"] = str(plan.get("avatar_code") or "")
    elif mode == "I2V":
        key["character_asset_id"] = str(plan.get("character_asset_id") or "")
        key["scene_asset_id"] = str(plan.get("scene_asset_id") or "")
        key["style_asset_id"] = str(plan.get("style_asset_id") or "")
    elif mode == "F2V":
        key["finished_frame_asset_id"] = str(plan.get("finished_frame_asset_id") or "")
    return key


def script_key_for_plan(plan: dict, *, dialogue_fingerprint: str | None = None) -> str:
    """The script identity, strongest evidence first.

    Library copy_set = FIXED text, known before compile. Without lineage the
    hook is only an ANGLE — DIFF_DIALOGUE strategies intentionally diverge
    the compiled dialogue from the same angle, so post-compile the real
    script identity is the dialogue fingerprint, and the hook text is only
    the pre-compile fallback.
    """
    copy_set_id = plan.get("copy_set_id")
    if copy_set_id:
        return f"copy_set:{copy_set_id}"
    if dialogue_fingerprint:
        return f"dialogue:{dialogue_fingerprint}"
    hook = " ".join(str(plan.get("hook_override") or "").lower().split())
    return f"hook:{hook}"


def combination_fingerprint(
    product_id: str, logical_mode: str, script_key: str, visual_key: dict[str, str]
) -> str:
    """Deterministic sha256 over the canonical combination identity."""
    canonical = json.dumps(
        {
            "product_id": str(product_id),
            "logical_mode": str(logical_mode or "").upper(),
            "script_key": script_key,
            "visual_key": {k: visual_key[k] for k in sorted(visual_key)},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_combination_fingerprint(
    product_id: str, plan: dict, *, dialogue_fingerprint: str | None = None
) -> str:
    """Fingerprint one planner item plan directly."""
    return combination_fingerprint(
        product_id,
        str(plan.get("logical_mode") or ""),
        script_key_for_plan(plan, dialogue_fingerprint=dialogue_fingerprint),
        visual_key_for_plan(plan),
    )


# A ledger burn is released ONLY from a package that is provably DEAD — it can
# never fire again, so it can never produce the combination. A package that is
# merely un-fired (APPROVED/QUEUED) stays blocking: it could still be fired, and
# releasing it would let two prepared batches carry the same dialogue.
_DEAD_PRODUCTION_STATES = {"CANCELLED", "FAILED"}
_DEAD_PACKAGE_STATES = {"BLOCKED", "ARCHIVED"}


async def _combination_is_spent(row: dict) -> bool:
    """Does this ledger row still legitimately consume its dialogue?

    The ledger exists to stop the same script x avatar x scene being *produced*
    twice, but the row is burned at PREPARE time — before anything is approved,
    enqueued or fired. A batch that was cancelled or blocked therefore consumed a
    dialogue while producing nothing, permanently shrinking a finite approved-copy
    pool (live: on product 6483d624, 14 of 17 HYBRID burns produced zero video and
    the pool hit fresh=0, blocking every bulk plan).

    Spent (keeps blocking) when ANY of:
      * an artifact exists — it was really produced;
      * a provider job id exists — it reached the provider, credit may be spent;
      * the package is still alive (not dead) — it can still fire;
      * anything cannot be proven — stay conservative.
    Released only for a DEAD package that produced nothing.
    """
    wgp_id = row.get("workspace_generation_package_id")
    if not wgp_id:
        return True  # unattributed burn — cannot prove anything
    pkg = await crud.get_workspace_generation_package(wgp_id)
    if not pkg:
        return True  # package gone — stay conservative
    if pkg.get("production_job_id"):
        return True  # reached the provider; credit may have been spent
    raw = pkg.get("artifact_media_ids_json")
    if raw:
        try:
            if json.loads(raw):
                return True  # a real artifact exists
        except (TypeError, ValueError):
            return True  # unreadable — stay conservative
    prod_state = str(pkg.get("production_status") or "").upper()
    pkg_state = str(pkg.get("status") or "").upper()
    is_dead = prod_state in _DEAD_PRODUCTION_STATES or pkg_state in _DEAD_PACKAGE_STATES
    return not is_dead  # alive => still spent; dead + nothing produced => released


async def combination_already_used(fingerprint: str) -> bool:
    row = await crud.get_content_combination_by_fingerprint(fingerprint)
    if row is None:
        return False
    return await _combination_is_spent(row)


async def record_combination(
    *,
    product_id: str,
    logical_mode: str,
    plan: dict,
    fingerprint: str,
    dialogue_fingerprint: str | None = None,
    workspace_generation_package_id: str | None = None,
    batch_run_id: str | None = None,
) -> dict[str, Any] | None:
    """Record one PRODUCED combination. Returns None when the fingerprint is
    already in the ledger AND that row really was produced (duplicate
    combination — caller must not ship it).

    If the existing row is RECLAIMABLE (its package never reached the provider
    and produced no artifact — a cancelled or never-fired prepare), the row is
    re-attributed to this attempt instead of refusing. Nothing is deleted: the
    ledger keeps exactly one row per combination fingerprint, so the UNIQUE
    index remains the duplicate defence, and a dialogue is only spent by work
    that actually produced something.
    """
    created = await crud.create_content_combination(
        product_id=product_id,
        logical_mode=str(logical_mode or "").upper(),
        copy_set_id=plan.get("copy_set_id"),
        script_key=script_key_for_plan(plan, dialogue_fingerprint=dialogue_fingerprint),
        visual_key_json=json.dumps(visual_key_for_plan(plan), sort_keys=True),
        combination_fingerprint=fingerprint,
        workspace_generation_package_id=workspace_generation_package_id,
        batch_run_id=batch_run_id,
    )
    if created is not None:
        return created
    existing = await crud.get_content_combination_by_fingerprint(fingerprint)
    if existing is None:
        return None
    if await _combination_is_spent(existing):
        return None  # genuinely produced before — refuse, exactly as before
    if not workspace_generation_package_id:
        return None  # nothing to re-attribute it to
    logger.info(
        "LEDGER_RECLAIM fingerprint=%s from wgp=%s -> wgp=%s (previous attempt "
        "produced nothing)", fingerprint[:12],
        existing.get("workspace_generation_package_id"), workspace_generation_package_id,
    )
    return await crud.reattribute_content_combination(
        fingerprint,
        workspace_generation_package_id=workspace_generation_package_id,
        batch_run_id=batch_run_id,
    )


async def clone_copy_set_to_product(
    copy_set_id: str, target_product_id: str
) -> dict[str, Any]:
    """Share a script with a SIMILAR product — explicit, never automatic.

    The clone re-enters review (COPY_REVIEW_REQUIRED) with a fresh claim-safety
    scan against the TARGET product: claim-safe copy for product A is not
    automatically safe for product B. Usage counters start at zero — the clone
    is a new library entry with its own reuse budget; lineage is recorded in
    provenance.
    """
    source = await crud.get_copy_set(copy_set_id)
    if not source:
        raise ValueError("COPY_SET_NOT_FOUND")
    target = await crud.get_product(target_product_id)
    if not target:
        raise ValueError("PRODUCT_NOT_FOUND")
    if str(source.get("product_id")) == str(target_product_id):
        raise ValueError("CLONE_TARGET_IS_SOURCE_PRODUCT")

    fields = {
        "angle": source.get("angle") or "",
        "hook": source.get("hook") or "",
        "subhook": source.get("subhook") or "",
        "usp_set": json.loads(source.get("usp_set_json") or "[]"),
        "cta": source.get("cta") or "",
        "platform": source.get("platform") or "TIKTOK",
        "language": source.get("language") or "BM_MS",
        "route_type": source.get("route_type") or "DIRECT",
        "formula_family": source.get("formula_family") or "HSO",
    }
    dedupe_key = _dedupe_key_for(target_product_id, fields)
    existing = await crud.find_copy_set_by_dedupe_key(dedupe_key)
    if existing:
        return {
            "copy_set": serialize_copy_set(existing),
            "created": False,
            "dedupe_match": True,
            "warnings": ["DEDUPE_MATCH_EXISTING_COPY_SET"],
        }

    safety = scan_copy_safety(fields, product_id=target_product_id)
    warnings: list[str] = []
    if not safety["safe"]:
        warnings.extend(safety["violations"])

    row = await crud.create_copy_set(
        target_product_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set_json=json.dumps(fields["usp_set"]),
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
        formula_family=fields["formula_family"],
        status=STATUS_COPY_REVIEW_REQUIRED,
        dedupe_key=dedupe_key,
        source=SOURCE_CLONE,
        provenance_json=json.dumps({
            "cloned_from_copy_set_id": copy_set_id,
            "cloned_from_product_id": source.get("product_id"),
            "safety_at_clone": safety,
        }),
        claim_review_json=json.dumps({"safety": safety, "cloned": True}),
    )
    logger.info(
        "copy clone: %s (product %s) -> %s (product %s)",
        copy_set_id, source.get("product_id"),
        row.get("copy_set_id"), target_product_id,
    )
    return {
        "copy_set": serialize_copy_set(row),
        "created": True,
        "dedupe_match": False,
        "warnings": warnings,
    }
