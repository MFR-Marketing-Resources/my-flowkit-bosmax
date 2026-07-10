"""Poster deliverable orchestration (POSTER_BUILDER_V2).

compose → QA → persist → save-to-library → reconstruct.

Guarantees:
- PREVIEW == SAVE: the deliverable stores the output PNG's sha256 at compose
  time; save-to-library re-reads the SAME file, verifies the hash, and never
  regenerates.
- Durable reconstruction: the full render manifest + copy-set reference +
  QA report are persisted on the deliverable row (survives the 48h
  generated_artifact purge).
- Final-approval strictness: drafts may compose permissively, but saving to the
  Creative Library requires an APPROVED poster copy set and zero QA blockers.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from agent.db import crud
from agent.models.creative_asset import CreativeAssetCreateRequest
from agent.models.poster_copy_set import (
    STATUS_POSTER_COPY_APPROVED,
    serialize_poster_copy_set,
)
from agent.models.poster_render_manifest import (
    PosterQAReport,
    build_qa_report,
)
from agent.services import poster_compositor_service as compositor
from agent.services.creative_asset_service import create_creative_asset
from agent.services.img_asset_lane_config import derive_asset_governance
from agent.services.poster_template_service import (
    PosterTemplateError,
    build_render_manifest,
)

class PosterDeliverableError(Exception):
    def __init__(self, code: str, message: str = "", *, status_code: int = 422):
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def _resolve_background(
    background_media_id: str, background_local_path: str
) -> tuple[str, str]:
    """Resolve the clean generated scene to a local file. Fail-closed."""
    media_id = _norm(background_media_id)
    local = _norm(background_local_path)
    if media_id:
        artifact = await crud.get_generated_artifact(media_id)
        if not artifact:
            raise PosterDeliverableError(
                "POSTER_BACKGROUND_ARTIFACT_NOT_FOUND",
                f"generated artifact {media_id} not found (48h purge?)",
                status_code=404,
            )
        local = _norm(artifact.get("local_path"))
    if not local or not Path(local).exists():
        raise PosterDeliverableError(
            "POSTER_BACKGROUND_FILE_MISSING",
            f"background image file missing: {local or '(none)'}",
            status_code=404,
        )
    return media_id, local


class PosterDeliverableService:
    @staticmethod
    async def compose_poster(
        *,
        product_id: str,
        poster_copy_set_id: str,
        recipe_id: str,
        background_media_id: str = "",
        background_local_path: str = "",
        image_model: str = "",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        product_id = _norm(product_id)
        product = await crud.get_product(product_id)
        if not product:
            raise PosterDeliverableError("PRODUCT_NOT_FOUND", status_code=404)

        pcs_row = await crud.get_poster_copy_set(_norm(poster_copy_set_id))
        if not pcs_row:
            raise PosterDeliverableError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        if _norm(pcs_row.get("product_id")) != product_id:
            raise PosterDeliverableError(
                "POSTER_COPY_SET_PRODUCT_MISMATCH", status_code=409
            )
        if pcs_row.get("status") in ("POSTER_COPY_REJECTED", "POSTER_COPY_SUPERSEDED"):
            raise PosterDeliverableError(
                "POSTER_COPY_SET_NOT_USABLE",
                f"copy set status {pcs_row.get('status')} cannot be composed",
                status_code=409,
            )
        copy_set = serialize_poster_copy_set(pcs_row)

        media_id, bg_local = await _resolve_background(
            background_media_id, background_local_path
        )

        try:
            manifest = build_render_manifest(
                recipe_id=_norm(recipe_id),
                copy_set=copy_set,
                background_media_id=media_id,
                background_local_path=bg_local,
                image_model=_norm(image_model),
            )
        except PosterTemplateError as exc:
            raise PosterDeliverableError(exc.code, str(exc), status_code=exc.status_code)

        try:
            out_path, report = await compositor.compose(manifest)
        except compositor.PosterCompositorError as exc:
            raise PosterDeliverableError(exc.code, str(exc), status_code=exc.status_code)

        qa = build_qa_report(
            report, expected_zone_ids=[z.zone_id for z in manifest.zones]
        )
        sha = _sha256(out_path)
        row = await crud.create_poster_deliverable(
            product_id,
            poster_copy_set_id=copy_set["poster_copy_set_id"],
            recipe_id=manifest.provenance.recipe_id,
            template_version=manifest.provenance.template_version,
            composition_strategy=manifest.product_layer.strategy,
            render_manifest_json=manifest.model_dump_json(),
            background_media_id=media_id,
            background_local_path=bg_local,
            output_path=str(out_path),
            output_sha256=sha,
            qa_report_json=qa.model_dump_json(),
            settings_json=json.dumps(settings or {}, ensure_ascii=False),
            status="POSTER_COMPOSED",
        )
        return {
            "deliverable": row,
            "render_report": report.model_dump(mode="json"),
            "qa_report": qa.model_dump(mode="json"),
        }

    @staticmethod
    async def save_to_library(poster_deliverable_id: str) -> dict[str, Any]:
        row = await crud.get_poster_deliverable(_norm(poster_deliverable_id))
        if not row:
            raise PosterDeliverableError("POSTER_DELIVERABLE_NOT_FOUND", status_code=404)
        if row.get("status") == "POSTER_SAVED" and _norm(row.get("creative_asset_id")):
            return {"deliverable": row, "creative_asset_id": row["creative_asset_id"],
                    "already_saved": True}
        if row.get("status") != "POSTER_COMPOSED":
            raise PosterDeliverableError(
                "POSTER_DELIVERABLE_NOT_COMPOSED", status_code=409
            )

        # FINAL-APPROVAL GATES (stricter than draft compose):
        qa = PosterQAReport.model_validate_json(row.get("qa_report_json") or "{}")
        if qa.block_count > 0:
            raise PosterDeliverableError(
                "POSTER_QA_BLOCKED",
                "; ".join(f.code for f in qa.findings if f.severity == "BLOCK"),
                status_code=409,
            )
        pcs_row = await crud.get_poster_copy_set(_norm(row.get("poster_copy_set_id")))
        if not pcs_row or pcs_row.get("status") != STATUS_POSTER_COPY_APPROVED:
            raise PosterDeliverableError(
                "POSTER_COPY_SET_NOT_APPROVED",
                "Saving to the Creative Library requires an APPROVED poster copy set",
                status_code=409,
            )

        # PREVIEW == SAVE identity: re-read the exact composed file and verify
        # the stored hash before registering. Never regenerate here.
        out_path = Path(_norm(row.get("output_path")))
        if not out_path.exists():
            raise PosterDeliverableError(
                "POSTER_OUTPUT_FILE_MISSING", str(out_path), status_code=404
            )
        data = out_path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if _norm(row.get("output_sha256")) and sha != _norm(row.get("output_sha256")):
            raise PosterDeliverableError(
                "POSTER_OUTPUT_IDENTITY_MISMATCH",
                "composed output changed on disk since preview — recompose required",
                status_code=409,
            )

        product = await crud.get_product(_norm(row.get("product_id"))) or {}
        governance = derive_asset_governance("PRODUCT_POSTER")
        copy_set = serialize_poster_copy_set(pcs_row)
        display = (
            f"Poster — {_norm(product.get('product_display_name')) or _norm(row.get('product_id'))}"
            f" — {_norm(copy_set.get('archetype')) or _norm(row.get('recipe_id'))}"
        )
        create_request = CreativeAssetCreateRequest(
            semantic_role=governance["semantic_role"],
            display_name=display[:120],
            description=(
                f"Deterministic poster (compositor). angle={copy_set.get('angle')}; "
                f"copy_set={copy_set.get('poster_copy_set_id')} v{copy_set.get('version')}; "
                f"deliverable={row.get('poster_deliverable_id')}"
            ),
            source_type="GENERATED_IMAGE",
            storage_kind="LOCAL_FILE",
            product_id=_norm(row.get("product_id")),
            category=_norm(product.get("category")) or None,
            silo=_norm(product.get("silo")) or None,
            product_type=_norm(product.get("type")) or None,
            allowed_modes=governance["allowed_modes"],
            engine_slot_eligibility=governance["engine_slot_eligibility"],
            asset_subtype=governance["asset_subtype"],
            generation_recipe_id=_norm(row.get("recipe_id")) or None,
            contains_rendered_text=governance["contains_rendered_text"],
            approved_for_video_support=governance["approved_for_video_support"],
            approved_for_poster=governance["approved_for_poster"],
            product_truth_status="PRESERVED",
            image_base64=base64.b64encode(data).decode("ascii"),
            file_name=f"poster_{row.get('poster_deliverable_id')}.png",
        )
        asset = await create_creative_asset(create_request)
        asset_id = getattr(asset, "asset_id", None) or getattr(asset, "id", "")
        updated = await crud.update_poster_deliverable(
            row["poster_deliverable_id"],
            creative_asset_id=str(asset_id),
            status="POSTER_SAVED",
        )
        return {
            "deliverable": updated,
            "creative_asset_id": str(asset_id),
            "already_saved": False,
        }

    @staticmethod
    async def get_with_manifest(poster_deliverable_id: str) -> dict[str, Any]:
        """Reconstruction contract: deliverable + manifest + copy set."""
        row = await crud.get_poster_deliverable(_norm(poster_deliverable_id))
        if not row:
            raise PosterDeliverableError("POSTER_DELIVERABLE_NOT_FOUND", status_code=404)
        manifest: dict[str, Any] = {}
        try:
            manifest = json.loads(row.get("render_manifest_json") or "{}")
        except ValueError:
            pass
        copy_set = None
        pcs_row = await crud.get_poster_copy_set(_norm(row.get("poster_copy_set_id")))
        if pcs_row:
            copy_set = serialize_poster_copy_set(pcs_row)
        qa: dict[str, Any] = {}
        try:
            qa = json.loads(row.get("qa_report_json") or "{}")
        except ValueError:
            pass
        return {
            "deliverable": row,
            "render_manifest": manifest,
            "poster_copy_set": copy_set,
            "qa_report": qa,
            "output_available": bool(
                _norm(row.get("output_path")) and Path(row["output_path"]).exists()
            ),
        }

    @staticmethod
    async def list_for_product(product_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await crud.list_poster_deliverables_for_product(_norm(product_id), limit)
