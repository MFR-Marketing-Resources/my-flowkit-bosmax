"""Existing-product Product Intelligence Recompute.

The defect this closes: the TikTok extractor existed but was reachable only through
`POST /api/products/import-tiktokshop`, which CREATES a product. An operator who wanted to
refresh a product already in the catalogue had no governed path at all — and using the
import route would have minted a duplicate row every press.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from agent.db import crud
from agent.db.schema import get_db
from agent.main import app
from agent.services import product_intelligence_recompute_service as recompute
from agent.services import tiktokshop_extraction_service as tiktok

LISTING_HTML = """
<html><head>
<meta property="og:title" content="Minyak Warisan Cap Burung 25ml" />
<meta property="og:description" content="Minyak urut tradisional. Bahan: minyak kelapa, halia, serai. Amaran: Elak kawasan mata. Saiz 25ml." />
<meta property="og:image" content="https://p16.tiktokcdn.com/img/minyak.jpg" />
<script type="application/ld+json">
{"@type":"Product","name":"Minyak Warisan Cap Burung 25ml",
 "description":"Minyak urut tradisional. Bahan: minyak kelapa, halia, serai. Amaran: Elak kawasan mata. Saiz 25ml.",
 "brand":{"name":"Cap Burung"},
 "image":["https://p16.tiktokcdn.com/img/minyak.jpg"],
 "offers":{"@type":"Offer","price":"18.90","priceCurrency":"MYR"}}
