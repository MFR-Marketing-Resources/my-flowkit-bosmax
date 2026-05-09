from fastapi import APIRouter, HTTPException
from agent.services.product_creative_brief import get_creative_brief, refresh_creative_brief
from agent.services.variation_matrix import generate_variation_plan
from agent.services.prompt_compiler_9_section import compile_9_section_prompt

router = APIRouter(prefix="/products/{product_id}", tags=["Creative Brief"])

@router.get("/creative-brief")
async def api_get_creative_brief(product_id: str):
    res = await get_creative_brief(product_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@router.post("/creative-brief/refresh")
async def api_refresh_creative_brief(product_id: str):
    res = await refresh_creative_brief(product_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@router.post("/variation-plan")
async def api_generate_variation_plan(product_id: str, quantity: int = 3):
    res = await generate_variation_plan(product_id, quantity)
    return res

@router.post("/prompt-preview")
async def api_prompt_preview(product_id: str, variant: dict):
    prompt = await compile_9_section_prompt(product_id, variant)
    return {"prompt": prompt}
