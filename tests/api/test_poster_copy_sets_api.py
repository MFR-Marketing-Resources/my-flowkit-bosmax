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


def test_new_version_route_is_registered_once():
    """A duplicate FastAPI registration makes the route contract ambiguous."""
    routes = [
        route
        for route in copy_sets_router.routes
        if route.path == "/poster/copy-sets/{poster_copy_set_id}/new-version"
        and route.methods == {"POST"}
    ]
    assert len(routes) == 1


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
    from agent.services import poster_deliverable_service as deliverable_svc
    monkeypatch.setattr(
        deliverable_svc,
        "_ALLOWED_BACKGROUND_ROOTS",
        (*deliverable_svc._ALLOWED_BACKGROUND_ROOTS, tmp_path),
    )
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


# ─── Repair PR: new-version route, by-asset round trip, path security ────────

def test_new_version_route_supersedes_parent_atomically(product_id):
    c = _client()
    r = c.post("/api/poster/copy-sets", json=_payload(product_id))
    assert r.status_code == 200, r.text
    pcs = r.json()
    r = c.post(
        f"/api/poster/copy-sets/{pcs['poster_copy_set_id']}/approve",
        json={"approval_phrase": POSTER_COPY_APPROVAL_PHRASE, "approved_by": "op"},
    )
    assert r.status_code == 200, r.text
    r = c.post(
        f"/api/poster/copy-sets/{pcs['poster_copy_set_id']}/new-version",
        json={"primary_message": "Versi baharu tajuk"},
    )
    assert r.status_code == 200, r.text
    child = r.json()
    assert child["version"] == 2
    assert child["status"] == "POSTER_COPY_DRAFT"
    assert child["parent_poster_copy_set_id"] == pcs["poster_copy_set_id"]
    parent = c.get(f"/api/poster/copy-sets/{pcs['poster_copy_set_id']}").json()
    assert parent["status"] == "POSTER_COPY_SUPERSEDED"
    # New-version on a non-approved (now superseded) parent is refused.
    r = c.post(
        f"/api/poster/copy-sets/{pcs['poster_copy_set_id']}/new-version",
        json={"primary_message": "Cuba lagi"},
    )
    assert r.status_code == 409


def test_deliverable_by_asset_route_404_when_unknown():
    c = _client()
    r = c.get("/api/poster/deliverables/by-asset/ca_unknown_asset")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "POSTER_DELIVERABLE_NOT_FOUND"


def test_compose_rejects_background_path_outside_roots(product_id, tmp_path):
    """API surface: arbitrary client paths are refused with a structured 422."""
    c = _client()
    r = c.post("/api/poster/copy-sets", json=_payload(product_id))
    pcs = r.json()
    bg = tmp_path / "evil.png"
    bg.write_bytes(b"\x89PNG_FAKE")
    r = c.post("/api/poster/compose", json={
        "product_id": product_id,
        "poster_copy_set_id": pcs["poster_copy_set_id"],
        "recipe_id": "product_hero_night_routine",
        "background_local_path": str(bg),
    })
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "POSTER_BACKGROUND_PATH_FORBIDDEN"


# ─── Closure: fork-historical route (item A) ────────────────────────────────


def test_fork_historical_route_forks_without_mutating(product_id):
    c = _client()
    r = c.post("/api/poster/copy-sets", json=_payload(product_id))
    assert r.status_code == 200, r.text
    pcs = r.json()
    parent_id = pcs["poster_copy_set_id"]
    c.post(f"/api/poster/copy-sets/{parent_id}/approve",
           json={"approval_phrase": POSTER_COPY_APPROVAL_PHRASE, "approved_by": "op"})
    # Supersede via new-version so the parent becomes historical.
    r = c.post(f"/api/poster/copy-sets/{parent_id}/new-version",
               json={"primary_message": "Versi kedua"})
    assert r.status_code == 200, r.text
    parent = c.get(f"/api/poster/copy-sets/{parent_id}").json()
    assert parent["status"] == "POSTER_COPY_SUPERSEDED"

    # Fork a fresh draft from the historical (superseded) parent.
    r = c.post(f"/api/poster/copy-sets/{parent_id}/fork-historical",
               json={"primary_message": "Draf sejarah"})
    assert r.status_code == 200, r.text
    forked = r.json()
    assert forked["status"] == "POSTER_COPY_DRAFT"
    assert forked["primary_message"] == "Draf sejarah"

    # Historical parent is unchanged.
    parent_after = c.get(f"/api/poster/copy-sets/{parent_id}").json()
    assert parent_after["status"] == "POSTER_COPY_SUPERSEDED"

    # Forking a non-superseded (fresh draft) is rejected 409.
    fresh = c.post("/api/poster/copy-sets", json=_payload(product_id)).json()
    r = c.post(
        f"/api/poster/copy-sets/{fresh['poster_copy_set_id']}/fork-historical", json={}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "POSTER_COPY_SET_NOT_HISTORICAL"
