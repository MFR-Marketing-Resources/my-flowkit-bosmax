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


async def _open_draft_count(pid: str) -> int:
    db = await get_db()
    from agent.services.product_intelligence_draft_lifecycle import SQL_OPEN_PREDICATE

    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=? "
        f"AND {SQL_OPEN_PREDICATE}", (pid,))
    n = (await cur.fetchone())[0]
    await cur.close()
    return int(n)


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
    review_status = row.pop("review_status", "APPROVED")
    cur = await db.execute(
        "SELECT 1 FROM product_intelligence_review_draft WHERE draft_id=?", (draft_id,))
    exists = await cur.fetchone()
    await cur.close()
    if not exists:
        await db.execute(
            "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
            "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (draft_id, pid, review_status, "2026-01-01T00:00:00Z",
             "2026-01-01T00:00:00Z"))
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
    await _seed_provenance("intake-d", draft_id="approved-d")
    await _snapshot("intake-d", "snap-d", status="APPROVED",
                    product_description="Ratified truth.",
                    created_from_review_draft_id="approved-d")
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


# ── B-586-02 final: field scoping + snapshot lineage ────────────────────────

@pytest.mark.asyncio
async def test_one_fields_verified_provenance_cannot_cover_another_field():
    """VERIFIED product_description must not vouch for PENDING warnings_text from the
    same page. evidence_signature previously omitted field_name entirely."""
    await _product("intake-fs")
    url = "https://shop-my.tiktok.com/pdp/fs"
    await _seed_provenance("intake-fs", draft_id="fs-draft", field_name="product_description",
                           source_url=url, source_type="SOURCE_PAGE",
                           extraction_method="DOM_EXTRACTION",
                           verification_status="VERIFIED")
    await _seed_provenance("intake-fs", draft_id="fs-draft", field_name="warnings_text",
                           source_url=url, source_type="SOURCE_PAGE",
                           extraction_method="DOM_EXTRACTION",
                           verification_status="PENDING_REVIEW")
    from agent.services.product_intake_service import provenance_is_covered
    stored = await _prov_rows("intake-fs")
    incoming = [{"field_name": "warnings_text", "source_url": url,
                 "source_type": "SOURCE_PAGE", "extraction_method": "DOM_EXTRACTION",
                 "verification_status": "VERIFIED"}]
    assert provenance_is_covered(stored, incoming) is False, (
        "product_description's VERIFIED row covered warnings_text")


