from fastapi.testclient import TestClient

from agent.main import app


def _entry() -> dict:
    return {
        "product_type_code": "3d_sticker_book",
        "cluster_name": "Toys & Hobbies",
        "display_name": "3D Sticker Book",
        "category": "Toys & Games",
        "subcategory": "Creative Play",
        "type": "3D Scene Sticker Books",
        "copywriting_angle": "Creative play angle",
        "source_workbook": "Download-Copywriting_Hub-Rev4-FIXED-WS-Database-Mapped.xlsx",
        "source_sheet": "Database",
        "source_row": 3,
        "registry_status": "ACTIVE",
        "created_at": "2026-08-11T00:00:00Z",
        "updated_at": "2026-08-11T00:00:00Z",
    }


def test_taxonomy_registry_route_is_read_only_and_filterable(monkeypatch):
    seen = {}

    async def fake_list(**kwargs):
        seen.update(kwargs)
        return {
            "schema_version": "copywriting-taxonomy-v2",
            "source_workbook": "Download-Copywriting_Hub-Rev4-FIXED-WS-Database-Mapped.xlsx",
            "source_sheet": "Database",
            "items": [_entry()],
            "total": 1,
            "limit": 25,
            "offset": 0,
            "filters": {
                "cluster_name": "Toys & Hobbies",
                "category": None,
                "subcategory": None,
                "type": None,
                "product_type_code": None,
                "registry_status": None,
                "query": "sticker",
            },
        }

    monkeypatch.setattr("agent.api.copywriting.list_copywriting_taxonomy_entries", fake_list)
    response = TestClient(app).get(
        "/api/copywriting/taxonomy",
        params={"cluster_name": "Toys & Hobbies", "q": "sticker", "limit": 25},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["product_type_code"] == "3d_sticker_book"
    assert seen["cluster_name"] == "Toys & Hobbies"
    assert seen["query"] == "sticker"
    assert seen["limit"] == 25


def test_taxonomy_rollup_route_shape(monkeypatch):
    async def fake_rollup():
        return {
            "schema_version": "copywriting-taxonomy-v2",
            "source_workbook": "Download-Copywriting_Hub-Rev4-FIXED-WS-Database-Mapped.xlsx",
            "source_sheet": "Database",
            "total_product_types": 313,
            "cluster_count": 54,
            "category_count": 18,
            "subcategory_count": 168,
            "type_count": 312,
            "angle_count": 295,
            "clusters": [
                {
                    "cluster_name": "Toys & Hobbies",
                    "product_type_count": 1,
                    "category_count": 1,
                    "subcategory_count": 1,
                    "type_count": 1,
                    "angle_count": 1,
                }
            ],
        }

    monkeypatch.setattr("agent.api.copywriting.get_copywriting_taxonomy_rollup", fake_rollup)
    response = TestClient(app).get("/api/copywriting/taxonomy/rollup")

    assert response.status_code == 200
    assert response.json()["total_product_types"] == 313
    assert response.json()["clusters"][0]["cluster_name"] == "Toys & Hobbies"
