"""F2V/I2V/HYBRID image-slot upload pre-pass on the production-queue DRY RUN.

Image modes need their reference image present in Flow as a real media UUID before
build_execution_payload can resolve the slot. This credit-free dry-run pre-pass
(_resolve_and_upload_image_slots) uploads the on-disk image via flow_client.upload_image
(an asset upload, NOT start_generate) and persists the UUID, so the item can reach ready.

No provider generation is ever called: the fake client's upload_image is an asset
upload and get_media a liveness read. A regression that fired a generation would need
make_video, which this path never imports.
"""
import json

import pytest

from agent.services import production_queue_service as pq

UUID = "11111111-1111-1111-1111-111111111111"
UUID2 = "22222222-2222-2222-2222-222222222222"


class _FakeClient:
    def __init__(self, connected=True, live=True, upload_ok=True):
        self.connected = connected
        self._live = live
        self._upload_ok = upload_ok
        self.upload_calls = []
        self.get_media_calls = []

    async def upload_image(self, image_base64, mime_type="", project_id="", file_name=""):
        self.upload_calls.append(file_name)
        return {"_mediaId": UUID} if self._upload_ok else {"error": "boom"}

    async def get_media(self, media_id):
        self.get_media_calls.append(media_id)
        return {"status": 200} if self._live else {"error": "dead", "status": 404}


@pytest.fixture
def flow(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    return client


def _f2v_item(slots, mode="F2V"):
    return {
        "workspace_generation_package_id": "wgp_img",
        "logical_mode": mode,
        "product_id": "prod-1",
        "resolved_engine_slots_json": json.dumps(slots),
    }


async def _noop(*a, **k):
    return None


# ── T2V / IMG are no-ops: the pre-pass never touches Flow ─────────────────


@pytest.mark.parametrize("mode", ["T2V", "IMG"])
@pytest.mark.asyncio
async def test_prepass_is_noop_and_never_touches_flow_for_non_image_modes(flow, mode):
    item = {"workspace_generation_package_id": "wgp_x", "logical_mode": mode,
            "resolved_engine_slots_json": json.dumps({"start_frame": "product-image:prod-1"})}
    blockers = await pq._resolve_and_upload_image_slots(item, {})
    assert blockers == []
    assert flow.upload_calls == []          # no upload
    assert flow.get_media_calls == []       # client never even consulted


# ── Fail-closed paths ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_offline_extension_blocks_without_uploading(monkeypatch):
    client = _FakeClient(connected=False)
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert blockers == ["EXTENSION_OFFLINE_FOR_UPLOAD"]
    assert client.upload_calls == []


@pytest.mark.asyncio
async def test_missing_local_file_blocks(flow, monkeypatch):
    async def get_product(pid):
        return {"id": pid, "media_id": "", "local_image_path": "/does/not/exist.png"}
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert any("IMAGE_FILE_MISSING" in b for b in blockers)
    assert flow.upload_calls == []          # never uploaded a missing file


@pytest.mark.asyncio
async def test_upload_returning_no_media_id_blocks(monkeypatch, tmp_path):
    client = _FakeClient(upload_ok=False)
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    img = tmp_path / "p.png"
    img.write_bytes(b"pngbytes")

    async def get_product(pid):
        return {"id": pid, "media_id": "", "local_image_path": str(img)}
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert any("UPLOAD_NO_MEDIA_ID" in b for b in blockers)


# ── The happy path: upload a real on-disk image and persist the UUID ──────


@pytest.mark.asyncio
async def test_f2v_product_image_uploaded_and_persisted(flow, monkeypatch, tmp_path):
    img = tmp_path / "prod.png"
    img.write_bytes(b"\x89PNG-real-bytes")
    persisted = {}

    async def get_product(pid):
        return {"id": pid, "media_id": "", "local_image_path": str(img)}

    async def update_product(pid, **kw):
        persisted.update({"pid": pid, **kw})
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", update_product)

    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert blockers == []
    assert flow.upload_calls == ["prod.png"]
    assert persisted["media_id"] == UUID
    assert persisted["asset_status"] == "UPLOADED_TO_FLOW"


@pytest.mark.asyncio
async def test_creative_asset_slot_uploaded_and_persisted(flow, monkeypatch, tmp_path):
    img = tmp_path / "asset.jpg"
    img.write_bytes(b"jpegbytes")
    persisted = {}

    async def get_asset(aid):
        return {"id": aid, "media_id": "", "local_file_path": str(img)}

    async def update_asset(aid, **kw):
        persisted.update({"aid": aid, **kw})
    monkeypatch.setattr(pq.crud, "get_creative_asset", get_asset)
    monkeypatch.setattr(pq.crud, "update_creative_asset", update_asset)

    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "creative_asset_abc"}), {})
    assert blockers == []
    assert flow.upload_calls == ["asset.jpg"]
    assert persisted["media_id"] == UUID


