"""Strict V2 formula authority.

The legacy formula helpers intentionally retain their compatibility fallback
to HSO.  V2 cannot use that behavior: an absent or unknown formula is a hard
validation error.  This module is therefore a narrow, additive authority seam
over the existing checked-in registry.
"""
from __future__ import annotations

import json
from typing import Any

from agent.authority.copy_formula_registry import FORMULA_REGISTRY


FORMULA_AUTHORITY_VERSION = "copy-formula-registry-v1"


class UnknownV2Formula(ValueError):
    code = "COPY_V2_UNKNOWN_FORMULA"

    def __init__(self, formula_id: Any):
        self.formula_id = str(formula_id or "")
        super().__init__(f"unknown V2 formula: {self.formula_id or '<missing>'}")


class MissingV2Formula(ValueError):
    code = "COPY_V2_FORMULA_REQUIRED"

    def __init__(self):
        super().__init__("V2 requires an explicit formula")


_ALIASES = {
    "SAVAGE_PAS": "SavagePAS",
    "SAVAGEPAS": "SavagePAS",
    "SAVAGE_HPAS": "HPAS",
    "H_PAS": "HPAS",
    "HOOK_PAS": "HPAS",
}


def _canonical_formula_payload(formula: dict[str, Any]) -> dict[str, Any]:
    """Keep the formula version tied to authority semantics, not dict order."""

    return {
        "formula_id": formula["formula_id"],
        "compiler_family": formula["compiler_family"],
        "definition_status": formula["definition_status"],
        "slots": formula["slots"],
        "output_mapping": formula["output_mapping"],
    }


def strict_formula_id(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        raise MissingV2Formula()
    direct = next((fid for fid in FORMULA_REGISTRY if fid.casefold() == token.casefold()), None)
    if direct:
        return direct
    alias = _ALIASES.get(token.upper().replace(" ", "_"))
    if alias and alias in FORMULA_REGISTRY:
        return alias
    raise UnknownV2Formula(token)


def strict_formula_contract(formula_id: Any) -> dict[str, Any]:
    return FORMULA_REGISTRY[strict_formula_id(formula_id)]


def formula_version(formula_id: Any) -> str:
    formula = strict_formula_contract(formula_id)
    payload = json.dumps(
        _canonical_formula_payload(formula),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    import hashlib

    return f"{FORMULA_AUTHORITY_VERSION}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def required_formula_stage_keys(formula_id: Any) -> tuple[str, ...]:
    return tuple(
        slot["slot_id"]
        for slot in strict_formula_contract(formula_id)["slots"]
        if slot.get("required", True)
    )


def is_production_formula(formula_id: Any) -> bool:
    return strict_formula_contract(formula_id)["definition_status"] == "CANONICAL"
