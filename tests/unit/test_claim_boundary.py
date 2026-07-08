"""Claim Boundary — preserve market/problem language, control overclaim only."""
from agent.authority import claim_boundary as cb


def test_market_problem_language_is_preserved_not_banned():
    banned = cb.banned_terms_for_brief(is_stealth=False)
    for term in ("kembung perut", "perut berangin", "buang angin", "legakan", "gigitan serangga", "sengal", "kebas", "resdung"):
        assert term not in banned, f"{term} must NOT be banned (market/problem language)"


def test_overclaim_is_banned():
    banned = cb.banned_terms_for_brief(is_stealth=False)
    for term in ("cure", "100%", "dijamin", "guarantee", "clinically proven", "klinikal", "kkm", "npra", "sembuh"):
        assert term in banned, f"{term} must be banned (overclaim)"


def test_stealth_bans_anatomy_general_does_not():
    assert "zakar" in cb.banned_terms_for_brief(is_stealth=True)
    assert "penis" in cb.banned_terms_for_brief(is_stealth=True)
    assert "zakar" not in cb.banned_terms_for_brief(is_stealth=False)


def test_assess_problem_language_present_and_safe():
    r = cb.assess_claim_boundary("Anak kembung perut waktu malam, perut berangin, ibu susah rehat.")
    assert r["safe"] is True
    assert r["overclaim_hits"] == []
    assert any("kembung" in t for t in r["problem_language_present"])


def test_assess_flags_overclaim():
    r = cb.assess_claim_boundary("Dijamin 100% sembuh, clinically proven, diluluskan KKM.")
    assert r["safe"] is False
    assert "dijamin" in [h.casefold() for h in r["overclaim_hits"]]
    assert any(h.casefold() in ("100%", "sembuh", "clinically proven") for h in r["overclaim_hits"])


def test_is_problem_language():
    assert cb.is_problem_language("anak kembung perut") is True
    assert cb.is_problem_language("nak tampil yakin setiap hari tanpa banyak langkah") is False
