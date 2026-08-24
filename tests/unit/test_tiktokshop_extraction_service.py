"""TikTok Shop source-first extraction.

The route previously returned TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED and created an empty
shell product. These tests pin the two properties that make the replacement safe to point
at a live URL: it cannot be turned into an SSRF primitive, and it cannot invent a fact the
page did not state.
"""
from __future__ import annotations

import pytest

from agent.services import tiktokshop_extraction_service as svc

LISTING_HTML = """
<html><head>
<meta property="og:title" content="Minyak Warisan Cap Burung 25ml" />
<meta property="og:description" content="Minyak urut tradisional untuk badan lenguh." />
<meta property="og:image" content="https://p16.tiktokcdn.com/img/minyak.jpg" />
<script type="application/ld+json">
{"@type":"Product","name":"Minyak Warisan Cap Burung 25ml",
 "description":"Minyak urut tradisional untuk badan lenguh. Saiz 25ml.",
 "brand":{"name":"Cap Burung"},
 "image":["https://p16.tiktokcdn.com/img/minyak.jpg"],
 "offers":{"@type":"Offer","price":"18.90","priceCurrency":"MYR"}}
</script>
</head><body><div>Saiz 25ml</div></body></html>
"""


# ── SSRF / transport safety ──────────────────────────────────────────────────

@pytest.mark.parametrize("url,code", [
    ("", svc.ERR_URL_MISSING),
    ("http://shop.tiktok.com/view/product/1", svc.ERR_URL_SCHEME),
    ("file:///etc/passwd", svc.ERR_URL_SCHEME),
    ("https://evil.example.com/view/product/1", svc.ERR_URL_HOST),
    # the classic near-miss: an attacker-controlled host that merely CONTAINS the
    # allowlisted domain must not pass
    ("https://tiktok.com.evil.example/view/product/1", svc.ERR_URL_HOST),
])
def test_url_validation_rejects_unsafe_targets(url, code):
    with pytest.raises(svc.TikTokShopExtractionError) as excinfo:
        svc.validate_source_url(url)
    assert excinfo.value.code == code


def test_allowlisted_host_resolving_to_a_private_address_is_rejected(monkeypatch):
    """DNS is attacker-influenced. An allowlisted name that resolves inside the network
    (cloud metadata, a VPC address, loopback) must still be refused."""
    monkeypatch.setattr(svc.socket, "getaddrinfo",
                        lambda *a, **k: [(0, 0, 0, "", ("169.254.169.254", 0))])
    with pytest.raises(svc.TikTokShopExtractionError) as excinfo:
        svc.validate_source_url("https://shop.tiktok.com/view/product/1")
    assert excinfo.value.code == svc.ERR_URL_PRIVATE


def test_a_public_allowlisted_host_is_accepted(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo",
                        lambda *a, **k: [(0, 0, 0, "", ("23.1.2.3", 0))])
    assert svc.validate_source_url("https://shop-my.tiktok.com/view/product/1")


# ── extraction is deterministic and source-bound ─────────────────────────────

def test_extracts_only_what_the_listing_states():
    result = svc.extract_product("https://shop.tiktok.com/view/product/1",
                                 page_text=LISTING_HTML, propose=False)
    fields = result["fields"]
    assert fields["raw_product_title"] == "Minyak Warisan Cap Burung 25ml"
    assert fields["brand"] == "Cap Burung"
    assert fields["price"] == 18.90
    assert fields["currency"] == "MYR"
    assert fields["image_url"].startswith("https://p16.tiktokcdn.com/")
    # 25ml IS stated on the page, so it is accepted
    assert fields["size_or_volume"] == "25ml"
    assert result["size_resolution"] == "EXTRACTED"
    # nothing was invented for fields the page never mentioned
    for never_stated in ("ingredients_text", "warnings_text", "commission_rate"):
        assert never_stated not in fields
    assert "warnings_text" in result["absent_extract_only_fields"]


def test_a_page_with_no_product_evidence_raises_instead_of_inventing():
    with pytest.raises(svc.TikTokShopExtractionError) as excinfo:
        svc.extract_product("https://shop.tiktok.com/view/product/1",
                            page_text="<html><body>404</body></html>", propose=False)
    assert excinfo.value.code == svc.ERR_NO_EVIDENCE


# ── size / variant: the pack-truth rules ─────────────────────────────────────