</script></head><body></body></html>
"""


# Captured ONCE, before any monkeypatch. Re-reading `tiktok.extract_product` inside a
# helper picks up whatever stub is already installed, and re-wrapping that stub passes
# `page_text` twice.
_REAL_EXTRACT = tiktok.extract_product


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _product(title: str, **cols) -> dict:
    return await crud.create_product(raw_product_title=title, source="TIKTOKSHOP", **cols)


def _stub_extraction(monkeypatch, *, html: str = LISTING_HTML, candidates=None):
    """Drive the REAL extractor over fixed HTML: no network, real parsing/normalization."""
    def fake_complete_json(system, user):
        return candidates if candidates is not None else {}

    from agent.services import ai_copy_provider_adapter as adapter

    monkeypatch.setattr(adapter, "complete_json", fake_complete_json)
    monkeypatch.setattr(adapter, "provider_status",
                        lambda: {"provider_id": "deepseek", "model_id": "deepseek-chat"})
    monkeypatch.setattr(
        tiktok, "extract_product",
        lambda url, **kw: _REAL_EXTRACT(url, page_text=html, **kw))


async def _draft_row(product_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')", (product_id,))
    row = await cursor.fetchone()
    await cursor.close()
    return dict(row) if row else None


async def _provenance(product_id: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT field_name, source_type, evidence_kind, extraction_method, "
        "verification_status, source_url FROM "
        "product_intelligence_review_field_provenance WHERE product_id=?", (product_id,))
    rows = [dict(r) for r in await cursor.fetchall()]
    await cursor.close()
    return rows


@pytest.mark.asyncio
async def test_recompute_never_creates_a_product(monkeypatch):
    """THE defect. Recompute must operate on the product it was given."""
    _stub_extraction(monkeypatch)
    product = await _product("Recompute No Create",
                             tiktok_product_url="https://shop.tiktok.com/view/product/1")
    before = len(await crud.list_products(limit=5000, include_archived=True))

    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    assert response.status_code == 200, response.text

    after = len(await crud.list_products(limit=5000, include_archived=True))
    assert after == before, "recompute created a product row"
    assert response.json()["product_id"] == product["id"]
    assert (await crud.get_product(product["id"])) is not None


@pytest.mark.asyncio
async def test_recompute_is_idempotent_and_never_opens_a_second_draft(monkeypatch):
    _stub_extraction(monkeypatch)
    product = await _product("Recompute Idempotent",
                             tiktok_product_url="https://shop.tiktok.com/view/product/2")
    async with await _client() as client:
        first = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
        second = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    assert first.status_code == second.status_code == 200
    assert first.json()["draft_id"] == second.json()["draft_id"]
    # identical evidence a second time is a no-op, not a new review item
    assert second.json()["intake_outcome"] in (
        "NOOP_DRAFT_UP_TO_DATE", "NOOP_APPROVED_SNAPSHOT")

    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=? "
        "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')",
        (product["id"],))
    assert (await cursor.fetchone())[0] == 1
    await cursor.close()


@pytest.mark.asyncio
async def test_exact_per_field_provenance_is_persisted_not_a_generic_lane_label(
        monkeypatch):
    """A lane-wide TIKTOKSHOP_LINK label throws away HOW each field was obtained.

    Extraction knows the description came from JSON-LD/meta and that materials came from
    an explicitly LABELLED section; that difference must survive into the database.
    """
    _stub_extraction(monkeypatch)
    product = await _product("Recompute Provenance",
                             tiktok_product_url="https://shop.tiktok.com/view/product/3")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    assert response.status_code == 200, response.text

    rows = {r["field_name"]: r for r in await _provenance(product["id"])}
    assert rows, "recompute persisted no provenance at all"
    assert "TIKTOKSHOP_RECOMPUTE" not in rows["product_description"]["extraction_method"], (
        "the generic lane label overwrote the exact extraction method")
    assert "JSONLD" in rows["product_description"]["extraction_method"] or \
           "META" in rows["product_description"]["extraction_method"]
    assert rows["ingredients_text"]["extraction_method"] == "TIKTOKSHOP_LABELLED_SECTION"
    assert rows["warnings_text"]["extraction_method"] == "TIKTOKSHOP_LABELLED_SECTION"
    # Scoped to the fields THIS lane promoted. `create_review_draft` also writes its own
    # REVIEW_DRAFT rows for source_urls_json / image_evidence_json, which are a different
    # (and legitimate) evidence class.
    for field in ("product_description", "ingredients_text", "warnings_text",
                  "size_or_volume"):
        row = rows[field]
        assert row["source_url"], "provenance without a source URL is not evidence"
        assert row["source_type"] == "IMPORTED_TIKTOKSHOP"
        assert row["verification_status"] == "PENDING_REVIEW", (
            "extracted page evidence must not arrive pre-verified")


@pytest.mark.asyncio
async def test_materials_and_warnings_are_extracted_deterministically_not_generated(
        monkeypatch):
    """Labelled sections are read from the page. A model is never asked for these."""
    _stub_extraction(monkeypatch)
    product = await _product("Recompute Materials",
                             tiktok_product_url="https://shop.tiktok.com/view/product/4")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    body = response.json()
    assert "minyak kelapa" in body["extracted_fields"]["materials_text"].lower()
    assert "mata" in body["extracted_fields"]["warnings_text"].lower()

    draft = await _draft_row(product["id"])
    assert "minyak kelapa" in (draft["ingredients_text"] or "").lower()
    assert "mata" in (draft["warnings_text"] or "").lower()
    assert draft["size_or_volume"] == "25ml"


@pytest.mark.asyncio
async def test_a_page_without_labelled_sections_records_unresolved_and_invents_nothing(
        monkeypatch):
    sparse = ('<html><head><meta property="og:title" content="Sarung Kusyen Biru" />'
              '<meta property="og:description" content="Sarung kusyen warna biru." />'
              "</head><body></body></html>")
    _stub_extraction(monkeypatch, html=sparse)
    product = await _product("Recompute Sparse",
                             tiktok_product_url="https://shop.tiktok.com/view/product/5")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    body = response.json()

    assert body["unresolved"]["ingredients_text"] == "NOT_STATED_IN_SOURCE"
    assert body["unresolved"]["warnings_text"] == "NOT_STATED_IN_SOURCE"
    assert "size_or_volume" in body["unresolved"]
    assert "materials_text" not in body["extracted_fields"]
    assert "warnings_text" not in body["extracted_fields"]

    draft = await _draft_row(product["id"])
    assert not (draft["ingredients_text"] or "").strip(), "an ingredient list was invented"
    assert not (draft["warnings_text"] or "").strip(), "a warning was invented"
    assert not (draft["size_or_volume"] or "").strip(), "a pack size was invented"


@pytest.mark.asyncio
async def test_usp_and_other_candidates_are_persisted_as_AI_PROPOSED_and_survive_reload(
        monkeypatch):
    """USP was missing from the candidate contract entirely. It must be proposable, and a
    proposal must still be there — and still visibly unratified — after a reload."""
    _stub_extraction(monkeypatch, candidates={
        "usp_list": ["Formula tradisional", "Botol kecil mudah bawa"],
        "usage_text": "Sapu pada bahagian yang lenguh.",
        "warnings_text": "MODEL INVENTED WARNING",   # must be refused upstream
    })
    product = await _product("Recompute USP",
                             tiktok_product_url="https://shop.tiktok.com/view/product/6")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    body = response.json()
    persisted = {item["field"] for item in body["candidates_persisted"]}
    assert "usp_json" in persisted, "USP is still not in the candidate contract"
    assert "usage_text" in persisted

    # RELOAD: read back through the API the UI actually calls
    async with await _client() as client:
        reloaded = await client.get(
            f"/api/product-intelligence/review-drafts/{body['draft_id']}")
    assert reloaded.status_code == 200
    draft = reloaded.json()
    assert "Formula tradisional" in json.dumps(draft["usp_json"])
    assert draft["usage_text"].startswith("Sapu pada")
    # the model's warning was refused; the PAGE's warning is what is stored
    assert "MODEL INVENTED WARNING" not in json.dumps(draft)

    prov = {r["field_name"]: r for r in await _provenance(product["id"])}
    assert prov["usp_json"]["verification_status"] == "AI_PROPOSED", (
        "a model proposal is indistinguishable from operator evidence")
    assert prov["usp_json"]["extraction_method"].startswith("deepseek:")
    # and it is NOT approved
    assert draft["review_status"] not in ("APPROVED",)


@pytest.mark.asyncio
async def test_recompute_never_overwrites_evidence_a_human_already_entered(monkeypatch):
    _stub_extraction(monkeypatch, candidates={"usage_text": "MODEL TEXT"})
    product = await _product("Recompute Preserve",
                             tiktok_product_url="https://shop.tiktok.com/view/product/7")
    async with await _client() as client:
        first = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
        draft_id = first.json()["draft_id"]
        await client.patch(
            f"/api/product-intelligence/review-drafts/{draft_id}",
            json={"usage_text": "OPERATOR TYPED THIS"})
        again = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    skipped = {item["field"] for item in again.json()["candidates_skipped"]}
    assert "usage_text" in skipped
    draft = await _draft_row(product["id"])
    assert draft["usage_text"] == "OPERATOR TYPED THIS"


@pytest.mark.asyncio
async def test_save_draft_does_not_approve_and_creates_no_snapshot(monkeypatch):
    _stub_extraction(monkeypatch)
    product = await _product("Recompute SaveOnly",
                             tiktok_product_url="https://shop.tiktok.com/view/product/8")
    async with await _client() as client:
        body = (await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")).json()
        saved = await client.patch(
            f"/api/product-intelligence/review-drafts/{body['draft_id']}",
            json={"target_customer_text": "Dewasa aktif."})
    assert saved.status_code == 200
    assert saved.json()["review_status"] != "APPROVED"

    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_snapshot WHERE product_id=?",
        (product["id"],))
    assert (await cursor.fetchone())[0] == 0, "Save Draft created an approved snapshot"
    await cursor.close()


@pytest.mark.asyncio
async def test_recompute_reports_a_missing_source_link_instead_of_pretending_to_work():
    product = await _product("Recompute No URL")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    assert response.status_code == 422
    assert recompute.ERR_NO_SOURCE_URL in response.json()["detail"]


@pytest.mark.asyncio
async def test_recompute_on_an_unknown_product_is_404():
    async with await _client() as client:
        response = await client.post(
            "/api/product-intelligence/does-not-exist/recompute")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_unreadable_listing_fails_loudly_rather_than_reporting_empty_success(
        monkeypatch):
    def boom(url, **kw):
        raise tiktok.TikTokShopExtractionError(tiktok.ERR_FETCH_FAILED, "http_404")

    monkeypatch.setattr(tiktok, "extract_product", boom)
    product = await _product("Recompute Unreadable",
                             tiktok_product_url="https://shop.tiktok.com/view/product/9")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    assert response.status_code == 502
    assert tiktok.ERR_FETCH_FAILED in response.json()["detail"]


@pytest.mark.asyncio
async def test_failed_link_import_without_operator_identity_creates_no_placeholder(
        monkeypatch):
    """The catalogue must never gain a row literally titled TIKTOKSHOP_PENDING_METADATA."""
    from agent.api import products as api

    def boom(url, **kw):
        raise tiktok.TikTokShopExtractionError(tiktok.ERR_FETCH_FAILED, "http_404")

    monkeypatch.setattr(tiktok, "extract_product", boom)
    before = len(await crud.list_products(limit=5000, include_archived=True))
    async with await _client() as client:
        response = await client.post("/api/products/import-tiktokshop", json={
            "url": "https://shop-my.tiktok.com/view/product/unreachable"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["manual_entry_required"] is True
    assert body["product"] is None

    after = await crud.list_products(limit=5000, include_archived=True)
    assert len(after) == before, "a placeholder product was committed"
    assert not [p for p in after
                if p.get("raw_product_title") == "TIKTOKSHOP_PENDING_METADATA"]
    assert api  # imported for the monkeypatch target module to be loaded


# ── the CURRENT real-world failure, captured from the live response ──────────
# Verbatim shape of what shop.tiktok.com actually returned on 2026-08-01 for every
# product URL tried: HTTP 200, ~5.6KB, titled "Security Check", zero product data.
SECURITY_CHALLENGE_HTML = (
    '<html><head><meta charset="utf-8"><title>Security Check</title>'
    '<script nonce="x" charset="utf-8" src="https://sf16-website-login.neutral.'
    'ttwstatic.com/obj/tiktok_web_login_static/oec-ttweb-captcha/loader/sg/1.0.0.55/'
    'captcha/index.js"></script></head><body>'
    '<div class="middle_page_loading"></div></body></html>'
)


def test_the_security_wall_is_detected_and_is_never_treated_as_evidence():
    """HTTP 200 does not mean "we were shown the product".

    Parsing this page would "succeed" with an empty product, and a Recompute that then
    wrote that emptiness over good stored evidence would be silent data loss dressed up
    as a successful refresh.
    """
    assert tiktok.looks_like_security_challenge(SECURITY_CHALLENGE_HTML)
    with pytest.raises(tiktok.TikTokShopExtractionError) as excinfo:
        tiktok.extract_product("https://shop.tiktok.com/view/product/1",
                               page_text=SECURITY_CHALLENGE_HTML, propose=False)
    # NOT the generic no-evidence code: this is an authentication problem, and calling it
    # a data-quality problem would hide the real fix forever.
    assert excinfo.value.code == tiktok.ERR_AUTHENTICATED_BROWSER_REQUIRED
    assert not tiktok.looks_like_security_challenge(LISTING_HTML)


def _stub_wall(monkeypatch):
    """Every direct fetch now hits TikTok's Security Check — the live 2026-08-01 state."""
    monkeypatch.setattr(
        tiktok, "extract_product",
        lambda url, **kw: _REAL_EXTRACT(url, page_text=SECURITY_CHALLENGE_HTML, **kw))


