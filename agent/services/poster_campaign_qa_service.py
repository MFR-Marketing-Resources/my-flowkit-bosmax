"""Fail-closed QA and review orchestration for Creative Campaign posters.

This service deliberately separates deterministic render checks, machine-image
evidence and human visual review. Missing vision/font evidence is UNVERIFIED;
it is never upgraded to PASS by a payload or by a prompt.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from agent.models.poster_campaign_design_brief import (
    CampaignCopyRoute,
    PosterCampaignDesignBrief,
)
from agent.models.poster_campaign_qa import (
    CAMPAIGN_REJECTION_REASONS,
    CampaignMachineQA,
    CampaignPostCompositionQA,
    CampaignPreProviderLint,
    CampaignQADimension,
    CampaignReviewRequest,
    WorldClassPosterReview,
)
from agent.models.poster_render_manifest import (
    PosterRenderManifest,
    PosterRenderReport,
)


class CampaignQAError(ValueError):
    def __init__(self, code: str, message: str = "") -> None:
        detail = message or code
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.message = detail


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _candidate_value(candidate: CampaignCopyRoute | dict[str, Any], key: str) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key)
    return getattr(candidate, key, None)


def _candidate_score(candidate: CampaignCopyRoute | dict[str, Any]) -> int:
    score = _candidate_value(candidate, "score")
    return int(score.get("total", 0) if isinstance(score, dict) else getattr(score, "total", 0))


def _candidate_proofs(candidate: CampaignCopyRoute | dict[str, Any]) -> list[str]:
    values = _candidate_value(candidate, "approved_proof_points")
    if values is None:
        values = _candidate_value(candidate, "proof_points")
    return [_clean(value) for value in values or [] if _clean(value)]


def _prompt_copy_leaks(
    compiled_prompt: str,
    candidate: CampaignCopyRoute | dict[str, Any],
) -> list[str]:
    # Creative Campaign deliberately carries approved product facts in the
    # visual-grounding section so the provider can stage the right ritual and
    # materials.  Those facts are not the operator's marketing copy.  Mask
    # that typed grounding line before scanning the candidate fields; a proof
    # chip may be a bounded substring of an approved fact because poster-native
    # chip limits are shorter than some approved fact strings.
    prompt_without_grounding_facts = re.sub(
        r"(?im)^[ \t]*approved product facts only:[^\r\n]*(?:\r?\n|$)",
        "\n",
        str(compiled_prompt or ""),
    )
    prompt = _clean(prompt_without_grounding_facts).casefold()
    leaks: list[str] = []
    for key in ("primary_message", "support_message", "cta"):
        value = _clean(_candidate_value(candidate, key))
        if len(value) >= 4 and value.casefold() in prompt:
            leaks.append(key)
    for index, value in enumerate(_candidate_proofs(candidate), 1):
        if len(value) >= 4 and value.casefold() in prompt:
            leaks.append(f"proof_points[{index}]")
    # Literal field labels mean a caller serialised the copy layout into a
    # clean-KV prompt instead of passing structural copy-space only.
    if re.search(r"\b(?:headline|support|cta)\s*[:=]\s*\S", prompt):
        leaks.append("COPY_FIELD_LABEL")
    return sorted(set(leaks))


def build_pre_provider_lint(
    *,
    product_id: str,
    reference_pack: Any,
    brief: PosterCampaignDesignBrief,
    candidate: CampaignCopyRoute | dict[str, Any],
    compiled_prompt: str,
    model: str = "NANO_BANANA_PRO",
    output_intent: str = "CLEAN_KEY_VISUAL",
    max_provider_operations: int = 1,
    max_retry_operations: int = 0,
    live: bool = False,
    feature_enabled: bool = False,
    live_authorized: bool = False,
) -> CampaignPreProviderLint:
    """Validate every known gate before `/api/flow/generate` is called."""

    blockers: list[str] = []
    warnings: list[str] = []
    pack_status = _clean(getattr(reference_pack, "pack_status", "")) or _clean(
        (reference_pack or {}).get("pack_status") if isinstance(reference_pack, dict) else ""
    ) or "UNVERIFIED"
    approved_intelligence = brief.review_status
    score = _candidate_score(candidate)
    leaks = _prompt_copy_leaks(compiled_prompt, candidate)

    if pack_status != "APPROVED":
        blockers.append("REFERENCE_PACK_APPROVAL_REQUIRED")
    if brief.missing_field_blockers or approved_intelligence != "READY_FOR_COPY_REVIEW":
        blockers.append("APPROVED_INTELLIGENCE_REQUIRED")
    if score < 72:
        blockers.append(f"COPY_SCORE_BELOW_THRESHOLD:{score}")
    if not bool(_candidate_value(candidate, "production_eligible")):
        blockers.append("COPY_ROUTE_NOT_PRODUCTION_ELIGIBLE")
    proofs = _candidate_proofs(candidate)
    if proofs and any(
        not any(
            _clean(fact).casefold() in proof.casefold()
            or proof.casefold() in _clean(fact).casefold()
            for fact in brief.approved_proof_points
        )
        for proof in proofs
    ):
        blockers.append("PROOF_APPROVED_PROVENANCE_REQUIRED")
    if leaks:
        blockers.append("CLEAN_KEY_VISUAL_MARKETING_COPY_LEAK:" + ",".join(leaks))
    if _clean(model).upper() != "NANO_BANANA_PRO":
        blockers.append("CREATIVE_CAMPAIGN_FINAL_MODEL_REQUIRED:NANO_BANANA_PRO")
    if _clean(output_intent).upper() != "CLEAN_KEY_VISUAL":
        blockers.append("CREATIVE_CAMPAIGN_CLEAN_KEY_VISUAL_REQUIRED")
    if max_provider_operations != 1:
        blockers.append("PROVIDER_OPERATION_BUDGET_MUST_EQUAL_ONE")
    if max_retry_operations != 0:
        blockers.append("HIDDEN_RETRY_DISABLED_FOR_CREATIVE_CAMPAIGN")
    if live and not feature_enabled:
        blockers.append("CREATIVE_CAMPAIGN_FEATURE_DISABLED")
    if live and not live_authorized:
        blockers.append("CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZATION_REQUIRED")
    if not leaks:
        warnings.append("CLEAN_KEY_VISUAL_PROMPT_COPY_SCAN_PASS")
    warnings.append("GENERATED_OUTPUT_STILL_REQUIRES_MACHINE_AND_HUMAN_REVIEW")
    return CampaignPreProviderLint(
        allowed=not blockers,
        product_id=_clean(product_id),
        reference_pack_status=pack_status,
        approved_intelligence_status=approved_intelligence,
        copy_score=score,
        model=_clean(model),
        output_intent=_clean(output_intent),
        max_provider_operations=max_provider_operations,
        max_retry_operations=max_retry_operations,
        prompt_marketing_copy_leak=bool(leaks),
        blockers=sorted(set(blockers)),
        warnings=sorted(set(warnings)),
    )


def _dimension(status: str = "UNVERIFIED", *evidence: str) -> CampaignQADimension:
    return CampaignQADimension(status=status, evidence=[_clean(item) for item in evidence if _clean(item)])


def build_campaign_machine_qa(
    media_id: str,
    *,
    vision_signals: dict[str, Any] | None = None,
) -> CampaignMachineQA:
    """Build an honest image-QA record from optional reliable vision signals."""

    signals = vision_signals or {}
    dimensions = (
        "product_identity",
        "label",
        "logo",
        "geometry",
        "scale",
        "perspective",
        "contact_shadow",
        "lighting_coherence",
        "product_background_integration",
        "unexpected_marketing_text",
        "duplicated_products",
        "human_defects",
    )
    values: dict[str, CampaignQADimension] = {}
    findings: list[str] = []
    flagged = False
    unverified = False
    for name in dimensions:
        raw = signals.get(name)
        if isinstance(raw, bool):
            status = "PASS" if raw else "BLOCK"
            values[name] = _dimension(status, "VISION_SIGNAL")
            flagged = flagged or not raw
            if not raw:
                findings.append(f"{name.upper()}_FLAGGED")
        else:
            values[name] = _dimension("UNVERIFIED", "NO_RELIABLE_VISION_CHECK_CONFIGURED")
            unverified = True
            findings.append(f"{name.upper()}_UNVERIFIED")
    status = "FAIL" if flagged else ("WARN" if unverified else "PASS")
    return CampaignMachineQA(
        media_id=_clean(media_id),
        machine_qa_status=status,
        **values,
        findings=findings,
        human_review_required=True,
    )


def _safe_margin_check(manifest: PosterRenderManifest) -> CampaignQADimension:
    violations = []
    for zone in manifest.zones:
        rect = zone.rect
        if rect.x < 5 or rect.y < 5 or rect.x + rect.w > 95 or rect.y + rect.h > 95:
            violations.append(zone.zone_id)
    return _dimension(
        "BLOCK" if violations else "PASS",
        "zones=" + ",".join(violations) if violations else "5_PERCENT_SAFE_MARGIN",
    )


def build_campaign_post_composition_qa(
    *,
    manifest: PosterRenderManifest,
    report: PosterRenderReport,
    copy_set: dict[str, Any],
    settings: dict[str, Any],
    output_sha256: str,
) -> CampaignPostCompositionQA:
    """Extend deterministic compositor QA with campaign-specific evidence."""

    checks: dict[str, CampaignQADimension] = {}
    findings: list[str] = []
    blocks = 0
    warnings = 0

    def add(name: str, result: CampaignQADimension) -> None:
        nonlocal blocks, warnings
        checks[name] = result
        if result.status == "BLOCK":
            blocks += 1
            findings.append(name.upper())
        elif result.status in {"WARN", "UNVERIFIED"}:
            warnings += 1

    expected = {zone.zone_id: zone.text for zone in manifest.zones if zone.text}
    actual = {zone.zone_id: zone.rendered_text for zone in report.zones}
    copy_exact = not report.errors and all(actual.get(key) == value for key, value in expected.items())
    add("exact_rendered_copy_identity", _dimension("PASS" if copy_exact else "BLOCK", "render_report.rendered_text"))

    cta_zones = [zone for zone in manifest.zones if _clean(zone.role).upper() == "CTA" and zone.text]
    add("exactly_one_cta", _dimension("PASS" if len(cta_zones) == 1 else "BLOCK", f"count={len(cta_zones)}"))

    strings = [_clean(value).casefold() for value in expected.values() if _clean(value)]
    duplicates = sorted({value for value in strings if strings.count(value) > 1})
    add("duplicate_string_detection", _dimension("BLOCK" if duplicates else "PASS", ",".join(duplicates)))

    add("safe_margin_violations", _safe_margin_check(manifest))
    route_ok = bool(
        manifest.design_route
        and manifest.design_route == manifest.provenance.design_route
        and manifest.layout_variant == manifest.provenance.layout_variant
        and manifest.provenance.type_pairing_id
    )
    add("route_token_consistency", _dimension("PASS" if route_ok else "BLOCK", manifest.design_route))

    headline = next(
        (zone for zone in manifest.zones if _clean(zone.role).upper() == "HEADLINE"),
        None,
    )
    line_budget = max(1, len(_clean(headline.text).split()) // 4 + 1) if headline else 1
    requested_budget = int(
        (manifest.provenance.composition_plan.get("typography") or {}).get("headline_line_budget") or line_budget
    )
    add(
        "headline_line_budget",
        _dimension("PASS" if line_budget <= requested_budget else "BLOCK", f"estimated_lines={line_budget};budget={requested_budget}"),
    )
    add("cta_visibility", _dimension("PASS" if cta_zones and cta_zones[0].text else "BLOCK", "manifest_cta"))

    total_chars = sum(len(value) for value in expected.values())
    add("excessive_copy_density", _dimension("WARN" if total_chars > 160 else "PASS", f"chars={total_chars}"))

    font_status = manifest.provenance.font_readiness_status
    add(
        "font_loaded_proof",
        _dimension("PASS" if font_status == "PASS" else "UNVERIFIED", font_status or "NO_FONT_LOAD_PROOF"),
    )
    add("contrast_threshold", _dimension("UNVERIFIED", "NO_PIXEL_CONTRAST_ANALYZER_CONFIGURED"))
    add("product_label_obstruction", _dimension("UNVERIFIED", "REFERENCE_CONDITIONED_REQUIRES_HUMAN_REVIEW"))
    add("lighting_integration", _dimension("UNVERIFIED", "NO_RELIABLE_VISION_CHECK_CONFIGURED"))
    add(
        "repeated_component_style",
        _dimension("PASS" if len({zone.font_token for zone in manifest.zones}) > 1 else "WARN", "route_font_tokens"),
    )
    add("output_manifest_hash_identity", _dimension("PASS" if len(_clean(output_sha256)) == 64 else "BLOCK", output_sha256))

    lineage_ok = bool(
        (
            _clean(manifest.background_media_id)
            or _clean(manifest.background_local_path)
        )
        and bool(settings.get("raw_key_visual_is_lineage_only"))
        and _clean(settings.get("pipeline")).startswith("CLEAN_KEY_VISUAL")
        and manifest.product_layer.strategy == "REFERENCE_CONDITIONED"
    )
    add("clean_key_visual_lineage", _dimension("PASS" if lineage_ok else "BLOCK", "provider_kv_is_background_lineage"))
    copy_provenance = bool(
        manifest.provenance.poster_copy_set_id
        and manifest.provenance.poster_copy_set_version > 0
        and isinstance(copy_set.get("field_provenance"), dict)
    )
    add("copy_provenance", _dimension("PASS" if copy_provenance else "BLOCK", "approved_copy_set_manifest_lineage"))
    add("campaign_review_status", _dimension("UNVERIFIED", "PENDING_HUMAN_REVIEW"))

    return CampaignPostCompositionQA(
        ok=blocks == 0,
        checks=checks,
        findings=findings,
        block_count=blocks,
        warn_count=warnings,
        human_review_required=True,
        campaign_review_status="PENDING_HUMAN_REVIEW",
        clean_key_visual_lineage=lineage_ok,
        copy_provenance_verified=copy_provenance,
        output_sha256=_clean(output_sha256),
    )


def build_world_class_review(request: CampaignReviewRequest) -> WorldClassPosterReview:
    invalid_reasons = [reason for reason in request.rejection_reasons if reason not in CAMPAIGN_REJECTION_REASONS]
    if invalid_reasons:
        raise CampaignQAError("INVALID_REJECTION_REASON", ",".join(invalid_reasons))
    review = WorldClassPosterReview(
        decision=request.decision,
        reviewer=request.reviewer,
        product_identity=request.product_identity,
        product_integration_physics=request.product_integration_physics,
        typography_copy_hierarchy=request.typography_copy_hierarchy,
        malaysian_context_authenticity=request.malaysian_context_authenticity,
        conversion_strength=request.conversion_strength,
        critical_findings=request.critical_findings,
        review_notes=request.review_notes,
        rejection_reasons=request.rejection_reasons,
    )
    if review.decision == "APPROVED":
        threshold_failures = []
        if review.total < 82:
            threshold_failures.append("TOTAL_LT_82")
        if review.product_identity < 22:
            threshold_failures.append("PRODUCT_IDENTITY_LT_22")
        if review.product_integration_physics < 20:
            threshold_failures.append("INTEGRATION_PHYSICS_LT_20")
        if review.typography_copy_hierarchy < 17:
            threshold_failures.append("TYPOGRAPHY_HIERARCHY_LT_17")
        if review.malaysian_context_authenticity < 11:
            threshold_failures.append("MALAYSIAN_CONTEXT_LT_11")
        if review.conversion_strength < 12:
            threshold_failures.append("CONVERSION_LT_12")
        if review.critical_findings:
            threshold_failures.append("CRITICAL_FINDINGS_PRESENT")
        if threshold_failures:
            raise CampaignQAError("WORLD_CLASS_APPROVAL_THRESHOLD_NOT_MET", ",".join(threshold_failures))
    return review


def manifest_fingerprint(manifest: PosterRenderManifest) -> str:
    return hashlib.sha256(manifest.model_dump_json().encode("utf-8")).hexdigest()
