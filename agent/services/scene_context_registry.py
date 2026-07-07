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
    return {
        "scene_code": str(row.get("SceneCode") or "").strip(),
        "scene_name": str(row.get("SceneName") or "").strip(),
        "background_prompt": str(row.get("BackgroundPrompt") or "").strip(),
        "route_fit": _parse_route_fit(row.get("RouteFit")),
        "usage_tags": _parse_usage_tags(row.get("usage_tags")),
    }


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
