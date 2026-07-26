"""Authority CSV contract — AgeBand column, 15-col schema, minor safety."""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / "agent/authority/AVATAR_POOL_NORMALIZED.csv"

EXPECTED_HEADER = [
    "CharacterName",
    "Variant",
    "AvatarCode",
    "SkinTone",
    "HairStyle",
    "Wardrobe",
    "Environment",
    "Lighting",
    "Camera",
    "Expression",
    "SafetyBlock",
    "PromptV1",
    "approved_flag",
    "usage_tags",
    "AgeBand",
]

VALID_AGE_BANDS = {
    "Child (6-12)",
    "Teen (13-17)",
    "Young adult (18-29)",
    "Adult (30-54)",
    "Older adult (55-69)",
    "Senior (70+)",
}

CODE_RE = re.compile(r"^BOS_([FM])_([A-Z0-9]+)_\d{2,}$")


def _rows():
    with POOL.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        body = list(reader)
    return header, body


def test_avatar_pool_header_order_and_width():
    header, body = _rows()
    assert header == EXPECTED_HEADER
    assert all(len(row) == 15 for row in body), "every data row must have 15 columns"
    assert len(body) >= 1


def test_avatar_pool_codes_unique_and_gender_prefix():
    header, body = _rows()
    code_i = header.index("AvatarCode")
    codes = [row[code_i] for row in body]
    assert len(codes) == len(set(codes)), "duplicate AvatarCode in authority CSV"
    for code in codes:
        m = CODE_RE.match(code)
        assert m, f"malformed AvatarCode: {code}"


def test_avatar_pool_age_band_valid_and_mostly_adult_backfill():
    header, body = _rows()
    age_i = header.index("AgeBand")
    ages = [row[age_i].strip() for row in body]
    assert all(a in VALID_AGE_BANDS for a in ages)
    # Legacy backfill defaults to Adult for historical rows; Child/Teen may exist
    # for explicit operator profiles but automatic lanes must exclude them.
    assert ages.count("Adult (30-54)") >= 1


def test_crosswalk_excludes_child_teen_codes_when_resolvable():
    """Automatic crosswalk must not map Child/Teen codes (by pool AgeBand)."""
    import json

    header, body = _rows()
    code_i = header.index("AvatarCode")
    age_i = header.index("AgeBand")
    age_by_code = {row[code_i]: row[age_i] for row in body}

    cw_path = ROOT / "agent/authority/creative_avatar_cluster_crosswalk.json"
    if not cw_path.exists():
        # Alternate path used by some checkouts.
        candidates = list((ROOT / "agent").rglob("*crosswalk*.json"))
        assert candidates, "crosswalk json missing"
        cw_path = candidates[0]
    data = json.loads(cw_path.read_text(encoding="utf-8"))
    cross = data.get("crosswalk") or data
    minors = []
    for cluster, rows in cross.items():
        for row in rows:
            code = str(row.get("avatar_code") or "")
            age = age_by_code.get(code)
            if age in {"Child (6-12)", "Teen (13-17)"}:
                minors.append((cluster, code, age))
    assert minors == [], f"Child/Teen in automatic crosswalk: {minors[:5]}"
