"""Macro Round 3 P1 — deterministic V3->V2 materializer coverage.

Zero provider calls, zero credit, disposable DB only.  Reuses the Round 2 seed
helpers to build genuine APPROVED V3 supply (master + duration projections +
human approval receipt), then proves deterministic, idempotent, exact-text
materialization to a V2 PRODUCTION_VALID blueprint and fail-closed revalidation.
"""

from __future__ import annotations

import json

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.models.storyboard_landbank_v3 import normalized_text
from agent.services import copy_register_v2_service as v2
from agent.services import product_strategy_taxonomy_service
from agent.services.copywriting_taxonomy_service import seed_copywriting_taxonomy_registry
from agent.services.storyboard_landbank_v3_factory import V3CopyFactoryService
from agent.services.storyboard_landbank_v3_materializer import (
    MaterializationError,
    V3ToV2Materializer,
    deterministic_blueprint_id,
)
from agent.services.storyboard_landbank_v3_round2 import V3CopyRegisterRound2Service

_CHECKLIST = {
    "semantic_reviewed": True,
    "product_truth_reviewed": True,
    "formula_reviewed": True,
    "evidence_reviewed": True,
    "bridge_reviewed": True,
    "safety_reviewed": True,
    "duration_reviewed": True,
}


async def _seed_v2_production_ready_v3_supply(product_id: str):
    """Seed a V2-PRODUCTION-READY Product Truth plus an aligned V3 supply chain.

    The Round 2 seed is deliberately minimal and its evidence ids do not align
    with the V2 ``_fact_candidates`` derivation, so it can never clear the V2
    PRODUCTION gate that ``materialize_projection`` enforces at step (6).  This
    helper reproduces the proven cutover ``_seed_truth`` pattern (ACTIVE product +
    resolvable taxonomy authority + APPROVED CLAIM_SAFE snapshot) and then seeds
    ``copy_evidence_fact_v2`` rows whose ids/text/digests are exactly the V2
    candidate facts, so every fact the V3 supply grounds on maps cleanly back to a
    V2 ``EvidenceReference``.  Returns ``(factory, recipe, angle, family)`` like
    ``_seed_round2_fixture`` so ``_approved_supply`` can drive it unchanged.
    """

    db = await get_db()
    # (1) Product row keyed by the caller's EXACT product_id (crud.create_product
    #     auto-generates its own id, which the truth-drift test cannot target).
    #     Every column below is required by the V2 truth gate's identity +
    #     taxonomy-authority resolution.
    await db.execute(
        "INSERT INTO product "
        "(id, source, raw_product_title, product_display_name, product_short_name, "
        "category, subcategory, type, product_type, product_type_id, "
        "copywriting_product_type_code, copywriting_angle, silo, bosmax_product_family, "
        "lifecycle_status, created_at, updated_at) "
        "VALUES (?, 'MANUAL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)",
        (
            product_id,
            "Minyak Warisan Cap Burung 25ml",
            "Minyak Warisan Cap Burung 25ml",
            "Minyak Warisan Cap Burung",
            "Health & Personal Care",
            "Traditional Wellness",
            "Traditional Herbal Oils",
            "TRADITIONAL_HERBAL_OIL",
            "BEAUTY_PERSONAL_CARE",
            "traditional_topical_oil",
            "Heritage-led Nusantara herbs and targeted topical wellness support",
            "baby_care_universal_01",
            "BEAUTY_PERSONAL_CARE",
            "2026-08-18T00:00:00Z",
            "2026-08-18T00:00:00Z",
        ),
    )
    await db.commit()
    product = await crud.get_product(product_id)

    # (2) ACTIVE copywriting taxonomy registry + a VERIFIED/READY strategy
    #     authority so the truth gate resolves with EMPTY blockers.
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )
    strategy_candidate = product_strategy_taxonomy_service.build_product_strategy_taxonomy_candidate(
        product,
        materialization_status="MATERIALIZED",
    ).model_copy(
        update={
            "cluster": "traditional_wellness",
            "product_type_group": "traditional_herbal_oil",
            "scene_coverage_status": "COVERED",
            "specific_strategy": True,
            "review_status": "VERIFIED",
            "consumer_status": "READY",
            "authority_source": "MANUAL_OVERRIDE",
            "reviewer_id": "synthetic-strategy-reviewer",
            "reviewer_note": "Synthetic fixture has an explicit reviewed strategy authority.",
            "reviewed_at": "2026-08-14T00:00:00Z",
        }
    )
    await crud.upsert_manual_product_strategy_taxonomy(
        product_strategy_taxonomy_service._taxonomy_to_record(strategy_candidate)
    )

    # (3) APPROVED, CLAIM_SAFE Product Truth snapshot with every V2-required field.
    snapshot = await crud.create_product_intelligence_snapshot(
        product_id=product_id,
        version=1,
        status="APPROVED",
        product_description="A lightweight serum for a simple daily routine.",
        benefits_json=json.dumps(["menyerap cepat", "tekstur ringan"]),
        usp_json=json.dumps(["formula ringan"]),
        hook_angles_json=json.dumps(["rutin harian yang ringkas"]),
        pain_points_json=json.dumps(["rutin terasa leceh"]),
        target_customer_text="Pembeli yang mahu rutin mudah.",
        allowed_claims_json=json.dumps(["formula ringan", "menyerap cepat"]),
        blocked_claims_json=json.dumps(["menyembuhkan"]),
        buyer_persona_snapshot_json=json.dumps({"audience": "pembeli rutin harian"}),
        copy_strategy_summary_json=json.dumps({"angle": "rutin harian yang ringkas"}),
        claim_gate="CLAIM_SAFE",
        claim_risk_level="LOW",
        approved_by="synthetic-truth-reviewer",
        approved_at="2026-08-14T00:00:00Z",
    )

    # (4) copy_evidence_fact_v2 rows aligned EXACTLY to v2._fact_candidates, so the
    #     V3 evidence adapter grounds on the same ids the materializer maps back
    #     into V2 EvidenceReferences (identical fact_id, canonical_text, digest,
    #     kind).  The V3 fake provider grounds claim-bearing stages on facts[0],
    #     so seeding the whole candidate set guarantees the referenced id aligns.
    candidates = v2._fact_candidates(product, snapshot)
    for fact in candidates:
        await db.execute(
            "INSERT INTO copy_evidence_fact_v2 "
            "(product_id, snapshot_id, fact_id, fact_kind, canonical_text, text_digest, "
            "snapshot_version, snapshot_status, approved, source_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED', 1, ?, ?)",
            (
                fact.product_id,
                fact.snapshot_id,
                fact.fact_id,
                fact.fact_kind,
                fact.text,
                fact.text_digest,
                fact.snapshot_version,
                fact.source_ref,
                "2026-08-18T00:00:00Z",
            ),
        )
    await db.commit()
    grounding_fact_id = candidates[0].fact_id

    # (5) Genuine V3 supply grounded on an aligned approved fact id.
    factory = V3CopyFactoryService()
    angle = await factory.create_angle(
        product_id,
        {
            "angle_id": f"{product_id}-angle",
            "definition": "A lightweight daily routine angle for qualified buyers",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "Drive a safe trial",
            "evidence_fact_ids": [grounding_fact_id],
        },
        actor_id="mat-fixture",
        request_id=f"{product_id}:angle",
    )
    family = await factory.create_storyline_family(
        product_id,
        {
            "family_id": f"{product_id}-family",
            "angle_id": angle.angle_id,
            "formula_id": "PAS",
            "objective_compatibility": {"objective_ids": ["conversion"]},
            "reviewed_definition": "One continuous daily routine route for the buyer",
        },
        actor_id="mat-fixture",
        request_id=f"{product_id}:family",
    )
    recipe = await factory.create_recipe(
        product_id,
        {
            "recipe_id": f"{product_id}-recipe",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "Drive a safe trial",
            "target_angles": [{"entity_id": angle.angle_id, "revision": angle.revision}],
            "component_count_targets": {"HOOK": 1, "BODY_CORE": 1, "CTA": 1},
            "supported_durations_seconds": [8, 16, 24],
        },
        actor_id="mat-fixture",
        request_id=f"{product_id}:recipe",
    )
    return factory, recipe, angle, family


