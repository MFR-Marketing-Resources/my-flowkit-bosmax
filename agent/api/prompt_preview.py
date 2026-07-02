from fastapi import APIRouter

from agent.models.prompt_preview import PromptPreviewRequest, PromptPreviewResponse
from agent.services.prompt_preview_pipeline import run_prompt_preview_pipeline


router = APIRouter(prefix="/prompt-preview", tags=["prompt-preview"])


_NON_AUTHORITY_WARNING = (
    "NON_AUTHORITATIVE_PREVIEW: this offline preview pipeline is a FROZEN legacy "
    "surface (ADR-008). The engine-facing prompt that actually runs is produced "
    "by the canonical compiler via /api/workspace/ugc-video-prompt-compile."
)


@router.post("/offline", response_model=PromptPreviewResponse)
async def offline_prompt_preview(request: PromptPreviewRequest) -> PromptPreviewResponse:
    response = await run_prompt_preview_pipeline(request)
    if _NON_AUTHORITY_WARNING not in response.warnings:
        response.warnings.insert(0, _NON_AUTHORITY_WARNING)
    return response
