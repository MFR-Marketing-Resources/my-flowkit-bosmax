"""Verified-taxonomy-gated P3A direct-BM lip-colour copy previews."""
from __future__ import annotations

from agent.authority.lip_color_copy_registry import (
    LIP_COLOR_COPY_REGISTRY,
    P3A_ALLOWED_PRODUCT_IDS,
    LipColorScriptSlot,
)
from agent.db import crud
from agent.models.lip_color_copy_strategy import (
    LipColorCopyStrategyResponse,
    LipColorDurationSeconds,
)
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.services.copy_set_service import scan_copy_safety
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
    get_product_strategy_taxonomy_read_model,
    require_verified_product_strategy_taxonomy,
)
from agent.services.scene_strategy_library import SCENE_STRATEGIES

P3A_CLUSTER = "beauty_makeup"
P3A_PRODUCT_TYPE_GROUP = "lipstick_lip_tint"
P3A_SCENE_STRATEGY_ID = "LIP_COLOR"
P3A_WORD_BUDGETS: dict[int, int] = {8: 19, 10: 24, 16: 38}

_P3A_POLICY_OR_SECURITY_CLAIMS = (
    "tiktok approved",
    "tiktok safe",
    "tak kena ban",
    "tak kena shadowban",
    "algorithm approved",
    "security verified",
)
_P3A_UNSUPPORTED_PERMANENCE_CLAIMS = (
    "permanent",
    "permanently",
    "kekal selamanya",
    "tahan 7 hari",
    "tahan tujuh hari",
)


class LipColorCopyStrategyError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        product_id: str,
        blocked_reasons: list[str] | None = None,
        status_code: int = 409,
    ):
        super().__init__(code)
        self.code = code
        self.product_id = product_id
        self.blocked_reasons = blocked_reasons or [code]
        self.status_code = status_code


def _taxonomy_blocked_reasons(taxonomy: ProductStrategyTaxonomy) -> list[str]:
    reasons: list[str] = []
    if taxonomy.review_status != "VERIFIED":
        reasons.append("P3A_TAXONOMY_NOT_VERIFIED")
    if taxonomy.consumer_status != "READY":
        reasons.append("P3A_TAXONOMY_NOT_READY")
    if taxonomy.authority_source != "MANUAL_OVERRIDE":
        reasons.append("P3A_AUTO_DERIVED_NOT_ALLOWED")
    if taxonomy.materialization_status != "MATERIALIZED":
        reasons.append("P3A_TAXONOMY_NOT_MATERIALIZED")
    if taxonomy.is_stale:
        reasons.append("P3A_TAXONOMY_STALE")
    if taxonomy.cluster != P3A_CLUSTER:
        reasons.append("P3A_WRONG_CLUSTER")
    if taxonomy.product_type_group != P3A_PRODUCT_TYPE_GROUP:
        reasons.append("P3A_WRONG_PRODUCT_TYPE_GROUP")
    if taxonomy.matched_scene_strategy_id != P3A_SCENE_STRATEGY_ID:
        reasons.append("P3A_SCENE_STRATEGY_MISMATCH")
    if taxonomy.scene_coverage_status != "COVERED":
        reasons.append("P3A_COVERAGE_NOT_COVERED")
    if taxonomy.fallback_used:
        reasons.append("P3A_FALLBACK_NOT_ALLOWED")
    if not taxonomy.specific_strategy:
        reasons.append("P3A_SPECIFIC_STRATEGY_REQUIRED")
    return reasons


def _product_name(product: dict[str, object]) -> str:
    for field in ("product_display_name", "raw_product_title", "product_short_name"):
        value = str(product.get(field) or "").strip()
        if value:
            return value
    return ""


def _spoken_word_count(slot: LipColorScriptSlot) -> int:
    return sum(
        len(str(slot[field]).split())
        for field in ("hook_line", "demo_line", "benefit_line", "cta_line")
    )


def _registry_copy_blockers(
    slot: LipColorScriptSlot,
    *,
    product_id: str,
    duration_seconds: int,
) -> list[str]:
    blockers: list[str] = []
    if _spoken_word_count(slot) > P3A_WORD_BUDGETS[duration_seconds]:
        blockers.append("P3A_SCRIPT_DURATION_BUDGET_EXCEEDED")

    fields = {
        "hook": slot["hook_line"],
        "subhook": slot["demo_line"],
        "usp_set": [slot["benefit_line"]],
        "cta": slot["cta_line"],
        "overlay_text": slot["overlay_text"],
    }
    safety = scan_copy_safety(fields, product_id=product_id)
    blockers.extend(f"P3A_{code}" for code in safety["violations"])

    rendered = " ".join(str(value) for value in fields.values()).casefold()
    if any(term in rendered for term in _P3A_POLICY_OR_SECURITY_CLAIMS):
        blockers.append("P3A_PLATFORM_POLICY_CLAIM_NOT_ALLOWED")
    if any(term in rendered for term in _P3A_UNSUPPORTED_PERMANENCE_CLAIMS):
        blockers.append("P3A_UNSUPPORTED_PERMANENCE_CLAIM")
    return list(dict.fromkeys(blockers))


