"""IMG Asset Factory v1 — F2V start/end frame source resolver contract.

Mirrors the shape of ``i2v_semantic_slot_resolver`` but for F2V frames. It lets a
saved ``COMPOSITE_FRAME_REFERENCE`` (produced by an IMG composite lane) feed an
F2V start / end frame, alongside the approved product image and manual upload,
while excluding poster (rendered-text) assets from clean video-support frames.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


F2VFrameSlot = Literal["start_frame", "end_frame"]
F2VFrameSourceKind = Literal["PRODUCT_IMAGE", "COMPOSITE_FRAME_REFERENCE", "MANUAL_UPLOAD"]


class F2VResolvedFrame(BaseModel):
    slot_key: F2VFrameSlot
    source_kind: F2VFrameSourceKind
    asset_id: str | None = None
    display_name: str | None = None
    asset_fingerprint: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    media_id: str | None = None
    local_file_path: str | None = None


class F2VFrameSourceResolverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = None
    start_frame_asset_id: str | None = None
    end_frame_asset_id: str | None = None
    use_product_image_as_start: bool = True
    start_frame_manual_upload_present: bool = False
    end_frame_manual_upload_present: bool = False


class F2VFrameSourceResolverResponse(BaseModel):
    mode: Literal["F2V"] = "F2V"
    start_frame: F2VResolvedFrame | None = None
    end_frame: F2VResolvedFrame | None = None
    resolved_frames: list[F2VResolvedFrame] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
