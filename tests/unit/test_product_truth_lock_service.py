from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from agent.models.product_truth_lock import (
    ProductTruthLockApprovalRequest,
    ProductTruthLockOnboardingRequest,
)
from agent.services import product_truth_lock_service as lock_service


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assets(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "canonical.png"
    cutout = tmp_path / "cutout.png"
    Image.new("RGB", (20, 40), (20, 80, 120)).save(source)
    layer = Image.new("RGBA", (20, 40), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle((4, 2, 15, 36), fill=(10, 120, 60, 255))
    layer.save(cutout)
    alpha_sha = hashlib.sha256(layer.getchannel("A").tobytes()).hexdigest()
    return {
        "source": source,
        "cutout": cutout,
        "source_sha": _sha(source),
        "cutout_sha": _sha(cutout),
        "alpha_sha": alpha_sha,
    }


def _db(tmp_path: Path, assets: dict[str, object], *, status: str = "APPROVED") -> Path:
    db_path = tmp_path / "truth-lock.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE product_visual_truth_lock (
            product_id TEXT PRIMARY KEY,
            canonical_media_id TEXT NOT NULL,
            canonical_sha256 TEXT NOT NULL,
            source_width INTEGER NOT NULL,
            source_height INTEGER NOT NULL,
            canonical_source_path TEXT NOT NULL,
            canonical_cutout_media_id TEXT NOT NULL,
            canonical_cutout_sha256 TEXT NOT NULL,
            canonical_cutout_path TEXT NOT NULL,
            alpha_mask_json TEXT NOT NULL,
            anchor_point_json TEXT NOT NULL,
            min_scale REAL NOT NULL,
            max_scale REAL NOT NULL,
            allowed_bbox_json TEXT NOT NULL,
            allowed_rotation REAL NOT NULL,
            allowed_perspective REAL NOT NULL,
            identity_lock INTEGER NOT NULL,
            geometry_lock INTEGER NOT NULL,
            label_lock INTEGER NOT NULL,
            logo_lock INTEGER NOT NULL,
            colour_lock INTEGER NOT NULL,
            scale_lock INTEGER NOT NULL,
            review_status TEXT NOT NULL,
            failure_state TEXT,
            provenance_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        )
        """
    )
    source = assets["source"]
    cutout = assets["cutout"]
    row = (
        "p-1",
        "media-canonical",
        assets["source_sha"],
        20,
        40,
        str(source),
        "media-cutout",
        assets["cutout_sha"],
        str(cutout),
        json.dumps({"source": "cutout_alpha", "sha256": assets["alpha_sha"], "width": 20, "height": 40}),
        json.dumps({"x": 0.5, "y": 0.5}),
        0.5,
        1.5,
        json.dumps({"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}),
        0.0,
        0.0,
        1,
        1,
        1,
        1,
        1,
        1,
        status,
        "" if status == "APPROVED" else "operator_review_required",
        json.dumps({"source": "test-onboarding", "operator": "test"}),
        "1.0",
    )
    conn.execute(
        "INSERT INTO product_visual_truth_lock VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        row,
    )
    conn.commit()
    conn.close()
    return db_path


def test_approved_lock_resolves_and_verifies_all_bytes(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    monkeypatch.setattr(lock_service, "DB_PATH", _db(tmp_path, assets))

    resolved = lock_service.resolve_approved_product_truth_lock("p-1")

    assert resolved.product_id == "p-1"
    assert resolved.canonical_sha256 == assets["source_sha"]
    assert resolved.canonical_cutout_sha256 == assets["cutout_sha"]
    assert resolved.alpha_mask_sha256 == assets["alpha_sha"]
    assert resolved.review_status == "APPROVED"


def test_missing_lock_is_a_hard_requirement_for_exact_output(tmp_path, monkeypatch):
    monkeypatch.setattr(lock_service, "DB_PATH", tmp_path / "missing.sqlite3")

    status = lock_service.inspect_product_truth_lock("missing")

    assert status["product_truth_status"] == "PRODUCT_TRUTH_LOCK_REQUIRED"
    assert status["lock_present"] is False
    assert status["exact_allowed"] is False


def test_pending_lock_is_review_only(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    monkeypatch.setattr(lock_service, "DB_PATH", _db(tmp_path, assets, status="PENDING_REVIEW"))

    status = lock_service.inspect_product_truth_lock("p-1")

    assert status["product_truth_status"] == "HUMAN_REVIEW_REQUIRED"
    assert status["exact_allowed"] is False


def test_stale_canonical_source_fails_closed(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    db_path = _db(tmp_path, assets)
    monkeypatch.setattr(lock_service, "DB_PATH", db_path)
    Path(assets["source"]).write_bytes(b"stale-canonical")

    status = lock_service.inspect_product_truth_lock("p-1")

    assert status["product_truth_status"] == "CANONICAL_PRODUCT_SOURCE_INVALID"
    assert status["exact_allowed"] is False
    assert status["failure_state"] == "CANONICAL_PRODUCT_SOURCE_INVALID"


def test_fully_transparent_canonical_source_fails_closed(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    db_path = _db(tmp_path, assets)
    source = assets["source"]
    Image.new("RGBA", (20, 40), (0, 0, 0, 0)).save(source)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE product_visual_truth_lock SET canonical_sha256 = ? WHERE product_id = ?",
            (_sha(source), "p-1"),
        )
        conn.commit()
    monkeypatch.setattr(lock_service, "DB_PATH", db_path)

    status = lock_service.inspect_product_truth_lock("p-1")

    assert status["product_truth_status"] == "CANONICAL_PRODUCT_SOURCE_INVALID"
    assert status["exact_allowed"] is False


@pytest.mark.asyncio
async def test_onboarding_persists_server_owned_pending_lock_from_reviewed_cutout(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    source = assets["source"]
    cutout = assets["cutout"]
    captured: dict[str, object] = {}

    async def get_product(product_id: str):
        return {"id": product_id, "product_display_name": "Test product"}

    async def get_cutout_media(media_id: str):
        return {
            "media_id": media_id,
            "kind": "image",
            "status": "STORED",
            "local_path": str(cutout),
            "filename": "reviewed-cutout.png",
        }

    async def upsert(product_id: str, **kwargs):
        captured.update(kwargs)
        captured["product_id"] = product_id
        return {"product_id": product_id, **kwargs}

    async def no_existing_lock(_product_id: str):
        return None

    from agent.services import product_visual_grounding_resolver as resolver

    monkeypatch.setattr(lock_service.crud, "get_product", get_product)
    monkeypatch.setattr(lock_service.crud, "get_product_source_media", get_cutout_media)
    monkeypatch.setattr(lock_service.crud, "get_product_truth_lock", no_existing_lock)
    monkeypatch.setattr(lock_service.crud, "upsert_product_truth_lock", upsert)
    monkeypatch.setattr(
        resolver,
        "resolve_product_reference_image",
        lambda _product: SimpleNamespace(
            media_id="canonical-media",
            local_path=str(source),
            sha256=assets["source_sha"],
            width=20,
            height=40,
            mime_type="image/png",
            source_type="PRODUCT_ROW_MEDIA_ID",
            image_url=None,
            provenance="test",
            validation_status="VALIDATED",
        ),
    )
    monkeypatch.setattr(lock_service, "BASE_DIR", tmp_path)

    request = ProductTruthLockOnboardingRequest(
        canonical_cutout_media_id="reviewed-cutout",
        anchor_point={"x": 0.5, "y": 0.5},
        min_scale=0.5,
        max_scale=1.0,
        allowed_bbox={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
        created_by="operator-1",
        onboarding_note="Human reviewed transparent cutout",
    )

    result = await lock_service.create_pending_product_truth_lock("p-1", request)

    assert result["review_status"] == "PENDING_REVIEW"
    assert result["exact_allowed"] is False
    assert captured["product_id"] == "p-1"
    assert captured["canonical_media_id"] == "canonical-media"
    assert captured["canonical_cutout_media_id"] == "reviewed-cutout"
    assert captured["identity_lock"] == 0
    assert captured["review_status"] == "PENDING_REVIEW"
    assert captured["failure_state"] == "HUMAN_REVIEW_REQUIRED"
    assert json.loads(str(captured["alpha_mask_json"]))["source"] == "cutout_alpha"
    assert (tmp_path / str(captured["canonical_source_path"])).exists()
    assert (tmp_path / str(captured["canonical_cutout_path"])).exists()


@pytest.mark.asyncio
async def test_approval_requires_explicit_human_acknowledgement(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    db_path = _db(tmp_path, assets, status="PENDING_REVIEW")
    monkeypatch.setattr(lock_service, "DB_PATH", db_path)
    captured: dict[str, object] = {}

    async def upsert(product_id: str, **kwargs):
        captured.update(kwargs)
        captured["product_id"] = product_id
        return {"product_id": product_id, **kwargs}

    monkeypatch.setattr(lock_service.crud, "upsert_product_truth_lock", upsert)

    request = ProductTruthLockApprovalRequest(
        reviewed_by="human-reviewer",
        review_note="Identity, label, logo and scale checked against canonical source.",
        confirm_identity=True,
        confirm_label_logo=True,
        confirm_geometry_scale=True,
    )

    result = await lock_service.approve_product_truth_lock("p-1", request)

    assert result["review_status"] == "APPROVED"
    assert result["exact_allowed"] is True
    assert captured["review_status"] == "APPROVED"
    assert captured["identity_lock"] == 1
    assert captured["label_lock"] == 1
    assert captured["logo_lock"] == 1
    assert captured["geometry_lock"] == 1
    assert captured["scale_lock"] == 1
    assert captured["failure_state"] == ""
    provenance = json.loads(str(captured["provenance_json"]))
    assert provenance["reviewed_by"] == "human-reviewer"


@pytest.mark.asyncio
async def test_approval_rejects_missing_human_acknowledgement(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    db_path = _db(tmp_path, assets, status="PENDING_REVIEW")
    monkeypatch.setattr(lock_service, "DB_PATH", db_path)

    with pytest.raises(lock_service.ProductTruthLockError) as exc:
        await lock_service.approve_product_truth_lock(
            "p-1",
            ProductTruthLockApprovalRequest(
                reviewed_by="human-reviewer",
                review_note="Not enough evidence",
                confirm_identity=True,
                confirm_label_logo=False,
                confirm_geometry_scale=True,
            ),
        )

    assert exc.value.code == "HUMAN_REVIEW_CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_onboarding_rejects_canonical_source_hash_drift(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    source = assets["source"]
    cutout = assets["cutout"]

    async def get_product(_product_id: str):
        return {"id": "p-1", "product_display_name": "Test product"}

    async def get_cutout_media(_media_id: str):
        return {"media_id": "cutout-1", "kind": "image", "status": "STORED", "local_path": str(cutout)}

    async def no_existing_lock(_product_id: str):
        return None

    async def unexpected_upsert(*_args, **_kwargs):
        raise AssertionError("source hash drift must block before persistence")

    from agent.services import product_visual_grounding_resolver as resolver

    monkeypatch.setattr(lock_service.crud, "get_product", get_product)
    monkeypatch.setattr(lock_service.crud, "get_product_source_media", get_cutout_media)
    monkeypatch.setattr(lock_service.crud, "get_product_truth_lock", no_existing_lock)
    monkeypatch.setattr(lock_service.crud, "upsert_product_truth_lock", unexpected_upsert)
    monkeypatch.setattr(
        resolver,
        "resolve_product_reference_image",
        lambda _product: SimpleNamespace(
            media_id="canonical-media",
            local_path=str(source),
            sha256="f" * 64,
            width=20,
            height=40,
            mime_type="image/png",
            source_type="PRODUCT_ROW_MEDIA_ID",
            image_url=None,
            provenance="test",
            validation_status="VALIDATED",
        ),
    )
    monkeypatch.setattr(lock_service, "BASE_DIR", tmp_path)

    request = ProductTruthLockOnboardingRequest(
        canonical_cutout_media_id="cutout-1",
        anchor_point={"x": 0.5, "y": 0.5},
        min_scale=0.5,
        max_scale=1.0,
        allowed_bbox={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
        created_by="operator-1",
    )

    with pytest.raises(lock_service.ProductTruthLockError) as exc:
        await lock_service.create_pending_product_truth_lock("p-1", request)

    assert exc.value.code == "CANONICAL_PRODUCT_SOURCE_INVALID"
