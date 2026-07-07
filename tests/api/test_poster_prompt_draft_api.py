from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_prompt import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_prompt_draft_validation_422(monkeypatch):
    async def fake_build(_req):
        from agent.services.poster_prompt_draft_service import (
            PosterPromptDraftValidationError,
        )

        raise PosterPromptDraftValidationError(
            "Poster prompt draft validation failed",
            field_errors=["Missing required field: hook"],
        )

    monkeypatch.setattr(
        "agent.api.poster_prompt.PosterPromptDraftService.build_draft",
        fake_build,
    )
    response = _client().post(
        "/api/poster/prompt-draft",
        json={"product_id": "p1", "hook": ""},
    )
    assert response.status_code == 422
    body = response.json()
    detail = body.get("detail", body)
    assert detail["error"] == "POSTER_PROMPT_VALIDATION_FAILED"


def test_prompt_draft_repair_required_shape(monkeypatch):
    async def fake_build(_req):
        from agent.models.poster_prompt_draft import PosterPromptDraftResponse, PromptPackageStatus

        return PosterPromptDraftResponse(
            product_id="p1",
            poster_status="POSTER_REPAIR_REQUIRED",
            prompt_package_status=PromptPackageStatus.REPAIR_REQUIRED,
            blocked_reasons=["CLAIM_RISK_HIGH"],
            repair_actions=[{"action_code": "RUN_SAFE_CLAIM_CLEARANCE"}],
        )

    monkeypatch.setattr(
        "agent.api.poster_prompt.PosterPromptDraftService.build_draft",
        fake_build,
    )
    response = _client().post(
        "/api/poster/prompt-draft",
        json={"product_id": "p1", "hook": "x", "cta": "y"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_package_status"] == "REPAIR_REQUIRED"
    assert body["poster_prompt"] == ""