@pytest.mark.parametrize("label,reason", [
    ("Standard", "REJECTED_NOT_A_MEASUREMENT"),
    ("Default", "REJECTED_NOT_A_MEASUREMENT"),
    ("One Size", "REJECTED_NOT_A_MEASUREMENT"),
    ("Biru", "REJECTED_NO_UNIT"),
    ("", "ABSENT_IN_SOURCE"),
])
def test_merchandising_labels_are_never_accepted_as_a_pack_size(label, reason):
    """`Standard` as size_or_volume becomes fake pack truth and later drives scale locks
    in prompts — the same class of defect as the 25ml/roll-on incident."""
    value, got = svc.normalize_size(label, source_text="Standard Default One Size Biru")
    assert value is None
    assert got == reason


def test_a_size_not_present_in_the_source_is_refused():
    """Source-first: a measurement that did not come from the page is not evidence."""
    value, reason = svc.normalize_size("5 ML", source_text="no measurement here at all")
    assert value is None
    assert reason == "REJECTED_NOT_SUPPORTED_BY_SOURCE"
    # ... and the same string IS accepted once the page actually states it
    value_ok, reason_ok = svc.normalize_size("5 ML", source_text="Isi padu 5 ML sebotol")
    assert value_ok == "5 ML" and reason_ok == "EXTRACTED"


def test_multiple_variants_are_reported_ambiguous_rather_than_guessed():
    resolved, reason = svc.resolve_variant({"variant_labels": ["25ml", "60ml"]})
    assert resolved is None
    assert reason == "AMBIGUOUS_MULTIPLE_VARIANTS"


def test_exactly_one_real_variant_resolves():
    resolved, reason = svc.resolve_variant(
        {"variant_labels": ["25ml", "Standard"]})
    assert resolved == "25ml"
    assert reason == "EXACT_VARIANT_RESOLVED"


# ── candidates are proposals, never facts ────────────────────────────────────

def test_model_candidates_are_review_required_and_cannot_supply_extract_only_fields(
        monkeypatch):
    """A model that returns a price, an ingredient list or a warning must be ignored for
    those fields. Those are copied from the page or absent — never generated."""
    from agent.services import ai_copy_provider_adapter as adapter

    monkeypatch.setattr(adapter, "complete_json", lambda system, user, **kwargs: {
        "usage_text": "Sapu pada bahagian yang lenguh.",
        "target_customer_text": "Dewasa yang kerap sakit badan.",
        "warnings_text": "Jangan guna pada luka terbuka.",   # <- must be refused
        "ingredients_text": "Minyak kelapa, halia.",          # <- must be refused
        "price": 99.0,                                        # <- must be refused
    })
    result = svc.extract_product("https://shop.tiktok.com/view/product/1",
                                 page_text=LISTING_HTML, propose=True)
    assert result["candidate_status"] == "REVIEW_REQUIRED"
    assert "usage_text" in result["candidates"]
    assert "target_customer_text" in result["candidates"]
    for refused in ("warnings_text", "ingredients_text", "price"):
        assert refused not in result["candidates"], (
            f"{refused} was accepted from a model; it must come from the page or be absent")
    assert set(result["refused_model_fields"]) >= {"warnings_text", "ingredients_text",
                                                   "price"}
    # the extracted price survives untouched
    assert result["fields"]["price"] == 18.90


def test_an_unconfigured_provider_downgrades_instead_of_losing_the_extraction(monkeypatch):
    from agent.services import ai_copy_provider_adapter as adapter

    def not_configured(system, user, **kwargs):
        raise adapter.AICopyProviderNotConfigured(adapter.ERR_NOT_CONFIGURED)

    monkeypatch.setattr(adapter, "complete_json", not_configured)
    result = svc.extract_product("https://shop.tiktok.com/view/product/1",
                                 page_text=LISTING_HTML, propose=True)
    assert result["candidate_status"] == "PROVIDER_NOT_CONFIGURED"
    assert result["candidates"] == {}
    # a provider outage must not throw away a good deterministic extraction
    assert result["fields"]["raw_product_title"] == "Minyak Warisan Cap Burung 25ml"