class _FakeExtensionBridge:
    """The WebSocket bridge, without a browser. Records what the relay actually sent.

    Method-aware since the recompute lane now NAVIGATES the dedicated evidence tab before it
    READS it: TIKTOK_NAVIGATE_PRODUCT_TAB gets `nav_reply` (PAGE_READY by default so the lane
    proceeds to the read), TIKTOK_ACQUIRE_PRODUCT_EVIDENCE gets the configured `reply`.
    """

    def __init__(self, reply, *, connected=True, nav_reply=None):
        self._reply = reply
        self._nav_reply = nav_reply if nav_reply is not None else {
            "ok": True, "outcome": "PAGE_READY"}
        self.connected = connected
        self.sent: list[tuple[str, dict]] = []

    async def _send(self, method, params, timeout=0):
        self.sent.append((method, params))
        if method == "TIKTOK_NAVIGATE_PRODUCT_TAB":
            return self._nav_reply(params) if callable(self._nav_reply) else self._nav_reply
        return self._reply(params) if callable(self._reply) else self._reply


def _install_bridge(monkeypatch, bridge):
    from agent.services import flow_client as flow_client_module

    monkeypatch.setattr(flow_client_module, "get_flow_client", lambda: bridge)
    return bridge


# What an authenticated tab actually yields: the SAME listing the anonymous fetcher is
# walled away from.
RELAYED_EVIDENCE = {
    "canonical_url": "https://shop.tiktok.com/view/product/1729543210987654321",
    "title": "Minyak Warisan Cap Burung 25ml",
    "description": ("Minyak urut tradisional. Bahan: minyak kelapa, halia, serai. "
                    "Amaran: Elak kawasan mata."),
    "brand": "Cap Burung",
    "price_text": "18.90",
    "currency": "MYR",
    "variant_labels": ["25ml"],
    "images": ["https://p16.tiktokcdn.com/img/minyak.jpg"],
    "page_text": ("Minyak Warisan Cap Burung 25ml Minyak urut tradisional. "
                  "Bahan: minyak kelapa, halia, serai. Amaran: Elak kawasan mata."),
    "evidence_methods": ["JSONLD"],
}
RELAY_URL = RELAYED_EVIDENCE["canonical_url"]


