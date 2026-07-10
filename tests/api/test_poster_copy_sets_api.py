"""Poster Copy Set + compose API contract (POSTER_BUILDER_V2)."""
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
async def product_id():
    row = await crud.create_product(
        "Minyak Warisan Tok 25ml", source="MANUAL",
        product_display_name="Minyak Warisan Tok", category="Traditional",
    )
    return row["id"]


def _payload(product_id: str) -> dict:
    return {
        "product_id": product_id,
        "objective": "Product introduction",
        "archetype": "PRODUCT_HERO",
        "angle": "Premium hero",
        "primary_message": "Minyak warisan keluarga",
        "support_message": "Sedia bila anda perlukan.",
        "proof_points": ["Saiz poket"],
        "cta": "Beli sekarang",
        "language": "ms",
    }


def test_full_copy_set_api_lifecycle(product_id):
    c = _client()
    # Create draft.
    r = c.post("/api/poster/copy-sets", json=_payload(product_id))
    assert r.status_code == 200, r.text
    pcs = r.json()
    pcs_id = pcs["poster_copy_set_id"]
    assert pcs["status"] == "POSTER_COPY_DRAFT"
    # List + get.
    assert any(
        x["poster_copy_set_id"] == pcs_id
        for x in c.get(f"/api/poster/copy-sets?product_id={product_id}").json()["poster_copy_sets"]
    )
    # Approve requires the explicit phrase.
    r = c.post(f"/api/poster/copy-sets/{pcs_id}/approve",
               json={"approval_phrase": "ok", "approved_by": "op"})
    assert r.status_code == 422
    r = c.post(f"/api/poster/copy-sets/{pcs_id}/approve",
               json={"approval_phrase": POSTER_COPY_APPROVAL_PHRASE, "approved_by": "op"})
    assert r.status_code == 200
    assert r.json()["status"] == "POSTER_COPY_APPROVED"
    # Approved is immutable via PATCH.
    r = c.patch(f"/api/poster/copy-sets/{pcs_id}", json={"primary_message": "Edit"})
    assert r.status_code == 409
    # New version supersedes.
    r = c.post(f"/api/poster/copy-sets/{pcs_id}/new-version",
               json={"primary_message": "Versi kedua"})
    assert r.status_code == 200
    assert r.json()["version"] == 2


def test_recommenders_work_without_ai(product_id, monkeypatch):
    import agent.services.poster_copy_ai_service as svc
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    c = _client()
    r = c.post("/api/poster/copy-sets/recommend-objectives",
               json={"product_id": product_id})
    assert r.status_code == 200
    assert len(r.json()["recommendations"]) == 6
    r = c.post("/api/poster/copy-sets/recommend-angles",
               json={"product_id": product_id, "archetype": "PRODUCT_HERO"})
    assert r.status_code == 200
    assert r.json()["angles"]
    r = c.post("/api/poster/copy-sets/directions",
               json={"product_id": product_id, "archetype": "PRODUCT_HERO",
                     "angle": "Premium hero"})
    assert r.status_code == 200
    assert len(r.json()["directions"]) == 3
    # Field regen fails closed without a provider.
    r = c.post("/api/poster/copy-sets/regenerate-field",
               json={"product_id": product_id, "archetype": "PRODUCT_HERO",
                     "angle": "x", "field": "cta", "fields": {}})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "POSTER_AI_NOT_CONFIGURED"


def test_compose_api_flow_with_mocked_renderer(product_id, tmp_path, monkeypatch):
    from agent.models.poster_render_manifest import PosterRenderReport, ZoneRenderResult
    from agent.services import poster_compositor_service as compositor

    async def fake_compose(manifest, *, render_id: str = ""):
        out = tmp_path / "poster.png"
        out.write_bytes(b"PNGBYTES" * 16)
        zones = [
            ZoneRenderResult(zone_id=z.zone_id, fitted=True, overflowed=False,
                             overlaps_product=False, font_scale=1.0)
            for z in manifest.zones
        ]
        return out, PosterRenderReport(
            renderer="HTML_CHROMIUM_SERVICE_V1", canvas={"w": 1080, "h": 1920},
            output_png={"width": 1080, "height": 1920}, zones=zones, ok=True,
        )

    monkeypatch.setattr(compositor, "compose", fake_compose)
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"BG")
    c = _client()
    pcs = c.post("/api/poster/copy-sets", json=_payload(product_id)).json()
    c.post(f"/api/poster/copy-sets/{pcs['poster_copy_set_id']}/approve",
           json={"approval_phrase": POSTER_COPY_APPROVAL_PHRASE, "approved_by": "op"})
    r = c.post("/api/poster/compose", json={
        "product_id": product_id,
        "poster_copy_set_id": pcs["poster_copy_set_id"],
        "recipe_id": "product_hero_night_routine",
        "background_local_path": str(bg),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    did = body["deliverable"]["poster_deliverable_id"]
    assert body["qa_report"]["ok"] is True
    # Output served as the exact composed file.
    out = c.get(f"/api/poster/deliverables/{did}/output")
    assert out.status_code == 200
    assert out.content == (tmp_path / "poster.png").read_bytes()
    # Reconstruction endpoint.
    info = c.get(f"/api/poster/deliverables/{did}").json()
    assert info["render_manifest"]["zones"]
    assert info["poster_copy_set"]["primary_message"] == "Minyak warisan keluarga"
    # Save to library (creative asset mocked at the service seam).
    async def fake_create_asset(request):
        class _A:
            asset_id = "ca_api_test"
        return _A()
    monkeypatch.setattr(
        "agent.services.poster_deliverable_service.create_creative_asset",
        fake_create_asset,
    )
    r = c.post(f"/api/poster/deliverables/{did}/save-to-library")
    assert r.status_code == 200
    assert r.json()["creative_asset_id"] == "ca_api_test"
