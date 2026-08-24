from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.services import product_visual_onboarding_service as service


def _product(product_id: str, name: str, readiness: dict) -> dict:
    return {
        "id": product_id,
        "product_display_name": name,
        "raw_product_title": name,
        "lifecycle_status": "ACTIVE",
        "staff_release_status": "HIDDEN",
        "visual_readiness": readiness,
    }


def _pending(product_id: str, *, source_available: bool = True) -> dict:
    return {
        "official_visual_status": "NOT_APPROVED",
        "cutout_review_status": "PENDING_REVIEW",
        "canonical_media_status": "AVAILABLE" if source_available else "MISSING",
        "cutout_status": "PENDING_REVIEW",
        "canonical_cutout_sha256": f"{product_id.replace('-', '')[:8]:0<8}" * 8,
        "canonical_cutout_media_id": f"cutout-{product_id}",
        "visual_lock_updated_at": "v1",
        "canonical_source_sha256": "1" * 64,
        "candidate_source_kind": "AUTO_GENERATED",
        "candidate_provenance": {"canonical_source_type": "PRODUCT_SOURCE_MEDIA"},
        "historical_evidence_count": 0,
        "auto_cutout_preview_url": "/candidate.png" if source_available else None,
        "original_preview_url": "/source.png" if source_available else None,
        "original_display_url": "/display-source.png",
        "original_display_trust_status": "TRUSTED" if source_available else "DISPLAY_ONLY",
        "exact_commerce_status": "CUTOUT_REQUIRED",
        "current_system_visual": {"card": None, "status": "NOT_SELECTED"},
        "blockers": [],
        "active_cutout_preview_url": None,
    }


def test_visual_review_filter_reuses_owner_cohort_authority():
    product = _product("pending-1", "Pending one", _pending("pending-1"))
    readiness = product["visual_readiness"]

    assert service.visual_review_filter_matches(product, readiness, "PENDING_VISUAL_REVIEW")
    assert not service.visual_review_filter_matches(product, readiness, "SOURCE_REUPLOAD_REQUIRED")
    assert not service.visual_review_filter_matches(product, readiness, "VISUAL_READY")
    assert service.visual_review_filter_matches(
        product,
        {**readiness, "cutout_status": "APPROVED", "cutout_review_status": "APPROVED", "exact_commerce_status": "EXACT_COMMERCE_CUTOUT_READY"},
        "VISUAL_READY",
    )


@pytest.mark.asyncio
async def test_review_queue_keeps_three_cohorts_separate_and_paginates(monkeypatch):
    products = [
        _product("pending-1", "Pending one", _pending("pending-1")),
        _product("pending-2", "Pending two", _pending("pending-2")),
        _product("missing-1", "Missing source", _pending("missing-1", source_available=False)),
        _product(
            "broken-1",
            "Broken official",
            {
                **_pending("broken-1"),
                "official_visual_status": "INVALID",
                "cutout_review_status": "APPROVED",
                "cutout_status": "BROKEN_OFFICIAL_VISUAL",
                "exact_commerce_status": "EXACT_COMMERCE_BLOCKED",
                "auto_cutout_preview_url": None,
                "active_cutout_preview_url": None,
                "blockers": ["OFFICIAL_PRODUCT_VISUAL_INVALID"],
            },
        ),
    ]

    async def list_products(**_kwargs):
        return products

    async def annotate(rows):
        # The queue must consume the existing batched read model, not call one
        # detail-read endpoint per row.
        assert rows is products

    monkeypatch.setattr(service.crud, "list_products", list_products)
    monkeypatch.setattr(service, "annotate_products_visual_readiness", annotate)

    response = await service.get_product_visual_review_queue(
        cohort="PENDING_VISUAL_REVIEW", limit=1, offset=0
    )

    assert response["cohort_counts"] == {
        "PENDING_VISUAL_REVIEW": 2,
        "SOURCE_REUPLOAD_REQUIRED": 1,
        "BROKEN_APPROVED_VISUAL": 1,
    }
    assert response["total_count"] == 2
    assert response["returned_count"] == 1
    assert response["items"][0]["product_id"] == "pending-1"
    assert response["items"][0]["candidate_preview_url"] == "/candidate.png"
    assert response["items"][0]["readiness_impact"]["auto_release"] is False

    missing = await service.get_product_visual_review_queue(
        cohort="SOURCE_REUPLOAD_REQUIRED", limit=25, offset=0
    )
    broken = await service.get_product_visual_review_queue(
        cohort="BROKEN_APPROVED_VISUAL", limit=25, offset=0
    )
    assert missing["items"][0]["candidate_status"] == "TRUE_SOURCE_MISSING"
    assert missing["items"][0]["original_source_trust_status"] == "DISPLAY_ONLY"
    assert broken["items"][0]["candidate_status"] == "BROKEN_OFFICIAL_VISUAL"
    assert broken["items"][0]["missing_canonical_bytes"] == ["SOURCE", "CUTOUT"]