@pytest.mark.asyncio
async def test_B_approved_terminal_draft_with_zero_open_drafts_opens_a_new_review_draft():
    """The realistic state: one terminal APPROVED draft + its provenance + an APPROVED
    snapshot + ZERO open drafts. The earlier Case B left an open draft around, so it only
    proved an update path."""
    await _product("intake-b2")
    url = "https://shop-my.tiktok.com/pdp/b2"
    await _seed_provenance("intake-b2", draft_id="b2-approved",
                           field_name="product_description", source_url=url,
                           source_type="SOURCE_PAGE", extraction_method="DOM_EXTRACTION",
                           verification_status="PENDING_REVIEW")
    await _snapshot("intake-b2", "snap-b2", status="APPROVED",
                    product_description="Ratified.",
                    created_from_review_draft_id="b2-approved")
    open_before = await _open_draft_count("intake-b2")
    assert open_before == 0, "precondition: no open draft"

    r = await ensure_product_intelligence(
        "intake-b2",
        _VerifiedDraft({"product_knowledge_text": "Ratified.", "source_url": url},
                       verification_status="VERIFIED"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")

    assert r["outcome"] != NOOP_APPROVED_SNAPSHOT
    assert await _snapshot_status("snap-b2") == "APPROVED", "snapshot was disturbed"
    assert await _open_draft_count("intake-b2") == 1, "exactly one new open draft expected"
    new_rows = [x for x in await _prov_rows("intake-b2")
                if x["verification_status"] == "VERIFIED"]
    assert new_rows, "stronger provenance was not persisted"


@pytest.mark.asyncio
async def test_verified_provenance_from_a_rejected_draft_is_not_snapshot_coverage():
    """A rejected draft's evidence must never vouch for the current approved snapshot."""
    await _product("intake-rej")
    url = "https://shop-my.tiktok.com/pdp/rej"
    # the snapshot's real lineage carries only weak evidence
    await _seed_provenance("intake-rej", draft_id="rej-approved",
                           field_name="product_description", source_url=url,
                           source_type="SOURCE_PAGE", extraction_method="DOM_EXTRACTION",
                           verification_status="PENDING_REVIEW")
    await _snapshot("intake-rej", "snap-rej", status="APPROVED",
                    product_description="Ratified.",
                    created_from_review_draft_id="rej-approved")
    # an unrelated REJECTED draft happens to hold VERIFIED evidence
    await _seed_provenance("intake-rej", draft_id="rej-bad", review_status="REJECTED",
                           field_name="product_description", source_url=url,
                           source_type="SOURCE_PAGE", extraction_method="DOM_EXTRACTION",
                           verification_status="VERIFIED")

    r = await ensure_product_intelligence(
        "intake-rej",
        _VerifiedDraft({"product_knowledge_text": "Ratified.", "source_url": url},
                       verification_status="VERIFIED"),
        lane="PRODUCTS_TIKTOKSHOP_IMPORT")
    assert r["outcome"] != NOOP_APPROVED_SNAPSHOT, (
        "a rejected draft's VERIFIED row created a false no-op")


# ── B-586-03 atomicity ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provenance_failure_leaves_no_partial_draft_or_provenance(monkeypatch):
    """Injected failure DURING the provenance batch must leave nothing behind."""
    from agent.services import product_intake_service as pis

    await _product("intake-atomic")
    real = pis.build_provenance_inputs
    calls = {"n": 0}

    def boom(draft, payload):
        rows = real(draft, payload)
        calls["n"] += 1
        raise RuntimeError("provenance store offline")

    monkeypatch.setattr(pis, "build_provenance_inputs", boom)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-atomic",
            _Draft(declared={"product_knowledge_text": "Atomic test.",
                             "usage_text": "wipe"}),
            lane="PRODUCTS_MANUAL")

    assert await _draft_count("intake-atomic") == 0, "partial draft survived"
    assert await _prov_rows("intake-atomic") == [], "partial provenance survived"

    # retry after the fault clears succeeds exactly once
    monkeypatch.setattr(pis, "build_provenance_inputs", real)
    r = await pis.ensure_product_intelligence(
        "intake-atomic",
        _Draft(declared={"product_knowledge_text": "Atomic test.", "usage_text": "wipe"}),
        lane="PRODUCTS_MANUAL")
    assert r["outcome"] == CREATED
    assert await _draft_count("intake-atomic") == 1
    assert await _prov_rows("intake-atomic"), "retry wrote no provenance"


@pytest.mark.asyncio
async def test_a_failed_provenance_batch_is_all_or_nothing(monkeypatch):
    """The batch itself is one transaction: a failure on the 2nd row leaves 0 rows."""
    from agent.db.schema import get_db
    from agent.services import product_intake_service as pis

    await _product("intake-batch")
    db = await get_db()
    real_execute = db.execute
    state = {"n": 0}

    async def flaky(sql, *a, **k):
        if "INSERT INTO product_intelligence_review_field_provenance" in str(sql):
            state["n"] += 1
            if state["n"] == 2:
                raise RuntimeError("disk full mid-batch")
        return await real_execute(sql, *a, **k)

    monkeypatch.setattr(db, "execute", flaky)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-batch",
            _Draft(declared={"product_knowledge_text": "row one",
                             "usage_text": "row two", "warnings_text": "row three"}),
            lane="PRODUCTS_MANUAL")
    monkeypatch.setattr(db, "execute", real_execute)
    assert await _prov_rows("intake-batch") == [], "first row of the batch was retained"
    assert await _draft_count("intake-batch") == 0, "draft survived a failed batch"


