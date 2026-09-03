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
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

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


# Canonical (ADR-008) prompt section headers ("SECTION N - NAME") whose bodies
# describe RENDERING or HOLDING the product. Both exact-video scaffolds remove
# these sections wholesale and replace them with the interaction-zone
# choreography below; otherwise the canonical prompt contradicts the
# provider's scene-only role. HYBRID preserves its presenter and Faceless keeps
# only hands/forearms outside the reserved product region.
_CANONICAL_PRODUCT_VISUAL_SECTIONS = (
    "PRODUCT TRUTH LOCK",
    "CONTINUITY & STATE LOCK",
    "VISUAL STORY",
    "SHOT & CAMERA RULES",
    "CTA & END FRAME",
)
_CANONICAL_SECTION_RE = re.compile(
    r"^\s*SECTION\s+\d+\s*[-–]\s*(.+?)\s*$", re.IGNORECASE
)

# Extra line-level markers used ONLY on the presenter-visible path to scrub any
# product-render / product-hold prose that survives in the kept sections.
_PRESENTER_EXTRA_FORBIDDEN_MARKERS = (
    "generic prop",
    "real health & personal care",
    "printed label",
    "bottle shot",
    "packshot",
    "hero product",
    "in hand",
    "held at",
    "held by",
    "holding the product",
    "uploaded product image",
    "exact visual reference",
    "match its colour",
    "match its color",
    "natural grip",
)

_PRODUCT_WITHHELD_SOURCE_MARKERS = (
    "product",
    "packaging",
    "bottle",
    "label",
    "logo",
    "brand mark",
    "generic prop",
)
_DIALOGUE_SECTION_NAMES = (
    "SPOKEN DIALOGUE",
    "DIALOGUE",
    "VOICEOVER",
    "VOICE OVER",
    "AUDIO",
)


def _drop_canonical_product_sections(
    prompt: str, drop_names: tuple[str, ...]
) -> str:
    """Remove whole ``SECTION N - NAME`` blocks whose name is product-describing.

    Dropping runs from a matched product section header until the next canonical
    section header (any name), so only the product-visual sections are removed
    and the speech/role sections are preserved verbatim.
    """

    drop_upper = {name.upper() for name in drop_names}
    kept: list[str] = []
    dropping = False
    for raw_line in (prompt or "").splitlines():
        match = _CANONICAL_SECTION_RE.match(raw_line)
        if match:
            dropping = match.group(1).strip().upper() in drop_upper
            if dropping:
                continue
        if not dropping:
            kept.append(raw_line)
    return "\n".join(kept).strip()


def _strip_product_withheld_source_cues(prompt: str) -> str:
    """Remove provider product cues while preserving governed spoken copy."""

    kept: list[str] = []
    current_section = ""
    for raw_line in (prompt or "").splitlines():
        match = _CANONICAL_SECTION_RE.match(raw_line)
        if match:
            current_section = match.group(1).strip().upper()
            kept.append(raw_line)
            continue
        if current_section in _DIALOGUE_SECTION_NAMES:
            kept.append(raw_line)
            continue
        lowered = raw_line.lower()
        if any(marker in lowered for marker in _PRODUCT_WITHHELD_SOURCE_MARKERS):
            continue
        kept.append(raw_line)
    return "\n".join(kept).strip()


def _safe_product_withheld_scene_context(scene_context: str) -> str:
    """Keep only context sentences that cannot instruct product rendering."""

    safe_sentences = []
    for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", str(scene_context or "")):
        sentence = sentence.strip()
        if not sentence:
            continue
        lowered = sentence.lower()
        if any(marker in lowered for marker in _PRODUCT_WITHHELD_SOURCE_MARKERS):
            continue
        safe_sentences.append(sentence)
    return " ".join(safe_sentences)


