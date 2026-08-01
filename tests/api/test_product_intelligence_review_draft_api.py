import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_intelligence import router as product_intelligence_router
from agent.api.products import router as products_router
from agent.db import crud


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    app.include_router(product_intelligence_router, prefix="/api")
    return TestClient(app)


def _safe_payload():
    return {
        "product_description": "Compact 500ml bottle for daily routine storage.",
        "benefits_json": ["portable", "compact"],
        "usp_json": ["clean bottle format", "easy shelf fit"],
        "usage_text": "Use as part of a daily routine.",
        "ingredients_text": "Bottle, cap, printed label.",
        "warnings_text": "Store away from direct heat.",
        "target_customer_text": "Busy adults who prefer compact packaging.",
        "allowed_claims_json": ["portable daily carry", "compact shelf storage"],
        "source_urls_json": {"source_url": "https://example.com/source"},
        "image_evidence_json": {"image_url": "https://example.com/image.jpg"},
        "buyer_persona_snapshot_json": {"persona": "busy adults"},
        "copy_strategy_summary_json": {"angle": "compact routine convenience"},
        "created_by": "api-operator",
    }


def test_review_draft_create_list_get_update_and_validate_round_trip():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Draft API Round Trip",
            source="MANUAL",
            product_display_name="Bosmax Draft API Round Trip",
            product_short_name="Bosmax Draft API Round Trip",
        )
    )
    client = _client()

    create_response = client.post(
        f"/api/products/{product['id']}/intelligence/review-drafts",
        json=_safe_payload(),
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["review_status"] == "READY_FOR_REVIEW"
    assert created["claim_gate"] == "CLAIM_SAFE"

    list_response = client.get(
        f"/api/products/{product['id']}/intelligence/review-drafts"
    )
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["draft_id"] == created["draft_id"]

    detail_response = client.get(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["provenance_items"]

    patch_response = client.patch(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}",
        json={"reviewer_note": "Reviewed and updated."},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["reviewer_note"] == "Reviewed and updated."

    validate_response = client.post(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}/validate",
        json={},
    )
    assert validate_response.status_code == 200
    report = validate_response.json()
    assert report["draft"]["draft_id"] == created["draft_id"]
    assert report["readiness_status"] == "READY_FOR_APPROVAL"
    assert report["approval_blockers"] == []


def test_review_draft_approve_creates_snapshot_and_refreshes_latest_snapshot():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Draft API Approve",
            source="MANUAL",
            product_display_name="Bosmax Draft API Approve",
            product_short_name="Bosmax Draft API Approve",
        )
    )
    client = _client()
    created = client.post(
        f"/api/products/{product['id']}/intelligence/review-drafts",
        json=_safe_payload(),
    ).json()

    approve_response = client.post(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}/approve",
        json={"approved_by": "reviewer-api", "approval_note": "approved"},
    )
    assert approve_response.status_code == 200
    snapshot = approve_response.json()
    assert snapshot["status"] == "APPROVED"
    assert snapshot["created_from_review_draft_id"] == created["draft_id"]

    latest_snapshot_response = client.get(
        f"/api/products/{product['id']}/intelligence"
    )
    assert latest_snapshot_response.status_code == 200
    latest_payload = latest_snapshot_response.json()
    assert latest_payload["latest_snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
    assert latest_payload["status"] == "APPROVED_SNAPSHOT_AVAILABLE"

    provenance_response = client.get(
        f"/api/product-intelligence/snapshots/{snapshot['snapshot_id']}/provenance"
    )
    assert provenance_response.status_code == 200
    assert provenance_response.json()["items"]


def test_review_draft_blocked_claim_cannot_be_approved():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Draft API Blocked",
            source="MANUAL",
            product_display_name="Bosmax Draft API Blocked",
            product_short_name="Bosmax Draft API Blocked",
        )
    )
    client = _client()
    created = client.post(
        f"/api/products/{product['id']}/intelligence/review-drafts",
        json={
            **_safe_payload(),
            "product_description": "Guaranteed relief untuk penyakit dan sembuh cepat.",
            "allowed_claims_json": ["cure pain fast"],
        },
    ).json()

    approve_response = client.post(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}/approve",
        json={"approved_by": "reviewer-api"},
    )
    assert approve_response.status_code == 409
    assert approve_response.json()["detail"].startswith("DRAFT_NOT_APPROVABLE:")


def test_review_draft_claim_review_required_cannot_be_approved_without_override():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Draft API Review Required",
            source="MANUAL",
            product_display_name="Bosmax Draft API Review Required",
            product_short_name="Bosmax Draft API Review Required",
        )
    )
    client = _client()
    created = client.post(
        f"/api/products/{product['id']}/intelligence/review-drafts",
        json={
            **_safe_payload(),
            "product_description": "Anti-inflammatory comfort positioning for review.",
            "allowed_claims_json": ["portable daily carry"],
        },
    ).json()

    assert created["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert created["readiness_status"] == "CLAIM_REVIEW_REQUIRED"

    approve_response = client.post(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}/approve",
        json={"approved_by": "reviewer-api"},
    )
    assert approve_response.status_code == 409
    assert "CLAIM_REVIEW_REQUIRED:" in approve_response.json()["detail"]


