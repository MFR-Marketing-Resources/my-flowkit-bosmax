from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.config import BASE_DIR


RULES_PATH = BASE_DIR / "data" / "products" / "product_mapping_rules.json"
FALLBACK_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "products" / "product_mapping_rules.json"
_SHORT_NAME_STOPWORDS = {
    "premium",
    "disposable",
    "ultra",
    "thin",
    "ultra-thin",
    "breathable",
    "microfiber",
    "quick",
    "dry",
    "all",
    "size",
    "sizes",
    "official",
    "store",
}
_REQUIRED_FIELDS = ["category", "subcategory", "type", "product_type", "silo", "trigger_id", "formula"]


def _keyword_matched(keyword: str, normalized_title: str, normalized_tokens: set[str]) -> bool:
    if not keyword:
        return False
    if " " in keyword:
        return f" {keyword} " in f" {normalized_title} "
    return keyword in normalized_tokens


def _matched_keywords(rule: dict[str, Any], normalized_title: str, normalized_tokens: set[str]) -> list[str]:
    matches: list[str] = []
    for item in rule.get("keywords", []):
        keyword = normalize_mapping_text(item)
        if _keyword_matched(keyword, normalized_title, normalized_tokens):
            matches.append(keyword)
    return matches


def _rule_specificity(matched_keywords: list[str]) -> tuple[int, int]:
    if not matched_keywords:
        return (0, 0)
    return max((len(keyword.split()), len(keyword)) for keyword in matched_keywords)


@lru_cache(maxsize=1)
def load_mapping_rules() -> dict[str, Any]:
    rules_path = RULES_PATH if RULES_PATH.exists() else FALLBACK_RULES_PATH
    return json.loads(rules_path.read_text(encoding="utf-8"))


