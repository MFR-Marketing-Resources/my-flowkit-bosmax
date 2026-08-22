"""StaffProfile authority and durable attribution lineage tests."""

from __future__ import annotations

import pytest

from agent.db import crud
from agent.db import creative_production_crud as p6db
from agent.services import creative_production_plan_service as p6
from agent.services import make_video
from agent.services import staff_identity_service as staff


@pytest.mark.asyncio
async def test_staff_profile_lifecycle_preserves_id_and_history() -> None:
    created = await staff.create_staff_profile("Aisha Rahman")
    staff_id = created["staff_id"]

    assert staff_id.startswith("staff_")
    assert await staff.resolve_staff_identity(staff_id) == created

    renamed = await staff.update_staff_profile(
        staff_id,
        display_name="Aisha R.",
    )
    assert renamed["staff_id"] == staff_id
    assert renamed["display_name"] == "Aisha R."
    assert renamed["active"] is True

    inactive = await staff.update_staff_profile(staff_id, active=False)
    assert inactive["staff_id"] == staff_id
    assert inactive["display_name"] == "Aisha R."
    assert inactive["active"] is False

    with pytest.raises(staff.StaffIdentityError) as raised:
        await staff.resolve_staff_identity(staff_id)
    assert raised.value.code == staff.STAFF_IDENTITY_INACTIVE

    historical = await staff.resolve_staff_identity(staff_id, require_active=False)
    assert historical["staff_id"] == staff_id
    assert historical["display_name"] == "Aisha R."
    assert any(
        profile["staff_id"] == staff_id and not profile["active"]
        for profile in await staff.list_staff_profiles(include_inactive=True)
    )
    assert all(
        profile["staff_id"] != staff_id
        for profile in await staff.list_staff_profiles(include_inactive=False)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate, expected_code",
    [
        (None, staff.STAFF_IDENTITY_REQUIRED),
        ("", staff.STAFF_IDENTITY_REQUIRED),
        ("system", staff.STAFF_IDENTITY_GENERIC),
        ("p6-production-operator", staff.STAFF_IDENTITY_GENERIC),
        ("unknown", staff.STAFF_IDENTITY_GENERIC),
        ("not-registered", staff.STAFF_IDENTITY_UNKNOWN),
    ],
)
async def test_invalid_staff_identity_fails_closed(
    candidate: str | None,
    expected_code: str,
) -> None:
    with pytest.raises(staff.StaffIdentityError) as raised:
        await staff.resolve_staff_identity(candidate)
    assert raised.value.code == expected_code


@pytest.mark.asyncio
async def test_generation_boundary_rejects_missing_identity_before_provider_lane() -> None:
    result = await make_video.start_generate(
        "F2V",
        "provider-ready prompt",
        production_recipe="FACELESS",
        staff_id=None,
    )

    assert result["status"] == "REJECTED"
    assert result["error"] == staff.STAFF_IDENTITY_REQUIRED
    assert result["pre_provider"] == {
        "provider_calls": 0,
        "credit_spend": False,
    }


@pytest.mark.asyncio
async def test_staff_identity_is_carried_through_p6_and_output_ledgers() -> None:
    profile = await staff.create_staff_profile("Lineage Operator")
    staff_id = profile["staff_id"]
    staff_name = profile["display_name"]
    stamp = "2026-08-01T16:00:00Z"
    product_id = "lineage-product"
    plan_id = "lineage-plan"
    item_id = "lineage-item"
    attempt_id = "lineage-attempt"

    db = await crud.get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name) "
        "VALUES (?,?,?,?)",
        (product_id, "Lineage Product", "Lineage Product", "Lineage"),
    )
    await db.commit()

    plan = await p6db.create_plan(
        {
            "plan_id": plan_id,
            "request_id": "lineage-request",
            "created_by": staff_id,
            "staff_id": staff_id,
            "staff_display_name_snapshot": staff_name,
            "name": "Lineage plan",
            "p58_cohort_sha256": "lineage-sha",
            "p58_cohort_count": 1,
            "production_recipe": "HYBRID",
            "logical_mode": "HYBRID",
            "status": "APPROVED",
            "created_at": stamp,
            "updated_at": stamp,
        }
    )
    assert plan["staff_id"] == staff_id

    await p6db.insert_items(
        [
            {
                "item_id": item_id,
                "plan_id": plan_id,
                "staff_id": staff_id,
                "staff_display_name_snapshot": staff_name,
                "item_ordinal": 1,
                "product_id": product_id,
                "media_type": "VIDEO",
                "production_recipe": "HYBRID",
                "logical_mode": "HYBRID",
                "creative_dimensions_json": "{}",
                "creative_dna_sha256": "lineage-dna",
                "dedupe_guard_key": "lineage-guard",
                "status": "QA_APPROVED",
                "output_media_id": "lineage-media",
                "created_at": stamp,
                "updated_at": stamp,
            }
        ]
    )
    attempt = await p6db.create_attempt(
        {
            "attempt_id": attempt_id,
            "item_id": item_id,
            "staff_id": staff_id,
            "staff_display_name_snapshot": staff_name,
            "attempt_number": 1,
            "idempotency_key": "lineage-idempotency",
            "action_request_id": "lineage-action",
            "attempt_state": "REGISTERED",
            "payload_sha256": "lineage-payload",
            "provider": "GOOGLE_FLOW",
            "engine": "ADR_007_API_FIRST",
            "model_key": "veo-3.1",
            "last_actor_id": staff_id,
            "artifact_media_id": "lineage-media",
            "created_at": stamp,
            "updated_at": stamp,
            "registered_at": stamp,
            "completed_at": stamp,
        }
    )
    qa = await p6db.upsert_qa(
        {
            "qa_id": "lineage-qa",
            "item_id": item_id,
            "attempt_id": attempt_id,
            "staff_id": staff_id,
            "staff_display_name_snapshot": staff_name,
            "artifact_media_id": "lineage-media",
            "status": "QA_APPROVED",
            "checklist_json": "{}",
            "reviewer_id": staff_id,
            "reviewed_at": stamp,
            "created_at": stamp,
            "updated_at": stamp,
        }
    )
    audit = await p6.record_audit_event(
        plan_id=plan_id,
        request_id="lineage-audit-request",
        actor_id=staff_id,
        staff_id=staff_id,
        staff_display_name_snapshot=staff_name,
        action="TEST_LINEAGE",
        source_state="APPROVED",
        target_state="RUNNING",
        item_id=item_id,
        attempt_id=attempt_id,
    )
    artifact = await crud.insert_generated_artifact(
        "lineage-media",
        job_id="lineage-job",
        mode="F2V",
        artifact_kind="video",
        model_used="veo-3.1",
        staff_id=staff_id,
        staff_display_name_snapshot=staff_name,
    )
    await crud.insert_generation_result(
        "lineage-media",
        job_id="lineage-job",
        request_id="lineage-request",
        staff_id=staff_id,
        staff_display_name_snapshot=staff_name,
        mode="F2V",
        artifact_kind="video",
        product_id=product_id,
        product_name="Lineage Product",
    )

    assert attempt["staff_id"] == staff_id
    assert qa["staff_display_name_snapshot"] == staff_name
    assert audit["staff_id"] == staff_id
    assert audit["staff_display_name_snapshot"] == staff_name
    assert artifact["staff_id"] == staff_id
    result = await crud.get_generation_result("lineage-media")
    assert result is not None
    assert result["staff_id"] == staff_id
    assert result["staff_display_name_snapshot"] == staff_name
