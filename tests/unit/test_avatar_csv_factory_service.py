"""Avatar Registry CSV Factory — seed-schema validation, staging, review,
export and safe bridge sync (fail-closed at every gate)."""
from __future__ import annotations

import csv
import io

import pytest

from agent.services import avatar_csv_factory_service as factory
from agent.services import avatar_registry

SEED_HEADER = factory.SEED_SCHEMA


def _row(**overrides) -> dict[str, str]:
    base = {
        "CharacterName": "Aisyah",
        "Variant": "Office 01",
        "AvatarCode": "BOS_F_OFFICE_01",
        "SkinTone": "Medium tan",
        "HairStyle": "Neat shoulder-length hair",
        "Wardrobe": "Modest office blouse",
        "Environment": "Bright office desk",
        "Lighting": "Soft daylight",
        "Camera": "Waist-up",
        "Expression": "Warm natural smile",
        "SafetyBlock": "STANDARD_SAFETY_BLOCK",
        "PromptV1": "A warm office presenter at a bright desk, natural smile.",
        "approved_flag": "TRUE",
        "usage_tags": "UGC|desk|office",
    }
    base.update(overrides)
    return base


def _csv_bytes(rows: list[dict[str, str]], header: list[str] | None = None) -> bytes:
    header = header or SEED_HEADER
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in header})
    return out.getvalue().encode("utf-8")


@pytest.fixture()
def factory_env(tmp_path, monkeypatch):
    """Isolated staging dir + isolated avatar pool (seed with one avatar)."""
    pool_file = tmp_path / "authority" / "AVATAR_POOL_NORMALIZED.csv"
    pool_file.parent.mkdir(parents=True)
    pool_file.write_bytes(_csv_bytes([_row(
        CharacterName="Existing",
        Variant="Seed 01",
        AvatarCode="BOS_F_EXIST_01",
    )]))
    bridge_file = tmp_path / "data" / "avatar_registry" / "AVATAR_POOL_NORMALIZED.csv"
    monkeypatch.setattr(avatar_registry, "_POOL_FILE", pool_file)
    monkeypatch.setattr(avatar_registry, "_BRIDGE_FILE", bridge_file)
    monkeypatch.setattr(factory, "_FACTORY_DIR", tmp_path / "staging")
    avatar_registry._load_pool.cache_clear()
    yield tmp_path
    avatar_registry._load_pool.cache_clear()


# ── validation ──────────────────────────────────────────────────────────────

def test_valid_csv_passes_and_normalizes_tags(factory_env):
    report, rows = factory.validate_seed_csv(
        _csv_bytes([_row(usage_tags="UGC, desk , ugc|Office")]))
    assert report["status"] == "PASS"
    assert report["row_count"] == 1
    assert rows[0]["valid"] is True
    assert rows[0]["data"]["usage_tags"] == "UGC|desk|Office"
    assert report["summary"]["usage_tags_normalized_rows"] == 1


def test_header_order_mismatch_fails_and_stages_nothing(factory_env):
    header = list(SEED_HEADER)
    header[0], header[1] = header[1], header[0]
    report, rows = factory.validate_seed_csv(_csv_bytes([_row()], header=header))
    assert report["status"] == "FAIL"
    assert rows == []
    assert any(e["code"] == "SEED_SCHEMA_MISMATCH" for e in report["errors"])
    result = factory.import_seed_csv(_csv_bytes([_row()], header=header))
    assert result["staged"] is False
    assert result["batch"] is None


def test_bridge_helper_columns_rejected(factory_env):
    header = SEED_HEADER + ["Avatar_Wiring_Status"]
    report, rows = factory.validate_seed_csv(
        _csv_bytes([_row()], header=header))
    assert report["status"] == "FAIL"
    assert rows == []
    assert any(e["code"] == "BRIDGE_HELPER_COLUMNS_NOT_ALLOWED" for e in report["errors"])
    assert report["summary"]["bridge_helper_columns"] == ["Avatar_Wiring_Status"]


def test_duplicate_avatar_code_detected(factory_env):
    report, rows = factory.validate_seed_csv(_csv_bytes([
        _row(),
        _row(Variant="Office 02", AvatarCode="BOS_F_OFFICE_01"),
    ]))
    assert report["status"] == "FAIL"
    assert report["summary"]["duplicate_avatar_codes"] == 1
    assert rows[1]["valid"] is False
    assert "DUPLICATE_AVATARCODE" in rows[1]["errors"]


