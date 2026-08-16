from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from agent.db import crud
from agent.services import product_visual_grounding_resolver as resolver
from agent.services import product_visual_onboarding_service as service


PRODUCT_ID = "mwcb-reauthorization-test"
OLD_SHA = "1" * 64


def _write_image(path: Path, *, color: tuple[int, int, int]) -> str:
    Image.new("RGB", (96, 128), color).save(path, format="JPEG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _seed_lock(tmp_path: Path, *, review_status: str = "REJECTED", active_selection: str = "SAME_PRODUCT_TRUSTED_SOURCE"):
    global PRODUCT_ID
    PRODUCT_ID = f"mwcb-reauthorization-{uuid.uuid4().hex}"
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            """
            INSERT INTO product (
                id, source, raw_product_title, product_display_name,
                product_short_name, image_asset_status, asset_status,
                local_image_path
            ) VALUES (?, 'MANUAL', ?, ?, ?, 'DOWNLOADED', 'DOWNLOADED', ?)
            """,
            (
                PRODUCT_ID,
                "MWCB reauthorization test",
                "Minyak Warisan Cap Burung 25ml",
                "MWCB",
                str(tmp_path / "old-missing.jpg"),
            ),
        )
        await db.commit()
    product = await crud.get_product(PRODUCT_ID)
    cutout = tmp_path / "existing-cutout.png"
    Image.new("RGBA", (1000, 1000), (0, 0, 0, 0)).save(cutout)
    await crud.upsert_product_truth_lock(
        PRODUCT_ID,
        canonical_media_id="old-media",
        canonical_sha256=OLD_SHA,
        source_width=960,
        source_height=1280,
        canonical_source_path="data/exact-product/legacy-missing.jpg",
        canonical_cutout_media_id="existing-cutout-media",
        canonical_cutout_sha256=hashlib.sha256(cutout.read_bytes()).hexdigest(),
        canonical_cutout_path=str(cutout),
        alpha_mask_json=json.dumps({"source": "cutout_alpha", "sha256": "a" * 64, "width": 1000, "height": 1000}),
        anchor_point_json=json.dumps({"x": 0.5, "y": 0.5}),
        min_scale=0.5,
        max_scale=2.0,
        allowed_bbox_json=json.dumps({"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}),
        allowed_rotation=0.0,
        allowed_perspective=0.0,
        identity_lock=1 if review_status == "APPROVED" else 0,
        geometry_lock=1 if review_status == "APPROVED" else 0,
        label_lock=1 if review_status == "APPROVED" else 0,
        logo_lock=1 if review_status == "APPROVED" else 0,
        colour_lock=1 if review_status == "APPROVED" else 0,
        scale_lock=1 if review_status == "APPROVED" else 0,
        review_status=review_status,
        failure_state="" if review_status == "APPROVED" else "FALLBACK_SELECTED",
        provenance_json=json.dumps({
            "source_kind": "USER_UPLOAD",
            "active_selection": active_selection,
            "review_status": review_status,
        }),
        schema_version="1.0",
    )
    return product, cutout


def _reference(path: Path, sha: str, *, media_id: str = "replacement-media") -> SimpleNamespace:
    return SimpleNamespace(
        source_type="SCHEMA_CANONICAL_SOURCE",
        media_id=media_id,
        local_path=str(path),
        image_url=None,
        mime_type="image/jpeg",
        sha256=sha,
        width=96,
        height=128,
        provenance="UNIVERSAL_PRODUCT_SCHEMA",
        validation_status="VALIDATED",
    )


def _ready_payload() -> dict:
    return {
        "current_system_visual": {"card": "ORIGINAL_SOURCE"},
        "active_visual_source": "SAME_PRODUCT_TRUSTED_SOURCE",
        "cutout_review_status": "REJECTED",
        "cutout_history_count": 1,
        "provider_operations": 0,
    }


@pytest.mark.asyncio
async def test_stale_original_requires_explicit_reauthorization(tmp_path, monkeypatch):
    await _seed_lock(tmp_path)
    monkeypatch.setattr(service, "BASE_DIR", tmp_path)

    with pytest.raises(service.ProductVisualOnboardingError) as raised:
        await service.save_product_visual_setup(
            PRODUCT_ID,
            selected_visual="ORIGINAL",
            reviewed_by="Faris",
            review_note="Use the current original.",
        )

    assert raised.value.code == "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_REQUIRED"


@pytest.mark.asyncio
async def test_explicit_reauthorization_updates_only_original_authority_and_preserves_history(tmp_path, monkeypatch):
    product, cutout = await _seed_lock(tmp_path)
    replacement = tmp_path / "governed-mwcb.jpg"
    replacement_sha = _write_image(replacement, color=(20, 120, 80))
    await crud.update_product(PRODUCT_ID, local_image_path=str(replacement))
    monkeypatch.setattr(service, "BASE_DIR", tmp_path)
    monkeypatch.setattr(service, "resolve_governed_original_product_source", lambda _product: _reference(replacement, replacement_sha))
    async def readiness(_product_id):
        return _ready_payload()
    monkeypatch.setattr(service, "get_product_visual_readiness", readiness)

    history = await crud.create_product_truth_lock_history(
        PRODUCT_ID,
        history_id="preserved-history",
        source_kind="USER_UPLOAD",
        review_status="REJECTED",
        canonical_media_id="old-media",
        canonical_sha256=OLD_SHA,
        source_width=960,
        source_height=1280,
        canonical_source_path="history/old-source.jpg",
        canonical_cutout_media_id="existing-cutout-media",
        canonical_cutout_sha256=hashlib.sha256(cutout.read_bytes()).hexdigest(),
        canonical_cutout_path=str(cutout),
        alpha_mask_json="{}",
        anchor_point_json="{}",
        allowed_bbox_json="{}",
        provenance_json=json.dumps({"active_selection": "SAME_PRODUCT_TRUSTED_SOURCE"}),
        superseded_by_media_id=None,
        superseded_reason=None,
    )
    assert history["history_id"] == "preserved-history"

    result = await service.reauthorize_product_original_source(
        PRODUCT_ID,
        reviewed_by="Faris",
        review_note="Owner-authorized replacement after visual identity verification.",
        confirm_identity=True,
        confirm_label_logo=True,
        confirm_geometry_scale=True,
        confirm_product_isolation=True,
        expected_previous_canonical_sha256=OLD_SHA,
        expected_replacement_sha256=replacement_sha,
    )

    lock = await crud.get_product_truth_lock(PRODUCT_ID)
    assert lock["canonical_media_id"] == "replacement-media"
    assert lock["canonical_sha256"] == replacement_sha
    assert lock["canonical_source_path"] == str(replacement)
    assert lock["review_status"] == "REJECTED"
    assert lock["failure_state"] == "FALLBACK_SELECTED"
    assert lock["canonical_cutout_media_id"] == "existing-cutout-media"
    assert json.loads(lock["provenance_json"])["previous_canonical_sha256"] == OLD_SHA
    assert json.loads(lock["provenance_json"])["replacement_canonical_sha256"] == replacement_sha
    assert json.loads(lock["provenance_json"])["active_selection"] == "SAME_PRODUCT_TRUSTED_SOURCE"
    assert len(await crud.list_product_truth_lock_history(PRODUCT_ID)) == 1
    assert result["provider_operations"] == 0
    assert (await crud.get_product(PRODUCT_ID))["id"] == product["id"]


@pytest.mark.asyncio
async def test_wrong_previous_sha_fails_cas_without_resolving_or_writing(tmp_path, monkeypatch):
    await _seed_lock(tmp_path)
    resolver_called = False

    def resolve(_product):
        nonlocal resolver_called
        resolver_called = True
        raise AssertionError("CAS must fail before source resolution")

    monkeypatch.setattr(service, "resolve_governed_original_product_source", resolve)
    with pytest.raises(service.ProductVisualOnboardingError) as raised:
        await service.reauthorize_product_original_source(
            PRODUCT_ID,
            reviewed_by="Faris",
            review_note="CAS test",
            confirm_identity=True,
            confirm_label_logo=True,
            confirm_geometry_scale=True,
            confirm_product_isolation=True,
            expected_previous_canonical_sha256="2" * 64,
            expected_replacement_sha256="3" * 64,
        )
    assert raised.value.code == "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_STALE"
    assert resolver_called is False
    assert (await crud.get_product_truth_lock(PRODUCT_ID))["canonical_sha256"] == OLD_SHA


@pytest.mark.asyncio
async def test_wrong_replacement_sha_fails_cas_and_keeps_lock(tmp_path, monkeypatch):
    await _seed_lock(tmp_path)
    replacement = tmp_path / "governed-mwcb.jpg"
    replacement_sha = _write_image(replacement, color=(20, 120, 80))
    monkeypatch.setattr(service, "BASE_DIR", tmp_path)
    monkeypatch.setattr(service, "resolve_governed_original_product_source", lambda _product: _reference(replacement, replacement_sha))

    with pytest.raises(service.ProductVisualOnboardingError) as raised:
        await service.reauthorize_product_original_source(
            PRODUCT_ID,
            reviewed_by="Faris",
            review_note="Wrong replacement SHA test",
            confirm_identity=True,
            confirm_label_logo=True,
            confirm_geometry_scale=True,
            confirm_product_isolation=True,
            expected_previous_canonical_sha256=OLD_SHA,
            expected_replacement_sha256="4" * 64,
        )
    assert raised.value.code == "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_STALE"
    assert (await crud.get_product_truth_lock(PRODUCT_ID))["canonical_sha256"] == OLD_SHA


@pytest.mark.asyncio
async def test_replacement_outside_base_dir_and_wrong_product_media_fail_closed(tmp_path, monkeypatch):
    await _seed_lock(tmp_path)
    outside = tmp_path.parent / "outside-product.jpg"
    outside_sha = _write_image(outside, color=(90, 10, 10))
    monkeypatch.setattr(service, "BASE_DIR", tmp_path / "governed")
    monkeypatch.setattr(service, "resolve_governed_original_product_source", lambda _product: _reference(outside, outside_sha))

    with pytest.raises(service.ProductVisualOnboardingError) as outside_error:
        await service.reauthorize_product_original_source(
            PRODUCT_ID,
            reviewed_by="Faris",
            review_note="Outside path test",
            confirm_identity=True,
            confirm_label_logo=True,
            confirm_geometry_scale=True,
            confirm_product_isolation=True,
            expected_previous_canonical_sha256=OLD_SHA,
            expected_replacement_sha256=outside_sha,
        )
    assert outside_error.value.code == "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID"

    governed = tmp_path / "governed.jpg"
    governed_sha = _write_image(governed, color=(10, 10, 90))
    monkeypatch.setattr(service, "BASE_DIR", tmp_path)
    monkeypatch.setattr(service, "resolve_governed_original_product_source", lambda _product: _reference(governed, governed_sha, media_id="wrong-product-media"))
    monkeypatch.setattr(
        service.crud,
        "get_product_source_media",
        AsyncMock(return_value=None),
    )
    # A server-resolved path must still be tied to the exact product's
    # governed candidates; an unbound path is not accepted as authority.
    with pytest.raises(service.ProductVisualOnboardingError) as wrong_product_error:
        await service.reauthorize_product_original_source(
            PRODUCT_ID,
            reviewed_by="Faris",
            review_note="Wrong product test",
            confirm_identity=True,
            confirm_label_logo=True,
            confirm_geometry_scale=True,
            confirm_product_isolation=True,
            expected_previous_canonical_sha256=OLD_SHA,
            expected_replacement_sha256=governed_sha,
        )
    # The media id cannot be proved as belonging to this product, so the
    # resolver's product binding remains the fail-closed authority.
    assert wrong_product_error.value.code in {
        "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_PRODUCT_MISMATCH",
        "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
    }


@pytest.mark.asyncio
async def test_all_human_confirmations_and_reviewer_note_are_required(tmp_path):
    await _seed_lock(tmp_path)
    cases = [
        {"reviewed_by": "", "review_note": "note", "confirm_identity": True, "confirm_label_logo": True, "confirm_geometry_scale": True, "confirm_product_isolation": True},
        {"reviewed_by": "Faris", "review_note": "", "confirm_identity": True, "confirm_label_logo": True, "confirm_geometry_scale": True, "confirm_product_isolation": True},
        {"reviewed_by": "Faris", "review_note": "note", "confirm_identity": False, "confirm_label_logo": True, "confirm_geometry_scale": True, "confirm_product_isolation": True},
        {"reviewed_by": "Faris", "review_note": "note", "confirm_identity": True, "confirm_label_logo": False, "confirm_geometry_scale": True, "confirm_product_isolation": True},
        {"reviewed_by": "Faris", "review_note": "note", "confirm_identity": True, "confirm_label_logo": True, "confirm_geometry_scale": False, "confirm_product_isolation": True},
        {"reviewed_by": "Faris", "review_note": "note", "confirm_identity": True, "confirm_label_logo": True, "confirm_geometry_scale": True, "confirm_product_isolation": False},
    ]
    for case in cases:
        with pytest.raises(service.ProductVisualOnboardingError) as raised:
            await service.reauthorize_product_original_source(
                PRODUCT_ID,
                **case,
                expected_previous_canonical_sha256=OLD_SHA,
                expected_replacement_sha256="5" * 64,
            )
        assert raised.value.code in {"HUMAN_REVIEW_NOTE_REQUIRED", "HUMAN_REVIEW_CONFIRMATION_REQUIRED"}


def test_official_resolver_keeps_original_source_strict_after_reauthorization(tmp_path, monkeypatch):
    source = tmp_path / "reauthorized-source.jpg"
    source_sha = _write_image(source, color=(20, 120, 80))
    lock = SimpleNamespace(
        review_status="REJECTED",
        provenance={"active_selection": "SAME_PRODUCT_TRUSTED_SOURCE"},
        canonical_source_path=str(source),
        canonical_sha256=source_sha,
        canonical_media_id="replacement-media",
    )
    monkeypatch.setattr(resolver.truth_lock_service, "load_product_truth_lock", lambda _product_id: lock)
    resolved = resolver.resolve_official_product_reference_image({"id": PRODUCT_ID})
    assert resolved.source_type == "PRODUCT_TRUTH_LOCK_SOURCE"
    assert resolved.sha256 == source_sha


def test_governed_reauthorization_never_bypasses_invalid_approved_cutout(monkeypatch):
    lock = SimpleNamespace(
        review_status="APPROVED",
        provenance={"active_selection": "APPROVED_CANONICAL_CUTOUT"},
    )
    monkeypatch.setattr(resolver.truth_lock_service, "load_product_truth_lock", lambda _product_id: lock)
    monkeypatch.setattr(
        resolver.truth_lock_service,
        "resolve_approved_product_truth_lock",
        lambda _product_id: (_ for _ in ()).throw(
            resolver.truth_lock_service.ProductTruthLockError(
                "CANONICAL_CUTOUT_INVALID",
                "Approved cutout bytes are missing.",
            )
        ),
    )

    with pytest.raises(resolver.ProductVisualReferenceRequiredError) as raised:
        resolver.resolve_governed_original_product_source({"id": "approved-cutout-product"})
    assert "OFFICIAL_PRODUCT_VISUAL_INVALID" in str(raised.value)


@pytest.mark.asyncio
async def test_active_approved_cutout_missing_bytes_is_not_bypassed(tmp_path, monkeypatch):
    await _seed_lock(tmp_path, review_status="APPROVED", active_selection="APPROVED_CANONICAL_CUTOUT")
    monkeypatch.setattr(
        service,
        "resolve_governed_original_product_source",
        lambda _product: (_ for _ in ()).throw(
            resolver.ProductVisualReferenceRequiredError(
                "OFFICIAL_PRODUCT_VISUAL_INVALID: Approved Product Truth cutout bytes are missing or changed."
            )
        ),
    )
    with pytest.raises(service.ProductVisualOnboardingError) as raised:
        await service.reauthorize_product_original_source(
            PRODUCT_ID,
            reviewed_by="Faris",
            review_note="Approved cutout safety test",
            confirm_identity=True,
            confirm_label_logo=True,
            confirm_geometry_scale=True,
            confirm_product_isolation=True,
            expected_previous_canonical_sha256=OLD_SHA,
            expected_replacement_sha256="6" * 64,
        )
    assert raised.value.code == "OFFICIAL_PRODUCT_VISUAL_INVALID"
