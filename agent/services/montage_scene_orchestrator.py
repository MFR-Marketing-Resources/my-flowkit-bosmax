"""Montage R2 operational orchestrator — plan → existing package/generate primitives.

No second video engine. No DOM lane. Credit fire only via injected generate_fn
(default: None — prepare packages only). Operators / workers call existing
`/api/flow/generate` with package ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Sequence

from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
    plan_scenes_from_story,
    plan_to_dict,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    copy_v2_handoff_context,
    resolve_persisted_copy_execution_binding,
)


ERR_MONTAGE_AVATAR_SELECTION_REQUIRED = "ERR_MONTAGE_AVATAR_SELECTION_REQUIRED"


PackageFactory = Callable[..., Awaitable[dict[str, Any]]]
GenerateFn = Callable[..., Awaitable[dict[str, Any]]]
ImagePrepareFn = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class SceneJobState:
    """Durable-enough runtime state for one montage scene."""

    scene_id: str
    beat_id: str
    block_index: int
    route: str
    transport_mode: str
    source_mode: str
    reference_policy: str
    product_media_id: Optional[str] = None
    status: str = "PLANNED"
    image_job_id: Optional[str] = None
    image_media_id: Optional[str] = None
    video_job_id: Optional[str] = None
    video_media_id: Optional[str] = None
    workspace_execution_package_id: Optional[str] = None
    package_prompt: Optional[str] = None
    start_asset_snapshot: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None
    detail: str = ""
    copy_architecture_v2: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "beat_id": self.beat_id,
            "block_index": self.block_index,
            "route": self.route,
            "transport_mode": self.transport_mode,
            "source_mode": self.source_mode,
            "reference_policy": self.reference_policy,
            "product_media_id": self.product_media_id,
            "status": self.status,
            "image_job_id": self.image_job_id,
            "image_media_id": self.image_media_id,
            "video_job_id": self.video_job_id,
            "video_media_id": self.video_media_id,
            "workspace_execution_package_id": self.workspace_execution_package_id,
            "package_prompt": self.package_prompt,
            "start_asset_snapshot": self.start_asset_snapshot,
            "error_code": self.error_code,
            "detail": self.detail,
            "copy_architecture_v2": self.copy_architecture_v2,
        }


@dataclass
class MontageOrchestrationReport:
    product_id: str
    scenes: list[SceneJobState] = field(default_factory=list)
    credit_spend: bool = False
    ok: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "scene_count": len(self.scenes),
            "scenes": [s.to_dict() for s in self.scenes],
            "credit_spend": self.credit_spend,
            "ok": self.ok,
            "detail": self.detail,
            "assembly_path": "DISCRETE_MONTAGE",
        }



def _snapshot_start_asset(pkg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Capture transportable start-frame fields from a workspace package."""
    slots = list(pkg.get("asset_slots") or [])
    resolved = list(pkg.get("resolved_assets") or [])
    candidates: list[dict[str, Any]] = []
    for slot in slots:
        if str(slot.get("slot_key") or "") == "start_frame" and isinstance(slot.get("resolved_asset"), dict):
            ra = dict(slot["resolved_asset"])
            ra.setdefault("slot_key", "start_frame")
            candidates.append(ra)
    for ra in resolved:
        if isinstance(ra, dict) and str(ra.get("slot_key") or "") == "start_frame":
            candidates.append(ra)
    if not candidates:
        return None
    ra = candidates[0]
    return {
        "assetId": ra.get("asset_id"),
        "mediaId": ra.get("media_id"),
        "downloadUrl": ra.get("download_url"),
        "previewUrl": ra.get("preview_url"),
        "localFilePath": ra.get("local_file_path"),
        "fileName": ra.get("file_name") or "start_frame",
        "label": ra.get("label") or "start_frame",
        "assetFingerprint": ra.get("asset_fingerprint"),
        "assetSource": ra.get("asset_source"),
        "localImagePathPresent": bool(
            ra.get("local_image_path_present") or ra.get("local_file_path")
        ),
        "remoteImageUrlPresent": bool(
            ra.get("remote_image_url_present")
            or ra.get("download_url")
            or ra.get("preview_url")
        ),
    }


def _snapshot_is_transportable(snapshot: Optional[dict[str, Any]]) -> bool:
    """Return true only when the package contains a real image transport path."""
    if not isinstance(snapshot, dict):
        return False
    return bool(
        snapshot.get("mediaId")
        or snapshot.get("downloadUrl")
        or snapshot.get("previewUrl")
        or snapshot.get("localFilePath")
    )


