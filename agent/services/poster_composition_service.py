"""Canonical deterministic professional-poster composition resolver (WRNA Round 3).

ONE structured Poster Composition Plan per governed creative mode. Higher
authorities (Product Truth -> approved identity -> operator hard selections ->
recipe constraints) are applied OVER the WRNA mode defaults: only conflicting
mode properties are suppressed (with a stable provenance record); compatible
mode characteristics are retained. The plan is consumed by the final poster
prompt, preserved through the render manifest, and displayed in Poster Guided.

Constraint assembly (`build_composition_constraints`) is the wiring layer the
production callers use to translate the REAL resolved authorities (Product
Truth computed profile, Creative Direction representation policy, operator
selections, recipe template contract, poster copy-quality report) into the
canonical constraint contract. It is NOT a second resolver — resolution happens
only in `resolve_poster_composition`.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

COMPOSITION_SCHEMA_VERSION = "wrna-poster-composition-v1"
CONSTRAINT_SCHEMA_VERSION = "wrna-composition-constraints-v1"

# Authority levels, lowest first. Application order == list order, so a later
# (higher) authority deterministically overrides an earlier one and the
# suppression record names the authority that won.
AUTHORITY_WRNA_MODE = "WRNA_MODE"
AUTHORITY_RECIPE = "RECIPE"
AUTHORITY_OPERATOR = "OPERATOR"
AUTHORITY_APPROVED_IDENTITY = "APPROVED_IDENTITY"
AUTHORITY_PRODUCT_TRUTH = "PRODUCT_TRUTH"

# Poster copy limits mirrored from the poster copy SSOT (POSTER_COPY_LIMITS in
# poster_prompt_draft_service — not imported to avoid a service cycle; the
# draft service validates lengths upstream, these thresholds only classify
# composition-density warnings).
_HOOK_DENSITY_LIMIT = 48
_CTA_DENSITY_LIMIT = 24
_USP_COUNT_LIMIT = 3
_CTA_BURIED_SUPPORT_CHARS = 120
_HOOK_CHARS_PER_LINE = 18
_CTA_CHARS_PER_LINE = 20
_MAX_HOOK_LINES = 3
_MAX_CTA_LINES = 2
# A recipe product band spanning more than this % of the frame width leaves no
# room for a side copy column — copy must stack above/below the product band.
_BAND_SPAN_STACK_THRESHOLD = 60.0

# Poster copy-quality authority codes (poster_copy_quality_service) that the
# composition plan translates into its frozen governance outcomes. Reused, not
# re-implemented: the caller passes the real quality report via constraints.
_CHIP_QUALITY_CODES = ("TOO_MANY_CHIPS", "CHIP_TOO_LONG")
_CLAIM_BADGE_BLOCK_CODES = (
    "MEDICAL_RELIEF_CLAIM",
    "CHILD_HEALTH_CLAIM",
    "OFFER_PRICE_CLAIM_UNSUPPORTED",
)

_RECIPE_HUMAN_HAND_TOKENS = ("in-hand", "hand", "grip", "tangan", "dipegang")

_HUMAN_ABSENT_VALUES = {"prohibited", "none", "product_only", "product-forward"}


class PosterCompositionError(ValueError):
    """Fail-closed resolver error (unsupported mode / invalid contract)."""


# ── Five structurally distinct mode profiles ─────────────────────────────────
# Uniqueness lives in the independent structured dimensions below — NEVER in
# the descriptive `profile` id. Each mode differs across several of: anchor,
# dominance, reading order, human policy, face-safe policy, copy side, hook/
# USP/CTA treatment, typography intensity, background complexity, lighting,
# prop density, negative-space strategy and label style.
_PROFILES: dict[str, dict[str, Any]] = {
    "PGC_CAMPAIGN": {
        "profile": "campaign_product_hero_v1",
        "anchor": "middle-right",
        "dominance": "70-80%",
        "human_presence": "optional",
        "face_safe_rule": "upper-right protected when present",
        "copy_side": "left",
        "hook_treatment": "bold campaign headline",
        "usp_treatment": "two tight proof lines",
        "cta_treatment": "high-contrast campaign button",
        "typography_intensity": "high-impact display",
        "background_complexity": "controlled cinematic gradient",
        "lighting": "campaign key light",
        "prop_density": "minimal hero props",
        "negative_space": "left copy field",
        "label_style": "label forward and fully readable",
        "reading_order": ["product", "hook", "cta", "usp"],
    },
    "UGC_AUTHENTIC": {
        "profile": "authentic_routine_v1",
        "anchor": "lower-right",
        "dominance": "55-65%",
        "human_presence": "allowed",
        "face_safe_rule": "upper-right protected when present",
        "copy_side": "left",
        "hook_treatment": "simple conversational headline",
        "usp_treatment": "one practical proof line",
        "cta_treatment": "soft but discoverable action",
        "typography_intensity": "casual handwritten-adjacent",
        "background_complexity": "believable everyday context",
        "lighting": "ambient practical light",
        "prop_density": "routine-use props only",
        "negative_space": "natural wall or counter field",
        "label_style": "natural label angle, may sit off-axis",
        "reading_order": ["human_product", "hook", "cta", "usp"],
    },
    "MODEL_AMBASSADOR": {
        "profile": "ambassador_split_v1",
        "anchor": "lower-left",
        "dominance": "55-65%",
        "human_presence": "required",
        "face_safe_rule": "upper-left exclusion zone",
        "copy_side": "right",
        "hook_treatment": "headline outside the face-safe zone",
        "usp_treatment": "restrained proof lines",
        "cta_treatment": "polished advertising action",
        "typography_intensity": "polished advertising serif-sans mix",
        "background_complexity": "polished editorial backdrop",
        "lighting": "polished advertising light",
        "prop_density": "one supporting prop",
        "negative_space": "right copy column",
        "label_style": "label forward and fully readable",
        "reading_order": ["model_product", "hook", "cta", "usp"],
    },
    "CLEAN_STUDIO_CATALOGUE": {
        "profile": "studio_catalogue_v1",
        "anchor": "middle-center",
        "dominance": "70-80%",
        "human_presence": "prohibited",
        "face_safe_rule": "not applicable",
        "copy_side": "stacked",
        "hook_treatment": "restrained high-contrast headline",
        "usp_treatment": "single concise support line",
        "cta_treatment": "minimal catalogue action",
        "typography_intensity": "minimal precise grotesque",
        "background_complexity": "clean seamless studio",
        "lighting": "controlled studio light",
        "prop_density": "no props",
        "negative_space": "generous upper and lower field",
        "label_style": "label perfectly frontal",
        "reading_order": ["product", "hook", "cta", "usp"],
    },
    "LIFESTYLE_EDITORIAL": {
        "profile": "editorial_context_v1",
        "anchor": "lower-right",
        "dominance": "60-70%",
        "human_presence": "allowed",
        "face_safe_rule": "upper-third protected when present",
        "copy_side": "left",
        "hook_treatment": "curated editorial headline",
        "usp_treatment": "editorial support line",
        "cta_treatment": "subtle premium action",
        "typography_intensity": "refined editorial serif",
        "background_complexity": "aspirational contextual setting",
        "lighting": "refined natural light",
        "prop_density": "curated contextual props",
        "negative_space": "editorial left column",
        "label_style": "natural label angle, may sit off-axis",
        "reading_order": ["product", "hook", "usp", "cta"],
    },
}

SUPPORTED_COMPOSITION_MODES: tuple[str, ...] = tuple(sorted(_PROFILES))

# Copy-zone layout per copy side. Deterministic mapping — the zones move as ONE
# structural unit when a higher authority relocates the copy side.
_COPY_ZONES: dict[str, dict[str, str]] = {
    "left": {
        "hook_zone": "upper-left",
        "subhook_zone": "upper-left below hook",
        "usp_zone": "left-middle",
        "cta_zone": "lower-left",
    },
    "right": {
        "hook_zone": "upper-right",
        "subhook_zone": "upper-right below hook",
        "usp_zone": "right-middle",
        "cta_zone": "lower-right",
    },
    "stacked": {
        "hook_zone": "top-center",
        "subhook_zone": "top-center below hook",
        "usp_zone": "lower-center band",
        "cta_zone": "bottom-center",
    },
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _derive_anchor_from_safe_region(safe_region: dict[str, Any]) -> str:
    """Deterministic anchor from the recipe product-safe region geometry."""
    x = float(safe_region["x"])
    y = float(safe_region["y"])
    w = float(safe_region["w"])
    h = float(safe_region["h"])
    cx = x + w / 2.0
    cy = y + h / 2.0
    horizontal = "left" if cx < 40 else "right" if cx > 60 else "center"
    vertical = "upper" if cy < 40 else "lower" if cy > 60 else "middle"
    return f"{vertical}-{horizontal}"


def build_composition_constraints(
    *,
    product: dict[str, Any] | None = None,
    truth_profile: Any = None,
    creative_direction: Any = None,
    operator_human_presence: str = "",
    recipe: Any = None,
    template_contract: dict[str, Any] | None = None,
    copy_quality_report: Any = None,
) -> dict[str, Any]:
    """Assemble the canonical constraint contract from the REAL authorities.

    Every section is included only when its authority is actually present, so
    `provenance.active_locks` on the resolved plan reflects genuine wiring —
    never symbolic placeholders.
    """
    constraints: dict[str, Any] = {"constraint_schema": CONSTRAINT_SCHEMA_VERSION}

    if truth_profile is not None or product:
        product = product or {}
        display = _norm(product.get("product_display_name")) or _norm(
            product.get("raw_product_title")
        )
        claim_gate = _norm(
            getattr(
                getattr(truth_profile, "final_output_preview", None), "claim_gate", ""
            )
        ) or _norm(getattr(creative_direction, "product_truth_claim_gate", ""))
        constraints["product_truth"] = {
            "display_name": display,
            "claim_gate": claim_gate or "UNKNOWN",
            # The poster product-truth contract: identity, geometry, label,
            # quantity/volume and scale direction are locked to the reference.
            "locks": [
                "identity",
                "geometry",
                "label_visibility",
                "quantity_volume",
                "scale_direction",
            ],
        }

    if creative_direction is not None:
        policy = _norm(getattr(creative_direction, "human_presence_policy", ""))
        constraints["identity"] = {
            "approved_identity_required": "approved_avatar" in policy,
            "policy_version": _norm(
                getattr(creative_direction, "representation_policy_version", "")
            ),
        }

    operator_human_presence = _norm(operator_human_presence)
    if operator_human_presence:
        constraints["operator"] = {"human_presence": operator_human_presence}

    if recipe is not None or template_contract:
        recipe_block: dict[str, Any] = {
            "recipe_id": _norm(getattr(recipe, "recipe_id", "")),
        }
        placement = _norm(getattr(recipe, "product_placement", "")).lower()
        recipe_block["requires_human_hand"] = any(
            token in placement for token in _RECIPE_HUMAN_HAND_TOKENS
        )
        if template_contract and template_contract.get("product_safe_region"):
            safe = template_contract["product_safe_region"]
            recipe_block["product_safe_region"] = {
                "x": float(safe["x"]),
                "y": float(safe["y"]),
                "w": float(safe["w"]),
                "h": float(safe["h"]),
            }
            recipe_block["product_anchor"] = _derive_anchor_from_safe_region(safe)
            recipe_block["band_span_pct"] = float(safe["w"])
        constraints["recipe"] = recipe_block

    if copy_quality_report is not None:
        findings = getattr(copy_quality_report, "findings", []) or []
        constraints["copy_quality"] = {
            "block_codes": sorted(
                {f.code for f in findings if getattr(f, "severity", "") == "BLOCK"}
            ),
            "warn_codes": sorted(
                {f.code for f in findings if getattr(f, "severity", "") == "WARN"}
            ),
        }

    return constraints


def _copy_governance(
    fields: dict[str, str], constraints: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Deterministic copy/quality governance — fixed evaluation order.

    Warnings surface composition risks; blockers mark plans that must not ship
    (claim-as-badge). Quality-authority findings arrive via constraints so the
    established poster-copy validator is reused, never duplicated.
    """
    warnings: list[str] = []
    blockers: list[str] = []
    hook = _norm(fields.get("hook"))
    subhook = _norm(fields.get("subhook"))
    cta = _norm(fields.get("cta"))
    usps = [
        _norm(fields.get(name))
        for name in ("usp_1", "usp_2", "usp_3", "usp_4")
        if _norm(fields.get(name))
    ]

    if len(hook) > _HOOK_DENSITY_LIMIT:
        warnings.append("HOOK_DENSITY_EXCEEDS_COMPOSITION_LIMIT")
    if len(cta) > _CTA_DENSITY_LIMIT:
        warnings.append("CTA_DENSITY_EXCEEDS_COMPOSITION_LIMIT")
    if len(usps) > _USP_COUNT_LIMIT:
        warnings.append("USP_COUNT_EXCEEDS_COMPOSITION_LIMIT")

    copies = [
        v.strip().lower()
        for v in fields.values()
        if isinstance(v, str) and v.strip()
    ]
    if len(copies) != len(set(copies)):
        warnings.append("DUPLICATE_COPY_DETECTED")

    support_chars = len(subhook) + sum(len(u) for u in usps)
    if subhook and len(usps) >= 3 and support_chars > _CTA_BURIED_SUPPORT_CHARS:
        warnings.append("CTA_BURIED_BY_LOWER_PRIORITY_COPY")

    if hook and math.ceil(len(hook) / _HOOK_CHARS_PER_LINE) > _MAX_HOOK_LINES:
        warnings.append("UNSAFE_EDGE_PLACEMENT")
    elif cta and math.ceil(len(cta) / _CTA_CHARS_PER_LINE) > _MAX_CTA_LINES:
        warnings.append("UNSAFE_EDGE_PLACEMENT")

    quality = constraints.get("copy_quality") or {}
    quality_codes = set(quality.get("warn_codes") or []) | set(
        quality.get("block_codes") or []
    )
    if quality_codes & set(_CHIP_QUALITY_CODES):
        warnings.append("CHIP_BADGE_TREATMENT_UNCONTROLLED")
    if set(quality.get("block_codes") or []) & set(_CLAIM_BADGE_BLOCK_CODES):
        blockers.append("UNSUPPORTED_CLAIM_BADGE")

    return warnings, blockers


