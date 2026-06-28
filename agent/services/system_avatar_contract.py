"""System-avatar contract.

Operator mandate: everything that reaches Google Flow MUST come from the BOSMAX
system. A *visible human on screen* counts as "from outside" unless it is backed
by a system-provided avatar reference. Two enforcement points:

- (B) compile-time: for a package with NO system avatar, a visible-creator /
  AI-avatar presence is downgraded to FACELESS (product-only), so the engine
  never invents an uncontrolled person.
- (A) preflight: if a final prompt still demands a visible human and the package
  has no system avatar, BLOCK the run (fail closed) instead of letting Google
  Flow generate a random face.

Pure module (no I/O) so both call sites and tests can reuse it.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

ERR_CHARACTER_PROMPT_WITHOUT_SYSTEM_AVATAR = "ERR_CHARACTER_PROMPT_WITHOUT_SYSTEM_AVATAR"
WARN_CHARACTER_DOWNGRADED_NO_SYSTEM_AVATAR = "CHARACTER_DOWNGRADED_TO_FACELESS_NO_SYSTEM_AVATAR"

# Presence modes that put a visible human on screen → require a system avatar.
VISIBLE_HUMAN_PRESENCE = frozenset({"VISIBLE_CREATOR", "AVATAR_AI"})

# An asset is a system avatar reference when its slot/source/role names a person
# (never a product / scene / style asset).
_AVATAR_TOKEN_RE = re.compile(
    r"avatar|persona|character|creator|presenter|talent|spokesperson|model[_\s-]*face",
    re.I,
)

# A compiled prompt "demands a visible human" when it asserts a person on screen.
_VISIBLE_HUMAN_RE = re.compile(
    r"CHARACTER:\s*One visible creator"
    r"|CHARACTER\s*\(AI\s*AVATAR"
    r"|visible creator persona"
    r"|visible creator on screen"
    r"|on-screen AI avatar",
    re.I,
)


def _asset_strings(asset: Any) -> Iterable[str]:
    if not isinstance(asset, dict):
        return []
    out: list[str] = []
    for key in ("slot_key", "asset_source", "role", "asset_role", "label", "type"):
        value = asset.get(key)
        if value:
            out.append(str(value))
    nested = asset.get("resolved_asset")
    if isinstance(nested, dict):
        for key in ("slot_key", "asset_source", "role", "label"):
            value = nested.get(key)
            if value:
                out.append(str(value))
    return out


def package_has_system_avatar(resolved_assets: Any, *, avatar_id: Optional[str] = None) -> bool:
    """True when the package carries a system avatar/character reference (or an
    explicit avatar_id). Product / scene / style assets do NOT count."""
    if avatar_id and str(avatar_id).strip():
        return True
    if not isinstance(resolved_assets, (list, tuple)):
        return False
    for asset in resolved_assets:
        for text in _asset_strings(asset):
            if _AVATAR_TOKEN_RE.search(text):
                return True
    return False


def prompt_demands_visible_human(prompt_text: Optional[str]) -> bool:
    if not prompt_text:
        return False
    return bool(_VISIBLE_HUMAN_RE.search(str(prompt_text)))


def resolve_presence_for_avatar(
    requested_presence: Optional[str], has_system_avatar: bool
) -> tuple[str, bool]:
    """Return (effective_presence, downgraded). With no system avatar, a
    visible-human presence becomes FACELESS (product-only)."""
    presence = (requested_presence or "VISIBLE_CREATOR").strip().upper()
    if presence in VISIBLE_HUMAN_PRESENCE and not has_system_avatar:
        return "FACELESS", True
    return presence, False


def assert_system_avatar_contract(
    prompt_text: Optional[str], has_system_avatar: bool
) -> Optional[str]:
    """Preflight guard. Returns an error code if a visible human is demanded with
    no system avatar; otherwise None."""
    if has_system_avatar:
        return None
    if prompt_demands_visible_human(prompt_text):
        return ERR_CHARACTER_PROMPT_WITHOUT_SYSTEM_AVATAR
    return None
