"""AI Caption Assist API — grounded caption candidates endpoint.

Exercises the route handler directly (no HTTP server), the same way
tests/api/test_social_copy_api.py does. The provider adapter is mocked; the
endpoint fails closed (409) when the lane is unconfigured and maps provider
errors to 502 and unsupported platforms to 422.
"""
import pytest
from fastapi import HTTPException

from agent.api import social_copy_packages as api
from agent.services import ai_copy_provider_adapter as provider

SAFE = {
    "caption": "Rutin senang, hasil selesa.",
    "first_comment": "",
    "hashtags": ["fyp"],
    "call_to_action": "Tap link",
    "tone": "punchy",
    "rationale": "ok",
    "risk_notes": [],
}


async def test_ai_assist_returns_candidates(monkeypatch):
    monkeypatch.setattr(provider, "complete_json", lambda s, u: dict(SAFE))
    resp = await api.ai_assist(api.AICaptionAssistRequest(platform="tiktok"))
    assert resp["candidates"][0]["caption"] == "Rutin senang, hasil selesa."
    assert resp["candidates"][0]["hashtags"] == ["#fyp"]
    assert resp["provider"]["lane"] == "text_assist"


async def test_ai_assist_not_configured_returns_409(monkeypatch):
    def raise_nc(system, user):
        raise provider.AICopyProviderNotConfigured(provider.ERR_NOT_CONFIGURED)

    monkeypatch.setattr(provider, "complete_json", raise_nc)
    with pytest.raises(HTTPException) as exc:
        await api.ai_assist(api.AICaptionAssistRequest(platform="tiktok"))
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == provider.ERR_NOT_CONFIGURED


async def test_ai_assist_provider_error_returns_502(monkeypatch):
    def raise_err(system, user):
        raise provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID, detail="bad")

    monkeypatch.setattr(provider, "complete_json", raise_err)
    with pytest.raises(HTTPException) as exc:
        await api.ai_assist(api.AICaptionAssistRequest(platform="tiktok"))
    assert exc.value.status_code == 502


async def test_ai_assist_unsupported_platform_422(monkeypatch):
    monkeypatch.setattr(provider, "complete_json", lambda s, u: dict(SAFE))
    with pytest.raises(HTTPException) as exc:
        await api.ai_assist(api.AICaptionAssistRequest(platform="linkedin"))
    assert exc.value.status_code == 422