@pytest.mark.asyncio
async def test_an_approved_snapshot_survives_a_failed_provenance_batch(monkeypatch):
    from agent.services import product_intake_service as pis

    await _product("intake-atomic-s")
    await _seed_provenance("intake-atomic-s", draft_id="as-approved")
    await _snapshot("intake-atomic-s", "snap-as", status="APPROVED",
                    product_description="Ratified.",
                    created_from_review_draft_id="as-approved")

    def boom(draft, payload):
        raise RuntimeError("provenance store offline")

    monkeypatch.setattr(pis, "build_provenance_inputs", boom)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-atomic-s",
            _Draft(declared={"product_knowledge_text": "Changed after approval."}),
            lane="PRODUCTS_MANUAL")
    assert await _snapshot_status("snap-as") == "APPROVED"


# ── B-586-04 concurrency across INDEPENDENT connections ─────────────────────

@pytest.mark.asyncio
async def test_concurrent_first_intake_yields_exactly_one_open_draft():
    """Both racers are the same seam, which is the real production shape: two requests
    for the same product arriving before either has committed a draft."""
    import asyncio

    from agent.services import product_intake_service as pis

    await _product("intake-race")
    ev = _Draft(declared={"product_knowledge_text": "Race me.", "usage_text": "wipe"})
    results = await asyncio.gather(*[
        pis.ensure_product_intelligence("intake-race", ev, lane="PRODUCTS_MANUAL")
        for _ in range(4)
    ])
    assert await _open_draft_count("intake-race") == 1, (
        "concurrent first intake produced duplicate open drafts")
    # every caller is told about the SAME surviving draft
    ids = {r["intelligence_draft_id"] for r in results if r.get("intelligence_draft_id")}
    assert len(ids) == 1, f"callers disagreed on the surviving draft: {ids}"


@pytest.mark.asyncio
async def test_a_draft_created_by_another_connection_is_reconciled_not_duplicated():
    """A second connection commits an open draft mid-flight. The seam must converge on one
    survivor rather than leaving two."""
    import sqlite3

    from agent.db.schema import DB_PATH
    from agent.services import product_intake_service as pis

    await _product("intake-race2")
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("aaaa-other-connection", "intake-race2", "DRAFT", "CLAIM_REVIEW_REQUIRED",
         "MEDIUM", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    con.commit()
    con.close()

    await pis.ensure_product_intelligence(
        "intake-race2",
        _Draft(declared={"product_knowledge_text": "Mine.", "usage_text": "wipe"}),
        lane="PRODUCTS_MANUAL")
    assert await _open_draft_count("intake-race2") == 1


def _raw_connections():
    """Two INDEPENDENT sqlite3 connections to the same file as the app.

    An asyncio lock cannot serialize these, which is the whole point: B-586-04 has to hold
    even when the racers share no Python state. Deliberately NOT the app's aiosqlite
    connection.
    """
    import sqlite3

    from agent.config import DB_PATH

    a = sqlite3.connect(str(DB_PATH), timeout=30)
    b = sqlite3.connect(str(DB_PATH), timeout=30)
    for con in (a, b):
        con.execute("PRAGMA foreign_keys=ON")
    return a, b


@pytest.mark.asyncio
async def test_database_itself_rejects_a_second_open_draft_across_two_connections():
    """B-586-04. The invariant must be enforced by the DATABASE.

    The previous rule ran in application code AFTER both inserts had committed and then
    deleted the loser. Two independent connections defeat it: neither sees the other's
    uncommitted row, so both insert, and whichever cleanup runs last decides. Here the
    second INSERT must simply fail.
    """
    import sqlite3

    await _product("intake-dbrace")
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("dbrace-first", "intake-dbrace", "DRAFT", "2026-01-01T00:00:00Z",
         "2026-01-01T00:00:00Z"))
    await db.commit()

    con_a, con_b = _raw_connections()
    try:
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            con_b.execute(
                "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
                "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
                ("dbrace-second", "intake-dbrace", "NEEDS_REVISION",
                 "2026-01-01T00:00:01Z", "2026-01-01T00:00:01Z"))
            con_b.commit()
        assert "UNIQUE" in str(excinfo.value).upper()
        con_b.rollback()

        # ... yet a TERMINAL duplicate is still allowed: history is never blocked.
        con_a.execute(
            "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
            "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
            ("dbrace-history", "intake-dbrace", "SUPERSEDED", "2026-01-01T00:00:02Z",
             "2026-01-01T00:00:02Z"))
        con_a.commit()
    finally:
        con_a.close()
        con_b.close()

    assert await _open_draft_count("intake-dbrace") == 1
    assert await _draft_count("intake-dbrace") == 2


