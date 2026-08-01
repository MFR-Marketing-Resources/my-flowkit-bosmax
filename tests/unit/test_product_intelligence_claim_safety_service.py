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


# ── Mission-08D: contextual treat/cure downgrade (non-medical phrase + category) ──
AUTOMOTIVE = {"category": "Automotive"}
WELLNESS = {"category": "Wellness & Herbal"}
BABY = {"category": "Baby & Kids"}


def test_windshield_treatment_downgrades_to_review_required_for_automotive():
    """The Nakamichi false positive: the product NAME contains 'Treatment'."""
    result = evaluate_claim_safety(
        {"product_description": "Nakamichi Rapid Windshield Treatment Water Cleaner 30ml."},
        product=AUTOMOTIVE,
    )
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED", result
    assert "treat" in result["claim_tokens_json"]


def test_coating_allow_to_cure_downgrades_to_review_required():
    """The Diamond Coating false positive: 'Allow to cure for 10 minutes'."""
    result = evaluate_claim_safety(
        {"usage_text": "Spray on the panel. Allow to cure for 10 minutes. Buff."},
        product=AUTOMOTIVE,
    )
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED", result
    assert "cure" in result["claim_tokens_json"]


def test_curing_time_phrase_also_downgrades():
    # Curing is a cure-token spelling; this exact process phrase downgrades to review.
    safe = evaluate_claim_safety(
        {"product_description": "Ceramic spray with a 10 minute curing time."},
        product=AUTOMOTIVE,
    )
    assert safe["claim_gate"] == "CLAIM_REVIEW_REQUIRED", safe
    # The bare token inside the enumerated "cure time" phrase DOES need the downgrade.
    result = evaluate_claim_safety(
        {"usage_text": "Leave a 10 minute cure time before buffing."},
        product=AUTOMOTIVE,
    )
    medical = evaluate_claim_safety(
        {"usage_text": "Curing disease without medical care."},
        product=AUTOMOTIVE,
    )
    assert medical["claim_gate"] == "CLAIM_BLOCKED", medical

    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED", result


def test_medical_treat_stays_fully_blocked_even_for_automotive_category():
    """One bare medical use of the token anywhere keeps the FULL block: the phrase
    context governs, not the category alone."""
    result = evaluate_claim_safety(
        {"product_description": "Windshield Treatment spray that also treats joint pain."},
        product=AUTOMOTIVE,
    )
    assert result["claim_gate"] == "CLAIM_BLOCKED", result
    assert "treat" in result["claim_tokens_json"]


def test_wellness_cure_pain_stays_blocked():
    result = evaluate_claim_safety(
        {"benefits_json": ["cures pain fast"]}, product=WELLNESS,
    )
    assert result["claim_gate"] == "CLAIM_BLOCKED"


def test_health_category_never_downgrades_even_with_the_exact_phrase():
    """A wellness product whose copy says 'surface treatment' is still a health-context
    product: no downgrade outside provably non-health categories."""
    result = evaluate_claim_safety(
        {"product_description": "Herbal balm with a gentle surface treatment effect."},
        product=WELLNESS,
    )
    assert result["claim_gate"] == "CLAIM_BLOCKED"
    result_baby = evaluate_claim_safety(
        {"product_description": "Baby mattress surface treatment spray."},
        product=BABY,
    )
    assert result_baby["claim_gate"] == "CLAIM_BLOCKED"
    result_supplements = evaluate_claim_safety(
        {"product_description": "Supplement surface treatment format."},
        product={"category": "Health Supplements"},
    )
    assert result_supplements["claim_gate"] == "CLAIM_BLOCKED"


def test_unknown_or_absent_category_keeps_the_full_block():
    payload = {"product_description": "Windshield Treatment cleaner."}
    assert evaluate_claim_safety(payload)["claim_gate"] == "CLAIM_BLOCKED"
    assert evaluate_claim_safety(payload, product={})["claim_gate"] == "CLAIM_BLOCKED"
    assert evaluate_claim_safety(
        payload, product={"category": ""})["claim_gate"] == "CLAIM_BLOCKED"


def test_other_blocked_tokens_are_untouched_by_the_downgrade():
    """Only treat/cure have contexts; ubat/penyakit/sembuh etc. block regardless."""
    result = evaluate_claim_safety(
        {"product_description": "Windshield Treatment yang juga ubat untuk penyakit."},
        product=AUTOMOTIVE,
    )
    assert result["claim_gate"] == "CLAIM_BLOCKED"
    assert "ubat" in result["claim_tokens_json"]
    assert "penyakit" in result["claim_tokens_json"]


def test_exact_non_medical_phrase_in_allowed_claims_downgrades_after_full_scan():
    result = evaluate_claim_safety(
        {"allowed_claims_json": ["Windshield Treatment coating protection"]},
        product=AUTOMOTIVE,
    )
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED", result
    assert "treat" in result["claim_tokens_json"]


def test_ingestible_category_never_downgrades_exact_non_medical_phrase():
    result = evaluate_claim_safety(
        {"allowed_claims_json": ["surface treatment finish"]},
        product={"category": "Food & Beverage"},
    )
    assert result["claim_gate"] == "CLAIM_BLOCKED", result
    assert "treat" in result["claim_tokens_json"]
