from fastapi import APIRouter

from agent.models.copy_signal_generator import (
    CopySignalGenerateRequest,
    CopySignalGenerateResponse,
    CopySignalRoutesResponse,
)
from agent.services.copy_signal_generator_service import (
    generate_copy_signal_response,
    get_copy_signal_routes_summary,
)


router = APIRouter(prefix="/copy-signals", tags=["copy-signals"])


@router.get("/routes", response_model=CopySignalRoutesResponse)
async def copy_signal_routes() -> CopySignalRoutesResponse:
    return get_copy_signal_routes_summary()


@router.post("/generate", response_model=CopySignalGenerateResponse)
async def copy_signal_generate(
    request: CopySignalGenerateRequest,
) -> CopySignalGenerateResponse:
    return await generate_copy_signal_response(request)