import pytest
import pytest_asyncio

from agent.authority import product_readiness_applicability_registry as registry
from agent.db import product_treatment_factory_crud as factory_crud
from agent.db.schema import get_db, init_db
from agent.models.product_readiness import (
    ProductReadinessEvaluateRequest,
    ProductReadinessProjection,
    ResolvedProductReadinessInput,
)
from agent.models.product_treatment_factory import (
    CreateFactoryPlanRequest,
    FactoryProductContext,
    PrepareFactoryPlanRequest,
)
from agent.services import product_treatment_factory_service as service
from agent.services.product_treatment_template_service import resolve_treatment_template


@pytest_asyncio.fixture(autouse=True)
async def _clean_factory_tables():
    await init_db()
    db = await get_db()
    await db.execute("DELETE FROM product_treatment_factory_event")
    await db.execute("DELETE FROM product_treatment_factory_task")
    await db.execute("DELETE FROM product_treatment_factory_plan")
    await db.commit()
    yield
    await db.execute("DELETE FROM product_treatment_factory_event")
    await db.execute("DELETE FROM product_treatment_factory_task")
    await db.execute("DELETE FROM product_treatment_factory_plan")
    await db.commit()


def _context(product_id: str) -> FactoryProductContext:
    return FactoryProductContext(
        product_id=product_id,
        selected_action_index=0,
        format="PGC",
        logical_mode="HYBRID",
        generation_mode="SINGLE",
        model_key="veo_3_1_fast",
        duration_seconds=8,
    )


def _scan(
    product_id: str,
    *,
    approved_copy: bool = False,
    approved_treatment: bool = False,
    error_code: str | None = None,
) -> service.ProductScan:
    context = _context(product_id)
    if error_code:
        return service.ProductScan(
            context=context,
            resolved=None,
            readiness=None,
            template=None,
            copy_preview={},
            treatments=[],
            error_code=error_code,
        )
    profile = next(item for item in registry.list_applicability_profiles() if item.supported)
    readiness_context = ProductReadinessEvaluateRequest(
        product_id=product_id,
        allowed_action_index=0,
        creative_format="PGC",
        logical_mode="HYBRID",
        generation_mode="SINGLE",
        model_key="veo_3_1_fast",
        duration_seconds=8,
    )
    copy_ids = ["copy-approved"] if approved_copy else []
    treatment_ids = ["treatment-approved"] if approved_treatment else []
    resolved = ResolvedProductReadinessInput.model_validate(
        {
            "context": readiness_context.model_dump(mode="json"),
            "product_authority_sha256": "a" * 64,
            "taxonomy": {
                "matched_scene_strategy_id": profile.scene_strategy_id,
                "specific_strategy": True,
            },
            "product_truth": {
                "snapshot_id": "truth-approved",
                "snapshot_sha256": "b" * 64,
                "snapshot_status": "APPROVED",
            },
            "copy": {
                "grounding_ready": True,
                "approved_copy_set_ids": copy_ids,
            },
            "selection": {
                "selection_id": "selection-approved",
                "status": "APPROVED",
                "selection_sha256": "c" * 64,
            },
            "assets": {
                "required_roles": ["PRODUCT_REFERENCE"],
                "eligible_asset_ids_by_role": {
                    "PRODUCT_REFERENCE": ["asset-approved"],
                },
                "missing_roles": [],
                "authority_sha256": "d" * 64,
            },
            "treatment": {
                "approved_treatment_ids": treatment_ids,
                "p6_ready": approved_treatment,
            },
        }
    )
    layer_names = (
        "taxonomy",
        "product_truth",
        "copy_grounding",
        "claim_safety",
        "action_evidence",
        "copy_set",
        "creative_selection",
        "visual_assets",
        "treatment_template",
        "treatment_instance",
        "p6",
    )
    readiness = ProductReadinessProjection(
        projection_version="test-v1",
        product_id=product_id,
        primary_status="READY" if approved_treatment else "REVIEW_REQUIRED",
        context=readiness_context,
        context_sha256="e" * 64,
        product_authority_sha256="a" * 64,
        taxonomy_fingerprint="f" * 64,
        applicability_profile=profile,
        selected_action=profile.indexed_actions[0],
        product_truth_snapshot_id="truth-approved",
        product_truth_snapshot_sha256="b" * 64,
        readiness_layers=[
            {
                "layer": name,
                "state": (
                    "READY"
                    if name
                    not in {
                        "copy_set" if not approved_copy else "",
                        "treatment_instance" if not approved_treatment else "",
                        "p6" if not approved_treatment else "",
                    }
                    else "BLOCKED"
                ),
                "blocker_codes": [],
            }
            for name in layer_names
        ],
        approved_copy_set_ids=copy_ids,
        approved_treatment_ids=treatment_ids,
        selected_treatment_ids=[],
        readiness_sha256="1" * 64,
    )
    template = resolve_treatment_template(
        context=readiness_context,
        profile=profile,
        requirements=[],
    )
    return service.ProductScan(
        context=context,
        resolved=resolved,
        readiness=readiness,
        template=template,
        copy_preview={"produced": 0 if approved_copy else 1},
        treatments=[],
        error_code=None,
    )


