import pytest
from fastapi.testclient import TestClient
from agent.main import app

client = TestClient(app)

def test_get_product_truth_audit():
    # We need a real product ID from the DB
    import sqlite3
    from agent.config import DB_PATH
    from agent.db.schema import init_db
    import asyncio
    
    # Initialize DB for tests
    asyncio.run(init_db())
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Insert a dummy product if none exists
    c.execute("SELECT id FROM product LIMIT 1")
    row = c.fetchone()
    if not row:
        product_id = "test-prod-123"
        c.execute("INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, source, category, subcategory, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (product_id, "Test Product", "Test Product Display", "Test Prod", "FASTMOSS", "Baby Care", "Hygiene", "Wipes"))
        conn.commit()
    else:
        product_id = row[0]
    conn.close()
    
    response = client.get(f"/api/products/{product_id}/truth-audit")
    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == product_id
    assert "reconciliation" in data

def test_get_reconciliation_audit():
    response = client.get("/api/product-truth/reconciliation-audit?sample_limit=1")
    assert response.status_code == 200
    data = response.json()
    assert "total_products" in data
    assert "samples" in data
    assert data["no_write_back"] is True
