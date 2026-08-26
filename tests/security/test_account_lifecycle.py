from __future__ import annotations

import json
import secrets

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from agent.db.schema import get_db
from agent.main import app
from agent.security.access_control import required_permission
from agent.services import access_control_service as access


def _password(label: str = "Password") -> str:
    return f"{label}Aa{secrets.token_urlsafe(18)}7"


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
    return await client.post(path, json=body, headers={"X-CSRF-Token": await _csrf(client)})


async def _setup_owner(client: httpx.AsyncClient, password: str) -> httpx.Response:
    return await _post(
        client,
        "/api/auth/setup-owner",
        {
            "display_name": "Lifecycle Owner",
            "email": _email("owner"),
            "password": password,
            "password_confirmation": password,
        },
    )


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
async def test_invite_activation_is_fail_closed_then_enables_operator_readiness():
    owner_password = _password("Owner")
    operator_password = _password("Operator")
    operator_email = _email("operator")

    async with await _client() as owner:
        setup = await _setup_owner(owner, owner_password)
        assert setup.status_code == 200
        invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Lifecycle Operator", "email": operator_email, "role_codes": ["OPERATOR"]},
        )
        assert invite.status_code == 201
        invite_payload = invite.json()
        setup_token = invite_payload["setup_token"]
        operator_id = invite_payload["user"]["user_id"]
        assert invite_payload["user"]["account_status"] == "INVITED"
        assert invite_payload["user"]["staff_active"] is True
        assert invite_payload["user"]["role_codes"] == ["OPERATOR"]

        db = await get_db()
        account = await (
            await db.execute("SELECT password_hash, account_status FROM user_account WHERE user_id=?", (operator_id,))
        ).fetchone()
        assert account is not None
        assert account[0] is None
        assert account[1] == "INVITED"

        async with await _client() as operator:
            before_activation = await _post(
                operator,
                "/api/auth/login",
                {"email": operator_email, "password": operator_password},
            )
            assert before_activation.status_code == 401
            assert before_activation.json()["detail"]["error"] == "LOGIN_FAILED"

            activated = await _post(
                operator,
                "/api/auth/activate-account",
                {"token": setup_token, "password": operator_password, "password_confirmation": operator_password},
            )
            assert activated.status_code == 200
            activated_user = activated.json()["user"]
            assert activated_user["account_status"] == "ACTIVE"
            assert activated_user["role_codes"] == ["OPERATOR"]
            assert {"production.read", "production.execute"}.issubset(activated_user["permissions"])
            assert setup_token not in activated.text
            assert operator_password not in activated.text

            current = await operator.get("/api/auth/me")
            assert current.status_code == 200
            assert current.json()["authenticated"] is True
            assert current.json()["user"]["role_codes"] == ["OPERATOR"]

            readiness = await operator.get(
                "/api/flow/direct-video-readiness",
                params={
                    "mode": "F2V",
                    "model": "veo_3_1_lite",
                    "duration_s": 8,
                    "aspect": "9:16",
                    "ref_count": 1,
                    "count": 1,
                },
            )
            assert readiness.status_code == 200, readiness.text
            assert required_permission("/api/flow/direct-video-readiness", "GET") == "production.read"
            assert required_permission("/api/flow/generate", "POST") == "production.execute"

            unused_password = _password("NeverUsed")
            reused = await _post(
                operator,
                "/api/auth/activate-account",
                {"token": setup_token, "password": unused_password, "password_confirmation": unused_password},
            )
            assert reused.status_code == 400
            assert reused.json()["detail"]["error"] == "TOKEN_INVALID_OR_EXPIRED"

    events = await access.list_audit_events()
    serialized_events = json.dumps(events, sort_keys=True)
    assert setup_token not in serialized_events
    assert operator_password not in serialized_events
    db = await get_db()
    stored_token = await (
        await db.execute("SELECT token_hash, used_at FROM auth_setup_token WHERE user_id=?", (operator_id,))
    ).fetchone()
    assert stored_token is not None
    assert stored_token[0] != setup_token
    assert stored_token[1] is not None


