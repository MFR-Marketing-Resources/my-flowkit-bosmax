"""Comprehensive regression suite for Hybrid Approval-Gate Reference Identity Drift Remediation.

Proves:
1. Hybrid product visual with NO live Flow UUID:
   review -> approve -> materialize/upload -> new Flow UUID -> dispatch PASS.
2. Same exact canonical visual re-uploaded:
   Flow UUID A -> Flow UUID B
   approval remains valid because canonical visual content hash is unchanged.
3. Same product_id, actual official visual changed:
   full SHA A -> full SHA B
   old approval FAILS CLOSED (DISPATCH_NOT_APPROVED).
4. Manual F2V selected frame changed:
   explicit user-selected frame changes after approval -> FAILS CLOSED.
5. Existing live Flow media UUID:
   PASS, no regression.
6. T2V:
   unchanged, no-reference behavior passes.
7. I2V:
   reference locking preserved.
8. Tampering (prompt / model / aspect / duration / count):
   each remains strictly fail-closed.
9. Provider backstop:
   no unapproved video dispatch reaches provider.
10. Historical v1 snapshot:
   auditable with envelope_version=1 and distinct identity from v2.
"""

from __future__ import annotations

import hashlib
import json
import pytest

from agent.db import crud, execution_approval_crud as approval_crud
from agent.services import execution_approval_service as eas
from agent.services.execution_approval_service import ApprovalState
from agent.services.product_visual_grounding_resolver import (
    canonical_product_visual_approval_fingerprint,
    get_canonical_product_visual_fingerprint,
)


