from agent.services.registration_hook_cta_generation_service import (
    generate_registration_hook_cta,
)


def test_sensitive_health_hook_cta_stays_claim_safe():
    result = generate_registration_hook_cta(
        {
            "product_name": "Bosmax Herbs 5 ML",
            "benefits_text": "Membantu keyakinan kelelakian dan ketegangan.",
            "target_customer_text": "Lelaki dewasa",
            "usage_text": "Sapuan luaran setiap hari.",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["ketegangan", "bahagian intim"],
            "copy_route": "STEALTH",
            "silo": "health_supp_stealth_01",
        }
    )

    combined = " ".join(result["hook_angles"] + result["cta_angles"]).casefold()
    assert "luaran" in combined
    assert "prestasi fizikal lelaki" not in combined
    assert "ketegangan" not in combined
    assert "ubat kuat" not in combined
    assert "cure" not in combined


def test_general_product_hook_cta_is_non_empty():
    result = generate_registration_hook_cta(
        {
            "product_name": "Atlas Laundry Liquid",
            "benefits_text": "Membantu cucian harian kelihatan lebih bersih dan wangi.",
            "target_customer_text": "Isi rumah moden",
            "usage_text": "Tuang ke dalam mesin basuh.",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "laundry_01",
        }
    )

    assert len(result["hook_angles"]) == 3
    assert len(result["cta_angles"]) == 3
