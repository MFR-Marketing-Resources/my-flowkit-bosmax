"""Task C — legacy copy_set runtime closure.

Proves that in NORMAL runtime (legacy copy maintenance OFF) the product treatment
factory and product readiness derive copy authority exclusively from V2:

  * no active production WRITE to legacy copy_set
  * no active production READ of legacy copy_set as authority
  * missing V2 authority FAILS CLOSED (COPY_V2_BINDING_REQUIRED)
  * zero provider / media / credit spend on the fail-closed path

The whole suite otherwise runs with COPY_LEGACY_MAINTENANCE_MODE=1 (conftest), so
each production-default test explicitly removes the flag. The final test proves the
legacy path is still reachable ONLY under explicit maintenance mode.
"""

import sqlite3

import pytest

from agent import config
from agent.db.schema import init_db
from agent.services import product_readiness_applicability_service as readiness_service
from agent.services import product_treatment_factory_service as service


@pytest.fixture
def production_default(monkeypatch):
    """Force the production default: legacy copy maintenance OFF."""
    monkeypatch.delenv("COPY_LEGACY_MAINTENANCE_MODE", raising=False)


def _copy_task(*, binding=False, copy_set_ids=None, provider=False, required=3):
    preview: dict[str, object] = {
        "required_dialogues": required,
        "provider_calls_enabled": provider,
    }
    if copy_set_ids is not None:
        preview["eligible_approved_copy_set_ids"] = list(copy_set_ids)
    if binding:
        preview["eligible_approved_binding_ids"] = [
            "binding:bpv2_test:1:PRODUCTION_STUDIO_P6:approval:test"
        ]
    return {
        "task_id": "copy-task",
        "product_id": "product-a",
        "snapshot": {
            "required_dialogues": required,
            "provider_calls_enabled": provider,
            "copy_preview": preview,
        },
    }


@pytest.mark.asyncio
async def test_no_v2_binding_fails_closed_and_never_composes(production_default, monkeypatch):
    """C + D: legacy copy_set ids never satisfy readiness; the composer is never called."""
    compose_calls: list = []

    async def compose(*args, **kwargs):
        compose_calls.append((args, kwargs))
        return {"created": 1, "produced": 1}

    monkeypatch.setattr(service.copy_composer_service, "compose_and_persist", compose)

    task = _copy_task(binding=False, copy_set_ids=["copy-a", "copy-b"], required=3)
    with pytest.raises(service.ProductTreatmentFactoryError) as exc:
        await service._prepare_copy_task(task)

    assert exc.value.code == "COPY_V2_BINDING_REQUIRED"
    assert compose_calls == []  # no legacy copy_set write attempted


@pytest.mark.asyncio
async def test_no_v2_binding_never_calls_legacy_ai_assist(production_default, monkeypatch):
    """E: the provider-enabled no-binding path must never invoke legacy AI copy assist."""
    compose_calls: list = []
    ai_calls: list = []

    async def compose(*args, **kwargs):
        compose_calls.append(1)
        return {"created": 0}

    async def ai_batch(*args, **kwargs):
        ai_calls.append(1)
        return {"created_count": 0}

    monkeypatch.setattr(service.copy_composer_service, "compose_and_persist", compose)
    monkeypatch.setattr(
        service.ai_copy_assist_service,
        "generate_ai_copy_candidates_batch",
        ai_batch,
    )

    task = _copy_task(binding=False, copy_set_ids=[], provider=True, required=5)
    with pytest.raises(service.ProductTreatmentFactoryError) as exc:
        await service._prepare_copy_task(task)

    assert exc.value.code == "COPY_V2_BINDING_REQUIRED"
    # F: fail closed BEFORE any provider/media/credit-spending call.
    assert compose_calls == []
    assert ai_calls == []


@pytest.mark.asyncio
async def test_valid_v2_binding_stays_satisfied_via_v2(production_default, monkeypatch):
    """B + I: a valid V2 binding remains SATISFIED via COPY_REGISTER_V2, no legacy call."""

    async def compose(*args, **kwargs):
        raise AssertionError("compose_and_persist must not be called on the V2 path")

    monkeypatch.setattr(service.copy_composer_service, "compose_and_persist", compose)

    task = _copy_task(binding=True, required=3)
    status, result = await service._prepare_copy_task(task)

    assert status == "SATISFIED"
    assert result["copy_authority"] == "COPY_REGISTER_V2"
    assert result["provider_calls"] == 0
    assert result["media_generation_calls"] == 0
    assert result["credit_spend"] == 0


