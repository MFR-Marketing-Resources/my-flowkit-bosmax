from agent.models.image_generation_contract import (
    ImageOperationPlanRequest,
    ImagePromptCompileRequest,
    ImageReferenceBinding,
    PhysicalMeasurementEvidence,
    ProductReferencePackRecord,
)
from agent.services.image_prompt_compiler import (
    IMAGE_PROMPT_SECTIONS,
    build_operation_plan,
    compile_image_prompt,
)
from agent.services.product_reference_pack_service import (
    ProductReferencePackError,
    _explicit_measurements,
    machine_check_generated_output,
    transport_reference_ids,
)
from agent.services.make_video import _image_provider_operation_reference


PRODUCT_ID = "product-test-1"


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
        ),
    )

    assert "no headline" in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert "Must not be rendered" not in response.sections["MARKETING_COPY_AND_TEXT_LAYOUT"]
    assert response.blockers == []


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
