"""Montage R3 — fail-closed assembly readiness for the discrete-scene path.

SIBLING to google_flow_final_timeline_runtime.preflight_segment_durations.
Does NOT modify Laluan-A native-extend concat preflight behavior.

A partial mandatory scene set must never silently concatenate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from agent.services.montage_scene_reference_policy import (
    SceneReferenceDeclaration,
    SceneReferencePolicy,
    policy_requires_product_media,
    validate_scene_reference_declaration,
    validate_scene_reference_set,
)

# Named fail-closed blocker (canonical required name from the build brief).
BLOCKED_INCOMPLETE_SCENE_SET = "BLOCKED_INCOMPLETE_SCENE_SET"
ERR_MONTAGE_MISSING_SCENE_CLIP = "ERR_MONTAGE_MISSING_SCENE_CLIP"
ERR_MONTAGE_MISSING_DIALOGUE = "ERR_MONTAGE_MISSING_DIALOGUE"
ERR_MONTAGE_MISSING_PRODUCT_MEDIA = "ERR_MONTAGE_MISSING_PRODUCT_MEDIA"
ERR_MONTAGE_EMPTY_PLAN = "ERR_MONTAGE_EMPTY_PLAN"


class MontageAssemblyError(RuntimeError):
    """Machine-readable discrete-montage assembly failure."""

    def __init__(self, code: str, detail: str = "", *, blockers: Optional[list[dict]] = None) -> None:
        self.code = code
        self.detail = detail
        self.blockers = list(blockers or [])
        super().__init__(f"{code}:{detail}" if detail else code)


@dataclass
class MontageSceneReadiness:
    scene_id: str
    mandatory: bool = True
    reference_policy: SceneReferencePolicy = SceneReferencePolicy.PRODUCT_ANCHOR
    product_media_id: Optional[str] = None
    reference_media_ids: tuple[str, ...] = ()
    previous_clip_media_id: Optional[str] = None
    clip_media_id: Optional[str] = None
    image_ready: bool = False
    video_ready: bool = False
    dialogue_required: bool = False
    dialogue_text: Optional[str] = None
    image_generation_required: bool = True
    video_generation_required: bool = True


@dataclass
class MontageAssemblyReport:
    ok: bool
    code: Optional[str] = None
    detail: str = ""
    blockers: list[dict[str, Any]] = field(default_factory=list)
    ready_scene_ids: list[str] = field(default_factory=list)
    clip_media_ids: list[str] = field(default_factory=list)

    def raise_if_blocked(self) -> None:
        if not self.ok:
            raise MontageAssemblyError(
                self.code or BLOCKED_INCOMPLETE_SCENE_SET,
                self.detail,
                blockers=self.blockers,
            )


def _scene_to_declaration(scene: MontageSceneReadiness) -> SceneReferenceDeclaration:
    return SceneReferenceDeclaration(
        scene_id=scene.scene_id,
        policy=scene.reference_policy,
        reference_media_ids=scene.reference_media_ids,
        product_media_id=scene.product_media_id,
        previous_clip_media_id=scene.previous_clip_media_id,
        image_generation_required=scene.image_generation_required,
        video_generation_required=scene.video_generation_required,
    )


def assess_montage_assembly_readiness(
    scenes: Sequence[MontageSceneReadiness],
    *,
    require_dialogue_when_flagged: bool = True,
) -> MontageAssemblyReport:
    """Fail closed when any mandatory scene is incomplete or mis-referenced.

    Complete sets return ok=True with ordered clip_media_ids for concat.
    """
    if not scenes:
        return MontageAssemblyReport(
            ok=False,
            code=BLOCKED_INCOMPLETE_SCENE_SET,
            detail="no scenes in montage plan",
            blockers=[{
                "error_code": ERR_MONTAGE_EMPTY_PLAN,
                "detail": "Montage assembly requires at least one scene",
            }],
        )

    blockers: list[dict[str, Any]] = []
    ready_ids: list[str] = []
    clips: list[str] = []

    # 1) Per-scene reference policy (existing contract).
    decls = [_scene_to_declaration(s) for s in scenes]
    refs_ok, ref_violations = validate_scene_reference_set(decls)
    if not refs_ok:
        for v in ref_violations:
            blockers.append({
                "scene_id": v["scene_id"],
                "error_code": v["error_code"],
                "detail": v["detail"],
            })

    # 2) Product media when policy demands it.
    for scene in scenes:
        if not scene.mandatory:
            continue
        if policy_requires_product_media(scene.reference_policy):
            product = str(scene.product_media_id or "").strip()
            refs = [str(r).strip() for r in scene.reference_media_ids if str(r or "").strip()]
            if not product and not refs:
                blockers.append({
                    "scene_id": scene.scene_id,
                    "error_code": ERR_MONTAGE_MISSING_PRODUCT_MEDIA,
                    "detail": (
                        f"scene {scene.scene_id}: policy {scene.reference_policy.value} "
                        "demands product truth media_id before assembly"
                    ),
                })

        # 3) Image-first readiness.
        if scene.image_generation_required and not scene.image_ready:
            # Inherit route may skip image plate.
            if scene.reference_policy is not SceneReferencePolicy.INHERIT_PREVIOUS_CLIP:
                blockers.append({
                    "scene_id": scene.scene_id,
                    "error_code": BLOCKED_INCOMPLETE_SCENE_SET,
                    "detail": f"scene {scene.scene_id}: image plate not ready",
                })

        # 4) Video clip readiness.
        if scene.video_generation_required:
            clip = str(scene.clip_media_id or "").strip()
            if not clip or not scene.video_ready:
                blockers.append({
                    "scene_id": scene.scene_id,
                    "error_code": ERR_MONTAGE_MISSING_SCENE_CLIP,
                    "detail": (
                        f"scene {scene.scene_id}: mandatory clip missing — "
                        "refusing silent partial concat"
                    ),
                })
            else:
                ready_ids.append(scene.scene_id)
                clips.append(clip)
        elif scene.reference_policy is SceneReferencePolicy.INHERIT_PREVIOUS_CLIP:
            # Inherit contributes previous clip if bound.
            prev = str(scene.previous_clip_media_id or scene.clip_media_id or "").strip()
            if not prev:
                blockers.append({
                    "scene_id": scene.scene_id,
                    "error_code": ERR_MONTAGE_MISSING_SCENE_CLIP,
                    "detail": f"scene {scene.scene_id}: inherit route has no previous clip",
                })
            else:
                ready_ids.append(scene.scene_id)
                clips.append(prev)

        # 5) Dialogue when required.
        if require_dialogue_when_flagged and scene.dialogue_required:
            if not str(scene.dialogue_text or "").strip():
                blockers.append({
                    "scene_id": scene.scene_id,
                    "error_code": ERR_MONTAGE_MISSING_DIALOGUE,
                    "detail": f"scene {scene.scene_id}: required dialogue block missing",
                })

    if blockers:
        return MontageAssemblyReport(
            ok=False,
            code=BLOCKED_INCOMPLETE_SCENE_SET,
            detail=(
                f"{len(blockers)} readiness blocker(s) — montage assembly refused "
                "(fail-closed; no silent partial concat)"
            ),
            blockers=blockers,
            ready_scene_ids=ready_ids,
            clip_media_ids=clips,
        )

    if len(clips) < 1:
        return MontageAssemblyReport(
            ok=False,
            code=BLOCKED_INCOMPLETE_SCENE_SET,
            detail="no complete scene clips available for assembly",
            blockers=[{
                "error_code": ERR_MONTAGE_MISSING_SCENE_CLIP,
                "detail": "complete scene set produced zero clips",
            }],
        )

    return MontageAssemblyReport(
        ok=True,
        code=None,
        detail=f"{len(clips)} scene clip(s) ready for discrete concat",
        blockers=[],
        ready_scene_ids=ready_ids,
        clip_media_ids=clips,
    )


def preflight_montage_discrete_assembly(
    scenes: Sequence[MontageSceneReadiness],
    **kwargs: Any,
) -> dict[str, Any]:
    """Public preflight entry — raises MontageAssemblyError when blocked.

    Sibling to preflight_segment_durations; safe to call without touching
    Laluan-A native-extend behavior.
    """
    report = assess_montage_assembly_readiness(scenes, **kwargs)
    report.raise_if_blocked()
    return {
        "status": "READY",
        "scene_count": len(scenes),
        "clip_media_ids": list(report.clip_media_ids),
        "ready_scene_ids": list(report.ready_scene_ids),
        "assembly_path": "DISCRETE_MONTAGE",
    }
