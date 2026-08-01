"""The intake invariant: every runtime intake ends with an up-to-date PI draft.

Run against the REAL DB, not a mocked promotion — the two existing commit test files mock
promotion out entirely, so they pass whether or not a product ends up with an intelligence
row. These assert the branch that actually ran, because "a draft exists" is too weak a
test: the FastMoss lane re-imports up to 500 rows per call and must not manufacture 500
fresh review items when nothing changed.
"""
from __future__ import annotations

import pytest

from agent.db.schema import get_db
from agent.services.product_intake_service import (
    CREATED,
    CREATED_MINIMAL,
    NOOP_APPROVED_SNAPSHOT,
    NOOP_DRAFT_UP_TO_DATE,
    UPDATED_REVIEW_REQUIRED,
    digest_of_payload,
    digest_of_stored_draft,
    ensure_product_intelligence,
    evidence_digest,
)
from agent.services.registration_intelligence_promotion_service import (
    build_promotion_payload,
)


class _Draft:
    def __init__(self, declared=None, candidates=None, approval=None, **kw):
        self.declared_evidence_fields = declared or {}
        self.canonical_candidate_fields = candidates or {}
        self.approval_checklist = approval or {}
        self.claim_risk_level = kw.get("claim_risk_level", "MEDIUM")
        self.claim_tokens = kw.get("claim_tokens", [])
        self.source_lane = kw.get("source_lane", "FASTMOSS")


async def _product(pid: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, "
        "product_short_name, lifecycle_status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (pid, "Intake Fixture", "Intake Fixture", "Intake Fixture", "ACTIVE",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    await db.commit()


async def _draft_count(pid: str) -> int:
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=?", (pid,))
    n = (await cur.fetchone())[0]
    await cur.close()
    return int(n)


# ── digest ───────────────────────────────────────────────────────────────────

def test_digest_ignores_fields_the_system_recomputes():
    """If the digest moved on claim scores or timestamps, the no-op branch could never
    fire and every recompute would look like changed evidence."""
    base = {"product_description": "x", "usage_text": "y"}
    assert evidence_digest(base) == evidence_digest(
        {**base, "claim_gate": "CLAIM_BLOCKED", "updated_at": "2026-09-09T00:00:00Z",
         "review_status": "NEEDS_REVISION", "completeness_score": 0.9})


def test_digest_survives_json_text_vs_list_representation():
    """The stored row holds JSON text; the payload holds a real list."""
    assert evidence_digest({"benefits_json": ["a", "b"]}) == evidence_digest(
        {"benefits_json": '["a", "b"]'})


def test_digest_treats_blank_and_absent_identically():
    assert evidence_digest({"usage_text": "   "}) == evidence_digest({})


def test_digest_changes_when_real_evidence_changes():
    assert evidence_digest({"usage_text": "a"}) != evidence_digest({"usage_text": "b"})


def test_payload_and_stored_row_digests_are_comparable():
    payload = build_promotion_payload(_Draft(declared={
        "product_knowledge_text": "Cotton skirting.", "benefits_text": "Waterproof\nCheap"}))
    stored = {"product_description": "Cotton skirting.",
              "benefits_json": '["Waterproof", "Cheap"]'}
    assert digest_of_payload(payload) == digest_of_stored_draft(stored)


# ── lifecycle branches ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_intake_creates_a_draft():
    await _product("intake-a")
    r = await ensure_product_intelligence(
        "intake-a", _Draft(declared={"product_knowledge_text": "A cotton skirting."}),
        lane="FASTMOSS")
    assert r["outcome"] == CREATED
    assert r["intelligence_draft_id"]
    assert await _draft_count("intake-a") == 1


@pytest.mark.asyncio
async def test_reimporting_identical_evidence_is_a_noop():
    """THE FastMoss case: 500 unchanged rows must not create 500 review items."""
    await _product("intake-b")
    d = _Draft(declared={"product_knowledge_text": "Same text.", "usage_text": "Wipe."})
    first = await ensure_product_intelligence("intake-b", d, lane="FASTMOSS")
    assert first["outcome"] == CREATED

    for _ in range(4):
        again = await ensure_product_intelligence("intake-b", d, lane="FASTMOSS")
        assert again["outcome"] == NOOP_DRAFT_UP_TO_DATE
        assert again["wrote"] is False
        assert again["intelligence_draft_id"] == first["intelligence_draft_id"]
    assert await _draft_count("intake-b") == 1, "re-import duplicated review debt"


@pytest.mark.asyncio
async def test_changed_evidence_updates_the_open_draft_review_required():
    await _product("intake-c")
    await ensure_product_intelligence(
        "intake-c", _Draft(declared={"usage_text": "old"}), lane="MANUAL")
    r = await ensure_product_intelligence(
        "intake-c", _Draft(declared={"usage_text": "new and different"}), lane="MANUAL")
    assert r["outcome"] == UPDATED_REVIEW_REQUIRED
    assert r["wrote"] is True
    assert await _draft_count("intake-c") == 1, "an update must version, not duplicate"

    db = await get_db()
    cur = await db.execute(
        "SELECT usage_text, approved_by, approved_at FROM "
        "product_intelligence_review_draft WHERE product_id=?", ("intake-c",))
    row = dict(await cur.fetchone())
    await cur.close()
    assert row["usage_text"] == "new and different"
    assert not row["approved_by"] and not row["approved_at"]


@pytest.mark.asyncio
async def test_an_approved_snapshot_is_never_disturbed_by_reimport():
    await _product("intake-d")
    d = _Draft(declared={"product_knowledge_text": "Ratified truth."})
    await ensure_product_intelligence("intake-d", d, lane="MANUAL")
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, version, "
        "status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("snap-d", "intake-d", 1, "APPROVED", "2026-01-01T00:00:00Z",
         "2026-01-01T00:00:00Z"))
    await db.commit()

    r = await ensure_product_intelligence("intake-d", d, lane="FASTMOSS")
    assert r["outcome"] == NOOP_APPROVED_SNAPSHOT
    assert r["wrote"] is False

    cur = await db.execute(
        "SELECT status FROM product_intelligence_snapshot WHERE snapshot_id='snap-d'")
    assert dict(await cur.fetchone())["status"] == "APPROVED"
    await cur.close()