def _relay_reply(*, ok=True, evidence=None, error=None):
    def build(params):
        return {"result": {
            "ok": ok,
            "error": error,
            "evidence_request_id": params["evidence_request_id"],
            "tab_id": 7,
            "matched_tabs": 1,
            "observed_url": RELAY_URL,
            "evidence": evidence,
        }}
    return build


@pytest.mark.asyncio
async def test_the_wall_with_no_extension_fails_closed_and_corrupts_nothing(monkeypatch):
    """Fail-closed proof against the ACTUAL blocker, with no browser available.

    Must be an explicit, named acquisition failure — not an HTTP 500, not a duplicate
    product, not a wiped draft. The relay is ATTEMPTED (that is the Phase B change), and
    when there is no extension to attempt it through, that specific fact is what surfaces.
    """
    _stub_extraction(monkeypatch)   # first pass: real evidence, real draft
    product = await _product("Recompute Wall",
                             tiktok_product_url="https://shop.tiktok.com/view/product/w")
    async with await _client() as client:
        good = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    assert good.status_code == 200
    assert good.json()["acquisition_mode"] == "DIRECT_FETCH"
    draft_before = await _draft_row(product["id"])
    prov_before = await _provenance(product["id"])
    products_before = len(await crud.list_products(limit=5000, include_archived=True))

    # now the wall goes up on the very next refresh, and no extension is connected
    _stub_wall(monkeypatch)
    _install_bridge(monkeypatch, _FakeExtensionBridge({}, connected=False))
    async with await _client() as client:
        blocked = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    # 409, not 502: the operator fixes this in their own browser. Calling it a server
    # fault would leave them with no reason to believe a Retry could ever work.
    assert blocked.status_code == 409, "a bot wall must not surface as a 500"
    detail = blocked.json()["detail"]
    assert detail["code"] == "TIKTOK_RELAY_EXTENSION_DISCONNECTED"
    assert detail["operator_actionable"] is True

    assert len(await crud.list_products(limit=5000, include_archived=True)) == \
        products_before, "the failed refresh created a product"
    draft_after = await _draft_row(product["id"])
    assert draft_after == draft_before, "the failed refresh mutated the draft"
    assert await _provenance(product["id"]) == prov_before, (
        "the failed refresh mutated provenance")
    assert await _draft_row(product["id"]) is not None, "the draft was destroyed"


