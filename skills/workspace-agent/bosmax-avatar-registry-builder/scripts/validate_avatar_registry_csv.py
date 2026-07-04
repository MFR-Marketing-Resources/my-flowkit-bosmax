\
#!/usr/bin/env python3
"""Validate and normalize BOSMAX Avatar Registry seed-schema CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

SEED_SCHEMA = [
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
]

BRIDGE_HELPER_COLUMNS = {
    "Name",
    "Avatar Poster Upload",
    "AvatarCode_Generated",
    "AvatarCode_Mismatch",
    "Avatar_Generation_Source",
    "Avatar_Last_Generated_At",
    "Avatar_Wiring_Status",
    "PromptV1_Generated",
    "PromptV1_Mismatch",
}

AVATAR_CODE_RE = re.compile(r"^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$")
PROMPT_CODE_LABEL_RE = re.compile(r"\bCode\s*:", re.IGNORECASE)
PROMPT_AVATAR_CODE_RE = re.compile(r"\bBOS_[FM]_[A-Z0-9_]+\b")
SENSITIVE_TOKENS = {
    "HEALTH_AND_WELLNESS",
    "FEMALE_HEALTH_SENSITIVE",
    "MALE_HEALTH_SENSITIVE",
    "UNKNOWN_REVIEW_REQUIRED",
    "cure",
    "treat",
    "medical",
    "clinical",
    "before-after",
    "virility",
    "intimate",
}


def _base_report(input_file: str, mode: str) -> dict[str, Any]:
    return {
        "status": "PASS",
        "input_file": input_file,
        "mode": mode,
        "row_count": 0,
        "errors": [],
        "warnings": [],
        "normalized_output_file": None,
        "summary": {
            "duplicate_avatar_codes": 0,
            "duplicate_character_variant_pairs": 0,
            "invalid_avatar_code_rows": 0,
            "promptv1_metadata_leak_rows": 0,
            "approved_flag_invalid_rows": 0,
            "bridge_helper_column_rows": 0,
            "usage_tags_normalized_rows": 0,
        },
    }


def _error(report: dict[str, Any], code: str, message: str, row: int | None = None) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if row is not None:
        item["row"] = row
    report["errors"].append(item)


def _warning(report: dict[str, Any], code: str, message: str, row: int | None = None) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if row is not None:
        item["row"] = row
    report["warnings"].append(item)


def _split_tags(value: str) -> list[str]:
    raw = value or ""
    parts = re.split(r"[|,]", raw)
    return [p.strip() for p in parts if p.strip()]


def _normalize_tags(value: str) -> str:
    seen: set[str] = set()
    tags: list[str] = []
    for tag in _split_tags(value):
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return "|".join(tags)


def validate_csv(path: Path, mode: str) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    report = _base_report(str(path), mode)
    if not path.is_file():
        _error(report, "INPUT_FILE_NOT_FOUND", f"File not found: {path}")
        report["status"] = "FAIL"
        return report, [], []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    report["row_count"] = len(rows)

    helper_columns = sorted(set(fieldnames) & BRIDGE_HELPER_COLUMNS)
    if helper_columns:
        report["summary"]["bridge_helper_column_rows"] = len(rows)
        _error(
            report,
            "BRIDGE_HELPER_COLUMNS_NOT_ALLOWED",
            "Bridge/helper/generated columns are not allowed in V1 seed-schema CSV: " + ", ".join(helper_columns),
        )

    if fieldnames != SEED_SCHEMA:
        _error(
            report,
            "SEED_SCHEMA_MISMATCH",
            "CSV header must exactly match the seed schema and order.",
        )

    code_seen: dict[str, int] = {}
    pair_seen: dict[tuple[str, str], int] = {}
    normalized_rows: list[dict[str, str]] = []

    for idx, row in enumerate(rows, start=2):
        cleaned = {col: str(row.get(col) or "").strip() for col in SEED_SCHEMA}
        normalized_rows.append(cleaned)

        code = cleaned["AvatarCode"]
        if code in code_seen:
            report["summary"]["duplicate_avatar_codes"] += 1
            _error(report, "DUPLICATE_AVATARCODE", f"Duplicate AvatarCode also seen on row {code_seen[code]}", idx)
        else:
            code_seen[code] = idx

        if not AVATAR_CODE_RE.match(code):
            report["summary"]["invalid_avatar_code_rows"] += 1
            _error(report, "AVATARCODE_FORMAT_INVALID", f"Invalid AvatarCode: {code}", idx)

        pair = (cleaned["CharacterName"].casefold(), cleaned["Variant"].casefold())
        if pair in pair_seen:
            report["summary"]["duplicate_character_variant_pairs"] += 1
            _error(report, "DUPLICATE_CHARACTER_VARIANT", f"Duplicate CharacterName + Variant also seen on row {pair_seen[pair]}", idx)
        else:
            pair_seen[pair] = idx

        approved = cleaned["approved_flag"]
        if approved not in {"TRUE", "FALSE"}:
            report["summary"]["approved_flag_invalid_rows"] += 1
            _error(report, "APPROVED_FLAG_INVALID", "approved_flag must be exactly TRUE or FALSE", idx)

        prompt = cleaned["PromptV1"]
        leak_found = False
        if PROMPT_CODE_LABEL_RE.search(prompt):
            leak_found = True
            _error(report, "PROMPTV1_METADATA_LEAK_CODE_LABEL", "PromptV1 contains Code: metadata label", idx)
        if PROMPT_AVATAR_CODE_RE.search(prompt):
            leak_found = True
            _error(report, "PROMPTV1_METADATA_LEAK_AVATARCODE_PATTERN", "PromptV1 contains BOS_F_ or BOS_M_ avatar code pattern", idx)
        if leak_found:
            report["summary"]["promptv1_metadata_leak_rows"] += 1

        tags = cleaned["usage_tags"]
        normalized_tags = _normalize_tags(tags)
        if not normalized_tags:
            _warning(report, "USAGE_TAGS_EMPTY", "usage_tags should not be empty", idx)
        elif normalized_tags != tags:
            report["summary"]["usage_tags_normalized_rows"] += 1
            cleaned["usage_tags"] = normalized_tags

        combined = " ".join(cleaned.values())
        if any(token.lower() in combined.lower() for token in SENSITIVE_TOKENS):
            _warning(report, "SENSITIVE_GROUP_AUTO_PLAN_VIOLATION", "Sensitive/review token found; manual review required", idx)

    if report["errors"]:
        report["status"] = "FAIL"
    elif report["warnings"]:
        report["status"] = "PASS_WITH_WARNINGS"
    else:
        report["status"] = "PASS"

    return report, normalized_rows, fieldnames


def write_report(report: dict[str, Any], path: Path | None) -> None:
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if path:
        path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def write_normalized(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SEED_SCHEMA)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in SEED_SCHEMA})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate BOSMAX Avatar Registry seed-schema CSV files.")
    sub = parser.add_subparsers(dest="mode", required=True)

    validate_only = sub.add_parser("validate-only", help="Validate a CSV and print a JSON report.")
    validate_only.add_argument("input", type=Path)
    validate_only.add_argument("--report", type=Path, default=None, help="Optional path for JSON validation report.")

    normalize = sub.add_parser("normalize-output", help="Validate and write a normalized seed-schema CSV if valid.")
    normalize.add_argument("input", type=Path)
    normalize.add_argument("--output", type=Path, default=None, help="Normalized CSV output path.")
    normalize.add_argument("--report", type=Path, default=None, help="Optional path for JSON validation report.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report, rows, _fieldnames = validate_csv(args.input, args.mode)

    if args.mode == "normalize-output" and report["status"] != "FAIL":
        output = args.output or args.input.with_suffix(".normalized.seed.csv")
        write_normalized(rows, output)
        report["normalized_output_file"] = str(output)

    write_report(report, getattr(args, "report", None))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
