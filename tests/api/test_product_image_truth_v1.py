"""Issue #203 follow-up — truthful product-image readiness + operator attach path.

Covers the image-evidence gate that keeps F2V / I2V / HYBRID honest:

* a stale ``image_asset_status=DOWNLOADED`` row whose file is gone (or is a
  0-byte upload) must read as LOCAL_CACHE_MISSING, never IMAGE_CACHE_READY;
* the operator attach path (``_save_manual_image``, used by manual-create and
  ``PATCH /api/products/{id}``) must persist only a real image and reject empty
  / non-image payloads so nothing can be faked into READY;
* once a real image is attached, F2V and I2V flip to READY, and deleting it
  flips them back to their exact blockers.
"""
from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi import HTTPException

from agent.api import products as products_api
from agent.services import approved_product_package_service as svc
from agent.services.product_intelligence import resolve_image_readiness

# A real, minimal 1x1 PNG (valid magic bytes + non-empty).
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_JPEG_MAGIC = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
_GIF_MAGIC = b"GIF89a" + b"\x00" * 32
_WEBP_MAGIC = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


# ── resolve_image_readiness — file truth, not the DB field ───────────────────


def test_readiness_real_nonempty_file_is_cache_ready(tmp_path):
    img = tmp_path / "p.png"
    img.write_bytes(_PNG_1x1)
    out = resolve_image_readiness(
        {"local_image_path": str(img), "image_asset_status": "DOWNLOADED"}
    )
    assert out["image_readiness_status"] == "IMAGE_CACHE_READY"


def test_readiness_missing_file_despite_downloaded_status(tmp_path):
    """Stale DB truth: status says DOWNLOADED but the file is absent."""
    out = resolve_image_readiness(
        {"local_image_path": str(tmp_path / "gone.png"), "image_asset_status": "DOWNLOADED"}
    )
    assert out["image_readiness_status"] == "LOCAL_CACHE_MISSING"


def test_readiness_zero_byte_file_is_not_ready(tmp_path):
    """Regression guard for the closed hole: a 0-byte file must not read ready."""
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    out = resolve_image_readiness(
        {"local_image_path": str(empty), "image_asset_status": "DOWNLOADED"}
    )
    assert out["image_readiness_status"] == "LOCAL_CACHE_MISSING"


def test_readiness_is_product_specific(tmp_path):
    """Each product resolves against its own path — no cross-product leakage."""
    a = tmp_path / "a.png"
    a.write_bytes(_PNG_1x1)
    ready = resolve_image_readiness({"local_image_path": str(a)})
    missing = resolve_image_readiness({"local_image_path": str(tmp_path / "b.png")})
    assert ready["image_readiness_status"] == "IMAGE_CACHE_READY"
    assert missing["image_readiness_status"] == "LOCAL_CACHE_MISSING"


# ── _detect_image_ext / _save_manual_image — attach path validation ──────────


@pytest.mark.parametrize(
    "data,ext",
    [(_PNG_1x1, "png"), (_JPEG_MAGIC, "jpg"), (_GIF_MAGIC, "gif"), (_WEBP_MAGIC, "webp")],
)
def test_detect_image_ext_accepts_real_images(data, ext):
    assert products_api._detect_image_ext(data) == ext


@pytest.mark.parametrize("data", [b"", b"not-an-image", b"<html>nope</html>"])
def test_detect_image_ext_rejects_non_images(data):
    assert products_api._detect_image_ext(data) is None


def test_save_manual_image_persists_real_image(tmp_path, monkeypatch):
    monkeypatch.setattr(
        products_api, "product_image_path", lambda pid, ext="jpg": tmp_path / f"{pid}.{ext}"
    )
    b64 = base64.b64encode(_PNG_1x1).decode()
    path, status = asyncio.run(products_api._save_manual_image("prod-1", b64, "photo.png"))
    assert status == "DOWNLOADED"
    from pathlib import Path

    saved = Path(path)
    assert saved.is_file() and saved.stat().st_size > 0
    # And that saved file is what readiness will trust.
    assert (
        resolve_image_readiness({"local_image_path": path})["image_readiness_status"]
        == "IMAGE_CACHE_READY"
    )


