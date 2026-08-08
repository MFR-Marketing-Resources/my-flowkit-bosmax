"""Montage R1 — per-scene reference policy validated by the EXISTING contract.

Does NOT create a new enforcement engine. Each scene/beat declares a
SCENE_REFERENCE_POLICY; the declaration is mapped to a transport/source mode
and checked with flow_mode_reference_contract.validate_reference_count.

This generalizes the crude "last scene only gets product" rule into an
explicit per-scene product-truth need so packaging cannot drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence

from agent.services import flow_mode_reference_contract as refc

ERR_UNKNOWN_SCENE_REFERENCE_POLICY = "ERR_UNKNOWN_SCENE_REFERENCE_POLICY"
ERR_SCENE_REFERENCE_POLICY_VIOLATION = "ERR_SCENE_REFERENCE_POLICY_VIOLATION"
ERR_SCENE_PRODUCT_MEDIA_REQUIRED = "ERR_SCENE_PRODUCT_MEDIA_REQUIRED"
ERR_SCENE_REFERENCE_INHERIT_MISSING = "ERR_SCENE_REFERENCE_INHERIT_MISSING"


class SceneReferencePolicy(str, Enum):
    NONE = "NONE"
    PRODUCT_ANCHOR = "PRODUCT_ANCHOR"
    START_FRAME = "START_FRAME"
    START_END_FRAMES = "START_END_FRAMES"
    AVATAR_PRODUCT = "AVATAR_PRODUCT"
    INGREDIENT_REFERENCES = "INGREDIENT_REFERENCES"
    INHERIT_PREVIOUS_CLIP = "INHERIT_PREVIOUS_CLIP"


# Map policy → (transport_mode, source_mode, expected min refs for declaration)
# validated against the existing contract bounds.
_POLICY_MODE: dict[SceneReferencePolicy, tuple[str, Optional[str]]] = {
    SceneReferencePolicy.NONE: ("T2V", "T2V"),
    SceneReferencePolicy.PRODUCT_ANCHOR: ("F2V", "HYBRID"),
    SceneReferencePolicy.START_FRAME: ("F2V", "FRAMES"),
    SceneReferencePolicy.START_END_FRAMES: ("F2V", "FRAMES"),
    SceneReferencePolicy.AVATAR_PRODUCT: ("F2V", "HYBRID"),
    SceneReferencePolicy.INGREDIENT_REFERENCES: ("I2V", "INGREDIENTS"),
    SceneReferencePolicy.INHERIT_PREVIOUS_CLIP: ("T2V", "T2V"),  # refs come from prior clip, not new count
}


def parse_scene_reference_policy(value: Any) -> SceneReferencePolicy:
    raw = str(value or "").strip().upper()
    try:
        return SceneReferencePolicy(raw)
    except ValueError as exc:
        raise ValueError(
            f"{ERR_UNKNOWN_SCENE_REFERENCE_POLICY}: '{value}' is not a valid "
            f"SCENE_REFERENCE_POLICY — allowed: {[p.value for p in SceneReferencePolicy]}"
        ) from exc


def policy_requires_product_media(policy: SceneReferencePolicy) -> bool:
    return policy in {
        SceneReferencePolicy.PRODUCT_ANCHOR,
        SceneReferencePolicy.START_FRAME,
        SceneReferencePolicy.START_END_FRAMES,
        SceneReferencePolicy.AVATAR_PRODUCT,
        SceneReferencePolicy.INGREDIENT_REFERENCES,
    }


def policy_image_generation_required(policy: SceneReferencePolicy) -> bool:
    """Whether the scene expects an image-first plate before video."""
    return policy in {
        SceneReferencePolicy.START_FRAME,
        SceneReferencePolicy.START_END_FRAMES,
        SceneReferencePolicy.PRODUCT_ANCHOR,
        SceneReferencePolicy.AVATAR_PRODUCT,
        SceneReferencePolicy.INGREDIENT_REFERENCES,
    }


def policy_video_generation_required(policy: SceneReferencePolicy) -> bool:
    # All policies except pure inherit may still need a video clip for assembly;
    # inherit reuses previous clip media and does not generate a new one.
    return policy is not SceneReferencePolicy.INHERIT_PREVIOUS_CLIP


@dataclass(frozen=True)
class SceneReferenceDeclaration:
    """Per-scene / per-beat reference declaration for Montage."""

    scene_id: str
    policy: SceneReferencePolicy
    reference_media_ids: tuple[str, ...] = ()
    product_media_id: Optional[str] = None
    previous_clip_media_id: Optional[str] = None
    image_generation_required: Optional[bool] = None
    video_generation_required: Optional[bool] = None

    def effective_image_generation_required(self) -> bool:
        if self.image_generation_required is not None:
            return bool(self.image_generation_required)
        return policy_image_generation_required(self.policy)

    def effective_video_generation_required(self) -> bool:
        if self.video_generation_required is not None:
            return bool(self.video_generation_required)
        return policy_video_generation_required(self.policy)


def validate_scene_reference_declaration(
    decl: SceneReferenceDeclaration,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Validate one scene against the EXISTING mode reference contract.

    Returns (ok, error_code, human_detail).

    Counting rules (product truth vs engine slots):
    - PRODUCT_ANCHOR / AVATAR_PRODUCT: product_media_id alone satisfies HYBRID (1).
    - START_FRAME / START_END_FRAMES: only reference_media_ids count as frame slots;
      product_media_id is still required as product-truth binding but does not
      invent a missing end frame.
    - INGREDIENT_REFERENCES: only reference_media_ids count toward I2V 2–3.
    - NONE / INHERIT: no new engine ref count (inherit needs previous clip id).
    """
    policy = decl.policy
    transport, source = _POLICY_MODE[policy]

    if policy is SceneReferencePolicy.INHERIT_PREVIOUS_CLIP:
        if not str(decl.previous_clip_media_id or "").strip():
            return False, ERR_SCENE_REFERENCE_INHERIT_MISSING, (
                f"scene {decl.scene_id}: INHERIT_PREVIOUS_CLIP requires "
                "previous_clip_media_id — refusing silent packaging drift"
            )
        return True, None, None

    refs = tuple(r for r in decl.reference_media_ids if str(r or "").strip())
    product = str(decl.product_media_id or "").strip() or None

    if policy_requires_product_media(policy):
        if not product and len(refs) == 0:
            return False, ERR_SCENE_PRODUCT_MEDIA_REQUIRED, (
                f"scene {decl.scene_id}: policy {policy.value} requires a bound "
                "product/reference media_id — refusing generation without product truth"
            )

    if policy is SceneReferencePolicy.START_END_FRAMES:
        if len(refs) < 2:
            return False, ERR_SCENE_REFERENCE_POLICY_VIOLATION, (
                f"scene {decl.scene_id}: START_END_FRAMES requires start + end frame "
                f"references, got {len(refs)}"
            )
        count = len(refs)
    elif policy is SceneReferencePolicy.START_FRAME:
        # One start frame: explicit ref, or product plate acting as the frame.
        count = len(refs) if refs else (1 if product else 0)
    elif policy in {
        SceneReferencePolicy.PRODUCT_ANCHOR,
        SceneReferencePolicy.AVATAR_PRODUCT,
    }:
        # HYBRID product anchor: product_media alone => 1.
        if product and product not in refs:
            count = max(len(refs), 1)
        else:
            count = len(refs) if refs else (1 if product else 0)
    elif policy is SceneReferencePolicy.INGREDIENT_REFERENCES:
        # I2V bounds apply to ingredient slots only.
        count = len(refs)
    else:
        count = len(refs)

    ok, code, detail = refc.validate_reference_count(
        transport, count, source_mode=source,
    )
    if not ok:
        return False, code or ERR_SCENE_REFERENCE_POLICY_VIOLATION, (
            f"scene {decl.scene_id} policy {policy.value}: {detail}"
        )
    return True, None, None