@pytest.fixture(autouse=True)
def _enforce_gate(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")


@pytest.fixture
async def sample_product(tmp_path):
    """Create a real product with a verified canonical image cutout in DB."""
    from PIL import Image

    img_file = tmp_path / "canonical_cutout.png"
    img = Image.new("RGBA", (64, 64), color=(255, 0, 0, 255))
    img.save(img_file, format="PNG")
    img_bytes = img_file.read_bytes()
    img_sha = hashlib.sha256(img_bytes).hexdigest()

    prod = await crud.create_product(
        raw_product_title="Test Hybrid Product Title",
        product_display_name="Test Hybrid Product",
        brand_name="TestBrand",
        category="Health",
        local_image_path=str(img_file),
    )
    return prod, str(img_file), img_sha


# --------------------------------------------------------------------------- #
# Test 1 & 2: Hybrid Materialization & Flow UUID Rotation
# --------------------------------------------------------------------------- #

async def test_hybrid_product_asset_materialization_and_uuid_rotation(sample_product):
    """Proves that a product visual without a live Flow UUID at review time
    passes dispatch after backend materialization, and that rotating the Flow
    media UUID does NOT break the valid approval."""
    prod, img_path, img_sha = sample_product
    product_id = prod["id"]

    prompt = "A high quality cinematic shot of premium herbal massage oil on wooden table"
    
    # 1. Review snapshot created with NO live Flow UUID (or local asset ID)
    review_snap = await eas.create_review_snapshot(
        surface="hybrid",
        logical_mode="F2V",
        final_prompt_text=prompt,
        product_id=product_id,
        source_mode="HYBRID",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=["local-asset-id-1234"],  # pre-resolution ID
    )
    assert review_snap["approval_state"] == ApprovalState.REVIEW_REQUIRED
    env = json.loads(review_snap["execution_envelope_json"])
    assert env["envelope_version"] == 2
    assert env["product_id"] == product_id
    # Must use full canonical SHA
    expected_fp = f"PRODUCT_VISUAL|{product_id}|start_frame|{img_sha}"
    assert env["asset_fingerprints"] == [expected_fp]

    # 2. Operator approves
    approved = await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")
    assert approved["approval_state"] == ApprovalState.APPROVED

    # 3. Backend materializes/uploads asset and gets newly generated Flow UUID A
    flow_uuid_a = "flow-uuid-aaaa-1111"
    verdict = await eas.verify_and_bind_dispatch(
        mode="F2V",
        final_prompt_text=prompt,
        product_id=product_id,
        source_mode="HYBRID",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[flow_uuid_a],
    )
    assert verdict["pass"] is True
    assert verdict["reason"] == "APPROVED_ENVELOPE_MATCH"
    assert verdict["snapshot_id"] == review_snap["snapshot_id"]


async def test_same_visual_reuploaded_with_new_flow_uuid(sample_product):
    """Proves that if an approval is created and the same visual is re-uploaded
    to Flow getting UUID B, dispatch still matches and passes."""
    prod, img_path, img_sha = sample_product
    product_id = prod["id"]
    prompt = "A high quality cinematic shot of premium herbal massage oil on wooden table - scene 2"

    review_snap = await eas.create_review_snapshot(
        surface="hybrid",
        logical_mode="F2V",
        final_prompt_text=prompt,
        product_id=product_id,
        source_mode="HYBRID",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=["local-asset-id-9999"],
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    # Flow upload results in Flow UUID B
    flow_uuid_b = "flow-uuid-bbbb-2222"
    verdict = await eas.verify_and_bind_dispatch(
        mode="F2V",
        final_prompt_text=prompt,
        product_id=product_id,
        source_mode="HYBRID",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[flow_uuid_b],
    )
    assert verdict["pass"] is True
    assert verdict["reason"] == "APPROVED_ENVELOPE_MATCH"


# --------------------------------------------------------------------------- #
# Test 3: Actual Product Visual Content Changed Post-Approval -> FAILS CLOSED
# --------------------------------------------------------------------------- #

async def test_actual_product_visual_changed_fails_closed(sample_product, tmp_path):
    """Proves that if the product visual content changes after approval,
    the dispatch envelope hash changes and the gate strictly fails closed."""
    prod, img_path, img_sha = sample_product
    product_id = prod["id"]
    prompt = "A high quality cinematic shot of premium herbal massage oil on wooden table - scene 3"

    review_snap = await eas.create_review_snapshot(
        surface="hybrid",
        logical_mode="F2V",
        final_prompt_text=prompt,
        product_id=product_id,
        source_mode="HYBRID",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    # Mutate the underlying product visual file to different bytes (new SHA)
    from PIL import Image

    new_img_file = tmp_path / "canonical_cutout_v2.png"
    new_img = Image.new("RGBA", (64, 64), color=(0, 255, 0, 255))
    new_img.save(new_img_file, format="PNG")
    await crud.update_product(product_id, local_image_path=str(new_img_file))

    with pytest.raises(eas.ExecutionApprovalError) as exc_info:
        await eas.verify_and_bind_dispatch(
            mode="F2V",
            final_prompt_text=prompt,
            product_id=product_id,
            source_mode="HYBRID",
            model="Veo 3.1 - Lite",
            aspect="9:16",
            duration_s=8,
            count=1,
        )
    assert exc_info.value.code == "DISPATCH_NOT_APPROVED"


# --------------------------------------------------------------------------- #
# Test 4: Manual F2V Selected Frame Changed -> FAILS CLOSED
# --------------------------------------------------------------------------- #

async def test_manual_f2v_frame_changed_fails_closed():
    """Proves that manual F2V (source_mode=FRAMES) retains strict frame locking;
    changing the selected frame after approval fails closed."""
    prompt = "Manual F2V frame continuation test"
    frame_a = "frame_asset_uuid_AAAA"
    frame_b = "frame_asset_uuid_BBBB"

    review_snap = await eas.create_review_snapshot(
        surface="f2v",
        logical_mode="F2V",
        final_prompt_text=prompt,
        source_mode="FRAMES",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[frame_a],
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    # Dispatch with frame_b instead of frame_a
    with pytest.raises(eas.ExecutionApprovalError) as exc_info:
        await eas.verify_and_bind_dispatch(
            mode="F2V",
            final_prompt_text=prompt,
            source_mode="FRAMES",
            model="Veo 3.1 - Lite",
            aspect="9:16",
            duration_s=8,
            count=1,
            asset_media_ids=[frame_b],
        )
    assert exc_info.value.code == "DISPATCH_NOT_APPROVED"


# --------------------------------------------------------------------------- #
# Test 5, 6, 7: Existing Live UUID, T2V, and I2V
# --------------------------------------------------------------------------- #

async def test_existing_live_flow_media_uuid_passes():
    """Proves that manual / non-product assets with existing live Flow UUIDs pass."""
    prompt = "Existing Flow UUID test"
    live_uuid = "existing-live-flow-uuid-1111"
    review_snap = await eas.create_review_snapshot(
        surface="f2v",
        logical_mode="F2V",
        final_prompt_text=prompt,
        source_mode="FRAMES",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[live_uuid],
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    verdict = await eas.verify_and_bind_dispatch(
        mode="F2V",
        final_prompt_text=prompt,
        source_mode="FRAMES",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[live_uuid],
    )
    assert verdict["pass"] is True


async def test_t2v_no_references_passes():
    """Proves that T2V (text-only, no references) functions cleanly without regression."""
    prompt = "T2V text-only generation test"
    review_snap = await eas.create_review_snapshot(
        surface="t2v",
        logical_mode="T2V",
        final_prompt_text=prompt,
        source_mode="T2V",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    verdict = await eas.verify_and_bind_dispatch(
        mode="T2V",
        final_prompt_text=prompt,
        source_mode="T2V",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
    )
    assert verdict["pass"] is True


async def test_i2v_reference_authority():
    """Proves that I2V reference locking is strictly preserved."""
    prompt = "I2V character reference test"
    char_ref = "character_asset_uuid_999"
    review_snap = await eas.create_review_snapshot(
        surface="i2v",
        logical_mode="I2V",
        final_prompt_text=prompt,
        source_mode="INGREDIENTS",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[char_ref],
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    verdict = await eas.verify_and_bind_dispatch(
        mode="I2V",
        final_prompt_text=prompt,
        source_mode="INGREDIENTS",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        asset_media_ids=[char_ref],
    )
    assert verdict["pass"] is True


# --------------------------------------------------------------------------- #
# Test 8: Tampering (prompt / model / aspect / duration / count)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "field,tampered_val",
    [
        ("final_prompt_text", "TAMPERED PROMPT TEXT"),
        ("model", "Veo 3.1 - Fast"),
        ("aspect", "16:9"),
        ("duration_s", 16),
        ("count", 2),
    ],
)
async def test_parameter_tampering_post_approval_fails_closed(sample_product, field, tampered_val):
    """Proves that altering any provider-affecting parameter after approval fails closed."""
    prod, _, _ = sample_product
    product_id = prod["id"]
    prompt = f"Baseline prompt for tamper test {field}"

    review_snap = await eas.create_review_snapshot(
        surface="hybrid",
        logical_mode="F2V",
        final_prompt_text=prompt,
        product_id=product_id,
        source_mode="HYBRID",
        model="Veo 3.1 - Lite",
        aspect="9:16",
        duration_s=8,
        count=1,
    )
    await eas.approve_snapshot(review_snap["snapshot_id"], approved_by="operator")

    dispatch_kwargs = {
        "mode": "F2V",
        "final_prompt_text": prompt,
        "product_id": product_id,
        "source_mode": "HYBRID",
        "model": "Veo 3.1 - Lite",
        "aspect": "9:16",
        "duration_s": 8,
        "count": 1,
    }
    dispatch_kwargs[field] = tampered_val

    with pytest.raises(eas.ExecutionApprovalError) as exc_info:
        await eas.verify_and_bind_dispatch(**dispatch_kwargs)
    assert exc_info.value.code == "DISPATCH_NOT_APPROVED"


# --------------------------------------------------------------------------- #
# Test 9: Provider Backstop
# --------------------------------------------------------------------------- #

def test_provider_backstop_blocks_unapproved_context():
    """Proves that without gate authorization in context, provider dispatch is blocked."""
    eas._DISPATCH_AUTH.set(None)
    reason = eas.video_dispatch_unauthorized_reason(method="generate_video")
    assert reason == "PROVIDER_DISPATCH_UNAUTHORIZED"


# --------------------------------------------------------------------------- #
# Test 10: Envelope Versioning & Historical v1 Snapshot Auditing
# --------------------------------------------------------------------------- #

async def test_envelope_v2_versioning_and_historical_v1():
    """Proves that new snapshots use envelope_version=2 and historical v1 snapshots
    remain distinct and auditable without silent mutation."""
    identity = eas.compute_dispatch_identity(
        mode="F2V",
        final_prompt_text="Version test",
        source_mode="HYBRID",
        product_id="prod_ver_1",
    )
    assert identity["execution_envelope"]["envelope_version"] == 2
    assert "product_id" in identity["execution_envelope"]

    # Historical v1 envelope shape (from past PRs)
    v1_env = {
        "envelope_version": 1,
        "mode": "F2V",
        "prompt_sha256": hashlib.sha256(b"v1 prompt").hexdigest(),
        "source_mode": "HYBRID",
        "model": "Veo 3.1 - Lite",
        "aspect": "9:16",
        "duration_s": 8,
        "count": 1,
        "image_model": None,
        "asset_fingerprints": ["old_v1_asset"],
    }
    v1_sha = hashlib.sha256(json.dumps(v1_env, sort_keys=True).encode("utf-8")).hexdigest()

    # Create historical v1 record in DB directly
    await approval_crud.create_snapshot({
        "snapshot_id": "eas_hist_v1_0000",
        "review_session_id": "rev_hist_v1",
        "product_id": "prod_ver_1",
        "surface": "hybrid",
        "logical_mode": "F2V",
        "source_mode": "HYBRID",
        "final_prompt_text": "v1 prompt",
        "prompt_sha256": v1_env["prompt_sha256"],
        "execution_envelope_json": json.dumps(v1_env, sort_keys=True),
        "execution_envelope_sha256": v1_sha,
        "approval_state": ApprovalState.APPROVED,
        "approved_execution_envelope_sha256": v1_sha,
        "edited": 0,
        "scan_clean": 1,
        "approved_version": 1,
        "approved_by": "operator_v1",
    })

    # Verify historical v1 record is retrievable and unchanged
    saved = await approval_crud.get_snapshot("eas_hist_v1_0000")
    assert saved is not None
    saved_env = json.loads(saved["execution_envelope_json"])
    assert saved_env["envelope_version"] == 1
    assert saved["approved_execution_envelope_sha256"] == v1_sha


# --------------------------------------------------------------------------- #
# Test 11: Fail-Closed on Canonical Product Visual Resolver Failure
# --------------------------------------------------------------------------- #

async def test_hybrid_product_visual_resolver_failure_fails_closed(monkeypatch):
    """Proves that if canonical Product Visual resolution fails for product-backed HYBRID:
    - create_review_snapshot fails closed (no fallback to caller media ID)
    - verify_and_bind_dispatch fails closed
    - zero unverified/fallback dispatch occurs.
    """
    # 1. Non-existent product ID
    with pytest.raises(eas.ExecutionApprovalError) as exc_info:
        await eas.create_review_snapshot(
            surface="hybrid",
            logical_mode="F2V",
            final_prompt_text="Test prompt with missing product",
            product_id="non_existent_product_9999",
            source_mode="HYBRID",
            model="Veo 3.1 - Lite",
            aspect="9:16",
            duration_s=8,
            count=1,
            asset_media_ids=["fallback-flow-uuid-1111"],
            asset_fingerprints=["FALLBACK_FP_2222"],
        )
    assert exc_info.value.code == "PRODUCT_VISUAL_REFERENCE_REQUIRED"

    # 2. Mocked exception in get_canonical_product_visual_fingerprint
    async def _mock_fail(*args, **kwargs):
        raise RuntimeError("Disk I/O failure loading product cutout")

    monkeypatch.setattr(
        "agent.services.product_visual_grounding_resolver.get_canonical_product_visual_fingerprint",
        _mock_fail,
    )

    # Review snapshot MUST fail closed
    with pytest.raises(eas.ExecutionApprovalError) as exc_info2:
        await eas.create_review_snapshot(
            surface="hybrid",
            logical_mode="F2V",
            final_prompt_text="Test prompt with erroring resolver",
            product_id="prod_err_1",
            source_mode="HYBRID",
            model="Veo 3.1 - Lite",
            asset_media_ids=["fallback-flow-uuid-3333"],
        )
    assert exc_info2.value.code == "PRODUCT_VISUAL_REFERENCE_REQUIRED"

    # Dispatch verification MUST fail closed
    with pytest.raises(eas.ExecutionApprovalError) as exc_info3:
        await eas.verify_and_bind_dispatch(
            mode="F2V",
            final_prompt_text="Test prompt with erroring resolver",
            source_mode="HYBRID",
            product_id="prod_err_1",
            model="Veo 3.1 - Lite",
            asset_media_ids=["fallback-flow-uuid-3333"],
        )
    assert exc_info3.value.code in ("PRODUCT_VISUAL_REFERENCE_REQUIRED", "DISPATCH_NOT_APPROVED")

