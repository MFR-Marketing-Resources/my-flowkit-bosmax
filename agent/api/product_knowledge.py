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
    request.allow_live_image_analysis = True
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
    try:
        file_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return AIFormImportResponse(
            import_id="decode-error",
            parse_status="PARSE_ERROR",
            parse_error_code="INVALID_JSON",
            parse_error_detail=f"Uploaded file must be valid UTF-8 text: {exc}",
            parse_errors=["Uploaded file must be valid UTF-8 text."],
            accepted_formats=[
                ".md with fenced ```json block",
                ".markdown with fenced ```json block",
                ".json raw object",
                ".JSON raw object",
                ".txt raw JSON text",
            ],
            detected_extension=(file.filename or "").rsplit(".", 1)[-1] if file.filename and "." in file.filename else "",
            detected_content_type=file.content_type,
            provenance=["product_knowledge_import_api:v1"],
        )
    return import_ai_form(file_content, file.filename or "uploaded-form.txt", file.content_type)
