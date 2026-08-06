"""Creative Recipe generator — deterministic (avatar x scene) -> camera-derived tuples.

WHY THIS EXISTS (owner architecture, 2026-08-06):
The old Creative Direction showed three FLAT, independent lists (avatars / scene
templates / camera presets) with a fill-all default (17 cameras pre-ticked). That let
the operator build incoherent combos (wrong-gender avatar, a cooking product with an
office-clothes/tudung scene, a camera that does not match the scene) — wasting credits
on nonsense during production.

THE MODEL:
  * A "recipe" is one COHERENT tuple: (avatar, scene_template, camera).
  * CAMERA FOLLOWS SCENE — it is NEVER an independent 3rd axis. Each scene template's
    Variation archetype (1-7, consistent across every cluster) maps via the
    scene->variation->camera bridge (creative_scene_variation_camera_bridge.json) to the
    EXISTING camera block_content_mapping, so every recipe carries a shot-coherent camera.
    This collapses the nonsense explosion (avatars x scenes x 17 cameras) into a coherent
    grid (avatars x scenes) where the camera is determined.
  * PRODUCT-SCOPED BY CONSTRUCTION — avatars are gender+cluster filtered and scenes are
    cluster filtered (both come straight from resolve_creative_setup), so avatar x scene
    is a free, already-coherent grid.

The knowledge base is RULES, not per-product data: the 7-row bridge + the existing
cluster/gender/camera authorities produce recipes for EVERY product automatically. No AI,
no credits. See [[project_pi_editor_prepare_accuracy_and_declutter]].
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_AUTHORITY = Path(__file__).resolve().parent.parent / "authority"
_BRIDGE_FILE = _AUTHORITY / "creative_scene_variation_camera_bridge.json"
_CAMERA_FILE = _AUTHORITY / "creative_camera_preset_library.json"

_VARIATION_RE = re.compile(r"variation\s*(\d+)", re.IGNORECASE)

# Manual pre-tick caps — keep the default sane (a few coherent recipes), NOT fill-all.
# The FULL recipe pool is always returned for mass-production rotation.
_DEFAULT_AVATAR_CAP = 2
_DEFAULT_VARIATION_CAP = 4


@dataclass(frozen=True)
class CreativeRecipe:
    """One coherent (avatar, scene, camera) combination. camera_* is DERIVED from the
    scene's Variation via the bridge — never picked independently."""

    avatar_code: str
    scene_template_id: str
    scene_variant: str
    variation: int | None
    camera_preset_code: str
    camera_alts: list[str]
    block_purpose: str
    content_type: str
    rationale: str


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def variation_of(variant: str) -> int | None:
    """Parse the Variation number (1-7) from a scene template's free-text variant label
    (e.g. 'Variation 1 - Holding & Presenting' -> 1). None when absent."""
    match = _VARIATION_RE.search(str(variant or ""))
    return int(match.group(1)) if match else None


def _camera_index(camera_mapping: list[dict]) -> dict[tuple[str, str], dict]:
    """(block_purpose, content_type) -> block_content_mapping row."""
    index: dict[tuple[str, str], dict] = {}
    for row in camera_mapping or []:
        key = (
            str(row.get("block_purpose", "")).strip(),
            str(row.get("content_type", "")).strip(),
        )
        index[key] = row
    return index


def camera_for_variation(
    variation: int | None, bridge: dict, camera_index: dict[tuple[str, str], dict]
) -> dict[str, Any]:
    """Resolve the shot-coherent camera for a scene Variation: bridge -> (block_purpose,
    content_type) -> existing block_content_mapping. Fails soft to the bridge fallback."""
    vmap = bridge.get("variation_map", {})
    fallback = bridge.get("fallback") or {
        "archetype": "",
        "block_purpose": "Body Block",
        "content_type": "Product Demo",
    }
    spec = vmap.get(str(variation)) if variation is not None else None
    if not spec:
        spec = fallback
    block_purpose = str(spec.get("block_purpose") or fallback["block_purpose"]).strip()
    content_type = str(spec.get("content_type") or fallback["content_type"]).strip()
    row = camera_index.get((block_purpose, content_type)) or {}
    alts = [
        str(row.get("alt_preset_1") or "").strip(),
        str(row.get("alt_preset_2") or "").strip(),
    ]
    return {
        "archetype": str(spec.get("archetype") or ""),
        "block_purpose": block_purpose,
        "content_type": content_type,
        "camera_preset_code": str(row.get("recommended_preset") or "").strip(),
        "camera_alts": [alt for alt in alts if alt],
    }


