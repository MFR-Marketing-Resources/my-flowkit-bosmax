"""Operator-uploaded source media for Smart Registration (images + videos).

ADDITIVE and fully separate from the single primary image lane
(`declared_evidence_fields.image_url` / `local_image_path`), which is left
untouched. Files are stored and served LOCALLY only — nothing is sent to any
provider, so this whole lane is zero AI/credit cost. Videos never touch the Flow
WebSocket bridge.

Limits (owner-set): up to 10 images (<=5 MB each, JPG/PNG/WebP) and up to 3
videos (<=50 MB each, MP4/MOV/WebM). The size cap is enforced WHILE streaming to
disk so a large upload can never be fully buffered in memory.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile

from agent.config import BASE_DIR
from agent.db import crud
from agent.utils.paths import registration_media_path

MAX_IMAGES = 10
MAX_VIDEOS = 3
IMAGE_MAX_BYTES = 5 * 1024 * 1024      # 5 MB
VIDEO_MAX_BYTES = 50 * 1024 * 1024     # 50 MB
_CHUNK = 1 << 20                       # 1 MiB streaming chunk

IMAGE_TYPES_LABEL = "JPG/PNG/WebP"
VIDEO_TYPES_LABEL = "MP4/MOV/WebM"


def limits() -> dict:
    """Surface the caps to the FE so it can show them and pre-validate."""
    return {
        "max_images": MAX_IMAGES,
        "max_videos": MAX_VIDEOS,
        "image_max_bytes": IMAGE_MAX_BYTES,
        "video_max_bytes": VIDEO_MAX_BYTES,
        "image_types": IMAGE_TYPES_LABEL,
        "video_types": VIDEO_TYPES_LABEL,
    }


def _image_ext(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _video_ext(head: bytes) -> str | None:
    # ISO base media (mp4 / mov): bytes 4..8 == 'ftyp'; 'qt  ' brand => .mov
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov" if head[8:12] == b"qt  " else "mp4"
    # Matroska / WebM EBML header
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


def _mime_for(kind: str, ext: str) -> str:
    if ext == "jpg":
        return "image/jpeg"
    return f"{kind}/{ext}"


async def add_media_to_draft(draft_id: str, kind: str, uploads: list[UploadFile]) -> dict:
    """Validate + persist a batch of uploads for one draft; returns the full media
    listing (both kinds) so the FE can re-render."""
    kind = (kind or "").strip().lower()
    if kind not in ("image", "video"):
        raise HTTPException(status_code=422, detail="kind must be 'image' or 'video'")
    uploads = [u for u in (uploads or []) if u is not None]
    if not uploads:
        raise HTTPException(status_code=422, detail="No file provided.")

    cap = MAX_IMAGES if kind == "image" else MAX_VIDEOS
    counts = await crud.count_product_source_media_by_draft(draft_id)
    existing = int(counts.get(kind, 0))
    if existing + len(uploads) > cap:
        raise HTTPException(
            status_code=422,
            detail=f"Too many {kind}s: {existing} already stored + {len(uploads)} new "
                   f"exceeds the maximum of {cap}.",
        )

    size_cap = IMAGE_MAX_BYTES if kind == "image" else VIDEO_MAX_BYTES
    types_label = IMAGE_TYPES_LABEL if kind == "image" else VIDEO_TYPES_LABEL
    ordinal = existing
    for up in uploads:
        head = await up.read(_CHUNK)
        ext = _image_ext(head) if kind == "image" else _video_ext(head)
        if not ext:
            await up.close()
            raise HTTPException(
                status_code=422,
                detail=f"'{up.filename}' is not a supported {kind} (allowed: {types_label}).",
            )
        media_id = uuid.uuid4().hex
        dest = registration_media_path(draft_id, media_id, ext)
        total = 0
        overflow = False
        with dest.open("wb") as fh:
            chunk = head
            while chunk:
                total += len(chunk)
                if total > size_cap:
                    overflow = True
                    break
                fh.write(chunk)
                chunk = await up.read(_CHUNK)
        await up.close()
        if overflow:
            dest.unlink(missing_ok=True)
            mb = size_cap // (1024 * 1024)
            raise HTTPException(
                status_code=422,
                detail=f"'{up.filename}' exceeds the {mb} MB {kind} limit — please compress it first.",
            )
        rel = str(dest.relative_to(BASE_DIR)).replace("\\", "/")
        await crud.create_product_source_media(
            draft_id,
            kind,
            media_id=media_id,
            local_path=rel,
            filename=(up.filename or f"{media_id}.{ext}"),
            mime=_mime_for(kind, ext),
            bytes=total,
            ordinal=ordinal,
            status="STORED",
        )
        ordinal += 1

    return await list_draft_media(draft_id)


async def list_draft_media(draft_id: str) -> dict:
    """{'images': [...], 'videos': [...], 'limits': {...}} for a draft."""
    rows = await crud.list_product_source_media(draft_id=draft_id)
    images = [_public(r) for r in rows if r.get("kind") == "image"]
    videos = [_public(r) for r in rows if r.get("kind") == "video"]
    return {"draft_id": draft_id, "images": images, "videos": videos, "limits": limits()}


async def delete_draft_media(draft_id: str, media_id: str) -> dict:
    row = await crud.get_product_source_media(media_id)
    if not row or row.get("draft_id") != draft_id:
        raise HTTPException(status_code=404, detail="Media not found for this draft.")
    rel = str(row.get("local_path") or "").strip()
    if rel:
        target = (BASE_DIR / rel).resolve()
        try:  # only unlink inside the media root — never follow a stray path out
            target.relative_to(BASE_DIR.resolve())
            target.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass
    await crud.delete_product_source_media(media_id)
    return await list_draft_media(draft_id)


def resolve_media_file(row: dict):
    """Absolute on-disk path for serving, guarded against path traversal."""
    rel = str(row.get("local_path") or "").strip()
    if not rel:
        return None
    target = (BASE_DIR / rel).resolve()
    try:
        target.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return target if target.exists() else None


def _public(row: dict) -> dict:
    """Client-facing shape — never leak the absolute disk path."""
    return {
        "media_id": row.get("media_id"),
        "kind": row.get("kind"),
        "filename": row.get("filename"),
        "mime": row.get("mime"),
        "bytes": row.get("bytes"),
        "ordinal": row.get("ordinal"),
        "status": row.get("status"),
    }
