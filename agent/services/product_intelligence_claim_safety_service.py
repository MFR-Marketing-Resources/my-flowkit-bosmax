from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping

from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceClaimGate,
    ProductIntelligenceClaimRiskLevel,
)


# The gate scans the PRODUCT'S published claims — the copy a customer reads + the
# claims the product is allowed to make. It deliberately EXCLUDES internal, non-published
# fields that legitimately contain medical words and would otherwise permanently block a
# correct draft:
#   - blocked_claims_json     : the "do NOT say" quarantine / guardrail list (e.g.
#                               "Jangan guna 'merawat' penyakit") — scanning it re-trips
#                               the gate on the very words it forbids.
#   - buyer_persona_snapshot_json / copy_strategy_summary_json : the customer AVATAR +
#                               internal strategy. A health-product avatar naturally
#                               describes the customer's world (pains like "penyakit",
#                               desires like "kelegaan tanpa ambil ubat") — that is not a
#                               product claim, and scanning it blocks the whole health
#                               category. The copy the engine writes from it IS scanned.
#   - reviewer_note           : the operator's internal note, not published copy.
CLAIM_TEXT_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "allowed_claims_json",
)

BLOCKED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cure", re.compile(r"\bcur(?:e|ed|es|ing)\b", re.IGNORECASE)),
    ("treat", re.compile(r"\btreat(?:ed|s|ing|ment)?\b", re.IGNORECASE)),
    ("heal", re.compile(r"\bheal(?:ed|s|ing)?\b", re.IGNORECASE)),
    (
        "guaranteed result",
        re.compile(r"\bguaranteed?\s+(?:result|results)\b", re.IGNORECASE),
    ),
    (
        "guaranteed relief",
        re.compile(r"\bguaranteed?\s+relief\b", re.IGNORECASE),
    ),
    ("diagnosis", re.compile(r"\bdiagnos(?:e|ed|is|ing)\b", re.IGNORECASE)),
    ("disease", re.compile(r"\bdisease(?:s)?\b", re.IGNORECASE)),
    (
        "pain cure",
        re.compile(r"\bpain\s+cure\b|\bcures?\s+pain\b", re.IGNORECASE),
    ),
    (
        "permanent result",
        re.compile(r"\bpermanent(?:ly)?\s+(?:result|results|relief)\b", re.IGNORECASE),
    ),
    ("miracle result", re.compile(r"\bmiracle\s+(?:result|results)\b", re.IGNORECASE)),
    ("sembuh", re.compile(r"\bmeny?sembuh\w*\b|\bsembuh\w*\b", re.IGNORECASE)),
    ("rawat", re.compile(r"\bmerawat\b|\brawat\b", re.IGNORECASE)),
    ("ubat", re.compile(r"\bubat\b", re.IGNORECASE)),
    ("penyakit", re.compile(r"\bpenyakit\b", re.IGNORECASE)),
    (
        "hilang sakit dijamin",
        re.compile(r"\bhilang\s+sakit\s+dijamin\b", re.IGNORECASE),
    ),
    (
        "dijamin berkesan",
        re.compile(r"\bdijamin\s+berkesan\b", re.IGNORECASE),
    ),
    (
        "testimoni penyakit",
        re.compile(r"\btestimoni\s+penyakit\b", re.IGNORECASE),
    ),
    (
        "sebelum selepas penyakit",
        re.compile(r"\bsebelum\s+selepas\s+penyakit\b", re.IGNORECASE),
    ),
)

REVIEW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "anti-inflammatory",
        re.compile(r"\banti[\s-]?inflammatory\b", re.IGNORECASE),
    ),
    (
        "doctor certified",
        re.compile(r"\bdoctor\s+certified\b|\bdoktor\s+(?:sahkan|disahkan)\b", re.IGNORECASE),
    ),
    (
        "kkm mohm claim",
        re.compile(r"\b(?:kkm|moh)\b", re.IGNORECASE),
    ),
    (
        "before after disease result",
        re.compile(r"\bbefore\s+after\b|\bsebelum\s+selepas\b", re.IGNORECASE),
    ),
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True)
    except TypeError:
        return str(value)


def _collect_segments(payload: Mapping[str, Any]) -> list[str]:
    segments: list[str] = []
    for field_name in CLAIM_TEXT_FIELDS:
        value = payload.get(field_name)
        if value is None:
            continue
        if isinstance(value, list):
            segments.extend(_stringify(item) for item in value if _stringify(item).strip())
            continue
        text = _stringify(value).strip()
        if text:
            segments.append(text)
    return segments


