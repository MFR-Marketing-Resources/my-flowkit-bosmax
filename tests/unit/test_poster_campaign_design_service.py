"""PR-B Campaign Design Brief, copy ranking and route authority tests."""

import pytest

from agent.models.copy_grounding import (
    ClaimGuardrails,
    CopyGrounding,
    BuyerPersona,
    ProductKnowledge,
    GROUNDING_APPROVED_SNAPSHOT,
    GROUNDING_MINIMAL,
)
from agent.models.poster_campaign_design_brief import (
    CAMPAIGN_BRIEF_REVIEW_READY,
    COPY_ROUTE_DRAFT_FALLBACK,
    PosterCampaignDesignBrief,
)
from agent.services.poster_campaign_design_service import (
    CampaignDesignBriefError,
    build_campaign_design_brief,
    generate_campaign_copy_routes,
    score_campaign_copy_route,
)
from agent.services.poster_design_system import font_readiness, resolve_design_route


PRODUCT = {
    "id": "prod-warisan-25ml",
    "product_display_name": "Minyak Warisan Cap Burung 25ml",
    "raw_product_title": "Minyak Warisan Cap Burung 25ml",
    "category": "Traditional Wellness",
    "subcategory": "Minyak tradisional",
    "product_type": "small bottle",
    "product_scale": "small_object",
    "physics_class": "liquid_bottle",
}


def _brief(**overrides):
    data = dict(
        product_id=PRODUCT["id"],
        product_name=PRODUCT["product_display_name"],
        approved_snapshot_id="snapshot-1",
        approved_snapshot_version=3,
        product_truth_status="RESTRICTED",
        approved_claims_status="APPROVED_SNAPSHOT_BOUND",
        audience="penjaga rumah di Malaysia",
        buyer_moment="rutin keluarga",
        desire="pilihan yang mudah dicapai",
        objection="sukar memilih produk yang jelas",
        trigger="masa menyediakan rutin harian",
        selected_message_angle="warisan yang dekat dengan rutin",
        singular_proposition="warisan yang dekat dengan rutin",
        reason_to_believe="Formula tradisional",
        approved_proof_points=["Formula tradisional"],
        tone="hangat dan meyakinkan",
        creative_territory="heritage craft translated through a restrained modern editorial grid",
        visual_metaphor_or_thesis="warisan dalam ritual sebenar",
        layout_family="HERITAGE_EDITORIAL",
        visual_tension="tactile heritage cues against contemporary clarity",
        product_anchor="registered silhouette=liquid_bottle",
        copy_anchor="headline -> support -> proof -> CTA",
        headline_personality="specific, warm, no vague superlatives",
        type_pairing_id="heritage-georgia-trebuchet-v1",
        color_strategy="material earth neutrals",
        cta_treatment="clear action cue",
        proof_treatment="editorial ruled facts",
        malaysian_context_route="relevant ritual; no generic prop substitution",
        review_status=CAMPAIGN_BRIEF_REVIEW_READY,
        design_route="HERITAGE_EDITORIAL",
        layout_variant="EDITORIAL_ASYMMETRY",
        field_provenance={"product_knowledge.usps": "APPROVED_SNAPSHOT.usp_json"},
    )
    data.update(overrides)
    return PosterCampaignDesignBrief(**data)


