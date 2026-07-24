"""Compose copy sets from atomic components.

Phase C1 of `.ai/architecture/COPY_ANGLE_AND_COMPONENT_ARCHITECTURE.md`.

This is the CONSUMER of the Phase B1 pool, and therefore the thing that defines
what a component must be. Its output slots mirror `CopySetResponse` exactly
(angle / hook / subhook / usp_set / cta) — which is why the component
vocabulary is HOOK/SUBHOOK/USP_SET/CTA and why there is no `BODY`.

FOUR PROPERTIES, each one load-bearing
--------------------------------------
1. ANGLE-COHERENT. Components only combine inside their own angle. A hook about
   infant colic must never meet a subhook about post-work body aches. Angles are
   alternatives, not factors.
2. DETERMINISTIC. Same pool + same request => same output, always. Mirrors
   `copy_rotation_service`, which is explicitly "repeatable, never random".
   Nothing here calls random() or reads the clock.
3. LRU-FIRST. Components are consumed least-used-first so fatigue spreads
   evenly instead of hammering whichever hook happens to sort first.
4. ANGLE ROUND-ROBIN. Requests are spread ACROSS angles before going deep into
   any one of them. This is the anti-monoculture property built into the engine
   itself: the failure this whole workstream exists to fix was 57 of 58 sets
   landing on one theme, and a composer that drained angle 1 before touching
   angle 2 would reproduce it exactly.

The hook is the fastest-varying digit of the combination odometer, so the first
N compositions differ in the most visible element rather than sharing a hook
and differing only in the CTA.

Composed output is NOT approved copy. It still flows through the existing
dedupe / near-dup / claim gates unchanged — this module only assembles.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from agent.services.copy_component_service import (
    COMPONENT_TYPES,
    CTA,
    HOOK,
    STATUS_APPROVED,
    SUBHOOK,
    USP_SET,
)

__all__ = ["compose", "combination_fingerprint", "compose_and_persist"]

# Composed copy is NEVER approved copy: it lands COPY_REVIEW_REQUIRED and flows
# through the SAME dedupe / claim / near-dup gates as AI-assist copy, so the
# Copy Set Registry treats a composed row identically to a generated one.
SOURCE_COMPONENT_COMPOSER = "COMPONENT_COMPOSER"

_GLOBAL_ANGLE = ""
# Odometer digit order: leftmost varies FASTEST.
_SLOT_ORDER = (HOOK, SUBHOOK, USP_SET, CTA)


def combination_fingerprint(component_ids: Iterable[str], formula: str = "") -> str:
    """Stable identity of one composed copy.

    Order-insensitive over components so the same four parts cannot be
    re-emitted as a 'new' combination by shuffling them.

    FORMULA-INDEPENDENT by design. The composer does not use the formula to
    change any text — hook/subhook/usp/cta all come from components; the formula
    is only a downstream TAG. So the copy TEXT of a combination is identical
    whatever formula is attached, and the persist dedupe_key (which is text-based
    and formula-blind) treats them as one. If the fingerprint counted formula,
    the same components under a different formula would look like a 'new'
    combination, get composed, then collapse on dedupe — wasting the slot and
    making re-runs with different formula params re-tread old ground. The
    `formula` argument is accepted for call-site compatibility and ignored.
    """
    _ = formula
    basis = "|".join(sorted(str(c) for c in component_ids))
    return "cc_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _is_live(component: dict[str, Any]) -> bool:
    return (
        not int(component.get("archived") or 0)
        and str(component.get("status") or "") == STATUS_APPROVED
    )


def _lru_key(component: dict[str, Any]) -> tuple:
    """Least-used first, then oldest use, then a total-order tiebreak so the
    ordering is fully determined even when usage is identical."""
    return (
        int(component.get("usage_count") or 0),
        str(component.get("last_used_at") or ""),
        str(component.get("component_id") or ""),
    )


def _pools_for_angle(
    components: Iterable[dict[str, Any]], angle_key: str
) -> dict[str, list[dict[str, Any]]]:
    """Per-type pools for one angle, LRU-sorted, with global components folded
    in (an empty angle_key means 'applies to every angle' — how CTAs behave)."""
    pools: dict[str, list[dict[str, Any]]] = {t: [] for t in COMPONENT_TYPES}
    for c in components:
        if not _is_live(c):
            continue
        ctype = str(c.get("component_type") or "")
        if ctype not in pools:
            continue
        akey = str(c.get("angle_key") or _GLOBAL_ANGLE)
        if akey in (angle_key, _GLOBAL_ANGLE):
            pools[ctype].append(c)
    for ctype in pools:
        pools[ctype].sort(key=_lru_key)
    return pools


def _usp_value(component: dict[str, Any]) -> list[str]:
    """USP_SET content is a JSON array; tolerate a plain string too."""
    import json

    raw = component.get("content")
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    text = str(raw or "").strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:  # noqa: BLE001
            pass
    return [text] if text else []


def compose(
    components: Iterable[dict[str, Any]],
    angles: list[dict[str, Any]],
    count: int,
    *,
    formula_families: list[str] | None = None,
    exclude_fingerprints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Assemble up to `count` distinct copy sets from the pool.

    `angles` are the Phase A records ({'angle_key', 'label', ...}); their ORDER
    is the round-robin order.

    Never raises and never pads: if the pool cannot supply `count` distinct
    combinations it returns what it can plus a `shortfall`, because silently
    emitting duplicates is exactly the monoculture this workstream is fixing.
    """
    components = list(components or [])
    angles = [a for a in (angles or []) if a and a.get("angle_key")]
    formulas = [f for f in (formula_families or []) if str(f).strip()] or [""]
    want = max(0, int(count or 0))
    seen: set[str] = {str(f) for f in (exclude_fingerprints or [])}

    if not want or not angles:
        return {
            "items": [], "requested": want, "produced": 0, "shortfall": want,
            "blocked_angles": [a["angle_key"] for a in angles], "warnings": [],
        }

    warnings: list[str] = []
    per_angle: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    for angle in angles:
        akey = str(angle["angle_key"])
        pools = _pools_for_angle(components, akey)
        missing = [t for t in COMPONENT_TYPES if not pools[t]]
        if missing:
            blocked.append(akey)
            warnings.append(f"ANGLE_BLOCKED:{akey}:missing={','.join(missing)}")
            continue
        per_angle[akey] = {"angle": angle, "pools": pools, "cursor": 0}

    items: list[dict[str, Any]] = []
    live = [a for a in angles if str(a["angle_key"]) in per_angle]
    exhausted: set[str] = set()

    # Round-robin across angles; within an angle walk the odometer with HOOK as
    # the fastest-varying digit.
    while len(items) < want and len(exhausted) < len(live):
        progressed = False
        for angle in live:
            if len(items) >= want:
                break
            akey = str(angle["angle_key"])
            if akey in exhausted:
                continue
            state = per_angle[akey]
            pools = state["pools"]
            sizes = [len(pools[t]) for t in _SLOT_ORDER]
            # The odometer walks COMPONENT combinations only. Formula is NOT a
            # dimension of it — it does not change any text, so counting it here
            # would only manufacture same-text duplicates that dedupe kills.
            total = 1
            for s in sizes:
                total *= s

            picked = None
            while state["cursor"] < total:
                k = state["cursor"]
                state["cursor"] += 1
                rem = k
                chosen: dict[str, Any] = {}
                for slot, size in zip(_SLOT_ORDER, sizes):
                    chosen[slot] = pools[slot][rem % size]
                    rem //= size
                ids = [str(chosen[s].get("component_id") or "") for s in _SLOT_ORDER]
                fp = combination_fingerprint(ids)
                if fp in seen:
                    continue
                seen.add(fp)
                picked = (chosen, ids, fp)
                break

            if picked is None:
                exhausted.add(akey)
                continue

            chosen, ids, fp = picked
            # Formula is a rotating TAG assigned per emitted item, so a batch
            # carries varied formula labels across DISTINCT combinations instead
            # of stamping every combination with the first formula.
            formula = formulas[len(items) % len(formulas)]
            items.append({
                "angle_key": akey,
                "angle": str(angle.get("label") or angle.get("angle_label") or ""),
                "hook": str(chosen[HOOK].get("content") or ""),
                "subhook": str(chosen[SUBHOOK].get("content") or ""),
                "usp_set": _usp_value(chosen[USP_SET]),
                "cta": str(chosen[CTA].get("content") or ""),
                "formula_family": formula,
                "component_ids": ids,
                "combination_fingerprint": fp,
            })
            progressed = True
        if not progressed:
            break

    if blocked:
        warnings.append(f"BLOCKED_ANGLE_COUNT:{len(blocked)}")

    # Phase C2 — every composition reports its own angle spread. Round-robin
    # makes a skew unlikely, but a pool that is deep on one angle and shallow on
    # another still produces one, and the whole point of the coverage gate is
    # that nothing else in the lane measures this.
    from agent.services.copy_coverage_service import evaluate_coverage

    coverage = evaluate_coverage(
        items,
        [str(a["angle_key"]) for a in angles],
        labels={
            str(a["angle_key"]): str(a.get("label") or a.get("angle_label") or "")
            for a in angles
        },
    )
    warnings.extend(coverage["warnings"])

    return {
        "items": items,
        "requested": want,
        "produced": len(items),
        "shortfall": max(0, want - len(items)),
        "blocked_angles": blocked,
        "coverage": coverage,
        "warnings": warnings,
    }


