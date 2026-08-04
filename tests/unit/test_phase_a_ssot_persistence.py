"""SSOT Phase A — the three fields that previously dropped at registration commit
(or were re-derived every read) must now persist durably.

1. hook_angles / cta_angles were declared by operators but had no PROMOTION_MAP
   target, so they vanished at commit.
2. pain_points was not even a registration field; it only survived inside the
   buyer_persona_snapshot_json blob.
3. bosmax_product_family had no `product` column, so it was re-derived by every
   consumer and drifted (root of the sensitive-mislabel bug class).

These pin the durable homes end-to-end (promotion payload -> intelligence draft
-> reload, and product row -> reload).
"""
from __future__ import annotations

import json

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.registration_intelligence_promotion_service import (
    PROMOTION_MAP,
    build_promotion_payload,
    promote_registration_to_intelligence,
)


class _Draft:
    def __init__(self, declared=None, candidates=None, approval=None, **kw):
        self.declared_evidence_fields = declared or {}
        self.canonical_candidate_fields = candidates or {}
        self.approval_checklist = approval or {}
        self.claim_risk_level = kw.get("claim_risk_level", "MEDIUM")
        self.claim_tokens = kw.get("claim_tokens", [])
        self.source_lane = kw.get("source_lane", "MANUAL")


# ── promotion payload (pure) ──────────────────────────────────────────────────
def test_copy_seeds_and_pain_points_are_promoted_not_dropped():
    payload = build_promotion_payload(_Draft(declared={
        "hook_angles": ["Hook one", "Hook two"],
        "cta_angles": ["Grab it today"],
        "pain_points": "Line snaps on big catches\nTangles easily",
    }))
    assert payload["fields"]["hook_angles_json"] == ["Hook one", "Hook two"]
    assert payload["fields"]["cta_angles_json"] == ["Grab it today"]
    # multi-line text becomes a list for the list column
    assert payload["fields"]["pain_points_json"] == [
        "Line snaps on big catches", "Tangles easily"]
    dropped_sources = {d["source"] for d in payload["dropped_fields"]}
    assert {"hook_angles", "cta_angles", "pain_points"}.isdisjoint(dropped_sources)


def test_new_targets_are_in_the_promotion_map():
    targets = {t for t, _ in PROMOTION_MAP}
    assert {"hook_angles_json", "cta_angles_json", "pain_points_json"} <= targets


def test_usp_text_promotes_to_usp_json():
    """Phase C: USP is its own declared field now (was lumped into Benefits)."""
    payload = build_promotion_payload(_Draft(declared={
        "usp_text": "Waterproof\nUltra-light 8-strand braid",
    }))
    assert payload["fields"]["usp_json"] == [
        "Waterproof", "Ultra-light 8-strand braid"]


def test_subhook_promotes_to_subhook_json():
    """Phase C part 2: Subhook is a durable copy seed like hook/cta (multi-line
    declared text becomes a list)."""
    payload = build_promotion_payload(_Draft(declared={
        "subhook": "The one pros trust\nNever snaps mid-fight",
    }))
    assert payload["fields"]["subhook_json"] == [
        "The one pros trust", "Never snaps mid-fight"]
    assert "subhook" not in {d["source"] for d in payload["dropped_fields"]}


def test_subhook_is_in_the_promotion_map_and_list_targets():
    from agent.services.registration_intelligence_promotion_service import (
        _LIST_TARGETS,
    )
    assert "subhook_json" in {t for t, _ in PROMOTION_MAP}
    assert "subhook_json" in _LIST_TARGETS


# ── intelligence round-trip (real DB) ─────────────────────────────────────────
async def _make_product(pid: str, **cols) -> None:
    db = await get_db()
    base = dict(
        id=pid, raw_product_title="Phase A Fixture",
        product_display_name="Phase A Fixture", product_short_name="Phase A Fixture",
        lifecycle_status="ACTIVE",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    base.update(cols)
    keys = ",".join(base)
    await db.execute(
        f"INSERT INTO product ({keys}) VALUES ({','.join('?' * len(base))})",
        list(base.values()),
    )
    await db.commit()


async def _draft_row(pid: str) -> dict:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=?", (pid,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    assert len(rows) == 1
    return rows[0]


@pytest.mark.asyncio
async def test_copy_seeds_survive_promotion_and_reload():
    await _make_product("phase-a-seeds")
    receipt = await promote_registration_to_intelligence(
        "phase-a-seeds",
        _Draft(declared={
            "product_knowledge_text": "Braided PE X8 fishing line.",
            "hook_angles": ["Big fish? No problem."],
            "cta_angles": ["Get yours today."],
            "pain_points": "Line snaps on big catches\nTangles easily",
            "subhook": "Trusted by pros\nRated for 40lb",
        }),
    )
    assert receipt["minimal_draft"] is False
    row = await _draft_row("phase-a-seeds")
    assert json.loads(row["hook_angles_json"]) == ["Big fish? No problem."]
    assert json.loads(row["cta_angles_json"]) == ["Get yours today."]
    assert json.loads(row["pain_points_json"]) == [
        "Line snaps on big catches", "Tangles easily"]
    assert json.loads(row["subhook_json"]) == ["Trusted by pros", "Rated for 40lb"]


@pytest.mark.asyncio
async def test_no_copy_seeds_leaves_empty_lists_not_null():
    await _make_product("phase-a-empty-seeds")
    await promote_registration_to_intelligence(
        "phase-a-empty-seeds",
        _Draft(declared={"product_knowledge_text": "A product with no seeds."}),
    )
    row = await _draft_row("phase-a-empty-seeds")
    assert json.loads(row["hook_angles_json"]) == []
    assert json.loads(row["pain_points_json"]) == []
    assert json.loads(row["subhook_json"]) == []


# ── product family persistence (real DB) ──────────────────────────────────────
@pytest.mark.asyncio
async def test_product_persists_bosmax_product_family():
    product = await crud.create_product(
        "SeaHunter Fishing Line", source="MANUAL",
        category="Sports & Outdoor",
        bosmax_product_family="AUTO_TOOL_GENERAL",
    )
    fetched = await crud.get_product(product["id"])
    assert fetched["bosmax_product_family"] == "AUTO_TOOL_GENERAL"
