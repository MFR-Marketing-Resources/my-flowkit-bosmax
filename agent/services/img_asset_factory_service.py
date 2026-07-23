"""IMG Asset Factory v1 — save an approved, real IMG output into the Library.

This is the governance bridge between a REAL image output and the Creative
Library. It:
  - requires EXACTLY ONE real output source (a finished ``generated_artifact``
    image OR uploaded base64 bytes) — never zero, never both, never fabricated,
  - verifies the bound product and any supplied lineage assets actually exist
    (correct ACTIVE status + semantic role) before writing anything,
  - derives ``semantic_role`` / ``allowed_modes`` / ``engine_slot_eligibility`` /
    rendered-text / poster classification from the LANE (operator cannot mislabel
    a poster as a clean frame),
  - refuses to mark an asset APPROVED while its truth/safety gates are still
    UNVERIFIED.
"""

from __future__ import annotations

import base64
from pathlib import Path
import re

from agent.db import crud
from agent.models.creative_asset import CreativeAssetCreateRequest, CreativeAssetRecord
from agent.models.img_asset_factory import (
    ImgAssetLaneSummary,
    ImgFastlanePresetListResponse,
    ImgFastlanePresetSummary,
    ImgFastlanePromptPreviewRequest,
    ImgFastlanePromptPreviewResponse,
    ImgProviderStatusResponse,
    SaveImgOutputRequest,
)
from agent.services.creative_asset_service import create_creative_asset, get_creative_asset
from agent.services.img_asset_lane_config import (
    derive_asset_governance,
    get_img_asset_lane,
    list_img_asset_lanes,
    validate_img_lane_inputs,
)
from agent.services.product_lock_builder import build_product_lock
from agent.services.creative_direction_service import (
    resolve_creative_direction,
    select_creative_direction_directives,
)


# NOTE: deliberately NOT worded as a "TikTok image". Live leak (owner-reported):
# a frames output rendered social-app UI chrome (like/share icons, a CTA button,
# a template-name chip) plus garbled engine-invented Malay marketing copy — the
# platform word itself invites the engine to draw the platform's interface. The
# spec now states the clean-frame contract positively.
_FASTLANE_OUTPUT_SPEC = (
    "Vertical 9:16 commercial photo frame for social video use. A completely clean "
    "frame: no text, no captions, no buttons, no icons, no interface elements of any kind."
)


