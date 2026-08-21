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


@pytest.fixture(autouse=True)
async def _maintenance_test_database(tmp_path):
    """Keep this high-volume matrix suite off the shared pytest DB handle."""
    from agent.db import schema

    await schema.close_db()
    original_path = schema.DB_PATH
    schema.DB_PATH = tmp_path / "copy-landbank-maintenance.db"
    await schema.init_db()
    try:
        yield
    finally:
        await schema.close_db()
        schema.DB_PATH = original_path


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


async def _seed_filter_matrix(monkeypatch):
    """Create a disposable multi-product matrix for real SQL filter/sort proof."""
    specs = (
        ("filter-alpha", "DRAFT", "PAS", "alpha-angle", "2026-08-21T00:00:00Z", "Alpha Product"),
        ("filter-beta", "REVIEW_REQUIRED", "FAB", "beta-angle", "2026-08-19T00:00:00Z", "Beta Product"),
        ("filter-gamma", "VALIDATED", "PAS", "gamma-angle", "2026-08-20T00:00:00Z", "Gamma Product"),
        ("filter-delta", "APPROVED", "AIDA", "delta-angle", "2026-08-18T00:00:00Z", "Delta Product"),
    )
    generated: dict[str, dict[str, object]] = {}
    factory = None
    for product_id, status, formula_id, _angle_id, created_at, product_name in specs:
        factory, _round2, result = await _generate(product_id, monkeypatch)
        typed_master = await factory.repository.get("MASTER_STORYBOARD", result["master"]["entity_id"], 1)
        generated[product_id] = {
            "master_id": result["master"]["entity_id"],
            "status": status,
            "formula_id": formula_id,
            "angle_id": typed_master.angle.entity_id,
            "created_at": created_at,
            "product_name": product_name,
        }

    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    alpha_id = str(generated["filter-alpha"]["master_id"])
    alpha_detail = await service.get_detail(alpha_id, 1)
    alpha_stages = [
        {"stage_key": stage["stage_key"], "authored_text": stage["authored_text"]}
        for stage in alpha_detail["stages"]
    ]
    alpha_revision = await service.create_manual_revision(
        alpha_id,
        source_revision=1,
        stages=alpha_stages,
        actor_id="maintenance-filter-fixture",
        request_id="maintenance-filter-fixture:alpha-revision",
    )

    db = await get_db()
    for product_id, values in generated.items():
        await db.execute(
            "UPDATE product SET raw_product_title=?, product_display_name=? WHERE id=?",
            (values["product_name"], values["product_name"], product_id),
        )
        await db.execute(
            "UPDATE master_storyboard_v3 SET status=?, formula_id=?, angle_id=?, created_at=? WHERE master_id=? AND revision=1",
            (values["status"], values["formula_id"], values["angle_id"], values["created_at"], values["master_id"]),
        )
    await db.execute(
        "UPDATE master_storyboard_v3 SET status='DRAFT', formula_id='PAS', angle_id=?, created_at=? WHERE master_id=? AND revision=?",
        (generated["filter-alpha"]["angle_id"], "2026-08-22T00:00:00Z", alpha_id, int(alpha_revision["new_revision"])),
    )

    # Advance one approved truth snapshot so the existing stale predicate has a
    # real, current-vs-bound lineage difference to evaluate.
    truth_row = await (await db.execute(
        "SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND version=1",
        ("filter-gamma",),
    )).fetchone()
    truth = dict(truth_row)
    truth["snapshot_id"] = "filter-gamma-snapshot-v2"
    truth["version"] = 2
    truth["created_at"] = "2026-08-23T00:00:00Z"
    truth["updated_at"] = "2026-08-23T00:00:00Z"
    columns = list(truth)
    await db.execute(
        "INSERT INTO product_intelligence_snapshot (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")",
        [truth[column] for column in columns],
    )
    await db.commit()
    return factory, generated, {"alpha_revision": int(alpha_revision["new_revision"])}