@pytest.mark.asyncio
async def test_losing_racer_merges_its_evidence_instead_of_deleting_anything():
    """The loser must not vanish and must not delete the winner.

    The old rule deleted the losing draft outright, so whatever that racer had captured
    was gone. Now the loser reconciles: fields the winner left EMPTY are adopted, and a
    real disagreement is reported rather than silently overwritten.
    """
    from agent.services import product_intake_service as pis

    await _product("intake-lostrace")
    db = await get_db()
    # the "winner": already committed by a rival connection, with usage_text EMPTY
    await db.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, product_description, usage_text, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("lostrace-winner", "intake-lostrace", "NEEDS_REVISION", "Winner text.", None,
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    await db.commit()

    payload = {"fields": {"product_description": "Loser text.", "usage_text": "Apply."}}
    result = await pis._reconcile_lost_race("intake-lostrace", payload)

    assert result["draft_id"] == "lostrace-winner"
    # winner was silent about usage_text -> adopted, nothing lost
    assert result["merged_fields"] == ["usage_text"]
    # winner already had a DIFFERENT product_description -> conflict, not overwritten
    assert result["conflicting_fields"] == ["product_description"]

    cur = await db.execute(
        "SELECT product_description, usage_text FROM "
        "product_intelligence_review_draft WHERE draft_id='lostrace-winner'")
    row = await cur.fetchone()
    await cur.close()
    assert row[0] == "Winner text.", "a rival's committed value was overwritten"
    assert row[1] == "Apply.", "the loser's non-conflicting evidence was discarded"
    assert await _open_draft_count("intake-lostrace") == 1


@pytest.mark.asyncio
async def test_every_caller_receives_the_same_live_draft_id():
    """A converged product must not hand different callers different draft ids."""
    from agent.services.product_intake_service import _latest_open_draft

    await _product("intake-samelive")
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("samelive-open", "intake-samelive", "DRAFT", "2026-01-01T00:00:00Z",
         "2026-01-01T00:00:00Z"))
    # a superseded sibling must never be served as the live draft
    await db.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("samelive-old", "intake-samelive", "SUPERSEDED", "2026-01-02T00:00:00Z",
         "2026-01-02T00:00:00Z"))
    await db.commit()

    seen = set()
    for _ in range(3):
        row, _terminal = await _latest_open_draft("intake-samelive")
        seen.add(row["draft_id"])
    assert seen == {"samelive-open"}


