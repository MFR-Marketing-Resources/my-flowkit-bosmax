"""Unit tests — workspace_generation_package_service.

Tests F2V and I2V package creation, manual handoff payload generation,
DOM scaffold generation, and BLOCKED vs READY_MANUAL status.
"""
import json
import pytest

from agent.services.workspace_generation_package_service import (
    _build_dom_scaffold,
    _build_manual_handoff,
    create_f2v_generation_package,
    create_i2v_generation_package,
    get_workspace_generation_package,
    list_workspace_generation_packages,
)


# ─── Shared fakes ────────────────────────────────────────────

FAKE_APPROVED_PKG = {
    "prompt_package_snapshot_id": "pkg_test_001",
    "product_id": "prod-001",
    "product_name": "Bosmax Test Product",
    "mode": "F2V",
    "production_generation_allowed": False,
    "prompt_text": "Compiled F2V prompt",
    "prompt_fingerprint": "fp_test_001",
    "asset_slots": [],
    "manual_fallback": {"copy_prompt_available": True},
    "blockers": [],
    "source_of_truth_notes": [],
    "claim_safe_rewrite": None,
}

FAKE_COMPILE_RESULT = {
    "final_compiled_prompt_text": "Block 1 (ANCHOR)\nShow product with creator.",
    "prompt_blocks": [{"block_id": "block_1", "block_index": 1, "duration_seconds": 8}],
    "prompt_fingerprint": "fp_compiled_001",
}

# The REAL resolver contract (I2VSemanticSlotResolverResponse.model_dump()):
# resolved_assets with slot_key in subject/scene/style — NOT the old invented
# "resolved_slots" shape, which hid a live crash (the service called dict .get()
# on the pydantic model and read a non-existent key; every real I2V create died
# with "'I2VSemanticSlotResolverResponse' object has no attribute 'get'").
FAKE_RESOLVER_RESULT = {
    "mode": "I2V",
    "recipe_id": "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
    "resolved_assets": [
        {
            "slot_key": "subject",
            "semantic_role": "character_reference",
            "asset_id": "asset_char_001",
            "asset_fingerprint": "af_char",
            "display_name": "Test Character",
            "preview_url": "/api/creative-assets/asset_char_001/preview",
            "download_url": "/api/creative-assets/asset_char_001/download",
        },
        {
            "slot_key": "scene",
            "semantic_role": "scene_context",
            "asset_id": "asset_scene_001",
            "asset_fingerprint": "af_scene",
            "display_name": "Test Scene",
            "preview_url": "/api/creative-assets/asset_scene_001/preview",
            "download_url": "/api/creative-assets/asset_scene_001/download",
        },
    ],
    "warnings": [],
    "blockers": [],
    "compiler_context_summary": "Character: Test Character | Scene: Test Scene",
}

FAKE_WGP_ROW = {
    "workspace_generation_package_id": "wgp_abc123",
    "mode": "F2V",
    "product_id": "prod-001",
    "product_name_snapshot": "Bosmax Test Product",
    "source_lane": "F2V",
    "prompt_package_snapshot_id": "pkg_test_001",
    "workspace_execution_package_id": None,
    "generation_mode": "SINGLE",
    "final_prompt_text": "Block 1 (ANCHOR)\nShow product with creator.",
    "prompt_blocks_json": "[]",
    "selected_assets_json": "{}",
    "resolved_engine_slots_json": "{}",
    "resolver_output_json": "{}",
    "image_assets_json": "{}",
    "manual_handoff_json": "{}",
    "dom_handoff_payload_json": '{"readiness": {"manual_handoff_ready": true, "dom_handoff_ready": false, "blockers": [], "warnings": []}}',
    "blockers_json": "[]",
    "warnings_json": "[]",
    "status": "READY_MANUAL",
    "created_at": "2026-05-19T00:00:00Z",
    "updated_at": "2026-05-19T00:00:00Z",
}


# ─── DOM scaffold ─────────────────────────────────────────────

