"""B-08A-02 — approved Product Knowledge must survive registration commit.

Before this service, both commit lanes wrote identity / taxonomy / physics / commerce only.
Approved Product Knowledge was discarded, and `excluded_fields` could not reveal it because
that list only contains candidates the operator did NOT approve. These tests pin the
promotion contract and, critically, that promotion never approves anything.
"""
from __future__ import annotations

import pytest

from agent.services.registration_intelligence_promotion_service import (
    PROMOTION_MAP,
    build_create_request,
    build_promotion_payload,
    build_provenance_inputs,
)


class _Draft:
    """Minimal stand-in for RegistrationReviewDraft (only the read fields are used)."""

    def __init__(self, declared=None, candidates=None, approval=None, **kw):
        self.declared_evidence_fields = declared or {}
        self.canonical_candidate_fields = candidates or {}
        self.approval_checklist = approval or {}
        self.claim_risk_level = kw.get("claim_risk_level", "MEDIUM")
        self.claim_tokens = kw.get("claim_tokens", [])
        self.source_lane = kw.get("source_lane", "MANUAL")


def test_declared_evidence_is_promoted_without_needing_a_checkbox():
    """Declared evidence is the operator's own input, not a proposal."""
    payload = build_promotion_payload(_Draft(declared={
        "product_knowledge_text": "Cotton table skirting.",
        "usage_text": "Wipe with a damp cloth.",
        "package_notes": "One folded piece per polybag.",
    }))
    assert payload["fields"]["product_description"] == "Cotton table skirting."
    assert payload["fields"]["usage_text"] == "Wipe with a damp cloth."
    assert payload["fields"]["package_notes"] == "One folded piece per polybag."


def test_unapproved_candidate_is_dropped_with_an_explicit_reason():
    payload = build_promotion_payload(_Draft(
        candidates={"usage_text": "AI guessed usage"}, approval={"usage_text": False}))
    assert "usage_text" not in payload["fields"]
    assert payload["dropped_fields"] == [
        {"target": "usage_text", "source": "usage_text",
         "reason": "CANDIDATE_NOT_APPROVED_BY_OPERATOR"}]


def test_approved_candidate_is_promoted_and_marked_operator_approved():
    draft = _Draft(candidates={"target_customer": "Home cafe owners"},
                   approval={"target_customer": True})
    payload = build_promotion_payload(draft)
    assert payload["fields"]["target_customer_text"] == "Home cafe owners"
    prov = build_provenance_inputs(draft, payload)
    row = next(r for r in prov if r.field_name == "target_customer_text")
    assert row.evidence_kind == "OPERATOR_APPROVED_CANDIDATE"
    assert row.reviewer_decision == "OPERATOR_APPROVED"


def test_an_approved_field_with_no_target_is_reported_never_silently_lost():
    """The exact hole B-08A-02 describes: approved, unmapped, invisible."""
    payload = build_promotion_payload(_Draft(
        candidates={"some_future_field": "value"}, approval={"some_future_field": True}))
    assert any(d["reason"] == "NO_INTELLIGENCE_TARGET_FOR_APPROVED_FIELD"
               and d["source"] == "some_future_field"
               for d in payload["dropped_fields"])


def test_declared_evidence_outranks_a_candidate_for_the_same_target():
    payload = build_promotion_payload(_Draft(
        declared={"usage_text": "operator text"},
        candidates={"usage_summary": "ai text"},
        approval={"usage_summary": True}))
    assert payload["fields"]["usage_text"] == "operator text"


@pytest.mark.parametrize("target", [t for t, _ in PROMOTION_MAP])
def test_every_promotion_target_is_a_real_intelligence_draft_field(target):
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftCreateRequest as Req)
    assert target in Req.model_fields


def test_the_four_catalogue_empty_fields_are_all_promotable():
    """package_notes 0.0%, packaging_description 0.4%, product_form_factor 0.7%,
    size_or_volume 1.3% — the exact fields registration collected but never promoted."""
    targets = {t for t, _ in PROMOTION_MAP}
    assert {"package_notes", "packaging_description",
            "product_form_factor", "size_or_volume"} <= targets


def test_multiline_evidence_becomes_a_list_for_list_columns():
    payload = build_promotion_payload(_Draft(
        declared={"benefits_text": "Waterproof\nEasy to wipe\n"}))
    assert payload["fields"]["benefits_json"] == ["Waterproof", "Easy to wipe"]


def test_promotion_never_sets_any_approval_field():
    """Registration approval approves a VALUE. Product Truth approval is separate."""
    draft = _Draft(declared={"product_knowledge_text": "x"})
    payload = build_promotion_payload(draft)
    req = build_create_request(payload)
    dumped = req.model_dump()
    # Strongest form: the create contract has no approval surface at all, so promotion
    # cannot approve even by mistake.
    for approval_field in ("approved_by", "approved_at", "reviewed_by",
                           "claim_review_acknowledged"):
        assert not dumped.get(approval_field), approval_field
    for row in build_provenance_inputs(draft, payload):
        assert row.verification_status == "PENDING_REVIEW"