@pytest.mark.asyncio
async def test_a_still_present_captcha_is_reported_and_never_solved(monkeypatch):
    """The operator clears TikTok's challenge by hand. Nothing here works around it."""
    _stub_wall(monkeypatch)
    # The wall is detected at NAVIGATION (the readiness probe): a challenge shell states no
    # product, so it can never be mistaken for a readable listing. One navigation attempt,
    # never a read, never a solve.
    bridge = _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(evidence=RELAYED_EVIDENCE),
        nav_reply={"ok": False, "outcome": "SECURITY_CHECK_REQUIRES_HUMAN"}))
    product = await _product("Recompute Captcha", tiktok_product_url=RELAY_URL)

    async with await _client() as client:
        blocked = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "TIKTOK_RELAY_SECURITY_CHECK_PRESENT"
    assert detail["product_url"] == RELAY_URL, (
        "the operator is told to open a link the screen never shows them")
    # ONE acquisition attempt: no retry loop that could read as challenge-grinding.
    assert len(bridge.sent) == 1
    # and absolutely nothing was written
    assert await _draft_row(product["id"]) is None
    assert await _provenance(product["id"]) == []


@pytest.mark.asyncio
async def test_no_open_product_tab_is_its_own_actionable_state(monkeypatch):
    _stub_wall(monkeypatch)
    _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(ok=False, error="TIKTOK_NO_MATCHING_TAB")))
    product = await _product("Recompute NoTab", tiktok_product_url=RELAY_URL)

    async with await _client() as client:
        blocked = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "TIKTOK_RELAY_NO_MATCHING_TAB"
    assert await _draft_row(product["id"]) is None, "a failed acquisition opened a draft"


