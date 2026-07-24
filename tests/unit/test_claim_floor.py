"""Claim posture FLOOR — a content scan must never sink below category risk.

Live case that forced this: BOSMAX HERBS Herbal Oil Roll On, a male-vitality
topical (`claim_risk_level=HIGH`, family MALE_HEALTH_SENSITIVE demanding
CLAIM_REVIEW_REQUIRED). Its draft recorded the owner's asserted effect
"melancarkan peredaran darah" — a physiological claim containing NO banned
token — so `evaluate_claim_safety` returned CLAIM_SAFE/LOW and the draft went
READY_FOR_APPROVAL with a falsely-safe posture on the most sensitive product in
the catalog.
"""
from agent.services import product_intelligence_review_draft_service as svc

HIGH_RISK_PRODUCT = {
    "id": "p-stealth",
    "product_display_name": "BOSMAX HERBS Herbal Oil Roll On",
    "category": "Health",
    "subcategory": "Supplements",
    "silo": "health_supp_stealth_01",
    "claim_risk_level": "HIGH",
}
BENIGN_PRODUCT = {"id": "p-plain", "category": "Household", "claim_risk_level": "LOW"}

# Text with a real physiological claim but NO banned token.
CLEAN_LOOKING_PAYLOAD = {
    "product_description": "Minyak herba sapuan luaran untuk lelaki dewasa.",
    "benefits_json": ["Melancarkan peredaran darah"],
}


def test_content_scan_alone_calls_the_live_case_safe():
    """Pins WHY the floor is needed: with no product context the scan says SAFE."""
    out = svc._evaluate_validation_payload(dict(CLEAN_LOOKING_PAYLOAD), None)
    assert out["claim_gate"] == "CLAIM_SAFE"
    assert out["claim_risk_level"] == "LOW"


def test_high_risk_product_raises_the_floor():
    out = svc._evaluate_validation_payload(dict(CLEAN_LOOKING_PAYLOAD), HIGH_RISK_PRODUCT)
    assert out["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert out["claim_risk_level"] == "HIGH"


def _complete_payload():
    """Every REQUIRED_FIELD filled — mirrors the real Bosmax draft, which had
    completeness 1.0 and so had nothing ELSE left to block approval."""
    payload = {f: "x" for f in svc.REQUIRED_FIELDS}
    payload.update(CLEAN_LOOKING_PAYLOAD)
    payload["benefits_json"] = ["Melancarkan peredaran darah"]
    return payload


def test_raised_floor_blocks_approval_on_an_otherwise_complete_draft():
    """The live failure exactly: completeness 1.0, no banned token, so nothing
    else stood between it and approval."""
    clean = svc._evaluate_validation_payload(_complete_payload(), None)
    assert clean["readiness_status"] == "READY_FOR_APPROVAL"  # the hole

    floored = svc._evaluate_validation_payload(_complete_payload(), HIGH_RISK_PRODUCT)
    assert floored["readiness_status"] == "CLAIM_REVIEW_REQUIRED"
    assert any(b.startswith("CLAIM_REVIEW_REQUIRED") for b in floored["approval_blockers"])


def test_floor_never_lowers_a_worse_computed_verdict():
    """A content scan that finds something genuinely blocked must survive."""
    payload = {"product_description": "Produk ini menyembuhkan dan merawat 100% dijamin."}
    out = svc._evaluate_validation_payload(payload, BENIGN_PRODUCT)
    assert out["claim_gate"] in ("CLAIM_REVIEW_REQUIRED", "CLAIM_BLOCKED")
    assert out["claim_gate"] != "CLAIM_SAFE"


def test_benign_product_is_unaffected():
    """Narrow on purpose: an ordinary product must NOT be dragged into claim
    review. An earlier draft of this floor also read the framework family gate,
    which swept in every unclassified item for no safety gain."""
    out = svc._evaluate_validation_payload(dict(CLEAN_LOOKING_PAYLOAD), BENIGN_PRODUCT)
    assert out["claim_gate"] == "CLAIM_SAFE"
    assert out["claim_risk_level"] == "LOW"


def test_product_with_no_risk_field_is_unaffected():
    out = svc._evaluate_validation_payload(
        dict(CLEAN_LOOKING_PAYLOAD), {"id": "x", "category": "Household"}
    )
    assert out["claim_gate"] == "CLAIM_SAFE"


def test_medium_risk_raises_risk_but_not_the_gate():
    out = svc._evaluate_validation_payload(
        dict(CLEAN_LOOKING_PAYLOAD), {"id": "x", "claim_risk_level": "MEDIUM"}
    )
    assert out["claim_risk_level"] == "MEDIUM"
    assert out["claim_gate"] == "CLAIM_SAFE"


def test_missing_or_malformed_product_is_safe_to_pass():
    for bad in (None, {}, "nope", 7):
        out = svc._evaluate_validation_payload(dict(CLEAN_LOOKING_PAYLOAD), bad)
        assert out["claim_gate"] in _ALL_GATES


_ALL_GATES = {"CLAIM_SAFE", "CLAIM_REVIEW_REQUIRED", "CLAIM_BLOCKED"}


def test_floor_helper_is_ordered_correctly():
    assert svc._claim_floor(HIGH_RISK_PRODUCT) == ("CLAIM_REVIEW_REQUIRED", "HIGH")
    assert svc._claim_floor(None) == ("CLAIM_SAFE", "LOW")
    assert svc._claim_floor({}) == ("CLAIM_SAFE", "LOW")
