"""B-586-05: a failing intelligence ensure must never leave a half-committed product.

Unlike Smart Registration, the products.py lanes had no compensation at all: create_product
commits, then ensure runs, so a failure left a canonical product with no intelligence
record and no error trail.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agent.db import crud
from agent.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _count(title: str) -> int:
    rows = await crud.list_products(limit=5000, include_archived=True)
    return sum(1 for r in rows if r.get("raw_product_title") == title)


@pytest.mark.asyncio
async def test_manual_create_leaves_no_orphan_when_intelligence_fails(monkeypatch):
    from agent.api import products as api

    title = "Orphan Prevention Fixture A"

    async def boom(*a, **k):
        raise RuntimeError("intelligence store offline")

    monkeypatch.setattr(api, "ensure_product_intelligence", boom)
    async with await _client() as c:
        r = await c.post("/api/products/manual", json={
            "raw_product_title": title, "category": "Beauty"})
    assert r.status_code == 500
    assert "COMPENSATED" in r.json()["detail"]
    assert await _count(title) == 0, "an orphan product survived a failed ensure"


@pytest.mark.asyncio
async def test_tiktok_import_leaves_no_orphan_when_intelligence_fails(monkeypatch):
    from agent.api import products as api

    async def boom(*a, **k):
        raise RuntimeError("intelligence store offline")

    before = len(await crud.list_products(limit=5000, include_archived=True))
    monkeypatch.setattr(api, "ensure_product_intelligence", boom)
    async with await _client() as c:
        r = await c.post("/api/products/import-tiktokshop", json={
            "url": "https://shop-my.tiktok.com/pdp/orphan-b",
            "raw_product_title": "Orphan Prevention Fixture B"})
    assert r.status_code == 500
    after = len(await crud.list_products(limit=5000, include_archived=True))
    assert after == before, "tiktok import left an orphan product"


@pytest.mark.asyncio
async def test_a_successful_manual_create_always_has_an_intelligence_record():
    from agent.db.schema import get_db

    async with await _client() as c:
        r = await c.post("/api/products/manual", json={
            "raw_product_title": "Orphan Prevention Fixture C",
            "category": "Beauty", "usage_text": "wipe it"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=?", (pid,))
    n = (await cur.fetchone())[0]
    await cur.close()
    assert n == 1, "a committed product ended without an intelligence record"


# ── B-586-05: compensation must be a real compare-and-swap ────────────────────
# The previous shape read the row, compared updated_at in Python, then issued a separate
# UPDATE. These tests target the two things that made it unsound: the window between the
# check and the write, and the fact that nothing verified the write matched anything.

async def _mk_product(title: str, **cols) -> dict:
    return await crud.create_product(raw_product_title=title, source="MANUAL", **cols)


@pytest.mark.asyncio
async def test_cas_restores_the_complete_before_state_when_nothing_moved():
    """rowcount == 1: the guard matched, so every changed column goes back."""
    product = await _mk_product("CAS Fixture Restore", brand="Before", shop_name="ShopA")
    pid = product["id"]

    applied = await crud.update_product(pid, brand="After", shop_name="ShopB")
    ok = await crud.compare_and_swap_product(
        pid,
        expected={"updated_at": applied["updated_at"], "brand": "After",
                  "shop_name": "ShopB"},
        changes={"brand": "Before", "shop_name": "ShopA"})
    assert ok is True

    row = await crud.get_product(pid)
    assert row["brand"] == "Before" and row["shop_name"] == "ShopA"


@pytest.mark.asyncio
async def test_cas_refuses_and_preserves_newer_work_when_the_row_moved():
    """rowcount == 0: someone else edited the row, so the restore must NOT happen."""
    product = await _mk_product("CAS Fixture Refuse", brand="Before")
    pid = product["id"]

    applied = await crud.update_product(pid, brand="After")
    # a concurrent operator edit lands before compensation runs
    await crud.update_product(pid, brand="OperatorEdit")

    ok = await crud.compare_and_swap_product(
        pid,
        expected={"updated_at": applied["updated_at"], "brand": "After"},
        changes={"brand": "Before"})
    assert ok is False, "CAS matched a row that had moved underneath it"

    row = await crud.get_product(pid)
    assert row["brand"] == "OperatorEdit", "a rollback clobbered a concurrent edit"


@pytest.mark.asyncio
async def test_cas_guard_is_null_safe():
    """A NULL guard column must be comparable. With `=` instead of `IS` it never matches,
    so compensation would silently never fire for any product with a NULL column."""
    product = await _mk_product("CAS Fixture Null", brand=None)
    pid = product["id"]
    applied = await crud.get_product(pid)
    assert applied["brand"] is None

    ok = await crud.compare_and_swap_product(
        pid, expected={"brand": None}, changes={"brand": "Set"})
    assert ok is True, "a NULL-valued guard column could not be matched"
    assert (await crud.get_product(pid))["brand"] == "Set"


@pytest.mark.asyncio
async def test_conditional_delete_refuses_to_remove_a_product_edited_after_creation():
    product = await _mk_product("CAS Fixture Delete Guard")
    pid = product["id"]
    # The full row is the guard. `_now()` only has second resolution, so an edit in the
    # same second as the insert leaves updated_at identical — a version-only guard would
    # not notice it and would delete the operator's work.
    as_created = await crud.get_product(pid)
    await crud.update_product(pid, brand="AdoptedByOperator")

    removed = await crud.compare_and_delete_product(pid, expected=as_created)
    assert removed is False
    assert await crud.get_product(pid) is not None, (
        "compensation deleted a product that had been edited after creation")

    still_there = await crud.get_product(pid)
    removed_now = await crud.compare_and_delete_product(
        pid, expected={"updated_at": still_there["updated_at"]})
    assert removed_now is True
    assert await crud.get_product(pid) is None


@pytest.mark.asyncio
async def test_map_persist_create_leaves_no_orphan_when_intelligence_fails(monkeypatch):
    from agent.api import products as api

    async def boom(*a, **k):
        raise RuntimeError("intelligence store offline")

    title = "Orphan Prevention Fixture Map"
    monkeypatch.setattr(api, "ensure_product_intelligence", boom)
    async with await _client() as c:
        r = await c.post("/api/products/map", json={
            "product_name": title, "persist": True, "source": "MANUAL"})
    assert r.status_code == 500
    assert "COMPENSATED" in r.json()["detail"]
    assert await _count(title) == 0, "map persist left an orphan product"


@pytest.mark.asyncio
async def test_physics_map_persist_rolls_back_the_columns_it_wrote(monkeypatch):
    """B-586-05 + B-586-06. This lane writes physics/readiness columns that the request
    payload never names. The payload-keyed restore could not reach them, so a failed
    ensure used to leave the persisted physics behind."""
    from agent.api import products as api

    product = await _mk_product(
        "Physics Rollback Fixture", physics_class="ORIGINAL_CLASS",
        product_scale="ORIGINAL_SCALE", prompt_readiness_status="ORIGINAL_STATUS")
    pid = product["id"]
    before = await crud.get_product(pid)

    async def boom(*a, **k):
        raise RuntimeError("intelligence store offline")

    monkeypatch.setattr(api, "ensure_product_intelligence", boom)
    async with await _client() as c:
        r = await c.post("/api/products/physics-map", json={
            "product_id": pid, "persist": True})
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "RESTORED" in detail or "NOTHING_TO_RESTORE" in detail, detail

    after = await crud.get_product(pid)
    for column in ("physics_class", "product_scale", "prompt_readiness_status",
                   "recommended_grip", "section_5_product_physics_prompt",
                   "section_5_physics_hint"):
        assert after[column] == before[column], (
            f"{column} kept the failed operation's value: "
            f"{before[column]!r} -> {after[column]!r}")


@pytest.mark.asyncio
async def test_fastmoss_reimport_failure_restores_the_existing_product(monkeypatch):
    """The re-import lane updates an EXISTING product, so it must restore, never delete."""
    from agent.api import products as api

    product = await _mk_product(
        "FastMoss Reimport Fixture", brand="OriginalBrand", shop_name="OriginalShop")
    pid = product["id"]
    prior = await crud.get_product(pid)

    updated = await crud.update_product(
        pid, brand="ImportedBrand", shop_name="ImportedShop")

    async def boom(*a, **k):
        raise RuntimeError("intelligence store offline")

    monkeypatch.setattr(api, "ensure_product_intelligence", boom)
    with pytest.raises(Exception) as excinfo:
        await api._ensure_intake_intelligence(
            updated, {"brand": "ImportedBrand"},
            lane="PRODUCTS_FASTMOSS_REIMPORT", prior=prior)
    assert "RESTORED" in str(getattr(excinfo.value, "detail", excinfo.value))

    after = await crud.get_product(pid)
    assert after["brand"] == "OriginalBrand"
    assert after["shop_name"] == "OriginalShop", (
        "a column the payload never named kept the failed import's value")
    assert after is not None, "the re-import lane deleted a pre-existing product"


@pytest.mark.asyncio
async def test_fastmoss_create_failure_removes_only_its_own_product(monkeypatch):
    from agent.api import products as api

    keep = await _mk_product("FastMoss Bystander", brand="Untouched")
    created = await _mk_product("FastMoss Create Fixture")

    async def boom(*a, **k):
        raise RuntimeError("intelligence store offline")

    monkeypatch.setattr(api, "ensure_product_intelligence", boom)
    with pytest.raises(Exception):
        await api._ensure_intake_intelligence(
            created, {"raw_product_title": "FastMoss Create Fixture"},
            lane="PRODUCTS_FASTMOSS_IMPORT", created=True)

    assert await crud.get_product(created["id"]) is None
    bystander = await crud.get_product(keep["id"])
    assert bystander is not None and bystander["brand"] == "Untouched", (
        "compensation reached beyond the product it created")


@pytest.mark.asyncio
async def test_a_concurrent_operator_edit_during_ensure_yields_CAS_REFUSED(monkeypatch):
    """The exact race the old check-then-write could not see.

    The edit lands DURING the ensure call — after the applied-after snapshot was taken and
    before compensation runs. The old code read the row again at compensation time and
    compared it to a stale `product` dict; here the compensation must refuse outright and
    say so, rather than reporting RESTORED while overwriting the operator.
    """
    from agent.api import products as api

    product = await _mk_product("CAS Race Fixture", brand="OriginalBrand")
    pid = product["id"]
    prior = await crud.get_product(pid)
    applied = await crud.update_product(pid, brand="ImportedBrand")

    async def boom_then_operator_edits(*a, **k):
        # a different operator saves the product while our ensure is still running
        await crud.update_product(pid, brand="OperatorTypedThis")
        raise RuntimeError("intelligence store offline")

    monkeypatch.setattr(api, "ensure_product_intelligence", boom_then_operator_edits)
    with pytest.raises(Exception) as excinfo:
        await api._ensure_intake_intelligence(
            applied, {"brand": "ImportedBrand"},
            lane="PRODUCTS_FASTMOSS_REIMPORT", prior=prior)
    detail = str(getattr(excinfo.value, "detail", excinfo.value))
    assert "CAS_REFUSED" in detail, detail
    assert "RESTORED" not in detail, "claimed RESTORED while refusing to restore"

    after = await crud.get_product(pid)
    assert after["brand"] == "OperatorTypedThis", (
        "the rollback clobbered a concurrent operator edit")


@pytest.mark.asyncio
async def test_created_product_edited_during_ensure_is_not_deleted(monkeypatch):
    """Created-product compensation is conditional too."""
    from agent.api import products as api

    created = await _mk_product("CAS Race Create Fixture")
    pid = created["id"]

    async def boom_then_operator_edits(*a, **k):
        await crud.update_product(pid, brand="OperatorAdoptedIt")
        raise RuntimeError("intelligence store offline")

    monkeypatch.setattr(api, "ensure_product_intelligence", boom_then_operator_edits)
    with pytest.raises(Exception) as excinfo:
        await api._ensure_intake_intelligence(
            created, {"raw_product_title": "CAS Race Create Fixture"},
            lane="PRODUCTS_MANUAL", created=True)
    detail = str(getattr(excinfo.value, "detail", excinfo.value))
    assert "CAS_REFUSED" in detail, detail

    survivor = await crud.get_product(pid)
    assert survivor is not None, "deleted a product another operator had adopted"
    assert survivor["brand"] == "OperatorAdoptedIt"


@pytest.mark.asyncio
async def test_no_lane_leaves_an_orphan_draft_or_provenance_row():
    """Successful or failed, no draft may reference a product that no longer exists."""
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_draft d "
        "LEFT JOIN product p ON p.id = d.product_id WHERE p.id IS NULL")
    orphan_drafts = (await cur.fetchone())[0]
    await cur.close()
    cur = await db.execute(
        "SELECT COUNT(*) FROM product_intelligence_review_field_provenance f "
        "LEFT JOIN product_intelligence_review_draft d ON d.draft_id = f.draft_id "
        "WHERE d.draft_id IS NULL")
    orphan_prov = (await cur.fetchone())[0]
    await cur.close()
    assert orphan_drafts == 0, f"{orphan_drafts} drafts reference a deleted product"
    assert orphan_prov == 0, f"{orphan_prov} provenance rows reference a deleted draft"
