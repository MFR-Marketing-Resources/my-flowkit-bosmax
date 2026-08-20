"""Final Prompt Approval Gate — provider-free proof of the WYSIWYG invariant.

Proves, without any provider call or credit spend, that:

    approved_execution_envelope_sha256 == dispatched_execution_envelope_sha256

is the ONLY thing that authorises a dispatch, and that every provider-affecting
change after approval (prompt / model / aspect / duration / count / asset) fails
closed. These are the service-level backend bypass-matrix guarantees; the choke
wiring tests assert the same at the dispatch boundary.

Each DB-backed test uses a UNIQUE prompt (hence a unique execution envelope) so
the suite is robust to imperfect per-test DB reset on Windows (see
conftest._unlink_db_safe, which tolerates WinError 32) — a lingering approval
from one test can never satisfy another test's envelope check.
"""

from __future__ import annotations

import pytest

from agent.services import execution_approval_service as eas


@pytest.fixture(autouse=True)
def _mock_canonical_pv(monkeypatch):
    async def _mock_fp(product_id: str, slot_key: str = "start_frame"):
        return f"PRODUCT_VISUAL|{product_id}|{slot_key}|fake_canonical_sha256"

    monkeypatch.setattr(
        "agent.services.product_visual_grounding_resolver.get_canonical_product_visual_fingerprint",
        _mock_fp,
    )


_ASSET = "550e8400-e29b-41d4-a716-446655440000"


def _spec(prompt: str, **ov):
    d = dict(
        surface="hybrid",
        logical_mode="F2V",
        final_prompt_text=prompt,
        product_id="prod_test_1",
        source_mode="HYBRID",
        model="Veo 3.1 Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[_ASSET],
    )
    d.update(ov)
    return d


def _dispatch(prompt: str, **ov):
    """Dispatch-boundary arg names for the same envelope produced by ``_spec``."""
    d = dict(
        mode="F2V",
        final_prompt_text=prompt,
        product_id="prod_test_1",
        source_mode="HYBRID",
        model="Veo 3.1 Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[_ASSET],
    )
    d.update(ov)
    return d


# --------------------------------------------------------------------------- #
# Deterministic envelope + hashing (pure — no DB)
# --------------------------------------------------------------------------- #

def test_identity_is_deterministic_for_equal_inputs():
    a = eas.compute_dispatch_identity(**_dispatch("same prompt"))
    b = eas.compute_dispatch_identity(**_dispatch("same prompt"))
    assert a["execution_envelope_sha256"] == b["execution_envelope_sha256"]
    assert a["prompt_sha256"] == b["prompt_sha256"]


def test_asset_order_does_not_change_hash():
    a = eas.compute_dispatch_identity(**_dispatch("p", asset_media_ids=["a", "b", "c"]))
    b = eas.compute_dispatch_identity(**_dispatch("p", asset_media_ids=["c", "a", "b"]))
    assert a["execution_envelope_sha256"] == b["execution_envelope_sha256"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("final_prompt_text", "a DIFFERENT prompt"),
        ("model", "Veo 3.1 Fast"),
        ("aspect", "16:9"),
        ("duration_s", 16),
        ("count", 2),
        ("source_mode", "FRAMES"),
        ("asset_media_ids", ["different-asset"]),
        ("product_id", "prod_test_2"),
    ],
)
def test_any_provider_affecting_change_changes_the_hash(field, value):
    base = eas.compute_dispatch_identity(**_dispatch("baseline prompt"))
    changed = eas.compute_dispatch_identity(**_dispatch("baseline prompt", **{field: value}))
    assert base["execution_envelope_sha256"] != changed["execution_envelope_sha256"]


def test_faceless_execution_identity_is_provider_affecting():
    identity = {
        "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
        "lane": "FACELESS",
        "transport_mode": "F2V",
        "product_id": "prod_test_1",
        "actor_profile_resolved": "FEMALE",
        "opening_strategy_resolved": "GENERAL_USP_PRODUCT",
    }
    changed = {**identity, "actor_profile_resolved": "MALE"}
    first = eas.compute_dispatch_identity(
        **_dispatch("faceless identity baseline", execution_identity=identity)
    )
    second = eas.compute_dispatch_identity(
        **_dispatch("faceless identity baseline", execution_identity=changed)
    )
    assert first["execution_envelope"]["execution_identity"] == identity
    assert first["execution_envelope_sha256"] != second["execution_envelope_sha256"]


