import csv
import hashlib
import io
import json

import pytest

from agent.services import scene_context_registry as registry


@pytest.fixture(autouse=True)
def _clear_registry_caches():
    registry._classification_by_code.cache_clear()
    registry._load_pool.cache_clear()
    yield
    registry._classification_by_code.cache_clear()
    registry._load_pool.cache_clear()


def _authority_payload() -> dict:
    return json.loads(registry._CLASSIFICATION_FILE.read_text(encoding="utf-8"))


def _authority_file(tmp_path, payload: dict):
    authority = tmp_path / "classification.json"
    authority.write_text(json.dumps(payload), encoding="utf-8")
    return authority


def _seed_csv(*, headers=None, mutate=None) -> bytes:
    with registry._POOL_FILE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
        fieldnames = headers or list(rows[0])
    if mutate:
        mutate(rows)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _use_temp_bridge(monkeypatch, tmp_path):
    bridge = tmp_path / "SCENE_CONTEXT_POOL.csv"
    monkeypatch.setattr(registry, "_BRIDGE_FILE", bridge)
    return bridge


def test_seed_classification_is_complete_and_fail_closed():
    profiles = registry.list_pool()
    assert len(profiles) == 20
    assert {p["scene_code"] for p in profiles} == set(registry._classification_by_code())
    for profile in profiles:
        assert profile["cluster_classification_status"] in {"CLASSIFIED", "REVIEW_REQUIRED"}
        assert all(cluster in registry.canonical_clusters() for cluster in profile["compatible_clusters"])
        if profile["cluster_classification_status"] == "CLASSIFIED":
            assert profile["primary_cluster"] in profile["compatible_clusters"]
        else:
            assert profile["primary_cluster"] is None


def test_coverage_is_read_only_and_has_exact_authority_totals():
    before = hashlib.sha256(registry._POOL_FILE.read_bytes()).hexdigest()
    coverage = registry.cluster_coverage()
    assert coverage["registry_mutations"] == 0
    assert coverage["canonical_clusters"] == list(registry.canonical_clusters())
    assert (coverage["active_scene_total"], coverage["classified_scene_total"], coverage["review_required_scene_total"], coverage["shared_scene_total"]) == (20, 13, 7, 2)
    assert [(row["cluster"], row["eligible_active_scene_count"], row["gap_to_target"]) for row in coverage["per_cluster"]] == [
        ("Automotive", 0, 3), ("Baby & Kids", 0, 3), ("Beauty", 0, 3),
        ("Electronics & Gadgets", 0, 3), ("Fashion", 0, 3), ("Food & Beverage", 7, 0),
        ("Home & Living", 4, 0), ("Islamic & Books", 1, 2), ("Office & Stationery", 0, 3),
        ("Pet Care", 0, 3), ("Sports & Outdoors", 3, 0), ("Tools & Home Improvement", 0, 3),
    ]
    assert hashlib.sha256(registry._POOL_FILE.read_bytes()).hexdigest() == before


def test_sync_without_optional_cluster_columns_is_backward_compatible(monkeypatch, tmp_path):
    bridge = _use_temp_bridge(monkeypatch, tmp_path)
    result = registry.sync_pool_csv(_seed_csv())
    assert result["rows"] == 20 and bridge.exists()
    assert registry.resolve_scene_context("SCN_RAYA_KAMPUNG")["primary_cluster"] == "Islamic & Books"


def test_explicit_bridge_metadata_overrides_repository_authority(monkeypatch, tmp_path):
    bridge = _use_temp_bridge(monkeypatch, tmp_path)

    def mutate(rows):
        for row in rows:
            row["PrimaryCluster"] = "Beauty" if row["SceneCode"] == "SCN_WHITE_STUDIO_BERSIH" else ""
            row["CompatibleClusters"] = "Beauty" if row["SceneCode"] == "SCN_WHITE_STUDIO_BERSIH" else ""

    headers = list(csv.DictReader(io.StringIO(_seed_csv().decode("utf-8"))).fieldnames) + ["PrimaryCluster", "CompatibleClusters"]
    registry.sync_pool_csv(_seed_csv(headers=headers, mutate=mutate))
    profile = registry.resolve_scene_context("SCN_WHITE_STUDIO_BERSIH")
    assert bridge.exists()
    assert profile["cluster_classification_basis"] == "bridge_csv"
    assert profile["primary_cluster"] == "Beauty"


@pytest.mark.parametrize(
    "primary,compatible",
    [("Unknown", "Unknown"), ("Food & Beverage", "Food & Beverage|Food & Beverage"), ("Food & Beverage", "Home & Living"), ("", "Food & Beverage"), ("Food & Beverage", "")],
)
def test_invalid_bridge_metadata_fails_before_write(monkeypatch, tmp_path, primary, compatible):
    bridge = _use_temp_bridge(monkeypatch, tmp_path)
    original = b"preserve-this-bridge-byte-for-byte\r\n"
    bridge.write_bytes(original)

    def mutate(rows):
        rows[0]["PrimaryCluster"] = primary
        rows[0]["CompatibleClusters"] = compatible

    headers = list(csv.DictReader(io.StringIO(_seed_csv().decode("utf-8"))).fieldnames) + ["PrimaryCluster", "CompatibleClusters"]
    with pytest.raises(ValueError, match="SCENE_REGISTRY_INVALID_CLUSTER_METADATA"):
        registry.sync_pool_csv(_seed_csv(headers=headers, mutate=mutate))
    assert bridge.read_bytes() == original


def test_authority_rejects_duplicate_scene_code(monkeypatch, tmp_path):
    payload = _authority_payload()
    payload["scenes"].append(payload["scenes"][0].copy())
    monkeypatch.setattr(registry, "_CLASSIFICATION_FILE", _authority_file(tmp_path, payload))
    with pytest.raises(ValueError, match="SCENE_CLASSIFICATION_DUPLICATE_SCENE_CODE"):
        registry._classification_by_code()


@pytest.mark.parametrize("mutation,error", [
    (lambda payload: payload["scenes"].__setitem__(0, {**payload["scenes"][0], "scene_code": "SCN_UNKNOWN"}), "UNKNOWN_SCENE_CODE"),
    (lambda payload: payload["scenes"].pop(), "MISSING_SEED_SCENE_CODE"),
    (lambda payload: payload.__setitem__("classification_version", ""), "BLANK_VERSION"),
    (lambda payload: payload["scenes"][0].__setitem__("classification_version", "r4-v2"), "INCONSISTENT_VERSION"),
    (lambda payload: payload["scenes"][0].__setitem__("primary_cluster", None), "INVALID_PRIMARY"),
    (lambda payload: payload["scenes"][3].__setitem__("primary_cluster", "Beauty"), "INVALID_REVIEW_REQUIRED"),
    (lambda payload: payload["scenes"][1].__setitem__("compatible_clusters", ["Food & Beverage", "Food & Beverage"]), "SCENE_CLASSIFICATION_INVALID"),
])
def test_authority_rejects_invalid_contract(monkeypatch, tmp_path, mutation, error):
    payload = _authority_payload()
    mutation(payload)
    monkeypatch.setattr(registry, "_CLASSIFICATION_FILE", _authority_file(tmp_path, payload))
    with pytest.raises(ValueError, match=error):
        registry._classification_by_code()


def test_authority_accepts_valid_multi_cluster_classification():
    entry = registry._classification_by_code()["SCN_DAPUR_MODEN_OPEN_PLAN"]
    assert entry["primary_cluster"] == "Home & Living"
    assert entry["compatible_clusters"] == ["Home & Living", "Food & Beverage"]
