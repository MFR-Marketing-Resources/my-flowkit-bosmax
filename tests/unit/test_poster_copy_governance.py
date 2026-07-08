"""Phase D — Poster Builder copywriting governance.

Covers: (1) the recommender PREFERS a formula-validated approved Copy Set over
drafts/AI/fallback (never truncated behind them) + surfaces formula_validated;
(2) the prompt-draft never silently uses ungrounded copy — non-approved copy is
review-only (PREVIEW_ONLY + warning + production blocked) unless fallback is
explicitly confirmed. No Google Flow / queue / prompt-compiler / DB migration.
"""
import json

import pytest

from agent.models.poster_copy_recommendations import (
    PosterCopyRecommendationRequest,
    PosterKitSource,
)
from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services.poster_copy_recommendation_service import (
    PosterCopyRecommendationService,
)
from agent.services.poster_prompt_draft_service import PosterPromptDraftService
from tests.unit.test_poster_copy_recommendation_service import _readiness
from tests.unit.test_poster_readiness_service import _ready_base


def _row(cid: str, status: str, hook: str, *, formula_valid: bool | None = None) -> dict:
    row = {
        "id": cid,
        "copy_set_id": cid,
        "product_id": "prod-ready-001",
        "status": status,
        "angle": f"Angle {cid}",
        "hook": hook,
        "subhook": "Saiz mudah bawa",
        "usp_set_json": json.dumps(["Botol 25ml", "Jimat", "Pilihan keluarga"]),
        "cta": "Beli sekarang",
        "archived": 0,
    }
    if formula_valid is not None:
        row["claim_review_json"] = json.dumps(
            {"formula_validation": {"valid": formula_valid, "review_required": not formula_valid}}
        )
    return row


def _recommend_env(monkeypatch, product, rows):
    async def fake_get(_pid):
        return product

    async def fake_list(_pid):
        return rows

    async def fake_eval(_product, enrich=False):
        return _readiness()

    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.get_product", fake_get
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.list_copy_sets_for_product",
        fake_list,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.PosterReadinessService.evaluate_product",
        fake_eval,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.ai_provider.is_configured",
        lambda: False,
    )


@pytest.mark.asyncio
async def test_approved_copy_set_is_preferred_and_never_truncated(monkeypatch):
    product = _ready_base()
    # 5 draft rows FIRST, then the approved set LAST — in DB order the approved kit
    # would be the 6th appended and truncated by MAX_KITS. The trust sort must rescue it.
    rows = [_row(f"draft-{i}", "COPY_REVIEW_REQUIRED", f"Hook draf {i}") for i in range(5)]
    rows.append(_row("approved-1", "COPY_APPROVED", "Hook diluluskan", formula_valid=True))
    _recommend_env(monkeypatch, product, rows)

    result = await PosterCopyRecommendationService.recommend(
        PosterCopyRecommendationRequest(product_id=product["id"])
    )
    assert result.recommendation_source == PosterKitSource.APPROVED_COPY_SET
    # The approved kit survives truncation AND is ranked first.
    assert result.recommendations[0].source == PosterKitSource.APPROVED_COPY_SET
    assert result.recommendations[0].copy_set_id == "approved-1"
    assert result.recommendations[0].formula_validated is True
    # Drafts are never marked formula-validated.
    assert all(
        not k.formula_validated
        for k in result.recommendations
        if k.source != PosterKitSource.APPROVED_COPY_SET
    )


@pytest.mark.asyncio
async def test_approved_without_valid_formula_is_not_marked_validated(monkeypatch):
    product = _ready_base()
    rows = [_row("approved-x", "COPY_APPROVED", "Hook diluluskan", formula_valid=False)]
    _recommend_env(monkeypatch, product, rows)

    result = await PosterCopyRecommendationService.recommend(
        PosterCopyRecommendationRequest(product_id=product["id"])
    )
    approved = [k for k in result.recommendations if k.source == PosterKitSource.APPROVED_COPY_SET]
    assert approved and approved[0].formula_validated is False


# ── Prompt-draft ungrounded-copy governance ──────────────────────────────────
def _draft_request(**overrides) -> PosterPromptDraftRequest:
    base = {
        "product_id": "prod-ready-001",
        "poster_objective": "Drive awareness",
        "poster_type": "Product hero",
        "visual_route": "Studio product on heritage backdrop",
        "human_presence_mode": "none",
        "frame_ratio": "9:16",
        "language": "ms",
        "text_density": "medium",
        "angle": "Heritage trust",
        "hook": "Warisan sejak dulu",
        "subhook": "Saiz mudah bawa",
        "usp_1": "Botol 25ml",
        "usp_2": "Jimat",
        "usp_3": "Pilihan keluarga",
        "cta": "Beli sekarang",
        "operator_notes": "",
    }
    base.update(overrides)
    return PosterPromptDraftRequest(**base)


def _draft_env(monkeypatch, product):
    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product", fake_get
    )


@pytest.mark.asyncio
async def test_approved_copy_source_stays_production_ready(monkeypatch):
    _draft_env(monkeypatch, _ready_base())
    result = await PosterPromptDraftService.build_draft(
        _draft_request(copy_source="APPROVED_COPY_SET", copy_set_id="cs-1")
    )
    assert result.prompt_package_status == "DRAFT_READY"
    assert result.production_allowed is True
    assert "UNGROUNDED_COPY_REVIEW_ONLY" not in result.validation_warnings


@pytest.mark.asyncio
async def test_ungrounded_copy_is_review_only(monkeypatch):
    _draft_env(monkeypatch, _ready_base())
    for source in ("FALLBACK_TEMPLATE", "AI_CANDIDATE", "manual", "DRAFT_COPY_SET"):
        result = await PosterPromptDraftService.build_draft(
            _draft_request(copy_source=source)
        )
        assert result.prompt_package_status == "PREVIEW_ONLY", source
        assert result.production_allowed is False, source
        assert "UNGROUNDED_COPY_REVIEW_ONLY" in result.validation_warnings, source


@pytest.mark.asyncio
async def test_explicit_fallback_confirmation_lifts_review_only(monkeypatch):
    _draft_env(monkeypatch, _ready_base())
    result = await PosterPromptDraftService.build_draft(
        _draft_request(copy_source="AI_CANDIDATE", copy_fallback_confirmed=True)
    )
    assert result.prompt_package_status == "DRAFT_READY"
    assert "UNGROUNDED_COPY_REVIEW_ONLY" not in result.validation_warnings


@pytest.mark.asyncio
async def test_legacy_request_without_copy_source_is_unchanged(monkeypatch):
    _draft_env(monkeypatch, _ready_base())
    result = await PosterPromptDraftService.build_draft(_draft_request())
    # No provenance declared → prior behavior preserved (no forced downgrade).
    # (Poster copy quality WARN findings may appear now, but the governance
    # downgrade warning must NOT — that is the intent of this test.)
    assert result.prompt_package_status == "DRAFT_READY"
    assert "UNGROUNDED_COPY_REVIEW_ONLY" not in result.validation_warnings
