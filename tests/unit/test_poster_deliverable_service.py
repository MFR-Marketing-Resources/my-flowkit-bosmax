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
from agent.services import poster_deliverable_service as deliverable_svc
from agent.services.poster_copy_set_service import PosterCopySetService
from agent.services.poster_deliverable_service import (
    PosterDeliverableError,
    PosterDeliverableService,
)


@pytest.fixture(autouse=True)
def _allow_tmp_background(tmp_path, monkeypatch):
    """Whitelist the pytest tmp dir as an allowed background root."""
    monkeypatch.setattr(
        deliverable_svc,
        "_ALLOWED_BACKGROUND_ROOTS",
        (*deliverable_svc._ALLOWED_BACKGROUND_ROOTS, tmp_path),
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


# ─── Repair PR: honest product truth, path security, library round trip ──────

async def _compose(pid, pcs, tmp_path):
    return await PosterDeliverableService.compose_poster(
        product_id=pid,
        poster_copy_set_id=pcs["poster_copy_set_id"],
        recipe_id="product_hero_night_routine",
        background_local_path=_bg(tmp_path),
    )


def _mock_asset(monkeypatch, captured, asset_id="ca_truth_1"):
    async def fake_create_asset(request):
        captured["request"] = request

        class _A:
            pass

        a = _A()
        a.asset_id = asset_id
        return a

    monkeypatch.setattr(
        "agent.services.poster_deliverable_service.create_creative_asset",
        fake_create_asset,
    )


@pytest.mark.asyncio
async def test_save_stamps_reference_conditioned_unverified(tmp_path, monkeypatch):
    """REFERENCE_CONDITIONED composition must NEVER be stamped PRESERVED."""
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await _compose(pid, pcs, tmp_path)
    assert result["deliverable"]["composition_strategy"] == "REFERENCE_CONDITIONED"
    captured = {}
    _mock_asset(monkeypatch, captured)
    await PosterDeliverableService.save_to_library(
        result["deliverable"]["poster_deliverable_id"]
    )
    req = captured["request"]
    assert req.product_truth_status == "REFERENCE_CONDITIONED_UNVERIFIED"
    assert req.product_truth_status != "PRESERVED"
    # The library description carries the honest human-review note.
    assert "human review" in req.description


def test_truth_status_mapping_is_fail_closed():
    assert (
        deliverable_svc.derive_poster_truth_status("REFERENCE_CONDITIONED")
        == "REFERENCE_CONDITIONED_UNVERIFIED"
    )
    assert (
        deliverable_svc.derive_poster_truth_status("DETERMINISTIC_COMPOSITE")
        == "DETERMINISTIC_COMPOSITE_VERIFIED"
    )
    # Unknown / missing strategy → most conservative label, never PRESERVED.
    assert deliverable_svc.derive_poster_truth_status("") == "HUMAN_REVIEW_REQUIRED"
    assert deliverable_svc.derive_poster_truth_status("WEIRD") == "HUMAN_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_background_path_outside_roots_rejected(tmp_path_factory, tmp_path, monkeypatch):
    """A client path outside the allowed roots is refused with a structured error."""
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    outside = tmp_path_factory.mktemp("outside_roots")  # sibling of tmp_path
    bg = outside / "bg.png"
    bg.write_bytes(b"\x89PNG_FAKE_BG")
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.compose_poster(
            product_id=pid,
            poster_copy_set_id=pcs["poster_copy_set_id"],
            recipe_id="product_hero_night_routine",
            background_local_path=str(bg),
        )
    assert exc.value.code == "POSTER_BACKGROUND_PATH_FORBIDDEN"
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_background_path_traversal_rejected(tmp_path_factory, tmp_path, monkeypatch):
    """`..` traversal is canonicalized away and refused when it escapes the roots."""
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    outside = tmp_path_factory.mktemp("outside_trav")
    bg = outside / "bg.png"
    bg.write_bytes(b"\x89PNG_FAKE_BG")
    sneaky = str(tmp_path / ".." / outside.name / "bg.png")
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.compose_poster(
            product_id=pid,
            poster_copy_set_id=pcs["poster_copy_set_id"],
            recipe_id="product_hero_night_routine",
            background_local_path=sneaky,
        )
    assert exc.value.code == "POSTER_BACKGROUND_PATH_FORBIDDEN"


def test_background_path_resolution_runtime_error_is_structured(monkeypatch):
    """A symlink-loop style resolver failure must not escape as an untyped 500."""
    def _raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("symlink resolution loop")

    monkeypatch.setattr(deliverable_svc.Path, "resolve", _raise_runtime_error)
    with pytest.raises(PosterDeliverableError) as exc:
        deliverable_svc._validate_client_background_path("C:/untrusted/bg.png")
    assert exc.value.code == "POSTER_BACKGROUND_PATH_FORBIDDEN"
    assert exc.value.status_code == 422


def test_allowed_root_resolution_runtime_error_is_structured(tmp_path, monkeypatch):
    """A malformed allowlisted root must fail closed rather than leak RuntimeError."""
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"PNG")
    original_resolve = deliverable_svc.Path.resolve

    def _resolve_with_bad_root(path, *args, **kwargs):
        if path == tmp_path:
            raise RuntimeError("allowlisted root resolution loop")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(deliverable_svc.Path, "resolve", _resolve_with_bad_root)
    with pytest.raises(PosterDeliverableError) as exc:
        deliverable_svc._validate_client_background_path(str(bg))
    assert exc.value.code == "POSTER_BACKGROUND_PATH_FORBIDDEN"


@pytest.mark.asyncio
async def test_creative_library_round_trip_by_asset(tmp_path, monkeypatch):
    """Library reopen: creative_asset_id → deliverable + manifest + copy set."""
    pid = await _seed_product()
    pcs = await _seed_copy_set(pid)
    monkeypatch.setattr(compositor, "compose", _fake_compose(tmp_path))
    result = await _compose(pid, pcs, tmp_path)
    captured = {}
    _mock_asset(monkeypatch, captured, asset_id="ca_roundtrip_1")
    await PosterDeliverableService.save_to_library(
        result["deliverable"]["poster_deliverable_id"]
    )
    recon = await PosterDeliverableService.get_by_creative_asset("ca_roundtrip_1")
    assert (
        recon["deliverable"]["poster_deliverable_id"]
        == result["deliverable"]["poster_deliverable_id"]
    )
    assert recon["poster_copy_set"]["poster_copy_set_id"] == pcs["poster_copy_set_id"]
    assert recon["render_manifest"]["provenance"]["recipe_id"] == "product_hero_night_routine"
    assert recon["output_available"] is True
    # Unknown asset → structured 404.
    with pytest.raises(PosterDeliverableError) as exc:
        await PosterDeliverableService.get_by_creative_asset("ca_nope")
    assert exc.value.status_code == 404
