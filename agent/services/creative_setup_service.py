"""Creative Intelligence — Round 4: unified creative resolver + saved selection.

READ-FIRST for the resolver; review-gated writes ONLY to the
``creative_product_selection`` config table. This service:
  * composes the Round 1 (avatar), Round 2 (scene/image prompt) and Round 3
    (camera/video preset) recommendations for a product into one payload, plus
    the product's saved selection (if any) and its preview package;
  * lets the user SAVE/UPDATE one creative selection per product (chosen avatar +
    scene template + camera preset), validated against the live pools/libraries,
    starting review-gated at status ``DRAFT``;
  * lets a reviewer APPROVE/REJECT a DRAFT selection.

Safety: it NEVER writes product rows or product camera columns, Product Truth,
Product Intelligence snapshots/drafts, Copy Sets, Copy Registry, Copy Intelligence,
DeepSeek, the canonical compiler, or any generation/asset table. The saved
selection is a planning artifact only — it never triggers or feeds generation, and
scene-template ``[AVATAR]``/``[PRODUCT]`` placeholders stay unresolved in the
preview.
"""
from __future__ import annotations

import json
from typing import Any

from agent.services import avatar_registry
from agent.services import creative_avatar_recommendation_service as _avatar
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera

PROVENANCE_SOURCE = "CREATIVE_SETUP_v1"
_VALID_STATUS = ("DRAFT", "APPROVED", "REJECTED")


def _avatar_index() -> dict[str, dict[str, Any]]:
    return {a["avatar_code"]: a for a in avatar_registry.list_pool()}


def _scene_index() -> dict[str, dict[str, Any]]:
    return {t["template_id"]: t for t in _scene.library_templates()}


def _camera_index() -> dict[str, dict[str, Any]]:
    return {p["preset_code"]: p for p in _camera.named_presets()}


def _build_preview(row: dict[str, Any]) -> dict[str, Any]:
    """Compose the read-only planning preview for a saved selection.

    Scene ``[AVATAR]``/``[PRODUCT]`` placeholders are preserved unresolved.
    """
    avatar = _avatar_index().get(row.get("selected_avatar_code") or "")
    scene = _scene_index().get(row.get("selected_scene_template_id") or "")
    camera = _camera_index().get(row.get("selected_camera_preset_code") or "")
    return {
        "cluster": row.get("cluster"),
        "cluster_source": row.get("cluster_source"),
        "avatar": avatar,
        "scene_template": scene,
        "camera_preset": camera,
        "not_for_generation": True,
        "note": "Planning preview only — not sent to generation. [AVATAR]/[PRODUCT] stay unresolved.",
    }


