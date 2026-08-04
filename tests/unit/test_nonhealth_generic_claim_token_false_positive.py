"""Generic physical words — "ketat" (tight), "rapat" (close/snug), "ketegangan"
(tension), "anjal" (elastic) — must NOT drag a clearly non-health physical-goods
product into intimate MALE/FEMALE health classification.

Live regression: a SeaHunter braided FISHING LINE (Sports & Outdoor) whose spooling
instructions say "diikat dengan ketat ... gunakan sedikit ketegangan" was resolved
to FEMALE_HEALTH_SENSITIVE / CLAIM_REVIEW_REQUIRED, mislabeling it a sensitive
feminine-health product and freezing it behind CLEAR_PRODUCT_FAMILY_INFERENCE. The
tokens only carry a sensitive-health meaning inside a health/beauty/intimate context;
genuine feminine/male products still classify sensitive because their taxonomy or an
actual intimate cue corroborates the token.
"""
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.product_intelligence_service import (
    _resolve_family_from_title,
    evaluate_product_claims,
    resolve_product_intelligence_profile,
)
from agent.services.product_knowledge_service import complete_product_knowledge

_FISHING_TITLE = (
    "SeaHunter Blue Shark 100M/150M/300M Fishing Line, PE X8 Braided Multifilament "
    "Line 20-35LB Tali Pancing Senar benang 100M Japan Quality High Stength Main Line"
)
_FISHING_USAGE = (
    "Persediaan Kekili (Spooling): Pastikan benang diikat dengan ketat pada spool "
    "kekili menggunakan simpul arbor knot. Gunakan sedikit ketegangan (tension) "
    "semasa menggulung untuk mengelakkan benang longgar."
)


def _fishing_product(**overrides):
    payload = {
        "id": "prod-fishing-001",
        "source": "FASTMOSS",
        "raw_product_title": _FISHING_TITLE,
        "usage": _FISHING_USAGE,
        "category": "Sports & Outdoor",
    }
    payload.update(overrides)
    return payload


def test_fishing_line_not_resolved_to_sensitive_family():
    family, _reason = _resolve_family_from_title(_fishing_product())
    assert family not in {"FEMALE_HEALTH_SENSITIVE", "MALE_HEALTH_SENSITIVE"}


def test_fishing_line_generic_tokens_do_not_trigger_claim_review():
    _blocked, review, _warn = evaluate_product_claims(_fishing_product())
    assert "ketat" not in review
    assert "ketegangan" not in review
    assert "rapat" not in review


def test_fishing_line_profile_not_sensitive_and_no_false_tokens():
    """The fabricated intimate-health identity must be gone.  The family may
    honestly fall to UNKNOWN_REVIEW_REQUIRED (no BOSMAX rule for a braided
    fishing line yet) — that is a truthful "human, confirm the family" state,
    NOT a confident mislabel — but it must never be a sensitive-health family,
    must not route to the STEALTH sensitive lane, and must carry no fabricated
    sensitive claim tokens."""
    profile = resolve_product_intelligence_profile(_fishing_product())
    assert profile["bosmax_product_family"] not in {
        "FEMALE_HEALTH_SENSITIVE",
        "MALE_HEALTH_SENSITIVE",
    }
    assert profile["copy_route"] != "STEALTH"
    assert "ketat" not in profile["claim_tokens"]
    assert "ketegangan" not in profile["claim_tokens"]


def test_genuine_feminine_ketat_still_sensitive():
    """A Feminine-Care product using the SAME word stays gated — the taxonomy
    context corroborates the token."""
    product = {
        "id": "prod-fem-001",
        "raw_product_title": "Jamu Perapat Miss V rapat dan ketat semula",
        "category": "Health",
        "subcategory": "Feminine Care",
        "type": "Female Health",
    }
    profile = resolve_product_intelligence_profile(product)
    assert profile["bosmax_product_family"] == "FEMALE_HEALTH_SENSITIVE"
    assert profile["claim_gate"] == "CLAIM_REVIEW_REQUIRED"


def test_fishing_line_full_completion_path_not_male_health():
    """End-to-end through complete_product_knowledge (the real Smart Registration
    recompute). Guards two extra traps beyond the intelligence profile: the
    "lelaki" (man) mapping keyword and the "kulit" (skin) safety-warning that
    were dragging a men's-audience fishing line into Male Health / Supplements /
    STEALTH."""
    req = ProductKnowledgeCompleteRequest(
        product_name="SeaHunter Blue Shark Fishing Line Tali Pancing PE X8 Braided",
        product_knowledge_text="Benang pancing braided PE X8, 8 helai serat polyethylene.",
        usage_text="Ikat benang dengan ketat pada spool kekili; guna sedikit ketegangan semasa menggulung.",
        target_customer_text="Lelaki berumur 18-55 tahun yang minat memancing.",
        warnings_text="Benang braided sangat tajam dan boleh memotong kulit jika ditarik tangan kosong.",
        category="Sports & Outdoor",
        source_lane="FASTMOSS",
    )
    resp = complete_product_knowledge(req, enable_text_assist=False)
    assert resp.suggested_bosmax_product_family not in {
        "FEMALE_HEALTH_SENSITIVE",
        "MALE_HEALTH_SENSITIVE",
    }
    assert resp.suggested_subcategory != "Supplements"
    assert resp.suggested_type != "Male Health"
    assert resp.suggested_copy_route != "STEALTH"
    assert "ketat" not in (resp.claim_tokens or [])
    assert "ketegangan" not in (resp.claim_tokens or [])


def test_genuine_male_health_still_maps_via_specific_keyword():
    """A real male-enhancement product keeps its Male Health mapping — the
    specific tokens (kuat lelaki / tenaga batin) survive the rule tightening."""
    req = ProductKnowledgeCompleteRequest(
        product_name="Kuat Lelaki Herba Tenaga Batin Tahan Lama",
        product_knowledge_text="Suplemen herba untuk kuat lelaki dan tenaga batin.",
        category="Health",
        source_lane="MANUAL",
    )
    resp = complete_product_knowledge(req, enable_text_assist=False)
    assert resp.suggested_bosmax_product_family == "MALE_HEALTH_SENSITIVE"
    assert resp.suggested_subcategory == "Supplements"


def test_genuine_male_ketegangan_still_sensitive():
    product = {
        "id": "prod-male-001",
        "raw_product_title": "Bosmax Herbs 5 ML kuat lelaki",
        "benefits": "Meningkatkan ketegangan dan keyakinan kelelakian.",
        "category": "Health",
        "subcategory": "Supplements",
        "type": "Male Health",
    }
    profile = resolve_product_intelligence_profile(product)
    assert profile["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"
    assert profile["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert "ketegangan" in profile["claim_tokens"]
