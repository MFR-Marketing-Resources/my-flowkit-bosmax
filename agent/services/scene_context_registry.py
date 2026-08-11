"""Scene-context registry — deterministic scene/background resolution layer.

Mirror of ``avatar_registry`` (ADR-008 pattern) for reusable SCENE CONTEXTS.
Consumes the retained scene pool (``agent/authority/SCENE_CONTEXT_POOL.csv`` — the
repo seed of the 20 deterministic scene snippets; the pool GROWS over time) and
resolves ONE normalized, clean, background-only scene profile.

Law: registry fields are UPSTREAM authoring inputs. The final prompt renderer
receives a resolved profile and renders the real ``Background:`` prose — never
pool metadata, never selection instructions. A scene context is a background/
environment PLATE (no people, no product); its PromptV1 generates a clean scene
reference image (IMG ``SCENE_REFERENCE`` lane, credit-free).

Hard rule carried from the source pack: scene snippets from this pool are NOT
enough to activate Mode C, and must never override a locked inherited scene DNA
coming from ``source_image_handoff`` (BOSMAX_IMAGE_HANDOFF route). This module
only SUPPLIES snippets; enforcement of that precedence lives in the compiler.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"
_POOL_FILE = _AUTHORITY_DIR / "SCENE_CONTEXT_POOL.csv"
# Normalized bridge target: growth arrives as an explicit, validated CSV sync into
# this file. When present it OVERRIDES the repo seed; when absent the vendored
# retained pool is authoritative (mirrors avatar_registry).
_BRIDGE_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "scene_context_registry" / "SCENE_CONTEXT_POOL.csv"
)

# PromptV1 is required so a synced CSV can always drive generate-image; without it
# get_generation_prompt would fail closed only later, at generation time.
REQUIRED_COLUMNS = {"SceneName", "SceneCode", "BackgroundPrompt", "PromptV1"}
_CLUSTER_MAP_FILE = _AUTHORITY_DIR / "creative_category_cluster_map.json"
_CLASSIFICATION_FILE = _AUTHORITY_DIR / "scene_context_cluster_classification.json"


@lru_cache(maxsize=1)
def canonical_clusters() -> tuple[str, ...]:
    """The existing Creative Intelligence cluster authority; never infer a new taxonomy."""
    data = json.loads(_CLUSTER_MAP_FILE.read_text(encoding="utf-8"))
    return tuple(str(value) for value in data["clusters"])


def _normalise_cluster(value: str) -> str | None:
    wanted = " ".join(str(value or "").split()).casefold()
    return next((cluster for cluster in canonical_clusters() if cluster.casefold() == wanted), None)


def _parse_clusters(raw: str) -> list[str]:
    parsed: list[str] = []
    for value in str(raw or "").split("|"):
        cluster = _normalise_cluster(value)
        if cluster:
            parsed.append(cluster)
    return parsed


def _seed_scene_codes() -> set[str]:
    with _POOL_FILE.open(encoding="utf-8-sig", newline="") as source:
        return {
            str(row.get("SceneCode") or "").strip().upper()
            for row in csv.DictReader(source)
            if str(row.get("SceneCode") or "").strip()
        }


@lru_cache(maxsize=1)
def _classification_by_code() -> dict[str, dict]:
    payload = json.loads(_CLASSIFICATION_FILE.read_text(encoding="utf-8"))
    classification_version = str(payload.get("classification_version") or "").strip()
    if not classification_version:
        raise ValueError("SCENE_CLASSIFICATION_BLANK_VERSION")
    result: dict[str, dict] = {}
    for entry in payload.get("scenes") or []:
        code = str(entry["scene_code"]).strip().upper()
        if code in result:
            raise ValueError(f"SCENE_CLASSIFICATION_DUPLICATE_SCENE_CODE:{code}")
        primary = entry.get("primary_cluster")
        compatible = list(entry.get("compatible_clusters") or [])
        status = entry.get("classification_status")
        basis = str(entry.get("classification_basis") or "").strip()
        version = str(entry.get("classification_version") or "").strip()
        if version != classification_version:
            raise ValueError(f"SCENE_CLASSIFICATION_INCONSISTENT_VERSION:{code}")
        if (
            not basis
            or status not in {"CLASSIFIED", "REVIEW_REQUIRED"}
            or any(_normalise_cluster(x) != x for x in compatible)
            or len({str(cluster).casefold() for cluster in compatible}) != len(compatible)
        ):
            raise ValueError(f"SCENE_CLASSIFICATION_INVALID:{code}")
        if status == "CLASSIFIED" and (primary is None or not compatible or compatible.count(primary) != 1 or _normalise_cluster(primary) != primary):
            raise ValueError(f"SCENE_CLASSIFICATION_INVALID_PRIMARY:{code}")
        if status == "REVIEW_REQUIRED" and (primary is not None or compatible):
            raise ValueError(f"SCENE_CLASSIFICATION_INVALID_REVIEW_REQUIRED:{code}")
        result[code] = entry
    seed_codes = _seed_scene_codes()
    unknown = sorted(set(result) - seed_codes)
    missing = sorted(seed_codes - set(result))
    if unknown:
        raise ValueError(f"SCENE_CLASSIFICATION_UNKNOWN_SCENE_CODE:{','.join(unknown)}")
    if missing:
        raise ValueError(f"SCENE_CLASSIFICATION_MISSING_SEED_SCENE_CODE:{','.join(missing)}")
    return result


def _explicit_clusters(row: dict) -> tuple[str | None, list[str]] | None:
    raw_primary, raw_compatible = str(row.get("PrimaryCluster") or "").strip(), str(row.get("CompatibleClusters") or "").strip()
    if not raw_primary and not raw_compatible:
        return None
    compatible = _parse_clusters(raw_compatible)
    if not raw_primary or len(compatible) != len([x for x in raw_compatible.split("|") if x.strip()]):
        raise ValueError("SCENE_REGISTRY_INVALID_CLUSTER_METADATA")
    primary = _normalise_cluster(raw_primary)
    if not primary or compatible.count(primary) != 1 or len({x.casefold() for x in compatible}) != len(compatible):
        raise ValueError("SCENE_REGISTRY_INVALID_CLUSTER_METADATA")
    return primary, compatible


def _active_pool_file() -> Path:
    return _BRIDGE_FILE if _BRIDGE_FILE.exists() else _POOL_FILE


def sync_pool_csv(csv_bytes: bytes) -> dict:
    """Fail-closed registry sync: validate the uploaded normalized CSV, then
    install it as the runtime bridge override and reload the cache."""
    text = csv_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("SCENE_REGISTRY_EMPTY")
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(f"SCENE_REGISTRY_COLUMNS_MISSING:{sorted(missing)}")
    codes = [str(r.get("SceneCode") or "").strip() for r in rows]
    if not all(codes):
        raise ValueError("SCENE_REGISTRY_BLANK_SCENE_CODE")
    if len(set(codes)) != len(codes):
        raise ValueError("SCENE_REGISTRY_DUPLICATE_SCENE_CODE")
    if not all(str(r.get("BackgroundPrompt") or "").strip() for r in rows):
        raise ValueError("SCENE_REGISTRY_BLANK_BACKGROUND_PROMPT")
    for row in rows:
        _explicit_clusters(row)
    _atomic_write_bridge(csv_bytes)
    count = reload_pool()
    return {"rows": len(rows), "approved_loaded": count, "bridge_path": str(_BRIDGE_FILE)}


def _atomic_write_bridge(csv_bytes: bytes) -> None:
    """Install a fully validated bridge as one filesystem replacement."""
    _BRIDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="scene-context-", suffix=".csv", dir=_BRIDGE_FILE.parent)
    try:
        with os.fdopen(handle, "wb") as target:
            target.write(csv_bytes)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, _BRIDGE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore_bridge_snapshot(existed: bool, previous_bytes: bytes | None) -> None:
    """Restore an exact pre-activation bridge snapshot and refresh the pool cache."""
    if existed:
        _atomic_write_bridge(previous_bytes or b"")
    elif _BRIDGE_FILE.exists():
        _BRIDGE_FILE.unlink()
    reload_pool()


@lru_cache(maxsize=1)
def _load_pool() -> tuple[dict, ...]:
    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        rows = tuple(
            row for row in csv.DictReader(f)
            if str(row.get("approved_flag", "")).strip().lower() in ("true", "1", "yes", "approved", "")
        )
    if not rows:
        raise RuntimeError("SCENE_POOL_EMPTY: no approved scene contexts in registry")
    return rows


def reload_pool() -> int:
    """Clear the cache after the registry file is updated (pool grows over time)."""
    _load_pool.cache_clear()
    return len(_load_pool())


def _parse_usage_tags(raw: str) -> list[str]:
    """Parse a usage_tags cell (accepts both `a, b` and `a|b`), stripped + deduped."""
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


def _parse_route_fit(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[|,]", str(raw or "")) if p.strip()]


def _normalize_profile(row: dict) -> dict:
    code = str(row.get("SceneCode") or "").strip().upper()
    explicit = _explicit_clusters(row)
    authority = _classification_by_code().get(code, {})
    primary_cluster, compatible_clusters = explicit or (authority.get("primary_cluster"), list(authority.get("compatible_clusters") or []))
    status = "CLASSIFIED" if explicit else authority.get("classification_status", "REVIEW_REQUIRED")
    return {
        "scene_code": str(row.get("SceneCode") or "").strip(),
        "scene_name": str(row.get("SceneName") or "").strip(),
        "background_prompt": str(row.get("BackgroundPrompt") or "").strip(),
        "route_fit": _parse_route_fit(row.get("RouteFit")),
        "usage_tags": _parse_usage_tags(row.get("usage_tags")),
        "primary_cluster": primary_cluster if status == "CLASSIFIED" else None,
        "compatible_clusters": compatible_clusters,
        "cluster_classification_status": status,
        "cluster_classification_basis": "bridge_csv" if explicit else authority.get("classification_basis", "No classification authority entry."),
    }


def cluster_coverage() -> dict:
    """Read-only coverage matrix. Legacy rows without classification remain explicit review-required."""
    profiles = list_pool()
    rows: list[dict] = []
    for cluster in canonical_clusters():
        eligible = [p for p in profiles if p["cluster_classification_status"] == "CLASSIFIED" and cluster in p["compatible_clusters"]]
        primary = [p for p in eligible if p["primary_cluster"] == cluster]
        rows.append({"cluster": cluster, "eligible_active_scene_count": len(eligible), "primary_scene_count": len(primary), "shared_compatible_scene_count": len(eligible)-len(primary), "gap_to_target": max(0, 3-len(eligible)), "eligible_scene_codes": sorted(p["scene_code"] for p in eligible)})
    review_required = [p for p in profiles if p["cluster_classification_status"] == "REVIEW_REQUIRED"]
    return {"canonical_clusters": list(canonical_clusters()), "target_per_cluster": 3, "active_scene_total": len(profiles), "classified_scene_total": len(profiles)-len(review_required), "review_required_scene_total": len(review_required), "shared_scene_total": sum(1 for p in profiles if p["cluster_classification_status"] == "CLASSIFIED" and len(p["compatible_clusters"]) > 1), "per_cluster": rows, "milestone_complete": all(not r["gap_to_target"] for r in rows), "registry_mutations": 0}


def classification() -> dict:
    return {"active_scene_total": len(list_pool()), "registry_mutations": 0, "scenes": list_pool()}


def scene_background_prose(profile: dict) -> str:
    """Render the resolved scene as engine-facing background prose.

    This is the ONLY sanctioned way a scene context enters a final prompt: the
    real ``Background:`` description, clean (no people, no product, no metadata).
    """
    bg = str(profile.get("background_prompt") or "").strip()
    if not bg:
        return ""
    # BackgroundPrompt is already stored as "Background: ..."; keep it verbatim.
    if not bg.lower().startswith("background"):
        bg = f"Background: {bg}"
    return bg


def get_generation_prompt(scene_code: str) -> dict:
    """Server-side only: the scene's PromptV1 (full scene-reference image prompt).
    Raw prompt text never reaches the dashboard — only the IMG job it feeds."""
    wanted = str(scene_code or "").strip().upper()
    for row in _load_pool():
        if str(row.get("SceneCode", "")).strip().upper() == wanted:
            prompt = str(row.get("PromptV1") or "").strip()
            if not prompt:
                raise ValueError(f"SCENE_PROMPT_EMPTY:{scene_code}")
            return {
                "scene_code": str(row.get("SceneCode")).strip(),
                "scene_name": str(row.get("SceneName") or "").strip(),
                "prompt": prompt,
            }
    raise ValueError(f"SCENE_NOT_FOUND:{scene_code}")


def list_pool() -> list[dict]:
    """Read-only view of every approved scene profile (dashboard registry tab).

    Returns normalized profiles only — raw rows (PromptV1 etc.) stay internal; the
    scene enters prompts solely via scene_background_prose().
    """
    return [_normalize_profile(row) for row in _load_pool()]


def resolve_scene_context(
    scene_id: str | None = None,
    *,
    usage_context: str | None = None,
    seed: str | None = None,
) -> dict:
    """Resolve exactly ONE scene profile, deterministically.

    Priority: explicit scene_id (SceneCode) → usage-tag/context match →
    deterministic seed pick (same seed always yields the same scene). Never random.
    """
    pool = _load_pool()
    if scene_id:
        wanted = str(scene_id).strip().upper()
        for row in pool:
            if str(row.get("SceneCode", "")).strip().upper() == wanted:
                return _normalize_profile(row)
        raise ValueError(f"SCENE_NOT_FOUND:{scene_id}")
    candidates = pool
    if usage_context:
        ctx = usage_context.strip().lower()
        tagged = [
            row for row in pool
            if ctx in str(row.get("usage_tags", "")).lower()
            or ctx in str(row.get("SceneName", "")).lower()
            or ctx in str(row.get("BackgroundPrompt", "")).lower()
        ]
        if tagged:
            candidates = tuple(tagged)
    digest = hashlib.sha256(str(seed or "bosmax-scene-default").encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(candidates)
    return _normalize_profile(candidates[index])


# ── Manual single-row add + AI auto-generate support (additive, mirror of
# avatar_registry). Both paths write through the EXISTING fail-closed sync_pool_csv()
# door so REQUIRED_COLUMNS + uniqueness stay authoritative.


def _normalize_text(text: str) -> str:
    """Lowercased, whitespace-collapsed comparison key."""
    return " ".join(str(text or "").strip().lower().split())


def add_scene(row: dict) -> dict:
    """Single-row add WITHOUT a CSV upload. Requires row['SceneCode']
    (case-insensitive uniqueness), builds a full row for EVERY header column, then
    writes the whole table back through the EXISTING fail-closed sync_pool_csv()."""
    new_code = str(row.get("SceneCode") or "").strip()
    if not new_code:
        raise ValueError("SCENE_CODE_REQUIRED")

    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        existing = list(reader)

    for existing_row in existing:
        if str(existing_row.get("SceneCode") or "").strip().casefold() == new_code.casefold():
            raise ValueError(f"SCENE_CODE_EXISTS:{new_code}")

    full_row = {column: str(row.get(column, "") or "") for column in header}

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    for existing_row in existing:
        writer.writerow({column: str(existing_row.get(column, "") or "") for column in header})
    writer.writerow(full_row)
    return sync_pool_csv(buffer.getvalue().encode("utf-8"))


def delete_scene(scene_code: str) -> dict:
    """Remove ONE row by SceneCode (case-insensitive) and write the whole table
    back through the SAME fail-closed sync_pool_csv() door as add_scene. Raises
    SCENE_CODE_NOT_FOUND if absent, refuses to empty the registry
    (SCENE_REGISTRY_WOULD_BE_EMPTY)."""
    target = str(scene_code or "").strip()
    if not target:
        raise ValueError("SCENE_CODE_REQUIRED")

    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        existing = list(reader)

    kept = [
        r for r in existing
        if str(r.get("SceneCode") or "").strip().casefold() != target.casefold()
    ]
    if len(kept) == len(existing):
        raise ValueError(f"SCENE_CODE_NOT_FOUND:{target}")
    if not kept:
        raise ValueError("SCENE_REGISTRY_WOULD_BE_EMPTY")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    for r in kept:
        writer.writerow({column: str(r.get(column, "") or "") for column in header})
    result = sync_pool_csv(buffer.getvalue().encode("utf-8"))
    return {"removed": target, "remaining": result["rows"], "bridge_path": result["bridge_path"]}


# Non-identity presentation columns a metadata-only edit may change. SceneCode and
# every field that derives the code (SceneName), the dedup key (SceneName +
# BackgroundPrompt), or the generation prompt (PromptV1) are intentionally absent,
# so an edit can never change identity, break a reference, or collide with another
# scene. usage_tags is also absent from the generation prompt.
_METADATA_EDITABLE_COLUMNS = ("usage_tags",)


def update_scene(scene_code: str, updates: dict) -> dict:
    """Metadata-only edit of ONE scene by SceneCode (case-insensitive).

    Only whitelisted non-identity columns (currently usage_tags) may change; the
    SceneCode and identity/prompt fields stay frozen. Writes the whole table back
    through the SAME fail-closed sync_pool_csv() door as add/delete. Raises
    SCENE_CODE_NOT_FOUND if the code is absent, and SCENE_NO_EDITABLE_FIELDS if no
    editable column was supplied."""
    target = str(scene_code or "").strip()
    if not target:
        raise ValueError("SCENE_CODE_REQUIRED")
    clean = {
        column: str(updates.get(column) or "")
        for column in _METADATA_EDITABLE_COLUMNS
        if column in updates
    }
    if not clean:
        raise ValueError("SCENE_NO_EDITABLE_FIELDS")

    with open(_active_pool_file(), encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        existing = list(reader)

    found = False
    for existing_row in existing:
        if str(existing_row.get("SceneCode") or "").strip().casefold() == target.casefold():
            for column, value in clean.items():
                if column in header:
                    existing_row[column] = value
            found = True
            break
    if not found:
        raise ValueError(f"SCENE_CODE_NOT_FOUND:{target}")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header)
    writer.writeheader()
    for existing_row in existing:
        writer.writerow({column: str(existing_row.get(column, "") or "") for column in header})
    result = sync_pool_csv(buffer.getvalue().encode("utf-8"))
    return {"updated": target, "rows": result["rows"], "bridge_path": result["bridge_path"]}


def find_duplicate_scene(scene_name: str, background_prompt: str) -> dict | None:
    """Return the first pool profile that matches on normalized scene_name OR on
    identical normalized background text, else None."""
    wanted_name = _normalize_text(scene_name)
    wanted_bg = _normalize_text(background_prompt)
    for profile in list_pool():
        if wanted_name and _normalize_text(profile.get("scene_name")) == wanted_name:
            return profile
        if wanted_bg and _normalize_text(profile.get("background_prompt")) == wanted_bg:
            return profile
    return None


def _slugify(text: str) -> str:
    """Uppercased alnum slug: non-alnum -> '_', collapsed repeats, no edge '_'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_").upper()