def _hydrate_selection(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    out = dict(row)
    for jf in ("preview_json", "provenance_json"):
        raw = out.get(jf)
        if isinstance(raw, str) and raw:
            try:
                out[jf.replace("_json", "")] = json.loads(raw)
            except (ValueError, TypeError):
                out[jf.replace("_json", "")] = None
    return out


async def resolve_creative_setup(product_id: str) -> dict[str, Any]:
    """Unified read-only creative setup: recommended avatars + scene templates +
    camera presets for the product, plus the saved selection (if any). Raises
    ``ValueError('PRODUCT_NOT_FOUND')`` for an unknown product. Never mutates."""
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    category = product.get("category")

    avatars = await _avatar.recommend_avatars_for_category(category)
    saved = _hydrate_selection(await crud.get_creative_product_selection(product_id))

    # Fail-closed: an un-categorised / unresolved product is REVIEW_REQUIRED. No
    # avatar/scene/camera plan is offered and nothing may be auto-linked or saved
    # until a real category exists (mirrors the product-cluster audit; never a
    # silent Home & Living fallback).
    if avatars.get("review_required"):
        return {
            "product_id": product_id,
            "product_name": product.get("product_display_name") or product.get("raw_product_title"),
            "category": category,
            "cluster": None,
            "cluster_source": avatars["cluster_source"],
            "review_required": True,
            "recommended_avatars": [],
            "recommended_scene_templates": [],
            "camera_block_recommendations": [],
            "camera_library": {
                "shot_distances": [], "camera_angles": [], "camera_movements": [],
                "ecomm_shot_types": [], "named_presets": [],
            },
            "saved_selection": saved,
        }

    scenes = await _scene.recommend_scene_prompts_for_category(category)
    cameras = await _camera.recommend_camera_presets_for_category(category)

    return {
        "product_id": product_id,
        "product_name": product.get("product_display_name") or product.get("raw_product_title"),
        "category": category,
        "cluster": avatars["cluster"],
        "cluster_source": avatars["cluster_source"],
        "review_required": False,
        "recommended_avatars": avatars["avatars"],
        "recommended_scene_templates": scenes["templates"],
        "camera_block_recommendations": cameras["block_recommendations"],
        "camera_library": cameras["library"],
        "saved_selection": saved,
    }


async def save_creative_selection(
    product_id: str,
    *,
    selected_avatar_code: str | None = None,
    selected_scene_template_id: str | None = None,
    selected_camera_preset_code: str | None = None,
    selected_block_purpose: str | None = None,
    selected_content_type: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create/update the product's saved creative selection (status DRAFT).

    Validates each selected id against the live pool/library. Raises
    ``ValueError`` with a specific code on bad input. Only writes the
    ``creative_product_selection`` table — never product rows or generation.
    """
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    if selected_avatar_code and selected_avatar_code not in _avatar_index():
        raise ValueError("INVALID_AVATAR_CODE")
    if selected_scene_template_id and selected_scene_template_id not in _scene_index():
        raise ValueError("INVALID_SCENE_TEMPLATE_ID")
    if selected_camera_preset_code and selected_camera_preset_code not in _camera_index():
        raise ValueError("INVALID_CAMERA_PRESET_CODE")

    resolved = _avatar.resolve_cluster(product.get("category"))
    if resolved["cluster"] is None:
        # Fail-closed: never persist a creative selection for a review-required
        # (un-categorised / unresolved) product. A real category must be set
        # first — no silent Home & Living plan.
        raise ValueError("PRODUCT_CATEGORY_REVIEW_REQUIRED")
    row_for_preview = {
        "cluster": resolved["cluster"], "cluster_source": resolved["cluster_source"],
        "selected_avatar_code": selected_avatar_code,
        "selected_scene_template_id": selected_scene_template_id,
        "selected_camera_preset_code": selected_camera_preset_code,
    }
    preview = _build_preview(row_for_preview)
    provenance = {
        "source": PROVENANCE_SOURCE,
        "resolved_cluster": resolved["cluster"],
        "cluster_source": resolved["cluster_source"],
    }

    saved = await crud.upsert_creative_product_selection(
        product_id=product_id,
        cluster=resolved["cluster"],
        cluster_source=resolved["cluster_source"],
        selected_avatar_code=selected_avatar_code,
        selected_scene_template_id=selected_scene_template_id,
        selected_camera_preset_code=selected_camera_preset_code,
        selected_block_purpose=selected_block_purpose,
        selected_content_type=selected_content_type,
        notes=notes,
        preview_json=json.dumps(preview, ensure_ascii=False),
        provenance_json=json.dumps(provenance, ensure_ascii=False),
        status="DRAFT",
    )
    return _hydrate_selection(saved)


async def get_creative_selection(product_id: str) -> dict[str, Any] | None:
    from agent.db import crud

    return _hydrate_selection(await crud.get_creative_product_selection(product_id))


AVATAR_PATCH_SOURCE = "AVATAR_REGISTRY_AVATAR_PATCH_v1"


async def update_creative_selection_avatar(
    product_id: str,
    *,
    selected_avatar_code: str,
    notes_append: str | None = None,
) -> dict[str, Any]:
    """Avatar-only partial update for a product creative selection.

    Reads the existing selection (if any), validates the new avatar against the
    live pool, preserves scene/camera/block/content_type/unrelated notes, then
    writes only selected_avatar_code + avatar-related provenance and rebuilds
    preview/provenance from the merged row. Always returns the selection to
    DRAFT (including when prior status was APPROVED or REJECTED).

    Raises:
      PRODUCT_NOT_FOUND, INVALID_AVATAR_CODE, PRODUCT_CATEGORY_REVIEW_REQUIRED
    Never mutates product rows or generation tables.
    """
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    code = str(selected_avatar_code or "").strip()
    if not code or code not in _avatar_index():
        raise ValueError("INVALID_AVATAR_CODE")

    resolved = _avatar.resolve_cluster(product.get("category"))
    if resolved["cluster"] is None:
        raise ValueError("PRODUCT_CATEGORY_REVIEW_REQUIRED")

    existing = await crud.get_creative_product_selection(product_id) or {}
    scene_id = existing.get("selected_scene_template_id")
    camera_code = existing.get("selected_camera_preset_code")
    block = existing.get("selected_block_purpose")
    content_type = existing.get("selected_content_type")
    prior_notes = existing.get("notes")

    notes = prior_notes
    append = str(notes_append or "").strip()
    if append:
        if prior_notes and append not in str(prior_notes):
            notes = f"{prior_notes}\n{append}" if str(prior_notes).strip() else append
        elif not prior_notes:
            notes = append

    prior_prov: dict[str, Any] = {}
    raw_prov = existing.get("provenance_json")
    if isinstance(raw_prov, str) and raw_prov:
        try:
            loaded = json.loads(raw_prov)
            if isinstance(loaded, dict):
                prior_prov = loaded
        except (ValueError, TypeError):
            prior_prov = {}
    elif isinstance(raw_prov, dict):
        prior_prov = dict(raw_prov)

    row_for_preview = {
        "cluster": resolved["cluster"],
        "cluster_source": resolved["cluster_source"],
        "selected_avatar_code": code,
        "selected_scene_template_id": scene_id,
        "selected_camera_preset_code": camera_code,
    }
    preview = _build_preview(row_for_preview)
    provenance = {
        **prior_prov,
        "source": AVATAR_PATCH_SOURCE,
        "resolved_cluster": resolved["cluster"],
        "cluster_source": resolved["cluster_source"],
        "update_kind": "AVATAR_ONLY",
        "previous_avatar_code": existing.get("selected_avatar_code"),
        "selected_avatar_code": code,
    }

    saved = await crud.upsert_creative_product_selection(
        product_id=product_id,
        cluster=resolved["cluster"],
        cluster_source=resolved["cluster_source"],
        selected_avatar_code=code,
        selected_scene_template_id=scene_id,
        selected_camera_preset_code=camera_code,
        selected_block_purpose=block,
        selected_content_type=content_type,
        notes=notes,
        preview_json=json.dumps(preview, ensure_ascii=False),
        provenance_json=json.dumps(provenance, ensure_ascii=False),
        status="DRAFT",
    )
    return _hydrate_selection(saved)


async def review_creative_selection(
    product_id: str, action: str, reviewer_note: str | None = None
) -> dict[str, Any]:
    """Transition a DRAFT selection to APPROVED or REJECTED. Fail-closed:
    unknown product/selection -> SELECTION_NOT_FOUND; non-DRAFT -> NOT_IN_DRAFT;
    unknown action -> INVALID_ACTION."""
    from agent.db import crud

    action = (action or "").upper()
    target = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}.get(action)
    if not target:
        raise ValueError("INVALID_ACTION")

    current = await crud.get_creative_product_selection(product_id)
    if not current:
        raise ValueError("SELECTION_NOT_FOUND")
    if current.get("status") != "DRAFT":
        raise ValueError("NOT_IN_DRAFT")

    updated = await crud.set_creative_product_selection_status(
        product_id, target, reviewer_note
    )
    return _hydrate_selection(updated)