@pytest.mark.asyncio
async def test_expiry_and_reset_are_one_time_and_replace_the_previous_password():
    owner_password = _password("Owner")
    old_password = _password("Old")
    new_password = _password("New")
    operator_email = _email("reset")

    async with await _client() as owner:
        setup = await _setup_owner(owner, owner_password)
        assert setup.status_code == 200
        invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Reset Operator", "email": operator_email, "role_codes": ["OPERATOR"]},
        )
        setup_token = invite.json()["setup_token"]
        user_id = invite.json()["user"]["user_id"]

        expired_invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Expired Operator", "email": _email("expired"), "role_codes": ["OPERATOR"]},
        )
        expired_token = expired_invite.json()["setup_token"]
        expired_password = _password("Expired")
        db = await get_db()
        await db.execute(
            "UPDATE auth_setup_token SET expires_at=? WHERE token_hash=?",
            ("2000-01-01T00:00:00Z", access.hash_session_token(expired_token)),
        )
        await db.commit()
        async with await _client() as expired_client:
            expired = await _post(
                expired_client,
                "/api/auth/activate-account",
                {"token": expired_token, "password": expired_password, "password_confirmation": expired_password},
            )
            assert expired.status_code == 400
            assert expired.json()["detail"]["error"] == "TOKEN_INVALID_OR_EXPIRED"

        async with await _client() as operator:
            activated = await _post(
                operator,
                "/api/auth/activate-account",
                {"token": setup_token, "password": old_password, "password_confirmation": old_password},
            )
            assert activated.status_code == 200
            reset = await _post(owner, f"/api/system/staff-access/staff/{user_id}/reset", {})
            assert reset.status_code == 200
            reset_token = reset.json()["reset_token"]
            assert reset.json()["user"]["account_status"] == "INVITED"

            old_login = await _post(
                operator,
                "/api/auth/login",
                {"email": operator_email, "password": old_password},
            )
            assert old_login.status_code == 401

            completed = await _post(
                operator,
                "/api/auth/reset-password",
                {"token": reset_token, "password": new_password, "password_confirmation": new_password},
            )
            assert completed.status_code == 200
            assert completed.json()["user"]["account_status"] == "ACTIVE"
            assert completed.json()["user"]["role_codes"] == ["OPERATOR"]

        async with await _client() as old_client:
            old_again = await _post(old_client, "/api/auth/login", {"email": operator_email, "password": old_password})
            assert old_again.status_code == 401
        async with await _client() as new_client:
            new_login = await _post(new_client, "/api/auth/login", {"email": operator_email, "password": new_password})
            assert new_login.status_code == 200
            reuse_password = _password("Reuse")
            reused = await _post(
                new_client,
                "/api/auth/reset-password",
                {"token": reset_token, "password": reuse_password, "password_confirmation": reuse_password},
            )
            assert reused.status_code == 400
            assert reused.json()["detail"]["error"] == "TOKEN_INVALID_OR_EXPIRED"

    events = await access.list_audit_events()
    assert reset_token not in json.dumps(events, sort_keys=True)
    assert old_password not in json.dumps(events, sort_keys=True)
    assert new_password not in json.dumps(events, sort_keys=True)


@pytest.mark.asyncio
async def test_status_protections_remain_fail_closed_and_owner_authentication_is_unchanged():
    owner_password = _password("Owner")
    operator_password = _password("Operator")
    operator_email = _email("protected")

    async with await _client() as owner:
        setup = await _setup_owner(owner, owner_password)
        assert setup.status_code == 200
        invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Protected Operator", "email": operator_email, "role_codes": ["OPERATOR"]},
        )
        user_id = invite.json()["user"]["user_id"]
        async with await _client() as operator:
            assert (await _post(
                operator,
                "/api/auth/activate-account",
                {"token": invite.json()["setup_token"], "password": operator_password, "password_confirmation": operator_password},
            )).status_code == 200

        suspended = await _post(owner, f"/api/system/staff-access/staff/{user_id}/suspend", {"reason": "TEST_SUSPEND"})
        assert suspended.status_code == 200
        assert suspended.json()["user"]["account_status"] == "SUSPENDED"
        async with await _client() as suspended_client:
            assert (await _post(suspended_client, "/api/auth/login", {"email": operator_email, "password": operator_password})).status_code == 401
        assert (await _post(owner, f"/api/system/staff-access/staff/{user_id}/reset", {})).status_code == 409

        reactivated = await _post(owner, f"/api/system/staff-access/staff/{user_id}/reactivate", {"reason": "TEST_REACTIVATE"})
        assert reactivated.status_code == 200
        assert reactivated.json()["user"]["account_status"] == "ACTIVE"
        disabled = await _post(owner, f"/api/system/staff-access/staff/{user_id}/disable", {"reason": "TEST_DISABLE"})
        assert disabled.status_code == 200
        async with await _client() as disabled_client:
            assert (await _post(disabled_client, "/api/auth/login", {"email": operator_email, "password": operator_password})).status_code == 401
        assert (await _post(owner, f"/api/system/staff-access/staff/{user_id}/reset", {})).status_code == 409

        terminated = await _post(owner, f"/api/system/staff-access/staff/{user_id}/terminate", {"reason": "TEST_TERMINATE"})
        assert terminated.status_code == 200
        assert terminated.json()["user"]["account_status"] == "TERMINATED"
        assert terminated.json()["user"]["staff_active"] is False
        assert terminated.json()["user"]["role_codes"] == []
        assert (await _post(owner, f"/api/system/staff-access/staff/{user_id}/reset", {})).status_code == 409
        assert (await _post(owner, f"/api/system/staff-access/staff/{user_id}/reactivate", {"reason": "TEST_REACTIVATE_TERMINATED"})).status_code == 409

        owner_session = await owner.get("/api/auth/me")
        assert owner_session.status_code == 200
        assert owner_session.json()["authenticated"] is True
        async with await _client() as owner_login:
            owner_again = await _post(owner_login, "/api/auth/login", {"email": setup.json()["user"]["email"], "password": owner_password})
            assert owner_again.status_code == 200