@pytest.mark.asyncio
async def test_a_product_with_no_promotable_evidence_still_enters_the_lifecycle():
    await _product("intake-e")
    r = await ensure_product_intelligence(
        "intake-e", _Draft(candidates={"category": "Beauty"}, approval={"category": True}),
        lane="PRODUCTS_MANUAL")
    assert r["outcome"] == CREATED_MINIMAL
    assert r["intelligence_draft_id"]
    assert r["reason"] == "NO_PROMOTABLE_FIELDS"
    assert await _draft_count("intake-e") == 1


@pytest.mark.asyncio
async def test_an_empty_reimport_never_blanks_an_existing_draft():
    await _product("intake-f")
    await ensure_product_intelligence(
        "intake-f", _Draft(declared={"usage_text": "keep me"}), lane="MANUAL")
    r = await ensure_product_intelligence("intake-f", _Draft(), lane="FASTMOSS")
    assert r["outcome"] == NOOP_DRAFT_UP_TO_DATE
    assert r["wrote"] is False
    db = await get_db()
    cur = await db.execute(
        "SELECT usage_text FROM product_intelligence_review_draft WHERE product_id=?",
        ("intake-f",))
    assert dict(await cur.fetchone())["usage_text"] == "keep me"
    await cur.close()


@pytest.mark.asyncio
async def test_replayed_concurrent_intake_does_not_duplicate_drafts():
    import asyncio

    await _product("intake-g")
    d = _Draft(declared={"product_knowledge_text": "Replay me."})
    await ensure_product_intelligence("intake-g", d, lane="MANUAL")
    await asyncio.gather(*[
        ensure_product_intelligence("intake-g", d, lane="MANUAL") for _ in range(5)])
    assert await _draft_count("intake-g") == 1


@pytest.mark.asyncio
async def test_ensure_never_calls_a_paid_provider(monkeypatch):
    """prepare_product_for_copywriting spends tokens; /import-fastmoss would fire it 500x."""
    from agent.services import product_intelligence_prepare_service as prep

    called = []
    monkeypatch.setattr(
        prep, "prepare_product_for_copywriting",
        lambda *a, **k: called.append(1), raising=False)
    await _product("intake-h")
    await ensure_product_intelligence(
        "intake-h", _Draft(declared={"usage_text": "no tokens please"}), lane="FASTMOSS")
    assert called == []
