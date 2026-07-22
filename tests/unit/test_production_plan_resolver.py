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


async def test_blocked_execution_package_never_mints_a_production_plan():
    # Fail-closed package gate: a BLOCKED package (readiness blockers, e.g. a
    # missing required I2V recipe role) must be rejected at plan time even when
    # its media-ref count still lands inside the transport contract.
    product = await crud.create_product("Blocked Package Product")
    pid = product["id"]
    await crud.create_or_replace_workspace_execution_package(
        "wep_blocked", product_id=pid, mode="I2V", duration_seconds=16,
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT", model="veo_3_1_extension_lite",
        manual_override=False, prompt_text="single-block prompt",
        prompt_fingerprint="pf", prompt_package_snapshot_id="snap",
        asset_slots=json.dumps([]),
        resolved_assets=json.dumps([
            {"asset_id": f"product-image:{pid}:subject",
             "asset_fingerprint": "sha-a", "slot_key": "subject",
             "media_id": "media-a"},
            {"asset_id": "ca_character", "asset_fingerprint": "sha-b",
             "slot_key": "scene", "media_id": "media-b"},
        ]),
        readiness="BLOCKED", execution_allowed=False,
        production_generation_allowed=False,
        manual_fallback="{}",
        blockers=json.dumps(["MISSING_SCENE_CONTEXT_REFERENCE"]),
        request_lineage_payload=json.dumps(
            {"compiler": {"source_mode": "INGREDIENTS"}}),
        source_of_truth_notes="[]")
    out = await resolver.resolve_production_authority({
        "product_id": pid, "execution_package_id": "wep_blocked",
        "requested_duration_seconds": 16,
    }, trust_client_authority=False)
    assert "execution_package_execution_allowed" in out["missing"]


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


async def test_dispatch_never_ships_a_multi_block_document_as_the_initial(monkeypatch):
    """Dispatch invariant protected by the audio-seam repair: Block 1 resolves to the
    reviewed `initial_generation_prompt_text` and Block 2+ to the reviewed
    `flow_extend_prompt_text` — the whole multi-block document is NEVER the initial
    generation prompt (which would collapse both seams into one clip)."""
    _HDR = "SECTION 1 - ROLE & OBJECTIVE"
    b1 = f"{_HDR}\nYou are generating an 8-second block (opening block 1 of 2)."
    b2 = "Extend this video from the exact ending of Video 1. ...continuation..."
    whole_document = b1 + "\n\n" + f"{_HDR}\nYou are generating an 8-second block (final block 2 of 2)."

    async def fake_compile(**kwargs):
        return {"prompt_blocks": [
            {"block_index": 1, "initial_generation_prompt_text": b1,
             "flow_extend_prompt_text": None, "engine_prompt_text": whole_document},
            {"block_index": 2, "flow_extend_prompt_text": b2, "is_final": True},
        ]}
    import agent.services.workspace_execution_package_service as weps
    monkeypatch.setattr(weps, "compile_workspace_prompt_preview", fake_compile)

    out = await resolver.resolve_production_authority({
        "product_id": "6483d624", "execution_package_id": "wep_stub",
        "approved_asset_id": "product-image:6483d624:subject",
        "approved_asset_sha256": "sha", "initial_asset_media_id": "m", "initial_mode": "I2V",
        "engine": "GOOGLE_FLOW", "model": "veo", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "requested_duration_seconds": 16,
    }, trust_client_authority=True)
    assert out["initial_prompt_text"] == b1                       # reviewed block-1 initial
    assert out["initial_prompt_text"] != whole_document          # never the whole document
    assert [c["prompt"] for c in out["continuation_prompts"]] == [b2]  # reviewed extend
    assert out["missing"] == []


# ── copy-binding fix: production reuses the WEP's persisted per-block prompts ──
# The bug: in production (trust=False) the resolver ALWAYS recompiled the block
# prompts via compile_workspace_prompt_preview with NO copy_set_id, so every
# durable EXTEND job rendered LANDBANK fallback dialogue instead of the copy that
# was bound to its execution package. The fix reuses the package's already-
# compiled, copy-bound blocks verbatim and NEVER recompiles copy-blind.

async def _seed_extend_wep(pid: str, wep_id: str, *, prompt_blocks, blockers="[]",
                           readiness="READY", execution_allowed=True):
    """A real EXTEND execution package with (optionally) persisted per-block prompts
    carrying the operator's BOUND copy — exactly the shape create_workspace_execution
    _package writes (request_lineage_payload.compiler.prompt_blocks)."""
    compiler = {"source_mode": "INGREDIENTS"}
    if prompt_blocks is not None:
        compiler["prompt_blocks"] = prompt_blocks
    await crud.create_or_replace_workspace_execution_package(
        wep_id, product_id=pid, mode="I2V", duration_seconds=16,
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT", model="veo_3_1_extension_lite",
        manual_override=False,
        # multi-block joined document → the single-block guard leaves the initial
        # empty, so the resolver must source it from the persisted blocks.
        prompt_text="SECTION 1 - ROLE & OBJECTIVE\nblock1\n\nSECTION 1 - ROLE & OBJECTIVE\nblock2",
        prompt_fingerprint="pf", prompt_package_snapshot_id="snap",
        asset_slots=json.dumps(["subject", "scene"]),
        resolved_assets=json.dumps([
            {"asset_id": f"product-image:{pid}:subject",
             "asset_fingerprint": "sha-a", "slot_key": "subject", "media_id": "media-a"},
            {"asset_id": f"scene-context:{pid}:scene",
             "asset_fingerprint": "sha-b", "slot_key": "scene", "media_id": "media-b"},
        ]),
        readiness=readiness, execution_allowed=execution_allowed,
        production_generation_allowed=True, manual_fallback="{}", blockers=blockers,
        request_lineage_payload=json.dumps({"compiler": compiler}),
        source_of_truth_notes="[]")


