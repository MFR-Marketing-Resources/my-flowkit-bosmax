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


async def _snapshot(pid: str, sid: str, *, status: str, **fields) -> None:
    db = await get_db()
    cols = ["snapshot_id", "product_id", "version", "status", "created_at", "updated_at"]
    vals = [sid, pid, 1, status, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"]
    for k, v in fields.items():
        cols.append(k)
        vals.append(v)
    await db.execute(
        f"INSERT INTO product_intelligence_snapshot ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})", vals)
    await db.commit()


async def _snapshot_status(sid: str) -> str:
    db = await get_db()
    cur = await db.execute(
        "SELECT status FROM product_intelligence_snapshot WHERE snapshot_id=?", (sid,))
    row = dict(await cur.fetchone())
    await cur.close()
    return row["status"]


async def _seed_provenance(pid: str, **row) -> None:
    """Record evidence provenance for a product whose draft was already APPROVED.

    provenance.draft_id is a real FK, and an approved snapshot is produced FROM an
    approved draft, so that is the shape seeded here.
    """
    from agent.db import crud
    db = await get_db()
    draft_id = row.pop("draft_id", f"seed-{pid}")
    await db.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (draft_id, pid, "APPROVED", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    await db.commit()
    await crud.create_product_intelligence_review_field_provenance(
        draft_id=draft_id,
        product_id=pid,
        field_name=row.pop("field_name", "product_description"),
        source_type=row.pop("source_type", "REGISTRATION_COMMIT"),
        evidence_kind=row.pop("evidence_kind", "OPERATOR_DECLARED"),
        extraction_method=row.pop("extraction_method", "REGISTRATION_PROMOTION"),
        verification_status=row.pop("verification_status", "PENDING_REVIEW"),
        declared_value=row.pop("declared_value", None),
        normalized_value=None, source_url=row.pop("source_url", None),
        source_lane=None, confidence_score=None, claim_risk_flag=None,
        reviewer_decision=None, reviewer_note=None,
    )


@pytest.mark.asyncio
async def test_approved_snapshot_with_identical_values_and_provenance_is_a_noop():
    """A no-op needs identical VALUES *and* identical provenance. The earlier fixture had
    an approved snapshot with zero provenance rows, so incoming evidence was genuinely new
    information about where those values came from."""
    await _product("intake-d")
    await _snapshot("intake-d", "snap-d", status="APPROVED",
                    product_description="Ratified truth.")
    await _seed_provenance("intake-d")
    r = await ensure_product_intelligence(
        "intake-d", _Draft(declared={"product_knowledge_text": "Ratified truth."}),
        lane="FASTMOSS")
    assert r["outcome"] == NOOP_APPROVED_SNAPSHOT
    assert r["wrote"] is False
    assert await _snapshot_status("snap-d") == "APPROVED"
    # only the pre-existing APPROVED (terminal) draft; no new open draft was opened
    assert await _draft_count("intake-d") == 1


@pytest.mark.asyncio
async def test_approved_snapshot_with_no_recorded_provenance_records_the_evidence():
    """The inverse: values match but nothing says where they came from, so the incoming
    provenance is new and must be captured rather than discarded."""
    await _product("intake-d3")
    await _snapshot("intake-d3", "snap-d3", status="APPROVED",
                    product_description="Ratified truth.")
    r = await ensure_product_intelligence(
        "intake-d3", _Draft(declared={"product_knowledge_text": "Ratified truth."}),
        lane="FASTMOSS")
    assert r["outcome"] != NOOP_APPROVED_SNAPSHOT
    assert await _snapshot_status("snap-d3") == "APPROVED", "snapshot must be untouched"


@pytest.mark.asyncio
async def test_evidence_that_changes_after_approval_becomes_a_new_review_item():
    """B-586-01 REGRESSION: this previously returned NOOP whenever there was no open
    draft, so evidence arriving AFTER approval was silently discarded."""
    await _product("intake-d2")
    await _snapshot("intake-d2", "snap-d2", status="APPROVED",
                    product_description="Old truth.", usage_text="old usage")
    r = await ensure_product_intelligence(
        "intake-d2",
        _Draft(declared={"product_knowledge_text": "Old truth.",
                         "usage_text": "NEW usage from marketplace"}),
        lane="PRODUCTS_FASTMOSS_REIMPORT")
    assert r["outcome"] != NOOP_APPROVED_SNAPSHOT, "new evidence was thrown away"
    assert r["wrote"] is True
    assert await _draft_count("intake-d2") == 1
    # the ratified snapshot itself is untouched
    assert await _snapshot_status("snap-d2") == "APPROVED"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["SUPERSEDED", "REJECTED", "DRAFT", "ARCHIVED"])
async def test_a_non_approved_snapshot_does_not_count_as_approved(status):
    """9 SUPERSEDED snapshots exist in live data; the first version treated ANY snapshot
    row as ratified Product Truth."""
    pid = f"intake-ns-{status.lower()}"
    await _product(pid)
    await _snapshot(pid, f"snap-{status.lower()}", status=status,
                    product_description="Not ratified.")
    r = await ensure_product_intelligence(
        pid, _Draft(declared={"product_knowledge_text": "Not ratified."}), lane="MANUAL")
    assert r["outcome"] != NOOP_APPROVED_SNAPSHOT
    assert await _draft_count(pid) == 1


@pytest.mark.asyncio
async def test_the_same_value_with_a_new_source_is_not_swallowed():
    """B-586-02: identical text backed by a newly acquired source must persist that
    source, otherwise an evidence-closure mission cannot close any evidence."""
    await _product("intake-src")
    first = await ensure_product_intelligence(
        "intake-src", _Draft(declared={"product_knowledge_text": "Same words."}),
        lane="PRODUCTS_MANUAL")
    assert first["outcome"] == CREATED
    second = await ensure_product_intelligence(
        "intake-src",
        _Draft(declared={"product_knowledge_text": "Same words.",
                         "source_url": "https://shop.example/acquired/1"}),
        lane="PRODUCTS_FASTMOSS_REIMPORT")
    assert second["outcome"] == UPDATED_REVIEW_REQUIRED, "new source was swallowed"
    assert second["wrote"] is True
    assert await _draft_count("intake-src") == 1


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


# ── B-586-02 completion + B-586-07 provenance truth ─────────────────────────

def test_verification_upgrade_is_not_covered_by_weaker_stored_evidence():
    """Same URL re-acquired through a stronger lane is NEW information."""
    from agent.services.product_intake_service import provenance_is_covered
    stored = [{"source_url": "https://s/1", "source_type": "IMPORTED_FASTMOSS",
               "extraction_method": "FASTMOSS_WORKBOOK",
               "verification_status": "PENDING_REVIEW"}]
    same = [dict(stored[0])]
    stronger = [{**stored[0], "verification_status": "VERIFIED"}]
    assert provenance_is_covered(stored, same) is True
    assert provenance_is_covered(stored, stronger) is False


def test_a_different_source_type_for_the_same_url_is_not_covered():
    from agent.services.product_intake_service import provenance_is_covered
    stored = [{"source_url": "https://s/1", "source_type": "IMPORTED_FASTMOSS",
               "extraction_method": "FASTMOSS_WORKBOOK",
               "verification_status": "PENDING_REVIEW"}]
    acquired = [{"source_url": "https://s/1", "source_type": "SOURCE_PAGE",
                 "extraction_method": "DOM_EXTRACTION",
                 "verification_status": "PENDING_REVIEW"}]
    assert provenance_is_covered(stored, acquired) is False


def test_imported_lanes_are_not_labelled_operator_declared():
    """B-586-07: nobody vouched for a FastMoss workbook row or a TikTok link import."""
    from agent.services.product_intake_service import evidence_from_product_payload
    from agent.services.registration_intelligence_promotion_service import (
        build_promotion_payload, build_provenance_inputs)
    for lane, expect_type, expect_kind in (
        ("PRODUCTS_FASTMOSS_REIMPORT", "IMPORTED_FASTMOSS", "IMPORTED_MARKETPLACE_ROW"),
        ("PRODUCTS_TIKTOKSHOP_IMPORT", "IMPORTED_TIKTOKSHOP", "IMPORTED_MARKETPLACE_LINK"),
    ):
        ev = evidence_from_product_payload({"usage_text": "wipe it"}, lane=lane)
        rows = build_provenance_inputs(ev, build_promotion_payload(ev))
        assert rows, lane
        assert rows[0].source_type == expect_type
        assert rows[0].evidence_kind == expect_kind
        assert rows[0].reviewer_decision is None, "an import is not an operator approval"
        assert rows[0].verification_status == "PENDING_REVIEW"


def test_operator_manual_entry_keeps_operator_semantics():
    from agent.services.product_intake_service import evidence_from_product_payload
    from agent.services.registration_intelligence_promotion_service import (
        build_promotion_payload, build_provenance_inputs)
    ev = evidence_from_product_payload({"usage_text": "typed by hand"},
                                       lane="PRODUCTS_MANUAL")
    rows = build_provenance_inputs(ev, build_promotion_payload(ev))
    assert rows[0].source_type == "OPERATOR_MANUAL_ENTRY"
    assert rows[0].evidence_kind == "OPERATOR_DECLARED"


# ── B-586-02 PRODUCTION-PATH proof (helper tests are not sufficient) ─────────

class _LaneDraft(_Draft):
    """Declares truthful lane provenance, like evidence_from_product_payload does."""

    def __init__(self, declared, *, source_type, extraction_method,
                 verification_status="PENDING_REVIEW", lane="PRODUCTS_TIKTOKSHOP_IMPORT"):
        super().__init__(declared=declared, source_lane=lane)
        self.provenance_source_type = source_type
        self.provenance_evidence_kind = "IMPORTED_MARKETPLACE_LINK"
        self.provenance_extraction_method = extraction_method
        self.provenance_verification_status = verification_status


async def _prov_rows(pid: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT source_url, source_type, extraction_method, verification_status "
        "FROM product_intelligence_review_field_provenance WHERE product_id=?", (pid,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows


@pytest.mark.asyncio
async def test_stronger_extraction_for_the_same_url_is_not_a_noop_through_the_real_path():
    """B-586-02 REGRESSION: provenance_is_covered existed but ensure_product_intelligence
    never called it, so this upgrade was swallowed in production while the helper's own
    unit test passed."""
    await _product("intake-upgrade")
    url = "https://shop-my.tiktok.com/pdp/123"

    first = await ensure_product_intelligence(
        "intake-upgrade",
        _LaneDraft({"product_knowledge_text": "Cotton skirting.", "source_url": url},
                   source_type="IMPORTED_TIKTOKSHOP",
                   extraction_method="TIKTOKSHOP_LINK"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert first["outcome"] == CREATED

    # identical evidence -> still a no-op
    repeat = await ensure_product_intelligence(
        "intake-upgrade",
        _LaneDraft({"product_knowledge_text": "Cotton skirting.", "source_url": url},
                   source_type="IMPORTED_TIKTOKSHOP",
                   extraction_method="TIKTOKSHOP_LINK"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert repeat["outcome"] == NOOP_DRAFT_UP_TO_DATE

    # SAME url + SAME text, but genuinely acquired from the page -> must NOT be a no-op
    upgraded = await ensure_product_intelligence(
        "intake-upgrade",
        _LaneDraft({"product_knowledge_text": "Cotton skirting.", "source_url": url},
                   source_type="SOURCE_PAGE",
                   extraction_method="DOM_EXTRACTION"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert upgraded["outcome"] != NOOP_DRAFT_UP_TO_DATE, (
        "stronger acquired evidence was swallowed by the production path")
    assert upgraded["wrote"] is True

    # the stronger provenance is actually persisted, and re-read from the DB
    methods = {r["extraction_method"] for r in await _prov_rows("intake-upgrade")}
    assert "DOM_EXTRACTION" in methods, "upgraded provenance never reached the database"
    assert await _draft_count("intake-upgrade") == 1, "an upgrade must version, not duplicate"


# ── B-586-02: the three production-path cases the counter-audit specified ────

class _VerifiedDraft(_Draft):
    def __init__(self, declared, *, verification_status, source_type="SOURCE_PAGE",
                 extraction_method="DOM_EXTRACTION"):
        super().__init__(declared=declared, source_lane="PRODUCTS_TIKTOKSHOP_IMPORT")
        self.provenance_source_type = source_type
        self.provenance_evidence_kind = "IMPORTED_MARKETPLACE_LINK"
        self.provenance_extraction_method = extraction_method
        self.provenance_verification_status = verification_status


@pytest.mark.asyncio
async def test_A_open_draft_pending_to_verified_is_not_a_noop():
    """Same URL, same source type, same extraction method — only the verification status
    rises. This is the case build_provenance_inputs could not previously express."""
    await _product("intake-ver")
    url = "https://shop-my.tiktok.com/pdp/ver"
    ev = {"product_knowledge_text": "Identical text.", "source_url": url}
    first = await ensure_product_intelligence(
        "intake-ver", _VerifiedDraft(ev, verification_status="PENDING_REVIEW"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert first["outcome"] == CREATED

    upgraded = await ensure_product_intelligence(
        "intake-ver", _VerifiedDraft(ev, verification_status="VERIFIED"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert upgraded["outcome"] != NOOP_DRAFT_UP_TO_DATE, "PENDING->VERIFIED was swallowed"
    statuses = {r["verification_status"] for r in await _prov_rows("intake-ver")}
    assert "VERIFIED" in statuses, "VERIFIED provenance never persisted"


@pytest.mark.asyncio
async def test_B_approved_snapshot_plus_stronger_evidence_opens_a_review_draft():
    await _product("intake-apv")
    url = "https://shop-my.tiktok.com/pdp/apv"
    ev = {"product_knowledge_text": "Ratified.", "source_url": url}
    await ensure_product_intelligence(
        "intake-apv", _VerifiedDraft(ev, verification_status="PENDING_REVIEW"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    await _snapshot("intake-apv", "snap-apv", status="APPROVED",
                    product_description="Ratified.")

    r = await ensure_product_intelligence(
        "intake-apv", _VerifiedDraft(ev, verification_status="VERIFIED"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert r["outcome"] != NOOP_APPROVED_SNAPSHOT, (
        "stronger evidence after approval was discarded by the snapshot branch")
    assert await _snapshot_status("snap-apv") == "APPROVED", "snapshot was disturbed"


@pytest.mark.asyncio
async def test_C_identical_values_and_identical_provenance_is_a_genuine_noop():
    await _product("intake-idn")
    url = "https://shop-my.tiktok.com/pdp/idn"
    ev = {"product_knowledge_text": "Unchanged.", "source_url": url}
    await ensure_product_intelligence(
        "intake-idn", _VerifiedDraft(ev, verification_status="PENDING_REVIEW"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    again = await ensure_product_intelligence(
        "intake-idn", _VerifiedDraft(ev, verification_status="PENDING_REVIEW"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert again["outcome"] == NOOP_DRAFT_UP_TO_DATE
    assert again["wrote"] is False
    assert await _draft_count("intake-idn") == 1
