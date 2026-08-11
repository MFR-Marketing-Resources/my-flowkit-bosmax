"""Scene context registry metadata-only update (usage_tags).

Proves update_scene changes ONLY the whitelisted non-identity metadata while the
SceneCode and identity/prompt fields stay frozen. The real fail-closed write door
(sync_pool_csv) is captured, not executed, so the committed data/ bridge is never
touched.
"""
import csv as _csv
import io

import pytest

from agent.services import scene_context_registry

_HEADER = [
    "SceneName", "SceneCode", "BackgroundPrompt", "RouteFit", "SafetyBlock",
    "PromptV1", "approved_flag", "usage_tags",
]


def _row(code: str, usage: str = "office") -> dict:
    base = {column: "" for column in _HEADER}
    base.update({
        "SceneName": "Modern Office", "SceneCode": code,
        "BackgroundPrompt": "Background: a clean modern office", "RouteFit": "T2V",
        "PromptV1": "Background: a clean modern office", "approved_flag": "1",
        "usage_tags": usage,
    })
    return base


def _isolate(monkeypatch, tmp_path, rows) -> dict:
    captured: dict = {}
    path = tmp_path / "scene_pool.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    monkeypatch.setattr(scene_context_registry, "_active_pool_file", lambda: path)

    def fake_sync(csv_bytes: bytes) -> dict:
        captured["csv"] = csv_bytes.decode("utf-8")
        return {"rows": 1, "approved_loaded": 1, "bridge_path": "x"}

    monkeypatch.setattr(scene_context_registry, "sync_pool_csv", fake_sync)
    return captured


def test_update_scene_changes_usage_tags_only(tmp_path, monkeypatch):
    captured = _isolate(monkeypatch, tmp_path, [_row("BOS_SCN_OFFICE_01", "office")])

    result = scene_context_registry.update_scene(
        "BOS_SCN_OFFICE_01", {"usage_tags": "event|launch"})

    assert result["updated"] == "BOS_SCN_OFFICE_01"
    written = list(_csv.DictReader(io.StringIO(captured["csv"])))
    assert len(written) == 1
    assert written[0]["usage_tags"] == "event|launch"                 # metadata changed
    assert written[0]["SceneCode"] == "BOS_SCN_OFFICE_01"             # code frozen
    assert written[0]["SceneName"] == "Modern Office"                 # identity frozen
    assert written[0]["BackgroundPrompt"] == "Background: a clean modern office"


def test_update_scene_not_found(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path, [_row("BOS_SCN_OFFICE_01")])
    with pytest.raises(ValueError, match="SCENE_CODE_NOT_FOUND"):
        scene_context_registry.update_scene("BOS_SCN_NOPE_99", {"usage_tags": "x"})


def test_update_scene_ignores_identity_fields(tmp_path, monkeypatch):
    """A non-whitelisted (identity) field is not editable -> no-op guard fires."""
    _isolate(monkeypatch, tmp_path, [_row("BOS_SCN_OFFICE_01", "office")])
    with pytest.raises(ValueError, match="SCENE_NO_EDITABLE_FIELDS"):
        scene_context_registry.update_scene(
            "BOS_SCN_OFFICE_01", {"BackgroundPrompt": "Background: a beach"})