def test_dom_scaffold_dom_handoff_ready_is_always_false():
    scaffold = _build_dom_scaffold(
        mode="F2V",
        product_id="prod-001",
        prompt_package_snapshot_id="pkg_001",
        workspace_execution_package_id="wep_001",
        workspace_generation_package_id="wgp_001",
        final_prompt_text="Test prompt",
        prompt_blocks=[],
        generation_mode="SINGLE",
        asset_map={},
        settings={},
        semantic_resolution={},
        upload_order=["start_frame"],
        blockers=[],
        warnings=[],
        prompt_fingerprint="fp_001",
        asset_fingerprints=[],
    )
    assert scaffold["readiness"]["dom_handoff_ready"] is False


def test_dom_scaffold_manual_handoff_ready_false_when_blockers():
    scaffold = _build_dom_scaffold(
        mode="F2V",
        product_id="prod-001",
        prompt_package_snapshot_id="pkg_001",
        workspace_execution_package_id=None,
        workspace_generation_package_id="wgp_001",
        final_prompt_text="",
        prompt_blocks=[],
        generation_mode="SINGLE",
        asset_map={},
        settings={},
        semantic_resolution={},
        upload_order=[],
        blockers=["final_prompt_text is empty"],
        warnings=[],
        prompt_fingerprint="fp_001",
        asset_fingerprints=[],
    )
    assert scaffold["readiness"]["dom_handoff_ready"] is False
    assert scaffold["readiness"]["manual_handoff_ready"] is False
    assert "final_prompt_text is empty" in scaffold["readiness"]["blockers"]


def test_dom_scaffold_lineage_fields():
    scaffold = _build_dom_scaffold(
        mode="I2V",
        product_id="prod-002",
        prompt_package_snapshot_id="pkg_002",
        workspace_execution_package_id="wep_002",
        workspace_generation_package_id="wgp_002",
        final_prompt_text="I2V prompt",
        prompt_blocks=[],
        generation_mode="SINGLE",
        asset_map={},
        settings={},
        semantic_resolution={"resolved_slots": []},
        upload_order=["subject", "scene", "style"],
        blockers=[],
        warnings=[],
        prompt_fingerprint="fp_002",
        asset_fingerprints=["af_001"],
    )
    assert scaffold["lineage"]["product_id"] == "prod-002"
    assert scaffold["lineage"]["workspace_execution_package_id"] == "wep_002"
    assert scaffold["lineage"]["workspace_generation_package_id"] == "wgp_002"
    assert scaffold["manual_handoff"]["upload_order"] == ["subject", "scene", "style"]


# ─── Manual handoff ───────────────────────────────────────────

def test_manual_handoff_copy_prompt_always_available():
    mh = _build_manual_handoff(
        mode="F2V",
        final_prompt_text="Test prompt",
        image_assets={},
        upload_order=["start_frame"],
        blockers=[],
        warnings=[],
    )
    assert mh["copy_prompt_available"] is True
    assert mh["manual_fallback_ready"] is True
    assert "DOM handoff not enabled in this wave" in mh["dom_handoff_note"]


def test_manual_handoff_blocked_when_blockers():
    mh = _build_manual_handoff(
        mode="F2V",
        final_prompt_text="",
        image_assets={},
        upload_order=[],
        blockers=["final_prompt_text is empty"],
        warnings=[],
    )
    assert mh["manual_fallback_ready"] is False
    assert mh["blockers"] == ["final_prompt_text is empty"]


def test_manual_handoff_f2v_upload_order():
    image_assets = {
        "start_frame": {
            "slot_key": "start_frame", "label": "Start Frame",
            "preview_url": "/api/products/prod-001/image",
            "download_url": "/api/products/prod-001/image",
        }
    }
    mh = _build_manual_handoff(
        mode="F2V",
        final_prompt_text="Test prompt",
        image_assets=image_assets,
        upload_order=["start_frame"],
        blockers=[],
        warnings=[],
    )
    assert mh["upload_order"] == ["start_frame"]
    action_types = [a["action"] for a in mh["actions"]]
    assert "copy_prompt" in action_types
    assert "open_image" in action_types
    assert "download_image" in action_types


