"""Universal producer/consumer matrix for the Phase 2 copy adapters.

This is a contract inventory, not consumer cutover.  Each descriptor names the
current API, service, and page seams so later Phase 3 wiring cannot silently
skip a lane or invent a second copy path.
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


_DESCRIPTORS = (
    CopyLaneDescriptor(
        "T2V", "T2V", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=T2V)",
        "agent/services/workspace_execution_package_service.py",
        "dashboard/src/pages/OperatorPage.tsx (mode=T2V)",
        "VideoCopyProjection", "bind selected V2 revision into T2V package/compile path",
    ),
    CopyLaneDescriptor(
        "F2V", "F2V", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=F2V)",
        "agent/services/f2v_frame_source_resolver_service.py",
        "dashboard/src/pages/OperatorPage.tsx (mode=F2V)",
        "VideoCopyProjection", "bind selected V2 revision alongside frame lineage",
    ),
    CopyLaneDescriptor(
        "HYBRID", "Hybrid", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=HYBRID)",
        "agent/services/workspace_execution_package_service.py",
        "dashboard/src/pages/OperatorPage.tsx",
        "VideoCopyProjection", "bind selected V2 revision without legacy fallback",
    ),
    CopyLaneDescriptor(
        "I2V", "I2V", "VIDEO", "REQUIRED",
        "POST /api/flow/execute-flow-job (mode=I2V)",
        "agent/services/i2v_semantic_slot_resolver_service.py",
        "dashboard/src/pages/OperatorPage.tsx (mode=I2V)",
        "VideoCopyProjection", "bind selected V2 revision alongside subject/scene/style slots",
    ),
    CopyLaneDescriptor(
        "FACELESS", "Faceless", "VIDEO", "REQUIRED",
        "POST /api/faceless/prepare (pre-generation contract)",
        "agent/services/faceless_lane_service.py",
        "dashboard/src/pages/FacelessVideoPage.tsx",
        "VideoCopyProjection", "bind selected V2 revision into faceless preparation",
    ),
    CopyLaneDescriptor(
        "MONTAGE", "Montage", "VIDEO", "REQUIRED",
        "POST /api/montage/runs (pre-generation contract)",
        "agent/services/montage_run_service.py",
        "dashboard/src/pages/MontagePage.tsx",
        "VideoCopyProjection", "bind selected V2 revision into montage scene planning",
    ),
    CopyLaneDescriptor(
        "PRODUCTION_STUDIO_P6", "Production Studio / P6", "VIDEO", "REQUIRED",
        "POST /api/creative-production/plans (pre-generation contract)",
        "agent/services/creative_production_compile_service.py",
        "dashboard/src/pages/CreativeProductionStudioPage.tsx",
        "VideoCopyProjection", "bind selected V2 revision into P6 compile/queue boundaries",
    ),
    CopyLaneDescriptor(
        "IMAGE_GEN", "Image Gen", "IMAGE", "NOT_REQUIRED",
        "POST /api/flow/generate (mode=IMG)",
        "agent/services/image_prompt_compiler.py",
        "dashboard/src/components/workspace/IMGModule.tsx",
        "ImageCopyProjection", "declare copy-free image policy with explicit readiness proof",
    ),
    CopyLaneDescriptor(
        "IMG_FASTLANE", "IMG Fastlane", "IMAGE", "NOT_REQUIRED",
        "POST /api/img-factory/*",
        "agent/services/img_asset_factory_service.py",
        "dashboard/src/pages/ImgFastlanePage.tsx",
        "ImageCopyProjection", "declare copy-free image policy with explicit readiness proof",
    ),
    CopyLaneDescriptor(
        "IMG_COCKPIT", "IMG Cockpit", "IMAGE", "NOT_REQUIRED",
        "POST /api/flow/generate (mode=IMG) via cockpit settings",
        "agent/services/image_prompt_compiler.py",
        "dashboard/src/pages/ImgCockpitPage.tsx",
        "ImageCopyProjection", "declare copy-free image policy with explicit readiness proof",
    ),
    CopyLaneDescriptor(
        "POSTER_BUILDER", "Poster Builder", "IMAGE", "REQUIRED",
        "POST /api/poster/compose and /api/poster/prompt-draft",
        "agent/services/poster_composition_service.py",
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
