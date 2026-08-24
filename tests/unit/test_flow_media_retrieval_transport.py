"""Regression coverage for the current Flow media delivery contract.

Flow exposes a delivery-tile UUID in the DOM but the metadata endpoint now
expects the generation resource key captured from the authenticated project
payload.  These tests stay zero-credit and exercise only the local relay/client
contract and terminal job bridge.
"""

from pathlib import Path

import pytest

from agent.services.flow_client import FlowClient
from agent.services import make_video as mv


DELIVERY_MEDIA_ID = "11111111-1111-4111-8111-111111111111"
GENERATION_MEDIA_ID = "flowMedia/22222222-2222-4222-8222-222222222222"
ROOT = Path(__file__).resolve().parents[2]


async def test_harvest_mapping_drives_media_metadata_request(monkeypatch):
    client = FlowClient()
    calls = []

    async def fake_send(method, params, timeout=None):
        calls.append((method, params, timeout))
        if method == "HARVEST_VIDEO_URLS":
            return {
                "result": {
                    "diag": {
                        "mediaGenerationIds": {
                            DELIVERY_MEDIA_ID: GENERATION_MEDIA_ID,
                        }
                    }
                }
            }
        return {"status": 200, "data": {}}

    monkeypatch.setattr(client, "_send", fake_send)

    await client.harvest_video_urls(tab_id=42)
    await client.get_media(DELIVERY_MEDIA_ID)

    api_call = calls[-1]
    assert api_call[0] == "api_request"
    assert "/v1/media/22222222-2222-4222-8222-222222222222?" in api_call[1]["url"]
    assert DELIVERY_MEDIA_ID not in api_call[1]["url"]


async def test_media_redirect_relay_is_authenticated_and_bounded(monkeypatch):
    client = FlowClient()
    calls = []

    async def fake_send(method, params, timeout=None):
        calls.append((method, params, timeout))
        return {
            "result": {
                "ok": True,
                "status": 200,
                "media_id": DELIVERY_MEDIA_ID,
                "url": "https://flow-content.google/video/signed-token",
            }
        }

    monkeypatch.setattr(client, "_send", fake_send)

    result = await client.get_media_download_url(DELIVERY_MEDIA_ID)

    assert result["ok"] is True
    assert calls == [
        (
            "MEDIA_URL_REDIRECT",
            {
                "url": (
                    "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name="
                    + DELIVERY_MEDIA_ID
                )
            },
            30,
        )
    ]


async def test_project_media_unwraps_current_flow_identity_payload(monkeypatch):
    client = FlowClient()
    calls = []
    current_media = {
        "name": DELIVERY_MEDIA_ID,
        "projectId": "project-1",
        "mediaMetadata": {
            "mediaStatus": {
                "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
            },
        },
        "video": {"generatedVideo": {"prompt": "prompt", "model": "model"}},
    }

    async def fake_send(method, params, timeout=None):
        calls.append((method, params, timeout))
        return {
            "status": 200,
            "data": {
                "result": {
                    "data": {
                        "json": {
                            "projectId": "project-1",
                            "projectContents": {"media": [current_media]},
                        },
                    },
                },
            },
        }

    monkeypatch.setattr(client, "_send", fake_send)

    result = await client.list_project_media("project-1")

    assert result == {
        "status": 200,
        "project_id": "project-1",
        "media": [current_media],
    }
    assert calls[0][0] == "trpc_request"
    assert calls[0][1]["method"] == "GET"
    assert "flow.projectInitialData?input=" in calls[0][1]["url"]
    assert calls[0][2] == 30