def test_seed_is_not_part_of_the_envelope():
    ident = eas.compute_dispatch_identity(**_dispatch("p"))
    assert "seed" not in ident["execution_envelope"]


# --------------------------------------------------------------------------- #
# Lifecycle + the dispatch gate (the bypass matrix)
# --------------------------------------------------------------------------- #

async def test_create_then_approve_then_dispatch_pass():
    prompt = "P_create_pass — a clean provider-ready prompt"
    snap = await eas.create_review_snapshot(**_spec(prompt))
    assert snap["approval_state"] == eas.ApprovalState.REVIEW_REQUIRED
    assert snap["scan_clean"] == 1

    approved = await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    assert approved["approval_state"] == eas.ApprovalState.APPROVED
    assert approved["approved_execution_envelope_sha256"] == snap["execution_envelope_sha256"]

    verdict = await eas.verify_and_bind_dispatch(**_dispatch(prompt))
    assert verdict["pass"] is True
    assert verdict["reason"] == "APPROVED_ENVELOPE_MATCH"
    assert (
        verdict["dispatched_execution_envelope_sha256"]
        == approved["approved_execution_envelope_sha256"]
    )
    bound = await eas.get_snapshot(snap["snapshot_id"])
    assert bound["approval_state"] == eas.ApprovalState.DISPATCHED


async def test_no_approval_blocks_when_enforced(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(**_dispatch("P_noapproval_enforced"))
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


async def test_no_approval_is_observe_only_when_not_enforced(monkeypatch):
    monkeypatch.delenv("EXECUTION_APPROVAL_GATE_ENFORCED", raising=False)
    verdict = await eas.verify_and_bind_dispatch(**_dispatch("P_noapproval_observe"))
    assert verdict["pass"] is False
    assert verdict["enforced"] is False
    assert verdict["reason"] == "NO_APPROVED_SNAPSHOT_FOR_ENVELOPE"


async def test_img_is_enforced_and_blocks_without_approval(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    # Corrective GAP 3: credit-FREE (owner law, no COST gate) does NOT mean
    # approval-optional. IMG must ENFORCE approval — an unapproved IMG dispatch
    # hard-blocks exactly like video (the free/paid axis governs cost warnings,
    # not the WYSIWYG approval requirement).
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(**_dispatch("P_img_enforced", mode="IMG"))
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("final_prompt_text", "an edited-after prompt the user never approved"),
        ("model", "Veo 3.1 Fast"),
        ("aspect", "16:9"),
        ("duration_s", 16),
        ("count", 2),
        # NOTE: asset_media_ids is intentionally NOT here — for product-backed
        # HYBRID/F2V the canonical resolver binds the product-visual SHA and ignores
        # caller media ids, so a media-id swap does not change the hash. Explicit
        # asset-change blocking is covered by test_changed_frame_asset_* (FRAMES).
        ("product_id", "prod_test_2"),
    ],
)
async def test_changed_field_after_approval_blocks(monkeypatch, field, value):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "P_changed — approved baseline"
    snap = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(**_dispatch(prompt, **{field: value}))
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


