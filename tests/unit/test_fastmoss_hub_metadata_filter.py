"""FastMoss HUB ingestion must reject TikTok *creative* metadata (hashtags, music,
clip duration, CTA slogans) that Kalodata stages as "benefits/target/ingredients",
so a sanitary-napkin ref never inherits a SKINTIFIC clay-mask video caption as
product evidence. Genuine product copy must pass through untouched. No fabrication.
"""
from agent.services import fastmoss_bulk_promotion_service as svc


def test_hub_tiktok_video_metadata_rejected_at_ingestion(monkeypatch):
    contaminated = {
        "benefits_text": "#SKINTIFIC #SnailMucin #HydratingSerum #TikTokShopMY\n15-30s\nHydration music",
        "target_customer_text": "SKINTIFIC SNAIL MUCIN hydrating serum! Grab now!",
        "ingredients_text": "Snail power! Grab now!",
    }
    monkeypatch.setattr(svc, "_staged_hub_enrichment_for", lambda _ref: dict(contaminated))
    ref = {"id": "ref-x", "raw_product_title": "Tuala Wanita Postpartum 30 Keping", "category": "Fashion"}

    req = svc._ref_to_completion_request(ref)

    # video-caption junk must NOT become declared product evidence -> MISSING (grounded fill later)
    assert req.benefits_text is None
    assert req.target_customer_text is None
    assert req.ingredients_text is None


def test_hub_genuine_product_copy_preserved(monkeypatch):
    genuine = {
        "benefits_text": "Menyerap dengan baik, kalis bocor pada 360 darjah, selesa untuk ibu selepas bersalin.",
        "target_customer_text": "Ibu mengandung dan wanita selepas bersalin.",
        "ingredients_text": "Lapisan kapas lembut, teras penyerap SAP, lapisan luar bernafas.",
    }
    monkeypatch.setattr(svc, "_staged_hub_enrichment_for", lambda _ref: dict(genuine))
    ref = {"id": "ref-y", "raw_product_title": "Tuala Wanita Postpartum 30 Keping", "category": "Fashion"}

    req = svc._ref_to_completion_request(ref)

    assert req.benefits_text and "Menyerap" in req.benefits_text
    assert req.target_customer_text and "Ibu" in req.target_customer_text
    assert req.ingredients_text and "kapas" in req.ingredients_text
