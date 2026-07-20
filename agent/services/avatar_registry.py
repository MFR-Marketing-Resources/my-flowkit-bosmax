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
import json
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


# ── Controlled descriptor vocabulary (single source of truth for the Create
# Avatar dropdowns, the AI allowed-values prompt, and fail-closed validation).
_VOCAB_FILE = _AUTHORITY_DIR / "avatar_registry_vocab.json"
_VOCAB_REQUIRED_FIELDS = ("skin_tone", "hair_style", "wardrobe", "expression")
_VOCAB_OPTIONAL_FIELDS = ("environment", "lighting", "camera")
_PERSONA_RE = re.compile(r"^BOS_[FM]_([A-Z0-9]+)_[0-9]{2,}$")
# Same shape as _PERSONA_RE but also captures the gender letter (used to derive
# per-gender persona lists from the pool AvatarCode prefix).
_PERSONA_GENDER_RE = re.compile(r"^BOS_([FM])_([A-Z0-9]+)_[0-9]{2,}$")

_AVATAR_REFERENCE_FREE_HAND_LAW = (
    "Avatar reference pose law: both hands must be empty and visible where framed. "
    "The avatar must not hold, touch, present, carry, sip from, or interact with any object. "
    "No cup, bottle, phone, book, food, bag, product, prop, tool, package, label, or container in the hands. "
    "Use a neutral reusable commercial identity pose: relaxed open hands, hands by sides, "
    "or hands resting naturally, leaving the hand area clean for future product-composite generation."
)


def avatar_reference_free_hand_law() -> str:
    """Public test/readback hook for the reusable avatar-reference pose law."""
    return _AVATAR_REFERENCE_FREE_HAND_LAW


def _harden_avatar_generation_prompt(prompt: str) -> str:
    """Append the avatar free-hand law to legacy PromptV1 rows at read time.

    The live bridge can contain older CSV rows. Hardening at the getter protects
    bulk/regeneration without forcing a risky registry rewrite.
    """
    clean = str(prompt or "").strip()
    if not clean or "Avatar reference pose law:" in clean:
        return clean
    return f"{clean} {_AVATAR_REFERENCE_FREE_HAND_LAW}"