def test_duplicate_character_variant_detected_case_insensitive(factory_env):
    report, _rows = factory.validate_seed_csv(_csv_bytes([
        _row(),
        _row(CharacterName="AISYAH", Variant="office 01",
             AvatarCode="BOS_F_OFFICE_02"),
    ]))
    assert report["summary"]["duplicate_character_variant_pairs"] == 1


@pytest.mark.parametrize("bad_code", [
    "BOS_X_OFFICE_01",      # gender token invalid
    "BOS_F_office_01",      # lowercase
    "BOS_F_OFFICE_1",       # <2 trailing digits
    "bos_f_office_01",
    "OFFICE_01",
])
def test_invalid_avatar_code_format(factory_env, bad_code):
    report, rows = factory.validate_seed_csv(_csv_bytes([_row(AvatarCode=bad_code)]))
    assert report["summary"]["invalid_avatar_code_rows"] == 1
    assert "AVATARCODE_FORMAT_INVALID" in rows[0]["errors"]


@pytest.mark.parametrize("prompt,leak_codes", [
    ("Presenter at desk. Code: BOSF01", ["PROMPTV1_METADATA_LEAK_CODE_LABEL"]),
    ("Presenter BOS_F_OFFICE_01 at desk", ["PROMPTV1_METADATA_LEAK_AVATARCODE"]),
    ("Presenter BOS_M_DESK_02 code: x", [
        "PROMPTV1_METADATA_LEAK_CODE_LABEL",
        "PROMPTV1_METADATA_LEAK_AVATARCODE",
    ]),
])
def test_promptv1_metadata_leak_blocked(factory_env, prompt, leak_codes):
    report, rows = factory.validate_seed_csv(_csv_bytes([_row(PromptV1=prompt)]))
    assert report["status"] == "FAIL"
    assert report["summary"]["promptv1_metadata_leak_rows"] == 1
    for code in leak_codes:
        assert code in rows[0]["errors"]


@pytest.mark.parametrize("flag", ["", "true", "True", "YES", "1", "approved"])
def test_approved_flag_must_be_explicit_true_or_false(factory_env, flag):
    report, rows = factory.validate_seed_csv(_csv_bytes([_row(approved_flag=flag)]))
    assert report["summary"]["approved_flag_invalid_rows"] == 1
    assert "APPROVED_FLAG_INVALID" in rows[0]["errors"]


def test_approved_flag_false_is_valid(factory_env):
    report, rows = factory.validate_seed_csv(_csv_bytes([_row(approved_flag="FALSE")]))
    assert report["status"] == "PASS"
    assert rows[0]["valid"] is True


def test_code_already_in_runtime_pool_is_an_error(factory_env):
    report, rows = factory.validate_seed_csv(
        _csv_bytes([_row(AvatarCode="BOS_F_EXIST_01")]))
    assert report["summary"]["existing_pool_duplicate_rows"] == 1
    assert "AVATARCODE_ALREADY_IN_POOL" in rows[0]["errors"]


def test_empty_csv_fails(factory_env):
    report, rows = factory.validate_seed_csv(_csv_bytes([]))
    assert report["status"] == "FAIL"
    assert any(e["code"] == "CSV_EMPTY" for e in report["errors"])
    assert rows == []


# ── staging / review ────────────────────────────────────────────────────────

def test_import_stages_batch_with_row_level_errors(factory_env):
    result = factory.import_seed_csv(_csv_bytes([
        _row(),
        _row(CharacterName="Bad", Variant="X 01", AvatarCode="not-a-code"),
    ]), source_filename="candidates.csv")
    assert result["staged"] is True
    batch = result["batch"]
    assert batch["row_count"] == 2
    assert batch["valid_rows"] == 1
    assert batch["pending_rows"] == 2
    listed = factory.list_batches()
    assert [b["batch_id"] for b in listed] == [batch["batch_id"]]


def test_review_cannot_approve_invalid_row(factory_env):
    result = factory.import_seed_csv(_csv_bytes([
        _row(AvatarCode="not-a-code"),
    ]))
    batch_id = result["batch"]["batch_id"]
    with pytest.raises(ValueError, match="CANNOT_APPROVE_INVALID_ROW"):
        factory.review_rows(batch_id, [{"row_index": 2, "decision": "APPROVE"}])
    # rejecting the invalid row is allowed
    summary = factory.review_rows(batch_id, [{"row_index": 2, "decision": "REJECT"}])
    assert summary["rejected_rows"] == 1


