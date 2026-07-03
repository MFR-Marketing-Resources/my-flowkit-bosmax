"""Contracts for the repo-root .env bootstrap (agent/config.py).

The Setup Doctor tells operators "edit .env and restart the BOSMAX
agent/server" — these tests prove that instruction is real:

* a repo-root ``.env`` populates POSTIZ_* variables when the OS env is empty,
* pre-existing OS environment variables stay authoritative (override=False),
* a missing ``.env`` is a silent no-op (startup must never fail),
* the load works even when python-dotenv is NOT installed in the running
  interpreter (durability must not depend on the launcher's interpreter),
* POSTIZ_API_KEY never leaks into logs or the setup-status response,
* fail-safe defaults survive: POSTIZ_ENABLED=false, POSTIZ_DEFAULT_POST_TYPE=draft.
"""
import builtins
import logging
import os

import pytest

from agent import config
from agent.services import postiz_client as pz

_POSTIZ_KEYS = (
    "POSTIZ_ENABLED", "POSTIZ_BASE_URL", "POSTIZ_API_KEY",
    "POSTIZ_UPLOAD_MODE", "POSTIZ_DEFAULT_POST_TYPE", "POSTIZ_API_PREFIX",
)


@pytest.fixture(autouse=True)
def _clean_postiz_env():
    """Snapshot and restore POSTIZ_* so load_dotenv writes can't bleed
    between tests (monkeypatch can't restore keys created by load_dotenv)."""
    before = {k: os.environ.get(k) for k in _POSTIZ_KEYS}
    for k in _POSTIZ_KEYS:
        os.environ.pop(k, None)
    yield
    for k, v in before.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _write_env(tmp_path, **values):
    lines = [f"{k}={v}" for k, v in values.items()]
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def _block_dotenv(monkeypatch):
    """Force ``from dotenv import load_dotenv`` to raise ImportError, mimicking
    the uv/uvicorn interpreter the external supervisor launches the agent in."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dotenv" or name.startswith("dotenv."):
            raise ImportError("simulated: python-dotenv not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_env_loads_without_python_dotenv_installed(tmp_path, monkeypatch):
    """The regression that kept resurfacing: when the launching interpreter has
    no python-dotenv, .env MUST still load via the built-in parser (not a
    silent no-op that leaves POSTIZ_* unset)."""
    _block_dotenv(monkeypatch)
    with pytest.raises(ImportError):
        __import__("dotenv")  # guard: the block is actually in effect
    env_file = _write_env(
        tmp_path,
        POSTIZ_ENABLED="true",
        POSTIZ_BASE_URL="http://127.0.0.1:5000",
        POSTIZ_API_KEY="file-key-not-a-real-secret",
    )
    assert config._load_env_file(env_file) is True
    cfg = pz.postiz_config()
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://127.0.0.1:5000"
    assert cfg["api_key"] == "file-key-not-a-real-secret"


def test_builtin_parser_handles_comments_quotes_export_and_os_precedence(tmp_path):
    """The dependency-free fallback must match dotenv semantics for the cases
    a real .env uses."""
    os.environ["POSTIZ_BASE_URL"] = "http://os-wins:5000"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "export POSTIZ_ENABLED=true",
                'POSTIZ_API_KEY="quoted-key-value"',
                "POSTIZ_UPLOAD_MODE='file'",
                "POSTIZ_BASE_URL=http://file-loses:5000",  # OS already set -> ignored
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert config._parse_env_file(env_file) is True
    assert os.environ["POSTIZ_ENABLED"] == "true"          # export stripped
    assert os.environ["POSTIZ_API_KEY"] == "quoted-key-value"  # double quotes stripped
    assert os.environ["POSTIZ_UPLOAD_MODE"] == "file"      # single quotes stripped
    assert os.environ["POSTIZ_BASE_URL"] == "http://os-wins:5000"  # OS authoritative


def test_env_file_populates_postiz_vars_when_os_env_missing(tmp_path):
    env_file = _write_env(
        tmp_path,
        POSTIZ_ENABLED="true",
        POSTIZ_BASE_URL="http://127.0.0.1:5000",
        POSTIZ_API_KEY="file-key-not-a-real-secret",
    )
    assert config._load_env_file(env_file) is True
    cfg = pz.postiz_config()
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://127.0.0.1:5000"
    assert cfg["api_key"] == "file-key-not-a-real-secret"


def test_os_env_overrides_env_file_when_both_exist(tmp_path):
    os.environ["POSTIZ_BASE_URL"] = "http://os-wins:5000"
    os.environ["POSTIZ_API_KEY"] = "os-key"
    env_file = _write_env(
        tmp_path,
        POSTIZ_BASE_URL="http://file-loses:5000",
        POSTIZ_API_KEY="file-key",
        POSTIZ_ENABLED="true",
    )
    config._load_env_file(env_file)
    cfg = pz.postiz_config()
    # OS values stay authoritative; file only fills the gaps.
    assert cfg["base_url"] == "http://os-wins:5000"
    assert cfg["api_key"] == "os-key"
    assert cfg["enabled"] is True  # gap-filled from the file


def test_missing_env_file_is_silent_noop(tmp_path):
    assert config._load_env_file(tmp_path / "does-not-exist.env") is False
    # And nothing was set.
    assert os.environ.get("POSTIZ_ENABLED") is None


def test_env_loading_never_logs_the_api_key(tmp_path, caplog):
    env_file = _write_env(tmp_path, POSTIZ_API_KEY="super-secret-value-42")
    with caplog.at_level(logging.DEBUG):
        config._load_env_file(env_file)
    assert "super-secret-value-42" not in caplog.text


async def test_setup_status_never_returns_or_logs_the_api_key(tmp_path, caplog, monkeypatch):
    env_file = _write_env(
        tmp_path,
        POSTIZ_ENABLED="true",
        POSTIZ_BASE_URL="http://127.0.0.1:5000",
        POSTIZ_API_KEY="super-secret-value-42",
    )
    config._load_env_file(env_file)

    async def fake_probe(base_url):
        return False  # unreachable branch — no network in unit tests

    monkeypatch.setattr(pz, "probe_reachable", fake_probe)
    with caplog.at_level(logging.DEBUG):
        status = await pz.setup_status()
    import json
    serialized = json.dumps(status)
    assert "super-secret-value-42" not in serialized
    assert "super-secret-value-42" not in caplog.text
    assert status["api_key_present"] is True
    assert "api_key" not in status  # only the boolean flag is exposed


def test_defaults_stay_fail_safe_without_any_env():
    cfg = pz.postiz_config()
    assert cfg["enabled"] is False              # POSTIZ_ENABLED defaults false
    assert cfg["default_post_type"] == "draft"  # never public by default


def test_env_file_cannot_flip_defaults_unless_explicit(tmp_path):
    # A .env that only sets the base URL must NOT enable the adapter.
    env_file = _write_env(tmp_path, POSTIZ_BASE_URL="http://127.0.0.1:5000")
    config._load_env_file(env_file)
    cfg = pz.postiz_config()
    assert cfg["enabled"] is False
    assert cfg["default_post_type"] == "draft"