@pytest.mark.asyncio
async def test_superseded_rows_keep_every_value_and_all_their_provenance():
    """Convergence must not be a disguised delete, and must not fabricate a review."""
    await _product("intake-keepev")
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_review_draft (draft_id, product_id, "
        "review_status, product_description, usage_text, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("keepev-loser", "intake-keepev", "SUPERSEDED", "Losing evidence.", "Rub in.",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    await db.execute(
        "INSERT INTO product_intelligence_review_field_provenance ("
        "review_provenance_id, draft_id, product_id, field_name, source_type, "
        "evidence_kind, extraction_method, verification_status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("keepev-prov", "keepev-loser", "intake-keepev", "usage_text", "IMPORTED_FASTMOSS",
         "IMPORTED_MARKETPLACE_ROW", "FASTMOSS_WORKBOOK", "PENDING_REVIEW",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    await db.commit()

    cur = await db.execute(
        "SELECT product_description, usage_text, approved_by, approved_at, rejected_by, "
        "rejected_at, reviewed_by FROM product_intelligence_review_draft "
        "WHERE draft_id='keepev-loser'")
    row = await cur.fetchone()
    await cur.close()
    assert row[0] == "Losing evidence." and row[1] == "Rub in."
    assert all(v is None for v in row[2:]), (
        "convergence fabricated a reviewer identity or a review decision")

    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_field_provenance "
        "WHERE draft_id='keepev-loser'")
    assert (await cur.fetchone())[0] == 1, "superseded evidence lost its provenance"
    await cur.close()


@pytest.mark.asyncio
async def test_no_product_in_the_catalogue_holds_two_open_drafts():
    """The catalogue-wide invariant. Must be zero, always."""
    from agent.services.product_intelligence_draft_lifecycle import SQL_OPEN_PREDICATE

    db = await get_db()
    cur = await db.execute(
        "SELECT product_id, COUNT(*) c FROM product_intelligence_review_draft "
        f"WHERE {SQL_OPEN_PREDICATE} GROUP BY product_id HAVING c > 1")
    offenders = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    assert offenders == [], f"products holding >1 open draft: {offenders}"


@pytest.mark.asyncio
async def test_the_unique_index_is_persisted_in_the_schema_not_just_in_memory():
    """"Survives restart" means it lives in sqlite_master, not in a runtime guard."""
    from agent.services.product_intelligence_draft_lifecycle import (
        UNIQUE_OPEN_DRAFT_INDEX,
    )

    db = await get_db()
    cur = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
        (UNIQUE_OPEN_DRAFT_INDEX,))
    row = await cur.fetchone()
    await cur.close()
    assert row is not None, "the constraint is not in the persisted schema"
    assert "UNIQUE" in row[0].upper()
    assert "PRODUCT_ID" in row[0].upper()


@pytest.mark.asyncio
async def test_a_failed_update_never_destroys_pre_existing_provenance(monkeypatch):
    """REGRESSION: the update rollback called _delete_provenance_for_draft, wiping EVERY
    provenance row on the draft — including evidence written by earlier operations that
    this request never touched. A rollback must not destroy data it did not write."""
    from agent.services import product_intake_service as pis

    await _product("intake-noloss")
    await pis.ensure_product_intelligence(
        "intake-noloss",
        _Draft(declared={"product_knowledge_text": "Original.", "usage_text": "wipe"}),
        lane="PRODUCTS_MANUAL")
    before = await _prov_rows("intake-noloss")
    assert before, "precondition: provenance exists"

    # build_provenance_inputs is ALSO used by the coverage check, which runs first. If it
    # raises there the rollback path is never reached and the test proves nothing, so fail
    # only on the write call (the 2nd invocation).
    real = pis.build_provenance_inputs
    state = {"n": 0}

    def boom(draft, payload):
        state["n"] += 1
        if state["n"] >= 2:
            raise RuntimeError("provenance store offline")
        return real(draft, payload)

    monkeypatch.setattr(pis, "build_provenance_inputs", boom)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-noloss",
            _Draft(declared={"product_knowledge_text": "Changed text.",
                             "usage_text": "wipe"}),
            lane="PRODUCTS_MANUAL")
    monkeypatch.setattr(pis, "_write_provenance", real)
    assert state["n"] >= 1, "the write path was never reached; test proves nothing"

    after = await _prov_rows("intake-noloss")
    assert len(after) == len(before), (
        f"rollback destroyed pre-existing provenance: {len(before)} -> {len(after)}")


