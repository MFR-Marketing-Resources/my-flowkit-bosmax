from pathlib import Path
from unittest.mock import patch

from agent.models.product_intelligence import ProductIntelligenceImageAnalysis
from agent.services.product_image_analysis_service import (
    SEMANTIC_IMAGE_WARNING,
    analyze_product_image_payload,
)

_no_vision_key = patch(
    "agent.services.product_image_analysis_service.get_lane_api_key",
    return_value=None,
)


@_no_vision_key
def test_image_url_without_provider_returns_provider_not_configured_and_no_fake_detections(_mock):
    result = analyze_product_image_payload(
        {
            "id": "prod-001",
            "raw_product_title": "Sabun Dobi Liquid",
            "image_url": "https://example.com/detergent.jpg",
        }
    )

    assert result["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert result["provider"] == "not_configured"
    assert result["detected_package"] is None
    assert result["detected_text"] == []
    assert result["visual_confidence"] == "NOT_VERIFIED"
    assert SEMANTIC_IMAGE_WARNING in result["warnings"]


def test_product_with_no_image_returns_image_missing():
    result = analyze_product_image_payload(
        {
            "id": "prod-002",
            "raw_product_title": "Mystery Product",
        }
    )

    assert result["status"] == "IMAGE_MISSING"
    assert result["provider"] == "metadata_only"
    assert result["detected_package"] is None
    assert result["detected_text"] == []


@_no_vision_key
def test_metadata_only_mode_does_not_invent_package_or_text(_mock, tmp_path: Path):
    image_path = tmp_path / "product.jpg"
    image_path.write_bytes(b"fake-binary-jpg")

    result = analyze_product_image_payload(
        {
            "id": "prod-003",
            "image_url": "https://example.com/product.jpg",
            "local_image_path": str(image_path),
        }
    )

    assert result["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert result["detected_package"] is None
    assert result["detected_text"] == []
    assert result["metadata"]["local_file_exists"] is True
    assert result["metadata"]["local_file_size_bytes"] > 0


def test_configured_provider_returns_analyzed_payload_and_merges_metadata(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "product.jpg"
    image_path.write_bytes(b"fake-binary-jpg")

    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda provider, payload, metadata: ProductIntelligenceImageAnalysis(
            status="ANALYZED",
            image_url=None,
            local_image_path=None,
            detected_package="bottle",
            detected_text=["Hydrating Face Mist", "100ml"],
            detected_brand="Bosmax",
            detected_size_text="100ml",
            detected_form_factor="bottle",
            visual_confidence="HIGH",
            evidence=["provider:anthropic"],
            warnings=[],
            provider=provider,
            metadata={"provider_roundtrip": True},
        ),
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-004",
            "raw_product_title": "Hydrating Face Mist",
            "image_url": "https://example.com/product.jpg",
            "local_image_path": str(image_path),
        }
    )

    assert result["status"] == "ANALYZED"
    assert result["provider"] == "anthropic"
    assert result["detected_package"] == "bottle"
    assert result["detected_text"] == ["Hydrating Face Mist", "100ml"]
    assert result["visual_confidence"] == "HIGH"
    assert result["metadata"]["local_file_exists"] is True
    assert result["metadata"]["provider_roundtrip"] is True
    assert "provider:anthropic" in result["evidence"]


def test_configured_provider_failure_falls_closed_to_analysis_failed(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda provider, payload, metadata: None,
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-005",
            "raw_product_title": "Sabun Dobi Liquid",
            "image_url": "https://example.com/detergent.jpg",
        }
    )

    assert result["status"] == "ANALYSIS_FAILED"
    assert result["provider"] == "anthropic"
    assert result["detected_package"] is None
    assert result["detected_text"] == []
    assert result["warnings"] == ["SEMANTIC_IMAGE_ANALYSIS_FAILED"]
