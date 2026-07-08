"""AI Caption Assist — grounded, reviewable social-caption candidate generator.

The provider adapter seam (complete_json) is ALWAYS mocked — no network, no key.
Proves: grounding is wired, the claim-safe gate FLAGS (never hides) unsafe copy,
an artifact media_id resolves the product, candidate_count is capped, and the
lane fails closed when unconfigured. This is a SUGGESTION generator — it never
persists a package and never approves anything.
"""
import pytest

from agent.db import crud
from agent.services import ai_caption_assist_service as svc
from agent.services import ai_copy_provider_adapter as provider
from agent.services import social_copy_package_service as scp

SAFE = {
    "caption": "Rutin harian yang senang — sekali guna, terus selesa.",
    "first_comment": "Simpan post ni untuk rujukan ya.",
    "hashtags": ["fyp", "rutinharian"],
    "call_to_action": "Tap keranjang kuning",
    "tone": "punchy",
    "rationale": "Angle rutin harian dari avatar.",
    "risk_notes": [],
}

UNSAFE = {**SAFE, "caption": "Dijamin cure penyakit anda, 100% berkesan ubat."}


def _mock(monkeypatch, value):
    def fake(system, user):
        if isinstance(value, Exception):
            raise value
        return dict(value)

    monkeypatch.setattr(provider, "complete_json", fake)


async def _make_product(**kw) -> str:
    product = await crud.create_product(
        raw_product_title=kw.pop("raw_product_title", "AI Caption Serum"),
        source="MANUAL",
        **kw,
    )
    return product["id"]


async def test_not_configured_fails_closed(monkeypatch):
    _mock(monkeypatch, provider.AICopyProviderNotConfigured(provider.ERR_NOT_CONFIGURED))
    with pytest.raises(provider.AICopyProviderNotConfigured):
        await svc.generate_caption_candidates({"platform": "tiktok"})


async def test_unsupported_platform_raises():
    with pytest.raises(scp.SocialCopyError):
        await svc.generate_caption_candidates({"platform": "linkedin"})


async def test_returns_normalized_safe_candidate(monkeypatch):
    _mock(monkeypatch, SAFE)
    out = await svc.generate_caption_candidates({"platform": "tiktok"})
    assert len(out["candidates"]) == 1
    c = out["candidates"][0]
    assert c["caption"]
    assert c["hashtags"] == ["#fyp", "#rutinharian"]  # normalized with '#'
    assert c["compliance_status"] == "OK"
    assert c["blockers"] == []
    assert out["provider"]["lane"] == "text_assist"


async def test_unsafe_candidate_is_flagged_not_hidden(monkeypatch):
    _mock(monkeypatch, UNSAFE)
    out = await svc.generate_caption_candidates({"platform": "tiktok"})
    c = out["candidates"][0]
    assert c["compliance_status"] == "BLOCKED"
    assert any("UNSAFE_LANGUAGE" in b for b in c["blockers"])


async def test_grounds_from_media_id(monkeypatch):
    pid = await _make_product()
    await crud.insert_generation_result(
        "cap-media-1", mode="T2V", artifact_kind="video",
        product_id=pid, product_name="AI Caption Serum",
        final_prompt_text="a calm morning routine, product held in hand")
    _mock(monkeypatch, SAFE)
    out = await svc.generate_caption_candidates(
        {"platform": "tiktok", "artifact_media_id": "cap-media-1"})
    assert out["grounding"]["product_name"] == "AI Caption Serum"
    assert out["candidates"][0]["caption"]


async def test_candidate_count_is_capped(monkeypatch):
    _mock(monkeypatch, SAFE)
    out = await svc.generate_caption_candidates(
        {"platform": "instagram", "candidate_count": 9})  # capped to 3
    assert len(out["candidates"]) == 3
