from fastapi import APIRouter, HTTPException

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
    try:
        return await generate_copy_signal_response(request)
    except ValueError as exc:
        if str(exc).startswith("COPY_INELIGIBLE"):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise