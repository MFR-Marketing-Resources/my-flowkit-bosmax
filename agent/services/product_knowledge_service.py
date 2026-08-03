from __future__ import annotations

import base64
import json
import logging
import uuid
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.models.product_knowledge import (
    ModeReadiness,
    ProductKnowledgeCompleteRequest,
    ProductKnowledgeCompleteResponse,
    AIFormImportResponse,
)
from agent.models.product_registration import EvidenceCompletionFieldMetadata
from agent.models.product_strategy_taxonomy import ProductStrategyCoverageStatus
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_intelligence_service import (
    evaluate_product_claims,
    resolve_product_intelligence_profile,
)
from agent.services.product_physics import resolve_product_physics
from agent.services.product_mapping import normalize_mapping_text, resolve_product_mapping
from agent.services.product_strategy_taxonomy_service import (
    lookup_product_strategy_type_registry_entry,
)
from agent.config import BASE_DIR
from agent.services.registration_hook_cta_generation_service import (
    generate_registration_hook_cta,
)
from agent.services.registration_evidence_quality_service import (
    audit_registration_evidence,
)
from agent.services.registration_consistency_service import (
    evaluate_registration_consistency,
)
from agent.services import ai_copy_provider_adapter
from agent.services.ai_copy_provider_adapter import (
    AICopyProviderError,
    AICopyProviderNotConfigured,
    ERR_RESPONSE_INVALID,
)


LOGGER = logging.getLogger(__name__)


class TextAssistFieldRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal[
        "product_knowledge_summary",
        "benefits",
        "usage_summary",
        "target_customer",
        "materials_or_components",
        "size_or_volume",
        "package_notes",
        "warnings_or_limitations",
    ]
    proposed_value: str | list[str] | None = None
    evidence_used: list[str] = Field(default_factory=list)
    confidence: Literal["LOW", "MEDIUM"] = "LOW"
    reason: str
    action: Literal["FILL_MISSING", "REPAIR_INVALID_OR_PLACEHOLDER"]
    needs_review: Literal[True] = True


class TextAssistTaxonomySuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    subcategory: str
    type: str
    cluster: str | None = None
    product_type_group: str | None = None
    matched_scene_strategy_id: str | None = None
    scene_coverage_status: ProductStrategyCoverageStatus | None = None
    registry_entry_key: str
    evidence_used: list[str] = Field(default_factory=list)
    confidence: Literal["LOW", "MEDIUM"] = "LOW"
    reason: str
    needs_review: Literal[True] = True


class TextAssistEvidenceCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_knowledge_summary: str | None = None
    benefits: list[str] = Field(default_factory=list)
    usage_summary: str | None = None
    target_customer: str | None = None
    usp_list: list[str] = Field(default_factory=list)
    size_or_volume: str | None = None
    package_notes: str | None = None
    materials_or_components: str | None = None
    ingredients_applicability: Literal[
        "APPLICABLE", "NOT_APPLICABLE", "UNKNOWN"
    ] = "UNKNOWN"
    field_repairs: list[TextAssistFieldRepair] = Field(default_factory=list)
    taxonomy_suggestion: TextAssistTaxonomySuggestion | None = None
    warnings_or_limitations: list[str] = Field(default_factory=list)
    confidence: Literal["LOW", "MEDIUM"] = "LOW"
    provenance: list[str] = Field(default_factory=list)
    needs_review: Literal[True] = True


TaxonomyRegistryLookup = Callable[
    [str, str],
    Mapping[str, Any] | None,
]


def validate_text_assist_taxonomy_suggestion_registry(
    suggestion: TextAssistTaxonomySuggestion,
    *,
    registry_lookup: TaxonomyRegistryLookup | None = None,
) -> dict[str, Any] | None:
    """Return the exact active registry row only when every binding agrees."""

    cluster = suggestion.cluster
    product_type_group = suggestion.product_type_group
    matched_scene_strategy_id = suggestion.matched_scene_strategy_id
    scene_coverage_status = suggestion.scene_coverage_status
    if not all(
        (
            cluster,
            product_type_group,
            matched_scene_strategy_id,
            scene_coverage_status,
        )
    ):
        return None
    if suggestion.registry_entry_key != f"{cluster}/{product_type_group}":
        return None

    lookup = registry_lookup or lookup_product_strategy_type_registry_entry
    registry_entry = lookup(cluster, product_type_group)
    if not registry_entry:
        return None
    expected_binding = {
        "cluster": cluster,
        "product_type_group": product_type_group,
        "registry_status": "ACTIVE",
        "matched_scene_strategy_id": matched_scene_strategy_id,
        "scene_coverage_status": scene_coverage_status,
    }
    if any(
        registry_entry.get(field) != expected
        for field, expected in expected_binding.items()
    ):
        return None
    return dict(registry_entry)


def _json_schema_types(field_schema: dict[str, Any]) -> tuple[str, ...]:
    json_types: list[str] = []
    direct_type = field_schema.get("type")
    if isinstance(direct_type, str):
        json_types.append(direct_type)
    for option in field_schema.get("anyOf") or []:
        if not isinstance(option, dict):
            continue
        option_type = option.get("type")
        if isinstance(option_type, str):
            json_types.append(option_type)
    return tuple(dict.fromkeys(json_types))


