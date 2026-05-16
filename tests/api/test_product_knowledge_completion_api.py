from fastapi.testclient import TestClient
from agent.main import app

def test_product_knowledge_complete_api():
    client = TestClient(app)
    response = client.post("/api/product-knowledge/complete", json={
        "product_name": "Bosmax Liquid Detergent",
        "product_knowledge_text": "Sabun dobi wangi 1.2kg botol biru",
        "source_lane": "MANUAL"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["completion_status"] == "COMPLETION_READY"
    assert data["suggested_bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert "1.2kg" in data["extracted_product_facts"]["size_or_volume"]
