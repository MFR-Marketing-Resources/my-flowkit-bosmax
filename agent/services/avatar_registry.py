"""Avatar registry — deterministic presenter resolution layer (ADR-008).

Consumes the retained avatar pool (agent/authority/AVATAR_POOL_NORMALIZED.csv —
the repo seed of the live Notion avatar registry; the pool GROWS over time) and
resolves ONE normalized, concrete, product-safe presenter profile for the
canonical prompt compiler.

Law (retained pack): registry fields are UPSTREAM authoring inputs. The final
prompt renderer receives a resolved profile and renders real descriptive prose —
never "one visible creator on screen", never avatar-pool references, never
selection instructions.
"""
from __future__ import annotations

import csv
import hashlib
from functools import lru_cache
from pathlib import Path

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"
_POOL_FILE = _AUTHORITY_DIR / "AVATAR_POOL_NORMALIZED.csv"
# Normalized bridge target (ADR-008 avatar law): the LIVE Notion registry is not
# safe as a runtime dependency (auth/latency/availability), so growth arrives as
# an explicit, validated CSV sync into this file. When present it OVERRIDES the
# repo seed; when absent the vendored retained pool is authoritative.
_BRIDGE_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "avatar_registry" / "AVATAR_POOL_NORMALIZED.csv"
)

REQUIRED_COLUMNS = {"CharacterName", "AvatarCode", "SkinTone", "HairStyle",
                    "Wardrobe", "Expression"}


def _active_pool_file() -> Path:
    return _BRIDGE_FILE if _BRIDGE_FILE.exists() else _POOL_FILE


def sync_pool_csv(csv_bytes: bytes) -> dict:
    """Fail-closed registry sync: validate the uploaded normalized CSV, then
    install it as the runtime bridge override and reload the cache."""
    import io
    text = csv_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("AVATAR_REGISTRY_EMPTY")
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(f"AVATAR_REGISTRY_COLUMNS_MISSING:{sorted(missing)}")
    codes = [str(r.get("AvatarCode") or "").strip() for r in rows]
    if not all(codes):
        raise ValueError("AVATAR_REGISTRY_BLANK_AVATAR_CODE")
    if len(set(codes)) != len(codes):
        raise ValueError("AVATAR_REGISTRY_DUPLICATE_AVATAR_CODE")
    _BRIDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BRIDGE_FILE.write_text(text, encoding="utf-8")
    count = reload_pool()
    return {"rows": len(rows), "approved_loaded": count, "bridge_path": str(_BRIDGE_FILE)}


@lru_cache(maxsize=1)
def _load_pool() -> tuple[dict, ...]:
    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        rows = tuple(
            row for row in csv.DictReader(f)
            if str(row.get("approved_flag", "")).strip().lower() in ("true", "1", "yes", "approved", "")
        )
    if not rows:
        raise RuntimeError("AVATAR_POOL_EMPTY: no approved avatars in registry")
    return rows


def reload_pool() -> int:
    """Clear the cache after the registry file is updated (pool grows over time)."""
    _load_pool.cache_clear()
    return len(_load_pool())


def _normalize_profile(row: dict) -> dict:
    return {
        "avatar_code": str(row.get("AvatarCode") or "").strip(),
        "character_name": str(row.get("CharacterName") or "").strip(),
        "variant": str(row.get("Variant") or "").strip(),
        "skin_tone": str(row.get("SkinTone") or "").strip(),
        "hair_style": str(row.get("HairStyle") or "").strip(),
        "wardrobe": str(row.get("Wardrobe") or "").strip(),
        "environment": str(row.get("Environment") or "").strip(),
        "lighting": str(row.get("Lighting") or "").strip(),
        "camera": str(row.get("Camera") or "").strip(),
        "expression": str(row.get("Expression") or "").strip(),
        "usage_tags": [t.strip() for t in str(row.get("usage_tags") or "").split(",") if t.strip()],
    }


def _gender_word(avatar_code: str) -> str:
    code = avatar_code.upper()
    if "_F_" in code or code.startswith("BOS_F"):
        return "woman"
    if "_M_" in code or code.startswith("BOS_M"):
        return "man"
    return "adult"


def presenter_prose(profile: dict) -> str:
    """Render the resolved profile as concrete engine-facing descriptive prose.

    This is the ONLY sanctioned way avatar identity enters a final prompt: real
    description, reusable across blocks, no pool metadata, no placeholders.
    """
    gender = _gender_word(profile.get("avatar_code", ""))
    bits = []
    skin = profile.get("skin_tone")
    hair = profile.get("hair_style")
    wardrobe = profile.get("wardrobe")
    expression = profile.get("expression")
    lead = f"a Malaysian adult {gender}"
    if skin:
        lead += f" with {skin.lower()} skin"
    if hair:
        lead += f" and {hair.lower()} hair"
    bits.append(lead)
    if wardrobe:
        bits.append(f"wearing {wardrobe.lower()}")
    if expression:
        bits.append(f"with a {expression.lower()} expression")
    prose = ", ".join(bits)
    return (
        f"The presenter is {prose}. Keep this exact presenter identity — face, "
        f"hair, wardrobe, and body language — consistent in every shot."
    )


def list_pool() -> list[dict]:
    """Read-only view of every approved avatar profile (dashboard registry tab).

    Returns normalized profiles only — the raw pool rows (PromptV1 etc.) stay
    internal; identity enters prompts solely via presenter_prose().
    """
    return [_normalize_profile(row) for row in _load_pool()]


def resolve_presenter(
    avatar_id: str | None = None,
    *,
    usage_context: str | None = None,
    seed: str | None = None,
) -> dict:
    """Resolve exactly ONE presenter profile, deterministically.

    Priority: explicit avatar_id (AvatarCode) → usage-tag/context match →
    deterministic seed pick (same seed always yields the same presenter, so a
    product keeps one face across regenerations). Never random.
    """
    pool = _load_pool()
    if avatar_id:
        wanted = str(avatar_id).strip().upper()
        for row in pool:
            if str(row.get("AvatarCode", "")).strip().upper() == wanted:
                return _normalize_profile(row)
        raise ValueError(f"AVATAR_NOT_FOUND:{avatar_id}")
    candidates = pool
    if usage_context:
        ctx = usage_context.strip().lower()
        tagged = [
            row for row in pool
            if ctx in str(row.get("usage_tags", "")).lower()
            or ctx in str(row.get("Variant", "")).lower()
            or ctx in str(row.get("Environment", "")).lower()
        ]
        if tagged:
            candidates = tuple(tagged)
    digest = hashlib.sha256(str(seed or "bosmax-default").encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(candidates)
    return _normalize_profile(candidates[index])
