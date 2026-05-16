import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from agent.main import app

client = TestClient(app)

@pytest.fixture
def mock_commit_service():
    with patch("agent.api.product_registration.RegistrationCommitService") as mock:
        mock.commit_draft = AsyncMock(return_value={"commit_status": "COMMITTED", "write_back_performed": True})
        yield mock

def test_commit_draft_api(mock_commit_service):
    payload = {
        "draft_id": "d1",
        "write_back_confirmed": True,
        "user_confirmation_phrase": "REGISTER_OWNED_PRODUCT"
    }
    response = client.post("/api/product-registration/review-drafts/d1/commit", json=payload)
    assert response.status_code == 200
    assert response.json()["commit_status"] == "COMMITTED"
    mock_commit_service.commit_draft.assert_called_once()

def test_commit_draft_api_mismatch(mock_commit_service):
    payload = {
        "draft_id": "different",
        "write_back_confirmed": True,
        "user_confirmation_phrase": "REGISTER_OWNED_PRODUCT"
    }
    response = client.post("/api/product-registration/review-drafts/d1/commit", json=payload)
    assert response.status_code == 400
    assert "ID mismatch" in response.json()["detail"]
