"""Copy Usage service — usage/fatigue tracking for Copy Sets.

Tracks how many times each approved Copy Set has been used in a final
prompt generation, which modes it was used in, and when it was last
used.  Also provides per-product usage statistics and fatigue warnings
so the Copywriting Intelligence Hub can surface actionable risk.

Phase 1 foundation — the increment functions are callable but NOT yet
wired into the compiler / workspace package generation path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.db import crud


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _unique_append(existing: str, mode: str) -> str:
    """Add ``mode`` to a JSON array string without duplicates."""
    try:
        modes: list[str] = json.loads(existing)
    except (TypeError, json.JSONDecodeError):
        modes = []
    cleaned = _clean(mode).upper()
    if cleaned and cleaned not in (m.upper() for m in modes):
        modes.append(cleaned)
    return json.dumps(modes)


async def increment_copy_usage(
    copy_set_id: str,
    mode: str,
) -> dict[str, Any]:
    """Record one usage event for a Copy Set.

    Increments ``usage_count``, sets ``last_used_at`` to now, and
    appends ``mode`` to ``used_in_modes`` (deduplicated).
    """
    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise ValueError(f"COPY_SET_NOT_FOUND:{copy_set_id}")
    current_count = row.get("usage_count") or 0
    current_modes = row.get("used_in_modes") or "[]"
    updated_modes = _unique_append(current_modes, mode)
    return await crud.update_copy_set(
        copy_set_id,
        usage_count=current_count + 1,
        last_used_at=_now(),
        used_in_modes=updated_modes,
    )


# Fatigue thresholds (configurable constants for Phase 1).
FATIGUE_WARN_THRESHOLD = 5     # warn when usage_count >= this
FATIGUE_HIGH_THRESHOLD = 10    # stronger warning above this


async def get_product_copy_usage_stats(
    product_id: str,
) -> dict[str, Any]:
    """Return per-product copy usage statistics.

    Includes:
    - total copy sets (all statuses)
    - approved count
    - per-copy-set usage data (hook preview, usage_count, last_used_at, modes)
    - fatigue warnings for over-used approved Copy Sets
    """
    all_rows = await crud.list_copy_sets_for_product(product_id)
    total = len(all_rows)
    approved = [r for r in all_rows if r.get("status") == "COPY_APPROVED"]
    approved_count = len(approved)

    usage_items: list[dict[str, Any]] = []
    fatigue_warnings: list[dict[str, Any]] = []

    for cs in approved:
        count = cs.get("usage_count") or 0
        hook = _clean(cs.get("hook"))
        item = {
            "copy_set_id": cs.get("copy_set_id"),
            "hook_preview": hook[:80] if hook else "",
            "usage_count": count,
            "last_used_at": cs.get("last_used_at"),
            "used_in_modes": _parse_json_list(cs.get("used_in_modes")),
        }
        usage_items.append(item)

        if count >= FATIGUE_HIGH_THRESHOLD:
            fatigue_warnings.append({
                "copy_set_id": cs.get("copy_set_id"),
                "hook_preview": hook[:80] if hook else "",
                "usage_count": count,
                "level": "HIGH_FATIGUE",
                "message": f"Copy Set used {count} times — strongly consider retiring or regenerating.",
            })
        elif count >= FATIGUE_WARN_THRESHOLD:
            fatigue_warnings.append({
                "copy_set_id": cs.get("copy_set_id"),
                "hook_preview": hook[:80] if hook else "",
                "usage_count": count,
                "level": "ELEVATED_USAGE",
                "message": f"Copy Set used {count} times — approaching fatigue threshold.",
            })

    return {
        "product_id": product_id,
        "total_copy_sets": total,
        "approved_count": approved_count,
        "usage_by_copy_set": sorted(usage_items, key=lambda x: -x["usage_count"]),
        "fatigue_warnings": fatigue_warnings,
        "thresholds": {
            "fatigue_warn": FATIGUE_WARN_THRESHOLD,
            "fatigue_high": FATIGUE_HIGH_THRESHOLD,
        },
    }


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []
