"""Feature C — Prompt & SOP Library: CRUD, search/filter, safe attachments,
path-traversal guard, and the hard decoupling law."""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from agent.db import crud
from agent.services import prompt_library_service as svc

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(data), filename=name)


async def test_item_crud_lifecycle():
    item = await svc.create_item(
        title="Hook prompt", type="PROMPT", category="Hooks",
        description="A reusable hook", content="Write a scroll-stopping hook.",
        tags=["hook", "tiktok"],
    )
    assert item["id"].startswith("pli_")
    assert item["type"] == "PROMPT"
    assert item["tags"] == ["hook", "tiktok"]
    assert item["status"] == "ACTIVE"

    fetched = await svc.get_item(item["id"])
    assert fetched["title"] == "Hook prompt"

    updated = await svc.update_item(item["id"], title="Hook prompt v2", content="Updated.")
    assert updated["title"] == "Hook prompt v2"
    assert updated["content"] == "Updated."

    archived = await svc.archive_item(item["id"])
    assert archived["status"] == "ARCHIVED"

    assert await svc.delete_item(item["id"]) is True
    assert await svc.get_item(item["id"]) is None


async def test_all_item_types_supported():
    for t in ["PROMPT", "SOP", "TUTORIAL", "TEMPLATE", "REFERENCE"]:
        item = await svc.create_item(title=f"{t} item", type=t)
        assert item["type"] == t


async def test_invalid_type_rejected():
    with pytest.raises(svc.PromptLibraryError) as exc:
        await svc.create_item(title="x", type="NONSENSE")
    assert exc.value.code == "PROMPT_LIBRARY_INVALID_TYPE"


async def test_title_required():
    with pytest.raises(svc.PromptLibraryError) as exc:
        await svc.create_item(title="   ")
    assert exc.value.code == "PROMPT_LIBRARY_TITLE_REQUIRED"


async def test_search_and_filter():
    # Scope every assertion to a unique category so the test is independent of
    # any rows other tests left behind (Windows keeps the sqlite file handle open,
    # so the shared suite does not hard-reset between tests).
    cat = "PL_FILTER_TEST_CAT"
    await svc.create_item(title="Alpha SOP", type="SOP", category=cat, content="alpha zzdeploy steps", tags=["zzdeploy"])
    await svc.create_item(title="Beta prompt", type="PROMPT", category=cat, content="beta zzhookline", tags=["zzhook"])
    gamma = await svc.create_item(title="Gamma template", type="TEMPLATE", category=cat)
    await svc.archive_item(gamma["id"])

    active = await svc.list_items(category=cat, status="ACTIVE")
    assert {i["title"] for i in active} == {"Alpha SOP", "Beta prompt"}  # archived Gamma excluded

    by_type = await svc.list_items(type="SOP", category=cat)
    assert [i["title"] for i in by_type] == ["Alpha SOP"]

    by_search = await svc.list_items(search="beta zzhookline")
    assert [i["title"] for i in by_search] == ["Beta prompt"]

    by_tag = await svc.list_items(tag="zzdeploy")
    assert [i["title"] for i in by_tag] == ["Alpha SOP"]

    archived = await svc.list_items(status="ARCHIVED", category=cat)
    assert [i["title"] for i in archived] == ["Gamma template"]


async def test_attachment_upload_list_and_serve():
    item = await svc.create_item(title="With attachments")
    png = await svc.add_attachment(item["id"], _upload("logo.png", PNG_BYTES))
    txt = await svc.add_attachment(item["id"], _upload("notes.md", b"# Notes\nhello"))

    assert png["mime"] == "image/png"
    assert txt["ext"] == "md"

    listed = await svc.list_attachments(item["id"])
    assert len(listed) == 2

    path, row = await svc.resolve_attachment_file(png["id"])
    assert path is not None and path.exists()
    assert row["item_id"] == item["id"]


async def test_unsupported_attachment_rejected():
    item = await svc.create_item(title="x")
    with pytest.raises(svc.PromptLibraryError) as exc:
        await svc.add_attachment(item["id"], _upload("malware.exe", b"MZ..."))
    assert exc.value.code == "UNSUPPORTED_ATTACHMENT_TYPE"
    assert exc.value.status_code == 415


async def test_oversized_attachment_rejected(monkeypatch):
    item = await svc.create_item(title="x")
    monkeypatch.setitem(svc._ATTACHMENT_TYPES, "txt", ("text/plain", "text", 8))
    with pytest.raises(svc.PromptLibraryError) as exc:
        await svc.add_attachment(item["id"], _upload("big.txt", b"way over eight bytes"))
    assert exc.value.code == "ATTACHMENT_TOO_LARGE"
    assert exc.value.status_code == 413


async def test_content_mismatch_rejected():
    item = await svc.create_item(title="x")
    with pytest.raises(svc.PromptLibraryError) as exc:
        await svc.add_attachment(item["id"], _upload("fake.png", b"this is not a png"))
    assert exc.value.code == "ATTACHMENT_CONTENT_MISMATCH"


async def test_path_traversal_guard_on_resolve():
    item = await svc.create_item(title="x")
    # Directly craft a row whose local_path escapes the attachment store.
    att_id = "evil123"
    await crud.create_prompt_library_attachment(
        att_id, item_id=item["id"], file_name="passwd", mime="text/plain", ext="txt",
        size_bytes=1, local_path="C:/Windows/System32/drivers/etc/hosts",
    )
    path, row = await svc.resolve_attachment_file(att_id)
    assert path is None  # containment guard refuses paths outside the store
    assert row is not None


async def test_delete_attachment_removes_file():
    item = await svc.create_item(title="x")
    att = await svc.add_attachment(item["id"], _upload("logo.png", PNG_BYTES))
    path, _ = await svc.resolve_attachment_file(att["id"])
    assert path.exists()
    assert await svc.delete_attachment(att["id"]) is True
    assert not path.exists()
    assert await crud.get_prompt_library_attachment(att["id"]) is None


async def test_delete_item_cleans_attachment_files():
    item = await svc.create_item(title="x")
    att = await svc.add_attachment(item["id"], _upload("logo.png", PNG_BYTES))
    path, _ = await svc.resolve_attachment_file(att["id"])
    assert path.exists()
    await svc.delete_item(item["id"])
    assert not path.exists()


def test_prompt_library_has_no_generation_dependency():
    """Hard decoupling law: the library imports NOTHING from generation /
    compiler / Product Truth / Copy V2 / Montage."""
    forbidden = [
        "montage", "flow", "make_video", "agent_video",
        "workspace_execution_package", "workspace_generation_package",
        "copy_execution_resolver", "copy_register", "product_truth_lock",
        "prompt_compiler", "canonical_prompt", "product_visual_grounding",
    ]
    for rel in ("agent/services/prompt_library_service.py", "agent/api/prompt_library.py"):
        source = Path(rel).read_text(encoding="utf-8")
        import_lines = [
            ln for ln in source.splitlines()
            if ln.strip().startswith("import ") or ln.strip().startswith("from ")
        ]
        blob = "\n".join(import_lines)
        for token in forbidden:
            assert token not in blob, f"{rel} illegally imports '{token}'"