@pytest.mark.asyncio
async def test_the_authenticated_tab_completes_the_lane_the_wall_was_blocking(monkeypatch):
    """THE mission: walled server fetch -> authenticated tab -> review-required draft.

    Proves the whole chain in one place — real evidence lands, provenance records that it
    came from a browser read, DeepSeek output stays unratified, and nothing is approved.
    """
    _stub_extraction(monkeypatch)          # wires the provider stubs...
    _stub_wall(monkeypatch)                # ...then the wall goes up on the direct lane
    _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(evidence=RELAYED_EVIDENCE)))
    product = await _product("Recompute Relayed", tiktok_product_url=RELAY_URL)

    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["acquisition_mode"] == "AUTHENTICATED_BROWSER_RELAY"
    assert body["relay"]["matched_tabs"] == 1
    assert body["approved"] is False, "recompute approved something"

    # The deterministic rules still hold on relayed evidence — same normalizer.
    assert body["extracted_fields"]["size_or_volume"] == "25ml"
    draft = await _draft_row(product["id"])
    assert draft is not None, "the relayed evidence produced no draft"
    assert "minyak kelapa" in (draft["ingredients_text"] or "").lower()
    assert "mata" in (draft["warnings_text"] or "").lower()
    assert draft["review_status"] != "APPROVED"

    prov = {r["field_name"]: r for r in await _provenance(product["id"])}
    assert "AUTHENTICATED_DOM" in prov["product_description"]["extraction_method"], (
        "a browser read is indistinguishable from an anonymous fetch in the evidence table")
    assert prov["ingredients_text"]["extraction_method"] == "TIKTOKSHOP_LABELLED_SECTION"
    assert prov["product_description"]["verification_status"] == "PENDING_REVIEW"

    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_snapshot WHERE product_id=?",
        (product["id"],))
    assert (await cursor.fetchone())[0] == 0, "the relay produced an approved snapshot"
    await cursor.close()


@pytest.mark.asyncio
async def test_retrying_the_relay_duplicates_no_draft_and_no_provenance(monkeypatch):
    """Safe retry. The operator WILL press Retry more than once — that must be free."""
    _stub_extraction(monkeypatch)
    _stub_wall(monkeypatch)
    _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(evidence=RELAYED_EVIDENCE)))
    product = await _product("Recompute Retry", tiktok_product_url=RELAY_URL)

    async with await _client() as client:
        first = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
        after_first = await _provenance(product["id"])
        second = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert first.status_code == second.status_code == 200
    assert first.json()["draft_id"] == second.json()["draft_id"]

    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=? "
        "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')",
        (product["id"],))
    assert (await cursor.fetchone())[0] == 1, "Retry opened a second draft"
    await cursor.close()
    assert len(await _provenance(product["id"])) == len(after_first), (
        "Retry duplicated provenance rows")


