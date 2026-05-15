from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_get_all_product_mapping_audit(monkeypatch):
    async def fake_audit(sample_limit: int = 20):
        assert sample_limit == 5
        return {
            "total_products": 317,
            "source_distribution": {"FASTMOSS": 299, "MANUAL": 18},
            "image_readiness_distribution": {"IMAGE_READY": 200},
            "image_analysis_status_distribution": {"VISION_PROVIDER_NOT_CONFIGURED": 298},
            "group_distribution": {"FASHION_AND_APPAREL": 47},
            "sub_group_distribution": {"SPORTSWEAR": 12},
            "type_of_product_distribution": {"SPORTSWEAR": 12},
            "bosmax_family_distribution": {"fashion_apparel": 25},
            "copy_route_distribution": {"DIRECT": 280},
            "claim_gate_distribution": {"CLAIM_SAFE": 240},
            "intelligence_confidence_distribution": {"HIGH": 220},
            "taxonomy_conflict_count": 12,
            "needs_review_count": 37,
            "unknown_review_required_count": 29,
            "low_confidence_count": 29,
            "suspicious_high_confidence_count": 4,
            "missing_sales_metrics_count": 19,
            "examples": [
                {
                    "product_id": "prod-001",
                    "title": "Atlas Lip Serum",
                    "source_category": "Beauty & Personal Care",
                    "source_subcategory": "Skincare",
                    "source_type": "Serum",
                    "bosmax_group": "HOUSEHOLD_CARE",
                    "bosmax_family": "HOME_TEXTILE",
                    "confidence": "HIGH",
                    "copy_route": "DIRECT",
                    "claim_gate": "CLAIM_SAFE",
                    "reason": "BEAUTY_EVIDENCE_CONTRADICTS_HOUSEHOLD_OR_HOME_TEXTILE_MAPPING",
                }
            ],
            "write_back_status": "READ_ONLY_NO_DB_WRITES",
        }

    monkeypatch.setattr(
        "agent.api.product_intelligence.get_all_product_mapping_audit",
        fake_audit,
    )

    client = TestClient(_build_app())
    response = client.get("/api/product-intelligence/mapping-audit?sample_limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_products"] == 317
    assert payload["suspicious_high_confidence_count"] == 4
    assert payload["examples"][0]["product_id"] == "prod-001"
