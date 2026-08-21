"""Provider-free proof for the Lapis 2 Phase 2 review queue."""
from __future__ import annotations

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import EvidenceFact, ProductTruthLineage
from agent.services import copy_register_review_queue_service as queue
from agent.services import copy_register_v2_service as v2
from tests.unit.test_copy_blueprint_v2_contract import _blueprint
from tests.unit.test_copy_register_v2_cutover import _seed_truth


_READINESS = {
    "readiness_validated": True,
    "provenance_validated": True,
    "safety_validated": True,
    "bridge_validated": True,
    "duration_validated": True,
}


async def _seed_draft(
    blueprint_id: str,
    *,
    claim_status: str = "CLAIM_SAFE_COPY_APPROVED",
    risk_level: str = "LOW",
):
    product, snapshot = await _seed_truth()
    db = await get_db()
    await db.execute(
        "UPDATE product SET claim_safe_copy_status=?, claim_risk_level=? WHERE id=?",
        (claim_status, risk_level, product["id"]),
    )
    await db.commit()
    proof = await v2.get_product_truth_proof(product["id"])
    lineage = ProductTruthLineage.model_validate(proof["product_truth"]["lineage"])
    fact = EvidenceFact.model_validate(proof["facts"][0])
    ref = fact.reference()
    base = _blueprint()
    stages = tuple(
        stage.model_copy(update={"fact_refs": (ref,) if stage.claim_bearing else ()})
        for stage in base.stages
    )
    blueprint = base.model_copy(
        update={
            "blueprint_id": blueprint_id,
            "product_id": product["id"],
            "stages": stages,
            "evidence_refs": (ref,),
            "product_truth_lineage": lineage,
            "target_duration_seconds": None,
        }
    )
    await v2._insert_blueprint(blueprint)
    return product, snapshot, blueprint


