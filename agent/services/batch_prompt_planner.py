"""Batch Prompt Planner — variation strategies + anti-redundancy fingerprints.

Prompt/production split (Batch Prompt Builder): one batch prompt run uses
exactly ONE logical mode (T2V | HYBRID | F2V | I2V). The planner expands
Qty N into N deterministic item plans BEFORE any compile call — rotating
avatars, scenes and hooks according to the selected variation strategy —
then annotates every generated package with redundancy fingerprints and
enforces hard blocks / soft warnings against batch-local and product-history
duplication.

This module is pure planning/analysis: it never writes the DB and never
calls the compiler, so it stays unit-testable without fixtures.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import re

# ── Mode law ──────────────────────────────────────────────────────────────

LOGICAL_MODES = ("T2V", "HYBRID", "F2V", "I2V")

# logical_mode → descriptive execution lane (stored, user-visible)
EXECUTION_LANES = {
    "T2V": "TEXT_TO_VIDEO",
    "HYBRID": "PRODUCT_ANCHOR_PRESENTER",
    "F2V": "FINISHED_FRAME_TO_VIDEO",
    "I2V": "INGREDIENTS_TO_VIDEO",
}

# logical_mode → engine mode fired at the one hardened generate door
# (ADR-007). HYBRID keeps its logical identity everywhere except the
# engine payload, where it rides the proven F2V lane (product anchor frame).
ENGINE_MODES = {
    "T2V": "T2V",
    "HYBRID": "F2V",
    "F2V": "F2V",
    "I2V": "I2V",
}

VARIATION_STRATEGIES = (
    "SAME_SCRIPT_DIFF_VISUALS",
    "DIFF_SCRIPT_DIFF_VISUALS",
    "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
)
DEFAULT_VARIATION_STRATEGY = "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS"

# Soft-warning thresholds
DIALOGUE_SIMILARITY_CEILING = 0.90
AVATAR_BATCH_SLACK = 1  # allowed uses above the fair round-robin share
SCENE_BATCH_SLACK = 1


def _sha1(*parts: str) -> str:
    return hashlib.sha1("||".join(p or "" for p in parts).encode("utf-8")).hexdigest()


def normalize_text(text: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace — comparison form."""
    cleaned = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


# ── Mode input contracts ──────────────────────────────────────────────────


def validate_mode_inputs(
    logical_mode: str,
    *,
    quantity: int = 1,
    variation_strategy: str | None = None,
    finished_frame_asset_id: str | None = None,
    character_asset_ids: list[str] | None = None,
    scene_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    product_row: dict | None = None,
) -> list[str]:
    """Deterministic mode-contract errors. Empty list = inputs are legal."""
    errors: list[str] = []
    mode = str(logical_mode or "").strip().upper()
    if mode not in LOGICAL_MODES:
        return [f"UNSUPPORTED_LOGICAL_MODE:{logical_mode}"]
    if quantity < 1 or quantity > 100:
        errors.append("QUANTITY_OUT_OF_RANGE:1-100")
    strategy = variation_strategy or DEFAULT_VARIATION_STRATEGY
    if strategy not in VARIATION_STRATEGIES:
        errors.append(f"UNSUPPORTED_VARIATION_STRATEGY:{variation_strategy}")

    has_char = bool(character_asset_ids)
    has_scene = bool(scene_asset_ids)
    has_style = bool(style_asset_ids)
    product = product_row or {}
    has_product_anchor = bool(
        product.get("media_id")
        or product.get("local_image_path")
        or product.get("image_url")
    )

    if mode == "T2V":
        # Text-only: prompt generation must not require or accept image slots.
        if finished_frame_asset_id or has_char or has_scene or has_style:
            errors.append("T2V_FORBIDS_IMAGE_SLOTS")
    elif mode == "HYBRID":
        # Product image is the visual truth anchor; presenter comes from the
        # avatar registry (rotated by the planner), never from an image slot.
        if not has_product_anchor:
            errors.append("HYBRID_REQUIRES_PRODUCT_ANCHOR")
        if finished_frame_asset_id:
            errors.append("HYBRID_FORBIDS_FINISHED_FRAME_SLOT")
    elif mode == "F2V":
        # One finished/composite frame is the single visual truth.
        if not finished_frame_asset_id:
            errors.append("F2V_REQUIRES_FINISHED_FRAME")
        if has_char or has_scene or has_style:
            errors.append("F2V_FORBIDS_SEPARATE_ROLE_SLOTS")
    elif mode == "I2V":
        # Explicit role map: PRODUCT_REFERENCE (from product record) +
        # AVATAR_REFERENCE are required; style/scene is optional.
        if not has_char:
            errors.append("I2V_REQUIRES_AVATAR_REFERENCE")
        if not has_product_anchor:
            errors.append("I2V_REQUIRES_PRODUCT_REFERENCE")
        if finished_frame_asset_id:
            errors.append("I2V_FORBIDS_FINISHED_FRAME_SLOT")
    return errors


