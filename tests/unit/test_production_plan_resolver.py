"""Production authority resolution (Mission 2 / 3 / 7).

Proves the resolver (a) preserves explicit reviewed authority, (b) reports every
missing authority field for an incomplete plan (fail-closed → 422), (c) reads the
REAL persisted execution package for model/aspect/asset/initial prompt, and (d)
maps the ONE compile door's per-block output into the exact initial + fingerprint-
bound continuation prompts (no generic fallback).
"""
import json

from agent.db import crud
from agent.services import production_plan_resolver as resolver


async def test_explicit_authority_is_complete():
    intent = {
        "product_id": "p1", "execution_package_id": "wep1",
        "approved_asset_id": "product-image:p1:subject", "approved_asset_sha256": "sha1",
        "initial_asset_media_id": "m1", "initial_mode": "I2V",
        "engine": "GOOGLE_FLOW", "model": "veo", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "requested_duration_seconds": 16,
        "initial_prompt_text": "the reviewed block-1 prompt",
        "continuation_prompts": [{"position": 1, "block_index": 2,
                                  "prompt": "the reviewed continuation", "is_final": True}],
    }
    out = await resolver.resolve_production_authority(intent, trust_client_authority=True)
    assert out["missing"] == []
    assert out["initial_prompt_fingerprint"] == resolver._fp("the reviewed block-1 prompt")
    assert out["continuation_prompt_fingerprints"] == [
        resolver._fp("the reviewed continuation")]
    assert out["operation_counts"]["total"] == 3


async def test_incomplete_reports_every_missing_field():
    out = await resolver.resolve_production_authority(
        {"product_id": "ponly", "requested_duration_seconds": 16})
    missing = set(out["missing"])
    assert {"execution_package_id", "approved_asset_id", "approved_asset_sha256",
            "initial_asset_media_id", "initial_prompt_text",
            "initial_prompt_fingerprint", "continuation_prompts"} <= missing


async def test_production_strips_client_authority_override():
    # trust=False (production): the client CANNOT inject prompt/asset — they are
    # dropped, so a would-be override never reaches the plan.
    intent = {
        "product_id": "p1", "execution_package_id": "",  # no package to resolve from
        "requested_duration_seconds": 16,
        "initial_prompt_text": "INJECTED prompt", "approved_asset_id": "INJECTED",
        "approved_asset_sha256": "INJECTED", "initial_asset_media_id": "INJECTED",
        "continuation_prompts": [{"position": 1, "prompt": "INJECTED cont"}],
    }
    out = await resolver.resolve_production_authority(intent, trust_client_authority=False)
    # nothing was honored from the client; the plan is incomplete (fail-closed)
    assert out.get("initial_prompt_text") in (None, "")
    assert "approved_asset_id" in out["missing"]
    assert "continuation_prompts" in out["missing"]


async def test_supplied_fingerprint_mismatch_is_rejected():
    import pytest
    intent = {
        "product_id": "p1", "execution_package_id": "wep1",
        "approved_asset_id": "product-image:p1:subject", "approved_asset_sha256": "sha1",
        "initial_asset_media_id": "m1", "initial_mode": "I2V", "engine": "GOOGLE_FLOW",
        "model": "veo", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "requested_duration_seconds": 16,
        "initial_prompt_text": "the real prompt B",
        "initial_prompt_fingerprint": resolver._fp("a DIFFERENT prompt A"),  # lie
        "continuation_prompts": [{"position": 1, "prompt": "cont", "is_final": True}],
    }
    with pytest.raises(resolver.AuthorityMismatchError):
        await resolver.resolve_production_authority(intent, trust_client_authority=True)


async def test_invalid_duration_flagged_missing():
    out = await resolver.resolve_production_authority(
        {"product_id": "p1", "requested_duration_seconds": 20}, trust_client_authority=True)
    assert out["duration_valid"] is False
    assert "valid_duration_plan" in out["missing"]