async def _seed_production_ready_fixture(monkeypatch):
    factory, round2, result = await _generate("filter-production", monkeypatch)
    master_id = result["master"]["entity_id"]
    approval = await round2.human_approve(
        master_id,
        projection_ids=result["projections"],
        checklist=_checklist(),
        approved_by="maintenance-filter-fixture",
        rationale="Isolated production-ready filter fixture.",
        actor_id="maintenance-filter-fixture",
        request_id="maintenance-filter-fixture:approve",
    )
    master = approval["master"]
    projection = approval["projections"][0]
    receipt = approval["receipt"]
    db = await get_db()
    await db.execute(
        "UPDATE product SET raw_product_title='Production Product', product_display_name='Production Product' WHERE id=?",
        (master["product_id"],),
    )
    await db.execute(
        "INSERT INTO materialization_link_v3 ("
        "link_id, revision, product_id, master_id, master_revision, master_exact_content_digest, "
        "projection_id, projection_revision, projection_exact_digest, derivation_source, "
        "approval_receipt_id, approval_receipt_digest, v2_blueprint_id, v2_blueprint_revision, "
        "v2_approval_snapshot_id, product_truth_snapshot_id, product_truth_snapshot_version, "
        "product_truth_snapshot_digest, formula_id, formula_version, evidence_digest, "
        "target_duration_seconds, materializer_version, materialization_digest, status, source, "
        "supersedes_link_id, supersedes_link_revision, created_at, created_by"
        ") VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'DETERMINISTIC', ?, ?, 'fixture-v2-blueprint', 1, "
        "'fixture-v2-approval', ?, ?, ?, ?, ?, ?, ?, 'fixture-materializer', ?, 'PRODUCTION_VALID', "
        "'maintenance-filter-fixture', NULL, NULL, ?, 'maintenance-filter-fixture')",
        (
            "filter-production-link",
            master["product_id"],
            master["master_id"],
            master["revision"],
            master["exact_content_digest"],
            projection["projection_id"],
            projection["revision"],
            projection["exact_projection_digest"],
            receipt["receipt_id"],
            receipt["receipt_digest"],
            master["product_truth"]["snapshot_id"],
            master["product_truth"]["snapshot_version"],
            master["product_truth"]["snapshot_digest"],
            master["formula"]["formula_id"],
            master["formula"]["formula_version"],
            master["evidence_digest"],
            projection["target_duration_seconds"],
            "f" * 64,
            "2026-08-24T00:00:00Z",
        ),
    )
    await db.commit()
    return factory, master["master_id"], int(master["revision"])


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
            params={"search": master_id, "limit": 1, "sort_by": "revision", "sort_dir": "asc"},
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert listed_payload["total"] == 1
        assert listed_payload["items"][0]["master_id"] == master_id
        assert (listed_payload["sort_by"], listed_payload["sort_dir"]) == ("revision", "asc")

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