def build_exact_scene_scaffold_prompt(
    base_prompt: str,
    plan: dict[str, Any],
    *,
    scene_context: str = "",
    presenter_visible: bool = False,
) -> str:
    """Make a provider prompt that cannot authorize provider product pixels.

    ``presenter_visible`` distinguishes the two exact-composite scaffolds that
    share this builder:

    * FACELESS (default): the provider must not render a face — only the scene,
      hands, and torso outside the empty reserved product region.
    * HYBRID (``presenter_visible=True``): the on-camera human presenter stays
      fully visible and lip-synced to the dialogue; only the *product* is
      withheld for the deterministic compositor.  The standard HYBRID compiler
      integrates "presenter holds and renders the exact product" throughout its
      visual sections, which contradicts a scene-only scaffold, so those
      product-visual sections are DROPPED for both exact routes and replaced by
      an explicit
      presenter–product interaction-zone choreography: the presenter presents
      TOWARD a reserved (empty) product region instead of holding the product
      (hand-hold requires per-frame occlusion masks the compositor does not
      have). FACELESS receives the corresponding face-free interaction zone.
      Speech (dialogue/voice) and role sections are preserved.
    """

    raw_prompt = _strip_product_withheld_source_cues(_drop_canonical_product_sections(
        str(base_prompt or ""), _CANONICAL_PRODUCT_VISUAL_SECTIONS
    ))
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
    if presenter_visible:
        forbidden_directive_markers = (
            forbidden_directive_markers + _PRESENTER_EXTRA_FORBIDDEN_MARKERS
        )
    safe_lines = [
        line
        for line in raw_prompt.splitlines()
        if not any(marker in line.lower() for marker in forbidden_directive_markers)
    ]
    prompt = augment_prompt_scene_only("\n".join(safe_lines))
    prompt = prompt.replace(
        "Reserve the declared placement bounding box as a clear unobstructed "
        "region, provide a physically plausible contact surface and compatible "
        "scene lighting, and do not place foreground objects, hands, text, "
        "shadows, reflections, or props across that region.",
        "Provide an ordinary physically plausible contact surface and compatible "
        "scene lighting. Keep the scene naturally sparse and unobstructed. Never "
        "visualize any compositor placement instruction or guide.",
    )
    faceless_priority_preamble = ""
    additions = [
        "EXECUTION ROUTE: EXACT_PRODUCT_DETERMINISTIC_COMPOSITE.",
        "PROVIDER ROLE: scene scaffold only; the provider output is an internal plate and is never the final product artifact.",
        "Do not generate product pixels, packaging, label, logo, cap, replacement bottle, product text, product shadow, or product reflection.",
        "COMPOSITOR MOTION CONTRACT: use a locked-off camera and a stable ordinary "
        "contact surface. Any later foreground insertion is system-owned and must "
        "not be represented, marked, or illustrated with guides or proxy pixels.",
        "NO PLACEHOLDER OR GUIDE: do not render a blank card, sheet of paper, "
        "rectangle, box, corner brackets, markers, outline, guide, matte, screen, "
        "or sign. Show only an ordinary unobstructed scene surface.",
        "SPARSE PROP FIELD: do not render bottle-shaped containers, vials, jars, "
        "tubes, dispensers, or freestanding upright proxy props anywhere in frame. "
        "Keep the scene sparse and natural.",
    ]
    if presenter_visible:
        # HYBRID: the governed on-camera presenter is REQUIRED and fully visible.
        # The reserved product region is an intentional presenter-product
        # interaction zone — the presenter presents TOWARD it (never holds the
        # product, which would need per-frame occlusion masks). Only the product
        # pixels are withheld for the compositor; the presenter is never
        # suppressed and never reduced to a generic talking head.
        additions.append(
            "PRESENTER (REQUIRED, FULLY VISIBLE): render the governed on-camera "
            "human presenter/spokesperson fully visible and lip-synced to the "
            "spoken dialogue, visually active across the entire selling beat — "
            "never a static or generic talking head beside a pack shot."
        )
        additions.append(
            "PRESENTER-PRODUCT INTERACTION ZONE: the reserved product region is an "
            "intentional interaction zone. The presenter must visibly acknowledge "
            "and present toward it — point, gesture, and frame toward the reserved "
            "region and coordinate body language with its position, as if "
            "presenting the product to the viewer."
        )
        additions.append(
            "RESERVED REGION STAYS EMPTY: leave the reserved product region "
            "completely empty in the provider output. The presenter may gesture "
            "around and toward the region but must NOT hold, grab, occlude, "
            "overlap, or pass a hand, arm, or object behind or in front of it — "
            "the exact product is inserted there only by the deterministic "
            "compositor."
        )
    else:
        # Put the FACELESS visual contract before the preserved dialogue.  The
        # provider otherwise tends to cast nouns from the opening spoken copy
        # (for example, "anak") before it reaches a trailing negative prompt.
        # Dialogue remains byte-for-byte present for audio generation; it is
        # simply subordinated to an explicit visual grammar at prompt start.
        faceless_priority_preamble = (
            "FACELESS VISUAL CONTRACT — HIGHEST PRIORITY; THIS OVERRIDES ALL "
            "VISUAL IMPLICATIONS OF THE SPOKEN DIALOGUE. DIALOGUE IS AUDIO ONLY "
            "and must never visually cast, instantiate, illustrate, or cut to a "
            "speaker or any person mentioned or implied by the words. Absolutely "
            "no visible face, head, eyes, or mouth anywhere: no babies, children, "
            "adult faces or heads, reflections, portraits, screens, photos, or "
            "background people. Human presence is limited to adult hands, "
            "forearms, arms, and partial torso with every head fully outside the "
            "frame for the entire clip. The reserved product interaction region "
            "is visually invisible: render no white card, placeholder frame, "
            "rectangle, box, outline, corner marks, guide, matte, screen, sign, "
            "proxy object, bottle-like prop, or upright container. Keep a sparse, "
            "natural scene. Adult hands must perform a meaningful selling gesture "
            "around and toward the invisible future product location without "
            "crossing or occluding it. Render no product pixels."
        )
        additions.append(
            "FACELESS: absolutely no visible face, head, eyes, or mouth anywhere, "
            "including in reflections, portraits, photos, screens, or background "
            "people; only hands, forearms, arms, and partial torso may appear."
        )
        additions.append(
            "DIALOGUE IS AUDIO ONLY: never visualize, cast, illustrate, or cut to "
            "a person mentioned or implied by the spoken words. Do not depict a "
            "baby, child, adult head, or adult face, directly or indirectly; show "
            "only adult hands, forearms, and partial torso."
        )
        additions.append(
            "MEANINGFUL FACELESS INTERACTION: adult hands and forearms must make "
            "a clear selling gesture around and toward the invisible future "
            "product location, while never crossing, occluding, holding, or "
            "touching that region. Do not visualize the region itself."
        )
        additions.append(
            "PRODUCT-FREE SCENE: do not place a product, proxy bottle, product-like "
            "prop, product text, product shadow, or product reflection anywhere in "
            "the provider output."
        )
    safe_context = _safe_product_withheld_scene_context(scene_context)
    if safe_context:
        additions.append(f"SCENE CONTEXT (PRODUCT-WITHHELD): {safe_context}")
    if faceless_priority_preamble:
        return f"{faceless_priority_preamble}\n\n{prompt}\n\n" + " ".join(additions)
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


