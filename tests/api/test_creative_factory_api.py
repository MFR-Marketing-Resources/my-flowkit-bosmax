"""HTTP smoke for the Creative Factory router (provider-free).

Proves the router is wired and auth-gated, that reads and the governed
confirmation gate behave, and that the audited manual-review endpoint resolves a
REVIEW_REQUIRED benefit — all without a single provider call. The build path
itself is proven at the service layer with injected fakes and is intentionally
NOT exercised here (no provider risk).
"""

from __future__ import annotations

import secrets

import httpx
import pytest
from httpx import ASGITransport

from agent.db.schema import get_db
from agent.main import app
from agent.services import ai_copy_provider_adapter as adapter
from tests.conftest import make_product_copy_eligible, seed_product_ready

SUPPORTED = "melembapkan kulit sepanjang hari"
UNSUPPORTED = "zzz qwerty unrelated random tokens 12345"

_OWNER_EMAIL = f"cf-owner-{secrets.token_hex(6)}@example.test"
_OWNER_PASSWORD = f"Aa{secrets.token_urlsafe(18)}7"


def _anon_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _owner_client() -> httpx.AsyncClient:
    client = _anon_client()
    r = await client.get("/api/auth/csrf")
    assert r.status_code == 200
    csrf = client.cookies.get("bosmax_csrf")
    assert csrf
    setup = await client.post(
        "/api/auth/setup-owner",
        json={
            "display_name": "CF Test Owner",
            "email": _OWNER_EMAIL,
            "password": _OWNER_PASSWORD,
            "password_confirmation": _OWNER_PASSWORD,
        },
        headers={"X-CSRF-Token": str(csrf)},
    )
    if setup.status_code == 409:
        login = await client.post(
            "/api/auth/login",
            json={"email": _OWNER_EMAIL, "password": _OWNER_PASSWORD},
            headers={"X-CSRF-Token": str(csrf)},
        )
        assert login.status_code == 200, login.text
    else:
        assert setup.status_code == 200, setup.text
    client.headers.update({"X-CSRF-Token": str(client.cookies.get("bosmax_csrf"))})
    return client


def _real_calls():
    return adapter.provider_call_receipt()["request_count_since_process_start"]


async def _seed(product_id):
    db = await get_db()
    await seed_product_ready(db, product_id)
    await make_product_copy_eligible(product_id)


async def test_mutation_requires_authentication():
    async with _anon_client() as client:
        # CSRF only, no authenticated session
        await client.get("/api/auth/csrf")
        resp = await client.post(
            "/api/creative-factory/benefits",
            json={"product_id": "p", "benefit": SUPPORTED},
            headers={"X-CSRF-Token": str(client.cookies.get("bosmax_csrf") or "")},
        )
        # 401 (auth required) / 403 (permission) / 428 (first-owner setup required)
        # all prove the mutation is BLOCKED without an authenticated session.
        assert resp.status_code in (401, 403, 428), resp.text


async def test_registry_reads_and_confirmation_gate_are_provider_free():
    product_id = "prod_api_cf"
    await _seed(product_id)
    before = _real_calls()
    client = await _owner_client()
    try:
        created = await client.post(
            "/api/creative-factory/benefits",
            json={"product_id": product_id, "benefit": SUPPORTED, "usage_hint": "Sapu pada kulit"},
        )
        assert created.status_code == 200, created.text
        assert created.json()["status"] == "VERIFIED"

        listing = await client.get(f"/api/creative-factory/benefits?product_id={product_id}")
        assert listing.status_code == 200
        assert listing.json()["count"] == 1

        capacity = await client.get(f"/api/creative-factory/capacity?product_id={product_id}")
        assert capacity.status_code == 200
        assert capacity.json()["verified_benefits"] == 1

        plan = await client.get(f"/api/creative-factory/build-plan?product_id={product_id}")
        assert plan.status_code == 200
        assert plan.json()["verified_benefit_count"] == 1
        assert plan.json()["expected_provider_calls"] == 1

        # governed batch: refuses without explicit confirmation
        batch = await client.post(
            "/api/creative-factory/build-verified",
            json={"product_id": product_id, "confirm": False},
        )
        assert batch.status_code == 409
        assert batch.json()["detail"]["error"] == "CONFIRMATION_REQUIRED"
    finally:
        await client.aclose()
    assert _real_calls() == before  # nothing above touched the provider


async def test_manual_review_resolution_via_api():
    product_id = "prod_api_review"
    await _seed(product_id)
    before = _real_calls()
    client = await _owner_client()
    try:
        created = await client.post(
            "/api/creative-factory/benefits",
            json={"product_id": product_id, "benefit": UNSUPPORTED},
        )
        assert created.status_code == 200
        benefit_id = created.json()["benefit_id"]
        assert created.json()["status"] == "REVIEW_REQUIRED"

        ctx = await client.get(f"/api/creative-factory/benefits/{benefit_id}/review-context")
        assert ctx.status_code == 200
        assert ctx.json()["resolvable"] is True

        verify = await client.post(
            f"/api/creative-factory/benefits/{benefit_id}/review",
            json={"action": "VERIFY", "reviewer_note": "Valid paraphrase; approved."},
        )
        assert verify.status_code == 200, verify.text
        assert verify.json()["status"] == "VERIFIED"
        assert verify.json()["provenance"]["resolution"] == "MANUAL"
    finally:
        await client.aclose()
    assert _real_calls() == before  # manual resolution is deterministic