def _forbid_recompile(monkeypatch):
    """Install a compile door that records every call and returns LANDBANK junk.
    Any call means the resolver recompiled copy-blind — the exact bug."""
    import agent.services.workspace_execution_package_service as weps
    calls: list = []

    async def fake_compile(**kwargs):
        calls.append(kwargs)
        return {"prompt_blocks": [
            {"block_index": 1, "initial_generation_prompt_text": "LANDBANK FALLBACK initial"},
            {"block_index": 2, "flow_extend_prompt_text": "LANDBANK FALLBACK extend",
             "is_final": True},
        ]}
    monkeypatch.setattr(weps, "compile_workspace_prompt_preview", fake_compile)
    return calls


async def test_production_extend_renders_the_packages_bound_copy_not_fallback(monkeypatch):
    """A durable EXTEND plan resolved from a WEP bound to copy X contains X's
    dialogue in its block prompts — reused verbatim, with ZERO recompile."""
    product = await crud.create_product("Bound Copy Extend Product")
    pid = product["id"]
    await _seed_extend_wep(pid, "wep_bound_copy", prompt_blocks=[
        {"block_index": 1,
         "initial_generation_prompt_text": "INITIAL: BOUND-COPY-X hook and product truth",
         "engine_prompt_text": "indep"},
        {"block_index": 2,
         "flow_extend_prompt_text": "EXTEND: BOUND-COPY-X continuation and CTA",
         "is_final": True},
    ])
    calls = _forbid_recompile(monkeypatch)

    out = await resolver.resolve_production_authority({
        "product_id": pid, "execution_package_id": "wep_bound_copy",
        "requested_duration_seconds": 16,
    }, trust_client_authority=False)

    # the exact reviewed, copy-bound text — never the landbank fallback
    assert out["initial_prompt_text"] == "INITIAL: BOUND-COPY-X hook and product truth"
    assert [c["prompt"] for c in out["continuation_prompts"]] == [
        "EXTEND: BOUND-COPY-X continuation and CTA"]
    assert "BOUND-COPY-X" in out["initial_prompt_text"]
    assert "LANDBANK" not in out["initial_prompt_text"]
    # fingerprints still recomputed server-side from the canonical text
    assert out["initial_prompt_fingerprint"] == resolver._fp(
        "INITIAL: BOUND-COPY-X hook and product truth")
    assert out["continuation_prompt_fingerprints"] == [
        resolver._fp("EXTEND: BOUND-COPY-X continuation and CTA")]
    assert calls == []              # the copy-blind recompile door was NEVER opened
    assert out["missing"] == []     # a complete, copy-bound production plan


async def test_production_extend_without_bound_block_authority_fails_closed(monkeypatch):
    """A WEP with no reusable per-block authority is REFUSED (missing → 422),
    never silently backfilled with landbank fallback copy."""
    product = await crud.create_product("No Bound Blocks Extend Product")
    pid = product["id"]
    # READY + execution_allowed, valid assets — but NO compiler.prompt_blocks.
    await _seed_extend_wep(pid, "wep_no_blocks", prompt_blocks=None)
    calls = _forbid_recompile(monkeypatch)

    out = await resolver.resolve_production_authority({
        "product_id": pid, "execution_package_id": "wep_no_blocks",
        "requested_duration_seconds": 16,
    }, trust_client_authority=False)

    assert calls == []                                   # never recompiled copy-blind
    assert not resolver._clean(out.get("initial_prompt_text"))
    assert out.get("continuation_prompts") in (None, [])
    missing = set(out["missing"])
    assert "initial_prompt_text" in missing
    assert "continuation_prompts" in missing             # INCOMPLETE_PRODUCTION_PLAN


async def test_recovery_path_still_recompiles_when_it_has_no_execution_package(monkeypatch):
    """Guard the untouched lane: with NO execution package the recompile door is
    still the per-block authority source (recovery / legacy intents)."""
    calls = _forbid_recompile(monkeypatch)

    out = await resolver.resolve_production_authority({
        "product_id": "6483d624", "execution_package_id": "",
        "approved_asset_id": "product-image:6483d624:subject",
        "approved_asset_sha256": "sha", "initial_asset_media_id": "m", "initial_mode": "I2V",
        "engine": "GOOGLE_FLOW", "model": "veo",
        "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "requested_duration_seconds": 16,
    }, trust_client_authority=True)

    assert len(calls) == 1  # no package → the one compile door is the authority
    assert out["initial_prompt_text"] == "LANDBANK FALLBACK initial"
