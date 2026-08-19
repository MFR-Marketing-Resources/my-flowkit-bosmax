"""Prompt & SOP Library — standalone human-reference CRUD + safe attachments.

HARD DECOUPLING LAW: this module must NEVER be imported by generation /
compiler / Product Truth / Copy V2 / Montage code, and it must never feed runtime
generation. It is reference storage only — not a second prompt SSOT.

Attachments are validated (extension allowlist + light magic-byte sanity), size
capped while streaming, stored under a DEDICATED directory with server-generated
names, and served with a path-traversal containment guard.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import UploadFile

from agent.db import crud
from agent.utils.paths import (
    prompt_library_attachment_path,
    prompt_library_attachments_dir,
)

ITEM_TYPES = {"PROMPT", "SOP", "TUTORIAL", "TEMPLATE", "REFERENCE"}
STATUSES = {"ACTIVE", "ARCHIVED"}

_MB = 1024 * 1024
_CHUNK = 1 << 20  # 1 MiB streaming chunk

# ext -> (mime, category, max_bytes). Anything not listed is rejected (fail-closed;
# no executables / unknown types).
_ATTACHMENT_TYPES: dict[str, tuple[str, str, int]] = {
    "png": ("image/png", "image", 10 * _MB),
    "jpg": ("image/jpeg", "image", 10 * _MB),
    "jpeg": ("image/jpeg", "image", 10 * _MB),
    "webp": ("image/webp", "image", 10 * _MB),
    "gif": ("image/gif", "image", 10 * _MB),
    "mp4": ("video/mp4", "video", 100 * _MB),
    "mov": ("video/quicktime", "video", 100 * _MB),
    "webm": ("video/webm", "video", 100 * _MB),
    "pdf": ("application/pdf", "document", 25 * _MB),
    "txt": ("text/plain", "text", 5 * _MB),
    "md": ("text/markdown", "text", 5 * _MB),
    "csv": ("text/csv", "text", 5 * _MB),
    "json": ("application/json", "text", 5 * _MB),
}

SUPPORTED_ATTACHMENT_EXTENSIONS = sorted(_ATTACHMENT_TYPES.keys())


class PromptLibraryError(Exception):
    """Typed error carrying an HTTP status for the API layer."""

    def __init__(self, code: str, status_code: int = 400, detail: str = "") -> None:
        self.code = code
        self.status_code = status_code
        self.detail = detail or code
        super().__init__(self.detail)


def _norm_tags(tags: Any) -> list[str]:
    if not tags:
        return []
    if isinstance(tags, str):
        parts = [t.strip() for t in tags.split(",")]
    elif isinstance(tags, (list, tuple)):
        parts = [str(t).strip() for t in tags]
    else:
        return []
    seen: list[str] = []
    for t in parts:
        if t and t not in seen:
            seen.append(t[:60])
    return seen[:40]


def _loads_tags(raw: Any) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return [str(t) for t in value] if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def _public_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "type": row["type"],
        "category": row.get("category") or "",
        "description": row.get("description") or "",
        "content": row.get("content") or "",
        "tags": _loads_tags(row.get("tags_json")),
        "status": row["status"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _public_attachment(row: dict[str, Any]) -> dict[str, Any]:
    item_id = row["item_id"]
    att_id = row["id"]
    base = f"/api/prompt-library/items/{item_id}/attachments/{att_id}"
    return {
        "id": att_id,
        "item_id": item_id,
        "file_name": row["file_name"],
        "mime": row["mime"],
        "ext": row["ext"],
        "size_bytes": row.get("size_bytes") or 0,
        "created_at": row.get("created_at"),
        "preview_url": f"{base}/preview",
        "download_url": f"{base}/download",
    }


def _magic_ok(category: str, head: bytes) -> bool:
    """Light defense-in-depth: reject binary content that clearly contradicts the
    claimed extension. Text types have no signature, so they pass."""
    if category == "image":
        return (
            head[:3] == b"\xff\xd8\xff"
            or head[:8] == b"\x89PNG\r\n\x1a\n"
            or head[:4] == b"RIFF"  # webp
            or head[:6] in (b"GIF87a", b"GIF89a")
        )
    if category == "document":
        return head[:5] == b"%PDF-"
    if category == "video":
        return b"ftyp" in head[:16] or head[:4] == b"\x1aE\xdf\xa3"  # mp4/mov | webm(EBML)
    return True


# --- Items -------------------------------------------------------------------
async def create_item(
    *,
    title: str,
    type: str = "PROMPT",
    category: str = "",
    description: str = "",
    content: str = "",
    tags: Any = None,
    status: str = "ACTIVE",
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise PromptLibraryError("PROMPT_LIBRARY_TITLE_REQUIRED", 400, "Title is required.")
    item_type = (type or "PROMPT").strip().upper()
    if item_type not in ITEM_TYPES:
        raise PromptLibraryError("PROMPT_LIBRARY_INVALID_TYPE", 400, f"Invalid type: {type!r}")
    item_status = (status or "ACTIVE").strip().upper()
    if item_status not in STATUSES:
        item_status = "ACTIVE"
    item_id = f"pli_{uuid.uuid4().hex[:16]}"
    row = await crud.create_prompt_library_item(
        item_id,
        title=title[:300],
        type=item_type,
        category=(category or "").strip()[:120],
        description=description or "",
        content=content or "",
        tags_json=json.dumps(_norm_tags(tags)),
        status=item_status,
    )
    return _public_item(row)


async def get_item(item_id: str) -> Optional[dict[str, Any]]:
    row = await crud.get_prompt_library_item(item_id)
    return _public_item(row) if row else None


async def list_items(
    *,
    type: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    rows = await crud.list_prompt_library_items(
        type=(type.strip().upper() if type else None),
        category=category or None,
        status=(status.strip().upper() if status else None),
        search=search or None,
        tag=tag or None,
        limit=limit,
    )
    return [_public_item(r) for r in rows]


async def update_item(item_id: str, **fields: Any) -> dict[str, Any]:
    existing = await crud.get_prompt_library_item(item_id)
    if not existing:
        raise PromptLibraryError("PROMPT_LIBRARY_ITEM_NOT_FOUND", 404, "Item not found.")
    patch: dict[str, Any] = {}
    if fields.get("title") is not None:
        title = str(fields["title"]).strip()
        if not title:
            raise PromptLibraryError("PROMPT_LIBRARY_TITLE_REQUIRED", 400, "Title is required.")
        patch["title"] = title[:300]
    if fields.get("type") is not None:
        item_type = str(fields["type"]).strip().upper()
        if item_type not in ITEM_TYPES:
            raise PromptLibraryError("PROMPT_LIBRARY_INVALID_TYPE", 400, "Invalid type.")
        patch["type"] = item_type
    if fields.get("category") is not None:
        patch["category"] = str(fields["category"]).strip()[:120]
    if fields.get("description") is not None:
        patch["description"] = str(fields["description"])
    if fields.get("content") is not None:
        patch["content"] = str(fields["content"])
    if fields.get("tags") is not None:
        patch["tags_json"] = json.dumps(_norm_tags(fields["tags"]))
    if fields.get("status") is not None:
        item_status = str(fields["status"]).strip().upper()
        if item_status not in STATUSES:
            raise PromptLibraryError("PROMPT_LIBRARY_INVALID_STATUS", 400, "Invalid status.")
        patch["status"] = item_status
    row = await crud.update_prompt_library_item(item_id, **patch)
    return _public_item(row)


async def archive_item(item_id: str) -> dict[str, Any]:
    return await update_item(item_id, status="ARCHIVED")


async def unarchive_item(item_id: str) -> dict[str, Any]:
    return await update_item(item_id, status="ACTIVE")


async def delete_item(item_id: str) -> bool:
    existing = await crud.get_prompt_library_item(item_id)
    if not existing:
        return False
    # Remove attachment files first (rows cascade with the item via FK).
    for att in await crud.list_prompt_library_attachments(item_id):
        _safe_unlink(att.get("local_path"))
    return await crud.delete_prompt_library_item(item_id)


# --- Attachments -------------------------------------------------------------
def _safe_unlink(local_path: Any) -> None:
    if not local_path:
        return
    try:
        p = Path(str(local_path)).resolve()
        root = prompt_library_attachments_dir().resolve()
        p.relative_to(root)  # containment guard — refuse to unlink outside the store
        p.unlink(missing_ok=True)
    except (ValueError, OSError):
        pass


async def add_attachment(item_id: str, upload: UploadFile) -> dict[str, Any]:
    item = await crud.get_prompt_library_item(item_id)
    if not item:
        raise PromptLibraryError("PROMPT_LIBRARY_ITEM_NOT_FOUND", 404, "Item not found.")

    filename = (upload.filename or "attachment").strip() or "attachment"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    spec = _ATTACHMENT_TYPES.get(ext)
    if not spec:
        raise PromptLibraryError(
            "UNSUPPORTED_ATTACHMENT_TYPE",
            415,
            f"Unsupported file type '.{ext}'. Allowed: {', '.join(SUPPORTED_ATTACHMENT_EXTENSIONS)}.",
        )
    mime, category, max_bytes = spec

    attachment_id = uuid.uuid4().hex
    dest = prompt_library_attachment_path(item_id, attachment_id, ext)

    head = await upload.read(512)
    if not _magic_ok(category, head):
        raise PromptLibraryError(
            "ATTACHMENT_CONTENT_MISMATCH",
            400,
            "File content does not match its extension.",
        )

    total = 0
    overflow = False
    with dest.open("wb") as fh:
        chunk = head
        while chunk:
            total += len(chunk)
            if total > max_bytes:
                overflow = True
                break
            fh.write(chunk)
            chunk = await upload.read(_CHUNK)
    if overflow:
        dest.unlink(missing_ok=True)
        raise PromptLibraryError(
            "ATTACHMENT_TOO_LARGE",
            413,
            f"File exceeds the {max_bytes // _MB} MB limit for {category} attachments.",
        )

    row = await crud.create_prompt_library_attachment(
        attachment_id,
        item_id=item_id,
        file_name=filename[:200],
        mime=mime,
        ext=ext,
        size_bytes=total,
        local_path=str(dest),
    )
    return _public_attachment(row)


async def list_attachments(item_id: str) -> list[dict[str, Any]]:
    return [_public_attachment(r) for r in await crud.list_prompt_library_attachments(item_id)]


async def resolve_attachment_file(attachment_id: str) -> tuple[Optional[Path], Optional[dict[str, Any]]]:
    """Return (path, row) with a containment guard. path is None if missing/unsafe."""
    row = await crud.get_prompt_library_attachment(attachment_id)
    if not row:
        return None, None
    try:
        p = Path(str(row.get("local_path"))).resolve()
        root = prompt_library_attachments_dir().resolve()
        p.relative_to(root)  # traversal guard
    except (ValueError, OSError):
        return None, row
    if not p.exists() or p.stat().st_size == 0:
        return None, row
    return p, row


async def delete_attachment(attachment_id: str) -> bool:
    row = await crud.get_prompt_library_attachment(attachment_id)
    if not row:
        return False
    _safe_unlink(row.get("local_path"))
    return await crud.delete_prompt_library_attachment(attachment_id)
