from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.models.product_knowledge import ProductKnowledgeCompleteRequest


EvidenceStatus = Literal[
    "EXACT_SOURCE_EVIDENCE",
    "NOT_AVAILABLE",
    "NOT_APPLICABLE",
    "INVALID_MARKETING_METADATA",
    "INVALID_CTA_COPY",
    "PLACEHOLDER",
    "CROSS_FIELD_CONTAMINATION",
]


class EvidenceQualityDecision(BaseModel):
    status: EvidenceStatus
    confidence: Literal["HIGH", "MEDIUM", "LOW", "NOT_APPLICABLE"]
    raw_value: Any = None
    sanitized_value: Any = None
    reason_codes: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    repair_action: Literal[
        "NONE",
        "FILL_MISSING",
        "REPAIR_INVALID_OR_PLACEHOLDER",
        "MARK_NOT_APPLICABLE",
    ] = "NONE"
    applicability: Literal["APPLICABLE", "NOT_APPLICABLE", "UNKNOWN"] = "UNKNOWN"


class RegistrationEvidenceAudit(BaseModel):
    status: Literal["CLEAN", "REVIEW_REQUIRED"]
    raw_fields: dict[str, Any] = Field(default_factory=dict)
    sanitized_fields: dict[str, Any] = Field(default_factory=dict)
    decisions: dict[str, EvidenceQualityDecision] = Field(default_factory=dict)
    issue_codes: list[str] = Field(default_factory=list)


