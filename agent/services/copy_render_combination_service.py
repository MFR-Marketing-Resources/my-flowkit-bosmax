"""Deterministic recipe selector for the On-Demand Copy Renderer (Round 2).

ZERO provider calls. Reads Round-1 ACTIVE atoms + `creative_atom_compatibility`
and enumerates valid recipes `(benefit, angle, hook, body, cta)` — compatibility
triples when present, else the full within-Angle Cartesian. Selection is a
reproducible, diversity-preferring greedy over a session-seed digest ordering
(no LLM ranking): each pick prefers a new Angle, then Hook, then Body, then CTA.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from agent.db import creative_factory_crud as cfc


def recipe_fingerprint(benefit_id: str, angle_id: str, hook_id: str, body_id: str, cta_id: str) -> str:
    return hashlib.sha256(
        "|".join([benefit_id, angle_id, hook_id, body_id, cta_id]).encode("utf-8")
    ).hexdigest()


async def enumerate_recipes(benefit_id: str) -> list[dict[str, Any]]:
    """All valid recipes for a benefit (compat-narrowed within Angle), carrying
    atom ids + text for the stitch prompt / render artifact."""
    atoms = await cfc.get_benefit_atoms(benefit_id, status="ACTIVE")
    angles = atoms["angle"]
    hooks_by_angle: dict[str, dict[str, dict]] = defaultdict(dict)
    bodies_by_angle: dict[str, dict[str, dict]] = defaultdict(dict)
    ctas_by_angle: dict[str, dict[str, dict]] = defaultdict(dict)
    for h in atoms["hook"]:
        hooks_by_angle[h["angle_id"]][h["hook_id"]] = h
    for b in atoms["body"]:
        bodies_by_angle[b["angle_id"]][b["body_id"]] = b
    for c in atoms["cta"]:
        ctas_by_angle[c["angle_id"]][c["cta_id"]] = c

    compat_by_angle: dict[str, list[dict]] = defaultdict(list)
    for row in await cfc.list_compatibility([a["angle_id"] for a in angles]):
        compat_by_angle[row["angle_id"]].append(row)

    recipes: list[dict[str, Any]] = []
    for a in angles:
        aid = a["angle_id"]
        hmap, bmap, cmap = hooks_by_angle[aid], bodies_by_angle[aid], ctas_by_angle[aid]
        if compat_by_angle.get(aid):
            triples = [(r["hook_id"], r["body_id"], r["cta_id"]) for r in compat_by_angle[aid]]
        else:
            triples = [(h, b, c) for h in hmap for b in bmap for c in cmap]
        for hid, bid, cid in triples:
            if hid in hmap and bid in bmap and cid in cmap:
                recipes.append({
                    "benefit_id": benefit_id,
                    "angle_id": aid, "hook_id": hid, "body_id": bid, "cta_id": cid,
                    "angle_text": a["angle_text"],
                    "hook_text": hmap[hid]["atom_text"],
                    "body_text": bmap[bid]["atom_text"],
                    "cta_text": cmap[cid]["atom_text"],
                    "recipe_fingerprint": recipe_fingerprint(benefit_id, aid, hid, bid, cid),
                })
    return recipes


async def unique_capacity(benefit_id: str) -> int:
    return len(await enumerate_recipes(benefit_id))


def _seed_key(seed: str, fingerprint: str) -> str:
    return hashlib.sha256((seed + "|" + fingerprint).encode("utf-8")).hexdigest()


def select_diverse(
    recipes: list[dict[str, Any]],
    used_fingerprints: set[str],
    *,
    seed: str,
    count: int,
) -> list[dict[str, Any]]:
    """Deterministic diversity-preferring selection of ≤count unused recipes."""
    pool = [r for r in recipes if r["recipe_fingerprint"] not in used_fingerprints]
    pool.sort(key=lambda r: _seed_key(seed, r["recipe_fingerprint"]))
    order = {r["recipe_fingerprint"]: i for i, r in enumerate(pool)}
    chosen: list[dict[str, Any]] = []
    seen = {"angle_id": set(), "hook_id": set(), "body_id": set(), "cta_id": set()}
    remaining = list(pool)
    while remaining and len(chosen) < count:
        def novelty(r: dict[str, Any]) -> int:
            return (
                (r["angle_id"] not in seen["angle_id"]) * 8
                + (r["hook_id"] not in seen["hook_id"]) * 4
                + (r["body_id"] not in seen["body_id"]) * 2
                + (r["cta_id"] not in seen["cta_id"]) * 1
            )
        pick = max(remaining, key=lambda r: (novelty(r), -order[r["recipe_fingerprint"]]))
        chosen.append(pick)
        for k in seen:
            seen[k].add(pick[k])
        remaining.remove(pick)
    return chosen


async def plan_batch(
    benefit_id: str,
    used_fingerprints: set[str],
    *,
    seed: str,
    count: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return (selected recipes ≤count, total unique capacity)."""
    recipes = await enumerate_recipes(benefit_id)
    selected = select_diverse(recipes, used_fingerprints, seed=seed, count=count)
    return selected, len(recipes)
