"""Unit tests for copy_grounding_service — two-tier grounding (approved snapshot →
framework family → minimal). Provider is never called; no token spend."""
from types import SimpleNamespace

import pytest

from agent.models.copy_grounding import (
    GROUNDING_APPROVED_SNAPSHOT,
    GROUNDING_FRAMEWORK_FAMILY,
    GROUNDING_MINIMAL,
)
from agent.services import copy_grounding_service as cg


def _stealth_product() -> dict:
    return {
        "id": "p1",
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
    }


def _direct_product() -> dict:
    return {
        "id": "p2",
        "product_display_name": "Storage Box 2L",
        "raw_product_title": "Storage Box 2L",
        "category": "Home",
        "subcategory": "Organization",
        "type": "Storage",
    }


def test_framework_tier_stealth_grounds_avatar_and_angles():
    g = cg.build_framework_grounding(_stealth_product())
    assert g.source == GROUNDING_FRAMEWORK_FAMILY
    assert g.grounded is True
    assert g.family == "MALE_HEALTH_SENSITIVE"
    assert g.is_stealth is True
    assert g.effective_route == "STEALTH"
    assert g.buyer_persona.audience  # real avatar
    assert "ego" in g.buyer_persona.triggers
    assert len(g.angle_strategies) >= 3
    assert len(set(g.angle_strategies)) == len(g.angle_strategies)  # distinct
    assert g.claim_guardrails.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert "zakar" in g.claim_guardrails.banned_terms
    # framework tier NEVER invents product facts
    assert g.product_knowledge.benefits == []
    assert g.product_knowledge.usps == []
    assert g.missing  # guides the operator to author a snapshot


def test_framework_tier_direct_is_not_stealth():
    g = cg.build_framework_grounding(_direct_product())
    assert g.is_stealth is False
    assert g.effective_route != "STEALTH"
    assert g.source in (GROUNDING_FRAMEWORK_FAMILY, GROUNDING_MINIMAL)


@pytest.mark.asyncio
async def test_approved_snapshot_tier_uses_real_knowledge(monkeypatch):
    snap = SimpleNamespace(
        product_description="Minyak herba dalam botol 5ml.",
        benefits_json=["mudah dibawa", "diskret"],
        usp_json=["format kompak", "tutup mudah dikenali"],
        ingredients_text="Herba campuran.",
        usage_text="",
        warnings_text="",
        target_customer_text="Lelaki dewasa yang jaga keyakinan diri.",
        buyer_persona_snapshot_json={
            "audience": "Lelaki 30-50",
            "desires": ["yakin semula"],
            "objections": ["selamat ke?"],
        },
        copy_strategy_summary_json={"angles": ["ego_recovery", "compact_standby"]},
        allowed_claims_json=["mudah dibawa"],
        blocked_claims_json=["cure", "guaranteed"],
        claim_gate="CLAIM_REVIEW_REQUIRED",
        claim_risk_level="HIGH",
    )

    async def fake_latest(_pid):
        return snap

    monkeypatch.setattr(
        "agent.services.product_intelligence_snapshot_service.get_latest_approved_snapshot",
        fake_latest,
    )

    g = await cg.resolve_copy_grounding(_stealth_product())
    assert g.source == GROUNDING_APPROVED_SNAPSHOT
    assert g.grounded is True
    # real product knowledge crosses (from the approved snapshot)
    assert g.product_knowledge.benefits == ["mudah dibawa", "diskret"]
    assert g.product_knowledge.usps
    # persona: snapshot keys win, framework fills the gaps (triggers)
    assert g.buyer_persona.audience == "Lelaki 30-50"
    assert "yakin semula" in g.buyer_persona.desires
    assert "ego" in g.buyer_persona.triggers  # framework fallback
    # angles come from the strategy json
    assert g.angle_strategies == ["ego_recovery", "compact_standby"]
    assert "cure" in g.claim_guardrails.blocked_claims
    assert "cure" in g.claim_guardrails.banned_terms


@pytest.mark.asyncio
async def test_resolve_falls_back_to_framework_when_no_snapshot(monkeypatch):
    async def fake_none(_pid):
        return None

    monkeypatch.setattr(
        "agent.services.product_intelligence_snapshot_service.get_latest_approved_snapshot",
        fake_none,
    )
    g = await cg.resolve_copy_grounding(_stealth_product())
    assert g.source == GROUNDING_FRAMEWORK_FAMILY
    assert g.is_stealth is True
    assert g.buyer_persona.audience
