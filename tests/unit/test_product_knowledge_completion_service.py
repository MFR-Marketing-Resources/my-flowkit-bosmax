import pytest
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.ai_copy_provider_adapter import (
    AICopyProviderError,
    ERR_RESPONSE_INVALID,
)
from agent.services.product_knowledge_service import complete_product_knowledge


@pytest.fixture(autouse=True)
def _disable_live_providers(monkeypatch):
    """No unit test may cross the configured text_assist provider boundary."""
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": False,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": False,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: pytest.fail("unexpected real text_assist call"),
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_api_key",
        lambda lane: None,
    )


def _valid_text_assist_payload():
    return {
        "product_knowledge_summary": "Serbuk perasa untuk masakan harian.",
        "benefits": ["Membantu melengkapkan rasa masakan"],
        "usage_summary": "Tabur secukup rasa ketika memasak.",
        "target_customer": "Pengguna yang memasak di rumah",
        "usp_list": ["Mudah digunakan untuk masakan harian"],
        "size_or_volume": None,
        "package_notes": "Dibungkus dalam pek serbuk.",
        "warnings_or_limitations": [],
        "confidence": "MEDIUM",
        "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
        "needs_review": True,
    }


def _enable_mock_deepseek(monkeypatch, completion):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: completion,
    )


def test_complete_product_knowledge_basic():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        product_knowledge_text="Sabun dobi wangi 1.2kg botol biru",
        price=12.9,
        currency="MYR",
        commission_amount=1.29,
        commission_rate="10%",
        image_url="https://example.com/detergent.jpg",
        product_url="https://example.com/detergent",
        source_url="https://example.com/source/detergent",
        image_notes="Front label visible in uploaded image.",
        product_form_factor="refill pouch",
        packaging_description="Soft blue pouch with cap",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.completion_status == "COMPLETION_READY"
    assert response.suggested_bosmax_product_family == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert response.claim_gate == "CLAIM_SAFE"
    assert "1.2kg" in response.extracted_product_facts["size_or_volume"]
    assert response.image_analysis_status == "VISION_PROVIDER_NOT_CONFIGURED"
    assert response.image_analysis_image_url == "https://example.com/detergent.jpg"
    assert response.declared_input_fields["source_url"] == "https://example.com/source/detergent"
    assert response.declared_input_fields["image_notes"] == "Front label visible in uploaded image."
    assert response.declared_input_fields["product_form_factor"] == "refill pouch"
    assert response.declared_input_fields["packaging_description"] == "Soft blue pouch with cap"

def test_complete_product_knowledge_claim_gate_review():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Whitening Serum",
        product_knowledge_text="Mencerahkan kulit dengan cepat dan berkesan.",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert "whitening" in response.claim_tokens or "mencerahkan" in response.claim_tokens

def test_complete_product_knowledge_claim_gate_blocked():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Miracle Oil",
        product_knowledge_text="Boleh menyembuhkan sakit lutut dalam 3 hari.",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.claim_gate == "CLAIM_BLOCKED"
    assert "menyembuhkan" in response.claim_tokens

def test_complete_product_knowledge_male_health_claim_gate_review():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Herbs",
        product_knowledge_text="Minyak urutan lelaki untuk tenaga batin dan bahagian intim.",
        benefits_text="Meningkatkan ketegangan dan keyakinan kelelakian.",
        package_notes="Botol kecil 5 ML dengan penitis dropper.",
        size_or_volume="5 ML",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)

    assert response.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert any(token in response.claim_tokens for token in ["tenaga batin", "bahagian intim", "ketegangan", "keyakinan kelelakian"])
    assert response.suggested_category == "Health"
    assert response.suggested_subcategory == "Supplements"
    assert response.suggested_type == "Male Health"
    assert response.suggested_bosmax_product_family == "MALE_HEALTH_SENSITIVE"
    assert response.suggested_physics_class == "SUPPLEMENT_BOTTLE"
    assert response.readiness_by_mode["IMG"].status == "IMAGE_REFERENCE_REQUIRED"

def test_complete_product_knowledge_insufficient_data():
    request = ProductKnowledgeCompleteRequest(
        product_name=None,
        product_knowledge_text=None
    )
    response = complete_product_knowledge(request)
    
    assert response.completion_status == "NEEDS_REVIEW"
    assert "PRODUCT_NAME" in response.missing_required_evidence