# ── B-586-03: the persistence boundary ────────────────────────────────────────
# Row COUNTS are too weak a test. A rollback that restores a hand-listed subset of
# columns keeps the count identical while leaving the failed operation's values in
# every column nobody remembered to list. These compare complete row CONTENT.

async def _draft_rows_hash(pid: str) -> str:
    """SHA-256 over every column of every draft row for this product."""
    import hashlib
    import json

    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        "ORDER BY draft_id", (pid,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


async def _prov_rows_hash(pid: str) -> str:
    """SHA-256 over every column of every provenance row for this product."""
    import hashlib
    import json

    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_field_provenance WHERE product_id=? "
        "ORDER BY review_provenance_id", (pid,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def _fail_on_provenance_write(monkeypatch, pis):
    """Inject a failure ONLY after the draft mutation has already been applied.

    Deliberately targets `_write_provenance` rather than `build_provenance_inputs`.
    `build_provenance_inputs` is ALSO called by the coverage check, and that check
    short-circuits on `material_is_covered` before reaching it — so a call-counting
    injection fires on the wrong call (or never), and the test silently proves nothing.
    `_write_provenance` is called only from inside the transaction, immediately after
    `create_review_draft` / `update_review_draft`, which is exactly the window B-586-03
    is about. Returns a counter the test MUST assert on, so a mis-armed injection fails
    loudly instead of passing vacuously.
    """
    real = pis._write_provenance
    state = {"n": 0}

    async def boom(draft_id, product_id, draft, payload):
        state["n"] += 1
        raise RuntimeError("provenance store offline")

    monkeypatch.setattr(pis, "_write_provenance", boom)
    return state, real


@pytest.mark.asyncio
async def test_failed_update_restores_the_complete_before_state_not_just_some_columns(
        monkeypatch):
    """B-586-03. EVERY column and EVERY provenance row must match the before-state.

    The compensating version restored only the promotion targets plus review_status, so
    `source_urls_json`, `image_evidence_json`, `completeness_score`, `readiness_status`,
    `claim_gate` and `updated_at` all silently kept the FAILED operation's values. Row
    hashes catch that; row counts do not.
    """
    from agent.services import product_intake_service as pis

    await _product("intake-b03-full")
    await pis.ensure_product_intelligence(
        "intake-b03-full",
        _Draft(declared={"product_knowledge_text": "Original knowledge.",
                         "usage_text": "Apply twice daily.",
                         "source_url": "https://example.test/original"}),
        lane="PRODUCTS_MANUAL")

    before_drafts = await _draft_rows_hash("intake-b03-full")
    before_prov = await _prov_rows_hash("intake-b03-full")
    assert await _prov_rows("intake-b03-full"), "precondition: provenance exists"

    state, real = _fail_on_provenance_write(monkeypatch, pis)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-b03-full",
            _Draft(declared={"product_knowledge_text": "MUTATED knowledge.",
                             "usage_text": "Apply once.",
                             "source_url": "https://example.test/changed"}),
            lane="PRODUCTS_MANUAL")
    monkeypatch.setattr(pis, "_write_provenance", real)
    assert state["n"] >= 1, "the write path was never reached; test proves nothing"

    assert await _draft_rows_hash("intake-b03-full") == before_drafts, (
        "draft row content differs from the before-state after rollback")
    assert await _prov_rows_hash("intake-b03-full") == before_prov, (
        "provenance row content differs from the before-state after rollback")


@pytest.mark.asyncio
async def test_failed_first_intake_leaves_neither_draft_nor_provenance(monkeypatch):
    """A create that fails must leave the product exactly as it was: nothing at all."""
    from agent.services import product_intake_service as pis

    await _product("intake-b03-create")
    assert await _draft_count("intake-b03-create") == 0

    state, real = _fail_on_provenance_write(monkeypatch, pis)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-b03-create",
            _Draft(declared={"product_knowledge_text": "Never persisted.",
                             "usage_text": "wipe",
                             "source_url": "https://example.test/new"}),
            lane="PRODUCTS_MANUAL")
    monkeypatch.setattr(pis, "_write_provenance", real)
    assert state["n"] >= 1, "the write path was never reached; test proves nothing"

    assert await _draft_count("intake-b03-create") == 0, "an orphan draft survived"
    assert await _prov_rows("intake-b03-create") == [], "orphan provenance survived"


