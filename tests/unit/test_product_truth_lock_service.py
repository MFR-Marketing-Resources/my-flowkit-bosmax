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


def _standard_cutout(tmp_path: Path) -> Path:
    cutout = tmp_path / "standard-cutout.png"
    layer = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle((200, 120, 799, 879), fill=(10, 120, 60, 255))
    layer.save(cutout)
    layer.close()
    return cutout


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
    db_path = _db(tmp_path, assets, status="PENDING_REVIEW")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE product_visual_truth_lock
            SET identity_lock = 0, geometry_lock = 0, label_lock = 0,
                logo_lock = 0, colour_lock = 0, scale_lock = 0
            WHERE product_id = ?
            """,
            ("p-1",),
        )
        conn.commit()
    monkeypatch.setattr(lock_service, "DB_PATH", db_path)

    status = lock_service.inspect_product_truth_lock("p-1")

    assert status["product_truth_status"] == "HUMAN_REVIEW_REQUIRED"
    assert status["failure_state"] == "HUMAN_REVIEW_REQUIRED"
    assert status["canonical_cutout_media_id"] == "media-cutout"
    assert status["canonical_cutout_sha256"] == assets["cutout_sha"]
    assert status["exact_allowed"] is False


def test_pending_cutout_preview_is_server_owned(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    monkeypatch.setattr(lock_service, "DB_PATH", _db(tmp_path, assets, status="PENDING_REVIEW"))
    monkeypatch.setattr(lock_service, "BASE_DIR", tmp_path)

    preview = lock_service.resolve_product_truth_cutout_preview("p-1")

    assert preview == Path(assets["cutout"]).resolve()
    assert preview.read_bytes() == Path(assets["cutout"]).read_bytes()


def test_manual_cutout_png_alpha_and_upload_boundaries(tmp_path):
    assets = _assets(tmp_path)
    raw = Path(assets["cutout"]).read_bytes()

    width, height, _alpha_sha, bbox = lock_service._uploaded_cutout_details(raw, expected_dimensions=(20, 40))
    assert (width, height) == (20, 40)
    assert bbox == (4, 2, 16, 37)
    assert lock_service._safe_upload_filename(r"..\..\operator\manual.png") == "manual.png"

    jpeg = tmp_path / "cutout.jpg"
    Image.new("RGB", (20, 40), (10, 20, 30)).save(jpeg, format="JPEG")
    with pytest.raises(lock_service.ProductTruthLockError) as jpeg_error:
        lock_service._uploaded_cutout_details(jpeg.read_bytes())
    assert jpeg_error.value.code == "CANONICAL_CUTOUT_MIME_INVALID"

    with pytest.raises(lock_service.ProductTruthLockError) as fake_error:
        lock_service._uploaded_cutout_details(b"not-a-png")
    assert fake_error.value.code == "CANONICAL_CUTOUT_INVALID"

    with pytest.raises(lock_service.ProductTruthLockError) as size_error:
        lock_service._uploaded_cutout_details(b"x" * (10 * 1024 * 1024 + 1))
    # The byte-size guard is enforced at the public registration boundary;
    # decode-only validation correctly reports an undecodable oversized body.
    assert size_error.value.code == "CANONICAL_CUTOUT_INVALID"


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
    cutout = _standard_cutout(tmp_path)
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
async def test_cutout_media_registration_is_stored_without_approving_lock(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    cutout = _standard_cutout(tmp_path)
    captured: dict[str, object] = {}

    async def get_product(product_id: str):
        return {"id": product_id, "product_display_name": "Test product"}

    async def no_existing_media(*, product_id: str):
        assert product_id == "p-1"
        return []

    async def create_media(draft_id: str, kind: str, **kwargs):
        captured.update(kwargs)
        captured["draft_id"] = draft_id
        captured["kind"] = kind
        return {"media_id": "stored-cutout-1", **kwargs}

    from agent.services import product_visual_grounding_resolver as resolver

    monkeypatch.setattr(lock_service.crud, "get_product", get_product)
    monkeypatch.setattr(lock_service.crud, "list_product_source_media", no_existing_media)
    monkeypatch.setattr(lock_service.crud, "create_product_source_media", create_media)
    monkeypatch.setattr(
        resolver,
        "resolve_product_reference_image",
        lambda _product: SimpleNamespace(width=20, height=40),
    )
    monkeypatch.setattr(lock_service, "BASE_DIR", tmp_path)

    result = await lock_service.register_product_truth_cutout_media(
        "p-1",
        filename=r"..\..\reviewed-cutout.png",
        content_type="image/png",
        raw_bytes=cutout.read_bytes(),
    )

    assert result["media_id"] == "stored-cutout-1"
    assert result["status"] == "STORED"
    assert result["review_status"] == "PENDING_REVIEW"
    assert captured["draft_id"] == "visual-lock:p-1"
    assert captured["kind"] == "image"
    assert captured["status"] == "STORED"
    assert captured["filename"] == "reviewed-cutout.png"
    assert ".." not in str(captured["local_path"])
    assert (tmp_path / str(captured["local_path"])).exists()


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
        confirm_product_isolation=True,
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
    assert provenance["active_selection"] == lock_service.ACTIVE_CANONICAL_CUTOUT


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
async def test_user_rejection_and_fallback_never_leave_exact_allowed(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    db_path = _db(tmp_path, assets, status="PENDING_REVIEW")
    monkeypatch.setattr(lock_service, "DB_PATH", db_path)
    captured: dict[str, object] = {}

    async def upsert(product_id: str, **kwargs):
        captured.update(kwargs)
        captured["product_id"] = product_id
        return {"product_id": product_id, **kwargs}

    monkeypatch.setattr(lock_service.crud, "upsert_product_truth_lock", upsert)

    rejected = await lock_service.reject_product_truth_lock(
        "p-1", rejected_by="operator-1", reason="Auto cutout has the wrong package geometry."
    )
    assert rejected["review_status"] == "REJECTED_BY_USER"
    assert rejected["exact_allowed"] is False
    assert captured["review_status"] == "REJECTED"
    assert json.loads(str(captured["provenance_json"]))["active_selection"] == lock_service.ACTIVE_SAME_PRODUCT_FALLBACK

    fallback = await lock_service.select_product_truth_fallback(
        "p-1", selected_by="operator-1", reason="Use the trusted same-product source while manual review is pending."
    )
    assert fallback["review_status"] == "FALLBACK_SELECTED"
    assert fallback["exact_allowed"] is False


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


@pytest.mark.asyncio
async def test_manual_replacement_archives_auto_candidate_before_switching_active_row(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    source = assets["source"]
    cutout = _standard_cutout(tmp_path)
    captured: dict[str, object] = {}
    existing = {
        "product_id": "p-1",
        "canonical_media_id": "canonical-media",
        "canonical_sha256": assets["source_sha"],
        "source_width": 20,
        "source_height": 40,
        "canonical_source_path": str(source),
        "canonical_cutout_media_id": "auto-media",
        "canonical_cutout_sha256": _sha(cutout),
        "canonical_cutout_path": str(cutout),
        "alpha_mask_json": json.dumps({"source": "cutout_alpha"}),
        "anchor_point_json": json.dumps({"x": 0.5, "y": 0.5}),
        "allowed_bbox_json": json.dumps({"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}),
        "review_status": "APPROVED",
        "provenance_json": json.dumps({"created_by": "system:deterministic-product-cutout"}),
    }

    async def get_product(product_id: str):
        return {"id": product_id, "product_display_name": "Test product"}

    async def get_media(media_id: str):
        return {"media_id": media_id, "kind": "image", "status": "STORED", "local_path": str(cutout), "filename": "manual.png"}

    async def get_lock(_product_id: str):
        return existing

    async def archive(product_id: str, **kwargs):
        captured["history_product_id"] = product_id
        captured["history"] = kwargs
        return {"history_id": kwargs.get("history_id"), **kwargs}

    async def upsert(product_id: str, **kwargs):
        captured["upsert_product_id"] = product_id
        captured["upsert"] = kwargs
        return {"product_id": product_id, **kwargs}

    from agent.services import product_visual_grounding_resolver as resolver

    monkeypatch.setattr(lock_service.crud, "get_product", get_product)
    monkeypatch.setattr(lock_service.crud, "get_product_source_media", get_media)
    monkeypatch.setattr(lock_service.crud, "get_product_truth_lock", get_lock)
    monkeypatch.setattr(lock_service.crud, "create_product_truth_lock_history", archive)
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
            source_type="PRODUCT_ROW_MEDIA_ID",
            provenance="test",
        ),
    )
    monkeypatch.setattr(lock_service, "BASE_DIR", tmp_path)

    result = await lock_service.create_pending_product_truth_lock(
        "p-1",
        ProductTruthLockOnboardingRequest(
            canonical_cutout_media_id="manual-media",
            anchor_point={"x": 0.5, "y": 0.5},
            min_scale=0.5,
            max_scale=1.0,
            allowed_bbox={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
            created_by="operator-1",
            onboarding_note="Manual override",
        ),
        allow_approved_replacement=True,
        source_kind=lock_service.USER_UPLOAD,
        original_filename="manual.png",
        uploaded_by="operator-1",
        supersede_reason="MANUAL_CUTOUT_OVERRIDE",
    )

    history = captured["history"]
    assert captured["history_product_id"] == "p-1"
    assert history["source_kind"] == lock_service.AUTO_GENERATED
    assert Path(tmp_path / history["canonical_source_path"]).exists()
    assert Path(tmp_path / history["canonical_cutout_path"]).exists()
    assert result["provenance"]["source_kind"] == lock_service.USER_UPLOAD
    assert captured["upsert"]["review_status"] == "PENDING_REVIEW"
