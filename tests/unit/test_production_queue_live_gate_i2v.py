"""ONE_SERIAL_I2V — the ingredients/references live gate + aspect-gate scoping.

I2V fires generate_video_with_references / veo_3_1_r2v_lite — the exact tool +
model the HYBRID fire live-proved (g_8845373fbb86) — through the same one door.
This suite mirrors the F2V-gate proofs (fail-closed before any state change;
mode-exact loop authorization) and pins the FRAMING-gate scoping: the
SLOT_ASPECT gate applies to output-frame slots (start_frame/end_frame) ONLY —
I2V ingredient references (subject/scene/style) are identity sources, not
frames, and must never be blocked for aspect.
"""
import json

import pytest

from agent.services import production_queue_service as pq

RUN_ID = "run_i2v_1"
WGP_ID = "wgp_i2v_1"
GREEN = {"checked": 1, "ready": 1, "blocked": 0, "items": [{"package_id": WGP_ID}]}


def _run(config=None, status="PENDING"):
    cfg = {"model": "Veo 3.1 - Lite", "aspect": "9:16", "count": 1,
           "last_dry_run_report": GREEN}
    cfg.update(config or {})
    return {"production_run_id": RUN_ID, "status": status, "dry_run": 1,
            "config_json": json.dumps(cfg)}


def _item(**over):
    item = {
        "workspace_generation_package_id": WGP_ID,
        "product_id": "prod-i2v-1",
        "logical_mode": "I2V", "mode": "I2V", "source_lane": "INGREDIENTS",
        "production_status": "QUEUED", "production_job_id": None,
        "final_prompt_text": "a synthetic i2v prompt",
        "resolved_engine_slots_json": json.dumps({"subject": "ca_subject", "scene": "ca_scene"}),
    }
    item.update(over)
    return item


@pytest.fixture
def queue(monkeypatch):
    state = {"run": _run(), "items": [_item()], "updates": [], "scheduled": [],
             "payload_mode": "I2V", "payload_blockers": []}

    async def get_production_run(run_id):
        return state["run"] if run_id == RUN_ID else None

    async def list_pkgs(production_run_id=None, production_status=None, **kw):
        return list(state["items"])

    async def update_run(run_id, **kw):
        state["updates"].append(kw)
        return state["run"]

    async def bep(item, cfg):
        return ({"logical_mode": state["payload_mode"], "mode": state["payload_mode"]},
                list(state["payload_blockers"]))

    def ensure_future(coro):
        state["scheduled"].append(coro)
        coro.close()
        return None

    monkeypatch.setattr(pq.crud, "get_production_run", get_production_run)
    monkeypatch.setattr(pq.crud, "list_production_queue_packages", list_pkgs)
    monkeypatch.setattr(pq.crud, "update_production_run", update_run)
    monkeypatch.setattr(pq, "build_execution_payload", bep)
    monkeypatch.setattr(pq.asyncio, "ensure_future", ensure_future)
    return state


def _nothing_fired(state):
    assert state["scheduled"] == []
    for u in state["updates"]:
        assert u.get("dry_run") != 0 and u.get("status") != "RUNNING"


def _live_write(state):
    lives = [u for u in state["updates"] if u.get("dry_run") == 0]
    return lives[-1] if lives else None


async def _go_live_i2v(**over):
    kw = {"confirm_live_credit_burn": True,
          "live_gate": pq.LIVE_GATE_ONE_SERIAL_I2V,
          "confirm_phrase": pq.LIVE_I2V_CONFIRM_PHRASE,
          "expect_package_id": WGP_ID}
    kw.update(over)
    return await pq.run_production_queue(RUN_ID, **kw)


# ── Gate: happy path + fail-closed mirror ─────────────────────────────────


@pytest.mark.asyncio
async def test_one_ready_i2v_item_goes_live_and_authorizes_exactly_i2v(queue):
    res = await _go_live_i2v()
    assert res["status"] == "RUNNING" and res["package_id"] == WGP_ID
    written = json.loads(_live_write(queue)["config_json"])
    assert written.get("authorized_live_mode") == "I2V"


@pytest.mark.parametrize("phrase", [
    None, "", "authorize_one_i2v_live_run", "AUTHORIZE_ONE_T2V_LIVE_RUN",
    "AUTHORIZE_ONE_F2V_LIVE_RUN",  # the first-frame phrase can NEVER authorize I2V
])
@pytest.mark.asyncio
async def test_wrong_phrase_refuses(queue, phrase):
    with pytest.raises(ValueError, match="LIVE_CONFIRM_PHRASE_INVALID"):
        await _go_live_i2v(confirm_phrase=phrase)
    _nothing_fired(queue)


@pytest.mark.parametrize("mode", ["T2V", "F2V", "HYBRID"])
@pytest.mark.asyncio
async def test_non_i2v_item_refuses(queue, mode):
    queue["payload_mode"] = mode
    with pytest.raises(ValueError, match="LIVE_I2V_ONLY"):
        await _go_live_i2v()
    _nothing_fired(queue)


@pytest.mark.asyncio
async def test_two_items_refuse_fan_out(queue):
    queue["items"] = [_item(), _item(workspace_generation_package_id="wgp_i2v_2")]
    with pytest.raises(ValueError, match="LIVE_REQUIRES_EXACTLY_ONE_ITEM:2"):
        await _go_live_i2v()
    _nothing_fired(queue)


@pytest.mark.asyncio
async def test_prior_job_refuses(queue):
    queue["items"] = [_item(production_job_id="job_done")]
    with pytest.raises(ValueError, match="LIVE_DUPLICATE_SUBMISSION"):
        await _go_live_i2v()
    _nothing_fired(queue)


