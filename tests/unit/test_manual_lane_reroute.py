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


def test_manual_lane_resolves_i2v_refs_aspect_and_model(monkeypatch):
    # I2V/IMG modules send refs.{subjectAsset,sceneAsset,styleAsset} (NOT startAsset),
    # plus orientation (not aspect) and the model ui_label. Previously refs were
    # DROPPED (I2V died ERR_START_ASSET_REQUIRED), orientation was ignored (always
    # 9:16) and model was ignored. All three must flow through.
    calls = {"uploaded": [], "start_generate": None}

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "flow_url": "https://labs.google/fx/tools/flow/project/open-2",
                               "diag": {"projectId": "open-2"}}}

        async def upload_image(self, b64, mime_type="image/png", project_id="", file_name=""):
            calls["uploaded"].append(file_name)
            return {"_mediaId": "fresh-upload-1", "data": {}}

    async def fake_materialize(url, file_name):
        import pathlib, tempfile
        p = pathlib.Path(tempfile.gettempdir()) / "bosmax_test_ref.png"
        p.write_bytes(b"\x89PNG_fake")
        return {"local_file_path": str(p), "file_name": file_name, "mime_type": "image/png"}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None,
                                  aspect="9:16", tier="PAYGATE_TIER_ONE", model=None,
                                  duration_s=None, num_videos=1, **kw):
        calls["start_generate"] = {"mode": mode, "image_media_ids": image_media_ids,
                                   "aspect": aspect, "model": model,
                                   "duration_s": duration_s, "num_videos": num_videos}
        return {"job_id": "g_test4", "status": "SUBMITTED", "mode": mode}

    async def fake_stage(*a, **kw):
        return None

    async def fake_upsert(request_id, **kw):
        return None

    monkeypatch.setattr(flow_api, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow_api, "_materialize_remote_url_to_staging", fake_materialize)
    monkeypatch.setattr(flow_api.crud, "add_stage_event", fake_stage)
    monkeypatch.setattr(flow_api.crud, "upsert_request_telemetry", fake_upsert)
    import agent.services.make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = {
        "request_id": "manual_test4",
        "prompt": "make it",
        "orientation": "HORIZONTAL",
        "model": "Veo 3.1 - Lite",
        "count": 2,
        "duration_s": 8,
        "refs": {
            "subjectAsset": {"mediaId": "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"},
            "sceneAsset": {"mediaId": None, "localFilePath": "",
                           "downloadUrl": "https://s.500fd.com/tt_product/scene.webp",
                           "assetId": "product-image:x:scene"},
            "styleAsset": None,
        },
    }
    result = _run(flow_api._run_manual_job_via_generate(body, "I2V", None))

    assert result["ok"] is True
    sg = calls["start_generate"]
    assert sg["image_media_ids"] == ["aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb", "fresh-upload-1"]
    assert sg["aspect"] == "16:9"                      # orientation HORIZONTAL honoured
    from agent.services import video_models as _vm
    assert sg["model"] == _vm.resolve("Veo 3.1 - Lite")["key"]  # ui_label resolved
    assert sg["num_videos"] == 2                       # count x2 honoured
    assert sg["duration_s"] == 8                       # duration honoured


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


# ── Source-lineage law at the preview boundary (2026-07-09 corrective audit) ──


def test_preview_source_mode_resolution_pins_caller_lineage():
    from agent.services.workspace_execution_package_service import (
        _resolve_preview_source_mode,
    )
    import pytest

    # A caller that names a canonical lineage keeps it (no silent HYBRID flip).
    assert _resolve_preview_source_mode("FRAMES", None) == "FRAMES"
    assert _resolve_preview_source_mode("INGREDIENTS", None) == "INGREDIENTS"
    assert _resolve_preview_source_mode("T2V", None) == "T2V"
    # Explicit source_mode always wins.
    assert _resolve_preview_source_mode("FRAMES", "HYBRID") == "HYBRID"
    assert _resolve_preview_source_mode("F2V", "FRAMES") == "FRAMES"
    # Ambiguous surface modes defer to the compiler's documented defaults.
    assert _resolve_preview_source_mode("F2V", None) is None
    assert _resolve_preview_source_mode("I2V", None) is None
    # Junk fails closed instead of silently compiling another lineage.
    with pytest.raises(ValueError, match="SOURCE_MODE_INVALID"):
        _resolve_preview_source_mode("FRAMES", "FRAMSE")


