import pytest

from agent.db import crud


@pytest.mark.asyncio
async def test_product_intelligence_field_provenance_create_and_filter():
    product = await crud.create_product(
        raw_product_title="Bosmax Provenance Test",
        source="MANUAL",
        product_display_name="Bosmax Provenance Test",
        product_short_name="Bosmax Provenance",
    )
    snapshot = await crud.create_product_intelligence_snapshot(
        product_id=product["id"],
        version=1,
        status="APPROVED",
        approved_at="2026-07-05T12:00:00Z",
    )

    await crud.create_product_intelligence_field_provenance(
        snapshot_id=snapshot["snapshot_id"],
        product_id=product["id"],
        field_name="product_description",
        source_type="MANUAL_DECLARED",
        evidence_kind="TEXT",
        extraction_method="OPERATOR_INPUT",
        verification_status="REVIEWED_APPROVED",
        declared_value="Original description",
        normalized_value="Normalized description",
    )
    second = await crud.create_product_intelligence_field_provenance(
        snapshot_id=snapshot["snapshot_id"],
        product_id=product["id"],
        field_name="benefits_json",
        source_type="MANUAL_DECLARED",
        evidence_kind="TEXT",
        extraction_method="BULLET_NORMALIZATION",
        verification_status="REVIEWED_APPROVED",
        declared_value="portable",
        normalized_value='["portable"]',
    )

    by_snapshot = await crud.list_product_intelligence_field_provenance(
        snapshot_id=snapshot["snapshot_id"]
    )
    assert len(by_snapshot) == 2

    by_product_field = await crud.list_product_intelligence_field_provenance(
        product_id=product["id"],
        field_name="benefits_json",
    )
    assert len(by_product_field) == 1
    assert by_product_field[0]["provenance_id"] == second["provenance_id"]


@pytest.mark.asyncio
async def test_product_intelligence_field_provenance_requires_scope():
    with pytest.raises(ValueError, match="SNAPSHOT_ID_OR_PRODUCT_ID_REQUIRED"):
        await crud.list_product_intelligence_field_provenance()