_PLACEHOLDERS = {"n/a", "na", "none", "unknown", "-", "tbc", "tbd", "placeholder"}
_CTA_PATTERN = re.compile(
    r"\b(order|buy|shop|grab|checkout|klik|beli|dapatkan)\b.{0,20}\b(now|sekarang|today|hari ini)\b",
    re.IGNORECASE,
)
_DURATION_PATTERN = re.compile(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\s*s(?:ec(?:ond)?s?)?\b", re.IGNORECASE)
_MUSIC_PATTERN = re.compile(r"\b(music|audio|soundtrack|bgm|lagu)\b", re.IGNORECASE)
_HASHTAG_PATTERN = re.compile(r"(?<!\w)#[A-Za-z0-9_]+")

_MATERIAL_TERMS: tuple[tuple[str, str], ...] = (
    ("fabrik", "fabric"),
    ("fabric", "fabric"),
    ("renda", "lace"),
    ("lace", "lace"),
    ("soft cotton", "soft cotton"),
    ("cotton", "cotton"),
    ("polyester", "polyester"),
    ("linen", "linen"),
    ("velvet", "velvet"),
)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _is_placeholder(value: Any) -> bool:
    text = _clean(value)
    return bool(text and text.casefold() in _PLACEHOLDERS)


def _extract_materials(*values: Any) -> str | None:
    haystack = " ".join(str(value or "") for value in values).casefold()
    found: list[str] = []
    for token, canonical in _MATERIAL_TERMS:
        if (
            canonical == "cotton"
            and "soft cotton" in found
        ):
            continue
        if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", haystack) and canonical not in found:
            found.append(canonical)
    return "; ".join(found) or None


def _exact(field: str, value: Any) -> EvidenceQualityDecision:
    return EvidenceQualityDecision(
        status="EXACT_SOURCE_EVIDENCE",
        confidence="HIGH",
        raw_value=value,
        sanitized_value=value,
        evidence_used=[f"declared_evidence:{field}"],
        repair_action="NONE",
        applicability="APPLICABLE",
    )


def audit_registration_evidence(
    request: ProductKnowledgeCompleteRequest,
    *,
    product_family: str | None,
) -> RegistrationEvidenceAudit:
    raw_fields = {
        "product_knowledge_text": request.product_knowledge_text,
        "benefits_text": request.benefits_text,
        "usage_text": request.usage_text,
        "target_customer_text": request.target_customer_text,
        "ingredients_text": request.ingredients_text,
        "materials_text": request.materials_text,
        "warnings_text": request.warnings_text,
        "size_or_volume": request.size_or_volume,
        "package_notes": request.package_notes,
    }
    sanitized_fields = dict(raw_fields)
    decisions: dict[str, EvidenceQualityDecision] = {}
    issue_codes: list[str] = []

    field_aliases = {
        "product_knowledge_text": "product_knowledge_summary",
        "benefits_text": "benefits",
        "usage_text": "usage_summary",
        "target_customer_text": "target_customer",
        "warnings_text": "warnings_or_limitations",
        "size_or_volume": "size_or_volume",
        "package_notes": "package_notes",
    }
    for source_field, candidate_field in field_aliases.items():
        value = raw_fields[source_field]
        if _is_placeholder(value):
            issue = f"EVIDENCE_{source_field.upper()}_PLACEHOLDER"
            issue_codes.append(issue)
            sanitized_fields[source_field] = None
            decisions[candidate_field] = EvidenceQualityDecision(
                status="PLACEHOLDER",
                confidence="LOW",
                raw_value=value,
                reason_codes=[issue],
                evidence_used=[f"declared_evidence:{source_field}"],
                repair_action="REPAIR_INVALID_OR_PLACEHOLDER",
                applicability="APPLICABLE",
            )
        elif _clean(value):
            decisions[candidate_field] = _exact(source_field, value)
        else:
            decisions[candidate_field] = EvidenceQualityDecision(
                status="NOT_AVAILABLE",
                confidence="LOW",
                raw_value=value,
                reason_codes=[f"EVIDENCE_{source_field.upper()}_MISSING"],
                repair_action="FILL_MISSING",
                applicability="APPLICABLE",
            )

    benefits = _clean(request.benefits_text)
    benefits_reasons: list[str] = []
    if benefits and _HASHTAG_PATTERN.search(benefits):
        benefits_reasons.append("EVIDENCE_BENEFITS_HASHTAG_METADATA")
    if benefits and _DURATION_PATTERN.search(benefits):
        benefits_reasons.append("EVIDENCE_BENEFITS_DURATION_METADATA")
    if benefits and _MUSIC_PATTERN.search(benefits):
        benefits_reasons.append("EVIDENCE_BENEFITS_PRODUCTION_METADATA")
    if benefits_reasons:
        issue_codes.extend(benefits_reasons)
        sanitized_fields["benefits_text"] = None
        decisions["benefits"] = EvidenceQualityDecision(
            status="INVALID_MARKETING_METADATA",
            confidence="LOW",
            raw_value=request.benefits_text,
            reason_codes=benefits_reasons,
            evidence_used=["declared_evidence:benefits_text"],
            repair_action="REPAIR_INVALID_OR_PLACEHOLDER",
            applicability="APPLICABLE",
        )

    target_customer = _clean(request.target_customer_text)
    if target_customer and (
        re.search(r"\bviral\b", target_customer, re.IGNORECASE)
        or _CTA_PATTERN.search(target_customer)
    ):
        target_reason = "EVIDENCE_TARGET_CUSTOMER_MARKETING_COPY"
        issue_codes.append(target_reason)
        sanitized_fields["target_customer_text"] = None
        decisions["target_customer"] = EvidenceQualityDecision(
            status="INVALID_MARKETING_METADATA",
            confidence="LOW",
            raw_value=request.target_customer_text,
            reason_codes=[target_reason],
            evidence_used=["declared_evidence:target_customer_text"],
            repair_action="REPAIR_INVALID_OR_PLACEHOLDER",
            applicability="APPLICABLE",
        )

    ingredients = _clean(request.ingredients_text)
    ingredient_reasons: list[str] = []
    if ingredients and _CTA_PATTERN.search(ingredients):
        ingredient_reasons.append("EVIDENCE_INGREDIENTS_CTA_COPY")
        issue_codes.extend(ingredient_reasons)
        sanitized_fields["ingredients_text"] = None

    textile_context = " ".join(
        str(value or "")
        for value in (
            request.category,
            request.subcategory,
            request.type,
            request.product_type,
            request.product_name,
        )
    ).casefold()
    is_non_consumable_textile = (
        str(product_family or "").upper() == "HOME_TEXTILE"
        or any(
            token in textile_context
            for token in ("textile", "furnishing", "curtain", "langsir")
        )
    )
    materials = _clean(request.materials_text) or _extract_materials(
        request.product_name,
        request.product_knowledge_text,
        request.paste_anything_about_product,
    )
    sanitized_fields["materials_text"] = materials
    if is_non_consumable_textile:
        decisions["ingredients_or_materials"] = EvidenceQualityDecision(
            status="NOT_APPLICABLE",
            confidence="NOT_APPLICABLE",
            raw_value=request.ingredients_text,
            sanitized_value=materials,
            reason_codes=ingredient_reasons + ["INGREDIENTS_NOT_APPLICABLE_FOR_HOME_TEXTILE"],
            evidence_used=["declared_evidence:product_name"],
            repair_action="MARK_NOT_APPLICABLE",
            applicability="NOT_APPLICABLE",
        )
    elif ingredient_reasons:
        decisions["ingredients_or_materials"] = EvidenceQualityDecision(
            status="INVALID_CTA_COPY",
            confidence="LOW",
            raw_value=request.ingredients_text,
            reason_codes=ingredient_reasons,
            evidence_used=["declared_evidence:ingredients_text"],
            repair_action="REPAIR_INVALID_OR_PLACEHOLDER",
            applicability="APPLICABLE",
        )
    elif ingredients:
        decisions["ingredients_or_materials"] = _exact(
            "ingredients_text", request.ingredients_text
        )
    else:
        decisions["ingredients_or_materials"] = EvidenceQualityDecision(
            status="NOT_AVAILABLE",
            confidence="LOW",
            raw_value=request.ingredients_text,
            reason_codes=["EVIDENCE_INGREDIENTS_OR_MATERIALS_MISSING"],
            repair_action="FILL_MISSING",
            applicability="UNKNOWN",
        )

    return RegistrationEvidenceAudit(
        status="REVIEW_REQUIRED" if issue_codes else "CLEAN",
        raw_fields=raw_fields,
        sanitized_fields=sanitized_fields,
        decisions=decisions,
        issue_codes=list(dict.fromkeys(issue_codes)),
    )
