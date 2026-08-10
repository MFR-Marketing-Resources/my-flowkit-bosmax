import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router
from agent.services import avatar_registry


def test_system_delete_returns_deterministic_409_before_asset_archive(tmp_path, monkeypatch):
    asset_calls: list[str] = []

    seed = tmp_path / "system.csv"
    bridge = tmp_path / "custom.csv"
    shutil.copyfile(avatar_registry._POOL_FILE, seed)
    monkeypatch.setattr(avatar_registry, "_POOL_FILE", seed)
    monkeypatch.setattr(avatar_registry, "_BRIDGE_FILE", bridge)
    avatar_registry.reload_pool()
    seed_before = seed.read_bytes()

    async def unexpected_list(**_kwargs):
        asset_calls.append("list")
        return []

    monkeypatch.setattr("agent.services.creative_asset_service.list_creative_assets", unexpected_list)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    response = TestClient(app).delete("/api/workspace/avatar-registry/BOS_F_ALYA_01")
    assert response.status_code == 409
    assert response.json()["detail"] == "SYSTEM_AVATAR_IMMUTABLE"
    assert asset_calls == []
    assert seed.read_bytes() == seed_before
    assert not bridge.exists()
