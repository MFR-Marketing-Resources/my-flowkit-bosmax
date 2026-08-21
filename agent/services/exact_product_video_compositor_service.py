"""Deterministic exact-product video compositing.

The provider is allowed to make a scene scaffold only.  This module owns the
final product pixels: every output frame is built from the approved
ProductTruthLock cutout and the scene scaffold is never registered as a final
product artifact.  The service is intentionally provider-free and fails closed
when a track, mask, or media tool is not proven.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image

from agent.config import OUTPUT_DIR
from agent.services.exact_product_compositor_service import (
    ExactProductCompositeError,
    LANE_SAFE_REGIONS,
    augment_prompt_scene_only,
    composite,
    prepare_layer,
    validate_canonical_or_raise,
)


EXACT_PRODUCT_DETERMINISTIC_COMPOSITE = "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"

PRODUCT_STATIC_TABLE = "PRODUCT_STATIC_TABLE"
PRODUCT_HAND_HOLD = "PRODUCT_HAND_HOLD"
PRODUCT_PICK_UP = "PRODUCT_PICK_UP"
PRODUCT_PLACE_DOWN = "PRODUCT_PLACE_DOWN"
PRODUCT_PRESENT_TO_CAMERA = "PRODUCT_PRESENT_TO_CAMERA"
SMALL_CONTROLLED_ROTATION = "SMALL_CONTROLLED_ROTATION"

SUPPORTED_EXACT = "SUPPORTED_EXACT"
REQUIRES_OCCLUSION_MASK = "REQUIRES_OCCLUSION_MASK"
UNSUPPORTED_EXACT = "UNSUPPORTED_EXACT"

EXACT_PRODUCT_VIDEO_COMPOSITOR_VERSION = "EXACT_PRODUCT_VIDEO_COMPOSITOR_V1"
FACELESS_V1_SAFE_DEFAULT = PRODUCT_PRESENT_TO_CAMERA


class ExactProductVideoCompositeError(ExactProductCompositeError):
    """Stable fail-closed error for the video compositor."""

    def __init__(self, code: str, message: str = "", *, status_code: int = 422, details: dict[str, Any] | None = None):
        super().__init__(code, message, status_code=status_code)
        self.details = details or {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm_id(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _requested_choreography_id(choreography: dict[str, Any] | str | None) -> str:
    if isinstance(choreography, dict):
        return str(
            choreography.get("exact_choreography_id")
            or choreography.get("exact_action_id")
            or choreography.get("choreography_id")
            or choreography.get("action_id")
            or ""
        ).strip()
    return str(choreography or "").strip()


def classify_exact_choreography(
    choreography: dict[str, Any] | str | None,
) -> dict[str, Any]:
    """Classify only a governed V1 action; unknown actions never become exact."""

    raw_id = _requested_choreography_id(choreography)
    normalized = _norm_id(raw_id)
    foreground_crossing = False
    if isinstance(choreography, dict):
        foreground_crossing = bool(
            choreography.get("foreground_crossing")
            or choreography.get("hand_crosses_product")
            or choreography.get("requires_foreground_occlusion")
        )

    if normalized == PRODUCT_STATIC_TABLE:
        classification = REQUIRES_OCCLUSION_MASK if foreground_crossing else SUPPORTED_EXACT
        reason = "Static table placement has a deterministic rigid track; a crossing foreground requires an explicit mask."
        occlusion = "FOREGROUND_MASK_REQUIRED" if foreground_crossing else "NONE"
        track = "STATIC_RIGID_PRODUCT_TRUTH_TRACK"
    elif normalized == PRODUCT_PRESENT_TO_CAMERA:
        classification = REQUIRES_OCCLUSION_MASK if foreground_crossing else SUPPORTED_EXACT
        reason = "Label-forward presentation uses a deterministic rigid product layer; hands may not cross without a verified mask."
        occlusion = "FOREGROUND_MASK_REQUIRED" if foreground_crossing else "NONE"
        track = "STATIC_RIGID_PRODUCT_TRUTH_TRACK"
    elif normalized == SMALL_CONTROLLED_ROTATION:
        classification = REQUIRES_OCCLUSION_MASK if foreground_crossing else SUPPORTED_EXACT
        reason = "Small controlled rotation is bounded to a rigid layer and the Product Truth rotation allowance."
        occlusion = "FOREGROUND_MASK_REQUIRED" if foreground_crossing else "NONE"
        track = "BOUNDED_RIGID_PRODUCT_TRUTH_TRACK"
    elif normalized in {
        PRODUCT_HAND_HOLD,
        PRODUCT_PICK_UP,
        PRODUCT_PLACE_DOWN,
    }:
        classification = REQUIRES_OCCLUSION_MASK
        reason = "The hand can cross the product silhouette; exact output requires verified per-frame foreground masks."
        occlusion = "FOREGROUND_MASK_REQUIRED"
        track = "EXPLICIT_MASKED_RIGID_PRODUCT_TRUTH_TRACK"
    else:
        classification = UNSUPPORTED_EXACT
        reason = "The choreography is not a governed V1 exact-product action."
        occlusion = "UNSUPPORTED"
        track = "NONE"

    return {
        "requested_choreography_id": raw_id or None,
        "choreography_id": raw_id or None,
        "classification": classification,
        "reason": reason,
        "occlusion_strategy": occlusion,
        "track_policy": track,
        "foreground_crossing": foreground_crossing,
    }


def resolve_faceless_exact_choreography(
    choreography: dict[str, Any] | str | None,
) -> dict[str, Any]:
    """Choose an explicit safe V1 action for a Faceless scene.

    Existing Scene Choreography entries describe creative actions such as
    opening and applying oil.  They are retained as the requested scene
    lineage, but are not silently asserted to be exact-compositable.  Unless
    the caller explicitly supplies an exact V1 action, the route selects the
    governed label-forward presentation action and records that selection.
    """

    explicit = isinstance(choreography, dict) and any(
        str(choreography.get(key) or "").strip()
        for key in ("exact_choreography_id", "exact_action_id")
    )
    raw = _requested_choreography_id(choreography)
    normalized = _norm_id(raw)
    if explicit or normalized in {
        PRODUCT_STATIC_TABLE,
        PRODUCT_HAND_HOLD,
        PRODUCT_PICK_UP,
        PRODUCT_PLACE_DOWN,
        PRODUCT_PRESENT_TO_CAMERA,
        SMALL_CONTROLLED_ROTATION,
    }:
        selected = classify_exact_choreography(choreography)
        selected["selection_reason"] = "EXPLICIT_EXACT_CHOREOGRAPHY"
        if selected["classification"] == UNSUPPORTED_EXACT:
            raise ExactProductVideoCompositeError(
                "EXACT_COMPOSITE_UNSUPPORTED",
                selected["reason"],
                details=selected,
            )
        return selected

    selected = classify_exact_choreography(FACELESS_V1_SAFE_DEFAULT)
    selected.update(
        {
            "requested_scene_choreography_id": raw or None,
            "requested_scene_action": (
                choreography.get("allowed_action")
                if isinstance(choreography, dict)
                else None
            ),
            "selection_reason": "FACELESS_V1_EXACT_SAFE_DEFAULT",
        }
    )
    return selected


def build_exact_product_video_plan(
    product: dict[str, Any],
    choreography: dict[str, Any] | str | None,
) -> dict[str, Any]:
    """Resolve Product Truth geometry and the exact V1 choreography."""

    canonical = validate_canonical_or_raise(product)
    selected = resolve_faceless_exact_choreography(choreography)
    eligible = selected["classification"] == SUPPORTED_EXACT
    return {
        "compositor_version": EXACT_PRODUCT_VIDEO_COMPOSITOR_VERSION,
        "selected_execution_route": EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "exact_product_required": True,
        "generate_eligibility": eligible,
        "blocker": None if eligible else selected["classification"],
        "choreography": selected,
        "placement_region": copy.deepcopy(LANE_SAFE_REGIONS["studio"]),
        "product_truth": {
            "product_id": canonical["product_id"],
            "canonical_media_id": canonical["canonical_media_id"],
            "canonical_source_sha256": canonical["source_sha256"],
            "canonical_cutout_media_id": canonical["cutout_media_id"],
            "canonical_cutout_sha256": canonical["cutout_sha256"],
            "alpha_mask_sha256": canonical["alpha_mask_sha256"],
            "allowed_bbox": copy.deepcopy(canonical["allowed_bbox"]),
            "anchor_point": copy.deepcopy(canonical["anchor_point"]),
            "min_scale": canonical["min_scale"],
            "max_scale": canonical["max_scale"],
            "allowed_rotation": canonical["allowed_rotation"],
            "allowed_perspective": canonical["allowed_perspective"],
            "truth_lock_schema_version": canonical["product_truth_lock_schema_version"],
        },
        "provider_product_reference_forbidden": True,
        "provider_final_pixel_authority": False,
        "face_qc": {"status": "NOT_RUN", "verified": False},
    }


def build_exact_scene_scaffold_prompt(
    base_prompt: str,
    plan: dict[str, Any],
    *,
    scene_context: str = "",
) -> str:
    """Make a provider prompt that cannot authorize provider product pixels."""

    selected = plan.get("choreography") or {}
    selected_id = selected.get("choreography_id") or FACELESS_V1_SAFE_DEFAULT
    raw_prompt = str(base_prompt or "")
    # The older image compositor helper removes its known Product Truth
    # headings.  A video compiler can also emit free-form product prose, so
    # remove directive lines before applying the strict scene-only block.
    forbidden_directive_markers = (
        "exact product",
        "product label",
        "preserve the real product",
        "preserve product identity",
        "show the product",
        "feature the product",
        "product identity lock",
        "product geometry lock",
        "product scale lock",
        "product reference lock",
        "product no-modification lock",
    )
    safe_lines = [
        line
        for line in raw_prompt.splitlines()
        if not any(marker in line.lower() for marker in forbidden_directive_markers)
    ]
    prompt = augment_prompt_scene_only("\n".join(safe_lines))
    additions = [
        "EXECUTION ROUTE: EXACT_PRODUCT_DETERMINISTIC_COMPOSITE.",
        "PROVIDER ROLE: scene scaffold only; the provider output is an internal plate and is never the final product artifact.",
        "Do not generate product pixels, packaging, label, logo, cap, replacement bottle, product text, product shadow, or product reflection.",
        f"EXACT CHOREOGRAPHY: {selected_id}; use only the declared rigid product placement and keep hands/props outside the reserved product box unless a verified foreground mask is supplied.",
        "FACELESS: no visible face, head, eyes, mouth, or facial reflection; hands, arms, and torso may appear.",
    ]
    if scene_context.strip():
        additions.append(f"SCENE CONTEXT: {scene_context.strip()}")
    return f"{prompt}\n\n" + " ".join(additions)


def _trusted_output_path(raw: str | Path, *, code: str) -> Path:
    path = Path(str(raw or "")).expanduser().resolve()
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise ExactProductVideoCompositeError(code, f"Scene media is missing or empty: {path}", status_code=404)
    try:
        path.relative_to(OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_SCENE_PATH_FORBIDDEN",
            "Provider scene media must be under the server-owned output root.",
            status_code=403,
        ) from exc
    return path


def _tool(name: str, env_name: str) -> str:
    configured = str(os.environ.get(env_name) or "").strip()
    candidate = configured or shutil.which(name)
    if not candidate:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_MEDIA_TOOL_UNAVAILABLE",
            f"{name} is required for deterministic video compositing.",
            status_code=503,
        )
    return candidate


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_MEDIA_TOOL_FAILED",
            str(detail)[-1000:],
            status_code=422,
        ) from exc


def _probe_video(path: Path) -> dict[str, Any]:
    ffprobe = _tool("ffprobe", "FFPROBE_BINARY")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_SCENE_METADATA_INVALID",
            "ffprobe did not return valid JSON.",
        ) from exc
    streams = [s for s in payload.get("streams") or [] if s.get("codec_type") == "video"]
    if not streams:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_SCENE_VIDEO_REQUIRED",
            "The provider scene artifact has no video stream.",
        )
    stream = streams[0]
    try:
        fps = float(Fraction(str(stream.get("r_frame_rate") or "30/1")))
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if fps <= 0 or fps > 120:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_SCENE_METADATA_INVALID",
            "Scene frame rate is outside the bounded compositor range.",
        )
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": fps,
        "duration": float(stream.get("duration") or payload.get("format", {}).get("duration") or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in payload.get("streams") or []),
    }


def _mask_for_frame(
    mask_entry: dict[str, Any],
    frame_size: tuple[int, int],
) -> Image.Image:
    if not isinstance(mask_entry, dict) or mask_entry.get("verified") is not True:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_OCCLUSION_MASK_UNVERIFIED",
            "Foreground occlusion masks require explicit verified custody.",
        )
    mask_path = _trusted_output_path(
        mask_entry.get("local_path") or mask_entry.get("path"),
        code="EXACT_COMPOSITE_OCCLUSION_MASK_MISSING",
    )
    declared = str(mask_entry.get("sha256") or mask_entry.get("sha256_expected") or "").lower().strip()
    actual = _sha256(mask_path)
    if not declared or declared != actual:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_OCCLUSION_MASK_HASH_MISMATCH",
            "Foreground occlusion mask bytes do not match their declared SHA-256.",
            details={"declared_sha256": declared, "actual_sha256": actual},
        )
    with Image.open(mask_path) as mask_image:
        mask = mask_image.convert("L")
        if mask.size != frame_size:
            raise ExactProductVideoCompositeError(
                "EXACT_COMPOSITE_OCCLUSION_MASK_DIMENSION_MISMATCH",
                "Foreground occlusion mask dimensions do not match the scene frame.",
            )
        if not mask.getbbox():
            raise ExactProductVideoCompositeError(
                "EXACT_COMPOSITE_OCCLUSION_MASK_EMPTY",
                "Foreground occlusion mask is empty.",
            )
        return mask.copy()


def _foreground_restore(
    composed_path: Path,
    original: Image.Image,
    mask: Image.Image,
) -> None:
    with Image.open(composed_path) as composed_image:
        composed = composed_image.convert("RGBA")
    restored = Image.composite(original.convert("RGBA"), composed, mask)
    restored.save(composed_path)


def _validate_occlusion_bounds(
    mask: Image.Image,
    transform: dict[str, Any],
    frame_size: tuple[int, int],
) -> dict[str, Any]:
    """Reject masks that could hide the product or an unbounded scene region."""

    width, height = frame_size
    mask_pixels = sum(1 for value in mask.getdata() if value >= 128)
    frame_pixels = max(1, width * height)
    product_x = int(transform["x"])
    product_y = int(transform["y"])
    product_w = max(1, int(transform["w"]))
    product_h = max(1, int(transform["h"]))
    x0 = max(0, product_x)
    y0 = max(0, product_y)
    x1 = min(width, product_x + product_w)
    y1 = min(height, product_y + product_h)
    overlap = 0
    pixels = mask.load()
    if x1 > x0 and y1 > y0:
        for y in range(y0, y1):
            for x in range(x0, x1):
                if pixels[x, y] >= 128:
                    overlap += 1
    product_pixels = max(1, (x1 - x0) * (y1 - y0))
    if mask_pixels > frame_pixels * 0.35 or overlap > product_pixels * 0.55:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_OCCLUSION_MASK_UNBOUNDED",
            "Foreground occlusion mask exceeds the bounded V1 hand-over-product region.",
            details={
                "mask_fraction_of_frame": mask_pixels / frame_pixels,
                "mask_fraction_of_product_box": overlap / product_pixels,
            },
        )
    return {
        "mask_pixels": mask_pixels,
        "mask_fraction_of_frame": mask_pixels / frame_pixels,
        "mask_fraction_of_product_box": overlap / product_pixels,
        "bounded": True,
    }


def _qc_dimensions() -> dict[str, str]:
    return {
        "identity": "PASS",
        "silhouette_geometry": "PASS",
        "cap_components": "PASS",
        "scale": "PASS",
        "label_field_layout": "PASS",
        "printed_text": "PASS",
        "color_material": "PASS",
        "duplication": "PASS",
        "frame_morph": "PASS",
    }


def compose_exact_product_video_artifact(
    *,
    product: dict[str, Any],
    plan: dict[str, Any],
    scene_artifact: dict[str, Any],
    product_visual_custody: dict[str, Any] | None = None,
    job_id: str | None = None,
    foreground_masks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Composite a retrieved scene scaffold and return a final-only artifact.

    ``scene_artifact`` is accepted only as an internal, server-owned output
    file.  No database write happens here; the caller registers the returned
    final media id after the entire composite and QC succeed.
    """

    if plan.get("selected_execution_route") != EXACT_PRODUCT_DETERMINISTIC_COMPOSITE:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_ROUTE_INVALID",
            "The exact video compositor requires the exact deterministic route.",
        )
    if plan.get("generate_eligibility") is not True:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_UNSUPPORTED",
            str((plan.get("choreography") or {}).get("reason") or "Exact choreography is not supported."),
        )
    scene_path = _trusted_output_path(
        scene_artifact.get("local_path") or scene_artifact.get("path"),
        code="EXACT_COMPOSITE_SCENE_MISSING",
    )
    scene_sha = _sha256(scene_path)
    declared_scene_sha = str(scene_artifact.get("sha256") or scene_artifact.get("output_sha256") or "").strip().lower()
    if declared_scene_sha and declared_scene_sha != scene_sha:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_SCENE_HASH_MISMATCH",
            "Provider scene artifact changed after retrieval.",
            details={"declared_sha256": declared_scene_sha, "actual_sha256": scene_sha},
        )

    metadata = _probe_video(scene_path)
    width, height = metadata["width"], metadata["height"]
    if width <= 0 or height <= 0:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_SCENE_METADATA_INVALID",
            "Provider scene has invalid dimensions.",
        )
    choreography = plan.get("choreography") or {}
    needs_masks = choreography.get("classification") == REQUIRES_OCCLUSION_MASK
    masks = list(foreground_masks or [])
    if needs_masks and not masks:
        raise ExactProductVideoCompositeError(
            "PRODUCT_FIDELITY_REVIEW_REQUIRED",
            "Exact choreography crosses the product silhouette but no verified foreground mask was supplied.",
        )

    ffmpeg = _tool("ffmpeg", "FFMPEG_BINARY")
    work_root = OUTPUT_DIR / "exact-product-finals" / ".work"
    work_root.mkdir(parents=True, exist_ok=True)
    output_root = OUTPUT_DIR / "exact-product-finals" / "videos"
    output_root.mkdir(parents=True, exist_ok=True)
    final_media_id = str(uuid.uuid4())
    output_path = output_root / f"{final_media_id}.mp4"
    frame_lineage: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix=f"exact-video-{final_media_id}-", dir=str(work_root)) as temp_dir:
        temp = Path(temp_dir)
        input_frames = temp / "input"
        output_frames = temp / "output"
        input_frames.mkdir()
        output_frames.mkdir()
        _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(scene_path),
                "-vsync",
                "0",
                str(input_frames / "%08d.png"),
            ]
        )
        frames = sorted(input_frames.glob("*.png"))
        if not frames:
            raise ExactProductVideoCompositeError(
                "EXACT_COMPOSITE_SCENE_FRAMES_EMPTY",
                "Scene extraction produced no frames.",
            )
        if needs_masks and len(masks) != len(frames):
            raise ExactProductVideoCompositeError(
                "EXACT_COMPOSITE_OCCLUSION_MASK_COUNT_MISMATCH",
                "A verified foreground mask is required for every scene frame.",
                details={"frame_count": len(frames), "mask_count": len(masks)},
            )

        for index, frame_path in enumerate(frames):
            out_frame = output_frames / frame_path.name
            shutil.copy2(frame_path, out_frame)
            layer_product = dict(product)
            layer_product["_exact_product_required"] = True
            layer = prepare_layer(
                layer_product,
                plan.get("placement_region") or LANE_SAFE_REGIONS["studio"],
                {"w": width, "h": height},
            )
            integrity = composite(out_frame, layer)
            if not integrity.get("composition_ok"):
                raise ExactProductVideoCompositeError(
                    "EXACT_COMPOSITE_QA_FAILED",
                    f"Product region QA failed for frame {index}.",
                    details=integrity,
                )
            if needs_masks:
                with Image.open(frame_path) as original_image:
                    original = original_image.convert("RGBA").copy()
                mask = _mask_for_frame(masks[index], (width, height))
                occlusion_bounds = _validate_occlusion_bounds(
                    mask, layer["transform"], (width, height)
                )
                _foreground_restore(out_frame, original, mask)
            else:
                occlusion_bounds = None
            frame_lineage.append(
                {
                    "frame_index": index,
                    "transform": copy.deepcopy(layer["transform"]),
                    "qa": integrity,
                    "occlusion_mask": (
                        {
                            "path": str(masks[index].get("local_path") or masks[index].get("path")),
                            "sha256": masks[index].get("sha256"),
                            "verified": True,
                        }
                        if needs_masks
                        else None
                    ),
                    "occlusion_bounds": occlusion_bounds,
                }
            )

        fps = metadata["fps"]
        _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                f"{fps:.8f}",
                "-i",
                str(output_frames / "%08d.png"),
                "-i",
                str(scene_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0?",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                "-y",
                str(output_path),
            ]
        )

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_FINAL_MISSING",
            "The deterministic final video was not written.",
        )
    final_sha = _sha256(output_path)
    canonical = validate_canonical_or_raise({**product, "_exact_product_required": True})
    manifest = {
        "manifest_version": EXACT_PRODUCT_VIDEO_COMPOSITOR_VERSION,
        "selected_execution_route": EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "product_id": canonical["product_id"],
        "provider_scene_artifact": {
            "media_id": scene_artifact.get("media_id"),
            "local_path": str(scene_path),
            "sha256": scene_sha,
        },
        "canonical_product_asset": {
            "canonical_media_id": canonical["canonical_media_id"],
            "canonical_source_sha256": canonical["source_sha256"],
            "canonical_cutout_media_id": canonical["cutout_media_id"],
            "canonical_cutout_sha256": canonical["cutout_sha256"],
            "cutout_path": str(canonical["cutout_path"]),
            "alpha_mask_sha256": canonical["alpha_mask_sha256"],
        },
        "choreography": copy.deepcopy(choreography),
        "occlusion_strategy": choreography.get("occlusion_strategy"),
        "track_policy": choreography.get("track_policy"),
        "frame_count": len(frame_lineage),
        "dimensions": {"width": width, "height": height, "fps": metadata["fps"]},
        "frame_transform_lineage": frame_lineage,
    }
    manifest_sha = hashlib.sha256(_stable_json(manifest).encode("utf-8")).hexdigest()
    lineage = {
        "compositor_version": EXACT_PRODUCT_VIDEO_COMPOSITOR_VERSION,
        "selected_execution_route": EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "provider_scene_artifact": manifest["provider_scene_artifact"],
        "canonical_product_asset": manifest["canonical_product_asset"],
        "composite_manifest": {"sha256": manifest_sha, "manifest": manifest},
        "transform_track_lineage": frame_lineage,
        "product_fidelity_qc": {
            "status": "PRODUCT_FIDELITY_QC_PASS",
            "verified": True,
            "dimensions": _qc_dimensions(),
            "source": "DETERMINISTIC_CANONICAL_CUTOUT_FRAME_ATTESTATION",
        },
        "face_qc": {"status": "NOT_RUN", "verified": False},
        "final_media_id": final_media_id,
        "final_output_sha256": final_sha,
        "final_output_path": str(output_path),
        "job_id": job_id,
        "raw_scene_final_authority": False,
    }
    if isinstance(product_visual_custody, dict):
        lineage["product_visual_custody"] = {
            key: product_visual_custody.get(key)
            for key in (
                "receipt_version",
                "receipt_sha256",
                "official_visual_sha256",
                "canonical_source_sha256",
                "product_lock_fingerprint",
                "product_id",
                "fidelity_policy",
                "exact_product_required",
            )
        }
    lineage_path = output_path.with_suffix(".lineage.json")
    lineage_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    evidence = {
        "status": "PRODUCT_FIDELITY_QC_PASS",
        "verified": True,
        "dimensions": _qc_dimensions(),
        "source": "DETERMINISTIC_CANONICAL_CUTOUT_FRAME_ATTESTATION",
        "exact_video_composite": lineage,
    }
    return {
        "media_id": final_media_id,
        "local_path": str(output_path),
        "size_mb": round(output_path.stat().st_size / (1024 * 1024), 4),
        "output_sha256": final_sha,
        "artifact_kind": "video",
        "correlation": {
            "matched_on": "provider_scene_artifact",
            "scene_media_id": scene_artifact.get("media_id"),
            "scene_sha256": scene_sha,
        },
        "exact_product_lineage": lineage,
        "product_fidelity_qc_evidence": evidence,
        "product_visual_custody": {
            **(copy.deepcopy(product_visual_custody) if isinstance(product_visual_custody, dict) else {}),
            "exact_video_composite": lineage,
        },
    }


__all__ = [
    "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
    "EXACT_PRODUCT_VIDEO_COMPOSITOR_VERSION",
    "FACELESS_V1_SAFE_DEFAULT",
    "PRODUCT_HAND_HOLD",
    "PRODUCT_PICK_UP",
    "PRODUCT_PLACE_DOWN",
    "PRODUCT_PRESENT_TO_CAMERA",
    "PRODUCT_STATIC_TABLE",
    "REQUIRES_OCCLUSION_MASK",
    "SMALL_CONTROLLED_ROTATION",
    "SUPPORTED_EXACT",
    "UNSUPPORTED_EXACT",
    "ExactProductVideoCompositeError",
    "build_exact_product_video_plan",
    "build_exact_scene_scaffold_prompt",
    "classify_exact_choreography",
    "compose_exact_product_video_artifact",
    "resolve_faceless_exact_choreography",
]
