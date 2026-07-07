"""Poster copy kit recommendations — copy bank first, AI assist second, safe fallbacks."""
from __future__ import annotations

import uuid
from typing import Any

from agent.db import crud
from agent.models.copy_set import (
    AICopyAssistRequest,
    STATUS_COPY_APPROVED,
    STATUS_COPY_REVIEW_REQUIRED,
    STATUS_DRAFT_COPY,
    serialize_copy_set,
)
from agent.models.poster_copy_recommendations import (
    PosterCopyKit,
    PosterCopyRecommendationRequest,
    PosterCopyRecommendationsResponse,
    PosterKitSource,
    PosterKitStatus,
)
from agent.models.poster_readiness import PosterReadinessStatus
from agent.services import ai_copy_assist_service as ai_svc
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services.copy_set_service import _normalize_fields, scan_copy_safety
from agent.services.poster_prompt_draft_service import UNSAFE_CLAIM_TERMS
from agent.services.poster_readiness_service import PosterReadinessService

MAX_KITS = 5
RESTRICTED_ANGLES = (
    "Daily comfort routine",
    "Heritage trust",
    "Portable standby",
    "Product size clarity",
    "Lifestyle convenience",
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _usp_triple(usp_set: Any) -> tuple[str, str, str]:
    items = usp_set if isinstance(usp_set, list) else []
    padded = [_norm(x) for x in items] + ["", "", ""]
    return padded[0], padded[1], padded[2]


def _operator_fields_from_kit(kit: dict[str, str]) -> dict[str, str]:
    return {
        "hook": kit.get("hook", ""),
        "subhook": kit.get("subhook", ""),
        "usp_1": kit.get("usp_1", ""),
        "usp_2": kit.get("usp_2", ""),
        "usp_3": kit.get("usp_3", ""),
        "cta": kit.get("cta", ""),
    }


def _unsafe_operator_copy(fields: dict[str, str]) -> list[str]:
    hits: list[str] = []
    blob = " ".join(_norm(v).lower() for v in fields.values())
    for term in UNSAFE_CLAIM_TERMS:
        if term in blob:
            hits.append(term)
    return hits


def _safety_for_product(fields: dict[str, Any], product_id: str) -> dict[str, Any]:
    return scan_copy_safety(fields, product_id=product_id)


def _settings_from_request(req: PosterCopyRecommendationRequest) -> dict[str, str]:
    return {
        "poster_objective": _norm(req.poster_objective) or "Product awareness",
        "poster_type": _norm(req.poster_type) or "Product-only hero poster",
        "frame_ratio": _norm(req.frame_ratio) or "9:16",
        "language": _norm(req.language) or "ms",
        "visual_route": _norm(req.visual_route) or "Premium commercial",
        "human_presence_mode": _norm(req.human_presence_mode)
        or "No human / product-forward",
        "text_density": _norm(req.text_density) or "medium",
        "brand_tone": _norm(req.brand_tone),
        "background_environment": _norm(req.background_environment),
    }


def _kit_from_copy_row(
    row: dict[str, Any],
    *,
    settings: dict[str, str],
    source: PosterKitSource,
    status: PosterKitStatus,
    product_id: str,
) -> PosterCopyKit | None:
    cs = serialize_copy_set(row)
    usp1, usp2, usp3 = _usp_triple(cs.get("usp_set"))
    fields = {
        "angle": _norm(cs.get("angle")),
        "hook": _norm(cs.get("hook")),
        "subhook": _norm(cs.get("subhook")),
        "usp_set": [usp1, usp2, usp3],
        "cta": _norm(cs.get("cta")),
    }
    safety = _safety_for_product(fields, product_id)
    op = _operator_fields_from_kit(
        {"hook": fields["hook"], "subhook": fields["subhook"], "usp_1": usp1, "usp_2": usp2, "usp_3": usp3, "cta": fields["cta"]}
    )
    unsafe = _unsafe_operator_copy(op)
    blocked: list[str] = []
    notes: list[str] = []
    if not safety.get("safe", True):
        blocked.extend(safety.get("violations") or [])
    if unsafe:
        blocked.append(f"unsafe_terms:{','.join(unsafe)}")
    if blocked:
        return None
    return PosterCopyKit(
        kit_id=cs.get("copy_set_id") or str(uuid.uuid4()),
        status=status,
        source=source,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_1=usp1,
        usp_2=usp2,
        usp_3=usp3,
        cta=fields["cta"],
        poster_type=settings["poster_type"],
        visual_route=settings["visual_route"],
        human_presence_mode=settings["human_presence_mode"],
        frame_ratio=settings["frame_ratio"],
        language=settings["language"],
        text_density=settings["text_density"],
        background_environment=settings["background_environment"],
        brand_tone=settings["brand_tone"],
        safety_notes=notes,
        blocked_reasons=blocked,
        copy_set_id=cs.get("copy_set_id"),
    )


def _fallback_kits(
    product: dict[str, Any],
    settings: dict[str, str],
    *,
    restricted: bool,
) -> list[PosterCopyKit]:
    name = _norm(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or "Product"
    )
    angles = RESTRICTED_ANGLES if restricted else (
        "Daily convenience",
        "Trust & heritage",
        "Problem-solution clarity",
        "Premium product hero",
        "Compact portability",
    )
    kits: list[PosterCopyKit] = []
    for i, angle in enumerate(angles[:MAX_KITS]):
        hook = f"{name} — {angle.lower()}"
        subhook = "Designed for everyday use. Product truth locked."
        usp1 = "Easy to carry"
        usp2 = "Daily routine friendly"
        usp3 = "Clear product presentation"
        cta = "Learn more"
        fields = {
            "angle": angle,
            "hook": hook,
            "subhook": subhook,
            "usp_set": [usp1, usp2, usp3],
            "cta": cta,
        }
        if not _safety_for_product(fields, product["id"]).get("safe", True):
            continue
        if _unsafe_operator_copy(_operator_fields_from_kit(
            {"hook": hook, "subhook": subhook, "usp_1": usp1, "usp_2": usp2, "usp_3": usp3, "cta": cta}
        )):
            continue
        kits.append(
            PosterCopyKit(
                kit_id=f"fallback-{i}",
                status=PosterKitStatus.CANDIDATE,
                source=PosterKitSource.FALLBACK_TEMPLATE,
                angle=angle,
                hook=hook,
                subhook=subhook,
                usp_1=usp1,
                usp_2=usp2,
                usp_3=usp3,
                cta=cta,
                poster_type=settings["poster_type"],
                visual_route=settings["visual_route"],
                human_presence_mode=settings["human_presence_mode"],
                frame_ratio=settings["frame_ratio"],
                language=settings["language"],
                text_density=settings["text_density"],
                background_environment=settings["background_environment"]
                or "Clean studio background",
                brand_tone=settings["brand_tone"] or "Friendly commercial",
                safety_notes=["Fallback template — review before production."],
            )
        )
    return kits


async def _ai_ephemeral_kits(
    req: PosterCopyRecommendationRequest,
    product: dict[str, Any],
    settings: dict[str, str],
    count: int,
) -> tuple[list[PosterCopyKit], list[str]]:
    warnings: list[str] = []
    if not ai_provider.is_configured():
        warnings.append("AI provider not configured — using fallback templates only.")
        return [], warnings
    kits: list[PosterCopyKit] = []
    assist = AICopyAssistRequest(
        product_id=req.product_id,
        language=settings["language"],
        platform="TIKTOK",
        operator_notes=(
            f"Poster objective: {settings['poster_objective']}. "
            f"Poster type: {settings['poster_type']}. "
            f"Visual route: {settings['visual_route']}. "
            "Generate safe commercial poster copy only. No medical claims."
        ),
    )
    for i in range(count):
        try:
            brief = ai_svc._build_brief(assist, product)
            raw = ai_provider.generate_candidate(brief)
            if not isinstance(raw, dict):
                warnings.append(f"AI candidate {i + 1} invalid response.")
                continue
            fields = ai_svc._merge_candidate_fields(raw, assist)
            fields = _normalize_fields(fields)
            safety = _safety_for_product(fields, req.product_id)
            usp1, usp2, usp3 = _usp_triple(fields.get("usp_set"))
            op = {
                "hook": _norm(fields.get("hook")),
                "subhook": _norm(fields.get("subhook")),
                "usp_1": usp1,
                "usp_2": usp2,
                "usp_3": usp3,
                "cta": _norm(fields.get("cta")),
            }
            if not safety.get("safe", True) or _unsafe_operator_copy(op):
                warnings.append(f"AI candidate {i + 1} filtered (unsafe/incomplete).")
                continue
            kits.append(
                PosterCopyKit(
                    kit_id=f"ai-{uuid.uuid4().hex[:12]}",
                    status=PosterKitStatus.CANDIDATE,
                    source=PosterKitSource.AI_CANDIDATE,
                    angle=_norm(fields.get("angle")),
                    hook=op["hook"],
                    subhook=op["subhook"],
                    usp_1=usp1,
                    usp_2=usp2,
                    usp_3=usp3,
                    cta=op["cta"],
                    poster_type=settings["poster_type"],
                    visual_route=settings["visual_route"],
                    human_presence_mode=settings["human_presence_mode"],
                    frame_ratio=settings["frame_ratio"],
                    language=settings["language"],
                    text_density=settings["text_density"],
                    background_environment=settings["background_environment"]
                    or "Studio gradient",
                    brand_tone=settings["brand_tone"] or "Premium commercial",
                    safety_notes=["AI candidate — not approved until operator reviews."],
                )
            )
        except ai_provider.AICopyProviderError as exc:
            warnings.append(str(exc.code or exc))
            break
    return kits, warnings


class PosterCopyRecommendationService:
    @staticmethod
    async def recommend(
        request: PosterCopyRecommendationRequest | dict,
    ) -> PosterCopyRecommendationsResponse:
        req = (
            request
            if isinstance(request, PosterCopyRecommendationRequest)
            else PosterCopyRecommendationRequest.model_validate(request)
        )
        product = await crud.get_product(req.product_id)
        if not product:
            raise ValueError("PRODUCT_NOT_FOUND")

        readiness = await PosterReadinessService.evaluate_product(product, enrich=False)
        settings = _settings_from_request(req)
        status = readiness.poster_status
        warnings: list[str] = []

        if status == PosterReadinessStatus.POSTER_BLOCKED:
            return PosterCopyRecommendationsResponse(
                product_id=req.product_id,
                product_display_name=readiness.product_display_name,
                poster_status=status.value,
                generation_allowed=False,
                blocked_reasons=list(readiness.blockers),
                repair_actions=[a.model_dump(mode="json") for a in readiness.repair_actions],
            )

        if status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED:
            return PosterCopyRecommendationsResponse(
                product_id=req.product_id,
                product_display_name=readiness.product_display_name,
                poster_status=status.value,
                generation_allowed=False,
                blocked_reasons=list(readiness.blockers),
                repair_actions=[a.model_dump(mode="json") for a in readiness.repair_actions],
                warnings=["Repair required — no usable poster kits for prompt generation."],
            )

        restricted = status == PosterReadinessStatus.POSTER_READY_RESTRICTED
        preview_only = status == PosterReadinessStatus.POSTER_PREVIEW_ONLY
        generation_allowed = readiness.generation_allowed and not preview_only

        kits: list[PosterCopyKit] = []
        rows = await crud.list_copy_sets_for_product(req.product_id)
        for row in rows:
            st = row.get("status")
            if st == STATUS_COPY_APPROVED and not row.get("archived"):
                kit = _kit_from_copy_row(
                    row,
                    settings=settings,
                    source=PosterKitSource.APPROVED_COPY_SET,
                    status=PosterKitStatus.APPROVED,
                    product_id=req.product_id,
                )
                if kit:
                    kits.append(kit)
            elif st in (STATUS_COPY_REVIEW_REQUIRED, STATUS_DRAFT_COPY):
                kit = _kit_from_copy_row(
                    row,
                    settings=settings,
                    source=PosterKitSource.DRAFT_COPY_SET,
                    status=PosterKitStatus.DRAFT,
                    product_id=req.product_id,
                )
                if kit:
                    kits.append(kit)

        primary_source = PosterKitSource.APPROVED_COPY_SET if any(
            k.source == PosterKitSource.APPROVED_COPY_SET for k in kits
        ) else ""

        if len(kits) < MAX_KITS and (req.refresh_ai or not kits):
            ai_kits, ai_warn = await _ai_ephemeral_kits(
                req, product, settings, MAX_KITS - len(kits)
            )
            warnings.extend(ai_warn)
            kits.extend(ai_kits)
            if ai_kits and not primary_source:
                primary_source = PosterKitSource.AI_CANDIDATE

        if len(kits) < 3:
            fb = _fallback_kits(product, settings, restricted=restricted)
            for kit in fb:
                if len(kits) >= MAX_KITS:
                    break
                if not any(k.hook == kit.hook and k.angle == kit.angle for k in kits):
                    kits.append(kit)
            if fb and not primary_source:
                primary_source = PosterKitSource.FALLBACK_TEMPLATE

        kits = kits[:MAX_KITS]
        if not primary_source and kits:
            primary_source = kits[0].source

        if preview_only:
            warnings.append(
                "Preview-only readiness — recommendations are diagnostic; production export not approved."
            )

        return PosterCopyRecommendationsResponse(
            product_id=req.product_id,
            product_display_name=readiness.product_display_name,
            poster_status=status.value,
            generation_allowed=generation_allowed,
            recommendation_source=primary_source or PosterKitSource.FALLBACK_TEMPLATE,
            recommendations=kits,
            blocked_reasons=[] if kits else ["NO_USABLE_KITS"],
            repair_actions=[a.model_dump(mode="json") for a in readiness.repair_actions],
            ai_provider_status=ai_provider.provider_status(),
            warnings=warnings,
        )