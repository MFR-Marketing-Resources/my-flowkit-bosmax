from __future__ import annotations

import secrets

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from agent.access_control_constants import PERMISSION_CODES, ROLE_PERMISSION_CODES
from agent.db import crud
from agent.main import app
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftCreateRequest,
)
from agent.security.access_control import (
    _module_for_path,
    _flow_dispatcher_route_allowed,
    classify_route,
    required_permission,
)
from agent.services import access_control_service as access
from agent.services.product_intelligence_review_draft_service import create_review_draft
from agent.db.schema import get_db


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


async def _post(client: httpx.AsyncClient, path: str, body: dict, csrf: str | None = None) -> httpx.Response:
    token = csrf or await _csrf(client)
    return await client.post(path, json=body, headers={"X-CSRF-Token": token})


def _safe_product_intelligence_draft_request() -> ProductIntelligenceReviewDraftCreateRequest:
    return ProductIntelligenceReviewDraftCreateRequest(
        product_description="Compact 500ml bottle for daily routine storage.",
        benefits_json=["portable", "compact"],
        usp_json=["clean bottle format", "easy shelf fit"],
        usage_text="Use as part of a daily routine.",
        ingredients_text="Bottle, cap, printed label.",
        warnings_text="Store away from direct heat.",
        target_customer_text="Busy adults who prefer compact packaging.",
        allowed_claims_json=["portable daily carry", "compact shelf storage"],
        source_urls_json={"source_url": "https://example.com/source"},
        image_evidence_json={"image_url": "https://example.com/image.jpg"},
        buyer_persona_snapshot_json={"persona": "busy adults"},
        copy_strategy_summary_json={"angle": "compact routine convenience"},
        created_by="owner",
    )


def test_flow_dispatcher_scope_allows_status_polling_but_blocks_paid_recovery():
    assert _flow_dispatcher_route_allowed("GET", "/api/flow/generate-job/job_123")
    assert not _flow_dispatcher_route_allowed(
        "POST", "/api/flow/generate-job/job_123/retry-artifact-delivery"
    )
    assert not _flow_dispatcher_route_allowed(
        "POST", "/api/flow/generate-job/job_123/reretrieve-media"
    )


