from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


class _Cursor:
    async def fetchall(self):
        return [("BOS_F_ACTIVE_01",)]


class _DB:
    async def execute(self, *args, **kwargs):
        return _Cursor()


def test_active_product_fit_projects_only_mapped_adult_pool_rows(monkeypatch):
    from agent.services import avatar_registry

    monkeypatch.setattr(avatar_registry, "list_pool", lambda: [
        {"avatar_code": "BOS_F_ACTIVE_01", "character_name": "Active", "age_band": "Adult (30-54)"},
        {"avatar_code": "BOS_F_CHILD_01", "character_name": "Child", "age_band": "Child (6-12)"},
        {"avatar_code": "BOS_F_LEGACY_01", "character_name": "Legacy", "age_band": "Adult (30-54)"},
    ])
    monkeypatch.setattr(avatar_registry, "_active_pool_file", lambda: "repo-seed.csv")
    monkeypatch.setattr(avatar_registry, "_BRIDGE_FILE", type("Bridge", (), {"exists": lambda self: False})())

    async def fake_fits(limit=10_000):
        return [
            {"avatar_code": "BOS_F_ACTIVE_01", "product_category": "beauty", "fit_score": 0.9},
            {"avatar_code": "BOS_F_CHILD_01", "product_category": "beauty", "fit_score": 1.0},
        ]

    async def fake_assets():
        return {"BOS_F_ACTIVE_01": "asset-1"}

    async def fake_db():
        return _DB()

    monkeypatch.setattr("agent.db.crud.list_avatar_product_fits", fake_fits)
    monkeypatch.setattr("agent.db.crud.get_db", fake_db)
    monkeypatch.setattr("agent.api.workspace_packages._generated_avatar_asset_ids", fake_assets)

    app = FastAPI()
    app.include_router(router, prefix="/api")
    body = TestClient(app).get("/api/workspace/avatar-registry/active-product-fit").json()

    assert body["count"] == 1
    row = body["avatars"][0]
    assert row["avatar_code"] == "BOS_F_ACTIVE_01"
    assert row["product_clusters"] == ["beauty"]
    assert row["best_fit_score"] == 0.9
    assert row["image_generated"] is True
    assert row["saved_selection_reference_count"] == 1
