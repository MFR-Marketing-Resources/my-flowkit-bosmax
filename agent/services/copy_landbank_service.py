"""Copywriting landbank — operator-uploaded COPY_MASTER rows (ADR-008).

The landbank is a SECONDARY reference for the canonical compiler: it keeps the
system from going mute on copywriting, it never overrides an explicit operator
copy_intelligence payload, and a missing landbank never fails a compile. It
grows over time (products, angles, hooks, subhooks, USPs, CTAs).

Storage: data/copywriting_landbank/{product_id}.csv in the retained COPY_MASTER
column shape (see agent/authority/COPYWRITING_FRAMEWORK_UNIVERSAL.yaml →
output_mapping_to_copy_master). Only rows with status=approved are served.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

_LANDBANK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "copywriting_landbank"

REQUIRED_COLUMNS = {"product_id", "angle", "hook", "cta"}
KNOWN_COLUMNS = (
    "copy_id", "product", "product_id", "angle_id", "angle", "hook_id", "hook",
    "subhook", "usp1", "usp2", "usp3", "cta", "status", "notes", "language",
    "usage_tags", "formula_family",
)


def _safe_product_id(product_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(product_id or "").strip())
    if not cleaned:
        raise ValueError("PRODUCT_ID_REQUIRED")
    return cleaned


def save_csv(product_id: str, csv_bytes: bytes) -> dict:
    """Validate + store an uploaded COPY_MASTER csv for a product. Fail-closed
    on missing required columns; never silently accept a broken bank."""
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    columns = {c.strip().lower() for c in (reader.fieldnames or [])}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise ValueError(f"LANDBANK_COLUMNS_MISSING:{sorted(missing)}")
    rows = list(reader)
    if not rows:
        raise ValueError("LANDBANK_EMPTY")
    _LANDBANK_DIR.mkdir(parents=True, exist_ok=True)
    path = _LANDBANK_DIR / f"{_safe_product_id(product_id)}.csv"
    path.write_text(text, encoding="utf-8")
    approved = sum(1 for r in rows if str(r.get("status", "approved")).strip().lower() in ("approved", ""))
    return {"product_id": product_id, "rows": len(rows), "approved_rows": approved,
            "path": str(path)}


def lookup(product_id: str, *, angle: str | None = None) -> dict | None:
    """Return normalized copy-intelligence fields for a product, or None.
    Deterministic: first approved row (optionally filtered by angle)."""
    if not str(product_id or "").strip():
        return None
    try:
        path = _LANDBANK_DIR / f"{_safe_product_id(product_id)}.csv"
    except ValueError:
        return None
    if not path.exists():
        return None
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [
            {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            for row in csv.DictReader(f)
        ]
    rows = [r for r in rows if str(r.get("status", "approved")).lower() in ("approved", "")]
    if angle:
        wanted = str(angle).strip().lower()
        filtered = [r for r in rows if wanted in r.get("angle", "").lower()]
        rows = filtered or rows
    if not rows:
        return None
    row = rows[0]
    return {
        "angle": row.get("angle", ""),
        "hook": row.get("hook", ""),
        "subhook": row.get("subhook", ""),
        "usps": [u for u in (row.get("usp1"), row.get("usp2"), row.get("usp3")) if u],
        "cta": row.get("cta", ""),
        "formula_family": row.get("formula_family", "") or "HSO",
        "copy_id": row.get("copy_id", ""),
        "language": row.get("language", ""),
    }


def list_products() -> list[dict]:
    """Landbank inventory for the dashboard."""
    if not _LANDBANK_DIR.exists():
        return []
    items = []
    for path in sorted(_LANDBANK_DIR.glob("*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            count = sum(1 for _ in csv.DictReader(f))
        items.append({"product_id": path.stem, "rows": count})
    return items
