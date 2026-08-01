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
