"""Final Prompt Approval Gate — provider-free proof of the WYSIWYG invariant.

Proves, without any provider call or credit spend, that:

    approved_execution_envelope_sha256 == dispatched_execution_envelope_sha256

is the ONLY thing that authorises a dispatch, and that every provider-affecting
change after approval (prompt / model / aspect / duration / count / asset) fails
closed. These are the service-level backend bypass-matrix guarantees; the choke
wiring tests assert the same at the dispatch boundaries.
"""

from __future__ import annotations

import pytest

from agent.services import execution_approval_service as eas


_BASE = dict(
    surface="hybrid",
    logical_mode="F2V",
    final_prompt_text="A clean provider-ready UGC prompt about a serum.",
    product_id="prod_test_1",
    source_mode="HYBRID",
    model="Veo 3.1 Lite",
    aspect="9:16",
    duration_s=8,
    count=1,
    asset_media_ids=["550e8400-e29b-41d4-a716-446655440000"],
)


def _dispatch_args(**overrides):
    """Map a review spec to the dispatch-boundary arg names."""
    args = dict(
        mode=_BASE["logical_mode"],
        final_prompt_text=_BASE["final_prompt_text"],
        source_mode=_BASE["source_mode"],
        model=_BASE["model"],
        aspect=_BASE["aspect"],
        duration_s=_BASE["duration_s"],
        count=_BASE["count"],
        asset_media_ids=list(_BASE["asset_media_ids"]),
    )
    args.update(overrides)
    return args


# --------------------------------------------------------------------------- #
# Deterministic envelope + hashing
# --------------------------------------------------------------------------- #

def test_identity_is_deterministic_for_equal_inputs():
    a = eas.compute_dispatch_identity(**_dispatch_args())
    b = eas.compute_dispatch_identity(**_dispatch_args())
    assert a["execution_envelope_sha256"] == b["execution_envelope_sha256"]
    assert a["prompt_sha256"] == b["prompt_sha256"]


def test_asset_order_does_not_change_hash():
    a = eas.compute_dispatch_identity(**_dispatch_args(asset_media_ids=["a", "b", "c"]))
    b = eas.compute_dispatch_identity(**_dispatch_args(asset_media_ids=["c", "a", "b"]))
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
    base = eas.compute_dispatch_identity(**_dispatch_args())
    changed = eas.compute_dispatch_identity(**_dispatch_args(**{field: value}))
    assert base["execution_envelope_sha256"] != changed["execution_envelope_sha256"]


def test_seed_is_not_part_of_the_envelope():
    # `seed` is not a runtime input to start_generate; passing it must be ignored
    # (compute_dispatch_identity does not accept it), proving no invented field.
    ident = eas.compute_dispatch_identity(**_dispatch_args())
    assert "seed" not in ident["execution_envelope"]


# --------------------------------------------------------------------------- #
# Lifecycle + the dispatch gate (the bypass matrix)
# --------------------------------------------------------------------------- #

async def test_create_then_approve_then_dispatch_pass():
    snap = await eas.create_review_snapshot(**_BASE)
    assert snap["approval_state"] == eas.ApprovalState.REVIEW_REQUIRED
    assert snap["scan_clean"] == 1

    approved = await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    assert approved["approval_state"] == eas.ApprovalState.APPROVED
    assert approved["approved_execution_envelope_sha256"] == snap["execution_envelope_sha256"]

    verdict = await eas.verify_and_bind_dispatch(**_dispatch_args())
    assert verdict["pass"] is True
    assert verdict["reason"] == "APPROVED_ENVELOPE_MATCH"
    assert (
        verdict["dispatched_execution_envelope_sha256"]
        == approved["approved_execution_envelope_sha256"]
    )
    # single-use: the snapshot is now DISPATCHED.
    bound = await eas.get_snapshot(snap["snapshot_id"])
    assert bound["approval_state"] == eas.ApprovalState.DISPATCHED


