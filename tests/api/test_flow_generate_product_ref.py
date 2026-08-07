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


def test_product_subject_bare_media_id_passes_into_image_media_ids(monkeypatch):
    """SCALE-07 case A: a product with a live Flow media_id (sent as
    refs.subjectAsset.mediaId) passes through to the generator's image_media_ids."""
    calls = {"start_generate": None}
    uuid = "12345678-1234-1234-1234-123456789abc"

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None, **kw):
        calls["start_generate"] = {"mode": mode, "image_media_ids": image_media_ids}
        return {"job_id": "g", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv

    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = flow.GenerateRequest(
        mode="IMG",
        prompt="Poster prompt text",
        refs={"subjectAsset": {"mediaId": uuid, "assetSource": "PRODUCT_IMAGE_URL"}},
    )
    result = _run(flow.generate(body))

    assert result["status"] == "SUBMITTED"
    assert uuid in calls["start_generate"]["image_media_ids"]


def test_product_subject_local_file_uploads_into_image_media_ids(monkeypatch):
    """SCALE-07 case C: a product with only a local cached file (sent as
    refs.subjectAsset.localFilePath) is uploaded and reaches image_media_ids."""
    import pathlib
    import tempfile

    calls = {"start_generate": None, "uploaded": []}
    local = pathlib.Path(tempfile.gettempdir()) / "bosmax_test_local_product_ref.png"
    local.write_bytes(b"\x89PNG_local_fake")

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

        async def upload_image(self, b64, mime_type="image/png", project_id="", file_name=""):
            calls["uploaded"].append(file_name)
            return {"_mediaId": "fresh-local-1", "data": {}}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None, **kw):
        calls["start_generate"] = {"mode": mode, "image_media_ids": image_media_ids}
        return {"job_id": "g", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv

    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = flow.GenerateRequest(
        mode="IMG",
        prompt="Poster prompt text",
        refs={
            "subjectAsset": {
                "mediaId": None,
                "localFilePath": str(local),
                "assetSource": "PRODUCT_IMAGE_URL",
            }
        },
    )
    result = _run(flow.generate(body))

    assert result["status"] == "SUBMITTED"
    assert calls["uploaded"], "the local product file must be uploaded before generation"
    assert "fresh-local-1" in calls["start_generate"]["image_media_ids"]


def test_img_generation_orders_product_reference_before_explicit_refs(monkeypatch):
    """IMG must put the product slot first in the provider reference list.

    The dashboard sends product truth in ``refs.productAsset`` while older
    callers still populate ``image_media_ids`` with avatar/scene references.
    Those two sources must be merged in canonical slot order so the product is
    not silently demoted to the final, unlabeled provider input.
    """
    calls = {"start_generate": None}
    product = "11111111-1111-1111-1111-111111111111"
    subject = "22222222-2222-2222-2222-222222222222"
    scene = "33333333-3333-3333-3333-333333333333"
    avatar = "44444444-4444-4444-4444-444444444444"

    class _C:
        connected = True

        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None, **kw):
        calls["start_generate"] = {
            "mode": mode,
            "image_media_ids": image_media_ids,
        }
        return {"job_id": "g_order", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv

    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    body = flow.GenerateRequest(
        mode="IMG",
        prompt="Product hero prompt",
        # These are legacy/explicit non-product references. ``scene`` is also
        # present in refs to prove duplicate suppression during the merge.
        image_media_ids=[avatar, scene],
        refs={
            "productAsset": {"mediaId": product},
            "subjectAsset": {"mediaId": subject},
            "sceneAsset": {"mediaId": scene},
        },
    )

    result = _run(flow.generate(body))

    assert result["status"] == "SUBMITTED"
    assert calls["start_generate"] is not None
    assert calls["start_generate"]["image_media_ids"] == [
        product,
        subject,
        scene,
        avatar,
    ]
