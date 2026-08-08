"""PR-C Campaign review/variant API surfaces are explicit and credit-free."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_compose import router
from agent.models.poster_campaign_qa import CampaignVariant, CampaignVariantsResponse


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _variants() -> CampaignVariantsResponse:
    return CampaignVariantsResponse(
        product_id="prod-1",
        poster_deliverable_id="pd-1",
        selected_copy_route="ROUTE_01",
        selected_design_route="HERITAGE_EDITORIAL",
        variants=[
            CampaignVariant(
                variant_id=f"v{i}-{'a' * 64}"[:80],
                variant_index=i,
                design_route="HERITAGE_EDITORIAL",
                layout_variant=f"VARIANT_{i}",
                manifest_sha256=chr(96 + i) * 64,
                output_url=f"/v{i}.png",
            )
            for i in range(1, 4)
        ],
        provider_operation_count=0,
        max_retry_operations=0,
    )


def test_campaign_variants_endpoint_has_zero_provider_budget(monkeypatch):
    async def fake_variants(_deliverable_id, _request):
        return _variants()

    monkeypatch.setattr("agent.api.poster_compose.build_campaign_variants", fake_variants)
    response = _client().post("/api/poster/deliverables/pd-1/variants", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["variants"]) == 3
    assert body["provider_operation_count"] == 0
    assert body["max_retry_operations"] == 0


def test_campaign_review_endpoint_requires_explicit_scored_payload(monkeypatch):
    captured = {}

    async def fake_review(deliverable_id, request):
        captured["id"] = deliverable_id
        captured["request"] = request
        return {
            "deliverable": {"poster_deliverable_id": deliverable_id},
            "qa_report": {"ok": True, "findings": [], "block_count": 0, "warn_count": 0},
            "world_class_review": {"decision": request.decision, "total": 88},
            "product_truth_status": "REFERENCE_CONDITIONED_UNVERIFIED",
            "approved_for_poster": False,
        }

    monkeypatch.setattr(
        "agent.api.poster_compose.PosterDeliverableService.review_campaign_deliverable",
        fake_review,
    )
    response = _client().post(
        "/api/poster/deliverables/pd-1/review",
        json={
            "decision": "APPROVED",
            "reviewer": "operator",
            "product_identity": 23,
            "product_integration_physics": 22,
            "typography_copy_hierarchy": 18,
            "malaysian_context_authenticity": 12,
            "conversion_strength": 13,
        },
    )
    assert response.status_code == 200, response.text
    assert captured["id"] == "pd-1"
    assert response.json()["approved_for_poster"] is False


def test_campaign_variant_output_proxies_local_compositor_without_provider(monkeypatch, tmp_path):
    output = Path(tmp_path) / "variant.png"
    output.write_bytes(b"PNG")
    selected = _variants().variants[0]

    async def fake_render(_deliverable_id, _variant_id):
        return output, selected

    monkeypatch.setattr("agent.api.poster_compose.render_campaign_variant", fake_render)
    response = _client().get("/api/poster/deliverables/pd-1/variants/v1/output")
    assert response.status_code == 200
    assert response.content == b"PNG"
    assert response.headers["x-poster-provider-operations"] == "0"
