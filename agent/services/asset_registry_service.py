from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.db import crud
from agent.materials import list_materials as list_builtin_materials
from agent.models.asset_registry import (
    AssetCatalogEntry,
    AssetCatalogResponse,
    AssetCompatibilityRequest,
    AssetCompatibilityResponse,
    AssetDetailResponse,
    AssetOption,
    AssetOptionsResponse,
    AssetSelectionRequest,
    AssetSelectionResponse,
)
from agent.services.product_mapping import load_mapping_rules
from agent.services.product_physics import PHYSICS_FAMILY_RULES


SUPPORTED_ASSET_TYPES = [
    "CHARACTER",
    "WARDROBE",
    "HEADWEAR",
    "CAMERA_STYLE",
    "CAMERA_BEHAVIOR",
    "SCENE_CONTEXT",
    "COPYWRITING_FORMULA",
    "OVERLAY_TEMPLATE",
    "PRODUCT_HANDLING",
    "PRODUCT_PHYSICS",
    "PRODUCT_REFERENCE",
    "STYLE_REFERENCE",
    "LANGUAGE",
    "PLATFORM",
    "ENGINE_PROFILE",
]

ASSET_TYPE_DESCRIPTIONS = {
    "CHARACTER": "Prompt-generation character references sourced from repo-local character rows when present.",
    "WARDROBE": "Wardrobe selection slot for future assisted/manual planners. No repo registry dataset is proven.",
    "HEADWEAR": "Headwear selection slot for future assisted/manual planners. No repo registry dataset is proven.",
    "CAMERA_STYLE": "Camera style hints derived from repo-local product metadata when available.",
    "CAMERA_BEHAVIOR": "Camera behavior hints derived from repo-local product metadata when available.",
    "SCENE_CONTEXT": "Scene context hints derived from repo-local product metadata when available.",
    "COPYWRITING_FORMULA": "Copywriting formulas resolved from source-controlled product mapping profile rules.",
    "OVERLAY_TEMPLATE": "Overlay hint surface. No canonical template registry is proven.",
    "PRODUCT_HANDLING": "Handling guidance surfaced from source-controlled product physics rules.",
    "PRODUCT_PHYSICS": "Physics guidance surfaced from source-controlled product physics rules.",
    "PRODUCT_REFERENCE": "Product reference options derived from repo-local product rows.",
    "STYLE_REFERENCE": "Style references surfaced from source-controlled built-in material definitions.",
    "LANGUAGE": "Language input-slot defaults visible in repo surfaces. Not a governed registry dataset.",
    "PLATFORM": "Platform input-slot defaults visible in repo surfaces. Not a governed registry dataset.",
    "ENGINE_PROFILE": "Engine profile input-slot defaults visible in repo surfaces. Not a governed registry dataset.",
}

STATIC_INPUT_SLOT_OPTIONS = {
    "LANGUAGE": [
        ("language:Malay", "Malay", "Operator and batch defaults prove Malay as a supported language slot."),
        ("language:English", "English", "Operator defaults prove English as a supported language slot."),
    ],
    "PLATFORM": [
        ("platform:TikTok", "TikTok", "Repo defaults prove TikTok as a supported platform slot."),
    ],
    "ENGINE_PROFILE": [
        ("engine:VEO_3_1", "VEO_3_1", "Repo defaults prove VEO_3_1 as a supported engine slot."),
    ],
}

INPUT_SLOT_ONLY_TYPES = {"WARDROBE", "HEADWEAR", "LANGUAGE", "PLATFORM", "ENGINE_PROFILE"}
PRODUCT_DERIVED_TYPES = {"CAMERA_STYLE", "CAMERA_BEHAVIOR", "SCENE_CONTEXT", "OVERLAY_TEMPLATE", "PRODUCT_REFERENCE"}
FORBIDDEN_CANONICAL_WRITE_KEYS = {
    "canonical_registry_write",
    "write_canonical_registry",
    "auto_write_registry",
}
FORBIDDEN_UNVERIFIED_PROOF_KEYS = {
    "mark_external_asset_verified",
    "external_registry_truth_verified",
    "mark_unverified_truth_as_verified",
    "verify_external_truth",
}


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _repo_relative(path: str) -> str:
    return path.replace("\\", "/")