def test_manual_handoff_i2v_upload_order():
    image_assets = {
        "subject": {"slot_key": "subject", "label": "Subject", "preview_url": "/api/creative-assets/s/preview", "download_url": "/api/creative-assets/s/download"},
        "scene": {"slot_key": "scene", "label": "Scene", "preview_url": "/api/creative-assets/sc/preview", "download_url": "/api/creative-assets/sc/download"},
    }
    mh = _build_manual_handoff(
        mode="I2V",
        final_prompt_text="I2V prompt",
        image_assets=image_assets,
        upload_order=["subject", "scene"],
        blockers=[],
        warnings=[],
    )
    assert mh["upload_order"] == ["subject", "scene"]


# ─── F2V package creation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_f2v_package_creation_ready_manual(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return FAKE_COMPILE_RESULT
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)

    stored = {}

    async def fake_create(wgp_id, *, mode, product_id, status, final_prompt_text, **kw):
        stored["wgp_id"] = wgp_id
        stored["status"] = status
        stored["final_prompt_text"] = final_prompt_text
        row = {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "status": status, "final_prompt_text": final_prompt_text}
        return row

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    result = await create_f2v_generation_package(product_id="prod-001")
    assert stored["status"] == "READY_MANUAL"
    assert "Block 1" in stored["final_prompt_text"]
    assert result["workspace_generation_package_id"].startswith("wgp_")
    # Verify dom_handoff_ready is False in the enriched result
    dom = result.get("dom_handoff_payload_json")
    if isinstance(dom, dict):
        assert dom["readiness"]["dom_handoff_ready"] is False


@pytest.mark.asyncio
async def test_f2v_package_preserves_hybrid_source_lane(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    captured_compile = {}
    def fake_compile(**kwargs):
        captured_compile.update(kwargs)
        return FAKE_COMPILE_RESULT
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)

    async def fake_create(wgp_id, *, source_lane, dom_handoff_payload_json, **kw):
        dom = json.loads(dom_handoff_payload_json)
        assert source_lane == "HYBRID"
        assert dom["settings"]["source_mode"] == "HYBRID"
        return {
            **FAKE_WGP_ROW,
            "workspace_generation_package_id": wgp_id,
            "source_lane": source_lane,
            "dom_handoff_payload_json": dom_handoff_payload_json,
        }

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    result = await create_f2v_generation_package(product_id="prod-001", source_mode="HYBRID")
    assert captured_compile["source_mode"] == "HYBRID"
    assert result["source_lane"] == "HYBRID"


@pytest.mark.asyncio
async def test_f2v_package_blocked_when_no_prompt(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return {"final_compiled_prompt_text": "", "prompt_blocks": [], "prompt_fingerprint": "fp_empty"}
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)

    async def fake_create(wgp_id, *, status, **kw):
        row = {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "status": status}
        return row

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    result = await create_f2v_generation_package(product_id="prod-001")
    assert result["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_f2v_start_frame_auto_seeded_from_product_image(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return FAKE_COMPILE_RESULT
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)

    captured_selected_assets = {}

    async def fake_create(wgp_id, *, selected_assets_json, **kw):
        captured_selected_assets.update(json.loads(selected_assets_json))
        return {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "selected_assets_json": selected_assets_json}

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    await create_f2v_generation_package(product_id="prod-001")
    start_frame = captured_selected_assets.get("start_frame", {})
    assert start_frame["source"] == "PRODUCT_IMAGE_AUTO_SEED"
    assert "prod-001" in start_frame["preview_url"]


@pytest.mark.asyncio
async def test_f2v_operator_selected_start_frame_persists(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return FAKE_COMPILE_RESULT
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)

    captured = {}

    async def fake_create(wgp_id, *, selected_assets_json, **kw):
        captured["selected_assets_json"] = selected_assets_json
        return {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "selected_assets_json": selected_assets_json}

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    await create_f2v_generation_package(
        product_id="prod-001",
        start_frame_asset_id="custom_asset_001",
        start_frame_preview_url="/custom/preview.jpg",
        start_frame_download_url="/custom/download.jpg",
    )
    assets = json.loads(captured["selected_assets_json"])
    assert assets["start_frame"]["asset_id"] == "custom_asset_001"
    assert assets["start_frame"]["source"] == "OPERATOR_SELECTED"