async def _make_current_truth_stale(product_id: str, snapshot: dict) -> None:
    await crud.create_product_intelligence_snapshot(
        product_id=product_id,
        version=int(snapshot["version"]) + 1,
        status="APPROVED",
        product_description=snapshot["product_description"],
        benefits_json=snapshot["benefits_json"],
        usp_json=snapshot["usp_json"],
        hook_angles_json=snapshot["hook_angles_json"],
        pain_points_json=snapshot["pain_points_json"],
        target_customer_text=snapshot["target_customer_text"],
        allowed_claims_json=snapshot["allowed_claims_json"],
        blocked_claims_json=snapshot["blocked_claims_json"],
        buyer_persona_snapshot_json=snapshot["buyer_persona_snapshot_json"],
        copy_strategy_summary_json=snapshot["copy_strategy_summary_json"],
        claim_gate="CLAIM_SAFE",
        claim_risk_level="LOW",
        approved_by="truth-reviewer-v2",
        approved_at="2026-08-21T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_review_queue_cross_product_annotations_and_safe_filter():
    safe_product, _, safe = await _seed_draft("bp-safe")
    risky_product, _, risky = await _seed_draft(
        "bp-risk", claim_status="CLAIM_SAFE_COPY_APPROVED", risk_level="HIGH"
    )

    result = await queue.list_review_queue()
    by_id = {item["blueprint_id"]: item for item in result["items"]}

    assert by_id[safe.blueprint_id]["product_id"] == safe_product["id"]
    assert by_id[safe.blueprint_id]["product_name"] == safe_product["product_display_name"]
    assert by_id[safe.blueprint_id]["formula_id"] == "PAS"
    assert by_id[safe.blueprint_id]["batch_approvable"] is True
    assert by_id[safe.blueprint_id]["draft_blocked_reason"] is None
    assert by_id[risky.blueprint_id]["claim_risk_level"] == "HIGH"
    assert by_id[risky.blueprint_id]["batch_approvable"] is False
    assert "CLAIM_RISK_HIGH" in by_id[risky.blueprint_id]["draft_blocked_reason"]

    safe_only = await queue.list_review_queue(only_claim_safe=True)
    assert [item["blueprint_id"] for item in safe_only["items"]] == [safe.blueprint_id]


@pytest.mark.asyncio
async def test_batch_approve_happy_path_is_human_attested_and_never_activates(monkeypatch):
    _, _, first = await _seed_draft("bp-batch-1")
    _, _, second = await _seed_draft("bp-batch-2")

    def fail_provider(*_args, **_kwargs):
        raise AssertionError("batch approval must not call the provider")

    monkeypatch.setattr(v2.ai_provider, "complete_json_with_receipt", fail_provider)

    db = await get_db()
    before = int((await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0])
    result = await queue.batch_approve_drafts(
        [first.blueprint_id, second.blueprint_id],
        reviewer="batch-reviewer",
        rationale="Reviewed every displayed draft against Product Truth and the five readiness gates.",
        readiness_proof_dict=_READINESS,
        confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
    )

    assert result["approved_count"] == 2
    assert [item["status"] for item in result["results"]] == ["APPROVED", "APPROVED"]
    assert all(item["production_status"] == "PRODUCTION_VALID" for item in result["results"])
    assert result["activation_mutations"] == 0
    assert result["provider_calls"] == 0
    after = int((await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0])
    assert after == before == 0

    approved = await v2.get_blueprint(first.blueprint_id)
    assert approved.semantic_review is not None
    assert approved.semantic_review.reviewer == "batch-reviewer"
    assert approved.semantic_review.decision == "APPROVED"
    assert approved.readiness_proof is not None
    assert all(approved.readiness_proof.model_dump(mode="python").values())


@pytest.mark.asyncio
async def test_batch_preflight_rejects_claim_risk_stale_bad_phrase_and_false_readiness():
    _, stale_snapshot, stale = await _seed_draft("bp-stale")
    await _make_current_truth_stale(stale.product_id, stale_snapshot)
    _, _, risky = await _seed_draft(
        "bp-high", claim_status="CLAIM_REVIEW_REQUIRED", risk_level="LOW"
    )

    with pytest.raises(queue.CopyRegisterReviewQueueError) as phrase_error:
        await queue.batch_approve_drafts(
            [risky.blueprint_id],
            reviewer="reviewer",
            rationale="rationale",
            readiness_proof_dict=_READINESS,
            confirmation_phrase="WRONG",
        )
    assert phrase_error.value.code == "INVALID_CONFIRMATION_PHRASE"

    with pytest.raises(queue.CopyRegisterReviewQueueError) as proof_error:
        await queue.batch_approve_drafts(
            [risky.blueprint_id],
            reviewer="reviewer",
            rationale="rationale",
            readiness_proof_dict={**_READINESS, "safety_validated": False},
            confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
        )
    assert proof_error.value.code == "COPY_V2_READINESS_REQUIRED"

    with pytest.raises(queue.CopyRegisterReviewQueueError) as risk_error:
        await queue.batch_approve_drafts(
            [risky.blueprint_id],
            reviewer="reviewer",
            rationale="rationale",
            readiness_proof_dict=_READINESS,
            confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
        )
    assert risk_error.value.code == "COPY_V2_BATCH_PREFLIGHT_FAILED"
    assert risk_error.value.details["items"][0]["error_code"] == "COPY_V2_CLAIM_SAFETY_BATCH_BLOCKED"

    with pytest.raises(queue.CopyRegisterReviewQueueError) as stale_error:
        await queue.batch_approve_drafts(
            [stale.blueprint_id],
            reviewer="reviewer",
            rationale="rationale",
            readiness_proof_dict=_READINESS,
            confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
        )
    assert stale_error.value.code == "COPY_V2_BATCH_PREFLIGHT_FAILED"
    assert stale_error.value.details["items"][0]["error_code"] == "COPY_V2_PRODUCT_TRUTH_STALE"


@pytest.mark.asyncio
async def test_batch_rerun_is_idempotent_and_does_not_change_authority():
    _, _, draft = await _seed_draft("bp-idempotent")
    first = await queue.batch_approve_drafts(
        [draft.blueprint_id],
        reviewer="reviewer",
        rationale="Explicit human review completed.",
        readiness_proof_dict=_READINESS,
        confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
    )
    assert first["approved_count"] == 1

    db = await get_db()
    before = int((await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0])
    with pytest.raises(queue.CopyRegisterReviewQueueError) as rerun_error:
        await queue.batch_approve_drafts(
            [draft.blueprint_id],
            reviewer="reviewer",
            rationale="Explicit human review completed.",
            readiness_proof_dict=_READINESS,
            confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
        )
    assert rerun_error.value.code == "COPY_V2_BATCH_PREFLIGHT_FAILED"
    assert rerun_error.value.details["items"][0]["error_code"] == "COPY_V2_BLUEPRINT_NOT_DRAFT"
    after = int((await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0])
    assert after == before == 0


async def _approve_for_activation(blueprint):
    result = await queue.batch_approve_drafts(
        [blueprint.blueprint_id],
        reviewer="activation-reviewer",
        rationale="Explicit human review completed against current Product Truth.",
        readiness_proof_dict=_READINESS,
        confirmation_phrase=queue.BATCH_APPROVAL_CONFIRMATION_PHRASE,
    )
    assert result["approved_count"] == 1


@pytest.mark.asyncio
async def test_activation_candidates_and_batch_bind_each_approved_product_to_all_required_lanes(
    monkeypatch,
):
    first_product, _, first = await _seed_draft("bp-activate-1")
    second_product, _, second = await _seed_draft("bp-activate-2")
    await _approve_for_activation(first)
    await _approve_for_activation(second)

    def fail_provider(*_args, **_kwargs):
        raise AssertionError("copy authority activation must not call the provider")

    monkeypatch.setattr(v2.ai_provider, "complete_json_with_receipt", fail_provider)

    candidates = await queue.list_activation_candidates()
    by_id = {item["blueprint_id"]: item for item in candidates["items"]}
    assert {first.blueprint_id, second.blueprint_id}.issubset(by_id)
    for blueprint, product in ((first, first_product), (second, second_product)):
        row = by_id[blueprint.blueprint_id]
        assert row["product_id"] == product["id"]
        assert row["status"] == "PRODUCTION_VALID"
        assert row["activatable"] is True
        assert row["current_authority_state"] == "NONE"
        assert row["required_lane_count"] == 8

    db = await get_db()
    before_binding = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_binding_v2")).fetchone())[0]
    )
    before_authority = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0]
    )
    result = await queue.batch_activate(
        [first.blueprint_id, second.blueprint_id],
        confirmation_phrase=queue.BATCH_ACTIVATION_CONFIRMATION_PHRASE,
        owner_authorization=True,
    )

    assert result["activated_count"] == 2
    assert result["idempotent_count"] == 0
    assert result["failed_count"] == 0
    assert result["bound_lane_count"] == 16
    assert result["activation_mutations"] == 2
    assert result["provider_calls"] == 0
    assert result["credit_spend"] == 0
    assert all(item["status"] == "ACTIVATED" for item in result["results"])
    assert all(item["lane_count"] == 8 for item in result["results"])

    after_binding = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_binding_v2")).fetchone())[0]
    )
    after_authority = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0]
    )
    assert after_binding - before_binding == 16
    assert after_authority - before_authority == 16
    cursor = await db.execute(
        """
        SELECT binding.blueprint_id, binding.binding_status, COUNT(authority.lane) AS lanes
        FROM copy_execution_binding_v2 binding
        JOIN copy_execution_authority_v2 authority ON authority.binding_id = binding.binding_id
        WHERE binding.blueprint_id IN (?, ?)
        GROUP BY binding.blueprint_id, binding.binding_status
        """,
        (first.blueprint_id, second.blueprint_id),
    )
    rows = await cursor.fetchall()
    assert {(row["blueprint_id"], row["binding_status"], int(row["lanes"])) for row in rows} == {
        (first.blueprint_id, "BOUND", 8),
        (second.blueprint_id, "BOUND", 8),
    }


