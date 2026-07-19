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

from agent.config import OUTPUT_DIR
from agent.db import crud
from agent.models.creative_asset import CreativeAssetCreateRequest
from agent.services.creative_direction_service import resolve_creative_direction
from agent.models.poster_copy_set import (
    STATUS_POSTER_COPY_APPROVED,
    poster_fields_to_zone_fields,
    serialize_poster_copy_set,
)
from agent.models.poster_copy_quality import PosterCopyQualityRequest
from agent.models.poster_render_manifest import (
    PosterQAReport,
    build_qa_report,
)
from agent.services import poster_compositor_service as compositor
from agent.services import poster_recipe_service
from agent.services.poster_composition_service import (
    build_composition_constraints,
    resolve_poster_composition,
)
from agent.services.poster_copy_quality_service import evaluate_poster_copy
from agent.services.product_truth_service import ProductTruthService
from agent.services.creative_asset_service import (
    CREATIVE_ASSET_UPLOAD_DIR,
    create_creative_asset,
    get_creative_asset_file_path,
)
from agent.services.img_asset_lane_config import derive_asset_governance
from agent.services.poster_template_service import (
    PosterTemplateError,
    build_render_manifest,
    manifest_frame_ratio,
    template_contract,
)

# HONEST product-truth stamping: REFERENCE_CONDITIONED generation cannot prove
# pixel-level product preservation — never stamp PRESERVED for it. A
# DETERMINISTIC_COMPOSITE is likewise NOT trusted just because its strategy
# name says "composite": it stays *_UNVERIFIED until explicit verification
# evidence is supplied. Unknown strategies fail to the most conservative label.
_TRUTH_STATUS_BY_STRATEGY = {
    "REFERENCE_CONDITIONED": "REFERENCE_CONDITIONED_UNVERIFIED",
    "DETERMINISTIC_COMPOSITE": "DETERMINISTIC_COMPOSITE_UNVERIFIED",
}
_TRUTH_STATUS_DEFAULT = "HUMAN_REVIEW_REQUIRED"

# A deterministic composite earns the VERIFIED label ONLY when every piece of
# verification evidence is present and truthy: an approved product-asset
# reference, that asset's hash/provenance, a successful deterministic
# composition, and a verification/attestation record. Missing ANY of these →
# fail closed to *_UNVERIFIED. Absent an actual deterministic-composite pipeline,
# no caller supplies this, so composites correctly remain unverified.
_COMPOSITE_VERIFICATION_KEYS = (
    "approved_product_asset_id",
    "product_asset_sha256",
    "composition_ok",
    "attestation",
)


def _has_composite_verification(verification: dict[str, Any] | None) -> bool:
    if not isinstance(verification, dict):
        return False
    return all(bool(verification.get(k)) for k in _COMPOSITE_VERIFICATION_KEYS)


def derive_poster_truth_status(
    composition_strategy: str, *, verification: dict[str, Any] | None = None
) -> str:
    base = _TRUTH_STATUS_BY_STRATEGY.get(
        str(composition_strategy or "").strip(), _TRUTH_STATUS_DEFAULT
    )
    if base == "DETERMINISTIC_COMPOSITE_UNVERIFIED" and _has_composite_verification(
        verification
    ):
        return "DETERMINISTIC_COMPOSITE_VERIFIED"
    return base


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


# Trusted storage roots for ANY background image — whether supplied as a client
# background_local_path OR resolved from a background_media_id artifact row. A
# database record does NOT make a path safe: the SAME canonical-root containment
# is enforced on both. Generated scenes live under OUTPUT_DIR/retrieved and
# approved product photos under the creative-asset upload dir; both are trusted.
# Traversal/symlinks collapse under resolve(). Tests may extend via monkeypatch.
_ALLOWED_BACKGROUND_ROOTS: tuple[Path, ...] = (OUTPUT_DIR, CREATIVE_ASSET_UPLOAD_DIR)


