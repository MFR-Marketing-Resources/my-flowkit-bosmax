"""Clean-scene generation contract + poster copy set consumption in
build_draft (POSTER_BUILDER_V2).

The recipe path must produce a CLEAN scene prompt (compositor owns marketing
text); the legacy no-recipe path stays byte-compatible (diffusion text kept).
"""
import pytest

from agent.db import crud
from agent.models.poster_copy_set import (
    POSTER_COPY_APPROVAL_PHRASE,
    PosterCopySetCreateRequest,
)
from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services.poster_copy_set_service import PosterCopySetService
from agent.services.poster_prompt_draft_service import (
    PosterPromptDraftService,
    PosterPromptDraftValidationError,
)
from tests.unit.test_poster_readiness_service import _ready_base


def _request(**overrides) -> PosterPromptDraftRequest:
    base = {
        "product_id": "prod-ready-001",
        "poster_objective": "Drive awareness",
        "poster_type": "Product hero",
        "visual_route": "Studio product",
        "human_presence_mode": "none",
        "frame_ratio": "9:16",
        "language": "ms",
        "text_density": "medium",
        "hook": "Warisan sejak dulu",
        "subhook": "Saiz mudah bawa",
        "usp_1": "Saiz poket",
        "usp_2": "Jimat",
        "usp_3": "",
        "cta": "Beli sekarang",
        "operator_notes": "",
    }
    base.update(overrides)
    return PosterPromptDraftRequest(**base)


def _patch_product(monkeypatch, product=None):
    product = product or _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product", fake_get
    )


@pytest.mark.asyncio
async def test_recipe_path_emits_clean_scene_prompt(monkeypatch):
    _patch_product(monkeypatch)
    result = await PosterPromptDraftService.build_draft(
        _request(poster_recipe_id="product_hero_night_routine")
    )
    # Clean-scene contract: compositor owns marketing text.
    assert "CLEAN SCENE MODE" in result.poster_prompt
    assert "PRESERVE the real product label" in result.poster_prompt
    # The old diffusion text-hierarchy instruction must be GONE on this path.
    assert "hook largest" not in result.poster_prompt
    # Negative prompt suppresses marketing typography, not the product label.
    assert "marketing headline text" in result.negative_prompt
    assert "poster typography overlay" in result.negative_prompt
    # Product region from the template contract appears in the instruction.
    assert "product region" in result.poster_prompt


@pytest.mark.asyncio
async def test_legacy_path_unchanged_diffusion_text_retained(monkeypatch):
    _patch_product(monkeypatch)
    result = await PosterPromptDraftService.build_draft(_request())
    assert "CLEAN SCENE MODE" not in result.poster_prompt
    assert "hook largest" in result.poster_prompt  # legacy overlay instruction
    assert "marketing headline text" not in result.negative_prompt


@pytest.mark.asyncio
async def test_build_draft_consumes_approved_poster_copy_set(monkeypatch):
    product = _ready_base()
    row = await crud.create_product(
        "Minyak Warisan Tok 25ml", source="MANUAL",
        product_display_name="Minyak Warisan Tok", category="Traditional",
    )
    pid = row["id"]
    product["id"] = pid

    _patch_product(monkeypatch, product)
    pcs = await PosterCopySetService.create_draft(
        PosterCopySetCreateRequest(
            product_id=pid,
            archetype="PRODUCT_HERO",
            angle="Premium hero",
            primary_message="Minyak warisan keluarga",
            support_message="Sedia bila anda perlukan.",
            proof_points=["Saiz poket"],
            cta="Dapatkan sekarang",
            language="ms",
        )
    )
    approved = await PosterCopySetService.approve(
        pcs["poster_copy_set_id"],
        approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
        approved_by="op",
    )
    result = await PosterPromptDraftService.build_draft(
        _request(
            product_id=pid,
            hook="", subhook="", usp_1="", usp_2="", cta="",  # projected instead
            poster_recipe_id="product_hero_night_routine",
            poster_copy_set_id=approved["poster_copy_set_id"],
        )
    )
    # Projection: the poster copy set fields drive the zone copy.
    assert result.copy_layout.hook == "Minyak warisan keluarga"
    assert result.copy_layout.cta == "Dapatkan sekarang"
    # Approved poster copy is production-eligible (no ungrounded downgrade).
    assert "UNGROUNDED_COPY_REVIEW_ONLY" not in (result.validation_warnings or [])
    assert result.production_allowed is True


@pytest.mark.asyncio
async def test_draft_poster_copy_set_is_review_only(monkeypatch):
    product = _ready_base()
    row = await crud.create_product(
        "Minyak Warisan Tok 25ml", source="MANUAL",
        product_display_name="Minyak Warisan Tok", category="Traditional",
    )
    pid = row["id"]
    product["id"] = pid
    _patch_product(monkeypatch, product)
    pcs = await PosterCopySetService.create_draft(
        PosterCopySetCreateRequest(
            product_id=pid,
            archetype="PRODUCT_HERO",
            primary_message="Minyak warisan keluarga",
            cta="Beli sekarang",
            language="ms",
        )
    )
    result = await PosterPromptDraftService.build_draft(
        _request(
            product_id=pid,
            poster_recipe_id="product_hero_night_routine",
            poster_copy_set_id=pcs["poster_copy_set_id"],
        )
    )
    assert "UNGROUNDED_COPY_REVIEW_ONLY" in result.validation_warnings
    assert result.production_allowed is False


@pytest.mark.asyncio
async def test_unknown_poster_copy_set_fails_closed(monkeypatch):
    _patch_product(monkeypatch)
    with pytest.raises(PosterPromptDraftValidationError):
        await PosterPromptDraftService.build_draft(
            _request(poster_copy_set_id="nope-123")
        )


@pytest.mark.asyncio
async def test_offer_archetype_blocks_price_claims(monkeypatch):
    _patch_product(monkeypatch)
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _request(
                poster_recipe_id="offer_promo",
                hook="Jimat RM10 hari ini",
                subhook="", usp_3="",
            )
        )
    assert any("OFFER_PRICE_CLAIM_UNSUPPORTED" in e for e in exc.value.field_errors)