@pytest.mark.asyncio
async def test_selected_approval_is_candidate_bound_and_reports_partial_failure(monkeypatch):
    actor = SimpleNamespace(
        user_id="user-owner",
        staff_id="staff-owner",
        display_name="Authenticated Owner",
    )
    calls: list[dict] = []

    async def get_readiness(product_id: str):
        return {
            "product_id": product_id,
            "cutout_review_status": "PENDING_REVIEW",
            "exact_commerce_status": "CUTOUT_REQUIRED",
            "canonical_cutout_sha256": "a" * 64 if product_id == "p-1" else "b" * 64,
            "canonical_cutout_media_id": f"media-{product_id}",
            "visual_lock_updated_at": "v1",
            "candidate_source_kind": "AUTO_GENERATED",
        }

    async def save(product_id: str, **kwargs):
        calls.append({"product_id": product_id, **kwargs})
        return {
            "product_id": product_id,
            "exact_commerce_status": "EXACT_COMMERCE_CUTOUT_READY",
        }

    monkeypatch.setattr(service, "get_product_visual_readiness", get_readiness)
    monkeypatch.setattr(service, "save_product_visual_setup", save)
    monkeypatch.setattr(service, "_record_visual_review_audit", lambda **_kwargs: _noop())

    async def release_state(product_id: str):
        return {
            "staff_release_status": "HIDDEN",
            "minimum_eligibility_status": "ELIGIBLE" if product_id == "p-1" else "BLOCKED",
        }

    # The service imports this authority at call time; patch the module import
    # seam without touching the release writer.
    import agent.services.product_release_service as release_service

    monkeypatch.setattr(release_service, "load_product_release_state", release_state)
    response = await service.approve_selected_product_visuals(
        [
            {
                "product_id": "p-1",
                "candidate_sha256": "a" * 64,
                "candidate_media_id": "media-p-1",
                "expected_lock_updated_at": "v1",
                "candidate_source_kind": "AUTO_GENERATED",
            },
            {
                "product_id": "p-2",
                "candidate_sha256": "c" * 64,
                "candidate_media_id": "media-p-2",
                "expected_lock_updated_at": "v1",
                "candidate_source_kind": "AUTO_GENERATED",
            },
        ],
        review_note="Owner visual recovery review",
        actor=actor,
        confirm_identity=True,
        confirm_label_logo=True,
        confirm_geometry_scale=True,
        confirm_product_isolation=True,
    )

    assert response["status"] == "PARTIAL_SUCCESS"
    assert response["all_succeeded"] is False
    assert response["approved_count"] == 1
    assert response["failed_count"] == 1
    assert [row["status"] for row in response["results"]] == ["APPROVED", "STALE_CANDIDATE"]
    assert calls[0]["reviewed_by"] == "Authenticated Owner"
    assert calls[0]["reviewer_user_id"] == "user-owner"
    assert calls[0]["reviewer_staff_id"] == "staff-owner"


async def _noop():
    return None
