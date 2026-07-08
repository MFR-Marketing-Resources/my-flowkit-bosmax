"""Poster copy auto-fit service — condense over-length copy, fail-closed, mock-only.

The provider adapter is ALWAYS mocked: a real call would spend text_assist tokens.
"""

import agent.services.poster_copy_fit_service as svc
from agent.models.poster_copy_fit import PosterCopyFitRequest

# Every field deliberately over its poster limit (hook 48 / subhook 72 / USP 36 / CTA 24).
_OVER = {
    "hook": "H" * 90,
    "subhook": "S" * 100,
    "usp_1": "1" * 140,
    "usp_2": "2" * 99,
    "usp_3": "3" * 73,
    "cta": "C" * 71,
}

# A well-behaved AI response: every field comfortably within its limit.
_SHORT = {
    "hook": "Anak tak tidur lena?",
    "subhook": "Bantu redakan perut kembung bayi",
    "usp_1": "Formula warisan tradisional",
    "usp_2": "Sapu sedikit sahaja",
    "usp_3": "Saiz kecil mudah dibawa",
    "cta": "Dapatkan sekarang",
}


def _req(**overrides) -> PosterCopyFitRequest:
    base = {"language": "ms", **_OVER}
    base.update(overrides)
    return PosterCopyFitRequest(**base)


def test_no_over_limit_never_calls_provider(monkeypatch):
    calls = {"n": 0}

    def _tripwire(*_a, **_k):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(svc.ai_provider, "complete_json", _tripwire)

    res = svc.fit_poster_copy(
        PosterCopyFitRequest(language="ms", hook="Lega segera.", cta="Beli")
    )

    assert res.applied is False
    assert calls["n"] == 0  # no token spend when nothing overflows
    assert res.fields.hook == "Lega segera."


def test_provider_not_configured_fails_closed(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)

    res = svc.fit_poster_copy(_req())

    assert res.applied is False
    assert res.provider_configured is False
    assert res.warnings
    # Original copy is preserved untouched, and the overflow is still reported.
    assert res.fields.hook == _OVER["hook"]
    assert any(s.startswith("Hook") for s in res.still_over_limit)


def test_condenses_all_over_limit_fields(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(svc.ai_provider, "complete_json", lambda _s, _u: dict(_SHORT))

    res = svc.fit_poster_copy(_req())

    assert res.applied is True
    assert res.still_over_limit == []
    assert len(res.fields.hook) <= 48
    assert len(res.fields.cta) <= 24
    assert "Hook" in res.changed_fields
    assert "CTA" in res.changed_fields


def test_ai_line_still_too_long_keeps_original_and_flags(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    # AI shortens everything except hook (returns a still-too-long hook).
    bad = dict(_SHORT)
    bad["hook"] = "H" * 90
    monkeypatch.setattr(svc.ai_provider, "complete_json", lambda _s, _u: bad)

    res = svc.fit_poster_copy(_req())

    # Hook candidate rejected -> original kept -> still flagged as over-limit.
    assert res.fields.hook == _OVER["hook"]
    assert any(s.startswith("Hook") for s in res.still_over_limit)
    assert "Hook" not in res.changed_fields
    # The valid ones were applied.
    assert res.fields.subhook == _SHORT["subhook"]
    assert "Subhook" in res.changed_fields


def test_unsafe_ai_output_discarded_whole(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    unsafe = dict(_SHORT)
    unsafe["hook"] = "Ubat sakit perut"  # "ubat" is an UNSAFE_CLAIM_TERM
    monkeypatch.setattr(svc.ai_provider, "complete_json", lambda _s, _u: unsafe)

    res = svc.fit_poster_copy(_req())

    assert res.applied is False
    # Entire AI output discarded — none of it applied, original copy intact.
    assert res.fields.hook == _OVER["hook"]
    assert res.fields.subhook == _OVER["subhook"]
    assert any("tidak selamat" in w for w in res.warnings)


def test_provider_error_fails_closed(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)

    def _boom(_s, _u):
        raise svc.ai_provider.AICopyProviderError("AI_COPY_ASSIST_CALL_FAILED")

    monkeypatch.setattr(svc.ai_provider, "complete_json", _boom)

    res = svc.fit_poster_copy(_req())

    assert res.applied is False
    assert res.provider_configured is True
    assert res.fields.hook == _OVER["hook"]
    assert res.warnings


def test_only_over_limit_fields_are_condensed(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    seen = {}

    def _capture(_system, user):
        seen["user"] = user
        return dict(_SHORT)

    monkeypatch.setattr(svc.ai_provider, "complete_json", _capture)

    # hook over limit; cta within limit.
    res = svc.fit_poster_copy(
        PosterCopyFitRequest(language="ms", hook="H" * 90, cta="Beli sekarang")
    )

    assert res.applied is True
    # The within-limit CTA is left exactly as the operator wrote it.
    assert res.fields.cta == "Beli sekarang"
    assert "CTA" not in res.changed_fields
    # The prompt only asked the AI to rewrite the over-limit hook.
    assert '"hook"' in seen["user"]
    assert '"cta"' not in seen["user"]
