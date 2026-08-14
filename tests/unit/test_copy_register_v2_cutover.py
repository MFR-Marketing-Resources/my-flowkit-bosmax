"""Persistent formula-native Copy Register V2 cutover proof.

All data is synthetic and local.  The fixture never calls a provider and the
legacy ledgers are measured before/after to prove they are untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.authority.copy_lane_matrix import IMAGE_LANES, VIDEO_LANES
from agent.db import crud
from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import (
    CopyBlueprintV2FeatureFlagState,
    ProductionReadinessProof,
    SemanticReviewProof,
)
from agent.services import copy_register_v2_service as service
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)


async def _seed_truth():
    product = await crud.create_product(
        raw_product_title="V2 Synthetic Product",
        source="MANUAL",
        product_display_name="V2 Synthetic Product",
        product_short_name="V2 Product",
        category="Skincare",
        subcategory="Serum",
        type="Topical",
    )
    snapshot = await crud.create_product_intelligence_snapshot(
        product_id=product["id"],
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
    return product, snapshot


async def _counts():
    db = await get_db()
    counts = {}
    for table in ("copy_set", "copy_component", "copy_blueprint_v2", "copy_evidence_fact_v2", "copy_execution_binding_v2"):
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cursor.fetchone()
        counts[table] = int(row[0])
    return counts


def _readiness() -> ProductionReadinessProof:
    return ProductionReadinessProof(
        readiness_validated=True,
        provenance_validated=True,
        safety_validated=True,
        bridge_validated=True,
        duration_validated=True,
    )


def _review() -> SemanticReviewProof:
    return SemanticReviewProof(
        decision="APPROVED",
        reviewer="synthetic-semantic-reviewer",
        rationale="Every claim-bearing stage was checked against approved Product Truth facts.",
        reviewed_at="2026-08-14T00:10:00Z",
    )


@pytest.mark.asyncio
async def test_new_button_workflow_is_v2_only_and_legacy_rows_do_not_change():
    product, _snapshot = await _seed_truth()
    before = await _counts()

    angles = await service.generate_angle_options(product["id"], "PAS")
    assert angles["provider_calls"] == 0
    assert angles["credit_spend"] == 0
    selected_angle = angles["angles"][0]
    selected_facts = [fact["fact_id"] for fact in angles["facts"][:5]]
    blueprint = await service.generate_blueprint(
        product_id=product["id"],
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="Help a qualified buyer choose a grounded next step.",
        angle_id=selected_angle["angle_id"],
        angle_definition=selected_angle["definition"],
        evidence_fact_ids=selected_facts,
    )
    assert blueprint.blueprint_id.startswith("bpv2_")
    assert blueprint.status == "DRAFT"
    assert not hasattr(blueprint, "copy_set_id")
    assert len(blueprint.stages) == 4
    assert [stage.formula_stage_key for stage in blueprint.stages] == ["problem", "agitate", "solution", "cta"]

    after_generate = await _counts()
    assert after_generate["copy_set"] == before["copy_set"]
    assert after_generate["copy_component"] == before["copy_component"]
    assert after_generate["copy_blueprint_v2"] == before["copy_blueprint_v2"] + 1
    assert after_generate["copy_evidence_fact_v2"] >= len(selected_facts)

    approved = await service.approve_blueprint(
        blueprint.blueprint_id,
        approved_by="synthetic-operator",
        semantic_review=_review(),
        readiness_proof=_readiness(),
    )
    assert approved.status == "PRODUCTION_VALID"
    assert approved.approval_snapshot is not None
    assert approved.semantic_review == _review()
    assert approved.readiness_proof == _readiness()

    revised = await service.regenerate_stage(approved.blueprint_id, approved.stages[0].stage_key)
    assert revised.revision == 2
    assert revised.status == "DRAFT"
    assert revised.supersedes is not None
    assert revised.supersedes.revision == 1
    old = await service.get_blueprint(approved.blueprint_id, 1)
    assert old.status == "PRODUCTION_VALID"
    assert old.approval_snapshot is not None

    after_revision = await _counts()
    assert after_revision["copy_set"] == before["copy_set"]
    assert after_revision["copy_component"] == before["copy_component"]
    assert after_revision["copy_blueprint_v2"] == before["copy_blueprint_v2"] + 2


@pytest.mark.asyncio
async def test_persisted_binding_is_lineage_complete_for_all_required_lanes():
    product, _snapshot = await _seed_truth()
    angles = await service.generate_angle_options(product["id"], "PAS")
    bp = await service.generate_blueprint(
        product_id=product["id"],
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="A grounded conversion objective.",
        angle_id=angles["angles"][0]["angle_id"],
        angle_definition=angles["angles"][0]["definition"],
        evidence_fact_ids=[fact["fact_id"] for fact in angles["facts"][:2]],
    )
    approved = await service.approve_blueprint(
        bp.blueprint_id,
        approved_by="synthetic-operator",
        semantic_review=_review(),
        readiness_proof=_readiness(),
    )
    flags = CopyBlueprintV2FeatureFlagState(
        enabled=True,
        scope="copy-register-v2-test",
        pilot_scope=("copy-register-v2-test",),
        state="PILOT",
    )
    for lane in (*VIDEO_LANES, "POSTER_BUILDER"):
        binding = await service.bind_blueprint(
            blueprint_id=approved.blueprint_id,
            lane=lane,
            feature_flags=flags,
        )
        assert binding.blueprint_id == approved.blueprint_id
        assert binding.revision == approved.revision
        assert binding.formula_id == "PAS"
        assert binding.approval_snapshot_id == approved.approval_snapshot.approval_snapshot_id
        assert binding.product_truth_lineage.snapshot_id == approved.product_truth_lineage.snapshot_id
        assert binding.evidence_lineage.fact_ids
        assert binding.feature_flag_state.state == "PILOT"
    assert (await _counts())["copy_execution_binding_v2"] == len(VIDEO_LANES) + 1


@pytest.mark.asyncio
async def test_missing_semantic_review_and_stale_truth_fail_closed():
    product, _snapshot = await _seed_truth()
    angles = await service.generate_angle_options(product["id"], "PAS")
    bp = await service.generate_blueprint(
        product_id=product["id"],
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="A grounded objective.",
        angle_id=angles["angles"][0]["angle_id"],
        angle_definition=angles["angles"][0]["definition"],
        evidence_fact_ids=[angles["facts"][0]["fact_id"]],
    )
    with pytest.raises(service.CopyRegisterV2Error) as missing_review:
        await service.approve_blueprint(
            bp.blueprint_id,
            approved_by="synthetic-operator",
            semantic_review=SemanticReviewProof(
                decision="REJECTED",
                reviewer="reviewer",
                rationale="Not approved",
                reviewed_at="2026-08-14T00:00:00Z",
            ),
            readiness_proof=_readiness(),
        )
    assert missing_review.value.code == "COPY_V2_SEMANTIC_REVIEW_REQUIRED"

    db = await get_db()
    await db.execute(
        """
        INSERT INTO product_intelligence_snapshot
        (snapshot_id, product_id, version, status, product_description, benefits_json, usp_json,
         target_customer_text, allowed_claims_json, buyer_persona_snapshot_json,
         copy_strategy_summary_json, claim_gate, claim_risk_level, approved_by, approved_at,
         created_at, updated_at)
        VALUES (?, ?, ?, 'APPROVED', ?, ?, ?, ?, ?, ?, ?, 'CLAIM_SAFE', 'LOW', ?, ?, ?, ?)
        """,
        (
            "snapshot-v2-stale", product["id"], 2,
            "A newer approved truth.", json.dumps(["new benefit"]), json.dumps(["new usp"]),
            "A buyer", json.dumps(["new claim"]), json.dumps({"audience": "buyer"}),
            json.dumps({"angle": "new angle"}), "reviewer", "2026-08-14T00:20:00Z",
            "2026-08-14T00:20:00Z", "2026-08-14T00:20:00Z",
        ),
    )
    await db.commit()
    with pytest.raises(service.CopyRegisterV2Error) as stale:
        await service.approve_blueprint(
            bp.blueprint_id,
            approved_by="synthetic-operator",
            semantic_review=_review(),
            readiness_proof=_readiness(),
        )
    assert stale.value.code == "COPY_V2_PRODUCT_TRUTH_STALE"


@pytest.mark.asyncio
async def test_claim_review_required_truth_is_not_production_ready():
    product, snapshot = await _seed_truth()
    db = await get_db()
    await db.execute(
        "UPDATE product_intelligence_snapshot SET claim_gate='CLAIM_REVIEW_REQUIRED' WHERE snapshot_id=?",
        (snapshot["snapshot_id"],),
    )
    await db.commit()

    proof = await service.get_product_truth_proof(product["id"])
    assert proof["ready_for_copy"] is False
    assert proof["blockers"] == ["V2_PRODUCT_TRUTH_CLAIM_REVIEW_REQUIRED"]
    with pytest.raises(service.CopyRegisterV2Error) as blocked:
        await service.generate_angle_options(product["id"], "PAS")
    assert blocked.value.code == "V2_PRODUCT_TRUTH_CLAIM_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_product_truth_digest_covers_angle_and_evidence_authority_fields():
    product, snapshot = await _seed_truth()
    first = await service.get_product_truth_proof(product["id"])
    db = await get_db()
    await db.execute(
        "UPDATE product_intelligence_snapshot SET hook_angles_json=? WHERE snapshot_id=?",
        (json.dumps(["a materially changed grounded angle"]), snapshot["snapshot_id"]),
    )
    await db.commit()
    second = await service.get_product_truth_proof(product["id"])
    assert (
        first["product_truth"]["lineage"]["snapshot_digest"]
        != second["product_truth"]["lineage"]["snapshot_digest"]
    )


@pytest.mark.asyncio
async def test_approved_blueprint_is_immutable_at_database_boundary():
    product, _snapshot = await _seed_truth()
    angles = await service.generate_angle_options(product["id"], "PAS")
    bp = await service.generate_blueprint(
        product_id=product["id"],
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="A grounded objective.",
        angle_id=angles["angles"][0]["angle_id"],
        angle_definition=angles["angles"][0]["definition"],
        evidence_fact_ids=[angles["facts"][0]["fact_id"]],
    )
    approved = await service.approve_blueprint(
        bp.blueprint_id,
        approved_by="synthetic-operator",
        semantic_review=_review(),
        readiness_proof=_readiness(),
    )
    db = await get_db()
    with pytest.raises(Exception, match="COPY_V2_APPROVED_IMMUTABLE"):
        await db.execute(
            "UPDATE copy_blueprint_v2 SET formula_id='HSO' WHERE blueprint_id=? AND revision=?",
            (approved.blueprint_id, approved.revision),
        )
    await db.rollback()


@pytest.mark.asyncio
async def test_consumers_read_the_persisted_binding_and_copy_free_lanes_stay_explicit():
    product, _snapshot = await _seed_truth()
    angles = await service.generate_angle_options(product["id"], "PAS")
    blueprint = await service.generate_blueprint(
        product_id=product["id"],
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="A grounded conversion objective.",
        angle_id=angles["angles"][0]["angle_id"],
        angle_definition=angles["angles"][0]["definition"],
        evidence_fact_ids=[fact["fact_id"] for fact in angles["facts"][:2]],
    )
    approved = await service.approve_blueprint(
        blueprint.blueprint_id,
        approved_by="synthetic-operator",
        semantic_review=_review(),
        readiness_proof=_readiness(),
    )
    flags = CopyBlueprintV2FeatureFlagState(
        enabled=True,
        scope="copy-register-v2-test",
        pilot_scope=("copy-register-v2-test",),
        state="PILOT",
    )
    required_lanes = (*VIDEO_LANES, "POSTER_BUILDER")
    for lane in required_lanes:
        await service.bind_blueprint(
            blueprint_id=approved.blueprint_id,
            lane=lane,
            feature_flags=flags,
        )

    for lane in required_lanes:
        resolved = await resolve_persisted_copy_execution_binding(
            product["id"], lane, {"feature_flags": flags}
        )
        assert resolved.ready is True
        assert resolved.binding is not None
        assert resolved.binding.blueprint_id == approved.blueprint_id
        assert resolved.binding.revision == approved.revision
        assert resolved.binding.approval_snapshot_id == approved.approval_snapshot.approval_snapshot_id
        assert resolved.compiler_copy_intelligence["blueprint_id"] == approved.blueprint_id
        assert resolved.compiler_copy_intelligence["revision"] == approved.revision
        assert resolved.approved_dialogue == " ".join(
            item.text for item in approved.approved_execution_text
        )

    for lane in set(IMAGE_LANES) - {"POSTER_BUILDER"}:
        resolved = await resolve_persisted_copy_execution_binding(
            product["id"],
            lane,
            {
                "feature_flags": flags,
                "readiness_validated": True,
                "provenance_validated": True,
                "safety_validated": True,
            },
        )
        assert resolved.ready is True
        assert resolved.copy_policy == "NOT_REQUIRED"
        assert resolved.binding is None
        assert resolved.projection is not None
        assert resolved.projection.copy_required is False


@pytest.mark.asyncio
async def test_persisted_required_consumer_fails_closed_without_binding():
    product, _snapshot = await _seed_truth()
    flags = CopyBlueprintV2FeatureFlagState(
        enabled=True,
        scope="copy-register-v2-test",
        pilot_scope=("copy-register-v2-test",),
        state="PILOT",
    )
    with pytest.raises(CopyExecutionResolutionError) as missing:
        await resolve_persisted_copy_execution_binding(product["id"], "T2V", {"feature_flags": flags})
    assert missing.value.code == "V2 BINDING REQUIRED"


@pytest.mark.asyncio
async def test_formula_and_evidence_selection_fail_closed_without_defaults_or_invention():
    product, _snapshot = await _seed_truth()
    with pytest.raises(service.CopyRegisterV2Error) as missing_formula:
        await service.generate_blueprint(
            product_id=product["id"],
            formula_id="",
            objective_id="conversion",
            objective_definition="A grounded objective.",
            angle_id="angle:missing",
            angle_definition="Missing",
            evidence_fact_ids=["fact:missing"],
        )
    assert missing_formula.value.code == "COPY_V2_FORMULA_REQUIRED"

    angles = await service.generate_angle_options(product["id"], "PAS")
    assert len(angles["facts"]) >= 6
    request = {
        "product_id": product["id"],
        "formula_id": "PAS",
        "objective_id": "conversion",
        "objective_definition": "A grounded objective.",
        "angle_id": angles["angles"][0]["angle_id"],
        "angle_definition": angles["angles"][0]["definition"],
    }
    with pytest.raises(service.CopyRegisterV2Error) as too_many:
        await service.generate_blueprint(
            **request,
            evidence_fact_ids=[fact["fact_id"] for fact in angles["facts"][:6]],
        )
    assert too_many.value.code == "COPY_V2_EVIDENCE_LIMIT"

    with pytest.raises(service.CopyRegisterV2Error) as invented:
        await service.generate_blueprint(
            **request,
            evidence_fact_ids=["fact:invented:not-in-product-truth"],
        )
    assert invented.value.code == "COPY_V2_EVIDENCE_INVALID"


@pytest.mark.asyncio
async def test_referenced_legacy_history_is_retained_but_never_selectable_or_deduped_into_v2():
    product, _snapshot = await _seed_truth()
    legacy = await crud.create_copy_set(
        product["id"],
        angle="legacy angle",
        hook="legacy hook",
        dedupe_key="shared-dedupe-key",
        source="LEGACY_TEST",
    )
    db = await get_db()
    await db.execute(
        """
        INSERT INTO creative_variation_group
        (group_id, product_id, copy_set_id, dialogue_sha256, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "legacy-reference-group",
            product["id"],
            legacy["copy_set_id"],
            "a" * 64,
            "synthetic-history-test",
        ),
    )
    await db.commit()

    angles = await service.generate_angle_options(product["id"], "PAS")
    request = {
        "product_id": product["id"],
        "formula_id": "PAS",
        "objective_id": "conversion",
        "objective_definition": "A grounded objective.",
        "angle_id": angles["angles"][0]["angle_id"],
        "angle_definition": angles["angles"][0]["definition"],
        "evidence_fact_ids": [angles["facts"][0]["fact_id"]],
    }
    first = await service.generate_blueprint(**request)
    second = await service.generate_blueprint(**request)
    active = await service.list_blueprints(product["id"])

    assert first.blueprint_id != second.blueprint_id
    assert {item.blueprint_id for item in active} == {
        first.blueprint_id,
        second.blueprint_id,
    }
    assert legacy["copy_set_id"] not in json.dumps(
        [item.model_dump(mode="json") for item in active]
    )
    assert await crud.get_copy_set(legacy["copy_set_id"]) is not None
    ref_cursor = await db.execute(
        "SELECT COUNT(*) FROM creative_variation_group WHERE copy_set_id=?",
        (legacy["copy_set_id"],),
    )
    assert int((await ref_cursor.fetchone())[0]) == 1


