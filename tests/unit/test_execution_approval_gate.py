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
    ],
)
def test_any_provider_affecting_change_changes_the_hash(field, value):
    base = eas.compute_dispatch_identity(**_dispatch("baseline prompt"))
    changed = eas.compute_dispatch_identity(**_dispatch("baseline prompt", **{field: value}))
    assert base["execution_envelope_sha256"] != changed["execution_envelope_sha256"]


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


async def test_img_is_observe_only_even_when_enforced(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    # IMG is credit-free (owner law): verify never RAISES for it, even enforced +
    # unapproved — it returns an observe verdict so free image generation is never
    # blocked. Video (the default _dispatch mode) DOES hard-block.
    verdict = await eas.verify_and_bind_dispatch(**_dispatch("P_img_free", mode="IMG"))
    assert verdict["pass"] is False
    assert verdict["reason"] == "NO_APPROVED_SNAPSHOT_FOR_ENVELOPE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("final_prompt_text", "an edited-after prompt the user never approved"),
        ("model", "Veo 3.1 Fast"),
        ("aspect", "16:9"),
        ("duration_s", 16),
        ("count", 2),
        ("asset_media_ids", ["swapped-asset"]),
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
    assert result["error"] == "DISPATCH_NOT_APPROVED"


async def test_start_generate_img_is_observe_only_when_enforced(monkeypatch):
    import asyncio

    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    from agent.services import make_video

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(make_video, "_run_generate", _noop)
    # IMG generation is credit-free (owner law): never hard-blocked, even without
    # an approval and even when enforcement is on.
    result = await make_video.start_generate(
        mode="IMG", prompt="P_img_observe unapproved image prompt",
        aspect="1:1", num_videos=1, image_model="GEM_PIX_2",
    )
    await asyncio.sleep(0)
    assert result["status"] == "SUBMITTED"


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
# Non-UI enablement safety: upstream-approved auto-snapshot (queue / bulk /
# scheduler / Extend fire ALREADY-approved packages/plans).
# --------------------------------------------------------------------------- #

async def test_ensure_upstream_approved_creates_and_approves():
    snap = await eas.ensure_upstream_approved_snapshot(
        **_dispatch("P_upstream_1"), surface="production_queue", provenance="production_queue",
    )
    assert snap["approval_state"] == eas.ApprovalState.APPROVED
    assert snap["created_by"] == "production_queue"


async def test_ensure_upstream_approved_is_idempotent():
    a = await eas.ensure_upstream_approved_snapshot(
        **_dispatch("P_upstream_idem"), surface="bulk_video", provenance="bulk_video",
    )
    b = await eas.ensure_upstream_approved_snapshot(
        **_dispatch("P_upstream_idem"), surface="bulk_video", provenance="bulk_video",
    )
    assert a["snapshot_id"] == b["snapshot_id"]


async def test_ensure_upstream_approved_never_approves_dirty_prompt():
    snap = await eas.ensure_upstream_approved_snapshot(
        **_dispatch("P_upstream leaks prod_dirty_1", product_id="prod_dirty_1"),
        surface="production_queue",
        provenance="production_queue",
    )
    assert snap["approval_state"] != eas.ApprovalState.APPROVED  # fail-closed


async def test_start_generate_upstream_provenance_auto_approves(monkeypatch):
    import asyncio

    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    from agent.services import make_video

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(make_video, "_run_generate", _noop)

    # No pre-created snapshot; the upstream-approved provenance materialises one so
    # an already-approved production run is not blocked when enforcement is on.
    result = await make_video.start_generate(
        mode="IMG", prompt="P_upstream_sg clean prompt", aspect="1:1", num_videos=1,
        image_model="GEM_PIX_2", upstream_approved_provenance="production_queue",
    )
    await asyncio.sleep(0)
    assert result["status"] == "SUBMITTED"