def _approved_grounding():
    return CopyGrounding(
        product_id=PRODUCT["id"],
        grounded=True,
        source=GROUNDING_APPROVED_SNAPSHOT,
        family="TRADITIONAL_WELLNESS",
        product_knowledge=ProductKnowledge(
            description="Minyak tradisional.",
            benefits=["Mudah disimpan"],
            usps=["Formula tradisional"],
        ),
        buyer_persona=BuyerPersona(
            audience="penjaga rumah di Malaysia",
            desires=["pilihan yang mudah dicapai"],
            objections=["sukar memilih produk yang jelas"],
            triggers=["masa menyediakan rutin harian"],
            tone="hangat dan meyakinkan",
        ),
        angle_strategies=["warisan yang dekat dengan rutin"],
        claim_guardrails=ClaimGuardrails(
            claim_gate="RESTRICTED",
            allowed_claims=["Formula tradisional"],
            blocked_claims=[],
            banned_terms=[],
        ),
        field_provenance={
            "buyer_persona.audience": "APPROVED_SNAPSHOT.buyer_persona_snapshot_json.audience",
            "buyer_persona.desires": "APPROVED_SNAPSHOT.buyer_persona_snapshot_json.desires",
            "buyer_persona.objections": "APPROVED_SNAPSHOT.buyer_persona_snapshot_json.objections",
            "buyer_persona.triggers": "APPROVED_SNAPSHOT.buyer_persona_snapshot_json.triggers",
            "buyer_persona.tone": "APPROVED_SNAPSHOT.buyer_persona_snapshot_json.tone",
            "angle_strategies": "APPROVED_SNAPSHOT.copy_strategy_summary_json.angles",
            "product_knowledge.usps": "APPROVED_SNAPSHOT.usp_json",
        },
    )


@pytest.mark.asyncio
async def test_missing_approved_intelligence_fails_closed(monkeypatch):
    async def fake_product(_product_id):
        return PRODUCT

    async def fake_grounding(_product):
        return CopyGrounding(product_id=PRODUCT["id"], source=GROUNDING_MINIMAL)

    async def fake_snapshot(_product_id):
        return None

    monkeypatch.setattr("agent.services.poster_campaign_design_service.crud.get_product", fake_product)
    monkeypatch.setattr("agent.services.poster_campaign_design_service.resolve_copy_grounding", fake_grounding)
    monkeypatch.setattr(
        "agent.services.poster_campaign_design_service.crud.get_latest_approved_product_intelligence_snapshot",
        fake_snapshot,
    )
    with pytest.raises(CampaignDesignBriefError) as exc:
        await build_campaign_design_brief(PRODUCT["id"], fail_closed=True)
    assert exc.value.code == "CAMPAIGN_INTELLIGENCE_INCOMPLETE"
    assert any("approved product-intelligence snapshot" in item for item in exc.value.blockers)


@pytest.mark.asyncio
async def test_approved_snapshot_provenance_survives_to_brief(monkeypatch):
    async def fake_product(_product_id):
        return PRODUCT

    async def fake_grounding(_product):
        return _approved_grounding()

    async def fake_snapshot(_product_id):
        return {"snapshot_id": "snapshot-1", "version": 3, "status": "APPROVED"}

    monkeypatch.setattr("agent.services.poster_campaign_design_service.crud.get_product", fake_product)
    monkeypatch.setattr("agent.services.poster_campaign_design_service.resolve_copy_grounding", fake_grounding)
    monkeypatch.setattr(
        "agent.services.poster_campaign_design_service.crud.get_latest_approved_product_intelligence_snapshot",
        fake_snapshot,
    )
    brief = await build_campaign_design_brief(
        PRODUCT["id"], objective="Product Hero", selected_angle="warisan yang dekat dengan rutin"
    )
    assert brief.review_status == CAMPAIGN_BRIEF_REVIEW_READY
    assert brief.approved_snapshot_id == "snapshot-1"
    assert brief.approved_snapshot_version == 3
    assert brief.field_provenance["product_knowledge.usps"].startswith("APPROVED_SNAPSHOT")
    assert brief.design_route == "HERITAGE_EDITORIAL"


def test_five_fallback_routes_are_distinct_and_not_production_ready():
    response = generate_campaign_copy_routes(_brief())
    assert len(response.candidates) == 5
    assert len({item.primary_message for item in response.candidates}) == 5
    assert all(item.status == COPY_ROUTE_DRAFT_FALLBACK for item in response.candidates)
    assert all(not item.production_eligible for item in response.candidates)
    assert response.provider_operation_count == 0
    assert response.hidden_retry_count == 0
    assert len(response.top_three_route_ids) == 3


