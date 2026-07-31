import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "universal-product-treatment-factory-rehearsal.py"
)


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_VERSION", None)
    return env


def test_rehearsal_requires_explicit_isolated_data_directory(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--product-id",
            "isolated-product",
        ],
        cwd=SCRIPT.parents[1],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "--data-dir" in completed.stderr
    assert not (tmp_path / "flow_agent.db").exists()


def test_rehearsal_records_zero_provider_and_credit_activity(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-dir",
            str(tmp_path),
            "--product-id",
            "isolated-product",
        ],
        cwd=SCRIPT.parents[1],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["provider_calls"] == 0
    assert payload["google_flow_calls"] == 0
    assert payload["media_generation_calls"] == 0
    assert payload["credit_spend"] == 0
    assert payload["plan"]["product_count"] == 1
    assert len(payload["plan"]["tasks"]) == 10
    assert payload["plan"]["failure_count"] == 1
    assert (tmp_path / "flow_agent.db").exists()
