"""P7.5-B treatment lifecycle, lineage, and Variation Group enforcement."""

from types import SimpleNamespace

import pytest

from agent.db.schema import get_db
from agent.models.creative_treatment import (
    APPROVE_TREATMENT_CONFIRMATION,
    APPROVE_VARIATION_GROUP_CONFIRMATION,
    CreateTreatmentRequest,
    CreateVariationGroupRequest,
    ReviewTreatmentRequest,
    ReviewVariationGroupRequest,
)
from agent.services import creative_treatment_service as service
from agent.services.scene_strategy_library import SCENE_STRATEGIES


PRODUCT_ID = "product-p75b-service"
COPY_SET_ID = "copy-p75b-service"
SNAPSHOT_ID = "truth-p75b-service"
SELECTION_ID = "selection-p75b-service"
ASSET_ID = "asset-p75b-service"


async def _seed_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    db = await get_db()
    await db.execute(
        """
        DELETE FROM creative_treatment_audit_event
        WHERE entity_id IN (
            SELECT treatment_id FROM creative_treatment WHERE product_id=?
        ) OR entity_id IN (
            SELECT group_id FROM creative_variation_group WHERE product_id=?
        )
        """,
        (PRODUCT_ID, PRODUCT_ID),
    )
    await db.execute(
        """
        DELETE FROM creative_treatment
        WHERE product_id=? AND supersedes_treatment_id IS NOT NULL
        """,
        (PRODUCT_ID,),
    )
    await db.execute(
        "DELETE FROM creative_treatment WHERE product_id=?",
        (PRODUCT_ID,),
    )
    await db.execute(
        """
        DELETE FROM creative_variation_group
        WHERE product_id=? AND supersedes_group_id IS NOT NULL
        """,
        (PRODUCT_ID,),
    )
    await db.execute(
        "DELETE FROM creative_variation_group WHERE product_id=?",
        (PRODUCT_ID,),
    )
    await db.execute("DELETE FROM creative_asset WHERE asset_id=?", (ASSET_ID,))
    await db.execute(
        "DELETE FROM creative_product_selection WHERE product_id=?",
        (PRODUCT_ID,),
    )
    await db.execute("DELETE FROM copy_set WHERE copy_set_id=?", (COPY_SET_ID,))
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
        ) VALUES (?, 'Rempah', 'Rempah', 'Rempah')
        """,
        (PRODUCT_ID,),
    )
    await db.execute(
        """
        INSERT INTO product_intelligence_snapshot (
            snapshot_id, product_id, version, status, product_description,
            readiness_status, created_at, updated_at
        ) VALUES (?, ?, 1, 'APPROVED', 'Rempah masakan.',
                  'READY_FOR_APPROVAL', '2026-07-30T00:00:00Z',
                  '2026-07-30T00:00:00Z')
        """,
        (SNAPSHOT_ID, PRODUCT_ID),
    )
    await db.execute(
        """
        INSERT INTO copy_set (
            copy_set_id, product_id, angle, hook, subhook, usp_set_json, cta,
            status, archived
        ) VALUES (?, ?, 'Aroma rempah', 'Harum rempah terus naik.',
                  'Masakan terasa lengkap.', '["Mudah digunakan"]',
                  'Cuba hari ini.', 'COPY_APPROVED', 0)
        """,
        (COPY_SET_ID, PRODUCT_ID),
    )
    await db.execute(
        """
        INSERT INTO creative_product_selection (
            product_id, selection_id, cluster, status
        ) VALUES (?, ?, 'food_cooking', 'APPROVED')
        """,
        (PRODUCT_ID, SELECTION_ID),
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


def _request(
    *,
    created_by: str = "author",
    action_index: int = 0,
    group_id: str | None = None,
    ordinal: int | None = None,
    supersedes_treatment_id: str | None = None,
) -> CreateTreatmentRequest:
    action_text = SCENE_STRATEGIES["SPICE_SEASONING"]["allowed_actions"][
        action_index
    ]
    return CreateTreatmentRequest(
        product_id=PRODUCT_ID,
        product_truth_snapshot_id=SNAPSHOT_ID,
        copy_set_id=COPY_SET_ID,
        creative_selection_id=SELECTION_ID,
        scene_strategy_id="SPICE_SEASONING",
        format="PGC",
        generation_mode="SINGLE",
        duration_seconds=8,
        action_sequence=[
            {
                "sequence": 1,
                "allowed_action_index": action_index,
                "action_text": action_text,
                "actor_role": "PRODUCT",
                "initial_state": "Product pack sealed",
                "resulting_state": "Product demonstrated",
                "continuity_requirements": ["pack identity remains stable"],
            },
        ],
        shot_grammar=[
            {
                "sequence": 1,
                "action_sequences": [1],
                "purpose": "Demonstrate the product action",
                "framing": "product close-up",
                "camera_motion": "controlled push-in",
                "subject": "rempah and plated dish",
                "duration_seconds": 8,
                "continuity_in": ["sealed product pack"],
                "continuity_out": ["same pack beside dish"],
            },
        ],
        compatibility_profile={
            "logical_mode": "F2V",
            "source_mode": "FRAMES",
            "model_keys": ["veo_3_1"],
            "required_asset_roles": ["PRODUCT_REFERENCE"],
        },
        asset_bindings=[
            {"role": "PRODUCT_REFERENCE", "asset_id": ASSET_ID},
        ],
        variation_group_id=group_id,
        variation_ordinal=ordinal,
        supersedes_treatment_id=supersedes_treatment_id,
        created_by=created_by,
    )


async def _approve(treatment: dict, actor: str = "reviewer") -> dict:
    await service.submit_treatment_review(
        treatment["treatment_id"],
        actor_id="submitter",
    )
    return await service.review_treatment(
        treatment["treatment_id"],
        ReviewTreatmentRequest(
            decision="APPROVED",
            actor_id=actor,
            expected_sha256=treatment["treatment_sha256"],
            confirmation=APPROVE_TREATMENT_CONFIRMATION,
        ),
    )


@pytest.mark.asyncio
async def test_treatment_hash_is_deterministic_and_lifecycle_is_audited(
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_authority(monkeypatch)
    created = await service.create_treatment(_request())
    current = await service._revalidate(
        await service.treatment_crud.get_treatment(created["treatment_id"]),
    )
    assert current["treatment_sha256"] == created["treatment_sha256"]

    approved = await _approve(created)
    assert approved["status"] == "APPROVED"
    detail = await service.get_treatment(created["treatment_id"])
    assert [event["action"] for event in detail["audit_events"]] == [
        "CREATED",
        "REVIEW_REQUIRED",
        "APPROVED",
    ]


@pytest.mark.asyncio
async def test_submit_fails_closed_when_copy_authority_changes(
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_authority(monkeypatch)
    created = await service.create_treatment(_request())
    db = await get_db()
    await db.execute(
        "UPDATE copy_set SET hook='Changed after treatment' WHERE copy_set_id=?",
        (COPY_SET_ID,),
    )
    await db.commit()

    with pytest.raises(
        service.CreativeTreatmentError,
        match="TREATMENT_AUTHORITY_STALE",
    ):
        await service.submit_treatment_review(
            created["treatment_id"],
            actor_id="submitter",
        )


@pytest.mark.asyncio
async def test_same_dialogue_requires_declared_variation_group(
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_authority(monkeypatch)
    first = await service.create_treatment(_request())
    await _approve(first)
    second = await service.create_treatment(
        _request(action_index=1, created_by="second-author"),
    )
    await service.submit_treatment_review(
        second["treatment_id"],
        actor_id="submitter",
    )
    with pytest.raises(
        service.CreativeTreatmentError,
        match="UNDECLARED_SAME_DIALOGUE_VARIATION",
    ):
        await service.review_treatment(
            second["treatment_id"],
            ReviewTreatmentRequest(
                decision="APPROVED",
                actor_id="reviewer",
                expected_sha256=second["treatment_sha256"],
                confirmation=APPROVE_TREATMENT_CONFIRMATION,
            ),
        )


@pytest.mark.asyncio
async def test_approved_successor_supersedes_exact_predecessor_atomically(
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_authority(monkeypatch)
    predecessor = await service.create_treatment(_request())
    await _approve(predecessor)
    successor = await service.create_treatment(
        _request(
            action_index=1,
            created_by="successor-author",
            supersedes_treatment_id=predecessor["treatment_id"],
        ),
    )
    approved = await _approve(successor)
    previous = await service.get_treatment(predecessor["treatment_id"])
    assert approved["status"] == "APPROVED"
    assert previous["status"] == "SUPERSEDED"
    assert previous["audit_events"][-1]["evidence"] == {
        "successor_treatment_id": successor["treatment_id"],
    }


@pytest.mark.asyncio
async def test_variation_group_enforces_same_dialogue_distinct_visuals_and_review(
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_authority(monkeypatch)
    group = await service.create_variation_group(
        CreateVariationGroupRequest(
            product_id=PRODUCT_ID,
            copy_set_id=COPY_SET_ID,
            created_by="group-author",
        ),
    )
    first = await service.create_treatment(
        _request(group_id=group["group_id"], ordinal=1),
    )
    second = await service.create_treatment(
        _request(
            action_index=1,
            group_id=group["group_id"],
            ordinal=2,
            created_by="second-author",
        ),
    )
    await _approve(first)
    await _approve(second)

    submitted = await service.submit_variation_group_review(
        group["group_id"],
        actor_id="group-submitter",
    )
    approved = await service.review_variation_group(
        group["group_id"],
        ReviewVariationGroupRequest(
            decision="APPROVED",
            actor_id="group-reviewer",
            expected_sha256=submitted["group_sha256"],
            confirmation=APPROVE_VARIATION_GROUP_CONFIRMATION,
        ),
    )
    assert approved["status"] == "APPROVED"
    assert approved["member_count"] == 2
