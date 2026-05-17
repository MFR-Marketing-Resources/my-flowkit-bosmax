import pytest
import json
from agent.services.product_knowledge_service import (
    get_ai_form_template,
    get_ai_coaching_prompt,
    import_ai_form,
    _parse_ai_form_content
)

def test_get_ai_form_template():
    template = get_ai_form_template()
    assert template["filename"] == "BOSMAX_PRODUCT_KNOWLEDGE_INTAKE_FORM_v1.md"
    assert "bosmax_product_knowledge_form_version" in template["content"]
    assert "```json" in template["content"]
    assert '"commission_amount": null' in template["content"]
    assert '"currency": "MYR"' in template["content"]
    assert '"source_url": ""' in template["content"]
    assert '"tiktok_product_url": ""' in template["content"]

def test_get_ai_coaching_prompt():
    prompt = get_ai_coaching_prompt()
    assert "BOSMAX Product Intelligence Coach" in prompt
    assert "Markdown template" in prompt

def test_parse_markdown_json_block():
    md = """
# Some Title
Random text.
```json
{
  "key": "value",
  "nested": {"a": 1}
}
```
Footer.
"""
    parsed = _parse_ai_form_content(md)
    assert parsed.parsed_json == {"key": "value", "nested": {"a": 1}}
    assert parsed.strategy_used == "FENCED_JSON"

def test_parse_raw_json():
    raw = '{"key": "value"}'
    parsed = _parse_ai_form_content(raw)
    assert parsed.parsed_json == {"key": "value"}
    assert parsed.strategy_used == "RAW_JSON"

def test_parse_raw_json_txt_strategy():
    raw = '{"key": "value"}'
    parsed = _parse_ai_form_content(raw, file_name="Bosmax 5ML.txt", content_type="text/plain")
    assert parsed.parsed_json == {"key": "value"}
    assert parsed.strategy_used == "RAW_JSON_TEXT"

def test_parse_bom_whitespace_json():
    raw = "\ufeff   {\"key\": \"value\"}   "
    parsed = _parse_ai_form_content(raw, file_name="bom.JSON", content_type="application/json")
    assert parsed.parsed_json == {"key": "value"}
    assert parsed.strategy_used == "RAW_JSON"

def test_import_ai_form_valid():
    md = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "AI Product",
  "source_lane": "OWNED",
  "product_knowledge_text": "Smart info",
  "currency": "MYR",
  "commission_amount": 12.5,
  "commission_rate": "10%",
  "image_url": "https://example.com/product.jpg",
  "product_url": "https://example.com/product",
  "size_or_volume": "100ml",
  "user_review_status": "USER_APPROVED",
  "evidence_notes": {
    "what_ai_inferred": ["size from description"]
  }
}
```
"""
    result = import_ai_form(md, "test.md")
    assert result.parse_status == "PARSED"
    assert result.parser_strategy_used == "FENCED_JSON"
    assert result.parsed_request.product_name == "AI Product"
    assert result.parsed_request.image_url == "https://example.com/product.jpg"
    assert result.parsed_request.product_url == "https://example.com/product"
    assert result.parsed_request.currency == "MYR"
    assert result.parsed_request.commission_amount == 12.5
    assert result.completion_response is not None
    assert any("AI_INFERRED_FACTS_DETECTED" in w for w in result.parse_warnings)

def test_import_ai_form_malformed():
    md = "```json { malformed } ```"
    result = import_ai_form(md, "bad.md")
    assert result.parse_status == "PARSE_ERROR"
    assert result.parse_error_code == "INVALID_JSON"
    assert result.parse_error_detail is not None
    assert len(result.parse_errors) > 0

def test_import_ai_form_unsupported_version():
    md = '```json {"bosmax_product_knowledge_form_version": "2.0"} ```'
    result = import_ai_form(md, "old.md")
    assert result.parse_status == "VALIDATION_ERROR"
    assert result.parse_error_code == "UNSUPPORTED_VERSION"
    assert any("UNSUPPORTED_VERSION" in e for e in result.parse_errors)

def test_import_ai_form_raw_json_txt():
    raw = json.dumps({
        "bosmax_product_knowledge_form_version": "1.0",
        "product_name": "Bosmax Herbs",
        "source_lane": "OWNED",
        "size_or_volume": "5 ML",
        "user_review_status": "USER_REVIEW_REQUIRED",
    })
    result = import_ai_form(raw, "Bosmax 5ML.txt", "text/plain")
    assert result.parse_status == "PARSED"
    assert result.parser_strategy_used == "RAW_JSON_TEXT"
    assert result.detected_extension == "txt"
    assert result.parsed_request.product_name == "Bosmax Herbs"

def test_import_ai_form_uppercase_json():
    raw = json.dumps({
        "bosmax_product_knowledge_form_version": "1.0",
        "product_name": "Bosmax Herbs",
        "source_lane": "OWNED",
        "user_review_status": "USER_REVIEW_REQUIRED",
    })
    result = import_ai_form(raw, "Bosmax 5ML.JSON", "application/json")
    assert result.parse_status == "PARSED"
    assert result.parser_strategy_used == "RAW_JSON"
    assert result.detected_extension == "JSON"

def test_import_ai_form_no_json_found():
    result = import_ai_form("this is not json", "bad.txt", "text/plain")
    assert result.parse_status == "PARSE_ERROR"
    assert result.parse_error_code == "NO_JSON_FOUND"
    assert result.parse_error_detail is not None

def test_import_ai_form_multiple_json_objects():
    raw = '{"a":1}\n{"b":2}'
    result = import_ai_form(raw, "two.txt", "text/plain")
    assert result.parse_status == "PARSE_ERROR"
    assert result.parse_error_code == "MULTIPLE_JSON_OBJECTS_FOUND"

def test_import_risky_claim():
    md = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "Cancer Cure",
  "product_knowledge_text": "This product can cure everything.",
  "user_review_status": "USER_APPROVED"
}
```
"""
    result = import_ai_form(md, "risky.md")
    assert result.parse_status == "PARSED"
    assert result.completion_response.claim_gate == "CLAIM_BLOCKED"

def test_import_affiliate_lane():
    md = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "Affiliate Item",
  "source_lane": "FASTMOSS"
}
```
"""
    result = import_ai_form(md, "affiliate.md")
    assert any("AFFILIATE_LANE_CONTAMINATION_RISK" in w for w in result.parse_warnings)
