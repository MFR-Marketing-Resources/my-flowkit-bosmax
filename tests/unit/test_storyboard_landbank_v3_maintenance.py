"""Focused proof for the additive Copywriting Landbank Reporting surface."""

from __future__ import annotations

import pytest
import httpx

from agent.db.schema import get_db
from agent.main import app
from agent.models.storyboard_landbank_v3 import digest_text
from agent.services.storyboard_landbank_v3_factory import V3FactoryError
from agent.services.storyboard_landbank_v3_maintenance import (
    V3CopywritingLandbankMaintenanceService,
)
from agent.services.storyboard_landbank_v3_round2 import V3CopyRegisterRound2Service
from tests.unit.test_storyboard_landbank_v3_round2_copy_register import _seed_round2_fixture


async def _generate(product_id: str, monkeypatch):
    monkeypatch.setenv("V3_ROUND2_FAKE_PROVIDER", "1")
    factory, recipe, _angle, _family = await _seed_round2_fixture(product_id)
    round2 = V3CopyRegisterRound2Service(factory=factory)
    plan = await round2.plan_assistant(
        product_id,
        recipe.recipe_id,
        mode="CREATE",
        actor_id="maintenance-fixture",
        request_id=f"{product_id}:plan",
    )
    result = await round2.execute_assistant(
        plan.plan_id,
        actor_id="maintenance-fixture",
        request_id=f"{product_id}:execute",
        provider_mode="FAKE_TEST",
    )
    return factory, round2, result


def _checklist() -> dict[str, bool]:
    return {
        "semantic_reviewed": True,
        "product_truth_reviewed": True,
        "formula_reviewed": True,
        "evidence_reviewed": True,
        "bridge_reviewed": True,
        "safety_reviewed": True,
        "duration_reviewed": True,
    }


@pytest.mark.asyncio
async def test_all_product_list_is_exact_revision_paged_and_provider_free(monkeypatch):
    factory, _round2, first = await _generate("maintenance-one", monkeypatch)
    await _generate("maintenance-two", monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)

    page = await service.list_records(limit=1, offset=1)
    assert page["source"] == "V3_COPY_REGISTER_MAINTENANCE"
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["summary"]["total_copy_masters"] == 2
    assert page["summary"]["total_master_revisions"] == 2
    assert page["summary"]["products_with_copy"] == 2
    assert page["summary"]["products_without_copy"] == 0
    assert page["provider_calls"] == 0
    assert page["mutations"] == 0
    assert {item["product_id"] for item in page["product_coverage"]} == {"maintenance-one", "maintenance-two"}

    searched = await service.list_records(search=first["master"]["entity_id"])
    assert searched["total"] == 1
    assert searched["items"][0]["master_id"] == first["master"]["entity_id"]


