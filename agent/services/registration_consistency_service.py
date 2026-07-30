from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RegistrationConsistencyResult(BaseModel):
    status: Literal["CONSISTENT", "BLOCKED_REVIEW_REQUIRED"]
    issue_codes: list[str] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)


def _text(value: Any) -> str:
    return str(value or "").strip().upper()


def evaluate_registration_consistency(
    candidates: dict[str, Any],
) -> RegistrationConsistencyResult:
    family = _text(candidates.get("bosmax_product_family"))
    physical_state = _text(candidates.get("physical_state"))
    physics_class = _text(candidates.get("physics_class"))
    copy_formula = _text(candidates.get("copy_formula"))
    taxonomy = " ".join(
        _text(candidates.get(field))
        for field in ("category", "subcategory", "type")
    )
    issues: list[str] = []
    explanations: list[str] = []

    textile_taxonomy = any(
        token in taxonomy
        for token in ("TEXTILE", "CURTAIN", "FURNISHING", "HOUSEHOLD TEXTILE")
    )
    if textile_taxonomy and family and family != "HOME_TEXTILE":
        issues.append("CONSISTENCY_FAMILY_TAXONOMY_CONFLICT")
        explanations.append(
            f"Taxonomy is home textile but product family resolved to {family}."
        )
    if family == "HOME_TEXTILE":
        if physical_state and physical_state != "TEXTILE":
            issues.append("CONSISTENCY_FAMILY_PHYSICAL_STATE_CONFLICT")
            explanations.append(
                f"HOME_TEXTILE requires textile physical state, not {physical_state}."
            )
        if physics_class and physics_class != "HOME_TEXTILE_SOFT_GOOD":
            issues.append("CONSISTENCY_FAMILY_PHYSICS_CONFLICT")
            explanations.append(
                f"HOME_TEXTILE requires HOME_TEXTILE_SOFT_GOOD, not {physics_class}."
            )
        if "PET" in copy_formula:
            issues.append("CONSISTENCY_FAMILY_COPY_CONFLICT")
            explanations.append(
                f"HOME_TEXTILE cannot use pet-care copy formula {copy_formula}."
            )
    elif family.startswith("PET") and (
        textile_taxonomy or physics_class == "HOME_TEXTILE_SOFT_GOOD"
    ):
        if "CONSISTENCY_FAMILY_TAXONOMY_CONFLICT" not in issues:
            issues.append("CONSISTENCY_FAMILY_TAXONOMY_CONFLICT")
            explanations.append(
                f"Pet family {family} conflicts with home-textile taxonomy."
            )
        issues.append("CONSISTENCY_FAMILY_PHYSICS_CONFLICT")
        explanations.append(
            f"Pet family {family} conflicts with HOME_TEXTILE_SOFT_GOOD physics."
        )

    return RegistrationConsistencyResult(
        status="BLOCKED_REVIEW_REQUIRED" if issues else "CONSISTENT",
        issue_codes=list(dict.fromkeys(issues)),
        explanations=explanations,
    )
