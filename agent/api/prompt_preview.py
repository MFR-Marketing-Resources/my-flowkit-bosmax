from fastapi import APIRouter

from agent.models.prompt_preview import PromptPreviewRequest, PromptPreviewResponse
from agent.services.prompt_preview_pipeline import run_prompt_preview_pipeline


router = APIRouter(prefix="/prompt-preview", tags=["prompt-preview"])


@router.post("/offline", response_model=PromptPreviewResponse)
async def offline_prompt_preview(request: PromptPreviewRequest) -> PromptPreviewResponse:
    return await run_prompt_preview_pipeline(request)
