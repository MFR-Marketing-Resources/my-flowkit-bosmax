"""Operator-uploaded source media (Smart Registration) — validation, storage,
count-limit enforcement, streaming size cap, and draft->product carry.

Additive lane: nothing here touches the primary image_url/local_image_path path.
"""
from __future__ import annotations

import shutil
import uuid

import pytest
from fastapi import HTTPException

from agent.db import crud
from agent.services import registration_media_service as media
from agent.utils.paths import registration_media_dir

# Minimal magic-byte fixtures
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 24
NOT_MEDIA = b"this is not an image or a video at all"


class _FakeUpload:
    """Mimics starlette UploadFile's async chunked read + close."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk, self._pos = self._data[self._pos:], len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    async def close(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def draft_id():
    # unique per test — the DB persists across tests, so a shared id would leak rows
    did = "test-media-" + uuid.uuid4().hex[:12]
    yield did
    shutil.rmtree(registration_media_dir() / did, ignore_errors=True)


# ── magic-byte detection ──────────────────────────────────────────────────────
def test_image_ext_detects_real_images_only():
    assert media._image_ext(JPG) == "jpg"
    assert media._image_ext(PNG) == "png"
    assert media._image_ext(NOT_MEDIA) is None
    assert media._image_ext(MP4) is None  # a video is not an image


def test_video_ext_detects_iso_bmff_and_webm():
    assert media._video_ext(MP4) == "mp4"
    assert media._video_ext(b"\x1a\x45\xdf\xa3" + b"\x00" * 20) == "webm"
    assert media._video_ext(JPG) is None


# ── store + list + count + delete (real DB + disk) ────────────────────────────
@pytest.mark.asyncio
async def test_add_list_count_delete_roundtrip(draft_id):
    listing = await media.add_media_to_draft(draft_id, "image", [_FakeUpload("a.jpg", JPG)])
    assert len(listing["images"]) == 1
    assert listing["images"][0]["kind"] == "image"
    assert listing["images"][0]["bytes"] == len(JPG)
    assert (await crud.count_product_source_media_by_draft(draft_id))["image"] == 1

    # a video lands in the video bucket, independent of the image count
    listing = await media.add_media_to_draft(draft_id, "video", [_FakeUpload("v.mp4", MP4)])
    assert len(listing["videos"]) == 1
    counts = await crud.count_product_source_media_by_draft(draft_id)
    assert counts == {"image": 1, "video": 1}

    media_id = listing["images"][0]["media_id"]
    after = await media.delete_draft_media(draft_id, media_id)
    assert len(after["images"]) == 0 and len(after["videos"]) == 1


@pytest.mark.asyncio
async def test_bad_type_is_rejected(draft_id):
    with pytest.raises(HTTPException) as exc:
        await media.add_media_to_draft(draft_id, "image", [_FakeUpload("x.txt", NOT_MEDIA)])
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_count_cap_is_enforced(draft_id, monkeypatch):
    monkeypatch.setattr(media, "MAX_IMAGES", 2)
    await media.add_media_to_draft(draft_id, "image", [_FakeUpload("1.jpg", JPG)])
    await media.add_media_to_draft(draft_id, "image", [_FakeUpload("2.jpg", JPG)])
    with pytest.raises(HTTPException) as exc:
        await media.add_media_to_draft(draft_id, "image", [_FakeUpload("3.jpg", JPG)])
    assert exc.value.status_code == 422
    assert (await crud.count_product_source_media_by_draft(draft_id))["image"] == 2


@pytest.mark.asyncio
async def test_size_cap_enforced_and_file_removed(draft_id, monkeypatch):
    monkeypatch.setattr(media, "IMAGE_MAX_BYTES", 8)  # smaller than JPG fixture
    with pytest.raises(HTTPException) as exc:
        await media.add_media_to_draft(draft_id, "image", [_FakeUpload("big.jpg", JPG)])
    assert exc.value.status_code == 422
    # nothing persisted, and no orphan file left behind
    assert (await crud.count_product_source_media_by_draft(draft_id))["image"] == 0
    d = registration_media_dir() / draft_id
    assert not d.exists() or not any(d.iterdir())


@pytest.mark.asyncio
async def test_commit_carry_links_media_to_product(draft_id):
    await media.add_media_to_draft(draft_id, "image", [_FakeUpload("a.jpg", JPG)])
    product = await crud.create_product("Media Carry Fixture", source="MANUAL")
    moved = await crud.link_draft_media_to_product(draft_id, product["id"])
    assert moved == 1
    by_product = await crud.list_product_source_media(product_id=product["id"])
    assert len(by_product) == 1 and by_product[0]["product_id"] == product["id"]
