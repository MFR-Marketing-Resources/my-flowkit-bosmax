"""Bulk angle suggestion — run the per-product suggest engine across many products.

Phase 2 of the AI angle lane. The operator picks a batch of eligible products (those
with an APPROVED product-intelligence snapshot that still have room for more angles)
and this service:

- list_eligible_products(): a read-only cross-product roster for the bulk UI.
- bulk_suggest(product_ids): loop the EXISTING per-product engine
  (copy_angle_suggestion_service.suggest_product_angles) with pacing + per-product
  isolation, and return candidates for review. It writes NOTHING — the operator
  reviews and commits chosen angles through the existing FREE, claim-gated
  add-angles path.

Guardrails:
- Paced (small asyncio.sleep between calls). suggest_product_angles already offloads
  the blocking provider call to a thread, so a batch never starves /health (PR #404).
- Per-product errors are ISOLATED: one bad product never aborts the batch. An
  unconfigured provider is the one fail-fast case (AICopyProviderNotConfigured raises).
- Batch size is capped here (defensive backstop); the API/client also chunk so no
  single request runs too long.

Read-only DB access uses get_db() directly (crud.py is off-limits to this module's
mandor domain); it never writes.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from agent.services import ai_copy_provider_adapter as provider
from agent.services.copy_angle_derivation import MAX_ANGLES
from agent.services.copy_angle_suggestion_service import suggest_product_angles

# The text_assist lane has no 429/backoff of its own, so pacing lives here.
_PACE_SECONDS = 0.4
_RETRY_SECONDS = 1.5
# Defensive cap so a single request can never run too long; the client chunks well
# under this.
_MAX_BATCH = 30


def _persona_pain_count(persona_json: Any) -> int:
    try:
        persona = (
            persona_json
            if isinstance(persona_json, dict)
            else json.loads(persona_json or "{}")
        )
    except Exception:  # noqa: BLE001
        return 0
    if not isinstance(persona, dict):
        return 0
    pains = persona.get("pains")
    if not isinstance(pains, list):
        return 0
    return len([p for p in pains if isinstance(p, str) and p.strip()])


async def list_eligible_products() -> dict[str, Any]:
    """Active products with an APPROVED snapshot that still have room for angles.

    Read-only. Returns {items: [{product_id, name, angle_count, room}], count}.
    """
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        """
        SELECT s.product_id AS product_id,
               COALESCE(p.product_display_name, p.raw_product_title, p.id) AS name,
               s.buyer_persona_snapshot_json AS persona
        FROM product_intelligence_snapshot s
        JOIN product p ON p.id = s.product_id
        WHERE s.status = 'APPROVED'
          AND COALESCE(p.lifecycle_status, 'ACTIVE') = 'ACTIVE'
          AND s.version = (
              SELECT MAX(s2.version)
              FROM product_intelligence_snapshot s2
              WHERE s2.product_id = s.product_id AND s2.status = 'APPROVED'
          )
        ORDER BY name COLLATE NOCASE
        """
    )
    rows = await cur.fetchall()

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        pid = row["product_id"]
        if pid in seen:  # defensive: dupe max-version rows
            continue
        seen.add(pid)
        count = _persona_pain_count(row["persona"])
        room = MAX_ANGLES - count
        if room <= 0:
            continue
        items.append(
            {
                "product_id": pid,
                "name": row["name"] or pid,
                "angle_count": count,
                "room": room,
            }
        )
    return {"items": items, "count": len(items)}


async def bulk_suggest(product_ids: list[str]) -> dict[str, Any]:
    """Run suggest_product_angles for each product with pacing + per-product isolation.

    Returns {results: [{product_id, ok, suggestions?, existing_count?, error?}], ...}.
    Writes nothing. Raises AICopyProviderNotConfigured (fail fast) when the lane is
    unconfigured — no point looping N times on a config error.
    """
    ids = [pid for pid in (product_ids or []) if isinstance(pid, str) and pid.strip()]
    ids = ids[:_MAX_BATCH]

    results: list[dict[str, Any]] = []
    for index, pid in enumerate(ids):
        if index:
            await asyncio.sleep(_PACE_SECONDS)
        try:
            res = await suggest_product_angles(pid)
            results.append({"product_id": pid, "ok": True, **res})
        except provider.AICopyProviderNotConfigured:
            raise  # config error — fail fast, do not loop
        except provider.AICopyProviderError:
            # One retry on a transient provider error, then record + continue.
            await asyncio.sleep(_RETRY_SECONDS)
            try:
                res = await suggest_product_angles(pid)
                results.append({"product_id": pid, "ok": True, **res})
            except provider.AICopyProviderNotConfigured:
                raise
            except Exception as retry_error:  # noqa: BLE001
                results.append(
                    {
                        "product_id": pid,
                        "ok": False,
                        "error": getattr(retry_error, "code", str(retry_error)),
                    }
                )
        except ValueError as error:
            results.append({"product_id": pid, "ok": False, "error": str(error)})

    ok = [r for r in results if r.get("ok")]
    return {
        "results": results,
        "products": len(results),
        "ok_products": len(ok),
        "total_suggestions": sum(len(r.get("suggestions") or []) for r in ok),
    }