@pytest_asyncio.fixture(autouse=True)
async def isolated_access_tables():
    db = await get_db()
    for table in (
        "access_audit_event",
        "auth_service_token",
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
async def test_owner_approves_scoped_flow_dispatcher_and_can_revoke_it(monkeypatch, tmp_path):
    token_file = tmp_path / "bot4-flow-dispatcher.token"
    monkeypatch.setattr(access, "FLOW_DISPATCHER_TOKEN_FILE", token_file)
    owner_password = _password()
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Dispatcher Owner",
                "email": _email("dispatcher-owner"),
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200

        approved = await _post(owner, "/api/auth/flow-dispatcher/approve", {})
        assert approved.status_code == 200
        assert approved.json()["approved"] is True
        raw_token = token_file.read_text(encoding="utf-8")
        assert len(raw_token) >= 32
        assert raw_token not in approved.text

        status = await owner.get("/api/auth/flow-dispatcher")
        assert status.status_code == 200
        assert status.json()["approved"] is True
        assert status.json()["credential_file_present"] is True

        async with await _client() as bot4:
            allowed = await bot4.get(
                "/api/flow/direct-video-readiness?mode=F2V&source_mode=FRAMES",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert allowed.status_code != 401
            assert allowed.status_code != 403

            denied = await bot4.get(
                "/api/products",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert denied.status_code == 403
            assert denied.json()["error"] == "SERVICE_SCOPE_DENIED"

        revoked = await _post(owner, "/api/auth/flow-dispatcher/revoke", {})
        assert revoked.status_code == 200
        assert revoked.json() == {"revoked": True}
        assert not token_file.exists()

        async with await _client() as bot4:
            rejected = await bot4.get(
                "/api/flow/direct-video-readiness?mode=F2V&source_mode=FRAMES",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert rejected.status_code == 401
            assert rejected.json()["error"] == "SERVICE_AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_first_owner_bootstrap_is_atomic_and_permanently_closed():
    owner_email = _email("owner")
    owner_password = _password()
    async with await _client() as client:
        response = await _post(
            client,
            "/api/auth/setup-owner",
            {
                "display_name": "Bootstrap Owner",
                "email": owner_email,
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert response.status_code == 200
        assert response.json()["user"]["role_codes"] == ["OWNER"]
        assert "session_token" not in response.text
        assert "csrf_token" not in response.text
        assert client.cookies.get(access.SESSION_COOKIE_NAME)
        set_cookie_headers = response.headers.get_list("set-cookie")
        session_cookie = next(
            header for header in set_cookie_headers if header.startswith(f"{access.SESSION_COOKIE_NAME}=")
        )
        csrf_cookie = next(
            header for header in set_cookie_headers if header.startswith(f"{access.CSRF_COOKIE_NAME}=")
        )
        assert "HttpOnly" in session_cookie
        assert "SameSite=lax" in session_cookie
        assert "HttpOnly" not in csrf_cookie
        assert "SameSite=lax" in csrf_cookie

        second_password = _password()
        second = await _post(
            client,
            "/api/auth/setup-owner",
            {
                "display_name": "Second Owner",
                "email": _email("second"),
                "password": second_password,
                "password_confirmation": second_password,
            },
        )
        assert second.status_code == 409
        assert second.json()["detail"]["error"] == "OWNER_ALREADY_BOOTSTRAPPED"

    db = await get_db()
    row = await (
        await db.execute(
            "SELECT password_hash, account_status FROM user_account WHERE email=?",
            (owner_email,),
        )
    ).fetchone()
    assert row is not None
    assert str(row[0]).startswith("$argon2id$")
    assert owner_password not in str(row[0])
    assert row[1] == "ACTIVE"


@pytest.mark.asyncio
async def test_human_api_is_fail_closed_before_bootstrap_and_auth_mutations_require_csrf():
    async with await _client() as client:
        unauthenticated = await client.get("/api/products")
        assert unauthenticated.status_code == 428
        assert unauthenticated.json()["error"] == "SETUP_REQUIRED"

        missing_csrf = await client.post(
            "/api/auth/login",
            json={"email": _email("owner"), "password": _password()},
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"] == "CSRF_REQUIRED"

        arbitrary_local_origin = await client.post(
            "/api/auth/login",
            json={"email": _email("owner"), "password": _password()},
            headers={"Origin": "http://localhost:9999"},
        )
        assert arbitrary_local_origin.status_code == 403
        assert arbitrary_local_origin.json()["error"] == "CSRF_REQUIRED"


@pytest.mark.asyncio
async def test_rbac_denies_direct_api_and_binds_staff_session():
    owner_email = _email("owner")
    owner_password = _password()
    editor_email = _email("editor")
    editor_password = _password()
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Owner",
                "email": owner_email,
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200
        owner_staff_id = setup.json()["user"]["staff_id"]
        owner_csrf = await _csrf(owner)
        owner_role_lock = await owner.put(
            "/api/system/staff-access/roles/OWNER/permissions",
            json={"permission_codes": []},
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert owner_role_lock.status_code == 409
        assert owner_role_lock.json()["detail"]["error"] == "OWNER_ROLE_PROTECTED"
        invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Editor", "email": editor_email, "role_codes": ["EDITOR"]},
        )
        assert invite.status_code == 201
        invite_payload = invite.json()
        setup_token = invite_payload["setup_token"]
        assert all(setup_token not in str(event) for event in await access.list_audit_events())

        async with await _client() as editor:
            await _csrf(editor)
            activated = await _post(
                editor,
                "/api/auth/activate-account",
                {
                    "token": setup_token,
                    "password": editor_password,
                    "password_confirmation": editor_password,
                },
            )
            assert activated.status_code == 200
            assert activated.json()["user"]["role_codes"] == ["EDITOR"]

            denied = await editor.get("/api/system/staff-access/staff")
            assert denied.status_code == 403
            assert denied.json()["error"] == "PERMISSION_DENIED"

            spoof = await _post(
                editor,
                "/api/faceless/validate",
                {
                    "product_id": "missing-product",
                    "model": "veo_3_1_fast",
                    "staff_id": owner_staff_id,
                },
            )
            assert spoof.status_code == 403
            assert spoof.json()["detail"]["error_code"] == "STAFF_IDENTITY_SPOOF_ATTEMPT"

            logout = await _post(editor, "/api/auth/logout", {})
            assert logout.status_code == 200
            assert (await editor.get("/api/auth/current-session")).json()["authenticated"] is False


@pytest.mark.asyncio
async def test_owner_product_intelligence_workflow_passes_real_access_middleware():
    owner_email = _email("owner")
    owner_password = _password()
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Product Owner",
                "email": owner_email,
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200

        session = await owner.get("/api/auth/current-session")
        assert session.status_code == 200
        session_user = session.json()["user"]
        assert session.json()["authenticated"] is True
        assert session_user["role_codes"] == ["OWNER"]
        assert "products.create" in session_user["permissions"]
        assert "products.update" in session_user["permissions"]
        assert "products.execute" not in session_user["permissions"]

        product = await crud.create_product(
            raw_product_title="RBAC Product Intelligence Fixture",
            source="MANUAL",
            product_display_name="RBAC Product Intelligence Fixture",
            product_short_name="RBAC Product Intelligence Fixture",
        )
        draft = await create_review_draft(
            product["id"], _safe_product_intelligence_draft_request()
        )
        csrf = str(owner.cookies.get(access.CSRF_COOKIE_NAME))
        headers = {"X-CSRF-Token": csrf}

        save = await owner.patch(
            f"/api/product-intelligence/review-drafts/{draft.draft_id}",
            json={"reviewer_note": "Saved through the real middleware."},
            headers=headers,
        )
        assert save.status_code == 200, save.text

        validate = await owner.post(
            f"/api/product-intelligence/review-drafts/{draft.draft_id}/validate",
            json={},
            headers=headers,
        )
        assert validate.status_code == 200, validate.text

        approve = await owner.post(
            f"/api/product-intelligence/review-drafts/{draft.draft_id}/approve",
            json={"approved_by": "owner"},
            headers=headers,
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["status"] == "APPROVED"
        for response in (save, validate, approve):
            assert not (
                response.status_code == 403
                and response.json().get("permission") == "products.execute"
            )


def test_product_role_boundaries_and_seed_vocabulary_remain_canonical():
    assert set(ROLE_PERMISSION_CODES["OWNER"]) == set(PERMISSION_CODES)
    assert {"products.create", "products.update"}.issubset(
        ROLE_PERMISSION_CODES["EDITOR"]
    )
    assert "products.update" not in ROLE_PERMISSION_CODES["OPERATOR"]
    assert "products.create" not in ROLE_PERMISSION_CODES["OPERATOR"]
    assert "products.update" not in ROLE_PERMISSION_CODES["VIEWER"]
    assert "products.create" not in ROLE_PERMISSION_CODES["VIEWER"]


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    (
        (
            "PATCH",
            "/api/product-intelligence/review-drafts/draft-1",
            "products.update",
        ),
        (
            "POST",
            "/api/product-intelligence/review-drafts/draft-1/validate",
            "products.update",
        ),
        (
            "POST",
            "/api/product-intelligence/review-drafts/draft-1/approve",
            "products.update",
        ),
        (
            "POST",
            "/api/product-intelligence/review-drafts/draft-1/reject",
            "products.update",
        ),
        (
            "POST",
            "/api/product-intelligence/review-drafts/draft-1/ai-fill-missing",
            "products.update",
        ),
        (
            "POST",
            "/api/product-intelligence/review-drafts/draft-1/field-dispositions",
            "products.update",
        ),
        (
            "POST",
            "/api/products/product-1/intelligence/revision-drafts",
            "products.create",
        ),
        (
            "POST",
            "/api/products/product-1/claim-safe-rewrite-approval",
            "products.update",
        ),
        (
            "POST",
            "/api/product-truth/product-1/visual-lock/approve",
            "products.update",
        ),
    ),
)
def test_product_intelligence_permission_contract(method: str, path: str, expected: str):
    actual = required_permission(path, method)
    assert actual == expected
    assert actual in PERMISSION_CODES


def test_every_registered_product_route_uses_canonical_permission_code():
    product_routes = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods or classify_route(route.path) != "B_AUTHENTICATED_HUMAN":
            continue
        if _module_for_path(route.path) != "products":
            continue
        for method in sorted(methods):
            permission = required_permission(route.path, method)
            product_routes.append((method, route.path, permission))
            assert permission in PERMISSION_CODES, (
                f"{method} {route.path} generated phantom permission {permission}"
            )
    assert product_routes


@pytest.mark.asyncio
async def test_termination_revokes_sessions_preserves_staff_and_protects_last_owner():
    owner_email = _email("owner")
    owner_password = _password()
    viewer_email = _email("viewer")
    viewer_password = _password()
    async with await _client() as owner:
        setup = await _post(
            owner,
            "/api/auth/setup-owner",
            {
                "display_name": "Owner",
                "email": owner_email,
                "password": owner_password,
                "password_confirmation": owner_password,
            },
        )
        assert setup.status_code == 200
        owner_user_id = setup.json()["user"]["user_id"]
        owner_staff_id = setup.json()["user"]["staff_id"]
        invite = await _post(
            owner,
            "/api/system/staff-access/staff",
            {"display_name": "Viewer", "email": viewer_email, "role_codes": ["VIEWER"]},
        )
        viewer_user_id = invite.json()["user"]["user_id"]
        viewer_staff_id = invite.json()["user"]["staff_id"]
        async with await _client() as viewer:
            await _csrf(viewer)
            assert (await _post(
                viewer,
                "/api/auth/activate-account",
                {
                    "token": invite.json()["setup_token"],
                    "password": viewer_password,
                    "password_confirmation": viewer_password,
                },
            )).status_code == 200
            terminated = await _post(
                owner,
                f"/api/system/staff-access/staff/{viewer_user_id}/terminate",
                {"reason": "OWNER_TEST_TERMINATION"},
            )
            assert terminated.status_code == 200
            assert terminated.json()["user"]["account_status"] == "TERMINATED"
            terminated_status_change = await _post(
                owner,
                f"/api/system/staff-access/staff/{viewer_user_id}/suspend",
                {"reason": "SHOULD_REMAIN_TERMINAL"},
            )
            assert terminated_status_change.status_code == 409
            assert terminated_status_change.json()["detail"]["error"] == "ACCOUNT_TERMINATED"
            terminated_reset = await _post(
                owner,
                f"/api/system/staff-access/staff/{viewer_user_id}/reset",
                {},
            )
            assert terminated_reset.status_code == 409
            assert terminated_reset.json()["detail"]["error"] == "ACCOUNT_TERMINATED"

            viewer_session = await viewer.get("/api/auth/current-session")
            assert viewer_session.json()["authenticated"] is False

        last_owner = await _post(
            owner,
            f"/api/system/staff-access/staff/{owner_user_id}/terminate",
            {"reason": "SHOULD_BE_BLOCKED"},
        )
        assert last_owner.status_code == 409
        assert last_owner.json()["detail"]["error"] == "LAST_OWNER_PROTECTED"

    db = await get_db()
    preserved = await (
        await db.execute(
            "SELECT ua.account_status, ua.password_hash, sp.active "
            "FROM user_account ua JOIN staff_profile sp ON sp.staff_id=ua.staff_id WHERE ua.user_id=?",
            (viewer_user_id,),
        )
    ).fetchone()
    assert preserved[0] == "TERMINATED"
    assert preserved[1] is None
    assert int(preserved[2]) == 0
    assert await (
        await db.execute("SELECT 1 FROM staff_profile WHERE staff_id=?", (viewer_staff_id,))
    ).fetchone()
    assert await (
        await db.execute("SELECT 1 FROM access_audit_event WHERE event_type='ACCOUNT_TERMINATED' AND target_user_id=?", (viewer_user_id,))
    ).fetchone()
    assert owner_staff_id != viewer_staff_id


def test_route_classification_and_permission_policy_fail_closed():
    assert classify_route("/api/auth/login") == "A_PUBLIC_AUTH"
    assert classify_route("/api/ext/callback") == "C_INTERNAL_SERVICE"
    assert classify_route("/api/extreme") == "B_AUTHENTICATED_HUMAN"
    assert classify_route("/health") == "D_HEALTH_PROVENANCE"
    assert classify_route("/api/products") == "B_AUTHENTICATED_HUMAN"
    assert required_permission("/api/flow/generate", "POST") == "production.execute"
    assert required_permission("/api/flowery", "POST") == "system.settings.manage"
    assert required_permission("/api/reporting/production/summary", "GET") == "reporting.read"
    assert required_permission("/api/system/staff-access/staff", "POST") == "staff.manage"
    assert required_permission("/api/unknown-human-route", "POST") == "system.settings.manage"
