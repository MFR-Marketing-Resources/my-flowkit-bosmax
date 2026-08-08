import json

import pytest

from agent.models.image_generation_contract import (
    ImageCreativeContext,
    ImageOperationPlanRequest,
    ImagePromptCompileRequest,
    ImageReferenceBinding,
    PhysicalMeasurementEvidence,
    ProductReferencePackRecord,
)
from agent.models.copy_grounding import (
    BuyerPersona,
    ClaimGuardrails,
    CopyGrounding,
    GROUNDING_APPROVED_SNAPSHOT,
    GROUNDING_FRAMEWORK_FAMILY,
    ProductKnowledge,
)
from agent.services.image_prompt_compiler import (
    IMAGE_PROMPT_SECTIONS,
    build_operation_plan,
    compile_image_prompt,
)
from agent.services.copy_grounding_service import build_safe_campaign_context
from agent.services.product_reference_pack_service import (
    ProductReferencePackError,
    _create_asset,
    _explicit_measurements,
    machine_check_generated_output,
    transport_reference_ids,
)
from agent.services.make_video import _image_provider_operation_reference


PRODUCT_ID = "product-test-1"


@pytest.mark.asyncio
async def test_product_reference_pack_assets_do_not_claim_video_engine_slots(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}

    async def fake_get(_asset_id):
        return None

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(
        "agent.services.product_reference_pack_service.crud.get_creative_asset",
        fake_get,
    )
    monkeypatch.setattr(
        "agent.services.product_reference_pack_service.crud.create_creative_asset",
        fake_create,
    )

    await _create_asset(
        product={"id": PRODUCT_ID, "product_display_name": "Test product"},
        pack_id="pack-test-1",
        role="PRODUCT_CANONICAL",
        path=tmp_path / "canonical.jpg",
        metadata={"sha256": "a" * 64},
    )

    assert json.loads(str(captured["engine_slot_eligibility"])) == []


def _grounding_for_context(
    *,
    family: str = "BEAUTY_PERSONAL_CARE",
    audience: str = "wanita bekerja",
    desires: list[str] | None = None,
    objections: list[str] | None = None,
    triggers: list[str] | None = None,
    source: str = GROUNDING_APPROVED_SNAPSHOT,
    angle: str = "quiet confidence",
) -> CopyGrounding:
    source_prefix = "APPROVED_SNAPSHOT" if source == GROUNDING_APPROVED_SNAPSHOT else "FRAMEWORK_FAMILY"
    return CopyGrounding(
        product_id=PRODUCT_ID,
        grounded=source == GROUNDING_APPROVED_SNAPSHOT,
        source=source,
        family=family,
        copy_formula="PAS / AIDA",
        metaphor_silos=["quiet_confidence"],
        product_knowledge=ProductKnowledge(usps=["Bekalan 25ml yang praktikal"]),
        buyer_persona=BuyerPersona(
            audience=audience,
            desires=desires or ["rasa lebih bersedia dalam rutin harian"],
            objections=objections or ["mahu pilihan yang mudah difahami"],
            triggers=triggers or ["mencari pilihan praktikal sebelum keluar"],
            tone="mesra, yakin dan prihatin",
        ),
        angle_strategies=[angle],
        claim_guardrails=ClaimGuardrails(),
        field_provenance={
            "buyer_persona.audience": f"{source_prefix}.persona.audience",
            "buyer_persona.desires": f"{source_prefix}.persona.desires",
            "buyer_persona.objections": f"{source_prefix}.persona.objections",
            "buyer_persona.triggers": f"{source_prefix}.persona.triggers",
            "buyer_persona.tone": f"{source_prefix}.persona.tone",
            "angle_strategies": f"{source_prefix}.angle_strategies",
            "product_knowledge.usps": f"{source_prefix}.product_knowledge.usps",
        },
    )


def _pack(*, status: str = "PENDING_REVIEW", approved: bool = False):
    roles = (
        "PRODUCT_CANONICAL",
        "PRODUCT_LABEL_CROP",
        "PRODUCT_LOGO_CROP",
        "PRODUCT_CUTOUT",
    )
    return ProductReferencePackRecord(
        pack_id="prp-test-1",
        product_id=PRODUCT_ID,
        schema_version="product_reference_pack_v1",
        pack_status=status,
        machine_qa_status="WARN",
        machine_qa={"findings": ["PHYSICAL_SCALE_UNVERIFIED_NO_PIXEL_INFERENCE"]},
        physical_measurements=PhysicalMeasurementEvidence(),
        references=[
            ImageReferenceBinding(
                role=role,
                asset_id=f"asset-{role.lower()}",
                local_file_path=f"C:/tmp/{role.lower()}.png",
                sha256="a" * 64,
                source_type="PRODUCT_CACHE",
                approved=approved,
            )
            for role in roles
        ],
        provenance={"created_without_credit": True},
        human_review={},
        created_at="2026-08-08T00:00:00Z",
        updated_at="2026-08-08T00:00:00Z",
    )


