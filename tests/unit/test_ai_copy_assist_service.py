"""Unit tests for AI Copy Assist V1 (candidate Copy Set generator).

The provider adapter is ALWAYS mocked here — no network, no real key. Proves the
candidate obeys the existing Copy Set lifecycle: review-required (never approved),
claim-risk enforced, dedupe enforced, binds only after approval, and the provider
raw response/provenance never crosses into compiler copy.
"""
import json

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.services import ai_copy_assist_service as ai
from agent.services import ai_copy_provider_adapter as provider
from agent.services import copy_set_service as copy_svc
from agent.services import copy_binding_service as binding


SAFE_AI = {
    "angle": "Segar sepanjang hari",
    "hook": "Nak rutin kulit nampak segar sepanjang hari?",
    "subhook": "Rutin ringkas tanpa leceh",
    "usp_set": ["Sesuai untuk rutin harian", "Mudah digunakan", "Formula ringan"],
    "cta": "Cuba masukkan dalam rutin kau hari ni.",
    "formula_family": "HSO",
    "rationale": "Angle harian + hook soalan langsung.",
    "risk_notes": [],
}

UNSAFE_AI = {
    **SAFE_AI,
    "cta": "Dijamin cure your skin, guaranteed 100% berkesan",
}


async def _make_product(**kw) -> str:
    product = await crud.create_product(
        raw_product_title=kw.pop("raw_product_title", "AI Assist Serum 5ML"),
        source="MANUAL",
        **kw,
    )
    return product["id"]


def _mock_provider(monkeypatch, value):
    def fake(brief):
        if isinstance(value, Exception):
            raise value
        return dict(value)

    monkeypatch.setattr(provider, "generate_candidate", fake)


@pytest.mark.asyncio
async def test_provider_not_configured_fails_closed(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, provider.AICopyProviderNotConfigured(provider.ERR_NOT_CONFIGURED))
    with pytest.raises(provider.AICopyProviderNotConfigured) as exc:
        await ai.generate_ai_copy_candidate({"product_id": pid})
    assert exc.value.code == "AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_product_not_found_fails_closed(monkeypatch):
    _mock_provider(monkeypatch, SAFE_AI)
    with pytest.raises(copy_svc.CopySetError) as exc:
        await ai.generate_ai_copy_candidate({"product_id": "missing"})
    assert exc.value.code == "PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_valid_candidate_is_review_required_not_approved(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, SAFE_AI)
    result = await ai.generate_ai_copy_candidate({"product_id": pid})

    assert len(result["candidates"]) == 1
    cand = result["candidates"][0]
    cs = cand["copy_set"]
    assert cand["created"] is True
    assert cs["status"] == models.STATUS_COPY_REVIEW_REQUIRED
    assert cs["status"] != models.STATUS_COPY_APPROVED
    assert cs["source"] == models.SOURCE_AI_COPY_ASSIST
    assert cs["hook"] == SAFE_AI["hook"]
    assert cand["safety"]["safe"] is True


@pytest.mark.asyncio
async def test_candidate_can_be_approved_only_via_existing_gate(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, SAFE_AI)
    cs = (await ai.generate_ai_copy_candidate({"product_id": pid}))["candidates"][0]["copy_set"]

    # Wrong phrase is rejected by the SAME approval gate.
    with pytest.raises(copy_svc.CopySetPermissionError):
        await copy_svc.approve_copy_set(cs["copy_set_id"], {"approval_phrase": "WRONG"})

    approved = await copy_svc.approve_copy_set(
        cs["copy_set_id"], {"approval_phrase": models.APPROVAL_PHRASE, "approved_by": "operator"}
    )
    assert approved["status"] == models.STATUS_COPY_APPROVED


@pytest.mark.asyncio
async def test_unsafe_candidate_is_review_required_and_cannot_approve(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, UNSAFE_AI)
    cand = (await ai.generate_ai_copy_candidate({"product_id": pid}))["candidates"][0]

    cs = cand["copy_set"]
    assert cs["status"] == models.STATUS_COPY_REVIEW_REQUIRED
    assert cs["status"] != models.STATUS_COPY_APPROVED
    assert cand["safety"]["safe"] is False
    assert cand["warnings"]  # violation codes surfaced
    # Claim-risk QA is NOT bypassed: approval fails closed on the unsafe copy.
    with pytest.raises(copy_svc.CopySetError) as exc:
        await copy_svc.approve_copy_set(
            cs["copy_set_id"], {"approval_phrase": models.APPROVAL_PHRASE}
        )
    assert exc.value.code == "COPY_SET_UNSAFE"


@pytest.mark.asyncio
async def test_duplicate_candidate_reuses_existing(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, SAFE_AI)
    first = (await ai.generate_ai_copy_candidate({"product_id": pid}))["candidates"][0]
    second = (await ai.generate_ai_copy_candidate({"product_id": pid}))["candidates"][0]

    assert first["created"] is True
    assert second["created"] is False
    assert second["dedupe_match"] is True
    assert second["copy_set"]["copy_set_id"] == first["copy_set"]["copy_set_id"]


@pytest.mark.asyncio
async def test_candidate_binds_only_after_approval(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, SAFE_AI)
    cs = (await ai.generate_ai_copy_candidate({"product_id": pid}))["candidates"][0]["copy_set"]
    csid = cs["copy_set_id"]

    # Review-required AI candidate cannot bind into the compiler.
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid, csid)
    assert exc.value.code == binding.ERR_NOT_APPROVED

    await copy_svc.approve_copy_set(csid, {"approval_phrase": models.APPROVAL_PHRASE})
    bound = await binding.resolve_compiler_copy_intelligence(pid, csid)
    assert bound["lineage"]["copy_binding_status"] == binding.BINDING_BOUND
    assert bound["copy_intelligence"]["hook"] == SAFE_AI["hook"]


