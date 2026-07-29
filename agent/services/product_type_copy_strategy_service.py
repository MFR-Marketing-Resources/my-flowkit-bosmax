"""Verified-taxonomy-gated P4 product-type copy previews and eligibility."""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from typing import TypedDict

from agent.authority.product_type_copy_strategy_registry import (
    PRODUCT_TYPE_COPY_STRATEGY_REGISTRY,
    ProductTypeCopyScriptTemplate,
    ProductTypeCopyStrategyEntry,
    ProductTypeCopyStrategyKey,
)
from agent.db import crud
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.models.product_type_copy_strategy import (
    ProductTypeCopyDurationSeconds,
    ProductTypeCopyEligibleReport,
    ProductTypeCopyReportGroup,
    ProductTypeCopyReportProduct,
    ProductTypeCopyStrategyResponse,
)
from agent.services.copy_set_service import scan_copy_safety
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
    attach_product_strategy_taxonomies,
    get_product_strategy_taxonomy_read_model,
    require_verified_product_strategy_taxonomy,
)
from agent.services.scene_strategy_library import SCENE_STRATEGIES

P4_WORD_BUDGETS: dict[int, int] = {8: 19, 10: 24, 16: 38}
P4_REPORT_SAMPLE_LIMIT = 20

_SIZE_PATTERN = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(g|gram|grams|ml)\b",
    re.IGNORECASE,
)
_PROMO_PREFIX_PATTERN = re.compile(r"^\s*(?:\[[^\]]+\]\s*)+")
_TOKEN_PATTERN = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:['’-][A-Za-zÀ-ÿ0-9]+)?")
_LIP_TYPE_PATTERN = re.compile(
    r"\b(lip\s*tint|lip\s*gloss|lip\s*matte|lipmatte|lipstick|lipstik)\b",
    re.IGNORECASE,
)
_LIP_REFERENCE_NOISE = frozenset(
    {
        "all",
        "all-day",
        "blurring",
        "edition",
        "full",
        "ink",
        "lasting",
        "liquid",
        "lock",
        "long",
        "matte",
        "perfect",
        "stay",
        "super",
        "to",
        "transfer",
        "two-in-one",
        "waterproof",
        "wear",
    }
)
_P4_UNSAFE_CLAIM_TERMS = (
    "tiktok approved",
    "tiktok safe",
    "tiktok rasmi",
    "official tiktok",
    "tak kena ban",
    "tak kena shadowban",
    "algorithm approved",
    "security verified",
    "checkout selamat",
    "secure checkout",
    "sakit",
    "rawat",
    "merawat",
    "sembuh",
    "ubat",
    "detox",
    "kurus",
    "buang angin",
    "legakan",
    "no side effects",
    "confirm",
    "gerenti",
    "dijamin",
    "guaranteed",
    "pasti",
    "terjamin",
    "instant result",
    "permanent",
    "kekal selamanya",
    "tahan 7 hari",
    "7 hari",
    "16h",
    "24h",
    "48h",
    "long lasting",
    "all-day wear",
    "transfer proof",
    "waterproof",
    "kkm",
    "npra",
    "klinikal",
    "doktor",
    "premium lifestyle",
    "lifestyle premium",
)

_REGISTERED_SCENES_BY_PRODUCT_TYPE: dict[tuple[str, str], frozenset[str]] = {}
for _cluster, _product_type_group, _scene_strategy_id in (
    PRODUCT_TYPE_COPY_STRATEGY_REGISTRY
):
    _pair = (_cluster, _product_type_group)
    _REGISTERED_SCENES_BY_PRODUCT_TYPE[_pair] = frozenset(
        {
            *_REGISTERED_SCENES_BY_PRODUCT_TYPE.get(_pair, frozenset()),
            _scene_strategy_id,
        }
    )


class ProductTypeCopyFacts(TypedDict):
    product_name: str
    product_reference: str
    product_descriptor: str
    size_label: str
    use_context: str
    benefit_evidence: str
    finish_descriptor: str
    cta_prompt: str
    overlay_label: str


class ProductTypeCopyStrategyError(RuntimeError):
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


def _strategy_key(
    taxonomy: ProductStrategyTaxonomy,
) -> ProductTypeCopyStrategyKey:
    return (
        taxonomy.cluster,
        taxonomy.product_type_group,
        taxonomy.matched_scene_strategy_id,
    )


def _taxonomy_blocked_reasons(
    taxonomy: ProductStrategyTaxonomy,
) -> list[str]:
    reasons: list[str] = []
    if taxonomy.review_status != "VERIFIED":
        reasons.append("TAXONOMY_NOT_VERIFIED")
    if taxonomy.consumer_status != "READY":
        reasons.append("TAXONOMY_NOT_READY")
    if taxonomy.authority_source != "MANUAL_OVERRIDE":
        reasons.append("AUTO_DERIVED_NOT_ALLOWED")
    if taxonomy.materialization_status != "MATERIALIZED":
        reasons.append("TAXONOMY_NOT_MATERIALIZED")
    if taxonomy.is_stale:
        reasons.append("TAXONOMY_STALE")
    if taxonomy.scene_coverage_status != "COVERED":
        reasons.append("COVERAGE_NOT_COVERED")
    if taxonomy.fallback_used:
        reasons.append("FALLBACK_NOT_ALLOWED")
    if not taxonomy.specific_strategy:
        reasons.append("SPECIFIC_STRATEGY_REQUIRED")

    key = _strategy_key(taxonomy)
    pair = key[:2]
    registered_scenes = _REGISTERED_SCENES_BY_PRODUCT_TYPE.get(pair)
    if registered_scenes is not None and key[2] not in registered_scenes:
        reasons.append("SCENE_STRATEGY_MISMATCH")
    elif key not in PRODUCT_TYPE_COPY_STRATEGY_REGISTRY:
        reasons.append("COPY_STRATEGY_NOT_REGISTERED")
    return list(dict.fromkeys(reasons))


def _product_name(product: Mapping[str, object]) -> str:
    for field in (
        "product_display_name",
        "raw_product_title",
        "product_short_name",
    ):
        value = str(product.get(field) or "").strip()
        if value:
            return value
    return ""


def _approved_safe_product_name(product: Mapping[str, object]) -> str:
    if product.get("claim_safe_copy_status") != "CLAIM_SAFE_COPY_APPROVED":
        return ""
    try:
        payload = json.loads(str(product.get("claim_safe_copy_payload") or "{}"))
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("safe_product_name") or "").strip()