@pytest.mark.asyncio
async def test_manual_save_uses_exact_revision_conflict_and_recomputes_text_digest(monkeypatch):
    factory, _round2, result = await _generate("maintenance-save", monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    master_id = result["master"]["entity_id"]
    detail = await service.get_detail(master_id, 1)
    submitted = [
        {"stage_key": stage["stage_key"], "authored_text": stage["authored_text"]}
        for stage in detail["stages"]
    ]
    submitted[0]["authored_text"] = "A safer manual hook for this exact draft."
    saved = await service.create_manual_revision(
        master_id,
        source_revision=1,
        stages=submitted,
        actor_id="maintenance-editor",
        request_id="maintenance-save:one",
    )
    assert saved["source_revision"] == 1
    assert saved["new_revision"] == 2
    assert saved["master"]["status"] == "DRAFT"
    assert saved["automatic_approval"] is False
    assert saved["approval_carried_forward"] is False
    assert saved["production_authority_carried_forward"] is False

    original = await factory.repository.get("MASTER_STORYBOARD", master_id, 1)
    revised = await factory.repository.get("MASTER_STORYBOARD", master_id, 2)
    assert original.stages[0].authored_text != revised.stages[0].authored_text
    assert revised.stages[0].text_digest == digest_text(revised.stages[0].authored_text)

    with pytest.raises(V3FactoryError) as conflict:
        await service.create_manual_revision(
            master_id,
            source_revision=1,
            stages=submitted,
            actor_id="maintenance-editor",
            request_id="maintenance-save:stale",
        )
    assert conflict.value.code == "V3_MAINTENANCE_REVISION_CONFLICT"
    assert conflict.value.status_code == 409
    assert conflict.value.details["current_revision"] == 2


@pytest.mark.asyncio
async def test_approved_source_remains_immutable_and_manual_edit_is_unapproved_draft(monkeypatch):
    factory, round2, result = await _generate("maintenance-approved", monkeypatch)
    approval = await round2.human_approve(
        result["master"]["entity_id"],
        projection_ids=result["projections"],
        checklist=_checklist(),
        approved_by="maintenance-owner",
        rationale="Exact revision reviewed.",
        actor_id="maintenance-owner",
        request_id="maintenance-approved:approve",
    )
    master_id = result["master"]["entity_id"]
    approved_revision = int(approval["master"]["revision"])
    approved_before = await factory.repository.get("MASTER_STORYBOARD", master_id, approved_revision)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    detail = await service.get_detail(master_id, approved_revision)
    stages = [{"stage_key": stage["stage_key"], "authored_text": stage["authored_text"]} for stage in detail["stages"]]
    stages[-1]["authored_text"] = "A manually edited CTA still requiring approval."
    saved = await service.create_manual_revision(
        master_id,
        source_revision=approved_revision,
        stages=stages,
        actor_id="maintenance-editor",
        request_id="maintenance-approved:edit",
    )
    approved_after = await factory.repository.get("MASTER_STORYBOARD", master_id, approved_revision)
    draft = await factory.repository.get("MASTER_STORYBOARD", master_id, saved["new_revision"])
    assert approved_after.model_dump(mode="json") == approved_before.model_dump(mode="json")
    assert draft.status == "DRAFT"
    assert saved["approval_carried_forward"] is False
    assert saved["production_authority_carried_forward"] is False
    assert (await service.get_detail(master_id, saved["new_revision"]))["approval_receipt"] is None


@pytest.mark.asyncio
async def test_delete_is_guarded_by_canonical_references_and_status(monkeypatch):
    factory, round2, result = await _generate("maintenance-delete", monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    master_id = result["master"]["entity_id"]

    db = await get_db()
    await db.execute(
        "UPDATE master_storyboard_v3 SET status='DRAFT' WHERE master_id=? AND revision=1",
        (master_id,),
    )
    await db.commit()
    with pytest.raises(V3FactoryError) as referenced:
        await service.delete_draft(
            master_id,
            1,
            actor_id="maintenance-operator",
            request_id="maintenance-delete:referenced",
        )
    assert referenced.value.code == "V3_DRAFT_REFERENCED"
    assert "DURATION_PROJECTION" in referenced.value.details["blockers"]

    approval = await round2.human_approve(
        master_id,
        projection_ids=result["projections"],
        checklist=_checklist(),
        approved_by="maintenance-owner",
        rationale="Exact revision reviewed.",
        actor_id="maintenance-owner",
        request_id="maintenance-delete:approve",
    )
    with pytest.raises(V3FactoryError) as terminal:
        await service.delete_draft(
            master_id,
            int(approval["master"]["revision"]),
            actor_id="maintenance-operator",
            request_id="maintenance-delete:approved",
        )
    assert terminal.value.code == "DRAFT_DELETE_ONLY"

    detail = await service.get_detail(master_id, int(approval["master"]["revision"]))
    draft = await service.create_manual_revision(
        master_id,
        source_revision=int(approval["master"]["revision"]),
        stages=[
            {"stage_key": stage["stage_key"], "authored_text": stage["authored_text"]}
            for stage in detail["stages"]
        ],
        actor_id="maintenance-editor",
        request_id="maintenance-delete:draft",
    )
    assert await service.delete_draft(
        master_id,
        int(draft["new_revision"]),
        actor_id="maintenance-operator",
        request_id="maintenance-delete:unreferenced-draft",
    ) is True
    assert await factory.repository.get("MASTER_STORYBOARD", master_id, int(draft["new_revision"])) is None


@pytest.mark.asyncio
async def test_reporting_http_routes_bind_exact_detail_and_revision_safe_save(monkeypatch):
    _factory, _round2, result = await _generate("maintenance-http", monkeypatch)
    master_id = result["master"]["entity_id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        listed = await client.get(
            "/api/storyboard-landbank/v3/copy-register/maintenance",
            params={"search": master_id, "limit": 1},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["master_id"] == master_id

        exact = await client.get(
            f"/api/storyboard-landbank/v3/copy-register/maintenance/{master_id}",
            params={"revision": 1},
        )
        assert exact.status_code == 200
        stages = [
            {"stage_key": stage["stage_key"], "authored_text": stage["authored_text"]}
            for stage in exact.json()["stages"]
        ]
        stages[0]["authored_text"] = "HTTP route exact revision edit."
        saved = await client.post(
            f"/api/storyboard-landbank/v3/copy-register/maintenance/{master_id}/revisions",
            headers={"X-Actor-Id": "maintenance-http", "X-Request-Id": "maintenance-http:save"},
            json={"source_revision": 1, "stages": stages},
        )
        assert saved.status_code == 201
        assert saved.json()["new_revision"] == 2
        assert saved.json()["master"]["status"] == "DRAFT"

        conflict = await client.post(
            f"/api/storyboard-landbank/v3/copy-register/maintenance/{master_id}/revisions",
            headers={"X-Actor-Id": "maintenance-http", "X-Request-Id": "maintenance-http:stale"},
            json={"source_revision": 1, "stages": stages},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "V3_MAINTENANCE_REVISION_CONFLICT"
