"""Deterministic poster prompt draft assembly (read-only product + readiness gate)."""

from __future__ import annotations

import re
from typing import Any

from agent.db import crud
from agent.models.poster_prompt_draft import (
    PosterCopyLayout,
    PosterPromptDraftRequest,
    PosterPromptDraftResponse,
    PromptPackageStatus,
)
from agent.models.poster_readiness import PosterReadinessStatus
from agent.services import poster_recipe_service
from agent.services.poster_prompt_composer import compose_recipe_poster
from agent.services.poster_readiness_service import PosterReadinessService
from agent.services.product_truth_service import ProductTruthService

CRITICAL_FIELDS: tuple[str, ...] = (
    "poster_objective",
    "poster_type",
    "visual_route",
    "frame_ratio",
    "language",
    "hook",
    "cta",
)

# Poster copy is SHORT — a headline + a few bullets + a CTA that must FIT the poster,
# not long video-style sentences. Max characters per copy field (SSOT; the dashboard
# mirrors these limits in dashboard/src/poster/posterBuilderUi.ts — keep them in sync).
POSTER_COPY_LIMITS: dict[str, int] = {
    "hook": 48,
    "subhook": 72,
    "usp_1": 36,
    "usp_2": 36,
    "usp_3": 36,
    "cta": 24,
}

UNSAFE_CLAIM_TERMS: tuple[str, ...] = (
    "cure",
    "treat",
    "heal",
    "disease",
    "guaranteed relief",
    "pain gone",
    "ubat",
    "sembuh",
    "rawat",
    "penyakit",
    "hilang sakit",
    "jamin lega",
)

RESTRICTED_SAFETY_GUARDRAILS: tuple[str, ...] = (
    "No cure/treat/heal claim.",
    "No disease claim.",
    "No guaranteed relief.",
    "No before-after.",
    "No fake certificate/proof.",
    "Use routine, standby, lifestyle, comfort, heritage, portability, product-size angles only.",
)

BASE_NEGATIVE_PROMPT = (
    "blurry text, misspelled Malay, wrong product shape, extra limbs, distorted logo, "
    "watermark, low resolution, cluttered layout, medical claim text, before-after comparison, "
    "fake certificate, unrealistic bottle size"
)


class PosterPromptDraftValidationError(Exception):
    def __init__(self, message: str, *, field_errors: list[str] | None = None):
        super().__init__(message)
        self.field_errors = field_errors or []


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _request_as_dict(req: PosterPromptDraftRequest) -> dict[str, str]:
    return {
        "poster_objective": _norm(req.poster_objective),
        "poster_type": _norm(req.poster_type),
        "visual_route": _norm(req.visual_route),
        "human_presence_mode": _norm(req.human_presence_mode),
        "frame_ratio": _norm(req.frame_ratio),
        "language": _norm(req.language),
        "text_density": _norm(req.text_density),
        "hook": _norm(req.hook),
        "subhook": _norm(req.subhook),
        "usp_1": _norm(req.usp_1),
        "usp_2": _norm(req.usp_2),
        "usp_3": _norm(req.usp_3),
        "cta": _norm(req.cta),
        "operator_notes": _norm(req.operator_notes),
    }


def _validate_critical_fields(fields: dict[str, str]) -> list[str]:
    missing = [name for name in CRITICAL_FIELDS if not fields.get(name)]
    return [f"Missing required field: {name}" for name in missing]


def _validate_copy_lengths(fields: dict[str, str]) -> list[str]:
    """Poster copy must fit the poster — reject over-length copy so nothing overflows."""
    errors: list[str] = []
    for name, limit in POSTER_COPY_LIMITS.items():
        length = len(fields.get(name) or "")
        if length > limit:
            errors.append(
                f"{name} too long for a poster: {length}/{limit} chars — keep it short"
            )
    return errors


