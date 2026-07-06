import pytest

from agent.db import crud


@pytest.mark.asyncio
async def test_product_intelligence_review_draft_crud_round_trip_and_provenance():
    product = await crud.create_product(
        raw_product_title="Bosmax Review Draft CRUD",
        source="MANUAL",
        product_display_name="Bosmax Review Draft CRUD",
        product_short_name="Bosmax Review Draft CRUD",
    )

    draft = await crud.create_product_intelligence_review_draft(
        product_id=product["id"],
        review_status="DRAFT",
        product_description="Portable bottle",
        benefits_json='["portable"]',
        source_urls_json='{"source_url":"https://example.com"}',
    )
    assert draft["product_id"] == product["id"]
    assert draft["review_status"] == "DRAFT"

    updated = await crud.update_product_intelligence_review_draft(
        draft["draft_id"],
        review_status="READY_FOR_REVIEW",
        readiness_status="READY_FOR_APPROVAL",
    )
    assert updated["review_status"] == "READY_FOR_REVIEW"
    assert updated["readiness_status"] == "READY_FOR_APPROVAL"

    rows = await crud.list_product_intelligence_review_drafts(
        product_id=product["id"],
        limit=None,
    )
    assert [row["draft_id"] for row in rows] == [draft["draft_id"]]

    first = await crud.create_product_intelligence_review_field_provenance(
        draft_id=draft["draft_id"],
        product_id=product["id"],
        field_name="product_description",
        source_type="REVIEW_DRAFT",
        evidence_kind="TEXT",
        extraction_method="MANUAL_REVIEW",
        verification_status="PENDING_REVIEW",
        declared_value="Portable bottle",
    )
    second = await crud.create_product_intelligence_review_field_provenance(
        draft_id=draft["draft_id"],
        product_id=product["id"],
        field_name="benefits_json",
        source_type="REVIEW_DRAFT",
        evidence_kind="JSON",
        extraction_method="MANUAL_REVIEW",
        verification_status="PENDING_REVIEW",
        normalized_value='["portable"]',
    )

    provenance_rows = await crud.list_product_intelligence_review_field_provenance(
        draft_id=draft["draft_id"],
    )
    assert {row["review_provenance_id"] for row in provenance_rows} == {
        first["review_provenance_id"],
        second["review_provenance_id"],
    }

    await crud.delete_product_intelligence_review_field_provenance_for_draft(
        draft["draft_id"],
    )
    assert (
        await crud.list_product_intelligence_review_field_provenance(
            draft_id=draft["draft_id"]
        )
    ) == []