def _base_provenance() -> dict[str, Any]:
    return {
        "scope": "ROUND_8_ASSET_REGISTRY_API_ONLY",
        "asset_registry_service": "agent.services.asset_registry_service",
        "safe_read_only_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_ui_modules": False,
        "uses_runtime_orchestration": False,
        "uses_db_writes": False,
    }


def _titleize(value: str) -> str:
    return value.replace("_", " ").title()


def _input_slot_option(
    asset_type: str,
    asset_id: str,
    label: str,
    description: str,
) -> AssetOption:
    return AssetOption(
        asset_id=asset_id,
        asset_type=asset_type,
        label=label,
        description=description,
        metadata={"slot_type": "input_default"},
        compatibility_tags=[f"asset_type:{asset_type.lower()}"],
        source_status="INPUT_SLOT_ONLY",
        source_file="agent/api/operator.py",
        source_path="repo-input-slot-defaults",
        warnings=["INPUT_SLOT_ONLY_NO_SOURCE_CONTROLLED_REGISTRY_DATASET"],
        provenance=_base_provenance(),
        is_selectable=True,
        is_canonical=False,
        verified_level="INPUT_SLOT_ONLY",
    )


def _empty_response(asset_type: str, source_status: str, warning: str, empty_reason: str) -> AssetOptionsResponse:
    warnings = [warning] if warning else []
    return AssetOptionsResponse(
        asset_type=asset_type,
        options=[],
        warnings=warnings,
        provenance=_base_provenance(),
        source_status=source_status,
        empty_reason=empty_reason,
    )


async def _load_character_options() -> AssetOptionsResponse:
    rows = await crud.list_characters()
    options = [
        AssetOption(
            asset_id=f"character:{row['id']}",
            asset_type="CHARACTER",
            label=row.get("name") or row["id"],
            description=row.get("description") or "Character row from repo-local database.",
            metadata={
                "entity_type": row.get("entity_type"),
                "has_media_id": bool(row.get("media_id")),
                "has_reference_image_url": bool(row.get("reference_image_url")),
            },
            compatibility_tags=[f"entity_type:{row.get('entity_type') or 'character'}"],
            source_status="REPO_VERIFIED",
            source_file="agent/db/schema.py",
            source_path="sqlite:character",
            warnings=[] if row.get("media_id") else ["GENERATED_CHARACTER_ASSET_NOT_PROVEN_BY_MEDIA_RECORD"],
            provenance=_base_provenance(),
            is_selectable=True,
            is_canonical=False,
            verified_level="REPO_ROW",
        )
        for row in rows
    ]
    if not options:
        return _empty_response(
            "CHARACTER",
            "EMPTY_NOT_VERIFIED",
            "NO_REPO_CHARACTER_ROWS_FOUND",
            "No character rows were found in the repo-local database.",
        )
    return AssetOptionsResponse(
        asset_type="CHARACTER",
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="REPO_VERIFIED",
    )


async def _load_product_rows() -> list[dict[str, Any]]:
    return await crud.list_products(limit=500)