@pytest.mark.asyncio
async def test_activation_preflight_rejects_stale_and_draft_before_any_mutation():
    _, stale_snapshot, stale = await _seed_draft("bp-activation-stale")
    _, _, draft = await _seed_draft("bp-activation-draft")
    await _approve_for_activation(stale)
    await _make_current_truth_stale(stale.product_id, stale_snapshot)

    db = await get_db()
    before = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0]
    )
    with pytest.raises(queue.CopyRegisterReviewQueueError) as error:
        await queue.batch_activate(
            [stale.blueprint_id, draft.blueprint_id],
            confirmation_phrase=queue.BATCH_ACTIVATION_CONFIRMATION_PHRASE,
            owner_authorization=True,
        )

    assert error.value.code == "COPY_V2_ACTIVATION_BATCH_PREFLIGHT_FAILED"
    details = {item["blueprint_id"]: item for item in error.value.details["items"]}
    assert details[stale.blueprint_id]["error_code"] in {
        "COPY_V2_PRODUCT_TRUTH_STALE",
        "COPY_V2_TAXONOMY_AUTHORITY_STALE",
    }
    assert details[draft.blueprint_id]["error_code"] == "EXPLICIT_HUMAN_APPROVAL_REQUIRED"
    after = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0]
    )
    assert after == before == 0