@pytest.mark.asyncio
async def test_product_filter_returns_only_matching_product(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(product_id="filter-beta")
    assert page["total"] == 1
    assert {item["product"]["id"] for item in page["items"]} == {"filter-beta"}


@pytest.mark.asyncio
async def test_status_filter_returns_only_matching_status(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(status="REVIEW_REQUIRED")
    assert page["total"] == 1
    assert {item["status"] for item in page["items"]} == {"REVIEW_REQUIRED"}


@pytest.mark.asyncio
async def test_formula_filter_returns_only_matching_formula(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(formula_id="FAB")
    assert page["total"] == 1
    assert page["items"][0]["formula"]["formula_id"] == "FAB"


@pytest.mark.asyncio
async def test_angle_filter_returns_only_matching_angle(monkeypatch):
    factory, generated, _meta = await _seed_filter_matrix(monkeypatch)
    gamma_angle = generated["filter-gamma"]["angle_id"]
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(angle_id=gamma_angle)
    assert page["total"] == 1
    assert page["items"][0]["angle"]["entity_id"] == gamma_angle


@pytest.mark.asyncio
async def test_production_ready_true_returns_materialization_linked_revision(monkeypatch):
    factory, master_id, revision = await _seed_production_ready_fixture(monkeypatch)

    async def fake_enrichment(payload):
        for item in payload["items"]:
            item["v2_materialization"] = "MATERIALIZED"
            for projection in item["projections"]:
                projection["materialization"] = {"status": "MATERIALIZED"}
        return payload

    monkeypatch.setattr(
        "agent.services.storyboard_landbank_v3_maintenance.supply_service.enrich_landbank_payload",
        fake_enrichment,
    )
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(production_ready=True)
    assert page["total"] == 1
    assert (page["items"][0]["master_id"], page["items"][0]["revision"]) == (master_id, revision)


@pytest.mark.asyncio
async def test_production_ready_false_excludes_materialization_linked_revision(monkeypatch):
    factory, master_id, revision = await _seed_production_ready_fixture(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(production_ready=False)
    assert all((item["master_id"], item["revision"]) != (master_id, revision) for item in page["items"])


@pytest.mark.asyncio
async def test_stale_filter_returns_advanced_truth_lineage(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(stale=True)
    assert page["total"] == 1
    assert {item["product"]["id"] for item in page["items"]} == {"filter-gamma"}


@pytest.mark.asyncio
async def test_current_truth_filter_excludes_advanced_truth_lineage(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(stale=False)
    assert page["total"] == 4
    assert all(item["product"]["id"] != "filter-gamma" for item in page["items"])


@pytest.mark.asyncio
async def test_text_search_matches_product_name(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(search="Gamma Product")
    assert page["total"] == 1
    assert page["items"][0]["product"]["id"] == "filter-gamma"


@pytest.mark.asyncio
async def test_combined_product_status_formula_filters_are_intersection(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(
        product_id="filter-alpha", status="DRAFT", formula_id="PAS",
    )
    assert page["total"] == 2
    assert {item["product"]["id"] for item in page["items"]} == {"filter-alpha"}
    assert {item["status"] for item in page["items"]} == {"DRAFT"}
    assert {item["formula"]["formula_id"] for item in page["items"]} == {"PAS"}


@pytest.mark.asyncio
async def test_total_count_is_independent_of_page_size(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(limit=1)
    assert page["total"] == 5
    assert len(page["items"]) == 1


@pytest.mark.asyncio
async def test_pagination_preserves_created_at_order(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    first = await service.list_records(sort_by="created_at", sort_dir="desc", limit=2, offset=0)
    second = await service.list_records(sort_by="created_at", sort_dir="desc", limit=2, offset=2)
    assert [item["created_at"] for item in first["items"]] == sorted(
        [item["created_at"] for item in first["items"]], reverse=True,
    )
    assert not {
        (item["master_id"], item["revision"]) for item in first["items"]
    } & {
        (item["master_id"], item["revision"]) for item in second["items"]
    }
    assert first["has_more"] is True


@pytest.mark.asyncio
async def test_created_at_ascending_sort_is_server_side(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(sort_by="created_at", sort_dir="asc")
    assert page["sort_by"] == "created_at"
    assert page["sort_dir"] == "asc"
    assert [item["created_at"] for item in page["items"]] == sorted(item["created_at"] for item in page["items"])


@pytest.mark.asyncio
async def test_created_at_descending_sort_is_default_and_server_side(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records()
    assert (page["sort_by"], page["sort_dir"]) == ("created_at", "desc")
    assert [item["created_at"] for item in page["items"]] == sorted(
        (item["created_at"] for item in page["items"]), reverse=True,
    )


@pytest.mark.asyncio
async def test_product_name_ascending_and_descending_sort(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    ascending = await service.list_records(sort_by="product_name", sort_dir="asc")
    descending = await service.list_records(sort_by="product_name", sort_dir="desc")
    asc_names = [item["product"]["name"] for item in ascending["items"]]
    desc_names = [item["product"]["name"] for item in descending["items"]]
    assert asc_names == sorted(asc_names, key=str.casefold)
    assert desc_names == sorted(desc_names, key=str.casefold, reverse=True)


@pytest.mark.asyncio
async def test_status_sorting_is_server_side(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(sort_by="status", sort_dir="asc")
    statuses = [item["status"] for item in page["items"]]
    assert statuses == sorted(statuses)


@pytest.mark.asyncio
async def test_formula_sorting_is_server_side(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(sort_by="formula", sort_dir="asc")
    formulas = [item["formula"]["formula_id"] for item in page["items"]]
    assert formulas == sorted(formulas)


@pytest.mark.asyncio
async def test_revision_sorting_is_server_side(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    page = await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(sort_by="revision", sort_dir="asc")
    revisions = [item["revision"] for item in page["items"]]
    assert revisions == sorted(revisions)
    assert revisions[0] == 1 and revisions[-1] == 2


@pytest.mark.asyncio
async def test_invalid_sort_by_is_rejected_before_sql_execution(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    with pytest.raises(V3FactoryError) as error:
        await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(sort_by="revision; DROP TABLE master_storyboard_v3")
    assert error.value.code == "MAINTENANCE_SORT_INVALID"


@pytest.mark.asyncio
async def test_invalid_sort_direction_is_rejected(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    with pytest.raises(V3FactoryError) as error:
        await V3CopywritingLandbankMaintenanceService(factory=factory).list_records(sort_dir="sideways")
    assert error.value.code == "MAINTENANCE_SORT_DIRECTION_INVALID"


@pytest.mark.asyncio
async def test_sort_inputs_cannot_inject_sql_and_canonical_table_remains_readable(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    with pytest.raises(V3FactoryError):
        await service.list_records(sort_by="created_at DESC, (SELECT 1)")
    db = await get_db()
    row = await (await db.execute("SELECT COUNT(*) AS n FROM master_storyboard_v3")).fetchone()
    assert int(row["n"]) == 5


@pytest.mark.asyncio
async def test_reporting_reads_are_provider_free_and_non_mutating(monkeypatch):
    factory, _generated, _meta = await _seed_filter_matrix(monkeypatch)
    service = V3CopywritingLandbankMaintenanceService(factory=factory)
    db = await get_db()
    before = await (await db.execute("SELECT COUNT(*) AS n FROM master_storyboard_v3")).fetchone()
    page = await service.list_records(search="filter", sort_by="revision", sort_dir="desc")
    after = await (await db.execute("SELECT COUNT(*) AS n FROM master_storyboard_v3")).fetchone()
    assert page["provider_calls"] == 0
    assert page["mutations"] == 0
    assert int(before["n"]) == int(after["n"]) == 5