def _text_assist_schema_contract_prompt() -> str:
    schema = TextAssistEvidenceCompletion.model_json_schema()
    properties = schema.get("properties") or {}
    field_names = tuple(TextAssistEvidenceCompletion.model_fields)
    array_fields = tuple(
        field_name
        for field_name in field_names
        if isinstance(properties.get(field_name), dict)
        and properties[field_name].get("type") == "array"
        and isinstance(properties[field_name].get("items"), dict)
        and properties[field_name]["items"].get("type") == "string"
    )
    nullable_scalar_fields = tuple(
        field_name
        for field_name in field_names
        if isinstance(properties.get(field_name), dict)
        and set(_json_schema_types(properties[field_name])) == {"string", "null"}
    )
    confidence_values = tuple(
        value
        for value in properties["confidence"].get("enum") or []
        if isinstance(value, str)
    )
    canonical_example = json.dumps(
        TextAssistEvidenceCompletion().model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    array_rules = " ".join(
        f"{field_name} must always be an array of strings; "
        "use [] when unavailable."
        for field_name in array_fields
    )
    return (
        "Return exactly one JSON object and no markdown. "
        f"Return exactly the listed keys: {', '.join(field_names)}. "
        f"Canonical valid JSON example:\n{canonical_example}\n"
        f"{array_rules} "
        "Never return null or a scalar for an array field. "
        f"Nullable scalar fields may use null: {', '.join(nullable_scalar_fields)}. "
        "Only nullable scalar fields may use null. "
        'A single list item must still be wrapped in an array, for example '
        'warnings_or_limitations: ["warning text"], never a scalar. '
        f"confidence must be {' or '.join(confidence_values)}. "
        "needs_review must be true."
    )


class _SmartRegistrationCompletionResponse(ProductKnowledgeCompleteResponse):
    suggested_product_knowledge_summary: str | None = None
    suggested_benefits: list[str] = Field(default_factory=list)
    suggested_warnings_or_limitations: list[str] = Field(default_factory=list)
    evidence_field_status: dict[str, EvidenceCompletionFieldMetadata] = Field(
        default_factory=dict
    )


AI_FORM_ACCEPTED_FORMATS = [
    ".md with fenced ```json block",
    ".markdown with fenced ```json block",
    ".json raw object",
    ".JSON raw object",
    ".txt raw JSON text",
]

SOURCE_LANE_ALIASES = {
    "OWNED": "OWNED",
    "MANUAL": "MANUAL",
    "FASTMOSS": "FASTMOSS",
    "FASTMOSS_REFERENCE": "FASTMOSS",
    "TIKTOKSHOP": "TIKTOKSHOP",
    "TIKTOKSHOP_DRAFT": "TIKTOKSHOP",
    "UNKNOWN": "UNKNOWN",
    "UNKNOWN_REVIEW_REQUIRED": "UNKNOWN",
}


@dataclass
class _AIFormParseResult:
    parsed_json: dict[str, Any] | None = None
    strategy_used: str | None = None
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None


def _normalize_source_lane(value: str | None) -> str:
    normalized = str(value or "OWNED").strip().upper()
    return SOURCE_LANE_ALIASES.get(normalized, normalized or "OWNED")


def _infer_image_extension(filename: str | None) -> str:
    if filename and "." in filename:
        suffix = filename.rsplit(".", 1)[-1].strip().lower()
        if suffix:
            return suffix
    return "jpg"


def _persist_intake_image(image_base64: str | None, image_filename: str | None) -> str | None:
    if not image_base64:
        return None
    payload = image_base64.split(",", 1)[-1]
    data = base64.b64decode(payload)
    intake_dir = BASE_DIR / "data" / "product_registration" / "intake_images"
    intake_dir.mkdir(parents=True, exist_ok=True)
    dest = intake_dir / f"{uuid.uuid4().hex}.{_infer_image_extension(image_filename)}"
    dest.write_bytes(data)
    return str(dest)


def _normalize_completion_request(
    request: ProductKnowledgeCompleteRequest,
) -> ProductKnowledgeCompleteRequest:
    local_image_path = request.local_image_path
    if not local_image_path and request.image_base64:
        local_image_path = _persist_intake_image(request.image_base64, request.image_filename)

    normalized_package_notes = (
        request.package_notes
        or request.packaging_description
        or request.product_form_factor
    )
    source_url = request.source_url or request.product_url or request.tiktok_product_url or request.tiktok_shop_url
    product_url = request.product_url or request.source_url or request.tiktok_product_url
    tiktok_product_url = request.tiktok_product_url or (
        source_url if _normalize_source_lane(request.source_lane) == "TIKTOKSHOP" else None
    )

    return request.model_copy(
        update={
            "local_image_path": local_image_path,
            "source_url": source_url,
            "product_url": product_url,
            "tiktok_product_url": tiktok_product_url,
            "currency": request.currency or "MYR",
            "package_notes": normalized_package_notes,
        }
    )


def _resolve_extraction_status(request: ProductKnowledgeCompleteRequest) -> str | None:
    if _normalize_source_lane(request.source_lane) == "TIKTOKSHOP" and (
        request.tiktok_product_url or request.tiktok_shop_url or request.product_url or request.source_url
    ):
        return "NOT_IMPLEMENTED"
    return None


def complete_product_knowledge(
    request: ProductKnowledgeCompleteRequest,
    *,
    enable_text_assist: bool = False,
) -> ProductKnowledgeCompleteResponse:
    request = _normalize_completion_request(request)

    # 1. Fact Extraction from messy text
    extracted_facts = _extract_facts(request)

    # 2. Claim Analysis first so manual-owned sensitive lanes can influence taxonomy safely.
    claim_gate, claim_tokens, claim_risk, copy_safety = _analyze_claims(request, extracted_facts)
    text_assist_completion: TextAssistEvidenceCompletion | None = None
    text_assist_warnings: list[str] = []
    text_assist_provenance: list[str] = []
    if enable_text_assist and claim_gate == "CLAIM_SAFE":
        (
            text_assist_completion,
            text_assist_warnings,
            text_assist_provenance,
        ) = _complete_missing_evidence_with_text_assist(request)
    elif enable_text_assist:
        text_assist_warnings.append("TEXT_ASSIST_SKIPPED_CLAIM_GATE")
    taxonomy_candidate = _resolve_taxonomy_candidate(request, extracted_facts, claim_tokens)

    # 3. Build temporary product dictionary for inference
    temp_product = _build_temp_product(request, extracted_facts, taxonomy_candidate)

    # 4. Resolve Intelligence and Physics
    intelligence = resolve_product_intelligence_profile(temp_product)
    image_size_warning = _backfill_size_from_high_confidence_image_analysis(
        extracted_facts,
        dict(intelligence.get("image_analysis") or {}),
    )
    physics_seed = dict(temp_product)
    physics_seed["bosmax_product_family"] = intelligence.get("bosmax_product_family")
    physics = resolve_product_physics(product=physics_seed)

    # 5. Determine Completion Status
    completion_status, input_quality, missing_evidence = _evaluate_completion_status(request, extracted_facts, intelligence)

    # 6. Build Readiness
    readiness = _evaluate_mode_readiness(intelligence, physics, missing_evidence)
    
    # 7. Map suggested fields
    normalized_name = _build_normalized_name(request, extracted_facts)
    hook_cta = generate_registration_hook_cta(
        {
            "product_name": normalized_name or request.product_name,
            "benefits_text": request.benefits_text,
            "target_customer_text": request.target_customer_text,
            "usage_text": request.usage_text,
            "category": request.category,
            "claim_gate": claim_gate,
            "claim_tokens": claim_tokens,
            "copy_route": intelligence.get("copy_route"),
            "silo": taxonomy_candidate.get("silo"),
        }
    )
    evidence_candidates, evidence_field_status = (
        _resolve_evidence_completion_candidates(
            request,
            extracted_facts,
            hook_cta,
            text_assist_completion,
            text_assist_provenance,
        )
    )
    suggested_usp_list = list(evidence_candidates.get("usp_list") or [])
    completion_evidence_audit = audit_registration_evidence(
        request,
        product_family=str(intelligence.get("bosmax_product_family") or ""),
    )
    consistency = evaluate_registration_consistency(
        {
            "category": taxonomy_candidate.get("category"),
            "subcategory": taxonomy_candidate.get("subcategory"),
            "type": taxonomy_candidate.get("type"),
            "bosmax_product_family": intelligence.get("bosmax_product_family"),
            "physical_state": intelligence.get("physical_state"),
            "physics_class": physics.get("physics_class"),
            "copy_formula": intelligence.get("copy_formula"),
        }
    )
    taxonomy_repair: dict[str, Any] | None = None
    if text_assist_completion and text_assist_completion.taxonomy_suggestion:
        suggestion = text_assist_completion.taxonomy_suggestion
        deterministic_match = all(
            normalize_mapping_text(value)
            == normalize_mapping_text(taxonomy_candidate.get(field))
            for field, value in (
                ("category", suggestion.category),
                ("subcategory", suggestion.subcategory),
                ("type", suggestion.type),
            )
        )
        registry_entry = (
            validate_text_assist_taxonomy_suggestion_registry(suggestion)
            if deterministic_match
            else None
        )
        if registry_entry:
            taxonomy_repair = suggestion.model_dump(mode="json")
        else:
            text_assist_warnings.append(
                "TEXT_ASSIST_TAXONOMY_SUGGESTION_NOT_APPLIED_WITHOUT_REGISTRY_VALIDATION"
            )

    image_analysis = dict(intelligence.get("image_analysis") or {})
    warnings = list(intelligence.get("warnings", [])) + text_assist_warnings
    if image_size_warning:
        warnings.append(image_size_warning)
    extraction_status = _resolve_extraction_status(request)
    if extraction_status == "NOT_IMPLEMENTED":
        warnings.append("TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED")
        if "TIKTOKSHOP_MANUAL_COMPLETION_REQUIRED" not in missing_evidence:
            missing_evidence.append("TIKTOKSHOP_MANUAL_COMPLETION_REQUIRED")

    provenance = ["product_knowledge_completion_service:v2"] + text_assist_provenance
    human_review_fields = _identify_review_fields(intelligence, physics, claim_gate)
    human_review_fields.extend(
        field
        for field, metadata in evidence_field_status.items()
        if metadata.needs_review
    )
    human_review_fields = list(dict.fromkeys(human_review_fields))

    return _SmartRegistrationCompletionResponse(
        completion_status=completion_status,
        input_quality_status=input_quality,
        declared_evidence_summary=_build_evidence_summary(request, extracted_facts),
        declared_input_fields=_build_declared_input_fields(request),
        extracted_product_facts=extracted_facts,
        suggested_normalized_name=normalized_name,
        suggested_product_knowledge_summary=evidence_candidates.get(
            "product_knowledge_summary"
        ),
        suggested_benefits=list(evidence_candidates.get("benefits") or []),
        suggested_size_or_volume=evidence_candidates.get("size_or_volume"),
        suggested_package_notes=evidence_candidates.get("package_notes"),
        suggested_source_lane=request.source_lane,
        suggested_category=taxonomy_candidate.get("category"),
        suggested_subcategory=taxonomy_candidate.get("subcategory"),
        suggested_type=taxonomy_candidate.get("type"),
        suggested_materials_or_components=(
            text_assist_completion.materials_or_components
            if text_assist_completion
            and text_assist_completion.materials_or_components
            else completion_evidence_audit.sanitized_fields.get("materials_text")
        ),
        ingredients_applicability=completion_evidence_audit.decisions[
            "ingredients_or_materials"
        ].applicability,
        suggested_taxonomy_repair=taxonomy_repair,
        suggested_bosmax_product_family=intelligence.get("bosmax_product_family"),
        suggested_package_form=intelligence.get("package_form"),
        suggested_physical_state=intelligence.get("physical_state"),
        suggested_product_scale_class=intelligence.get("product_scale_class"),
        suggested_physics_class=physics.get("physics_class"),
        suggested_handling_profile=intelligence.get("handling_profile"),
        suggested_recommended_grip=physics.get("recommended_grip"),
        suggested_section_5_product_physics_prompt=physics.get("section_5_product_physics_prompt"),
        suggested_copy_route=intelligence.get("copy_route"),
        suggested_copy_formula=intelligence.get("copy_formula"),
        suggested_silo=taxonomy_candidate.get("silo"),
        suggested_trigger_id=taxonomy_candidate.get("trigger_id"),
        suggested_target_customer=evidence_candidates.get("target_customer"),
        suggested_usage_summary=evidence_candidates.get("usage_summary"),
        suggested_usp_list=suggested_usp_list[:5],
        suggested_warnings_or_limitations=list(
            evidence_candidates.get("warnings_or_limitations") or []
        ),
        suggested_hook_angles=list(hook_cta.get("hook_angles") or []),
        suggested_cta_angles=list(hook_cta.get("cta_angles") or []),
        evidence_field_status=evidence_field_status,
        claim_tokens=claim_tokens,
        claim_gate=claim_gate,
        claim_risk_level=claim_risk,
        copy_safety_notes=copy_safety,
        image_analysis_status=str(image_analysis.get("status") or "IMAGE_MISSING"),
        image_analysis_provider=str(image_analysis.get("provider") or "metadata_only"),
        image_analysis_visual_confidence=str(image_analysis.get("visual_confidence") or "NOT_VERIFIED"),
        image_analysis_warnings=list(image_analysis.get("warnings") or []),
        image_analysis_detected_package=image_analysis.get("detected_package"),
        image_analysis_detected_text=list(image_analysis.get("detected_text") or []),
        image_analysis_local_image_path=image_analysis.get("local_image_path"),
        image_analysis_image_url=image_analysis.get("image_url"),
        extraction_status=extraction_status,
        missing_required_evidence=missing_evidence,
        human_review_fields=human_review_fields,
        evidence_quality_status=completion_evidence_audit.status,
        evidence_quality_issues=completion_evidence_audit.issue_codes,
        consistency_status=consistency.status,
        consistency_issues=consistency.issue_codes,
        readiness_by_mode=readiness,
        provenance=provenance,
        warnings=list(
            dict.fromkeys(
                warnings
                + completion_evidence_audit.issue_codes
                + (
                    ["AFFILIATE_LANE_CONTAMINATION_RISK"]
                    if _normalize_source_lane(request.source_lane)
                    in ["FASTMOSS", "TIKTOKSHOP"]
                    else []
                )
            )
        ),
        errors=intelligence.get("errors", [])
    )


def _extract_facts(request: ProductKnowledgeCompleteRequest) -> dict[str, Any]:
    facts = {}
    combined_text = " ".join(filter(None, [
        request.product_name,
        request.product_knowledge_text,
        request.paste_anything_about_product,
        request.benefits_text,
        request.ingredients_text
    ]))
    
    # Simple regex for price
    price_match = re.search(r"(?:RM|Price|Harga)\s*[:=]?\s*(\d+(?:\.\d{2})?)", combined_text, re.I)
    if price_match:
        facts["price"] = float(price_match.group(1))
    elif request.price:
        facts["price"] = request.price
        
    _size_found = _extract_size_or_volume_from_text(combined_text)
    if _size_found:
        facts["size_or_volume"] = _size_found
    elif request.size_or_volume:
        facts["size_or_volume"] = request.size_or_volume
        
    # Extraction of USP/Benefits from text
    usp_list = []
    if request.benefits_text:
        # Already handled in main loop if needed, but let's look for keywords
        pass
        
    facts["usp_list"] = usp_list
    return facts


def _clean_suggestion_text(value: Any, *, limit: int = 800) -> str | None:
    normalized = " ".join(str(value or "").split()).strip(" -•*")
    return normalized[:limit] if normalized else None


def _clean_suggestion_list(value: Any, *, limit: int = 5) -> list[str]:
    if isinstance(value, str):
        raw_items = value.splitlines()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = _clean_suggestion_text(item, limit=240)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
        if len(normalized) >= limit:
            break
    return normalized


def _extract_qwen_usp_suggestions(
    request: ProductKnowledgeCompleteRequest,
    facts: dict[str, Any],
) -> list[str]:
    """Backward-compatible private helper routed through the generic adapter.

    Smart Registration no longer calls this Qwen-specific entry point. It remains
    only for older internal callers and fails closed unless text_assist is
    explicitly configured to Qwen.
    """
    if facts.get("usp_list") or request.benefits_text:
        return []
    if _normalize_source_lane(request.source_lane) not in {"OWNED", "MANUAL"}:
        return []
    source_text = "\n".join(
        str(item).strip()
        for item in (
            request.product_name,
            request.paste_anything_about_product,
            request.ingredients_text,
            request.usage_text,
            request.target_customer_text,
        )
        if str(item or "").strip()
    )
    status = ai_copy_provider_adapter.provider_status()
    if status.get("provider_id") != "qwen" or not status.get("configured"):
        return []
    try:
        payload = ai_copy_provider_adapter.complete_json(
            (
                "Extract only explicit USP candidates. Return strict JSON with "
                "one key named usp_list. No markdown and no invented claims."
            ),
            source_text,
        )
    except (AICopyProviderError, AICopyProviderNotConfigured):
        return []
    return _clean_suggestion_list(payload.get("usp_list"))


def _text_assist_source_payload(
    request: ProductKnowledgeCompleteRequest,
) -> dict[str, Any]:
    return {
        "product_name": request.product_name,
        "product_knowledge_text": request.product_knowledge_text,
        "benefits_text": request.benefits_text,
        "usage_text": request.usage_text,
        "target_customer_text": request.target_customer_text,
        "ingredients_text": request.ingredients_text,
        "warnings_text": request.warnings_text,
        "size_or_volume": request.size_or_volume,
        "package_notes": request.package_notes,
        "paste_anything_about_product": request.paste_anything_about_product,
        "category": request.category,
        "subcategory": request.subcategory,
        "type": request.type,
        "product_type": request.product_type,
        "product_type_id": request.product_type_id,
        "materials_text": request.materials_text,
        "source_lane": request.source_lane,
        "evidence_quality": {
            field: {
                "status": decision.status,
                "reason_codes": decision.reason_codes,
                "repair_action": decision.repair_action,
                "applicability": decision.applicability,
            }
            for field, decision in audit_registration_evidence(
                request,
                product_family=None,
            ).decisions.items()
        },
    }


def _has_sufficient_text_assist_evidence(payload: dict[str, Any]) -> bool:
    source_text = " ".join(
        str(payload.get(field) or "").strip()
        for field in (
            "product_knowledge_text",
            "benefits_text",
            "usage_text",
            "target_customer_text",
            "ingredients_text",
            "warnings_text",
            "paste_anything_about_product",
        )
    ).strip()
    return bool(str(payload.get("product_name") or "").strip()) and len(source_text) >= 20


def _normalize_text_assist_completion(
    completion: TextAssistEvidenceCompletion,
) -> TextAssistEvidenceCompletion:
    confidence = "MEDIUM" if completion.confidence == "HIGH" else completion.confidence
    updates: dict[str, Any] = {
            "product_knowledge_summary": _clean_suggestion_text(
                completion.product_knowledge_summary
            ),
            "benefits": _clean_suggestion_list(completion.benefits),
            "usage_summary": _clean_suggestion_text(completion.usage_summary),
            "target_customer": _clean_suggestion_text(completion.target_customer),
            "usp_list": _clean_suggestion_list(completion.usp_list),
            "size_or_volume": _clean_suggestion_text(
                completion.size_or_volume,
                limit=120,
            ),
            "package_notes": _clean_suggestion_text(
                completion.package_notes,
                limit=240,
            ),
            "warnings_or_limitations": _clean_suggestion_list(
                completion.warnings_or_limitations
            ),
            "materials_or_components": _clean_suggestion_text(
                completion.materials_or_components,
                limit=240,
            ),
            "confidence": confidence,
            "needs_review": True,
        }
    repair_field_map = {
        "product_knowledge_summary": "product_knowledge_summary",
        "benefits": "benefits",
        "usage_summary": "usage_summary",
        "target_customer": "target_customer",
        "materials_or_components": "materials_or_components",
        "size_or_volume": "size_or_volume",
        "package_notes": "package_notes",
        "warnings_or_limitations": "warnings_or_limitations",
    }
    for repair in completion.field_repairs:
        target = repair_field_map[repair.field]
        current = updates.get(target)
        if current not in (None, "", []):
            continue
        if target in {"benefits", "warnings_or_limitations"}:
            proposed = (
                repair.proposed_value
                if isinstance(repair.proposed_value, list)
                else [repair.proposed_value]
                if repair.proposed_value
                else []
            )
            updates[target] = _clean_suggestion_list(proposed)
        else:
            updates[target] = _clean_suggestion_text(repair.proposed_value)
    return completion.model_copy(update=updates)


def _text_assist_invalid_response_warnings(
    category: str,
    metadata: dict[str, object] | None = None,
) -> list[str]:
    safe_category = re.sub(r"[^A-Z0-9_]", "", str(category or "").upper())
    if not safe_category:
        safe_category = "SCHEMA_VALIDATION_FAILED"
    warnings = [
        "TEXT_ASSIST_INVALID_RESPONSE",
        f"TEXT_ASSIST_DIAGNOSTIC_{safe_category}",
    ]
    safe_metadata = metadata or {}
    for key, warning_prefix in (
        ("missing_keys", "TEXT_ASSIST_MISSING_KEYS"),
        ("unexpected_keys", "TEXT_ASSIST_UNEXPECTED_KEYS"),
        ("validation_field_paths", "TEXT_ASSIST_VALIDATION_FIELD_PATHS"),
        ("validation_type_metadata", "TEXT_ASSIST_VALIDATION_TYPES"),
    ):
        value = safe_metadata.get(key)
        if isinstance(value, (list, tuple, set)):
            names = sorted(
                {
                    re.sub(r"[^A-Za-z0-9_.-]", "", str(item))[:120]
                    for item in value
                    if str(item).strip()
                }
            )
            if names:
                warnings.append(f"{warning_prefix}:{','.join(names[:32])}")
    finish_reason = re.sub(
        r"[^A-Za-z0-9_.-]",
        "",
        str(safe_metadata.get("finish_reason") or ""),
    )[:64]
    if finish_reason:
        warnings.append(f"TEXT_ASSIST_FINISH_REASON:{finish_reason}")
    return warnings


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (int, float)):
        return "number"
    return "object"