@pytest.mark.asyncio
async def test_binding_identity_is_normalized_and_conflicting_rebind_fails_closed():
    product, _snapshot = await _seed_truth()
    angles = await service.generate_angle_options(product["id"], "PAS")
    draft = await service.generate_blueprint(
        product_id=product["id"],
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="A grounded objective.",
        angle_id=angles["angles"][0]["angle_id"],
        angle_definition=angles["angles"][0]["definition"],
        evidence_fact_ids=[angles["facts"][0]["fact_id"]],
    )
    approved = await service.approve_blueprint(
        draft.blueprint_id,
        approved_by="synthetic-operator",
        semantic_review=_review(),
        readiness_proof=_readiness(),
    )
    flags = CopyBlueprintV2FeatureFlagState(
        enabled=True,
        scope="copy-register-v2-test",
        pilot_scope=("copy-register-v2-test",),
        state="PILOT",
    )
    bound = await service.bind_blueprint(
        blueprint_id=approved.blueprint_id,
        lane="T2V",
        feature_flags=flags,
    )
    assert (await service.get_binding(product["id"], "t2v")) == bound

    other_flags = CopyBlueprintV2FeatureFlagState(
        enabled=True,
        scope="alternate-scope",
        pilot_scope=("alternate-scope",),
        state="PILOT",
    )
    with pytest.raises(service.CopyRegisterV2Error) as conflict:
        await service.bind_blueprint(
            blueprint_id=approved.blueprint_id,
            lane="T2V",
            feature_flags=other_flags,
        )
    assert conflict.value.code == "COPY_V2_BINDING_CONFLICT"


