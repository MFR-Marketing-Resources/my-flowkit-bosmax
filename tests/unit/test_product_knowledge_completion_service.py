import pytest
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.product_knowledge_service import complete_product_knowledge


@pytest.fixture(autouse=True)
def _disable_live_providers(monkeypatch):
    """Isolate all unit tests from live API keys stored on the machine.
    Patches both the old get_provider_api_key (legacy callers) and the new
    lane-based get_lane_api_key in both consuming services."""
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: None,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_api_key",
        lambda lane: None,
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

    assert response.suggested_size_or_volume is None
    assert "SIZE_OR_VOLUME_EVIDENCE" in response.missing_required_evidence
    assert "SIZE_OR_VOLUME_FROM_IMAGE_OCR_HIGH_CONFIDENCE" not in response.warnings


def test_complete_product_knowledge_qwen_enriches_usp_list_for_manual_lane(monkeypatch):
    class _MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"usp_list":["Haruman segar tahan lama","Lembut pada fabrik"]}',
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        lambda *args, **kwargs: _MockResponse(),
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        product_knowledge_text="Sabun dobi cuci bersih dengan haruman segar tahan lama dan formula lembut pada fabrik.",
        paste_anything_about_product="Sabun dobi cuci bersih dengan haruman segar tahan lama dan formula lembut pada fabrik.",
        source_lane="MANUAL",
    )

    response = complete_product_knowledge(request)

    assert response.extracted_product_facts["usp_list"] == [
        "Haruman segar tahan lama",
        "Lembut pada fabrik",
    ]
    assert response.suggested_usp_list == [
        "Haruman segar tahan lama",
        "Lembut pada fabrik",
    ]
    assert "QWEN_USP_SUGGESTION_APPLIED" in response.warnings
    assert "qwen_usp_suggest_only:v1" in response.provenance


def test_complete_product_knowledge_qwen_falls_back_to_next_region(monkeypatch):
    class _MockResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.request = None

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx

                raise httpx.HTTPStatusError(
                    "status error",
                    request=httpx.Request("POST", "https://example.com"),
                    response=httpx.Response(self.status_code, request=httpx.Request("POST", "https://example.com")),
                )
            return None

        def json(self):
            return self._payload

    calls = []

    def _mock_post(url, *args, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _MockResponse(401, {})
        return _MockResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"usp_list":["Haruman segar tahan lama"]}',
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        _mock_post,
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        paste_anything_about_product="Sabun dobi dengan haruman segar tahan lama.",
        source_lane="MANUAL",
    )

    response = complete_product_knowledge(request)

    assert response.suggested_usp_list == ["Haruman segar tahan lama"]
    assert len(calls) == 2


def test_complete_product_knowledge_qwen_retries_next_region_after_request_error(monkeypatch):
    import httpx

    class _MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"usp_list":["Lembut pada fabrik"]}',
                        }
                    }
                ]
            }

    calls = []

    def _mock_post(url, *args, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.RequestError("dns failed", request=httpx.Request("POST", url))
        return _MockResponse()

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        _mock_post,
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Bosmax Liquid Detergent",
            paste_anything_about_product="Formula lembut pada fabrik.",
            source_lane="MANUAL",
        )
    )

    assert response.suggested_usp_list == ["Lembut pada fabrik"]
    assert len(calls) == 2


def test_complete_product_knowledge_qwen_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )

    def _raise_http_error(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        _raise_http_error,
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        product_knowledge_text="Sabun dobi cuci bersih dengan haruman segar tahan lama.",
        paste_anything_about_product="Sabun dobi cuci bersih dengan haruman segar tahan lama.",
        source_lane="MANUAL",
    )

    response = complete_product_knowledge(request)

    assert response.extracted_product_facts["usp_list"] == []
    assert response.suggested_usp_list == []
    assert "QWEN_USP_SUGGESTION_APPLIED" not in response.warnings


def test_complete_product_knowledge_qwen_skips_affiliate_lane(monkeypatch):
    def _unexpected_http_call(*args, **kwargs):
        raise AssertionError("Qwen should not be called for FASTMOSS lane")

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        _unexpected_http_call,
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="FastMoss Product",
        product_knowledge_text="Produk affiliate dengan title panjang dan positioning tak stabil.",
        paste_anything_about_product="Produk affiliate dengan title panjang dan positioning tak stabil.",
        source_lane="FASTMOSS",
    )

    response = complete_product_knowledge(request)

    assert response.extracted_product_facts["usp_list"] == []
    assert "QWEN_USP_SUGGESTION_APPLIED" not in response.warnings
    assert "AFFILIATE_LANE_CONTAMINATION_RISK" in response.warnings


def test_complete_product_knowledge_qwen_does_not_override_declared_benefits(monkeypatch):
    def _unexpected_http_call(*args, **kwargs):
        raise AssertionError("Qwen should not be called when benefits_text already exists")

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        _unexpected_http_call,
    )

    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        product_knowledge_text="Sabun dobi harian.",
        paste_anything_about_product="Sabun dobi harian.",
        benefits_text="- Cuci bersih\n- Haruman segar",
        source_lane="MANUAL",
    )

    response = complete_product_knowledge(request)

    assert response.extracted_product_facts["usp_list"] == []
    assert response.suggested_usp_list == ["Cuci bersih", "Haruman segar"]
    assert "QWEN_USP_SUGGESTION_APPLIED" not in response.warnings


def test_complete_product_knowledge_qwen_skips_when_copywriting_assist_lane_disabled(monkeypatch):
    def _unexpected_http_call(*args, **kwargs):
        raise AssertionError("Qwen should not be called when copywriting_assist lane is disabled")

    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_provider",
        lambda lane: "qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.get_lane_api_key",
        lambda lane: "sk-qwen" if lane == "copywriting_assist" else None,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.is_lane_execution_enabled",
        lambda lane: False if lane == "copywriting_assist" else True,
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.httpx.post",
        _unexpected_http_call,
    )

    response = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name="Bosmax Liquid Detergent",
            paste_anything_about_product="Sabun dobi cuci bersih dengan haruman segar tahan lama.",
            source_lane="MANUAL",
        )
    )

    assert response.extracted_product_facts["usp_list"] == []
    assert response.suggested_usp_list == []
    assert "QWEN_USP_SUGGESTION_APPLIED" not in response.warnings
