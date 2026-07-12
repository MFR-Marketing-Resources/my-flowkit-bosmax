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