def _classify_text_assist_validation_error(
    exc: ValidationError,
    raw_completion: dict[str, object],
) -> tuple[str, dict[str, list[str]]]:
    errors = exc.errors(include_url=False, include_input=False)
    field_paths = sorted(
        {
            ".".join(str(part) for part in error.get("loc") or ())
            for error in errors
            if error.get("loc")
        }
    )
    root_fields = {path.split(".", 1)[0] for path in field_paths}
    if "needs_review" in root_fields:
        category = "NEEDS_REVIEW_INVALID"
    elif "confidence" in root_fields or any(
        str(error.get("type") or "") == "literal_error" for error in errors
    ):
        category = "ENUM_INVALID"
    else:
        category = "FIELD_TYPE_INVALID"

    schema_properties = (
        TextAssistEvidenceCompletion.model_json_schema().get("properties") or {}
    )
    validation_type_metadata: set[str] = set()
    for error in errors:
        location = tuple(error.get("loc") or ())
        if not location:
            continue
        field_schema = schema_properties.get(str(location[0]))
        actual_value: object = raw_completion.get(str(location[0]))
        for path_part in location[1:]:
            if isinstance(field_schema, dict) and field_schema.get("type") == "array":
                field_schema = field_schema.get("items")
            elif isinstance(field_schema, dict) and field_schema.get("type") == "object":
                field_schema = (field_schema.get("properties") or {}).get(
                    str(path_part)
                )
            if isinstance(actual_value, list) and isinstance(path_part, int):
                actual_value = actual_value[path_part]
            elif isinstance(actual_value, dict):
                actual_value = actual_value.get(str(path_part))
        expected_types = (
            _json_schema_types(field_schema)
            if isinstance(field_schema, dict)
            else ()
        )
        expected_json_type = "-or-".join(expected_types) or "object"
        field_path = ".".join(str(part) for part in location)
        validation_error_type = re.sub(
            r"[^A-Za-z0-9_-]",
            "",
            str(error.get("type") or "validation_error"),
        )
        validation_type_metadata.add(
            f"{field_path}.expected-{expected_json_type}."
            f"actual-{_json_type_name(actual_value)}."
            f"error-{validation_error_type}"
        )
    return category, {
        "validation_field_paths": field_paths,
        "validation_type_metadata": sorted(validation_type_metadata),
    }


