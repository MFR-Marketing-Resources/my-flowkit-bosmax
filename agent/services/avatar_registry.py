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
import re
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


def _parse_usage_tags(raw: str) -> list[str]:
    """Parse a usage_tags cell into a clean tag list.

    Accepts BOTH the legacy comma-delimited form (`UGC, desk, office`) and the
    CSV-Factory pipe-delimited form (`UGC|desk|office`), plus any mix of the
    two. Tags are stripped and de-duplicated case-insensitively while the
    first-seen readable text is preserved.
    """
    seen: set[str] = set()
    tags: list[str] = []
    for part in re.split(r"[|,]", str(raw or "")):
        tag = part.strip()
        if not tag:
            continue
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


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
        "usage_tags": _parse_usage_tags(row.get("usage_tags")),
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


def get_generation_prompt(avatar_code: str) -> dict:
    """Server-side only: the avatar's PromptV1 (full image-generation prompt)
    plus identity fields, for the IMG-lane avatar image factory. Raw prompt
    text never reaches the dashboard — only the job it feeds."""
    wanted = str(avatar_code or "").strip().upper()
    for row in _load_pool():
        if str(row.get("AvatarCode", "")).strip().upper() == wanted:
            prompt = str(row.get("PromptV1") or "").strip()
            if not prompt:
                raise ValueError(f"AVATAR_PROMPT_EMPTY:{avatar_code}")
            return {
                "avatar_code": str(row.get("AvatarCode")).strip(),
                "character_name": str(row.get("CharacterName") or "").strip(),
                "prompt": prompt,
            }
    raise ValueError(f"AVATAR_NOT_FOUND:{avatar_code}")


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


# ── Manual single-row add + AI auto-generate support (additive). Both paths write
# through the EXISTING fail-closed sync_pool_csv() door so REQUIRED_COLUMNS +
# uniqueness validation and the runtime bridge/reload stay authoritative.

_CODE_RE = re.compile(r"^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$")


def add_avatar(row: dict) -> dict:
    """Single-row add WITHOUT a CSV upload.

    Reads the active pool, requires row['AvatarCode'] (case-insensitive uniqueness),
    builds a full row for EVERY header column, then writes the whole table back
    through the EXISTING fail-closed sync_pool_csv() door (which re-validates
    REQUIRED_COLUMNS + uniqueness, installs the bridge, and reloads the cache)."""
    import io

    new_code = str(row.get("AvatarCode") or "").strip()
    if not new_code:
        raise ValueError("AVATAR_CODE_REQUIRED")

    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        existing = list(reader)

    for existing_row in existing:
        if str(existing_row.get("AvatarCode") or "").strip().casefold() == new_code.casefold():
            raise ValueError(f"AVATAR_CODE_EXISTS:{new_code}")

    full_row = {column: str(row.get(column, "") or "") for column in header}

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    for existing_row in existing:
        writer.writerow({column: str(existing_row.get(column, "") or "") for column in header})
    writer.writerow(full_row)
    return sync_pool_csv(buffer.getvalue().encode("utf-8"))


def delete_avatar(avatar_code: str) -> dict:
    """Remove ONE row by AvatarCode (case-insensitive) and write the whole table
    back through the SAME fail-closed sync_pool_csv() door as add_avatar (which
    re-validates REQUIRED_COLUMNS + uniqueness, installs the bridge, reloads the
    cache). Raises AVATAR_CODE_NOT_FOUND if the code is absent, and refuses to
    empty the registry (AVATAR_REGISTRY_WOULD_BE_EMPTY)."""
    import io

    target = str(avatar_code or "").strip()
    if not target:
        raise ValueError("AVATAR_CODE_REQUIRED")

    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        existing = list(reader)

    kept = [
        r for r in existing
        if str(r.get("AvatarCode") or "").strip().casefold() != target.casefold()
    ]
    if len(kept) == len(existing):
        raise ValueError(f"AVATAR_CODE_NOT_FOUND:{target}")
    if not kept:
        raise ValueError("AVATAR_REGISTRY_WOULD_BE_EMPTY")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    for r in kept:
        writer.writerow({column: str(r.get(column, "") or "") for column in header})
    result = sync_pool_csv(buffer.getvalue().encode("utf-8"))
    return {"removed": target, "remaining": result["rows"], "bridge_path": result["bridge_path"]}


