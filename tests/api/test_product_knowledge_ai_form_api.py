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
    md_content = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "API Import Product",
  "source_lane": "OWNED",
  "product_knowledge_text": "From API"
}
```
"""
    files = {"file": ("test.md", io.BytesIO(md_content.encode("utf-8")), "text/markdown")}
    response = client.post("/api/product-knowledge/import-ai-form", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "PARSED"
    assert data["parsed_request"]["product_name"] == "API Import Product"
    assert data["completion_response"] is not None

def test_import_ai_form_api_invalid():
    files = {"file": ("bad.txt", io.BytesIO(b"not json"), "text/plain")}
    response = client.post("/api/product-knowledge/import-ai-form", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "PARSE_ERROR"
