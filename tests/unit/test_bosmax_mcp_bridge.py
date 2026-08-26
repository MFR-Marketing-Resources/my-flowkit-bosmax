"""Provider-free security and route proof for the local BOSMAX MCP bridge."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from bosmax_mcp_bridge import BridgeConfig, BridgeConfigError, BridgeInputError, BridgeRequestError
from bosmax_mcp_bridge.bridge import BOSMAX_FLOW_TOOLS, BosmaxMcpBridge


EMAIL = "hermes-operator@example.test"
PASSWORD = "operator-password-secret"
SESSION = "session-cookie-secret"
CSRF = "csrf-cookie-secret"
BASE_URL = "http://127.0.0.1:8100"


@pytest.fixture(autouse=True)
async def db_setup():
    """The bridge suite is transport-only and must not bootstrap the app DB."""

    yield


def _login_response(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/auth/login"
    body = json.loads(request.content.decode("utf-8"))
    assert body == {"email": EMAIL, "password": PASSWORD}
    return httpx.Response(
        200,
        headers=[
            ("set-cookie", f"bosmax_session={SESSION}; Path=/; HttpOnly"),
            ("set-cookie", f"bosmax_csrf={CSRF}; Path=/"),
        ],
        json={"authenticated": True, "user": {"email": EMAIL}},
    )


def _config() -> BridgeConfig:
    return BridgeConfig(BASE_URL, EMAIL, PASSWORD)


def test_mcp_tool_list_is_exactly_the_four_fixed_bosmax_tools() -> None:
    bridge = BosmaxMcpBridge(_config(), transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    try:
        definitions = bridge.tool_definitions()
        assert [item["name"] for item in definitions] == [
            "bosmax_flow_readiness",
            "bosmax_flow_generate",
            "bosmax_flow_job_status",
            "bosmax_flow_reretrieve_media",
        ]
        assert len(definitions) == len(BOSMAX_FLOW_TOOLS) == 4
        for item in definitions:
            assert "base_url" not in json.dumps(item)
            assert "cookie" not in json.dumps(item).lower()
    finally:
        import asyncio

        asyncio.run(bridge.close())


async def _bridge(handler) -> BosmaxMcpBridge:
    return BosmaxMcpBridge(_config(), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_login_succeeds_and_cookie_values_remain_private() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        return httpx.Response(200, json={"ready": True})

    bridge = await _bridge(handler)
    try:
        result = await bridge.call_tool("bosmax_flow_readiness", {})
        text = result["content"][0]["text"]
        assert result["isError"] is False
        assert sorted(cookie.name for cookie in bridge._cookies.jar) == [
            "bosmax_csrf",
            "bosmax_session",
        ]
        assert SESSION not in text
        assert CSRF not in text
        assert PASSWORD not in text
        assert EMAIL not in text
        assert len(calls) == 2
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_b_readiness_request_carries_authenticated_session_and_exact_inputs() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        assert request.url.path == "/api/flow/direct-video-readiness"
        assert request.headers.get("cookie") == f"bosmax_session={SESSION}; bosmax_csrf={CSRF}"
        assert dict(request.url.params) == {
            "mode": "F2V",
            "model": "veo_3_1_lite",
            "duration_s": "8",
            "aspect": "9:16",
            "ref_count": "1",
            "count": "1",
        }
        return httpx.Response(200, json={"readiness": "PASS", "contract": "direct-video-readiness-v2"})

    bridge = await _bridge(handler)
    try:
        result = await bridge.readiness(
            {
                "mode": "F2V",
                "model": "veo_3_1_lite",
                "duration_s": 8,
                "aspect": "9:16",
                "ref_count": 1,
                "count": 1,
            }
        )
        assert result["payload"] == {
            "readiness": "PASS",
            "contract": "direct-video-readiness-v2",
        }
        assert [request.url.path for request in calls] == [
            "/api/auth/login",
            "/api/flow/direct-video-readiness",
        ]
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_c_mutation_sends_session_cookie_and_matching_csrf_header() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        assert request.url.path == "/api/flow/generate"
        assert request.headers.get("cookie") == f"bosmax_session={SESSION}; bosmax_csrf={CSRF}"
        assert request.headers.get("x-csrf-token") == CSRF
        return httpx.Response(200, json={"job_id": "g_test", "status": "QUEUED"})

    bridge = await _bridge(handler)
    try:
        result = await bridge.generate({"mode": "T2V", "prompt": "safe test prompt"})
        assert result["endpoint"] == "/api/flow/generate"
        assert result["payload"] == {"job_id": "g_test", "status": "QUEUED"}
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_d_first_401_causes_exactly_one_relogin_and_one_retry() -> None:
    login_count = 0
    readiness_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count, readiness_count
        if request.url.path == "/api/auth/login":
            login_count += 1
            return _login_response(request)
        readiness_count += 1
        if readiness_count == 1:
            return httpx.Response(401, json={"error": "expired", "token": SESSION})
        return httpx.Response(200, json={"readiness": "PASS"})

    bridge = await _bridge(handler)
    try:
        result = await bridge.readiness({})
        assert result["payload"] == {"readiness": "PASS"}
        assert login_count == 2
        assert readiness_count == 2
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_e_second_401_fails_closed() -> None:
    login_count = 0
    readiness_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count, readiness_count
        if request.url.path == "/api/auth/login":
            login_count += 1
            return _login_response(request)
        readiness_count += 1
        return httpx.Response(401, json={"error": "expired", "token": SESSION})

    bridge = await _bridge(handler)
    try:
        result = await bridge.call_tool("bosmax_flow_readiness", {})
        assert result["isError"] is True
        assert result["structuredContent"]["error"] == "BOSMAX_UNAUTHORIZED"
        assert SESSION not in result["content"][0]["text"]
        assert login_count == 2
        assert readiness_count == 2
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_f_403_fails_closed_without_privilege_escalation() -> None:
    login_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count
        if request.url.path == "/api/auth/login":
            login_count += 1
            return _login_response(request)
        return httpx.Response(403, json={"error": "PERMISSION_DENIED", "session": SESSION})

    bridge = await _bridge(handler)
    try:
        result = await bridge.call_tool("bosmax_flow_reretrieve_media", {"job_id": "g_test"})
        assert result["isError"] is True
        assert result["structuredContent"]["error"] == "BOSMAX_FORBIDDEN"
        assert login_count == 1
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_g_credentials_and_cookie_values_never_appear_in_tool_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        return httpx.Response(
            200,
            json={
                "email": EMAIL,
                "password": PASSWORD,
                "bosmax_session": SESSION,
                "bosmax_csrf": CSRF,
                "set-cookie": f"bosmax_session={SESSION}",
                "nested": [{"authorization": f"Bearer {SESSION}"}],
            },
        )

    bridge = await _bridge(handler)
    try:
        result = await bridge.call_tool("bosmax_flow_job_status", {"job_id": "g_test"})
        serialized = json.dumps(result, sort_keys=True)
        for secret in (EMAIL, PASSWORD, SESSION, CSRF):
            assert secret not in serialized
        assert "credentials_exposed" in serialized
        assert "cookies_exposed" in serialized
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_h_arbitrary_endpoints_are_rejected() -> None:
    bridge = await _bridge(lambda request: httpx.Response(500))
    try:
        with pytest.raises(BridgeInputError, match="ENDPOINT_NOT_ALLOWED"):
            await bridge._request("GET", "/api/admin/users")
        result = await bridge.call_tool(
            "bosmax_flow_readiness", {"endpoint": "/api/admin/users"}
        )
        assert result["isError"] is True
        assert result["structuredContent"]["error"] == "INPUT_INVALID"
    finally:
        await bridge.close()


def test_i_arbitrary_base_urls_are_rejected() -> None:
    with pytest.raises(BridgeConfigError):
        BridgeConfig.from_env(
            {"BOSMAX_BOT_EMAIL": EMAIL, "BOSMAX_BOT_PASSWORD": PASSWORD}
        )
    assert BridgeConfig.from_env(
        {
            "BOSMAX_LOCAL_USE": "1",
            "BOSMAX_BOT_EMAIL": EMAIL,
            "BOSMAX_BOT_PASSWORD": PASSWORD,
        }
    ).base_url == BASE_URL
    with pytest.raises(BridgeConfigError):
        BridgeConfig.from_env(
            {
                "BOSMAX_BASE_URL": "http://evil.example",
                "BOSMAX_BOT_EMAIL": EMAIL,
                "BOSMAX_BOT_PASSWORD": PASSWORD,
            }
        )
    with pytest.raises(BridgeConfigError):
        BridgeConfig.from_env(
            {
                "BOSMAX_BASE_URL": "https://evil.example/path?token=leak",
                "BOSMAX_BOT_EMAIL": EMAIL,
                "BOSMAX_BOT_PASSWORD": PASSWORD,
            }
        )


@pytest.mark.asyncio
async def test_j_generate_maps_only_to_canonical_generate_endpoint() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        assert request.url.path == "/api/flow/generate"
        return httpx.Response(200, json={"job_id": "g_test"})

    bridge = await _bridge(handler)
    try:
        await bridge.generate({"mode": "F2V", "prompt": "frame prompt"})
        assert paths == ["/api/auth/login", "/api/flow/generate"]
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_k_no_dom_generation_code_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.services.make_video as make_video

    def fail_if_called(*args, **kwargs):
        raise AssertionError("provider generation must not be called by the MCP bridge")

    monkeypatch.setattr(make_video, "start_generate", fail_if_called)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        return httpx.Response(200, json={"readiness": "PASS"})

    bridge = await _bridge(handler)
    try:
        await bridge.readiness({})
        source = Path("bosmax_mcp_bridge/bridge.py").read_text(encoding="utf-8")
        assert "content-flow-dom" not in source
        assert "f2v-flow-queue-runner" not in source
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_l_mcp_suite_never_calls_provider_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.services.make_video as make_video

    provider_calls = 0

    def fail_if_called(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider generation must not be called")

    monkeypatch.setattr(make_video, "start_generate", fail_if_called)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return _login_response(request)
        if request.url.path == "/api/flow/direct-video-readiness":
            return httpx.Response(200, json={"readiness": "PASS"})
        if request.url.path == "/api/flow/generate":
            return httpx.Response(200, json={"job_id": "g_test", "provider_calls": 0})
        if request.url.path.endswith("/reretrieve-media"):
            return httpx.Response(200, json={"status": "DONE", "provider_generation_submits": 0})
        return httpx.Response(200, json={"status": "QUEUED", "provider_generation_submits": 0})

    bridge = await _bridge(handler)
    try:
        await bridge.call_tool("bosmax_flow_readiness", {})
        await bridge.call_tool("bosmax_flow_generate", {"mode": "T2V", "prompt": "test"})
        await bridge.call_tool("bosmax_flow_job_status", {"job_id": "g_test"})
        await bridge.call_tool("bosmax_flow_reretrieve_media", {"job_id": "g_test"})
        assert provider_calls == 0
    finally:
        await bridge.close()
