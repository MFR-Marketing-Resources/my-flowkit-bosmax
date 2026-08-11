"""No-spend Product Reference Pack materialization and review gates.

The pack is the generative route's evidence bundle.  It is deliberately not the
exact compositor's product truth lock: image bytes, label/logo candidates and
physical measurements are recorded here, while every generated output still
requires an independent machine check and human approval.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from agent.config import BASE_DIR
from agent.db import crud
from agent.models.image_generation_contract import (
    GeneratedImageMachineQA,
    ImageReferenceBinding,
    PhysicalMeasurementEvidence,
    ProductReferencePackRecord,
)
from agent.services.product_lock_builder import resolve_schema_entry
from agent.services.product_visual_grounding_resolver import (
    ProductVisualReferenceRequiredError,
    resolve_product_reference_image,
)

logger = logging.getLogger(__name__)


class ProductReferencePackError(ValueError):
    """Stable fail-closed error for creative reference-pack gates."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_metadata(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_bbox = alpha.getbbox()
            return {
                "width": int(image.width),
                "height": int(image.height),
                "mime": str(Image.MIME.get(image.format, "application/octet-stream")),
                "sha256": _sha256(path),
                "alpha_bbox": list(alpha_bbox) if alpha_bbox else None,
                "has_transparency": image.mode in {"RGBA", "LA", "P"}
                and ("transparency" in image.info or image.mode in {"RGBA", "LA"}),
            }
    except (OSError, ValueError):
        return None


def _path_from_reference(reference: dict[str, Any] | None) -> Path | None:
    raw = (reference or {}).get("local_path") or (reference or {}).get("local_file_path")
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_file() else None


def _pack_dir(product_id: str) -> Path:
    # Product IDs are UUIDs in the canonical database.  Restrict the path
    # component even if a malformed external ID reaches this service.
    safe_id = "".join(char for char in product_id if char.isalnum() or char in "-_")
    return BASE_DIR / "data" / "product-reference-packs" / safe_id


def _candidate_crop(source_path: Path, destination: Path, role: str) -> dict[str, Any] | None:
    """Create a deterministic crop candidate, never an automatic approval.

    Cropping from pixels can locate a review candidate but cannot prove that it
    is the label or logo.  The provenance explicitly carries that limitation.
    """
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGBA")
            width, height = image.size
            left = max(0, int(width * 0.15))
            right = min(width, int(width * 0.85))
            top = max(0, int(height * 0.25))
            bottom = min(height, int(height * 0.82))
            if right <= left or bottom <= top:
                return None
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.crop((left, top, right, bottom)).save(destination, format="PNG")
        metadata = _image_metadata(destination)
        if not metadata:
            return None
        metadata.update(
            {
                "role": role,
                "candidate_method": "DETERMINISTIC_CENTER_CROP",
                "requires_human_review": True,
            }
        )
        return metadata
    except (OSError, ValueError):
        return None


