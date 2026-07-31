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


def _run_scale_proof(data_dir: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-dir",
            str(data_dir),
            "--scale-proof",
        ],
        cwd=SCRIPT.parents[1],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


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


def test_scale_proof_is_exact_deterministic_and_zero_credit(tmp_path):
    payload = _run_scale_proof(tmp_path)

    assert payload["database_opened"] is False
    assert payload["database_writes"] == 0
    assert payload["canonical_database_accessed"] is False
    assert not (tmp_path / "flow_agent.db").exists()
    for key in (
        "provider_calls",
        "google_flow_calls",
        "media_generation_calls",
        "credit_spend",
    ):
        assert payload[key] == 0
        assert payload["dispatch_boundary"][key] == 0
    assert payload["dispatch_boundary"]["dispatch_attempt_calls"] == 0
    assert payload["dispatch_boundary"]["scheduler_tick_calls"] == 0

    single = payload["single_product"]
    mixed = payload["mixed_product"]
    for scenario in (single, mixed):
        assert scenario["requested"] == 100
        assert scenario["planned"] == 100
        assert scenario["materialized"] == 100
        assert scenario["compiled"] == 100
        assert scenario["dry_run_ready"] == 100
        assert scenario["unique_item_count"] == 100
        assert scenario["unique_dna_count"] == 100
        assert scenario["cartesian_expansion_count"] == 0
        assert scenario["candidate_selections_per_item"] == 1
        assert scenario["revalidated_count"] == 100
        assert scenario["deterministic_replay"] is True

    assert mixed["per_product_isolation"] is True
    assert mixed["cross_product_authority_leaks"] == 0
    assert mixed["product_counts"] == {
        "fixture-apparel": 25,
        "fixture-audio": 25,
        "fixture-food": 25,
        "fixture-supplement": 25,
    }
    assert mixed["blocked_products"] == [
        {
            "product_id": "fixture-unsupported",
            "status": "UNSUPPORTED_PRODUCT_TAXONOMY",
            "reason": "APPLICABILITY_PROFILE_UNSUPPORTED",
            "next_action": "Map the product to a supported non-fallback taxonomy.",
        }
    ]


def test_scale_proof_covers_profiles_modes_and_five_member_variation(tmp_path):
    payload = _run_scale_proof(tmp_path)
    coverage = payload["supported_profile_coverage"]
    assert coverage["supported_profile_count"] > 90
    assert (
        coverage["resolved_supported_profile_count"]
        == coverage["supported_profile_count"]
    )
    assert coverage["unsupported_profiles_fail_closed"] == [
        "GENERIC_FALLBACK",
        "UNKNOWN",
    ]
    assert set(coverage["risk_classes"]) >= {
        "CHEMICAL",
        "CHILD",
        "COMPOSITION_SENSITIVE",
        "ELECTRICAL",
        "HIGH_RISK",
        "INGESTIBLE",
        "MATERIAL_SENSITIVE",
        "MECHANICAL_HAZARD",
        "REGULATED",
        "TOPICAL",
    }

    matrix = payload["format_mode_matrix"]
    assert matrix["combination_count"] == 12
    assert matrix["ready_count"] == 12
    assert matrix["formats"] == ["CINEMATIC", "PGC", "UGC"]
    assert matrix["logical_modes"] == ["F2V", "HYBRID", "I2V", "T2V"]
    assert all(row["blockers"] == [] for row in matrix["rows"])
    assert {
        (row["logical_mode"], row["payload_mode"], row["execution_lane"])
        for row in matrix["rows"]
    } >= {
        ("T2V", "T2V", "TEXT_TO_VIDEO"),
        ("F2V", "F2V", "FINISHED_FRAME_TO_VIDEO"),
        ("I2V", "I2V", "INGREDIENTS_TO_VIDEO"),
        ("HYBRID", "F2V", "PRODUCT_ANCHOR_PRESENTER"),
    }

    variation = payload["variation_group"]
    assert variation["member_count"] == 5
    assert variation["max_member_count"] == 5
    assert variation["same_dialogue"] is True
    assert variation["distinct_visual_fingerprint_count"] == 5
    assert variation["unrestricted_cartesian_mixing"] is False
    assert len({row["item_id"] for row in variation["members"]}) == 5
    assert payload["evidence_states_preserved"] == [
        "VERIFIED_VALUE",
        "NOT_APPLICABLE",
        "NOT_STATED_IN_EVIDENCE",
        "UNKNOWN_REVIEW_REQUIRED",
    ]