def _scene_action(taxonomy: ProductStrategyTaxonomy, action_index: int) -> str:
    strategy = SCENE_STRATEGIES.get(taxonomy.matched_scene_strategy_id)
    if strategy is None:
        raise LipColorCopyStrategyError(
            "P3A_SCENE_STRATEGY_NOT_REGISTERED",
            product_id=taxonomy.product_id,
        )
    actions = strategy["allowed_actions"]
    if action_index >= len(actions):
        raise LipColorCopyStrategyError(
            "P3A_SCENE_ACTION_NOT_REGISTERED",
            product_id=taxonomy.product_id,
        )
    return (
        f"{actions[action_index]}; show shade, colour payoff, texture, "
        "and finished-lip result clearly"
    )


async def build_lip_color_copy_strategy(
    product_id: str,
    duration_seconds: LipColorDurationSeconds,
) -> LipColorCopyStrategyResponse:
    """Build one deterministic, non-persisting P3A copy preview."""

    if product_id not in P3A_ALLOWED_PRODUCT_IDS:
        raise LipColorCopyStrategyError(
            "P3A_PRODUCT_NOT_ALLOWED",
            product_id=product_id,
            status_code=403,
        )

    product = await crud.get_product(product_id)
    if not product:
        raise LipColorCopyStrategyError(
            "PRODUCT_NOT_FOUND",
            product_id=product_id,
            status_code=404,
        )
    if str(product.get("lifecycle_status") or "ACTIVE").upper() != "ACTIVE":
        raise LipColorCopyStrategyError(
            "P3A_PRODUCT_NOT_ACTIVE",
            product_id=product_id,
        )

    try:
        taxonomy = await get_product_strategy_taxonomy_read_model(product_id)
    except ProductStrategyTaxonomyError as exc:
        raise LipColorCopyStrategyError(
            f"P3A_{str(exc)}",
            product_id=product_id,
        ) from exc

    blocked_reasons = _taxonomy_blocked_reasons(taxonomy)
    if blocked_reasons:
        raise LipColorCopyStrategyError(
            blocked_reasons[0],
            product_id=product_id,
            blocked_reasons=blocked_reasons,
        )

    try:
        taxonomy = await require_verified_product_strategy_taxonomy(product_id)
    except ProductStrategyTaxonomyError as exc:
        raise LipColorCopyStrategyError(
            "P3A_VERIFIED_TAXONOMY_GATE_REJECTED",
            product_id=product_id,
            blocked_reasons=[f"P3A_{str(exc)}"],
        ) from exc
    post_gate_blockers = _taxonomy_blocked_reasons(taxonomy)
    if post_gate_blockers:
        raise LipColorCopyStrategyError(
            post_gate_blockers[0],
            product_id=product_id,
            blocked_reasons=post_gate_blockers,
        )

    entry = LIP_COLOR_COPY_REGISTRY[product_id]
    slot = entry["scripts"][duration_seconds]
    copy_blockers = _registry_copy_blockers(
        slot,
        product_id=product_id,
        duration_seconds=duration_seconds,
    )
    if copy_blockers:
        raise LipColorCopyStrategyError(
            copy_blockers[0],
            product_id=product_id,
            blocked_reasons=copy_blockers,
            status_code=422,
        )

    product_name = _product_name(product)
    if not product_name:
        raise LipColorCopyStrategyError(
            "P3A_PRODUCT_NAME_MISSING",
            product_id=product_id,
            status_code=422,
        )

    return LipColorCopyStrategyResponse(
        product_id=product_id,
        product_name=product_name,
        cluster=P3A_CLUSTER,
        product_type_group=P3A_PRODUCT_TYPE_GROUP,
        scene_strategy_id=P3A_SCENE_STRATEGY_ID,
        copy_strategy_id=entry["copy_strategy_id"],
        duration_seconds=duration_seconds,
        hook_line=slot["hook_line"],
        demo_line=slot["demo_line"],
        benefit_line=slot["benefit_line"],
        cta_line=slot["cta_line"],
        overlay_text=slot["overlay_text"],
        scene_action=_scene_action(taxonomy, entry["scene_action_index"]),
        blocked_reasons=[],
    )