@pytest.mark.asyncio
async def test_create_plan_is_idempotent_and_isolates_blocked_products(monkeypatch):
    scans = {
        "product-a": _scan("product-a", approved_copy=True),
        "product-b": _scan("product-b", error_code="PRODUCT_TRUTH_REQUIRED"),
    }

    async def scan_product(context):
        return scans[context.product_id]

    monkeypatch.setattr(service, "_scan_product", scan_product)
    request = CreateFactoryPlanRequest(
        products=[_context("product-b"), _context("product-a")],
        created_by="factory-test",
    )

    first = await service.create_plan(request)
    second = await service.create_plan(request)

    assert first.plan_id == second.plan_id
    assert first.plan_identity_sha256 == second.plan_identity_sha256
    assert len(first.tasks) == 20
    assert len(second.tasks) == 20
    assert first.failure_count == 1
    blocked = [task for task in first.tasks if task.product_id == "product-b"]
    assert len(blocked) == 10
    assert {task.status for task in blocked} == {"REVIEW_REQUIRED"}


@pytest.mark.asyncio
async def test_prepare_continues_after_one_product_task_fails(monkeypatch):
    scans = {
        "product-a": _scan("product-a"),
        "product-b": _scan("product-b"),
    }

    async def scan_product(context):
        return scans[context.product_id]

    async def compose(product_id, count, *, dry_run):
        assert count == 1
        assert dry_run is False
        if product_id == "product-a":
            raise ValueError("COPY_COMPONENT_COMPOSITION_FAILED")
        return {
            "product_id": product_id,
            "created": 1,
            "produced": 1,
            "items": [{"copy_set_id": "copy-review-required"}],
        }

    monkeypatch.setattr(service, "_scan_product", scan_product)
    monkeypatch.setattr(service.copy_composer_service, "compose_and_persist", compose)
    plan = await service.create_plan(
        CreateFactoryPlanRequest(
            products=[_context("product-a"), _context("product-b")],
            created_by="factory-test",
        )
    )

    prepared = await service.prepare_plan(
        plan.plan_id,
        PrepareFactoryPlanRequest(
            actor_id="factory-test",
            materialize_treatment_candidates=False,
        ),
    )

    copy_tasks = {
        task.product_id: task
        for task in prepared.tasks
        if task.task_type == "COPY_COMPOSITION"
    }
    assert copy_tasks["product-a"].status == "FAILED"
    assert copy_tasks["product-b"].status == "REVIEW_REQUIRED"
    assert prepared.status == "COMPLETED_WITH_BLOCKERS"
    assert prepared.failure_count == 1


