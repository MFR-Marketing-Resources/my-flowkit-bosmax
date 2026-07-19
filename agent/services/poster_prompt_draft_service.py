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
from agent.models.poster_copy_quality import PosterCopyQualityRequest
from agent.services import poster_recipe_service
from agent.services.poster_copy_quality_service import (
    evaluate_poster_copy,
    map_legacy_to_poster,
)
from agent.services.poster_prompt_composer import compose_recipe_poster
from agent.services.poster_composition_service import (
    build_composition_constraints,
    render_composition_instruction,
    resolve_poster_composition,
)
from agent.services.poster_readiness_service import PosterReadinessService
from agent.models.poster_copy_set import (
    STATUS_POSTER_COPY_APPROVED,
    poster_fields_to_zone_fields,
    serialize_poster_copy_set,
)
from agent.services.poster_template_service import (
    PosterTemplateError,
    template_contract,
)
from agent.services.product_truth_service import ProductTruthService
from agent.services.creative_direction_service import (
    resolve_creative_direction,
    select_creative_direction_directives,
)

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


def _creative_direction_payload(direction: Any) -> dict[str, Any]:
    return {
        "mode": direction.mode.value,
        "authority_version": direction.authority_version,
        "representation_policy_version": direction.representation_policy_version,
    }


def _apply_creative_direction(
    visual: str,
    direction: Any | None,
    *,
    operator_human_presence: str = "",
    recipe_constraint_locked: bool = False,
) -> str:
    if direction is None:
        return visual
    directives = select_creative_direction_directives(
        direction,
        product_truth_locked=True,
        operator_human_presence=operator_human_presence,
        composition_constraint_locked=recipe_constraint_locked,
    )
    return "\n".join(
        (
            visual,
            "Governed Creative Direction (after deterministic higher-authority conflict suppression):",
            *(f"{label}: {value}" for label, value in directives),
            "Localisation cues: " + ", ".join(direction.malaysian_localisation_cues),
        )
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


# POSTER_BUILDER_V2: marketing-text suppression for the compositor lane. The
# product's OWN label/logo/packaging text is explicitly preserved — only
# generated marketing typography is banned (never a broad "no text").
CLEAN_SCENE_NEGATIVE = (
    "marketing headline text, slogan text, poster typography overlay, "
    "USP bullet text, CTA button graphic, price tag graphic, promotional "
    "badge text, watermark text"
)


def _build_clean_scene_instruction(safe_region: dict, background_constraints: str) -> str:
    return (
        "CLEAN SCENE MODE - the deterministic compositor renders ALL marketing "
        "text after generation. Do NOT draw any marketing text: no headline, "
        "slogan, USP bullets, CTA, price, badge or watermark. PRESERVE the real "
        "product label, logo, cap and packaging text exactly (product truth). "
        f"Keep the product hero fully inside the product region (approx "
        f"x {safe_region['x']}% y {safe_region['y']}% w {safe_region['w']}% "
        f"h {safe_region['h']}% of the frame) and leave clean uncluttered "
        "negative space everywhere else for the copy zones. "
        + (f"Background constraints: {background_constraints}" if background_constraints else "")
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
        creative_direction = (
            resolve_creative_direction(request.creative_mode, product=product)
            if request.creative_mode is not None
            else None
        )
        readiness = await PosterReadinessService.evaluate_product(product, enrich=False)
        fields = _request_as_dict(request)
        readiness_meta = readiness.model_dump(mode="json")

        # POSTER_BUILDER_V2: an explicit poster-native copy set projects its
        # fields into the zone copy fields. Approved sets are production-
        # eligible; non-approved sets keep the review-only downgrade below.
        poster_copy_set = None
        poster_copy_set_id = _norm(request.poster_copy_set_id)
        if poster_copy_set_id:
            _pcs_row = await crud.get_poster_copy_set(poster_copy_set_id)
            if not _pcs_row:
                raise PosterPromptDraftValidationError(
                    "Unknown poster copy set",
                    field_errors=[f"Unknown poster_copy_set_id: {poster_copy_set_id}"],
                )
            if _norm(_pcs_row.get("product_id")) != product_id:
                raise PosterPromptDraftValidationError(
                    "Poster copy set belongs to a different product",
                    field_errors=["POSTER_COPY_SET_PRODUCT_MISMATCH"],
                )
            poster_copy_set = serialize_poster_copy_set(_pcs_row)
            fields.update(poster_fields_to_zone_fields(poster_copy_set))
            if _norm(poster_copy_set.get("language")):
                fields["language"] = _norm(poster_copy_set.get("language"))

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

        # Poster copy quality guard (expert e-commerce rules). Legacy video-style
        # fields are mapped to poster-native copy; BLOCK findings stop the draft,
        # WARN findings are surfaced. archetype/max_chips come from the recipe.
        _q_archetype = ""
        _q_max_chips = 3
        _q_recipe_id = _norm(request.poster_recipe_id)
        if _q_recipe_id:
            _q_recipe = poster_recipe_service.get_recipe(_q_recipe_id)
            if _q_recipe is not None:
                _q_archetype = _q_recipe.archetype
                _q_max_chips = _q_recipe.max_chips or 3
        _q_report = evaluate_poster_copy(
            PosterCopyQualityRequest(
                archetype=_q_archetype,
                language=fields["language"],
                max_chips=_q_max_chips,
                **map_legacy_to_poster(fields),
            )
        )
        _q_blocks = [
            f"{x.code}: {x.message}" for x in _q_report.findings if x.severity == "BLOCK"
        ]
        if _q_blocks:
            raise PosterPromptDraftValidationError(
                "Poster copy quality failed", field_errors=_q_blocks
            )
        _q_warnings = [
            f"POSTER_QUALITY_WARN {x.code}"
            for x in _q_report.findings
            if x.severity == "WARN"
        ]

        profile = ProductTruthService.build_computed_profile(product)
        truth_lock = _product_truth_lock(product, profile)
        guardrails = list(RESTRICTED_SAFETY_GUARDRAILS if restricted_mode else [])
        guardrails.append("Follow product truth lock; no unapproved claims.")
        if readiness.poster_status == PosterReadinessStatus.POSTER_PREVIEW_ONLY:
            guardrails.append("Preview-only diagnostic package — not for production approval.")

        visual = _apply_creative_direction(
            _build_visual_instruction(fields, readiness.image_tier.value),
            creative_direction,
            operator_human_presence=fields["human_presence_mode"],
            recipe_constraint_locked=bool(request.poster_recipe_id),
        )
        overlay = _build_text_overlay(fields)
        # Recipe V2 routing. A recipe_id composes a recipe-structured prompt +
        # poster_spec/overlay_spec. NO recipe_id → the legacy assembler runs
        # unchanged (poster_prompt byte-identical; specs stay None).
        poster_spec = None
        overlay_spec = None
        negative_prompt = _negative_prompt(restricted_mode)
        if creative_direction is not None:
            negative_prompt += ", " + ", ".join(creative_direction.negative_rules)
        recipe_id = _norm(request.poster_recipe_id)
        _recipe_obj = None
        _template_contract = None
        if recipe_id:
            recipe = poster_recipe_service.get_recipe(recipe_id)
            if recipe is None:
                raise PosterPromptDraftValidationError(
                    "Unknown poster recipe",
                    field_errors=[f"Unknown poster recipe: {recipe_id}"],
                )
            # POSTER_BUILDER_V2 clean-scene contract: the deterministic
            # compositor owns ALL marketing text, so the image engine must
            # produce a CLEAN product-anchored scene (product label preserved,
            # zero marketing typography) with the product inside the template's
            # product-safe region.
            try:
                _contract = template_contract(recipe_id)
            except PosterTemplateError as exc:
                raise PosterPromptDraftValidationError(
                    "Poster template contract unavailable",
                    field_errors=[f"{exc.code}: {exc}"],
                )
            _recipe_obj = recipe
            _template_contract = _contract
            _safe = _contract["product_safe_region"]
            overlay = _build_clean_scene_instruction(_safe, _contract["background_constraints"])
            poster_prompt, poster_spec, overlay_spec = compose_recipe_poster(
                fields=fields,
                recipe=recipe,
                product_truth_lock=truth_lock,
                visual_instruction=visual,
                text_overlay_instruction=overlay,
                safety_guardrails=guardrails,
                restricted_mode=restricted_mode,
            )
            negative_prompt = negative_prompt + ", " + CLEAN_SCENE_NEGATIVE
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

        # B-01: the PRODUCTION caller passes the REAL resolved higher-authority
        # constraints into the canonical resolver — actual Product Truth profile,
        # representation-policy identity rule, the operator's hard human-presence
        # selection, the recipe template contract and the copy-quality report.
        composition_constraints = (
            build_composition_constraints(
                product=product,
                truth_profile=profile,
                creative_direction=creative_direction,
                operator_human_presence=fields["human_presence_mode"],
                recipe=_recipe_obj,
                template_contract=_template_contract,
                copy_quality_report=_q_report,
            )
            if creative_direction is not None
            else None
        )
        composition_plan = resolve_poster_composition(
            creative_direction=creative_direction,
            recipe_id=recipe_id,
            frame_ratio=fields["frame_ratio"],
            fields=fields,
            constraints=composition_constraints,
        )
        if composition_plan:
            poster_prompt += "\n=== PROFESSIONAL COMPOSITION PLAN ===\n" + render_composition_instruction(composition_plan)

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
        validation_warnings: list[str] = list(_q_warnings)
        # Deterministic composition governance is surfaced, never hidden. The
        # legacy no-mode path has an empty plan and stays byte-identical.
        validation_warnings.extend(
            f"COMPOSITION_WARN {code}"
            for code in composition_plan.get("warnings", [])
        )
        validation_warnings.extend(
            f"COMPOSITION_BLOCKER {code}"
            for code in composition_plan.get("blockers", [])
        )
        copy_source = _norm(request.copy_source)
        if poster_copy_set is not None:
            copy_source = (
                "APPROVED_POSTER_COPY_SET"
                if poster_copy_set.get("status") == STATUS_POSTER_COPY_APPROVED
                else "POSTER_COPY_SET_DRAFT"
            )
        if (
            copy_source
            and copy_source not in ("APPROVED_COPY_SET", "APPROVED_POSTER_COPY_SET")
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
            creative_direction=(
                _creative_direction_payload(creative_direction)
                if creative_direction is not None else {}
            ),
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
            composition_plan=composition_plan,
        )
