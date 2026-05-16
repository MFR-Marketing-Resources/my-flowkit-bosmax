from fastapi import APIRouter

from agent.models.product_knowledge import (
    ProductKnowledgeCompleteRequest,
    ProductKnowledgeCompleteResponse,
)
from agent.services.product_knowledge_service import (
    complete_product_knowledge,
)


router = APIRouter(prefix="/product-knowledge", tags=["product-knowledge"])


@router.post("/complete", response_model=ProductKnowledgeCompleteResponse)
async def product_knowledge_complete(
    request: ProductKnowledgeCompleteRequest,
) -> ProductKnowledgeCompleteResponse:
    return complete_product_knowledge(request)
