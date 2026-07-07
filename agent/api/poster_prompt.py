from fastapi import APIRouter, HTTPException

from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services.poster_prompt_draft_service import (
    PosterPromptDraftService,
    PosterPromptDraftValidationError,
)

router = APIRouter(prefix="/poster", tags=["poster"])


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