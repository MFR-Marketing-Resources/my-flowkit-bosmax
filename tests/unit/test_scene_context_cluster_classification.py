import hashlib
from pathlib import Path

from agent.services import scene_context_registry as registry


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


def test_coverage_is_read_only_and_has_all_canonical_clusters():
    before = hashlib.sha256(registry._POOL_FILE.read_bytes()).hexdigest()
    coverage = registry.cluster_coverage()
    assert coverage["registry_mutations"] == 0
    assert coverage["canonical_clusters"] == list(registry.canonical_clusters())
    assert len(coverage["per_cluster"]) == 12
    assert hashlib.sha256(registry._POOL_FILE.read_bytes()).hexdigest() == before
