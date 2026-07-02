"""CANONICAL DELEGATION SHIM (ADR-008 sovereignty repair, 2026-07-02).

This module previously rendered a CONFLICTING "9-section" taxonomy (Biometric
Anchor DNA / Dialogue & Silo Purity / Overlay & Typography) that competed with
the retained canonical authority and was still LIVE through batch_planner and
the creative-brief prompt-preview endpoint.

The legacy body has been REMOVED. The public function keeps its exact
signature but now delegates to THE canonical compiler
(agent/services/canonical_prompt_compiler.py), so every historical caller is
neutralized without edits. Do not add rendering logic here — prompt-quality
changes belong in the canonical compiler or its authority data.
"""
from __future__ import annotations

from agent.services import canonical_prompt_compiler as _canonical
from agent.services import copy_landbank_service as _landbank
from agent.services.product_creative_brief import get_creative_brief


async def compile_9_section_prompt(product_id: str, variant_plan: dict) -> str:
    """Compile the canonical 9-section prompt set for a batch/brief variant.

    Signature preserved for legacy callers (batch_planner, creative_brief API).
    Output is now the retained canonical 9-section contract — one complete set
    per block, HYBRID product-anchor semantics, concrete presenter prose.
    """
    brief = await get_creative_brief(product_id)
    if "error" in brief:
        return "Error: Product brief not found."

    intelligence = brief.get("product_intelligence", {}) or {}
    copy_route = brief.get("copywriting_route", {}) or {}
    physics = brief.get("physics_dna", {}) or {}
    variant_plan = variant_plan or {}

    product = {
        "id": product_id,
        "name": intelligence.get("product_short_name")
        or intelligence.get("product_name")
        or "the product",
        "category": intelligence.get("category", ""),
    }
    # Copy intelligence: landbank first (secondary reference), then the brief's
    # copywriting route. Variant hook_angle/camera_route are VISUAL directions,
    # not spoken copy — they shape the scene, never Section 6.
    copy = _landbank.lookup(product_id, angle=copy_route.get("copywriting_angle")) or {
        "angle": copy_route.get("copywriting_angle", ""),
        "formula_family": copy_route.get("formula", ""),
    }
    scene_bits = [
        str(variant_plan.get("scene_context") or ""),
        str(variant_plan.get("hook_angle") or ""),
        str(variant_plan.get("camera_route") or ""),
    ]
    result = _canonical.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=int(variant_plan.get("duration_seconds") or 8),
        product=product,
        scene_context=". ".join(x for x in scene_bits if x),
        copy=copy,
        avatar_id=variant_plan.get("avatar_id"),
        target_language=str(variant_plan.get("target_language") or "BM_MS"),
        handling_notes=str(physics.get("section_5_product_physics_prompt") or ""),
    )
    return "\n\n".join(block["engine_prompt_text"] for block in result["blocks"])