async def test_correlated_output_records_media_fetch_failure_without_accepting_tile(monkeypatch):
    class _Client:
        async def get_media(self, _media_id):
            return {
                "status": 400,
                "data": {"error": {"status": "INVALID_ARGUMENT"}},
            }

    stats = {
        "unverifiable": 0,
        "prompt_mismatched": 0,
        "model_mismatched": 0,
        "seed_mismatched": 0,
        "unverifiable_ids": [],
    }
    result = await mv._accept_correlated_output(
        _Client(), [DELIVERY_MEDIA_ID], set(),
        {"submitted_prompt": "this run", "seed": None}, stats,
    )

    assert result == (None, None, None, None)
    assert stats["media_fetch_errors"] == 1
    assert stats["media_fetch_error_ids"] == [DELIVERY_MEDIA_ID]
    assert stats["media_fetch_error_statuses"][DELIVERY_MEDIA_ID] == 400


async def test_current_project_metadata_correlates_then_downloads_delivery_tile(
        tmp_path, monkeypatch):
    prompt = "this run"
    project_id = "project-1"
    download_calls = []

    class _Client:
        async def get_media(self, _media_id, media_generation_id=None):
            return {
                "status": 400,
                "data": {"error": {"status": "INVALID_ARGUMENT"}},
            }

        async def list_project_media(self, observed_project_id):
            assert observed_project_id == project_id
            return {
                "status": 200,
                "project_id": project_id,
                "media": [{
                    "name": DELIVERY_MEDIA_ID,
                    "projectId": project_id,
                    "mediaMetadata": {
                        "mediaStatus": {
                            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                        },
                    },
                    "video": {"generatedVideo": {
                        "prompt": (
                            "<root><instruction><prompt>this run</prompt>"
                            "</instruction></root>"
                        ),
                        "model": "veo_3_1_r2v_lite",
                        "seed": 603743,
                    }},
                }],
            }

    async def fake_download(_client, media_id, _url, media_generation_id=None):
        download_calls.append(media_id)
        return b"\x00\x00\x00\x18ftypmp42" + (b"v" * 20000), "media_redirect"

    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(mv, "_download_video_bytes", fake_download)
    stats = {
        "unverifiable": 0,
        "prompt_mismatched": 0,
        "model_mismatched": 0,
        "seed_mismatched": 0,
        "unverifiable_ids": [],
    }

    mid, path, size, evidence = await mv._accept_correlated_output(
        _Client(), [DELIVERY_MEDIA_ID], set(),
        {"submitted_prompt": prompt, "expected_model": "veo_3_1_r2v_lite",
         "seed": None, "_project_id": project_id},
        stats,
    )

    assert mid == DELIVERY_MEDIA_ID
    assert Path(path).read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
    assert size > 0
    assert download_calls == [DELIVERY_MEDIA_ID]
    assert evidence["metadata_source"] == "project_initial_data"
    assert evidence["retrieval_source"] == "media_redirect"
    assert evidence["prompt_normalization"] == "XML_INNER_PROMPT"
    assert stats["project_metadata_fallback_ids"] == [DELIVERY_MEDIA_ID]


