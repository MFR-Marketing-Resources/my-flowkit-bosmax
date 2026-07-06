from agent.services.product_intelligence_claim_safety_service import (
    evaluate_claim_safety,
)


def test_claim_safety_safe_product_truth_stays_claim_safe():
    result = evaluate_claim_safety(
        {
            "product_description": "Compact 500ml bottle for daily storage convenience.",
            "benefits_json": ["portable", "travel-friendly"],
            "allowed_claims_json": ["portable bottle", "easy daily carry"],
            "buyer_persona_snapshot_json": {"persona": "busy commuter"},
        }
    )

    assert result["claim_gate"] == "CLAIM_SAFE"
    assert result["claim_risk_level"] == "LOW"
    assert result["claim_tokens_json"] == []
    assert result["blocked_claims_json"] == []


def test_claim_safety_blocks_medical_english_and_malay_language():
    result = evaluate_claim_safety(
        {
            "product_description": "Guaranteed relief untuk penyakit dan sembuh cepat.",
            "allowed_claims_json": ["cure back pain", "portable support"],
        }
    )

    assert result["claim_gate"] == "CLAIM_BLOCKED"
    assert result["claim_risk_level"] == "HIGH"
    assert "cure" in result["claim_tokens_json"]
    assert "sembuh" in result["claim_tokens_json"]
    assert "penyakit" in result["claim_tokens_json"]
    assert "cure back pain" in result["blocked_claims_json"]
    assert "portable support" in result["allowed_claims_json"]


def test_claim_safety_review_terms_require_human_review_without_block():
    result = evaluate_claim_safety(
        {
            "product_description": "Anti-inflammatory comfort positioning for review.",
            "allowed_claims_json": ["doctor certified formula"],
        }
    )

    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert result["claim_risk_level"] == "MEDIUM"
    assert "anti-inflammatory" in result["claim_tokens_json"]
    assert "doctor certified" in result["claim_tokens_json"]
    assert "doctor certified formula" in result["blocked_claims_json"]
