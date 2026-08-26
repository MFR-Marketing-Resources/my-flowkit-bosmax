"""GET /api/flow/retrieved/{media_id} must serve the final concat deliverable.

The real full-duration video is registered as `final_{job_id}` (minted by
google_flow_final_timeline_runtime.save_final_video), NOT a bare Flow UUID.
Before the fix the route hard-rejected any non-UUID id with 422, so the genuine
16s final (e.g. final_vj_aa993dab70aa.mp4) could never be served/previewed.
The id pattern stays path-traversal-safe (alphanumerics + underscore only).
"""
import agent.config as cfg
from agent.api import flow as api
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock


def _seed_retrieved(tmp_path, monkeypatch, name: str) -> None:
    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path)
    rdir = tmp_path / "retrieved"
    rdir.mkdir(exist_ok=True)
    (rdir / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)


async def test_final_id_serves_the_video(tmp_path, monkeypatch):
    _seed_retrieved(tmp_path, monkeypatch, "final_vj_aa993dab70aa.mp4")
    resp = await api.get_retrieved_artifact("final_vj_aa993dab70aa")
    assert resp.media_type == "video/mp4"
    assert str(resp.path).endswith("final_vj_aa993dab70aa.mp4")


async def test_final_id_missing_file_is_404_not_422(tmp_path, monkeypatch):
    _seed_retrieved(tmp_path, monkeypatch, "final_vj_present.mp4")
    with pytest.raises(HTTPException) as exc:
        await api.get_retrieved_artifact("final_vj_absent")
    assert exc.value.status_code == 404


async def test_bare_uuid_still_accepted(tmp_path, monkeypatch):
    _seed_retrieved(tmp_path, monkeypatch, "x.mp4")  # unrelated file
    # Valid bare UUID passes the id gate; 404 only because no matching file.
    with pytest.raises(HTTPException) as exc:
        await api.get_retrieved_artifact(
            "69051c7b-1a50-4560-89a8-50795e12ff5c")
    assert exc.value.status_code == 404


async def test_path_traversal_and_garbage_rejected():
    for bad in [
        "final_../etc/passwd", "final_a/b", "../secret", "final_a/x",
        "not_final_x", "final_", "final_a.b",
    ]:
        with pytest.raises(HTTPException) as exc:
            await api.get_retrieved_artifact(bad)
        assert exc.value.status_code == 422, bad


async def test_registered_legacy_image_path_is_served(tmp_path, monkeypatch):
    media_id = "69051c7b-1a50-4560-89a8-50795e12ff5c"
    state_output = tmp_path / "state-output"
    monkeypatch.setattr(cfg, "OUTPUT_DIR", state_output)
    legacy_root = tmp_path / "legacy-checkout"
    legacy_retrieved = legacy_root / "output" / "retrieved"
    legacy_retrieved.mkdir(parents=True)
    image = legacy_retrieved / f"{media_id}.jpg"
    image.write_bytes(b"legacy-image")
    monkeypatch.setenv("BOSMAX_DEV_ROOT", str(legacy_root))
    monkeypatch.setattr(
        api.crud,
        "get_generated_artifact",
        AsyncMock(return_value={"media_id": media_id, "local_path": str(image)}),
    )

    response = await api.get_retrieved_artifact(media_id)

    assert response.media_type == "image/jpeg"
    assert response.path == image.resolve()


async def test_registered_unknown_outside_path_remains_forbidden(tmp_path, monkeypatch):
    media_id = "69051c7b-1a50-4560-89a8-50795e12ff5c"
    state_output = tmp_path / "state-output"
    monkeypatch.setattr(cfg, "OUTPUT_DIR", state_output)
    outside = tmp_path / "untrusted" / f"{media_id}.jpg"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"outside-image")
    monkeypatch.setenv("BOSMAX_DEV_ROOT", str(tmp_path / "different-checkout"))
    monkeypatch.setattr(
        api.crud,
        "get_generated_artifact",
        AsyncMock(return_value={"media_id": media_id, "local_path": str(outside)}),
    )

    with pytest.raises(HTTPException) as exc:
        await api.get_retrieved_artifact(media_id)

    assert exc.value.status_code == 403
