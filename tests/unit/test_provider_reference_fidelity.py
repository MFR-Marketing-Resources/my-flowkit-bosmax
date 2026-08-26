"""Provider-reference product-fidelity regression tests (owner A-J).

Every product-conditioned provider video lane (Hybrid, reference-conditioned
Faceless, Montage product-anchor scenes, P6 provider stages) converges on the
shared boundary ``prepare_official_provider_reference`` and the custody seam.
These tests pin the shared guarantees: the reference is the registration-backed
official visual only, the product is never rescaled, the canvas is padded when a
target aspect differs, the geometry contract survives to the custody payload, and
the provider-boundary SHA must match the governed prepared reference.
"""
import hashlib

import pytest
from PIL import Image

import agent.services.official_provider_reference_service as ref_svc
import agent.services.product_visual_custody_service as cust
from agent.services.official_provider_reference_service import (
    OfficialProviderReferenceError,
    prepare_official_provider_reference,
)


def _official_asset(tmp_path, *, source_type="PRODUCT_TRUTH_LOCK_CUTOUT",
                    product_id="p-1", media_id="ca_official_1", sha_override=None,
                    frame=(1000, 1000), product_box=(300, 250, 400, 600)):
    img = Image.new("RGBA", frame, (0, 0, 0, 0))
    px, py, pw, ph = product_box
    img.paste(Image.new("RGBA", (pw, ph), (200, 180, 160, 255)), (px, py))
    path = tmp_path / f"official-{product_id}.png"
    img.save(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = {
        "product_id": product_id,
        "media_id": media_id,
        "local_file_path": str(path),
        "official_visual_sha256": sha_override or sha,
        "official_visual_source_type": source_type,
        "official_visual": True,
        "asset_source": "PRODUCT_VISUAL_OFFICIAL_CUTOUT"
        if "CUTOUT" in source_type else "PRODUCT_VISUAL_OFFICIAL_SOURCE",
        "width": frame[0],
        "height": frame[1],
    }
    return asset, path, sha


NON_OFFICIAL_SOURCE_TYPES = [
    "PRODUCT_ROW_IMAGE_URL",       # materialized listing/catalog thumbnail
    "PRODUCT_ROW_LOCAL_PATH",      # scraped catalog local path
    "PRODUCT_ROW_MEDIA_ID",        # stale generated artifact
    "SCHEMA_CANONICAL_SOURCE",     # schema photo, not registration selection
    "CREATIVE_ASSET_PRODUCT_REFERENCE",
    "REFERENCE_PACK_CANONICAL_SOURCE",
]


# ── A-D: every lane's shared boundary uses the registration-backed official only ──

def test_A_hybrid_uses_current_official_visual_only(tmp_path):
    """HYBRID (F2V) — the shared boundary accepts the approved-cutout official."""
    asset, _p, sha = _official_asset(tmp_path, source_type="PRODUCT_TRUTH_LOCK_CUTOUT")
    prepared = prepare_official_provider_reference({"id": "p-1"}, asset)
    assert prepared["official_source_type"] == "PRODUCT_TRUTH_LOCK_CUTOUT"
    assert prepared["official_media_id"] == "ca_official_1"
    assert prepared["official_sha256"] == sha
    assert prepared["prepared_reference_sha256"] == sha  # native, no re-encode


def test_B_faceless_reference_route_uses_official_only(tmp_path):
    """Reference-conditioned FACELESS — registered Original Source is official."""
    asset, _p, sha = _official_asset(tmp_path, source_type="PRODUCT_TRUTH_LOCK_SOURCE")
    prepared = prepare_official_provider_reference({"id": "p-1"}, asset)
    assert prepared["official_source_type"] == "PRODUCT_TRUTH_LOCK_SOURCE"
    assert prepared["prepared_reference_sha256"] == sha


def test_C_montage_product_scene_uses_official(tmp_path):
    """MONTAGE product-anchor scene routes through the same boundary."""
    asset, _p, _sha = _official_asset(tmp_path, source_type="PRODUCT_TRUTH_LOCK_CUTOUT")
    prepared = prepare_official_provider_reference({"id": "p-1"}, asset)
    assert prepared["product_rescaled"] is False
    assert prepared["geometry_contract"]["geometry_lock_enabled"] is True


def test_D_p6_provider_stage_uses_official(tmp_path):
    """P6 provider stage routes through the same boundary (custody-bearing)."""
    asset, _p, sha = _official_asset(tmp_path, source_type="PRODUCT_TRUTH_LOCK_SOURCE")
    prepared = prepare_official_provider_reference({"id": "p-1"}, asset)
    assert prepared["official_sha256"] == sha
    assert prepared["pixel_fidelity_verified"] is True


# ── E: preparation never changes product pixel dimensions ──

def test_E_preparation_never_changes_product_pixel_dimensions(tmp_path):
    asset, _p, _sha = _official_asset(tmp_path, product_box=(300, 250, 400, 600))
    prepared = prepare_official_provider_reference({"id": "p-1"}, asset)
    assert prepared["product_pixel_dimensions"] == {"w": 400, "h": 600}
    assert prepared["product_rescaled"] is False
    assert prepared["canvas_padding"] is None


# ── F: target-aspect change pads canvas, product pixels preserved ──

def test_F_target_aspect_pads_canvas_not_product(tmp_path):
    asset, _p, sha = _official_asset(tmp_path, frame=(1000, 1000))
    # 9:16 canvas that CONTAINS the native frame -> pad, never shrink.
    prepared = prepare_official_provider_reference(
        {"id": "p-1"}, asset, target_canvas={"w": 1080, "h": 1920}
    )
    assert prepared["product_rescaled"] is False
    assert prepared["pixel_fidelity_verified"] is True
    assert prepared["product_pixel_dimensions"] == {"w": 400, "h": 600}  # unchanged
    assert prepared["reference_width"] == 1080 and prepared["reference_height"] == 1920
    assert prepared["canvas_padding"] == {"left": 40, "top": 460, "right": 40, "bottom": 460}
    assert prepared["prepared_reference_sha256"] != sha  # padded plate differs from native


def test_F_canvas_smaller_than_product_fails_closed(tmp_path):
    asset, _p, _sha = _official_asset(tmp_path, frame=(1000, 1000))
    with pytest.raises(OfficialProviderReferenceError) as exc:
        prepare_official_provider_reference(
            {"id": "p-1"}, asset, target_canvas={"w": 720, "h": 1280}
        )
    assert exc.value.code == ref_svc.ERR_OFFICIAL_PROVIDER_REFERENCE_CANVAS_TOO_SMALL


# ── G: replacing the official visual invalidates the old prepared reference ──

def test_G_official_visual_replacement_changes_prepared_sha(tmp_path):
    a1, _p1, sha1 = _official_asset(tmp_path, product_id="p-1")
    prepared1 = prepare_official_provider_reference({"id": "p-1"}, a1)
    # Operator replaces the official visual (different pixels -> different bytes).
    a2, _p2, sha2 = _official_asset(
        tmp_path, product_id="p-1", product_box=(200, 200, 500, 700)
    )
    a2["local_file_path"] = str(_p2)
    prepared2 = prepare_official_provider_reference({"id": "p-1"}, a2)
    assert sha1 != sha2
    assert prepared1["prepared_reference_sha256"] != prepared2["prepared_reference_sha256"]
    # A stale uploaded reference (old sha) can no longer bind onto the new receipt.
    receipt = {"prepared_reference_sha256": prepared2["prepared_reference_sha256"]}
    with pytest.raises(cust.ProductVisualCustodyError) as exc:
        cust.bind_provider_reference_transport(
            receipt,
            provider_reference_media_ids=["m1"],
            official_provider_media_id="m1",
            uploaded_local_sha256=sha1,  # stale
        )
    assert exc.value.code == cust.ERR_PROVIDER_REFERENCE_SHA_DRIFT


# ── H: stale / non-official source fails closed ──

@pytest.mark.parametrize("source_type", NON_OFFICIAL_SOURCE_TYPES)
def test_H_non_official_source_fails_closed(tmp_path, source_type):
    asset, _p, _sha = _official_asset(tmp_path, source_type=source_type)
    with pytest.raises(OfficialProviderReferenceError) as exc:
        prepare_official_provider_reference({"id": "p-1"}, asset)
    assert exc.value.code == ref_svc.ERR_OFFICIAL_PROVIDER_REFERENCE_NOT_REGISTERED


def test_H_tampered_official_bytes_fail_closed(tmp_path):
    asset, path, _sha = _official_asset(tmp_path)
    asset["official_visual_sha256"] = "0" * 64  # declared authority no longer matches bytes
    with pytest.raises(OfficialProviderReferenceError) as exc:
        prepare_official_provider_reference({"id": "p-1"}, asset)
    assert exc.value.code == ref_svc.ERR_OFFICIAL_PROVIDER_REFERENCE_HASH_MISMATCH


# ── I: geometry contract survives into the custody payload ──

def test_I_geometry_contract_survives_to_custody(tmp_path, monkeypatch):
    asset, _p, sha = _official_asset(tmp_path, product_box=(300, 250, 400, 600))
    prepared = prepare_official_provider_reference({"id": "p-1"}, asset)
    # Isolate the receipt-merge from DB-backed snapshots.
    monkeypatch.setattr(cust, "_truth_lock_snapshot", lambda pid: {"canonical_sha256": sha})
    monkeypatch.setattr(cust, "_product_lock_snapshot", lambda p: ({"identity_lock": "x"}, "fp"))
    monkeypatch.setattr(cust, "exact_product_required", lambda p: False)
    receipt = cust.build_product_visual_custody_receipt(
        {"id": "p-1"}, asset, mode="F2V", source_mode="HYBRID",
        prepared_reference=prepared,
    )
    gc = receipt["geometry_contract"]
    assert gc is not None and gc["geometry_lock_enabled"] is True
    assert gc["product_bbox_px"] == {"x": 300, "y": 250, "w": 400, "h": 600}
    assert receipt["geometry_contract_digest"] == prepared["geometry_contract_digest"]
    assert receipt["prepared_reference_sha256"] == sha
    assert receipt["product_rescaled"] is False
    # The fully-bound receipt must be traceable to the official visual.
    bound = cust.bind_provider_reference_transport(
        receipt, provider_reference_media_ids=["m1"],
        official_provider_media_id="m1", uploaded_local_sha256=sha,
    )
    cust.assert_official_provider_reference_traceable(bound)  # no raise


# ── J: provider-boundary SHA matches the governed prepared reference ──

def test_J_provider_boundary_sha_matches_prepared(tmp_path):
    receipt = {
        "product_id": "p-1",
        "official_visual_sha256": "a" * 64,
        "prepared_reference_sha256": "a" * 64,
        "geometry_contract": {"geometry_lock_enabled": True},
        "official_provider_reference_media_id": "ca_official_1",
        "product_rescaled": False,
        "pixel_fidelity_verified": True,
    }
    # Matching uploaded SHA binds and records the uploaded reference sha.
    bound = cust.bind_provider_reference_transport(
        dict(receipt), provider_reference_media_ids=["prov-1"],
        official_provider_media_id="prov-1", uploaded_local_sha256="a" * 64,
    )
    assert bound["uploaded_reference_sha256"] == "a" * 64
    cust.assert_official_provider_reference_traceable(bound)
    # A drifted upload fails closed.
    with pytest.raises(cust.ProductVisualCustodyError) as exc:
        cust.bind_provider_reference_transport(
            dict(receipt), provider_reference_media_ids=["prov-1"],
            official_provider_media_id="prov-1", uploaded_local_sha256="b" * 64,
        )
    assert exc.value.code == cust.ERR_PROVIDER_REFERENCE_SHA_DRIFT


def test_J_untraceable_receipt_fails_closed():
    # Missing prepared_reference_sha256 -> not traceable.
    with pytest.raises(cust.ProductVisualCustodyError) as exc:
        cust.assert_official_provider_reference_traceable(
            {"official_visual_sha256": "a" * 64, "geometry_contract": {"x": 1},
             "official_provider_reference_media_id": "m"}
        )
    assert exc.value.code == cust.ERR_PROVIDER_REFERENCE_NOT_TRACEABLE


# ── generic-bottle classification (owner rule 6) ──

def test_generic_bottle_output_is_classified_not_certified():
    verdict = cust.classify_product_fidelity_failure(
        {"status": "REVIEW_REQUIRED", "generic_bottle": True,
         "dimensions": {"label_field_layout": False, "identity": False}}
    )
    assert verdict["is_product_fidelity_failure"] is True
    assert verdict["certifiable"] is False
    assert verdict["retry_safe"] is False
    assert "GENERIC_BOTTLE_SUBSTITUTED" in verdict["reasons"]


def test_unproven_fidelity_is_a_failure():
    # No structured pass evidence -> never inferred as a pass.
    verdict = cust.classify_product_fidelity_failure({"status": "PENDING", "dimensions": {}})
    assert verdict["is_product_fidelity_failure"] is True
    assert verdict["certifiable"] is False