def _product_texts(product: Mapping[str, object]) -> list[str]:
    values = [
        _approved_safe_product_name(product),
        str(product.get("product_display_name") or "").strip(),
        str(product.get("raw_product_title") or "").strip(),
        str(product.get("product_short_name") or "").strip(),
    ]
    return list(dict.fromkeys(value for value in values if value))


def _size_label(product: Mapping[str, object]) -> str:
    for text in _product_texts(product):
        match = _SIZE_PATTERN.search(text)
        if not match:
            continue
        value = match.group(1).replace(",", ".")
        unit = match.group(2).casefold()
        if unit in {"gram", "grams"}:
            unit = "g"
        return f"{value}{unit}"
    return ""


def _clean_product_text(value: str) -> str:
    cleaned = _PROMO_PREFIX_PATTERN.sub("", value)
    cleaned = cleaned.replace("|", " ").replace("·", " ").replace("_", " ")
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def _lip_product_reference(product: Mapping[str, object]) -> tuple[str, str]:
    selected_text = ""
    selected_match: re.Match[str] | None = None
    for value in _product_texts(product):
        cleaned = _clean_product_text(value)
        match = _LIP_TYPE_PATTERN.search(cleaned)
        if match:
            selected_text = cleaned
            selected_match = match
            break

    if selected_match is None:
        return "produk warna bibir", "warna bibir"

    raw_marker = selected_match.group(1).casefold().replace("  ", " ")
    if "tint" in raw_marker:
        marker = "lip tint"
    elif "gloss" in raw_marker:
        marker = "lip gloss"
    elif "matte" in raw_marker or "lipmatte" in raw_marker:
        marker = "lip matte"
    elif "lipstik" in raw_marker:
        marker = "lipstik"
    else:
        marker = "lipstick"

    prefix = selected_text[: selected_match.start()]
    prefix_tokens: list[str] = []
    for token in _TOKEN_PATTERN.findall(prefix):
        normalized = token.casefold()
        if normalized in _LIP_REFERENCE_NOISE:
            continue
        if re.fullmatch(r"\d+(?:h|hr|jam|hari)?", normalized):
            continue
        prefix_tokens.append(token)
        if len(prefix_tokens) == 3:
            break

    reference = " ".join([*prefix_tokens, marker]).strip()
    return reference or marker, marker


