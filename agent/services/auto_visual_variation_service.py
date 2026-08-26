"""Round 3 — Auto Visual Variation Resolver (provider-free, deterministic).

SYSTEM OWNS VISUAL VARIATION SELECTION. This composes the EXISTING coherent visual
authorities into N coherent visual configurations for a production recipe, each
carrying a deterministic ``visual_variation_fingerprint``. There is NO new visual
LLM, NO image/video provider call, NO random selection, and NO independent camera
pick — camera follows scene. It REUSES (never duplicates):

  HYBRID   -> ``creative_recipe_service`` (avatar x scene -> scene-derived camera)
  FACELESS -> ``faceless_lane_service.resolve_faceless_scene_authority`` (no avatar)
  MONTAGE  -> ``product_mascot_service`` (mascot identity; fail-closed) + faceless
              scene choreography for beat variation (mascot is the protagonist,
              never a human Avatar Registry presenter).

Diversity is a deterministic seeded round-robin over the coherent pool: for N
outputs it selects N distinct visual fingerprints when capacity allows, and only
falls back to controlled reuse (recorded, never silent) once unique capacity is
exhausted. Nothing here writes DB state or spends credits.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

AUTO_VISUAL_RESOLVER_VERSION = "AUTO_VISUAL_VARIATION_V1"
SUPPORTED_PRODUCTION_RECIPES = ("HYBRID", "FACELESS", "MONTAGE")
# Upper bound on how many raw variation indices we probe when discovering the
# unique FACELESS/MONTAGE scene-variation capacity (deterministic, provider-free).
_MAX_SCENE_PROBE = 64
VISUAL_CAPACITY_REUSE = "VISUAL_CAPACITY_REUSE"


class AutoVisualVariationError(Exception):
    """Deterministic, fail-closed visual-resolution error (never a silent default)."""

    def __init__(self, code: str, message: str = "", *, details: Any = None,
                 status_code: int = 409) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details or {}
        self.status_code = status_code


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                      default=str)


def visual_variation_fingerprint(payload: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 over a variation's provider-affecting visual identity.

    Two visually equivalent variations fingerprint identically; volatile fields
    (timestamps/uuids) are never included by construction (callers pass only the
    stable visual identity)."""
    return hashlib.sha256(_stable_json(dict(payload)).encode("utf-8")).hexdigest()


def _seed_offset(seed: str | None, product_id: str, production_recipe: str, size: int) -> int:
    if size <= 0:
        return 0
    key = f"{AUTO_VISUAL_RESOLVER_VERSION}|{seed or ''}|{product_id}|{production_recipe}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % size


def _spread(pool: list[dict[str, Any]], count: int, *, seed: str | None,
            product_id: str, production_recipe: str) -> tuple[list[dict[str, Any]], int]:
    """Deterministic seeded round-robin selection of ``count`` variations from a pool
    of distinct configs. Distinct fingerprints first; controlled, recorded reuse only
    once the unique pool is exhausted. Returns (selected, unique_capacity)."""
    unique_capacity = len(pool)
    if unique_capacity == 0:
        return [], 0
    offset = _seed_offset(seed, product_id, production_recipe, unique_capacity)
    selected: list[dict[str, Any]] = []
    for i in range(int(count)):
        base = dict(pool[(offset + i) % unique_capacity])
        reuse = i >= unique_capacity
        base["index"] = i
        base["reuse"] = reuse
        base["reuse_reason"] = VISUAL_CAPACITY_REUSE if reuse else None
        selected.append(base)
    return selected, unique_capacity