def test_operation_plan_is_bounded_and_requires_confirmation():
    plan = build_operation_plan(
        ImageOperationPlanRequest(
            product_id=PRODUCT_ID,
            requested_outputs=3,
            max_retry_operations=0,
            model="NANO_BANANA_2",
        )
    )

    assert plan.max_provider_operations == 3
    assert plan.max_retry_operations == 0
    assert plan.estimated_credit_exposure_status == "UNVERIFIED"
    assert plan.explicit_confirmation_required is True
    assert plan.hidden_retry_allowed is False


def test_compiler_emits_ordered_nine_sections_and_unverified_scale_warning():
    response = compile_image_prompt(
        {
            "id": PRODUCT_ID,
            "product_display_name": "Test Product",
        },
        _pack(),
        ImagePromptCompileRequest(
            product_id=PRODUCT_ID,
            output_intent="COMPLETE_POSTER",
            copy_layout={"headline": "Exact headline", "cta": "Beli sekarang"},
            scene_direction="A Malaysian home setting",
        ),
    )

    assert list(response.sections) == list(IMAGE_PROMPT_SECTIONS)
    assert "PHYSICAL SCALE UNVERIFIED" in response.sections["PRODUCT_SCALE_AND_GEOMETRY"]
    assert "no altered label, logo" in response.sections["NEGATIVE_CONSTRAINTS_AND_OUTPUT_SPECIFICATION"]
    assert "REFERENCE_PACK_APPROVAL_REQUIRED" in response.blockers
    assert response.capability_status["multi_reference_roles"] == "UNPROVEN"
    assert response.provider_operation_plan["max_provider_operations"] == 1


def test_clean_key_visual_compiler_excludes_marketing_copy():
    response = compile_image_prompt(
        {"id": PRODUCT_ID, "product_display_name": "Test Product"},
        _pack(status="APPROVED", approved=True),
        ImagePromptCompileRequest(
            product_id=PRODUCT_ID,
            output_intent="CLEAN_KEY_VISUAL",
            copy_layout={"headline": "Must not be rendered"},
            copy_space={
                "headline_line_budget": 2,
                "copy_zone_strategy": "DELIBERATE_NEGATIVE_SPACE",
            },
        ),
    )

    assert "no headline" in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert "Must not be rendered" not in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert "headline_line_budget=2" in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert response.provider_operation_plan["model"] == "NANO_BANANA_PRO"
    assert response.blockers == []


def test_context_uses_approved_persona_and_never_infers_parents_from_size():
    product = {
        "id": PRODUCT_ID,
        "product_display_name": "Small Product A",
        "product_scale": "SMALL_OBJECT",
        "physics_class": "SMALL_BOTTLE",
    }
    grounding = _grounding_for_context(
        audience="wanita bekerja",
        desires=["rasa yakin sebelum memulakan hari"],
        objections=["mahu pilihan yang mudah difahami"],
        triggers=["bersiap sebelum keluar bekerja"],
    )

    context = build_safe_campaign_context(
        product,
        grounding,
        operator_direction="quiet confidence",
        objective="Product Hero",
        copy_layout={"headline": "Rasa Yakin Setiap Hari"},
    )

    assert context["intelligence_status"] == "READY"
    assert context["audience"] == "wanita bekerja"
    assert context["desire"] == "rasa yakin sebelum memulakan hari"
    assert context["trigger"] == "bersiap sebelum keluar bekerja"
    assert "parents" not in str(context).casefold()
    assert all(
        value.startswith("APPROVED_SNAPSHOT")
        for value in context["field_provenance"].values()
    )


def test_same_size_products_with_different_approved_personas_do_not_collapse():
    product = {"id": PRODUCT_ID, "product_scale": "SMALL_OBJECT"}
    first = build_safe_campaign_context(
        product,
        _grounding_for_context(
            audience="wanita bekerja",
            desires=["rasa yakin sebelum memulakan hari"],
            triggers=["bersiap sebelum keluar bekerja"],
        ),
    )
    second = build_safe_campaign_context(
        product,
        _grounding_for_context(
            audience="penjaga warga emas",
            desires=["rutin penjagaan yang lebih teratur"],
            triggers=["menyusun keperluan sebelum perjalanan"],
        ),
    )

    assert first["audience"] != second["audience"]
    assert first["desire"] != second["desire"]
    assert first["trigger"] != second["trigger"]


def test_missing_approved_intelligence_is_incomplete_and_blocks_campaign():
    context = build_safe_campaign_context(
        {"id": PRODUCT_ID, "product_scale": "SMALL_OBJECT"},
        _grounding_for_context(source=GROUNDING_FRAMEWORK_FAMILY),
    )
    assert context["intelligence_status"] == "INCOMPLETE"
    assert "approved snapshot" in context["missing_fields"]
    assert context["audience"] == ""
    assert context["safe_angle"] == ""

    response = compile_image_prompt(
        {"id": PRODUCT_ID, "product_display_name": "Test Product"},
        _pack(status="APPROVED", approved=True),
        ImagePromptCompileRequest(product_id=PRODUCT_ID),
        ImageCreativeContext.model_validate(context),
    )
    assert "CREATIVE_INTELLIGENCE_INCOMPLETE" in response.blockers