def _collect_copy_text(fields: dict[str, str]) -> str:
    parts = [
        fields.get("hook", ""),
        fields.get("subhook", ""),
        fields.get("usp_1", ""),
        fields.get("usp_2", ""),
        fields.get("usp_3", ""),
        fields.get("cta", ""),
        fields.get("operator_notes", ""),
    ]
    return " ".join(p for p in parts if p)


def _find_unsafe_terms(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for term in UNSAFE_CLAIM_TERMS:
        if term in lowered:
            hits.append(term)
    return hits


def _unsafe_copy_validation_message(status: PosterReadinessStatus) -> str:
    if status == PosterReadinessStatus.POSTER_READY_RESTRICTED:
        return "Unsafe claim wording detected for restricted-safe poster route."
    return "Unsafe or unapproved claim wording detected."


def _reject_unsafe_operator_copy(
    fields: dict[str, str],
    readiness_status: PosterReadinessStatus,
) -> None:
    """Block prompt assembly when operator copy contains claim-risk terms (all draft paths)."""
    copy_blob = _collect_copy_text(fields)
    unsafe_hits = _find_unsafe_terms(copy_blob)
    if not unsafe_hits:
        return
    raise PosterPromptDraftValidationError(
        _unsafe_copy_validation_message(readiness_status),
        field_errors=[f"Unsafe term: {t}" for t in unsafe_hits],
    )


def _product_truth_lock(product: dict[str, Any], profile: Any) -> str:
    display = _norm(product.get("product_display_name")) or _norm(product.get("raw_product_title"))
    category = _norm(product.get("category"))
    subcategory = _norm(product.get("subcategory"))
    ptype = _norm(product.get("type"))
    title = _norm(getattr(getattr(profile, "text_evidence", None), "normalized_title", None)) or display
    lines = [
        f"Product display name (locked): {display}",
        f"Canonical title signal: {title}",
        f"Category: {category or '—'} / Subcategory: {subcategory or '—'} / Type: {ptype or '—'}",
        "Do not swap SKU, volume, brand, or product form factor.",
        "Render only this product identity; no generic substitute packaging.",
    ]
    return "\n".join(lines)


def _build_visual_instruction(fields: dict[str, str], readiness_image_tier: str) -> str:
    return (
        f"Visual route: {fields['visual_route']}. "
        f"Poster type: {fields['poster_type']}. "
        f"Objective: {fields['poster_objective']}. "
        f"Human presence: {fields['human_presence_mode'] or 'product-forward'}. "
        f"Image tier from readiness: {readiness_image_tier}. "
        "Hero product placement centered or rule-of-thirds; clean negative space for copy."
    )


def _build_text_overlay(fields: dict[str, str]) -> str:
    density = fields.get("text_density") or "medium"
    lang = fields.get("language") or "ms"
    return (
        f"Language: {lang}. Text density: {density}. "
        f"Hierarchy: hook largest ({fields['hook']}), subhook secondary ({fields['subhook'] or 'optional'}), "
        f"three USP bullets, CTA button-style ({fields['cta']}). "
        "Keep Malay/English consistent with language field; high contrast readable overlay."
    )


def _assemble_poster_prompt(
    *,
    fields: dict[str, str],
    product_truth_lock: str,
    visual_instruction: str,
    text_overlay_instruction: str,
    safety_guardrails: list[str],
    restricted_mode: bool,
) -> str:
    usps = [fields["usp_1"], fields["usp_2"], fields["usp_3"]]
    usp_block = "\n".join(f"- {u}" for u in usps if u) or "- (no USP lines provided)"
    guardrail_block = "\n".join(f"- {g}" for g in safety_guardrails)
    sections = [
        "=== PRODUCT TRUTH LOCK ===",
        product_truth_lock,
        "=== VISUAL COMPOSITION ===",
        visual_instruction,
        f"Frame ratio: {fields['frame_ratio']}. Camera: commercial product poster framing, slight angle acceptable.",
        "Lighting: soft studio key with gentle fill; brand-safe, not clinical.",
        "=== COPY HIERARCHY ===",
        f"Hook: {fields['hook']}",
        f"Subhook: {fields['subhook']}",
        "USP:",
        usp_block,
        f"CTA: {fields['cta']}",
        "=== TEXT OVERLAY ===",
        text_overlay_instruction,
        "=== OPERATOR NOTES ===",
        fields["operator_notes"] or "(none)",
        "=== SAFETY / COMPLIANCE ===",
        guardrail_block,
    ]
    if restricted_mode:
        sections.append("=== RESTRICTED-SAFE MODE ===")
        sections.append("Lifestyle / routine / heritage / portability only. No therapeutic promises.")
    return "\n".join(sections)


def _negative_prompt(restricted_mode: bool) -> str:
    extra = ", therapeutic claim, cure claim, disease treatment, guaranteed results"
    if restricted_mode:
        extra += ", medical imagery, stethoscope, hospital, prescription"
    return BASE_NEGATIVE_PROMPT + extra


def _map_package_status(readiness_status: PosterReadinessStatus) -> PromptPackageStatus | None:
    if readiness_status == PosterReadinessStatus.POSTER_READY:
        return PromptPackageStatus.DRAFT_READY
    if readiness_status == PosterReadinessStatus.POSTER_READY_RESTRICTED:
        return PromptPackageStatus.DRAFT_READY
    if readiness_status == PosterReadinessStatus.POSTER_PREVIEW_ONLY:
        return PromptPackageStatus.PREVIEW_ONLY
    if readiness_status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED:
        return PromptPackageStatus.REPAIR_REQUIRED
    if readiness_status == PosterReadinessStatus.POSTER_BLOCKED:
        return PromptPackageStatus.BLOCKED
    return PromptPackageStatus.BLOCKED


class PosterPromptDraftService:
    @staticmethod
    async def build_draft(request: PosterPromptDraftRequest) -> PosterPromptDraftResponse:
        product_id = _norm(request.product_id)
        if not product_id:
            raise PosterPromptDraftValidationError("product_id is required")

        row = await crud.get_product(product_id)
        if not row:
            raise PosterPromptDraftValidationError("PRODUCT_NOT_FOUND")

        product = dict(row)
        readiness = await PosterReadinessService.evaluate_product(product, enrich=False)
        fields = _request_as_dict(request)
        readiness_meta = readiness.model_dump(mode="json")

        package_status = _map_package_status(readiness.poster_status)
        repair_payload = [a.model_dump(mode="json") for a in readiness.repair_actions]

        if readiness.poster_status in {
            PosterReadinessStatus.POSTER_REPAIR_REQUIRED,
            PosterReadinessStatus.POSTER_BLOCKED,
        }:
            blocked = readiness.blockers[:]
            if readiness.poster_status == PosterReadinessStatus.POSTER_BLOCKED:
                blocked.append("POSTER_BLOCKED")
            return PosterPromptDraftResponse(
                product_id=product_id,
                product_display_name=readiness.product_display_name,
                poster_status=readiness.poster_status.value,
                prompt_package_status=package_status or PromptPackageStatus.BLOCKED,
                generation_allowed=False,
                production_allowed=False,
                restricted_mode=False,
                blocked_reasons=blocked,
                repair_actions=repair_payload,
                readiness_meta=readiness_meta,
                operator_notes=fields["operator_notes"],
            )

        field_errors = _validate_critical_fields(fields)
        field_errors.extend(_validate_copy_lengths(fields))
        if field_errors:
            raise PosterPromptDraftValidationError(
                "Poster prompt draft validation failed",
                field_errors=field_errors,
            )

        restricted_mode = readiness.poster_status == PosterReadinessStatus.POSTER_READY_RESTRICTED
        _reject_unsafe_operator_copy(fields, readiness.poster_status)

        profile = ProductTruthService.build_computed_profile(product)
        truth_lock = _product_truth_lock(product, profile)
        guardrails = list(RESTRICTED_SAFETY_GUARDRAILS if restricted_mode else [])
        guardrails.append("Follow product truth lock; no unapproved claims.")
        if readiness.poster_status == PosterReadinessStatus.POSTER_PREVIEW_ONLY:
            guardrails.append("Preview-only diagnostic package — not for production approval.")

        visual = _build_visual_instruction(fields, readiness.image_tier.value)
        overlay = _build_text_overlay(fields)
        # Recipe V2 routing. A recipe_id composes a recipe-structured prompt +
        # poster_spec/overlay_spec. NO recipe_id → the legacy assembler runs
        # unchanged (poster_prompt byte-identical; specs stay None).
        poster_spec = None
        overlay_spec = None
        negative_prompt = _negative_prompt(restricted_mode)
        recipe_id = _norm(request.poster_recipe_id)
        if recipe_id:
            recipe = poster_recipe_service.get_recipe(recipe_id)
            if recipe is None:
                raise PosterPromptDraftValidationError(
                    "Unknown poster recipe",
                    field_errors=[f"Unknown poster recipe: {recipe_id}"],
                )
            poster_prompt, poster_spec, overlay_spec = compose_recipe_poster(
                fields=fields,
                recipe=recipe,
                product_truth_lock=truth_lock,
                visual_instruction=visual,
                text_overlay_instruction=overlay,
                safety_guardrails=guardrails,
                restricted_mode=restricted_mode,
            )
            if recipe.negative_prompt_additions:
                negative_prompt = (
                    negative_prompt + ", " + ", ".join(recipe.negative_prompt_additions)
                )
        else:
            poster_prompt = _assemble_poster_prompt(
                fields=fields,
                product_truth_lock=truth_lock,
                visual_instruction=visual,
                text_overlay_instruction=overlay,
                safety_guardrails=guardrails,
                restricted_mode=restricted_mode,
            )

        production_allowed = readiness.poster_status == PosterReadinessStatus.POSTER_READY
        prompt_status = (
            PromptPackageStatus.PREVIEW_ONLY
            if readiness.poster_status == PosterReadinessStatus.POSTER_PREVIEW_ONLY
            else PromptPackageStatus.DRAFT_READY
        )

        # Copy provenance governance (Phase D): poster copy that is NOT an approved
        # Copy Set is review-only and never silently production-approved. We downgrade
        # only when the caller explicitly declares a non-approved source and has not
        # confirmed fallback — legacy callers that omit copy_source keep prior behavior.
        validation_warnings: list[str] = []
        copy_source = _norm(request.copy_source)
        if (
            copy_source
            and copy_source != "APPROVED_COPY_SET"
            and not request.copy_fallback_confirmed
        ):
            validation_warnings.append("UNGROUNDED_COPY_REVIEW_ONLY")
            prompt_status = PromptPackageStatus.PREVIEW_ONLY
            production_allowed = False

        usps = [fields["usp_1"], fields["usp_2"], fields["usp_3"]]
        usps = [u for u in usps if u]

        return PosterPromptDraftResponse(
            product_id=product_id,
            product_display_name=readiness.product_display_name,
            poster_status=readiness.poster_status.value,
            prompt_package_status=prompt_status,
            generation_allowed=readiness.generation_allowed,
            production_allowed=production_allowed,
            restricted_mode=restricted_mode,
            poster_prompt=poster_prompt,
            negative_prompt=negative_prompt,
            copy_layout=PosterCopyLayout(
                hook=fields["hook"],
                subhook=fields["subhook"],
                usp=usps,
                cta=fields["cta"],
            ),
            visual_instruction=visual,
            text_overlay_instruction=overlay,
            product_truth_lock=truth_lock,
            safety_guardrails=guardrails,
            blocked_reasons=[],
            repair_actions=repair_payload,
            readiness_meta=readiness_meta,
            operator_notes=fields["operator_notes"],
            validation_warnings=validation_warnings,
            poster_spec=poster_spec,
            overlay_spec=overlay_spec,
        )