# ─── I2V package creation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_i2v_package_creation_ready_manual(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return FAKE_COMPILE_RESULT
    async def fake_resolver(req): return FAKE_RESOLVER_RESULT
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.resolve_i2v_semantic_slots", fake_resolver)

    async def fake_create(wgp_id, *, status, source_lane, resolver_output_json, **kw):
        assert source_lane == "I2V"
        resolver = json.loads(resolver_output_json)
        assert "resolved_assets" in resolver  # the REAL resolver contract persists
        row = {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "status": status, "mode": "I2V", "source_lane": "I2V"}
        return row

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    result = await create_i2v_generation_package(product_id="prod-001")
    assert result["mode"] == "I2V"
    assert result["status"] == "READY_MANUAL"


@pytest.mark.asyncio
async def test_i2v_package_includes_semantic_asset_selections(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return FAKE_COMPILE_RESULT
    async def fake_resolver(req): return FAKE_RESOLVER_RESULT
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.resolve_i2v_semantic_slots", fake_resolver)

    captured = {}

    async def fake_create(wgp_id, *, selected_assets_json, image_assets_json, **kw):
        captured["selected_assets_json"] = json.loads(selected_assets_json)
        captured["image_assets_json"] = json.loads(image_assets_json)
        return {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "mode": "I2V"}

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    await create_i2v_generation_package(product_id="prod-001")
    # Should have subject from character_reference slot
    assert "subject" in captured["selected_assets_json"] or "product_reference" in captured["selected_assets_json"]


@pytest.mark.asyncio
async def test_i2v_blocked_when_resolver_has_blockers(monkeypatch):
    async def fake_approved(product_id, mode): return FAKE_APPROVED_PKG
    def fake_compile(**kwargs): return FAKE_COMPILE_RESULT
    async def fake_resolver(req): return {**FAKE_RESOLVER_RESULT, "blockers": ["required_slot_missing: character_reference"]}
    monkeypatch.setattr("agent.services.workspace_generation_package_service.get_approved_product_package", fake_approved)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.compile_ugc_video_prompt", fake_compile)
    monkeypatch.setattr("agent.services.workspace_generation_package_service.resolve_i2v_semantic_slots", fake_resolver)

    async def fake_create(wgp_id, *, status, **kw):
        return {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id, "status": status, "mode": "I2V"}

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.create_workspace_generation_package", fake_create)

    result = await create_i2v_generation_package(product_id="prod-001")
    assert result["status"] == "BLOCKED"


# ─── List / get ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_workspace_generation_packages(monkeypatch):
    async def fake_list(mode=None, status=None, product_id=None, batch_run_id=None, limit=50):
        return [FAKE_WGP_ROW]

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.list_workspace_generation_packages", fake_list)

    result = await list_workspace_generation_packages(mode="F2V", limit=10)
    assert len(result) == 1
    assert result[0]["workspace_generation_package_id"] == "wgp_abc123"


@pytest.mark.asyncio
async def test_get_workspace_generation_package_dom_ready_forced_false(monkeypatch):
    """dom_handoff_ready must always be False regardless of stored value."""
    row_with_true = dict(FAKE_WGP_ROW)
    row_with_true["dom_handoff_payload_json"] = '{"readiness": {"manual_handoff_ready": true, "dom_handoff_ready": true, "blockers": [], "warnings": []}}'

    async def fake_get(wgp_id):
        return row_with_true

    monkeypatch.setattr("agent.services.workspace_generation_package_service.crud.get_workspace_generation_package", fake_get)

    result = await get_workspace_generation_package("wgp_abc123")
    dom = result["dom_handoff_payload_json"]
    assert dom["readiness"]["dom_handoff_ready"] is False


# ─── BLOCK-SPLIT: handoff bank derives the workbook N-block plan from a total ──
# compile_ugc_video_prompt is LEFT REAL here, so the workbook authority + the
# fail-closed rule are exercised end-to-end (parity with preview + execution pkg).

def _stub_handoff_common(monkeypatch, capture: dict):
    async def fake_approved(product_id, mode):
        return FAKE_APPROVED_PKG

    async def fake_resolver(req):
        return FAKE_RESOLVER_RESULT

    async def fake_create(wgp_id, *, prompt_blocks_json, generation_mode, **kw):
        capture["blocks"] = json.loads(prompt_blocks_json)
        capture["generation_mode"] = generation_mode

        for key in ("manual_handoff_json", "dom_handoff_payload_json"):
            capture[key] = json.loads(kw[key])
        return {**FAKE_WGP_ROW, "workspace_generation_package_id": wgp_id}

    P = "agent.services.workspace_generation_package_service."
    monkeypatch.setattr(P + "get_approved_product_package", fake_approved)
    monkeypatch.setattr(P + "resolve_i2v_semantic_slots", fake_resolver)
    monkeypatch.setattr(P + "crud.create_workspace_generation_package", fake_create)


@pytest.mark.asyncio
async def test_f2v_hybrid_handoff_extend_24_resolves_three_blocks(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_f2v_generation_package(
        product_id="prod-001", source_mode="HYBRID",
        generation_mode="EXTEND", engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=24,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8, 8]
    assert cap["blocks"][0]["block_role"] == "ANCHOR"
    assert cap["blocks"][-1]["block_role"] == "FINAL"


@pytest.mark.asyncio
async def test_f2v_handoff_single_stays_one_block(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_f2v_generation_package(product_id="prod-001", generation_mode="SINGLE")
    assert len(cap["blocks"]) == 1
    assert cap["blocks"][0]["block_role"] == "ANCHOR"


@pytest.mark.asyncio
async def test_f2v_extend_handoff_persists_the_exact_storyboard_plan(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_f2v_generation_package(
        product_id="prod-001", source_mode="HYBRID",
        generation_mode="EXTEND", engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=24,
    )

    planner = cap["manual_handoff_json"]["storyboard_plan"]
    assert planner["resolved_block_plan"] == [8, 8, 8]
    assert planner["full_story_plan"]["story_beats"]
    assert planner["full_dialogue_plan"]["utterances"]
    assert len(planner["block_allocations"]) == 3
    assert cap["dom_handoff_payload_json"]["prompt"]["planner_result"] == planner
    assert all(block["allocation"] for block in cap["blocks"])


@pytest.mark.asyncio
async def test_i2v_handoff_extend_16_stores_two_blocks(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_i2v_generation_package(
        product_id="prod-001", generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=16,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8]
    assert cap["blocks"][0]["block_role"] == "ANCHOR"
    assert cap["blocks"][1]["block_role"] == "FINAL"


@pytest.mark.asyncio
async def test_i2v_handoff_extend_24_stores_three_blocks(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_i2v_generation_package(
        product_id="prod-001", generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=24,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8, 8]


@pytest.mark.asyncio
async def test_i2v_handoff_extend_15_fails_closed(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    with pytest.raises(ValueError) as exc:
        await create_i2v_generation_package(
            product_id="prod-001", generation_mode="EXTEND",
            engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=15,
        )
    assert "UNSUPPORTED_EXTEND_TOTAL_DURATION_15" in str(exc.value)


@pytest.mark.asyncio
async def test_handoff_block_plan_parity_with_direct_compiler(monkeypatch):
    """Handoff resolves the SAME plan the compiler resolves directly — i.e.
    preview, execution package, and generation package agree (32s -> [8,8,8,8])."""
    from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt

    direct = compile_ugc_video_prompt(
        product={"id": "prod-001", "name": "Bosmax Test Product", "category": ""},
        approved_package=FAKE_APPROVED_PKG,
        mode="F2V", source_mode="HYBRID",
        generation_mode="EXTEND", engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=32,
    )
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_f2v_generation_package(
        product_id="prod-001", source_mode="HYBRID",
        generation_mode="EXTEND", engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=32,
    )
    assert (
        [b["duration_seconds"] for b in cap["blocks"]]
        == [b["duration_seconds"] for b in direct["prompt_blocks"]]
        == [8, 8, 8, 8]
    )


# ─── ALL-MODES completion: T2V + standalone HYBRID + IMG classification + batch ──

from agent.services.workspace_generation_package_service import (  # noqa: E402
    _MODE_CREATORS,
    create_hybrid_generation_package,
    create_img_generation_package,
    create_t2v_generation_package,
)


@pytest.mark.asyncio
async def test_t2v_handoff_extend_16_stores_two_blocks(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_t2v_generation_package(
        product_id="prod-001", generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=16,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8]


@pytest.mark.asyncio
async def test_t2v_handoff_extend_24_stores_three_blocks(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_t2v_generation_package(
        product_id="prod-001", generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=24,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8, 8]


@pytest.mark.asyncio
async def test_t2v_handoff_extend_15_fails_closed(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    with pytest.raises(ValueError) as exc:
        await create_t2v_generation_package(
            product_id="prod-001", generation_mode="EXTEND",
            engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=15,
        )
    assert "UNSUPPORTED_EXTEND_TOTAL_DURATION_15" in str(exc.value)


@pytest.mark.asyncio
async def test_t2v_handoff_single_stays_one_block(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_t2v_generation_package(product_id="prod-001", generation_mode="SINGLE")
    assert len(cap["blocks"]) == 1


@pytest.mark.asyncio
async def test_hybrid_standalone_handoff_extend_24_stores_three_blocks(monkeypatch):
    """Standalone HYBRID creator inherits F2V authority via **kwargs passthrough."""
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await create_hybrid_generation_package(
        product_id="prod-001", generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=24,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8, 8]


@pytest.mark.asyncio
async def test_hybrid_standalone_handoff_extend_15_fails_closed(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    with pytest.raises(ValueError) as exc:
        await create_hybrid_generation_package(
            product_id="prod-001", generation_mode="EXTEND",
            engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=15,
        )
    assert "UNSUPPORTED_EXTEND_TOTAL_DURATION_15" in str(exc.value)


@pytest.mark.asyncio
async def test_img_handoff_fails_closed_on_extend_total(monkeypatch):
    """IMG is an image mode: an Extend total-duration must fail closed."""
    _stub_handoff_common(monkeypatch, {})
    with pytest.raises(ValueError) as exc:
        await create_img_generation_package(
            product_id="prod-001", generation_mode="EXTEND",
            requested_total_duration_seconds=16,
        )
    assert "IMG_MODE_NO_EXTEND_TOTAL_DURATION" in str(exc.value)


@pytest.mark.asyncio
async def test_img_handoff_without_total_still_works(monkeypatch):
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    result = await create_img_generation_package(product_id="prod-001", generation_mode="SINGLE")
    assert result["workspace_generation_package_id"]


def test_batch_mode_creators_are_total_aware():
    """Every batch dispatch target (F2V/HYBRID/I2V/T2V) accepts the workbook total;
    IMG accepts-then-guards. Prevents a batch path silently degrading to 2 blocks."""
    import inspect
    for mode in ("F2V", "HYBRID", "I2V", "T2V", "IMG"):
        sig = inspect.signature(_MODE_CREATORS[mode])
        has_var_kw = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
        assert has_var_kw or "requested_total_duration_seconds" in sig.parameters, mode


@pytest.mark.asyncio
async def test_batch_dispatch_through_mode_creators_honors_total(monkeypatch):
    """Calling THROUGH _MODE_CREATORS (as the batch loop does) honors the total."""
    cap = {}
    _stub_handoff_common(monkeypatch, cap)
    await _MODE_CREATORS["T2V"](
        product_id="prod-001", generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=32,
    )
    assert [b["duration_seconds"] for b in cap["blocks"]] == [8, 8, 8, 8]
