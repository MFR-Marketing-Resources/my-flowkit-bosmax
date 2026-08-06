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
import re
from typing import Any

from agent.services import avatar_registry
from agent.services import creative_avatar_recommendation_service as _avatar
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera

PROVENANCE_SOURCE = "CREATIVE_SETUP_v1"
_VALID_STATUS = ("DRAFT", "APPROVED", "REJECTED")

_VARIANT_SUFFIX = re.compile(r"_\d+$")
_MINOR_AGE_BANDS = {"child (6-12)", "teen (13-17)"}


def _full_avatar_roster(recommended_codes: set[str]) -> list[dict[str, Any]]:
    """The full pickable avatar roster — one entry per distinct persona (not every
    pose-variant), adults only, with the cluster's recommended picks flagged and
    sorted first. This is what lets the operator choose from the WHOLE registry
    instead of only the 3-4 avatars the cluster crosswalk recommends.
    """
    recommended_bases = {_VARIANT_SUFFIX.sub("", str(c)) for c in recommended_codes}
    seen: dict[str, dict[str, Any]] = {}
    for prof in avatar_registry.list_pool():
        code = str(prof.get("avatar_code") or "").strip()
        if not code:
            continue
        base = _VARIANT_SUFFIX.sub("", code)
        if base in seen:
            continue
        if str(prof.get("age_band") or "").strip().casefold() in _MINOR_AGE_BANDS:
            continue
        upper = code.upper()
        seen[base] = {
            "avatar_code": code,
            "character_name": prof.get("character_name") or "",
            "gender": "F" if "_F_" in upper else ("M" if "_M_" in upper else ""),
            "age_band": prof.get("age_band") or "",
            "recommended": code in recommended_codes or base in recommended_bases,
        }
    roster = list(seen.values())
    roster.sort(key=lambda x: (not x["recommended"], x["avatar_code"]))
    return roster


_FEMALE_TOKENS = re.compile(
    r"\b(tudung|hijab|muslimah|wanita|perempuan|women|woman|female|ladies|lady|girl|"
    r"kurung|jubah|abaya|telekung|kebaya|gaun|dress|blouse|skirt|maxi|labuh|lingerie|"
    r"bra|kosmetik|lipstik|lipstick|makeup|mekap|serkup)\b",
    re.IGNORECASE,
)
_MALE_TOKENS = re.compile(
    r"\b(lelaki|men|man|male|boy|songkok|kopiah|jersi\s+lelaki|seluar\s+lelaki|"
    r"baju\s+melayu|kemeja\s+lelaki|misai|janggut)\b",
    re.IGNORECASE,
)


def _code_gender(code: str) -> str:
    up = str(code or "").upper()
    return "F" if "_F_" in up else ("M" if "_M_" in up else "")


def _resolve_product_target_gender(
    product: dict[str, Any], snapshot: dict[str, Any] | None
) -> str:
    """Best-effort target gender ('F' / 'M' / 'ANY') from product identity + approved
    intelligence, so the smart default only ticks gender-appropriate avatars — a women's
    tudung must never get a male presenter. Fail-OPEN to 'ANY' (keep all recommended)
    when the signal is unclear or unisex, so we never wrongly narrow a general product.
    """
    parts = [
        str(product.get("product_display_name") or ""),
        str(product.get("raw_product_title") or ""),
        str(product.get("product_short_name") or ""),
        str(product.get("type") or ""),
        str(product.get("category") or ""),
    ]
    if snapshot:
        parts.append(str(snapshot.get("target_customer_text") or ""))
        try:
            persona = json.loads(snapshot.get("buyer_persona_snapshot_json") or "{}")
            if isinstance(persona, dict):
                parts.append(str(persona.get("audience") or ""))
        except Exception:
            pass
    text = " ".join(p for p in parts if p)
    female = bool(_FEMALE_TOKENS.search(text))
    male = bool(_MALE_TOKENS.search(text))
    if female and not male:
        return "F"
    if male and not female:
        return "M"
    return "ANY"


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
    # Multi-select lists. Parse the JSON arrays; fall back to [primary] so old
    # single-select rows still expose a one-item list to the client.
    for jf, key, primary in (
        ("selected_avatar_codes_json", "selected_avatar_codes", "selected_avatar_code"),
        ("selected_scene_template_ids_json", "selected_scene_template_ids", "selected_scene_template_id"),
        ("selected_camera_preset_codes_json", "selected_camera_preset_codes", "selected_camera_preset_code"),
    ):
        parsed: list[str] = []
        raw = out.get(jf)
        if isinstance(raw, str) and raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, list):
                    parsed = [str(c) for c in loaded if str(c or "").strip()]
            except (ValueError, TypeError):
                parsed = []
        if not parsed and out.get(primary):
            parsed = [str(out[primary])]
        out[key] = parsed
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
            "avatar_library": [],
            "default_selection": None,
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
    # GENDER-APPROPRIATE smart default: read the product identity + approved
    # intelligence to keep ONLY avatars of the product's target gender, so a women's
    # tudung never ticks a male presenter (the Fashion crosswalk mixes genders). Scenes
    # and camera presets stay cluster-scoped (already product-type-appropriate).
    snapshot = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    target_gender = _resolve_product_target_gender(product, snapshot)
    recommended_codes = [
        a["avatar_code"] for a in avatars["avatars"] if a.get("avatar_code")
    ]
    if target_gender in ("F", "M"):
        gender_avatars = [c for c in recommended_codes if _code_gender(c) == target_gender]
        if not gender_avatars:
            # cluster crosswalk had no avatar of the product's gender — pull from the
            # full roster so a gendered product still gets gender-correct presenters.
            gender_avatars = [
                a["avatar_code"]
                for a in _full_avatar_roster(set())
                if a["gender"] == target_gender
            ][:4]
    else:
        gender_avatars = recommended_codes

    # avatar_library flags the gender-appropriate recommended set (★) but still lists
    # every avatar so the operator can manually override.
    avatar_library = _full_avatar_roster(set(gender_avatars))
    # Live-derived, recomputed every read → auto-updates when avatars / scene templates
    # / camera presets change. A saved selection (if any) OVERRIDES this. Diverse-by-
    # design so mass production can rotate combinations without repeating.
    default_selection = {
        "selected_avatar_codes": gender_avatars,
        "selected_scene_template_ids": [
            t["template_id"] for t in scenes["templates"] if t.get("template_id")
        ],
        "selected_camera_preset_codes": [
            p["preset_code"]
            for p in cameras["library"]["named_presets"]
            if p.get("preset_code")
        ],
        "source": "AUTO_DEFAULT_FROM_CLUSTER_MAPPING",
        "target_gender": target_gender,
    }

    return {
        "product_id": product_id,
        "product_name": product.get("product_display_name") or product.get("raw_product_title"),
        "category": category,
        "cluster": avatars["cluster"],
        "cluster_source": avatars["cluster_source"],
        "review_required": False,
        "recommended_avatars": avatars["avatars"],
        "avatar_library": avatar_library,
        "default_selection": default_selection,
        "recommended_scene_templates": scenes["templates"],
        "camera_block_recommendations": cameras["block_recommendations"],
        "camera_library": cameras["library"],
        "saved_selection": saved,
    }


