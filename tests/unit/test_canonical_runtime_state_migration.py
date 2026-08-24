from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "migrate-canonical-runtime-state.ps1"
PROVIDER_HELPER = REPO_ROOT / "scripts" / "migrate-provider-settings-state.py"


def _load_provider_helper():
    spec = importlib.util.spec_from_file_location(
        "migrate_provider_settings_state", PROVIDER_HELPER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(*, with_keys: bool = True, configured_lanes: bool = True) -> dict:
    default_models = {
        "qwen": "qwen-plus",
        "anthropic": "claude-sonnet-5",
        "openai": "gpt-4o-mini",
        "gemini": "gemini-2.0-flash",
        "deepseek": "deepseek-v4-flash",
    }
    providers = {
        provider_id: {
            "api_key": (
                f"synthetic-{provider_id}-migration-key"
                if with_keys
                else ""
            ),
            "updated_at": "2026-01-01T00:00:00Z" if with_keys else None,
            "activated_at": "2026-01-01T00:00:00Z" if with_keys else None,
            "default_model": default_models[provider_id] if with_keys else None,
        }
        for provider_id in ("qwen", "anthropic", "openai", "gemini", "deepseek")
    }
    lanes = {
        "text_assist": {
            "provider_id": "deepseek" if configured_lanes else None,
            "model_id": "deepseek-v4-flash" if configured_lanes else None,
            "execution_enabled": configured_lanes,
            "configured_by_user": configured_lanes,
        },
        "vision": {
            "provider_id": "anthropic" if configured_lanes else None,
            "model_id": "claude-haiku-4-5-20251001" if configured_lanes else None,
            "execution_enabled": configured_lanes,
            "configured_by_user": configured_lanes,
        },
    }
    return {
        "version": 3,
        "active_provider": "deepseek" if configured_lanes else None,
        "providers": providers,
        "lanes": lanes,
    }


def _write_settings(path: Path, **kwargs) -> bytes:
    payload = _settings(**kwargs)
    raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _write_minimal_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE product (id TEXT PRIMARY KEY)")
        connection.execute(
            """
            CREATE TABLE product_visual_truth_lock (
                product_id TEXT PRIMARY KEY,
                review_status TEXT,
                canonical_source_path TEXT,
                canonical_sha256 TEXT,
                canonical_cutout_path TEXT,
                canonical_cutout_sha256 TEXT
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def _run_migration(source: Path, state: Path) -> subprocess.CompletedProcess[str]:
    runtime_root = state.parent
    powershell = shutil.which("pwsh") or "powershell"
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(MIGRATION_SCRIPT),
            "-Repo",
            str(source),
            "-RuntimeRoot",
            str(runtime_root),
            "-StateRoot",
            str(state),
            "-Python",
            sys.executable,
            "-Apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_db_data_and_provider_state_migrate_byte_for_byte(tmp_path: Path):
    source = tmp_path / "source"
    state = tmp_path / "runtime" / "state"
    source.mkdir()
    (source / "data").mkdir()
    _write_minimal_db(source / "flow_agent.db")
    source_settings = source / ".local-agent" / "ai-provider-settings.json"
    source_bytes = _write_settings(source_settings)

    result = _run_migration(source, state)

    assert result.returncode == 0, result.stderr
    destination_settings = state / ".local-agent" / "ai-provider-settings.json"
    assert (state / "flow_agent.db").is_file()
    assert (state / "data").is_dir()
    assert destination_settings.read_bytes() == source_bytes
    assert source_settings.read_bytes() == source_bytes
    receipt = (state / "state-migration-receipt.json").read_text(encoding="utf-8")
    assert "synthetic-" not in receipt
    assert "synthetic-" not in result.stdout
    assert "synthetic-" not in result.stderr

    helper = _load_provider_helper()
    summary = helper.inspect_settings(destination_settings)
    assert all(item["has_key"] for item in summary["providers"].values())
    assert summary["active_provider"] == "deepseek"
    assert summary["lanes"]["text"]["model_id"] == "deepseek-v4-flash"
    assert summary["lanes"]["structure"]["model_id"] == "deepseek-v4-flash"
    assert summary["lanes"]["image"]["model_id"] == "claude-haiku-4-5-20251001"
    assert summary["lanes"]["video"]["provider_id"] is None


def test_missing_provider_source_does_not_block_db_data_migration(tmp_path: Path):
    source = tmp_path / "source"
    state = tmp_path / "runtime" / "state"
    source.mkdir()
    (source / "data").mkdir()
    _write_minimal_db(source / "flow_agent.db")

    result = _run_migration(source, state)

    assert result.returncode == 0, result.stderr
    assert (state / "flow_agent.db").is_file()
    assert (state / "data").is_dir()
    assert not (state / ".local-agent" / "ai-provider-settings.json").exists()
    assert "synthetic-" not in result.stdout
    assert "synthetic-" not in result.stderr


def test_existing_destination_is_not_overwritten(tmp_path: Path):
    source = tmp_path / "source"
    state = tmp_path / "runtime" / "state"
    source.mkdir()
    (source / "data").mkdir()
    _write_minimal_db(source / "flow_agent.db")
    source_settings = source / ".local-agent" / "ai-provider-settings.json"
    _write_settings(source_settings)
    destination_settings = state / ".local-agent" / "ai-provider-settings.json"
    destination_bytes = _write_settings(
        destination_settings, with_keys=True, configured_lanes=False
    )

    result = _run_migration(source, state)

    assert result.returncode != 0
    assert destination_settings.read_bytes() == destination_bytes
    assert "synthetic-" not in result.stdout
    assert "synthetic-" not in result.stderr


def test_provider_helper_rejects_conflicting_keyless_destination(tmp_path: Path):
    helper = _load_provider_helper()
    source = tmp_path / "source.json"
    destination = tmp_path / "destination.json"
    _write_settings(source)
    _write_settings(destination, with_keys=False, configured_lanes=True)

    with pytest.raises(
        helper.ProviderSettingsMigrationError,
        match="PROVIDER_SETTINGS_DESTINATION_CONFLICT",
    ):
        helper.migrate_provider_settings(source, destination)


def test_flow_agent_dir_resolves_provider_state_from_external_root(tmp_path: Path):
    external_root = tmp_path / "canonical-state"
    env = os.environ.copy()
    env["FLOW_AGENT_DIR"] = str(external_root)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent.services.ai_provider_settings_service import AI_PROVIDER_SETTINGS_FILE; print(AI_PROVIDER_SETTINGS_FILE)",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(external_root / ".local-agent" / "ai-provider-settings.json")