@pytest.mark.asyncio
async def test_existing_candidate_signature_is_reused_without_duplicate(monkeypatch):
    scan = _scan("product-a", approved_copy=True)
    template = scan.template
    assert template is not None
    task = {
        "task_id": "candidate-task",
        "plan_id": "factory-plan",
        "product_id": "product-a",
        "template_id": template.template_id,
        "template_sha256": template.template_sha256,
        "snapshot": service._task_snapshot(scan),
    }
    request = service._treatment_request_from_snapshot(task, created_by="factory-test")
    existing = {
        **request.model_dump(mode="json"),
        "treatment_id": "existing-treatment",
        "treatment_sha256": "9" * 64,
        "status": "DRAFT",
    }
    created_calls = 0

    async def list_treatments(**_kwargs):
        return [existing]

    async def create_treatment(_request):
        nonlocal created_calls
        created_calls += 1
        return existing

    monkeypatch.setattr(
        service.creative_treatment_service,
        "list_treatments",
        list_treatments,
    )
    monkeypatch.setattr(
        service.creative_treatment_service,
        "create_treatment",
        create_treatment,
    )

    status, result = await service._prepare_treatment_task(
        task,
        actor_id="factory-test",
    )

    assert status == "REVIEW_REQUIRED"
    assert result["created"] is False
    assert result["treatment_id"] == "existing-treatment"
    assert result["lineage"] == {
        "template_id": template.template_id,
        "template_sha256": template.template_sha256,
        "treatment_id": "existing-treatment",
        "treatment_sha256": "9" * 64,
    }
    assert created_calls == 0


@pytest.mark.asyncio
async def test_materialized_candidate_promotes_treatment_review_without_approval(
    monkeypatch,
):
    async def scan_product(_context):
        return _scan("product-a", approved_copy=True)

    async def list_treatments(**_kwargs):
        return []

    async def create_treatment(request):
        return {
            **request.model_dump(mode="json"),
            "treatment_id": "draft-treatment",
            "treatment_sha256": "8" * 64,
            "status": "DRAFT",
        }

    monkeypatch.setattr(service, "_scan_product", scan_product)
    monkeypatch.setattr(
        service.creative_treatment_service,
        "list_treatments",
        list_treatments,
    )
    monkeypatch.setattr(
        service.creative_treatment_service,
        "create_treatment",
        create_treatment,
    )
    plan = await service.create_plan(
        CreateFactoryPlanRequest(
            products=[_context("product-a")],
            created_by="factory-test",
        )
    )

    prepared = await service.prepare_plan(
        plan.plan_id,
        PrepareFactoryPlanRequest(
            actor_id="factory-test",
            materialize_copy_composition=False,
            materialize_treatment_candidates=True,
        ),
    )
    candidate = next(
        task for task in prepared.tasks if task.task_type == "TREATMENT_CANDIDATE"
    )
    review = next(
        task for task in prepared.tasks if task.task_type == "TREATMENT_REVIEW"
    )

    assert candidate.status == "REVIEW_REQUIRED"
    assert review.status == "REVIEW_REQUIRED"
    assert candidate.treatment_id == "draft-treatment"
    assert review.treatment_id == "draft-treatment"
    assert candidate.result["status"] == "DRAFT"
    assert "APPROVED" not in {candidate.result["status"], review.status}


@pytest.mark.asyncio
async def test_pause_and_resume_are_database_backed(monkeypatch):
    async def scan_product(_context):
        return _scan("product-a", approved_copy=True)

    monkeypatch.setattr(service, "_scan_product", scan_product)
    request = CreateFactoryPlanRequest(
        products=[_context("product-a")],
        created_by="factory-test",
    )
    plan = await service.create_plan(request)
    control = service.FactoryPlanControlRequest(
        actor_id="factory-test",
        reason="governed pause",
    )

    paused = await service.pause_plan(plan.plan_id, control)
    idempotent_rerun = await service.create_plan(request)
    resumed = await service.resume_plan(plan.plan_id, control)
    persisted = await factory_crud.get_plan(plan.plan_id)

    assert paused.status == "PAUSED"
    assert idempotent_rerun.plan_id == plan.plan_id
    assert idempotent_rerun.status == "PAUSED"
    assert resumed.status == "SCANNED"
    assert persisted is not None
    assert persisted["status"] == "SCANNED"