def _start_frame_for_plan(plan: MontageSceneExecutionPlan) -> Optional[str]:
    if plan.reference_media_ids:
        return plan.reference_media_ids[0]
    return plan.product_media_id


async def execute_scene_plan(
    plan: MontageSceneExecutionPlan,
    *,
    product_id: str,
    staff_id: str | None = None,
    staff_display_name_snapshot: str | None = None,
    package_factory: PackageFactory,
    image_prepare_fn: Optional[ImagePrepareFn] = None,
    generate_fn: Optional[GenerateFn] = None,
    scene_context_override: Optional[str] = None,
    copy_fallback_confirmed: bool = True,
    model: str | None = None,
    duration_seconds: int | None = None,
    copy_v2_context: dict[str, Any] | None = None,
    mascot_start_asset: Optional[dict[str, Any]] = None,
    mascot_scene_context: Optional[str] = None,
    mascot_block_count: Optional[int] = None,
    mascot_atomic_seconds: Optional[int] = None,
    mascot_has_dialogue: bool = True,
) -> SceneJobState:
    """Run one planned scene through existing package (+ optional generate) path."""
    resolved_copy_v2_context = copy_v2_context
    try:
        v2_resolution = await resolve_persisted_copy_execution_binding(
            product_id,
            "MONTAGE",
            copy_v2_context,
        )
    except CopyExecutionResolutionError as exc:
        return SceneJobState(
            scene_id=plan.scene_id,
            beat_id=plan.beat_id,
            block_index=plan.block_index,
            route=plan.route.value,
            transport_mode=plan.transport_mode,
            source_mode=plan.source_mode,
            reference_policy=plan.reference_policy.value,
            product_media_id=plan.product_media_id,
            status="PACKAGE_FAILED",
            error_code=exc.code,
            detail=str(exc)[:400],
        )
    if v2_resolution.v2_enabled:
        resolved_copy_v2_context = copy_v2_handoff_context(
            copy_v2_context,
            v2_resolution,
        )
    else:
        # An explicitly supplied flag-off context must not alter the legacy
        # package call shape or accidentally select a V2 lane.
        resolved_copy_v2_context = None
    state = SceneJobState(
        scene_id=plan.scene_id,
        beat_id=plan.beat_id,
        block_index=plan.block_index,
        route=plan.route.value,
        transport_mode=plan.transport_mode,
        source_mode=plan.source_mode,
        reference_policy=plan.reference_policy.value,
        product_media_id=plan.product_media_id,
        copy_architecture_v2=(
            v2_resolution.to_metadata(
                consumer_context=resolved_copy_v2_context,
            )
            if v2_resolution is not None and v2_resolution.v2_enabled
            else None
        ),
    )

    if plan.route == SceneExecutionRoute.INHERIT_PREVIOUS:
        if not plan.previous_clip_media_id:
            state.status = "BLOCKED"
            state.error_code = "ERR_MONTAGE_MISSING_PREVIOUS_CLIP"
            state.detail = "INHERIT_PREVIOUS requires previous_clip_media_id"
            return state
        state.video_media_id = plan.previous_clip_media_id
        state.status = "VIDEO_READY"
        return state

    # Montage currently has no explicit Avatar Registry identity field. An
    # AVATAR_PRODUCT declaration must therefore fail closed at the Montage
    # boundary rather than inheriting VISIBLE_CREATOR or silently becoming
    # FACELESS inside the generic package/compiler path.
    if plan.reference_policy is SceneReferencePolicy.AVATAR_PRODUCT:
        state.status = "PACKAGE_FAILED"
        state.error_code = ERR_MONTAGE_AVATAR_SELECTION_REQUIRED
        state.detail = (
            "AVATAR_PRODUCT requires an explicit Avatar Registry identity; "
            "Montage will not select, invent, or downgrade an avatar"
        )
        return state

    # IMAGE_FIRST: optional image prepare; PRODUCT_ANCHOR/HYBRID may defer to package product image
    start_frame = _start_frame_for_plan(plan)
    hybrid_product_anchor = str(plan.source_mode or "").upper() == "HYBRID"
    is_mascot_start_frame = (
        mascot_start_asset is not None
        and plan.reference_policy is SceneReferencePolicy.START_FRAME
    )
    if plan.route == SceneExecutionRoute.IMAGE_FIRST and plan.image_generation_required:
        if is_mascot_start_frame:
            # Product Mascot Key Visual IS the start-frame visual; bound as the
            # scene start asset after the package builds — never image_prepare,
            # never the Official Product Visual.
            state.status = "IMAGE_BOUND"
        elif image_prepare_fn is not None and not start_frame and not hybrid_product_anchor:
            img = await image_prepare_fn(
                product_id=product_id,
                scene_id=plan.scene_id,
                policy=plan.reference_policy.value,
            )
            start_frame = str(img.get("media_id") or img.get("image_media_id") or "") or None
            state.image_job_id = img.get("job_id")
            state.image_media_id = start_frame
            state.status = "IMAGE_READY" if start_frame else "IMAGE_PENDING"
        elif start_frame:
            state.image_media_id = start_frame
            state.status = "IMAGE_BOUND"
        elif hybrid_product_anchor:
            # Canonical product package supplies start_frame after factory call
            state.status = "IMAGE_PENDING_PACKAGE"
            state.detail = "PRODUCT_ANCHOR → HYBRID product image from approved package"
        else:
            state.status = "IMAGE_PENDING"
            state.error_code = "ERR_MONTAGE_IMAGE_REQUIRED"
            state.detail = (
                f"IMAGE_FIRST scene {plan.scene_id} needs product/start frame "
                "or image_prepare_fn result"
            )
            return state

    if not plan.video_generation_required:
        state.status = "SKIPPED_VIDEO"
        return state

    # DIRECT_VIDEO or IMAGE_FIRST → create workspace execution package via canonical factory
    mode = plan.transport_mode
    source_mode = plan.source_mode if plan.source_mode != mode else None
    if is_mascot_start_frame:
        # Build a plain F2V prompt/copy package with NO frame binding — a mascot
        # (CHARACTER_REFERENCE) cannot pass the package factory's FRAMES
        # COMPOSITE_FRAME_REFERENCE validation. The FRAMES lineage stays on the
        # scene state (state.source_mode) so the generate boundary + the existing
        # flow gate honor the mascot start asset; it is not baked into a frame slot.
        source_mode = None
    # Prefer operator-selected model/duration (no empty model / hardcoded-only path)
    model_label = str(model or "").strip()
    try:
        dur = int(duration_seconds) if duration_seconds is not None else 0
    except (TypeError, ValueError):
        dur = 0
    if not model_label or dur <= 0:
        state.status = "PACKAGE_FAILED"
        state.error_code = "ERR_MONTAGE_MODEL_DURATION_REQUIRED"
        state.detail = "Montage requires an explicitly selected canonical model and duration"
        return state
    from agent.services import video_capability_matrix as _cm

    capability_ok, capability_code = _cm.validate_single("GOOGLE_FLOW", model_label, dur)
    if not capability_ok:
        state.status = "PACKAGE_FAILED"
        state.error_code = f"ERR_MONTAGE_{capability_code}"
        state.detail = f"Unsupported canonical Montage model/duration: {capability_code}"
        return state
    kwargs: dict[str, Any] = {
        "product_id": product_id,
        "mode": mode,
        "duration_seconds": dur,
        "aspect_ratio": "9:16",
        "model": model_label,
        "manual_override": False,
        "generation_mode": "SINGLE",
        "source_mode": source_mode,
        "copy_fallback_confirmed": copy_fallback_confirmed,
        "scene_context_override": scene_context_override,
        "copy_v2_context": resolved_copy_v2_context,
    }
    # Optional identity is carried on active API calls, while legacy/provider-free
    # package factories may not accept the newer kwargs when no profile is given.
    if staff_id:
        kwargs["staff_id"] = staff_id
        kwargs["staff_display_name_snapshot"] = staff_display_name_snapshot
    # FRAMES/I2V need explicit start; HYBRID product-anchor does not take start_frame_asset_id
    if start_frame and mode in ("F2V", "I2V", "FRAMES") and str(source_mode or "").upper() != "HYBRID":
        kwargs["start_frame_asset_id"] = start_frame
    if plan.product_media_id and str(source_mode or "").upper() == "HYBRID":
        kwargs["product_reference_asset_id"] = plan.product_media_id
    if plan.reference_policy is SceneReferencePolicy.PRODUCT_ANCHOR:
        # PRODUCT_ANCHOR is the normal presenter-free Montage contract. The
        # generic package factory defaults to VISIBLE_CREATOR, so make the
        # Montage-owned intent explicit and keep Avatar Registry identity null.
        kwargs["character_presence"] = "FACELESS"
        kwargs["avatar_id"] = None
    if is_mascot_start_frame:
        # Presenter-free: the mascot is the on-screen product character, not a
        # human creator. Never inherit the generic VISIBLE_CREATOR default.
        kwargs["character_presence"] = "FACELESS"
        # Keep the legacy transport presence field for package/API compatibility,
        # but make the provider-facing compiler contract unambiguously mascot-owned.
        kwargs["product_presence_type"] = "PRODUCT_MASCOT"
        kwargs["compiler_source_mode"] = "FRAMES"
        kwargs["wps_mode"] = "SWEET"
        kwargs["enforce_temporal_contract"] = True
        kwargs["avatar_id"] = None
        if mascot_block_count:
            # V1.1 Creative Grammar: compose a DISTINCT per-scene direction —
            # this block's macro purpose + its objective/visual_action + four
            # micro-beats + mascot action grammar + lip-sync + identity lock +
            # visual dynamism — layered on the resolved hook/background context.
            # This is how objective/visual_action (dropped by the generic
            # compiler) materially reach the engine prompt, per scene.
            from agent.services import montage_mascot_creative_grammar as _mmcg

            kwargs["scene_context_override"] = _mmcg.compose_scene_context(
                block_index=plan.block_index,
                block_count=int(mascot_block_count),
                atomic_seconds=int(mascot_atomic_seconds or dur),
                objective=plan.objective,
                visual_action=plan.visual_action,
                has_dialogue=mascot_has_dialogue,
                existing_context=scene_context_override,
            )
        elif mascot_scene_context:
            kwargs["scene_context_override"] = mascot_scene_context

    try:
        pkg = await package_factory(**kwargs)
    except Exception as exc:  # noqa: BLE001
        state.status = "PACKAGE_FAILED"
        state.error_code = "ERR_MONTAGE_PACKAGE"
        state.detail = str(exc)[:400]
        return state

    if not isinstance(pkg, dict):
        state.status = "PACKAGE_FAILED"
        state.error_code = "ERR_MONTAGE_PACKAGE_INVALID"
        state.detail = "workspace package factory returned a non-object result"
        return state
    if isinstance(pkg.get("copy_architecture_v2"), dict):
        state.copy_architecture_v2 = pkg["copy_architecture_v2"]
    state.workspace_execution_package_id = str(
        pkg.get("workspace_execution_package_id") or ""
    ) or None
    state.package_prompt = str(pkg.get("prompt_text") or pkg.get("prompt") or "") or None
    state.start_asset_snapshot = _snapshot_start_asset(pkg)
    if is_mascot_start_frame:
        # The mascot is the authoritative start visual — override any package plate
        # so the scene renders FROM the mascot, not the Official Product Visual.
        state.start_asset_snapshot = dict(mascot_start_asset)
    if state.package_prompt and not state.detail:
        state.detail = state.package_prompt[:400]
    if not bool(pkg.get("execution_allowed")):
        state.status = "IMAGE_PENDING" if plan.route == SceneExecutionRoute.IMAGE_FIRST else "PACKAGE_FAILED"
        state.error_code = "ERR_MONTAGE_IMAGE_REQUIRED" if state.status == "IMAGE_PENDING" else "ERR_MONTAGE_PACKAGE_BLOCKED"
        state.detail = str(pkg.get("blockers") or "workspace package is not execution-ready")[:400]
        return state

    # Product-anchor HYBRID: package start_frame IS the scene image plate.
    # A composite asset id alone is not a transportable image; keep the real
    # media id separate so assembly cannot be satisfied by a fabricated id.
    if state.start_asset_snapshot and not state.image_media_id:
        mid = state.start_asset_snapshot.get("mediaId")
        if mid:
            state.image_media_id = str(mid)
            if not state.product_media_id and plan.reference_policy in (
                SceneReferencePolicy.PRODUCT_ANCHOR,
                SceneReferencePolicy.AVATAR_PRODUCT,
            ):
                state.product_media_id = str(mid)
        if state.image_media_id:
            state.status = "IMAGE_BOUND"
    if (
        plan.route == SceneExecutionRoute.IMAGE_FIRST
        and not state.image_media_id
        and not _snapshot_is_transportable(state.start_asset_snapshot)
    ):
        state.status = "IMAGE_PENDING"
        state.error_code = "ERR_MONTAGE_IMAGE_REQUIRED"
        state.detail = "IMAGE_FIRST scene has no transportable canonical plate"
        return state
    state.status = "PACKAGE_READY"

    if generate_fn is None:
        # Default: stop at package — operator fires one-door generate explicitly
        return state

    gen = await generate_fn(
        product_id=product_id,
        mode=mode,
        source_mode=state.source_mode,
        workspace_execution_package_id=state.workspace_execution_package_id,
        prompt=state.package_prompt or pkg.get("prompt_text") or "",
        scene_id=plan.scene_id,
        start_asset=state.start_asset_snapshot,
        image_media_id=state.image_media_id,
        model=model_label,
        duration_s=dur,
    )
    state.video_job_id = str(gen.get("job_id") or gen.get("id") or "") or None
    state.video_media_id = str(
        gen.get("media_id") or gen.get("video_media_id") or ""
    ) or None
    state.status = "VIDEO_SUBMITTED" if state.video_job_id else "GENERATE_RETURNED"
    if state.video_media_id:
        state.status = "VIDEO_READY"
    return state