def _signature(plan: dict[str, Any]) -> str:
    """Stable full-plan signature over a canonical serialization (everything
    except the signature itself)."""
    stable = {k: v for k, v in plan.items() if k != "signature"}
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_poster_composition(
    *,
    creative_direction: Any,
    recipe_id: str,
    frame_ratio: str,
    fields: dict[str, str],
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the canonical composition plan for one governed creative mode.

    Legacy no-mode callers receive {} (their prompt path stays byte-identical).
    Unknown modes fail closed. Identical inputs always produce an identical
    plan, provenance, warnings and signature.
    """
    mode = _norm(getattr(creative_direction, "mode", ""))
    if not mode:
        return {}
    profile = _PROFILES.get(mode)
    if profile is None:
        raise PosterCompositionError("UNSUPPORTED_COMPOSITION_MODE")

    constraints = constraints or {}
    fields = fields or {}
    suppressions: list[dict[str, str]] = []
    active_locks: set[str] = set()

    def suppress(prop: str, mode_value: Any, resolved_value: Any, reason: str, authority: str) -> None:
        suppressions.append(
            {
                "property": prop,
                "mode_value": _norm(mode_value),
                "resolved_value": _norm(resolved_value),
                "reason": reason,
                "authority": authority,
            }
        )

    # Mode defaults (the WRNA authority level).
    anchor = str(profile["anchor"])
    copy_side = str(profile["copy_side"])
    human_presence = str(profile["human_presence"])
    face_safe_rule = str(profile["face_safe_rule"])
    label_style = str(profile["label_style"])

    # ── RECIPE authority (over WRNA mode) ────────────────────────────────────
    recipe_block = constraints.get("recipe") or {}
    if recipe_block.get("product_anchor"):
        recipe_anchor = str(recipe_block["product_anchor"])
        if recipe_anchor != anchor:
            suppress("product.anchor", anchor, recipe_anchor, "RECIPE_SAFE_REGION_LOCK", AUTHORITY_RECIPE)
            anchor = recipe_anchor
        active_locks.add("RECIPE_SAFE_REGION")
    if float(recipe_block.get("band_span_pct") or 0.0) > _BAND_SPAN_STACK_THRESHOLD:
        # The recipe product band spans the frame — side copy columns would
        # overlap the product-safe region, so copy stacks above/below it.
        if copy_side != "stacked":
            suppress("copy.copy_side", copy_side, "stacked", "RECIPE_SAFE_REGION_LOCK", AUTHORITY_RECIPE)
            copy_side = "stacked"
    if recipe_block.get("requires_human_hand") and human_presence in _HUMAN_ABSENT_VALUES:
        suppress(
            "scene.human_presence",
            human_presence,
            "required-hands-scale-cue",
            "RECIPE_REQUIRED_HUMAN",
            AUTHORITY_RECIPE,
        )
        human_presence = "required-hands-scale-cue"
        active_locks.add("RECIPE_REQUIRED_HUMAN")

    # ── OPERATOR authority (over recipe + mode) ──────────────────────────────
    operator_block = constraints.get("operator") or {}
    operator_presence = _norm(operator_block.get("human_presence"))
    if operator_presence:
        if operator_presence != human_presence:
            suppress(
                "scene.human_presence",
                human_presence,
                operator_presence,
                "OPERATOR_HARD_SELECTION",
                AUTHORITY_OPERATOR,
            )
            human_presence = operator_presence
        active_locks.add("OPERATOR_HUMAN_PRESENCE")

    human_absent = human_presence.lower() in _HUMAN_ABSENT_VALUES
    identity_policy = "no person" if human_absent else "unrestricted natural person"

    # ── APPROVED IDENTITY authority (over operator) ──────────────────────────
    identity_block = constraints.get("identity") or {}
    if identity_block.get("approved_identity_required") and not human_absent:
        suppress(
            "scene.identity_policy",
            identity_policy,
            "approved identity only",
            "APPROVED_IDENTITY_LOCK",
            AUTHORITY_APPROVED_IDENTITY,
        )
        identity_policy = "approved identity only"
        active_locks.add("APPROVED_IDENTITY")

    # ── PRODUCT TRUTH authority (highest) ────────────────────────────────────
    truth_block = constraints.get("product_truth") or {}
    identity_locked = bool(truth_block)
    if truth_block:
        locked_style = "label fully readable, true packaging, real-world scale"
        if label_style != locked_style:
            suppress(
                "product.label_style",
                label_style,
                locked_style,
                "PRODUCT_TRUTH_LOCK",
                AUTHORITY_PRODUCT_TRUTH,
            )
            label_style = locked_style
        active_locks.add("PRODUCT_TRUTH")

    # Face-safe activation: a person introduced into a mode with no face plan
    # gets a deterministic protected zone; a hook sharing that zone relocates.
    zones = dict(_COPY_ZONES[copy_side])
    # A hands-only scale cue never brings a face into frame — the face-safe
    # activation applies only when an actual person can appear.
    face_possible = not human_absent and human_presence != "required-hands-scale-cue"
    if face_possible and face_safe_rule == "not applicable":
        face_safe_rule = "upper-center protected"
    if face_possible:
        # Conflict when the face-safe zone and the hook zone share the same
        # horizontal column (last "-" token): the hook drops below the band.
        face_column = face_safe_rule.split(" ")[0].rsplit("-", 1)[-1]
        hook_column = zones["hook_zone"].split(" ")[0].rsplit("-", 1)[-1]
        if face_column and face_column == hook_column:
            zones["hook_zone"] = f"{zones['hook_zone']} below face-safe band"
            zones["subhook_zone"] = f"{zones['subhook_zone']} below face-safe band"

    warnings, blockers = _copy_governance(fields, constraints)
    if any(s["reason"] == "RECIPE_SAFE_REGION_LOCK" and s["property"] == "copy.copy_side" for s in suppressions):
        warnings.append("PRODUCT_COPY_ZONE_CONFLICT_RESOLVED")
    if any("below face-safe band" in z for z in zones.values()):
        warnings.append("FACE_COPY_ZONE_CONFLICT_RESOLVED")
    if constraints.get("copy_quality") is not None:
        active_locks.add("COPY_QUALITY_GOVERNANCE")

    authority_versions = {
        "creative_direction": _norm(getattr(creative_direction, "authority_version", "")),
        "representation_policy": _norm(
            getattr(creative_direction, "representation_policy_version", "")
        )
        or _norm((constraints.get("identity") or {}).get("policy_version")),
    }

    plan: dict[str, Any] = {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "profile_id": str(profile["profile"]),
        "creative_mode": mode,
        "recipe_id": _norm(recipe_id),
        "authority_versions": authority_versions,
        "provenance": {
            "constraint_schema": _norm(constraints.get("constraint_schema")),
            "active_locks": sorted(active_locks),
            "suppressions": suppressions,
        },
        "canvas": {
            "frame_ratio": _norm(frame_ratio) or "9:16",
            "safe_margin": "5%",
            "edge_exclusion": "text and CTA stay inside safe margin",
        },
        "reading_order": list(profile["reading_order"]),
        "product": {
            "anchor": anchor,
            "dominance": str(profile["dominance"]),
            "label_visibility": "required",
            "label_style": label_style,
            "real_world_scale": "required",
            "identity_lock": identity_locked,
            "prohibited_overlaps": ["hook", "cta", "face"],
        },
        "copy": {
            "copy_side": copy_side,
            "hook_zone": zones["hook_zone"],
            "subhook_zone": zones["subhook_zone"],
            "usp_zone": zones["usp_zone"],
            "cta_zone": zones["cta_zone"],
            "strategy": str(profile["negative_space"]),
            "max_lines": {"hook": 3, "subhook": 3, "usp": 3, "cta": 2},
        },
        "typography": {
            "hook": str(profile["hook_treatment"]),
            "subhook": "supporting",
            "usp": str(profile["usp_treatment"]),
            "cta": str(profile["cta_treatment"]),
            "intensity": str(profile["typography_intensity"]),
        },
        "scene": {
            "lighting": str(profile["lighting"]),
            "human_presence": human_presence,
            "identity_policy": identity_policy,
            "face_safe_rule": face_safe_rule,
            "negative_space": str(profile["negative_space"]),
            "background_complexity": str(profile["background_complexity"]),
            "prop_density": str(profile["prop_density"]),
        },
        "quality_negative_rules": [
            "no text covering product or face",
            "no floating chips",
            "no excessive badges",
            "no duplicate product crop",
            "no fabricated certification",
            "no cluttered spec-sheet layout",
        ],
        "warnings": warnings,
        "blockers": blockers,
    }
    plan["signature"] = _signature(plan)
    return plan


def render_composition_instruction(plan: dict[str, Any]) -> str:
    """Engine-facing composition instruction. Carries ONLY visual direction —
    never profile ids, schema versions, signatures or lock provenance codes."""
    if not plan:
        return ""
    product = plan["product"]
    copy = plan["copy"]
    scene = plan["scene"]
    typography = plan["typography"]
    human = scene["human_presence"]
    person_line = (
        "No person in frame."
        if human.lower() in _HUMAN_ABSENT_VALUES
        else f"Human presence: {human}; {scene['identity_policy']}; face-safe: {scene['face_safe_rule']}."
    )
    return (
        f"Professional composition: {plan['canvas']['frame_ratio']} canvas; "
        f"product anchored {product['anchor']} at {product['dominance']} visual dominance; "
        f"{product['label_style']}; no product form-factor or scale change. "
        f"Reading order {' then '.join(plan['reading_order'])}. "
        f"Keep hook {copy['hook_zone']}, USP {copy['usp_zone']} and CTA {copy['cta_zone']} "
        f"inside the {plan['canvas']['safe_margin']} safe margin. "
        f"{person_line} "
        f"{scene['lighting']}; {scene['background_complexity']}; {scene['prop_density']}; "
        f"negative space: {scene['negative_space']}. "
        f"Typography: {typography['intensity']}; hook {typography['hook']}; CTA {typography['cta']}. "
        f"{'; '.join(plan['quality_negative_rules'])}."
    )
