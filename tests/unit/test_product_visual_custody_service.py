import hashlib
from pathlib import Path

import pytest

from agent.services import product_visual_custody_service as custody


PRODUCT_ID = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"


def _product() -> dict:
    return {
        "id": PRODUCT_ID,
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
        "raw_product_title": "Minyak Warisan Cap Burung 25ml",
        "product_type": "TRADITIONAL_HERBAL_OIL",
    }


def _official_asset(path: Path) -> dict:
    return {
        "asset_id": "e7d8b1ae-f050-4c65-a0db-52817d88ec0d",
        "product_id": PRODUCT_ID,
        "asset_source": "PRODUCT_VISUAL_OFFICIAL_CUTOUT",
        "official_visual": True,
        "official_visual_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "local_file_path": str(path),
    }


def _lock_snapshot(monkeypatch):
    monkeypatch.setattr(
        custody,
        "_truth_lock_snapshot",
        lambda _product_id: {
            "status": "PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE",
            "review_status": "APPROVED",
            "lock_present": True,
            "lock_valid": True,
            "schema_version": "PRODUCT_TRUTH_LOCK_V1",
            "canonical_media_id": "ca-source",
            "canonical_sha256": "b" * 64,
            "canonical_cutout_media_id": "e7d8",
            "canonical_cutout_sha256": "a" * 64,
            "failure_state": "",
        },
    )


def test_mwcb_schema_policy_is_exact_even_when_lane_is_hybrid():
    assert custody.exact_product_required(_product()) is True


def test_official_reference_hash_mismatch_fails_closed():
    path = Path(__file__)
    asset = _official_asset(path)
    asset["official_visual_sha256"] = "0" * 64

    with pytest.raises(custody.ProductVisualCustodyError) as exc:
        custody.validate_official_reference_asset(_product(), asset)

    assert exc.value.code == custody.ERR_OFFICIAL_PRODUCT_VISUAL_HASH_MISMATCH


def test_receipt_contains_authority_prompt_locks_and_exact_policy(monkeypatch):
    _lock_snapshot(monkeypatch)
    path = Path(__file__)
    prompt = " ".join(
        [
            "PRODUCT IDENTITY LOCK",
            "PRODUCT GEOMETRY LOCK",
            "PRODUCT SCALE LOCK",
            "PRODUCT REFERENCE LOCK",
            "FRAME PERSISTENCE LOCK",
            "PRODUCT NO-MODIFICATION LOCK",
        ]
    )

    receipt = custody.build_product_visual_custody_receipt(
        _product(),
        _official_asset(path),
        mode="F2V",
        source_mode="HYBRID",
        prompt=prompt,
        provider_route="API_FIRST_GENERATIVE_REFERENCE",
        generation_type="reference_frame_2_video",
    )

    assert receipt["official_visual_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["canonical_source_sha256"] == "b" * 64
    assert receipt["fidelity_policy"] == custody.EXACT_PRODUCT_REQUIRED
    assert receipt["exact_product_required"] is True
    assert receipt["product_fidelity_qc_required"] is True
    assert receipt["prompt_lock"]["all_required_markers_present"] is True
    assert len(receipt["product_lock_fingerprint"]) == 64
    assert len(receipt["receipt_sha256"]) == 64


def test_exact_product_generative_route_blocks_before_dispatch():
    receipt = {
        "exact_product_required": True,
        "fidelity_policy": custody.EXACT_PRODUCT_REQUIRED,
    }

    with pytest.raises(custody.ProductVisualCustodyError) as exc:
        custody.validate_pre_dispatch_route(
            receipt,
            provider_route="DIRECT_API",
            generation_type="reference_frame_2_video",
        )

    assert exc.value.code == custody.ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN


def test_prompt_and_reference_id_never_prove_video_fidelity():
    receipt = {
        "exact_product_required": True,
        "product_fidelity_qc_required": True,
    }
    qc = custody.evaluate_product_fidelity_qc(
        receipt,
        evidence={"prompt_lock_present": True, "provider_reference_media_id": "m1"},
        artifact_available=True,
    )

    assert qc["status"] == custody.PRODUCT_FIDELITY_REVIEW_REQUIRED
    assert custody.exact_output_ready(receipt, qc) is False


def test_structured_verified_qc_is_the_only_exact_ready_path():
    receipt = {
        "exact_product_required": True,
        "product_fidelity_qc_required": True,
    }
    qc = custody.evaluate_product_fidelity_qc(
        receipt,
        evidence={
            "status": "PASS",
            "verified": True,
            "dimensions": {
                key: "PASS" for key in custody.PRODUCT_FIDELITY_QC_DIMENSIONS
            },
        },
        artifact_available=True,
    )

    assert qc["status"] == custody.PRODUCT_FIDELITY_QC_PASS
    assert custody.exact_output_ready(receipt, qc) is True


def test_incomplete_verified_dimensions_cannot_mark_exact_ready():
    receipt = {
        "exact_product_required": True,
        "product_fidelity_qc_required": True,
    }
    qc = custody.evaluate_product_fidelity_qc(
        receipt,
        evidence={
            "status": "PASS",
            "verified": True,
            "dimensions": {"identity": "PASS"},
        },
        artifact_available=True,
    )

    assert qc["status"] == custody.PRODUCT_FIDELITY_REVIEW_REQUIRED
    assert custody.exact_output_ready(receipt, qc) is False