def test_complete_product_knowledge_tiktok_draft_fails_closed_without_fake_scrape():
    request = ProductKnowledgeCompleteRequest(
        product_name="TikTok Draft Product",
        source_lane="TIKTOKSHOP_DRAFT",
        tiktok_product_url="https://shop.tiktok.com/view/product/123",
        product_url="https://shop.tiktok.com/view/product/123",
        price=19.9,
        currency="MYR",
    )

    response = complete_product_knowledge(request)

    assert response.extraction_status == "NOT_IMPLEMENTED"
    assert "TIKTOKSHOP_MANUAL_COMPLETION_REQUIRED" in response.missing_required_evidence
    assert "TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED" in response.warnings


def test_complete_product_knowledge_high_confidence_image_ocr_can_fill_size_evidence(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.resolve_product_intelligence_profile",
        lambda payload: {
            "bosmax_product_family": "BEAUTY_PERSONAL_CARE",
            "package_form": "bottle",
            "physical_state": "liquid",
            "product_scale_class": "handheld_small",
            "handling_profile": "controlled_grip",
            "copy_route": "REVIEW_REQUIRED",
            "copy_formula": "REVIEW_REQUIRED",
            "warnings": [],
            "errors": [],
            "image_analysis": {
                "status": "ANALYZED",
                "image_url": payload.get("image_url"),
                "local_image_path": payload.get("local_image_path"),
                "detected_package": "bottle",
                "detected_text": ["Hydrating Face Mist", "100ml"],
                "detected_brand": None,
                "detected_size_text": "100ml",
                "detected_form_factor": "bottle",
                "visual_confidence": "HIGH",
                "evidence": ["provider:mock"],
                "warnings": [],
                "provider": "mock_provider",
                "metadata": {},
            },
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.resolve_product_physics",
        lambda product: {
            "physics_class": "LIQUID_BOTTLE",
            "recommended_grip": "center_hold",
            "section_5_product_physics_prompt": "Physics DNA: LIQUID_BOTTLE",
        },
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="Hydrating Face Mist",
        paste_anything_about_product="Product: Hydrating Face Mist | Category: Beauty & Personal Care",
        source_lane="MANUAL",
        category="Beauty & Personal Care",
        price=19.9,
        currency="MYR",
        commission_rate="10%",
        image_url="https://example.com/face-mist.jpg",
    )

    response = complete_product_knowledge(request)

    assert response.suggested_size_or_volume == "100ml"
    assert response.extracted_product_facts["size_or_volume"] == "100ml"
    assert "SIZE_OR_VOLUME_EVIDENCE" not in response.missing_required_evidence
    assert "SIZE_OR_VOLUME_FROM_IMAGE_OCR_HIGH_CONFIDENCE" in response.warnings


def test_complete_product_knowledge_low_confidence_image_ocr_does_not_clear_size_block(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.resolve_product_intelligence_profile",
        lambda payload: {
            "bosmax_product_family": "BEAUTY_PERSONAL_CARE",
            "package_form": "bottle",
            "physical_state": "liquid",
            "product_scale_class": "handheld_small",
            "handling_profile": "controlled_grip",
            "copy_route": "REVIEW_REQUIRED",
            "copy_formula": "REVIEW_REQUIRED",
            "warnings": [],
            "errors": [],
            "image_analysis": {
                "status": "ANALYZED",
                "image_url": payload.get("image_url"),
                "local_image_path": payload.get("local_image_path"),
                "detected_package": "bottle",
                "detected_text": ["Hydrating Face Mist", "100ml"],
                "detected_brand": None,
                "detected_size_text": "100ml",
                "detected_form_factor": "bottle",
                "visual_confidence": "LOW",
                "evidence": ["provider:mock"],
                "warnings": [],
                "provider": "mock_provider",
                "metadata": {},
            },
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.resolve_product_physics",
        lambda product: {
            "physics_class": "LIQUID_BOTTLE",
            "recommended_grip": "center_hold",
            "section_5_product_physics_prompt": "Physics DNA: LIQUID_BOTTLE",
        },
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="Hydrating Face Mist",
        paste_anything_about_product="Product: Hydrating Face Mist | Category: Beauty & Personal Care",
        source_lane="MANUAL",
        category="Beauty & Personal Care",
        price=19.9,
        currency="MYR",
        commission_rate="10%",
        image_url="https://example.com/face-mist.jpg",
    )

    response = complete_product_knowledge(request)

    assert response.suggested_size_or_volume == "N/A"
    assert response.evidence_field_status["size_or_volume"].status == "NOT_AVAILABLE"
    assert "SIZE_OR_VOLUME_EVIDENCE" in response.missing_required_evidence
    assert "SIZE_OR_VOLUME_FROM_IMAGE_OCR_HIGH_CONFIDENCE" not in response.warnings


def test_complete_product_knowledge_uses_configured_deepseek_text_assist(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda system, user: calls.append((system, user))
        or {
            "product_knowledge_summary": "Serbuk perasa untuk masakan harian.",
            "benefits": ["Membantu melengkapkan rasa masakan"],
            "usage_summary": "Tabur secukup rasa ketika memasak.",
            "target_customer": "Pengguna yang memasak di rumah",
            "usp_list": ["Mudah digunakan untuk masakan harian"],
            "size_or_volume": None,
            "package_notes": "Dibungkus dalam pek serbuk.",
            "warnings_or_limitations": [],
            "confidence": "HIGH",
            "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
            "needs_review": True,
        },
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Serbuk Perasa Warisan",
            paste_anything_about_product=(
                "Serbuk perasa untuk masakan harian. Tabur secukup rasa ketika memasak."
            ),
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert len(calls) == 1
    assert response.suggested_product_knowledge_summary == (
        "Serbuk perasa untuk masakan harian."
    )
    assert response.suggested_benefits == ["Membantu melengkapkan rasa masakan"]
    assert response.suggested_usage_summary == "Tabur secukup rasa ketika memasak."
    assert response.suggested_target_customer == "Pengguna yang memasak di rumah"
    assert response.suggested_usp_list == ["Mudah digunakan untuk masakan harian"]
    assert response.suggested_size_or_volume == "N/A"
    assert response.evidence_field_status["benefits"].status == "AI_SUGGESTED"
    assert response.evidence_field_status["benefits"].needs_review is True
    assert response.evidence_field_status["benefits"].confidence == "MEDIUM"
    assert "benefits" in response.human_review_fields
    assert "text_assist:deepseek:deepseek-v4-pro:review_only" in response.provenance
    assert response.extracted_product_facts["usp_list"] == []


def test_complete_product_knowledge_disabled_text_assist_uses_safe_fallback(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: pytest.fail("disabled provider must not be called"),
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Serbuk Perasa Warisan",
            paste_anything_about_product="Serbuk perasa untuk masakan harian.",
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert "TEXT_ASSIST_NOT_CONFIGURED" in response.warnings
    assert response.suggested_size_or_volume == "N/A"
    assert response.suggested_package_notes == "NOT_AVAILABLE"
    assert response.suggested_warnings_or_limitations == ["NOT_AVAILABLE"]
    assert "SIZE_OR_VOLUME_EVIDENCE" in response.missing_required_evidence
    assert response.evidence_field_status["size_or_volume"].needs_review is True


def test_complete_product_knowledge_invalid_text_assist_json_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: {"unexpected": "shape"},
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Serbuk Perasa Warisan",
            paste_anything_about_product="Serbuk perasa untuk masakan harian.",
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert "TEXT_ASSIST_INVALID_RESPONSE" in response.warnings
    assert "TEXT_ASSIST_DIAGNOSTIC_MISSING_KEYS" in response.warnings
    assert any(
        warning.startswith("TEXT_ASSIST_MISSING_KEYS:")
        for warning in response.warnings
    )
    assert any(
        warning.startswith("TEXT_ASSIST_UNEXPECTED_KEYS:")
        for warning in response.warnings
    )
    assert response.suggested_size_or_volume == "N/A"
    assert response.suggested_package_notes == "NOT_AVAILABLE"


@pytest.mark.parametrize(
    ("case", "diagnostic", "metadata_prefix"),
    [
        ("missing_key", "MISSING_KEYS", "TEXT_ASSIST_MISSING_KEYS:"),
        ("unexpected_key", "UNEXPECTED_KEYS", "TEXT_ASSIST_UNEXPECTED_KEYS:"),
        (
            "wrong_field_type",
            "FIELD_TYPE_INVALID",
            "TEXT_ASSIST_VALIDATION_FIELD_PATHS:",
        ),
        (
            "invalid_confidence",
            "ENUM_INVALID",
            "TEXT_ASSIST_VALIDATION_FIELD_PATHS:",
        ),
        (
            "needs_review_false",
            "NEEDS_REVIEW_INVALID",
            "TEXT_ASSIST_VALIDATION_FIELD_PATHS:",
        ),
    ],
)
def test_text_assist_schema_failures_are_exact_and_preserve_manual_fields(
    monkeypatch,
    case,
    diagnostic,
    metadata_prefix,
):
    payload = _valid_text_assist_payload()
    if case == "missing_key":
        payload.pop("benefits")
    elif case == "unexpected_key":
        payload["unknown_field"] = "blocked"
    elif case == "wrong_field_type":
        payload["benefits"] = "not-a-list"
    elif case == "invalid_confidence":
        payload["confidence"] = "CERTAIN"
    elif case == "needs_review_false":
        payload["needs_review"] = False
    _enable_mock_deepseek(monkeypatch, payload)

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Serbuk Perasa Warisan",
            product_knowledge_text="Ringkasan manual kekal berkuasa.",
            paste_anything_about_product=(
                "Serbuk perasa untuk masakan harian dan penggunaan di rumah."
            ),
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert "TEXT_ASSIST_INVALID_RESPONSE" in response.warnings
    assert f"TEXT_ASSIST_DIAGNOSTIC_{diagnostic}" in response.warnings
    assert any(
        warning.startswith(metadata_prefix) for warning in response.warnings
    )
    assert response.suggested_product_knowledge_summary == (
        "Ringkasan manual kekal berkuasa."
    )
    assert (
        response.evidence_field_status["product_knowledge_summary"].status
        == "EXACT_SOURCE_EVIDENCE"
    )
    assert all(
        metadata.status != "AI_SUGGESTED"
        for metadata in response.evidence_field_status.values()
    )


def test_adapter_diagnostic_is_exposed_without_provider_content(monkeypatch):
    error = AICopyProviderError(
        ERR_RESPONSE_INVALID,
        diagnostic_category="TRUNCATED_RESPONSE",
        diagnostic_metadata={"finish_reason": "length"},
        finish_reason="length",
    )
    _enable_mock_deepseek(monkeypatch, None)
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Serbuk Perasa Warisan",
            paste_anything_about_product="Serbuk perasa untuk masakan harian.",
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert "TEXT_ASSIST_INVALID_RESPONSE" in response.warnings
    assert "TEXT_ASSIST_DIAGNOSTIC_TRUNCATED_RESPONSE" in response.warnings
    assert "TEXT_ASSIST_FINISH_REASON:length" in response.warnings
    assert response.suggested_benefits == []


def test_complete_product_knowledge_provider_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Bosmax Liquid Detergent",
            paste_anything_about_product="Sabun dobi untuk rutin cucian harian.",
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert "TEXT_ASSIST_CALL_FAILED" in response.warnings
    assert response.suggested_usp_list == []
    assert response.suggested_size_or_volume == "N/A"


def test_complete_product_knowledge_discards_unsafe_ai_claims(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: {
            "product_knowledge_summary": "Produk herba untuk rutin harian.",
            "benefits": ["Menyembuhkan semua sakit dengan segera"],
            "usage_summary": None,
            "target_customer": None,
            "usp_list": ["Jaminan sembuh"],
            "size_or_volume": None,
            "package_notes": None,
            "warnings_or_limitations": [],
            "confidence": "MEDIUM",
            "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
            "needs_review": True,
        },
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Minyak Herba Harian",
            paste_anything_about_product="Minyak herba untuk rutin sapuan luaran harian.",
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert "TEXT_ASSIST_UNSAFE_SUGGESTION_DISCARDED" in response.warnings
    assert response.suggested_benefits == []
    assert response.suggested_usp_list == []
    assert response.claim_gate == "CLAIM_SAFE"


def test_complete_product_knowledge_does_not_override_declared_evidence(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: {
            "product_knowledge_summary": "Conflicting AI summary",
            "benefits": ["Conflicting AI benefit"],
            "usage_summary": "Conflicting AI usage",
            "target_customer": "Pengguna rumah",
            "usp_list": ["Conflicting AI USP"],
            "size_or_volume": None,
            "package_notes": None,
            "warnings_or_limitations": [],
            "confidence": "MEDIUM",
            "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
            "needs_review": True,
        },
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Bosmax Liquid Detergent",
            product_knowledge_text="Sabun dobi harian.",
            benefits_text="- Cuci bersih\n- Haruman segar",
            usage_text="Tuang mengikut sukatan cucian.",
            paste_anything_about_product="Sabun dobi harian untuk kegunaan rumah.",
            source_lane="MANUAL",
        ),
        enable_text_assist=True,
    )

    assert response.suggested_product_knowledge_summary == "Sabun dobi harian."
    assert response.suggested_benefits == ["Cuci bersih", "Haruman segar"]
    assert response.suggested_usage_summary == "Tuang mengikut sukatan cucian."
    assert response.suggested_usp_list == ["Cuci bersih", "Haruman segar"]
    assert response.evidence_field_status["benefits"].status == (
        "EXACT_SOURCE_EVIDENCE"
    )


def test_direct_completion_is_credit_free_without_explicit_text_assist(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Bosmax Liquid Detergent",
            paste_anything_about_product="Sabun dobi cuci bersih dengan haruman segar tahan lama.",
            source_lane="MANUAL",
        )
    )

    assert response.suggested_usp_list == []
    assert "TEXT_ASSIST_SUGGESTIONS_REQUIRE_REVIEW" not in response.warnings
    assert response.suggested_size_or_volume == "N/A"