def validate_scene_reference_set(
    declarations: Sequence[SceneReferenceDeclaration],
) -> tuple[bool, list[dict[str, str]]]:
    """Validate all scenes. Returns (all_ok, violations[])."""
    violations: list[dict[str, str]] = []
    for decl in declarations:
        ok, code, detail = validate_scene_reference_declaration(decl)
        if not ok:
            violations.append({
                "scene_id": decl.scene_id,
                "policy": decl.policy.value,
                "error_code": str(code or ERR_SCENE_REFERENCE_POLICY_VIOLATION),
                "detail": str(detail or "reference policy violation"),
            })
    return (len(violations) == 0), violations


def declaration_from_mapping(raw: dict[str, Any]) -> SceneReferenceDeclaration:
    """Build a declaration from a plain dict (API/test helper)."""
    policy = parse_scene_reference_policy(raw.get("policy") or raw.get("reference_policy"))
    refs = raw.get("reference_media_ids") or raw.get("references") or ()
    return SceneReferenceDeclaration(
        scene_id=str(raw.get("scene_id") or raw.get("beat_id") or "").strip() or "scene",
        policy=policy,
        reference_media_ids=tuple(str(x) for x in refs if str(x or "").strip()),
        product_media_id=(str(raw["product_media_id"]).strip() if raw.get("product_media_id") else None),
        previous_clip_media_id=(
            str(raw["previous_clip_media_id"]).strip()
            if raw.get("previous_clip_media_id") else None
        ),
        image_generation_required=raw.get("image_generation_required"),
        video_generation_required=raw.get("video_generation_required"),
    )