def test_art_direction_changes_with_product_visual_territory():
    cases = [
        (
            {"id": PRODUCT_ID, "product_display_name": "Warisan Herbal Oil", "product_scale": "SMALL_OBJECT"},
            _grounding_for_context(family="TRADITIONAL_HERBAL_OIL"),
        ),
        (
            {"id": PRODUCT_ID, "product_display_name": "Daily Serum", "product_scale": "MEDIUM_OBJECT"},
            _grounding_for_context(family="BEAUTY_PERSONAL_CARE"),
        ),
        (
            {"id": PRODUCT_ID, "product_display_name": "Desk Organizer", "product_scale": "LARGE_OBJECT"},
            _grounding_for_context(family="HOME_STORAGE"),
        ),
    ]
    directions = [
        build_safe_campaign_context(
            product,
            grounding,
            objective="Product Hero",
            copy_layout={"headline": "Short Hook"},
        )["art_direction"]
        for product, grounding in cases
    ]

    assert {item["layout_family"] for item in directions} == {
        "HERITAGE_EDITORIAL",
        "ROUTINE_EDITORIAL",
        "PRODUCT_HERO_SCULPTURE",
    }
    assert len({item["creative_territory"] for item in directions}) == 3


def test_creative_campaign_compiler_carries_campaign_intelligence_and_mobile_hierarchy():
    context = ImageCreativeContext(
        intelligence_status="READY",
        grounding_source="APPROVED_SNAPSHOT",
        approved_snapshot_id="snapshot-1",
        approved_snapshot_version=5,
        product_family="BEAUTY_PERSONAL_CARE",
        formula="PAS / AIDA",
        audience="Malaysian household shoppers and parents",
        desire="a familiar product that is easy to keep close",
        objection="The product identity must be immediately legible.",
        trigger="choosing a practical standby for home or travel",
        safe_angle="Lead with familiar heritage identity and compact portability.",
        tone="warm, confident and grounded",
        approved_facts=[
            "Resipi tradisional warisan Tok Cap Burung",
            "Bekalan 25ml yang praktikal dan mudah dibawa",
        ],
    )

    response = compile_image_prompt(
        {"id": PRODUCT_ID, "product_display_name": "Minyak Warisan Cap Burung 25ml"},
        _pack(status="APPROVED", approved=True),
        ImagePromptCompileRequest(
            product_id=PRODUCT_ID,
            output_intent="COMPLETE_POSTER",
            composition="Premium look",
            copy_layout={
                "headline": "Warisan Tok, Kini Premium",
                "support": "Mudah dibawa, sentiasa dekat",
                "proof_1": "Resipi tradisional",
                "proof_2": "25ml praktikal",
                "cta": "Dapatkan sekarang",
            },
        ),
        creative_context=context,
    )

    assert response.creative_context == context
    assert "Campaign intelligence" in response.sections["COMPOSITION_AND_HIERARCHY"]
    assert "familiar heritage identity" in response.compiled_prompt
    assert "MOBILE-FIRST TEXT HIERARCHY" in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert "typed art direction's headline personality" in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert "do not force an upper/middle/lower grid" in response.sections["COMPOSITION_AND_HIERARCHY"]
    assert "proof_1: Resipi tradisional" in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert "Do not depict symptoms, treatment, medical outcomes" in response.compiled_prompt


def test_physical_scale_never_comes_from_pixel_dimensions(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_reference_pack_service.resolve_schema_entry",
        lambda _product: {},
    )

    measurement = _explicit_measurements(
        {
            "id": PRODUCT_ID,
            "width": 960,
            "height": 1280,
            "name": "25ml bottle",
        }
    )

    assert measurement.physical_width_mm is None
    assert measurement.physical_height_mm is None
    assert measurement.volume_ml is None
    assert measurement.scale_evidence_source == "UNVERIFIED"
    assert measurement.scale_confidence == "UNVERIFIED"


def test_pack_approval_and_output_machine_check_are_independent():
    pack = _pack(status="APPROVED", approved=True)
    assert transport_reference_ids(pack)["PRODUCT_CANONICAL"] == "asset-product_canonical"

    qa = machine_check_generated_output("media-1", pack)
    assert qa.review_state == "GENERATED_OUTPUT_MACHINE_CHECKED"
    assert qa.human_review_required is True
    assert qa.machine_qa_status == "WARN"

    pending = _pack()
    try:
        transport_reference_ids(pending)
    except ProductReferencePackError as exc:
        assert exc.code == "REFERENCE_PACK_APPROVAL_REQUIRED"
    else:
        raise AssertionError("unapproved pack must fail closed")


def test_provider_operation_reference_never_invents_missing_id():
    missing = _image_provider_operation_reference({"data": {"media": []}})
    assert missing["provider_operation_id"] is None
    assert missing["operation_id_status"] == "UNPROVEN_PROVIDER_OPERATION_ID"

    observed = _image_provider_operation_reference(
        {"data": {"operationId": "op-1", "batchId": "batch-1"}}
    )
    assert observed["provider_operation_id"] == "op-1"
    assert observed["transport_batch_id"] == "batch-1"
    assert observed["operation_id_status"] == "OBSERVED"
