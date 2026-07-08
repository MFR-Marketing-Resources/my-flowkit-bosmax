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
    ("cure", re.compile(r"\bcure(?:d|s|ing)?\b", re.IGNORECASE)),
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


def evaluate_claim_safety(payload: Mapping[str, Any]) -> dict[str, Any]:
    blocked_tokens: list[str] = []
    review_tokens: list[str] = []
    for segment in _collect_segments(payload):
        blocked_tokens.extend(_matches_any(segment, BLOCKED_PATTERNS))
        review_tokens.extend(_matches_any(segment, REVIEW_PATTERNS))

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
