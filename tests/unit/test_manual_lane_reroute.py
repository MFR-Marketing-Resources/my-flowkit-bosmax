"""Manual-lane API-first reroute — project self-provisioning contract.

Live manual_1fb86ffd (2026-07-02): the user deleted every Flow project, so the
manual F2V button died NO_OPEN_EDITOR after a successful stale-media self-heal.
A user-initiated dashboard job must create + open a project EXPLICITLY (with
telemetry) and pin the video bind to it — never fail because Flow is empty.
"""
import asyncio

from agent.api import flow as flow_api


def _run(coro):
    return asyncio.run(coro)


def test_manual_lane_creates_and_pins_project_when_no_editor_open(monkeypatch):
    calls = {"create_project": 0, "open_target": [], "start_generate": None,
             "stages": []}

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

        async def harvest_video_urls(self, tab_id=None):
            # No editor open: root shell, no projectId.
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "flow_url": "https://labs.google/fx/tools/flow",
                               "diag": {"projectId": None}}}

        async def create_project(self, title, tool_name="PINHOLE"):
            calls["create_project"] += 1
            return {"data": {"result": {"projectId": "new-proj-1"}}}

        async def open_target_flow_project(self, url):
            calls["open_target"].append(url)
            return {"ok": True}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None,
                                  aspect="9:16", tier="PAYGATE_TIER_ONE", **kw):
        calls["start_generate"] = {"mode": mode, "project_id": project_id,
                                   "image_media_ids": image_media_ids}
        return {"job_id": "g_test1", "status": "SUBMITTED", "mode": mode}

    async def fake_stage(request_id, stage, status, message, source, **kw):
        calls["stages"].append(stage)

    async def fake_upsert(request_id, **kw):
        return None

    monkeypatch.setattr(flow_api, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow_api.crud, "add_stage_event", fake_stage)
    monkeypatch.setattr(flow_api.crud, "upsert_request_telemetry", fake_upsert)
    import agent.services.make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = {"request_id": "manual_test1", "prompt": "make it",
            "startAsset": {"mediaId": "ref-ok-1"}, "aspect": "9:16"}
    result = _run(flow_api._run_manual_job_via_generate(body, "F2V", body["startAsset"]))

    assert result["ok"] is True and result["lane"] == "API_FIRST_GENERATE"
    assert calls["create_project"] == 1                       # project self-provisioned
    assert calls["open_target"] == [
        "https://labs.google/fx/tools/flow/project/new-proj-1"]
    assert calls["start_generate"]["project_id"] == "new-proj-1"   # bind pinned to it
    assert calls["start_generate"]["image_media_ids"] == ["ref-ok-1"]
    assert "API_PROJECT_CREATED" in calls["stages"]


def test_manual_lane_reuses_open_editor_without_minting(monkeypatch):
    calls = {"create_project": 0, "start_generate": None}

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "flow_url": "https://labs.google/fx/tools/flow/project/open-1",
                               "diag": {"projectId": "open-1"}}}

        async def create_project(self, title, tool_name="PINHOLE"):
            calls["create_project"] += 1
            return {}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None,
                                  aspect="9:16", tier="PAYGATE_TIER_ONE", **kw):
        calls["start_generate"] = {"project_id": project_id}
        return {"job_id": "g_test2", "status": "SUBMITTED", "mode": mode}

    async def fake_stage(*a, **kw):
        return None

    async def fake_upsert(request_id, **kw):
        return None

    monkeypatch.setattr(flow_api, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow_api.crud, "add_stage_event", fake_stage)
    monkeypatch.setattr(flow_api.crud, "upsert_request_telemetry", fake_upsert)
    import agent.services.make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = {"request_id": "manual_test2", "prompt": "make it",
            "startAsset": {"mediaId": "ref-ok-2"}, "aspect": "9:16"}
    result = _run(flow_api._run_manual_job_via_generate(body, "F2V", body["startAsset"]))

    assert result["ok"] is True
    assert calls["create_project"] == 0                    # never mints when editor open
    assert calls["start_generate"]["project_id"] is None   # binds the open editor
