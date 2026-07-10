"""Poster deliverable — compose orchestration, preview/save identity, final
gates, Creative Library registration, reconstruction (POSTER_BUILDER_V2).

The Chromium renderer is mocked here (subprocess-free); the real render path is
proven by tests/ui/test_poster_compositor_service_contract.py + the committed
per-archetype fixtures.
"""
import hashlib
import json
from pathlib import Path

import pytest

from agent.db import crud
from agent.models.poster_copy_set import (
    POSTER_COPY_APPROVAL_PHRASE,
    PosterCopySetCreateRequest,
)
from agent.models.poster_render_manifest import PosterRenderReport, ZoneRenderResult
from agent.services import poster_compositor_service as compositor
from agent.services.poster_copy_set_service import PosterCopySetService
from agent.services.poster_deliverable_service import (
    PosterDeliverableError,
    PosterDeliverableService,
)


async def _seed_product() -> str:
    row = await crud.create_product(
        "Minyak Warisan Tok 25ml", source="MANUAL",
        product_display_name="Minyak Warisan Tok", category="Traditional",
    )
    return row["id"]


async def _seed_copy_set(pid: str, *, approve: bool = True) -> dict:
    out = await PosterCopySetService.create_draft(
        PosterCopySetCreateRequest(
            product_id=pid,
            objective="Product introduction",
            archetype="PRODUCT_HERO",
            angle="Premium hero",
            primary_message="Minyak warisan keluarga",
            support_message="Sedia bila anda perlukan.",
            proof_points=["Saiz poket", "Mudah dibawa"],
            cta="Beli sekarang",
            language="ms",
        )
    )
    if approve:
        out = await PosterCopySetService.approve(
            out["poster_copy_set_id"],
            approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
            approved_by="op",
        )
    return out


def _fake_compose(tmp_path: Path, *, ok: bool = True):
    """Monkeypatch-able compositor.compose that writes a real PNG file."""

    async def fake(manifest, *, render_id: str = ""):
        out = tmp_path / (render_id or "render") / "poster.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x89PNG_FAKE_POSTER_BYTES_" + b"x" * 64)
        zones = [
            ZoneRenderResult(
                zone_id=z.zone_id, fitted=ok, overflowed=not ok,
                overlaps_product=False, font_scale=1.0, rendered_text=z.text,
            )
            for z in manifest.zones
        ]
        report = PosterRenderReport(
            renderer="HTML_CHROMIUM_SERVICE_V1",
            canvas={"w": 1080, "h": 1920},
            output_png={"width": 1080, "height": 1920},
            zones=zones, errors=[], ok=ok,
        )
        return out, report

    return fake


def _bg(tmp_path: Path) -> str:
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"\x89PNG_FAKE_BG")
    return str(bg)


@pytest.mark.asyncio
async def test_compose_persists_manifest_qa_and_hash(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
        image_model="NANO_BANANA_PRO",
    )
    row = result["deliverable"]
    assert row["status"] == "POSTER_COMPOSED"
    assert row["output_sha256"]
    manifest = json.loads(row["render_manifest_json"])
    assert manifest["provenance"]["poster_copy_set_id"] == pcs["poster_copy_set_id"]
    assert manifest["schema_version"] == "poster-render-manifest-v1"
    assert result["qa_report"]["ok"] is True
    # The stored hash matches the real file on disk (preview/save identity base).
    data = Path(row["output_path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == row["output_sha256"]


@pytest.mark.asyncio
async def test_save_registers_creative_asset_with_poster_governance(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
    )
    captured = {}

    async def fake_create_asset(request):
        captured["request"] = request

        class _A:  # minimal record
            asset_id = "ca_poster_test_1"

        return _A()

    monkeypatch.setattr(
        "agent.services.poster_deliverable_service.create_creative_asset",
        fake_create_asset,
    )
    saved = await PosterDeliverableService.save_to_library(
        result["deliverable"]["poster_deliverable_id"]
    )
    assert saved["creative_asset_id"] == "ca_poster_test_1"
    assert saved["deliverable"]["status"] == "POSTER_SAVED"
    req = captured["request"]
    # PRODUCT_POSTER lane governance is stamped, not improvised.
    assert req.asset_subtype == "POSTER_AD"
    assert req.contains_rendered_text is True
    assert req.approved_for_poster is True
    assert req.allowed_modes == ["IMG"]
    # PREVIEW == SAVE: the exact composed bytes were sent.
    import base64
    sent = base64.b64decode(req.image_base64)
    disk = Path(result["deliverable"]["output_path"]).read_bytes()
    assert sent == disk
    # Idempotent re-save.
    again = await PosterDeliverableService.save_to_library(
        result["deliverable"]["poster_deliverable_id"]
    )
    assert again["already_saved"] is True


@pytest.mark.asyncio
async def test_save_requires_approved_copy_set(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid, approve=False)  # DRAFT
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
    )
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.save_to_library(
            result["deliverable"]["poster_deliverable_id"]
        )
    assert exc.value.code == "POSTER_COPY_SET_NOT_APPROVED"


@pytest.mark.asyncio
async def test_save_detects_identity_mismatch(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
    )
    # Tamper with the composed file after preview.
    Path(result["deliverable"]["output_path"]).write_bytes(b"TAMPERED")
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.save_to_library(
            result["deliverable"]["poster_deliverable_id"]
        )
    assert exc.value.code == "POSTER_OUTPUT_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_save_blocked_by_qa(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path, ok=False))
    result = await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
    )
    assert result["qa_report"]["block_count"] > 0
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.save_to_library(
            result["deliverable"]["poster_deliverable_id"]
        )
    assert exc.value.code == "POSTER_QA_BLOCKED"


@pytest.mark.asyncio
async def test_reconstruction_returns_manifest_copy_and_qa(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
    )
    info = await PosterDeliverableService.get_with_manifest(
        result["deliverable"]["poster_deliverable_id"]
    )
    assert info["render_manifest"]["zones"], "manifest reconstructable"
    assert info["poster_copy_set"]["primary_message"] == "Minyak warisan keluarga"
    assert info["qa_report"]["ok"] is True
    assert info["output_available"] is True


@pytest.mark.asyncio
async def test_missing_background_fails_closed(tmp_path, monkeypatch):
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.compose_poster(
            product_id=pid,
            poster_copy_set_id=pcs["poster_copy_set_id"],
            recipe_id="product_hero_night_routine",
            background_local_path=str(tmp_path / "missing.png"),
        )
    assert exc.value.code == "POSTER_BACKGROUND_FILE_MISSING"