async def test_current_project_metadata_still_rejects_foreign_prompt(
        tmp_path, monkeypatch):
    class _Client:
        async def get_media(self, _media_id):
            return {"status": 400}

        async def list_project_media(self, _project_id):
            return {
                "status": 200,
                "project_id": "project-1",
                "media": [{
                    "name": DELIVERY_MEDIA_ID,
                    "mediaMetadata": {"mediaStatus": {
                        "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                    }},
                    "video": {"generatedVideo": {
                        "prompt": "another run",
                        "model": "veo_3_1_r2v_lite",
                    }},
                }],
            }

    async def must_not_download(*_args, **_kwargs):
        raise AssertionError("foreign media must be rejected before download")

    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(mv, "_download_video_bytes", must_not_download)
    stats = {
        "unverifiable": 0,
        "prompt_mismatched": 0,
        "model_mismatched": 0,
        "seed_mismatched": 0,
        "unverifiable_ids": [],
    }

    result = await mv._accept_correlated_output(
        _Client(), [DELIVERY_MEDIA_ID], set(),
        {"submitted_prompt": "this run", "seed": None,
         "_project_id": "project-1"}, stats,
    )

    assert result == (None, None, None, None)
    assert stats["prompt_mismatched"] == 1


def test_flow_content_delivery_host_is_strictly_allowlisted():
    assert mv._DIRECT_FIFE_URL_RE.match(
        "https://flow-content.google/video/signed-token")
    assert mv._DIRECT_FIFE_URL_RE.match(
        "https://region.flow-content.google/video/signed-token")
    assert not mv._DIRECT_FIFE_URL_RE.match(
        "https://flow-content.google.attacker.example/video/signed-token")


async def test_image_without_inline_url_uses_delivery_id_from_flow_redirect():
    calls = []

    class _Client:
        async def get_media_download_url(self, media_id):
            calls.append(media_id)
            return {"ok": True, "url": "https://flow-content.google/image/signed-token"}

    resolved = await mv._resolve_media_download_url(
        _Client(),
        "projects/p/media/generation-key",
        "/fx/api/trpc/media.getMediaUrlRedirect?name=" + DELIVERY_MEDIA_ID,
    )

    assert resolved == "https://flow-content.google/image/signed-token"
    assert calls == [DELIVERY_MEDIA_ID]


async def test_terminal_bridge_closes_render_without_waiting_forever(monkeypatch):
    import agent.api.flow as flow

    calls = []

    monkeypatch.setattr(
        mv,
        "get_job",
        lambda _job_id: {
            "status": "RENDER_NOT_MATERIALIZED",
            "stage": "render_not_materialized",
            "error": "render did not materialize",
        },
    )

    async def record(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(flow.crud, "add_stage_event", record)
    monkeypatch.setattr(flow.crud, "upsert_request_telemetry", record)
    monkeypatch.setattr(flow.crud, "update_request", record)
    monkeypatch.setattr(flow, "_persist_output_correlation_evidence", record)
    monkeypatch.setattr(flow.crud, "_now", lambda: "now")

    await flow._bridge_generate_job_telemetry("req-1", "job-1", {})

    request_updates = [kwargs for _, kwargs in calls if kwargs.get("status") == "FAILED"]
    assert any(update.get("error_code") == "render did not materialize" for update in request_updates)
    assert any(update.get("status") == "FAILED" for update in request_updates)


def test_new_render_terminal_states_release_video_lane():
    mv._JOBS.clear()
    try:
        for status in ("RENDER_NOT_MATERIALIZED", "STALE_OR_FOREIGN_CANDIDATES_ONLY"):
            mv._JOBS[status] = {"status": status}
            assert mv._job_active(status) is False
    finally:
        mv._JOBS.clear()


def test_extension_bridges_generation_mapping_and_bound_media_delivery():
    content = (ROOT / "extension" / "content.js").read_text(encoding="utf-8")
    injected = (ROOT / "extension" / "injected.js").read_text(encoding="utf-8")
    background = (ROOT / "extension" / "background.js").read_text(encoding="utf-8")

    assert "TRPC_MEDIA_URLS" in content
    assert "chrome.runtime.sendMessage" in content
    assert "hasGenerationMapping" in injected
    assert "flowMediaGenerationIds" in background
    assert "MEDIA_URL_REDIRECT" in background
    assert "mediaGenerationIds" in background
    assert "handleReloadFlowTab(msg.params?.tab_id)" in background


@pytest.mark.parametrize("rotated_field", ["connection_id", "flow_tab_id", "project_id"])
async def test_bound_retrieval_rejects_connection_tab_or_project_rotation(
    monkeypatch, rotated_field
):
    """A paid attempt may retrieve only through its challenged connection/tab/project."""

    expected_url = "https://labs.google/fx/tools/flow/project/project-a"
    lease = {
        "lease_id": "lease-a",
        "connection_id": "connection-a",
        "connection_epoch": 1,
        "installation_id": "installation-a",
        "extension_session_id": "session-a",
        "extension_build": "build-a",
        "flow_tab_id": 41,
        "flow_url": expected_url,
        "flow_project_id": "project-a",
    }
    observed = {
        "connection_id": "connection-a",
        "installation_id": "installation-a",
        "extension_session_id": "session-a",
        "flow_tab_id": 41,
        "project_id": "project-a",
    }
    if rotated_field == "connection_id":
        observed["connection_id"] = "connection-b"
    elif rotated_field == "flow_tab_id":
        observed["flow_tab_id"] = 99
    else:
        observed["project_id"] = "project-b"
    observed_url = (
        "https://labs.google/fx/tools/flow/project/" + observed["project_id"]
    )

    class _Client:
        async def create_agent_session(self, project_id):
            assert project_id == "project-a"
            return {"data": {"sessionInfo": {"agentSessionId": "session-provider"}}}

        async def harvest_video_urls(self, tab_id=None):
            return {
                "result": {
                    "connection_id": observed["connection_id"],
                    "installation_id": observed["installation_id"],
                    "extension_session_id": observed["extension_session_id"],
                    "flow_tab_found": True,
                    "flow_tab_id": observed["flow_tab_id"],
                    "flow_url": observed_url,
                    "flow_project_id": observed["project_id"],
                    "handled_flow_tab_id": observed["flow_tab_id"],
                    "handled_flow_url": observed_url,
                    "handled_flow_project_id": observed["project_id"],
                    "envelope_flow_tab_id": observed["flow_tab_id"],
                    "envelope_flow_url": observed_url,
                    "diag": {
                        "projectId": observed["project_id"],
                        "videoIds": [DELIVERY_MEDIA_ID],
                    },
                }
            }

    async def bind(_client, requested_project_id=None, job=None):
        assert requested_project_id == "project-a"
        return {
            "project_id": "project-a",
            "flow_tab_id": 41,
            "flow_project_url": expected_url,
            "bridge_lease": dict(lease),
        }

    async def negotiate(*_args, **_kwargs):
        return {
            "approved": True,
            "model_ok": True,
            "duration_ok": True,
            "model_used": "veo_3_1_r2v_lite",
            "duration_used": 8,
        }

    async def no_known_media():
        return set()

    async def no_sync(_job):
        return True

    class _InstantAsyncio:
        def __init__(self, real):
            self._real = real

        async def sleep(self, *_args, **_kwargs):
            return None

        def __getattr__(self, name):
            return getattr(self._real, name)

    job_id = "g_bound_retrieval_" + rotated_field
    mv._JOBS.clear()
    mv._JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "project_id": "project-a",
        "bridge_lease": dict(lease),
        "provider_generation_submit_count": 0,
    }
    monkeypatch.setattr(mv, "get_flow_client", lambda: _Client())
    monkeypatch.setattr(mv, "_bind_with_recovery", bind)
    monkeypatch.setattr(mv.agent_video, "negotiate_and_generate", negotiate)
    monkeypatch.setattr(mv, "_durable_media_exclusion", no_known_media)
    monkeypatch.setattr(mv, "_sync_durable_single_job", no_sync)
    monkeypatch.setattr(mv, "asyncio", _InstantAsyncio(mv.asyncio))

    try:
        await mv._run_generate(
            job_id,
            "T2V",
            "prompt",
            "project-a",
            None,
            None,
            "9:16",
            None,
            model="veo_3_1_lite",
            duration_s=8,
        )
        job = mv._JOBS[job_id]
        assert job["status"] == "GENERATED_BUT_UNRETRIEVED", (
            job.get("error"),
            job.get("original_error"),
            job.get("approved"),
            job.get("stage"),
        )
        assert "BOUND_RETRIEVAL_IDENTITY_MISMATCH" in job["original_error"]
        assert job["provider_generation_submit_count"] == 1
    finally:
        mv._JOBS.clear()
