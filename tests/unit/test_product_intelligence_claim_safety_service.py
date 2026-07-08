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


def test_claim_safety_ignores_internal_guardrail_and_avatar_fields():
    # Regression (BOSMAX health category): internal, non-published fields legitimately
    # contain medical words and must NOT trip the product-claim gate —
    #   * blocked_claims_json = the "do NOT say" quarantine / guardrail list, and
    #   * buyer_persona_snapshot_json = the customer AVATAR, which describes the
    #     customer's world ("kelegaan tanpa ambil ubat", pains like "penyakit").
    # The published copy stays clean market-problem language, so the draft is SAFE.
    result = evaluate_claim_safety(
        {
            "product_description": "Minyak angin tradisional untuk melegakan kembung perut dan sengal.",
            "benefits_json": ["melegakan perut kembung", "mengurangkan rasa sengal"],
            "allowed_claims_json": ["melegakan kembung perut", "sesuai kegunaan luaran"],
            "blocked_claims_json": [
                "Jangan guna 'menyembuhkan' atau 'merawat' sebarang penyakit.",
                "Jangan dakwa untuk semua jenis penyakit.",
                "ubat",
            ],
            "buyer_persona_snapshot_json": {
                "audience": "Warga emas yang mengalami penyakit ringan",
                "desires": ["Nak kelegaan tanpa perlu pergi klinik atau ambil ubat"],
            },
            "copy_strategy_summary_json": {"angles": ["bukan ubat, minyak tradisional"]},
            "reviewer_note": "Semak istilah 'ubat' / 'penyakit' sebelum lulus.",
        }
    )

    assert result["claim_gate"] == "CLAIM_SAFE"
    assert result["claim_risk_level"] == "LOW"
    # No claim tokens flagged from the guardrail list, the avatar, or the clean copy.
    assert result["claim_tokens_json"] == []
    # The guardrail list is preserved in the output (still kept as guardrails).
    assert "ubat" in result["blocked_claims_json"]


def test_claim_safety_still_blocks_overclaim_in_published_copy():
    # The published copy IS still scanned — a real overclaim there is still blocked.
    result = evaluate_claim_safety(
        {
            "product_description": "Merawat penyakit dan menyembuhkan dalam 3 hari.",
            "buyer_persona_snapshot_json": {"desires": ["clean avatar"]},
        }
    )
    assert result["claim_gate"] == "CLAIM_BLOCKED"
    assert "rawat" in result["claim_tokens_json"]
    assert "penyakit" in result["claim_tokens_json"]


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
