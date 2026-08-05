"""Read-only Product Scene Suitability Registry — Round 1.

Maps a registered product (or raw category) through the canonical creative
cluster resolver and returns the matching workbook-derived scene templates as
preview-only suitability recommendations.  This layer is deliberately separate
from the background-only ``SCENE_CONTEXT_POOL.csv`` registry: it never promotes
templates, resolves placeholders, writes a database row, or invokes generation.
"""
from __future__ import annotations

from typing import Any

from agent.services import creative_avatar_recommendation_service as _avatar
from agent.services import creative_scene_prompt_service as _scene_prompts


SUITABILITY_SOURCE = "PRODUCT_SCENE_SUITABILITY_R1"


def _suitability_reason(template: dict[str, Any], cluster: str) -> str:
    """Return stable, explainable provenance without interpreting the prompt."""
    return (
        f"Canonical cluster '{cluster}' matches template '{template.get('template_id')}' "
        f"from source category '{template.get('source_category')}' "
        f"via library mapping '{template.get('cluster_source')}'."
    )


def _recommendation(template: dict[str, Any], cluster: str) -> dict[str, Any]:
    """Project only preview metadata plus the unresolved source template."""
    return {
        "template_id": template.get("template_id"),
        "source_category": template.get("source_category"),
        "variant": template.get("variant"),
        "main_action": template.get("main_action"),
        "setting": template.get("setting"),
        "notes": template.get("notes"),
        "status": template.get("status"),
        "full_prompt_template": template.get("full_prompt_template"),
        "suitability_reason": _suitability_reason(template, cluster),
    }


async def recommend_scene_suitability_for_category(
    category: str | None, *, limit: int = 50,
    _resolved: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Return read-only scene suitability recommendations for ``category``.

    The canonical resolver remains fail-closed: blank or unknown categories
    produce no recommendations and require review rather than silently adopting
    a visual cluster.  ``[AVATAR]`` and ``[PRODUCT]`` stay verbatim in every
    returned template.
    """
    # _resolved: product-first dual-source bypass passed by the _for_product wrapper.
    resolved = _resolved or _avatar.resolve_cluster(category)
    cluster = resolved["cluster"]
    if cluster is None:
        return {
            "category": category,
            "cluster": None,
            "cluster_source": resolved["cluster_source"],
            "review_required": True,
            "template_count": 0,
            "recommendations": [],
            "source": SUITABILITY_SOURCE,
        }

    templates = _scene_prompts.templates_for_cluster(cluster, limit=limit)
    return {
        "category": category,
        "cluster": cluster,
        "cluster_source": resolved["cluster_source"],
        "review_required": False,
        "template_count": len(templates),
        "recommendations": [_recommendation(template, cluster) for template in templates],
        "source": SUITABILITY_SOURCE,
    }


async def recommend_scene_suitability_for_product(
    product_id: str, *, limit: int = 50
) -> dict[str, Any]:
    """Return read-only scene suitability recommendations for a stored product.

    Raises ``ValueError('PRODUCT_NOT_FOUND')`` when the product does not exist.
    """
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    resolved = await _avatar.resolve_product_cluster(product_id, product.get("category"))
    result = await recommend_scene_suitability_for_category(
        product.get("category"), limit=limit, _resolved=resolved
    )
    result["product_id"] = product_id
    result["product_name"] = (
        product.get("product_display_name") or product.get("raw_product_title")
    )
    return result
