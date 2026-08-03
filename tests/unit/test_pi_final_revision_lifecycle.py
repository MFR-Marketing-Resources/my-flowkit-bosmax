"""PI-FINAL-B01: production-safety acceptance tests for the revision lifecycle.

Covers the twenty mission acceptance cases: terminal immutability, seed authority,
fail-closed explicit-seed validation, idempotent reuse, governed supersession of
unrelated open drafts, atomic rollback, snapshot versioning/supersession on approval,
claim-gate enforcement, and schema durability of the lineage columns.
"""
import json

import pytest

from agent.db import crud
from agent.db.schema import get_db, init_db
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftRejectRequest,
    ProductIntelligenceReviewDraftUpdateRequest,
)
from agent.services import product_intelligence_review_draft_service as svc


FULL_FIELDS = dict(
    product_description="Compact stainless steel tumbler, 500ml.",
    benefits_json='["Keeps drinks cold", "Fits car cup holders"]',
    usp_json='["500ml stainless steel body"]',
    usage_text="Fill, close the lid, drink.",
    ingredients_text="Stainless steel 304.",
    warnings_text="Hand wash only.",
    target_customer_text="Commuters who bring their own drinks.",
    allowed_claims_json='["Product type: Home / Drinkware / Tumbler"]',
    buyer_persona_snapshot_json='{"audience": "commuters"}',
    copy_strategy_summary_json='{"angles": ["cold drinks on the go"]}',
    source_urls_json='{"primary_listing": "https://example.com/listing/1"}',
    image_evidence_json='{"main": "https://example.com/img/1.jpg"}',
    claim_gate="CLAIM_SAFE",
    claim_risk_level="LOW",
)


async def _make_product(title="PI-FINAL Revision Product"):
    return await crud.create_product(
        raw_product_title=title, source="MANUAL",
        product_display_name=title, product_short_name=title,
    )


async def _make_full_draft(product_id: str, **overrides):
    fields = {**FULL_FIELDS, **overrides}
    return await crud.create_product_intelligence_review_draft(
        product_id=product_id, review_status="READY_FOR_REVIEW", **fields,
    )


async def _approve(draft_id: str, **req):
    return await svc.approve_review_draft(
        draft_id, ProductIntelligenceReviewDraftApproveRequest(approved_by="pi-final-test", **req),
    )


async def _draft_row(draft_id: str) -> dict:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE draft_id=?", (draft_id,))
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


async def _snapshot_row(snapshot_id: str) -> dict:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_snapshot WHERE snapshot_id=?", (snapshot_id,))
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


REASON = "PI-FINAL recovery"


# ── 1-3: terminal drafts are never mutated by revision creation ──────────────

async def test_approved_terminal_draft_unchanged_by_revision():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    await _approve(d1["draft_id"])
    before = await _draft_row(d1["draft_id"])
    await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    after = await _draft_row(d1["draft_id"])
    assert before == after
    assert after["review_status"] == "APPROVED"


async def test_rejected_terminal_draft_unchanged_by_revision():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    await svc.reject_review_draft(
        d1["draft_id"], ProductIntelligenceReviewDraftRejectRequest(rejected_by="t"))
    before = await _draft_row(d1["draft_id"])
    await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    after = await _draft_row(d1["draft_id"])
    assert before == after
    assert after["review_status"] == "REJECTED"


async def test_superseded_terminal_draft_unchanged_by_revision():
    product = await _make_product()
    debris = await _make_full_draft(product["id"])
    # first revision supersedes the unrelated open draft (governed)
    await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    superseded = await _draft_row(debris["draft_id"])
    assert superseded["review_status"] == "SUPERSEDED"
    # a retry must NOT touch the superseded terminal row again
    await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    assert await _draft_row(debris["draft_id"]) == superseded


# ── 4-5: new draft id, seeded from the latest approved snapshot ──────────────

async def test_revision_gets_new_draft_id_and_seeds_latest_approved_snapshot():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    snap1 = await _approve(d1["draft_id"])
    rev = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    assert rev.draft_id != d1["draft_id"]
    assert rev.review_status == "READY_FOR_REVIEW"
    assert rev.revision_of_snapshot_id == snap1.snapshot_id
    assert rev.product_description == FULL_FIELDS["product_description"]


