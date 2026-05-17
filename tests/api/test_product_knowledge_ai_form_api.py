import pytest
from fastapi.testclient import TestClient
from agent.main import app
import json
import io

client = TestClient(app)

def test_get_ai_form_template_api():
    response = client.get("/api/product-knowledge/ai-form-template")
    assert response.status_code == 200
    data = response.json()
    assert "filename" in data
    assert "content" in data
    assert '"image_url": "UNKNOWN"' in data["content"]
    assert '"commission_amount": null' in data["content"]
    assert '"tiktok_shop_url": "UNKNOWN"' in data["content"]

def test_get_ai_coaching_prompt_api():
    response = client.get("/api/product-knowledge/ai-coaching-prompt")
    assert response.status_code == 200
    data = response.json()
    assert "prompt" in data
    assert "commission amount" in data["prompt"]
    assert "product image URL" in data["prompt"]
    assert "valid raw JSON" in data["prompt"]

def test_import_ai_form_api():
    raw_content = json.dumps({
        "bosmax_product_knowledge_form_version": "1.0",
        "product_name": "API Import Product",
        "source_lane": "OWNED",
        "product_knowledge_text": "From API",
        "image_url": "https://example.com/product.jpg",
        "product_url": "https://example.com/product",
        "source_url": "https://example.com/source",
        "tiktok_product_url": "https://shop.tiktok.com/view/product/123",
        "tiktok_shop_url": "https://shop.tiktok.com/view/shop/999",
        "currency": "MYR",
        "commission_amount": 11.25,
        "commission_rate": "9%",
        "image_notes": "Bottle image supplied by operator.",
        "product_form_factor": "small bottle",
        "packaging_description": "matte bottle with roll-on cap",
        "user_review_status": "USER_REVIEW_REQUIRED",
    })
    files = {"file": ("test.JSON", io.BytesIO(raw_content.encode("utf-8")), "application/json")}
    response = client.post("/api/product-knowledge/import-ai-form", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "PARSED"
    assert data["parser_strategy_used"] == "RAW_JSON"
    assert data["parsed_request"]["product_name"] == "API Import Product"
    assert data["parsed_request"]["image_url"] == "https://example.com/product.jpg"
    assert data["parsed_request"]["product_url"] == "https://example.com/product"
    assert data["parsed_request"]["source_url"] == "https://example.com/source"
    assert data["parsed_request"]["tiktok_product_url"] == "https://shop.tiktok.com/view/product/123"
    assert data["parsed_request"]["tiktok_shop_url"] == "https://shop.tiktok.com/view/shop/999"
    assert data["parsed_request"]["commission_amount"] == 11.25
    assert data["parsed_request"]["image_notes"] == "Bottle image supplied by operator."
    assert data["completion_response"] is not None

def test_import_ai_form_api_txt_raw_json():
    raw_content = json.dumps({
        "bosmax_product_knowledge_form_version": "1.0",
        "product_name": "TXT Import Product",
        "source_lane": "OWNED",
        "user_review_status": "USER_REVIEW_REQUIRED",
    })
    files = {"file": ("good.txt", io.BytesIO(raw_content.encode("utf-8")), "text/plain")}
    response = client.post("/api/product-knowledge/import-ai-form", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "PARSED"
    assert data["parser_strategy_used"] == "RAW_JSON_TEXT"

def test_import_ai_form_api_invalid():
    files = {"file": ("bad.txt", io.BytesIO(b"not json"), "text/plain")}
    response = client.post("/api/product-knowledge/import-ai-form", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "PARSE_ERROR"
    assert data["parse_error_code"] == "NO_JSON_FOUND"
    assert data["accepted_formats"]
