"""Canonical product-identity authority for Copy Register V2 authoring.

The product row is the identity authority for copy authoring. Product Truth
facts are evidence, not permission to invent or repeat an alternate product
name. This module is deliberately read-only: it resolves the current name
and detects identity-shaped variants without normalising or mutating data.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


PRODUCT_IDENTITY_STALE = "COPY_V2_PRODUCT_IDENTITY_STALE"
PRODUCT_IDENTITY_UNRESOLVED = "COPY_V2_PRODUCT_IDENTITY_UNRESOLVED"

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", re.UNICODE)
_SNAPSHOT_IDENTITY_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "hook_angles_json",
    "cta_angles_json",
    "pain_points_json",
    "subhook_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "source_urls_json",
    "package_notes",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "claim_tokens_json",
    "allowed_claims_json",
    "blocked_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _tokens(value: Any) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_RE.findall(_clean(value)))


def _parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _walk_strings(value: Any, path: str) -> list[tuple[str, str]]:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        output: list[tuple[str, str]] = []
        for key, child in parsed.items():
            child_path = f"{path}.{key}" if path else str(key)
            output.extend(_walk_strings(child, child_path))
        return output
    if isinstance(parsed, list):
        output = []
        for index, child in enumerate(parsed):
            output.extend(_walk_strings(child, f"{path}[{index}]"))
        return output
    text = _clean(parsed)
    return [(path, text)] if text else []


def build_product_identity_authority(product: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the current product identity without writing or enriching it."""

    display_name = _clean(product.get("product_display_name"))
    raw_title = _clean(product.get("raw_product_title"))
    canonical_name = display_name or raw_title
    if not canonical_name:
        raise ValueError(PRODUCT_IDENTITY_UNRESOLVED)
    canonical_tokens = _tokens(canonical_name)
    if not canonical_tokens:
        raise ValueError(PRODUCT_IDENTITY_UNRESOLVED)

    short_name = _clean(product.get("product_short_name"))
    brand = _clean(product.get("brand"))
    brand_tokens = _tokens(brand)
    brand_start = -1
    if brand_tokens:
        brand_start = next(
            (
                index
                for index in range(len(canonical_tokens) - len(brand_tokens) + 1)
                if canonical_tokens[index : index + len(brand_tokens)] == brand_tokens
            ),
            -1,
        )
    if brand_start < 0:
        brand_tokens = ()

    forbidden_aliases = []
    if raw_title and _tokens(raw_title) != canonical_tokens:
        forbidden_aliases.append(raw_title)

    return {
        "canonical_name": canonical_name,
        "canonical_tokens": canonical_tokens,
        "canonical_short_name": short_name,
        "brand": brand,
        "brand_tokens": brand_tokens,
        "brand_start": brand_start,
        "allowed_exact_names": tuple(
            dict.fromkeys(name for name in (canonical_name, short_name, brand) if name)
        ),
        "forbidden_aliases": tuple(forbidden_aliases),
    }