def _lip_finish_descriptor(product: Mapping[str, object]) -> tuple[str, str]:
    haystack = " ".join(_product_texts(product)).casefold()
    if "gloss" in haystack:
        return "kilauan gloss", "Kilauan bibir lebih jelas"
    if "matte" in haystack or "lipmatte" in haystack:
        return "kemasan matte", "Kemasan matte lebih jelas"
    if "tint" in haystack:
        return "warna tint", "Warna tint lebih jelas"
    return "hasil warna bibir", "Warna bibir lebih jelas"


def _rempah_product_reference(product: Mapping[str, object]) -> tuple[str, str]:
    for value in _product_texts(product):
        cleaned = _clean_product_text(value)
        match = re.search(r"\brempah\b(?P<body>.*)", cleaned, re.IGNORECASE)
        if not match:
            continue
        body = re.split(
            r"\bby\b|\d+(?:[.,]\d+)?\s*(?:g|gram|grams|ml)\b|\(|/|,",
            match.group("body"),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        context_tokens = _TOKEN_PATTERN.findall(body)[:4]
        if context_tokens:
            context = " ".join(context_tokens)
            return f"Rempah {context}", context.casefold()
    return "rempah masakan", "hidangan pilihan"


def _overlay_label(product_reference: str, size_label: str) -> str:
    value = product_reference.upper()
    if size_label:
        value = f"{value} • {size_label.upper()}"
    if len(value) <= 48:
        return value
    shortened = value[:48].rsplit(" ", 1)[0].strip()
    return shortened or value[:48]


def _resolve_product_facts(
    product: Mapping[str, object],
    key: ProductTypeCopyStrategyKey,
) -> ProductTypeCopyFacts:
    product_name = _product_name(product)
    size_label = _size_label(product)
    if key == ("beauty_makeup", "lipstick_lip_tint", "LIP_COLOR"):
        product_reference, product_descriptor = _lip_product_reference(product)
        finish_descriptor, benefit_evidence = _lip_finish_descriptor(product)
        cta_prompt = (
            f"Semak shade {size_label}."
            if size_label
            else "Semak shade pilihan."
        )
        return {
            "product_name": product_name,
            "product_reference": product_reference,
            "product_descriptor": product_descriptor,
            "size_label": size_label,
            "use_context": "sapuan bibir",
            "benefit_evidence": benefit_evidence,
            "finish_descriptor": finish_descriptor,
            "cta_prompt": cta_prompt,
            "overlay_label": _overlay_label(product_reference, size_label),
        }

    product_reference, use_context = _rempah_product_reference(product)
    benefit_evidence = (
        f"Aroma {use_context} lebih jelas"
        if use_context != "hidangan pilihan"
        else "Aroma rempah lebih jelas"
    )
    cta_prompt = (
        f"Semak pek {size_label}."
        if size_label
        else "Semak pilihan rempah."
    )
    return {
        "product_name": product_name,
        "product_reference": product_reference,
        "product_descriptor": "rempah masakan",
        "size_label": size_label,
        "use_context": use_context,
        "benefit_evidence": benefit_evidence,
        "finish_descriptor": "hasil masakan",
        "cta_prompt": cta_prompt,
        "overlay_label": _overlay_label(product_reference, size_label),
    }


def _render_script_slot(
    entry: ProductTypeCopyStrategyEntry,
    duration_seconds: int,
    facts: ProductTypeCopyFacts,
) -> ProductTypeCopyScriptTemplate:
    template = entry["scripts"][duration_seconds]
    return {
        "hook_line": template["hook_line"].format_map(facts),
        "demo_line": template["demo_line"].format_map(facts),
        "benefit_line": template["benefit_line"].format_map(facts),
        "cta_line": template["cta_line"].format_map(facts),
        "overlay_text": template["overlay_text"].format_map(facts),
    }


def _spoken_word_count(slot: ProductTypeCopyScriptTemplate) -> int:
    return sum(
        len(str(slot[field]).split())
        for field in ("hook_line", "demo_line", "benefit_line", "cta_line")
    )


def _copy_blocked_reasons(
    slot: ProductTypeCopyScriptTemplate,
    *,
    product_id: str,
    duration_seconds: int,
) -> list[str]:
    fields = {
        "hook": slot["hook_line"],
        "subhook": slot["demo_line"],
        "usp_set": [slot["benefit_line"]],
        "cta": slot["cta_line"],
        "overlay_text": slot["overlay_text"],
    }
    safety = scan_copy_safety(fields, product_id=product_id)
    rendered = " ".join(str(value) for value in slot.values()).casefold()
    if (
        _spoken_word_count(slot) > P4_WORD_BUDGETS[duration_seconds]
        or safety["violations"]
        or any(term in rendered for term in _P4_UNSAFE_CLAIM_TERMS)
    ):
        return ["UNSAFE_COPY_CLAIM"]
    return []


def _scene_action(
    taxonomy: ProductStrategyTaxonomy,
    entry: ProductTypeCopyStrategyEntry,
    facts: ProductTypeCopyFacts,
) -> str:
    strategy = SCENE_STRATEGIES.get(taxonomy.matched_scene_strategy_id)
    if strategy is None:
        raise ProductTypeCopyStrategyError(
            "SCENE_STRATEGY_MISMATCH",
            product_id=taxonomy.product_id,
        )
    actions = strategy["allowed_actions"]
    action_parts: list[str] = []
    for action_index in entry["scene_action_indices"]:
        if action_index >= len(actions):
            raise ProductTypeCopyStrategyError(
                "SCENE_STRATEGY_MISMATCH",
                product_id=taxonomy.product_id,
            )
        action_parts.append(str(actions[action_index]))
    result = entry["scene_result_template"].format_map(facts)
    return f"{'; '.join(action_parts)}; {result}"


def _normalize_duration(
    duration_seconds: ProductTypeCopyDurationSeconds | int,
    *,
    product_id: str,
) -> ProductTypeCopyDurationSeconds:
    try:
        return ProductTypeCopyDurationSeconds(duration_seconds)
    except ValueError as exc:
        raise ProductTypeCopyStrategyError(
            "UNSUPPORTED_DURATION",
            product_id=product_id,
            status_code=422,
        ) from exc


async def build_product_type_copy_strategy(
    product_id: str,
    duration_seconds: ProductTypeCopyDurationSeconds | int,
) -> ProductTypeCopyStrategyResponse:
    """Build one deterministic P4 preview without persistence or providers."""

    duration = _normalize_duration(duration_seconds, product_id=product_id)
    product = await crud.get_product(product_id)
    if not product:
        raise ProductTypeCopyStrategyError(
            "PRODUCT_NOT_FOUND",
            product_id=product_id,
            status_code=404,
        )
    if str(product.get("lifecycle_status") or "ACTIVE").upper() != "ACTIVE":
        raise ProductTypeCopyStrategyError(
            "PRODUCT_NOT_ACTIVE",
            product_id=product_id,
        )

    try:
        taxonomy = await get_product_strategy_taxonomy_read_model(product_id)
    except ProductStrategyTaxonomyError as exc:
        raise ProductTypeCopyStrategyError(
            "TAXONOMY_NOT_MATERIALIZED",
            product_id=product_id,
        ) from exc
    blocked_reasons = _taxonomy_blocked_reasons(taxonomy)
    if blocked_reasons:
        raise ProductTypeCopyStrategyError(
            blocked_reasons[0],
            product_id=product_id,
            blocked_reasons=blocked_reasons,
        )

    try:
        taxonomy = await require_verified_product_strategy_taxonomy(product_id)
    except ProductStrategyTaxonomyError as exc:
        raise ProductTypeCopyStrategyError(
            "TAXONOMY_NOT_VERIFIED",
            product_id=product_id,
        ) from exc
    post_gate_blockers = _taxonomy_blocked_reasons(taxonomy)
    if post_gate_blockers:
        raise ProductTypeCopyStrategyError(
            post_gate_blockers[0],
            product_id=product_id,
            blocked_reasons=post_gate_blockers,
        )

    key = _strategy_key(taxonomy)
    entry = PRODUCT_TYPE_COPY_STRATEGY_REGISTRY[key]
    facts = _resolve_product_facts(product, key)
    slot = _render_script_slot(entry, int(duration), facts)
    copy_blockers = _copy_blocked_reasons(
        slot,
        product_id=product_id,
        duration_seconds=int(duration),
    )
    if copy_blockers:
        raise ProductTypeCopyStrategyError(
            copy_blockers[0],
            product_id=product_id,
            blocked_reasons=copy_blockers,
            status_code=422,
        )

    return ProductTypeCopyStrategyResponse(
        product_id=product_id,
        product_name=facts["product_name"],
        cluster=taxonomy.cluster,
        product_type_group=taxonomy.product_type_group,
        scene_strategy_id=taxonomy.matched_scene_strategy_id,
        copy_strategy_id=entry["copy_strategy_id"],
        duration_seconds=duration,
        hook_line=slot["hook_line"],
        demo_line=slot["demo_line"],
        benefit_line=slot["benefit_line"],
        cta_line=slot["cta_line"],
        overlay_text=slot["overlay_text"],
        scene_action=_scene_action(taxonomy, entry, facts),
        source_strategy=entry["source_strategy"],
        blocked_reasons=[],
    )


def _report_product(
    product: Mapping[str, object],
    taxonomy: ProductStrategyTaxonomy,
    blocked_reasons: list[str],
) -> ProductTypeCopyReportProduct:
    return ProductTypeCopyReportProduct(
        product_id=taxonomy.product_id,
        product_name=_product_name(product),
        cluster=taxonomy.cluster,
        product_type_group=taxonomy.product_type_group,
        scene_strategy_id=taxonomy.matched_scene_strategy_id,
        blocked_reasons=blocked_reasons,
    )


def _report_groups(
    counts: Counter[ProductTypeCopyStrategyKey],
) -> list[ProductTypeCopyReportGroup]:
    return [
        ProductTypeCopyReportGroup(
            cluster=key[0],
            product_type_group=key[1],
            scene_strategy_id=key[2],
            count=count,
        )
        for key, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


async def build_product_type_copy_eligible_report(
) -> ProductTypeCopyEligibleReport:
    """Return a bounded read-only eligibility report for the full catalog."""

    products = await crud.list_products(include_archived=True)
    attached = await attach_product_strategy_taxonomies(products)
    eligible: list[ProductTypeCopyReportProduct] = []
    blocked: list[
        tuple[tuple[int, int, str], ProductTypeCopyReportProduct]
    ] = []
    eligible_counts: Counter[ProductTypeCopyStrategyKey] = Counter()
    missing_counts: Counter[ProductTypeCopyStrategyKey] = Counter()
    blocked_reason_counts: Counter[str] = Counter()

    for product in attached:
        taxonomy = ProductStrategyTaxonomy.model_validate(
            product["strategy_taxonomy"]
        )
        reasons: list[str] = []
        if str(product.get("lifecycle_status") or "ACTIVE").upper() != "ACTIVE":
            reasons.append("PRODUCT_NOT_ACTIVE")
        reasons.extend(_taxonomy_blocked_reasons(taxonomy))

        if not reasons:
            try:
                canonical = await require_verified_product_strategy_taxonomy(
                    taxonomy.product_id
                )
            except ProductStrategyTaxonomyError:
                reasons.append("TAXONOMY_NOT_VERIFIED")
            else:
                reasons.extend(_taxonomy_blocked_reasons(canonical))

        reasons = list(dict.fromkeys(reasons))
        report_product = _report_product(product, taxonomy, reasons)
        key = _strategy_key(taxonomy)
        if reasons:
            blocked_reason_counts.update(reasons)
            if "COPY_STRATEGY_NOT_REGISTERED" in reasons:
                missing_counts[key] += 1
            priority = (
                0 if taxonomy.review_status == "VERIFIED" else 1,
                len(reasons),
                taxonomy.product_id,
            )
            blocked.append((priority, report_product))
        else:
            eligible_counts[key] += 1
            eligible.append(report_product)

    eligible.sort(
        key=lambda item: (
            item.cluster,
            item.product_type_group,
            item.product_name.casefold(),
            item.product_id,
        )
    )
    blocked.sort(key=lambda item: item[0])
    return ProductTypeCopyEligibleReport(
        total_products=len(attached),
        eligible_count=len(eligible),
        blocked_count=len(blocked),
        eligible_by_product_type=_report_groups(eligible_counts),
        blocked_by_reason=dict(
            sorted(
                blocked_reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        missing_copy_strategy_groups=_report_groups(missing_counts),
        sample_eligible=eligible[:P4_REPORT_SAMPLE_LIMIT],
        sample_blocked=[
            item[1] for item in blocked[:P4_REPORT_SAMPLE_LIMIT]
        ],
    )