def test_fallback_routes_use_canonical_product_name_not_internal_id():
    response = generate_campaign_copy_routes(_brief())
    assert PRODUCT["product_display_name"] in response.candidates[0].primary_message
    assert PRODUCT["id"] not in response.candidates[0].primary_message


def test_generic_fixture_is_below_production_threshold_and_reason_is_visible():
    score, reasons = score_campaign_copy_route(
        {
            "primary_message": "Warisan Tok, Kini Dalam Botol Premium",
            "support_message": "Sentuhan tradisional, gaya moden untuk seisi keluarga",
            "proof_points": [],
            "cta": "Dapatkan Sekarang",
        },
        _brief(),
    )
    assert score.total < 72
    assert any(reason.startswith("UNSUPPORTED_SUPERLATIVE") for reason in reasons)
    assert any(reason.startswith("GENERIC_PHRASE") for reason in reasons)


def test_copy_route_rejects_overlength_text_instead_of_clipping_it():
    score, reasons = score_campaign_copy_route(
        {
            "primary_message": "JBL PHANTOM P90 True Wireless Bluetooth In-Ear Earbuds: Deep waterproofing, ultra-long battery life",
            "support_message": "Ringkas.",
            "proof_points": [],
            "cta": "Lihat produk",
        },
        _brief(),
    )
    assert score.visual_fit_line_budget < 5
    assert any(reason.startswith("COPY_LENGTH_INVALID:") for reason in reasons)


def test_support_repetition_is_visible_as_a_copy_blocker():
    score, reasons = score_campaign_copy_route(
        {
            "primary_message": "Rutin keluarga",
            "support_message": "Rutin keluarga untuk setiap hari",
            "proof_points": ["Formula tradisional"],
            "cta": "Lihat produk",
        },
        _brief(),
    )
    assert score.non_redundancy < 5
    assert "SUPPORT_REPEATS_HEADLINE" in reasons


def test_route_changes_with_category_and_objective():
    heritage = resolve_design_route(PRODUCT, objective="Product Hero", selected_angle="Warisan")
    technical = resolve_design_route(
        {**PRODUCT, "category": "Consumer Electronics", "product_display_name": "Sensor Digital"},
        objective="Product Hero",
        selected_angle="Precision",
    )
    value = resolve_design_route(
        {**PRODUCT, "category": "Household", "product_display_name": "Set Nilai"},
        objective="Offer Promo",
        selected_angle="Value",
    )
    assert heritage["design_route"] == "HERITAGE_EDITORIAL"
    assert technical["design_route"] == "TECHNICAL_PRECISION"
    assert value["design_route"] == "BOLD_VALUE_COMMERCE"
    assert len(set(heritage["route_variants"])) >= 2


def test_route_font_pairing_and_readiness_fail_closed():
    assert font_readiness("HERITAGE_EDITORIAL")["font_license"] == "HOST_SYSTEM_LICENSED"
    with pytest.raises(ValueError, match="FONT_UNAVAILABLE"):
        font_readiness("TECHNICAL_PRECISION", available_families={"Arial"})


def test_provider_route_generation_is_one_explicit_operation(monkeypatch):
    calls = []

    def fake_complete(system, user):
        calls.append((system, user))
        return {
            "routes": [
                {
                    "route_id": f"AI_{i}",
                    "singular_proposition": "warisan yang dekat dengan rutin",
                    "primary_message": f"Formula tradisional {i}",
                    "support_message": "Pilihan jelas untuk rutin keluarga.",
                    "proof_points": ["Formula tradisional"],
                    "cta": "Lihat produk",
                    "tone": "hangat",
                }
                for i in range(1, 6)
            ]
        }

    response = generate_campaign_copy_routes(
        _brief(), invoke_provider=True, provider_complete=fake_complete
    )
    assert len(calls) == 1
    assert response.provider_operation_count == 1
    assert response.hidden_retry_count == 0
    assert len(response.candidates) == 5