def _dedup(codes: list[str] | None, single: str | None) -> list[str]:
    """Normalise a multi-select input: prefer the list, else wrap the singular;
    strip blanks, dedup, preserve order."""
    source = codes if codes is not None else ([single] if single else [])
    out: list[str] = []
    for code in source:
        clean = str(code or "").strip()
        if clean and clean not in out:
            out.append(clean)
    return out


async def save_creative_selection(
    product_id: str,
    *,
    selected_avatar_code: str | None = None,
    selected_scene_template_id: str | None = None,
    selected_camera_preset_code: str | None = None,
    selected_avatar_codes: list[str] | None = None,
    selected_scene_template_ids: list[str] | None = None,
    selected_camera_preset_codes: list[str] | None = None,
    selected_block_purpose: str | None = None,
    selected_content_type: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create/update the product's saved creative selection (status DRAFT).

    Multi-select: pass ``selected_*_codes`` LISTS (the singular ``selected_*_code``
    kwargs stay for backward compatibility and are treated as a one-item list).
    The first of each list becomes the backward-compatible PRIMARY that the
    generation pipeline reads. Validates every id against the live pool/library.
    Only writes the ``creative_product_selection`` table — never generation.
    """
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    avatar_codes = _dedup(selected_avatar_codes, selected_avatar_code)
    scene_ids = _dedup(selected_scene_template_ids, selected_scene_template_id)
    camera_codes = _dedup(selected_camera_preset_codes, selected_camera_preset_code)

    avatar_index, scene_index, camera_index = _avatar_index(), _scene_index(), _camera_index()
    if any(code not in avatar_index for code in avatar_codes):
        raise ValueError("INVALID_AVATAR_CODE")
    if any(sid not in scene_index for sid in scene_ids):
        raise ValueError("INVALID_SCENE_TEMPLATE_ID")
    if any(code not in camera_index for code in camera_codes):
        raise ValueError("INVALID_CAMERA_PRESET_CODE")

    # Primary = first of each list (kept for the single-value preview + as the
    # backward-compatible column). NOTE: as of the linkage audit, the saved selection
    # is consumed by the P6 plan builder for AVATARS only (via the multi-select list,
    # intersected against the plan pool) — the manual T2V/F2V/HYBRID/I2V, IMG, and
    # Poster lanes do NOT yet read it, and scene/camera never reach P6. Wiring those is
    # the pending program; do not claim this "feeds the generation pipeline" wholesale.
    primary_avatar = avatar_codes[0] if avatar_codes else None
    primary_scene = scene_ids[0] if scene_ids else None
    primary_camera = camera_codes[0] if camera_codes else None

    resolved = await _avatar.resolve_product_cluster(product_id, product.get("category"))
    if resolved["cluster"] is None:
        # Fail-closed: never persist a creative selection for a review-required
        # (un-categorised / unresolved) product. A real category must be set
        # first — no silent Home & Living plan.
        raise ValueError("PRODUCT_CATEGORY_REVIEW_REQUIRED")
    row_for_preview = {
        "cluster": resolved["cluster"], "cluster_source": resolved["cluster_source"],
        "selected_avatar_code": primary_avatar,
        "selected_scene_template_id": primary_scene,
        "selected_camera_preset_code": primary_camera,
    }
    preview = _build_preview(row_for_preview)
    provenance = {
        "source": PROVENANCE_SOURCE,
        "resolved_cluster": resolved["cluster"],
        "cluster_source": resolved["cluster_source"],
        "selected_counts": {
            "avatars": len(avatar_codes),
            "scenes": len(scene_ids),
            "cameras": len(camera_codes),
        },
    }

    saved = await crud.upsert_creative_product_selection(
        product_id=product_id,
        cluster=resolved["cluster"],
        cluster_source=resolved["cluster_source"],
        selected_avatar_code=primary_avatar,
        selected_scene_template_id=primary_scene,
        selected_camera_preset_code=primary_camera,
        selected_avatar_codes_json=json.dumps(avatar_codes, ensure_ascii=False),
        selected_scene_template_ids_json=json.dumps(scene_ids, ensure_ascii=False),
        selected_camera_preset_codes_json=json.dumps(camera_codes, ensure_ascii=False),
        selected_block_purpose=selected_block_purpose,
        selected_content_type=selected_content_type,
        notes=notes,
        preview_json=json.dumps(preview, ensure_ascii=False),
        provenance_json=json.dumps(provenance, ensure_ascii=False),
        status="DRAFT",
    )
    return _hydrate_selection(saved)


async def bulk_auto_setup(
    *,
    product_ids: list[str] | None = None,
    approve: bool = True,
    dry_run: bool = True,
    limit: int | None = None,
    refresh_auto: bool = False,
) -> dict[str, Any]:
    """Auto-fill each eligible product's creative selection from its COHERENT recipe
    pretick (avatar × scene, camera follows scene — arc-spread across intro/body/detail/
    benefit) and, when ``approve``, move it straight to APPROVED. Idempotent + fail-closed:
      * products already APPROVED are left untouched;
      * review-required (un-categorised) or no-recommendation products are skipped.
    Planning only — writes ``creative_product_selection`` rows, never generation.
    """
    from agent.db import crud
    from agent.services import creative_recipe_service as _recipe

    if product_ids is None:
        rows = await crud.list_products(include_archived=False)
        product_ids = [str(row.get("id")) for row in rows if row.get("id")]
    if limit:
        product_ids = product_ids[:limit]

    done = skipped = failed = 0
    reasons: dict[str, int] = {
        "already_approved": 0, "review_required": 0, "no_avatar": 0, "refreshed_auto": 0,
    }
    errors: list[dict[str, str]] = []
    for product_id in product_ids:
        try:
            existing = await get_creative_selection(product_id)
            if existing and existing.get("status") == "APPROVED":
                # refresh_auto upgrades ONLY machine-authored plans to the new coherent
                # recipe pretick — the "Auto-setup" top-1 plans AND the legacy fill-all
                # ("max diverse") plans. Hand-curated selections are never touched.
                notes = str(existing.get("notes") or "")
                is_machine = notes.startswith("Auto-setup") or "max diverse" in notes
                if not (refresh_auto and is_machine):
                    reasons["already_approved"] += 1
                    skipped += 1
                    continue
                reasons["refreshed_auto"] += 1
            setup = await resolve_creative_setup(product_id)
            if setup.get("review_required"):
                reasons["review_required"] += 1
                skipped += 1
                continue
            # Coherent recipe pretick (avatar × scene, camera follows scene) — replaces
            # the old top-1 pick, so every backfilled product gets an arc-spread plan
            # (intro → body → detail → benefit) rather than one shot. Deterministic.
            # honor_saved=False: regenerate the fresh arc-spread, never re-derive the
            # stale top-1 saved plan we are replacing.
            pretick = _recipe.recipes_from_setup(setup, honor_saved=False)["pretick"]
            if not pretick:
                reasons["no_avatar"] += 1
                skipped += 1
                continue
            a = _dedup([r.avatar_code for r in pretick], None)
            s = _dedup([r.scene_template_id for r in pretick], None)
            c = _dedup([r.camera_preset_code for r in pretick], None)
            if dry_run:
                done += 1
                continue
            await save_creative_selection(
                product_id,
                selected_avatar_codes=a,
                selected_scene_template_ids=s,
                selected_camera_preset_codes=c,
                notes="Auto-setup: coherent recipe pretick (camera follows scene)",
            )
            if approve:
                await review_creative_selection(product_id, "APPROVE", "Bulk auto-setup")
            done += 1
        except Exception as exc:  # noqa: BLE001 — report, never abort the batch
            failed += 1
            if len(errors) < 20:
                errors.append({"product_id": product_id, "error": str(exc)[:80]})
    return {
        "targets": len(product_ids),
        "done": done,
        "skipped": skipped,
        "failed": failed,
        "reasons": reasons,
        "errors": errors,
        "approved": approve and not dry_run,
        "applied": not dry_run,
    }


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

    resolved = await _avatar.resolve_product_cluster(product_id, product.get("category"))
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
