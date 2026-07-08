import pytest

from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.models.poster_readiness import PosterReadinessStatus
from agent.services.poster_prompt_draft_service import (
    PosterPromptDraftService,
    PosterPromptDraftValidationError,
)
from tests.unit.test_poster_readiness_service import _ready_base


def _full_request(**overrides) -> PosterPromptDraftRequest:
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


@pytest.mark.asyncio
async def test_ready_product_draft_ready(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.prompt_package_status == "DRAFT_READY"
    assert result.poster_prompt
    assert "PRODUCT TRUTH LOCK" in result.poster_prompt
    assert result.production_allowed is True
    assert result.negative_prompt


@pytest.mark.asyncio
async def test_poster_prompt_no_longer_requires_or_renders_angle(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    # Angle removed from the poster copy model: no angle supplied, still DRAFT_READY,
    # and the assembled prompt no longer carries an "Angle:" line.
    result = await PosterPromptDraftService.build_draft(_full_request(angle=""))
    assert result.prompt_package_status == "DRAFT_READY"
    assert "Angle:" not in result.poster_prompt
    assert "Hook:" in result.poster_prompt


@pytest.mark.asyncio
async def test_poster_copy_length_limit_rejects_long_hook(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    # Poster copy must be short — an over-length hook is rejected with a clear error.
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(_full_request(hook="x" * 80))
    assert any("too long" in err for err in exc.value.field_errors)


@pytest.mark.asyncio
async def test_restricted_draft_includes_safety_rules(monkeypatch):
    product = _ready_base(
        claim_risk_level="MEDIUM",
        production_prompt_approval_note="Approved RESTRICTED_SAFE_POSTER route",
    )

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.restricted_mode is True
    assert result.prompt_package_status == "DRAFT_READY"
    assert any("No cure" in g for g in result.safety_guardrails)
    assert "RESTRICTED-SAFE MODE" in result.poster_prompt


@pytest.mark.asyncio
async def test_repair_required_no_final_prompt(monkeypatch):
    product = _ready_base(claim_risk_level="HIGH")

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.prompt_package_status == "REPAIR_REQUIRED"
    assert result.poster_prompt == ""
    assert "CLAIM_RISK_HIGH" in result.blocked_reasons
    assert result.repair_actions


@pytest.mark.asyncio
async def test_blocked_hard_stop(monkeypatch):
    product = _ready_base(lifecycle_status="ARCHIVED")

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.prompt_package_status == "BLOCKED"
    assert not result.poster_prompt


@pytest.mark.asyncio
async def test_restricted_unsafe_terms_rejected(monkeypatch):
    product = _ready_base(
        claim_risk_level="MEDIUM",
        production_prompt_approval_note="Approved RESTRICTED_SAFE_POSTER route",
    )

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(hook="Ubat sakit hilang serta merta"),
        )
    assert any("Unsafe term" in e for e in exc.value.field_errors)
    assert "restricted-safe" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_ready_unsafe_hook_rejected(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(hook="This will cure your pain"),
        )
    assert "Unsafe or unapproved claim wording detected" in str(exc.value)
    assert any("cure" in e for e in exc.value.field_errors)


@pytest.mark.asyncio
async def test_ready_unsafe_usp_cta_rejected(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(usp_2="Guaranteed relief today", cta="Beli ubat sekarang"),
        )
    assert "Unsafe or unapproved claim wording detected" in str(exc.value)


@pytest.mark.asyncio
async def test_preview_only_unsafe_term_rejected(monkeypatch):
    product = _ready_base(
        local_image_path="",
        image_url="https://cdn.example.com/p.jpg",
        asset_status="",
        image_asset_status="",
        image_readiness_status="",
    )

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(operator_notes="Diagnostic only but claims sembuh"),
        )
    assert "Unsafe or unapproved claim wording detected" in str(exc.value)


@pytest.mark.asyncio
async def test_ready_safe_copy_still_draft_ready(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.poster_status == PosterReadinessStatus.POSTER_READY.value
    assert result.prompt_package_status == "DRAFT_READY"
    assert result.poster_prompt


@pytest.mark.asyncio
async def test_missing_critical_fields_validation(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    with pytest.raises(PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(poster_objective="", hook=""),
        )
    assert exc.value.field_errors


@pytest.mark.asyncio
async def test_preview_only_package_status(monkeypatch):
    product = _ready_base(
        local_image_path="",
        image_url="https://cdn.example.com/p.jpg",
        asset_status="",
        image_asset_status="",
        image_readiness_status="",
    )

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product",
        fake_get,
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.poster_status == PosterReadinessStatus.POSTER_PREVIEW_ONLY.value
    assert result.prompt_package_status == "PREVIEW_ONLY"
    assert result.poster_prompt
    assert result.production_allowed is False