def test_f2v_source_lane_normalizer_fails_closed_on_junk():
    from agent.services.workspace_generation_package_service import (
        _normalize_f2v_source_lane,
    )
    import pytest

    assert _normalize_f2v_source_lane("FRAMES") == "FRAMES"
    assert _normalize_f2v_source_lane("hybrid") == "HYBRID"
    assert _normalize_f2v_source_lane(None) == "HYBRID"
    with pytest.raises(ValueError, match="SOURCE_MODE_INVALID"):
        _normalize_f2v_source_lane("FRAMS")


# ── source_mode default-to-HYBRID warning (2026-07-09 corrective audit item 9) ──


def test_source_lineage_default_warning_fires_only_for_bare_f2v():
    from agent.services.workspace_execution_package_service import (
        _source_lineage_default_warning,
    )

    # Bare F2V surface without explicit source_mode WILL default to HYBRID -> warn.
    w = _source_lineage_default_warning("F2V", None)
    assert w and "SOURCE_MODE_DEFAULTED_TO_HYBRID" in w
    # An explicit canonical lineage (raw mode) pins itself -> no warning.
    assert _source_lineage_default_warning("FRAMES", None) is None
    assert _source_lineage_default_warning("HYBRID", None) is None
    # Explicit source_mode given -> no warning (caller was intentional).
    assert _source_lineage_default_warning("F2V", "FRAMES") is None
    assert _source_lineage_default_warning("F2V", "HYBRID") is None
    # Non-F2V ambiguous surfaces do not warn (they resolve unambiguously).
    assert _source_lineage_default_warning("I2V", None) is None
    assert _source_lineage_default_warning("T2V", None) is None
    assert _source_lineage_default_warning("IMG", None) is None


# ── unified all-mode reference contract (operator lane) ─────────────────────
import pytest
from fastapi import HTTPException


def _contract_client():
    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "flow_url": "https://labs.google/fx/tools/flow/project/p1",
                               "diag": {"projectId": "p1"}}}
    return _C()


def _wire_contract(monkeypatch, calls):
    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None,
                                  aspect="9:16", tier="PAYGATE_TIER_ONE", **kw):
        calls["start_generate"] = {"mode": mode, "image_media_ids": image_media_ids}
        return {"job_id": "g_contract", "status": "SUBMITTED", "mode": mode}

    async def fake_stage(request_id, stage, status, message, source, **kw):
        calls.setdefault("stages", []).append((stage, message))

    async def fake_upsert(request_id, **kw):
        calls.setdefault("telemetry", []).append(kw.get("error_code"))

    monkeypatch.setattr(flow_api, "get_flow_client", _contract_client)
    monkeypatch.setattr(flow_api.crud, "add_stage_event", fake_stage)
    monkeypatch.setattr(flow_api.crud, "upsert_request_telemetry", fake_upsert)
    import agent.services.make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)


_UUID_A = "aaaaaaaa-1111-4222-8333-000000000001"
_UUID_B = "bbbbbbbb-1111-4222-8333-000000000002"
_UUID_C = "cccccccc-1111-4222-8333-000000000003"


def test_manual_lane_f2v_end_frame_reaches_flow_in_order(monkeypatch):
    """The user-selected END frame was previously materialized then silently
    DROPPED (never uploaded) — a 2-image F2V job must send BOTH frames, start
    first, end second."""
    calls = {}
    _wire_contract(monkeypatch, calls)
    body = {"request_id": "m_f2v2", "prompt": "make it",
            "startAsset": {"mediaId": _UUID_A},
            "endAsset": {"mediaId": _UUID_B},
            "source_mode": "F2V", "aspect": "9:16"}
    result = _run(flow_api._run_manual_job_via_generate(body, "F2V", body["startAsset"]))
    assert result["ok"] is True
    assert calls["start_generate"]["image_media_ids"] == [_UUID_A, _UUID_B]