# ── 6: explicit source snapshot fails closed ─────────────────────────────────

async def test_explicit_source_snapshot_mismatch_fails_closed():
    product_a = await _make_product("Product A")
    product_b = await _make_product("Product B")
    d_b = await _make_full_draft(product_b["id"])
    snap_b = await _approve(d_b["draft_id"])
    with pytest.raises(ValueError, match="SOURCE_SNAPSHOT_PRODUCT_MISMATCH"):
        await svc.create_revision_draft(
            product_a["id"], created_by="t", revision_reason=REASON,
            source_snapshot_id=snap_b.snapshot_id)
    with pytest.raises(ValueError, match="SOURCE_SNAPSHOT_NOT_FOUND"):
        await svc.create_revision_draft(
            product_a["id"], created_by="t", revision_reason=REASON,
            source_snapshot_id="does-not-exist")
    # a superseded snapshot is not an appropriate approved seed
    d_b2 = await svc.create_revision_draft(product_b["id"], created_by="t", revision_reason=REASON)
    snap_b2 = await _approve(d_b2.draft_id)
    assert snap_b2.version == 2
    with pytest.raises(ValueError, match="SOURCE_SNAPSHOT_NOT_APPROVED"):
        await svc.create_revision_draft(
            product_b["id"], created_by="t", revision_reason="another reason",
            source_snapshot_id=snap_b.snapshot_id)


# ── 7: fallback to latest terminal draft when no approved snapshot exists ────

async def test_fallback_seed_latest_terminal_draft_without_snapshot():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"], product_description="Rejected era description.")
    await svc.reject_review_draft(
        d1["draft_id"], ProductIntelligenceReviewDraftRejectRequest(rejected_by="t"))
    rev = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    assert rev.revision_of_snapshot_id is None
    assert rev.revision_of_draft_id == d1["draft_id"]
    assert rev.product_description == "Rejected era description."


# ── 8-10: claims, source urls and provenance survive revision creation ───────

async def test_allowed_claims_source_urls_and_provenance_survive_revision():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    await crud.create_product_intelligence_review_field_provenance(
        draft_id=d1["draft_id"], product_id=product["id"],
        field_name="product_description", source_type="TIKTOK_EXTRACTION",
        evidence_kind="FACT", extraction_method="LISTING_TITLE_EXTRACTION",
        verification_status="EXTERNALLY_EXTRACTED",
        source_url="https://example.com/listing/1",
        declared_value="Compact stainless steel tumbler, 500ml.")
    snap1 = await _approve(d1["draft_id"])
    rev = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    assert rev.allowed_claims_json == json.loads(FULL_FIELDS["allowed_claims_json"])
    assert rev.source_urls_json == json.loads(FULL_FIELDS["source_urls_json"])
    db = await get_db()
    cur = await db.execute(
        "SELECT field_name, source_url, inherited_from_draft_id, inherited_from_snapshot_id "
        "FROM product_intelligence_review_field_provenance WHERE draft_id=?", (rev.draft_id,))
    cloned = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    assert any(
        r["field_name"] == "product_description"
        and r["source_url"] == "https://example.com/listing/1"
        and r["inherited_from_draft_id"] == d1["draft_id"]
        and r["inherited_from_snapshot_id"] == snap1.snapshot_id
        for r in cloned
    )


# ── 11-12: single open revision, idempotent retry ────────────────────────────

async def test_retry_reuses_the_single_open_revision():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    await _approve(d1["draft_id"])
    rev1 = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    rev2 = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    assert rev1.draft_id == rev2.draft_id
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=? "
        "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')", (product["id"],))
    assert (await cur.fetchone())[0] == 1
    await cur.close()


# ── 13-14: unrelated debug draft is not reused; preserved and superseded ─────

async def test_unrelated_open_draft_not_reused_but_preserved_superseded():
    product = await _make_product()
    debris = await _make_full_draft(product["id"], product_description="Debug lane leftovers.")
    rev = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    assert rev.draft_id != debris["draft_id"]
    row = await _draft_row(debris["draft_id"])
    assert row["review_status"] == "SUPERSEDED"
    assert row["product_description"] == "Debug lane leftovers."  # content preserved
    assert "REVISION_LIFECYCLE_SUPERSEDED" in (row["reviewer_note"] or "")


