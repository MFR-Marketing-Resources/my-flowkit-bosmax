from fastapi import APIRouter, HTTPException

from agent.models.poster_builder_settings import PosterBuilderSettingsResponse
from agent.models.poster_copy_recommendations import PosterCopyRecommendationRequest
from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services.poster_builder_settings_service import PosterBuilderSettingsService
from agent.services.poster_copy_recommendation_service import (
    PosterCopyRecommendationService,
)
from agent.services.poster_prompt_draft_service import (
    PosterPromptDraftService,
    PosterPromptDraftValidationError,
)

router = APIRouter(prefix="/poster", tags=["poster"])


@router.get("/builder-settings", response_model=PosterBuilderSettingsResponse)
async def get_poster_builder_settings() -> PosterBuilderSettingsResponse:
    """Read-only SSOT for the Poster Builder + Creative Cockpit: poster-dimension
    option lists, Flow Mirror image settings (from models.json), copy-component
    availability, and text_assist AI-provider status. No mutation, no generation,
    no token spend."""
    return PosterBuilderSettingsService.build_settings()


@router.post("/prompt-draft")
async def create_poster_prompt_draft(body: PosterPromptDraftRequest):
    """Assemble a poster prompt package from product readiness + operator copy fields."""
    try:
        result = await PosterPromptDraftService.build_draft(body)
    except PosterPromptDraftValidationError as exc:
        if str(exc) == "PRODUCT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
        raise HTTPException(
            status_code=422,
            detail={
                "error": "POSTER_PROMPT_VALIDATION_FAILED",
                "message": str(exc),
                "field_errors": exc.field_errors,
            },
        ) from exc
    return result.model_dump(mode="json")


@router.post("/copy-recommendations")
async def poster_copy_recommendations(body: PosterCopyRecommendationRequest):
    """Recommend poster copy kits from approved/draft copy sets, AI assist, or safe fallbacks."""
    try:
        result = await PosterCopyRecommendationService.recommend(body)
    except ValueError as exc:
        if str(exc) == "PRODUCT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
        raise
    return result.model_dump(mode="json")