def _dynamic_choreography(choreography: Mapping[str, Any]) -> bool:
    choreography_id = _norm_id(choreography.get("choreography_id"))
    track_policy = _norm_id(choreography.get("track_policy"))
    expected_policy = {
        PRODUCT_STATIC_TABLE: "STATIC_RIGID_PRODUCT_TRUTH_TRACK",
        PRODUCT_PRESENT_TO_CAMERA: "STATIC_RIGID_PRODUCT_TRUTH_TRACK",
        SMALL_CONTROLLED_ROTATION: "BOUNDED_RIGID_PRODUCT_TRUTH_TRACK",
        PRODUCT_HAND_HOLD: "EXPLICIT_MASKED_RIGID_PRODUCT_TRUTH_TRACK",
        PRODUCT_PICK_UP: "EXPLICIT_MASKED_RIGID_PRODUCT_TRUTH_TRACK",
        PRODUCT_PLACE_DOWN: "EXPLICIT_MASKED_RIGID_PRODUCT_TRUTH_TRACK",
    }.get(choreography_id)
    if expected_policy and track_policy and track_policy != expected_policy:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_TRACK_POLICY_MISMATCH",
            "Exact choreography and transform-track policy disagree.",
            details={
                "choreography_id": choreography_id,
                "expected_track_policy": expected_policy,
                "observed_track_policy": track_policy,
            },
        )
    if track_policy == "STATIC_RIGID_PRODUCT_TRUTH_TRACK":
        return False
    if track_policy in {
        "BOUNDED_RIGID_PRODUCT_TRUTH_TRACK",
        "EXPLICIT_MASKED_RIGID_PRODUCT_TRUTH_TRACK",
    }:
        return True
    return choreography_id in {
        PRODUCT_HAND_HOLD,
        PRODUCT_PICK_UP,
        PRODUCT_PLACE_DOWN,
        SMALL_CONTROLLED_ROTATION,
    }