# -- HYBRID -----------------------------------------------------------------
async def _hybrid_pool(product_id: str, avatar_id: str | None) -> list[dict[str, Any]]:
    from agent.services import creative_recipe_service as cr

    data = await cr.generate_product_recipes(product_id)
    if data.get("review_required"):
        raise AutoVisualVariationError(
            "HYBRID_VISUAL_NOT_READY",
            "The product's creative setup requires review before HYBRID visuals can be resolved.",
            details={"product_id": product_id, "cluster": data.get("cluster")})
    recipes = list(data.get("recipes") or [])
    if avatar_id:
        recipes = [r for r in recipes if str(r.get("avatar_code")) == str(avatar_id)]
        if not recipes:
            raise AutoVisualVariationError(
                "HYBRID_AVATAR_NOT_IN_POOL",
                "The governed avatar is not eligible for this product's current scene pool.",
                details={"product_id": product_id, "avatar_id": avatar_id})
    if not recipes:
        raise AutoVisualVariationError(
            "HYBRID_VISUAL_POOL_EMPTY",
            "No coherent avatar x scene recipe is available for this product.",
            details={"product_id": product_id})

    from agent.services import avatar_registry

    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in recipes:
        scene_template_id = str(r.get("scene_template_id") or "")
        camera_preset_code = str(r.get("camera_preset_code") or "")
        desc = cr.resolve_recipe_descriptors(scene_template_id, camera_preset_code)
        environment = str((desc.get("scene_template") or {}).get("setting") or "")
        wardrobe = ""
        try:
            profile = avatar_registry.resolve_presenter(avatar_id=str(r.get("avatar_code")))
            wardrobe = str((profile or {}).get("wardrobe") or "")
        except Exception:  # noqa: BLE001 - wardrobe is descriptive only; never fail the pool on it
            wardrobe = ""
        identity = {
            "production_recipe": "HYBRID",
            "avatar_id": str(r.get("avatar_code")),
            "scene_template_id": scene_template_id,
            "scene_variant": str(r.get("scene_variant") or ""),
            "camera_preset_code": camera_preset_code,
            "wardrobe": wardrobe,
            "environment": environment,
        }
        fp = visual_variation_fingerprint(identity)
        if fp in seen:
            continue
        seen.add(fp)
        pool.append({
            **identity,
            "visual_variation_fingerprint": fp,
            "character_presence": "VISIBLE_CREATOR",
            "descriptor": {
                "avatar_code": str(r.get("avatar_code")),
                "scene_template": desc.get("scene_template"),
                "camera_preset": desc.get("camera_preset"),
                "scene_variant": r.get("scene_variant"),
                "block_purpose": r.get("block_purpose"),
                "content_type": r.get("content_type"),
                "wardrobe": wardrobe,
                "environment": environment,
            },
        })
    return pool


# -- FACELESS / MONTAGE (shared scene-variation enumeration) ----------------
async def _faceless_scene_pool(product_id: str, production_recipe: str) -> list[dict[str, Any]]:
    from agent.services import faceless_lane_service as fl

    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    misses = 0
    for k in range(_MAX_SCENE_PROBE):
        try:
            auth = await fl.resolve_faceless_scene_authority(
                product_id=product_id, hook_id="AUTO", background_id="AUTO",
                actor_profile="AUTO", variation_index=k)
        except ValueError as exc:  # ERR_FACELESS_SCENE_STRATEGY_REQUIRED / PRODUCT_NOT_FOUND
            code = str(exc).split(":", 1)[0].strip() or "FACELESS_SCENE_UNRESOLVED"
            raise AutoVisualVariationError(
                "FACELESS_SCENE_STRATEGY_REQUIRED" if "STRATEGY" in code else "FACELESS_PRODUCT_NOT_FOUND",
                str(exc), details={"product_id": product_id, "reason": code})
        actor = auth.get("actor_profile") or {}
        scene = auth.get("scene_strategy") or {}
        chor = auth.get("choreography") or {}
        bg = auth.get("background") or {}
        identity = {
            "production_recipe": production_recipe,
            "faceless_actor_profile": str(actor.get("actor_profile_id") or actor.get("actor_profile") or ""),
            "faceless_scene_context": str(scene.get("scene_context") or scene.get("scene_context_id") or ""),
            "camera_route": str(scene.get("camera_route") or chor.get("camera_route") or ""),
            "choreography": str(chor.get("choreography_id") or chor.get("id") or ""),
            "environment": str(bg.get("environment_intent") or bg.get("background_id") or ""),
        }
        fp = visual_variation_fingerprint(identity)
        if fp in seen:
            misses += 1
            # two full cycles with no new fingerprint => capacity discovered
            if misses >= max(2, len(pool)):
                break
            continue
        misses = 0
        seen.add(fp)
        pool.append({
            **identity,
            "avatar_id": None,
            "visual_variation_fingerprint": fp,
            "character_presence": "FACELESS",
            "variation_index": k,
            "descriptor": {
                "actor_profile": actor,
                "scene_strategy": {"scene_context": scene.get("scene_context"),
                                   "camera_route": scene.get("camera_route")},
                "choreography": chor,
                "background": {"environment_intent": bg.get("environment_intent")},
            },
        })
    if not pool:
        raise AutoVisualVariationError(
            "FACELESS_SCENE_POOL_EMPTY",
            "No coherent faceless scene variation is available for this product.",
            details={"product_id": product_id})
    return pool


