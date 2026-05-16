import pytest
import httpx

@pytest.mark.asyncio
async def test_api_readiness_herbs():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8100/api") as client:
        resp = await client.get("/products/38a6bacd-2427-42ca-8409-2a78c7f0520c/prompt-readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["product_id"] == "38a6bacd-2427-42ca-8409-2a78c7f0520c"
        assert data["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"

@pytest.mark.asyncio
async def test_api_readiness_archived():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8100/api") as client:
        resp = await client.get("/products/cfb24f8f-a662-4a16-8bad-de77e35be510/prompt-readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_status"] == "ARCHIVED"
        assert "PRODUCT_ARCHIVED" in data["blockers"]