def write_exact_product_lineage_sidecar(
    output_file: str | Path,
    lineage: Mapping[str, Any],
) -> Path:
    """Atomically persist the current exact-product custody lineage."""

    output_path = Path(output_file).expanduser().resolve()
    if not output_path.exists() or not output_path.is_file():
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_FINAL_MISSING",
            f"Exact compositor output is missing: {output_path}",
        )
    lineage_path = output_path.with_suffix(".lineage.json")
    temp_path = lineage_path.with_suffix(lineage_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(dict(lineage), indent=2), encoding="utf-8")
    os.replace(temp_path, lineage_path)
    return lineage_path


def _normalise_transform_track(
    raw_track: Any,
    *,
    base_transform: Mapping[str, Any],
    frame_count: int,
    frame_size: tuple[int, int],
) -> list[dict[str, Any]]:
    if isinstance(raw_track, Mapping):
        verified = raw_track.get("verified") is True
        entries = raw_track.get("frames") or raw_track.get("track") or []
    else:
        verified = False
        entries = raw_track or []
    if not isinstance(entries, list) or len(entries) != frame_count:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_TRANSFORM_TRACK_COUNT_MISMATCH",
            "Dynamic exact-product choreography requires one transform for every scene frame.",
            details={"frame_count": frame_count, "track_count": len(entries) if isinstance(entries, list) else 0},
        )
    if not verified and not all(isinstance(item, Mapping) and item.get("verified") is True for item in entries):
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_TRANSFORM_TRACK_UNVERIFIED",
            "Dynamic exact-product transforms require explicit evidence-backed verification.",
        )
    width, height = frame_size
    expected_ratio = float(base_transform["w"]) / max(1.0, float(base_transform["h"]))
    output: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        raw = entry.get("transform") if isinstance(entry, Mapping) and isinstance(entry.get("transform"), Mapping) else entry
        if not isinstance(raw, Mapping):
            raise ExactProductVideoCompositeError("EXACT_COMPOSITE_TRANSFORM_TRACK_INVALID", f"Frame {index} has no transform.")
        try:
            transform = {
                **dict(base_transform),
                **{key: raw[key] for key in ("x", "y", "w", "h") if key in raw},
                "rotation_degrees": float(raw.get("rotation_degrees", base_transform.get("rotation_degrees", 0.0))),
                "perspective_skew_x": float(raw.get("perspective_skew_x", base_transform.get("perspective_skew_x", 0.0))),
            }
            x, y, w, h = (int(transform[key]) for key in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ExactProductVideoCompositeError("EXACT_COMPOSITE_TRANSFORM_TRACK_INVALID", f"Frame {index} has invalid geometry.") from exc
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
            raise ExactProductVideoCompositeError("EXACT_COMPOSITE_TRANSFORM_TRACK_OUT_OF_BOUNDS", f"Frame {index} leaves the scene canvas.")
        if abs((w / max(1.0, h)) - expected_ratio) > max(0.08, expected_ratio * 0.08):
            raise ExactProductVideoCompositeError("EXACT_COMPOSITE_TRANSFORM_ASPECT_DRIFT", f"Frame {index} changes the product aspect ratio.")
        output.append(transform)
    return output


def _plate_product_scan(
    frame_path: Path,
    *,
    reserved_box: Mapping[str, Any],
    canonical_cutout_path: Path,
    static_scene: bool,
) -> dict[str, Any]:
    """Perform a conservative provider-plate impostor/duplicate scan.

    The scan is intentionally deterministic and conservative: a large,
    vertical, high-contrast object in the reserved static product box is an
    impostor; outside the box only a reference-like component is rejected.
    It is not a general object detector and never substitutes for visual QC.
    """

    with Image.open(frame_path) as source:
        image = source.convert("RGB")
    scan_width = 160
    scan_height = max(1, round(image.height * scan_width / image.width))
    small = image.resize((scan_width, scan_height))
    px = small.load()
    corners = [px[0, 0], px[scan_width - 1, 0], px[0, scan_height - 1], px[scan_width - 1, scan_height - 1]]
    bg = tuple(round(sum(color[channel] for color in corners) / len(corners)) for channel in range(3))
    mask = [[False] * scan_width for _ in range(scan_height)]
    for y in range(scan_height):
        for x in range(scan_width):
            color = px[x, y]
            distance = sum((int(color[channel]) - int(bg[channel])) ** 2 for channel in range(3)) ** 0.5
            mask[y][x] = distance >= 42.0
    visited = [[False] * scan_width for _ in range(scan_height)]
    components: list[dict[str, Any]] = []
    for y0 in range(scan_height):
        for x0 in range(scan_width):
            if visited[y0][x0] or not mask[y0][x0]:
                continue
            stack = [(x0, y0)]
            visited[y0][x0] = True
            points: list[tuple[int, int]] = []
            while stack:
                x, y = stack.pop()
                points.append((x, y))
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < scan_width and 0 <= ny < scan_height and not visited[ny][nx] and mask[ny][nx]:
                        visited[ny][nx] = True
                        stack.append((nx, ny))
            if len(points) < 10:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            components.append({
                "area": len(points),
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs) + 1,
                "h": max(ys) - min(ys) + 1,
            })
    scale_x = scan_width / max(1, image.width)
    scale_y = scan_height / max(1, image.height)
    rx = float(reserved_box.get("x") or 0) * scale_x
    ry = float(reserved_box.get("y") or 0) * scale_y
    rw = float(reserved_box.get("w") or 0) * scale_x
    rh = float(reserved_box.get("h") or 0) * scale_y
    reserved_hits = [
        component
        for component in components
        if component["h"] >= component["w"] * 1.15
        and component["area"] >= 18
        and component["x"] < rx + rw
        and component["x"] + component["w"] > rx
        and component["y"] < ry + rh
        and component["y"] + component["h"] > ry
    ]
    # A reference-like duplicate outside the reserved box is compared to the
    # canonical cutout; generic background objects are not rejected solely by
    # being vertical.
    reference_like = 0
    try:
        with Image.open(canonical_cutout_path) as cutout:
            cutout_rgba = cutout.convert("RGBA")
            alpha = cutout_rgba.getchannel("A")
            alpha_box = alpha.getbbox()
            template_alpha = alpha.crop(alpha_box) if alpha_box else None
        if template_alpha is not None:
            template_mask = template_alpha.resize((32, 64)).point(lambda value: 255 if value >= 128 else 0)
            for component in components:
                if component in reserved_hits or component["h"] < component["w"] * 1.15 or component["area"] < 18:
                    continue
                x = round(component["x"] / scale_x)
                y = round(component["y"] / scale_y)
                w = max(1, round(component["w"] / scale_x))
                h = max(1, round(component["h"] / scale_y))
                candidate = image.crop((x, y, min(image.width, x + w), min(image.height, y + h))).resize((32, 64))
                candidate_px = candidate.load()
                candidate_mask = [
                    sum(
                        (int(candidate_px[cx, cy][channel]) - int(bg[channel])) ** 2
                        for channel in range(3)
                    ) ** 0.5
                    >= 42.0
                    for cy in range(64)
                    for cx in range(32)
                ]
                template_mask_values = [
                    template_mask.getpixel((cx, cy)) >= 128
                    for cy in range(64)
                    for cx in range(32)
                ]
                intersection = sum(left and right for left, right in zip(candidate_mask, template_mask_values))
                union = sum(left or right for left, right in zip(candidate_mask, template_mask_values))
                mask_iou = intersection / max(1, union)
                if mask_iou >= 0.72:
                    reference_like += 1
    except (OSError, ValueError):
        reference_like = 0
    suspicious = len(reserved_hits) if static_scene else 0
    suspicious += reference_like
    return {
        "components_scanned": len(components),
        "reserved_region_hits": len(reserved_hits),
        "reference_like_duplicates": reference_like,
        "suspicious_product_components": suspicious,
        "status": "PASS" if suspicious == 0 else "FAIL",
        "method": "DETERMINISTIC_CONTRAST_COMPONENT_AND_CANONICAL_REFERENCE_SCAN",
    }


