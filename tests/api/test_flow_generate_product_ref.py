"""PR A proof: POST /api/flow/generate (mode:IMG) anchors on a product image.

A BOSMAX product row has media_id=null and exposes its image via image_url, so the
frontend sends it as refs.subjectAsset { mediaId: null, downloadUrl: <image_url> }.
These tests prove the one-door /generate handler resolves that reference into the
image_media_ids passed to make_video.start_generate — WITHOUT hitting live Flow —
and that a resolver failure prevents generation from starting (fail closed).

Mirrors the mocking pattern of tests/api/test_generate_validation.py.
"""

import asyncio

from fastapi import HTTPException

from agent.api import flow


def _run(coro):
    return asyncio.run(coro)


def test_product_subject_downloadurl_resolves_into_image_media_ids(monkeypatch):
    calls = {"start_generate": None, "uploaded": [], "materialized": []}

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def upload_image(self, b64, mime_type="image/png", project_id="", file_name=""):
            calls["uploaded"].append(file_name)
            return {"_mediaId": "fresh-upload-1", "data": {}}

    async def fake_materialize(url, file_name):
        calls["materialized"].append(url)
        import pathlib
        import tempfile

        p = pathlib.Path(tempfile.gettempdir()) / "bosmax_test_product_ref.png"
        p.write_bytes(b"\x89PNG_fake")
        return {"local_file_path": str(p), "file_name": file_name, "mime_type": "image/png"}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None, **kw):
        calls["start_generate"] = {"mode": mode, "image_media_ids": image_media_ids}
        return {"job_id": "g_prod_ref", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow, "_materialize_remote_url_to_staging", fake_materialize)
    from agent.services import make_video as mv

    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    # Product-shaped subject asset — exactly what productSubjectAsset() emits for a
    # /api/products row (media_id=null, image_url surfaced as downloadUrl).
    body = flow.GenerateRequest(
        mode="IMG",
        prompt="Poster prompt text",
        refs={
            "subjectAsset": {
                "mediaId": None,
                "localFilePath": None,
                "downloadUrl": "https://s.500fd.com/tt_product/minyak.webp",
                "assetSource": "PRODUCT_IMAGE_URL",
            }
        },
    )
    result = _run(flow.generate(body))

    assert result["status"] == "SUBMITTED"
    # The product image URL was materialized + uploaded BEFORE generation...
    assert calls["materialized"] == ["https://s.500fd.com/tt_product/minyak.webp"]
    # ...and the resulting media id reached the generation call as a reference.
    assert calls["start_generate"] is not None
    assert calls["start_generate"]["mode"] == "IMG"
    assert "fresh-upload-1" in calls["start_generate"]["image_media_ids"]


def test_subject_resolver_failure_prevents_start_generate(monkeypatch):
    calls = {"start_generate": None}

    class _C:
        connected = True

    async def fake_start_generate(*a, **k):
        calls["start_generate"] = True
        return {"job_id": "x", "status": "SUBMITTED"}

    async def boom(client, asset, slot, *a, **k):
        # Resolver fails closed (e.g. ERR_SUBJECT_UPLOAD_API_FAILED).
        raise HTTPException(422, "ERR_SUBJECT_UPLOAD_API_FAILED")

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow, "_resolve_asset_to_media_id", boom)
    from agent.services import make_video as mv

    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = flow.GenerateRequest(
        mode="IMG",
        prompt="Poster prompt text",
        refs={"subjectAsset": {"mediaId": None, "downloadUrl": "https://x/p.webp"}},
    )

    try:
        _run(flow.generate(body))
        raise AssertionError("expected the resolver failure to propagate")
    except HTTPException as e:
        assert e.status_code == 422

    # Generation must NEVER start when the product reference could not be resolved.
    assert calls["start_generate"] is None
