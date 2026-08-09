"""Fail-closed QA and review orchestration for Creative Campaign posters.

This service deliberately separates deterministic render checks, machine-image
evidence and human visual review. Missing vision/font evidence is UNVERIFIED;
it is never upgraded to PASS by a payload or by a prompt.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
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


def _font_loaded_proof(
    manifest: PosterRenderManifest,
    report: PosterRenderReport,
) -> CampaignQADimension:
    """Evaluate renderer-backed font evidence; never trust template metadata.

    PASS requires ``document.fonts.ready``, every required family/weight check,
    every rendered zone's check, and no fallback flag.  An explicit missing or
    fallback result is a deterministic BLOCK; absent/legacy evidence remains
    UNVERIFIED so a Campaign review can never silently claim typography PASS.
    """

    fonts = report.fonts if isinstance(report.fonts, dict) else {}
    if not fonts:
        return _dimension("UNVERIFIED", "NO_RUNTIME_FONT_PROOF")
    required = fonts.get("required")
    zone_evidence = fonts.get("zone_evidence")
    missing = [str(item) for item in (fonts.get("missing_families") or []) if _clean(item)]
    explicit_failure = bool(missing)
    for item in required if isinstance(required, list) else []:
        if not isinstance(item, dict):
            explicit_failure = True
            continue
        if (
            item.get("document_fonts_check") is False
            or item.get("availability_check") is False
            or item.get("fallback_detected") is True
        ):
            explicit_failure = True
    for item in zone_evidence if isinstance(zone_evidence, list) else []:
        if not isinstance(item, dict):
            explicit_failure = True
            continue
        if item.get("document_fonts_check") is False or item.get("fallback_detected") is True:
            explicit_failure = True
    if explicit_failure:
        return _dimension("BLOCK", "FONT_FALLBACK_OR_MISSING", ",".join(missing))
    if fonts.get("document_fonts_ready") is not True:
        return _dimension("UNVERIFIED", "DOCUMENT_FONTS_READY_NOT_PROVEN")
    expected_zone_ids = {zone.zone_id for zone in manifest.zones if zone.text}
    proven_zone_ids = {
        str(item.get("zone_id"))
        for item in (zone_evidence if isinstance(zone_evidence, list) else [])
        if isinstance(item, dict) and _clean(item.get("zone_id"))
    }
    if not expected_zone_ids.issubset(proven_zone_ids):
        return _dimension(
            "UNVERIFIED",
            "ZONE_FONT_PROOF_INCOMPLETE",
            f"missing={','.join(sorted(expected_zone_ids - proven_zone_ids))}",
        )
    if isinstance(required, list) and any(
        not isinstance(item, dict)
        or item.get("document_fonts_check") is not True
        or item.get("availability_check") is not True
        or item.get("fallback_detected") is not False
        for item in required
    ):
        return _dimension("UNVERIFIED", "REQUIRED_FONT_WEIGHT_PROOF_INCOMPLETE")
    if any(
        not isinstance(item, dict)
        or item.get("document_fonts_check") is not True
        or item.get("fallback_detected") is not False
        for item in (zone_evidence if isinstance(zone_evidence, list) else [])
    ):
        return _dimension("UNVERIFIED", "ZONE_FONT_RUNTIME_PROOF_INCOMPLETE")
    return _dimension("PASS", "DOCUMENT_FONTS_READY", "ALL_REQUIRED_FAMILY_WEIGHT_CHECKS_PASS")


def _parse_css_color(value: Any) -> tuple[float, float, float, float] | None:
    raw = _clean(value).lower()
    if not raw:
        return None
    if raw.startswith("#"):
        hex_value = raw[1:]
        if len(hex_value) == 3:
            hex_value = "".join(char * 2 for char in hex_value)
        if len(hex_value) not in {6, 8} or not re.fullmatch(r"[0-9a-f]+", hex_value):
            return None
        alpha = int(hex_value[6:8], 16) / 255 if len(hex_value) == 8 else 1.0
        return tuple(int(hex_value[index : index + 2], 16) for index in (0, 2, 4)) + (alpha,)
    match = re.fullmatch(r"rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)(?:\s*,\s*([0-9.]+))?\s*\)", raw)
    if not match:
        return None
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return (float(match.group(1)), float(match.group(2)), float(match.group(3)), alpha)


def _composite_color(
    foreground: tuple[float, float, float, float],
    background: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    alpha = max(0.0, min(1.0, foreground[3]))
    return tuple(
        foreground[index] * alpha + background[index] * (1.0 - alpha)
        for index in range(3)
    ) + (1.0,)


def _relative_luminance(color: tuple[float, float, float, float]) -> float:
    channels = []
    for channel in color[:3]:
        value = max(0.0, min(255.0, float(channel))) / 255.0
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(
    foreground: tuple[float, float, float, float],
    background: tuple[float, float, float, float],
) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _sample_background_pixels(image: Any, rect: Any) -> list[tuple[float, float, float, float]]:
    width, height = image.size
    left = max(0, min(width - 1, int(float(rect.x) / 100 * width)))
    top = max(0, min(height - 1, int(float(rect.y) / 100 * height)))
    right = max(left + 1, min(width, int((float(rect.x) + float(rect.w)) / 100 * width)))
    bottom = max(top + 1, min(height, int((float(rect.y) + float(rect.h)) / 100 * height)))
    if right - left < 2 or bottom - top < 2:
        return []
    samples: list[tuple[float, float, float, float]] = []
    for row in range(4):
        y = min(bottom - 1, top + int((row + 0.5) * (bottom - top) / 4))
        for column in range(4):
            x = min(right - 1, left + int((column + 0.5) * (right - left) / 4))
            pixel = image.getpixel((x, y))
            if len(pixel) == 3:
                samples.append((float(pixel[0]), float(pixel[1]), float(pixel[2]), 1.0))
            else:
                samples.append(tuple(float(value) for value in pixel[:4]))
    return samples


def _contrast_dimension(
    manifest: PosterRenderManifest,
    *,
    background_path: str,
    output_path: str,
) -> CampaignQADimension:
    """Measure deterministic text contrast from the final PNG's real canvas.

    The clean-key-visual file is the actual visual underneath the compositor
    text.  For ordinary text we sample its exact zone from that file; opaque
    CTA/chip component colours are measured against their declared component
    background.  A conservative 10th-percentile contrast ratio must be at
    least 4.5 for every zone.  This is a BOSMAX readability gate, not a claim
    of formal WCAG conformance.
    """

    if not output_path or not background_path:
        return _dimension("UNVERIFIED", "CONTRAST_ARTIFACT_PATH_MISSING")
    try:
        from PIL import Image

        with Image.open(Path(output_path)) as final_image, Image.open(Path(background_path)) as background_image:
            final_image = final_image.convert("RGBA")
            background_image = background_image.convert("RGBA")
            canvas = manifest.canvas or {}
            expected_size = (int(canvas.get("w") or 0), int(canvas.get("h") or 0))
            if expected_size != final_image.size:
                return _dimension("UNVERIFIED", "FINAL_PNG_DIMENSIONS_UNPROVEN")
            if background_image.width < 2 or background_image.height < 2:
                return _dimension("UNVERIFIED", "BACKGROUND_PIXELS_UNMEASURABLE")
            palette = manifest.palette or {}
            styles = manifest.component_styles or {}
            ratios_by_zone: list[tuple[str, float]] = []
            for zone in manifest.zones:
                token = manifest.font_tokens.get(zone.font_token) or manifest.font_tokens.get("body") or {}
                foreground = _parse_css_color(token.get("color")) if isinstance(token, dict) else None
                if foreground is None:
                    return _dimension("UNVERIFIED", f"FOREGROUND_COLOR_UNPARSEABLE:{zone.zone_id}")
                source_samples = _sample_background_pixels(background_image, zone.rect)
                if len(source_samples) < 4:
                    return _dimension("UNVERIFIED", f"BACKGROUND_SAMPLE_INSUFFICIENT:{zone.zone_id}")
                component_spec = None
                if zone.component == "cta_button":
                    component_spec = palette.get("accent") or (styles.get("cta_button") or {}).get("background")
                elif zone.component == "chip":
                    component_spec = palette.get("chip_bg") or (styles.get("chip") or {}).get("background")
                component = _parse_css_color(component_spec)
                backgrounds = source_samples
                if component is not None and component[3] >= 0.999:
                    backgrounds = [component] * len(source_samples)
                elif component is not None:
                    backgrounds = [_composite_color(component, sample) for sample in source_samples]
                ratios = sorted(_contrast_ratio(foreground, sample) for sample in backgrounds)
                p10_index = max(0, min(len(ratios) - 1, math.ceil(len(ratios) * 0.10) - 1))
                p10 = ratios[p10_index]
                ratios_by_zone.append((zone.zone_id, p10))
            if not ratios_by_zone:
                return _dimension("UNVERIFIED", "NO_TEXT_ZONES")
            evidence = [
                "algorithm=10th_percentile_zone_sampling",
                "threshold=4.5",
                "formal_wcag_claim=false",
                *[f"{zone}=p10:{ratio:.2f}" for zone, ratio in ratios_by_zone[:9]],
            ]
            if any(ratio < 4.5 for _, ratio in ratios_by_zone):
                return _dimension("BLOCK", *evidence)
            return _dimension("PASS", *evidence)
    except (OSError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _dimension("UNVERIFIED", f"CONTRAST_MEASUREMENT_AMBIGUOUS:{type(exc).__name__}")


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
    background_path: str = "",
    output_path: str = "",
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

    add("font_loaded_proof", _font_loaded_proof(manifest, report))
    add(
        "contrast_threshold",
        _contrast_dimension(
            manifest,
            background_path=_clean(background_path) or _clean(manifest.background_local_path),
            output_path=_clean(output_path),
        ),
    )
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