def _qc_dimensions(
    frame_lineage: Sequence[Mapping[str, Any]],
    *,
    dynamic_track: bool,
    dynamic_track_verified: bool,
    plate_scans: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    region_verified = bool(frame_lineage) and all(
        row.get("qa", {}).get("composition_ok") is True
        and row.get("qa", {}).get("product_region_match") is True
        for row in frame_lineage
    )
    plate_clean = bool(plate_scans) and all(scan.get("status") == "PASS" for scan in plate_scans)
    transforms = [row.get("transform") or {} for row in frame_lineage]
    static_transform = bool(transforms) and all(transform == transforms[0] for transform in transforms[1:])
    geometry = {
        "status": "PASS" if region_verified else "NOT_VERIFIED",
        "method": "CANONICAL_CUTOUT_REGION_MATCH_EVERY_FRAME",
        "frames_measured": len(frame_lineage),
    }
    measured = {
        "identity": {"status": "PASS" if region_verified else "NOT_VERIFIED", "method": "CANONICAL_CUTOUT_REGION_MATCH_EVERY_FRAME"},
        "silhouette_geometry": geometry,
        "cap_components": {"status": "PASS" if region_verified else "NOT_VERIFIED", "method": "CANONICAL_CUTOUT_COMPONENTS_AND_ALPHA"},
        "scale": {"status": "PASS" if region_verified else "NOT_VERIFIED", "method": "BOUNDED_FRAME_TRANSFORM_MEASUREMENT"},
        "label_field_layout": {"status": "PASS" if region_verified else "NOT_VERIFIED", "method": "CANONICAL_CUTOUT_PIXELS_AND_REGION_MATCH"},
        "printed_text": {"status": "PASS" if region_verified else "NOT_VERIFIED", "method": "CANONICAL_CUTOUT_BYTES_ONLY_NO_PROVIDER_TEXT"},
        "color_material": {"status": "PASS" if region_verified else "NOT_VERIFIED", "method": "CANONICAL_CUTOUT_REGION_MATCH_EVERY_FRAME"},
        "duplication": {"status": "PASS" if plate_clean else "NOT_VERIFIED", "method": "DETERMINISTIC_PLATE_SCAN", "scans": list(plate_scans)},
        "frame_morph": {
            "status": (
                "PASS"
                if region_verified
                and (
                    (dynamic_track and dynamic_track_verified)
                    or (not dynamic_track and static_transform)
                )
                else "NOT_VERIFIED"
            ),
            "method": (
                "VERIFIED_FRAME_INDEXED_TRANSFORM_TRACK_AND_PER_FRAME_REGION_ATTESTATION"
                if dynamic_track
                else "STATIC_TRANSFORM_AND_PER_FRAME_REGION_ATTESTATION"
            ),
        },
    }
    return measured


def compose_exact_product_video_artifact(
    *,
    product: dict[str, Any],
    plan: dict[str, Any],
    scene_artifact: dict[str, Any],
    product_visual_custody: dict[str, Any] | None = None,
    job_id: str | None = None,
    foreground_masks: list[dict[str, Any]] | None = None,
    transform_track: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
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
    dynamic_track_required = _dynamic_choreography(choreography)
    if dynamic_track_required and transform_track is None:
        raise ExactProductVideoCompositeError(
            "EXACT_COMPOSITE_TRANSFORM_TRACK_REQUIRED",
            "Held, pickup, place-down, rotation and presentation choreography requires an evidence-backed frame-indexed transform track.",
        )
    if dynamic_track_required:
        needs_masks = True
    dynamic_track_verified = False
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
    identity_material = {
        "scene_sha256": scene_sha,
        "product_id": product.get("id") or product.get("product_id"),
        "canonical_cutout_sha256": plan.get("product_truth", {}).get("canonical_cutout_sha256"),
        "choreography": choreography,
        "placement_region": plan.get("placement_region"),
        "transform_track": transform_track,
        "foreground_masks": [
            {"sha256": mask.get("sha256"), "frame_index": index}
            for index, mask in enumerate(masks)
            if isinstance(mask, Mapping)
        ],
    }
    final_media_id = "exact-" + hashlib.sha256(_stable_json(identity_material).encode("utf-8")).hexdigest()[:32]
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

        layer_product = dict(product)
        layer_product["_exact_product_required"] = True
        base_layer = prepare_layer(
            layer_product,
            plan.get("placement_region") or LANE_SAFE_REGIONS["studio"],
            {"w": width, "h": height},
        )
        base_transform = dict(base_layer["transform"])
        frame_transforms = (
            _normalise_transform_track(
                transform_track,
                base_transform=base_transform,
                frame_count=len(frames),
                frame_size=(width, height),
            )
            if dynamic_track_required
            else [dict(base_transform) for _ in frames]
        )
        dynamic_track_verified = bool(dynamic_track_required and frame_transforms)
        plate_scans: list[dict[str, Any]] = []

        for index, frame_path in enumerate(frames):
            out_frame = output_frames / frame_path.name
            shutil.copy2(frame_path, out_frame)
            layer = {**base_layer, "transform": frame_transforms[index]}
            plate_scan = _plate_product_scan(
                frame_path,
                reserved_box=layer["transform"],
                canonical_cutout_path=Path(layer["asset_ref"]),
                static_scene=not dynamic_track_required,
            )
            plate_scans.append(plate_scan)
            if plate_scan.get("suspicious_product_components", 0) > 0:
                raise ExactProductVideoCompositeError(
                    "EXACT_COMPOSITE_PLATE_CONTAINS_PRODUCT_IMPOSTOR",
                    f"Scene-only plate contains a product-like object before canonical compositing on frame {index}.",
                    details={"frame_index": index, "plate_scan": plate_scan},
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

        qc_dimensions = _qc_dimensions(
            frame_lineage,
            dynamic_track=dynamic_track_required,
            dynamic_track_verified=dynamic_track_verified,
            plate_scans=plate_scans,
        )
        qc_verified = bool(qc_dimensions) and all(
            dimension.get("status") == "PASS"
            for dimension in qc_dimensions.values()
        )
        qc_status = "PRODUCT_FIDELITY_QC_PASS" if qc_verified else "PRODUCT_FIDELITY_REVIEW_REQUIRED"
        transform_track_evidence = {
            "required": dynamic_track_required,
            "verified": bool(frame_transforms) and (
                dynamic_track_verified or not dynamic_track_required
            ),
            "track_policy": choreography.get("track_policy"),
            "source": (
                "EVIDENCE_BACKED_FRAME_INDEXED_INPUT"
                if dynamic_track_required
                else "DETERMINISTIC_STATIC_PLAN"
            ),
            "frame_count": len(frame_transforms),
            "sha256": hashlib.sha256(
                _stable_json(frame_transforms).encode("utf-8")
            ).hexdigest(),
        }

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
            "provider_operation_id": (
                (scene_artifact.get("correlation") or {}).get("provider_operation_id")
                if isinstance(scene_artifact.get("correlation"), Mapping)
                else None
            ),
            "provider_operation_id_source": (
                (scene_artifact.get("correlation") or {}).get("provider_operation_id_source")
                if isinstance(scene_artifact.get("correlation"), Mapping)
                else None
            ),
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
        "transform_track_evidence": transform_track_evidence,
        "frame_transform_lineage": frame_lineage,
        "plate_scan_lineage": plate_scans,
        "product_fidelity_qc_dimensions": qc_dimensions,
    }
    manifest_sha = hashlib.sha256(_stable_json(manifest).encode("utf-8")).hexdigest()
    lineage = {
        "compositor_version": EXACT_PRODUCT_VIDEO_COMPOSITOR_VERSION,
        "selected_execution_route": EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "provider_scene_artifact": manifest["provider_scene_artifact"],
        "canonical_product_asset": manifest["canonical_product_asset"],
        "composite_manifest": {"sha256": manifest_sha, "manifest": manifest},
        "transform_track": transform_track_evidence,
        "transform_track_lineage": frame_lineage,
        "product_fidelity_qc": {
            "status": qc_status,
            "verified": qc_verified,
            "dimensions": qc_dimensions,
            "source": "DETERMINISTIC_CANONICAL_CUTOUT_FRAME_ATTESTATION",
            "plate_scans": plate_scans,
        },
        "face_qc": {"status": "NOT_RUN", "verified": False},
        "final_media_id": final_media_id,
        "final_output_sha256": final_sha,
        "final_output_path": str(output_path),
        "compositor_output": {
            "media_id": final_media_id,
            "local_path": str(output_path),
            "sha256": final_sha,
        },
        "final_registered_media": None,
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
    lineage_path = write_exact_product_lineage_sidecar(output_path, lineage)
    evidence = {
        "status": qc_status,
        "verified": qc_verified,
        "dimensions": qc_dimensions,
        "source": "DETERMINISTIC_CANONICAL_CUTOUT_FRAME_ATTESTATION",
        "plate_scans": plate_scans,
        "exact_video_composite": lineage,
    }
    return {
        "media_id": final_media_id,
        "local_path": str(output_path),
        "lineage_path": str(lineage_path),
        "size_mb": round(output_path.stat().st_size / (1024 * 1024), 4),
        "output_sha256": final_sha,
        "artifact_kind": "video",
        "correlation": {
            "matched_on": "provider_scene_artifact",
            "scene_media_id": scene_artifact.get("media_id"),
            "scene_sha256": scene_sha,
            "provider_operation_id": (
                (scene_artifact.get("correlation") or {}).get("provider_operation_id")
                if isinstance(scene_artifact.get("correlation"), Mapping)
                else None
            ),
            "provider_operation_id_source": (
                (scene_artifact.get("correlation") or {}).get("provider_operation_id_source")
                if isinstance(scene_artifact.get("correlation"), Mapping)
                else None
            ),
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
    "write_exact_product_lineage_sidecar",
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