@pytest.mark.asyncio
async def test_scan_all_active_uses_canonical_product_id_column(monkeypatch):
    async def list_products(*, include_archived):
        assert include_archived is False
        return [{"id": "product-b"}, {"id": "product-a"}]

    monkeypatch.setattr(service.crud, "list_products", list_products)
    contexts = await service._resolve_contexts(
        CreateFactoryPlanRequest(
            scan_all_active=True,
            created_by="factory-test",
        )
    )

    assert [context.product_id for context in contexts] == ["product-a", "product-b"]


@pytest.mark.asyncio
async def test_product_scan_converts_unexpected_authority_failure_into_product_blocker(
    monkeypatch,
):
    async def resolve(_request):
        raise RuntimeError("AUTHORITY_READ_FAILED")

    monkeypatch.setattr(
        service.product_readiness_applicability_service,
        "resolve_readiness_input",
        resolve,
    )

    scan = await service._scan_product(_context("product-a"))

    assert scan.context.product_id == "product-a"
    assert scan.error_code == "AUTHORITY_READ_FAILED"
    assert scan.readiness is None


@pytest.mark.asyncio
async def test_product_scan_preserves_unsupported_taxonomy_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _scan("unsupported-product")
    assert baseline.resolved is not None
    assert baseline.readiness is not None
    unsupported = baseline.readiness.model_copy(
        update={
            "primary_status": "UNSUPPORTED_PRODUCT_TAXONOMY",
            "next_actions": ["VERIFY_SUPPORTED_PRODUCT_TAXONOMY"],
        }
    )

    async def resolve(_request):
        return baseline.resolved

    def evaluate(_resolved):
        return unsupported

    def reject_template(**_kwargs):
        raise RuntimeError("APPLICABILITY_PROFILE_UNSUPPORTED")

    monkeypatch.setattr(
        service.product_readiness_applicability_service,
        "resolve_readiness_input",
        resolve,
    )
    monkeypatch.setattr(
        service.product_readiness_applicability_service,
        "evaluate_resolved_readiness",
        evaluate,
    )
    monkeypatch.setattr(service, "resolve_treatment_template", reject_template)

    scan = await service._scan_product(_context("unsupported-product"))
    task_status, blocker_code, next_action = service._task_decision(
        scan,
        "PRODUCT_TRUTH_REVIEW",
    )

    assert scan.resolved is baseline.resolved
    assert scan.readiness is unsupported
    assert scan.readiness.primary_status == "UNSUPPORTED_PRODUCT_TAXONOMY"
    assert scan.error_code == "UNSUPPORTED_PRODUCT_TAXONOMY"
    assert task_status == "REVIEW_REQUIRED"
    assert blocker_code == "UNSUPPORTED_PRODUCT_TAXONOMY"
    assert next_action == "VERIFY_SUPPORTED_PRODUCT_TAXONOMY"


def test_t2v_factory_request_allows_zero_bindings_when_no_roles_are_required() -> None:
    scan = _scan("t2v-product", approved_copy=True)
    snapshot = service._task_snapshot(scan)
    context = dict(snapshot["context"])
    context["logical_mode"] = "T2V"
    snapshot["context"] = context
    resolved = dict(snapshot["resolved_authority"])
    assets = dict(resolved["assets"])
    assets["required_roles"] = []
    assets["eligible_asset_ids_by_role"] = {}
    assets["missing_roles"] = []
    resolved["assets"] = assets
    snapshot["resolved_authority"] = resolved
    template = dict(snapshot["treatment_template"])
    compatibility = dict(template["compatibility_profile"])
    compatibility["logical_mode"] = "T2V"
    compatibility["source_mode"] = "T2V"
    compatibility["required_asset_roles"] = []
    template["compatibility_profile"] = compatibility
    snapshot["treatment_template"] = template

    request = service._treatment_request_from_snapshot(
        {
            "task_id": "task-t2v",
            "product_id": "t2v-product",
            "snapshot": snapshot,
        },
        created_by="factory-test",
    )

    assert request.compatibility_profile.logical_mode == "T2V"
    assert request.compatibility_profile.required_asset_roles == []
    assert request.asset_bindings == []