async def test_reads_real_execution_package(monkeypatch):
    # a REAL product + persisted execution package: authority for model/aspect/asset/prompt
    product = await crud.create_product("Minyak Warisan Tok Cap Burung 25ml")
    pid = product["id"]
    await crud.create_or_replace_workspace_execution_package(
        "wep_real", product_id=pid, mode="I2V", duration_seconds=16,
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT", model="veo_3_1_extension_lite",
        manual_override=False, prompt_text="PERSISTED block-1 product-truth prompt",
        prompt_fingerprint="pf", prompt_package_snapshot_id="snap",
        asset_slots=json.dumps(["subject", "scene"]),
        resolved_assets=json.dumps([
            {"asset_id": f"product-image:{pid}:subject",
             "asset_fingerprint": "sha-persisted", "slot_key": "subject",
             "media_id": "media-persisted"},
            {"asset_id": f"scene-context:{pid}:scene",
             "asset_fingerprint": "sha-scene", "slot_key": "scene",
             "media_id": "media-scene"},
        ]),
        readiness="READY", execution_allowed=True, production_generation_allowed=True,
        manual_fallback="{}", blockers="[]",
        request_lineage_payload=json.dumps(
            {"compiler": {"source_mode": "INGREDIENTS"}}),
        source_of_truth_notes="[]")
    # continuation prompts supplied explicitly so we isolate the package→authority map
    out = await resolver.resolve_production_authority({
        "product_id": pid, "execution_package_id": "wep_real",
        "requested_duration_seconds": 16,
        "continuation_prompts": [{"position": 1, "prompt": "cont A", "is_final": True}],
    }, trust_client_authority=True)
    assert out["missing"] == []
    assert out["model"] == "veo_3_1_extension_lite"
    assert out["aspect_ratio"] == "VIDEO_ASPECT_RATIO_PORTRAIT"
    assert out["approved_asset_id"] == f"product-image:{pid}:subject"
    assert out["approved_asset_sha256"] == "sha-persisted"
    assert out["initial_asset_media_id"] == "media-persisted"
    assert out["initial_prompt_text"] == "PERSISTED block-1 product-truth prompt"
    assert out["initial_mode"] == "I2V"
    # PR321 closure: the canonical source mode is SERVER-derived from the
    # package's persisted compiler lineage, and the ordered reference list is
    # the package's own asset selection (INGREDIENTS contract 2-3 — met).
    assert out["initial_source_mode"] == "INGREDIENTS"
    assert out["initial_reference_media_ids"] == ["media-persisted", "media-scene"]


async def test_maps_compile_door_block_prompts(monkeypatch):
    # stub ONLY the one compile door; the resolver's mapping logic runs for real
    async def fake_compile(**kwargs):
        assert kwargs["generation_mode"] == "EXTEND"
        assert kwargs["requested_total_duration_seconds"] == 24
        return {"prompt_blocks": [
            {"block_index": 1, "initial_generation_prompt_text": "INIT block prompt",
             "engine_prompt_text": "indep"},
            {"block_index": 2, "flow_extend_prompt_text": "EXTEND to block 2",
             "is_final": False},
            {"block_index": 3, "flow_extend_prompt_text": "EXTEND to block 3, final",
             "is_final": True},
        ]}
    import agent.services.workspace_execution_package_service as weps
    monkeypatch.setattr(weps, "compile_workspace_prompt_preview", fake_compile)

    out = await resolver.resolve_production_authority({
        "product_id": "6483d624", "execution_package_id": "wep_stub",
        "approved_asset_id": "product-image:6483d624:subject",
        "approved_asset_sha256": "sha", "initial_asset_media_id": "m", "initial_mode": "I2V",
        "engine": "GOOGLE_FLOW", "model": "veo", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "requested_duration_seconds": 24,
    }, trust_client_authority=True)
    assert out["initial_prompt_text"] == "INIT block prompt"
    conts = out["continuation_prompts"]
    assert [c["prompt"] for c in conts] == ["EXTEND to block 2", "EXTEND to block 3, final"]
    assert [c["position"] for c in conts] == [1, 2]
    assert conts[-1]["is_final"] is True
    assert out["continuation_prompt_fingerprints"] == [
        resolver._fp("EXTEND to block 2"), resolver._fp("EXTEND to block 3, final")]
    assert out["missing"] == []  # 24s → 2 extends, both resolved
