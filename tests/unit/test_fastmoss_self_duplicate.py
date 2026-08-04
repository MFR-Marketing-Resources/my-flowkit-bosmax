"""A COMMITTED FastMoss queue row must never be flagged DUPLICATE_SUSPECTED of the
very product it created. The detector self-excludes `ignore_product_id`, but its
callers passed only `duplicate_ignore_product_id`, not the row's own
`committed_product_id` — so committed rows self-matched their own FASTMOSS_PROMOTED
product (348 live rows). Callers now ignore `committed_product_id` first.
"""
from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.services.fastmoss_bulk_promotion_service import (
    _detect_queue_duplicate_candidate,
    sync_queue_row_from_draft,
)


def _draft(did, title):
    return SimpleNamespace(
        review_draft_id=did,
        declared_evidence_fields={
            "product_name": title,
            "image_url": "https://x/i.jpg",
            "tiktok_product_url": None,
        },
        claim_risk_level="LOW",
        missing_required_evidence=[],
        claim_tokens=[],
        claim_gate="CLAIM_SAFE",
    )


@pytest.mark.asyncio
async def test_committed_row_not_self_flagged_as_duplicate():
    title = "Sumikko 50PCS Premium Baby Diaper Pants"
    product = await crud.create_product(title, source="FASTMOSS", mapping_source="FASTMOSS_PROMOTED")

    # Detector semantics: it self-matches unless its OWN product is ignored.
    assert await _detect_queue_duplicate_candidate("ref", title, None) is not None
    assert await _detect_queue_duplicate_candidate(
        "ref", title, None, ignore_product_id=product["id"]
    ) is None

    # The committed row, synced from its draft, must NOT re-flag as a self-duplicate.
    ref, did = "fastmoss-ref:selfdup", "draft-selfdup"
    await crud.create_bulk_queue_row(
        ref, title,
        promotion_status="APPROVED", committed_product_id=product["id"],
        draft_id=did, claim_risk_level="LOW", image_readiness="IMAGE_REFERENCE_READY",
    )
    updated = await sync_queue_row_from_draft(_draft(did, title))
    assert updated["promotion_status"] != "DUPLICATE_SUSPECTED"
