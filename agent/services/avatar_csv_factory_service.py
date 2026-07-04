"""Avatar Registry CSV Factory — runtime seed-schema intake, staging and sync.

Phase 2 of the BOSMAX Avatar Registry system (Phase 1 = PR #192, which
installed the Workspace Agent Skill source pack as inert reference material).
This module is the RUNTIME authority for taking Avatar Registry seed-schema
CSV candidates through: validate -> stage -> operator review (approve/reject
per row) -> export -> safe sync into the runtime bridge.

Law:
- The seed schema (14 exact columns, exact order) is mandatory on intake.
- PromptV1 must never leak internal metadata (`Code:`, `BOS_F_`, `BOS_M_`).
- approved_flag must be an explicit TRUE or FALSE (blank is NOT approved).
- usage_tags intake accepts comma or pipe; final output is pipe-delimited,
  de-duplicated case-insensitively.
- Bridge/helper/generated columns are rejected in seed upload mode.
- Candidate rows NEVER touch the runtime bridge directly. Sync merges only
  reviewed+approved rows into the active pool and re-enters through the
  existing fail-closed door (`avatar_registry.sync_pool_csv`).

Storage: data/avatar_registry/csv_factory/batches/<batch_id>.json — one JSON
document per staged batch (same file-based pattern as the bridge CSV itself;
the live Notion registry is not a runtime dependency).
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.services import avatar_registry

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

_FACTORY_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "avatar_registry" / "csv_factory" / "batches"
)

REVIEW_PENDING = "PENDING"
REVIEW_APPROVED = "APPROVED"
REVIEW_REJECTED = "REJECTED"

BATCH_REVIEW = "REVIEW"
BATCH_SYNCED = "SYNCED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _base_report() -> dict[str, Any]:
    return {
        "status": "PASS",
        "row_count": 0,
        "errors": [],
        "warnings": [],
        "summary": {
            "duplicate_avatar_codes": 0,
            "duplicate_character_variant_pairs": 0,
            "invalid_avatar_code_rows": 0,
            "promptv1_metadata_leak_rows": 0,
            "approved_flag_invalid_rows": 0,
            "existing_pool_duplicate_rows": 0,
            "usage_tags_normalized_rows": 0,
            "bridge_helper_columns": [],
        },
    }


def _split_tags(value: str) -> list[str]:
    parts = re.split(r"[|,]", value or "")
    return [p.strip() for p in parts if p.strip()]


def normalize_usage_tags(value: str) -> str:
    """Comma/pipe intake -> pipe-delimited output, case-insensitive de-dupe."""
    seen: set[str] = set()
    tags: list[str] = []
    for tag in _split_tags(value):
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return "|".join(tags)


def _existing_pool_codes() -> set[str]:
    pool_file = avatar_registry._active_pool_file()
    if not pool_file.exists():
        return set()
    with open(pool_file, encoding="utf-8-sig", newline="") as f:
        return {
            str(row.get("AvatarCode") or "").strip()
            for row in csv.DictReader(f)
            if str(row.get("AvatarCode") or "").strip()
        }


def validate_seed_csv(csv_bytes: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate a seed-schema candidate CSV.

    Returns (report, rows) where rows carry the normalized data plus per-row
    error/warning codes so the staging layer can gate approval fail-closed.
    Header-level failures return an empty rows list (nothing stageable).
    """
    report = _base_report()

    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        report["errors"].append({
            "code": "CSV_NOT_UTF8",
            "message": "CSV must be UTF-8 encoded.",
        })
        report["status"] = "FAIL"
        return report, []

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])
    raw_rows = list(reader)
    report["row_count"] = len(raw_rows)

    helper_columns = sorted(set(fieldnames) & BRIDGE_HELPER_COLUMNS)
    if helper_columns:
        report["summary"]["bridge_helper_columns"] = helper_columns
        report["errors"].append({
            "code": "BRIDGE_HELPER_COLUMNS_NOT_ALLOWED",
            "message": (
                "Bridge/helper/generated columns are not allowed in seed "
                "upload mode: " + ", ".join(helper_columns)
            ),
        })

    if fieldnames != SEED_SCHEMA:
        report["errors"].append({
            "code": "SEED_SCHEMA_MISMATCH",
            "message": (
                "CSV header must exactly match the seed schema and order: "
                + ",".join(SEED_SCHEMA)
            ),
        })

    if report["errors"]:
        report["status"] = "FAIL"
        return report, []

    if not raw_rows:
        report["errors"].append({
            "code": "CSV_EMPTY",
            "message": "CSV contains no data rows.",
        })
        report["status"] = "FAIL"
        return report, []

    pool_codes = _existing_pool_codes()
    code_seen: dict[str, int] = {}
    pair_seen: dict[tuple[str, str], int] = {}
    rows: list[dict[str, Any]] = []

    for idx, raw in enumerate(raw_rows, start=2):
        data = {col: str(raw.get(col) or "").strip() for col in SEED_SCHEMA}
        row_errors: list[str] = []
        row_warnings: list[str] = []

        def _err(code: str, message: str) -> None:
            row_errors.append(code)
            report["errors"].append({"code": code, "message": message, "row": idx})

        def _warn(code: str, message: str) -> None:
            row_warnings.append(code)
            report["warnings"].append({"code": code, "message": message, "row": idx})

        code = data["AvatarCode"]
        if code in code_seen:
            report["summary"]["duplicate_avatar_codes"] += 1
            _err("DUPLICATE_AVATARCODE",
                 f"Duplicate AvatarCode {code!r} also on row {code_seen[code]}")
        else:
            code_seen[code] = idx

        if not AVATAR_CODE_RE.match(code):
            report["summary"]["invalid_avatar_code_rows"] += 1
            _err("AVATARCODE_FORMAT_INVALID", f"Invalid AvatarCode: {code!r}")
        elif code in pool_codes:
            report["summary"]["existing_pool_duplicate_rows"] += 1
            _err("AVATARCODE_ALREADY_IN_POOL",
                 f"AvatarCode {code!r} already exists in the runtime avatar pool")

        pair = (data["CharacterName"].casefold(), data["Variant"].casefold())
        if pair in pair_seen:
            report["summary"]["duplicate_character_variant_pairs"] += 1
            _err("DUPLICATE_CHARACTER_VARIANT",
                 f"Duplicate CharacterName + Variant also on row {pair_seen[pair]}")
        else:
            pair_seen[pair] = idx

        if data["approved_flag"] not in {"TRUE", "FALSE"}:
            report["summary"]["approved_flag_invalid_rows"] += 1
            _err("APPROVED_FLAG_INVALID",
                 "approved_flag must be exactly TRUE or FALSE (blank forbidden)")

        prompt = data["PromptV1"]
        leak = False
        if PROMPT_CODE_LABEL_RE.search(prompt):
            leak = True
            _err("PROMPTV1_METADATA_LEAK_CODE_LABEL",
                 "PromptV1 contains a 'Code:' metadata label")
        if PROMPT_AVATAR_CODE_RE.search(prompt):
            leak = True
            _err("PROMPTV1_METADATA_LEAK_AVATARCODE",
                 "PromptV1 contains a BOS_F_/BOS_M_ avatar code pattern")
        if leak:
            report["summary"]["promptv1_metadata_leak_rows"] += 1

        missing = [col for col in SEED_SCHEMA
                   if col not in ("approved_flag", "usage_tags") and not data[col]]
        if missing:
            _err("REQUIRED_FIELD_BLANK", "Blank required field(s): " + ", ".join(missing))

        normalized_tags = normalize_usage_tags(data["usage_tags"])
        if not normalized_tags:
            _warn("USAGE_TAGS_EMPTY", "usage_tags should not be empty")
        elif normalized_tags != data["usage_tags"]:
            report["summary"]["usage_tags_normalized_rows"] += 1
            data["usage_tags"] = normalized_tags

        rows.append({
            "row_index": idx,
            "data": data,
            "valid": not row_errors,
            "errors": row_errors,
            "warnings": row_warnings,
            "review_status": REVIEW_PENDING,
        })

    if report["errors"]:
        report["status"] = "FAIL"
    elif report["warnings"]:
        report["status"] = "PASS_WITH_WARNINGS"

    return report, rows