@pytest.mark.asyncio
async def test_i2v_mode_also_uses_the_prepass(flow, monkeypatch, tmp_path):
    img = tmp_path / "i.png"
    img.write_bytes(b"i2vbytes")
    monkeypatch.setattr(pq.crud, "get_product",
                        _aret({"id": "prod-1", "media_id": "", "local_image_path": str(img)}))
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"ref": "product-image:prod-1"}, mode="I2V"), {})
    assert blockers == []
    assert flow.upload_calls == ["i.png"]


# ── Idempotency + self-heal ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_existing_live_uuid_is_reused_no_reupload(flow, monkeypatch):
    async def get_product(pid):
        return {"id": pid, "media_id": UUID, "local_image_path": "/whatever.png"}
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert blockers == []
    assert flow.upload_calls == []          # live UUID reused, nothing uploaded
    assert flow.get_media_calls == [UUID]   # but liveness WAS checked


@pytest.mark.asyncio
async def test_dead_persisted_uuid_self_heals_by_reupload(monkeypatch, tmp_path):
    client = _FakeClient(live=False)  # get_media reports dead
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    img = tmp_path / "reup.png"
    img.write_bytes(b"reupload")
    persisted = {}

    async def get_product(pid):
        return {"id": pid, "media_id": UUID2, "local_image_path": str(img)}

    async def update_product(pid, **kw):
        persisted.update(kw)
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", update_product)

    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert blockers == []
    assert client.upload_calls == ["reup.png"]   # dead UUID → re-uploaded
    assert persisted["media_id"] == UUID          # persisted the fresh one


# ── _upload_local_image unit ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_local_image_missing(flow):
    mid, blk = await pq._upload_local_image(flow, None)
    assert mid is None and blk == "IMAGE_FILE_MISSING"


@pytest.mark.asyncio
async def test_upload_local_image_success(flow, tmp_path):
    img = tmp_path / "ok.png"
    img.write_bytes(b"okbytes")
    mid, blk = await pq._upload_local_image(flow, str(img))
    assert mid == UUID and blk is None


# ── Integration: the dry-run report clears the slot blocker after upload ──


@pytest.mark.asyncio
async def test_dry_run_report_clears_slot_blocker_and_persists(flow, monkeypatch, tmp_path):
    img = tmp_path / "prod.png"
    img.write_bytes(b"PNGdata")
    store = {"prod-1": {"id": "prod-1", "media_id": "", "local_image_path": str(img)}}

    async def get_product(pid):
        return store.get(pid)

    async def update_product(pid, **kw):
        store[pid].update(kw)

    async def list_pkgs(production_run_id=None, production_status=None, **kw):
        return [{
            "workspace_generation_package_id": "wgp_f2v",
            "logical_mode": "F2V", "product_id": "prod-1",
            "final_prompt_text": "a real prompt",
            "resolved_engine_slots_json": json.dumps({"start_frame": "product-image:prod-1"}),
            "dom_handoff_payload_json": json.dumps({"settings": {"duration_seconds": 8}}),
        }]
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", update_product)
    monkeypatch.setattr(pq.crud, "list_production_queue_packages", list_pkgs)

    run = {"production_run_id": "run-1",
           "config_json": json.dumps({"model": "Veo 3.1 - Lite", "aspect": "9:16", "count": 1})}
    report = await pq._dry_run_report(run)

    item = report["items"][0]
    # The slot-not-uploaded blockers are GONE (the whole point of the pre-pass).
    assert not any("SLOT_NOT_UPLOADED" in b or "NO_FLOW_MEDIA" in b for b in item["blockers"])
    # And the UUID was persisted so a re-run is idempotent.
    assert store["prod-1"]["media_id"] == UUID


def _aret(value):
    async def _f(*a, **k):
        return value
    return _f