def _unique_non_empty_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        value = str(row.get(field) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


async def _load_product_derived_options(asset_type: str, field: str, extra_warning: str | None = None) -> AssetOptionsResponse:
    rows = await _load_product_rows()
    values = _unique_non_empty_values(rows, field)
    options = [
        AssetOption(
            asset_id=f"{asset_type.lower()}:{index}",
            asset_type=asset_type,
            label=value,
            description=f"{asset_type.replace('_', ' ').title()} value derived from repo-local product data.",
            metadata={"field": field, "derived_from": "product"},
            compatibility_tags=["derived:product_data"],
            source_status="DERIVED_FROM_PRODUCT_DATA",
            source_file="agent/db/schema.py",
            source_path=f"sqlite:product.{field}",
            warnings=[warning for warning in [extra_warning, "DERIVED_FROM_PRODUCT_DATA_NOT_CANONICAL_REGISTRY_TRUTH"] if warning],
            provenance=_base_provenance(),
            is_selectable=True,
            is_canonical=False,
            verified_level="DERIVED_NOT_CANONICAL",
        )
        for index, value in enumerate(values, start=1)
    ]
    if not options:
        if asset_type in {"CAMERA_STYLE", "CAMERA_BEHAVIOR", "SCENE_CONTEXT"}:
            return _empty_response(
                asset_type,
                "INPUT_SLOT_ONLY",
                "INPUT_SLOT_ONLY_NO_REPO_DERIVED_VALUES_FOUND",
                "Repo proves the input slot exists, but no repo-local derived values were found.",
            )
        return _empty_response(
            asset_type,
            "EMPTY_NOT_VERIFIED",
            "NO_REPO_PRODUCT_DERIVED_VALUES_FOUND",
            "No repo-local product-derived values were found for this asset type.",
        )
    return AssetOptionsResponse(
        asset_type=asset_type,
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="DERIVED_FROM_PRODUCT_DATA",
    )


def _rules_source_file() -> str:
    return _repo_relative(str(Path("data/products/product_mapping_rules.json")))


def _load_formula_options() -> AssetOptionsResponse:
    rules = load_mapping_rules()
    by_formula: dict[str, dict[str, set[str]]] = {}
    for rule in rules.get("profile_rules", []):
        formula = str(rule.get("formula") or "").strip()
        if not formula:
            continue
        current = by_formula.setdefault(formula, {"silos": set(), "triggers": set()})
        silo = str(rule.get("silo") or "").strip()
        trigger = str(rule.get("trigger_id") or "").strip()
        if silo:
            current["silos"].add(silo)
        if trigger:
            current["triggers"].add(trigger)

    options = [
        AssetOption(
            asset_id=f"formula:{formula}",
            asset_type="COPYWRITING_FORMULA",
            label=formula,
            description="Copywriting formula sourced from source-controlled product mapping profile rules.",
            metadata={
                "silos": sorted(list(meta["silos"])),
                "triggers": sorted(list(meta["triggers"])),
            },
            compatibility_tags=[f"formula:{formula.lower()}"],
            source_status="REPO_VERIFIED",
            source_file=_rules_source_file(),
            source_path="profile_rules[].formula",
            warnings=["FORMULA_IS_RULE_SURFACE_NOT_CANONICAL_ASSET_TABLE"],
            provenance=_base_provenance(),
            is_selectable=True,
            is_canonical=False,
            verified_level="REPO_RULE_SURFACE",
        )
        for formula, meta in sorted(by_formula.items())
    ]
    if not options:
        return _empty_response(
            "COPYWRITING_FORMULA",
            "EMPTY_NOT_VERIFIED",
            "NO_REPO_COPYWRITING_FORMULAS_FOUND",
            "No source-controlled copywriting formulas were found.",
        )
    return AssetOptionsResponse(
        asset_type="COPYWRITING_FORMULA",
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="REPO_VERIFIED",
    )


def _load_product_physics_options() -> AssetOptionsResponse:
    options = []
    for family, rule in sorted(PHYSICS_FAMILY_RULES.items()):
        options.append(
            AssetOption(
                asset_id=f"product-physics:{family}",
                asset_type="PRODUCT_PHYSICS",
                label=_titleize(family),
                description=rule.get("section_5_product_physics_prompt") or "Product physics rule surface.",
                metadata={
                    "physics_class": rule.get("physics_class"),
                    "product_scale": rule.get("product_scale"),
                    "fragility_level": rule.get("fragility_level"),
                    "material_behavior": rule.get("material_behavior"),
                    "surface_behavior": rule.get("surface_behavior"),
                },
                compatibility_tags=[f"physics_family:{family}"],
                source_status="REPO_VERIFIED",
                source_file="agent/services/product_physics.py",
                source_path=f"PHYSICS_FAMILY_RULES.{family}",
                warnings=["PRODUCT_PHYSICS_RULE_SURFACE_NOT_CANONICAL_REGISTRY_TABLE"],
                provenance=_base_provenance(),
                is_selectable=True,
                is_canonical=False,
                verified_level="REPO_RULE_SURFACE",
            )
        )
    return AssetOptionsResponse(
        asset_type="PRODUCT_PHYSICS",
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="REPO_VERIFIED",
    )


def _load_product_handling_options() -> AssetOptionsResponse:
    options = []
    for family, rule in sorted(PHYSICS_FAMILY_RULES.items()):
        options.append(
            AssetOption(
                asset_id=f"product-handling:{family}",
                asset_type="PRODUCT_HANDLING",
                label=_titleize(family),
                description=rule.get("handling_notes") or "Product handling rule surface.",
                metadata={
                    "recommended_grip": rule.get("recommended_grip"),
                    "camera_handling_notes": rule.get("camera_handling_notes"),
                    "unsafe_handling_rules": rule.get("unsafe_handling_rules") or [],
                },
                compatibility_tags=[f"physics_family:{family}"],
                source_status="REPO_VERIFIED",
                source_file="agent/services/product_physics.py",
                source_path=f"PHYSICS_FAMILY_RULES.{family}",
                warnings=["PRODUCT_HANDLING_RULE_SURFACE_NOT_CANONICAL_REGISTRY_TABLE"],
                provenance=_base_provenance(),
                is_selectable=True,
                is_canonical=False,
                verified_level="REPO_RULE_SURFACE",
            )
        )
    return AssetOptionsResponse(
        asset_type="PRODUCT_HANDLING",
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="REPO_VERIFIED",
    )


async def _load_product_reference_options() -> AssetOptionsResponse:
    rows = await _load_product_rows()
    options = [
        AssetOption(
            asset_id=f"product:{row['id']}",
            asset_type="PRODUCT_REFERENCE",
            label=row.get("product_display_name") or row.get("product_short_name") or row.get("raw_product_title") or row["id"],
            description=row.get("raw_product_title") or "Product row from repo-local database.",
            metadata={
                "product_id": row.get("id"),
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "type": row.get("type"),
                "product_type": row.get("product_type"),
                "claim_risk_level": row.get("claim_risk_level"),
                "scene_context": row.get("scene_context"),
                "camera_style": row.get("camera_style"),
                "camera_behavior": row.get("camera_behavior"),
            },
            compatibility_tags=[
                tag
                for tag in [
                    f"category:{str(row.get('category') or '').lower()}".rstrip(":"),
                    f"type:{str(row.get('type') or '').lower()}".rstrip(":"),
                ]
                if ":" in tag and not tag.endswith(":")
            ],
            source_status="DERIVED_FROM_PRODUCT_DATA",
            source_file="agent/db/schema.py",
            source_path="sqlite:product",
            warnings=["PRODUCT_REFERENCE_IS_DERIVED_NOT_CANONICAL_REGISTRY_TRUTH"],
            provenance=_base_provenance(),
            is_selectable=True,
            is_canonical=False,
            verified_level="DERIVED_NOT_CANONICAL",
        )
        for row in rows
    ]
    if not options:
        return _empty_response(
            "PRODUCT_REFERENCE",
            "EMPTY_NOT_VERIFIED",
            "NO_REPO_PRODUCT_ROWS_FOUND",
            "No product rows were found in the repo-local database.",
        )
    return AssetOptionsResponse(
        asset_type="PRODUCT_REFERENCE",
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="DERIVED_FROM_PRODUCT_DATA",
    )


def _load_style_reference_options() -> AssetOptionsResponse:
    materials = list_builtin_materials()
    options = [
        AssetOption(
            asset_id=f"style:{material['id']}",
            asset_type="STYLE_REFERENCE",
            label=material.get("name") or material["id"],
            description=material.get("style_instruction") or "Built-in material style reference.",
            metadata={
                "negative_prompt": material.get("negative_prompt"),
                "scene_prefix": material.get("scene_prefix"),
                "lighting": material.get("lighting"),
            },
            compatibility_tags=[f"material:{material['id']}"],
            source_status="REPO_VERIFIED",
            source_file="agent/materials.py",
            source_path=f"MATERIALS.{material['id']}",
            warnings=["STYLE_REFERENCE_IS_BUILTIN_MATERIAL_SURFACE"],
            provenance=_base_provenance(),
            is_selectable=True,
            is_canonical=False,
            verified_level="REPO_RULE_SURFACE",
        )
        for material in materials
    ]
    return AssetOptionsResponse(
        asset_type="STYLE_REFERENCE",
        options=options,
        warnings=[],
        provenance=_base_provenance(),
        source_status="REPO_VERIFIED",
    )


def _load_static_input_slot_options(asset_type: str) -> AssetOptionsResponse:
    raw_options = STATIC_INPUT_SLOT_OPTIONS.get(asset_type, [])
    options = [_input_slot_option(asset_type, asset_id, label, description) for asset_id, label, description in raw_options]
    if not options:
        return _empty_response(
            asset_type,
            "INPUT_SLOT_ONLY",
            "INPUT_SLOT_ONLY_NO_SOURCE_CONTROLLED_REGISTRY_DATASET",
            "Repo proves the input slot exists but not a source-controlled registry dataset.",
        )
    return AssetOptionsResponse(
        asset_type=asset_type,
        options=options,
        warnings=["INPUT_SLOT_ONLY_NO_SOURCE_CONTROLLED_REGISTRY_DATASET"],
        provenance=_base_provenance(),
        source_status="INPUT_SLOT_ONLY",
    )


async def list_assets_by_type(asset_type: str) -> AssetOptionsResponse:
    normalized = str(asset_type or "").upper().strip()
    if normalized not in SUPPORTED_ASSET_TYPES:
        return _empty_response(
            normalized or "UNKNOWN",
            "EMPTY_NOT_VERIFIED",
            "UNSUPPORTED_ASSET_TYPE",
            "Unsupported asset type.",
        )

    if normalized == "CHARACTER":
        return await _load_character_options()
    if normalized == "WARDROBE":
        return _empty_response(
            "WARDROBE",
            "INPUT_SLOT_ONLY",
            "INPUT_SLOT_ONLY_NO_SOURCE_CONTROLLED_REGISTRY_DATASET",
            "Wardrobe is an input slot only. No source-controlled registry dataset is present in repo.",
        )
    if normalized == "HEADWEAR":
        return _empty_response(
            "HEADWEAR",
            "INPUT_SLOT_ONLY",
            "INPUT_SLOT_ONLY_NO_SOURCE_CONTROLLED_REGISTRY_DATASET",
            "Headwear is an input slot only. No source-controlled registry dataset is present in repo.",
        )
    if normalized == "CAMERA_STYLE":
        return await _load_product_derived_options("CAMERA_STYLE", "camera_style")
    if normalized == "CAMERA_BEHAVIOR":
        return await _load_product_derived_options("CAMERA_BEHAVIOR", "camera_behavior")
    if normalized == "SCENE_CONTEXT":
        return await _load_product_derived_options("SCENE_CONTEXT", "scene_context")
    if normalized == "COPYWRITING_FORMULA":
        return _load_formula_options()
    if normalized == "OVERLAY_TEMPLATE":
        return await _load_product_derived_options("OVERLAY_TEMPLATE", "section_9_overlay_hint", "OVERLAY_HINT_IS_PRODUCT_DERIVED_NOT_TEMPLATE_REGISTRY")
    if normalized == "PRODUCT_HANDLING":
        return _load_product_handling_options()
    if normalized == "PRODUCT_PHYSICS":
        return _load_product_physics_options()
    if normalized == "PRODUCT_REFERENCE":
        return await _load_product_reference_options()
    if normalized == "STYLE_REFERENCE":
        return _load_style_reference_options()
    if normalized in STATIC_INPUT_SLOT_OPTIONS:
        return _load_static_input_slot_options(normalized)
    return _empty_response(
        normalized,
        "EMPTY_NOT_VERIFIED",
        "NO_REPO_ASSET_SOURCE_FOUND",
        "No repo-proven asset source was found.",
    )


async def get_asset_catalog() -> AssetCatalogResponse:
    entries: list[AssetCatalogEntry] = []
    for asset_type in SUPPORTED_ASSET_TYPES:
        listing = await list_assets_by_type(asset_type)
        entries.append(
            AssetCatalogEntry(
                asset_type=asset_type,
                display_name=_titleize(asset_type),
                description=ASSET_TYPE_DESCRIPTIONS[asset_type],
                item_count=len(listing.options),
                source_status=listing.source_status,
                warnings=listing.warnings,
                provenance=listing.provenance,
                empty_reason=listing.empty_reason,
            )
        )
    return AssetCatalogResponse(catalog=entries, warnings=[], provenance=_base_provenance())


async def get_asset_by_id(asset_id: str) -> AssetDetailResponse | None:
    for asset_type in SUPPORTED_ASSET_TYPES:
        listing = await list_assets_by_type(asset_type)
        for option in listing.options:
            if option.asset_id == asset_id:
                return AssetDetailResponse(asset=option, warnings=listing.warnings, provenance=listing.provenance)
    return None


def _normalize_selection_request(
    request_input: dict[str, Any] | AssetSelectionRequest,
) -> tuple[AssetSelectionRequest, dict[str, Any]]:
    if isinstance(request_input, AssetSelectionRequest):
        return request_input, request_input.model_dump()
    parsed = AssetSelectionRequest.model_validate(request_input)
    return parsed, dict(request_input)


def _normalize_compatibility_request(
    request_input: dict[str, Any] | AssetCompatibilityRequest,
) -> tuple[AssetCompatibilityRequest, dict[str, Any]]:
    if isinstance(request_input, AssetCompatibilityRequest):
        return request_input, request_input.model_dump()
    parsed = AssetCompatibilityRequest.model_validate(request_input)
    return parsed, dict(request_input)


async def resolve_asset_selection(
    request_input: dict[str, Any] | AssetSelectionRequest,
) -> AssetSelectionResponse:
    request, raw_request = _normalize_selection_request(request_input)
    warnings: list[str] = []
    errors: list[str] = []
    resolved_assets: list[AssetOption] = []

    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_8")
    if _has_truthy_flag(raw_request, FORBIDDEN_UNVERIFIED_PROOF_KEYS):
        _unique_append(errors, "UNVERIFIED_ASSET_TRUTH_CANNOT_BE_MARKED_VERIFIED")
    if errors:
        return AssetSelectionResponse(
            selection_status="FAIL",
            resolved_assets=[],
            warnings=warnings,
            errors=errors,
            provenance=_base_provenance(),
        )

    for asset_type, selected in request.selected_assets.items():
        values = selected if isinstance(selected, list) else [selected]
        listing = await list_assets_by_type(asset_type)
        index = {option.asset_id: option for option in listing.options}
        for value in values:
            if not value:
                continue
            option = index.get(str(value))
            if option is None:
                _unique_append(warnings, f"ASSET_SELECTION_NOT_REPO_RESOLVABLE:{asset_type}:{value}")
                continue
            resolved_assets.append(option)
            if option.source_status != "REPO_VERIFIED":
                _unique_append(warnings, f"ASSET_SELECTION_NOT_REPO_VERIFIED:{option.asset_id}")

    _unique_append(warnings, "FULL_TUPLE_LEGALITY_NOT_PROVEN")
    _unique_append(warnings, "CANONICAL_VS_PREVIEW_ISOLATION_NOT_PROVEN")
    status = "PASS"
    if warnings:
        status = "WARN"
    return AssetSelectionResponse(
        selection_status=status,
        resolved_assets=resolved_assets,
        warnings=warnings,
        errors=errors,
        provenance=_base_provenance(),
    )


async def compatibility_check(
    request_input: dict[str, Any] | AssetCompatibilityRequest,
) -> AssetCompatibilityResponse:
    request, raw_request = _normalize_compatibility_request(request_input)
    warnings: list[str] = []
    errors: list[str] = []

    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_8")
    if _has_truthy_flag(raw_request, FORBIDDEN_UNVERIFIED_PROOF_KEYS):
        _unique_append(errors, "UNVERIFIED_ASSET_TRUTH_CANNOT_BE_MARKED_VERIFIED")
    if errors:
        return AssetCompatibilityResponse(
            compatibility_status="FAIL",
            warnings=warnings,
            errors=errors,
            provenance=_base_provenance(),
        )

    resolution = await resolve_asset_selection({"selected_assets": request.selected_assets})
    for warning in resolution.warnings:
        _unique_append(warnings, warning)
    _unique_append(warnings, "FULL_TUPLE_LEGALITY_NOT_PROVEN")
    _unique_append(warnings, "CANONICAL_VS_PREVIEW_ISOLATION_NOT_PROVEN")
    return AssetCompatibilityResponse(
        compatibility_status="NOT_VERIFIED",
        warnings=warnings,
        errors=[],
        provenance=_base_provenance(),
    )
