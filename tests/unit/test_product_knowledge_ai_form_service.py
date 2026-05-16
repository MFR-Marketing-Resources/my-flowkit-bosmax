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
    assert parsed == {"key": "value", "nested": {"a": 1}}

def test_parse_raw_json():
    raw = '{"key": "value"}'
    parsed = _parse_ai_form_content(raw)
    assert parsed == {"key": "value"}

def test_import_ai_form_valid():
    md = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "AI Product",
  "source_lane": "OWNED",
  "product_knowledge_text": "Smart info",
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
    assert result.parsed_request.product_name == "AI Product"
    assert result.completion_response is not None
    assert any("AI_INFERRED_FACTS_DETECTED" in w for w in result.parse_warnings)

def test_import_ai_form_malformed():
    md = "```json { malformed } ```"
    result = import_ai_form(md, "bad.md")
    assert result.parse_status == "PARSE_ERROR"
    assert len(result.parse_errors) > 0

def test_import_ai_form_unsupported_version():
    md = '```json {"bosmax_product_knowledge_form_version": "2.0"} ```'
    result = import_ai_form(md, "old.md")
    assert result.parse_status == "VALIDATION_ERROR"
    assert any("UNSUPPORTED_VERSION" in e for e in result.parse_errors)

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
