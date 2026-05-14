from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent.api.operator import ContentPackSummary, OperatorProduct, _content_pack_summary
from agent.config import BASE_DIR, OPERATOR_PACK_DIR
from agent.db import crud
from agent.models.asset_registry import AssetOptionsResponse
from agent.models.bosmax_authority import (
    BosmaxAuthorityFallback,
    BosmaxAuthorityOption,
    BosmaxCreativeGroup,
    BosmaxCharacterGroup,
    BosmaxExecutionGroup,
    BosmaxFieldProvenance,
    BosmaxProductContext,
    BosmaxProductContextResponse,
    BosmaxProductGroup,
    BosmaxPromptToolContextResponse,
    BosmaxProvenanceGroup,
    BosmaxSourceMatrixEntry,
    BosmaxSourceMatrixResponse,
    BosmaxVisualGroup,
)
from agent.services.asset_registry_service import list_assets_by_type
from agent.services.offline_prompt_planner import (
    ALLOWED_DESTINATION_MODES,
    ALLOWED_OUTPUT_TYPES,
    ALLOWED_SOURCE_ROUTES,
)
from agent.services.product_intelligence import enrich_product


PRODUCTS_ENDPOINT = "/api/products"
ASSET_REGISTRY_ENDPOINT = "/api/asset-registry/assets"
OPERATOR_ENDPOINT = "/api/operator/content-pack"
AUTHORITY_SCOPE = "BOSMAX_AUTHORITY_REGISTRY_ADAPTER"
EXTERNAL_OPERATOR_PACK = "EXTERNAL_OPERATOR_PACK"
SALES_ANALYZER_NOT_WIRED = "SALES_ANALYZER_NOT_WIRED_TO_PROMPT_TOOLS"


