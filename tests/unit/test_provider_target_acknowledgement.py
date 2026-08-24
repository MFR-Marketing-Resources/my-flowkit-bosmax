from __future__ import annotations

import pytest

from agent.services import execution_approval_service as eas


def _target():
    return eas.build_provider_target_authorization(
        lane="FACELESS_VIDEO",
        route="EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
        model="veo_3_1_lite",
        duration_s=8,
        aspect_ratio="9:16",
        product_id="product-1",
        copy_id="copy-1",
        profile_digest="profile-digest",
        sweetwps_digest="sweetwps-digest",
        compositor_digest="compositor-digest",
        compiler_digest="compiler-digest",
        owner_credit_ceiling=10,
    )


def test_target_digest_covers_all_authorized_fields():
    first = _target()
    changed = dict(first["target"], copy_id="copy-2")
    second = eas.build_provider_target_authorization(
        **{**changed, "owner_credit_ceiling": changed["owner_credit_ceiling"]}
    )
    assert first["target_digest"] != second["target_digest"]


@pytest.mark.asyncio
async def test_snapshot_ack_requires_exact_canonical_digest(monkeypatch):
    target = _target()
    ack = eas.build_provider_target_acknowledgement(
        target,
        provider_text="Confirmed: Veo 3.1 - Lite for 8 seconds.",
        model_duration_acknowledged=True,
    )
    snapshot = {"snapshot_id": "snap-1", "approval_state": eas.ApprovalState.DISPATCHED}
    monkeypatch.setattr(eas, "_require", lambda _snapshot_id: _async(snapshot))
    updates = []

    async def update(_snapshot_id, **values):
        updates.append(values)
        return {**snapshot, **values}

    monkeypatch.setattr(eas._crud, "update_snapshot", update)
    result = await eas.record_provider_target_acknowledgement(
        "snap-1", target_authorization=target, acknowledgement=ack
    )
    assert result["provider_target_digest"] == target["target_digest"]
    assert updates[0]["provider_target_ack_json"]

    bad = dict(ack, proposed_target_digest="stale-digest")
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        await eas.record_provider_target_acknowledgement(
            "snap-1", target_authorization=target, acknowledgement=bad
        )
    assert exc.value.code == "PROVIDER_TARGET_DIGEST_MISMATCH"


async def _async(value):
    return value
