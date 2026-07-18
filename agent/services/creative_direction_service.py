"""Round 1 resolver for governed, non-runtime Creative Direction data."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent.models.creative_direction import CreativeDirection, CreativeMode
from agent.services import avatar_registry
from agent.services import creative_avatar_recommendation_service as creative_avatar
from agent.services import creative_scene_prompt_service as creative_scene
from agent.services.img_category_adapt_service import resolve_category_adapt
from agent.services.product_truth_service import ProductTruthService

_AUTHORITY_PATH = Path(__file__).resolve().parent.parent / "authority" / "CREATIVE_DIRECTION_MODES.yaml"


class CreativeDirectionError(ValueError):
    """Stable fail-closed resolver errors for future callers."""


@lru_cache(maxsize=1)
def _load_authority() -> dict[str, Any]:
    try:
        data = yaml.safe_load(_AUTHORITY_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CreativeDirectionError("CREATIVE_DIRECTION_AUTHORITY_INVALID") from exc
    if not data.get("schema_version") or not data.get("modes"):
        raise CreativeDirectionError("CREATIVE_DIRECTION_AUTHORITY_INVALID")
    policy = data.get("representation_policy") or {}
    if not policy.get("schema_version") or not policy.get("rules"):
        raise CreativeDirectionError("CREATIVE_DIRECTION_AUTHORITY_INVALID")
    return data


def resolve_creative_direction(
    mode: CreativeMode | str,
    *,
    product: dict[str, Any] | None = None,
) -> CreativeDirection:
    """Resolve one supported mode against existing category adaptation context.

    The resolver performs read-only reuse of existing category, scene, avatar,
    and Product Truth authorities. It never selects an avatar, substitutes a
    scene template, or writes a Creative Setup record.
    """
    try:
        resolved_mode = CreativeMode(str(mode))
    except ValueError as exc:
        raise CreativeDirectionError("UNSUPPORTED_CREATIVE_MODE") from exc

    data = _load_authority()
    entry = (data["modes"] or {}).get(resolved_mode.value)
    if not isinstance(entry, dict):
        raise CreativeDirectionError("CREATIVE_DIRECTION_AUTHORITY_INVALID")
    category = resolve_category_adapt(product)
    cluster = creative_avatar.resolve_cluster((product or {}).get("category"))
    scene_templates = creative_scene.templates_for_cluster(cluster["cluster"], limit=3)
    truth = ProductTruthService.build_computed_profile(product or {})
    try:
        return CreativeDirection(
            authority_version=str(data["schema_version"]),
            representation_policy_version=str(data["representation_policy"]["schema_version"]),
            mode=resolved_mode,
            label=str(entry["label"]),
            composition_direction=str(entry["composition_direction"]),
            product_dominance=str(entry["product_dominance"]),
            lighting=str(entry["lighting"]),
            camera_framing=str(entry["camera_framing"]),
            props=str(entry["props"]),
            environment=str(entry["environment"]),
            human_presence_policy=str(entry["human_presence_policy"]),
            product_interaction=str(entry["product_interaction"]),
            negative_rules=list(entry["negative_rules"]),
            malaysian_localisation_cues=list(entry["malaysian_localisation_cues"]),
            category_context={k: str(v) for k, v in category.items()},
            canonical_cluster=str(cluster["cluster"]),
            cluster_source=str(cluster["cluster_source"]),
            scene_template_ids=[str(row.get("template_id")) for row in scene_templates if row.get("template_id")],
            avatar_vocabulary_source="avatar_registry_vocab.json" if avatar_registry.load_vocab() else "",
            product_truth_claim_gate=str(truth.final_output_preview.claim_gate),
            authority_sources=[
                "CREATIVE_DIRECTION_MODES.yaml",
                "CATEGORY_SCENE_MODEL_MAP.yaml",
                "creative_category_cluster_map.json",
                "creative_scene_prompt_library.json",
                "avatar_registry_vocab.json",
                "Product Truth",
            ],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CreativeDirectionError("CREATIVE_DIRECTION_AUTHORITY_INVALID") from exc


def select_creative_direction_directives(
    direction: CreativeDirection,
    *,
    operator_human_presence: str = "",
    identity_reference_locked: bool = False,
    composition_constraint_locked: bool = False,
) -> list[tuple[str, str]]:
    """Return only mode directives that do not yield to a higher authority.

    This is an application policy, not a second resolver: the canonical mode is
    always resolved above.  The caller supplies already-known higher-authority
    locks and this function deterministically removes the conflicting mode
    fields before a final prompt is assembled.
    """
    directives = [
        ("Composition", direction.composition_direction),
        ("Lighting", direction.lighting),
        ("Framing", direction.camera_framing),
        ("Props", direction.props),
        ("Environment", direction.environment),
        (
            "Human presence",
            f"{direction.human_presence_policy}; interaction: {direction.product_interaction}",
        ),
    ]
    suppressed: set[str] = set()
    if composition_constraint_locked:
        suppressed.update({"Composition", "Framing"})
    if operator_human_presence.strip() or identity_reference_locked:
        suppressed.add("Human presence")
    return [(label, value) for label, value in directives if label not in suppressed]