def next_scene_code(name: str) -> str:
    """SCN_{SLUG}; append _NN if that base (or an _NN sibling) already exists."""
    slug = _slugify(name)
    if not slug:
        raise ValueError("SCENE_NAME_EMPTY")
    base = f"SCN_{slug}"
    existing_codes = {
        str(row.get("SceneCode") or "").strip().upper() for row in _load_pool()
    }
    if base not in existing_codes:
        return base
    n = 2
    while f"{base}_{n:02d}" in existing_codes:
        n += 1
    return f"{base}_{n:02d}"


def build_scene_prompt_v1(name: str, background: str) -> str:
    """The clean empty-plate scene PromptV1, mirroring the seed-row format in
    SCENE_CONTEXT_POOL.csv (empty environment, no people/product, no rendered text)."""
    bg = str(background or "").strip()
    # BackgroundPrompt cells are stored as "Background: ..."; the PromptV1 embeds the
    # bare description after "Scene: {name}." — strip a leading "Background:" label.
    if bg.lower().startswith("background:"):
        bg = bg.split(":", 1)[1].strip()
    bg = bg.rstrip(". ")
    return (
        "Create a photorealistic empty background scene reference plate for "
        f"commercial compositing. Scene: {str(name or '').strip()}. {bg}. "
        "Empty environment — no people and no product in frame — a clean "
        "commercial background plate suitable as a scene/style reference for later "
        "compositing a presenter and product. Natural depth, perspective, and "
        "lighting exactly as described. No rendered text, captions, headlines, "
        "logos-as-text, price tags, watermark, sticker, or UI chrome — a clean "
        "plate only."
    )