@pytest.mark.asyncio
async def test_activation_attestation_and_batch_cap_fail_closed():
    _, _, approved = await _seed_draft("bp-activation-attestation")
    await _approve_for_activation(approved)

    with pytest.raises(queue.CopyRegisterReviewQueueError) as phrase_error:
        await queue.batch_activate(
            [approved.blueprint_id],
            confirmation_phrase="WRONG",
            owner_authorization=True,
        )
    assert phrase_error.value.code == "INVALID_CONFIRMATION_PHRASE"

    with pytest.raises(queue.CopyRegisterReviewQueueError) as owner_error:
        await queue.batch_activate(
            [approved.blueprint_id],
            confirmation_phrase=queue.BATCH_ACTIVATION_CONFIRMATION_PHRASE,
            owner_authorization=False,
        )
    assert owner_error.value.code == "OWNER_AUTHORIZATION_REQUIRED"

    with pytest.raises(queue.CopyRegisterReviewQueueError) as cap_error:
        await queue.batch_activate(
            [f"bp-over-cap-{index}" for index in range(queue.ACTIVATION_BATCH_MAX + 1)],
            confirmation_phrase=queue.BATCH_ACTIVATION_CONFIRMATION_PHRASE,
            owner_authorization=True,
        )
    assert cap_error.value.code == "COPY_V2_ACTIVATION_BATCH_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_activation_rerun_is_idempotent_and_does_not_grow_authority():
    _, _, approved = await _seed_draft("bp-activation-idempotent")
    await _approve_for_activation(approved)
    first = await queue.batch_activate(
        [approved.blueprint_id],
        confirmation_phrase=queue.BATCH_ACTIVATION_CONFIRMATION_PHRASE,
        owner_authorization=True,
    )
    assert first["activated_count"] == 1

    db = await get_db()
    before = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0]
    )
    second = await queue.batch_activate(
        [approved.blueprint_id],
        confirmation_phrase=queue.BATCH_ACTIVATION_CONFIRMATION_PHRASE,
        owner_authorization=True,
    )

    assert second["activated_count"] == 0
    assert second["idempotent_count"] == 1
    assert second["failed_count"] == 0
    assert second["activation_mutations"] == 0
    assert second["bound_lane_count"] == 0
    assert second["results"] == [
        {
            "blueprint_id": approved.blueprint_id,
            "activated": False,
            "idempotent": True,
            "status": "ALREADY_ACTIVE",
            "lane_count": 8,
            "error_code": None,
        }
    ]
    after = int(
        (await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0]
    )
    assert after == before == 8