def normalize_mapping_text(value: str | None) -> str:
    text = (value or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def derive_product_short_name(raw_title: str, existing_short_name: str | None = None) -> str:
    if existing_short_name and existing_short_name.strip():
        return existing_short_name.strip()

    cleaned = re.sub(r"\([^)]*\)", " ", raw_title)
    cleaned = re.sub(r"\b\d+\s*(pcs|pc|g|kg|ml|l|s|m|l|xl|xxl|xxxl)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(s/m/l/xl/xxl/xxxl|s-xl|0-6 months)\b", " ", cleaned, flags=re.IGNORECASE)
    tokens = [token for token in re.split(r"\s+", cleaned) if token]

    compact: list[str] = []
    for token in tokens:
        normalized = normalize_mapping_text(token)
        if not normalized or normalized in _SHORT_NAME_STOPWORDS:
            continue
        compact.append(token)
        if len(compact) >= 5:
            break

    return " ".join(compact) or " ".join(tokens[:4]).strip() or raw_title.strip()


def _resolve_source_label(
    product: dict[str, Any] | None,
    source_hint: str | None,
    matched: bool,
    *,
    has_explicit_override: bool = False,
) -> str:
    if has_explicit_override:
        return "explicit"
    source = (source_hint or (product.get("source") if product else "") or "").upper()
    if matched and source in {"MANUAL_PROJECT", "MANUAL"}:
        return "manual"
    if matched:
        return "rule"
    if product and any((product.get(field) or "").strip() for field in ("category", "subcategory", "type")):
        return "heuristic"
    if not source:
        return "manual"
    return "fallback"


def _match_keyword_rule(normalized_title: str) -> tuple[dict[str, Any] | None, list[str]]:
    normalized_tokens = set(normalized_title.split())
    matched_rules: list[tuple[dict[str, Any], list[str]]] = []
    for rule in load_mapping_rules().get("keyword_rules", []):
        matches = _matched_keywords(rule, normalized_title, normalized_tokens)
        if matches:
            matched_rules.append((rule, matches))
    
    if not matched_rules:
        return None, []
        
    by_id = {rule.get("id"): (rule, matches) for rule, matches in matched_rules}
    has_baby = "baby_diaper" in by_id
    has_baby_wipes = "baby_wipes" in by_id
    has_modestwear = "fashion_modestwear" in by_id
    has_fashion = any(rule.get("id") in {"fashion_bottoms", "fashion_sportswear"} for rule, _ in matched_rules)

    if has_baby_wipes and "beauty_fragrance" in by_id:
        baby_wipes_rule = by_id["baby_wipes"][0]
        return baby_wipes_rule, ["Conflict resolved: baby_wipes outranked beauty_fragrance due wipes/tisu basah keywords."]

    if has_baby_wipes and has_baby:
        baby_wipes_rule = by_id["baby_wipes"][0]
        return baby_wipes_rule, ["Conflict resolved: baby_wipes outranked baby_diaper due explicit wipes keywords."]
    
    if has_baby and has_fashion:
        baby_rule = by_id["baby_diaper"][0]
        return baby_rule, ["Conflict resolved: baby_diaper outranked fashion_bottoms due lampin/diaper keywords"]

    if has_modestwear and "fashion_sportswear" in by_id:
        modestwear_rule = by_id["fashion_modestwear"][0]
        return modestwear_rule, ["Conflict resolved: fashion_modestwear outranked fashion_sportswear due sarung/syria keywords."]

    home_carpet = by_id.get("home_carpet")
    fashion_bottoms = by_id.get("fashion_bottoms")
    if home_carpet and fashion_bottoms:
        _, carpet_matches = home_carpet
        if any(keyword in {"carpet", "karpet", "rug"} for keyword in carpet_matches):
            return home_carpet[0], ["Conflict resolved: explicit carpet keywords outranked fashion_bottoms."]
        return fashion_bottoms[0], ["Conflict resolved: fashion_bottoms outranked home_carpet because only soft mat keywords matched."]

    best_rule, _ = max(matched_rules, key=lambda item: _rule_specificity(item[1]))
    return best_rule, []


def _match_taxonomy_alias(category: str, subcategory: str, product_type: str) -> dict[str, Any] | None:
    current = {
        "category": normalize_mapping_text(category),
        "subcategory": normalize_mapping_text(subcategory),
        "type": normalize_mapping_text(product_type),
    }
    for alias in load_mapping_rules().get("taxonomy_aliases", []):
        match = alias.get("match", {})
        if all(
            not match.get(field)
            or current[field] in {normalize_mapping_text(value) for value in match.get(field, [])}
            for field in ("category", "subcategory", "type")
        ):
            return alias
    return None


def _match_profile(category: str, subcategory: str, product_type: str) -> dict[str, Any] | None:
    norm_category = normalize_mapping_text(category)
    norm_subcategory = normalize_mapping_text(subcategory)
    norm_type = normalize_mapping_text(product_type)
    candidates: list[dict[str, Any]] = []
    for profile in load_mapping_rules().get("profile_rules", []):
        match = profile.get("match", {})
        if match.get("category") and normalize_mapping_text(match["category"]) != norm_category:
            continue
        if match.get("subcategory") and normalize_mapping_text(match["subcategory"]) != norm_subcategory:
            continue
        if match.get("type") and normalize_mapping_text(match["type"]) != norm_type:
            continue
        candidates.append(profile)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda profile: sum(1 for field in ("category", "subcategory", "type") if profile.get("match", {}).get(field)),
    )


def _missing_fields(payload: dict[str, Any]) -> list[str]:
    missing = []
    for field in _REQUIRED_FIELDS:
        value = payload.get(field)
        if isinstance(value, list):
            if not value:
                missing.append(field)
            continue
        if not str(value or "").strip():
            missing.append(field)
    return missing


