"""Tests for the system-avatar contract.

Operator mandate: a visible human on screen must be backed by a system avatar
reference; otherwise the prompt is product-only (FACELESS) and a run that still
demands a human is blocked.
"""
from agent.services import system_avatar_contract as sac


# ── package_has_system_avatar ────────────────────────────────

def test_product_only_assets_have_no_system_avatar():
    assets = [{"slot_key": "start_frame", "asset_source": "PRODUCT_IMAGE_URL"},
              {"slot_key": "end_frame", "asset_source": "NONE"}]
    assert sac.package_has_system_avatar(assets) is False


def test_avatar_slot_counts_as_system_avatar():
    assets = [{"slot_key": "start_frame", "asset_source": "PRODUCT_IMAGE_URL"},
              {"slot_key": "character_reference", "asset_source": "AVATAR_UPLOAD"}]
    assert sac.package_has_system_avatar(assets) is True


def test_avatar_id_counts_as_system_avatar():
    assert sac.package_has_system_avatar([], avatar_id="avatar_123") is True
    assert sac.package_has_system_avatar([], avatar_id=None) is False
    assert sac.package_has_system_avatar(None) is False


# ── prompt_demands_visible_human ─────────────────────────────

def test_visible_creator_prompt_demands_human():
    assert sac.prompt_demands_visible_human("CHARACTER: One visible creator on screen.") is True
    assert sac.prompt_demands_visible_human("CHARACTER (AI AVATAR — LIP-SYNC): persona.") is True


def test_product_only_prompt_does_not_demand_human():
    assert sac.prompt_demands_visible_human(
        "SUBJECT (FACELESS): Product and hands only. No face or avatar shown."
    ) is False
    assert sac.prompt_demands_visible_human("Vertical 9:16 handheld product reveal.") is False
    assert sac.prompt_demands_visible_human(None) is False


# ── resolve_presence_for_avatar (compiler downgrade, B) ──────

def test_visible_creator_downgrades_to_faceless_without_avatar():
    presence, downgraded = sac.resolve_presence_for_avatar("VISIBLE_CREATOR", has_system_avatar=False)
    assert presence == "FACELESS" and downgraded is True


def test_avatar_ai_downgrades_to_faceless_without_avatar():
    presence, downgraded = sac.resolve_presence_for_avatar("AVATAR_AI", has_system_avatar=False)
    assert presence == "FACELESS" and downgraded is True


def test_visible_creator_kept_when_system_avatar_present():
    presence, downgraded = sac.resolve_presence_for_avatar("VISIBLE_CREATOR", has_system_avatar=True)
    assert presence == "VISIBLE_CREATOR" and downgraded is False


def test_faceless_is_unchanged():
    presence, downgraded = sac.resolve_presence_for_avatar("FACELESS", has_system_avatar=False)
    assert presence == "FACELESS" and downgraded is False


# ── assert_system_avatar_contract (preflight guard, A) ───────

def test_human_prompt_without_avatar_blocks():
    err = sac.assert_system_avatar_contract("CHARACTER: One visible creator on screen.", has_system_avatar=False)
    assert err == sac.ERR_CHARACTER_PROMPT_WITHOUT_SYSTEM_AVATAR


def test_human_prompt_with_avatar_allowed():
    err = sac.assert_system_avatar_contract("CHARACTER: One visible creator on screen.", has_system_avatar=True)
    assert err is None


def test_product_only_prompt_without_avatar_allowed():
    err = sac.assert_system_avatar_contract("Product-only reveal, no creator.", has_system_avatar=False)
    assert err is None