@pytest.mark.asyncio
async def test_no_green_dry_run_refuses(queue):
    queue["run"] = _run({"last_dry_run_report": None})
    with pytest.raises(ValueError, match="LIVE_REQUIRES_DRY_RUN_READY"):
        await _go_live_i2v()
    _nothing_fired(queue)


# ── Loop authorization (mode-exact) ───────────────────────────────────────


@pytest.fixture
def loop(monkeypatch):
    state = {"queue": [], "updates": [], "fired": [], "cfg": {}}

    async def get_run(rid):
        return {"production_run_id": RUN_ID, "status": "RUNNING",
                "config_json": json.dumps(state["cfg"]),
                "interval_min_seconds": 0, "interval_max_seconds": 0,
                "cooldown_after_n_jobs": 5, "cooldown_seconds": 0,
                "total_completed": 0, "total_failed": 0, "error_log_json": "[]"}

    async def list_pkgs(production_run_id=None, production_status=None, **kw):
        return [state["queue"].pop(0)] if state["queue"] else []

    async def update_wgp(wgp_id, **kw):
        state["updates"].append({"wgp_id": wgp_id, **kw})
        return {}

    async def update_run(rid, **kw):
        return {}

    async def fire(make_video, payload, wgp_id):
        state["fired"].append(wgp_id)
        return {"ok": True}

    monkeypatch.setattr(pq.crud, "get_production_run", get_run)
    monkeypatch.setattr(pq.crud, "list_production_queue_packages", list_pkgs)
    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", update_wgp)
    monkeypatch.setattr(pq.crud, "update_production_run", update_run)
    monkeypatch.setattr(pq, "_fire_and_wait", fire)
    return state


def _lp(mode, blockers=None):
    async def bep(item, cfg):
        return ({"logical_mode": mode, "mode": mode, "prompt": "x"}, blockers or [])
    return bep


@pytest.mark.asyncio
async def test_authorized_i2v_run_fires_i2v(loop, monkeypatch):
    loop["cfg"] = {"authorized_live_mode": "I2V"}
    monkeypatch.setattr(pq, "build_execution_payload", _lp("I2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_i2v"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == ["wgp_i2v"]


@pytest.mark.asyncio
async def test_i2v_authorization_does_not_admit_f2v(loop, monkeypatch):
    loop["cfg"] = {"authorized_live_mode": "I2V"}
    monkeypatch.setattr(pq, "build_execution_payload", _lp("F2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_stray"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and failed[0]["production_error"].startswith("LIVE_MODE_NOT_AUTHORIZED:F2V")


@pytest.mark.asyncio
async def test_unauthorized_i2v_still_blocked_in_the_loop(loop, monkeypatch):
    loop["cfg"] = {}
    monkeypatch.setattr(pq, "build_execution_payload", _lp("I2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_i2v"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and failed[0]["production_error"].startswith("LIVE_T2V_ONLY:I2V")


# ── Aspect-gate SCOPING: frame slots only ─────────────────────────────────


class _FakeClient:
    connected = True

    def __init__(self):
        self.upload_calls = []
        self.get_media_calls = []

    async def upload_image(self, image_base64, mime_type="", project_id="", file_name=""):
        self.upload_calls.append(file_name)
        return {"_mediaId": "11111111-1111-1111-1111-111111111111"}

    async def get_media(self, media_id):
        self.get_media_calls.append(media_id)
        return {"status": 200}


def _png(tmp_path, name, w, h):
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", (w, h), (0, 100, 0)).save(p)
    return str(p)


async def _noop(*a, **k):
    return None


@pytest.mark.asyncio
async def test_i2v_ingredient_ref_is_never_aspect_blocked(monkeypatch, tmp_path):
    """A 4:5 ingredient reference on a 9:16 I2V run uploads fine — identity
    sources are not output frames."""
    client = _FakeClient()
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    img = _png(tmp_path, "ref_4x5.png", 1122, 1402)

    async def get_asset(aid):
        return {"asset_id": aid, "media_id": "", "local_file_path": img}
    monkeypatch.setattr(pq.crud, "get_creative_asset", get_asset)
    monkeypatch.setattr(pq.crud, "update_creative_asset", _noop)

    blockers = await pq._resolve_and_upload_image_slots(
        {"workspace_generation_package_id": "wgp_x", "logical_mode": "I2V",
         "product_id": "prod-1",
         "resolved_engine_slots_json": json.dumps({"subject": "ca_ref"})},
        {"aspect": "9:16"})
    assert blockers == []
    assert client.upload_calls == ["ref_4x5.png"]


@pytest.mark.asyncio
async def test_f2v_frame_slot_still_aspect_blocked(monkeypatch, tmp_path):
    """Scoping must NOT weaken the frame gate: start_frame at 4:5 still blocks."""
    client = _FakeClient()
    monkeypatch.setattr("agent.services.flow_client.get_flow_client", lambda: client)
    img = _png(tmp_path, "frame_4x5.png", 1122, 1402)

    async def get_product(pid):
        return {"id": pid, "media_id": "", "local_image_path": img}
    monkeypatch.setattr(pq.crud, "get_product", get_product)
    monkeypatch.setattr(pq.crud, "update_product", _noop)

    blockers = await pq._resolve_and_upload_image_slots(
        {"workspace_generation_package_id": "wgp_y", "logical_mode": "F2V",
         "product_id": "prod-1",
         "resolved_engine_slots_json": json.dumps({"start_frame": "product-image:prod-1"})},
        {"aspect": "9:16"})
    assert any("SLOT_ASPECT_MISMATCH" in b for b in blockers)
    assert client.upload_calls == []