def test_manual_lane_blocks_t2v_with_any_reference(monkeypatch):
    calls = {}
    _wire_contract(monkeypatch, calls)
    body = {"request_id": "m_t2vref", "prompt": "text only",
            "startAsset": {"mediaId": _UUID_A}, "source_mode": "T2V"}
    with pytest.raises(HTTPException) as exc:
        _run(flow_api._run_manual_job_via_generate(body, "T2V", body["startAsset"]))
    assert exc.value.status_code == 422
    assert "ERR_T2V_REFERENCES_FORBIDDEN" in str(exc.value.detail)
    assert "start_generate" not in calls          # zero transport, zero credit


def test_manual_lane_blocks_i2v_with_fewer_than_two_refs(monkeypatch):
    calls = {}
    _wire_contract(monkeypatch, calls)
    body = {"request_id": "m_i2v1", "prompt": "ingredients",
            "refs": {"subjectAsset": {"mediaId": _UUID_A}}}
    with pytest.raises(HTTPException) as exc:
        _run(flow_api._run_manual_job_via_generate(body, "I2V", None))
    assert exc.value.status_code == 422
    assert "ERR_REFERENCE_COUNT_CONTRACT" in str(exc.value.detail)
    assert "start_generate" not in calls


def test_manual_lane_hybrid_is_exactly_one_product_image(monkeypatch):
    calls = {}
    _wire_contract(monkeypatch, calls)
    # exactly 1 → allowed
    ok_body = {"request_id": "m_hyb1", "prompt": "hybrid",
               "startAsset": {"mediaId": _UUID_A}, "source_mode": "HYBRID"}
    result = _run(flow_api._run_manual_job_via_generate(ok_body, "F2V", ok_body["startAsset"]))
    assert result["ok"] is True
    assert calls["start_generate"]["image_media_ids"] == [_UUID_A]
    # a second image under HYBRID → blocked (never silently dropped)
    calls.clear()
    bad = {"request_id": "m_hyb2", "prompt": "hybrid",
           "startAsset": {"mediaId": _UUID_A}, "endAsset": {"mediaId": _UUID_B},
           "source_mode": "HYBRID"}
    with pytest.raises(HTTPException) as exc:
        _run(flow_api._run_manual_job_via_generate(bad, "F2V", bad["startAsset"]))
    assert exc.value.status_code == 422
    assert "ERR_REFERENCE_COUNT_CONTRACT" in str(exc.value.detail)
    assert "start_generate" not in calls


def test_manual_lane_blocks_f2v_with_more_than_two_refs(monkeypatch):
    calls = {}
    _wire_contract(monkeypatch, calls)
    body = {"request_id": "m_f2v3", "prompt": "frames",
            "startAsset": {"mediaId": _UUID_A}, "endAsset": {"mediaId": _UUID_B},
            "refs": {"subjectAsset": {"mediaId": _UUID_C}}}
    with pytest.raises(HTTPException) as exc:
        _run(flow_api._run_manual_job_via_generate(body, "F2V", body["startAsset"]))
    assert exc.value.status_code == 422
    assert "ERR_REFERENCE_COUNT_CONTRACT" in str(exc.value.detail)
    assert "start_generate" not in calls


def test_manual_lane_i2v_three_refs_preserve_slot_order(monkeypatch):
    calls = {}
    _wire_contract(monkeypatch, calls)
    body = {"request_id": "m_i2v3", "prompt": "ingredients",
            "refs": {"subjectAsset": {"mediaId": _UUID_A},
                     "sceneAsset": {"mediaId": _UUID_B},
                     "styleAsset": {"mediaId": _UUID_C}}}
    result = _run(flow_api._run_manual_job_via_generate(body, "I2V", None))
    assert result["ok"] is True
    # canonical order: subject → scene → style (semantic roles preserved)
    assert calls["start_generate"]["image_media_ids"] == [_UUID_A, _UUID_B, _UUID_C]