# ---------------------------------------------------------------------------
# Staging store
# ---------------------------------------------------------------------------

def _batch_path(batch_id: str) -> Path:
    if not re.fullmatch(r"acf_[0-9a-f]{12}", batch_id):
        raise ValueError(f"AVATAR_CSV_FACTORY_BATCH_ID_INVALID:{batch_id}")
    return _FACTORY_DIR / f"{batch_id}.json"


def _save_batch(batch: dict[str, Any]) -> None:
    path = _batch_path(batch["batch_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _load_batch(batch_id: str) -> dict[str, Any]:
    path = _batch_path(batch_id)
    if not path.is_file():
        raise KeyError(f"AVATAR_CSV_FACTORY_BATCH_NOT_FOUND:{batch_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _batch_summary(batch: dict[str, Any]) -> dict[str, Any]:
    rows = batch["rows"]
    return {
        "batch_id": batch["batch_id"],
        "created_at": batch["created_at"],
        "source_filename": batch.get("source_filename"),
        "status": batch["status"],
        "validation_status": batch["report"]["status"],
        "row_count": len(rows),
        "valid_rows": sum(1 for r in rows if r["valid"]),
        "pending_rows": sum(1 for r in rows if r["review_status"] == REVIEW_PENDING),
        "approved_rows": sum(1 for r in rows if r["review_status"] == REVIEW_APPROVED),
        "rejected_rows": sum(1 for r in rows if r["review_status"] == REVIEW_REJECTED),
    }


def import_seed_csv(csv_bytes: bytes, source_filename: str | None = None) -> dict[str, Any]:
    """Validate a candidate CSV and stage it for review.

    Header-level failures (schema mismatch, bridge columns, empty/undecodable
    file) stage NOTHING and return {"staged": False, "report": ...}. Row-level
    errors still stage — invalid rows are visible in review but can never be
    approved.
    """
    if not csv_bytes:
        raise ValueError("AVATAR_CSV_FACTORY_EMPTY_BODY")

    report, rows = validate_seed_csv(csv_bytes)
    if not rows:
        return {"staged": False, "report": report, "batch": None}

    batch = {
        "batch_id": "acf_" + uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": source_filename,
        "status": BATCH_REVIEW,
        "report": report,
        "rows": rows,
        "synced_at": None,
    }
    _save_batch(batch)
    return {"staged": True, "report": report, "batch": _batch_summary(batch)}


def list_batches() -> list[dict[str, Any]]:
    if not _FACTORY_DIR.is_dir():
        return []
    summaries = []
    for path in sorted(_FACTORY_DIR.glob("acf_*.json")):
        try:
            summaries.append(_batch_summary(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError):
            continue
    summaries.sort(key=lambda s: s["created_at"], reverse=True)
    return summaries


def get_batch(batch_id: str) -> dict[str, Any]:
    batch = _load_batch(batch_id)
    return {**batch, "summary": _batch_summary(batch)}


def review_rows(batch_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply operator approve/reject decisions to staged rows (fail-closed:
    an invalid row can never be approved; synced batches are immutable)."""
    batch = _load_batch(batch_id)
    if batch["status"] == BATCH_SYNCED:
        raise ValueError(f"AVATAR_CSV_FACTORY_BATCH_ALREADY_SYNCED:{batch_id}")

    rows_by_index = {r["row_index"]: r for r in batch["rows"]}
    for decision in decisions:
        row_index = decision.get("row_index")
        verdict = str(decision.get("decision") or "").strip().upper()
        row = rows_by_index.get(row_index)
        if row is None:
            raise ValueError(f"AVATAR_CSV_FACTORY_ROW_NOT_FOUND:{row_index}")
        if verdict not in ("APPROVE", "REJECT"):
            raise ValueError(f"AVATAR_CSV_FACTORY_DECISION_INVALID:{verdict}")
        if verdict == "APPROVE" and not row["valid"]:
            raise ValueError(
                f"AVATAR_CSV_FACTORY_CANNOT_APPROVE_INVALID_ROW:{row_index}:"
                + ",".join(row["errors"])
            )
        row["review_status"] = REVIEW_APPROVED if verdict == "APPROVE" else REVIEW_REJECTED

    _save_batch(batch)
    return _batch_summary(batch)


def _approved_rows(batch: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in batch["rows"]
            if r["review_status"] == REVIEW_APPROVED and r["valid"]]


def export_approved_csv(batch_id: str) -> str:
    """Seed-schema CSV text of the reviewed+approved rows of a batch."""
    batch = _load_batch(batch_id)
    approved = _approved_rows(batch)
    if not approved:
        raise ValueError(f"AVATAR_CSV_FACTORY_NO_APPROVED_ROWS:{batch_id}")
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=SEED_SCHEMA, lineterminator="\n")
    writer.writeheader()
    for row in approved:
        writer.writerow({col: row["data"].get(col, "") for col in SEED_SCHEMA})
    return out.getvalue()


def sync_approved_to_bridge(batch_id: str) -> dict[str, Any]:
    """Merge the batch's approved rows into the active pool and install the
    combined CSV through the existing fail-closed door
    (`avatar_registry.sync_pool_csv`). Existing pool rows are preserved
    verbatim; nothing is overwritten in place.
    """
    batch = _load_batch(batch_id)
    if batch["status"] == BATCH_SYNCED:
        raise ValueError(f"AVATAR_CSV_FACTORY_BATCH_ALREADY_SYNCED:{batch_id}")
    approved = _approved_rows(batch)
    if not approved:
        raise ValueError(f"AVATAR_CSV_FACTORY_NO_APPROVED_ROWS:{batch_id}")

    pool_file = avatar_registry._active_pool_file()
    existing_rows: list[dict[str, str]] = []
    if pool_file.exists():
        with open(pool_file, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = list(reader.fieldnames or [])
            if header != SEED_SCHEMA:
                raise ValueError(
                    "AVATAR_CSV_FACTORY_POOL_HEADER_UNSUPPORTED: active pool "
                    "header does not match the seed schema; refusing merge"
                )
            existing_rows = [
                {col: str(row.get(col) or "") for col in SEED_SCHEMA}
                for row in reader
            ]

    existing_codes = {r["AvatarCode"].strip() for r in existing_rows}
    collisions = [r["data"]["AvatarCode"] for r in approved
                  if r["data"]["AvatarCode"] in existing_codes]
    if collisions:
        raise ValueError(
            "AVATAR_CSV_FACTORY_POOL_CODE_COLLISION:" + ",".join(sorted(collisions))
        )

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=SEED_SCHEMA, lineterminator="\n")
    writer.writeheader()
    for row in existing_rows:
        writer.writerow(row)
    for row in approved:
        writer.writerow({col: row["data"].get(col, "") for col in SEED_SCHEMA})

    sync_result = avatar_registry.sync_pool_csv(out.getvalue().encode("utf-8"))

    batch["status"] = BATCH_SYNCED
    batch["synced_at"] = datetime.now(timezone.utc).isoformat()
    _save_batch(batch)

    return {
        "batch_id": batch_id,
        "synced_rows": len(approved),
        "pool_rows_before": len(existing_rows),
        "pool_rows_after": len(existing_rows) + len(approved),
        "sync_result": sync_result,
    }
