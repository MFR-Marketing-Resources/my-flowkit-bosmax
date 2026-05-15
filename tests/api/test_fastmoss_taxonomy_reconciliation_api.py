import pytest
from fastapi.testclient import TestClient
from agent.main import app

client = TestClient(app)

def test_get_fastmoss_taxonomy_audit():
    response = client.get("/api/product-truth/fastmoss-taxonomy-audit?sample_limit=1")
    assert response.status_code == 200
    data = response.json()
    assert "total_fastmoss_products" in data
    assert "source_anchor_status_distribution" in data
    assert data["no_write_back"] is True
