"""CRUD boundary for the Creative Execution Recipe (Round 3).

Sole SQL layer for ``creative_execution_recipe_v1``. House conventions (see
copy_render_crud / creative_factory_crud): reads lock-free; writes under
``async with _db_lock``; ids ``CER_<hex>``; TEXT ISO-8601-Z timestamps; JSON
columns encoded with sorted keys.

The recipe is IMMUTABLE: ``get_or_create_recipe`` is idempotent by the recipe's
deterministic identity digest (same immutable inputs -> the same recipe_id =
exact replay), and ``bind_prompt_snapshot`` freezes the compiled prompt-snapshot
reference exactly once (DRAFT -> FINALIZED).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from agent.db.schema import _db_lock, get_db

_COLS = (
    "recipe_id", "recipe_identity_digest", "product_id", "production_recipe",
    "benefit_id", "benefit_digest", "copy_session_id", "candidate_id", "artifact_id",
    "copy_text_digest", "copy_source", "formula_id", "formula_version",
    "atom_recipe_fingerprint", "angle_id", "hook_id", "body_id", "cta_id",
    "requested_total_duration_seconds", "generation_mode", "orchestration_digest",
    "visual_variation_fingerprint", "visual_resolver_version", "avatar_id",
    "scene_template_id", "camera_preset_code", "wardrobe", "environment",
    "treatment_id", "faceless_actor_profile", "montage_mascot_media_id",
    "visual_config_json", "pi_snapshot_id", "pi_snapshot_version",
    "product_truth_digest", "official_visual_sha256", "compiler_version",
    "recipe_schema_version", "status", "workspace_execution_package_id",
    "prompt_fingerprint", "prompt_snapshot_json", "lineage_json", "created_at",
    "finalized_at",
)
_JSON_COLS = {"visual_config_json", "prompt_snapshot_json", "lineage_json"}


def new_id(prefix: str = "CER") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for col in _JSON_COLS:
        if col in out:
            out[col] = decode(out.get(col), {})
    return out


async def get_recipe(recipe_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM creative_execution_recipe_v1 WHERE recipe_id=?", (recipe_id,))
    return _row(await cur.fetchone())


async def get_recipe_by_identity(identity_digest: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM creative_execution_recipe_v1 WHERE recipe_identity_digest=?",
        (identity_digest,))
    return _row(await cur.fetchone())


async def list_recipes(*, candidate_id: str | None = None, product_id: str | None = None,
                       production_recipe: str | None = None) -> list[dict[str, Any]]:
    db = await get_db()
    where: list[str] = []
    params: list[Any] = []
    if candidate_id:
        where.append("candidate_id=?"); params.append(candidate_id)
    if product_id:
        where.append("product_id=?"); params.append(product_id)
    if production_recipe:
        where.append("production_recipe=?"); params.append(production_recipe)
    sql = "SELECT * FROM creative_execution_recipe_v1"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC, recipe_id ASC"
    cur = await db.execute(sql, params)
    return [_row(r) for r in await cur.fetchall()]


async def get_or_create_recipe(row: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotent by ``recipe_identity_digest``: if a recipe with the same immutable
    identity already exists it is returned unchanged (exact replay); otherwise the
    new immutable DRAFT recipe is inserted. Never overwrites an existing recipe."""
    identity = str(row["recipe_identity_digest"])
    async with _db_lock:
        db = await get_db()
        cur = await db.execute(
            "SELECT * FROM creative_execution_recipe_v1 WHERE recipe_identity_digest=?",
            (identity,))
        existing = await cur.fetchone()
        if existing is not None:
            return _row(existing)
        payload = dict(row)
        payload.setdefault("recipe_id", new_id())
        payload.setdefault("created_at", utc_now())
        payload.setdefault("status", "DRAFT")
        for col in _JSON_COLS:
            if col in payload and not isinstance(payload[col], str):
                payload[col] = encode(payload[col])
        cols = [c for c in _COLS if c in payload]
        await db.execute(
            f"INSERT INTO creative_execution_recipe_v1 ({','.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)})",
            [payload[c] for c in cols])
        await db.commit()
        return await get_recipe(payload["recipe_id"])


async def bind_prompt_snapshot(recipe_id: str, *, workspace_execution_package_id: str,
                               prompt_fingerprint: str,
                               prompt_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the compiled prompt-snapshot reference exactly once (DRAFT->FINALIZED).

    Immutable: if already FINALIZED the stored snapshot is returned unchanged and
    is NEVER overwritten (an authority change produces a NEW recipe, not a rewrite)."""
    async with _db_lock:
        db = await get_db()
        cur = await db.execute(
            "SELECT status FROM creative_execution_recipe_v1 WHERE recipe_id=?",
            (recipe_id,))
        found = await cur.fetchone()
        if found is None:
            raise KeyError(recipe_id)
        if str(dict(found).get("status")) == "FINALIZED":
            return await get_recipe(recipe_id)
        await db.execute(
            "UPDATE creative_execution_recipe_v1 SET status='FINALIZED', "
            "workspace_execution_package_id=?, prompt_fingerprint=?, "
            "prompt_snapshot_json=?, finalized_at=? WHERE recipe_id=?",
            (workspace_execution_package_id, prompt_fingerprint,
             encode(dict(prompt_snapshot)), utc_now(), recipe_id))
        await db.commit()
        return await get_recipe(recipe_id)
