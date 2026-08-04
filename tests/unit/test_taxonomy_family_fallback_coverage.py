"""Common physical-good categories must auto-resolve to a safe DIRECT-copy family
instead of falling to UNKNOWN_REVIEW_REQUIRED (which blocks commit on
CLEAR_PRODUCT_FAMILY_INFERENCE).

Two bugs closed here:
1. `_normalize_key` turns "&" -> "and", so taxonomy fallbacks written with "&"
   ("baby & maternity", "tools & hardware", "automotive & motorcycle",
   "phones & electronics", "food & beverage") silently NEVER matched — those
   whole categories were left UNKNOWN.
2. Sports & Outdoor / Toys / Books / Shoes / Luggage had no fallback at all.

None of these may resolve to a sensitive health family.
"""
import pytest

from agent.services.product_intelligence_service import resolve_product_intelligence_profile

_SENSITIVE = {"MALE_HEALTH_SENSITIVE", "FEMALE_HEALTH_SENSITIVE"}


@pytest.mark.parametrize(
    "title,category,expected_family",
    [
        # "&" normalization repair — these categories HAD fallbacks that never fired
        ("Botol Bayi Baru Lahir Moyuum PPSU", "Baby & Maternity", "BABY_DIAPER"),
        ("Mesin Rumput Lawn Mower Rechargeable", "Tools & Hardware", "AUTO_TOOL_GENERAL"),
        ("Universal Car Cover 3 Layers PVC", "Automotive & Motorcycle", "AUTO_TOOL_GENERAL"),
        ("Wireless Mouse Bluetooth 2.4Ghz", "Computers & Office Equipment", "electronics_wearable"),
        # newly-added category fallbacks
        ("SeaHunter Blue Shark Fishing Line Tali Pancing", "Sports & Outdoor", "AUTO_TOOL_GENERAL"),
        ("Kereta RC Drift Mini Kawalan Jauh", "Toys & Hobbies", "toy_play"),
        ("SPM KSSM Skema Jawapan Tingkatan 4", "Books, Magazines & Audio", "stationery_paper"),
        ("Novencci Canvas Sneakers Unisex", "Shoes", "fashion_apparel"),
        ("Beg Silang Badan Gaya Sukan Uniseks", "Luggage & Bags", "ACCESSORY_SMALL_ITEM"),
    ],
)
def test_category_auto_resolves_to_safe_family(title, category, expected_family):
    profile = resolve_product_intelligence_profile(
        {"id": "x", "raw_product_title": title, "category": category}
    )
    assert profile["bosmax_product_family"] == expected_family
    assert profile["bosmax_product_family"] not in _SENSITIVE
    assert profile["bosmax_product_family"] != "UNKNOWN_REVIEW_REQUIRED"
    # Safe generic families never route to the sensitive STEALTH lane.
    assert profile["copy_route"] != "STEALTH"


def test_unclassifiable_product_still_honestly_unknown():
    """A product with no usable category signal stays UNKNOWN — the auto-classify
    fallbacks must not fabricate a family for genuinely-ambiguous input."""
    profile = resolve_product_intelligence_profile(
        {"id": "x", "raw_product_title": "Mysterious Item 12345", "category": None}
    )
    assert profile["bosmax_product_family"] == "UNKNOWN_REVIEW_REQUIRED"