def _validate_trusted_storage_path(
    local: str,
    *,
    missing_code: str = "POSTER_BACKGROUND_FILE_MISSING",
    forbidden_code: str = "POSTER_BACKGROUND_PATH_FORBIDDEN",
) -> str:
    """Canonicalize a storage path and enforce trusted-root containment.

    Shared by the client-path and media-id-resolved-artifact lanes so neither
    can escape the trusted roots. resolve(strict=True) proves existence and
    collapses symlinks/traversal to a canonical path before containment.
    """
    try:
        resolved = Path(local).resolve(strict=True)
    except OSError:
        raise PosterDeliverableError(
            missing_code,
            f"background image file missing: {local}",
            status_code=404,
        )
    except RuntimeError:
        raise PosterDeliverableError(
            forbidden_code,
            "background path could not be safely canonicalized",
            status_code=422,
        )
    if not resolved.is_file():
        raise PosterDeliverableError(
            forbidden_code,
            "background path must resolve to a regular file",
            status_code=422,
        )
    for root in _ALLOWED_BACKGROUND_ROOTS:
        try:
            root_resolved = Path(root).resolve()
        except (OSError, RuntimeError):
            continue
        if resolved == root_resolved or root_resolved in resolved.parents:
            return str(resolved)
    raise PosterDeliverableError(
        forbidden_code,
        "background path is outside the trusted generated/creative-asset "
        "storage roots",
        status_code=422,
    )


# Back-compat alias: the client-path validator is now the shared trusted-storage
# resolver (also applied to media-id-resolved artifact paths). Same signature and
# error codes, so existing callers/tests are unaffected.
_validate_client_background_path = _validate_trusted_storage_path


def _quality_report_for_copy_set(copy_set: dict[str, Any], recipe: Any):
    """Reuse the established poster copy-quality authority over the poster-
    native copy set (never a duplicated validator)."""
    return evaluate_poster_copy(
        PosterCopyQualityRequest(
            archetype=_norm(getattr(recipe, "archetype", "")),
            language=_norm(copy_set.get("language")) or "ms",
            max_chips=(getattr(recipe, "max_chips", 3) or 3),
            poster_headline=_norm(copy_set.get("primary_message")),
            poster_support_line=_norm(copy_set.get("support_message")),
            poster_chips=[
                _norm(c) for c in (copy_set.get("proof_points") or []) if _norm(c)
            ],
            poster_cta=_norm(copy_set.get("cta")),
        )
    )


def _resolve_canonical_composition_plan(
    *,
    product: dict[str, Any],
    copy_set: dict[str, Any] | None,
    recipe_id: str,
    direction: Any,
    operator_human_presence: str = "",
    frame_ratio: str = "",
) -> dict[str, Any]:
    """Resolve the ONE canonical composition plan from the real authorities.

    Product Truth comes from the actual computed truth profile, identity policy
    from the resolved Creative Direction, recipe constraints from the real
    template contract, and copy governance from the established quality
    authority. Legacy no-mode callers get {} — nothing is fabricated.
    """
    if direction is None:
        return {}
    recipe_id = _norm(recipe_id)
    recipe_obj = poster_recipe_service.get_recipe(recipe_id) if recipe_id else None
    contract = template_contract(recipe_id) if recipe_id else None
    quality = (
        _quality_report_for_copy_set(copy_set, recipe_obj) if copy_set else None
    )
    constraints = build_composition_constraints(
        product=product,
        truth_profile=ProductTruthService.build_computed_profile(product),
        creative_direction=direction,
        operator_human_presence=operator_human_presence,
        recipe=recipe_obj,
        template_contract=contract,
        copy_quality_report=quality,
    )
    return resolve_poster_composition(
        creative_direction=direction,
        recipe_id=recipe_id,
        # The compositor renders the manifest canvas — its REAL reduced ratio
        # is the plan's frame ratio unless the caller supplies an actual one.
        frame_ratio=_norm(frame_ratio) or manifest_frame_ratio(),
        fields=poster_fields_to_zone_fields(copy_set) if copy_set else {},
        constraints=constraints,
    )


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
        art_local = _norm(artifact.get("local_path"))
        if not art_local:
            raise PosterDeliverableError(
                "POSTER_BACKGROUND_FILE_MISSING",
                "background image file missing: (none)",
                status_code=404,
            )
        # A DB record does not make a path safe — the artifact-recorded path is
        # validated against the SAME trusted roots as client input.
        return media_id, _validate_trusted_storage_path(
            art_local,
            missing_code="POSTER_BACKGROUND_FILE_MISSING",
            forbidden_code="POSTER_BACKGROUND_ARTIFACT_PATH_FORBIDDEN",
        )
    if not local:
        raise PosterDeliverableError(
            "POSTER_BACKGROUND_FILE_MISSING",
            "background image file missing: (none)",
            status_code=404,
        )
    return media_id, _validate_trusted_storage_path(local)