async def _montage_pool(product_id: str) -> list[dict[str, Any]]:
    from agent.services import product_mascot_service as pm

    mascot = await pm.get_current_product_mascot(product_id)
    if not mascot:
        raise AutoVisualVariationError(
            "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED",
            "Montage requires a governed product mascot key visual; none is currently available.",
            details={"product_id": product_id})
    mascot_media_id = str(mascot.get("media_id") or mascot.get("creative_asset_id")
                          or mascot.get("asset_id") or "")
    scene_pool = await _faceless_scene_pool(product_id, "MONTAGE")
    # The mascot is the fixed protagonist across every montage variation; scene
    # choreography provides the beat variation. Fold the mascot identity into each
    # fingerprint so montage variations never collide with faceless ones.
    pool: list[dict[str, Any]] = []
    for entry in scene_pool:
        identity = {
            "production_recipe": "MONTAGE",
            "montage_mascot_media_id": mascot_media_id,
            "faceless_scene_context": entry.get("faceless_scene_context"),
            "camera_route": entry.get("camera_route"),
            "choreography": entry.get("choreography"),
            "environment": entry.get("environment"),
        }
        fp = visual_variation_fingerprint(identity)
        pool.append({
            **entry,
            "production_recipe": "MONTAGE",
            "montage_mascot_media_id": mascot_media_id,
            "visual_variation_fingerprint": fp,
            "descriptor": {**(entry.get("descriptor") or {}), "mascot": mascot},
        })
    return pool


# -- public entry point -----------------------------------------------------
async def resolve_visual_variations(
    product_id: str,
    production_recipe: str,
    count: int,
    *,
    avatar_id: str | None = None,
    seed: str | None = None,
) -> dict[str, Any]:
    """Resolve ``count`` coherent, deterministically-spread visual variations for a
    production recipe. Provider-free. Raises ``AutoVisualVariationError`` fail-closed
    when the recipe/product cannot produce a governed visual identity."""
    recipe = str(production_recipe or "").strip().upper()
    if recipe not in SUPPORTED_PRODUCTION_RECIPES:
        raise AutoVisualVariationError(
            "PRODUCTION_RECIPE_UNSUPPORTED",
            f"Auto visual variation supports {SUPPORTED_PRODUCTION_RECIPES}.",
            details={"production_recipe": production_recipe})
    if int(count) < 1:
        raise AutoVisualVariationError("VISUAL_VARIATION_COUNT_INVALID",
                                       details={"count": count})
    if recipe == "HYBRID":
        pool = await _hybrid_pool(product_id, avatar_id)
    elif recipe == "FACELESS":
        pool = await _faceless_scene_pool(product_id, "FACELESS")
    else:  # MONTAGE
        pool = await _montage_pool(product_id)

    variations, unique_capacity = _spread(
        pool, int(count), seed=seed, product_id=product_id, production_recipe=recipe)
    reuse = [v["visual_variation_fingerprint"] for v in variations if v.get("reuse")]
    return {
        "product_id": product_id,
        "production_recipe": recipe,
        "requested_count": int(count),
        "resolver_version": AUTO_VISUAL_RESOLVER_VERSION,
        "unique_capacity": unique_capacity,
        "controlled_reuse_count": len(reuse),
        "variations": variations,
    }