@lru_cache(maxsize=1)
def _vocab_doc() -> dict:
    """Parsed vocabulary JSON (fields + gender rules). Cache mirrors load_vocab."""
    return json.loads(_VOCAB_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_vocab() -> dict[str, list[str]]:
    """Controlled vocabulary per descriptor field. Edit the JSON to add a value."""
    return {k: list(v) for k, v in _vocab_doc().get("fields", {}).items()}


def _vocab_set(field: str) -> set[str]:
    return {str(v).strip().casefold() for v in load_vocab().get(field, [])}


def snap_to_vocab(field: str, value: str | None) -> str | None:
    """Case-insensitive snap of ``value`` to its canonical vocab entry, or None if
    the value is not in the vocabulary. Used to normalize AI-returned values."""
    want = str(value or "").strip().casefold()
    if not want:
        return None
    for canonical in load_vocab().get(field, []):
        if str(canonical).strip().casefold() == want:
            return str(canonical)
    return None


# ── Gender-aware vocabulary. `fields` is the full superset (canonical casing +
# membership); `gender_specific_fields` narrow per gender via `by_gender`. A
# field not listed for a gender is shared (full list applies).

def gender_specific_fields() -> list[str]:
    """Descriptor fields whose allowed values depend on gender (e.g. wardrobe)."""
    return list(_vocab_doc().get("gender_specific_fields", []))


def vocab_for_gender(gender: str) -> dict[str, list[str]]:
    """Full descriptor vocab with the gender_specific_fields narrowed to the
    values allowed for ``gender`` ('F'/'M'); shared fields returned in full.
    An unknown gender yields the full superset (fail-open only for display —
    the fail-closed gate is validate_gender_compatibility)."""
    g = str(gender or "").strip().upper()
    by_gender = _vocab_doc().get("by_gender", {}).get(g, {})
    return {
        field: list(by_gender.get(field, values))
        for field, values in load_vocab().items()
    }


def _gender_allowed_set(field: str, gender: str) -> set[str]:
    return {str(v).strip().casefold() for v in vocab_for_gender(gender).get(field, [])}


def snap_to_vocab_for_gender(field: str, value: str | None, gender: str) -> str | None:
    """snap_to_vocab, but for a gender_specific field the canonical value must ALSO
    be allowed for ``gender`` — else None (so an AI male + female-only wardrobe is
    rejected, not silently kept). Shared fields behave exactly like snap_to_vocab."""
    canonical = snap_to_vocab(field, value)
    if canonical is None:
        return None
    if field in gender_specific_fields() and \
            canonical.strip().casefold() not in _gender_allowed_set(field, gender):
        return None
    return canonical


def validate_usage_tags(raw) -> None:
    """Every tag (comma/pipe list) must be in the usage_tags vocabulary."""
    allowed = _vocab_set("usage_tags")
    for tag in _parse_usage_tags(raw):
        if tag.strip().casefold() not in allowed:
            raise ValueError("AVATAR_VALUE_NOT_IN_VOCAB:usage_tags")


def validate_descriptors(payload: dict) -> None:
    """Fail-closed vocab check for a manual/AI avatar payload. Raises
    ``ValueError('AVATAR_VALUE_NOT_IN_VOCAB:<field>')`` on any off-vocab value.
    Required descriptors must be present + in-vocab; optional ones (environment/
    lighting/camera) are checked only when provided; usage_tags each in-vocab."""
    for field in _VOCAB_REQUIRED_FIELDS:
        if str(payload.get(field) or "").strip().casefold() not in _vocab_set(field):
            raise ValueError(f"AVATAR_VALUE_NOT_IN_VOCAB:{field}")
    for field in _VOCAB_OPTIONAL_FIELDS:
        value = str(payload.get(field) or "").strip()
        if value and value.casefold() not in _vocab_set(field):
            raise ValueError(f"AVATAR_VALUE_NOT_IN_VOCAB:{field}")
    validate_usage_tags(payload.get("usage_tags"))


def personas_from_pool() -> list[str]:
    """Distinct clean persona tokens (single segment, <= 16 chars) parsed from the
    live pool AvatarCodes — powers the Create Avatar 'existing persona' dropdown.
    Multi-segment descriptor-slug leaks are excluded by the single-segment regex."""
    seen: dict[str, None] = {}
    for row in list_pool():
        code = str(row.get("avatar_code") or "").strip().upper()
        match = _PERSONA_RE.match(code)
        if not match:
            continue
        token = match.group(1)
        if len(token) <= 16 and token not in seen:
            seen[token] = None
    return sorted(seen)


def personas_by_gender() -> dict[str, list[str]]:
    """Persona tokens split by gender, derived from the pool AvatarCode prefix
    (BOS_F_/BOS_M_). Powers the gender-filtered persona dropdown. The pool prefix
    is the gender authority (repaired PR #377); a token appearing under both
    genders is placed in neither bucket (ambiguous → unconstrained)."""
    buckets: dict[str, set[str]] = {"F": set(), "M": set()}
    conflict: set[str] = set()
    for row in list_pool():
        code = str(row.get("avatar_code") or "").strip().upper()
        match = _PERSONA_GENDER_RE.match(code)
        if not match:
            continue
        gender, token = match.group(1), match.group(2)
        if len(token) > 16:
            continue
        other = "M" if gender == "F" else "F"
        if token in buckets[other]:
            conflict.add(token)
        buckets[gender].add(token)
    for token in conflict:
        buckets["F"].discard(token)
        buckets["M"].discard(token)
    return {"F": sorted(buckets["F"]), "M": sorted(buckets["M"])}


def persona_gender(name: str) -> str | None:
    """Gender ('F'/'M') of an EXISTING pool persona token, else None (token not in
    the pool — e.g. a brand-new persona — or ambiguous). Case-insensitive."""
    key = str(name or "").strip().upper()
    if not key:
        return None
    buckets = personas_by_gender()
    found = [g for g, tokens in buckets.items() if key in tokens]
    return found[0] if len(found) == 1 else None


def validate_gender_compatibility(payload: dict) -> None:
    """Fail-closed gender-dependency gate for a manual/AI avatar payload. Raises
    ValueError on the first violation:
      - AVATAR_GENDER_INVALID:<g>          gender not F/M
      - AVATAR_HIJAB_MALE_INVALID          hijab requested on a male
      - AVATAR_VALUE_NOT_FOR_GENDER:<field> a gender_specific descriptor value
                                            not allowed for the chosen gender
      - AVATAR_PERSONA_GENDER_MISMATCH     an existing persona vs the other gender
    Membership (value in the field superset) is validate_descriptors' job; this
    layer only enforces the gender dependency on top of it."""
    gender = str(payload.get("gender") or "").strip().upper()
    if gender not in ("F", "M"):
        raise ValueError(f"AVATAR_GENDER_INVALID:{payload.get('gender')}")
    if bool(payload.get("hijab")) and gender == "M":
        raise ValueError("AVATAR_HIJAB_MALE_INVALID")
    for field in gender_specific_fields():
        value = str(payload.get(field) or "").strip()
        if value and value.casefold() not in _gender_allowed_set(field, gender):
            raise ValueError(f"AVATAR_VALUE_NOT_FOR_GENDER:{field}")
    expected = persona_gender(payload.get("character_name") or "")
    if expected is not None and expected != gender:
        raise ValueError("AVATAR_PERSONA_GENDER_MISMATCH")


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
    # Persona-variant override (Phase A): a profile carrying `prose_override`
    # (persona_variant_service) renders its curated description verbatim.
    # Pool-CSV profiles never carry this key — their output is byte-identical.
    override = str(profile.get("prose_override") or "").strip()
    if override:
        return (
            f"The presenter is {override.rstrip('.')}. Keep this exact presenter "
            f"identity — face, hair, wardrobe, and body language — consistent in "
            f"every shot."
        )
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
                "prompt": _harden_avatar_generation_prompt(prompt),
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

    prompt = (
        "Create a photorealistic avatar reference image. "
        f"Identity: {name}, Code: {code}. "
        f"Demographic: {demographic}, Young Adult, Malay/SEA market fit. "
        f"Skin tone: {skin or 'Light-medium'}. Hair: {hair or 'Medium tidy'}. "
        f"Styling: {styling or 'Smart casual wear'}. "
        f"Expression: {expression or 'Calm neutral'}. "
        "Pose: relaxed neutral reusable avatar reference pose, with empty hands and no object held. "
        f"Environment: {environment or 'clean commercial'}, "
        f"{lighting or 'balanced commercial'} lighting. "
        f"Camera framing: {camera or 'Waist-up'}, clear face. "
        "Safety: Do not generate nudity, sexual content, gore, violence, hate "
        "symbols, illegal activity, or any harmful or unsafe depiction. Keep the "
        "character fully clothed, respectful, and suitable for general audience "
        "and commercial use."
    )
    return _harden_avatar_generation_prompt(prompt)