def test_review_draft_reject_preserves_note_without_snapshot():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Draft API Reject",
            source="MANUAL",
            product_display_name="Bosmax Draft API Reject",
            product_short_name="Bosmax Draft API Reject",
        )
    )
    client = _client()
    created = client.post(
        f"/api/products/{product['id']}/intelligence/review-drafts",
        json=_safe_payload(),
    ).json()

    reject_response = client.post(
        f"/api/product-intelligence/review-drafts/{created['draft_id']}/reject",
        json={"rejected_by": "reviewer-api", "reviewer_note": "Need stronger evidence."},
    )
    assert reject_response.status_code == 200
    rejected = reject_response.json()
    assert rejected["review_status"] == "REJECTED"
    assert rejected["reviewer_note"] == "Need stronger evidence."

    latest_snapshot_response = client.get(
        f"/api/products/{product['id']}/intelligence"
    )
    assert latest_snapshot_response.status_code == 200
    assert latest_snapshot_response.json()["latest_snapshot"] is None


# ── Mission-08D: field-disposition endpoint contract ─────────────────────────
def _gap_payload():
    payload = _safe_payload()
    payload.update({"usage_text": "", "ingredients_text": "", "warnings_text": ""})
    return payload


def _mk_product_and_draft(client, name, category="Automotive"):
    product = asyncio.run(crud.create_product(
        raw_product_title=name, source="MANUAL", product_display_name=name,
        category=category))
    created = client.post(
        f"/api/products/{product['id']}/intelligence/review-drafts",
        json=_gap_payload())
    assert created.status_code == 200, created.text
    return product, created.json()["draft_id"]


def test_field_disposition_endpoint_upserts_and_returns_validation():
    client = _client()
    product, draft_id = _mk_product_and_draft(client, "API Disposition Happy")
    for field in ("usage_text", "ingredients_text", "warnings_text"):
        response = client.post(
            f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
            json={"field_name": field, "disposition": "NOT_STATED_IN_SOURCE",
                  "reviewed_by": "owner",
                  "reviewer_note": "Halaman sumber tidak menyatakan fakta ini."})
        assert response.status_code == 200, response.text
    body = response.json()
    assert body["readiness_status"] == "READY_WITH_GOVERNED_ABSENCE"
    assert set(body["governed_absent_fields"]) == {
        "usage_text", "ingredients_text", "warnings_text"}
    # retry is idempotent at the API layer too
    retry = client.post(
        f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
        json={"field_name": "usage_text", "disposition": "NOT_STATED_IN_SOURCE",
              "reviewed_by": "owner", "reviewer_note": "Ulangan yang sama."})
    assert retry.status_code == 200
    draft = client.get(
        f"/api/product-intelligence/review-drafts/{draft_id}").json()
    rows = [p for p in draft["provenance_items"]
            if p["evidence_kind"] == "FIELD_ABSENCE_DISPOSITION"
            and p["field_name"] == "usage_text"]
    assert len(rows) == 1


def test_field_disposition_endpoint_maps_refusals_to_statuses():
    client = _client()
    _product, draft_id = _mk_product_and_draft(client, "API Disposition Refusals")
    # 422: NA forbidden for a strict (Automotive) category
    na = client.post(
        f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
        json={"field_name": "ingredients_text", "disposition": "NOT_APPLICABLE",
              "reviewed_by": "owner", "reviewer_note": "Cubaan tidak sah."})
    assert na.status_code == 422
    assert "NOT_APPLICABLE_FORBIDDEN_FOR_CATEGORY" in na.json()["detail"]
    # 422: ineligible field
    claims = client.post(
        f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
        json={"field_name": "allowed_claims_json",
              "disposition": "NOT_STATED_IN_SOURCE",
              "reviewed_by": "owner", "reviewer_note": "Tidak boleh."})
    assert claims.status_code == 422
    # 422: empty note
    note = client.post(
        f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
        json={"field_name": "usage_text", "disposition": "NOT_STATED_IN_SOURCE",
              "reviewed_by": "owner", "reviewer_note": " "})
    assert note.status_code == 422

    # 422: anonymous dispositions are forbidden
    reviewer = client.post(
        f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
        json={"field_name": "usage_text", "disposition": "NOT_STATED_IN_SOURCE",
              "reviewed_by": "   ", "reviewer_note": "Nota sah di sini."})
    assert reviewer.status_code == 422
    assert "REVIEWER_REQUIRED" in reviewer.json()["detail"]

    # 404: unknown draft
    missing = client.post(
        "/api/product-intelligence/review-drafts/nope/field-dispositions",
        json={"field_name": "usage_text", "disposition": "NOT_STATED_IN_SOURCE",
              "reviewed_by": "owner", "reviewer_note": "Nota sah di sini."})
    assert missing.status_code == 404
    # invalid disposition literal is rejected by the model itself
    literal = client.post(
        f"/api/product-intelligence/review-drafts/{draft_id}/field-dispositions",
        json={"field_name": "usage_text", "disposition": "SKIP_IT",
              "reviewed_by": "owner", "reviewer_note": "Nota sah di sini."})
    assert literal.status_code == 422
