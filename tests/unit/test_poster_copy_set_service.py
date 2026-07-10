"""Poster Copy Set domain — lifecycle, approval gate, versioning, and the
video-copy ISOLATION invariants (POSTER_BUILDER_V2)."""
import pytest

from agent.db import crud
from agent.models.poster_copy_set import (
    POSTER_COPY_APPROVAL_PHRASE,
    STATUS_POSTER_COPY_APPROVED,
    STATUS_POSTER_COPY_DRAFT,
    STATUS_POSTER_COPY_SUPERSEDED,
    PosterCopySetCreateRequest,
    PosterCopySetPatchRequest,
    poster_fields_to_zone_fields,
)
from agent.services.poster_copy_set_service import (
    PosterCopySetError,
    PosterCopySetService,
)


async def _seed_product() -> str:
    row = await crud.create_product(
        "Minyak Warisan Tok 25ml",
        source="MANUAL",
        product_display_name="Minyak Warisan Tok",
        category="Traditional",
    )
    return row["id"]


def _create_request(product_id: str, **overrides) -> PosterCopySetCreateRequest:
    base = {
        "product_id": product_id,
        "objective": "Product introduction",
        "archetype": "PRODUCT_HERO",
        "angle": "Premium product hero",
        "primary_message": "Minyak warisan keluarga",
        "support_message": "Sedia bila anda perlukan.",
        "proof_points": ["Saiz poket", "Mudah dibawa"],
        "cta": "Beli sekarang",
        "tone": "mesra",
        "language": "ms",
    }
    base.update(overrides)
    return PosterCopySetCreateRequest(**base)


@pytest.mark.asyncio
async def test_create_draft_and_serialize_roundtrip():
    pid = await _seed_product()
    out = await PosterCopySetService.create_draft(_create_request(pid))
    assert out["status"] == STATUS_POSTER_COPY_DRAFT
    assert out["proof_points"] == ["Saiz poket", "Mudah dibawa"]
    assert out["version"] == 1
    fetched = await PosterCopySetService.get(out["poster_copy_set_id"])
    assert fetched["primary_message"] == "Minyak warisan keluarga"


@pytest.mark.asyncio
async def test_length_limits_fail_closed():
    pid = await _seed_product()
    with pytest.raises(PosterCopySetError) as exc:
        await PosterCopySetService.create_draft(
            _create_request(pid, primary_message="x" * 60)
        )
    assert exc.value.code == "POSTER_COPY_LENGTH_INVALID"


@pytest.mark.asyncio
async def test_approve_requires_phrase_and_strict_quality_gate():
    pid = await _seed_product()
    out = await PosterCopySetService.create_draft(_create_request(pid))
    with pytest.raises(PosterCopySetError) as exc:
        await PosterCopySetService.approve(
            out["poster_copy_set_id"], approval_phrase="yes", approved_by="op"
        )
    assert exc.value.code == "POSTER_COPY_APPROVAL_PHRASE_INVALID"

    # Medical wording is captured at draft as warnings but BLOCKS approval.
    bad = await PosterCopySetService.create_draft(
        _create_request(pid, primary_message="Legakan sakit segera")
    )
    with pytest.raises(PosterCopySetError) as exc:
        await PosterCopySetService.approve(
            bad["poster_copy_set_id"],
            approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
            approved_by="op",
        )
    assert exc.value.code == "POSTER_COPY_QUALITY_BLOCKED"

    approved = await PosterCopySetService.approve(
        out["poster_copy_set_id"],
        approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
        approved_by="op",
    )
    assert approved["status"] == STATUS_POSTER_COPY_APPROVED
    assert approved["approved_at"]
    assert approved["approved_by"] == "op"


@pytest.mark.asyncio
async def test_approved_is_immutable_and_versioning_supersedes():
    pid = await _seed_product()
    out = await PosterCopySetService.create_draft(_create_request(pid))
    await PosterCopySetService.approve(
        out["poster_copy_set_id"],
        approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
        approved_by="op",
    )
    with pytest.raises(PosterCopySetError) as exc:
        await PosterCopySetService.patch_draft(
            out["poster_copy_set_id"],
            PosterCopySetPatchRequest(primary_message="Edited"),
        )
    assert exc.value.code == "POSTER_COPY_SET_NOT_EDITABLE"

    child = await PosterCopySetService.new_version(
        out["poster_copy_set_id"],
        PosterCopySetPatchRequest(primary_message="Versi baharu poster"),
    )
    assert child["version"] == 2
    assert child["parent_poster_copy_set_id"] == out["poster_copy_set_id"]
    assert child["status"] == STATUS_POSTER_COPY_DRAFT
    parent = await PosterCopySetService.get(out["poster_copy_set_id"])
    assert parent["status"] == STATUS_POSTER_COPY_SUPERSEDED
    # Operator edit provenance stamped on the changed field.
    assert child["field_provenance"].get("primary_message") == "OPERATOR_EDIT"


@pytest.mark.asyncio
async def test_video_copy_isolation_invariants():
    """Poster copy NEVER enters the video copy_set namespace."""
    pid = await _seed_product()
    out = await PosterCopySetService.create_draft(_create_request(pid))
    await PosterCopySetService.approve(
        out["poster_copy_set_id"],
        approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
        approved_by="op",
    )
    # 1. The video copy_set table stays EMPTY after full poster lifecycle.
    video_rows = await crud.list_copy_sets_for_product(pid)
    assert video_rows == []
    # 2. The video compiler binding rejects a poster copy set id outright.
    from agent.services.copy_binding_service import (
        CopyBindingError,
        resolve_compiler_copy_intelligence,
    )
    with pytest.raises(CopyBindingError):
        await resolve_compiler_copy_intelligence(pid, out["poster_copy_set_id"])
    # 3. Poster statuses live in their own namespace.
    assert out["status"].startswith("POSTER_COPY_")


def test_zone_projection_is_render_time_only():
    fields = poster_fields_to_zone_fields(
        {
            "primary_message": "Tajuk",
            "support_message": "Sokongan",
            "proof_points": ["A", "B"],
            "cta": "Beli",
        }
    )
    assert fields == {
        "hook": "Tajuk",
        "subhook": "Sokongan",
        "usp_1": "A",
        "usp_2": "B",
        "usp_3": "",
        "cta": "Beli",
    }
