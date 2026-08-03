"""COPY-CORRECTIVE-B05 (defect #8): copy readiness fails CLOSED when strict
validity evaluation raises — never a silent success, null, or false-ready.
"""
import pytest

from agent.db import crud
from agent.services import copywriting_readiness_service as svc


@pytest.mark.asyncio
async def test_readiness_fails_closed_on_validity_eval_error(monkeypatch):
    from tests.conftest import make_product_copy_eligible

    product = await crud.create_product(
        raw_product_title="Readiness Failclosed 5ML", source="MANUAL"
    )
    pid = product["id"]
    await make_product_copy_eligible(pid)

    async def _boom(_pid):
        raise RuntimeError("validity boom")

    monkeypatch.setattr(
        "agent.services.copy_set_validity_service.product_copy_classification", _boom
    )

    r = await svc.get_copywriting_readiness(pid)
    assert r["ready_for_generation"] is False
    assert r["copy_classification"] == "VALIDITY_EVALUATION_FAILED"
    assert "VALIDITY_EVALUATION_FAILED" in r["blocking_reasons"]
    assert r["recommended_next_action"] == "BLOCKED"