def build_recipes(
    avatars: list[str],
    scenes: list[dict],
    bridge: dict,
    camera_mapping: list[dict],
) -> list[CreativeRecipe]:
    """PURE deterministic core (no I/O) — the coherent (avatar x scene) grid with a
    scene-derived camera on each tuple. Order: avatar-major, scene-order preserved."""
    camera_index = _camera_index(camera_mapping)
    recipes: list[CreativeRecipe] = []
    for raw_avatar in avatars:
        avatar = str(raw_avatar or "").strip()
        if not avatar:
            continue
        for scene in scenes:
            scene_id = str(scene.get("template_id") or "").strip()
            if not scene_id:
                continue
            variant = str(scene.get("variant") or "")
            variation = variation_of(variant)
            cam = camera_for_variation(variation, bridge, camera_index)
            archetype = cam["archetype"] or variant or scene_id
            preset = cam["camera_preset_code"] or "(no camera)"
            rationale = (
                f"{avatar} — {archetype} [{scene_id}] -> {preset} "
                f"({cam['block_purpose']}/{cam['content_type']})"
            )
            recipes.append(
                CreativeRecipe(
                    avatar_code=avatar,
                    scene_template_id=scene_id,
                    scene_variant=variant,
                    variation=variation,
                    camera_preset_code=cam["camera_preset_code"],
                    camera_alts=cam["camera_alts"],
                    block_purpose=cam["block_purpose"],
                    content_type=cam["content_type"],
                    rationale=rationale,
                )
            )
    return recipes


def _spread_pick(items: list, count: int) -> list:
    """Pick `count` items evenly SPREAD across the list (always including the first and
    last) — so a capped pick spans the shot arc (intro -> body -> detail -> benefit)
    instead of clustering at the start."""
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[0]]
    last = len(items) - 1
    return [items[round(i * last / (count - 1))] for i in range(count)]


def pretick_recipes(
    recipes: list[CreativeRecipe],
    *,
    avatar_cap: int = _DEFAULT_AVATAR_CAP,
    variation_cap: int = _DEFAULT_VARIATION_CAP,
) -> list[CreativeRecipe]:
    """A DIVERSE, capped subset for the manual pre-tick: the first `avatar_cap` avatars x
    a SPREAD of distinct Variations (so the default covers the shot arc — intro, body,
    close-up, benefit — not N near-identical demo shots). The full pool stays available
    for mass rotation."""
    if not recipes:
        return []
    ordered_avatars: list[str] = []
    first_by_variation: dict[str, dict] = {}
    variations_by_avatar: dict[str, list] = {}
    for recipe in recipes:
        if recipe.avatar_code not in ordered_avatars:
            ordered_avatars.append(recipe.avatar_code)
        key = recipe.variation if recipe.variation is not None else recipe.scene_template_id
        slot = first_by_variation.setdefault(recipe.avatar_code, {})
        if key not in slot:
            slot[key] = recipe
            variations_by_avatar.setdefault(recipe.avatar_code, []).append(key)
    keep = ordered_avatars[: max(1, avatar_cap)]
    out: list[CreativeRecipe] = []
    for avatar in keep:
        chosen = _spread_pick(variations_by_avatar.get(avatar, []), max(1, variation_cap))
        out.extend(first_by_variation[avatar][key] for key in chosen)
    return out


def load_bridge() -> dict:
    """The scene->variation->camera bridge authority (tunable JSON, no code change)."""
    return _load_json(_BRIDGE_FILE)


def load_camera_mapping() -> list[dict]:
    """The existing camera block_content_mapping (SSOT authority)."""
    return _load_json(_CAMERA_FILE).get("block_content_mapping", [])


def recipes_from_setup(
    setup: dict[str, Any], *, honor_saved: bool = True
) -> dict[str, list[CreativeRecipe]]:
    """Build coherent recipes from an ALREADY-RESOLVED creative setup dict, so callers
    that already hold one (e.g. the bulk backfill) avoid a second resolve.

    Returns {'recipes': full pool, 'pretick': recommended default}. When ``honor_saved``
    and the product has a SAVED selection, the pretick reconstructs THAT durable plan
    (saved avatars × saved scenes, camera derived); otherwise it is the freshly COMPUTED
    arc-spread default. The backfill passes honor_saved=False so it regenerates rather
    than re-deriving a stale top-1 plan."""
    bridge = load_bridge()
    camera_mapping = load_camera_mapping()
    all_scenes = list(setup.get("recommended_scene_templates") or [])
    default = setup.get("default_selection") or {}
    saved = setup.get("saved_selection") or {} if honor_saved else {}
    default_avatars = list(default.get("selected_avatar_codes") or [])
    saved_avatars = list(saved.get("selected_avatar_codes") or [])
    # The pool includes any saved avatar so the saved plan is always representable.
    pool_avatars = list(dict.fromkeys([*default_avatars, *saved_avatars]))
    recipes = build_recipes(pool_avatars, all_scenes, bridge, camera_mapping)
    saved_scene_ids = list(saved.get("selected_scene_template_ids") or [])
    if saved_avatars or saved_scene_ids:
        scene_by_id = {
            str(s.get("template_id")): s for s in all_scenes if s.get("template_id")
        }
        saved_scenes = [scene_by_id[sid] for sid in saved_scene_ids if sid in scene_by_id]
        if saved_scene_ids and not saved_scenes:
            # The saved plan's scenes have ALL drifted out of the product's CURRENT
            # cluster (reassignment / template removal / id rename). Do NOT silently
            # expand to every cluster scene — that re-introduces the fill-all this module
            # exists to prevent. Fall back to the computed arc-spread default instead.
            pretick = pretick_recipes(recipes)
        else:
            pretick = build_recipes(
                saved_avatars or default_avatars,
                saved_scenes or all_scenes,
                bridge,
                camera_mapping,
            )
    else:
        pretick = pretick_recipes(recipes)
    return {"recipes": recipes, "pretick": pretick}