async def _approved_supply(monkeypatch, product_id: str):
    monkeypatch.setenv("V3_ROUND2_FAKE_PROVIDER", "1")
    factory, recipe, _angle, _family = await _seed_v2_production_ready_v3_supply(product_id)
    svc = V3CopyRegisterRound2Service(factory=factory)
    plan = await svc.plan_assistant(
        recipe.product_id, recipe.recipe_id, mode="CREATE",
        actor_id="op", request_id="plan",
    )
    result = await svc.execute_assistant(
        plan.plan_id, actor_id="op", request_id="exec", provider_mode="FAKE_TEST"
    )
    approval = await svc.human_approve(
        result["master"]["entity_id"],
        projection_ids=result["projections"],
        checklist=_CHECKLIST,
        approved_by="owner",
        rationale="Reviewed storyboard, evidence, formula, bridge, safety, durations.",
        actor_id="owner",
        request_id="approve",
    )
    assert approval["master"]["status"] == "APPROVED"
    return svc, result, approval


async def _first_projection_id(master_id: str) -> str:
    db = await get_db()
    row = await (
        await db.execute(
            "SELECT projection_id FROM duration_projection_v3 "
            "WHERE master_id=? AND status='APPROVED' "
            "ORDER BY target_duration_seconds LIMIT 1",
            (master_id,),
        )
    ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.asyncio
async def test_materialize_approved_projection_to_production_valid(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "mat-happy")
    master_id = result["master"]["entity_id"]
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = await _first_projection_id(master_id)

    mat = V3ToV2Materializer(v3=svc)
    out = await mat.materialize_projection(projection_id=projection_id, receipt_id=receipt_id)

    assert out["status"] == "PRODUCTION_VALID"
    assert out["idempotent_reuse"] is False
    blueprint = out["blueprint"]
    assert blueprint.status == "PRODUCTION_VALID"
    assert blueprint.blueprint_id == deterministic_blueprint_id(
        product_id=out["link_inputs"]["product_id"],
        projection_id=projection_id,
        projection_revision=out["link_inputs"]["projection_revision"],
        projection_exact_digest=out["link_inputs"]["projection_exact_digest"],
    )

    # Exact human-approved projected text is preserved verbatim into V2 stages.
    projection = await svc.factory.repository.get(
        "DURATION_PROJECTION", projection_id, None
    )
    present = sorted(
        (s for s in projection.stage_allocations if s.omission_state != "OMITTED"),
        key=lambda s: s.order,
    )
    assert [normalized_text(s.projected_text) for s in present] == [
        stage.authored_text for stage in blueprint.stages
    ]

    # Genuine carry-forward provenance (never fabricated).
    provenance = {p.key: p.value for p in blueprint.provenance}
    assert provenance["approval_source"] == "V3_HUMAN_APPROVAL_CARRY_FORWARD"
    assert provenance["v3_approval_receipt_id"] == receipt_id
    assert blueprint.semantic_review is not None
    assert blueprint.semantic_review.decision == "APPROVED"
    assert blueprint.semantic_review.reviewer == "owner"
    assert receipt_id in blueprint.semantic_review.rationale
    assert blueprint.approval_snapshot is not None
    assert out["v2_approval_snapshot_id"] == blueprint.approval_snapshot.approval_snapshot_id


@pytest.mark.asyncio
async def test_materialize_is_deterministic_and_idempotent(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "mat-idem")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = await _first_projection_id(result["master"]["entity_id"])

    mat = V3ToV2Materializer(v3=svc)
    first = await mat.materialize_projection(projection_id=projection_id, receipt_id=receipt_id)
    second = await mat.materialize_projection(projection_id=projection_id, receipt_id=receipt_id)

    assert first["blueprint_id"] == second["blueprint_id"]
    assert first["status"] == second["status"] == "PRODUCTION_VALID"
    assert second["idempotent_reuse"] is True

    db = await get_db()
    count = await (
        await db.execute(
            "SELECT COUNT(*) FROM copy_blueprint_v2 WHERE blueprint_id=?",
            (first["blueprint_id"],),
        )
    ).fetchone()
    assert count[0] == 1


@pytest.mark.asyncio
async def test_materialize_fails_closed_on_unknown_receipt(monkeypatch):
    svc, result, _approval = await _approved_supply(monkeypatch, "mat-badreceipt")
    projection_id = await _first_projection_id(result["master"]["entity_id"])
    mat = V3ToV2Materializer(v3=svc)
    with pytest.raises(MaterializationError) as excinfo:
        await mat.materialize_projection(
            projection_id=projection_id, receipt_id="receipt-does-not-exist"
        )
    assert excinfo.value.code == "MATERIALIZATION_RECEIPT_NOT_FOUND"


@pytest.mark.asyncio
async def test_materialize_fails_closed_on_product_truth_drift(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "mat-truthdrift")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = await _first_projection_id(result["master"]["entity_id"])

    # Product Truth advances to a newer APPROVED snapshot -> the V3 approval is
    # now against a stale snapshot; materialization must fail closed.
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES ('mat-truthdrift-snap2','mat-truthdrift',2,'APPROVED','Newer description.', "
        "'[\"newer benefit\"]','[\"newer usp\"]','newer customer','[\"newer claim\"]','{\"a\":1}','{\"f\":\"PAS\"}', "
        "'CLAIM_SAFE','LOW','2026-08-18T00:00:00Z','2026-08-18T00:00:00Z')",
    )
    await db.commit()

    mat = V3ToV2Materializer(v3=svc)
    with pytest.raises(MaterializationError) as excinfo:
        await mat.materialize_projection(projection_id=projection_id, receipt_id=receipt_id)
    assert excinfo.value.code == "MATERIALIZATION_TRUTH_STALE"
