from __future__ import annotations

from typing import Final

from agent.models.product_readiness import (
    ApplicabilityProfileProjection,
    AssetRole,
    IndexedActionApplicability,
)
from agent.services.creative_treatment_service import canonical_sha256
from agent.services.scene_strategy_library import SCENE_STRATEGIES, SceneStrategyEntry


PROFILE_VERSION: Final = "product-readiness-applicability-v1"

_COMPOSITION_TOKENS: Final = frozenset(
    {
        "beauty",
        "beverage",
        "cleanser",
        "cosmetic",
        "deodorant",
        "food",
        "fragrance",
        "herbal",
        "ingredient",
        "makeup",
        "oil",
        "pantry",
        "pet_food",
        "sauce",
        "seasoning",
        "serum",
        "skincare",
        "snack",
        "supplement",
        "wellness",
    }
)
_TOPICAL_TOKENS: Final = frozenset(
    {
        "beauty",
        "cleanser",
        "cosmetic",
        "deodorant",
        "exfoliant",
        "fragrance",
        "hair",
        "makeup",
        "moisturizer",
        "oil",
        "serum",
        "skincare",
        "sunscreen",
        "treatment",
    }
)
_INGESTIBLE_TOKENS: Final = frozenset(
    {
        "beverage",
        "food",
        "pantry",
        "sauce",
        "seasoning",
        "snack",
        "supplement",
    }
)
_ELECTRICAL_TOKENS: Final = frozenset(
    {
        "audio",
        "device",
        "electrical",
        "electronics",
        "fan",
        "lighting",
        "vacuum",
    }
)
_CHEMICAL_TOKENS: Final = frozenset(
    {
        "cleaner",
        "cleaning",
        "detergent",
        "pest_control",
        "softener",
    }
)
_MECHANICAL_TOKENS: Final = frozenset(
    {
        "cookware",
        "equipment",
        "fishing",
        "fitness",
        "tool",
    }
)
_REGULATED_TOKENS: Final = frozenset(
    {
        "feminine",
        "health",
        "supplement",
        "wellness",
    }
)
_MATERIAL_TOKENS: Final = frozenset(
    {
        "accessory",
        "apparel",
        "automotive",
        "book",
        "cookware",
        "craft",
        "curtain",
        "decor",
        "device",
        "electronics",
        "equipment",
        "fabric",
        "fashion",
        "footwear",
        "lighting",
        "linen",
        "rug",
        "stationery",
        "storage",
        "textile",
        "tool",
    }
)

_USE_ACTION_TOKENS: Final = (
    "apply ",
    "assemble",
    "attach",
    "clean ",
    "close ",
    "consume",
    "dispense",
    "install",
    "mix ",
    "operate",
    "place or wear",
    "press ",
    "rinse",
    "serve",
    "sprinkle",
    "stir ",
    "use ",
    "wear ",
    "wipe ",
)
_COMPOSITION_ACTION_TOKENS: Final = (
    "dispense",
    "dropper",
    "formula",
    "ingredient",
    "measure",
    "mix ",
    "pour",
    "serving",
    "sprinkle",
    "stir ",
    "texture",
)
_MATERIAL_ACTION_TOKENS: Final = (
    "component",
    "fabric",
    "fastening",
    "finish",
    "material",
    "port",
    "seam",
    "texture",
)
_INTERACTION_ACTION_TOKENS: Final = (
    "apply ",
    "assemble",
    "attach",
    "dispense",
    "fit ",
    "hold ",
    "install",
    "measure",
    "operate",
    "place or wear",
    "press ",
    "sprinkle",
    "stir ",
    "wear ",
    "wipe ",
)
_SAFE_USE_ACTION_TOKENS: Final = (
    "correct ",
    "directions",
    "intact seal",
    "label-directed",
    "nozzle",
    "power or control",
    "serving",
    "suitable surface",
)

_ACTOR_POLICY_BY_FORMAT: Final = {
    "UGC": "PRESENTER_REQUIRED",
    "PGC": "PRESENTER_FORBIDDEN",
    "CINEMATIC": "PRESENTER_OPTIONAL",
}
_ASSET_ROLES_BY_MODE: Final[dict[str, tuple[AssetRole, ...]]] = {
    "T2V": (),
    "HYBRID": ("PRODUCT_REFERENCE",),
    "F2V": ("COMPOSITE_FRAME_REFERENCE",),
    "I2V": ("PRODUCT_REFERENCE", "SCENE_CONTEXT_REFERENCE"),
}