def resolve_recipe_descriptors(
    scene_template_id: str | None, camera_preset_code: str | None
) -> dict[str, Any]:
    """Resolve a picked recipe's scene-template id + camera-preset code to the DESCRIPTOR
    dicts the canonical compiler consumes: {"scene_template", "camera_preset"}.

    Read-only registry lookups (scene-prompt + camera-preset libraries). A blank/unknown
    id yields None for that slot, so the compiler behaves EXACTLY as before (its enrichment
    is opt-in). Lazy imports keep this free of the creative-planning services."""
    scene_template: dict[str, Any] | None = None
    camera_preset: dict[str, Any] | None = None
    sid = str(scene_template_id or "").strip()
    if sid:
        try:
            from agent.services import creative_scene_prompt_service as _scene

            for template in _scene.library_templates():
                if str(template.get("template_id")) == sid:
                    scene_template = {
                        "main_action": template.get("main_action"),
                        "setting": template.get("setting"),
                    }
                    break
        except Exception:
            scene_template = None
    code = str(camera_preset_code or "").strip()
    if code:
        try:
            from agent.services import creative_camera_preset_service as _camera

            for preset in _camera.named_presets():
                if str(preset.get("preset_code")) == code:
                    camera_preset = {
                        "preset_name": preset.get("preset_name"),
                        "distance_angle": preset.get("distance_angle"),
                        "movement": preset.get("movement"),
                    }
                    break
        except Exception:
            camera_preset = None
    return {"scene_template": scene_template, "camera_preset": camera_preset}


def resolve_scene_template(scene_template_id: str | None) -> dict[str, Any] | None:
    """Scene-template descriptor dict (or None) for the canonical compiler."""
    return resolve_recipe_descriptors(scene_template_id, None)["scene_template"]


def resolve_camera_preset(camera_preset_code: str | None) -> dict[str, Any] | None:
    """Camera-preset framing dict (or None) for the canonical compiler."""
    return resolve_recipe_descriptors(None, camera_preset_code)["camera_preset"]


async def generate_product_recipes(product_id: str) -> dict[str, Any]:
    """Async wrapper: reuse resolve_creative_setup for cluster/gender/scene eligibility,
    then build coherent recipes (honouring a saved plan). Returns the FULL pool (mass
    rotation) plus a capped `recommended_pretick`. Deterministic; no AI; no credits."""
    from agent.services import creative_setup_service  # lazy: avoid import cycle

    setup = await creative_setup_service.resolve_creative_setup(product_id)
    if setup.get("review_required") or not setup.get("default_selection"):
        return {
            "product_id": product_id,
            "cluster": setup.get("cluster"),
            "cluster_source": setup.get("cluster_source"),
            "review_required": bool(setup.get("review_required")),
            "recipes": [],
            "recommended_pretick": [],
            "counts": {"avatars": 0, "scenes": 0, "recipes": 0, "pretick": 0},
        }
    built = recipes_from_setup(setup)
    recipes = built["recipes"]
    pretick = built["pretick"]
    return {
        "product_id": product_id,
        "product_name": setup.get("product_name"),
        "cluster": setup.get("cluster"),
        "cluster_source": setup.get("cluster_source"),
        "review_required": False,
        "saved": bool(setup.get("saved_selection")),
        "recipes": [asdict(recipe) for recipe in recipes],
        "recommended_pretick": [asdict(recipe) for recipe in pretick],
        "counts": {
            # distinct avatars actually present in `recipes` (the pool unions default +
            # saved), so the summary never understates what the payload contains.
            "avatars": len({recipe.avatar_code for recipe in recipes}),
            "scenes": len(list(setup.get("recommended_scene_templates") or [])),
            "recipes": len(recipes),
            "pretick": len(pretick),
        },
    }
