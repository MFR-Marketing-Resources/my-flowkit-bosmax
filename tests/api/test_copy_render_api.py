"""HTTP smoke for the Copy Renderer router (provider-free).

Proves the router is wired, that BOTH reads and mutations are auth-gated
(amendment 8), and that the full create→generate→lock→finalize→selected path works
over HTTP with an injected stitch fake — without a single real provider call.
"""

from __future__ import annotations

import secrets

import httpx
from httpx import ASGITransport

from agent.main import app
from agent.services import copy_render_service as svc
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls

_OWNER_EMAIL = f"cr-owner-{secrets.token_hex(6)}@example.test"
_OWNER_PASSWORD = f"Aa{secrets.token_urlsafe(18)}7"


def _anon_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _owner_client() -> httpx.AsyncClient:
    client = _anon_client()
    r = await client.get("/api/auth/csrf")
    assert r.status_code == 200
    csrf = client.cookies.get("bosmax_csrf")
    setup = await client.post(
        "/api/auth/setup-owner",
        json={"display_name": "CR Test Owner", "email": _OWNER_EMAIL,
              "password": _OWNER_PASSWORD, "password_confirmation": _OWNER_PASSWORD},
        headers={"X-CSRF-Token": str(csrf)},
    )
    if setup.status_code == 409:
        login = await client.post(
            "/api/auth/login", json={"email": _OWNER_EMAIL, "password": _OWNER_PASSWORD},
            headers={"X-CSRF-Token": str(csrf)})
        assert login.status_code == 200, login.text
    else:
        assert setup.status_code == 200, setup.text
    client.headers.update({"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
    return client


async def test_mutation_requires_authentication():
    async with _anon_client() as client:
        await client.get("/api/auth/csrf")
        resp = await client.post(
            "/api/copy-render/sessions",
            json={"product_id": "p", "benefit_id": "b", "lane": "HYBRID",
                  "target_count": 3, "duration_seconds": 16},
            headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf") or "")})
        assert resp.status_code in (401, 403, 428), resp.text


async def test_reads_require_authentication():
    # Amendment 8: copy-render reads require an authenticated human session.
    async with _anon_client() as client:
        resp = await client.get("/api/copy-render/sessions/CRS_does_not_exist")
        assert resp.status_code in (401, 403, 428), resp.text


async def test_full_http_flow_is_provider_free(monkeypatch):
    boot = await bootstrap_ready_benefit(product_id="prod_api_cr")
    fake = StitchFake()
    monkeypatch.setattr(svc, "_default_provider", lambda: fake)
    before = real_calls()

    client = await _owner_client()
    try:
        created = await client.post(
            "/api/copy-render/sessions",
            json={"product_id": boot["product_id"], "benefit_id": boot["benefit_id"],
                  "lane": "HYBRID", "target_count": 2, "duration_seconds": 16},
            headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]
        assert created.json()["status"] == "OPEN"

        # authenticated read works
        got = await client.get(f"/api/copy-render/sessions/{sid}")
        assert got.status_code == 200 and got.json()["session_id"] == sid

        gen = await client.post(
            f"/api/copy-render/sessions/{sid}/suggestions",
            json={"request_id": "req-api-000001"},
            headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
        assert gen.status_code == 200, gen.text
        body = gen.json()
        assert body["provider_calls"] == 1
        shown = [c for c in body["candidates"] if c["status"] == "SHOWN"]
        assert len(shown) == 5

        for cid in [c["candidate_id"] for c in shown[:2]]:
            lk = await client.post(f"/api/copy-render/candidates/{cid}/lock",
                                   headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
            assert lk.status_code == 200, lk.text
        assert lk.json()["status"] == "TARGET_COMPLETE"

        fin = await client.post(f"/api/copy-render/sessions/{sid}/finalize",
                                headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
        assert fin.status_code == 200 and fin.json()["status"] == "FINALIZED"

        sel = await client.get(f"/api/copy-render/sessions/{sid}/selected")
        assert sel.status_code == 200 and sel.json()["count"] == 2
    finally:
        await client.aclose()

    assert fake.calls == 1              # exactly one logical stitch call over the flow
    assert real_calls() == before       # and NO real provider HTTP call


async def test_lane_scope_rejected_at_api_boundary():
    # A non-HYBRID/FACELESS lane is rejected by the request contract itself.
    boot = await bootstrap_ready_benefit(product_id="prod_api_lane")
    client = await _owner_client()
    try:
        resp = await client.post(
            "/api/copy-render/sessions",
            json={"product_id": boot["product_id"], "benefit_id": boot["benefit_id"],
                  "lane": "T2V", "target_count": 2, "duration_seconds": 16},
            headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
        assert resp.status_code == 422, resp.text
    finally:
        await client.aclose()
