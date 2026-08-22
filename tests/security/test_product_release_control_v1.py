from __future__ import annotations

import secrets

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from agent.db.schema import get_db
from agent.main import _CALLBACK_SECRET, app
from agent.services import access_control_service as access
from agent.services import product_release_service as release_service
from agent.services import creative_production_scheduler_service as scheduler_service
from agent.services.creative_production_plan_service import CreativeProductionError
from agent.security.access_control import required_permission
from agent.api.flow import _assert_public_remote_url, _safe_local_upload_path


def _password() -> str:
    return f"Aa{secrets.token_urlsafe(18)}7"


def _email(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6)}@example.test"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _csrf(client: httpx.AsyncClient) -> str:
    response = await client.get("/api/auth/csrf")
    assert response.status_code == 200
    token = client.cookies.get(access.CSRF_COOKIE_NAME)
    assert token
    return str(token)


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> httpx.Response:
    token = await _csrf(client)
    return await client.post(path, json=body, headers={"X-CSRF-Token": token})


@pytest_asyncio.fixture(autouse=True)
async def isolated_access_tables():
    db = await get_db()
    for table in (
        "access_audit_event",
        "auth_session",
        "auth_setup_token",
        "user_role",
        "user_account",
        "staff_profile",
    ):
        await db.execute(f"DELETE FROM {table}")
    await db.commit()
    yield


@pytest.mark.asyncio
async def test_product_release_control_is_owner_only_and_audited_boundary_is_separate():
    owner_password = _password()
    manager_password = _password()
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Release Owner",
                "email": _email("release-owner"),
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200
        invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Release Manager", "email": _email("release-manager"), "role_codes": ["MANAGER"]},
        )
        assert invite.status_code == 201

        async with await _client() as manager:
            activated = await _post(
                manager,
                "/api/auth/activate-account",
                {
                    "token": invite.json()["setup_token"],
                    "password": manager_password,
                    "password_confirmation": manager_password,
                },
            )
            assert activated.status_code == 200
            assert "products.release" not in activated.json()["user"]["permissions"]
            denied_read = await manager.get("/api/product-release")
            assert denied_read.status_code == 403
            assert denied_read.json()["error"] == "PERMISSION_DENIED"
            denied_mutation = await _post(
                manager,
                "/api/product-release/product-does-not-exist/release",
                {},
            )
            assert denied_mutation.status_code == 403

        owner_read = await owner.get("/api/product-release")
        assert owner_read.status_code == 200
        assert "items" in owner_read.json()
        missing = await _post(owner, "/api/product-release/product-does-not-exist/release", {})
        assert missing.status_code == 404
        assert missing.json()["detail"]["error"] == "PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_extension_callback_requires_server_issued_secret():
    async with await _client() as client:
        missing_secret = await client.post("/api/ext/callback", json={"id": "pending"})
        assert missing_secret.status_code == 401
        assert missing_secret.json()["detail"]["error"] == "CALLBACK_AUTHENTICATION_REQUIRED"

        valid_secret = await client.post(
            "/api/ext/callback",
            json={"id": "pending"},
            headers={"X-Callback-Secret": _CALLBACK_SECRET},
        )
        assert valid_secret.status_code == 200
        assert valid_secret.json()["ok"] is False


@pytest.mark.asyncio
async def test_authenticated_faceless_direct_api_rejects_missing_product_before_lane_work():
    owner_password = _password()
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Runtime Owner",
                "email": _email("runtime-owner"),
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200
        response = await _post(
            owner,
            "/api/faceless/validate",
            {
                "product_id": "product-not-in-catalog",
                "staff_id": setup.json()["user"]["staff_id"],
                "model": "veo_3_1_fast",
                "duration_seconds": 8,
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_release_of_blocked_product_is_rejected_before_mutation(monkeypatch):
    owner_password = _password()

    async def blocked_state(_product_id: str):
        return {
            "product": {"id": _product_id, "lifecycle_status": "ACTIVE"},
            "staff_release_status": "RELEASED",
            "minimum_eligibility_status": "BLOCKED",
            "operationally_visible": False,
            "visibility_reason": "RELEASED_BUT_BLOCKED",
            "blocker_codes": ["VISUAL_CUTOUT_NOT_READY"],
        }

    monkeypatch.setattr(release_service, "load_product_release_state", blocked_state)
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Blocked Release Owner",
                "email": _email("blocked-owner"),
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200
        response = await _post(owner, "/api/product-release/product-blocked/release", {})
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "PRODUCT_NOT_READY_FOR_RELEASE"
        assert response.json()["detail"]["details"]["blocker_codes"] == ["VISUAL_CUTOUT_NOT_READY"]


@pytest.mark.asyncio
async def test_production_studio_dispatch_rechecks_release_before_acquiring_lease(monkeypatch):
    provider_boundary_reached = False

    async def blocked_state(_product_id: str):
        return {
            "staff_release_status": "RELEASED",
            "minimum_eligibility_status": "BLOCKED",
            "operationally_visible": False,
            "visibility_reason": "RELEASED_BUT_BLOCKED",
            "blocker_codes": ["VISUAL_CUTOUT_NOT_READY"],
        }

    async def acquire_lease(*_args, **_kwargs):
        nonlocal provider_boundary_reached
        provider_boundary_reached = True
        raise AssertionError("release gate must run before dispatch lease acquisition")

    monkeypatch.setattr(release_service, "load_product_release_state", blocked_state)
    monkeypatch.setattr(scheduler_service, "_acquire_item_lease", acquire_lease)

    with pytest.raises(CreativeProductionError) as exc_info:
        await scheduler_service._dispatch_attempt(
            {"item_id": "item-1", "product_id": "product-1"},
            {"attempt_id": "attempt-1"},
            credit_confirmation="",
        )

    assert exc_info.value.code == "PRODUCT_NOT_OPERATIONALLY_VISIBLE"
    assert exc_info.value.details["blocker_codes"] == ["VISUAL_CUTOUT_NOT_READY"]
    assert provider_boundary_reached is False


def test_release_permission_and_production_route_classification_are_separate():
    assert required_permission("/api/product-release", "GET") == "products.release"
    assert required_permission("/api/product-release/p-1/hide", "POST") == "products.release"
    assert required_permission("/api/products/p-1/unarchive", "POST") == "products.archive"
    assert required_permission("/api/bulk-generation", "POST") == "jobs.control"
    assert required_permission("/api/batches", "POST") == "jobs.control"


def test_remote_materialization_rejects_private_targets_and_local_path_escape(tmp_path):
    with pytest.raises(ValueError, match="PRIVATE_TARGET"):
        _assert_public_remote_url("http://127.0.0.1:8080/internal")
    outside = tmp_path / "secret.bin"
    outside.write_bytes(b"not an image")
    with pytest.raises(Exception) as exc_info:
        _safe_local_upload_path(str(outside))
    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_context_independent_worker_release_assertion_fails_closed(monkeypatch):
    async def hidden_state(_product_id: str):
        return {
            "staff_release_status": "HIDDEN",
            "minimum_eligibility_status": "ELIGIBLE",
            "operationally_visible": False,
            "visibility_reason": "OWNER_RELEASE_REQUIRED",
            "blocker_codes": [],
        }

    monkeypatch.setattr(release_service, "load_product_release_state", hidden_state)
    with pytest.raises(release_service.ProductOperationalVisibilityError) as exc_info:
        await release_service.require_product_operational_visibility(
            "product-hidden", lane="WORKER_PROVIDER"
        )
    assert exc_info.value.code == "PRODUCT_NOT_OPERATIONALLY_VISIBLE"
