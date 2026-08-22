import asyncio
from unittest.mock import AsyncMock

from agent.api import operator


def _run(coro):
    return asyncio.run(coro)


def _authenticated_runtime():
    return {
        "runtime_sha": "a" * 40,
        "origin_main": "a" * 40,
        "runtime_current_main": True,
        "release_dir": "C:/runtime/releases/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_stale": False,
        "release_dirty": False,
        "db_canonical": True,
        "bundle_matches": True,
        "dashboard_bundle": "index-test.js",
    }


class _AgentFlowClient:
    connected = True

    def __init__(self):
        self.check_composer_calls = 0

    async def get_status(self, timeout=5):
        return {
            "connected": True,
            "flow_key_present": True,
            "extension_session_id": "session-agent",
            "extension_id": "extension-agent",
            "extension_version": "0.2.0",
            "extension_build": "build-agent",
        }

    async def verify_provider_session_challenge(self, _flow_tab_id):
        return {
            "extension_session_id": "session-agent",
            "extension_id": "extension-agent",
            "extension_version": "0.2.0",
            "extension_build": "build-agent",
            "extension_build_match": True,
            "flow_tab_found": True,
            "flow_project_url": "https://labs.google/fx/tools/flow/project/project-agent",
            "flow_project_id": "project-agent",
            "content_script_loaded": True,
            "content_script_alive": True,
            "session_challenge_verified": True,
            "same_extension_session": True,
            "same_flow_tab": True,
            "challenge_nonce_match": True,
        }

    async def get_credits(self):
        return {"data": {"credits": 978}}

    async def check_flow_composer_ready(self, _mode):
        self.check_composer_calls += 1
        raise AssertionError("AGENT_T2V must not require legacy UI composer proof")


def test_api_first_reference_agent_route_skips_legacy_composer_gate():
    request = operator.FlowProviderReadinessRequest(
        provider_browser_authority_mode="DEDICATED_CDP_UAT",
        provider_execution_route="API_FIRST_GENERATIVE_REFERENCE",
        scene_scaffold_route="AGENT_T2V",
    )
    assert operator._provider_ui_composer_required(request) is False


def test_flow_provider_readiness_accepts_authenticated_agent_transport_without_composer(
    monkeypatch,
):
    client = _AgentFlowClient()
    monkeypatch.setattr(operator, "_provider_readiness_runtime", AsyncMock(return_value=_authenticated_runtime()))
    monkeypatch.setattr(operator, "get_flow_client", lambda: client)
    monkeypatch.setattr(operator.crud, "list_video_production_jobs", AsyncMock(return_value=[]))

    result = _run(
        operator.flow_provider_readiness(
            operator.FlowProviderReadinessRequest(
                provider_browser_authority_mode="DEDICATED_CDP_UAT",
                provider_execution_route="API_FIRST_GENERATIVE_REFERENCE",
                scene_scaffold_route="AGENT_T2V",
            )
        )
    )

    assert result["ui_composer_required"] is False
    assert result["FLOW_PROVIDER_UAT_READY"] is True
    assert result["primary_blocker"] == "FLOW_PROVIDER_UAT_READY"
    assert result["composer_found"] is False
    assert client.check_composer_calls == 0


def test_non_agent_reference_route_keeps_legacy_composer_gate():
    request = operator.FlowProviderReadinessRequest(
        provider_browser_authority_mode="DEDICATED_CDP_UAT",
        provider_execution_route="API_FIRST_GENERATIVE_REFERENCE",
        scene_scaffold_route="UI_COMPOSER",
    )
    assert operator._provider_ui_composer_required(request) is True
