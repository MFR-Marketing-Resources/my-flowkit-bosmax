import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from agent.main import app
from agent.models.product_registration import RegistrationReviewDraft

client = TestClient(app)

@pytest.fixture
def mock_storage():
    with patch("agent.api.product_registration.RegistrationDraftStorageService") as mock:
        yield mock

def test_list_drafts_api(mock_storage):
    mock_storage.list_drafts.return_value = [
        RegistrationReviewDraft(review_draft_id="d1", review_status="READY", source_lane="MANUAL")
    ]
    response = client.get("/api/product-registration/review-drafts")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["review_draft_id"] == "d1"

def test_get_draft_api(mock_storage):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d2", review_status="READY", source_lane="MANUAL"
    )
    response = client.get("/api/product-registration/review-drafts/d2")
    assert response.status_code == 200
    assert response.json()["review_draft_id"] == "d2"

def test_get_draft_api_not_found(mock_storage):
    mock_storage.get_draft.return_value = None
    response = client.get("/api/product-registration/review-drafts/missing")
    assert response.status_code == 404
