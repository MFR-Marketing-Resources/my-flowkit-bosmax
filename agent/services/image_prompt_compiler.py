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


def compile_image_prompt(
    product: dict[str, Any],
    pack: ProductReferencePackRecord,
    request: ImagePromptCompileRequest,
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

    if request.output_intent == "CLEAN_KEY_VISUAL":
        copy_section = (
            "CLEAN KEY VISUAL: render no headline, CTA, offer, logo recreation or marketing text. "
            "Leave intentional negative space for the deterministic copy layer."
        )
    else:
        copy_section = (
            f"Render only the exact supplied copy/layout; never rewrite or hallucinate claims. "
            f"{_copy_text(request.copy_layout)}"
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
        IMAGE_PROMPT_SECTIONS[3]: _clean(request.composition),
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
        provider_operation_plan=build_operation_plan(
            ImageOperationPlanRequest(
                product_id=request.product_id,
                requested_outputs=request.requested_outputs,
                max_retry_operations=0,
                model=request.model,
            )
        ).model_dump(mode="json"),
    )
