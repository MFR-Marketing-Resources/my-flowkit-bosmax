"""Native-extend API surface: fail-closed status codes + DRY_RUN default."""
import pytest
from fastapi import HTTPException

from agent.api import flow


async def test_extend_video_missing_parent_is_422():
    body = flow.GenerateVideoExtendRequest(
        source_media_id="", project_id="p", scene_id="s", position=1, prompt="x")
    with pytest.raises(HTTPException) as exc:
        await flow.extend_video(body)
    assert exc.value.status_code == 422
    assert "EXTEND_PARENT_MEDIA_ID_MISSING" in str(exc.value.detail)


async def test_extend_video_unknown_aspect_is_422():
    body = flow.GenerateVideoExtendRequest(
        source_media_id="m", project_id="p", scene_id="s", position=1, prompt="x",
        aspect_ratio="VIDEO_ASPECT_RATIO_SQUARE")
    with pytest.raises(HTTPException) as exc:
        await flow.extend_video(body)
    assert exc.value.status_code == 422
    assert "EXTEND_UNSUPPORTED_MODEL" in str(exc.value.detail)


async def test_extend_video_disabled_flag_is_409(monkeypatch):
    monkeypatch.delenv("NATIVE_EXTEND_ENABLED", raising=False)
    body = flow.GenerateVideoExtendRequest(
        source_media_id="m", project_id="p", scene_id="s", position=1, prompt="x")
    with pytest.raises(HTTPException) as exc:
        await flow.extend_video(body)
    assert exc.value.status_code == 409
    assert "NATIVE_EXTEND_DISABLED" in str(exc.value.detail)


async def test_extend_video_confirm_required_is_409(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    body = flow.GenerateVideoExtendRequest(
        source_media_id="m", project_id="p", scene_id="s", position=1, prompt="x",
        confirm_live_credit_burn=False)
    with pytest.raises(HTTPException) as exc:
        await flow.extend_video(body)
    assert exc.value.status_code == 409
    assert "confirm_live_credit_burn" in str(exc.value.detail)


async def test_extend_run_dry_run_default_spends_nothing():
    body = flow.ExtendRunRequest(
        project_id="p", scene_id="s", source_operation_id="op1",
        blocks=[flow.ExtendBlockModel(block_index=2, position=1, prompt="b2",
                                      is_final=True)])
    out = await flow.extend_run(body)
    assert out["dry_run"] is True
    assert out["blocks"][0]["polling_state"] == "SOURCE_READY"