def test_source_and_image_evidence_are_carried_as_provenance():
    draft = _Draft(declared={
        "product_knowledge_text": "x",
        "source_url": "https://shop.example/p/1",
        "image_url": "https://cdn.example/1.jpg",
    })
    payload = build_promotion_payload(draft)
    assert payload["source_urls_json"]["source_url"] == "https://shop.example/p/1"
    assert payload["image_evidence_json"]["image_url"] == "https://cdn.example/1.jpg"
    assert build_provenance_inputs(draft, payload)[0].source_url == "https://shop.example/p/1"


def test_nothing_promotable_is_reported_rather_than_creating_an_empty_draft():
    payload = build_promotion_payload(_Draft())
    assert payload["fields"] == {}


def test_blank_and_whitespace_values_are_not_promoted():
    payload = build_promotion_payload(_Draft(
        declared={"usage_text": "   ", "warnings_text": ""}))
    assert "usage_text" not in payload["fields"]
    assert "warnings_text" not in payload["fields"]


# ── the invariant the mocked commit tests structurally cannot check ──────────
# Both existing commit test files patch promote_registration_to_intelligence out, so they
# pass whether or not a product ends up with an intelligence row. These exercise the real
# service against the real DB.

import pytest_asyncio  # noqa: E402

from agent.db import crud  # noqa: E402
from agent.db.schema import get_db  # noqa: E402
from agent.services.registration_intelligence_promotion_service import (  # noqa: E402
    promote_registration_to_intelligence,
)


async def _make_product(pid: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, "
        "product_short_name, lifecycle_status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (pid, "Promotion Fixture", "Promotion Fixture", "Promotion Fixture",
         "ACTIVE", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    await db.commit()


async def _drafts_for(pid: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=?", (pid,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows


@pytest.mark.asyncio
async def test_a_draft_with_no_promotable_knowledge_still_gets_an_intelligence_row():
    """REGRESSION: this returned early with intelligence_draft_id=None, and because the
    caller only treats an EXCEPTION as failure, commit reported COMMITTED while the
    product had zero intelligence rows — silently, and invisible to the KPI."""
    await _make_product("promo-empty")
    receipt = await promote_registration_to_intelligence(
        "promo-empty",
        _Draft(candidates={"category": "Beauty"}, approval={"category": True}),
    )
    assert receipt["intelligence_draft_id"], "a committed product must have a PI draft"
    assert receipt["minimal_draft"] is True
    assert receipt["reason"] == "NO_PROMOTABLE_FIELDS"
    assert len(await _drafts_for("promo-empty")) == 1


@pytest.mark.asyncio
async def test_promoted_knowledge_lands_in_the_intelligence_row_and_survives_reload():
    await _make_product("promo-full")
    receipt = await promote_registration_to_intelligence(
        "promo-full",
        _Draft(declared={
            "product_knowledge_text": "Cotton table skirting with lace trim.",
            "usage_text": "Wipe with a damp cloth.",
            "package_notes": "One folded piece per polybag.",
            "size_or_volume": "180cm x 75cm",
            "source_url": "https://shop.example/p/1",
        }),
    )
    assert receipt["minimal_draft"] is False
    rows = await _drafts_for("promo-full")
    assert len(rows) == 1
    row = rows[0]
    # the exact fields the catalogue audit found at ~0% because commit dropped them
    assert row["package_notes"] == "One folded piece per polybag."
    assert row["size_or_volume"] == "180cm x 75cm"
    assert row["usage_text"] == "Wipe with a damp cloth."
    assert row["product_description"] == "Cotton table skirting with lace trim."
    # and it is NOT approved by promotion
    assert not row["approved_by"]
    assert not row["approved_at"]


@pytest.mark.asyncio
async def test_promotion_writes_pending_review_provenance_per_field():
    await _make_product("promo-prov")
    await promote_registration_to_intelligence(
        "promo-prov", _Draft(declared={"product_knowledge_text": "x", "usage_text": "y"}))
    db = await get_db()
    cur = await db.execute(
        "SELECT field_name, source_type, verification_status FROM "
        "product_intelligence_review_field_provenance WHERE product_id=?", ("promo-prov",))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    # `create_review_draft` writes its own provenance too (e.g. source_urls_json), so
    # scope the assertion to the rows promotion itself is responsible for.
    mine = [r for r in rows if r["source_type"] == "REGISTRATION_COMMIT"]
    assert {r["field_name"] for r in mine} == {"product_description", "usage_text"}
    assert all(r["verification_status"] == "PENDING_REVIEW" for r in rows), (
        "no promotion path may pre-verify a field")
