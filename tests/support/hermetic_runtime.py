"""Hermetic temporary runtime roots for PR #298 A/B verification.

Never points at the canonical checkout. Initializes isolated FLOW_AGENT_DIR trees
from version-controlled sanitized fixtures only.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HERMETIC_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "hermetic"
SANITIZED_AI_SETTINGS = HERMETIC_FIXTURE_DIR / "ai-provider-settings.json"
SANITIZED_DOTENV = HERMETIC_FIXTURE_DIR / "sanitized.env"

ALLOWED_ENV_KEYS = frozenset(
    {
        "FLOW_AGENT_DIR",
        "PYTHONPATH",
        "PYTEST_CURRENT_TEST",
        "PYTEST_VERSION",
        "PYTEST_ADDOPTS",
        "VIRTUAL_ENV",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "HOME",
        "PATH",
        "SYSTEMROOT",
        "COMSPEC",
        "WINDIR",
        "BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED",
        "BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED",
        "PYTHONNOUSERSITE",
        "PYTHONIOENCODING",
        "LANG",
        "LC_ALL",
    }
)

SECRET_ENV_DENYLIST = frozenset(
    {
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
        "POSTIZ_API_KEY",
    }
)


def fixture_hash() -> str:
    parts = []
    for path in (SANITIZED_AI_SETTINGS, SANITIZED_DOTENV):
        parts.append(path.read_bytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()[:16]


def install_hermetic_runtime_root(target: Path) -> Path:
    """Create a fresh isolated agent root under ``target``."""
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    local_agent = target / ".local-agent"
    local_agent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SANITIZED_AI_SETTINGS, local_agent / "ai-provider-settings.json")
    shutil.copy2(SANITIZED_DOTENV, target / ".env")
    (target / "data").mkdir(parents=True, exist_ok=True)
    (target / "output").mkdir(parents=True, exist_ok=True)
    return target


def hermetic_env_for_root(agent_root: Path, *, repo_for_pythonpath: Path) -> dict[str, str]:
    """Copy host env minus secret keys; override FLOW_AGENT_DIR for isolation."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV_DENYLIST}
    env["FLOW_AGENT_DIR"] = str(agent_root.resolve())
    env["PYTHONPATH"] = str(repo_for_pythonpath.resolve())
    env["BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED"] = "0"
    env["BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED"] = "0"
    for candidate in (repo_for_pythonpath / ".venv", Path("C:/Users/USER/Desktop/_ref_flowkit/.venv")):
        if candidate.is_dir():
            env["VIRTUAL_ENV"] = str(candidate.resolve())
            break
    return env


def manifest_payload(
    *,
    label: str,
    commit_sha: str,
    python_executable: str,
    python_version: str,
    cwd: str,
    agent_root: str,
    test_command: list[str],
) -> dict:
    return {
        "label": label,
        "commit_sha": commit_sha,
        "python_executable": python_executable,
        "python_version": python_version,
        "cwd": cwd,
        "flow_agent_dir": agent_root,
        "fixture_hash": fixture_hash(),
        "allowed_env_keys": sorted(ALLOWED_ENV_KEYS),
        "secret_env_denylist": sorted(SECRET_ENV_DENYLIST),
        "test_command": test_command,
        "secrets_policy": "no_real_api_keys_in_fixtures",
    }