def _authority_tokens(entry: SceneStrategyEntry) -> set[str]:
    text = " ".join(
        (
            entry["product_family"],
            entry["product_type"],
            *entry["sensitive_handling_rules"],
        )
    )
    normalized = (
        text.casefold()
        .replace("-", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )
    return {token for token in normalized.split("_") if token}


def _has_authority_token(entry: SceneStrategyEntry, candidates: frozenset[str]) -> bool:
    normalized = " ".join(
        (
            entry["product_family"],
            entry["product_type"],
            *entry["sensitive_handling_rules"],
        )
    ).casefold()
    tokens = _authority_tokens(entry)
    return any(candidate in tokens or candidate in normalized for candidate in candidates)


def _risk_flags(entry: SceneStrategyEntry) -> list[str]:
    flags: set[str] = set()
    if _has_authority_token(entry, _COMPOSITION_TOKENS):
        flags.add("COMPOSITION_SENSITIVE")
    if _has_authority_token(entry, _TOPICAL_TOKENS):
        flags.add("TOPICAL")
    if _has_authority_token(entry, _INGESTIBLE_TOKENS):
        flags.add("INGESTIBLE")
    if _has_authority_token(entry, _ELECTRICAL_TOKENS):
        flags.add("ELECTRICAL")
    if _has_authority_token(entry, _CHEMICAL_TOKENS):
        flags.add("CHEMICAL")
    if _has_authority_token(entry, _MECHANICAL_TOKENS):
        flags.add("MECHANICAL_HAZARD")
    if _has_authority_token(entry, _REGULATED_TOKENS):
        flags.add("REGULATED")
    if "baby" in _authority_tokens(entry):
        flags.add("CHILD")
    if _has_authority_token(entry, _MATERIAL_TOKENS):
        flags.add("MATERIAL_SENSITIVE")
    if flags.intersection(
        {
            "CHILD",
            "CHEMICAL",
            "ELECTRICAL",
            "INGESTIBLE",
            "MECHANICAL_HAZARD",
            "REGULATED",
            "TOPICAL",
        }
    ):
        flags.add("HIGH_RISK")
    return sorted(flags)


def classify_indexed_action(action_text: str) -> list[str]:
    text = action_text.casefold()
    classes: set[str] = set()
    if any(token in text for token in _USE_ACTION_TOKENS):
        classes.add("USE_DEMONSTRATION")
    if any(token in text for token in _COMPOSITION_ACTION_TOKENS):
        classes.add("COMPOSITION_DEMONSTRATION")
    if any(token in text for token in _MATERIAL_ACTION_TOKENS):
        classes.add("MATERIAL_DEMONSTRATION")
    if any(token in text for token in _INTERACTION_ACTION_TOKENS):
        classes.add("PRODUCT_INTERACTION")
    if any(token in text for token in _SAFE_USE_ACTION_TOKENS):
        classes.add("SAFE_USE_MATERIAL")
    if not classes:
        classes.add("STATIC_PRODUCT_HERO")
    return sorted(classes)


def _profile_payload(
    *,
    scene_strategy_id: str,
    entry: SceneStrategyEntry | None,
) -> dict[str, object]:
    supported = (
        entry is not None
        and scene_strategy_id != "GENERIC_FALLBACK"
        and entry["product_family"] != "GENERIC_UNCLASSIFIED"
    )
    indexed_actions = (
        [
            {
                "allowed_action_index": index,
                "action_text": action,
                "action_classes": classify_indexed_action(action),
            }
            for index, action in enumerate(entry["allowed_actions"])
        ]
        if entry is not None
        else []
    )
    return {
        "profile_version": PROFILE_VERSION,
        "scene_strategy_id": scene_strategy_id,
        "product_family": entry["product_family"] if entry else "UNKNOWN",
        "product_type": entry["product_type"] if entry else "UNKNOWN",
        "supported": supported,
        "unsupported_code": None if supported else "APPLICABILITY_PROFILE_UNSUPPORTED",
        "risk_flags": _risk_flags(entry) if entry else [],
        "indexed_actions": indexed_actions,
        "actor_policy_by_format": dict(_ACTOR_POLICY_BY_FORMAT),
        "required_asset_roles_by_mode": {
            mode: list(roles) for mode, roles in _ASSET_ROLES_BY_MODE.items()
        },
    }


def resolve_applicability_profile(
    scene_strategy_id: str | None,
) -> ApplicabilityProfileProjection:
    normalized_id = str(scene_strategy_id or "UNKNOWN").strip().upper() or "UNKNOWN"
    entry = SCENE_STRATEGIES.get(normalized_id)
    payload = _profile_payload(scene_strategy_id=normalized_id, entry=entry)
    return ApplicabilityProfileProjection(
        **payload,
        profile_sha256=canonical_sha256(payload),
    )


def list_applicability_profiles() -> list[ApplicabilityProfileProjection]:
    profile_ids = sorted({*SCENE_STRATEGIES, "UNKNOWN"})
    return [resolve_applicability_profile(profile_id) for profile_id in profile_ids]


def select_indexed_action(
    profile: ApplicabilityProfileProjection,
    allowed_action_index: int,
) -> IndexedActionApplicability | None:
    for action in profile.indexed_actions:
        if action.allowed_action_index == allowed_action_index:
            return action
    return None


def requirement_policies(
    *,
    profile: ApplicabilityProfileProjection,
    action: IndexedActionApplicability,
    creative_format: str,
    logical_mode: str,
) -> list[dict[str, object]]:
    risk = set(profile.risk_flags)
    action_classes = set(action.action_classes)
    composition_required = bool(
        "COMPOSITION_SENSITIVE" in risk
        or "COMPOSITION_DEMONSTRATION" in action_classes
    )
    materials_required = bool(
        "MATERIAL_SENSITIVE" in risk
        and action_classes.intersection(
            {
                "MATERIAL_DEMONSTRATION",
                "PRODUCT_INTERACTION",
                "SAFE_USE_MATERIAL",
                "USE_DEMONSTRATION",
            }
        )
    )
    usage_required = "USE_DEMONSTRATION" in action_classes
    warnings_required = bool(
        "HIGH_RISK" in risk or "SAFE_USE_MATERIAL" in action_classes
    )
    scale_required = bool(
        action_classes.intersection(
            {
                "MATERIAL_DEMONSTRATION",
                "PRODUCT_INTERACTION",
                "USE_DEMONSTRATION",
            }
        )
    )
    visual_required = logical_mode != "T2V"
    target_criticality = "BOTH" if creative_format == "UGC" else "COPY_CRITICAL"

    return [
        {
            "requirement_code": "PRODUCT_IDENTITY",
            "criticality": "BOTH",
            "applicable": True,
            "rule_code": "IDENTITY_ALWAYS_APPLICABLE",
            "source_fields": ["product_identity"],
        },
        {
            "requirement_code": "BENEFITS_AND_USPS",
            "criticality": "BOTH",
            "applicable": True,
            "rule_code": "COMMERCIAL_TRUTH_ALWAYS_APPLICABLE",
            "source_fields": ["benefits_json", "usp_json", "product_description"],
        },
        {
            "requirement_code": "TARGET_CUSTOMER",
            "criticality": target_criticality,
            "applicable": True,
            "rule_code": (
                "UGC_ACTOR_AND_COPY_TARGET_REQUIRED"
                if creative_format == "UGC"
                else "COPY_TARGET_REQUIRED"
            ),
            "source_fields": ["target_customer_text"],
        },
        {
            "requirement_code": "ALLOWED_CLAIMS",
            "criticality": "BOTH",
            "applicable": True,
            "rule_code": "ALLOWED_CLAIMS_ALWAYS_EVALUATED",
            "source_fields": ["allowed_claims_json"],
        },
        {
            "requirement_code": "INGREDIENTS_OR_COMPOSITION",
            "criticality": "TREATMENT_CRITICAL",
            "applicable": composition_required,
            "rule_code": (
                "COMPOSITION_SENSITIVE_OR_ACTION_DEPENDENT"
                if composition_required
                else "COMPOSITION_STRUCTURALLY_IRRELEVANT"
            ),
            "source_fields": ["ingredients_text"],
        },
        {
            "requirement_code": "MATERIALS_OR_COMPONENTS",
            "criticality": "TREATMENT_CRITICAL",
            "applicable": materials_required,
            "rule_code": (
                "NON_CONSUMABLE_ACTION_DEPENDS_ON_MATERIAL_OR_COMPONENT"
                if materials_required
                else "MATERIAL_DETAIL_NOT_REQUIRED_BY_CONTEXT"
            ),
            "source_fields": [
                "package_notes",
                "product_form_factor",
                "packaging_description",
            ],
        },
        {
            "requirement_code": "USAGE_OR_INSTRUCTIONS",
            "criticality": "BOTH",
            "applicable": usage_required,
            "rule_code": (
                "INDEXED_ACTION_DEMONSTRATES_USE"
                if usage_required
                else "STATIC_ACTION_DOES_NOT_REQUIRE_USAGE"
            ),
            "source_fields": ["usage_text"],
        },
        {
            "requirement_code": "WARNINGS_OR_LIMITATIONS",
            "criticality": "TREATMENT_CRITICAL",
            "applicable": warnings_required,
            "rule_code": (
                "RISK_OR_SAFE_USE_CONTEXT_REQUIRES_WARNINGS"
                if warnings_required
                else "WARNINGS_NOT_MATERIAL_TO_CONTEXT"
            ),
            "source_fields": ["warnings_text"],
        },
        {
            "requirement_code": "PHYSICAL_SCALE_AND_STATE",
            "criticality": "TREATMENT_CRITICAL",
            "applicable": scale_required,
            "rule_code": (
                "PRODUCT_INTERACTION_REQUIRES_SCALE_STATE"
                if scale_required
                else "NO_SCALE_DEPENDENT_INTERACTION"
            ),
            "source_fields": [
                "size_or_volume",
                "product_form_factor",
                "packaging_description",
            ],
        },
        {
            "requirement_code": "VISUAL_ASSET_IDENTITY",
            "criticality": "TREATMENT_CRITICAL",
            "applicable": visual_required,
            "rule_code": (
                "REFERENCE_MODE_REQUIRES_VISUAL_IDENTITY"
                if visual_required
                else "T2V_HAS_NO_REFERENCE_ASSET_INPUT"
            ),
            "source_fields": [],
        },
    ]
