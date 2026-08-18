"""API contract: Product Truth catalog projection is set-based + PI authority only."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router as products_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    return app


def _base_product(pid: str, title: str) -> dict:
    # Include _CATALOG_PROJECTION_FIELDS so the registry path keeps our row
    # fields (claim_risk_level, etc.) instead of re-deriving mapping.
    return {
        "id": pid,
        "source": "MANUAL",
        "source_lane": "MANUAL",
        "raw_product_title": title,
        "product_display_name": title,
        "product_short_name": title,
        "lifecycle_status": "ACTIVE",
        "claim_risk_level": "LOW",
        "prompt_readiness_status": "READY",
        "updated_at": "2026-04-01T00:00:00Z",
        "created_at": "2026-04-01T00:00:00Z",
        "group": "TEST",
        "bosmax_product_family": "TEST",
        "copy_route": "STANDARD",
        "claim_gate": "CLAIM_CLEAR",
        "intelligence_confidence": "HIGH",
        "image_readiness_status": "READY",
    }


def _wire_catalog(monkeypatch, products, approved_by=None, drafts_by=None):
    approved_by = approved_by or {}
    drafts_by = drafts_by or {}
    call_log = {"approved_calls": 0, "draft_calls": 0, "approved_ids": [], "draft_ids": []}

    async def fake_list_products(**kwargs):
        return list(products)

    async def fake_approved(ids):
        call_log["approved_calls"] += 1
        call_log["approved_ids"].append(list(ids))
        return {k: v for k, v in approved_by.items() if k in set(ids)}

    async def fake_drafts(ids):
        call_log["draft_calls"] += 1
        call_log["draft_ids"].append(list(ids))
        return {k: v for k, v in drafts_by.items() if k in set(ids)}

    async def empty_map(*_a, **_k):
        return {}

    async def empty_list(*_a, **_k):
        return []

    async def annotate_visual(items):
        return items

    async def attach_tax(items):
        return items

    monkeypatch.setattr("agent.db.crud.list_products", fake_list_products)
    monkeypatch.setattr(
        "agent.db.crud.latest_approved_product_intelligence_snapshots_by_products",
        fake_approved,
    )
    monkeypatch.setattr(
        "agent.db.crud.latest_actionable_review_drafts_by_products",
        fake_drafts,
    )
    monkeypatch.setattr(
        "agent.db.crud.count_source_media_by_products",
        empty_map,
    )
    monkeypatch.setattr(
        "agent.db.crud.latest_open_review_drafts_by_products",
        empty_map,
    )
    monkeypatch.setattr(
        "agent.services.product_visual_onboarding_service.annotate_products_visual_readiness",
        annotate_visual,
    )
    monkeypatch.setattr(
        "agent.services.product_strategy_taxonomy_service.attach_product_strategy_taxonomies",
        attach_tax,
    )
    # Avoid FastMoss reference merge cost.
    async def no_refs(*_a, **_k):
        return []

    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.list_fastmoss_reference_products",
        no_refs,
    )
    return call_log


def test_catalog_product_truth_projection_matrix_and_no_n_plus_one(monkeypatch):
    products = [
        _base_product("p-approved", "Approved Only"),
        _base_product("p-pending", "Approved Update Pending"),
        _base_product("p-review", "Needs Review"),
        _base_product("p-action", "Action Required"),
        _base_product("p-none", "Not Started"),
    ]
    approved = {
        "p-approved": {
            "version": 4,
            "status": "APPROVED",
            "approved_at": "2026-04-01T00:00:00Z",
            "created_at": "2026-04-01T00:00:00Z",
        },
        "p-pending": {
            "version": 2,
            "status": "APPROVED",
            "approved_at": "2026-04-01T00:00:00Z",
            "created_at": "2026-04-01T00:00:00Z",
        },
    }
    drafts = {
        "p-pending": {
            "draft_id": "d-pending",
            "review_status": "READY_FOR_REVIEW",
            "updated_at": "2026-04-10T00:00:00Z",
            "created_at": "2026-04-10T00:00:00Z",
            "revision_of_snapshot_id": "snap-x",
        },
        "p-review": {
            "draft_id": "d-review",
            "review_status": "READY_FOR_REVIEW",
            "claim_gate": "CLAIM_CLEAR",
            "readiness_status": "READY",
            "updated_at": "2026-04-05T00:00:00Z",
        },
        "p-action": {
            "draft_id": "d-action",
            "review_status": "NEEDS_REVISION",
            "claim_gate": "CLAIM_CLEAR",
            "readiness_status": "READY",
            "updated_at": "2026-04-05T00:00:00Z",
        },
    }
    call_log = _wire_catalog(monkeypatch, products, approved, drafts)
    client = TestClient(_build_app())

    resp = client.get("/api/products?view=REGISTRY&limit=50&exclude_reference=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 5
    by_id = {item["id"]: item for item in body["items"]}

    assert by_id["p-approved"]["product_truth_status"] == "APPROVED"
    assert by_id["p-approved"]["product_truth_update_pending"] is False
    assert by_id["p-approved"]["product_truth_action_label"] == "View Product Truth"
    assert by_id["p-approved"]["product_truth_approved_snapshot_version"] == 4
    assert by_id["p-approved"]["open_review_draft"] is None

    assert by_id["p-pending"]["product_truth_status"] == "APPROVED"
    assert by_id["p-pending"]["product_truth_update_pending"] is True
    assert by_id["p-pending"]["product_truth_action_label"] == "Review Update"
    assert by_id["p-pending"]["open_review_draft"]["review_status"] == "READY_FOR_REVIEW"

    assert by_id["p-review"]["product_truth_status"] == "NEEDS_REVIEW"
    assert by_id["p-review"]["open_review_draft"]["review_status"] == "READY_FOR_REVIEW"
    assert by_id["p-action"]["product_truth_status"] == "ACTION_REQUIRED"
    assert by_id["p-action"]["open_review_draft"]["review_status"] == "NEEDS_REVISION"
    assert by_id["p-none"]["product_truth_status"] == "NOT_STARTED"
    assert by_id["p-none"]["open_review_draft"] is None

    summary = body["product_truth_summary"]
    assert summary["APPROVED"] == 2
    assert summary["UPDATE_PENDING"] == 1
    assert summary["NEEDS_REVIEW"] == 1
    assert summary["ACTION_REQUIRED"] == 1
    assert summary["NOT_STARTED"] == 1

    # Set-based: exactly one batch call each (not per-product).
    assert call_log["approved_calls"] == 1
    assert call_log["draft_calls"] == 1
    assert len(call_log["approved_ids"][0]) == 5


def test_catalog_product_truth_filter_server_side(monkeypatch):
    products = [
        _base_product("p-approved", "A"),
        _base_product("p-pending", "B"),
        _base_product("p-review", "C"),
        _base_product("p-action", "D"),
        _base_product("p-none", "E"),
    ]
    approved = {
        "p-approved": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "p-pending": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    drafts = {
        "p-pending": {
            "review_status": "DRAFT",
            "updated_at": "2026-02-01T00:00:00Z",
            "revision_of_snapshot_id": "s1",
        },
        "p-review": {"review_status": "READY_FOR_REVIEW"},
        "p-action": {"review_status": "NEEDS_REVISION"},
    }
    _wire_catalog(monkeypatch, products, approved, drafts)
    client = TestClient(_build_app())

    cases = [
        ("APPROVED", {"p-approved", "p-pending"}),
        ("APPROVED_UPDATE_PENDING", {"p-pending"}),
        ("NEEDS_REVIEW", {"p-review"}),
        ("ACTION_REQUIRED", {"p-action"}),
        ("NOT_STARTED", {"p-none"}),
    ]
    for token, expected_ids in cases:
        resp = client.get(
            f"/api/products?view=REGISTRY&limit=50&exclude_reference=true&product_truth={token}"
        )
        assert resp.status_code == 200, token
        body = resp.json()
        got = {item["id"] for item in body["items"]}
        assert got == expected_ids, token
        assert body["total_count"] == len(expected_ids)


def test_catalog_product_truth_summary_is_full_scope_not_page(monkeypatch):
    # 3 products, page size 1 — summary must still reflect full filtered scope.
    products = [
        _base_product("p1", "One"),
        _base_product("p2", "Two"),
        _base_product("p3", "Three"),
    ]
    approved = {
        "p1": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    drafts = {
        "p2": {"review_status": "READY_FOR_REVIEW"},
    }
    _wire_catalog(monkeypatch, products, approved, drafts)
    client = TestClient(_build_app())
    resp = client.get("/api/products?view=REGISTRY&limit=1&offset=0&exclude_reference=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["returned_count"] == 1
    assert body["total_count"] == 3
    assert body["product_truth_summary"] == {
        "APPROVED": 1,
        "NEEDS_REVIEW": 1,
        "ACTION_REQUIRED": 0,
        "NOT_STARTED": 1,
        "UPDATE_PENDING": 0,
    }


def test_catalog_product_truth_composes_with_risk_filter(monkeypatch):
    products = [
        {**_base_product("hi", "High risk approved"), "claim_risk_level": "HIGH"},
        {**_base_product("lo", "Low risk approved"), "claim_risk_level": "LOW"},
        {**_base_product("hi-none", "High risk none"), "claim_risk_level": "HIGH"},
    ]
    approved = {
        "hi": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "lo": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    _wire_catalog(monkeypatch, products, approved, {})
    client = TestClient(_build_app())
    resp = client.get(
        "/api/products?view=REGISTRY&limit=50&exclude_reference=true"
        "&claim_risk_level=HIGH&product_truth=APPROVED"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {item["id"] for item in body["items"]} == {"hi"}
    assert body["product_truth_summary"]["APPROVED"] == 1
    assert body["product_truth_summary"]["NOT_STARTED"] == 0


def test_catalog_review_draft_column_excludes_terminal_history(monkeypatch):
    """Review Draft column is actionable-only; terminal drafts never surface."""
    products = [
        _base_product("sambal", "Sambal Nyet Berapi by Khairulaming"),
        _base_product("rej", "Rejected only"),
        _base_product("sup", "Superseded only"),
        _base_product("ready", "Ready revision"),
        _base_product("needs", "Needs revision"),
        _base_product("draft-only", "Draft only no snapshot"),
    ]
    products[0]["id"] = "d2f8fd58-437b-4447-8730-694b782eef17"
    sambal_id = products[0]["id"]

    approved = {
        sambal_id: {
            "snapshot_id": "snap-sambal",
            "version": 5,
            "status": "APPROVED",
            "approved_at": "2026-08-08T15:40:14Z",
            "created_at": "2026-08-08T15:40:14Z",
        },
        "rej": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "sup": {
            "version": 1,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "ready": {
            "version": 2,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
        "needs": {
            "version": 2,
            "status": "APPROVED",
            "approved_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    drafts = {
        "ready": {
            "draft_id": "d-ready",
            "review_status": "READY_FOR_REVIEW",
            "updated_at": "2026-02-01T00:00:00Z",
            "created_at": "2026-02-01T00:00:00Z",
            "revision_of_snapshot_id": "snap-ready",
        },
        "needs": {
            "draft_id": "d-needs",
            "review_status": "NEEDS_REVISION",
            "updated_at": "2026-02-01T00:00:00Z",
            "created_at": "2026-02-01T00:00:00Z",
            "revision_of_snapshot_id": "snap-needs",
        },
        "draft-only": {
            "draft_id": "d-draft",
            "review_status": "DRAFT",
            "updated_at": "2026-02-01T00:00:00Z",
            "created_at": "2026-02-01T00:00:00Z",
        },
    }
    call_log = _wire_catalog(monkeypatch, products, approved, drafts)

    async def legacy_open_must_not_drive_column(ids):
        call_log["legacy_open_calls"] = call_log.get("legacy_open_calls", 0) + 1
        return {
            sambal_id: {
                "draft_id": "terminal-approved",
                "review_status": "APPROVED",
                "updated_at": "2026-08-08T15:40:14Z",
            },
            "rej": {
                "draft_id": "t-rej",
                "review_status": "REJECTED",
                "updated_at": "2026-01-02T00:00:00Z",
            },
            "sup": {
                "draft_id": "t-sup",
                "review_status": "SUPERSEDED",
                "updated_at": "2026-01-02T00:00:00Z",
            },
        }

    monkeypatch.setattr(
        "agent.db.crud.latest_open_review_drafts_by_products",
        legacy_open_must_not_drive_column,
    )

    client = TestClient(_build_app())
    resp = client.get("/api/products?view=REGISTRY&limit=50&exclude_reference=true")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {item["id"]: item for item in body["items"]}

    s = by_id[sambal_id]
    assert s["product_truth_status"] == "APPROVED"
    assert s["product_truth_update_pending"] is False
    assert s["product_truth_action_label"] == "View Product Truth"
    assert s["open_review_draft"] is None

    assert by_id["rej"]["product_truth_status"] == "APPROVED"
    assert by_id["rej"]["open_review_draft"] is None
    assert by_id["sup"]["product_truth_status"] == "APPROVED"
    assert by_id["sup"]["open_review_draft"] is None

    r = by_id["ready"]
    assert r["product_truth_status"] == "APPROVED"
    assert r["product_truth_update_pending"] is True
    assert r["open_review_draft"]["review_status"] == "READY_FOR_REVIEW"
    assert r["open_review_draft"]["draft_id"] == "d-ready"

    n = by_id["needs"]
    assert n["product_truth_status"] == "APPROVED"
    assert n["open_review_draft"]["review_status"] == "NEEDS_REVISION"

    d = by_id["draft-only"]
    assert d["product_truth_status"] == "NEEDS_REVIEW"
    assert d["open_review_draft"]["review_status"] == "DRAFT"

    assert call_log["draft_calls"] == 1
    resp2 = client.get("/api/products?view=REGISTRY&limit=2&offset=0&exclude_reference=true")
    assert resp2.status_code == 200
    b2 = resp2.json()
    assert b2["returned_count"] == 2
    assert b2["total_count"] == 6
    assert call_log.get("legacy_open_calls", 0) == 0