def _candidate_cutout(source_path: Path, destination: Path) -> dict[str, Any] | None:
    """Materialize a deterministic cutout candidate, never an approved truth lock."""
    try:
        from agent.services.exact_product_compositor_service import (
            ExactProductCompositeError,
            _build_canonical_cutout,
        )

        cutout = _build_canonical_cutout(source_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        cutout.save(destination, format="PNG")
        metadata = _image_metadata(destination)
        if not metadata:
            return None
        metadata.update(
            {
                "role": "PRODUCT_CUTOUT",
                "candidate_method": "DETERMINISTIC_PRODUCT_CUTOUT_CANDIDATE",
                "requires_human_review": True,
            }
        )
        return metadata
    except (ExactProductCompositeError, OSError, ValueError):
        return None


def _explicit_measurements(product: dict[str, Any]) -> PhysicalMeasurementEvidence:
    """Read authored physical evidence only; never infer from pixel geometry."""
    entry = resolve_schema_entry(product) or {}
    candidates: dict[str, Any] = {**entry, **product}

    def positive_number(*keys: str) -> float | None:
        for key in keys:
            raw = candidates.get(key)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return None

    width = positive_number("physical_width_mm", "width_mm")
    height = positive_number("physical_height_mm", "height_mm")
    depth = positive_number("physical_depth_mm", "depth_mm")
    volume = positive_number("volume_ml", "pack_size_ml", "net_volume_ml", "size_ml")
    explicit_keys = {
        "physical_width_mm",
        "physical_height_mm",
        "physical_depth_mm",
        "volume_ml",
        "pack_size_ml",
        "net_volume_ml",
        "size_ml",
    }
    source = "PRODUCT_RECORD_OR_AUTHORITY_SCHEMA" if any(
        candidates.get(key) not in (None, "") for key in explicit_keys
    ) else "UNVERIFIED"
    if source == "UNVERIFIED":
        confidence = "UNVERIFIED"
    elif width is not None and height is not None and depth is not None:
        confidence = "HIGH"
    else:
        # Volume is real authored evidence, but it does not establish the full
        # three-dimensional placement geometry on its own.
        confidence = "MEDIUM"
    return PhysicalMeasurementEvidence(
        physical_width_mm=width,
        physical_height_mm=height,
        physical_depth_mm=depth,
        volume_ml=volume,
        scale_evidence_source=source,
        scale_confidence=confidence,
    )


def _record_from_row(row: dict[str, Any]) -> ProductReferencePackRecord:
    def parse_json(key: str, fallback: Any) -> Any:
        raw = row.get(key)
        if raw in (None, ""):
            return fallback
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return fallback

    measurements = PhysicalMeasurementEvidence(
        physical_width_mm=row.get("physical_width_mm"),
        physical_height_mm=row.get("physical_height_mm"),
        physical_depth_mm=row.get("physical_depth_mm"),
        volume_ml=row.get("volume_ml"),
        scale_evidence_source=row.get("scale_evidence_source") or "UNVERIFIED",
        scale_confidence=row.get("scale_confidence") or "UNVERIFIED",
    )
    references = [ImageReferenceBinding.model_validate(item) for item in parse_json("references_json", [])]
    return ProductReferencePackRecord(
        pack_id=str(row["pack_id"]),
        product_id=str(row["product_id"]),
        schema_version=str(row.get("schema_version") or "product_reference_pack_v1"),
        pack_status=str(row.get("pack_status") or "DRAFT"),
        machine_qa_status=str(row.get("machine_qa_status") or "WARN"),
        machine_qa=parse_json("machine_qa_json", {}),
        physical_measurements=measurements,
        references=references,
        provenance=parse_json("provenance_json", {}),
        human_review=parse_json("human_review_json", {}),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


async def _create_asset(
    *,
    product: dict[str, Any],
    pack_id: str,
    role: str,
    path: Path,
    metadata: dict[str, Any],
    preserve_approval: bool = False,
) -> str:
    asset_id = "ca_refpack_" + hashlib.sha256(f"{pack_id}:{role}".encode()).hexdigest()[:24]
    existing = await crud.get_creative_asset(asset_id)
    if existing is None:
        await crud.create_creative_asset(
            asset_id=asset_id,
            semantic_role="PRODUCT_REFERENCE",
            display_name=f"{product.get('product_display_name') or product.get('raw_product_title') or product['id']} {role}",
            description=f"Product Reference Pack candidate for {role}; requires human review.",
            source_type="PRODUCT_CACHE",
            storage_kind="LOCAL_FILE",
            preview_url=None,
            download_url=None,
            media_id=None,
            local_file_path=str(path),
            remote_source_url=None,
            product_id=str(product["id"]),
            category=product.get("category"),
            silo=product.get("silo"),
            product_type=product.get("product_type"),
            allowed_modes=json.dumps(["IMG"]),
            # Product Reference Pack roles are IMG reference metadata, not
            # video engine slots.  Keep this field valid for CreativeAssetRecord.
            engine_slot_eligibility=json.dumps([]),
            mode_a_metadata_handoff=json.dumps({"reference_role": role, "metadata": metadata}),
            visual_dna_summary=None,
            character_dna=None,
            scene_context_dna=None,
            style_mood_dna=None,
            source_prompt_fingerprint=None,
            source_workspace_execution_package_id=None,
            source_prompt_package_snapshot_id=None,
            asset_subtype=f"PRODUCT_REFERENCE_PACK_{role}",
            contains_rendered_text=False,
            approved_for_video_support=False,
            approved_for_poster=False,
            product_truth_status="UNVERIFIED",
            identity_lock_status="UNVERIFIED",
            scale_truth_status="UNVERIFIED",
            claim_safety_status="NOT_APPLICABLE",
            review_status="PENDING_REVIEW",
            status="ACTIVE",
        )
    else:
        changes = {
            "local_file_path": str(path),
            "mode_a_metadata_handoff": json.dumps(
                {"reference_role": role, "metadata": metadata}
            ),
            # Repair rows created by the pre-pack contract as they are reused;
            # the reference role remains authoritative in the handoff metadata.
            "engine_slot_eligibility": json.dumps([]),
        }
        if not preserve_approval:
            changes.update(
                {
                    "review_status": "PENDING_REVIEW",
                    "approved_for_poster": False,
                    "identity_lock_status": "UNVERIFIED",
                    "scale_truth_status": "UNVERIFIED",
                }
            )
        await crud.update_creative_asset(asset_id, **changes)
    return asset_id


async def get_reference_pack(product_id: str) -> ProductReferencePackRecord | None:
    row = await crud.get_product_reference_pack(product_id)
    return _record_from_row(row) if row else None


async def ensure_product_reference_pack(product_id: str) -> ProductReferencePackRecord:
    product = await crud.get_product(product_id)
    if not product:
        raise ProductReferencePackError("PRODUCT_NOT_FOUND", f"Unknown product: {product_id}")

    try:
        reference = resolve_product_reference_image(product, prefer_approved_cutout=False)
    except ProductVisualReferenceRequiredError as exc:
        raise ProductReferencePackError("PRODUCT_REFERENCE_REQUIRED", str(exc)) from exc
    source_path = _path_from_reference({"local_path": reference.local_path})
    if source_path is None:
        raise ProductReferencePackError("PRODUCT_REFERENCE_FILE_MISSING", "Canonical source is not readable")
    source_meta = _image_metadata(source_path)
    if source_meta is None:
        raise ProductReferencePackError("PRODUCT_REFERENCE_INVALID", "Canonical source failed image validation")

    target_dir = _pack_dir(product_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = target_dir / (
        f"canonical-{source_meta['sha256']}{source_path.suffix.lower() or '.bin'}"
    )
    if canonical_path != source_path and not canonical_path.exists():
        try:
            shutil.copyfile(source_path, canonical_path)
        except OSError:
            canonical_path = source_path
    canonical_meta = _image_metadata(canonical_path) or source_meta

    label_path = target_dir / "label-candidate.png"
    logo_path = target_dir / "logo-candidate.png"
    label_meta = _candidate_crop(source_path, label_path, "PRODUCT_LABEL_CROP")
    logo_meta = _candidate_crop(source_path, logo_path, "PRODUCT_LOGO_CROP")
    cutout_path: Path | None = None
    cutout_meta: dict[str, Any] | None = None
    truth_cutout_bound = False
    truth_lock = await crud.get_product_truth_lock(product_id)
    if truth_lock and truth_lock.get("canonical_cutout_path"):
        cutout_path = _path_from_reference({"local_path": truth_lock["canonical_cutout_path"]})
    if cutout_path:
        cutout_meta = _image_metadata(cutout_path)
        truth_cutout_bound = cutout_meta is not None
    if not cutout_path:
        candidate_path = target_dir / "cutout-candidate.png"
        cutout_meta = _candidate_cutout(source_path, candidate_path)
        if cutout_meta:
            cutout_path = candidate_path

    measurements = _explicit_measurements(product)
    previous = await crud.get_product_reference_pack(product_id)
    previous_provenance = {}
    if previous:
        try:
            previous_provenance = json.loads(previous.get("provenance_json") or "{}")
        except (TypeError, ValueError):
            previous_provenance = {}
    unchanged_approved = (
        previous
        and previous.get("pack_status") == "APPROVED"
        and previous_provenance.get("canonical_sha256") == canonical_meta["sha256"]
    )
    pack_id = str(previous.get("pack_id")) if previous else "prp_" + hashlib.sha256(
        f"{product_id}:{canonical_meta['sha256']}".encode()
    ).hexdigest()[:28]

    references: list[ImageReferenceBinding] = []
    asset_specs = [
        ("PRODUCT_CANONICAL", canonical_path, canonical_meta),
        ("PRODUCT_LABEL_CROP", label_path, label_meta),
        ("PRODUCT_LOGO_CROP", logo_path, logo_meta),
    ]
    if cutout_path and cutout_meta:
        asset_specs.append(("PRODUCT_CUTOUT", cutout_path, cutout_meta))
    for role, path, metadata in asset_specs:
        if not path or not metadata:
            continue
        asset_id = await _create_asset(
            product=product,
            pack_id=pack_id,
            role=role,
            path=path,
            metadata=metadata,
            preserve_approval=bool(unchanged_approved),
        )
        references.append(
            ImageReferenceBinding(
                role=role,
                asset_id=asset_id,
                media_id=reference.media_id if role == "PRODUCT_CANONICAL" else None,
                local_file_path=str(path),
                sha256=metadata["sha256"],
                source_type=(
                    "PRODUCT_CACHE"
                    if role != "PRODUCT_CUTOUT"
                    else (
                        "EXACT_TRUTH_LOCK"
                        if truth_cutout_bound
                        else "DETERMINISTIC_CUTOUT_CANDIDATE"
                    )
                ),
                approved=bool(unchanged_approved),
                evidence=metadata,
            )
        )

    findings: list[str] = []
    if not label_meta:
        findings.append("LABEL_CROP_UNAVAILABLE")
    else:
        findings.append("LABEL_CROP_CANDIDATE_REQUIRES_HUMAN_REVIEW")
    if not logo_meta:
        findings.append("LOGO_CROP_UNAVAILABLE")
    else:
        findings.append("LOGO_CROP_CANDIDATE_REQUIRES_HUMAN_REVIEW")
    if not cutout_meta:
        findings.append("CUTOUT_NOT_BOUND")
    elif not truth_cutout_bound:
        findings.append("CUTOUT_CANDIDATE_REQUIRES_HUMAN_REVIEW")
    if measurements.scale_confidence == "UNVERIFIED":
        findings.append("PHYSICAL_SCALE_UNVERIFIED_NO_PIXEL_INFERENCE")
    machine_status = "FAIL" if not source_meta else ("PASS" if not findings else "WARN")
    pack_status = "APPROVED" if unchanged_approved else "PENDING_REVIEW"
    provenance = {
        "builder": "product_reference_pack_service",
        "schema_version": "product_reference_pack_v1",
        "canonical_sha256": canonical_meta["sha256"],
        "canonical_source": reference.provenance,
        "source_type": reference.source_type,
        "generated_by_provider": False,
        "created_without_credit": True,
    }
    human_review = (
        json.loads(previous.get("human_review_json") or "{}")
        if unchanged_approved and previous
        else {}
    )
    row = await crud.upsert_product_reference_pack(
        product_id,
        pack_id=pack_id,
        schema_version="product_reference_pack_v1",
        pack_status=pack_status,
        machine_qa_status=machine_status,
        machine_qa_json=json.dumps({"findings": findings, "source": source_meta}),
        physical_width_mm=measurements.physical_width_mm,
        physical_height_mm=measurements.physical_height_mm,
        physical_depth_mm=measurements.physical_depth_mm,
        volume_ml=measurements.volume_ml,
        scale_evidence_source=measurements.scale_evidence_source,
        scale_confidence=measurements.scale_confidence,
        geometry_json=json.dumps({"source_width": canonical_meta["width"], "source_height": canonical_meta["height"]}),
        references_json=json.dumps([item.model_dump(mode="json") for item in references]),
        provenance_json=json.dumps(provenance),
        human_review_json=json.dumps(human_review),
    )
    if not row:
        raise ProductReferencePackError("REFERENCE_PACK_PERSIST_FAILED")
    return _record_from_row(row)


async def approve_product_reference_pack(
    product_id: str, *, reviewed_by: str, note: str = ""
) -> ProductReferencePackRecord:
    pack = await get_reference_pack(product_id)
    if pack is None:
        raise ProductReferencePackError("PRODUCT_REFERENCE_PACK_REQUIRED")
    if pack.machine_qa_status == "FAIL":
        raise ProductReferencePackError("REFERENCE_PACK_MACHINE_QA_FAILED")
    required_roles = {"PRODUCT_CANONICAL", "PRODUCT_LABEL_CROP", "PRODUCT_LOGO_CROP"}
    present_roles = {item.role for item in pack.references}
    missing = sorted(required_roles - present_roles)
    if missing:
        raise ProductReferencePackError("REFERENCE_PACK_MISSING_ROLES", ",".join(missing))
    approved_references = [
        item.model_copy(update={"approved": True}).model_dump(mode="json")
        for item in pack.references
    ]
    row = await crud.upsert_product_reference_pack(
        product_id,
        pack_status="APPROVED",
        references_json=json.dumps(approved_references),
        human_review_json=json.dumps(
            {"reviewed_by": reviewed_by, "reviewed_at": crud._now(), "note": note}
        ),
    )
    return _record_from_row(row)


def transport_reference_ids(pack: ProductReferencePackRecord) -> dict[str, str]:
    """Map typed pack roles into the existing Flow media-id transport slots."""
    if pack.pack_status != "APPROVED":
        raise ProductReferencePackError("REFERENCE_PACK_APPROVAL_REQUIRED")
    output: dict[str, str] = {}
    for binding in pack.references:
        if not binding.approved:
            # The pack approval is the authority for all bound bytes.  Keep the
            # binding explicit so a stale or manually edited row fails closed.
            raise ProductReferencePackError("REFERENCE_BINDING_NOT_APPROVED", binding.role)
        media_id = binding.media_id or binding.asset_id
        if media_id:
            output[binding.role] = media_id
    if "PRODUCT_CANONICAL" not in output:
        raise ProductReferencePackError("PRODUCT_CANONICAL_REFERENCE_REQUIRED")
    return output


def machine_check_generated_output(
    media_id: str, pack: ProductReferencePackRecord
) -> GeneratedImageMachineQA:
    findings = [
        "GENERATED_OUTPUT_REQUIRES_HUMAN_APPROVAL",
        "IDENTITY_LABEL_LOGO_GEOMETRY_NOT_PROVEN_BY_PAYLOAD",
    ]
    if pack.physical_measurements.scale_confidence == "UNVERIFIED":
        findings.append("PHYSICAL_SCALE_UNVERIFIED")
    return GeneratedImageMachineQA(
        media_id=media_id,
        machine_qa_status="WARN",
        identity_status="UNVERIFIED",
        label_status="UNVERIFIED",
        geometry_status="UNVERIFIED",
        scale_status="UNVERIFIED",
        findings=findings,
        human_review_required=True,
    )