@pytest.mark.asyncio
async def test_treatment_no_binding_never_authorizes_from_legacy(production_default, monkeypatch):
    """Legacy copy_set ids must never authorize treatment creation in normal runtime."""
    created: list = []

    async def list_treatments(**_kwargs):
        return []

    async def create_treatment(request):
        created.append(request)
        return {
            "treatment_id": "t",
            "treatment_sha256": "9" * 64,
            "status": "DRAFT",
        }

    monkeypatch.setattr(service.creative_treatment_service, "list_treatments", list_treatments)
    monkeypatch.setattr(service.creative_treatment_service, "create_treatment", create_treatment)

    task = {
        "task_id": "treatment-task",
        "product_id": "product-a",
        "snapshot": {
            "required_dialogues": 2,
            "copy_preview": {
                "required_dialogues": 2,
                "eligible_approved_copy_set_ids": ["copy-a", "copy-b"],
            },
            "resolved_authority": {
                "copy": {"approved_copy_set_ids": ["copy-a", "copy-b"]},
                "selection": {},
            },
        },
    }
    with pytest.raises(service.ProductTreatmentFactoryError) as exc:
        await service._prepare_treatment_task(task, actor_id="factory-test")

    assert exc.value.code == "COPY_V2_BINDING_REQUIRED"
    assert created == []  # no treatment created from legacy copy authority


@pytest.mark.asyncio
async def test_readiness_does_not_read_or_count_legacy_copy_sets(production_default, monkeypatch):
    """The readiness authority never surfaces legacy copy_set rows as approved copy."""
    list_calls: list = []

    class _Grounding:
        grounded = True
        source = "APPROVED_SNAPSHOT"

    async def grounding(_product):
        return _Grounding()

    async def list_copy_sets(_product_id):
        list_calls.append(1)
        return [{"copy_set_id": "cs1", "status": readiness_service.STATUS_COPY_APPROVED}]

    monkeypatch.setattr(readiness_service.copy_grounding_service, "resolve_copy_grounding", grounding)
    monkeypatch.setattr(readiness_service.copy_set_service, "list_copy_sets", list_copy_sets)

    authority = await readiness_service._resolve_copy({"id": "product-a"})

    assert authority.approved_copy_set_ids == []
    assert list_calls == []  # the retired store is not even queried in normal runtime


@pytest.mark.asyncio
async def test_historical_variation_group_fk_intact(production_default):
    """G: the historical creative_variation_group copy authority FK is untouched."""
    await init_db()
    con = sqlite3.connect(str(config.DB_PATH))
    try:
        fks = con.execute(
            "PRAGMA foreign_key_list('creative_variation_group')"
        ).fetchall()
        targets = {fk[2] for fk in fks}
        # Fresh schema references copy_set; a post-cutover DB references the
        # legacy_copy_set_receipt archive. Either way the hard FK must remain.
        assert targets & {"copy_set", "legacy_copy_set_receipt"}
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        con.close()


@pytest.mark.asyncio
async def test_legacy_path_reachable_only_under_maintenance(monkeypatch):
    """§7: the legacy composer stays reachable ONLY under explicit maintenance mode."""
    monkeypatch.setenv("COPY_LEGACY_MAINTENANCE_MODE", "1")
    compose_calls: list = []

    async def compose(product_id, count, *, dry_run):
        compose_calls.append((product_id, count, dry_run))
        return {"product_id": product_id, "created": count, "produced": count}

    monkeypatch.setattr(service.copy_composer_service, "compose_and_persist", compose)

    task = _copy_task(binding=False, copy_set_ids=[], required=2)
    status, result = await service._prepare_copy_task(task)

    assert status == "REVIEW_REQUIRED"
    assert compose_calls == [("product-a", 2, False)]  # maintenance path still active
