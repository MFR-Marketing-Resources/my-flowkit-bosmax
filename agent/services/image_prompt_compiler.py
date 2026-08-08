"""Canonical nine-section image/poster prompt compiler.

This module only compiles an auditable request.  It never renders a poster,
places a cutout, spends provider credits or approves a generated artifact.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.models.image_generation_contract import (
    IMAGE_PROMPT_COMPILER_VERSION,
    CapabilityStatus,
    ImageCreativeContext,
    ImageOperationPlan,
    ImageOperationPlanRequest,
    ImagePromptCompileRequest,
    ImagePromptCompileResponse,
    ProductReferencePackRecord,
)


IMAGE_PROMPT_SECTIONS: tuple[str, ...] = (
    "OUTPUT_INTENT_AND_FORMAT",
    "PRODUCT_IDENTITY_LOCK",
    "PRODUCT_SCALE_AND_GEOMETRY",
    "COMPOSITION_AND_HIERARCHY",
    "CAMERA_FRAMING_AND_PERSPECTIVE",
    "LIGHTING_MATERIAL_AND_PHYSICAL_INTERACTION",
    "SCENE_AND_CULTURAL_DIRECTION",
    "MARKETING_COPY_AND_TEXT_LAYOUT",
    "NEGATIVE_CONSTRAINTS_AND_OUTPUT_SPECIFICATION",
)


def _clean(value: Any, fallback: str = "Not specified") -> str:
    text = " ".join(str(value or "").split()).strip()
    return text or fallback


def _copy_text(copy_layout: dict[str, str]) -> str:
    if not copy_layout:
        return "No marketing copy supplied; do not invent marketing claims."
    lines = [f"{key}: {_clean(value)}" for key, value in copy_layout.items() if _clean(value)]
    return "; ".join(lines) or "No marketing copy supplied; do not invent marketing claims."


_COPY_SPACE_KEYS: tuple[str, ...] = (
    "headline_line_budget",
    "support_line_budget",
    "proof_line_budget",
    "cta_line_budget",
    "text_hierarchy",
    "copy_zone_strategy",
    "copy_safe_margin",
    "avoid_product_overlap",
)


def _copy_space_text(copy_space: dict[str, Any]) -> str:
    """Compile structural copy-space metadata without leaking copy values.

    The clean-key-visual provider call owns visual integration; deterministic
    composition owns the wording.  Only geometry/line-budget keys are allowed
    through this boundary so a caller cannot accidentally turn a clean KV into
    a provider-rendered poster by putting text in the preview request.
    """
    parts: list[str] = []
    for key in _COPY_SPACE_KEYS:
        value = copy_space.get(key)
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        text = " ".join(str(value).split()).strip()
        if text:
            parts.append(f"{key}={text[:160]}")
    return "; ".join(parts) or (
        "headline_line_budget=1; support_line_budget=1; proof_line_budget=1; "
        "cta_line_budget=1; copy_zone_strategy=deliberate_negative_space; "
        "copy_safe_margin=5%; avoid_product_overlap=true"
    )


def _creative_context_text(context: ImageCreativeContext | None) -> str:
    if context is None:
        return (
            "No approved campaign intelligence supplied; keep the image product-led "
            "and do not invent audience or claims."
        )
    facts = "; ".join(context.approved_facts) or "No additional approved product facts supplied."
    art = context.art_direction
    provenance = "; ".join(
        f"{key}={value}" for key, value in context.field_provenance.items()
    ) or "NO_FIELD_PROVENANCE"
    missing = ", ".join(context.missing_fields) or "none"
    submission_rule = (
        "This context is incomplete: compile for diagnostics only and do not submit to a provider."
        if context.intelligence_status != "READY"
        else "This context is complete for compilation; generated output still requires separate machine and human approval."
    )
    return "\n".join(
        [
            f"Intelligence status={context.intelligence_status}; grounding source={context.grounding_source}; family={context.product_family or 'unspecified'}; formula={context.formula or 'single-idea poster'}.",
            submission_rule,
            f"Audience: {context.audience}",
            f"Purchase desire: {context.desire}",
            f"Safe campaign angle: {context.safe_angle}",
            f"Objection to answer visually: {context.objection}",
            f"Purchase trigger: {context.trigger}",
            f"Tone: {context.tone}",
            f"Approved product facts only: {facts}",
            f"Missing intelligence fields: {missing}",
            f"Field provenance: {provenance}",
            "TYPED ART DIRECTION:",
            f"creative territory={art.creative_territory}",
            f"layout family={art.layout_family}",
            f"visual tension={art.visual_tension}",
            f"product anchor={art.product_anchor}",
            f"copy anchor={art.copy_anchor}",
            f"headline personality={art.headline_personality}",
            f"headline line budget={art.headline_line_budget}",
            f"type contrast={art.type_contrast}",
            f"CTA treatment={art.cta_treatment}",
            f"negative-space strategy={art.negative_space_strategy}",
            "brand visual codes=" + "; ".join(art.brand_visual_codes),
            "anti-cliche rules=" + "; ".join(art.anti_cliche_rules),
            "Do not depict symptoms, treatment, medical outcomes, or unsupported claims. Translate raw customer concerns into safe readiness, comfort and product-familiarity cues.",
        ]
    )


def _measurements_text(pack: ProductReferencePackRecord) -> str:
    measurement = pack.physical_measurements
    values = [
        ("width_mm", measurement.physical_width_mm),
        ("height_mm", measurement.physical_height_mm),
        ("depth_mm", measurement.physical_depth_mm),
        ("volume_ml", measurement.volume_ml),
    ]
    known = ", ".join(f"{key}={value:g}" for key, value in values if value is not None)
    if not known:
        return (
            "PHYSICAL SCALE UNVERIFIED: do not infer real-world dimensions from pixels. "
            "Preserve the product's compact catalog-described presence and require human review."
        )
    return (
        f"Authored physical evidence ({known}); source={measurement.scale_evidence_source}; "
        f"confidence={measurement.scale_confidence}. Do not rescale beyond this evidence."
    )


def build_operation_plan(request: ImageOperationPlanRequest) -> ImageOperationPlan:
    """Bound the provider call budget before any live submit."""
    return ImageOperationPlan(
        product_id=request.product_id,
        model=request.model,
        requested_outputs=request.requested_outputs,
        max_provider_operations=request.requested_outputs + request.max_retry_operations,
        max_retry_operations=request.max_retry_operations,
        estimated_credit_exposure=None,
        estimated_credit_exposure_status="UNVERIFIED",
        explicit_confirmation_required=True,
        hidden_retry_allowed=False,
    )


async def resolve_image_creative_context(
    product: dict[str, Any],
    *,
    operator_direction: str = "",
    objective: str = "",
    copy_layout: dict[str, str] | None = None,
) -> ImageCreativeContext:
    """Resolve approved product intelligence without provider spend."""

    from agent.db import crud
    from agent.services.copy_grounding_service import (
        build_safe_campaign_context,
        resolve_copy_grounding,
    )

    grounding = await resolve_copy_grounding(product)
    payload = build_safe_campaign_context(
        product,
        grounding,
        operator_direction=operator_direction,
        objective=objective,
        copy_layout=copy_layout,
    )
    snapshot = await crud.get_latest_approved_product_intelligence_snapshot(
        str(product.get("id") or product.get("product_id") or "")
    )
    if snapshot:
        payload["approved_snapshot_id"] = snapshot.get("snapshot_id")
        payload["approved_snapshot_version"] = snapshot.get("version")
    return ImageCreativeContext.model_validate(payload)


def compile_image_prompt(
    product: dict[str, Any],
    pack: ProductReferencePackRecord,
    request: ImagePromptCompileRequest,
    creative_context: ImageCreativeContext | None = None,
) -> ImagePromptCompileResponse:
    if str(product.get("id") or product.get("product_id")) != request.product_id:
        raise ValueError("PRODUCT_REFERENCE_PACK_PRODUCT_MISMATCH")

    product_name = _clean(
        product.get("product_display_name")
        or product.get("product_short_name")
        or product.get("raw_product_title"),
        "the registered product",
    )
    requested_roles = list(dict.fromkeys(request.reference_roles))
    bindings = [binding for binding in pack.references if binding.role in requested_roles]
    present_roles = {binding.role for binding in bindings}
    blockers = [
        f"REFERENCE_ROLE_MISSING:{role}"
        for role in requested_roles
        if role not in present_roles
    ]
    if pack.pack_status != "APPROVED":
        blockers.append("REFERENCE_PACK_APPROVAL_REQUIRED")
    if request.creative_mode == "CREATIVE_CAMPAIGN" and request.output_intent == "COMPLETE_POSTER":
        if creative_context is None or creative_context.intelligence_status != "READY":
            blockers.append("CREATIVE_INTELLIGENCE_INCOMPLETE")

    if request.output_intent == "CLEAN_KEY_VISUAL":
        copy_section = (
            "CLEAN KEY VISUAL: render no headline, CTA, offer, logo recreation or marketing text. "
            "Leave intentional negative space for the deterministic copy layer. "
            f"Structural copy-space contract only: {_copy_space_text(request.copy_space)}."
        )
    else:
        copy_section = (
            "Render only the exact supplied copy/layout; never rewrite or hallucinate claims. "
            f"{_copy_text(request.copy_layout)}\n"
            "MOBILE-FIRST TEXT HIERARCHY: one short hook (prefer 3–6 words) is the first read; "
            "one complete support line (prefer 6–12 words); up to two compact proof chips from supplied facts; "
            "one action CTA (2–4 words). Use the typed art direction's headline personality, line budget, "
            "type contrast and CTA treatment; use strong contrast, generous line spacing and safe margins. "
            "Do not render a paragraph, repeated slogan, decorative pseudo-copy, or any text not supplied above. "
            "Do not substitute a generic font pairing or fixed upper/middle/lower placement. Keep the hook short, "
            "avoid long all-caps lines, and use deliberate size contrast rather than shrinking every line to fit. "
            "Keep every text block away from the product label and never let typography force product enlargement."
        )

    composition = _clean(request.composition)
    if creative_context is not None:
        composition = (
            f"{composition}. Build the mobile-first hierarchy from the typed art direction, not a fixed poster template: "
            "honour its layout family, visual tension, product anchor, copy anchor, headline line budget and "
            "negative-space strategy. Position copy and product around the registered silhouette and supplied copy length; "
            "do not force an upper/middle/lower grid. Use one visual idea and one grounded hero; avoid poster-by-committee "
            "layouts, tiny copy, decorative clutter and a background that competes with the label. "
            f"Campaign intelligence:\n{_creative_context_text(creative_context)}"
        )

    negatives = [
        "no product identity drift",
        "no altered label, logo, brand mark or printed text",
        "no invented packaging geometry or cap/bottle shape",
        "no product scale exaggeration or shrinkage beyond authored evidence",
        "no floating product; use physically coherent contact, shadow and perspective",
        "no duplicate product unless explicitly requested",
        "no cutout pasted onto a flat background; integrate the supplied product references into one scene",
        "no garbled marketing text",
        *request.negative_constraints,
    ]
    sections = {
        IMAGE_PROMPT_SECTIONS[0]: (
            f"Intent={request.output_intent}; aspect ratio={request.aspect_ratio}; "
            f"campaign mode={request.creative_mode}; generate the complete requested image in one provider output."
        ),
        IMAGE_PROMPT_SECTIONS[1]: (
            f"Registered product: {product_name}. Use the bound canonical product reference as identity authority, "
            "then use label and logo crops as inspection references. Preserve exact visible identity, colors, typography "
            "and packaging geometry. Do not substitute a similar product."
        ),
        IMAGE_PROMPT_SECTIONS[2]: _measurements_text(pack),
        IMAGE_PROMPT_SECTIONS[3]: composition,
        IMAGE_PROMPT_SECTIONS[4]: _clean(request.camera),
        IMAGE_PROMPT_SECTIONS[5]: _clean(request.lighting),
        IMAGE_PROMPT_SECTIONS[6]: (
            f"{_clean(request.scene_direction)}. Scene direction comes from this preset/prompt; "
            "a legacy scene asset is not required. Any optional scene reference is secondary to the product pack."
        ),
        IMAGE_PROMPT_SECTIONS[7]: copy_section,
        IMAGE_PROMPT_SECTIONS[8]: (
            "; ".join(dict.fromkeys(negatives))
            + f". Output specification: {request.output_intent}, {request.aspect_ratio}, no hidden retries."
        ),
    }
    compiled_prompt = "\n\n".join(
        f"{index + 1}. {name}\n{sections[name]}"
        for index, name in enumerate(IMAGE_PROMPT_SECTIONS)
    )
    fingerprint = hashlib.sha256(compiled_prompt.encode("utf-8")).hexdigest()
    capability: dict[str, CapabilityStatus] = {
        "multi_reference_roles": "UNPROVEN",
        "product_editing": "UNPROVEN",
        "complete_poster_output": "UNPROVEN",
        "response_media_contract": "SUPPORTED",
        "generated_identity_fidelity": "UNPROVEN",
    }
    warnings = [
        "Provider behavior is UNPROVEN until a bounded live artifact benchmark is authorized and inspected.",
        "Reference pack approval does not approve any generated output.",
    ]
    if pack.physical_measurements.scale_confidence == "UNVERIFIED":
        warnings.append("Physical scale is UNVERIFIED; no pixel-derived scale claim was added.")
    if pack.machine_qa_status == "WARN":
        warnings.append("Reference pack machine QA is WARN and requires human review.")
    return ImagePromptCompileResponse(
        compiler_version=IMAGE_PROMPT_COMPILER_VERSION,
        product_id=request.product_id,
        output_intent=request.output_intent,
        aspect_ratio=request.aspect_ratio,
        compiled_prompt=compiled_prompt,
        sections=sections,
        prompt_fingerprint=fingerprint,
        reference_pack=pack,
        reference_bindings=bindings,
        blockers=blockers,
        warnings=warnings,
        capability_status=capability,
        creative_context=creative_context,
        provider_operation_plan=build_operation_plan(
            ImageOperationPlanRequest(
                product_id=request.product_id,
                requested_outputs=request.requested_outputs,
                max_retry_operations=0,
                model=request.model,
            )
        ).model_dump(mode="json"),
    )