def test_review_unknown_row_or_decision_fails(factory_env):
    batch_id = factory.import_seed_csv(_csv_bytes([_row()]))["batch"]["batch_id"]
    with pytest.raises(ValueError, match="ROW_NOT_FOUND"):
        factory.review_rows(batch_id, [{"row_index": 99, "decision": "APPROVE"}])
    with pytest.raises(ValueError, match="DECISION_INVALID"):
        factory.review_rows(batch_id, [{"row_index": 2, "decision": "MAYBE"}])


# ── export / sync ───────────────────────────────────────────────────────────

def test_export_contains_only_approved_rows(factory_env):
    result = factory.import_seed_csv(_csv_bytes([
        _row(),
        _row(CharacterName="Zul", Variant="Desk 01",
             AvatarCode="BOS_M_DESK_01"),
    ]))
    batch_id = result["batch"]["batch_id"]
    with pytest.raises(ValueError, match="NO_APPROVED_ROWS"):
        factory.export_approved_csv(batch_id)
    factory.review_rows(batch_id, [
        {"row_index": 2, "decision": "APPROVE"},
        {"row_index": 3, "decision": "REJECT"},
    ])
    text = factory.export_approved_csv(batch_id)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert list(csv.DictReader(io.StringIO(text)).fieldnames) == SEED_HEADER
    assert len(parsed) == 1
    assert parsed[0]["AvatarCode"] == "BOS_F_OFFICE_01"


def test_sync_appends_approved_rows_and_preserves_pool(factory_env):
    batch_id = factory.import_seed_csv(_csv_bytes([_row()]))["batch"]["batch_id"]
    factory.review_rows(batch_id, [{"row_index": 2, "decision": "APPROVE"}])
    result = factory.sync_approved_to_bridge(batch_id)
    assert result["synced_rows"] == 1
    assert result["pool_rows_before"] == 1
    assert result["pool_rows_after"] == 2
    # bridge now active and contains BOTH the pre-existing seed row and the new one
    assert avatar_registry._BRIDGE_FILE.exists()
    with open(avatar_registry._BRIDGE_FILE, encoding="utf-8-sig", newline="") as f:
        codes = [r["AvatarCode"] for r in csv.DictReader(f)]
    assert codes == ["BOS_F_EXIST_01", "BOS_F_OFFICE_01"]
    # batch is now immutable
    detail = factory.get_batch(batch_id)
    assert detail["status"] == "SYNCED"
    with pytest.raises(ValueError, match="ALREADY_SYNCED"):
        factory.sync_approved_to_bridge(batch_id)
    with pytest.raises(ValueError, match="ALREADY_SYNCED"):
        factory.review_rows(batch_id, [{"row_index": 2, "decision": "REJECT"}])


def test_sync_without_approved_rows_fails(factory_env):
    batch_id = factory.import_seed_csv(_csv_bytes([_row()]))["batch"]["batch_id"]
    with pytest.raises(ValueError, match="NO_APPROVED_ROWS"):
        factory.sync_approved_to_bridge(batch_id)


def test_sync_fail_closed_on_pool_code_collision(factory_env):
    """A code that lands in the pool AFTER staging must still be blocked."""
    batch_id = factory.import_seed_csv(_csv_bytes([_row()]))["batch"]["batch_id"]
    factory.review_rows(batch_id, [{"row_index": 2, "decision": "APPROVE"}])
    # simulate the same code arriving in the pool after staging
    pool_file = avatar_registry._active_pool_file()
    pool_file.write_bytes(_csv_bytes([
        _row(CharacterName="Existing", Variant="Seed 01",
             AvatarCode="BOS_F_EXIST_01"),
        _row(),
    ]))
    with pytest.raises(ValueError, match="POOL_CODE_COLLISION"):
        factory.sync_approved_to_bridge(batch_id)


def test_get_batch_unknown_id(factory_env):
    with pytest.raises(KeyError):
        factory.get_batch("acf_000000000000")
    with pytest.raises(ValueError, match="BATCH_ID_INVALID"):
        factory.get_batch("../../etc/passwd")
