"""Credit-free deterministic Campaign poster variants.

Variants reuse the already-generated clean key visual and the immutable copy
set lineage. This module never calls a provider and never writes a database
row; it only derives manifests and lets the local compositor render a preview
on demand.
"""
from __future__ import annotations

from typing import Any

from agent.db import crud
from agent.models.poster_campaign_qa import (
    CampaignVariant,
    CampaignVariantsRequest,
    CampaignVariantsResponse,
)
from agent.models.poster_copy_set import serialize_poster_copy_set
from agent.models.poster_render_manifest import PosterRenderManifest
from agent.services import poster_compositor_service as compositor
from agent.services.poster_campaign_qa_service import manifest_fingerprint
from agent.services.poster_template_service import PosterTemplateError, build_render_manifest, template_contract


class CampaignVariantError(ValueError):
    def __init__(self, code: str, message: str = "", status_code: int = 409) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _copy_with_patch(copy_set: dict[str, Any], patch: dict[str, str]) -> dict[str, Any]:
    allowed = {"primary_message", "support_message", "cta", "disclaimer"}
    updated = dict(copy_set)
    for key, value in patch.items():
        if key in allowed:
            updated[key] = _clean(value)
    return updated


def _load_manifest(row: dict[str, Any]) -> PosterRenderManifest:
    try:
        return PosterRenderManifest.model_validate_json(row.get("render_manifest_json") or "{}")
    except (ValueError, TypeError) as exc:
        raise CampaignVariantError(
            "POSTER_VARIANT_MANIFEST_INVALID",
            "saved poster manifest cannot be reconstructed",
            409,
        ) from exc


async def _resolve_inputs(
    poster_deliverable_id: str,
    request: CampaignVariantsRequest,
) -> tuple[dict[str, Any], PosterRenderManifest, dict[str, Any]]:
    row = await crud.get_poster_deliverable(_clean(poster_deliverable_id))
    if not row:
        raise CampaignVariantError("POSTER_DELIVERABLE_NOT_FOUND", status_code=404)
    manifest = _load_manifest(row)
    if _clean(manifest.provenance.creative_mode).upper() != "CREATIVE_CAMPAIGN":
        raise CampaignVariantError(
            "POSTER_VARIANTS_NOT_APPLICABLE",
            "deterministic Campaign variants are not available for Exact Commerce",
        )
    pcs = await crud.get_poster_copy_set(_clean(row.get("poster_copy_set_id")))
    if not pcs:
        raise CampaignVariantError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
    copy_set = _copy_with_patch(serialize_poster_copy_set(pcs), request.copy_patch)
    return row, manifest, copy_set