def _complete_missing_evidence_with_text_assist(
    request: ProductKnowledgeCompleteRequest,
) -> tuple[TextAssistEvidenceCompletion | None, list[str], list[str]]:
    status = ai_copy_provider_adapter.provider_status()
    if not bool(status.get("configured")):
        return None, ["TEXT_ASSIST_NOT_CONFIGURED"], []

    source_payload = _text_assist_source_payload(request)
    if not _has_sufficient_text_assist_evidence(source_payload):
        return None, ["TEXT_ASSIST_SKIPPED_INSUFFICIENT_SOURCE_EVIDENCE"], []

    provider_id = str(status.get("provider_id") or "unknown")
    model_id = str(status.get("model_id") or "unknown")
    provider_provenance = [
        f"text_assist:{provider_id}:{model_id}:review_only",
    ]
    system_prompt = (
        "You create review-only product evidence suggestions from supplied source text. "
        f"{_text_assist_schema_contract_prompt()} "
        "Never invent medical, "
        "cure, guaranteed-result, permanence, regulatory, platform-approval, safety, or "
        "performance claims. Size and package facts must appear explicitly in the source. "
    )
    user_prompt = (
        "Complete missing fields and repair only fields explicitly marked invalid or "
        "placeholder by evidence_quality. Verified exact-source fields are immutable. "
        "Every repair must state FILL_MISSING or REPAIR_INVALID_OR_PLACEHOLDER, the "
        "evidence used, confidence, reason, and needs_review=true. Ingredients may be "
        "NOT_APPLICABLE for non-consumable products; use materials_or_components instead. "
        "Taxonomy suggestions are review-only and must name an existing registry_entry_key "
        "with the exact cluster, product_type_group, matched_scene_strategy_id, and "
        "scene_coverage_status from that registry row. "
        "JSON source evidence:\n"
        f"{json.dumps(source_payload, ensure_ascii=False, sort_keys=True)}"
    )

    try:
        raw_completion = ai_copy_provider_adapter.complete_json(
            system_prompt,
            user_prompt,
        )
        if not isinstance(raw_completion, dict):
            return (
                None,
                _text_assist_invalid_response_warnings("NON_OBJECT_JSON"),
                [],
            )
        expected_keys = set(TextAssistEvidenceCompletion.model_fields)
        optional_extension_keys = {
            "materials_or_components",
            "ingredients_applicability",
            "field_repairs",
            "taxonomy_suggestion",
        }
        actual_keys = set(raw_completion)
        missing_keys = sorted(
            (expected_keys - optional_extension_keys) - actual_keys
        )
        unexpected_keys = sorted(actual_keys - expected_keys)
        if missing_keys:
            return (
                None,
                _text_assist_invalid_response_warnings(
                    "MISSING_KEYS",
                    {
                        "missing_keys": missing_keys,
                        "unexpected_keys": unexpected_keys,
                    },
                ),
                [],
            )
        if unexpected_keys:
            return (
                None,
                _text_assist_invalid_response_warnings(
                    "UNEXPECTED_KEYS",
                    {"unexpected_keys": unexpected_keys},
                ),
                [],
            )
        completion = _normalize_text_assist_completion(
            TextAssistEvidenceCompletion.model_validate(raw_completion)
        )
    except AICopyProviderNotConfigured:
        return None, ["TEXT_ASSIST_NOT_CONFIGURED"], []
    except AICopyProviderError as exc:
        LOGGER.warning("Smart Registration text_assist failed closed: %s", exc.code)
        if exc.code == ERR_RESPONSE_INVALID:
            return (
                None,
                _text_assist_invalid_response_warnings(
                    exc.diagnostic_category or "SCHEMA_VALIDATION_FAILED",
                    exc.diagnostic_metadata,
                ),
                [],
            )
        return None, ["TEXT_ASSIST_CALL_FAILED"], []
    except ValidationError as exc:
        LOGGER.warning("Smart Registration text_assist returned schema-invalid JSON")
        category, metadata = _classify_text_assist_validation_error(
            exc,
            raw_completion,
        )
        return (
            None,
            _text_assist_invalid_response_warnings(category, metadata),
            [],
        )
    except Exception as exc:
        LOGGER.warning(
            "Smart Registration text_assist failed closed with an unexpected error: %s",
            type(exc).__name__,
        )
        return None, ["TEXT_ASSIST_CALL_FAILED"], []

    ai_claim_gate, _, _, _ = _analyze_claims(
        ProductKnowledgeCompleteRequest(
            product_name=request.product_name,
            product_knowledge_text=completion.product_knowledge_summary,
            benefits_text="\n".join(completion.benefits),
            usage_text=completion.usage_summary,
            target_customer_text=completion.target_customer,
            warnings_text="\n".join(completion.warnings_or_limitations),
            paste_anything_about_product="\n".join(completion.usp_list),
            source_lane=request.source_lane,
        ),
        {},
    )
    if ai_claim_gate != "CLAIM_SAFE":
        return None, ["TEXT_ASSIST_UNSAFE_SUGGESTION_DISCARDED"], []

    return completion, ["TEXT_ASSIST_SUGGESTIONS_REQUIRE_REVIEW"], provider_provenance


def _field_metadata(
    status: str,
    *,
    confidence: str,
    provenance: list[str],
) -> EvidenceCompletionFieldMetadata:
    return EvidenceCompletionFieldMetadata(
        status=status,
        confidence=confidence,
        provenance=provenance,
        needs_review=status != "EXACT_SOURCE_EVIDENCE",
    )


