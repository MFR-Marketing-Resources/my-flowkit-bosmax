"""PR-C credit-free Campaign compose → QA → variants → human review flow."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_compose import router as compose_router
from agent.api.poster_copy_sets import router as copy_sets_router
from agent.db import crud
from agent.models.poster_copy_set import POSTER_COPY_APPROVAL_PHRASE


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(copy_sets_router, prefix="/api")
    app.include_router(compose_router, prefix="/api")
    return TestClient(app)


@pytest.fixture
async def campaign_product_id():
    from tests.conftest import make_product_copy_eligible

    row = await crud.create_product(
        "Minyak Warisan Cap Burung 25ml",
        source="MANUAL",
        product_display_name="Minyak Warisan Cap Burung 25ml",
        category="Traditional Wellness",
    )
    await make_product_copy_eligible(row["id"])
    return row["id"]


def _copy_payload(product_id: str) -> dict:
    return {
        "product_id": product_id,
        "objective": "Product Hero",
        "archetype": "PRODUCT_HERO",
        "angle": "Warisan keluarga",
        "primary_message": "Warisan dekat dengan rutin",
        "support_message": "Formula tradisional untuk pilihan keluarga.",
        "proof_points": ["Formula tradisional"],
        "cta": "Lihat pilihan",
        "language": "ms",
        "field_provenance": {"primary_message": "APPROVED_SNAPSHOT.copy_strategy"},
    }


def test_campaign_compose_adds_qa_and_three_local_variants(
    campaign_product_id, tmp_path, monkeypatch
):
    from agent.models.poster_render_manifest import PosterRenderReport, ZoneRenderResult
    from agent.services import poster_deliverable_service as deliverable_service

    async def fake_resolve_background(_media_id, _local_path):
        return "media-kv-1", str(tmp_path / "key-visual.png")

    async def fake_compose(manifest, *, render_id: str = ""):
        out = tmp_path / f"{render_id or 'poster'}.png"
        out.write_bytes(b"campaign-png")
        return out, PosterRenderReport(
            renderer="HTML_CHROMIUM_SERVICE_V1",
            canvas={"w": 1080, "h": 1920},
            output_png={"width": 1080, "height": 1920},
            zones=[
                ZoneRenderResult(
                    zone_id=zone.zone_id,
                    fitted=True,
                    overflowed=False,
                    overlaps_product=False,
                    rendered_text=zone.text,
                )
                for zone in manifest.zones
            ],
            ok=True,
        )

    monkeypatch.setattr(deliverable_service, "_resolve_background", fake_resolve_background)
    monkeypatch.setattr(deliverable_service.compositor, "compose", fake_compose)
    client = _client()
    copy_set = client.post("/api/poster/copy-sets", json=_copy_payload(campaign_product_id)).json()
    approved = client.post(
        f"/api/poster/copy-sets/{copy_set['poster_copy_set_id']}/approve",
        json={"approval_phrase": POSTER_COPY_APPROVAL_PHRASE, "approved_by": "operator"},
    )
    assert approved.status_code == 200, approved.text
    composed = client.post(
        "/api/poster/compose",
        json={
            "product_id": campaign_product_id,
            "poster_copy_set_id": copy_set["poster_copy_set_id"],
            "recipe_id": "product_hero_night_routine",
            "background_media_id": "media-kv-1",
            "creative_mode": "CREATIVE_CAMPAIGN",
            "image_model": "NANO_BANANA_PRO",
            "settings": {
                "pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE",
                "raw_key_visual_is_lineage_only": True,
            },
        },
    )
    assert composed.status_code == 200, composed.text
    body = composed.json()
    assert body["qa_report"]["campaign_qa"]["clean_key_visual_lineage"] is True
    assert body["qa_report"]["machine_qa"]["machine_qa_status"] == "WARN"
    deliverable_id = body["deliverable"]["poster_deliverable_id"]

    variants = client.post(f"/api/poster/deliverables/{deliverable_id}/variants", json={})
    assert variants.status_code == 200, variants.text
    assert len(variants.json()["variants"]) == 3
    assert variants.json()["provider_operation_count"] == 0

    reviewed = client.post(
        f"/api/poster/deliverables/{deliverable_id}/review",
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
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["world_class_review"]["total"] == 88
    assert reviewed.json()["approved_for_poster"] is False
