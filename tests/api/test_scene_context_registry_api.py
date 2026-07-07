"""Scene-context registry API surface contract."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.scene_context_registry import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


async def _no_generated_assets(*_args, **_kwargs):
    # Mock the DB-backed generated-asset lookup so the pool endpoint needs no DB.
    return []


def test_pool_lists_20_seeded_scenes(monkeypatch):
    monkeypatch.setattr(
        "agent.services.creative_asset_service.list_creative_assets",
        _no_generated_assets,
    )
    client = TestClient(_build_app())
    response = client.get("/api/workspace/scene-context-registry/pool")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 20
    assert body["generated_count"] == 0  # none generated yet
    codes = {s["scene_code"] for s in body["scenes"]}
    assert "SCN_RAYA_KAMPUNG" in codes and "SCN_WHITE_STUDIO_BERSIH" in codes
    # every scene exposes the selectable fields the UI + dropdowns need
    for scene in body["scenes"]:
        assert scene["scene_name"] and scene["background_prompt"]
        assert "image_generated" in scene


def test_status_reports_pool_size():
    client = TestClient(_build_app())
    response = client.get("/api/workspace/scene-context-registry/status")
    assert response.status_code == 200
    assert response.json()["approved_scenes"] == 20


def test_generate_image_requires_credit_confirmation():
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/generate-image",
        json={"scene_code": "SCN_RAYA_KAMPUNG"},  # confirm_credit_burn defaults False
    )
    assert response.status_code == 422
    assert "CONFIRM_CREDIT_BURN_REQUIRED" in response.text


def test_generate_image_unknown_scene_404():
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/generate-image",
        json={"scene_code": "SCN_NOPE", "confirm_credit_burn": True},
    )
    assert response.status_code == 404
    assert "SCENE_NOT_FOUND" in response.text


def test_sync_rejects_missing_columns():
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/sync",
        content=b"Foo,Bar\n1,2\n",
    )
    assert response.status_code == 422
    assert "SCENE_REGISTRY_COLUMNS_MISSING" in response.text


def test_register_generated_constructs_valid_request_and_stamps_scene_governance(
    monkeypatch, tmp_path
):
    """The load-bearing path: register-generated must construct a VALID
    CreativeAssetCreateRequest (no extra-forbidden kwargs) and stamp the exact
    SCENE_REFERENCE lane governance + APPROVED so the scene becomes selectable in
    I2V/F2V. Regression guard for the extra='forbid' ValidationError."""
    from types import SimpleNamespace

    artifact_file = tmp_path / "scene_plate.jpg"
    artifact_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF-fake-jpeg-bytes")

    async def fake_artifacts(*_a, **_k):
        return [{"media_id": "m-scene-1", "local_path": str(artifact_file)}]

    async def fake_list_assets(*_a, **_k):
        return []  # no existing scene asset → no 409

    captured: dict = {}

    async def fake_create(req):
        captured["req"] = req
        return SimpleNamespace(asset_id="ca_scene_test")

    monkeypatch.setattr("agent.db.crud.list_generated_artifacts", fake_artifacts)
    monkeypatch.setattr(
        "agent.services.creative_asset_service.list_creative_assets", fake_list_assets)
    monkeypatch.setattr(
        "agent.services.creative_asset_service.create_creative_asset", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/register-generated",
        json={"scene_code": "SCN_RAYA_KAMPUNG", "media_id": "m-scene-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["asset_id"] == "ca_scene_test"
    assert response.json()["scene_code"] == "SCN_RAYA_KAMPUNG"

    req = captured["req"]  # the real CreativeAssetCreateRequest that was constructed
    assert req.semantic_role == "SCENE_CONTEXT_REFERENCE"
    assert req.allowed_modes == ["I2V", "IMG"]          # → shows in I2V dropdown
    assert req.engine_slot_eligibility == ["scene", "style"]
    assert req.review_status == "APPROVED"              # → passes require_approved gate
    assert req.contains_rendered_text is False          # clean plate
    assert "SCENE_CODE:SCN_RAYA_KAMPUNG" in req.description
    assert req.generation_recipe_id == "SCENE_REFERENCE"


# ── Manual add + AI auto-generate (additive). The AI adapter is ALWAYS mocked —
# no real provider network call ever happens in these tests.

def test_add_manual_redundant_scene_409():
    """A scene whose name already exists in the pool fails closed with 409."""
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/add-manual",
        json={"scene_name": "Raya Kampung",
              "background_prompt": "Background: something different"},
    )
    assert response.status_code == 409
    assert "SCENE_REDUNDANT" in response.text


def test_add_manual_happy_path(monkeypatch):
    """A distinct scene is added through the (mocked) add_scene door and returns
    a SCN_ code — the real bridge/pool is never touched."""
    captured: dict = {}

    def fake_add_scene(row):
        captured["row"] = row
        return {"rows": 21, "approved_loaded": 21, "bridge_path": "x"}

    monkeypatch.setattr(
        "agent.services.scene_context_registry.add_scene", fake_add_scene)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/add-manual",
        json={"scene_name": "Neon Arcade Lobby",
              "background_prompt": "Background: glowing neon arcade, retro cabinets",
              "usage_tags": "neon|arcade"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scene_code"] == "SCN_NEON_ARCADE_LOBBY"
    assert body["scene_name"] == "Neon Arcade Lobby"
    # the row that was assembled carries a clean-plate PromptV1 + approved flag
    row = captured["row"]
    assert row["SceneCode"] == "SCN_NEON_ARCADE_LOBBY"
    assert row["approved_flag"] == "TRUE"
    assert "no people and no product" in row["PromptV1"].lower()


def test_auto_generate_fail_closed_when_unconfigured(monkeypatch):
    """Unconfigured text_assist lane → 503, no provider call attempted."""
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: False)
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/auto-generate",
        json={"brief": "a cozy hawker stall at night"},
    )
    assert response.status_code == 503
    assert "TEXT_ASSIST_NOT_CONFIGURED" in response.text


def test_auto_generate_happy_path_mocked_adapter(monkeypatch):
    """Configured lane + mocked complete_json returning a valid distinct scene →
    200 with a scene_code. The provider is NEVER really called; add_scene mocked."""
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)

    def fake_complete_json(system, user):
        return {
            "scene_name": "Hawker Stall Night Market",
            "background_prompt": "Background: bustling hawker stall alley at night, "
                                 "warm string lights, steam, shallow depth of field",
            "usage_tags": ["hawker", "night", "street"],
        }

    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json", fake_complete_json)

    captured: dict = {}

    def fake_add_scene(row):
        captured["row"] = row
        return {"rows": 21, "approved_loaded": 21, "bridge_path": "x"}

    monkeypatch.setattr(
        "agent.services.scene_context_registry.add_scene", fake_add_scene)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/auto-generate",
        json={"brief": "night street food scene"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated"] is True
    assert body["scene_code"].startswith("SCN_HAWKER_STALL_NIGHT_MARKET")
    assert body["scene_name"] == "Hawker Stall Night Market"
    assert captured["row"]["usage_tags"] == "hawker|night|street"


def test_auto_generate_invalid_ai_json_502(monkeypatch):
    """A configured lane returning a dict missing required keys → 502."""
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json",
        lambda system, user: {"scene_name": "Only A Name"})  # no background_prompt
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/scene-context-registry/auto-generate",
        json={"brief": "x"},
    )
    assert response.status_code == 502
    assert "AI_SCENE_INVALID" in response.text
