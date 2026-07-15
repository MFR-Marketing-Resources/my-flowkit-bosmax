"""Creative Intelligence — Round 2: product/category -> recommended scene /
image-prompt templates.

READ-FIRST, non-generative, reference/preview only. This service:
  * loads a committed, reconciled Scene / Image Prompt library
    (``creative_scene_prompt_library.json``) ingested read-only from the workbook
    ``IMAGE_PROMPTS`` + ``IMG_CONFIG`` sheets;
  * REUSES the Round 1 reconciliation engine
    (``creative_avatar_recommendation_service.resolve_cluster``) — there is ONE
    category -> canonical-cluster resolver, not a parallel one;
  * returns recommended scene/action/placement/image-prompt templates for a
    product/category, keyed on the canonical cluster;
  * optionally persists the same library into the ``creative_scene_prompt`` config
    table (idempotent, dry-run default) purely for auditability.

Safety: it never writes Product Truth, Product Intelligence snapshots/drafts, Copy
Sets, Copy Registry, Copy Intelligence, DeepSeek, the canonical compiler, or any
generation/asset table. The ``[AVATAR]`` and ``[PRODUCT]`` placeholders are always
returned UNRESOLVED — Round 2 never substitutes real avatar/product text, and the
raw templates are never sent to generation.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.services import creative_avatar_recommendation_service as _avatar

_AUTHORITY = Path(__file__).resolve().parents[1] / "authority"
_LIBRARY_FILE = _AUTHORITY / "creative_scene_prompt_library.json"

LIBRARY_SOURCE = "CREATIVE_SCENE_PROMPT_v1"

# Columns persisted to the creative_scene_prompt config table by the seed.
_SEED_FIELDS = (
    "cluster",
    "source_category",
    "cluster_source",
    "main_action",
    "setting",
    "full_prompt_template",
    "base_prompt",
    "combined_prompt_suggestion",
    "negative_prompt",
    "variant",
    "notes",
)


@lru_cache(maxsize=1)
def _library() -> dict[str, Any]:
    return json.loads(_LIBRARY_FILE.read_text(encoding="utf-8"))


def global_config() -> dict[str, Any]:
    """Global style suffix, negative prompt, and common actions (IMG_CONFIG)."""
    return dict(_library().get("global_config", {}))


def category_reconciliation() -> list[dict[str, Any]]:
    """The explicit source-category -> canonical-cluster reconciliation table."""
    return list(_library().get("category_reconciliation", []))


def clusters_without_templates() -> list[str]:
    return list(_library().get("clusters_without_templates", []))


def quarantine() -> list[dict[str, Any]]:
    return list(_library().get("quarantine", []))


def library_templates() -> list[dict[str, Any]]:
    return list(_library().get("templates", []))


def templates_for_cluster(cluster: str, limit: int = 50) -> list[dict[str, Any]]:
    """Read-only: scene/image templates whose canonical cluster matches ``cluster``.

    Placeholders ``[AVATAR]``/``[PRODUCT]`` are returned verbatim (unresolved).
    """
    out = [t for t in library_templates() if t.get("cluster") == cluster]
    return out[: max(0, limit)]


async def seed_scene_prompts(*, dry_run: bool = True) -> dict[str, Any]:
    """Persist the reconciled library into the ``creative_scene_prompt`` config
    table. Idempotent (upsert keyed on ``template_id``). ``dry_run`` (default true)
    writes nothing. Only touches the config table — no Product Truth / Copy /
    generation effect. Templates are stored with placeholders unresolved.
    """
    from agent.db import crud

    templates = library_templates()
    written = 0
    for tpl in templates:
        if dry_run:
            continue
        payload = {k: tpl.get(k) for k in _SEED_FIELDS}
        payload["template_id"] = tpl.get("template_id")
        payload["provenance"] = f"{tpl.get('source_category')} row={tpl.get('source_row')} [src:{LIBRARY_SOURCE}]"
        await crud.upsert_creative_scene_prompt(**payload)
        written += 1

    return {
        "dry_run": dry_run,
        "source": LIBRARY_SOURCE,
        "library_version": _library().get("library_version"),
        "templates_available": len(templates),
        "written": 0 if dry_run else written,
        "quarantine": quarantine(),
    }


async def recommend_scene_prompts_for_category(
    category: str | None, limit: int = 50
) -> dict[str, Any]:
    """Read-only scene/image-prompt recommendation for a raw category.

    Resolves category -> canonical cluster via the Round 1 resolver, then returns
    that cluster's templates from the committed library. Never mutates; never
    resolves ``[AVATAR]``/``[PRODUCT]``; never calls generation.
    """
    resolved = _avatar.resolve_cluster(category)
    cluster = resolved["cluster"]
    templates = templates_for_cluster(cluster, limit=limit)
    return {
        "category": category,
        "cluster": cluster,
        "cluster_source": resolved["cluster_source"],
        "template_count": len(templates),
        "templates": templates,
        "global_config": global_config(),
        "cluster_has_templates": bool(templates),
    }


async def recommend_scene_prompts_for_product(
    product_id: str, limit: int = 50
) -> dict[str, Any]:
    """Read-only scene/image-prompt recommendation for a product (manual or
    imported). Raises ``ValueError('PRODUCT_NOT_FOUND')`` if unknown."""
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    result = await recommend_scene_prompts_for_category(product.get("category"), limit=limit)
    result["product_id"] = product_id
    result["product_name"] = (
        product.get("product_display_name") or product.get("raw_product_title")
    )
    return result