@pytest.mark.asyncio
async def test_provenance_never_crosses_into_compiler_copy(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, SAFE_AI)
    cs = (await ai.generate_ai_copy_candidate({"product_id": pid}))["candidates"][0]["copy_set"]

    # Provenance is stored internally (source/provider/rationale) ...
    assert cs["provenance"]["source"] == models.SOURCE_AI_COPY_ASSIST
    # ... but to_compiler_copy exposes ONLY clean copy fields.
    compiler_copy = models.to_compiler_copy(cs)
    for forbidden in ("provenance", "source", "provider_id", "rationale", "risk_notes", "status", "copy_set_id"):
        assert forbidden not in compiler_copy


@pytest.mark.asyncio
async def test_invalid_provider_response_fails_closed(monkeypatch):
    pid = await _make_product()
    _mock_provider(monkeypatch, provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID, detail="bad json"))
    with pytest.raises(provider.AICopyProviderError) as exc:
        await ai.generate_ai_copy_candidate({"product_id": pid})
    assert exc.value.code == "AI_COPY_ASSIST_RESPONSE_INVALID"


# ── Product-grounding of the AI brief (Fix 1) ────────────────────────────

def _stealth_product() -> dict:
    return {
        "id": "p-stealth",
        "product_display_name": "Bosmax Herbs 5 ML",
        "raw_product_title": "Bosmax Herbs 5 ML",
        "category": "Health",
        "subcategory": "Supplements",
        "type": "Male Health",
        "product_type": "STEALTH",
        "silo": "health_supp_stealth_01",
        "trigger_id": "EGO_01",
        "formula": "PAS",
        "claim_risk_level": "HIGH",
        "copywriting_angle": "",
    }


def _direct_product() -> dict:
    return {
        "id": "p-direct",
        "product_display_name": "Clean Face Serum 30 ML",
        "raw_product_title": "Clean Face Serum 30 ML",
        "category": "Beauty",
        "subcategory": "Skincare",
        "type": "Facial Serum",
        "product_type": "",
        "silo": "beauty_direct_01",
        "trigger_id": "",
        "formula": "HSO",
        "claim_risk_level": "LOW",
    }


def test_stealth_brief_carries_avatar_and_angle_strategy():
    from agent.services.copy_grounding_service import build_framework_grounding

    product = _stealth_product()
    g = build_framework_grounding(product)
    assert g.is_stealth is True
    assert g.effective_route == "STEALTH"
    assert g.family == "MALE_HEALTH_SENSITIVE"
    assert g.angle_strategies  # distinct strategic angles from the framework

    req = models.AICopyAssistRequest(product_id="p-stealth")  # operator sets no route
    angles = ai._rotation_angles(req, g)
    brief = json.loads(ai._build_brief(req, product, g, angles[0]))
    assert brief["sensitivity"] == "STEALTH"
    assert brief["route_type"] == "STEALTH"
    assert brief["family"] == "MALE_HEALTH_SENSITIVE"
    assert brief["avatar_audience"]  # the customer avatar is grounded
    assert "ego" in brief["avatar_triggers"]
    assert brief["target_angle_strategy"] == angles[0]
    assert brief["available_angle_strategies"]
    assert brief["banned_terms"]  # claim guardrails present
    assert "STEALTH" in brief["strategy"]


def test_direct_product_not_flagged_stealth():
    from agent.services.copy_grounding_service import build_framework_grounding

    product = _direct_product()
    g = build_framework_grounding(product)
    assert g.is_stealth is False

    req = models.AICopyAssistRequest(product_id="p-direct")
    brief = json.loads(ai._build_brief(req, product, g))
    assert brief.get("sensitivity", "") == ""
    assert "strategy" not in brief  # empty stealth strategy is filtered out
    assert brief["route_type"] != "STEALTH"


def test_rotation_angles_are_distinct_and_operator_angle_pins():
    from agent.services.copy_grounding_service import build_framework_grounding

    g = build_framework_grounding(_stealth_product())
    req = models.AICopyAssistRequest(product_id="x")  # no operator angle
    angles = ai._rotation_angles(req, g)
    assert len(angles) >= 3
    assert len(set(angles)) == len(angles)  # each candidate gets a DIFFERENT angle

    # An operator-pinned angle disables rotation (that one angle steers all).
    req_pinned = models.AICopyAssistRequest(product_id="x", angle="my angle")
    assert ai._rotation_angles(req_pinned, g) == []


def test_merge_auto_routes_stealth_only_for_stealth_products():
    from agent.services.copy_grounding_service import build_framework_grounding

    req = models.AICopyAssistRequest(product_id="x")  # no operator route
    stealth_g = build_framework_grounding(_stealth_product())
    direct_g = build_framework_grounding(_direct_product())

    assert ai._merge_candidate_fields(dict(SAFE_AI), req, stealth_g)["route_type"] == "STEALTH"
    assert ai._merge_candidate_fields(dict(SAFE_AI), req, direct_g)["route_type"] == "DIRECT"

    # An explicit operator route always wins over the auto-derived one.
    req_override = models.AICopyAssistRequest(product_id="x", route_type="DIRECT")
    assert (
        ai._merge_candidate_fields(dict(SAFE_AI), req_override, stealth_g)["route_type"]
        == "DIRECT"
    )


def test_provider_system_prompt_is_stealth_and_route_aware():
    system = provider.build_messages("{}")[0]["content"]
    assert "STEALTH" in system
    assert "route_type" in system
    assert "claim_risk_level" in system
    assert "STRICT JSON" in system  # existing contract preserved