def resolve_product_mapping(
    *,
    product: dict[str, Any] | None = None,
    product_name: str | None = None,
    source_hint: str | None = None,
    overrides: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    overrides = overrides or {}
    raw_title = (
        product_name
        or (product or {}).get("raw_product_title")
        or (product or {}).get("product_display_name")
        or (product or {}).get("product_short_name")
        or ""
    ).strip()
    existing_short_name = (product or {}).get("product_short_name")
    normalized_title = normalize_mapping_text(raw_title)

    base = {
        "product_id": (product or {}).get("id") or (product or {}).get("product_id") or "",
        "raw_product_title": raw_title,
        "product_short_name": derive_product_short_name(raw_title, existing_short_name),
        "category": "",
        "subcategory": "",
        "type": "",
        "product_type": "",
        "silo": "",
        "trigger_id": "",
        "formula": "",
        "mode_recommendations": [],
        "copywriting_angle": "",
        "claim_risk_level": "",
        "mapping_source": "FALLBACK",
        "mapping_confidence": "NEEDS_REVIEW",
        "missing_fields": [],
        "notes": [],
    }

    override_category = (overrides.get("category") or "").strip()
    override_subcategory = (overrides.get("subcategory") or "").strip()
    override_type = (overrides.get("type") or "").strip()
    has_explicit_override = bool(override_category or override_subcategory or override_type)

    matched = False
    profile: dict[str, Any] | None = None

    if has_explicit_override:
        base["category"] = override_category or (product or {}).get("category") or ""
        base["subcategory"] = override_subcategory or (product or {}).get("subcategory") or ""
        base["type"] = override_type or (product or {}).get("type") or ""
        profile = _match_profile(base["category"], base["subcategory"], base["type"])
        matched = bool(base["category"] or base["subcategory"] or base["type"])
        base["mapping_confidence"] = "HIGH" if all([override_category, override_subcategory, override_type]) else "MEDIUM"
        base["notes"].append("Applied advanced override for category taxonomy.")

    if not matched:
        keyword_rule, conflict_notes = _match_keyword_rule(normalized_title)
        if keyword_rule:
            base["category"] = keyword_rule["category"]
            base["subcategory"] = keyword_rule["subcategory"]
            base["type"] = keyword_rule["type"]
            base["copywriting_angle"] = keyword_rule.get("copywriting_angle", "")
            base["claim_risk_level"] = keyword_rule.get("claim_risk_level", "")
            profile = _match_profile(base["category"], base["subcategory"], base["type"])
            matched = True
            base["mapping_confidence"] = "HIGH"
            base["notes"].append(f"Matched keyword rule: {keyword_rule['id']}")
            if conflict_notes:
                base["notes"].extend(conflict_notes)

    if not matched:
        alias = _match_taxonomy_alias(
            (product or {}).get("category") or "",
            (product or {}).get("subcategory") or "",
            (product or {}).get("type") or "",
        )
        if alias:
            base["category"] = alias["category"]
            base["subcategory"] = alias["subcategory"]
            base["type"] = alias["type"]
            profile = _match_profile(base["category"], base["subcategory"], base["type"])
            matched = True
            base["mapping_confidence"] = "MEDIUM"
            base["notes"].append("Canonicalized taxonomy from existing catalog fields.")

    if not matched and product:
        base["category"] = (product.get("category") or "").strip()
        base["subcategory"] = (product.get("subcategory") or "").strip()
        base["type"] = (product.get("type") or "").strip()
        profile = _match_profile(base["category"], base["subcategory"], base["type"])
        matched = any([base["category"], base["subcategory"], base["type"]])
        base["mapping_confidence"] = "MEDIUM" if matched else "NEEDS_REVIEW"
        if matched:
            base["notes"].append("Used existing stored product taxonomy.")

    if profile:
        base["product_type"] = profile.get("product_type", "")
        base["silo"] = profile.get("silo", "")
        base["trigger_id"] = profile.get("trigger_id", "")
        base["formula"] = profile.get("formula", "")
        base["mode_recommendations"] = list(profile.get("mode_recommendations", []))
        if not base["copywriting_angle"]:
            base["copywriting_angle"] = profile.get("copywriting_angle", "")
        if not base["claim_risk_level"]:
            base["claim_risk_level"] = profile.get("claim_risk_level", "")

    base["mapping_source"] = _resolve_source_label(
        product,
        source_hint,
        matched,
        has_explicit_override=has_explicit_override,
    )
    base["missing_fields"] = _missing_fields(base)
    if base["missing_fields"]:
        if matched:
            base["mapping_confidence"] = "LOW"
        else:
            base["mapping_confidence"] = "NEEDS_REVIEW"

    if not matched:
        base["notes"].append("No keyword or taxonomy rule matched. Manual override is recommended.")

    return base