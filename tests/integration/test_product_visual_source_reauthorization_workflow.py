"""Provider-free proof for the Smart Registration Original Source reupload lane."""

from io import BytesIO
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from agent.db import crud
from agent.services import product_truth_lock_service
from agent.services import product_visual_onboarding_service as service


OLD_SHA = "1" * 64


def _image_bytes(*, color: tuple[int, int, int], size: tuple[int, int] = (96, 128)) -> bytes:
	stream = BytesIO()
	Image.new("RGB", size, color).save(stream, format="JPEG")
	return stream.getvalue()


def _manual_cutout_bytes(*, color: tuple[int, int, int], inset: int) -> bytes:
	cutout = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
	ImageDraw.Draw(cutout).rectangle(
		(inset, inset, 1000 - inset, 1000 - inset),
		fill=(*color, 255),
	)
	stream = BytesIO()
	cutout.save(stream, format="PNG")
	return stream.getvalue()


async def _seed_product_and_lock(tmp_path: Path, *, current_source: Path) -> tuple[dict, dict]:
	product = await crud.create_product(
		raw_product_title="Herbal Product Reupload",
		source="MANUAL",
		local_image_path=str(current_source),
		image_asset_status="READY",
		asset_status="DOWNLOADED",
	)
	product_id = str(product["id"])
	lock = await crud.upsert_product_truth_lock(
		product_id,
		canonical_media_id="old-media",
		canonical_sha256=OLD_SHA,
		source_width=96,
		source_height=128,
		canonical_source_path="data/product-registration/legacy-missing.jpg",
		canonical_cutout_media_id="old-cutout-media",
		canonical_cutout_sha256="2" * 64,
		canonical_cutout_path="data/product-registration/legacy-cutout-missing.png",
		alpha_mask_json="{}",
		anchor_point_json="{}",
		min_scale=0.5,
		max_scale=2.0,
		allowed_bbox_json=json.dumps({"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}),
		allowed_rotation=0.0,
		allowed_perspective=0.0,
		review_status="REJECTED",
		failure_state="FALLBACK_SELECTED",
		provenance_json=json.dumps({
			"source_kind": "USER_UPLOAD",
			"active_selection": "SAME_PRODUCT_TRUSTED_SOURCE",
		}),
		schema_version="1.0",
	)
	assert lock is not None
	return product, lock


@pytest.mark.asyncio
async def test_upload_and_explicit_reauthorization_promotes_new_source_without_losing_history(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	product, _ = await _seed_product_and_lock(tmp_path, current_source=current_source)
	product_id = str(product["id"])
	await crud.create_product_truth_lock_history(
		product_id,
		history_id="preserved-original-source-history",
		source_kind="USER_UPLOAD",
		review_status="REJECTED",
		canonical_media_id="old-media",
		canonical_sha256=OLD_SHA,
		source_width=96,
		source_height=128,
		canonical_source_path="history/legacy-missing.jpg",
		canonical_cutout_media_id="old-cutout-media",
		canonical_cutout_sha256="2" * 64,
		canonical_cutout_path="history/legacy-cutout-missing.png",
		provenance_json=json.dumps({"active_selection": "SAME_PRODUCT_TRUSTED_SOURCE"}),
	)
	before_history = await crud.list_product_truth_lock_history(product_id)

	replacement_bytes = _image_bytes(color=(180, 40, 90), size=(120, 160))
	receipt = await service.upload_original_source_candidate(
		product_id,
		filename="new-product-source.jpg",
		content_type="image/jpeg",
		raw_bytes=replacement_bytes,
		uploaded_by="registration-operator",
	)
	assert receipt["created_without_credit"] is True
	assert receipt["sha256"] == hashlib.sha256(replacement_bytes).hexdigest()

	still_current = await crud.get_product(product_id)
	assert still_current["media_id"] != receipt["media_id"]
	assert still_current["local_image_path"] == str(current_source)

	result = await service.save_product_visual_setup(
		product_id,
		selected_visual="ORIGINAL_SOURCE_REAUTHORIZE",
		reviewed_by="registration-operator",
		review_note="Owner confirmed the newer source matches identity, label, geometry, scale, and isolation.",
		confirm_identity=True,
		confirm_label_logo=True,
		confirm_geometry_scale=True,
		confirm_product_isolation=True,
		expected_previous_canonical_sha256=OLD_SHA,
		expected_replacement_sha256=receipt["sha256"],
		replacement_media_id=receipt["media_id"],
	)

	lock = await crud.get_product_truth_lock(product_id)
	updated_product = await crud.get_product(product_id)
	candidate = await crud.get_product_source_media(receipt["media_id"])
	after_history = await crud.list_product_truth_lock_history(product_id)
	assert lock is not None
	assert lock["canonical_media_id"] == receipt["media_id"]
	assert lock["canonical_sha256"] == receipt["sha256"]
	assert lock["canonical_source_path"].endswith(f"{receipt['media_id']}.jpg")
	assert updated_product["media_id"] == receipt["media_id"]
	assert updated_product["local_image_path"] == lock["canonical_source_path"]
	assert candidate is not None
	assert candidate["status"] == "STORED"
	candidate_path = Path(candidate["local_path"])
	if not candidate_path.is_absolute():
		candidate_path = runtime_root / candidate_path
	assert candidate_path.read_bytes() == replacement_bytes
	assert hashlib.sha256(candidate_path.read_bytes()).hexdigest() == lock["canonical_sha256"]
	assert candidate["media_id"] == updated_product["media_id"] == lock["canonical_media_id"]
	assert len(after_history) == len(before_history) == 1
	assert after_history[0]["canonical_media_id"] == "old-media"
	assert after_history[0]["canonical_sha256"] == OLD_SHA
	assert json.loads(lock["provenance_json"])["previous_canonical_sha256"] == OLD_SHA
	assert result["canonical_source_media_id"] == receipt["media_id"]
	assert result["canonical_source_sha256"] == receipt["sha256"]
	assert result["original_source_reauthorization_required"] is False
	assert result["current_system_visual"]["card"] == "ORIGINAL_SOURCE"
	assert result["original_preview_url"]


@pytest.mark.asyncio
async def test_manual_replacement_tombstones_when_bound_media_does_not_match_lock(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	product, _ = await _seed_product_and_lock(tmp_path, current_source=current_source)
	product_id = str(product["id"])
	mismatched_cutout = runtime_root / "data" / "products" / "old-cutout.png"
	mismatched_cutout.write_bytes(_manual_cutout_bytes(color=(30, 80, 140), inset=200))
	await crud.create_product_source_media(
		f"visual-source:{product_id}",
		"image",
		media_id="old-media",
		product_id=product_id,
		local_path=str(current_source),
		filename=current_source.name,
		mime="image/jpeg",
		bytes=current_source.stat().st_size,
		width=96,
		height=128,
		status="STORED",
	)
	await crud.create_product_source_media(
		f"visual-source:{product_id}",
		"image",
		media_id="old-cutout-media",
		product_id=product_id,
		local_path=str(mismatched_cutout),
		filename=mismatched_cutout.name,
		mime="image/png",
		bytes=mismatched_cutout.stat().st_size,
		width=1000,
		height=1000,
		status="STORED",
	)
	# The prior bytes cannot be recovered (bound media SHA != locked SHA). The
	# replace must NOT be blocked; a metadata-only tombstone is archived so the
	# audit record survives without trapping the operator.
	result = await service.upload_manual_product_cutout(
		product_id,
		filename="manual-replacement.png",
		content_type="image/png",
		raw_bytes=_manual_cutout_bytes(color=(180, 40, 90), inset=240),
		uploaded_by="registration-operator",
	)
	assert result["manual_cutout_status"] == "PENDING_REVIEW"

	history = await crud.list_product_truth_lock_history(product_id)
	assert len(history) == 1
	tombstone = history[0]
	assert tombstone["canonical_source_path"] is None
	assert tombstone["canonical_cutout_path"] is None
	# The true, unrecoverable SHAs are preserved in the tombstone (audit intact).
	assert tombstone["canonical_sha256"] == OLD_SHA
	assert tombstone["canonical_cutout_sha256"] == "2" * 64
	provenance = json.loads(tombstone["provenance_json"])
	assert provenance["history_byte_status"] == "UNAVAILABLE"
	assert tombstone["superseded_by_media_id"]
	assert tombstone["superseded_reason"]

	new_lock = await crud.get_product_truth_lock(product_id)
	assert new_lock is not None
	assert new_lock["canonical_cutout_media_id"] != "old-cutout-media"


@pytest.mark.asyncio
async def test_manual_replacement_tombstones_when_bytes_unrecoverable(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	# Seed a lock whose canonical byte paths point nowhere and whose bound media
	# rows do not exist — the production "byte store wiped" case: nothing to recover.
	product, old_lock = await _seed_product_and_lock(tmp_path, current_source=current_source)
	product_id = str(product["id"])

	result = await service.upload_manual_product_cutout(
		product_id,
		filename="fresh-manual.png",
		content_type="image/png",
		raw_bytes=_manual_cutout_bytes(color=(180, 40, 90), inset=240),
		uploaded_by="registration-operator",
	)
	assert result["manual_cutout_status"] == "PENDING_REVIEW"

	history = await crud.list_product_truth_lock_history(product_id)
	assert len(history) == 1
	tombstone = history[0]
	assert tombstone["canonical_source_path"] is None
	assert tombstone["canonical_cutout_path"] is None
	assert tombstone["canonical_sha256"] == OLD_SHA
	provenance = json.loads(tombstone["provenance_json"])
	assert provenance["history_byte_status"] == "UNAVAILABLE"
	assert provenance["expected_source_sha256"] == OLD_SHA

	new_lock = await crud.get_product_truth_lock(product_id)
	assert new_lock is not None
	assert new_lock["canonical_cutout_media_id"] != old_lock["canonical_cutout_media_id"]


@pytest.mark.asyncio
async def test_manual_replacement_recovers_missing_truth_lock_bytes_from_bound_media(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	product = await crud.create_product(
		raw_product_title="Recoverable Manual Cutout",
		source="MANUAL",
		local_image_path=str(current_source),
		image_asset_status="READY",
		asset_status="DOWNLOADED",
	)
	product_id = str(product["id"])
	old_cutout_bytes = _manual_cutout_bytes(color=(30, 80, 140), inset=200)
	await service.upload_manual_product_cutout(
		product_id,
		filename="old-manual.png",
		content_type="image/png",
		raw_bytes=old_cutout_bytes,
		uploaded_by="registration-operator",
	)
	old_lock = await crud.get_product_truth_lock(product_id)
	assert old_lock is not None
	old_source_path = Path(str(old_lock["canonical_source_path"]))
	old_cutout_path = Path(str(old_lock["canonical_cutout_path"]))
	if not old_source_path.is_absolute():
		old_source_path = runtime_root / old_source_path
	if not old_cutout_path.is_absolute():
		old_cutout_path = runtime_root / old_cutout_path
	assert old_source_path.is_file()
	assert old_cutout_path.is_file()
	old_source_path.unlink()
	old_cutout_path.unlink()

	result = await service.upload_manual_product_cutout(
		product_id,
		filename="replacement-manual.png",
		content_type="image/png",
		raw_bytes=_manual_cutout_bytes(color=(180, 40, 90), inset=240),
		uploaded_by="registration-operator",
	)

	history = await crud.list_product_truth_lock_history(product_id)
	assert len(history) == 1
	archived_source = Path(str(history[0]["canonical_source_path"]))
	archived_cutout = Path(str(history[0]["canonical_cutout_path"]))
	if not archived_source.is_absolute():
		archived_source = runtime_root / archived_source
	if not archived_cutout.is_absolute():
		archived_cutout = runtime_root / archived_cutout
	assert hashlib.sha256(archived_source.read_bytes()).hexdigest() == old_lock["canonical_sha256"]
	assert hashlib.sha256(archived_cutout.read_bytes()).hexdigest() == old_lock["canonical_cutout_sha256"]
	assert (
		json.loads(history[0]["provenance_json"])["history_byte_recovery"]
		== "DETERMINISTIC_BOUND_MEDIA_SHA256_VERIFIED"
	)
	new_lock = await crud.get_product_truth_lock(product_id)
	assert new_lock is not None
	assert new_lock["canonical_cutout_media_id"] != old_lock["canonical_cutout_media_id"]
	assert result["manual_cutout_status"] == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_manual_replacement_recovers_missing_truth_lock_bytes_from_local_store(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	product = await crud.create_product(
		raw_product_title="Recoverable Local Truth Store",
		source="MANUAL",
		local_image_path=str(current_source),
		image_asset_status="READY",
		asset_status="DOWNLOADED",
	)
	product_id = str(product["id"])
	old_source_bytes = _image_bytes(color=(30, 80, 140))
	old_cutout_bytes = _manual_cutout_bytes(color=(30, 80, 140), inset=200)
	truth_directory = product_truth_lock_service._truth_lock_directory(product_id)
	seed_directory = truth_directory / "history" / "seed"
	seed_directory.mkdir(parents=True, exist_ok=True)
	seed_source = seed_directory / "canonical_source.jpg"
	seed_cutout = seed_directory / "canonical_cutout.png"
	seed_source.write_bytes(old_source_bytes)
	seed_cutout.write_bytes(old_cutout_bytes)
	active_source = truth_directory / "versions" / "active" / "canonical_source.jpg"
	active_cutout = truth_directory / "versions" / "active" / "canonical_cutout.png"
	await crud.upsert_product_truth_lock(
		product_id,
		canonical_media_id="missing-old-media",
		canonical_sha256=hashlib.sha256(old_source_bytes).hexdigest(),
		source_width=96,
		source_height=128,
		canonical_source_path=str(active_source.relative_to(runtime_root)).replace("\\", "/"),
		canonical_cutout_media_id="missing-old-cutout-media",
		canonical_cutout_sha256=hashlib.sha256(old_cutout_bytes).hexdigest(),
		canonical_cutout_path=str(active_cutout.relative_to(runtime_root)).replace("\\", "/"),
		alpha_mask_json="{}",
		anchor_point_json="{}",
		min_scale=0.5,
		max_scale=2.0,
		allowed_bbox_json=json.dumps({"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}),
		allowed_rotation=0.0,
		allowed_perspective=0.0,
		review_status="REJECTED",
		failure_state="FALLBACK_SELECTED",
		provenance_json=json.dumps({
			"source_kind": "USER_UPLOAD",
			"active_selection": "SAME_PRODUCT_TRUSTED_SOURCE",
		}),
		schema_version="1.0",
	)

	result = await service.upload_manual_product_cutout(
		product_id,
		filename="replacement-manual.png",
		content_type="image/png",
		raw_bytes=_manual_cutout_bytes(color=(180, 40, 90), inset=240),
		uploaded_by="registration-operator",
	)

	history = await crud.list_product_truth_lock_history(product_id)
	assert len(history) == 1
	archived_source = Path(str(history[0]["canonical_source_path"]))
	archived_cutout = Path(str(history[0]["canonical_cutout_path"]))
	if not archived_source.is_absolute():
		archived_source = runtime_root / archived_source
	if not archived_cutout.is_absolute():
		archived_cutout = runtime_root / archived_cutout
	assert hashlib.sha256(archived_source.read_bytes()).hexdigest() == hashlib.sha256(old_source_bytes).hexdigest()
	assert hashlib.sha256(archived_cutout.read_bytes()).hexdigest() == hashlib.sha256(old_cutout_bytes).hexdigest()
	assert (
		json.loads(history[0]["provenance_json"])["history_byte_recovery"]
		== "TRUTH_LOCK_STORE_SHA256_VERIFIED"
	)
	assert active_source.read_bytes() == old_source_bytes
	assert active_cutout.read_bytes() == old_cutout_bytes
	assert result["manual_cutout_status"] == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_reauthorization_rejects_a_candidate_bound_to_another_product(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	first_product, _ = await _seed_product_and_lock(tmp_path, current_source=current_source)
	second_product, _ = await _seed_product_and_lock(tmp_path, current_source=current_source)
	receipt = await service.upload_original_source_candidate(
		str(first_product["id"]),
		filename="first-product-source.jpg",
		content_type="image/jpeg",
		raw_bytes=_image_bytes(color=(180, 40, 90)),
		uploaded_by="registration-operator",
	)

	with pytest.raises(service.ProductVisualOnboardingError) as raised:
		await service.save_product_visual_setup(
			str(second_product["id"]),
			selected_visual="ORIGINAL_SOURCE_REAUTHORIZE",
			reviewed_by="registration-operator",
			review_note="Binding test",
			confirm_identity=True,
			confirm_label_logo=True,
			confirm_geometry_scale=True,
			confirm_product_isolation=True,
			expected_previous_canonical_sha256=OLD_SHA,
			expected_replacement_sha256=receipt["sha256"],
			replacement_media_id=receipt["media_id"],
		)

	assert raised.value.code == "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_PRODUCT_MISMATCH"


@pytest.mark.asyncio
async def test_source_candidate_rejects_non_image_bytes(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)
	product, _ = await _seed_product_and_lock(tmp_path, current_source=current_source)

	with pytest.raises(service.ProductVisualOnboardingError) as raised:
		await service.upload_original_source_candidate(
			str(product["id"]),
			filename="not-an-image.jpg",
			content_type="image/jpeg",
			raw_bytes=b"not an image",
			uploaded_by="registration-operator",
		)

	assert raised.value.code == "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID"


@pytest.mark.asyncio
async def test_reauthorization_rolls_back_lock_product_and_candidate_on_promotion_failure(tmp_path, monkeypatch):
	runtime_root = tmp_path / "runtime"
	current_source = runtime_root / "data" / "products" / "current.jpg"
	current_source.parent.mkdir(parents=True, exist_ok=True)
	current_source.write_bytes(_image_bytes(color=(30, 80, 140)))
	monkeypatch.setattr(service, "BASE_DIR", runtime_root)
	monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", runtime_root)

	product, original_lock = await _seed_product_and_lock(tmp_path, current_source=current_source)
	product_id = str(product["id"])
	receipt = await service.upload_original_source_candidate(
		product_id,
		filename="rollback-source.jpg",
		content_type="image/jpeg",
		raw_bytes=_image_bytes(color=(180, 40, 90)),
		uploaded_by="registration-operator",
	)
	original_product = await crud.get_product(product_id)
	original_candidate = await crud.get_product_source_media(receipt["media_id"])

	original_promote = crud.promote_product_source_media

	async def fail_after_candidate_promotion(product_id_arg: str, media_id_arg: str):
		promoted = await original_promote(product_id_arg, media_id_arg)
		assert promoted is not None
		raise RuntimeError("injected failure after candidate promotion")

	monkeypatch.setattr(crud, "promote_product_source_media", fail_after_candidate_promotion)

	with pytest.raises(RuntimeError, match="injected failure after candidate promotion"):
		await service.save_product_visual_setup(
			product_id,
			selected_visual="ORIGINAL_SOURCE_REAUTHORIZE",
			reviewed_by="registration-operator",
			review_note="Atomic rollback test",
			confirm_identity=True,
			confirm_label_logo=True,
			confirm_geometry_scale=True,
			confirm_product_isolation=True,
			expected_previous_canonical_sha256=OLD_SHA,
			expected_replacement_sha256=receipt["sha256"],
			replacement_media_id=receipt["media_id"],
		)

	after_lock = await crud.get_product_truth_lock(product_id)
	after_product = await crud.get_product(product_id)
	after_candidate = await crud.get_product_source_media(receipt["media_id"])
	assert after_lock["canonical_sha256"] == original_lock["canonical_sha256"]
	assert after_lock["canonical_media_id"] == original_lock["canonical_media_id"]
	assert after_lock["canonical_source_path"] == original_lock["canonical_source_path"]
	assert after_product["media_id"] == original_product["media_id"]
	assert after_product["local_image_path"] == original_product["local_image_path"]
	assert after_candidate["status"] == original_candidate["status"] == "PENDING_REAUTHORIZATION"
	assert after_candidate["media_id"] != after_product["media_id"]
