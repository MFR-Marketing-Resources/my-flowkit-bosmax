"""Avatar registry metadata-only update (usage_tags).

Proves update_avatar changes ONLY the whitelisted non-identity metadata while the
AvatarCode and every identity descriptor stay frozen. The real fail-closed write
door (sync_pool_csv) is captured, not executed, so the committed data/ bridge is
never touched.
"""
import csv as _csv
import io

import pytest

from agent.services import avatar_registry

_HEADER = [
    "CharacterName", "Variant", "AvatarCode", "SkinTone", "HairStyle", "Wardrobe",
    "Environment", "Lighting", "Camera", "Expression", "SafetyBlock", "PromptV1",
    "approved_flag", "usage_tags", "AgeBand",
]


def _row(code: str, usage: str = "office") -> dict:
    base = {column: "" for column in _HEADER}
    base.update({
        "CharacterName": "Alya", "AvatarCode": code, "SkinTone": "Light-medium",
        "HairStyle": "Medium tidy", "Wardrobe": "Smart office wear",
        "Expression": "Calm neutral", "usage_tags": usage,
        "AgeBand": "Adult (30-54)", "approved_flag": "1",
    })
    return base


def _write_pool(tmp_path, rows) -> object:
    path = tmp_path / "pool.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _isolate(monkeypatch, tmp_path, rows) -> dict:
    captured: dict = {}
    pool = _write_pool(tmp_path, rows)
    monkeypatch.setattr(avatar_registry, "_active_pool_file", lambda: pool)
    monkeypatch.setattr(avatar_registry, "validate_usage_tags", lambda raw: None)

    def fake_sync(csv_bytes: bytes) -> dict:
        captured["csv"] = csv_bytes.decode("utf-8")
        return {"rows": 1, "approved_loaded": 1, "bridge_path": "x"}

    monkeypatch.setattr(avatar_registry, "sync_pool_csv", fake_sync)
    return captured


def test_update_avatar_changes_usage_tags_only(tmp_path, monkeypatch):
    captured = _isolate(monkeypatch, tmp_path, [_row("BOS_F_ALYA_01", "office")])

    result = avatar_registry.update_avatar("BOS_F_ALYA_01", {"usage_tags": "event|desk"})

    assert result["updated"] == "BOS_F_ALYA_01"
    written = list(_csv.DictReader(io.StringIO(captured["csv"])))
    assert len(written) == 1
    assert written[0]["usage_tags"] == "event|desk"         # metadata changed
    assert written[0]["SkinTone"] == "Light-medium"          # identity frozen
    assert written[0]["HairStyle"] == "Medium tidy"          # identity frozen
    assert written[0]["AvatarCode"] == "BOS_F_ALYA_01"       # code frozen


def test_update_avatar_not_found(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path, [_row("BOS_F_ALYA_01")])
    with pytest.raises(ValueError, match="AVATAR_CODE_NOT_FOUND"):
        avatar_registry.update_avatar("BOS_F_NOPE_99", {"usage_tags": "x"})


def test_update_avatar_ignores_identity_fields(tmp_path, monkeypatch):
    """A non-whitelisted (identity) field is not editable -> no-op guard fires."""
    _isolate(monkeypatch, tmp_path, [_row("BOS_F_ALYA_01", "office")])
    with pytest.raises(ValueError, match="AVATAR_NO_EDITABLE_FIELDS"):
        avatar_registry.update_avatar("BOS_F_ALYA_01", {"SkinTone": "Dark deep"})