def _contains_sequence(tokens: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    if not sequence or len(sequence) > len(tokens):
        return False
    width = len(sequence)
    return any(
        tokens[index : index + width] == sequence
        for index in range(len(tokens) - width + 1)
    )


def _find_inserted_variant(
    tokens: tuple[str, ...],
    canonical_tokens: tuple[str, ...],
    *,
    max_inserted_tokens: int = 4,
) -> tuple[str, ...] | None:
    """Find the canonical name with one or more inserted identity tokens."""

    if len(canonical_tokens) < 2:
        return None
    for split in range(1, len(canonical_tokens)):
        prefix = canonical_tokens[:split]
        suffix = canonical_tokens[split:]
        for start in range(max(0, len(tokens) - len(prefix) - len(suffix))):
            if tokens[start : start + len(prefix)] != prefix:
                continue
            gap_start = start + len(prefix)
            for gap_length in range(1, max_inserted_tokens + 1):
                suffix_start = gap_start + gap_length
                observed_end = suffix_start + len(suffix)
                if observed_end > len(tokens):
                    break
                if tokens[suffix_start:observed_end] == suffix:
                    return tokens[start:observed_end]
    return None


def find_product_identity_violation(
    text: Any,
    product: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a deterministic identity violation, or ``None`` for safe text."""

    normalized = _clean(text)
    if not normalized:
        return None
    authority = build_product_identity_authority(product)
    tokens = _tokens(normalized)

    for alias in authority["forbidden_aliases"]:
        alias_tokens = _tokens(alias)
        if _contains_sequence(tokens, alias_tokens):
            return {
                "code": PRODUCT_IDENTITY_STALE,
                "reason": "A non-canonical product-row title was repeated in generated text.",
                "canonical_name": authority["canonical_name"],
                "observed_alias": alias,
            }

    inserted = _find_inserted_variant(tokens, authority["canonical_tokens"])
    if inserted is not None:
        return {
            "code": PRODUCT_IDENTITY_STALE,
            "reason": "Generated text contains the canonical product name with inserted identity tokens.",
            "canonical_name": authority["canonical_name"],
            "observed_tokens": list(inserted),
        }

    # A shortened stale reference can retain the canonical brand while adding
    # an identity token immediately before it (for example, "Tok Cap Burung").
    # Use a canonical-name suffix as the anchor so ordinary mentions of the
    # brand remain valid when they are not identity-shaped.
    brand_tokens = authority["brand_tokens"]
    prefix_tokens = (
        authority["canonical_tokens"][: authority["brand_start"]]
        if brand_tokens
        else ()
    )
    for anchor_length in range(1, min(2, len(prefix_tokens)) + 1):
        left = prefix_tokens[-anchor_length:]
        for start in range(max(0, len(tokens) - len(left) - len(brand_tokens))):
            if tokens[start : start + len(left)] != left:
                continue
            gap_start = start + len(left)
            for gap_length in range(1, 4):
                brand_start = gap_start + gap_length
                brand_end = brand_start + len(brand_tokens)
                if brand_end > len(tokens):
                    break
                if tokens[brand_start:brand_end] == brand_tokens:
                    return {
                        "code": PRODUCT_IDENTITY_STALE,
                        "reason": "Generated text contains a non-canonical token inside the product-brand reference.",
                        "canonical_name": authority["canonical_name"],
                        "observed_tokens": list(tokens[start:brand_end]),
                    }
    return None


def validate_product_identity_text(text: Any, product: Mapping[str, Any]) -> str:
    """Validate one authored text value and return its normalized form."""

    normalized = _clean(text)
    violation = find_product_identity_violation(normalized, product)
    if violation:
        error = ValueError(violation["code"])
        error.details = violation  # type: ignore[attr-defined]
        raise error
    return normalized


def snapshot_product_identity_violations(
    product: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Inspect current Product Truth identity-bearing fields without mutation."""

    violations: list[dict[str, Any]] = []
    for field_name in _SNAPSHOT_IDENTITY_FIELDS:
        for path, text in _walk_strings(snapshot.get(field_name), field_name):
            violation = find_product_identity_violation(text, product)
            if violation:
                violations.append({"field": path, **violation})
    return violations


def product_identity_proof(product: Mapping[str, Any]) -> dict[str, Any]:
    authority = build_product_identity_authority(product)
    return {
        "canonical_name": authority["canonical_name"],
        "canonical_short_name": authority["canonical_short_name"] or None,
        "brand": authority["brand"] or None,
        "allowed_exact_names": list(authority["allowed_exact_names"]),
        "source": "product.product_display_name",
    }


__all__ = [
    "PRODUCT_IDENTITY_STALE",
    "PRODUCT_IDENTITY_UNRESOLVED",
    "build_product_identity_authority",
    "find_product_identity_violation",
    "product_identity_proof",
    "snapshot_product_identity_violations",
    "validate_product_identity_text",
]
