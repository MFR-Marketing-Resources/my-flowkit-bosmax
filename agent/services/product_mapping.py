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


def _resolve_source_label(product: dict[str, Any] | None, source_hint: str | None, matched: bool) -> str:
    source = (source_hint or product.get("source") if product else source_hint or "").upper()
    if matched and source in {"FASTMOSS", "MANUAL_PROJECT", "MANUAL"}:
        return "FASTMOSS" if source == "FASTMOSS" else "MANUAL"
    if matched and not source:
        return "MANUAL"
    return "FALLBACK"


def _match_keyword_rule(normalized_title: str) -> tuple[dict[str, Any] | None, list[str]]:
    matched_rules = []
    for rule in load_mapping_rules().get("keyword_rules", []):
        keywords = [normalize_mapping_text(item) for item in rule.get("keywords", [])]
        if any(keyword and keyword in normalized_title for keyword in keywords):
            matched_rules.append(rule)
    
    if not matched_rules:
        return None, []
        
    has_baby = any(r.get("id") == "baby_diaper" for r in matched_rules)
    has_seluar = any("fashion" in r.get("id", "") for r in matched_rules)
    
    if has_baby and has_seluar:
        baby_rule = next(r for r in matched_rules if r.get("id") == "baby_diaper")
        return baby_rule, ["Conflict resolved: baby_diaper outranked fashion_bottoms due lampin/diaper keywords"]

    return matched_rules[0], []


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
    for profile in load_mapping_rules().get("profile_rules", []):
        match = profile.get("match", {})
        if match.get("category") and normalize_mapping_text(match["category"]) != norm_category:
            continue
        if match.get("subcategory") and normalize_mapping_text(match["subcategory"]) != norm_subcategory:
            continue
        if match.get("type") and normalize_mapping_text(match["type"]) != norm_type:
            continue
        return profile
    return None


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

    matched = False
    profile: dict[str, Any] | None = None

    if override_category or override_subcategory or override_type:
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

    base["mapping_source"] = _resolve_source_label(product, source_hint, matched)
    base["missing_fields"] = _missing_fields(base)
    if base["missing_fields"]:
        if matched:
            base["mapping_confidence"] = "LOW"
        else:
            base["mapping_confidence"] = "NEEDS_REVIEW"

    if not matched:
        base["notes"].append("No keyword or taxonomy rule matched. Manual override is recommended.")

    return base