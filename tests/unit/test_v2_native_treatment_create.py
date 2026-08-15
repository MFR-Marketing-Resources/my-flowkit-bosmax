"""V2-native treatment create → approve → P6 (no legacy copy_set authority)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import (
    CopyBlueprintV2FeatureFlagState,
    ProductionReadinessProof,
    SemanticReviewProof,
)
from agent.models.creative_treatment import (
    APPROVE_TREATMENT_CONFIRMATION,
    CreateTreatmentRequest,
    ReviewTreatmentRequest,
)
from agent.services import copy_register_v2_service as copy_v2
from agent.services import creative_production_plan_service as p6
from agent.services import creative_treatment_service as service
from agent.services.scene_choreography_catalog import select_variant_for_strategy


PRODUCT_ID = "product-v2-native-treatment"
SNAPSHOT_ID = "truth-v2-native-treatment"
SELECTION_ID = "selection-v2-native-treatment"
ASSET_ID = "asset-v2-native-treatment"
AVATAR_CODE = "BOS_F_P75D_01"


def _spice_steps(action_index: int = 0, actor_role: str = "PRODUCT") -> list[dict]:
    variant = select_variant_for_strategy("SPICE_SEASONING", action_index)
    return [
        {
            "sequence": step.step_number,
            "allowed_action_index": action_index,
            "action_text": step.action_instruction,
            "actor_role": actor_role,
            "initial_state": "; ".join(
                f"{state.entity_id}@{state.location}" for state in step.initial_states
            ),
            "resulting_state": "; ".join(
                f"{state.entity_id}@{state.location}" for state in step.resulting_states
            ),
            "continuity_requirements": list(step.continuity_rules),
        }
        for step in variant.steps
    ]


def _spice_shots(duration_seconds: int, step_count: int) -> list[dict]:
    return [
        {
            "sequence": 1,
            "action_sequences": list(range(1, step_count + 1)),
            "purpose": "governed segment",
            "framing": "product close-up",
            "camera_motion": "controlled push-in",
            "subject": "product",
            "duration_seconds": duration_seconds,
            "continuity_in": ["sealed product pack"],
            "continuity_out": ["same pack beside dish"],
        }
    ]


@pytest.fixture(autouse=True)
def _deterministic_text_assist(monkeypatch):
    call_count = 0

    def complete_json_with_receipt(system: str, user: str):
        nonlocal call_count
        call_count += 1
        payload = json.loads(user)
        if copy_v2.ANGLE_PROMPT_VERSION in system:
            facts = payload["facts"]
            signals = payload["product_truth"]["approved_angle_signals"]
            result = {
                "angles": [
                    {
                        "definition": (
                            f"{signals[i % len(signals)]}: "
                            f"{facts[i % len(facts)]['text']}"
                        ),
                        "evidence_fact_ids": [facts[i % len(facts)]["fact_id"]],
                    }
                    for i in range(3)
                ]
            }
        elif copy_v2.FORMULA_PROMPT_VERSION in system:
            facts = payload["facts"]
            angle = payload["selected_angle"]["definition"]
            result = {
                "stages": [
                    {
                        "formula_stage_key": stage_key,
                        "text": (
                            "Semak maklumat produk dan pilih langkah seterusnya."
                            if stage_key in {"cta", "action", "response"}
                            else f"{angle}. {facts[index % len(facts)]['text']}."
                        ),
                        "evidence_fact_ids": (
                            []
                            if stage_key in {"cta", "action", "response"}
                            else [facts[index % len(facts)]["fact_id"]]
                        ),
                    }
                    for index, stage_key in enumerate(
                        payload["formula"]["ordered_stage_keys"]
                    )
                ]
            }
        else:
            raise AssertionError("unexpected prompt")
        return result, {
            "call_id": call_count,
            "lane": "text_assist",
            "provider_id": "synthetic-test-provider",
            "model_id": "synthetic-test-model",
            "transport": "synthetic-test-transport",
            "response_status": "SUCCEEDED",
            "json_parse_status": "VALID",
            "completed_at": "2026-08-15T00:00:00Z",
            "usage": {},
        }

    monkeypatch.setattr(copy_v2.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        copy_v2.ai_provider,
        "complete_json_with_receipt",
        complete_json_with_receipt,
    )
    monkeypatch.setattr(
        copy_v2.ai_provider,
        "provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "synthetic-test-provider",
            "model_id": "synthetic-test-model",
            "execution_enabled": True,
        },
    )


async def _seed_visual_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM creative_treatment WHERE product_id=?",
        (PRODUCT_ID,),
    )
    await db.execute(
        "DELETE FROM creative_asset WHERE asset_id=?",
        (ASSET_ID,),
    )
    await db.execute(
        "DELETE FROM creative_product_selection WHERE product_id=?",
        (PRODUCT_ID,),
    )
    await db.execute(
        "DELETE FROM product_intelligence_snapshot WHERE snapshot_id=?",
        (SNAPSHOT_ID,),
    )
    await db.execute("DELETE FROM product WHERE id=?", (PRODUCT_ID,))
    await db.commit()

    await db.execute(
        """
        INSERT INTO product (
            id, raw_product_title, product_display_name, product_short_name
        ) VALUES (?, 'Rempah V2', 'Rempah V2', 'Rempah V2')
        """,
        (PRODUCT_ID,),
    )
    await db.execute(
        """
        INSERT INTO product_intelligence_snapshot (
            snapshot_id, product_id, version, status, product_description,
            benefits_json, usp_json, hook_angles_json, pain_points_json,
            target_customer_text, allowed_claims_json, blocked_claims_json,
            buyer_persona_snapshot_json, copy_strategy_summary_json,
            claim_gate, claim_risk_level, approved_by, approved_at,
            readiness_status, created_at, updated_at
        ) VALUES (
            ?, ?, 1, 'APPROVED', 'Rempah masakan herba.',
            '["Mudah digunakan"]', '["Aroma kuat"]', '["Harum terus naik"]',
            '["Masakan hambar"]', 'Cooks at home',
            '["Mudah digunakan"]', '["Menyembuhkan"]',
            '{"audience":"home cook"}', '{"angle":"aroma"}',
            'CLAIM_SAFE', 'LOW', 'tester', '2026-08-15T00:00:00Z',
            'READY_FOR_APPROVAL', '2026-08-15T00:00:00Z', '2026-08-15T00:00:00Z'
        )
        """,
        (SNAPSHOT_ID, PRODUCT_ID),
    )
    await db.execute(
        """
        INSERT INTO creative_product_selection (
            product_id, selection_id, cluster, selected_avatar_code, status
        ) VALUES (?, ?, 'food_cooking', ?, 'APPROVED')
        """,
        (PRODUCT_ID, SELECTION_ID, AVATAR_CODE),
    )
    await db.execute(
        """
        INSERT INTO creative_asset (
            asset_id, semantic_role, display_name, source_type, storage_kind,
            remote_source_url, product_id, allowed_modes,
            approved_for_video_support, review_status, status
        ) VALUES (
            ?, 'PRODUCT_REFERENCE', 'Rempah pack', 'SYSTEM_SEED', 'REMOTE_URL',
            'https://example.invalid/rempah.png', ?, '["F2V"]',
            1, 'APPROVED', 'ACTIVE'
        )
        """,
        (ASSET_ID, PRODUCT_ID),
    )
    await db.commit()

    taxonomy = SimpleNamespace(
        product_id=PRODUCT_ID,
        taxonomy_version="product_strategy_taxonomy_v1",
        product_fingerprint="fingerprint",
        cluster="food_cooking",
        product_type_group="rempah_seasoning",
        matched_scene_strategy_id="SPICE_SEASONING",
        scene_coverage_status="COVERED",
        fallback_used=False,
        specific_strategy=True,
        classification_confidence="HIGH",
        review_status="VERIFIED",
        consumer_status="READY",
        authority_source="MANUAL_OVERRIDE",
        materialization_status="MATERIALIZED",
        is_stale=False,
    )

    async def _taxonomy(product_id: str):
        assert product_id == PRODUCT_ID
        return taxonomy

    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        _taxonomy,
    )
    monkeypatch.setattr(
        service.avatar_registry,
        "resolve_presenter",
        lambda avatar_id: {
            "avatar_code": avatar_id,
            "character_name": "Presenter V2",
            "wardrobe": "Approved wardrobe",
        },
    )


def _readiness() -> ProductionReadinessProof:
    return ProductionReadinessProof(
        readiness_validated=True,
        provenance_validated=True,
        safety_validated=True,
        bridge_validated=True,
        duration_validated=True,
    )


def _review_proof() -> SemanticReviewProof:
    return SemanticReviewProof(
        decision="APPROVED",
        reviewer="v2-treatment-reviewer",
        rationale="Claim-bearing stages checked against approved Product Truth.",
        reviewed_at="2026-08-15T00:10:00Z",
    )


@pytest.mark.asyncio
async def test_v2_native_create_approve_and_p6_authority(monkeypatch):
    # Production runtime: no legacy maintenance, no copy_set writes.
    monkeypatch.delenv("COPY_LEGACY_MAINTENANCE_MODE", raising=False)
    await _seed_visual_authority(monkeypatch)

    before_copy = await (await get_db()).execute("SELECT COUNT(*) FROM copy_set")
    before_count = int((await before_copy.fetchone())[0])

    angles = await copy_v2.generate_angle_options(PRODUCT_ID, "PAS")
    bp = await copy_v2.generate_blueprint(
        product_id=PRODUCT_ID,
        formula_id="PAS",
        objective_id="conversion",
        objective_definition="Help a qualified buyer choose a grounded next step.",
        angle_id=angles["angles"][0]["angle_id"],
        angle_definition=angles["angles"][0]["definition"],
        evidence_fact_ids=[fact["fact_id"] for fact in angles["facts"][:3]],
    )
    approved_bp = await copy_v2.approve_blueprint(
        bp.blueprint_id,
        approved_by="v2-operator",
        semantic_review=_review_proof(),
        readiness_proof=_readiness(),
    )
    flags = CopyBlueprintV2FeatureFlagState.from_environment(scope="global")
    binding = await copy_v2.bind_blueprint(
        blueprint_id=approved_bp.blueprint_id,
        lane="PRODUCTION_STUDIO_P6",
        feature_flags=flags,
    )

    steps = _spice_steps(0, "PRODUCT")
    body = CreateTreatmentRequest(
        product_id=PRODUCT_ID,
        product_truth_snapshot_id=SNAPSHOT_ID,
        copy_execution_binding_id_v2=binding.binding_id,
        creative_selection_id=SELECTION_ID,
        scene_strategy_id="SPICE_SEASONING",
        format="PGC",
        generation_mode="SINGLE",
        duration_seconds=8,
        action_sequence=steps,
        shot_grammar=_spice_shots(8, len(steps)),
        compatibility_profile={
            "logical_mode": "F2V",
            "source_mode": "FRAMES",
            "model_keys": ["veo_3_1"],
            "required_asset_roles": ["PRODUCT_REFERENCE"],
        },
        asset_bindings=[{"role": "PRODUCT_REFERENCE", "asset_id": ASSET_ID}],
        created_by="v2-native-author",
    )

    draft = await service.create_treatment(body)
    assert draft["status"] == "DRAFT"
    assert draft.get("copy_execution_binding_id_v2") == binding.binding_id
    assert not (draft.get("copy_set_id") or "").strip()
    assert draft.get("choreography_id")
    assert draft.get("choreography_sha256")

    submitted = await service.submit_treatment_review(
        draft["treatment_id"],
        actor_id="submitter",
    )
    assert submitted["status"] == "REVIEW_REQUIRED"

    approved = await service.review_treatment(
        draft["treatment_id"],
        ReviewTreatmentRequest(
            decision="APPROVED",
            actor_id="reviewer",
            expected_sha256=draft["treatment_sha256"],
            confirmation=APPROVE_TREATMENT_CONFIRMATION,
        ),
    )
    assert approved["status"] == "APPROVED"
    assert approved.get("copy_execution_binding_id_v2") == binding.binding_id

    # Receipt revalidation (P6 path for approved rows).
    row = await service.treatment_crud.get_treatment(draft["treatment_id"])
    receipt = service.revalidate_stored_treatment_receipt(row)
    assert receipt["treatment_sha256"] == draft["treatment_sha256"]

    authority = await p6.resolve_treatment_authority(draft["treatment_id"])
    decision = str(
        authority.get("decision")
        or authority.get("status")
        or authority.get("authority_status")
        or ""
    ).upper()
    code = str(authority.get("code") or authority.get("blocker_code") or "")
    assert code not in {
        "LEGACY_ATOMIC_TREATMENT_REJECTED",
        "TREATMENT_NOT_APPROVED",
        "LEGACY_COPY_STORAGE_DISABLED",
        "COPY_SET_NOT_FOUND",
    }
    assert decision not in {"FAIL_CLOSED", "REJECTED", "BLOCKED"}

    after_copy = await (await get_db()).execute("SELECT COUNT(*) FROM copy_set")
    assert int((await after_copy.fetchone())[0]) == before_count


@pytest.mark.asyncio
async def test_legacy_copy_set_create_blocked_without_maintenance(monkeypatch):
    monkeypatch.delenv("COPY_LEGACY_MAINTENANCE_MODE", raising=False)
    await _seed_visual_authority(monkeypatch)
    steps = _spice_steps(0, "PRODUCT")
    body = CreateTreatmentRequest(
        product_id=PRODUCT_ID,
        product_truth_snapshot_id=SNAPSHOT_ID,
        copy_set_id="copy-should-not-work",
        creative_selection_id=SELECTION_ID,
        scene_strategy_id="SPICE_SEASONING",
        format="PGC",
        generation_mode="SINGLE",
        duration_seconds=8,
        action_sequence=steps,
        shot_grammar=_spice_shots(8, len(steps)),
        compatibility_profile={
            "logical_mode": "F2V",
            "source_mode": "FRAMES",
            "model_keys": ["veo_3_1"],
            "required_asset_roles": ["PRODUCT_REFERENCE"],
        },
        asset_bindings=[{"role": "PRODUCT_REFERENCE", "asset_id": ASSET_ID}],
        created_by="v2-native-author",
    )
    with pytest.raises(service.CreativeTreatmentError) as err:
        await service.create_treatment(body)
    assert err.value.code == "LEGACY_COPY_STORAGE_DISABLED"