def test_provenance_is_field_scoped_and_separates_extracted_from_proposed(monkeypatch):
    from agent.services import ai_copy_provider_adapter as adapter

    monkeypatch.setattr(adapter, "complete_json",
                        lambda system, user, **kwargs: {"usage_text": "Sapu dua kali sehari."})
    result = svc.extract_product("https://shop.tiktok.com/view/product/1",
                                 page_text=LISTING_HTML, propose=True)
    by_field = {row["field_name"]: row for row in result["provenance"]}

    assert by_field["price"]["evidence_kind"] == "IMPORTED_MARKETPLACE_LINK"
    assert by_field["price"]["extraction_method"].startswith("TIKTOKSHOP_")
    # a reviewer must be able to tell "the page says this" from "a model suggested this"
    assert by_field["usage_text"]["evidence_kind"] == "MODEL_PROPOSED_CANDIDATE"
    assert by_field["usage_text"]["extraction_method"] == "TIKTOKSHOP_TEXT_ASSIST"
    # nothing arrives pre-verified
    assert {row["verification_status"] for row in result["provenance"]} == {"PENDING_REVIEW"}
    assert all(row["source_url"] for row in result["provenance"])


# ── the route ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_route_persists_extracted_facts_but_not_model_candidates(monkeypatch):
    """Extracted page facts are evidence; model proposals are NOT auto-accepted.

    Writing a proposal into the draft IS accepting it, and acceptance is a human act. The
    route therefore returns candidates for review and stores only what the page stated.
    """
    from httpx import ASGITransport, AsyncClient

    from agent.api import products as api
    from agent.db.schema import get_db
    from agent.main import app

    def fake_extract(url, **kw):
        return {
            "fields": {"raw_product_title": "Minyak Warisan Cap Burung 25ml",
                       "brand": "Cap Burung", "price": 18.90, "currency": "MYR",
                       "size_or_volume": "25ml"},
            "candidates": {"usage_text": "MODEL PROPOSAL - must not be stored"},
            "candidate_status": "REVIEW_REQUIRED",
            "variant": "25ml", "variant_resolution": "EXACT_VARIANT_RESOLVED",
            "size_resolution": "EXTRACTED", "evidence_methods": ["JSONLD"],
            "absent_extract_only_fields": ["warnings_text"],
            "source_url": url, "provenance": [],
        }

    monkeypatch.setattr(
        "agent.services.tiktokshop_extraction_service.extract_product", fake_extract)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.post("/api/products/import-tiktokshop", json={
            "url": "https://shop-my.tiktok.com/view/product/route-test"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["manual_entry_required"] is False
    assert body["error_code"] is None
    assert body["extraction"]["candidates"]["usage_text"].startswith("MODEL PROPOSAL")

    product_id = body["product"]["id"]
    assert body["product"]["raw_product_title"] == "Minyak Warisan Cap Burung 25ml"

    db = await get_db()
    cursor = await db.execute(
        "SELECT usage_text, size_or_volume FROM product_intelligence_review_draft "
        "WHERE product_id=?", (product_id,))
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None, "the import left no intelligence draft"
    assert row[0] is None, "a model proposal was auto-accepted into the draft"
    assert row[1] == "25ml", "an extracted page fact did not reach the draft"


@pytest.mark.asyncio
async def test_import_route_still_creates_the_product_when_extraction_fails(monkeypatch):
    """A 404 or a timeout is not a reason to lose the URL the operator pasted — but it is
    also not a reason to invent fields."""
    from httpx import ASGITransport, AsyncClient

    from agent.main import app

    def boom(url, **kw):
        raise svc.TikTokShopExtractionError(svc.ERR_FETCH_FAILED, "http_404")

    monkeypatch.setattr(
        "agent.services.tiktokshop_extraction_service.extract_product", boom)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.post("/api/products/import-tiktokshop", json={
            "url": "https://shop-my.tiktok.com/view/product/gone",
            "raw_product_title": "Operator Typed Title"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["error_code"] == svc.ERR_FETCH_FAILED
    assert body["manual_entry_required"] is True
    assert body["extraction"]["fields"] == {}
    assert body["product"]["raw_product_title"] == "Operator Typed Title"


# ── B-08B-D1: marketplace boilerplate is not product knowledge ───────────────
# The live og:description template captured on the first pilot round, verbatim shape:
BOILERPLATE_DESC = ("Buy Teachers Day Gift Bag Cute School Bag Transparent Design on "
                    "TikTok Shop. Discover great prices on and get free shipping on "
                    "eligible items. Shop now for exclusive deals!")


def test_the_marketplace_seo_template_is_recognised():
    assert svc.is_marketplace_boilerplate(BOILERPLATE_DESC)
    # opener alone is enough — the template always frames "Buy <title> on TikTok Shop"
    assert svc.is_marketplace_boilerplate(
        "Buy Nakamichi Windshield Cleaner 30ml on TikTok Shop.")
    # two markers without the opener still trip the gate
    assert svc.is_marketplace_boilerplate(
        "Discover great prices on cleaning fluids. Shop now for exclusive deals!")


def test_a_genuine_description_mentioning_the_platform_once_is_not_rejected():
    """One incidental platform mention must not censor a real description."""
    assert not svc.is_marketplace_boilerplate(
        "Minyak urut tradisional 25ml, kini boleh didapati on TikTok Shop dan farmasi "
        "terpilih. Bahan semula jadi.")
    assert not svc.is_marketplace_boilerplate("Sarung kusyen velvet warna biru, 45cm.")
    assert not svc.is_marketplace_boilerplate("")


def test_boilerplate_og_description_never_becomes_an_extracted_field():
    """The defect that overwrote three curated descriptions on the first live pilot."""
    page = (f'<html><head><meta property="og:title" content="Gift Bag 24CM" />'
            f'<meta property="og:description" content="{BOILERPLATE_DESC}" />'
            "</head><body></body></html>")
    result = svc.extract_product("https://shop.tiktok.com/view/product/1",
                                 page_text=page, propose=False)
    assert "product_description" not in result["fields"]
    assert result["unresolved"]["product_description"] == \
        svc.REJECTED_MARKETPLACE_BOILERPLATE
    # the title is still real evidence and still lands
    assert result["fields"]["raw_product_title"] == "Gift Bag 24CM"


def test_a_real_og_description_still_fills_normally():
    page = ('<html><head><meta property="og:title" content="Gift Bag 24CM" />'
            '<meta property="og:description" content="Beg hadiah transparent 24CM '
            'untuk Hari Guru. Material tahan lasak." /></head><body></body></html>')
    result = svc.extract_product("https://shop.tiktok.com/view/product/1",
                                 page_text=page, propose=False)
    assert result["fields"]["product_description"].startswith("Beg hadiah transparent")
    assert "product_description" not in result["unresolved"]


# ── B-08B-D2: labelled sections stop at the review stream ────────────────────
def test_a_labelled_section_hard_stops_at_review_fingerprints():
    """The exact leak class from the first live pilot: spec text runs into reviews.

    `…Bottle 2026-04-21 C**N H**d S**r Verified purchase Belum test lagi…` was stored as
    ingredients_text. Masked usernames and "Verified purchase" cannot occur inside a
    genuine ingredient statement, so the first fingerprint ends the section.
    """
    text = ("Material: Silicone polymer, solvents C**N ·Verified purchase MY Belum "
            "test lagi dan barang sampai cepat")
    value = svc.extract_labelled_section(text, ("material",))
    assert value == "Silicone polymer, solvents"
    assert "Verified" not in value and "**" not in value


def test_a_review_only_region_after_a_label_yields_nothing_not_junk():
    """When the label is immediately followed by review prose, the honest answer is
    None — NOT the review text and NOT a model guess."""
    text = "Material: H**d S**r·Verified purchase Sangat puas hati barang ori"
    assert svc.extract_labelled_section(text, ("material",)) is None


def test_a_realistic_page_with_specs_and_reviews_extracts_specs_only():
    """Both regions on one page — the shape every rendered TikTok listing actually has."""
    page = ('<html><head><meta property="og:title" content="Pencuci Cermin 30ml" />'
            '<meta property="og:description" content="Pencuci cermin kereta 30ml." />'
            "</head><body><main>"
            "Specifications Ingredients: Aqua, surfactant blend, isopropanol "
            "Warning: Jauhkan dari kanak-kanak "
            "Customer Reviews (128) C**N ·Verified purchase 2026-04-21 Bagus sangat! "
            "H**d S**r ·Verified purchase Barang ori</main></body></html>")
    result = svc.extract_product("https://shop.tiktok.com/view/product/2",
                                 page_text=page, propose=False)
    assert result["fields"]["materials_text"] == "Aqua, surfactant blend, isopropanol"
    assert result["fields"]["warnings_text"] == "Jauhkan dari kanak-kanak"
    for value in result["fields"].values():
        assert "Verified" not in str(value)
        assert "**" not in str(value)
