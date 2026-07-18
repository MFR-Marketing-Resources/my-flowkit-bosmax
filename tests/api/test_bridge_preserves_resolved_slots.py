"""from-execution-package must PRESERVE the WEP's resolved asset slots.

Live defect: wep_c35fff00bc18ef8b resolved start_frame -> ca_e468d188d12d4343
(an APPROVED 9:16 composite frame), but the bridged WGP carried the re-defaulted
product-image:* slot (raw 4:5 catalog photo) — which the aspect gate then
correctly blocked (SLOT_ASPECT_MISMATCH). The bridge dropped the reviewed
resolution; seeding must carry it through.
"""
import json

import pytest

from agent.api import workspace_generation_packages as api


@pytest.mark.asyncio
async def test_f2v_bridge_passes_resolved_start_and_end_frames(monkeypatch):
    wep = {
        "workspace_execution_package_id": "wep_x",
        "product_id": "prod-1",
        "mode": "F2V",
        "request_lineage_payload": json.dumps({"compiler": {"source_mode": "FRAMES"}}),
        "asset_slots": json.dumps([
            {"slot_key": "start_frame", "required": True,
             "resolved_asset": {"asset_id": "ca_start_916"}},
            {"slot_key": "end_frame", "required": False,
             "resolved_asset": {"asset_id": None}},
        ]),
    }

    async def get_wgp(_id):
        return None  # force the execution-package table lookup

    class _Cur:
        async def fetchone(self):
            return wep

    class _DB:
        async def execute(self, *_a, **_k):
            return _Cur()

    async def get_db():
        return _DB()

    captured = {}

    async def fake_f2v(**kw):
        captured.update(kw)
        return {"workspace_generation_package_id": "wgp_new",
                "resolved_engine_slots_json": json.dumps(
                    {"start_frame": kw.get("start_frame_asset_id"), "end_frame": kw.get("end_frame_asset_id")})}

    monkeypatch.setattr("agent.db.crud.get_workspace_generation_package", get_wgp)
    monkeypatch.setattr("agent.db.schema.get_db", get_db)
    monkeypatch.setattr(api, "create_f2v_generation_package", fake_f2v)

    pkg = await api.create_from_execution_package(
        workspace_execution_package_id="wep_x", mode="F2V")

    # The reviewed resolution is carried through — never re-defaulted.
    assert captured["start_frame_asset_id"] == "ca_start_916"
    assert captured["end_frame_asset_id"] is None
    slots = json.loads(pkg["resolved_engine_slots_json"])
    assert slots["start_frame"] == "ca_start_916"


@pytest.mark.asyncio
async def test_bridge_without_resolved_assets_keeps_the_default_seed(monkeypatch):
    """A WEP with no resolved assets behaves exactly as before (product-image seed
    comes from the seeding service itself when asset ids are None)."""
    wep = {
        "workspace_execution_package_id": "wep_y",
        "product_id": "prod-1",
        "mode": "F2V",
        "request_lineage_payload": "{}",
        "asset_slots": "[]",
    }

    async def get_wgp(_id):
        return None

    class _Cur:
        async def fetchone(self):
            return wep

    class _DB:
        async def execute(self, *_a, **_k):
            return _Cur()

    async def get_db():
        return _DB()

    captured = {}

    async def fake_f2v(**kw):
        captured.update(kw)
        return {"workspace_generation_package_id": "wgp_new2"}

    monkeypatch.setattr("agent.db.crud.get_workspace_generation_package", get_wgp)
    monkeypatch.setattr("agent.db.schema.get_db", get_db)
    monkeypatch.setattr(api, "create_f2v_generation_package", fake_f2v)

    await api.create_from_execution_package(
        workspace_execution_package_id="wep_y", mode="F2V")
    assert captured["start_frame_asset_id"] is None
    assert captured["end_frame_asset_id"] is None


@pytest.mark.asyncio
async def test_i2v_bridge_maps_subject_scene_style_and_skips_product_image_refs(monkeypatch):
    """I2V WEP slots are subject/scene/style. The bridge maps them to the
    resolver's reference-asset params, skipping auto-seeded product-image:* refs
    (not creative-asset ids — the resolver's own product auto-seed applies)."""
    wep = {
        "workspace_execution_package_id": "wep_i2v",
        "product_id": "prod-1",
        "mode": "I2V",
        "request_lineage_payload": "{}",
        "asset_slots": json.dumps([
            {"slot_key": "subject",
             "resolved_asset": {"asset_id": "product-image:prod-1:subject"}},
            {"slot_key": "scene", "resolved_asset": {"asset_id": "ca_scene_1"}},
            {"slot_key": "style", "resolved_asset": {"asset_id": "ca_style_1"}},
        ]),
    }

    async def get_wgp(_id):
        return None

    class _Cur:
        async def fetchone(self):
            return wep

    class _DB:
        async def execute(self, *_a, **_k):
            return _Cur()

    async def get_db():
        return _DB()

    captured = {}

    async def fake_i2v(**kw):
        captured.update(kw)
        return {"workspace_generation_package_id": "wgp_i2v_new"}

    monkeypatch.setattr("agent.db.crud.get_workspace_generation_package", get_wgp)
    monkeypatch.setattr("agent.db.schema.get_db", get_db)
    monkeypatch.setattr(api, "create_i2v_generation_package", fake_i2v)

    await api.create_from_execution_package(
        workspace_execution_package_id="wep_i2v", mode="I2V")

    assert captured["character_reference_asset_id"] is None      # product-image skipped
    assert captured["scene_context_reference_asset_id"] == "ca_scene_1"
    assert captured["style_reference_asset_id"] == "ca_style_1"
