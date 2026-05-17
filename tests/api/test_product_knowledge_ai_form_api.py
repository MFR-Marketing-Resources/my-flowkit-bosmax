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

def test_get_ai_coaching_prompt_api():
    response = client.get("/api/product-knowledge/ai-coaching-prompt")
    assert response.status_code == 200
    data = response.json()
    assert "prompt" in data

def test_import_ai_form_api():
    raw_content = json.dumps({
        "bosmax_product_knowledge_form_version": "1.0",
        "product_name": "API Import Product",
        "source_lane": "OWNED",
        "product_knowledge_text": "From API",
        "image_url": "https://example.com/product.jpg",
        "product_url": "https://example.com/product",
        "currency": "MYR",
        "commission_amount": 11.25,
        "commission_rate": "9%",
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
    assert data["parsed_request"]["commission_amount"] == 11.25
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