# ── Variation planning ────────────────────────────────────────────────────


def _rotate(pool: list, start: int, index: int):
    if not pool:
        return None
    return pool[(start + index) % len(pool)]


def plan_batch_items(
    *,
    logical_mode: str,
    variation_strategy: str,
    quantity: int,
    product_id: str,
    avatar_codes: list[str] | None = None,
    character_asset_ids: list[str] | None = None,
    scene_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    scene_contexts: list[str] | None = None,
    hook_angles: list[str] | None = None,
    copy_set_ids: list[str] | None = None,
    finished_frame_asset_id: str | None = None,
    product_reference_asset_id: str | None = None,
) -> list[dict]:
    """Expand Qty N into N deterministic item plans (round-robin rotation).

    The rotation start offset is seeded from product_id so re-running the
    same batch config yields the same plan (repeatable, never random).
    """
    mode = str(logical_mode or "").strip().upper()
    strategy = variation_strategy or DEFAULT_VARIATION_STRATEGY
    seed = int(_sha1(product_id, mode)[:8], 16)

    same_script = strategy == "SAME_SCRIPT_DIFF_VISUALS"
    avatars = list(avatar_codes or [])
    chars = list(character_asset_ids or [])
    scenes = list(scene_asset_ids or [])
    styles = list(style_asset_ids or [])
    contexts = list(scene_contexts or [])
    hooks = list(hook_angles or [])

    items: list[dict] = []
    for i in range(quantity):
        plan: dict = {
            "item_index": i,
            "logical_mode": mode,
            "execution_lane": EXECUTION_LANES[mode],
            "variation_strategy": strategy,
            "variation_salt": f"v{i + 1}",
        }
        # Visuals rotate every item under every strategy ("different visuals").
        if mode in ("T2V", "HYBRID"):
            plan["avatar_code"] = _rotate(avatars, seed, i)
        if mode == "I2V":
            plan["character_asset_id"] = _rotate(chars, seed, i)
            plan["scene_asset_id"] = _rotate(scenes, seed, i)
            plan["style_asset_id"] = _rotate(styles, seed, i)
        if mode == "F2V":
            plan["finished_frame_asset_id"] = finished_frame_asset_id
        if mode == "HYBRID":
            # The product anchor (PRODUCT_REFERENCE-role, target-aspect padded)
            # is CONSTANT across the batch — visuals rotate via avatar + scene,
            # never via the product's visual truth.
            plan["product_reference_asset_id"] = product_reference_asset_id
        plan["scene_context_override"] = _rotate(contexts, seed, i)
        # Script: same hook for all items when the strategy fixes the script;
        # otherwise rotate the hook angle so dialogue actually diverges.
        # copy_set_ids is index-aligned with hook_angles (Script Library
        # rotation) and MUST rotate with the identical (seed, i) so the
        # copy_set lineage stays paired with its hook text.
        plan["hook_override"] = (hooks[0] if hooks else None) if same_script else _rotate(hooks, seed, i)
        cs_ids = list(copy_set_ids or [])
        plan["copy_set_id"] = (cs_ids[0] if cs_ids else None) if same_script else _rotate(cs_ids, seed, i)
        items.append(plan)
    return items


# ── Fingerprints ──────────────────────────────────────────────────────────

_SECTION6_RE = re.compile(
    r"SECTION\s*6[^\n]*\n(.*?)(?=SECTION\s*7|\Z)", re.IGNORECASE | re.DOTALL
)


def extract_dialogue(final_prompt_text: str) -> str:
    """Spoken dialogue lives in SECTION 6 of every canonical block."""
    parts = _SECTION6_RE.findall(str(final_prompt_text or ""))
    return "\n".join(p.strip() for p in parts if p.strip())


def extract_hook(dialogue: str) -> str:
    """First spoken line/sentence — the hook that decides scroll-stop."""
    text = str(dialogue or "").strip()
    if not text:
        return ""
    first_line = text.splitlines()[0]
    sentences = re.split(r"(?<=[.!?])\s+", first_line)
    return sentences[0].strip() if sentences else first_line.strip()