async def _resolve_durable_output(row: dict[str, Any]) -> dict[str, Any]:
    """Resolve the original saved poster output from the most durable source.

    Order (never regenerates):
      1. the deliverable ``output_path`` file, verified against ``output_sha256``;
      2. the linked Creative Library asset file, verified against the same hash;
      3. honest failure.
    A hash mismatch on BOTH copies fails closed (POSTER_OUTPUT_IDENTITY_MISMATCH)
    rather than serving bytes that are not the saved poster.
    """
    expected = _norm(row.get("output_sha256"))
    saw_mismatch = False

    out_path = _norm(row.get("output_path"))
    if out_path and Path(out_path).exists():
        actual = _sha256(Path(out_path))
        if not expected or actual == expected:
            return {
                "available": True,
                "source": "DELIVERABLE_FILE",
                "path": out_path,
                "sha256_verified": bool(expected),
            }
        saw_mismatch = True

    asset_id = _norm(row.get("creative_asset_id"))
    if asset_id:
        asset_path = await get_creative_asset_file_path(asset_id)
        if asset_path and Path(asset_path).exists():
            actual = _sha256(Path(asset_path))
            if not expected or actual == expected:
                return {
                    "available": True,
                    "source": "CREATIVE_LIBRARY",
                    "path": str(asset_path),
                    "sha256_verified": bool(expected),
                }
            saw_mismatch = True

    return {
        "available": False,
        "source": None,
        "path": None,
        "sha256_verified": False,
        "reason": (
            "POSTER_OUTPUT_IDENTITY_MISMATCH" if saw_mismatch
            else "POSTER_OUTPUT_UNAVAILABLE"
        ),
    }


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
        creative_mode: str | None = None,
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
        settings = settings or {}
        direction = resolve_creative_direction(creative_mode, product=dict(product)) if creative_mode is not None else None

        media_id, bg_local = await _resolve_background(
            background_media_id, background_local_path
        )

        try:
            # B-01/B-03: the canonical plan is resolved ONCE here — with the
            # real product-truth/identity/recipe constraints — and passed into
            # the manifest verbatim so save/reopen preserves it deterministically.
            composition_plan = _resolve_canonical_composition_plan(
                product=dict(product),
                copy_set=copy_set,
                recipe_id=_norm(recipe_id),
                direction=direction,
            )
            manifest = build_render_manifest(
                recipe_id=_norm(recipe_id),
                copy_set=copy_set,
                background_media_id=media_id,
                background_local_path=bg_local,
                image_model=_norm(image_model),
                creative_direction=({"mode": direction.mode.value, "authority_version": direction.authority_version, "representation_policy_version": direction.representation_policy_version} if direction else None),
                composition_plan=composition_plan,
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
            # The EXACT plan the manifest preserves — so the UI can prove the
            # compiled poster used the same plan it displayed.
            "composition_plan": composition_plan,
        }

    @staticmethod
    async def preview_composition_plan(
        *,
        product_id: str,
        creative_mode: str,
        recipe_id: str = "",
        poster_copy_set_id: str = "",
        human_presence_mode: str = "",
        frame_ratio: str = "",
    ) -> dict[str, Any]:
        """Read-only backend-resolved composition plan for the Guided summary.

        Uses the SAME canonical resolver + constraint assembly as compose, so
        the plan the operator sees is the plan a compile would preserve. No
        mutation, no generation, no credit spend.
        """
        product = await crud.get_product(_norm(product_id))
        if not product:
            raise PosterDeliverableError("PRODUCT_NOT_FOUND", status_code=404)
        direction = resolve_creative_direction(
            _norm(creative_mode), product=dict(product)
        )
        copy_set = None
        if _norm(poster_copy_set_id):
            pcs_row = await crud.get_poster_copy_set(_norm(poster_copy_set_id))
            if not pcs_row:
                raise PosterDeliverableError(
                    "POSTER_COPY_SET_NOT_FOUND", status_code=404
                )
            if _norm(pcs_row.get("product_id")) != _norm(product_id):
                raise PosterDeliverableError(
                    "POSTER_COPY_SET_PRODUCT_MISMATCH", status_code=409
                )
            copy_set = serialize_poster_copy_set(pcs_row)
        try:
            plan = _resolve_canonical_composition_plan(
                product=dict(product),
                copy_set=copy_set,
                recipe_id=_norm(recipe_id),
                direction=direction,
                operator_human_presence=_norm(human_presence_mode),
                frame_ratio=_norm(frame_ratio),
            )
        except PosterTemplateError as exc:
            raise PosterDeliverableError(exc.code, str(exc), status_code=exc.status_code)
        return {"composition_plan": plan}

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
        truth_status = derive_poster_truth_status(row.get("composition_strategy"))
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
                f"deliverable={row.get('poster_deliverable_id')}; "
                f"product truth: {truth_status} — reference-conditioned scene; "
                "product identity/label/scale need human review"
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
            product_truth_status=truth_status,
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
        # The saved poster's copy set may since have been SUPERSEDED. Reopen must
        # still restore the EXACT historical copy the poster was rendered with —
        # read-only — and flag it so the UI can label it and offer a fork.
        copy_set_status = _norm(pcs_row.get("status")) if pcs_row else ""
        durable = await _resolve_durable_output(row)
        return {
            "deliverable": row,
            "render_manifest": manifest,
            "poster_copy_set": copy_set,
            "poster_copy_set_status": copy_set_status,
            "poster_copy_set_historical": copy_set_status == "POSTER_COPY_SUPERSEDED",
            "qa_report": qa,
            "output_available": durable["available"],
            "output_source": durable["source"],
            "output_sha256_verified": durable["sha256_verified"],
        }

    @staticmethod
    async def get_output_file(poster_deliverable_id: str) -> dict[str, Any]:
        """Resolve the ORIGINAL saved poster bytes from the most durable source.

        Reopen must not depend only on ``output_path`` (it can be purged). We
        try the original deliverable file (sha-verified), then the durable
        Creative Library asset (sha-verified), then fail honestly. The original
        saved output is served verbatim — a poster is NEVER silently regenerated.
        """
        row = await crud.get_poster_deliverable(_norm(poster_deliverable_id))
        if not row:
            raise PosterDeliverableError("POSTER_DELIVERABLE_NOT_FOUND", status_code=404)
        durable = await _resolve_durable_output(row)
        if not durable["available"]:
            code = durable.get("reason") or "POSTER_OUTPUT_UNAVAILABLE"
            raise PosterDeliverableError(
                code,
                "original saved poster output is unavailable from all durable "
                "sources — refusing to regenerate",
                status_code=409 if code == "POSTER_OUTPUT_IDENTITY_MISMATCH" else 404,
            )
        return durable

    @staticmethod
    async def get_by_creative_asset(creative_asset_id: str) -> dict[str, Any]:
        """Creative Library reopen: asset id → full reconstruction contract."""
        row = await crud.get_poster_deliverable_by_asset(_norm(creative_asset_id))
        if not row:
            raise PosterDeliverableError(
                "POSTER_DELIVERABLE_NOT_FOUND",
                f"no poster deliverable saved for creative asset {creative_asset_id}",
                status_code=404,
            )
        return await PosterDeliverableService.get_with_manifest(
            row["poster_deliverable_id"]
        )

    @staticmethod
    async def list_for_product(product_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await crud.list_poster_deliverables_for_product(_norm(product_id), limit)
