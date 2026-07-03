"""Contracts for the Postiz Setup Doctor (operator onboarding).

Every state must produce actionable next_steps — never a dead-end error
screen — and the API key must never appear in any response."""
import pytest

from agent.services import postiz_client as pz


def _env(monkeypatch, **values):
    for k in ("POSTIZ_ENABLED", "POSTIZ_BASE_URL", "POSTIZ_API_KEY",
              "POSTIZ_UPLOAD_MODE", "POSTIZ_DEFAULT_POST_TYPE", "POSTIZ_API_PREFIX"):
        monkeypatch.delenv(k, raising=False)
    for k, v in values.items():
        monkeypatch.setenv(k, v)


def _no_probe(monkeypatch, reachable=True):
    async def fake_probe(base_url):
        return reachable
    monkeypatch.setattr(pz, "probe_reachable", fake_probe)


_CHANNELS = [
    {"id": "tt-1", "provider": "tiktok", "name": "A", "picture": None,
     "disabled": False, "refresh_needed": False, "profile": "a"},
    {"id": "tt-2", "provider": "tiktok", "name": "B", "picture": None,
     "disabled": False, "refresh_needed": False, "profile": "b"},
    {"id": "yt-1", "provider": "youtube", "name": "C", "picture": None,
     "disabled": False, "refresh_needed": False, "profile": "c"},
]


async def test_disabled_default_state_returns_actionable_setup_steps(monkeypatch):
    _env(monkeypatch)  # nothing set — fresh install
    status = await pz.setup_status()
    assert status["postiz_enabled"] is False
    assert status["health_ok"] is False
    assert status["ready"] is False
    assert "POSTIZ_DISABLED" in status["problems"]
    assert "POSTIZ_BASE_URL_MISSING" in status["problems"]
    assert "POSTIZ_API_KEY_MISSING" in status["problems"]
    # Not a dead end: concrete steps, env block, restart note, docs pointer.
    assert status["next_steps"], "next_steps must never be empty in setup states"
    assert any("POSTIZ_ENABLED=true" in s for s in status["next_steps"])
    assert status["restart_instruction"].startswith("After editing")
    assert status["docs_path"] == "docs/integrations/postiz/OPERATOR_GUIDE.md"
    assert status["safe_env_example"]["POSTIZ_API_KEY"] == "<paste key>"
    assert status["safe_env_example"]["POSTIZ_ENABLED"] == "true"
    # Fresh install (no IPv6 trap detected) keeps the localhost default.
    assert status["safe_env_example"]["POSTIZ_BASE_URL"] == "http://localhost:5000"


async def test_missing_base_url_is_called_out(monkeypatch):
    _env(monkeypatch, POSTIZ_ENABLED="true", POSTIZ_API_KEY="k")
    status = await pz.setup_status()
    assert status["base_url_configured"] is False
    assert "POSTIZ_BASE_URL_MISSING" in status["problems"]
    assert any("POSTIZ_BASE_URL" in s and "http://localhost:5000" in s
               for s in status["next_steps"])


async def test_missing_api_key_points_to_postiz_settings(monkeypatch):
    _env(monkeypatch, POSTIZ_ENABLED="true", POSTIZ_BASE_URL="http://localhost:5000")
    _no_probe(monkeypatch, reachable=True)
    status = await pz.setup_status()
    assert status["api_key_present"] is False
    assert "POSTIZ_API_KEY_MISSING" in status["problems"]
    assert any("Settings → Public API" in s for s in status["next_steps"])


async def test_enabled_but_unreachable_shows_docker_commands(monkeypatch):
    _env(monkeypatch, POSTIZ_ENABLED="true",
         POSTIZ_BASE_URL="http://localhost:5000", POSTIZ_API_KEY="k")
    _no_probe(monkeypatch, reachable=False)
    status = await pz.setup_status()
    assert status["postiz_reachable"] is False
    assert "POSTIZ_UNREACHABLE" in status["problems"]
    joined = " ".join(status["next_steps"])
    assert "cd infra/postiz" in joined
    assert "docker compose up -d" in joined
    assert status["start_commands"] == [
        "cd infra/postiz", "copy .env.postiz.example .env", "docker compose up -d",
    ]