def _normalize_product_key(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _repo_relative(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _map_source_status(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized == "REPO_VERIFIED":
        return "REPO_VERIFIED"
    if normalized == "DERIVED_FROM_PRODUCT_DATA":
        return "PRODUCT_DERIVED"
    if normalized == "INPUT_SLOT_ONLY":
        return "INPUT_SLOT_ONLY"
    if normalized == "EXTERNAL_OPERATOR_PACK_NOT_VERIFIED":
        return "OPERATOR_PACK"
    if normalized == "EMPTY_NOT_VERIFIED":
        return "NOT_FOUND"
    return "NOT_FOUND"


def _option(
    value: str,
    label: str,
    *,
    source_status: str,
    source_file: str | None = None,
    source_endpoint: str | None = None,
    source_origin: str | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> BosmaxAuthorityOption:
    return BosmaxAuthorityOption(
        value=value,
        label=label,
        source_status=source_status,
        source_file=source_file,
        source_endpoint=source_endpoint,
        source_origin=source_origin,
        warnings=list(warnings or []),
        metadata=dict(metadata or {}),
    )


def _fallback(
    label: str,
    reason: str,
    *,
    source_status: str,
    source_file: str | None = None,
    source_endpoint: str | None = None,
    source_origin: str | None = None,
    warnings: list[str] | None = None,
) -> BosmaxAuthorityFallback:
    return BosmaxAuthorityFallback(
        label=label,
        reason=reason,
        source_status=source_status,
        source_file=source_file,
        source_endpoint=source_endpoint,
        source_origin=source_origin,
        warnings=list(warnings or []),
    )


def _field_provenance(
    field: str,
    source_status: str,
    *,
    source_file: str | None = None,
    source_endpoint: str | None = None,
    source_origin: str | None = None,
    warnings: list[str] | None = None,
) -> BosmaxFieldProvenance:
    return BosmaxFieldProvenance(
        field=field,
        source_status=source_status,
        source_file=source_file,
        source_endpoint=source_endpoint,
        source_origin=source_origin,
        warnings=list(warnings or []),
    )


def _matrix_entry(
    key: str,
    label: str,
    source_status: str,
    *,
    source_file: str | None = None,
    source_endpoint: str | None = None,
    source_origin: str | None = None,
    warnings: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> BosmaxSourceMatrixEntry:
    return BosmaxSourceMatrixEntry(
        key=key,
        label=label,
        source_status=source_status,
        source_file=source_file,
        source_endpoint=source_endpoint,
        source_origin=source_origin,
        warnings=list(warnings or []),
        details=dict(details or {}),
    )


def _dedupe_options(options: list[BosmaxAuthorityOption]) -> list[BosmaxAuthorityOption]:
    deduped: list[BosmaxAuthorityOption] = []
    seen: set[tuple[str, str]] = set()
    for option in options:
        key = (option.value, option.label)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(option)
    return deduped


def _asset_options_to_prompt_options(
    response: AssetOptionsResponse,
    *,
    default_source_file: str | None = None,
) -> list[BosmaxAuthorityOption]:
    converted: list[BosmaxAuthorityOption] = []
    mapped_status = _map_source_status(response.source_status)
    for item in response.options:
        converted.append(
            _option(
                item.label,
                item.label,
                source_status=_map_source_status(item.source_status) or mapped_status,
                source_file=item.source_file or default_source_file,
                source_endpoint=f"{ASSET_REGISTRY_ENDPOINT}?asset_type={response.asset_type}",
                warnings=item.warnings,
                metadata={
                    "asset_id": item.asset_id,
                    "asset_type": item.asset_type,
                    **item.metadata,
                },
            )
        )
    return _dedupe_options(converted)


def _build_operator_product_lookup(
    operator_pack: ContentPackSummary | None,
) -> dict[str, OperatorProduct]:
    lookup: dict[str, OperatorProduct] = {}
    for product in operator_pack.products if operator_pack else []:
        for value in [
            product.product_id,
            product.product_name,
            product.raw_product_title,
            product.product_display_name,
            product.product_short_name,
        ]:
            key = _normalize_product_key(value)
            if key and key not in lookup:
                lookup[key] = product
    return lookup


def _match_operator_product(
    product: dict[str, Any],
    lookup: dict[str, OperatorProduct],
) -> OperatorProduct | None:
    for value in [
        product.get("id"),
        product.get("product_display_name"),
        product.get("raw_product_title"),
        product.get("product_short_name"),
    ]:
        key = _normalize_product_key(str(value) if value is not None else None)
        if key and key in lookup:
            return lookup[key]
    return None


def _clean_duration_value(value: str | int | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    return match.group(1) if match else None


def _option_from_literal(value: str, source_file: str) -> BosmaxAuthorityOption:
    return _option(
        value,
        value,
        source_status="REPO_VERIFIED",
        source_file=source_file,
        warnings=[],
    )


def _operator_pack_option(value: str, label: str | None = None) -> BosmaxAuthorityOption:
    return _option(
        value,
        label or value,
        source_status="OPERATOR_PACK",
        source_file=str(OPERATOR_PACK_DIR),
        source_endpoint=OPERATOR_ENDPOINT,
        source_origin=EXTERNAL_OPERATOR_PACK,
        warnings=[EXTERNAL_OPERATOR_PACK],
    )


@lru_cache(maxsize=1)
def _authority_file_presence() -> dict[str, bool]:
    targets = {
        "SOVEREIGN_01_MASTER_SCHEMA.yaml",
        "SOVEREIGN_03_CORE_LOGIC.yaml",
        "SATELLITE_04D_SCENE_CAMERA_ORCHESTRATION_FINAL.yaml",
        "SATELLITE_04B_CAMERA_STYLE_COMPATIBILITY.yaml",
        "SATELLITE_04_MAPPING_MATRIX.yaml",
        "SATELLITE_03_VISUAL_DECK.yaml",
    }
    presence: dict[str, bool] = {name: False for name in targets}
    for path in BASE_DIR.rglob("*.yaml"):
        name = path.name
        if name in presence:
            presence[name] = True
    return presence


def _operator_pack_summary() -> tuple[ContentPackSummary | None, list[str]]:
    try:
        return _content_pack_summary(), []
    except HTTPException:
        return None, ["OPERATOR_PACK_UNAVAILABLE"]


async def _registry_listing(asset_type: str) -> AssetOptionsResponse:
    return await list_assets_by_type(asset_type)


async def _build_product_contexts(
    operator_pack: ContentPackSummary | None,
) -> BosmaxProductGroup:
    raw_products = await crud.list_products(limit=5000)
    operator_lookup = _build_operator_product_lookup(operator_pack)
    contexts: list[BosmaxProductContext] = []
    options: list[BosmaxAuthorityOption] = []

    for raw_product in raw_products:
        enriched = await enrich_product(raw_product)
        product_id = str(enriched.get("id") or enriched.get("product_id") or "")
        if not product_id:
            continue

        operator_product = _match_operator_product(enriched, operator_lookup)
        warnings: list[str] = []
        if operator_product is None:
            warnings.append("OPERATOR_PACK_COPY_SIGNALS_NOT_FOUND")
        if not enriched.get("section_9_overlay_hint"):
            warnings.append("OVERLAY_HINT_NOT_AVAILABLE_FOR_PRODUCT")
        if not enriched.get("section_5_product_physics_prompt"):
            warnings.append("PRODUCT_PHYSICS_HINT_NOT_AVAILABLE_FOR_PRODUCT")

        creative_mapping = {
            "camera_shot": enriched.get("camera_shot"),
            "section_4_hint": enriched.get("section_4_hint"),
            "section_5_physics_hint": enriched.get("section_5_physics_hint"),
            "section_6_copy_hint": enriched.get("section_6_copy_hint"),
            "section_9_overlay_hint": enriched.get("section_9_overlay_hint"),
        }

        product_group = {
            "product_id": product_id,
            "product_display_name": enriched.get("product_display_name"),
            "category": enriched.get("category"),
            "subcategory": enriched.get("subcategory"),
            "type": enriched.get("type"),
            "product_type": enriched.get("product_type") or enriched.get("product_type_id"),
            "source": enriched.get("source"),
            "claim_risk_level": enriched.get("claim_risk_level"),
            "raw_product_title": enriched.get("raw_product_title"),
        }
        creative_group = {
            "trigger_id": enriched.get("trigger_id"),
            "silo": enriched.get("silo"),
            "formula": enriched.get("formula"),
            "hook": operator_product.hook if operator_product else None,
            "usp_1": operator_product.usp_1 if operator_product else None,
            "usp_2": operator_product.usp_2 if operator_product else None,
            "usp_3": operator_product.usp_3 if operator_product else None,
            "cta": operator_product.cta if operator_product else None,
            "copywriting_angle": enriched.get("copywriting_angle") or (operator_product.copywriting_angle if operator_product else None),
            "creative_mapping": creative_mapping,
        }
        visual_group = {
            "scene_context": enriched.get("scene_context"),
            "camera_style": enriched.get("camera_style"),
            "camera_behavior": enriched.get("camera_behavior"),
            "style_reference": None,
            "overlay_hint": enriched.get("section_9_overlay_hint"),
            "product_handling": enriched.get("handling_notes") or enriched.get("recommended_grip"),
            "product_physics": enriched.get("section_5_product_physics_prompt") or enriched.get("physics_class"),
        }

        contexts.append(
            BosmaxProductContext(
                product_id=product_id,
                product=product_group,
                creative=creative_group,
                visual=visual_group,
                warnings=warnings,
                provenance=[
                    _field_provenance("product_id", "REPO_VERIFIED", source_file="agent/api/products.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("product_display_name", "PRODUCT_DERIVED", source_file="agent/services/product_intelligence.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("category", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("subcategory", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("type", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("product_type", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("source", "REPO_VERIFIED", source_file="agent/db/schema.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("claim_risk_level", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("trigger_id", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("silo", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("formula", "PRODUCT_DERIVED", source_file="agent/services/product_mapping.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance(
                        "hook",
                        "OPERATOR_PACK" if operator_product else "NOT_FOUND",
                        source_file=str(OPERATOR_PACK_DIR) if operator_product else None,
                        source_endpoint=OPERATOR_ENDPOINT if operator_product else None,
                        source_origin=EXTERNAL_OPERATOR_PACK if operator_product else None,
                        warnings=[] if operator_product else ["HOOK_NOT_FOUND_IN_OPERATOR_PACK"],
                    ),
                    _field_provenance(
                        "copywriting_angle",
                        "PRODUCT_DERIVED",
                        source_file="agent/services/product_mapping.py",
                        source_endpoint=PRODUCTS_ENDPOINT,
                    ),
                    _field_provenance("scene_context", "PRODUCT_DERIVED", source_file="agent/services/product_preflight.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("camera_style", "PRODUCT_DERIVED", source_file="agent/services/product_preflight.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("camera_behavior", "PRODUCT_DERIVED", source_file="agent/services/product_preflight.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance(
                        "style_reference",
                        "NOT_FOUND",
                        source_file="agent/services/asset_registry_service.py",
                        source_endpoint=f"{ASSET_REGISTRY_ENDPOINT}?asset_type=STYLE_REFERENCE",
                        warnings=["STYLE_REFERENCE_NOT_PRODUCT_SCOPED"],
                    ),
                    _field_provenance("overlay_hint", "PRODUCT_DERIVED", source_file="agent/services/product_preflight.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("product_handling", "PRODUCT_DERIVED", source_file="agent/services/product_preflight.py", source_endpoint=PRODUCTS_ENDPOINT),
                    _field_provenance("product_physics", "PRODUCT_DERIVED", source_file="agent/services/product_intelligence.py", source_endpoint=PRODUCTS_ENDPOINT),
                ],
            )
        )
        options.append(
            _option(
                product_id,
                f"{enriched.get('product_display_name')} ({product_id})",
                source_status="PRODUCT_DERIVED",
                source_file="agent/api/products.py",
                source_endpoint=PRODUCTS_ENDPOINT,
                metadata={
                    "product_display_name": enriched.get("product_display_name"),
                    "source": enriched.get("source"),
                },
            )
        )

    contexts.sort(key=lambda item: item.product.get("product_display_name") or "")
    options.sort(key=lambda item: item.label)
    return BosmaxProductGroup(options=options, contexts=contexts)


async def _build_visual_group() -> BosmaxVisualGroup:
    scene = await _registry_listing("SCENE_CONTEXT")
    style = await _registry_listing("CAMERA_STYLE")
    behavior = await _registry_listing("CAMERA_BEHAVIOR")
    overlay = await _registry_listing("OVERLAY_TEMPLATE")
    handling = await _registry_listing("PRODUCT_HANDLING")
    physics = await _registry_listing("PRODUCT_PHYSICS")
    style_refs = await _registry_listing("STYLE_REFERENCE")
    return BosmaxVisualGroup(
        scene_context_options=_asset_options_to_prompt_options(scene),
        camera_style_options=_asset_options_to_prompt_options(style),
        camera_behavior_options=_asset_options_to_prompt_options(behavior),
        style_reference_options=_asset_options_to_prompt_options(style_refs),
        overlay_hint_options=_asset_options_to_prompt_options(overlay),
        product_handling_options=_asset_options_to_prompt_options(handling),
        product_physics_options=_asset_options_to_prompt_options(physics),
    )


async def _build_character_group(
    operator_pack: ContentPackSummary | None,
) -> BosmaxCharacterGroup:
    character_listing = await _registry_listing("CHARACTER")
    return BosmaxCharacterGroup(
        character_options=_asset_options_to_prompt_options(character_listing),
        avatar_options=_dedupe_options([
            _operator_pack_option(value) for value in (operator_pack.avatars if operator_pack else [])
        ]),
        headwear_suggestions=_dedupe_options([
            _operator_pack_option(value) for value in (operator_pack.headwear_styles if operator_pack else [])
        ]),
        wardrobe_fallback=_fallback(
            "Wardrobe manual fallback",
            "Canonical wardrobe registry is not present in this checkout. Manual override remains available.",
            source_status="NOT_FOUND",
            source_file="agent/services/asset_registry_service.py",
            source_endpoint=f"{ASSET_REGISTRY_ENDPOINT}?asset_type=WARDROBE",
            warnings=["MANUAL_FALLBACK"],
        ),
    )


async def _build_creative_group(
    product_group: BosmaxProductGroup,
    operator_pack: ContentPackSummary | None,
) -> BosmaxCreativeGroup:
    formula_listing = await _registry_listing("COPYWRITING_FORMULA")
    trigger_options = _dedupe_options([
        *[
            _option(
                str(context.creative.get("trigger_id") or ""),
                str(context.creative.get("trigger_id") or ""),
                source_status="PRODUCT_DERIVED",
                source_file="agent/services/product_mapping.py",
                source_endpoint=PRODUCTS_ENDPOINT,
            )
            for context in product_group.contexts
            if context.creative.get("trigger_id")
        ],
        *[_operator_pack_option(value) for value in (operator_pack.triggers if operator_pack else [])],
    ])
    silo_options = _dedupe_options([
        *[
            _option(
                str(context.creative.get("silo") or ""),
                str(context.creative.get("silo") or ""),
                source_status="PRODUCT_DERIVED",
                source_file="agent/services/product_mapping.py",
                source_endpoint=PRODUCTS_ENDPOINT,
            )
            for context in product_group.contexts
            if context.creative.get("silo")
        ],
        *[_operator_pack_option(value) for value in (operator_pack.silos if operator_pack else [])],
    ])
    formula_options = _dedupe_options([
        *_asset_options_to_prompt_options(formula_listing),
        *[_operator_pack_option(value) for value in (operator_pack.formulas if operator_pack else [])],
    ])
    products_with_copy_signals = _dedupe_options([
        _option(
            context.product_id,
            str(context.product.get("product_display_name") or context.product_id),
            source_status="OPERATOR_PACK" if context.creative.get("hook") or context.creative.get("cta") else "NOT_FOUND",
            source_file=str(OPERATOR_PACK_DIR) if context.creative.get("hook") or context.creative.get("cta") else None,
            source_endpoint=OPERATOR_ENDPOINT if context.creative.get("hook") or context.creative.get("cta") else None,
            source_origin=EXTERNAL_OPERATOR_PACK if context.creative.get("hook") or context.creative.get("cta") else None,
            warnings=[] if context.creative.get("hook") or context.creative.get("cta") else ["COPY_SIGNALS_NOT_FOUND"],
            metadata={
                "hook": context.creative.get("hook"),
                "usp_1": context.creative.get("usp_1"),
                "usp_2": context.creative.get("usp_2"),
                "usp_3": context.creative.get("usp_3"),
                "cta": context.creative.get("cta"),
            },
        )
        for context in product_group.contexts
    ])
    return BosmaxCreativeGroup(
        trigger_options=trigger_options,
        silo_options=silo_options,
        formula_options=formula_options,
        products_with_copy_signals=products_with_copy_signals,
    )


async def _build_execution_group(
    operator_pack: ContentPackSummary | None,
) -> BosmaxExecutionGroup:
    languages = await _registry_listing("LANGUAGE")
    platforms = await _registry_listing("PLATFORM")
    engines = await _registry_listing("ENGINE_PROFILE")
    duration_values: list[str] = []
    for values in (operator_pack.durations_by_engine.values() if operator_pack else []):
        for value in values:
            cleaned = _clean_duration_value(value)
            if cleaned and cleaned not in duration_values:
                duration_values.append(cleaned)
    for value in ["8", "16", "24", "32"]:
        if value not in duration_values:
            duration_values.append(value)
    duration_options = [
        _option(
            value,
            value,
            source_status="OPERATOR_PACK" if operator_pack else "REPO_VERIFIED",
            source_file=str(OPERATOR_PACK_DIR) if operator_pack else "agent/services/offline_prompt_planner.py",
            source_endpoint=OPERATOR_ENDPOINT if operator_pack else None,
            source_origin=EXTERNAL_OPERATOR_PACK if operator_pack else None,
            warnings=[EXTERNAL_OPERATOR_PACK] if operator_pack else [],
        )
        for value in duration_values
    ]
    return BosmaxExecutionGroup(
        language_options=_dedupe_options([
            *_asset_options_to_prompt_options(languages),
            *[_operator_pack_option(value) for value in (operator_pack.language_defaults if operator_pack else [])],
        ]),
        platform_options=_asset_options_to_prompt_options(platforms),
        engine_options=_dedupe_options([
            *_asset_options_to_prompt_options(engines),
            *[_operator_pack_option(value) for value in (operator_pack.engines if operator_pack else [])],
        ]),
        duration_options=duration_options,
        source_route_options=[_option_from_literal(value, "agent/services/offline_prompt_planner.py") for value in sorted(ALLOWED_SOURCE_ROUTES)],
        destination_mode_options=[_option_from_literal(value, "agent/services/offline_prompt_planner.py") for value in sorted(ALLOWED_DESTINATION_MODES)],
        output_type_options=[_option_from_literal(value, "agent/services/offline_prompt_planner.py") for value in sorted(ALLOWED_OUTPUT_TYPES)],
    )


def _build_missing_sources() -> list[BosmaxAuthorityFallback]:
    presence = _authority_file_presence()
    missing: list[BosmaxAuthorityFallback] = [
        _fallback(
            "visual_en",
            "visual_en was not found in this checkout.",
            source_status="NOT_FOUND",
            warnings=["NOT_FOUND"],
        ),
        _fallback(
            "audio_en",
            "audio_en was not found in this checkout.",
            source_status="NOT_FOUND",
            warnings=["NOT_FOUND"],
        ),
        _fallback(
            "canonical wardrobe registry",
            "Wardrobe remains a manual fallback because no canonical repo-backed registry dataset exists in this checkout.",
            source_status="NOT_FOUND",
            source_file="agent/services/asset_registry_service.py",
            warnings=["MANUAL_FALLBACK"],
        ),
    ]
    for name, exists in sorted(presence.items()):
        if exists:
            continue
        missing.append(
            _fallback(
                name,
                f"{name} is not present in source control in this checkout.",
                source_status="NOT_FOUND",
                warnings=["NOT_FOUND"],
            )
        )
    return missing


def _build_source_matrix(
    operator_pack: ContentPackSummary | None,
    operator_pack_warnings: list[str],
    product_group: BosmaxProductGroup,
    visual_group: BosmaxVisualGroup,
    character_group: BosmaxCharacterGroup,
) -> list[BosmaxSourceMatrixEntry]:
    entries = [
        _matrix_entry(
            "product_lane",
            "Repo-local product lane",
            "PRODUCT_DERIVED" if product_group.contexts else "NOT_FOUND",
            source_file="agent/api/products.py",
            source_endpoint=PRODUCTS_ENDPOINT,
            details={"product_count": len(product_group.contexts)},
        ),
        _matrix_entry(
            "product_mapping_rules",
            "Product mapping rules",
            "REPO_VERIFIED",
            source_file="data/products/product_mapping_rules.json",
        ),
        _matrix_entry(
            "product_creative_brief",
            "Product creative brief service",
            "REPO_VERIFIED",
            source_file="agent/services/product_creative_brief.py",
        ),
        _matrix_entry(
            "asset_registry",
            "Asset registry",
            "REPO_VERIFIED",
            source_file="agent/api/asset_registry.py",
            source_endpoint="/api/asset-registry/catalog",
            details={
                "scene_options": len(visual_group.scene_context_options),
                "character_options": len(character_group.character_options),
            },
        ),
        _matrix_entry(
            "character_database",
            "Character database",
            "REPO_VERIFIED" if character_group.character_options else "NOT_FOUND",
            source_file="agent/db/schema.py",
            source_endpoint="/api/characters",
            details={"character_options": len(character_group.character_options)},
        ),
        _matrix_entry(
            "operator_content_pack",
            "Operator content pack",
            "OPERATOR_PACK" if operator_pack and operator_pack.available else "NOT_FOUND",
            source_file=str(OPERATOR_PACK_DIR),
            source_endpoint=OPERATOR_ENDPOINT,
            source_origin=EXTERNAL_OPERATOR_PACK,
            warnings=[EXTERNAL_OPERATOR_PACK, *operator_pack_warnings] if operator_pack else operator_pack_warnings,
            details={"available": bool(operator_pack and operator_pack.available)},
        ),
        _matrix_entry(
            "master_ignition",
            "MASTER_IGNITION_TEMPLATE.yaml",
            "OPERATOR_PACK" if operator_pack and "MASTER_IGNITION_TEMPLATE.yaml" in operator_pack.files else "NOT_FOUND",
            source_file=str(OPERATOR_PACK_DIR / "MASTER_IGNITION_TEMPLATE.yaml"),
            source_endpoint=OPERATOR_ENDPOINT if operator_pack else None,
            source_origin=EXTERNAL_OPERATOR_PACK if operator_pack else None,
            warnings=[EXTERNAL_OPERATOR_PACK] if operator_pack else ["NOT_FOUND"],
        ),
        _matrix_entry(
            "script_registry",
            "SCRIPT_REGISTRY_UNIFIED.yaml",
            "OPERATOR_PACK" if operator_pack and "SCRIPT_REGISTRY_UNIFIED.yaml" in operator_pack.files else "NOT_FOUND",
            source_file=str(OPERATOR_PACK_DIR / "SCRIPT_REGISTRY_UNIFIED.yaml"),
            source_endpoint=OPERATOR_ENDPOINT if operator_pack else None,
            source_origin=EXTERNAL_OPERATOR_PACK if operator_pack else None,
            warnings=[EXTERNAL_OPERATOR_PACK] if operator_pack else ["NOT_FOUND"],
        ),
        _matrix_entry(
            "sales_analyzer",
            "Products / Sales Analyzer",
            "REPO_VERIFIED",
            source_file="dashboard/src/pages/ProductsSalesAnalyzerPage.tsx",
            warnings=[SALES_ANALYZER_NOT_WIRED],
        ),
    ]
    return entries


async def get_prompt_tool_context() -> BosmaxPromptToolContextResponse:
    operator_pack, operator_pack_warnings = _operator_pack_summary()
    product_group = await _build_product_contexts(operator_pack)
    visual_group = await _build_visual_group()
    character_group = await _build_character_group(operator_pack)
    creative_group = await _build_creative_group(product_group, operator_pack)
    execution_group = await _build_execution_group(operator_pack)
    missing_sources = _build_missing_sources()
    source_matrix = _build_source_matrix(
        operator_pack,
        operator_pack_warnings,
        product_group,
        visual_group,
        character_group,
    )
    warnings = [AUTHORITY_SCOPE, SALES_ANALYZER_NOT_WIRED, *operator_pack_warnings]
    return BosmaxPromptToolContextResponse(
        product=product_group,
        creative=creative_group,
        visual=visual_group,
        character=character_group,
        execution=execution_group,
        provenance=BosmaxProvenanceGroup(
            source_matrix=source_matrix,
            missing_sources=missing_sources,
            warnings=warnings,
            sales_analyzer_wired_to_prompt_tools=False,
        ),
    )


async def get_source_matrix() -> BosmaxSourceMatrixResponse:
    context = await get_prompt_tool_context()
    return BosmaxSourceMatrixResponse(
        source_matrix=context.provenance.source_matrix,
        missing_sources=context.provenance.missing_sources,
        warnings=context.provenance.warnings,
        sales_analyzer_wired_to_prompt_tools=context.provenance.sales_analyzer_wired_to_prompt_tools,
    )


async def get_product_context(product_id: str) -> BosmaxProductContextResponse:
    context = await get_prompt_tool_context()
    selected = next((item for item in context.product.contexts if item.product_id == product_id), None)
    warnings = [] if selected else [f"PRODUCT_CONTEXT_NOT_FOUND:{product_id}"]
    return BosmaxProductContextResponse(
        product_context=selected,
        warnings=warnings,
        provenance={
            "scope": AUTHORITY_SCOPE,
            "source_endpoint": f"/api/bosmax-authority/product-context/{product_id}",
            "sales_analyzer_wired_to_prompt_tools": context.provenance.sales_analyzer_wired_to_prompt_tools,
        },
    )