async def test_no_approval_blocks_when_enforced(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(**_dispatch_args())
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


async def test_no_approval_is_observe_only_when_not_enforced(monkeypatch):
    monkeypatch.delenv("EXECUTION_APPROVAL_GATE_ENFORCED", raising=False)
    verdict = await eas.verify_and_bind_dispatch(**_dispatch_args())
    assert verdict["pass"] is False
    assert verdict["enforced"] is False
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
    snap = await eas.create_review_snapshot(**_BASE)
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.verify_and_bind_dispatch(**_dispatch_args(**{field: value}))
    assert exc.value.code == "DISPATCH_NOT_APPROVED"


async def test_edit_after_approval_requires_reapproval(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    snap = await eas.create_review_snapshot(**_BASE)
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")

    edited = await eas.apply_edit(
        snap["snapshot_id"],
        edited_prompt_text="A newly edited provider-ready prompt.",
        editor_id="faris",
    )
    assert edited["approval_state"] == eas.ApprovalState.EDITED
    assert edited["approved_execution_envelope_sha256"] is None

    # The edited envelope has no approved match -> BLOCK until re-approved.
    with pytest.raises(eas.ExecutionApprovalError):
        await eas.verify_and_bind_dispatch(
            **_dispatch_args(final_prompt_text="A newly edited provider-ready prompt.")
        )

    # Re-approve the edited snapshot -> the edited envelope now dispatches.
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    verdict = await eas.verify_and_bind_dispatch(
        **_dispatch_args(final_prompt_text="A newly edited provider-ready prompt.")
    )
    assert verdict["pass"] is True


async def test_invalidated_approval_blocks(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    snap = await eas.create_review_snapshot(**_BASE)
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    await eas.invalidate_snapshot(snap["snapshot_id"], reason="asset changed upstream")
    with pytest.raises(eas.ExecutionApprovalError):
        await eas.verify_and_bind_dispatch(**_dispatch_args())


async def test_dispatched_snapshot_is_single_use(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    snap = await eas.create_review_snapshot(**_BASE)
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    first = await eas.verify_and_bind_dispatch(**_dispatch_args())
    assert first["pass"] is True
    # A second dispatch of the identical envelope must NOT re-authorise.
    with pytest.raises(eas.ExecutionApprovalError):
        await eas.verify_and_bind_dispatch(**_dispatch_args())


async def test_scan_not_clean_refuses_approval():
    # scan_prompt_text flags product_id leakage; a prompt echoing the product_id
    # is not clean, so approval must be refused (no bypass via a dirty prompt).
    dirty = dict(_BASE)
    dirty["final_prompt_text"] = "prompt that leaks prod_test_1 into the text"
    snap = await eas.create_review_snapshot(**dirty)
    assert snap["scan_clean"] == 0
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    assert exc.value.code == "SNAPSHOT_SCAN_NOT_CLEAN"


async def test_snapshot_id_pin_prevents_foreign_approval_match(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    # Two independent approvals of the SAME envelope.
    snap_a = await eas.create_review_snapshot(**_BASE)
    await eas.approve_snapshot(snap_a["snapshot_id"], approved_by="faris")
    snap_b = await eas.create_review_snapshot(**_BASE)
    await eas.approve_snapshot(snap_b["snapshot_id"], approved_by="faris")

    # Pinning to snap_b binds snap_b, not snap_a.
    verdict = await eas.verify_and_bind_dispatch(
        **_dispatch_args(), snapshot_id=snap_b["snapshot_id"]
    )
    assert verdict["pass"] is True
    assert verdict["snapshot_id"] == snap_b["snapshot_id"]
    assert (await eas.get_snapshot(snap_b["snapshot_id"]))["approval_state"] == "DISPATCHED"
    assert (await eas.get_snapshot(snap_a["snapshot_id"]))["approval_state"] == "APPROVED"
