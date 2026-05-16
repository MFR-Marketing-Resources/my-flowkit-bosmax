from fastapi import APIRouter, UploadFile, File
from typing import Any

from agent.models.product_knowledge import (
    ProductKnowledgeCompleteRequest,
    ProductKnowledgeCompleteResponse,
    AIFormImportResponse,
)
from agent.services.product_knowledge_service import (
    complete_product_knowledge,
    get_ai_form_template,
    get_ai_coaching_prompt,
    import_ai_form,
)


router = APIRouter(prefix="/product-knowledge", tags=["product-knowledge"])


@router.post("/complete", response_model=ProductKnowledgeCompleteResponse)
async def product_knowledge_complete(
    request: ProductKnowledgeCompleteRequest,
) -> ProductKnowledgeCompleteResponse:
    return complete_product_knowledge(request)


@router.get("/ai-form-template")
async def product_knowledge_ai_form_template() -> dict[str, str]:
    return get_ai_form_template()


@router.get("/ai-coaching-prompt")
async def product_knowledge_ai_coaching_prompt() -> dict[str, str]:
    return {"prompt": get_ai_coaching_prompt()}


@router.post("/import-ai-form", response_model=AIFormImportResponse)
async def product_knowledge_import_ai_form(
    file: UploadFile = File(...),
) -> AIFormImportResponse:
    content = await file.read()
    file_content = content.decode("utf-8")
    return import_ai_form(file_content, file.filename)
