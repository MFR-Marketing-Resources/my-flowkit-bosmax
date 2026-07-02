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
            "startAsset": {"mediaId": "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"}, "aspect": "9:16"}
    result = _run(flow_api._run_manual_job_via_generate(body, "F2V", body["startAsset"]))

    assert result["ok"] is True and result["lane"] == "API_FIRST_GENERATE"
    assert calls["create_project"] == 1                       # project self-provisioned
    assert calls["open_target"] == [
        "https://labs.google/fx/tools/flow/project/new-proj-1"]
    assert calls["start_generate"]["project_id"] == "new-proj-1"   # bind pinned to it
    assert calls["start_generate"]["image_media_ids"] == ["aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"]
    assert "API_PROJECT_CREATED" in calls["stages"]


def test_manual_lane_materializes_remote_url_only_package_asset(monkeypatch):
    # VERBATIM frontend payload shape (live manual_259f0ab1, BOSMAX_DEBUG console):
    # mediaId null, localFilePath "", assetId is a COMPOSITE BOSMAX id (not a Flow
    # media UUID), and the only source is a remote downloadUrl. The lane previously
    # mistook the composite assetId for a Flow media id, skipped materialization,
    # and fail-closed ERR_START_MEDIA_NOT_FOUND. It must download + upload instead.
    calls = {"materialized": [], "uploaded": [], "start_generate": None, "stages": []}

    class _C:
        connected = True

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "flow_url": "https://labs.google/fx/tools/flow/project/open-9",
                               "diag": {"projectId": "open-9"}}}

        async def upload_image(self, b64, mime_type="image/png", project_id="", file_name=""):
            calls["uploaded"].append(file_name)
            return {"_mediaId": "fresh-upload-1", "data": {}}

    async def fake_materialize(url, file_name):
        calls["materialized"].append(url)
        import pathlib, tempfile
        p = pathlib.Path(tempfile.gettempdir()) / "bosmax_test_start.png"
        p.write_bytes(b"\x89PNG_fake")
        return {"local_file_path": str(p), "file_name": file_name, "mime_type": "image/png"}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None,
                                  aspect="9:16", tier="PAYGATE_TIER_ONE", **kw):
        calls["start_generate"] = {"image_media_ids": image_media_ids}
        return {"job_id": "g_test3", "status": "SUBMITTED", "mode": mode}

    async def fake_stage(request_id, stage, status, message, source, **kw):
        calls["stages"].append(stage)

    async def fake_upsert(request_id, **kw):
        return None

    monkeypatch.setattr(flow_api, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow_api, "_materialize_remote_url_to_staging", fake_materialize)
    monkeypatch.setattr(flow_api.crud, "add_stage_event", fake_stage)
    monkeypatch.setattr(flow_api.crud, "upsert_request_telemetry", fake_upsert)
    import agent.services.make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    start_asset = {
        "mediaId": None,
        "fileName": "82c54d11-8de3-47a9-bbc6-297056ed0fab.jpg",
        "label": "Product remote image URL",
        "previewUrl": "https://s.500fd.com/tt_product/x.webp",
        "downloadUrl": "https://s.500fd.com/tt_product/x.webp",
        "localFilePath": "",
        "assetId": "product-image:82c54d11-8de3-47a9-bbc6-297056ed0fab:start_frame",
        "assetSource": "PRODUCT_IMAGE_URL",
        "localImagePathPresent": False,
        "remoteImageUrlPresent": True,
    }
    body = {"request_id": "manual_test3", "prompt": "make it",
            "startAsset": start_asset, "aspect": "9:16"}
    result = _run(flow_api._run_manual_job_via_generate(body, "F2V", start_asset))

    assert result["ok"] is True
    assert calls["materialized"] == ["https://s.500fd.com/tt_product/x.webp"]
    assert calls["uploaded"], "remote asset must be uploaded via API"
    assert calls["start_generate"]["image_media_ids"] == ["fresh-upload-1"]
    assert "API_START_ASSET_MATERIALIZED" in calls["stages"]
    assert "API_START_ASSET_UPLOADED" in calls["stages"]


def test_extract_flow_media_id_rejects_composite_bosmax_ids():
    assert flow_api._extract_flow_media_id(
        {"assetId": "product-image:82c54d11-8de3-47a9-bbc6-297056ed0fab:start_frame"}) is None
    assert flow_api._extract_flow_media_id(
        {"mediaId": "dcf0b2a3-b714-4305-a0de-37033f9762a1"}) == "dcf0b2a3-b714-4305-a0de-37033f9762a1"
    assert flow_api._extract_flow_media_id({"mediaId": None, "assetId": ""}) is None


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
            "startAsset": {"mediaId": "cccccccc-1111-4222-8333-dddddddddddd"}, "aspect": "9:16"}
    result = _run(flow_api._run_manual_job_via_generate(body, "F2V", body["startAsset"]))

    assert result["ok"] is True
    assert calls["create_project"] == 0                    # never mints when editor open
    assert calls["start_generate"]["project_id"] is None   # binds the open editor