# ── 15-16: provenance-clone failure rolls back the whole revision ────────────

async def test_failure_mid_revision_rolls_back_everything(monkeypatch):
    product = await _make_product()
    debris = await _make_full_draft(product["id"], product_description="Debris before failure.")

    def _boom(*_a, **_k):
        raise RuntimeError("simulated readback failure")

    monkeypatch.setattr(svc, "_load_provenance_for_draft", _boom)
    with pytest.raises(RuntimeError, match="simulated readback failure"):
        await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    monkeypatch.undo()
    db = await get_db()
    cur = await db.execute(
        "SELECT draft_id, review_status FROM product_intelligence_review_draft WHERE product_id=?",
        (product["id"],))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    # nothing committed: no partial revision row, and the debris supersession rolled back too
    assert rows == [{"draft_id": debris["draft_id"], "review_status": "READY_FOR_REVIEW"}]


# ── 17-19: approval creates N+1, supersedes N, never rewrites history ────────

async def test_approval_versions_and_supersession_preserve_history():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    snap1 = await _approve(d1["draft_id"])
    assert snap1.version == 1
    snap1_before = await _snapshot_row(snap1.snapshot_id)
    d1_before = await _draft_row(d1["draft_id"])

    rev = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    await svc.update_review_draft(
        rev.draft_id,
        ProductIntelligenceReviewDraftUpdateRequest(
            product_description="Updated 500ml stainless steel tumbler description."))
    snap2 = await _approve(rev.draft_id)
    assert snap2.version == 2
    assert snap2.supersedes_snapshot_id == snap1.snapshot_id

    snap1_after = await _snapshot_row(snap1.snapshot_id)
    assert snap1_after["status"] == "SUPERSEDED"
    # only status/updated_at may change on the superseded snapshot; content is frozen
    for key, value in snap1_before.items():
        if key in ("status", "updated_at"):
            continue
        assert snap1_after[key] == value, f"snapshot field {key} was rewritten"
    d1_after = await _draft_row(d1["draft_id"])
    assert d1_after == d1_before


# ── 20: claim-blocked content remains unapprovable through the revision lane ─

async def test_claim_blocked_revision_remains_unapprovable():
    product = await _make_product()
    d1 = await _make_full_draft(product["id"])
    await _approve(d1["draft_id"])
    rev = await svc.create_revision_draft(product["id"], created_by="t", revision_reason=REASON)
    await svc.update_review_draft(
        rev.draft_id,
        ProductIntelligenceReviewDraftUpdateRequest(
            product_description="This product cures disease permanently."))
    with pytest.raises(ValueError, match="CLAIM_BLOCKED"):
        await _approve(rev.draft_id)


# ── schema durability: lineage columns exist on a fresh DB and upgrade older DBs ──

async def test_revision_lineage_columns_in_fresh_schema_and_migration():
    db = await get_db()
    cur = await db.execute("PRAGMA table_info(product_intelligence_review_draft)")
    draft_cols = {row[1] for row in await cur.fetchall()}
    await cur.close()
    assert {"revision_of_draft_id", "revision_of_snapshot_id", "revision_reason"} <= draft_cols
    cur = await db.execute("PRAGMA table_info(product_intelligence_review_field_provenance)")
    prov_cols = {row[1] for row in await cur.fetchall()}
    await cur.close()
    assert {"inherited_from_draft_id", "inherited_from_snapshot_id", "inherited_at"} <= prov_cols

    # simulate an older valid DB (predating the lineage columns) and prove the
    # idempotent migration restores them without manual SQL
    import sqlite3
    if sqlite3.sqlite_version_info >= (3, 35, 0):
        for col in ("revision_of_draft_id", "revision_of_snapshot_id", "revision_reason"):
            await db.execute(
                f"ALTER TABLE product_intelligence_review_draft DROP COLUMN {col}")
        await db.commit()
        await init_db()
        cur = await db.execute("PRAGMA table_info(product_intelligence_review_draft)")
        upgraded = {row[1] for row in await cur.fetchall()}
        await cur.close()
        assert {"revision_of_draft_id", "revision_of_snapshot_id", "revision_reason"} <= upgraded