@pytest.mark.asyncio
async def test_a_rollback_never_removes_another_requests_committed_work(monkeypatch):
    """B-586-03. The old cleanup was scoped by PRODUCT and ran after the fact, so it
    could not tell its own partial work from a rival's finished work. A failing request
    must not touch a concurrent request that already succeeded."""
    from agent.services import product_intake_service as pis

    await _product("intake-b03-rivalA")
    await _product("intake-b03-rivalB")

    # rival A succeeds and commits
    ok = await pis.ensure_product_intelligence(
        "intake-b03-rivalA",
        _Draft(declared={"product_knowledge_text": "Rival A survived.",
                         "usage_text": "wipe"}),
        lane="PRODUCTS_MANUAL")
    assert ok["wrote"] is True
    rival_drafts = await _draft_rows_hash("intake-b03-rivalA")
    rival_prov = await _prov_rows_hash("intake-b03-rivalA")

    # rival B fails and rolls back
    state, real = _fail_on_provenance_write(monkeypatch, pis)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-b03-rivalB",
            _Draft(declared={"product_knowledge_text": "Rival B dies.",
                             "usage_text": "wipe"}),
            lane="PRODUCTS_MANUAL")
    monkeypatch.setattr(pis, "_write_provenance", real)
    assert state["n"] >= 1

    assert await _draft_rows_hash("intake-b03-rivalA") == rival_drafts, (
        "a failing request's rollback destroyed a concurrent request's draft")
    assert await _prov_rows_hash("intake-b03-rivalA") == rival_prov, (
        "a failing request's rollback destroyed a concurrent request's provenance")
    assert await _draft_count("intake-b03-rivalB") == 0


@pytest.mark.asyncio
async def test_retry_after_a_rolled_back_failure_succeeds_exactly_once(monkeypatch):
    """The rollback must leave the product retryable, and the retry must not duplicate."""
    from agent.services import product_intake_service as pis

    await _product("intake-b03-retry")
    state, real = _fail_on_provenance_write(monkeypatch, pis)
    with pytest.raises(RuntimeError):
        await pis.ensure_product_intelligence(
            "intake-b03-retry",
            _Draft(declared={"product_knowledge_text": "Attempt one.",
                             "usage_text": "wipe"}),
            lane="PRODUCTS_MANUAL")
    monkeypatch.setattr(pis, "_write_provenance", real)
    assert state["n"] >= 1
    assert await _draft_count("intake-b03-retry") == 0

    retried = await pis.ensure_product_intelligence(
        "intake-b03-retry",
        _Draft(declared={"product_knowledge_text": "Attempt one.",
                         "usage_text": "wipe"}),
        lane="PRODUCTS_MANUAL")
    assert retried["outcome"] in (CREATED, CREATED_MINIMAL)
    assert await _draft_count("intake-b03-retry") == 1
    assert await _open_draft_count("intake-b03-retry") == 1
    assert await _prov_rows("intake-b03-retry"), "the retry wrote no provenance"

    # replaying the identical evidence is a no-op, not a second draft
    again = await pis.ensure_product_intelligence(
        "intake-b03-retry",
        _Draft(declared={"product_knowledge_text": "Attempt one.",
                         "usage_text": "wipe"}),
        lane="PRODUCTS_MANUAL")
    assert again["outcome"] == NOOP_DRAFT_UP_TO_DATE
    assert await _draft_count("intake-b03-retry") == 1
