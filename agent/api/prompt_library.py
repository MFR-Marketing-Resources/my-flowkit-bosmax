"""Prompt & SOP Library API — standalone human-reference CRUD + attachments.

Mounted at /api/prompt-library. Deliberately decoupled: it imports only its own
service and never any generation/compiler/Copy-V2/Montage module.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent.services import prompt_library_service as svc
from agent.services.prompt_library_service import PromptLibraryError

router = APIRouter(prefix="/prompt-library", tags=["prompt-library"])


class ItemCreateRequest(BaseModel):
    title: str
    type: str = "PROMPT"
    category: str = ""
    description: str = ""
    content: str = ""
    tags: list[str] = []
    status: str = "ACTIVE"


class ItemUpdateRequest(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


def _raise(err: PromptLibraryError) -> None:
    raise HTTPException(status_code=err.status_code, detail={"error": err.code, "detail": err.detail})


@router.get("/meta")
async def prompt_library_meta() -> dict[str, Any]:
    return {
        "item_types": sorted(svc.ITEM_TYPES),
        "statuses": sorted(svc.STATUSES),
        "supported_attachment_extensions": svc.SUPPORTED_ATTACHMENT_EXTENSIONS,
    }


@router.get("/items")
async def list_items(
    type: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    items = await svc.list_items(
        type=type, category=category, status=status, search=search, tag=tag, limit=limit
    )
    return {"items": items, "total": len(items)}


@router.post("/items")
async def create_item(body: ItemCreateRequest) -> dict[str, Any]:
    try:
        return await svc.create_item(
            title=body.title,
            type=body.type,
            category=body.category,
            description=body.description,
            content=body.content,
            tags=body.tags,
            status=body.status,
        )
    except PromptLibraryError as err:
        _raise(err)


@router.get("/items/{item_id}")
async def get_item(item_id: str) -> dict[str, Any]:
    item = await svc.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail={"error": "PROMPT_LIBRARY_ITEM_NOT_FOUND"})
    item["attachments"] = await svc.list_attachments(item_id)
    return item


@router.patch("/items/{item_id}")
async def update_item(item_id: str, body: ItemUpdateRequest) -> dict[str, Any]:
    try:
        return await svc.update_item(item_id, **body.model_dump(exclude_unset=True))
    except PromptLibraryError as err:
        _raise(err)


@router.post("/items/{item_id}/archive")
async def archive_item(item_id: str) -> dict[str, Any]:
    try:
        return await svc.archive_item(item_id)
    except PromptLibraryError as err:
        _raise(err)


@router.post("/items/{item_id}/unarchive")
async def unarchive_item(item_id: str) -> dict[str, Any]:
    try:
        return await svc.unarchive_item(item_id)
    except PromptLibraryError as err:
        _raise(err)


@router.delete("/items/{item_id}")
async def delete_item(item_id: str) -> dict[str, Any]:
    removed = await svc.delete_item(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail={"error": "PROMPT_LIBRARY_ITEM_NOT_FOUND"})
    return {"id": item_id, "removed": True}


@router.get("/items/{item_id}/attachments")
async def list_attachments(item_id: str) -> dict[str, Any]:
    return {"item_id": item_id, "attachments": await svc.list_attachments(item_id)}


@router.post("/items/{item_id}/attachments")
async def add_attachment(item_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        return await svc.add_attachment(item_id, file)
    except PromptLibraryError as err:
        _raise(err)


@router.get("/items/{item_id}/attachments/{attachment_id}/download")
async def download_attachment(item_id: str, attachment_id: str) -> FileResponse:
    path, row = await svc.resolve_attachment_file(attachment_id)
    if path is None or row is None or row.get("item_id") != item_id:
        raise HTTPException(status_code=404, detail={"error": "ATTACHMENT_NOT_FOUND"})
    return FileResponse(str(path), media_type=row.get("mime"), filename=row.get("file_name"))


@router.get("/items/{item_id}/attachments/{attachment_id}/preview")
async def preview_attachment(item_id: str, attachment_id: str) -> FileResponse:
    path, row = await svc.resolve_attachment_file(attachment_id)
    if path is None or row is None or row.get("item_id") != item_id:
        raise HTTPException(status_code=404, detail={"error": "ATTACHMENT_NOT_FOUND"})
    return FileResponse(str(path), media_type=row.get("mime"))


@router.delete("/items/{item_id}/attachments/{attachment_id}")
async def delete_attachment(item_id: str, attachment_id: str) -> dict[str, Any]:
    _path, row = await svc.resolve_attachment_file(attachment_id)
    if row is not None and row.get("item_id") != item_id:
        raise HTTPException(status_code=404, detail={"error": "ATTACHMENT_NOT_FOUND"})
    removed = await svc.delete_attachment(attachment_id)
    if not removed:
        raise HTTPException(status_code=404, detail={"error": "ATTACHMENT_NOT_FOUND"})
    return {"id": attachment_id, "removed": True}
