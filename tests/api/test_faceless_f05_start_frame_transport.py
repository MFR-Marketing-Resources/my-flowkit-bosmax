"""F-05: Faceless start-frame must reach make_video.start_generate.

Regression for PR #666 defect: UI prepared package with start_frame_asset_id but
POST /api/flow/generate omitted startAsset / image_media_ids. Package id alone
does not load the frame into the one-door reference resolver.

These tests call the real generate() handler with the Faceless payload shape
(buildFacelessGenerateBody parity) and assert image refs hit start_generate.
"""

from __future__ import annotations

import asyncio

from agent.api import flow


def _run(coro):
    return asyncio.run(coro)


def _mock_video_client(monkeypatch, calls: dict):
    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

        async def upload_image(
            self, b64, mime_type="image/png", project_id="", file_name=""
        ):
            calls["uploaded"].append(file_name)
            return {"_mediaId": "fresh-faceless-upload", "data": {}}

    async def fake_materialize(url, file_name):
        calls["materialized"].append(url)
        import pathlib
        import tempfile

        p = pathlib.Path(tempfile.gettempdir()) / "bosmax_faceless_f05.png"
        p.write_bytes(b"\x89PNG_fake_faceless")
        return {
            "local_file_path": str(p),
            "file_name": file_name,
            "mime_type": "image/png",
        }

    async def fake_start_generate(
        mode, prompt, project_id=None, image_media_ids=None, **kw
    ):
        calls["start_generate"] = {
            "mode": mode,
            "prompt": prompt,
            "image_media_ids": list(image_media_ids or []),
        }
        return {"job_id": "g_faceless_f05", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow, "_materialize_remote_url_to_staging", fake_materialize)
    from agent.services import make_video as mv

    monkeypatch.setattr(mv, "start_generate", fake_start_generate)


def test_faceless_start_asset_downloadurl_reaches_start_generate(monkeypatch):
    """Operator-selected frame as startAsset.downloadUrl (package-resolved shape)."""
    calls: dict = {"start_generate": None, "uploaded": [], "materialized": []}
    _mock_video_client(monkeypatch, calls)

    # Mirrors buildFacelessGenerateBody() output — NOT package-id-only.
    body = flow.GenerateRequest(
        mode="F2V",
        prompt="Faceless animate THIS product image",
        aspect="9:16",
        product_id="prod-1",
        startAsset={
            "mediaId": None,
            "assetId": "ca_start_selected",
            "downloadUrl": "https://cdn.example.com/operator-start.png",
            "previewUrl": "https://cdn.example.com/operator-start.png",
            "fileName": "start.png",
            "assetSource": "CREATIVE_LIBRARY_COMPOSITE",
        },
        image_media_ids=[],
    )
    result = _run(flow.generate(body))

    assert result["status"] == "SUBMITTED"
    assert calls["materialized"] == [
        "https://cdn.example.com/operator-start.png"
    ]
    assert calls["start_generate"] is not None
    assert calls["start_generate"]["mode"] == "F2V"
    assert "fresh-faceless-upload" in calls["start_generate"]["image_media_ids"]


def test_faceless_start_asset_live_media_id_reaches_start_generate(monkeypatch):
    calls: dict = {"start_generate": None, "uploaded": [], "materialized": []}
    _mock_video_client(monkeypatch, calls)
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    body = flow.GenerateRequest(
        mode="F2V",
        prompt="Faceless with live media",
        aspect="9:16",
        startAsset={
            "mediaId": uuid,
            "assetId": "ca_live",
            "fileName": "live.png",
        },
        image_media_ids=[uuid],
    )
    result = _run(flow.generate(body))

    assert result["status"] == "SUBMITTED"
    assert uuid in calls["start_generate"]["image_media_ids"]


def test_faceless_package_id_only_does_not_inject_start_frame(monkeypatch):
    """Document the defect class: package id without startAsset → empty refs."""
    calls: dict = {"start_generate": None, "uploaded": [], "materialized": []}
    _mock_video_client(monkeypatch, calls)

    # Pre-fix Faceless payload (what PR #666 UI sent).
    body = flow.GenerateRequest(
        mode="F2V",
        prompt="Faceless without frame transport",
        aspect="9:16",
        product_id="prod-1",
        image_media_ids=None,
        startAsset=None,
    )
    # Extra unknown fields are stripped by the model — simulate by not passing them.
    result = _run(flow.generate(body))

    # Without startAsset, start_generate may still run for F2V if engine allows
    # empty refs (image_prompt path) — the invariant we care about is NO operator
    # frame id appears. This test locks that package id is not magically resolved.
    assert calls["start_generate"] is not None
    ids = calls["start_generate"]["image_media_ids"]
    assert "fresh-faceless-upload" not in ids
    assert calls["materialized"] == []
