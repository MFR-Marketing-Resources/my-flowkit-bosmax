from fastapi import APIRouter

from agent.models.bosmax_authority import (
    BosmaxProductContextResponse,
    BosmaxPromptToolContextResponse,
    BosmaxSourceMatrixResponse,
)
from agent.services.bosmax_authority_registry import (
    get_product_context,
    get_prompt_tool_context,
    get_source_matrix,
)


router = APIRouter(prefix="/bosmax-authority", tags=["bosmax-authority"])


@router.get("/prompt-tool-context", response_model=BosmaxPromptToolContextResponse)
async def bosmax_prompt_tool_context() -> BosmaxPromptToolContextResponse:
    return await get_prompt_tool_context()


@router.get("/source-matrix", response_model=BosmaxSourceMatrixResponse)
async def bosmax_source_matrix() -> BosmaxSourceMatrixResponse:
    return await get_source_matrix()


@router.get("/product-context/{product_id}", response_model=BosmaxProductContextResponse)
async def bosmax_product_context(product_id: str) -> BosmaxProductContextResponse:
    return await get_product_context(product_id)