def _resolve_evidence_completion_candidates(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
    hook_cta: dict[str, Any],
    text_assist: TextAssistEvidenceCompletion | None,
    text_assist_provenance: list[str],
) -> tuple[dict[str, Any], dict[str, EvidenceCompletionFieldMetadata]]:
    evidence_audit = audit_registration_evidence(
        request,
        product_family=None,
    )
    request = request.model_copy(update=evidence_audit.sanitized_fields)
    candidates: dict[str, Any] = {}
    metadata: dict[str, EvidenceCompletionFieldMetadata] = {}
    ai_confidence = text_assist.confidence if text_assist else "LOW"

    def set_field(
        field: str,
        value: Any,
        status: str,
        confidence: str,
        provenance: list[str],
    ) -> None:
        candidates[field] = value
        metadata[field] = _field_metadata(
            status,
            confidence=confidence,
            provenance=provenance,
        )

    declared_summary = _clean_suggestion_text(request.product_knowledge_text)
    if declared_summary:
        set_field(
            "product_knowledge_summary",
            declared_summary,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:product_knowledge_text"],
        )
    elif text_assist and text_assist.product_knowledge_summary:
        set_field(
            "product_knowledge_summary",
            text_assist.product_knowledge_summary,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )

    declared_benefits = _clean_suggestion_list(request.benefits_text)
    if declared_benefits:
        set_field(
            "benefits",
            declared_benefits,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:benefits_text"],
        )
    elif text_assist and text_assist.benefits:
        set_field(
            "benefits",
            text_assist.benefits,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )

    declared_usage = _clean_suggestion_text(request.usage_text)
    if declared_usage:
        set_field(
            "usage_summary",
            declared_usage,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:usage_text"],
        )
    elif text_assist and text_assist.usage_summary:
        set_field(
            "usage_summary",
            text_assist.usage_summary,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )
    elif _clean_suggestion_text(hook_cta.get("usage_summary")):
        set_field(
            "usage_summary",
            _clean_suggestion_text(hook_cta.get("usage_summary")),
            "SYSTEM_INFERRED",
            "LOW",
            ["registration_hook_cta_generation_service:v1"],
        )

    declared_target = _clean_suggestion_text(request.target_customer_text)
    if declared_target:
        set_field(
            "target_customer",
            declared_target,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:target_customer_text"],
        )
    elif text_assist and text_assist.target_customer:
        set_field(
            "target_customer",
            text_assist.target_customer,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )
    elif _clean_suggestion_text(hook_cta.get("target_customer")):
        set_field(
            "target_customer",
            _clean_suggestion_text(hook_cta.get("target_customer")),
            "SYSTEM_INFERRED",
            "LOW",
            ["registration_hook_cta_generation_service:v1"],
        )

    declared_usp = declared_benefits or _clean_suggestion_list(
        extracted_facts.get("usp_list")
    )
    if declared_usp:
        set_field(
            "usp_list",
            declared_usp,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:benefits_text"],
        )
    elif text_assist and (text_assist.usp_list or text_assist.benefits):
        set_field(
            "usp_list",
            text_assist.usp_list or text_assist.benefits,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )
    else:
        candidates["usp_list"] = []

    exact_size = _clean_suggestion_text(
        extracted_facts.get("size_or_volume") or request.size_or_volume,
        limit=120,
    )
    if exact_size:
        set_field(
            "size_or_volume",
            exact_size,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["deterministic_extraction:size_or_volume"],
        )
    elif text_assist and text_assist.size_or_volume:
        set_field(
            "size_or_volume",
            text_assist.size_or_volume,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )
    else:
        set_field(
            "size_or_volume",
            "N/A",
            "NOT_AVAILABLE",
            "NOT_APPLICABLE",
            ["product_knowledge_completion_service:deterministic_fallback"],
        )

    exact_package = _clean_suggestion_text(request.package_notes, limit=240)
    if exact_package:
        set_field(
            "package_notes",
            exact_package,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:package_notes"],
        )
    elif text_assist and text_assist.package_notes:
        set_field(
            "package_notes",
            text_assist.package_notes,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )
    else:
        set_field(
            "package_notes",
            "NOT_AVAILABLE",
            "NOT_AVAILABLE",
            "NOT_APPLICABLE",
            ["product_knowledge_completion_service:deterministic_fallback"],
        )

    exact_warnings = _clean_suggestion_list(request.warnings_text)
    if exact_warnings:
        set_field(
            "warnings_or_limitations",
            exact_warnings,
            "EXACT_SOURCE_EVIDENCE",
            "HIGH",
            ["declared_evidence:warnings_text"],
        )
    elif text_assist and text_assist.warnings_or_limitations:
        set_field(
            "warnings_or_limitations",
            text_assist.warnings_or_limitations,
            "AI_SUGGESTED",
            ai_confidence,
            text_assist_provenance,
        )
    else:
        set_field(
            "warnings_or_limitations",
            ["NOT_AVAILABLE"],
            "NOT_AVAILABLE",
            "NOT_APPLICABLE",
            ["product_knowledge_completion_service:deterministic_fallback"],
        )

    return candidates, metadata


_SIZE_PATTERNS = [
    r"\d+\s*[x×]\s*\d+(?:\s*cm)?",
    r'bidang\s*\d+(?:["\']|-\d+(?:\s*dan\s*\d+(?:-\d+)?)?)?',
    r"\d+\s*(?:ft|cm|g|ml)\s*[-/]\s*\d+\s*(?:ft|cm|g|ml)",
    r"\d+\s*(?:liter|litre|kg)\s*/\s*\d+\s*(?:liter|litre|kg)",
    r"\d+(?:\.\d+)?\s*(?:ml|l(?:iter|itre)?|g|kg|cm|mm|m(?:eter|etre)?|ft|inch|oz|w(?:att)?)",
    r"\d+\s*(?:pcs|pieces|pc|tablets?|sachets?|kapsul|capsules?|pack|packs|pasang|biji|keping|helai|bottles?|cookies?|sheets?|kluster|cluster(?:s)?)",
    r"(?:XS|S|M|L|XL|XXL|XXXL|\dXL)(?:\s*[-/]\s*(?:XS|S|M|L|XL|XXL|XXXL|\dXL))+",
    r"\b(?:XS|S|M|L|XL|XXL|XXXL|\dXL)(?:\s+(?:XS|S|M|L|XL|XXL|XXXL|\dXL)){2,}\b",
    r"\b(?:SML|free\s*size|freesize|saiz\s*bebas|one\s*size)\b",
]


def _extract_size_or_volume_from_text(text: str | None) -> str | None:
    haystack = str(text or "").strip()
    if not haystack:
        return None
    for pattern in _SIZE_PATTERNS:
        match = re.search(pattern, haystack, re.I)
        if match:
            return match.group(0).strip()
    return None


def _backfill_size_from_high_confidence_image_analysis(
    extracted_facts: dict[str, Any],
    image_analysis: dict[str, Any],
) -> str | None:
    if extracted_facts.get("size_or_volume"):
        return None
    if str(image_analysis.get("status") or "") != "ANALYZED":
        return None
    if str(image_analysis.get("visual_confidence") or "") != "HIGH":
        return None

    explicit_size = _extract_size_or_volume_from_text(
        image_analysis.get("detected_size_text"),
    )
    if explicit_size:
        extracted_facts["size_or_volume"] = explicit_size
        return "SIZE_OR_VOLUME_FROM_IMAGE_OCR_HIGH_CONFIDENCE"

    detected_text = " ".join(
        str(item).strip()
        for item in list(image_analysis.get("detected_text") or [])
        if str(item).strip()
    )
    inferred_size = _extract_size_or_volume_from_text(detected_text)
    if inferred_size:
        extracted_facts["size_or_volume"] = inferred_size
        return "SIZE_OR_VOLUME_FROM_IMAGE_OCR_HIGH_CONFIDENCE"
    return None


