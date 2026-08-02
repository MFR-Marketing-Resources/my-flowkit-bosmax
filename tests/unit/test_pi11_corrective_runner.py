"""B-604 unit tests for the PI-11 CORRECTIVE runner pure decision logic (restore-only). The
mutation-proving lifecycle tests live in tests/api/test_pi11_corrective_apply.py (real DB copy).
"""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pi11corr", REPO / "scripts" / "pi11_corrective_runner.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

_PROD = {"id": "p1", "category": "Home & Living", "subcategory": "Decor", "type": "Wall Sticker",
         "claim_risk_level": "LOW"}
_SUPPORT = {"verification_status": "REVIEWED_APPROVED", "source_url": "https://s/x", "source_type": "REVIEW_DRAFT"}


def _supported_prior(**over):
    prior = {
        "product_description": "Marble-pattern PVC wall sticker 30x60cm, waterproof, easy to cut.",
        "benefits_json": json.dumps(["waterproof surface", "cuts to size"]),
        "usp_json": json.dumps(["self-adhesive", "30x60cm tiles"]),
        "target_customer_text": "Home decorators refreshing walls affordably.",
        "buyer_persona_snapshot_json": json.dumps({"persona": "budget home decorators"}),
        "copy_strategy_summary_json": json.dumps({"angle": "affordable refresh"}),
        "source_urls_json": json.dumps({"source_url": "https://s/x"}),
        "image_evidence_json": json.dumps({"image_url": "https://img/x.jpg"}),
        "allowed_claims_json": json.dumps([]),
        "blocked_claims_json": json.dumps([]),
    }
    prior.update(over)
    return prior


def _full_support():
    return {f: dict(_SUPPORT) for f in C.RESTORABLE_REQUIRED}


# ── B-604-03: provenance/support required for ALL fields, not just prose specificity ──────────
def test_supported_field_is_restored():
    v, s = C.restorable_value("product_description", "SkyPlant Eye Balm Stick 9g Korean Formula.", dict(_SUPPORT))
    assert s == "RESTORED_SUPPORTED" and v


def test_product_specific_prose_without_provenance_is_not_promoted():
    # product-specific but NO provenance row -> not evidence
    v, s = C.restorable_value("product_description", "SkyPlant Eye Balm Stick 9g.", None)
    assert v is None and s == "UNSUPPORTED_NO_PROVENANCE"


def test_generic_or_placeholder_prior_is_rejected_even_if_supported():
    v, s = C.restorable_value("product_description", "X is a Home product. This description is a neutral, identity-based summary", dict(_SUPPORT))
    assert v is None and s == "REJECTED_GENERIC_OR_PLACEHOLDER"


def test_claim_blocked_prior_is_not_restored():
    v, s = C.restorable_value("product_description", "This cream cures eczema and disease.", dict(_SUPPORT))
    assert v is None and s == "REJECTED_CLAIM_BLOCKED"


# ── B-604-04: claim reconciliation requires safety AND factual support ───────────────────────
def test_safe_but_unsupported_claim_is_not_allowed():
    allowed, blocked, q = C.reconcile_claims(["Clinically proven to work"], [], _PROD)  # safe-ish words, unsupported
    assert "Clinically proven to work" not in allowed
    assert "Clinically proven to work" in blocked  # retained, not deleted


def test_identity_grounded_claim_is_supported_and_allowed():
    claim = "Product type: Home & Living / Decor / Wall Sticker (source: product identity)."
    allowed, blocked, q = C.reconcile_claims([claim], [], _PROD)
    assert claim in allowed and claim not in blocked


def test_prior_blocked_claims_are_retained():
    allowed, blocked, q = C.reconcile_claims([], ["Do not claim it cures eczema"], _PROD)
    assert "Do not claim it cures eczema" in blocked


# ── B-604-05: persona/strategy sanitized, each value evaluated ONCE ──────────────────────────
def test_persona_sanitized_single_eval():
    persona = {"audience": "shoppers", "desires": ["a cream that cures eczema", "gentle daily care"]}
    clean, removed = C.sanitize_planning(persona)
    assert "a cream that cures eczema" not in clean["desires"] and "gentle daily care" in clean["desires"]
    assert removed == ["a cream that cures eczema"]  # exactly once


# ── B-604-05/07: RESTORE_APPROVE is decided by the REAL validator ────────────────────────────
def test_one_field_does_not_complete_an_empty_product():
    # only a supported description; everything else absent -> validator must NOT approve
    prior = {"product_description": "Marble-pattern PVC wall sticker 30x60cm."}
    prov = {"product_description": dict(_SUPPORT)}
    plan = C.build_correction_plan(_PROD, None, prior, prov)
    assert plan["decision"] == "LEAVE_INCOMPLETE"
    assert any(b.startswith("MISSING_REQUIRED_FIELDS") for b in plan["approval_blockers"])


def test_strict_restore_only_blocks_on_allowed_claims():
    # fully supported copy fields but empty allowed_claims (nothing to restore) -> incomplete
    plan = C.build_correction_plan(_PROD, None, _supported_prior(), _full_support(), assert_identity_claims=False)
    assert plan["decision"] == "LEAVE_INCOMPLETE"
    assert plan["approval_blockers"] == ["MISSING_REQUIRED_FIELDS:allowed_claims_json"]


def test_identity_claim_option_makes_fully_restored_product_approvable():
    plan = C.build_correction_plan(_PROD, None, _supported_prior(), _full_support(), assert_identity_claims=True)
    assert plan["decision"] == "RESTORE_APPROVE"
    assert plan["readiness_status"] == C.READINESS_GOVERNED_ABSENCE  # usage/ingredients/warnings governed-absent
    assert plan["identity_claim_added"]
    assert set(plan["dispositions"]) == {"usage_text", "ingredients_text", "warnings_text"}


def test_identity_claim_not_added_when_taxonomy_trips_lexicon():
    pet = {"id": "pet", "category": "Pet Supplies", "subcategory": "Dog & Cat Food", "type": "Cat Treats",
           "claim_risk_level": "LOW"}
    plan = C.build_correction_plan(pet, None, _supported_prior(), _full_support(), assert_identity_claims=True)
    assert plan["identity_claim_added"] is None  # "Cat Treats" trips the lexicon -> no unsafe assertion
    assert plan["decision"] == "LEAVE_INCOMPLETE"


# ── B-604-01: idempotent plan digest ─────────────────────────────────────────────────────────
def test_plan_digest_is_idempotent():
    a = C.build_correction_plan(_PROD, None, _supported_prior(), _full_support(), assert_identity_claims=True)
    b = C.build_correction_plan(_PROD, None, _supported_prior(), _full_support(), assert_identity_claims=True)
    assert C.plan_digest(a) == C.plan_digest(b)
