"""PR-C Campaign poster QA, review and deterministic variant contracts."""
from __future__ import annotations

import json

import pytest

from agent.models.poster_campaign_design_brief import (
    CAMPAIGN_BRIEF_REVIEW_READY,
    CampaignCopyRoute,
    CopyRouteScore,
    PosterCampaignDesignBrief,
)
from agent.models.poster_campaign_qa import CampaignReviewRequest
from agent.models.poster_render_manifest import PosterRenderReport, ZoneRenderResult
from agent.services.poster_campaign_qa_service import (
    CampaignQAError,
    build_campaign_machine_qa,
    build_campaign_post_composition_qa,
    build_pre_provider_lint,
    build_world_class_review,
)
from agent.services.poster_campaign_variant_service import build_campaign_variants
from agent.services.poster_template_service import build_render_manifest


def _brief() -> PosterCampaignDesignBrief:
    return PosterCampaignDesignBrief(
        product_id="prod-1",
        approved_snapshot_id="snapshot-1",
        approved_snapshot_version=4,
        approved_claims_status="APPROVED_SNAPSHOT_BOUND",
        audience="penjaga rumah Malaysia",
        buyer_moment="rutin keluarga",
        desire="pilihan mudah dicapai",
        objection="mahu produk yang jelas",
        trigger="masa rutin harian",
        selected_message_angle="warisan dekat dengan rutin",
        singular_proposition="warisan dekat dengan rutin",
        reason_to_believe="Formula tradisional",
        approved_proof_points=["Formula tradisional"],
        tone="hangat dan meyakinkan",
        creative_territory="heritage editorial yang terkawal",
        visual_metaphor_or_thesis="warisan dalam ritual sebenar",
        layout_family="HERITAGE_EDITORIAL",
        visual_tension="tactile heritage lawan grid moden",
        product_anchor="registered liquid bottle silhouette",
        copy_anchor="headline support proof CTA",
        headline_personality="specific and warm",
        headline_line_budget=2,
        type_pairing_id="heritage-georgia-trebuchet-v1",
        color_strategy="material earth neutrals",
        cta_treatment="clear action cue",
        proof_treatment="editorial fact note",
        malaysian_context_route="approved ritual context",
        field_provenance={"product_knowledge.usps": "APPROVED_SNAPSHOT.usp_json"},
        review_status=CAMPAIGN_BRIEF_REVIEW_READY,
        design_route="HERITAGE_EDITORIAL",
        layout_variant="EDITORIAL_ASYMMETRY",
    )


def _candidate(**overrides) -> CampaignCopyRoute:
    data = {
        "route_id": "route-1",
        "singular_proposition": "Warisan dekat dengan rutin",
        "primary_message": "Warisan dekat dengan rutin",
        "support_message": "Formula tradisional untuk pilihan keluarga.",
        "approved_proof_points": ["Formula tradisional"],
        "cta": "Lihat pilihan",
        "copy_provenance": {"primary_message": "APPROVED_SNAPSHOT.copy_strategy"},
        "score": CopyRouteScore(
            product_specificity=8,
            customer_relevance=8,
            immediate_comprehension=8,
            reason_to_believe=8,
            emotional_commercial_tension=8,
            natural_malaysian_malay=8,
            proof_relevance=8,
            non_redundancy=8,
            visual_fit_line_budget=8,
            differentiation=8,
            claim_safety=8,
            approved_fact_provenance=8,
            total=88,
        ),
        "status": "PRODUCTION_REVIEW_REQUIRED",
        "production_eligible": True,
    }
    data.update(overrides)
    return CampaignCopyRoute(**data)


def _copy_set(*, duplicate_proof: bool = False) -> dict:
    points = ["Formula tradisional", "Formula tradisional"] if duplicate_proof else ["Formula tradisional"]
    return {
        "poster_copy_set_id": "pcs-1",
        "version": 1,
        "primary_message": "Warisan dekat dengan rutin",
        "support_message": "Formula tradisional untuk pilihan keluarga.",
        "proof_points": points,
        "cta": "Lihat pilihan",
        "disclaimer": "Untuk kegunaan luaran sahaja.",
        "field_provenance": {"primary_message": "APPROVED_SNAPSHOT.copy_strategy"},
        "objective": "Product Hero",
        "angle": "Warisan dekat dengan rutin",
    }


def _manifest(copy_set: dict | None = None):
    copy_set = copy_set or _copy_set()
    return build_render_manifest(
        recipe_id="heritage_infographic",
        copy_set=copy_set,
        background_media_id="media-kv-1",
        background_local_path="C:/tmp/key-visual.png",
        image_model="NANO_BANANA_PRO",
        creative_direction={
            "mode": "CREATIVE_CAMPAIGN",
            "authority_version": "poster-design-system-v1",
            "representation_policy_version": "product-reference-pack-v1",
            "design_route": "HERITAGE_EDITORIAL",
            "layout_variant": "EDITORIAL_ASYMMETRY",
        },
        composition_plan={"typography": {"headline_line_budget": 2}},
        design_route="HERITAGE_EDITORIAL",
        layout_variant="EDITORIAL_ASYMMETRY",
    )


def _render_report(manifest, *, duplicate: bool = False) -> PosterRenderReport:
    zones = []
    for zone in manifest.zones:
        rendered = zone.text
        zones.append(
            ZoneRenderResult(
                zone_id=zone.zone_id,
                fitted=True,
                overflowed=False,
                overlaps_product=False,
                rendered_text=rendered,
            )
        )
    return PosterRenderReport(
        renderer="HTML_CHROMIUM_SERVICE_V1",
        canvas={"w": 1080, "h": 1920},
        output_png={"width": 1080, "height": 1920},
        zones=zones,
        ok=True,
    )