def _dedupe_preserve(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _matches_any(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[str]:
    tokens: list[str] = []
    for label, pattern in patterns:
        if pattern.search(text):
            tokens.append(label)
    return tokens


# ── Mission-08D: contextual non-medical downgrade for `treat` / `cure` ───────
# The blocked lexicon is intentionally blunt — but "Windshield Treatment" is a product
# NAME and "allow to cure for 10 minutes" is a coating process, not a health claim, and
# both permanently blocked real automotive products on the live pilot. The downgrade
# below is the SMALLEST contextual rule that fixes those without touching medical
# strictness:
#   * only the two tokens `treat` and `cure` are ever considered;
#   * the product's category must be known and must NOT touch health, wellness,
#     ingestion, body-contact, baby/children or medical territory (unknown/empty
#     category = NO downgrade — fail closed);
#   * EVERY occurrence of the token across EVERY scanned segment must sit inside one of
#     the enumerated non-medical phrases; one bare "treats pain" anywhere and the token
#     stays fully blocked;
#   * the result is CLAIM_REVIEW_REQUIRED, never CLAIM_SAFE — a human still has to
#     read it and record an acknowledgement before approval.
_HEALTH_CONTEXT_CATEGORY_RE = re.compile(
    r"(?i)\b(?:health|wellness|herbals?|supplements?|vitamins?|food|beverages?|snacks?|"
    r"ingest\w*|edibles?|beauty|skincare|cosmetics?|personal\s*care|body|baby|infants?|"
    r"kids?|child(?:ren)?|toys?|medic(?:al|ine)?|pharma|clinics?)\b")
_NON_MEDICAL_CONTEXT_RES: dict[str, tuple[re.Pattern[str], ...]] = {
    "treat": (
        re.compile(r"(?i)\b(?:windshield|windscreen|surface|coating|glass|paint)\s+"
                   r"treat(?:ment)?s?\b"),
    ),
    "cure": (
        re.compile(r"(?i)\ballow(?:ing)?(?:\s+\w+){0,3}?\s+to\s+cure\b"),
        re.compile(r"(?i)\bcuring\s+time\b"),
        re.compile(r"(?i)\bcure\s+time\b"),
    ),
}
_TOKEN_OCCURRENCE_RES: dict[str, re.Pattern[str]] = {
    "treat": re.compile(r"(?i)\btreat(?:ed|s|ing|ment)?\b"),
    "cure": re.compile(r"(?i)\bcur(?:e|ed|es|ing)\b"),
}


def _category_permits_downgrade(product: Mapping[str, Any] | None) -> bool:
    category = str((product or {}).get("category") or "").strip()
    if not category:
        return False  # unknown category -> keep the full block
    return not _HEALTH_CONTEXT_CATEGORY_RE.search(category)


def _every_occurrence_is_non_medical(token: str, segments: list[str]) -> bool:
    occurrence_re = _TOKEN_OCCURRENCE_RES.get(token)
    context_res = _NON_MEDICAL_CONTEXT_RES.get(token)
    if occurrence_re is None or context_res is None:
        return False
    saw_any = False
    for segment in segments:
        spans = [m.span() for ctx in context_res for m in ctx.finditer(segment)]
        for match in occurrence_re.finditer(segment):
            saw_any = True
            start, end = match.span()
            if not any(s <= start and end <= e for s, e in spans):
                return False  # one bare occurrence -> token stays blocked
    return saw_any


def evaluate_claim_safety(
    payload: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blocked_tokens: list[str] = []
    review_tokens: list[str] = []
    segments = _collect_segments(payload)
    for segment in segments:
        blocked_tokens.extend(_matches_any(segment, BLOCKED_PATTERNS))
        review_tokens.extend(_matches_any(segment, REVIEW_PATTERNS))

    # Contextual downgrade (08D): `treat`/`cure` drop from BLOCKED to REVIEW_REQUIRED
    # only when the category is provably non-health AND every single occurrence sits
    # inside an enumerated non-medical phrase. Callers that cannot supply the product
    # (product=None) get the unchanged full block.
    existing_allowed = [
        str(item).strip()
        for item in (payload.get("allowed_claims_json") or [])
        if str(item).strip()
    ]
    existing_blocked = [
        str(item).strip()
        for item in (payload.get("blocked_claims_json") or [])
        if str(item).strip()
    ]

    normalized_allowed: list[str] = []
    derived_blocked_claims: list[str] = []
    for claim in existing_allowed:
        claim_blocked = _matches_any(claim, BLOCKED_PATTERNS)
        claim_review = _matches_any(claim, REVIEW_PATTERNS)
        if claim_blocked or claim_review:
            derived_blocked_claims.append(claim)
            blocked_tokens.extend(claim_blocked)
            review_tokens.extend(claim_review)
        else:
            normalized_allowed.append(claim)

    # Apply the contextual downgrade only after allowed_claims_json has contributed
    # its tokens too; otherwise an exact non-medical phrase there re-adds a full block.
    if blocked_tokens and _category_permits_downgrade(product):
        downgraded: list[str] = []
        for token in ("treat", "cure"):
            if token in blocked_tokens and _every_occurrence_is_non_medical(token, segments):
                downgraded.append(token)
        if downgraded:
            blocked_tokens = [t for t in blocked_tokens if t not in downgraded]
            review_tokens.extend(downgraded)

    blocked_tokens = _dedupe_preserve(blocked_tokens)
    review_tokens = _dedupe_preserve(review_tokens)
    claim_tokens = _dedupe_preserve([*blocked_tokens, *review_tokens])

    claim_gate: ProductIntelligenceClaimGate
    claim_risk_level: ProductIntelligenceClaimRiskLevel
    if blocked_tokens:
        claim_gate = "CLAIM_BLOCKED"
        claim_risk_level = "HIGH"
    elif review_tokens:
        claim_gate = "CLAIM_REVIEW_REQUIRED"
        claim_risk_level = "MEDIUM"
    else:
        claim_gate = "CLAIM_SAFE"
        claim_risk_level = "LOW"

    return {
        "claim_gate": claim_gate,
        "claim_risk_level": claim_risk_level,
        "claim_tokens_json": claim_tokens,
        "allowed_claims_json": _dedupe_preserve(normalized_allowed),
        "blocked_claims_json": _dedupe_preserve(
            [*existing_blocked, *derived_blocked_claims],
        ),
    }