async def orchestrate_montage_scenes(
    *,
    product_id: str,
    staff_id: str | None = None,
    staff_display_name_snapshot: str | None = None,
    story_beats: Sequence[Any],
    package_factory: PackageFactory,
    default_policy: SceneReferencePolicy | str = SceneReferencePolicy.PRODUCT_ANCHOR,
    per_beat_policy: Optional[dict[str, str]] = None,
    product_media_id: Optional[str] = None,
    image_prepare_fn: Optional[ImagePrepareFn] = None,
    generate_fn: Optional[GenerateFn] = None,
    scene_context_override: Optional[str] = None,
    copy_fallback_confirmed: bool = True,
    model: str | None = None,
    duration_seconds: int | None = None,
    copy_v2_context: dict[str, Any] | None = None,
    mascot_start_asset: Optional[dict[str, Any]] = None,
    mascot_scene_context: Optional[str] = None,
    mascot_block_count: Optional[int] = None,
    mascot_atomic_seconds: Optional[int] = None,
    mascot_has_dialogue: bool = True,
) -> MontageOrchestrationReport:
    """Beat → route → package (/ optional generate) for the full scene set."""
    if not str(product_id or "").strip():
        return MontageOrchestrationReport(
            product_id=product_id or "",
            ok=False,
            detail="product_id required",
        )
    plans = plan_scenes_from_story(
        story_beats=story_beats,
        default_policy=default_policy,
        per_beat_policy=per_beat_policy,
        product_media_id=product_media_id,
    )
    resolved_copy_v2_context = copy_v2_context
    try:
        v2 = await resolve_persisted_copy_execution_binding(
            product_id,
            "MONTAGE",
            copy_v2_context,
        )
        if v2.v2_enabled:
            # Every scene receives the same persisted binding identity; scene
            # fan-out never reinterprets or rotates copy.
            resolved_copy_v2_context = copy_v2_handoff_context(
                copy_v2_context,
                v2,
            )
    except CopyExecutionResolutionError:
        # Let each package boundary surface the same fail-closed blocker in its
        # scene ledger; no scene is silently downgraded to legacy copy.
        resolved_copy_v2_context = copy_v2_context
    report = MontageOrchestrationReport(
        product_id=product_id,
        credit_spend=generate_fn is not None,
    )
    previous_clip: Optional[str] = None
    for plan in plans:
        # feed inherit chain
        if plan.route == SceneExecutionRoute.INHERIT_PREVIOUS and previous_clip:
            from dataclasses import replace

            plan = replace(plan, previous_clip_media_id=previous_clip)
        state = await execute_scene_plan(
            plan,
            product_id=product_id,
            staff_id=staff_id,
            staff_display_name_snapshot=staff_display_name_snapshot,
            package_factory=package_factory,
            image_prepare_fn=image_prepare_fn,
            generate_fn=generate_fn,
            scene_context_override=scene_context_override,
            copy_fallback_confirmed=copy_fallback_confirmed,
            model=model,
            duration_seconds=duration_seconds,
            copy_v2_context=resolved_copy_v2_context,
            mascot_start_asset=mascot_start_asset,
            mascot_scene_context=mascot_scene_context,
            mascot_block_count=mascot_block_count,
            mascot_atomic_seconds=mascot_atomic_seconds,
            mascot_has_dialogue=mascot_has_dialogue,
        )
        report.scenes.append(state)
        if state.video_media_id:
            previous_clip = state.video_media_id
        if state.status in ("BLOCKED", "PACKAGE_FAILED"):
            report.ok = False
    if not report.scenes:
        report.ok = False
        report.detail = "no scenes planned"
    return report


def plans_as_public_dicts(plans: Sequence[MontageSceneExecutionPlan]) -> list[dict[str, Any]]:
    return [plan_to_dict(p) for p in plans]
