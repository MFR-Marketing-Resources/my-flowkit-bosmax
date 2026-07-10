"""SQLite CRUD persistence for extension-native prompt representation fields."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from agent.db import crud
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
from agent.services.workspace_generation_package_service import (
    create_f2v_generation_package,
    get_workspace_generation_package,
)
from tests.conftest import seed_product_ready

PRODUCT_ID = "prod-sqlite-extend-298"

COPY = {
    "copy_source": "selected_copy_set",
    "formula_family": "PAS",
    "angle": "Rutin malam",
    "hook": "Anak susah tidur?",
    "subhook": "Hati ibu terganggu.",
    "usps": ["Formula tradisional."],
    "cta": "Cuba malam ini.",
}

APPROVED = {
    "prompt_package_snapshot_id": "pkg_sqlite_298",
    "product_id": PRODUCT_ID,
    "product_name": "Minyak Warisan Tok Cap Burung 25ml",
    "mode": "F2V",
    "scene_context": "bedroom",
    "production_generation_allowed": False,
    "prompt_text": "stub",
    "prompt_fingerprint": "fp_stub",
    "asset_slots": [],
    "manual_fallback": {"copy_prompt_available": True},
    "blockers": [],
    "source_of_truth_notes": [],
}


@pytest.mark.asyncio
async def test_sqlite_roundtrip_preserves_extend_representations(monkeypatch):
    db = await crud.get_db()
    await seed_product_ready(db, PRODUCT_ID)

    async def fake_approved(product_id, mode):
        assert product_id == PRODUCT_ID
        return deepcopy(APPROVED)

    monkeypatch.setattr(
        "agent.services.workspace_generation_package_service.get_approved_product_package",
        fake_approved,
    )

    created = await create_f2v_generation_package(
        product_id=PRODUCT_ID,
        generation_mode="EXTEND",
        source_mode="HYBRID",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
        copy_intelligence=deepcopy(COPY),
    )
    wgp_id = created["workspace_generation_package_id"]
    assert created["status"] in {"READY_MANUAL", "BLOCKED"}

    reloaded = await get_workspace_generation_package(wgp_id)
    assert reloaded is not None
    blocks = reloaded.get("prompt_blocks_json") or []
    assert len(blocks) >= 2
    b2 = blocks[1]
    assert (b2.get("flow_extend_prompt_text") or "").startswith("Extend this video")
    assert b2.get("prompt_representation") == "GOOGLE_FLOW_EXTEND"
    assert b2.get("flow_extend_prompt_validation", {}).get("valid") is True
    assert b2.get("independent_block_prompt_text")
    assert b2.get("engine_prompt_text") == b2.get("independent_block_prompt_text")
    reps = b2.get("prompt_representations") or {}
    extend_rep = reps.get("GOOGLE_FLOW_EXTEND") or {}
    assert extend_rep.get("text", "").startswith("Extend this video")
    assert extend_rep.get("audio_seam_contract", {}).get("representation") == "GOOGLE_FLOW_EXTEND"
    assert extend_rep.get("audio_seam_contract", {}).get("contract_purpose") == "CONTINUATION_FROM_PRIOR_VIDEO"

    row = await crud.get_workspace_generation_package(wgp_id)
    assert row is not None
    raw = json.loads(row.get("prompt_blocks_json") or "[]")
    assert raw[1]["flow_extend_prompt_text"] == b2["flow_extend_prompt_text"]
    assert created.get("final_prompt_text")
    assert reloaded.get("final_prompt_text") == created.get("final_prompt_text")