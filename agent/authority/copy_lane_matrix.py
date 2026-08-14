"""Canonical Copy Register V2 producer/consumer inventory.

The seven owner-deactivated pages remain redirected, while their internal lane
identities stay available to package, P6, and API-first programmatic callers.
Every descriptor names the current API, service, and UI state so a dormant page
cannot be mistaken for a deleted backend mode or an active acceptance target.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


VIDEO_LANES = (
    "T2V",
    "F2V",
    "HYBRID",
    "I2V",
    "FACELESS",
    "MONTAGE",
    "PRODUCTION_STUDIO_P6",
)
IMAGE_LANES = (
    "IMAGE_GEN",
    "IMG_FASTLANE",
    "IMG_COCKPIT",
    "POSTER_BUILDER",
)
ALL_COPY_LANES = VIDEO_LANES + IMAGE_LANES

MediaKind = Literal["VIDEO", "IMAGE"]
CopyPolicy = Literal["REQUIRED", "NOT_REQUIRED"]
UISurfaceState = Literal["ACTIVE", "DORMANT_REDIRECTED"]


@dataclass(frozen=True)
class CopyLaneDescriptor:
    lane_id: str
    display_name: str
    media_kind: MediaKind
    copy_policy: CopyPolicy
    current_api_entry_point: str
    current_service_entry_point: str
    current_page_entry_point: str
    adapter: str
    phase3_scope: str
    ui_surface_state: UISurfaceState = "ACTIVE"


_DESCRIPTORS = (
    CopyLaneDescriptor(
        "T2V", "T2V", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=T2V)",
        "workspace_execution_package_service.py -> workspace_generation_package_service.py -> flow._run_manual_job_via_generate",
        "DORMANT /operator/t2v -> /operator/hybrid; internal T2V mode retained",
        "VideoCopyProjection", "bind selected V2 revision into T2V package/compile path",
        ui_surface_state="DORMANT_REDIRECTED",
    ),
    CopyLaneDescriptor(
        "F2V", "F2V", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=F2V, source_mode=FRAMES)",
        "workspace_execution_package_service.py -> workspace_generation_package_service.py -> flow._run_manual_job_via_generate",
        "DORMANT /operator/f2v -> /operator/hybrid; internal F2V mode retained",
        "VideoCopyProjection", "bind selected V2 revision alongside frame lineage",
        ui_surface_state="DORMANT_REDIRECTED",
    ),
    CopyLaneDescriptor(
        "HYBRID", "Hybrid", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=F2V, source_mode=HYBRID)",
        "workspace_execution_package_service.py -> workspace_generation_package_service.py -> flow._run_manual_job_via_generate",
        "dashboard/src/pages/OperatorPage.tsx",
        "VideoCopyProjection", "bind selected V2 revision without legacy fallback",
    ),
    CopyLaneDescriptor(
        "I2V", "I2V", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=I2V)",
        "workspace_execution_package_service.py -> workspace_generation_package_service.py -> flow._run_manual_job_via_generate",
        "DORMANT /operator/i2v -> /operator/hybrid; internal I2V mode retained",
        "VideoCopyProjection", "bind selected V2 revision alongside subject/scene/style slots",
        ui_surface_state="DORMANT_REDIRECTED",
    ),
    CopyLaneDescriptor(
        "FACELESS", "Faceless", "VIDEO", "REQUIRED",
        "POST /api/faceless/prepare (pre-generation contract)",
        "faceless_lane_service.py -> copy_execution_resolver.py",
        "dashboard/src/pages/FacelessVideoPage.tsx",
        "VideoCopyProjection", "bind selected V2 revision into faceless preparation",
    ),
    CopyLaneDescriptor(
        "MONTAGE", "Montage", "VIDEO", "REQUIRED",
        "POST /api/montage/runs (pre-generation contract)",
        "montage_run_service.py -> montage_scene_orchestrator.py",
        "dashboard/src/pages/MontagePage.tsx",
        "VideoCopyProjection", "bind selected V2 revision into montage scene planning",
    ),
    CopyLaneDescriptor(
        "PRODUCTION_STUDIO_P6", "Production Studio / P6", "VIDEO", "REQUIRED",
        "POST /api/creative-production/plans (pre-generation contract)",
        "creative_production_plan_service.py -> creative_production_compile_service.py -> creative_production_scheduler_service.py",
        "dashboard/src/pages/CreativeProductionStudioPage.tsx",
        "VideoCopyProjection", "bind selected V2 revision into P6 compile/queue boundaries",
    ),
    CopyLaneDescriptor(
        "IMAGE_GEN", "Image Gen", "IMAGE", "NOT_REQUIRED",
        "POST /api/flow/execute-flow-job (mode=IMG, lane=IMAGE_GEN)",
        "workspace_generation_package_service.py -> image_prompt_compiler.py -> flow._run_manual_job_via_generate",
        "DORMANT /operator/img -> /creative/poster-builder; internal IMG mode retained",
        "ImageCopyProjection", "declare copy-free image policy with explicit readiness proof",
        ui_surface_state="DORMANT_REDIRECTED",
    ),
    CopyLaneDescriptor(
        "IMG_FASTLANE", "IMG Fastlane", "IMAGE", "NOT_REQUIRED",
        "POST /api/img-factory/fastlane-preview; internal live mode=IMG lane=IMG_FASTLANE",
        "img_asset_factory_service.py -> copy_execution_resolver.py",
        "DORMANT /assets/img-fastlane -> /creative/poster-builder; internal lane retained",
        "ImageCopyProjection", "declare copy-free image policy with explicit readiness proof",
        ui_surface_state="DORMANT_REDIRECTED",
    ),
    CopyLaneDescriptor(
        "IMG_COCKPIT", "IMG Cockpit", "IMAGE", "NOT_REQUIRED",
        "POST /api/flow/execute-flow-job (mode=IMG, lane=IMG_COCKPIT)",
        "image_prompt_compiler.py -> copy_execution_resolver.py -> flow._run_manual_job_via_generate",
        "DORMANT /assets/img-cockpit -> /creative/poster-builder; internal lane retained",
        "ImageCopyProjection", "declare copy-free image policy with explicit readiness proof",
        ui_surface_state="DORMANT_REDIRECTED",
    ),
    CopyLaneDescriptor(
        "POSTER_BUILDER", "Poster Builder", "IMAGE", "REQUIRED",
        "POST /api/poster/compose and /api/poster/prompt-draft",
        "poster_composition_service.py and poster_prompt_draft_service.py",
        "dashboard/src/pages/PosterBuilderPage.tsx",
        "ImageCopyProjection", "bind poster-aware V2 copy explicitly; never treat poster copy as video stages",
    ),
)

LANE_MATRIX = {descriptor.lane_id: descriptor for descriptor in _DESCRIPTORS}


def get_lane_descriptor(lane: str) -> CopyLaneDescriptor:
    token = str(lane or "").strip().upper().replace(" ", "_").replace("/", "_")
    aliases = {
        "HYBRID_VIDEO": "HYBRID",
        "PRODUCTION_STUDIO__P6": "PRODUCTION_STUDIO_P6",
        "PRODUCTION_STUDIO_P6": "PRODUCTION_STUDIO_P6",
        "IMAGEGEN": "IMAGE_GEN",
        "IMGFASTLANE": "IMG_FASTLANE",
        "IMGCOCKPIT": "IMG_COCKPIT",
        "POSTERBUILDER": "POSTER_BUILDER",
    }
    token = aliases.get(token, token)
    try:
        return LANE_MATRIX[token]
    except KeyError as exc:
        raise ValueError(f"COPY_V2_UNKNOWN_LANE:{lane}") from exc


def producer_consumer_matrix() -> list[dict[str, str]]:
    return [asdict(descriptor) for descriptor in _DESCRIPTORS]