@pytest.mark.asyncio
async def test_a_plain_data_failure_never_demands_a_browser(monkeypatch):
    """Only the auth wall routes to the relay.

    A dead link is a defect in the source. Sending those through the browser too would turn
    every data-quality problem into a demand that the operator go open a tab.
    """
    def boom(url, **kw):
        raise tiktok.TikTokShopExtractionError(tiktok.ERR_FETCH_FAILED, "http_404")

    monkeypatch.setattr(tiktok, "extract_product", boom)
    bridge = _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(evidence=RELAYED_EVIDENCE)))
    product = await _product("Recompute DataFail", tiktok_product_url=RELAY_URL)

    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert response.status_code == 502
    assert tiktok.ERR_FETCH_FAILED in response.json()["detail"]
    assert bridge.sent == [], "a dead link was escalated to the operator's browser"


@pytest.mark.asyncio
async def test_a_working_direct_fetch_never_touches_the_browser(monkeypatch):
    """The relay is the exception path, not the default. It costs an operator; the plain
    HTTPS GET costs nothing."""
    _stub_extraction(monkeypatch)
    bridge = _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(evidence=RELAYED_EVIDENCE)))
    product = await _product("Recompute DirectOnly",
                             tiktok_product_url="https://shop.tiktok.com/view/product/d")

    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert response.status_code == 200
    assert response.json()["acquisition_mode"] == "DIRECT_FETCH"
    assert bridge.sent == [], "a healthy direct fetch still went through the browser"


@pytest.mark.asyncio
async def test_a_link_the_relay_cannot_open_says_so_instead_of_promising_a_retry(
        monkeypatch):
    """The manifest grants exactly two hosts. Anything else must refuse honestly."""
    _stub_wall(monkeypatch)
    bridge = _install_bridge(monkeypatch, _FakeExtensionBridge(
        _relay_reply(evidence=RELAYED_EVIDENCE)))
    product = await _product(
        "Recompute WrongHost",
        tiktok_product_url="https://shop.tiktokglobalshop.com/view/product/5")

    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "TIKTOK_RELAY_HOST_NOT_SUPPORTED"
    # NOT actionable — no amount of opening tabs fixes a link on an unsupported host.
    assert detail["operator_actionable"] is False
    assert bridge.sent == []


# ── B-08B-D1/D2: the data-quality invariants proven at the API boundary ──────
BOILERPLATE_PAGE = (
    '<html><head><meta property="og:title" content="Gift Bag 24CM Transparent" />'
    '<meta property="og:description" content="Buy Gift Bag 24CM Transparent on TikTok '
    'Shop. Discover great prices on and get free shipping on eligible items. Shop now '
    'for exclusive deals!" />'
    '<meta property="og:image" content="https://p16.tiktokcdn.com/img/bag.jpg" />'
    "</head><body></body></html>")


@pytest.mark.asyncio
async def test_a_curated_description_survives_a_recompute_with_divergent_page_text(
        monkeypatch):
    """THE B-08B-D1 defect. A refresh fills, it never replaces.

    The first live pilot swapped three curated descriptions for TikTok's og:description.
    Here the draft holds a curated value, the page states something different and
    NON-boilerplate — and the curated value must still win, with the divergence
    REPORTED rather than silently applied or silently dropped.
    """
    _stub_extraction(monkeypatch)
    product = await _product("Recompute CuratedWins",
                             tiktok_product_url="https://shop.tiktok.com/view/product/c1")
    async with await _client() as client:
        first = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
        draft_id = first.json()["draft_id"]
        # the operator curates the description
        await client.patch(
            f"/api/product-intelligence/review-drafts/{draft_id}",
            json={"product_description": "CURATED: Minyak urut 25ml, botol kaca."})
        again = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    body = again.json()
    preserved = {item["field"]: item for item in body["evidence_skipped"]}
    assert "product_description" in preserved, (
        "the divergence was not reported — preservation must be visible, not silent")
    assert preserved["product_description"]["reason"] == "EXISTING_EVIDENCE_PRESERVED"
    assert preserved["product_description"]["extracted_value_not_stored"], (
        "the discarded page text must be shown so a reviewer can adopt it deliberately")

    draft = await _draft_row(product["id"])
    assert draft["product_description"] == "CURATED: Minyak urut 25ml, botol kaca.", (
        "marketplace extraction overwrote a curated description")