def _build_temp_product(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
    taxonomy_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = _build_normalized_name(request, extracted_facts) or "Unknown Manual Product"
    taxonomy_candidate = taxonomy_candidate or {}
    return {
        "raw_product_title": name,
        "product_display_name": name,
        "source": _normalize_source_lane(request.source_lane) or "MANUAL",
        "category": taxonomy_candidate.get("category") or request.category,
        "subcategory": taxonomy_candidate.get("subcategory") or request.subcategory,
        "type": (
            taxonomy_candidate.get("type")
            or request.type
            or request.product_type
            or request.product_type_id
        ),
        "price": extracted_facts.get("price") or request.price,
        "size_or_volume": extracted_facts.get("size_or_volume") or request.size_or_volume,
        "ingredients": request.ingredients_text,
        "materials": request.materials_text,
        "benefits": request.benefits_text,
        "usage": request.usage_text,
        "warnings": request.warnings_text,
        "target_customer": request.target_customer_text,
        "product_knowledge_text": request.product_knowledge_text,
        "package_notes": request.package_notes,
        "image_notes": request.image_notes,
        "product_form_factor": request.product_form_factor,
        "packaging_description": request.packaging_description,
        "currency": request.currency,
        "commission_amount": request.commission_amount,
        "commission_rate": request.commission_rate,
        "image_url": request.image_url,
        "local_image_path": request.local_image_path,
        "source_url": request.source_url or request.product_url,
        "tiktok_product_url": request.tiktok_product_url or request.tiktok_shop_url,
    }


def _build_normalized_name(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
) -> str | None:
    base_name = (request.product_name or "").strip()
    if not base_name:
        return None
    size = str(extracted_facts.get("size_or_volume") or request.size_or_volume or "").strip()
    if not size:
        return base_name
    if normalize_mapping_text(size) in normalize_mapping_text(base_name):
        return base_name
    return f"{base_name} {size}".strip()


def _build_declared_input_fields(request: ProductKnowledgeCompleteRequest) -> dict[str, Any]:
    payload = request.model_dump()
    return {
        key: value
        for key, value in payload.items()
        if key not in {"image_base64"} and value not in (None, "", [], {})
    }


def _contains_any_normalized(haystack: str, keywords: list[str]) -> bool:
    return any(normalize_mapping_text(keyword) in haystack for keyword in keywords)


def _size_evidence_is_soft_for_context(
    request: ProductKnowledgeCompleteRequest,
    intelligence: dict[str, Any],
) -> bool:
    # Size/volume is still required for measurable consumables.
    # The carve-outs below are intentionally narrow for decorative cosmetics
    # and durable accessory-like items where title truth does not depend on ml/g.
    size_exempt_families = {
        "fashion_apparel",
        "fashion_modestwear",
        "fashion_sportswear",
        "APPAREL_SLEEPWEAR",
        "ACCESSORY_SMALL_ITEM",
        "stationery_paper",
        "HOME_TEXTILE",
        "HOUSEHOLD_STORAGE_ORGANIZER",
        "electronics_wearable",
    }
    size_exempt_category_substrings = {
        "fashion",
        "muslim fashion",
        "womenswear",
        "menswear",
        "apparel",
        "clothing",
        "books",
        "stationery",
        "home decor",
        "accessories",
        "phones",
        "electronics",
    }
    family = str(intelligence.get("bosmax_product_family") or "")
    category_lower = normalize_mapping_text(request.category or "")
    if family in size_exempt_families:
        return True
    if any(sub in category_lower for sub in size_exempt_category_substrings):
        return True

    context = normalize_mapping_text(
        " ".join(
            filter(
                None,
                [
                    request.product_name,
                    request.product_knowledge_text,
                    request.paste_anything_about_product,
                    request.benefits_text,
                    request.ingredients_text,
                    request.package_notes,
                    request.packaging_description,
                ],
            )
        )
    )
    decorative_makeup_keywords = [
        "brow gel",
        "eyebrow",
        "eyeshadow",
        "mascara",
        "maskara",
        "lipstick",
        "lipstik",
        "lip tint",
        "lip gloss",
        "foundation",
        "concealer",
        "blusher",
        "powder blusher",
    ]
    if family == "BEAUTY_PERSONAL_CARE" and _contains_any_normalized(
        context, decorative_makeup_keywords
    ):
        return True

    durable_accessory_keywords = [
        "car phone holder",
        "phone holder",
        "phone mount",
        "dashboard mount",
        "windshield mount",
        "suction cup",
    ]
    if family in {
        "AUTO_TOOL_GENERAL",
        "UNKNOWN_REVIEW_REQUIRED",
        "ACCESSORY_SMALL_ITEM",
        "electronics_wearable",
    } and _contains_any_normalized(context, durable_accessory_keywords):
        return True
    return False


def _resolve_taxonomy_candidate(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
    claim_tokens: list[str],
) -> dict[str, Any]:
    mapping_seed_text = " ".join(
        filter(
            None,
            [
                request.product_name,
                request.product_knowledge_text,
                request.benefits_text,
                request.usage_text,
                request.target_customer_text,
                request.paste_anything_about_product,
            ],
        )
    ).strip()
    normalized_name = _build_normalized_name(request, extracted_facts) or request.product_name or "Unknown Manual Product"
    base_product = {
        "raw_product_title": mapping_seed_text or normalized_name,
        "product_display_name": normalized_name,
        "product_short_name": normalized_name,
        "source": _normalize_source_lane(request.source_lane) or "MANUAL",
        "category": request.category,
        "subcategory": request.subcategory,
        "type": request.type or request.product_type or request.product_type_id,
    }
    mapping = resolve_product_mapping(product=base_product, source_hint=_normalize_source_lane(request.source_lane))
    candidate = {
        "category": request.category or mapping.get("category") or None,
        "subcategory": request.subcategory or mapping.get("subcategory") or None,
        "type": (
            request.type
            or request.product_type
            or request.product_type_id
            or mapping.get("type")
            or None
        ),
        "silo": mapping.get("silo") or None,
        "trigger_id": mapping.get("trigger_id") or None,
    }
    if (
        candidate["category"] == "Textiles & Soft Furnishings"
        and not candidate["subcategory"]
    ):
        candidate["subcategory"] = "Household Textiles"
    if (
        candidate["category"] == "Textiles & Soft Furnishings"
        and not candidate["type"]
        and _contains_any_normalized(
            normalize_mapping_text(request.product_name),
            ["langsir", "curtain"],
        )
    ):
        candidate["type"] = "Curtains"

    combined_text = normalize_mapping_text(
        " ".join(
            filter(
                None,
                [
                    request.product_name,
                    request.product_knowledge_text,
                    request.benefits_text,
                    request.usage_text,
                    request.target_customer_text,
                    request.paste_anything_about_product,
                ],
            )
        )
    )
    male_health_tokens = {
        "tenaga batin",
        "batin lelaki",
        "bahagian intim",
        "ketegangan",
        "kelelakian",
        "stamina lelaki",
        "prestasi fizikal lelaki",
        "otot kelelakian",
        "male_health_sensitive",
    }
    female_health_tokens = {
        "jamu perapat",
        "jamu wanita",
        "kewanitaan",
        "miss v",
        "faraj",
        "vagina",
        "keputihan",
        "bau",
        "gatal",
        "rapat",
        "ketat",
        "anjal",
        "postpartum",
        "selepas bersalin",
        "intimate",
        "feminine hygiene",
        "feminine care",
        "female_health_sensitive",
    }
    owned_lane = _normalize_source_lane(request.source_lane) in {"OWNED", "MANUAL"}
    if owned_lane and (
        any(token in male_health_tokens for token in claim_tokens)
        or any(token in combined_text for token in male_health_tokens if token != "male_health_sensitive")
    ):
        candidate.update(
            {
                "category": "Health",
                "subcategory": "Supplements",
                "type": "Male Health",
                "silo": "health_supp_stealth_01",
                "trigger_id": "EGO_01",
            }
        )
    elif owned_lane and (
        any(token in female_health_tokens for token in claim_tokens)
        or any(token in combined_text for token in female_health_tokens if token != "female_health_sensitive")
    ):
        candidate.update(
            {
                "category": "Health",
                "subcategory": "Feminine Care",
                "type": "Female Health",
                "silo": "female_health_stealth_01",
                "trigger_id": "FEMALE_01",
            }
        )
    return candidate


def _evaluate_completion_status(
    request: ProductKnowledgeCompleteRequest, 
    facts: dict[str, Any],
    intelligence: dict[str, Any]
) -> tuple[str, str, list[str]]:
    missing = []
    if not request.product_name:
        missing.append("PRODUCT_NAME")
    if not request.product_knowledge_text and not request.paste_anything_about_product:
        missing.append("PRODUCT_DESCRIPTION_OR_KNOWLEDGE")
    if not _size_evidence_is_soft_for_context(request, intelligence) and not facts.get("size_or_volume") and not request.size_or_volume:
        missing.append("SIZE_OR_VOLUME_EVIDENCE")
    if request.price is None:
        missing.append("PRICE_EVIDENCE")
    if not request.currency:
        missing.append("CURRENCY_EVIDENCE")
    if request.commission_amount is None and (
        not request.commission_rate or str(request.commission_rate).strip().upper() == "UNKNOWN"
    ):
        missing.append("COMMISSION_EVIDENCE")
    if not request.commission_rate or str(request.commission_rate).strip().upper() == "UNKNOWN":
        missing.append("COMMISSION_RATE_EVIDENCE")
    
    if intelligence.get("bosmax_product_family") == "UNKNOWN_REVIEW_REQUIRED":
        missing.append("CLEAR_PRODUCT_FAMILY_INFERENCE")

    if not missing:
        return "COMPLETION_READY", "SUFFICIENT", []
    
    status = "NEEDS_REVIEW"
    quality = "PARTIAL" if len(missing) < 3 else "POOR"
    return status, quality, missing


def _analyze_claims(request: ProductKnowledgeCompleteRequest, facts: dict[str, Any]) -> tuple[str, list[str], str, str]:
    found_blocked, found_review, _warnings = evaluate_product_claims(
        {
            "product_name": request.product_name,
            "product_knowledge_text": request.product_knowledge_text,
            "benefits_text": request.benefits_text,
            "usage_text": request.usage_text,
            "target_customer_text": request.target_customer_text,
            "ingredients_text": request.ingredients_text,
            "warnings_text": request.warnings_text,
            "package_notes": request.package_notes,
            "paste_anything_about_product": request.paste_anything_about_product,
            "category": request.category,
            "subcategory": request.subcategory,
            "type": request.type,
            "product_type": request.product_type,
        }
    )
    
    all_tokens = list(set(found_blocked + found_review))
    
    if found_blocked:
        return "CLAIM_BLOCKED", all_tokens, "CRITICAL", "Medical cure or hard claims detected. NOT ALLOWED for direct copy."
    
    if found_review:
        return "CLAIM_REVIEW_REQUIRED", all_tokens, "HIGH", "Sensitive health/beauty claims detected. Requires human verification."
        
    return "CLAIM_SAFE", [], "LOW", "No high-risk claims detected in text."


def _evaluate_mode_readiness(intelligence: dict[str, Any], physics: dict[str, Any], missing_evidence: list[str]) -> dict[str, ModeReadiness]:
    readiness = {}
    
    # Registration readiness
    reg_status = "READY" if not missing_evidence else "NEEDS_EVIDENCE"
    readiness["registration"] = ModeReadiness(
        status=reg_status,
        detail="Enough structured data for draft registration" if reg_status == "READY" else "Requires more evidence for canonical truth",
        missing_evidence=missing_evidence
    )
    
    # Asset generator readiness
    asset_status = "READY" if physics.get("section_5_product_physics_prompt") else "NEEDS_PHYSICS"
    readiness["product_asset_generator"] = ModeReadiness(
        status=asset_status,
        detail="Physics profile derived successfully" if asset_status == "READY" else "Missing physical evidence for prompt generation",
        missing_evidence=[m for m in missing_evidence if "PHYSICS" in m or "SIZE" in m]
    )

    image_analysis = dict(intelligence.get("image_analysis") or {})
    has_image_reference = bool(image_analysis.get("image_url") or image_analysis.get("local_image_path"))
    image_missing = [] if has_image_reference else ["IMAGE_REFERENCE_REQUIRED"]
    t2v_status = "READY" if not missing_evidence else "NEEDS_REVIEW"
    image_mode_status = "READY" if has_image_reference else "IMAGE_REFERENCE_REQUIRED"

    readiness["T2V"] = ModeReadiness(
        status=t2v_status,
        detail="Identity and taxonomy are sufficient for text-first video drafting." if t2v_status == "READY" else "Requires reviewed taxonomy/claims or missing evidence resolution.",
        missing_evidence=missing_evidence,
    )
    readiness["IMG"] = ModeReadiness(
        status=image_mode_status,
        detail="Image reference supplied." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for visual/media generation lanes.",
        missing_evidence=image_missing,
    )
    readiness["I2V"] = ModeReadiness(
        status=image_mode_status,
        detail="Image reference supplied for ingredient/reference-driven video." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for ingredient/reference-driven video.",
        missing_evidence=image_missing,
    )
    readiness["F2V"] = ModeReadiness(
        status=image_mode_status,
        detail="Image reference supplied for frames-first video." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for frames-first video.",
        missing_evidence=image_missing,
    )
    readiness["Ingredients"] = ModeReadiness(
        status=image_mode_status,
        detail="Ingredient lane has required reference." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for Ingredients lane.",
        missing_evidence=image_missing,
    )
    readiness["Frames"] = ModeReadiness(
        status=image_mode_status,
        detail="Frames lane has required reference." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for Frames lane.",
        missing_evidence=image_missing,
    )
    readiness["prompt_generation"] = ModeReadiness(
        status="READY" if t2v_status == "READY" else "NEEDS_REVIEW",
        detail="Prompt generation may proceed with safe identity fields only." if t2v_status == "READY" else "Prompt generation remains review-gated until taxonomy/claims evidence is settled.",
        missing_evidence=missing_evidence,
    )
    
    return readiness


def _build_evidence_summary(request: ProductKnowledgeCompleteRequest, facts: dict[str, Any]) -> str:
    summary = []
    if request.product_name:
        summary.append(f"Name: {request.product_name}")
    if facts.get("price"):
        summary.append(f"Price: RM{facts['price']}")
    if facts.get("size_or_volume"):
        summary.append(f"Size: {facts['size_or_volume']}")
    if request.source_lane:
        summary.append(f"Source: {request.source_lane}")
    if request.currency:
        summary.append(f"Currency: {request.currency}")
    if request.commission_amount is not None:
        summary.append(f"Commission Amount: {request.commission_amount}")
    if request.commission_rate:
        summary.append(f"Commission Rate: {request.commission_rate}")
    if request.product_url or request.source_url:
        summary.append(f"Source URL: {request.product_url or request.source_url}")
    if request.image_url or request.local_image_path:
        summary.append("Image Evidence: PRESENT")
    return " | ".join(summary)


def _identify_review_fields(intelligence: dict[str, Any], physics: dict[str, Any], claim_gate: str) -> list[str]:
    fields = []
    if intelligence.get("confidence") == "LOW":
        fields.extend(["category", "subcategory", "type", "bosmax_product_family"])
    if claim_gate != "CLAIM_SAFE":
        fields.append("claims")
    if not physics.get("section_5_product_physics_prompt"):
        fields.append("physics_profile")
    return list(set(fields))


# --- AI-Assisted Form Pack ---

AI_FORM_TEMPLATE_V1 = """# BOSMAX Product Knowledge Intake Form v1.0

This form is designed to be completed by an AI assistant during a user interview.
The goal is to normalize unstructured product information into a structured JSON block.

## Instructions for AI Assistant:
1. Interview the user to collect all required and recommended evidence fields.
2. Ask follow-up questions before filling missing facts. Do NOT invent data.
3. Use `null` or `"UNKNOWN"` for missing commercial, image, or source evidence.
4. Detect risky medical/health/beauty/sexual claims and preserve them in `claim_safety_notes` for audit.
5. Keep safe rewrite suggestions separate from risky original wording.
6. When complete, return valid raw JSON matching the schema below. Markdown wrapper is optional.

## Required Checklist:
- Product Identity (Name, Lane)
- Product Specs (Price, Currency, Commission, Size, Volume, Packaging)
- Source Evidence (Product URL, Source URL, TikTok URLs)
- Image Evidence (Image URL or separate uploaded image notes)
- Product Knowledge (Description, Benefits, Usage, Ingredients, Warnings)
- Target Customer
- Evidence/Inference notes

## Structured Data (DO NOT MODIFY SCHEMA):

```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "completion_mode": "AI_ASSISTED_USER_INTERVIEW",
  "source_lane": "OWNED",
  "product_name": "",
  "product_knowledge_text": "",
  "benefits_text": "",
  "usage_text": "",
  "target_customer_text": "",
  "ingredients_text": "",
  "warnings_text": "",
  "price": null,
  "currency": "MYR",
  "commission_amount": null,
  "commission_rate": "UNKNOWN",
  "size_or_volume": "",
  "package_notes": "",
  "image_url": "UNKNOWN",
  "product_url": "UNKNOWN",
  "source_url": "UNKNOWN",
  "tiktok_product_url": "UNKNOWN",
  "tiktok_shop_url": "UNKNOWN",
  "image_notes": "",
  "product_form_factor": "",
  "packaging_description": "",
  "paste_anything_about_product": "",
  "evidence_notes": {
    "what_user_confirmed": [],
    "what_ai_inferred": [],
    "unknown_or_unverified": [],
    "questions_still_unanswered": []
  },
  "claim_safety_notes": {
    "possible_claim_tokens": [],
    "risky_claims_detected": [],
    "safe_rewording_suggestions": []
  },
  "user_review_status": "USER_REVIEW_REQUIRED"
}
```
"""

AI_COACHING_PROMPT_V1 = """You are the BOSMAX Product Intelligence Coach. Your mission is to interview the user until the Smart Registration intake has enough defensible evidence for governed completion.

I will provide you with a Markdown template called "BOSMAX_PRODUCT_KNOWLEDGE_INTAKE_FORM_v1.md".

Your process:
1. Ask for the product name first.
2. Then collect this evidence, asking follow-up questions until each item is user-confirmed, AI-inferred, or explicitly unknown:
   - product type/category if known
   - size/volume/variant
   - selling price
   - currency (default MYR unless the user states otherwise)
   - commission amount
   - commission rate
   - product URL or source URL
   - TikTok product URL or TikTok shop URL
   - product image URL or instruction that the image will be attached separately
   - package notes or visible packaging description
   - ingredients or materials
   - benefits or USP
   - usage or cara guna
   - warnings, pantang, allergy, age restrictions
   - target customer
   - claim-sensitive words used by seller or user
   - safe copy rewrite suggestions
3. If the user provides messy text such as chats, descriptions, or notes, extract facts carefully and list them in `what_ai_inferred`.
4. NEVER hallucinate facts. Use `UNKNOWN` or `null` for missing price, commission, image, or source data.
5. Preserve risky claim tokens for audit. Do NOT convert risky claims into safe verified claims.
6. For male-health or female-health sensitive products, set the posture to `CLAIM_REVIEW_REQUIRED` or `CLAIM_BLOCKED` in your reasoning notes.
7. Avoid explicit unsafe anatomy, tightening, enlargement, or sexual performance terms in safe copy rewrites.
8. Keep risky original claims under `risky_claims_detected` and put safer alternatives under `safe_rewording_suggestions`.
9. When enough evidence is gathered, output final valid raw JSON matching the template exactly. No markdown wrapper unless the user explicitly asks for it.
10. The JSON must be upload-ready for BOSMAX Smart Registration.

Begin the interview now by asking: What product are we registering today?
"""

def get_ai_form_template() -> dict[str, str]:
    return {
        "filename": "BOSMAX_PRODUCT_KNOWLEDGE_INTAKE_FORM_v1.md",
        "content_type": "text/markdown",
        "content": AI_FORM_TEMPLATE_V1
    }

def get_ai_coaching_prompt() -> str:
    return AI_COACHING_PROMPT_V1

def import_ai_form(
    file_content: str,
    file_name: str,
    content_type: str | None = None,
) -> AIFormImportResponse:
    import_id = str(uuid.uuid4())
    detected_extension = _detect_extension(file_name)
    
    # 1. Save raw file for audit trail
    import_dir = BASE_DIR / "data" / "product_knowledge" / "imports" / import_id / "raw"
    import_dir.mkdir(parents=True, exist_ok=True)
    with open(import_dir / file_name, "w", encoding="utf-8") as f:
        f.write(file_content)
    
    # 2. Parse JSON block
    parse_result = _parse_ai_form_content(
        file_content,
        file_name=file_name,
        content_type=content_type,
    )
    if not parse_result.parsed_json:
        return AIFormImportResponse(
            import_id=import_id,
            parse_status="PARSE_ERROR",
            parse_error_code=parse_result.error_code,
            parse_error_detail=parse_result.error_detail,
            parse_errors=[parse_result.error_detail or "Could not parse uploaded AI-assisted form."],
            parse_warnings=parse_result.warnings,
            accepted_formats=AI_FORM_ACCEPTED_FORMATS,
            detected_extension=detected_extension,
            detected_content_type=content_type,
            parser_strategy_used=parse_result.strategy_used,
            provenance=["product_knowledge_import_service:v1"]
        )
    parsed_json = parse_result.parsed_json
    
    # 3. Validate version
    validation_errors: list[str] = []
    version = parsed_json.get("bosmax_product_knowledge_form_version")
    if not version:
        validation_errors.append("MISSING_REQUIRED_KEYS")
    elif version != "1.0":
        validation_errors.append(f"UNSUPPORTED_VERSION: {version}")
    
    if validation_errors:
        return AIFormImportResponse(
            import_id=import_id,
            parse_status="VALIDATION_ERROR",
            parse_error_code="UNSUPPORTED_VERSION" if version else "MISSING_REQUIRED_KEYS",
            parse_error_detail=(
                f"Unsupported bosmax_product_knowledge_form_version: {version}"
                if version
                else "Required key missing: bosmax_product_knowledge_form_version"
            ),
            parse_errors=validation_errors,
            parse_warnings=parse_result.warnings,
            accepted_formats=AI_FORM_ACCEPTED_FORMATS,
            detected_extension=detected_extension,
            detected_content_type=content_type,
            parser_strategy_used=parse_result.strategy_used,
            provenance=["product_knowledge_import_service:v1"]
        )
    
    # 4. Map to request
    request = ProductKnowledgeCompleteRequest(
        product_name=parsed_json.get("product_name"),
        product_knowledge_text=parsed_json.get("product_knowledge_text"),
        benefits_text=parsed_json.get("benefits_text"),
        usage_text=parsed_json.get("usage_text"),
        target_customer_text=parsed_json.get("target_customer_text"),
        ingredients_text=parsed_json.get("ingredients_text"),
        warnings_text=parsed_json.get("warnings_text"),
        price=parsed_json.get("price"),
        currency=parsed_json.get("currency"),
        commission_amount=parsed_json.get("commission_amount"),
        commission_rate=parsed_json.get("commission_rate"),
        size_or_volume=parsed_json.get("size_or_volume"),
        package_notes=parsed_json.get("package_notes"),
        image_notes=parsed_json.get("image_notes"),
        product_form_factor=parsed_json.get("product_form_factor"),
        packaging_description=parsed_json.get("packaging_description"),
        source_lane=parsed_json.get("source_lane", "OWNED"),
        image_url=parsed_json.get("image_url"),
        product_url=parsed_json.get("product_url"),
        source_url=parsed_json.get("source_url"),
        tiktok_product_url=parsed_json.get("tiktok_product_url"),
        tiktok_shop_url=parsed_json.get("tiktok_shop_url"),
        paste_anything_about_product=parsed_json.get("paste_anything_about_product")
    )
    request = _normalize_completion_request(request)
    
    # 5. Handle AI inference warnings
    warnings = list(parse_result.warnings)
    evidence_notes = parsed_json.get("evidence_notes", {})
    inferred = evidence_notes.get("what_ai_inferred", [])
    if inferred:
        warnings.append(f"AI_INFERRED_FACTS_DETECTED: {', '.join(inferred)}")
    
    if parsed_json.get("user_review_status") != "USER_APPROVED":
        warnings.append("USER_REVIEW_NOT_EXPLICITLY_APPROVED_IN_FORM")
        
    # 6. Run completion
    completion = complete_product_knowledge(request)
    
    # Add affiliate warning if lane matches
    if _normalize_source_lane(request.source_lane) in ["FASTMOSS", "TIKTOKSHOP"]:
        warnings.append("AFFILIATE_LANE_CONTAMINATION_RISK")

    return AIFormImportResponse(
        import_id=import_id,
        parse_status="PARSED",
        parsed_request=request,
        parse_warnings=warnings,
        accepted_formats=AI_FORM_ACCEPTED_FORMATS,
        detected_extension=detected_extension,
        detected_content_type=content_type,
        parser_strategy_used=parse_result.strategy_used,
        completion_response=completion,
        provenance=["product_knowledge_import_service:v1"]
    )

def _detect_extension(file_name: str | None) -> str:
    if not file_name or "." not in file_name:
        return ""
    return file_name.rsplit(".", 1)[-1]


def _json_error_detail(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg} (line {exc.lineno}, column {exc.colno})"


def _find_balanced_json_object_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, index + 1))
                start = None
    return spans