IMG_FASTLANE_PRESETS: list[dict[str, object]] = [
    {
        "preset_id": "GENERIC_FRAMES_AVATAR_PRODUCT",
        "label": "Generic Avatar + Product Fastlane",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_COMPOSITE",
        "description": "Database-driven composite frame using product truth plus avatar identity.",
        "required_inputs": ["Database product", "Avatar reference", "Style reference"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["generic", "frames"],
        "negative_rules": [
            "No product drift.",
            "No oversized product-to-hand ratio.",
            "No fake typography or brand swap.",
        ],
    },
    {
        "preset_id": "GENERIC_FRAMES_AVATAR_PRODUCT_SCENE",
        "label": "Generic Avatar + Product + Scene Fastlane",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_SCENE_COMPOSITE",
        "description": "Database-driven frame route with avatar, product truth, and scene context.",
        "required_inputs": [
            "Database product",
            "Avatar reference",
            "Style reference",
            "Scene reference",
        ],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["generic", "frames", "scene"],
        "negative_rules": [
            "No product drift.",
            "No oversized product-to-hand ratio.",
            "No scene overpowering the product truth lock.",
        ],
    },
    {
        "preset_id": "BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF",
        "label": "BOSMAX Serum 3 Ref",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_SCENE_COMPOSITE",
        "description": "Avatar identity lock + context lock + BOSMAX Serum product truth lock.",
        "required_inputs": [
            "Database product",
            "Avatar identity reference",
            "Scene or wardrobe context reference",
            "Style reference",
        ],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["bosmax", "serum", "3ref", "frames"],
        "negative_rules": [
            "No typography drift.",
            "No branding drift.",
            "No product overscale or hand-ratio drift.",
        ],
    },
    {
        "preset_id": "BOSMAX_SERUM_AVATAR_PRODUCT_2REF",
        "label": "BOSMAX Serum 2 Ref",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_COMPOSITE",
        "description": "Avatar identity lock + BOSMAX Serum product truth lock.",
        "required_inputs": ["Database product", "Avatar identity reference"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["bosmax", "serum", "2ref", "frames"],
        "negative_rules": [
            "No matte-black bottle drift.",
            "No pinch-grip distortion.",
            "No label readability tricks that enlarge the product.",
        ],
    },
    {
        "preset_id": "MWCB_WG40_AVATAR_BOTTLE",
        "label": "MWCB WG40 Avatar + Bottle",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_COMPOSITE",
        "description": "Avatar identity lock with exact Minyak Warisan WG40 bottle truth.",
        "required_inputs": ["Database product", "Avatar identity reference", "Style reference"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["wg40", "minyak-warisan", "frames"],
        "negative_rules": [
            "Reject black cap.",
            "Reject roller ball.",
            "Reject oversized or generic bottle drift.",
        ],
    },
    {
        "preset_id": "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS",
        "label": "MWCB WG40 Video Lock",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_COMPOSITE",
        "description": "Frame-safe WG40 continuity lock for reusable video-support imagery.",
        "required_inputs": ["Database product", "Avatar identity reference", "Style reference"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["wg40", "video-lock", "frames"],
        "negative_rules": [
            "Reject cap proportion drift.",
            "Reject oil-color drift.",
            "Reject label cue loss across frames.",
        ],
    },
    {
        # WRNA technique (Phase C): hyper-real floating product render.
        "preset_id": "WRNA_CGI_COMMERCIAL_FLOAT",
        "label": "CGI Commercial Float (WRNA)",
        "route": "INGREDIENTS",
        "lane_id": "PRODUCT_ONLY_HERO",
        "ingredient_role": "PRODUCT_REFERENCE",
        "description": "Ultra-premium hyper-real CGI render: product floating in a category-adaptive conceptual environment, identity truth-locked.",
        "required_inputs": ["Database product"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["wrna", "cgi", "hero", "ingredients"],
        "negative_rules": [
            "No random liquid, unnecessary splash, or generic swirl unless contextually accurate to the product.",
            "No product identity, packaging, proportion, label, or branding drift.",
            "No humans in frame — product is the only hero.",
        ],
    },
    {
        # WRNA technique (Phase C): e-commerce lifestyle with human model.
        "preset_id": "WRNA_ECOM_LIFESTYLE",
        "label": "E-Commerce Lifestyle Model (WRNA)",
        "route": "FRAMES",
        "lane_id": "AVATAR_PRODUCT_SCENE_COMPOSITE",
        "description": "High-converting lifestyle ad: human model interacting naturally with the product, category-adaptive background, real-world scale.",
        "required_inputs": ["Database product"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["wrna", "ecommerce", "lifestyle", "frames"],
        "negative_rules": [
            "No unrealistic product stacking — max 3 units (small 2-3, medium 1-2, large/premium 1).",
            "No oversized or shrunken product relative to real-world hand/body scale.",
            "No irrelevant props; background stays clean, slightly blurred, and category-relevant.",
        ],
    },
    {
        "preset_id": "MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK",
        "label": "MWCB WG40 Product Poster Lock",
        "route": "INGREDIENTS",
        "lane_id": "PRODUCT_POSTER",
        "ingredient_role": "PRODUCT_REFERENCE",
        "description": "Create a WG40 poster-safe terminal asset without losing product truth.",
        "required_inputs": ["Database product"],
        "output_spec": _FASTLANE_OUTPUT_SPEC,
        "tags": ["wg40", "ingredients", "poster"],
        "negative_rules": [
            "Reject bottle overscale.",
            "Reject label redesign.",
            "Reject cap, stopper, or oil-color drift.",
        ],
    },
]


def list_img_fastlane_presets() -> ImgFastlanePresetListResponse:
    items = [ImgFastlanePresetSummary(**item) for item in IMG_FASTLANE_PRESETS]
    return ImgFastlanePresetListResponse(items=items, total=len(items))


def _clean_text(value: object | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _product_display_name(product: dict[str, object] | None) -> str:
    if not product:
        return "Selected product"
    return (
        _clean_text(product.get("product_display_name"))
        or _clean_text(product.get("product_short_name"))
        or _clean_text(product.get("raw_product_title"))
        or _clean_text(product.get("id"))
        or "Selected product"
    )


def _asset_label(asset: object | None) -> str | None:
    if asset is None:
        return None
    display_name = getattr(asset, "display_name", None)
    return _clean_text(display_name) or None


def _resolve_preset(preset_id: str, route: str, ingredient_role: str | None) -> dict[str, object]:
    for preset in IMG_FASTLANE_PRESETS:
        if preset["preset_id"] != preset_id:
            continue
        if str(preset["route"]) != route:
            continue
        preset_role = preset.get("ingredient_role")
        if preset_role and preset_role != ingredient_role:
            continue
        return preset
    raise ValueError("UNKNOWN_FASTLANE_PRESET")


# Clean-frame guard: every fastlane lane EXCEPT the poster lane produces a
# background/composite plate whose typography is layered later by the social-copy
# stage. The image model must therefore draw ZERO baked-in text. This mirrors the
# canonical video compiler's no-text negative block (see test_canonical_prompt_compiler)
# so IMG output obeys the same law. Poster lanes (allows_rendered_text=True) are
# intentionally exempt because their whole purpose is a text-bearing terminal asset.
_CLEAN_FRAME_NEGATIVE_RULES: tuple[str, ...] = (
    "No rendered text, captions, headlines, CTAs, price tags, subtitles, or logos-as-typography baked into the image.",
    "No watermark, sticker, badge, or UI chrome; keep a clean commercial frame so any copy is layered later, never drawn by the image model.",
    # Live leak (owner-reported): the engine drew a social-app interface onto a
    # frames output — like/comment/share icons, a follow button, an order/CTA
    # button, and a template-name chip — plus invented marketing copy. Ban the
    # interface family explicitly, not just 'UI chrome'.
    "No social-media interface elements of any kind: no like/comment/share icons, no follow or order buttons, no username or template/preset name chips, no progress bars, no phone status bars.",
    "No invented marketing copy, slogans, or taglines drawn into the frame — the only readable text anywhere is the text physically printed on the real product label.",
)


# Each profile represents hard instructions already emitted by the selected
# preset. Mode fields may fill only the fields not listed here. Keeping this
# table at the preset boundary makes precedence deterministic and auditable.
_PRESET_CREATIVE_CONSTRAINTS: dict[str, dict[str, object]] = {
    "BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF": {"product_truth": True, "human_presence": True},
    "BOSMAX_SERUM_AVATAR_PRODUCT_2REF": {"product_truth": True, "human_presence": True},
    "MWCB_WG40_AVATAR_BOTTLE": {"product_truth": True, "human_presence": True},
    "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS": {"product_truth": True, "human_presence": True},
    "MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK": {"product_truth": True, "composition": True},
    "WRNA_CGI_COMMERCIAL_FLOAT": {
        "product_truth": True,
        "composition": True,
        "lighting": True,
        "environment": True,
        "human_presence": True,
        "blocked_mode_negative_rules": {"cinematic grade"},
    },
    "WRNA_ECOM_LIFESTYLE": {
        "product_truth": True,
        "composition": True,
        "lighting": True,
        "environment": True,
        "human_presence": True,
    },
}


def _preset_creative_constraints(preset_id: str) -> dict[str, object]:
    """Return the declared hard locks for a known IMG preset."""
    return _PRESET_CREATIVE_CONSTRAINTS.get(preset_id, {})


def _compatible_mode_negative_rules(
    rules: list[str], constraints: dict[str, object]
) -> list[str]:
    blocked = {
        str(rule).strip().lower()
        for rule in constraints.get("blocked_mode_negative_rules", set())
    }
    return [rule for rule in rules if rule.strip().lower() not in blocked]


def _effective_negative_rules(preset: dict[str, object]) -> list[str]:
    """Preset negative rules plus the clean-frame no-text guard for non-poster lanes."""
    rules = [str(rule) for rule in list(preset.get("negative_rules") or [])]
    try:
        allows_text = bool(get_img_asset_lane(str(preset["lane_id"])).get("allows_rendered_text"))
    except Exception:
        allows_text = False
    if not allows_text:
        rules.extend(_CLEAN_FRAME_NEGATIVE_RULES)
    return rules


def _build_engine_prompt(
    *,
    output_spec: str,
    scene_context: str = "",
    reference_map: list[str],
    product_lock_lines: list[str],
    directives: list[str],
    override_notes: str,
    negative_rules: list[str],
) -> str:
    """Clean, engine-agnostic image brief actually sent to the generator.

    Deliberately carries NO internal routing metadata — no ``TEMPLATE PRESET``,
    ``FASTLANE ROUTE``, ``TARGET LANE``, or ``TARGET INGREDIENT ROLE`` lines. Those
    are engineering scaffolding that mean nothing to an image engine and can be
    rendered as literal on-image text. The result is a portable creative brief that
    can be pasted verbatim into Google Flow, ChatGPT Image, or Grok so the SAME
    brief drives a fair cross-engine quality comparison. The labeled operator
    breakdown still lives in ``prompt_text``; this is the payload.
    """
    blocks: list[str] = []
    spec = (output_spec or "").strip()
    if spec:
        blocks.append(spec)
    scene = (scene_context or "").strip()
    if scene:
        # Sets the environment early, before references/product locks (already
        # prefixed "Background: ..." by the scene registry).
        blocks.append(scene)
    refs = [r for r in reference_map if r]
    if refs:
        blocks.append("REFERENCES:\n" + "\n".join(f"- {r}" for r in refs))
    # product lock lines are self-labeled ("PRODUCT IDENTITY LOCK: ...") full
    # sentences, so they stand as their own paragraph without an extra header.
    lock_lines = [line for line in product_lock_lines if line]
    if lock_lines:
        blocks.append("\n".join(lock_lines))
    # Drop operator-facing workflow meta ("System composes the prompt ...") — it is
    # not visual direction and only clutters a portable cross-engine brief.
    comp = [d for d in directives if d and "system composes the prompt" not in d.lower()]
    if comp:
        blocks.append("COMPOSITION:\n" + "\n".join(f"- {d}" for d in comp))
    note = (override_notes or "").strip()
    if note:
        blocks.append("ADDITIONAL DIRECTION:\n- " + note)
    neg = [n for n in negative_rules if n]
    if neg:
        blocks.append("AVOID:\n" + "\n".join(f"- {n}" for n in neg))
    return "\n\n".join(blocks).strip()


def _product_family_flags(product: dict[str, object] | None) -> dict[str, bool]:
    text = _clean_text(
        (product or {}).get("product_display_name")
        or (product or {}).get("product_short_name")
        or (product or {}).get("raw_product_title")
    ).lower()
    return {
        "is_bosmax_serum": "bosmax" in text and ("5 ml" in text or "5ml" in text or "serum" in text or "roll on" in text or "roll-on" in text),
        "is_wg40": "minyak warisan" in text or "cap burung" in text or "wg40" in text,
    }


def _display_name_suggestion(
    preset: dict[str, object],
    product: dict[str, object] | None,
) -> str:
    product_name = _product_display_name(product)
    label = _clean_text(preset.get("label"))
    return f"{product_name} — {label}"


def _make_blockers(
    preset: dict[str, object],
    product: dict[str, object] | None,
    character_label: str | None,
    scene_label: str | None,
    style_label: str | None,
) -> list[str]:
    blockers: list[str] = []
    required_inputs = [str(item) for item in preset.get("required_inputs") or []]
    if "Database product" in required_inputs and product is None:
        blockers.append("PRODUCT_REQUIRED")
    if "Avatar identity reference" in required_inputs and not character_label:
        blockers.append("AVATAR_REFERENCE_REQUIRED")
    if "Avatar reference" in required_inputs and not character_label:
        blockers.append("AVATAR_REFERENCE_REQUIRED")
    if "Style reference" in required_inputs and not style_label:
        blockers.append("STYLE_REFERENCE_REQUIRED")
    if "Scene reference" in required_inputs and not scene_label:
        blockers.append("SCENE_REFERENCE_REQUIRED")
    if "Scene or wardrobe context reference" in required_inputs and not (scene_label or style_label):
        blockers.append("SCENE_OR_STYLE_CONTEXT_REQUIRED")
    return blockers


def _reference_map_lines(
    preset_id: str,
    product: dict[str, object] | None,
    character_label: str | None,
    scene_label: str | None,
    style_label: str | None,
    product_reference_label: str | None,
) -> list[str]:
    lines: list[str] = []
    if preset_id == "BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF":
        lines.append(f"Ref 1 = avatar identity lock: {character_label or 'Select avatar identity reference'}")
        lines.append(
            "Ref 2 = wardrobe / scene / style context: "
            + (scene_label or style_label or "Select scene or style context reference")
        )
        lines.append(f"Ref 3 = product truth: {_product_display_name(product)}")
        return lines
    if preset_id == "BOSMAX_SERUM_AVATAR_PRODUCT_2REF":
        lines.append(f"Ref 1 = avatar identity lock: {character_label or 'Select avatar identity reference'}")
        lines.append(f"Ref 2 = BOSMAX Herbs roll-on product truth: {_product_display_name(product)}")
        return lines
    if preset_id in {
        "MWCB_WG40_AVATAR_BOTTLE",
        "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS",
        "MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK",
    }:
        if character_label:
            lines.append(f"Avatar identity lock: {character_label}")
        lines.append(f"Exact bottle truth: {_product_display_name(product)}")
        return lines
    if character_label:
        lines.append(f"Existing avatar reference: {character_label}")
    if scene_label:
        lines.append(f"Existing scene reference: {scene_label}")
    if style_label:
        lines.append(f"Existing style reference: {style_label}")
    if product_reference_label:
        lines.append(f"Existing product reference: {product_reference_label}")
    if product:
        lines.append(f"Database product truth: {_product_display_name(product)}")
    return lines


def _product_lock_lines(product: dict[str, object] | None, *, is_video: bool) -> list[str]:
    if not product:
        return []
    lock = build_product_lock(
        dict(product),
        is_video=is_video,
        has_product_reference=bool(
            product.get("media_id") or product.get("image_url") or product.get("local_image_path")
        ),
    )
    return [
        line
        for line in (
            lock["identity_lock"],
            lock["geometry_lock"],
            lock["scale_lock"],
            lock["reference_lock"],
            lock["frame_persistence"],
            lock["negative_morph"],
            # All-out product-truth hardening (owner-directed): absolute
            # no-modification clause + scale anchor / legibility decoupling +
            # object-in-hand authority + category grip/handling.
            lock["no_modification_lock"],
            lock["scale_anchor_lock"],
            lock["object_authority_lock"],
            lock["handling_lock"],
        )
        if line
    ]


def _preset_directives(
    preset_id: str,
    product: dict[str, object] | None,
) -> list[str]:
    product_name = _product_display_name(product)
    directives: list[str] = []
    if preset_id == "BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF":
        directives.extend(
            [
                "Typography and branding lock: preserve BOSMAX HERBS identity, white typography, and label truth exactly as the real product appears.",
                "Spatial math lock: preserve product-to-hand ratio, air gap, product scale, and natural handheld depth so the bottle never enlarges for readability.",
                f"Render {product_name} as a vertical TikTok 9:16 commercial image with presenter identity locked to the selected avatar reference.",
            ]
        )
    elif preset_id == "BOSMAX_SERUM_AVATAR_PRODUCT_2REF":
        directives.extend(
            [
                "Enforce matte black cylindrical micro-bottle truth, white typography, lip balm size, and pinch grip label readability without enlarging the product.",
                "Reject perfume, spray, supplement, skincare, or generic bottle drift.",
            ]
        )
    elif preset_id == "MWCB_WG40_AVATAR_BOTTLE":
        directives.extend(
            [
                "Enforce exact compact rectangular clear flint glass bottle with red ribbed screw cap, hidden stopper, emerald herbal oil, and cream / deep green / gold label.",
                "Preserve bottle proportions and handheld scale with no black cap, no roller ball, and no oversized bottle drift.",
            ]
        )
    elif preset_id == "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS":
        directives.extend(
            [
                "Video continuity lock: same 25ml rectangular clear flint glass bottle, red ribbed cap, hidden stopper, emerald herbal green oil, dark green + cream + gold label, and bird on leafy branch.",
                "Preserve printed label cues 'Sejak 1958' and 'Petua Turun Temurun' with stable silhouette, cap proportion, oil color, and scale read across frames.",
            ]
        )
    elif preset_id == "MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK":
        directives.extend(
            [
                "Poster lock: preserve WG40 bottle truth while allowing terminal poster composition only after product identity, label, and scale remain exact.",
                "Rendered poster text may decorate around the bottle but must never replace or distort the real product label.",
            ]
        )
    elif preset_id == "WRNA_CGI_COMMERCIAL_FLOAT":
        from agent.services.img_category_adapt_service import resolve_category_adapt

        adapt = resolve_category_adapt(product)
        directives.extend(
            [
                f"Ultra-premium hyper-realistic CGI render of {product_name}, heroically floating in a high-end conceptual environment designed for its real usage context, while strictly preserving the exact product identity, packaging, proportions, material, label, and branding with zero distortion.",
                f"Surround the product only with purpose-driven floating elements that reinforce its function or sensory experience: {adapt['float_elements']}.",
                "Bold, clean, well-balanced composition with the product as the central hero; dramatic cinematic lighting, controlled highlights and shadows, premium reflections, soft depth of field, ultra-sharp detailing — slightly surreal yet believable for a real premium campaign.",
            ]
        )
    elif preset_id == "WRNA_ECOM_LIFESTYLE":
        from agent.services.img_category_adapt_service import resolve_category_adapt

        adapt = resolve_category_adapt(product)
        directives.extend(
            [
                f"High-converting commercial lifestyle advertisement of {product_name}: {adapt['model']} interacting naturally with the product, chest-up framing, natural expression.",
                f"Background: {adapt['background']} — clean, slightly blurred, category-relevant; extract the product's dominant colour and blend it naturally into the environment while keeping contrast.",
                "Close-up 85mm portrait look with shallow depth of field: product carries 60-70 percent of the visual focus at real-world scale relative to human hands and body; packaging stays accurate and readable; realistic quantity only.",
                "Bright commercial lighting with soft shadows that enhance product texture; ultra-realistic high-resolution commercial brand quality.",
            ]
        )
    else:
        directives.extend(
            [
                f"Use {_product_display_name(product)} as database-driven product truth when present.",
                "System composes the prompt from selected references and template preset; operator notes are optional and never mandatory.",
            ]
        )
    return directives


async def compile_img_fastlane_prompt_preview(
    request: ImgFastlanePromptPreviewRequest,
) -> ImgFastlanePromptPreviewResponse:
    preset = _resolve_preset(request.preset_id, request.route, request.ingredient_role)
    product = None
    if request.product_id:
        found_product = await crud.get_product(request.product_id)
        if found_product is None:
            raise ValueError("PRODUCT_NOT_FOUND")
        product = dict(found_product)
    creative_direction = (
        resolve_creative_direction(request.creative_mode, product=product)
        if request.creative_mode is not None
        else None
    )

    selected_character = (
        await get_creative_asset(request.character_reference_asset_id)
        if request.character_reference_asset_id
        else None
    )
    selected_scene = (
        await get_creative_asset(request.scene_reference_asset_id)
        if request.scene_reference_asset_id
        else None
    )
    selected_style = (
        await get_creative_asset(request.style_reference_asset_id)
        if request.style_reference_asset_id
        else None
    )
    selected_product_reference = (
        await get_creative_asset(request.product_reference_asset_id)
        if request.product_reference_asset_id
        else None
    )

    character_label = _asset_label(selected_character)
    scene_label = _asset_label(selected_scene)
    style_label = _asset_label(selected_style)
    product_reference_label = _asset_label(selected_product_reference)
    blockers = _make_blockers(
        preset,
        product,
        character_label,
        scene_label,
        style_label,
    )

    warnings: list[str] = []
    flags = _product_family_flags(product)
    if request.preset_id.startswith("BOSMAX_") and not flags["is_bosmax_serum"]:
        warnings.append("PRESET_PRODUCT_FAMILY_MISMATCH_BOSMAX_SERUM")
    if request.preset_id.startswith("MWCB_WG40") and not flags["is_wg40"]:
        warnings.append("PRESET_PRODUCT_FAMILY_MISMATCH_WG40")
    if request.route == "INGREDIENTS" and request.ingredient_role == "PRODUCT_REFERENCE" and not request.product_id:
        warnings.append("PRODUCT_CONTEXT_RECOMMENDED_FOR_PRODUCT_LOCK")

    # Optional scene-context injection: any of the 20 seeded registry scenes is
    # usable as environment TEXT immediately, without first generating a scene
    # image. Independent of scene_reference_asset_id (the optional image reference).
    scene_context_text = ""
    scene_context_name = ""
    if request.scene_context_code and _clean_text(request.scene_context_code):
        try:
            from agent.services import scene_context_registry
            _scene_profile = scene_context_registry.resolve_scene_context(
                _clean_text(request.scene_context_code))
            scene_context_text = scene_context_registry.scene_background_prose(_scene_profile)
            scene_context_name = str(_scene_profile.get("scene_name") or "")
        except Exception:
            warnings.append("SCENE_CONTEXT_NOT_FOUND")

    prompt_lines: list[str] = [
        f"TEMPLATE PRESET: {preset['preset_id']}",
        f"FASTLANE ROUTE: {request.route}",
        f"TARGET LANE: {preset['lane_id']}",
        f"OUTPUT SPEC: {preset['output_spec']}",
    ]
    if request.ingredient_role:
        prompt_lines.append(f"TARGET INGREDIENT ROLE: {request.ingredient_role}")
    prompt_lines.append("")
    prompt_lines.append("REFERENCE MAP:")
    prompt_lines.extend(
        f"- {line}"
        for line in _reference_map_lines(
            request.preset_id,
            product,
            character_label,
            scene_label,
            style_label,
            product_reference_label,
        )
    )
    prompt_lines.append("")
    prompt_lines.append("PRODUCT TRUTH LOCK:")
    product_lock_lines = _product_lock_lines(
        product,
        is_video=request.route == "FRAMES"
        or request.preset_id == "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS",
    )
    if product_lock_lines:
        prompt_lines.extend(f"- {line}" for line in product_lock_lines if line)
    else:
        prompt_lines.append("- No product selected. Select a product for product-truth locking.")
    prompt_lines.append("")
    preset_directives = _preset_directives(request.preset_id, product)
    constraints = _preset_creative_constraints(request.preset_id)
    prompt_lines.append("COMPOSITION DIRECTIVES:")
    prompt_lines.extend(f"- {line}" for line in preset_directives)
    creative_directives: list[str] = []
    if creative_direction is not None:
        creative_directives = [
            "Higher-authority conflicts suppressed before this mode is applied.",
            *(
                f"{label}: {value}"
                for label, value in select_creative_direction_directives(
                    creative_direction,
                    product_truth_locked=bool(constraints.get("product_truth")),
                    identity_reference_locked=bool(request.character_reference_asset_id),
                    composition_constraint_locked=bool(constraints.get("composition")),
                    lighting_constraint_locked=bool(constraints.get("lighting")),
                    environment_constraint_locked=bool(constraints.get("environment")),
                    human_presence_constraint_locked=bool(constraints.get("human_presence")),
                )
            ),
        ]
        prompt_lines.append("")
        prompt_lines.append("GOVERNED CREATIVE DIRECTION:")
        prompt_lines.extend(f"- {line}" for line in creative_directives)
    if scene_context_text:
        prompt_lines.append("")
        prompt_lines.append("SCENE CONTEXT (background):")
        _scene_label = f"{scene_context_name}: " if scene_context_name else ""
        prompt_lines.append(f"- {_scene_label}{scene_context_text}")
    if request.advanced_override_notes and _clean_text(request.advanced_override_notes):
        prompt_lines.append("")
        prompt_lines.append("ADVANCED OVERRIDE NOTES (optional):")
        prompt_lines.append(f"- {_clean_text(request.advanced_override_notes)}")
    effective_negative_rules = _effective_negative_rules(preset)
    if creative_direction is not None:
        effective_negative_rules = [
            *effective_negative_rules,
            *_compatible_mode_negative_rules(
                creative_direction.negative_rules, constraints
            ),
        ]
    prompt_lines.append("")
    prompt_lines.append("NEGATIVE RULES:")
    prompt_lines.extend(f"- {rule}" for rule in effective_negative_rules)

    # Clean, portable brief actually sent to the generator (no internal routing
    # ids) — reuses the same substantive pieces as the labeled breakdown above.
    engine_prompt_text = _build_engine_prompt(
        output_spec=str(preset["output_spec"]),
        scene_context=scene_context_text,
        reference_map=_reference_map_lines(
            request.preset_id,
            product,
            character_label,
            scene_label,
            style_label,
            product_reference_label,
        ),
        product_lock_lines=product_lock_lines,
        directives=[*preset_directives, *creative_directives],
        override_notes=_clean_text(request.advanced_override_notes)
        if request.advanced_override_notes
        else "",
        negative_rules=effective_negative_rules,
    )

    return ImgFastlanePromptPreviewResponse(
        preset_id=str(preset["preset_id"]),
        route=request.route,
        ingredient_role=request.ingredient_role,
        lane_id=str(preset["lane_id"]),
        prompt_text="\n".join(prompt_lines).strip(),
        engine_prompt_text=engine_prompt_text,
        display_name_suggestion=_display_name_suggestion(preset, product),
        blockers=blockers,
        warnings=warnings,
        output_spec=str(preset["output_spec"]),
        negative_rules=effective_negative_rules,
        reference_map=_reference_map_lines(
            request.preset_id,
            product,
            character_label,
            scene_label,
            style_label,
            product_reference_label,
        ),
        creative_direction=(
            {
                "mode": creative_direction.mode.value,
                "authority_version": creative_direction.authority_version,
                "representation_policy_version": creative_direction.representation_policy_version,
            }
            if creative_direction is not None else {}
        ),
    )


def list_img_lane_summaries() -> list[ImgAssetLaneSummary]:
    return [ImgAssetLaneSummary(**lane) for lane in list_img_asset_lanes()]


def get_img_provider_status() -> ImgProviderStatusResponse:
    """Honest report of the IMG generation runtime boundary.

    This PR ships and tests the save-to-library governance ONLY. Image
    GENERATION itself runs through the pre-existing API-first lane
    (``POST /api/flow/execute-flow-job`` with ``mode=IMG``), which is NOT
    re-proven with live/runtime evidence in this PR — hence the deliberately
    conservative state.
    """
    return ImgProviderStatusResponse(
        provider_state="SAVE_TO_LIBRARY_READY_GENERATION_RUNTIME_EXTERNAL",
        detail=(
            "Save-to-library governance is ready and unit-tested here. Image "
            "generation runs through the external pre-existing API-first lane and "
            "is NOT re-verified with runtime evidence in this PR. The factory only "
            "accepts REAL outputs (a generated_artifact image or an upload)."
        ),
        generation_endpoint="/api/flow/execute-flow-job",
        extra={"mode": "IMG", "save_endpoint": "/api/img-factory/save"},
    )


def build_image_gen_settings() -> dict:
    """Single source of truth for image-generation default settings shared by
    EVERY image-gen surface (IMG Fastlane, Image Gen, IMG Cockpit, Avatar
    Registry, and the Poster Builder Flow Mirror / Creative Cockpit): aspect
    ratios, counts, and the image-model list (from models.json). A model is
    ``pending`` when its Google internal id is not yet configured — the UI still
    lists it, but generation fails closed until the id is set."""
    from agent.config import IMAGE_MODELS

    labels = {
        "NANO_BANANA_PRO": "Nano Banana Pro",
        "NANO_BANANA_2": "Nano Banana 2",
        "NANO_BANANA_2_LITE": "Nano Banana 2 Lite",
    }
    models = [
        {
            "key": key,
            "label": labels.get(key, key.replace("_", " ").title()),
            "pending": (not str(internal).strip()) or "PENDING" in str(internal).upper(),
        }
        for key, internal in IMAGE_MODELS.items()
    ]
    return {
        "models": models,
        "default_model": "Nano Banana 2",
        "aspect_options": ["9:16", "1:1", "16:9", "4:3", "3:4"],
        "default_aspect": "9:16",
        "count_options": [1, 2, 3, 4],
        "default_count": 1,
    }


async def _resolve_real_output(
    request: SaveImgOutputRequest,
) -> tuple[str, str | None, str]:
    """Return ``(image_base64, file_name, source_type)`` from EXACTLY ONE real
    output source. Fail closed on zero or on more-than-one source."""
    has_artifact = bool(request.generated_artifact_media_id)
    has_base64 = bool(request.image_base64)
    if has_artifact and has_base64:
        raise ValueError("MULTIPLE_OUTPUT_SOURCES_NOT_ALLOWED")
    if not has_artifact and not has_base64:
        raise ValueError("NO_REAL_OUTPUT_SOURCE")

    if has_artifact:
        artifact = await crud.get_generated_artifact(request.generated_artifact_media_id)
        if not artifact:
            raise ValueError("GENERATED_ARTIFACT_NOT_FOUND")
        if str(artifact.get("artifact_kind")) != "image":
            raise ValueError("ARTIFACT_NOT_AN_IMAGE")
        local_path = artifact.get("local_path")
        if not local_path or not Path(local_path).exists():
            raise ValueError("ARTIFACT_FILE_MISSING")
        raw = Path(local_path).read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return encoded, request.file_name or Path(local_path).name, "GENERATED_IMAGE"

    return request.image_base64, request.file_name, "UPLOAD"


async def _lineage_blocker(
    asset_id: str | None,
    *,
    expected_role: str,
    blocker: str,
) -> str | None:
    """Return ``blocker`` when a supplied lineage asset is missing / archived /
    the wrong semantic role; ``None`` when absent or valid."""
    if not asset_id:
        return None
    asset = await get_creative_asset(asset_id)
    if asset is None or asset.status != "ACTIVE" or asset.semantic_role != expected_role:
        return blocker
    return None


async def save_img_output_to_library(request: SaveImgOutputRequest) -> CreativeAssetRecord:
    # Lane must exist (fail closed on unknown lane).
    governance = derive_asset_governance(request.lane_id)
    lane = get_img_asset_lane(request.lane_id)

    # Lane input requirements (e.g. product-truth lanes require a product_id).
    input_blockers = validate_img_lane_inputs(
        request.lane_id,
        product_id=request.product_id,
        character_reference_asset_id=request.source_character_asset_id,
        scene_reference_asset_id=request.source_scene_asset_id,
        style_reference_asset_id=request.source_style_asset_id,
    )
    if input_blockers:
        raise ValueError("IMG_LANE_INPUT_BLOCKED:" + ",".join(input_blockers))

    # The bound product must actually exist — never bottom out in a DB FK 500.
    product: dict[str, object] | None = None
    if request.product_id:
        found_product = await crud.get_product(request.product_id)
        if found_product is None:
            raise ValueError("PRODUCT_NOT_FOUND")
        product = dict(found_product)
    if lane["requires_product_id"]:
        if product is None:
            raise ValueError("PRODUCT_NOT_FOUND")

    # Supplied lineage assets must exist, be ACTIVE, and carry the right role.
    lineage_blockers = [
        b
        for b in (
            await _lineage_blocker(
                request.source_character_asset_id,
                expected_role="CHARACTER_REFERENCE",
                blocker="SOURCE_CHARACTER_ASSET_INVALID",
            ),
            await _lineage_blocker(
                request.source_scene_asset_id,
                expected_role="SCENE_CONTEXT_REFERENCE",
                blocker="SOURCE_SCENE_ASSET_INVALID",
            ),
            await _lineage_blocker(
                request.source_style_asset_id,
                expected_role="STYLE_REFERENCE",
                blocker="SOURCE_STYLE_ASSET_INVALID",
            ),
        )
        if b is not None
    ]
    if lineage_blockers:
        raise ValueError(",".join(lineage_blockers))

    image_base64, file_name, source_type = await _resolve_real_output(request)

    # Product truth is derived, not operator-set: PRESERVED only when a product
    # is actually bound to the asset; otherwise NOT_APPLICABLE.
    product_truth_status = "PRESERVED" if request.product_id else "NOT_APPLICABLE"
    identity_lock_status = request.identity_lock_status or "UNVERIFIED"
    scale_truth_status = request.scale_truth_status or "UNVERIFIED"
    claim_safety_status = request.claim_safety_status or "UNVERIFIED"

    # An asset may be APPROVED only when EVERY truth/safety gate explicitly PASSes.
    # Any UNVERIFIED or FAIL status blocks approval — an APPROVED asset is later
    # the only kind reusable downstream (validate_selectable_asset require_approved).
    if request.review_status == "APPROVED" and not all(
        status == "PASS"
        for status in (identity_lock_status, scale_truth_status, claim_safety_status)
    ):
        raise ValueError("APPROVAL_REQUIRES_ALL_TRUTH_PASS")

    direction = (
        resolve_creative_direction(request.creative_mode, product=product)
        if request.creative_mode is not None
        else None
    )
    create_request = CreativeAssetCreateRequest(
        semantic_role=governance["semantic_role"],  # type: ignore[arg-type]
        display_name=request.display_name,
        description=request.description,
        source_type=source_type,  # type: ignore[arg-type]
        storage_kind="LOCAL_FILE",
        product_id=request.product_id,
        category=request.category,
        silo=request.silo,
        product_type=request.product_type,
        allowed_modes=governance["allowed_modes"],
        engine_slot_eligibility=governance["engine_slot_eligibility"],
        source_prompt_fingerprint=request.source_prompt_fingerprint,
        source_workspace_execution_package_id=request.source_workspace_execution_package_id,
        source_prompt_package_snapshot_id=request.source_prompt_package_snapshot_id,
        asset_subtype=governance["asset_subtype"],
        generation_recipe_id=governance["generation_recipe_id"],
        source_character_asset_id=request.source_character_asset_id,
        source_scene_asset_id=request.source_scene_asset_id,
        source_style_asset_id=request.source_style_asset_id,
        contains_rendered_text=governance["contains_rendered_text"],
        approved_for_video_support=governance["approved_for_video_support"],
        approved_for_poster=governance["approved_for_poster"],
        product_truth_status=product_truth_status,
        identity_lock_status=identity_lock_status,
        scale_truth_status=scale_truth_status,
        claim_safety_status=claim_safety_status,
        review_status=request.review_status,
        mode_a_metadata_handoff=(
            {
                "creative_direction": {
                    "mode": direction.mode.value,
                    "authority_version": direction.authority_version,
                    "representation_policy_version": direction.representation_policy_version,
                }
            }
            if direction is not None
            else None
        ),
        image_base64=image_base64,
        file_name=file_name,
    )
    return await create_creative_asset(create_request)