# ── persist: pool → copy_set rows (the operator-facing capstone) ───────────────


def _angles_from_pool(components: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct the angle list (key + label) from the components themselves.

    Preserves first-seen order so composition is deterministic without a second
    trip to the persona derivation.
    """
    seen: dict[str, str] = {}
    for c in components:
        if str(c.get("status") or "") != STATUS_APPROVED or int(c.get("archived") or 0):
            continue
        key = str(c.get("angle_key") or "").strip()
        if key and key not in seen:
            seen[key] = str(c.get("angle_label") or "")
    return [{"angle_key": k, "label": v} for k, v in seen.items()]


async def compose_and_persist(
    product_id: str,
    count: int,
    *,
    formula_families: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compose up to `count` copy sets from a product's APPROVED component pool
    and persist each as a COPY_REVIEW_REQUIRED copy_set.

    Every persisted row goes through the SAME primitives AI-assist copy uses —
    normalise → dedupe_key → existing-check → claim scan — so a composed row is
    indistinguishable from a generated one to the Copy Set Registry, the near-dup
    scanner, and the approval gate. Composed copy is NEVER auto-approved.

    Re-runs never re-emit a prior composition: the combination fingerprints of
    already-composed rows are excluded, so calling this repeatedly walks new
    ground until the pool is exhausted.

    dry_run=True composes and returns a preview WITHOUT writing anything.
    """
    from agent.db import crud
    from agent.services.copy_grounding_service import resolve_copy_grounding
    from agent.services.copy_set_service import (
        STATUS_COPY_REVIEW_REQUIRED,
        _dedupe_key_for,
        _normalize_fields,
        scan_copy_safety,
    )

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    pool = await crud.list_copy_components_for_product(product_id)
    approved = [c for c in pool if str(c.get("status")) == STATUS_APPROVED]
    angles = _angles_from_pool(approved)
    if not angles:
        return {"product_id": product_id, "requested": int(count or 0), "produced": 0,
                "created": 0, "deduped": 0, "dry_run": bool(dry_run), "items": [],
                "coverage": None, "warnings": ["NO_APPROVED_COMPONENTS_OR_ANGLES"]}

    grounding = await resolve_copy_grounding(product)
    route_type = str(getattr(grounding, "effective_route", "") or "DIRECT")

    # Exclude fingerprints of copy sets already composed from this pool, so a
    # repeat call produces fresh combinations rather than colliding on dedupe.
    existing_rows = await crud.list_copy_sets_for_product(product_id)
    already: set[str] = set()
    for r in existing_rows:
        if str(r.get("source") or "") != SOURCE_COMPONENT_COMPOSER:
            continue
        prov = r.get("provenance_json")
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except Exception:  # noqa: BLE001
                prov = {}
        prov = prov or {}
        # RECOMPUTE the fingerprint from the durable component_ids with the
        # CURRENT function, rather than trusting the stored fingerprint string.
        # A stored fingerprint is only as current as the code that wrote it — a
        # row composed before the fingerprint became formula-independent carries
        # a stale-format hash that would never match, so the exclude would miss
        # it and the re-run would re-tread already-composed ground. Recomputing
        # from component_ids is drift-proof.
        cids = prov.get("component_ids")
        if cids:
            already.add(combination_fingerprint(cids))
        elif prov.get("combination_fingerprint"):
            already.add(str(prov["combination_fingerprint"]))

    result = compose(
        approved, angles, int(count or 0),
        formula_families=formula_families, exclude_fingerprints=already,
    )

    created: list[dict[str, Any]] = []
    deduped = 0
    for item in result["items"]:
        fields = _normalize_fields({
            "angle": item["angle"],
            "hook": item["hook"],
            "subhook": item["subhook"],
            "usp_set": item["usp_set"],
            "cta": item["cta"],
            "platform": "TIKTOK",
            "language": "BM_MS",
            "route_type": route_type,
            "formula_family": item["formula_family"] or "PAS",
        })
        safety = scan_copy_safety(fields, product_id=product_id)
        dedupe_key = _dedupe_key_for(product_id, fields)
        preview = {
            "angle": fields["angle"], "hook": fields["hook"], "subhook": fields["subhook"],
            "usp_set": fields["usp_set"], "cta": fields["cta"],
            "formula_family": fields["formula_family"],
            "combination_fingerprint": item["combination_fingerprint"],
            "component_ids": item["component_ids"],
            "safe": safety["safe"], "violations": safety["violations"],
        }
        if dry_run:
            created.append(preview)
            continue

        if await crud.find_copy_set_by_dedupe_key(dedupe_key):
            deduped += 1
            continue
        row = await crud.create_copy_set(
            product_id,
            angle=fields["angle"], hook=fields["hook"], subhook=fields["subhook"],
            usp_set_json=json.dumps(fields["usp_set"], ensure_ascii=False),
            cta=fields["cta"], platform=fields["platform"], language=fields["language"],
            route_type=fields["route_type"], formula_family=fields["formula_family"],
            status=STATUS_COPY_REVIEW_REQUIRED,
            dedupe_key=dedupe_key,
            source=SOURCE_COMPONENT_COMPOSER,
            provenance_json=json.dumps({
                "composed": True,
                "angle_key": item["angle_key"],
                "component_ids": item["component_ids"],
                "combination_fingerprint": item["combination_fingerprint"],
            }, ensure_ascii=False),
            claim_review_json=json.dumps({
                "composed": True, "safety": safety, "route_type": route_type,
            }, ensure_ascii=False),
        )
        created.append({"copy_set_id": row.get("copy_set_id"), **preview})

    return {
        "product_id": product_id,
        "requested": result["requested"],
        "produced": len(created) if dry_run else len(created),
        "created": 0 if dry_run else len(created),
        "deduped": deduped,
        "shortfall": result["shortfall"],
        "dry_run": bool(dry_run),
        "coverage": result["coverage"],
        "blocked_angles": result["blocked_angles"],
        "items": created,
        "warnings": result["warnings"],
    }