def _parse_ai_form_content(
    text: str,
    *,
    file_name: str | None = None,
    content_type: str | None = None,
) -> _AIFormParseResult:
    normalized = text.lstrip("\ufeff").strip()
    extension = _detect_extension(file_name).lower()
    decoder = json.JSONDecoder()

    fenced_blocks = [
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", normalized, re.IGNORECASE | re.DOTALL)
    ]
    if fenced_blocks:
        if len(fenced_blocks) > 1:
            return _AIFormParseResult(
                strategy_used="FENCED_JSON",
                error_code="MULTIPLE_JSON_OBJECTS_FOUND",
                error_detail="Multiple fenced JSON objects were found. Keep only one canonical JSON object in the uploaded file.",
            )
        try:
            parsed = json.loads(fenced_blocks[0])
            if isinstance(parsed, dict):
                return _AIFormParseResult(parsed_json=parsed, strategy_used="FENCED_JSON")
        except json.JSONDecodeError as exc:
            return _AIFormParseResult(
                strategy_used="FENCED_JSON",
                error_code="INVALID_JSON",
                error_detail=f"Malformed fenced JSON block: {_json_error_detail(exc)}",
            )

    if normalized.startswith("{"):
        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                strategy = "RAW_JSON_TEXT" if extension == "txt" or (content_type or "").startswith("text/plain") else "RAW_JSON"
                return _AIFormParseResult(parsed_json=parsed, strategy_used=strategy)
        except json.JSONDecodeError as exc:
            direct_error = _json_error_detail(exc)
        else:
            direct_error = None
    else:
        direct_error = None

    spans = _find_balanced_json_object_spans(normalized)
    if len(spans) > 1:
        return _AIFormParseResult(
            strategy_used="BALANCED_OBJECT_EXTRACTION",
            error_code="MULTIPLE_JSON_OBJECTS_FOUND",
            error_detail="Multiple JSON objects were found in the uploaded text. Keep only one canonical object.",
        )
    if len(spans) == 1:
        start, end = spans[0]
        candidate = normalized[start:end]
        try:
            parsed, parsed_end = decoder.raw_decode(candidate)
        except json.JSONDecodeError as exc:
            return _AIFormParseResult(
                strategy_used="BALANCED_OBJECT_EXTRACTION",
                error_code="INVALID_JSON",
                error_detail=f"Balanced JSON object extraction failed: {_json_error_detail(exc)}",
            )
        trailing = candidate[parsed_end:].strip()
        if trailing:
            return _AIFormParseResult(
                strategy_used="BALANCED_OBJECT_EXTRACTION",
                error_code="INVALID_JSON",
                error_detail="Balanced JSON object contains trailing content after the parsed object.",
            )
        if isinstance(parsed, dict):
            warning = "FALLBACK_BALANCED_OBJECT_EXTRACTION_USED"
            return _AIFormParseResult(
                parsed_json=parsed,
                strategy_used="BALANCED_OBJECT_EXTRACTION",
                warnings=[warning],
            )

    if direct_error:
        return _AIFormParseResult(
            strategy_used="RAW_JSON_TEXT" if extension == "txt" else "RAW_JSON",
            error_code="INVALID_JSON",
            error_detail=f"Raw JSON parse failed: {direct_error}",
        )

    return _AIFormParseResult(
        strategy_used="RAW_JSON_TEXT" if extension == "txt" else "BALANCED_OBJECT_EXTRACTION",
        error_code="NO_JSON_FOUND",
        error_detail="No valid JSON object was found. Accepted formats: fenced ```json markdown, raw .json/.JSON, or raw JSON in .txt.",
    )