async def test_reachable_but_zero_channels_guides_channel_setup(monkeypatch):
    _env(monkeypatch, POSTIZ_ENABLED="true",
         POSTIZ_BASE_URL="http://localhost:5000", POSTIZ_API_KEY="k")
    _no_probe(monkeypatch, reachable=True)

    async def fake_list():
        return []

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    status = await pz.setup_status()
    assert status["health_ok"] is True
    assert status["integrations_count"] == 0
    assert status["ready"] is False
    assert any("no social channels are connected yet" in s for s in status["next_steps"])
    assert any("Add Channel" in s for s in status["next_steps"])
    # Provider limits surfaced for the operator.
    assert any("audit" in w.lower() for w in status["provider_warnings"]["tiktok"])
    assert any("live" in w.lower() for w in status["provider_warnings"]["facebook"])


async def test_ready_state_with_multiple_same_provider_channels(monkeypatch):
    _env(monkeypatch, POSTIZ_ENABLED="true",
         POSTIZ_BASE_URL="http://localhost:5000", POSTIZ_API_KEY="k")
    _no_probe(monkeypatch, reachable=True)

    async def fake_list():
        return list(_CHANNELS)  # two tiktok accounts + one youtube

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    status = await pz.setup_status()
    assert status["ready"] is True
    assert status["integrations_count"] == 3  # NOT collapsed per provider
    # Normal reachable state keeps the localhost default in the env block.
    assert status["safe_env_example"]["POSTIZ_BASE_URL"] == "http://localhost:5000"


async def test_rejected_api_key_becomes_actionable_problem(monkeypatch):
    _env(monkeypatch, POSTIZ_ENABLED="true",
         POSTIZ_BASE_URL="http://localhost:5000", POSTIZ_API_KEY="wrong")
    _no_probe(monkeypatch, reachable=True)

    async def fake_list():
        raise pz.PostizApiError(401, '{"msg":"Invalid API key"}')

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    status = await pz.setup_status()
    assert "POSTIZ_API_KEY_REJECTED" in status["problems"]
    assert any("regenerate" in s.lower() for s in status["next_steps"])
    assert status["ready"] is False


async def test_api_key_never_appears_in_setup_status(monkeypatch):
    secret = "sk-super-secret-postiz-key-123456"
    _env(monkeypatch, POSTIZ_ENABLED="true",
         POSTIZ_BASE_URL="http://localhost:5000", POSTIZ_API_KEY=secret)
    _no_probe(monkeypatch, reachable=False)
    status = await pz.setup_status()
    assert secret not in str(status)
    assert status["api_key_present"] is True


async def test_setup_status_endpoint_works_while_disabled(monkeypatch):
    """The endpoint itself must not be gated behind POSTIZ_ENABLED."""
    from agent.api import postiz as postiz_api
    _env(monkeypatch)
    result = await postiz_api.setup_status()
    assert result["postiz_enabled"] is False
    assert result["next_steps"]


async def test_localhost_ipv6_trap_is_detected_with_exact_fix(monkeypatch):
    """Windows: localhost may resolve to ::1 where Docker's proxy hangs while
    127.0.0.1 answers — the doctor must name the exact fix (found live)."""
    _env(monkeypatch, POSTIZ_ENABLED="true",
         POSTIZ_BASE_URL="http://localhost:5000", POSTIZ_API_KEY="k")

    async def fake_probe(url):
        return "127.0.0.1" in url  # localhost dead, IPv4 alive

    monkeypatch.setattr(pz, "probe_reachable", fake_probe)
    status = await pz.setup_status()
    assert "POSTIZ_LOCALHOST_RESOLVES_IPV6" in status["problems"]
    assert any("POSTIZ_BASE_URL=http://127.0.0.1:5000" in s for s in status["next_steps"])
    # The rendered .env block must match the advice — no localhost/127.0.0.1
    # contradiction in the UI.
    assert status["safe_env_example"]["POSTIZ_BASE_URL"] == "http://127.0.0.1:5000"
    # The module-level template itself stays untouched.
    assert pz.SAFE_ENV_EXAMPLE["POSTIZ_BASE_URL"] == "http://localhost:5000"