def compute_fingerprints(
    *,
    final_prompt_text: str,
    item_plan: dict,
    resolved_engine_slots: dict | None = None,
) -> dict:
    """Redundancy metadata stored on every generated prompt package."""
    dialogue = extract_dialogue(final_prompt_text)
    hook = extract_hook(dialogue)
    scene_key = normalize_text(
        item_plan.get("scene_context_override")
        or item_plan.get("scene_asset_id")
        or ""
    )
    avatar_key = str(
        item_plan.get("avatar_code")
        or item_plan.get("character_asset_id")
        or ""
    ).strip().upper()
    role_map = {
        k: v for k, v in (resolved_engine_slots or {}).items() if v
    }
    return {
        "prompt_fingerprint": _sha1(normalize_text(final_prompt_text)),
        "dialogue_fingerprint": _sha1(normalize_text(dialogue)),
        "hook_fingerprint": _sha1(normalize_text(hook)),
        "avatar_fingerprint": _sha1(avatar_key) if avatar_key else "",
        "avatar_key": avatar_key,
        "scene_fingerprint": _sha1(scene_key) if scene_key else "",
        "asset_role_map_fingerprint": _sha1(json.dumps(role_map, sort_keys=True)),
        "dialogue_text_norm": normalize_text(dialogue),
    }


def dialogue_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# ── Anti-redundancy checks ────────────────────────────────────────────────


def check_redundancy(
    *,
    fingerprints: dict,
    batch_seen: list[dict],
    history_fingerprints: set[str],
    variation_strategy: str,
    quantity: int,
    rotation_pool_size: int,
) -> tuple[list[str], list[str]]:
    """Return (hard_blocks, soft_warnings) for one candidate item.

    batch_seen: fingerprint dicts of items already accepted in THIS batch.
    history_fingerprints: prompt fingerprints from prior packages for the
    same product + logical mode (hard-block scope).
    """
    hard: list[str] = []
    soft: list[str] = []
    fp = fingerprints

    if fp["prompt_fingerprint"] in history_fingerprints:
        hard.append("DUPLICATE_PROMPT_FINGERPRINT_IN_HISTORY")
    if any(s["prompt_fingerprint"] == fp["prompt_fingerprint"] for s in batch_seen):
        hard.append("DUPLICATE_PROMPT_FINGERPRINT_IN_BATCH")

    combo = (fp["avatar_fingerprint"], fp["scene_fingerprint"], fp["hook_fingerprint"])
    if any(
        (s["avatar_fingerprint"], s["scene_fingerprint"], s["hook_fingerprint"]) == combo
        for s in batch_seen
    ):
        hard.append("DUPLICATE_AVATAR_SCENE_HOOK_COMBO_IN_BATCH")

    # Soft: avatar/scene frequency above the fair round-robin share.
    pool = max(1, rotation_pool_size)
    fair_share = math.ceil(quantity / pool)
    if fp["avatar_fingerprint"]:
        uses = 1 + sum(
            1 for s in batch_seen if s["avatar_fingerprint"] == fp["avatar_fingerprint"]
        )
        if uses > fair_share + AVATAR_BATCH_SLACK:
            soft.append(f"AVATAR_OVERUSED_IN_BATCH:{uses}x")
    if fp["scene_fingerprint"]:
        uses = 1 + sum(
            1 for s in batch_seen if s["scene_fingerprint"] == fp["scene_fingerprint"]
        )
        if uses > fair_share + SCENE_BATCH_SLACK:
            soft.append(f"SCENE_OVERUSED_IN_BATCH:{uses}x")

    # Soft: dialogue similarity when the strategy demands different dialogue.
    if variation_strategy in (
        "DIFF_SCRIPT_DIFF_VISUALS",
        "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
    ):
        for s in batch_seen:
            prior = s.get("dialogue_text_norm", "")
            if not prior or not fp.get("dialogue_text_norm"):
                continue
            ratio = difflib.SequenceMatcher(
                None, prior, fp["dialogue_text_norm"]
            ).ratio()
            if ratio > DIALOGUE_SIMILARITY_CEILING:
                soft.append(f"DIALOGUE_TOO_SIMILAR:{ratio:.2f}")
                break

    return hard, soft


def public_fingerprints(fingerprints: dict) -> dict:
    """Storable subset (drops the normalized dialogue working text)."""
    return {
        k: v
        for k, v in fingerprints.items()
        if k
        in (
            "prompt_fingerprint",
            "dialogue_fingerprint",
            "hook_fingerprint",
            "avatar_fingerprint",
            "scene_fingerprint",
            "asset_role_map_fingerprint",
        )
    }