def test_pre_provider_lint_blocks_reference_copy_leak_and_budget_failures():
    brief = _brief()
    result = build_pre_provider_lint(
        product_id="prod-1",
        reference_pack={"pack_status": "DRAFT"},
        brief=brief,
        candidate=_candidate(),
        compiled_prompt="headline: Warisan dekat dengan rutin",
        max_provider_operations=2,
        max_retry_operations=1,
    )
    assert result.allowed is False
    assert "REFERENCE_PACK_APPROVAL_REQUIRED" in result.blockers
    assert any(item.startswith("CLEAN_KEY_VISUAL_MARKETING_COPY_LEAK") for item in result.blockers)
    assert "PROVIDER_OPERATION_BUDGET_MUST_EQUAL_ONE" in result.blockers
    assert "HIDDEN_RETRY_DISABLED_FOR_CREATIVE_CAMPAIGN" in result.blockers


def test_pre_provider_lint_allows_static_dry_run_when_all_compile_gates_are_ready():
    result = build_pre_provider_lint(
        product_id="prod-1",
        reference_pack={"pack_status": "APPROVED"},
        brief=_brief(),
        candidate=_candidate(),
        compiled_prompt="Vertical clean key visual with deliberate negative space and no marketing copy.",
        live=False,
    )
    assert result.allowed is True
    assert result.prompt_marketing_copy_leak is False
    assert result.max_provider_operations == 1
    assert result.max_retry_operations == 0


def test_machine_qa_never_infers_identity_or_scale_from_payload():
    qa = build_campaign_machine_qa("media-1")
    assert qa.machine_qa_status == "WARN"
    assert qa.product_identity.status == "UNVERIFIED"
    assert qa.scale.status == "UNVERIFIED"
    flagged = build_campaign_machine_qa("media-1", vision_signals={"label": False})
    assert flagged.machine_qa_status == "FAIL"
    assert flagged.label.status == "BLOCK"


def test_post_composition_qa_is_clean_but_keeps_human_visual_gates_unverified():
    manifest = _manifest()
    qa = build_campaign_post_composition_qa(
        manifest=manifest,
        report=_render_report(manifest),
        copy_set=_copy_set(),
        settings={
            "pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE",
            "raw_key_visual_is_lineage_only": True,
        },
        output_sha256="a" * 64,
    )
    assert qa.ok is True
    assert qa.clean_key_visual_lineage is True
    assert qa.copy_provenance_verified is True
    assert qa.checks["contrast_threshold"].status == "UNVERIFIED"
    assert qa.campaign_review_status == "PENDING_HUMAN_REVIEW"


def test_post_composition_qa_blocks_duplicate_copy_and_bad_lineage():
    manifest = _manifest(_copy_set(duplicate_proof=True))
    qa = build_campaign_post_composition_qa(
        manifest=manifest,
        report=_render_report(manifest),
        copy_set=_copy_set(duplicate_proof=True),
        settings={"pipeline": "WRONG", "raw_key_visual_is_lineage_only": False},
        output_sha256="a" * 64,
    )
    assert qa.ok is False
    assert qa.checks["duplicate_string_detection"].status == "BLOCK"
    assert qa.checks["clean_key_visual_lineage"].status == "BLOCK"


def test_world_class_review_requires_dimension_thresholds_for_approval():
    bad = CampaignReviewRequest(
        decision="APPROVED",
        reviewer="operator",
        product_identity=20,
        product_integration_physics=20,
        typography_copy_hierarchy=18,
        malaysian_context_authenticity=12,
        conversion_strength=13,
    )
    with pytest.raises(CampaignQAError, match="WORLD_CLASS_APPROVAL_THRESHOLD_NOT_MET"):
        build_world_class_review(bad)
    good = build_world_class_review(
        bad.model_copy(update={"product_identity": 23, "decision": "APPROVED"})
    )
    assert good.total == 86
    assert good.decision == "APPROVED"


@pytest.mark.asyncio
async def test_campaign_variants_are_three_distinct_credit_free_manifests(monkeypatch):
    manifest = _manifest()
    row = {
        "poster_deliverable_id": "pd-1",
        "product_id": "prod-1",
        "poster_copy_set_id": "pcs-1",
        "recipe_id": "heritage_infographic",
        "render_manifest_json": manifest.model_dump_json(),
    }
    pcs_row = {
        **_copy_set(),
        "proof_points_json": json.dumps(["Formula tradisional"]),
        "field_provenance_json": json.dumps(_copy_set()["field_provenance"]),
        "offer_json": "null",
        "variants_json": "[]",
    }
    monkeypatch.setattr("agent.services.poster_campaign_variant_service.crud.get_poster_deliverable", lambda _id: _async_value(row))
    monkeypatch.setattr("agent.services.poster_campaign_variant_service.crud.get_poster_copy_set", lambda _id: _async_value(pcs_row))
    result = await build_campaign_variants("pd-1")
    assert len(result.variants) == 3
    assert len({item.manifest_sha256 for item in result.variants}) == 3
    assert result.provider_operation_count == 0
    assert result.max_retry_operations == 0
    assert all(item.kv_reused for item in result.variants)


async def _async_value(value):
    return value
