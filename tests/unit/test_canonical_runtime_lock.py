"""Static contract checks for canonical runtime persistence and delivery lock."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_autostart_has_one_canonical_launcher_and_disables_known_duplicates():
    source = (ROOT / "scripts" / "install-canonical-runtime-autostart.ps1").read_text(encoding="utf-8")

    assert "BOSMAX Canonical Runtime.lnk" in source
    assert "start-canonical-runtime.ps1" in source
    assert 'Join-Path $RuntimeRoot "current"' in source
    assert "BOSMAX Flow Kit Local Agent.lnk" in source
    assert "BOSMAX Local Runner.lnk" in source
    assert "LEGACY_STARTUP_BACKUP_EXISTS" in source


def test_delivery_doc_keeps_merged_distinct_from_deployed():
    doc = (ROOT / "docs" / "CANONICAL_RUNTIME_PERSISTENCE.md").read_text(encoding="utf-8")

    assert "MERGED != DEPLOYED" in doc
    for stage in (
        "commit",
        "push",
        "PR",
        "CI green",
        "merge",
        "immutable release built from the merge SHA",
        "current pointer updated",
        "canonical runtime restarted",
        "runtime SHA == origin/main",
        "source_stale = false",
        "post-merge Smart Registration smoke PASS",
    ):
        assert stage in doc
