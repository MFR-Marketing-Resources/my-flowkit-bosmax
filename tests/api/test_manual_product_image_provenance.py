"""B-586-07: an operator's uploaded image must reach the intelligence evidence.

`/products/manual` previously called ensure_product_intelligence BEFORE
`_save_manual_image`, so `local_image_path` did not exist yet and the operator's own
image evidence never reached the draft or its field provenance.
"""
from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from agent.db.schema import get_db
from agent.main import app

# a 1x1 PNG
_PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")).decode()


@pytest.mark.asyncio
async def test_manual_upload_image_reaches_the_intelligence_evidence():
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        r = await c.post("/api/products/manual", json={
            "raw_product_title": "Manual Image Provenance Fixture 50ml",
            "product_short_name": "Manual Image Fixture",
            "category": "Beauty",
            "usage_text": "Wipe with a damp cloth.",
            "image_base64": _PNG,
            "image_filename": "fixture.png",
        })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    db = await get_db()
    cur = await db.execute(
        "SELECT image_evidence_json FROM product_intelligence_review_draft "
        "WHERE product_id=?", (pid,))
    row = await cur.fetchone()
    await cur.close()
    assert row is not None, "manual product created without an intelligence draft"
    evidence = str(row[0] or "")
    assert "local_image_path" in evidence, (
        "the uploaded image never reached the intelligence evidence — ensure ran before "
        "the image was cached")

    cur = await db.execute(
        "SELECT local_image_path FROM product WHERE id=?", (pid,))
    stored = await cur.fetchone()
    await cur.close()
    assert stored[0], "image was not cached on the product at all"