def descriptor_key(profile: dict, gender: str | None = None) -> tuple[str, ...]:
    """Lowercased descriptor tuple (skin_tone, hair_style, wardrobe, expression,
    gender_word) used to detect duplicate avatars. gender_word derives from the
    avatar_code, or falls back to a passed gender ('F'/'M' or a plain word)."""
    gender_word = _gender_word(str(profile.get("avatar_code") or ""))
    if gender_word == "adult" and gender:
        g = str(gender).strip().upper()
        gender_word = "woman" if g == "F" else "man" if g == "M" else str(gender).strip().lower()
    return (
        str(profile.get("skin_tone") or "").strip().lower(),
        str(profile.get("hair_style") or "").strip().lower(),
        str(profile.get("wardrobe") or "").strip().lower(),
        str(profile.get("expression") or "").strip().lower(),
        gender_word,
    )


def find_duplicate_avatar(
    skin_tone: str, hair_style: str, wardrobe: str, expression: str, gender: str
) -> dict | None:
    """Return the first pool profile whose descriptor_key equals the given one
    (case-insensitive), else None."""
    g = str(gender or "").strip().upper()
    gender_word = "woman" if g == "F" else "man" if g == "M" else str(gender or "").strip().lower()
    wanted = (
        str(skin_tone or "").strip().lower(),
        str(hair_style or "").strip().lower(),
        str(wardrobe or "").strip().lower(),
        str(expression or "").strip().lower(),
        gender_word,
    )
    for profile in list_pool():
        if descriptor_key(profile, gender=gender) == wanted:
            return profile
    return None


def _slugify(text: str) -> str:
    """Uppercased alnum slug: non-alnum -> '_', collapsed repeats, no edge '_'."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_").upper()
    return slug


def next_avatar_code(gender: str, descriptor: str) -> str:
    """Build BOS_{F|M}_{SLUG}_{NN}. NN = 2-digit (max existing NN for that
    BOS_{F|M}_{SLUG}_ prefix + 1, else '01'). Matches the canonical code regex."""
    g = str(gender or "").strip().upper()
    if g not in ("F", "M"):
        raise ValueError(f"AVATAR_GENDER_INVALID:{gender}")
    slug = _slugify(descriptor)
    if not slug:
        raise ValueError("AVATAR_DESCRIPTOR_EMPTY")
    prefix = f"BOS_{g}_{slug}_"
    max_nn = 0
    for row in _load_pool():
        code = str(row.get("AvatarCode") or "").strip().upper()
        if code.startswith(prefix):
            tail = code[len(prefix):]
            if tail.isdigit():
                max_nn = max(max_nn, int(tail))
    code = f"{prefix}{max_nn + 1:02d}"
    if not _CODE_RE.match(code):
        raise ValueError(f"AVATAR_CODE_MALFORMED:{code}")
    return code


def build_avatar_prompt_v1(profile: dict) -> str:
    """The image-gen PromptV1, mirroring the seed-row format in
    AVATAR_POOL_NORMALIZED.csv (Identity/Code included, matching the seed style)."""
    name = str(profile.get("CharacterName") or profile.get("character_name") or "").strip()
    code = str(profile.get("AvatarCode") or profile.get("avatar_code") or "").strip()
    gender_word = _gender_word(code)
    demographic = "Female" if gender_word == "woman" else "Male" if gender_word == "man" else "Adult"
    skin = str(profile.get("SkinTone") or profile.get("skin_tone") or "").strip()
    hair = str(profile.get("HairStyle") or profile.get("hair_style") or "").strip()
    wardrobe = str(profile.get("Wardrobe") or profile.get("wardrobe") or "").strip()
    expression = str(profile.get("Expression") or profile.get("expression") or "").strip()
    environment = str(profile.get("Environment") or profile.get("environment") or "").strip()
    lighting = str(profile.get("Lighting") or profile.get("lighting") or "").strip()
    camera = str(profile.get("Camera") or profile.get("camera") or "").strip()
    hijab = bool(profile.get("hijab"))

    styling = wardrobe
    if hijab:
        styling = f"{styling}, wearing a hijab/tudung" if styling else "wearing a hijab/tudung"

    return (
        "Create a photorealistic avatar reference image. "
        f"Identity: {name}, Code: {code}. "
        f"Demographic: {demographic}, Young Adult, Malay/SEA market fit. "
        f"Skin tone: {skin or 'Light-medium'}. Hair: {hair or 'Medium tidy'}. "
        f"Styling: {styling or 'Smart casual wear'}. "
        f"Expression: {expression or 'Calm neutral'}. Pose: Relaxed, natural. "
        f"Environment: {environment or 'clean commercial'}, "
        f"{lighting or 'balanced commercial'} lighting. "
        f"Camera framing: {camera or 'Waist-up'}, clear face. "
        "Safety: Do not generate nudity, sexual content, gore, violence, hate "
        "symbols, illegal activity, or any harmful or unsafe depiction. Keep the "
        "character fully clothed, respectful, and suitable for general audience "
        "and commercial use."
    )
