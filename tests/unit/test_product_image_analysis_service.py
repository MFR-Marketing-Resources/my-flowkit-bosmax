from pathlib import Path

from agent.services.product_image_analysis_service import (
    SEMANTIC_IMAGE_WARNING,
    analyze_product_image_payload,
)


def test_image_url_without_provider_returns_provider_not_configured_and_no_fake_detections():
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


def test_metadata_only_mode_does_not_invent_package_or_text(tmp_path: Path):
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
