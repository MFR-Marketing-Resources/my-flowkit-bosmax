import pytest
from agent.services.scheduler_safety import validate_batch_safety, check_diversity_fingerprints

@pytest.mark.asyncio
async def test_validate_batch_safety_limits():
    # Test quantity > 20
    data = {"quantity": 21, "max_parallel_jobs": 1, "interval_min_seconds": 45, "interval_max_seconds": 60, "product_id": "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"}
    res = await validate_batch_safety(data)
    assert not res["is_safe"]
    assert any("exceeds batch limit of 20" in e for e in res["errors"])

    # Test max_parallel > 1
    data = {"quantity": 10, "max_parallel_jobs": 2, "interval_min_seconds": 45, "interval_max_seconds": 60, "product_id": "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"}
    res = await validate_batch_safety(data)
    assert not res["is_safe"]
    assert any("exceeds limit of 1" in e for e in res["errors"])

    # Test interval < 30
    data = {"quantity": 10, "max_parallel_jobs": 1, "interval_min_seconds": 25, "interval_max_seconds": 60, "product_id": "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"}
    res = await validate_batch_safety(data)
    assert not res["is_safe"]
    assert any("below safety floor of 30s" in e for e in res["errors"])

def test_check_diversity_fingerprints():
    variants = [
        {"diversity_fingerprint": "fp1"},
        {"diversity_fingerprint": "fp2"},
        {"diversity_fingerprint": "fp1"}, # duplicate
    ]
    dupes = check_diversity_fingerprints(variants)
    assert len(dupes) == 1
    assert dupes[0] == "fp1"