async def test_changed_faceless_execution_identity_after_approval_blocks(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    identity = {
        "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
        "lane": "FACELESS",
        "transport_mode": "F2V",
        "product_id": "prod_test_1",
        "actor_profile_resolved": "FEMALE",
        "opening_strategy_resolved": "GENERAL_USP_PRODUCT",
    }
    prompt = "P_faceless_identity — approved baseline"
    snap = await eas.create_review_snapshot(
        **_spec(prompt, execution_identity=identity)
    )
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(
            **_dispatch(
                prompt,
                execution_identity={**identity, "actor_profile_resolved": "MALE"},
            )
        )
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


async def test_changed_frame_asset_after_approval_blocks(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "P_changed_frame — approved baseline"
    snap = await eas.create_review_snapshot(**_spec(prompt, source_mode="FRAMES", product_id=None))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(
            **_dispatch(prompt, source_mode="FRAMES", product_id=None, asset_media_ids=["swapped-frame"])
        )
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


async def test_edit_after_approval_requires_reapproval(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    orig = "P_edit_orig — approved original"
    new = "P_edit_new — freshly edited provider-ready prompt"
    snap = await eas.create_review_snapshot(**_spec(orig))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")

    edited = await eas.apply_edit(
        snap["snapshot_id"], edited_prompt_text=new, editor_id="faris",
    )
    assert edited["approval_state"] == eas.ApprovalState.EDITED
    assert edited["approved_execution_envelope_sha256"] is None

    with pytest.raises(eas.ExecutionApprovalError):
        await eas.verify_and_bind_dispatch(**_dispatch(new))

    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    verdict = await eas.verify_and_bind_dispatch(**_dispatch(new))
    assert verdict["pass"] is True


async def test_invalidated_approval_blocks(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "P_invalidated — approved then invalidated"
    snap = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    await eas.invalidate_snapshot(snap["snapshot_id"], reason="asset changed upstream")
    with pytest.raises(eas.ExecutionApprovalError):
        await eas.verify_and_bind_dispatch(**_dispatch(prompt))


async def test_dispatched_snapshot_is_single_use(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "P_singleuse — approved once"
    snap = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    first = await eas.verify_and_bind_dispatch(**_dispatch(prompt))
    assert first["pass"] is True
    with pytest.raises(eas.ExecutionApprovalError):
        await eas.verify_and_bind_dispatch(**_dispatch(prompt))


async def test_scan_not_clean_refuses_approval():
    # scan_prompt_text flags product_id leakage; a prompt echoing the product_id
    # is not clean, so approval must be refused (no bypass via a dirty prompt).
    snap = await eas.create_review_snapshot(
        **_spec("P_scan — a prompt that leaks prod_test_1 into the text")
    )
    assert snap["scan_clean"] == 0
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    assert exc.value.code == "SNAPSHOT_SCAN_NOT_CLEAN"


async def test_snapshot_id_pin_prevents_foreign_approval_match(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "P_pin — same envelope approved twice"
    snap_a = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap_a["snapshot_id"], approved_by="faris")
    snap_b = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap_b["snapshot_id"], approved_by="faris")

    verdict = await eas.verify_and_bind_dispatch(
        **_dispatch(prompt), snapshot_id=snap_b["snapshot_id"]
    )
    assert verdict["pass"] is True
    assert verdict["snapshot_id"] == snap_b["snapshot_id"]
    assert (await eas.get_snapshot(snap_b["snapshot_id"]))["approval_state"] == "DISPATCHED"
    assert (await eas.get_snapshot(snap_a["snapshot_id"]))["approval_state"] == "APPROVED"


# --------------------------------------------------------------------------- #
# Dispatch-boundary wiring: start_generate is gated (provider-free).
# IMG mode is single-flight-exempt and never touches the video lane globals.
# --------------------------------------------------------------------------- #

async def test_start_generate_blocks_unapproved_video_when_enforced(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    from agent.services import make_video

    monkeypatch.setattr(make_video, "_VIDEO_LANE_JOB", None)
    # A credit-bearing VIDEO dispatch with no approval is rejected BEFORE any
    # job/lane/provider work (the gate runs before the lane claim).
    result = await make_video.start_generate(
        mode="F2V", prompt="P_wire_block — an unapproved video prompt",
        image_media_ids=["550e8400-e29b-41d4-a716-446655440000"],
        aspect="9:16", num_videos=1, model="Veo 3.1 Lite", duration_s=8,
    )
    assert result["status"] == "REJECTED"
    assert result["error"] == make_video.ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL
    assert result["routing_receipt"]["TEXT_ONLY_TOOL_ALLOWED"] is False


async def test_start_generate_img_blocks_unapproved_when_enforced(monkeypatch):
    import asyncio

    eas._DISPATCH_AUTH.set(None)
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    from agent.services import make_video

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(make_video, "_run_generate", _noop)
    # Corrective GAP 3: IMG enforces approval. An unapproved IMG dispatch is
    # rejected at the gate BEFORE any lane/provider work — credit-free never means
    # approval-optional.
    result = await make_video.start_generate(
        mode="IMG", prompt="P_img_block unapproved image prompt",
        aspect="1:1", num_videos=1, image_model="GEM_PIX_2",
    )
    await asyncio.sleep(0)
    assert result["status"] == "REJECTED"
    assert result["error"] == "DISPATCH_NOT_APPROVED"


async def test_start_generate_passes_matching_approval_when_enforced(monkeypatch):
    import asyncio

    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    from agent.services import make_video

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(make_video, "_run_generate", _noop)

    prompt = "P_wire_pass — an approved, clean image prompt"
    snap = await eas.create_review_snapshot(
        surface="poster_builder", logical_mode="IMG", final_prompt_text=prompt,
        aspect="1:1", count=1, image_model="GEM_PIX_2",
    )
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")

    result = await make_video.start_generate(
        mode="IMG", prompt=prompt, aspect="1:1", num_videos=1,
        image_model="GEM_PIX_2",
    )
    await asyncio.sleep(0)
    assert result["status"] == "SUBMITTED"
    assert (await eas.get_snapshot(snap["snapshot_id"]))["approval_state"] == "DISPATCHED"


# --------------------------------------------------------------------------- #
# Non-UI enablement: Approved Generation Manifest (queue / bulk / scheduler /
# Montage / Extend). Corrective GAP 1/2: a non-UI dispatch inherits approval ONLY
# by RESOLVING an already human-approved manifest item whose envelope hash
# matches. No provenance string manufactures approval.
# --------------------------------------------------------------------------- #

async def test_resolve_requires_an_approved_manifest_never_manufactures():
    # A manifest that is only REVIEW_REQUIRED (created, not yet approved) does NOT
    # authorise a dispatch — resolve returns None (never fabricates APPROVED).
    prompt = "P_manifest_unapproved clean prompt"
    manifest = await eas.create_manifest(
        surface="production_queue", run_ref="run_unapproved_1",
        items=[dict(item_key="op1", mode="IMG", final_prompt_text=prompt,
                    image_model="GEM_PIX_2", aspect="1:1", count=1)],
    )
    assert manifest["state"] == "REVIEW_REQUIRED"
    resolved = await eas.resolve_manifest_approved_snapshot(
        manifest_id=manifest["manifest_id"], mode="IMG", final_prompt_text=prompt,
        image_model="GEM_PIX_2", aspect="1:1", count=1,
    )
    assert resolved is None  # fail-closed: no approval was manufactured


async def test_resolve_matches_only_after_manifest_approval():
    prompt = "P_manifest_approved clean prompt"
    manifest = await eas.create_manifest(
        surface="bulk", run_ref="run_approved_1",
        items=[dict(item_key="op1", mode="IMG", final_prompt_text=prompt,
                    image_model="GEM_PIX_2", aspect="1:1", count=1)],
    )
    await eas.approve_manifest(manifest["manifest_id"], approved_by="faris")
    resolved = await eas.resolve_manifest_approved_snapshot(
        manifest_id=manifest["manifest_id"], mode="IMG", final_prompt_text=prompt,
        image_model="GEM_PIX_2", aspect="1:1", count=1,
    )
    assert resolved is not None
    assert resolved["approval_state"] == eas.ApprovalState.APPROVED
    # A changed prompt (never approved) does NOT resolve — hash equality is the law.
    assert await eas.resolve_manifest_approved_snapshot(
        manifest_id=manifest["manifest_id"], mode="IMG",
        final_prompt_text=prompt + " TAMPERED", image_model="GEM_PIX_2",
        aspect="1:1", count=1,
    ) is None


async def test_approve_manifest_refuses_when_any_item_dirty():
    manifest = await eas.create_manifest(
        surface="montage", run_ref="run_dirty_1", product_id="prod_dirty_1",
        items=[
            dict(item_key="clean", mode="F2V", final_prompt_text="a clean scene prompt",
                 model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1),
            dict(item_key="dirty", mode="F2V",
                 final_prompt_text="scene leaking prod_dirty_1 into the text",
                 product_id="prod_dirty_1", model="Veo 3.1 Lite", aspect="9:16",
                 duration_s=8, count=1),
        ],
    )
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.approve_manifest(manifest["manifest_id"], approved_by="faris")
    assert exc.value.code == "MANIFEST_SCAN_NOT_CLEAN"


async def test_start_generate_manifest_resolves_approved_run(monkeypatch):
    import asyncio

    eas._DISPATCH_AUTH.set(None)
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    from agent.services import make_video

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(make_video, "_run_generate", _noop)

    prompt = "P_manifest_sg clean prompt"
    manifest = await eas.create_manifest(
        surface="production_queue", run_ref="run_sg_1",
        items=[dict(item_key="op1", mode="IMG", final_prompt_text=prompt,
                    image_model="GEM_PIX_2", aspect="1:1", count=1)],
    )
    manifest_id = manifest["manifest_id"]

    # BEFORE approval: manifest_id present but not approved -> resolve None ->
    # enforced gate BLOCKS (never auto-approved from the provenance/manifest ref).
    blocked = await make_video.start_generate(
        mode="IMG", prompt=prompt, aspect="1:1", num_videos=1,
        image_model="GEM_PIX_2", manifest_id=manifest_id,
    )
    assert blocked["status"] == "REJECTED"
    assert blocked["error"] == "DISPATCH_NOT_APPROVED"

    # AFTER human approval: the exact item resolves by envelope hash -> PASS.
    await eas.approve_manifest(manifest_id, approved_by="faris")
    ok = await make_video.start_generate(
        mode="IMG", prompt=prompt, aspect="1:1", num_videos=1,
        image_model="GEM_PIX_2", manifest_id=manifest_id,
    )
    await asyncio.sleep(0)
    assert ok["status"] == "SUBMITTED"


async def test_native_extend_requires_approved_manifest_item(monkeypatch):
    # Corrective GAP 4: native Extend has NO generic exemption. Its continuation
    # prompt must match a human-APPROVED manifest item by envelope hash (the exact
    # dispatch shape the extend runtime uses: mode=EXTEND + prompt + model + aspect).
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas._DISPATCH_AUTH.set(None)
    prompt = "P_extend continuation block prompt"
    ext = dict(mode="EXTEND", final_prompt_text=prompt, model="Veo 3.1 Lite", aspect="9:16")

    # Unapproved -> hard block (no exemption).
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(**ext)
    assert exc.value.code == "DISPATCH_NOT_APPROVED"

    # Approve an Extend manifest item, then the exact block resolves + binds.
    manifest = await eas.create_manifest(
        surface="native_extend", run_ref="wgp_extend_1",
        items=[dict(item_key="blk1", mode="EXTEND", final_prompt_text=prompt,
                    model="Veo 3.1 Lite", aspect="9:16")],
    )
    await eas.approve_manifest(manifest["manifest_id"], approved_by="faris")
    resolved = await eas.resolve_manifest_approved_snapshot(
        manifest_id=manifest["manifest_id"], **ext,
    )
    assert resolved is not None
    verdict = await eas.verify_and_bind_dispatch(**ext, snapshot_id=resolved["snapshot_id"])
    assert verdict["pass"] is True


async def test_native_extend_materialize_hash_matches_dispatch(monkeypatch):
    # The Extend materialize helper must produce items whose envelope hash EXACTLY
    # matches run_native_extend_block's dispatch — else an approved Extend chain
    # would still block. Proves the materialise->approve->resolve loop end to end.
    import agent.services.google_flow_native_extend_runtime as nx
    from agent import config

    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas._DISPATCH_AUTH.set(None)
    ar = "VIDEO_ASPECT_RATIO_PORTRAIT"
    model_key = config.EXTEND_VIDEO_MODELS.get(ar)
    prompt = "extend continuation block prompt"

    class _B:
        block_index = 1
        position = 1
        prompt = "extend continuation block prompt"
        is_final = False
        start_frame_index = 0
        end_frame_index = 1

    class _Req:
        project_id = "pr1"
        scene_id = "sc1"
        source_operation_id = "op1"
        aspect_ratio = ar
        workspace_generation_package_id = "wgp_extend_mat"
        blocks = [_B()]

    derived = nx.build_extend_manifest_items(_Req())
    manifest = await eas.create_manifest(
        surface="native_extend", run_ref=derived["run_ref"],
        logical_mode="EXTEND", items=derived["items"],
    )
    await eas.approve_manifest(manifest["manifest_id"], approved_by="faris")

    # The exact dispatch run_native_extend_block performs.
    resolved = await eas.resolve_manifest_approved_snapshot(
        manifest_id=await eas.approved_manifest_id_for_run(
            "wgp_extend_mat", surface="native_extend"),
        mode="EXTEND", final_prompt_text=prompt, model=model_key, aspect=ar,
    )
    assert resolved is not None
    verdict = await eas.verify_and_bind_dispatch(
        mode="EXTEND", final_prompt_text=prompt, model=model_key, aspect=ar,
        snapshot_id=resolved["snapshot_id"],
    )
    assert verdict["pass"] is True


async def test_montage_mascot_frames_manifest_parity(monkeypatch):
    # Mascot montage threads source_mode=FRAMES into the dispatch; the materialised
    # manifest item must carry it too or the canonical Envelope v2 SHA won't match.
    # A manifest dispatch passes asset_media_ids=[] (no volatile media id), so both
    # the item (no assets) and the dispatch ([]) resolve to the same canonical set.
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas._DISPATCH_AUTH.set(None)
    prompt = "P_montage_mascot start-frame scene prompt"
    manifest = await eas.create_manifest(
        surface="montage", run_ref="run_mascot_1", product_id="prod_mascot_1",
        items=[dict(item_key="scene_1", mode="F2V", final_prompt_text=prompt,
                    product_id="prod_mascot_1", source_mode="FRAMES",
                    model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1)],
    )
    await eas.approve_manifest(manifest["manifest_id"], approved_by="faris")
    # Dispatch shape a montage mascot scene hands make_video (manifest -> assets=[]).
    resolved = await eas.resolve_manifest_approved_snapshot(
        manifest_id=await eas.approved_manifest_id_for_run(
            "run_mascot_1", surface="montage"),
        mode="F2V", final_prompt_text=prompt, source_mode="FRAMES",
        model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1,
        product_id="prod_mascot_1", asset_media_ids=[],
    )
    assert resolved is not None
    verdict = await eas.verify_and_bind_dispatch(
        mode="F2V", final_prompt_text=prompt, source_mode="FRAMES",
        model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1,
        product_id="prod_mascot_1", asset_media_ids=[],
        snapshot_id=resolved["snapshot_id"],
    )
    assert verdict["pass"] is True
    # A source_mode drift (FRAMES vs HYBRID) must NOT resolve — canonical identity.
    assert await eas.resolve_manifest_approved_snapshot(
        manifest_id=manifest["manifest_id"], mode="F2V", final_prompt_text=prompt,
        source_mode="HYBRID", model="Veo 3.1 Lite", aspect="9:16", duration_s=8,
        count=1, product_id="prod_mascot_1", asset_media_ids=[],
    ) is None


async def test_approved_manifest_id_for_run_lookup():
    prompt = "P_run_lookup clean prompt"
    manifest = await eas.create_manifest(
        surface="montage", run_ref="run_lookup_1",
        items=[dict(item_key="s1", mode="F2V", final_prompt_text=prompt,
                    model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1)],
    )
    # Not approved yet -> no dispatch authority for the run.
    assert await eas.approved_manifest_id_for_run("run_lookup_1", surface="montage") is None
    await eas.approve_manifest(manifest["manifest_id"], approved_by="faris")
    assert (
        await eas.approved_manifest_id_for_run("run_lookup_1", surface="montage")
        == manifest["manifest_id"]
    )