async def build_campaign_variants(
    poster_deliverable_id: str,
    request: CampaignVariantsRequest | None = None,
) -> CampaignVariantsResponse:
    request = request or CampaignVariantsRequest()
    row, base_manifest, copy_set = await _resolve_inputs(poster_deliverable_id, request)
    route = _clean(request.design_route).upper() or base_manifest.design_route
    if not route:
        raise CampaignVariantError("POSTER_VARIANT_DESIGN_ROUTE_MISSING")
    try:
        contract = template_contract(_clean(row.get("recipe_id")), route)
    except PosterTemplateError as exc:
        raise CampaignVariantError(exc.code, str(exc), exc.status_code) from exc
    variants = list((contract.get("route_variants") or {}).keys())
    if len(variants) < 3:
        raise CampaignVariantError(
            "POSTER_VARIANT_AUTHORITY_INCOMPLETE",
            f"design route {route} exposes fewer than three deterministic variants",
            500,
        )
    chosen = variants[:3]
    requested_variant = _clean(request.layout_variant).upper()
    if requested_variant and requested_variant not in chosen:
        raise CampaignVariantError(
            "POSTER_VARIANT_UNKNOWN",
            f"layout variant {requested_variant} is not one of the three controlled variants",
            422,
        )
    manifests: list[tuple[str, PosterRenderManifest]] = []
    for variant in chosen:
        direction = {
            "mode": base_manifest.provenance.creative_mode,
            "authority_version": base_manifest.provenance.creative_direction_authority_version,
            "representation_policy_version": base_manifest.provenance.representation_policy_version,
            "design_route": route,
            "layout_variant": variant,
        }
        try:
            manifest = build_render_manifest(
                recipe_id=_clean(row.get("recipe_id")),
                copy_set=copy_set,
                background_media_id=base_manifest.background_media_id,
                background_local_path=base_manifest.background_local_path,
                image_model=base_manifest.provenance.image_model,
                background_prompt_fingerprint=base_manifest.provenance.background_prompt_fingerprint,
                creative_direction=direction,
                composition_plan=base_manifest.provenance.composition_plan,
                design_route=route,
                layout_variant=variant,
                exact_product_layer=None,
            )
        except PosterTemplateError as exc:
            raise CampaignVariantError(exc.code, str(exc), exc.status_code) from exc
        manifests.append((variant, manifest))

    result: list[CampaignVariant] = []
    for index, (variant, manifest) in enumerate(manifests, start=1):
        fingerprint = manifest_fingerprint(manifest)
        variant_id = f"v{index}-{fingerprint[:16]}"
        result.append(
            CampaignVariant(
                variant_id=variant_id,
                variant_index=index,
                design_route=route,
                layout_variant=variant,
                manifest_sha256=fingerprint,
                output_url=(
                    f"/api/poster/deliverables/{_clean(poster_deliverable_id)}"
                    f"/variants/{variant_id}/output"
                ),
                key_visual_media_id=base_manifest.background_media_id,
                provider_operation_count=0,
                max_retry_operations=0,
                kv_reused=True,
            )
        )
    if len({item.manifest_sha256 for item in result}) != 3:
        raise CampaignVariantError(
            "POSTER_VARIANT_FINGERPRINT_COLLISION",
            "controlled variants did not produce three distinct manifests",
            500,
        )
    return CampaignVariantsResponse(
        product_id=_clean(row.get("product_id")),
        poster_deliverable_id=_clean(poster_deliverable_id),
        selected_copy_route=_clean(copy_set.get("campaign_copy_route_id") or copy_set.get("angle")),
        selected_design_route=route,
        variants=result,
        key_visual_reused=True,
        provider_operation_count=0,
        max_retry_operations=0,
        warnings=[
            "VARIANTS_ARE_DETERMINISTIC_LOCAL_COMPOSITIONS",
            "NO_PROVIDER_CALL_OR_CREDIT_SPEND",
            "HUMAN_REVIEW_REQUIRED_FOR_PRODUCT_IDENTITY_AND_AESTHETIC_QUALITY",
        ],
    )


async def render_campaign_variant(
    poster_deliverable_id: str,
    variant_id: str,
    request: CampaignVariantsRequest | None = None,
) -> tuple[Any, CampaignVariant]:
    response = await build_campaign_variants(poster_deliverable_id, request)
    selected = next((item for item in response.variants if item.variant_id == variant_id), None)
    if selected is None:
        raise CampaignVariantError("POSTER_VARIANT_UNKNOWN", status_code=404)
    row, base_manifest, copy_set = await _resolve_inputs(
        poster_deliverable_id, request or CampaignVariantsRequest()
    )
    direction = {
        "mode": base_manifest.provenance.creative_mode,
        "authority_version": base_manifest.provenance.creative_direction_authority_version,
        "representation_policy_version": base_manifest.provenance.representation_policy_version,
        "design_route": selected.design_route,
        "layout_variant": selected.layout_variant,
    }
    try:
        manifest = build_render_manifest(
            recipe_id=_clean(row.get("recipe_id")),
            copy_set=copy_set,
            background_media_id=base_manifest.background_media_id,
            background_local_path=base_manifest.background_local_path,
            image_model=base_manifest.provenance.image_model,
            background_prompt_fingerprint=base_manifest.provenance.background_prompt_fingerprint,
            creative_direction=direction,
            composition_plan=base_manifest.provenance.composition_plan,
            design_route=selected.design_route,
            layout_variant=selected.layout_variant,
            exact_product_layer=None,
        )
    except PosterTemplateError as exc:
        raise CampaignVariantError(exc.code, str(exc), exc.status_code) from exc
    if manifest_fingerprint(manifest) != selected.manifest_sha256:
        raise CampaignVariantError("POSTER_VARIANT_FINGERPRINT_MISMATCH", status_code=409)
    out_path, _report = await compositor.compose(
        manifest,
        render_id=f"campaign-variant-{selected.manifest_sha256[:24]}",
    )
    return out_path, selected
