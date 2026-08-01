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
    real = tiktok.extract_product
    monkeypatch.setattr(
        tiktok, "extract_product",
        lambda url, **kw: real(url, page_text=html, **kw))


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