def test_every_production_consumer_uses_the_persisted_resolver_and_v2_has_no_legacy_sql():
    root = Path(__file__).resolve().parents[2]
    consumers = (
        "agent/api/faceless.py",
        "agent/api/flow.py",
        "agent/api/img_factory.py",
        "agent/api/montage.py",
        "agent/api/poster_compose.py",
        "agent/api/poster_prompt.py",
        "agent/services/creative_production_compile_service.py",
        "agent/services/creative_production_scheduler_service.py",
        "agent/services/montage_scene_orchestrator.py",
        "agent/services/workspace_execution_package_service.py",
        "agent/services/workspace_generation_package_service.py",
    )
    for relative in consumers:
        source = (root / relative).read_text(encoding="utf-8")
        assert "resolve_persisted_copy_execution_binding" in source, relative
        assert "resolve_copy_execution_binding(" not in source, relative

    for relative in (
        "agent/api/copy_register_v2.py",
        "agent/services/copy_register_v2_service.py",
    ):
        normalized = (root / relative).read_text(encoding="utf-8").lower()
        for forbidden in (
            "from copy_set",
            "join copy_set",
            "insert into copy_set",
            "update copy_set",
            "from copy_component",
            "join copy_component",
        ):
            assert forbidden not in normalized, (relative, forbidden)