@pytest.mark.parametrize(
    "b64",
    [
        "data:image/png;base64,",  # non-empty header, empty payload -> EMPTY_IMAGE
        base64.b64encode(b"totally not an image").decode(),  # decodes to non-image bytes
    ],
)
def test_save_manual_image_rejects_fake_uploads(tmp_path, monkeypatch, b64):
    monkeypatch.setattr(
        products_api, "product_image_path", lambda pid, ext="jpg": tmp_path / f"{pid}.{ext}"
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(products_api._save_manual_image("prod-1", b64, "photo.png"))
    assert exc.value.status_code == 422
    # And nothing was written to disk.
    assert not any(tmp_path.iterdir())


def test_save_manual_image_no_image_is_noop(tmp_path, monkeypatch):
    """An empty/absent base64 string means "no image supplied" — a no-op, not an
    error and not a written file."""
    monkeypatch.setattr(
        products_api, "product_image_path", lambda pid, ext="jpg": tmp_path / f"{pid}.{ext}"
    )
    assert asyncio.run(products_api._save_manual_image("prod-1", "", "photo.png")) == (None, None)
    assert asyncio.run(products_api._save_manual_image("prod-1", None, None)) == (None, None)
    assert not any(tmp_path.iterdir())


# ── End-to-end readiness — real image flips F2V/I2V READY, then back ─────────


def _approved_row(local_image_path: str) -> dict:
    return {
        "id": "prod-1",
        "product_display_name": "Bosmax Herbs 5 ML",
        "raw_product_title": "Bosmax Herbs 5 ML",
        "lifecycle_status": "ACTIVE",
        "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
        "production_prompt_approved_modes": ["T2V", "IMG"],
        "local_image_path": local_image_path,
        "image_asset_status": "DOWNLOADED",
    }


def _patch_gate(monkeypatch, row):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_enrich(product, persist=False):
        d = dict(row)
        d.update(resolve_image_readiness(d))  # real file-truth computation
        return d

    async def fake_claim_safe(product_id: str):
        return {"claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED"}

    monkeypatch.setattr(svc.crud, "get_product", fake_get_product)
    monkeypatch.setattr(svc, "enrich_product", fake_enrich)
    monkeypatch.setattr(svc, "get_stored_claim_safe_package", fake_claim_safe)


async def test_real_image_makes_f2v_and_i2v_ready(tmp_path, monkeypatch):
    img = tmp_path / "prod-1.png"
    img.write_bytes(_PNG_1x1)
    _patch_gate(monkeypatch, _approved_row(str(img)))

    assert (await svc.get_product_package_readiness("prod-1", "F2V"))["readiness_status"] == "READY"
    assert (await svc.get_product_package_readiness("prod-1", "I2V"))["readiness_status"] == "READY"


async def test_deleting_image_reblocks_f2v_and_i2v(tmp_path, monkeypatch):
    img = tmp_path / "prod-1.png"
    img.write_bytes(_PNG_1x1)
    _patch_gate(monkeypatch, _approved_row(str(img)))
    assert (await svc.get_product_package_readiness("prod-1", "F2V"))["readiness_status"] == "READY"

    img.unlink()  # simulate the exact stale scenario the live BOSMAX/MW rows are in
    assert (
        await svc.get_product_package_readiness("prod-1", "F2V")
    )["readiness_status"] == "START_FRAME_REQUIRED"
    assert (
        await svc.get_product_package_readiness("prod-1", "I2V")
    )["readiness_status"] == "SUBJECT_REQUIRED"


async def test_t2v_and_img_stay_ready_without_image(tmp_path, monkeypatch):
    """Regression: the image truth check must not regress the image-less modes."""
    _patch_gate(monkeypatch, _approved_row(str(tmp_path / "missing.png")))
    assert (await svc.get_product_package_readiness("prod-1", "T2V"))["readiness_status"] == "READY"
    assert (await svc.get_product_package_readiness("prod-1", "IMG"))["readiness_status"] == "READY"


# ── HYBRID surface maps to the F2V image gate (frontend boundary) ────────────


def test_operator_hybrid_maps_to_f2v_job_mode():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "dashboard/src/pages/OperatorPage.tsx"
    text = src.read_text(encoding="utf-8")
    assert 'mode === "HYBRID" ? "F2V"' in text