@pytest.mark.asyncio
async def test_seo_boilerplate_never_lands_even_in_an_empty_description(monkeypatch):
    """An EMPTY field is not a license to store the marketplace's SEO template."""
    _stub_extraction(monkeypatch, html=BOILERPLATE_PAGE)
    product = await _product("Recompute BoilerplateEmpty",
                             tiktok_product_url="https://shop.tiktok.com/view/product/c2")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["unresolved"]["product_description"] == \
        tiktok.REJECTED_MARKETPLACE_BOILERPLATE
    assert "product_description" not in body["extracted_fields"]

    draft = await _draft_row(product["id"])
    assert draft is not None
    stored = draft["product_description"] or ""
    assert "Shop now for exclusive deals" not in stored
    assert "Discover great prices" not in stored


@pytest.mark.asyncio
async def test_a_boilerplate_model_candidate_is_refused_for_an_empty_description(
        monkeypatch):
    """The candidate door enforces the same gate as the extraction door."""
    _stub_extraction(monkeypatch, html=BOILERPLATE_PAGE, candidates={
        "product_description": ("Buy Gift Bag 24CM Transparent on TikTok Shop. "
                                "Shop now for exclusive deals!"),
        "product_form_factor": "Transparent PVC gift bag",
    })
    product = await _product("Recompute BoilerplateCandidate",
                             tiktok_product_url="https://shop.tiktok.com/view/product/c3")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    body = response.json()
    skipped = {item["field"]: item["reason"] for item in body["candidates_skipped"]}
    assert skipped.get("product_description") == "REJECTED_MARKETPLACE_BOILERPLATE"
    persisted = {item["field"] for item in body["candidates_persisted"]}
    assert "product_form_factor" in persisted, (
        "a legitimate candidate was collateral damage of the boilerplate gate")

    draft = await _draft_row(product["id"])
    assert "Shop now" not in (draft["product_description"] or "")
    assert draft["product_form_factor"] == "Transparent PVC gift bag"


@pytest.mark.asyncio
async def test_a_legitimate_empty_description_still_fills_from_real_page_text(
        monkeypatch):
    """The preserve rule must not break the fill-from-source purpose of Recompute."""
    _stub_extraction(monkeypatch)   # LISTING_HTML carries a real og:description
    product = await _product("Recompute FillEmpty",
                             tiktok_product_url="https://shop.tiktok.com/view/product/c4")
    async with await _client() as client:
        response = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
    draft = await _draft_row(product["id"])
    assert (draft["product_description"] or "").startswith("Minyak urut tradisional")
    assert response.json()["evidence_skipped"] == []


@pytest.mark.asyncio
async def test_preserve_and_retry_together_stay_idempotent(monkeypatch):
    """Retry after preservation: same draft, no duplicate provenance, values intact."""
    _stub_extraction(monkeypatch)
    product = await _product("Recompute PreserveRetry",
                             tiktok_product_url="https://shop.tiktok.com/view/product/c5")
    async with await _client() as client:
        first = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
        draft_id = first.json()["draft_id"]
        await client.patch(
            f"/api/product-intelligence/review-drafts/{draft_id}",
            json={"product_description": "CURATED KEKAL."})
        second = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")
        prov_after_second = await _provenance(product["id"])
        third = await client.post(
            f"/api/product-intelligence/{product['id']}/recompute")

    assert second.json()["draft_id"] == third.json()["draft_id"] == draft_id
    draft = await _draft_row(product["id"])
    assert draft["product_description"] == "CURATED KEKAL."
    assert len(await _provenance(product["id"])) == len(prov_after_second), (
        "a preserved-field retry manufactured provenance rows")