@pytest.mark.asyncio
async def test_upload_returning_a_non_uuid_media_id_blocks_and_persists_nothing(monkeypatch, tmp_path):
    """Defense-in-depth: a bad (non-UUID) upload response is a blocker, never
    stamped into product.media_id / asset_status=UPLOADED_TO_FLOW."""
    class _BadIdClient(_FakeClient):
        async def upload_image(self, image_base64, mime_type="", project_id="", file_name=""):
            self.upload_calls.append(file_name)
            return {"_mediaId": "not-a-flow-uuid"}
    client = _BadIdClient()
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    img = tmp_path / "p.png"
    img.write_bytes(b"pngbytes")
    persisted = {}

    async def get_product(pid):
        return {"id": pid, "media_id": "", "local_image_path": str(img)}

    async def update_product(pid, **kw):
        persisted.update(kw)
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", update_product)

    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert any("UPLOAD_BAD_MEDIA_ID" in b for b in blockers)
    assert persisted == {}          # nothing garbage written


# ── SLOT ASPECT GATE — wrong-frame source can never reach ready ───────────
#
# Live F2V g_7b29b837c259 fired with the RAW 4:5 catalog photo (1122x1402) as
# the start frame of a 9:16 run → letterboxed/oversized render. The pre-pass now
# fail-closes readiness when the slot's source image aspect differs from the run
# aspect by >3% — compose a target-aspect frame first (proven IMG lane).


def _png(tmp_path, name, w, h):
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", (w, h), (0, 128, 0)).save(p)
    return str(p)


@pytest.mark.asyncio
async def test_wrong_aspect_catalog_photo_blocks_readiness(flow, monkeypatch, tmp_path):
    """The exact live failure: 4:5 catalog photo on a 9:16 run → blocked, no upload."""
    img = _png(tmp_path, "catalog_4x5.png", 1122, 1402)
    monkeypatch.setattr(pq.crud, "get_product",
                        _aret({"id": "prod-1", "media_id": "", "local_image_path": img}))
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {"aspect": "9:16"})
    assert any("SLOT_ASPECT_MISMATCH" in b for b in blockers)
    assert flow.upload_calls == []          # never uploaded a wrong-frame source


@pytest.mark.asyncio
async def test_wrong_aspect_blocks_even_when_a_live_uuid_already_exists(flow, monkeypatch, tmp_path):
    """A previously-uploaded (live) UUID for a wrong-aspect source must not slip
    through the reuse path."""
    img = _png(tmp_path, "catalog_4x5.png", 800, 1000)
    monkeypatch.setattr(pq.crud, "get_product",
                        _aret({"id": "prod-1", "media_id": UUID, "local_image_path": img}))
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {"aspect": "9:16"})
    assert any("SLOT_ASPECT_MISMATCH" in b for b in blockers)
    assert flow.get_media_calls == []       # gate fires before the liveness check


@pytest.mark.asyncio
async def test_correct_aspect_frame_passes_and_uploads(flow, monkeypatch, tmp_path):
    img = _png(tmp_path, "composed_9x16.png", 1080, 1920)
    persisted = {}

    async def update_product(pid, **kw):
        persisted.update(kw)
    monkeypatch.setattr(pq.crud, "get_product",
                        _aret({"id": "prod-1", "media_id": "", "local_image_path": img}))
    monkeypatch.setattr(pq.crud, "update_product", update_product)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {"aspect": "9:16"})
    assert blockers == []
    assert flow.upload_calls == ["composed_9x16.png"]
    assert persisted["media_id"] == UUID


@pytest.mark.asyncio
async def test_no_run_aspect_leaves_the_gate_off(flow, monkeypatch, tmp_path):
    """Empty cfg (no aspect) → gate off — pre-existing behaviour unchanged."""
    img = _png(tmp_path, "catalog_4x5.png", 1122, 1402)
    monkeypatch.setattr(pq.crud, "get_product",
                        _aret({"id": "prod-1", "media_id": "", "local_image_path": img}))
    monkeypatch.setattr(pq.crud, "update_product", _noop)
    blockers = await pq._resolve_and_upload_image_slots(
        _f2v_item({"start_frame": "product-image:prod-1"}), {})
    assert blockers == []
    assert flow.upload_calls == ["catalog_4x5.png"]


def test_aspect_ratio_parser_fails_closed_to_none():
    assert pq._aspect_ratio_of("9:16") == pytest.approx(0.5625)
    assert pq._aspect_ratio_of("16:9") == pytest.approx(1.7778, rel=1e-3)
    assert pq._aspect_ratio_of(None) is None
    assert pq._aspect_ratio_of("garbage") is None
    assert pq._aspect_ratio_of("9:0") is None
