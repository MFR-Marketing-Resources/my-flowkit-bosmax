import logging
import httpx
import json
from pathlib import Path
from agent.db import crud
from agent.utils.paths import product_image_path
from agent.services.flow_client import get_flow_client

logger = logging.getLogger(__name__)

async def generate_product_prompt(product: dict, mode: str) -> str:
    """Generate a high-conversion prompt based on product metadata and category guardrails."""
    name = product.get("product_short_name") or product.get("product_display_name")
    category = product.get("category", "").lower()
    
    # Base descriptive prompt
    prompt = f"Product showcase of {name}. {product.get('product_display_name')}. "
    
    # Category-specific enhancements & guardrails
    if "baby" in category or "diaper" in category:
        prompt += (
            "Clean, bright, professional parenting context. "
            "Focus on product quality, soft texture, and reliable baby care. "
            "No unsafe handling, no medical claims. Product-focused demonstration."
        )
    elif "food" in category or "milk" in category:
        prompt += (
            "Appetizing, fresh, high-quality food presentation. "
            "Clean kitchen or natural setting. Professional food photography lighting."
        )
    elif "toy" in category:
        prompt += (
            "Bright, playful, educational environment. "
            "Clear focus on the toy's features and safe interactive elements."
        )
    else:
        prompt += "High-quality commercial product cinematography, studio lighting, sharp focus."

    # Mode specific adjustments
    if mode == "IMG":
        prompt = f"Professional studio product shot: {prompt}"
    elif mode in ["I2V", "F2V"]:
        prompt = f"Cinematic product commercial: {prompt} Subtle camera movement, dynamic lighting."
        
    return prompt

async def resolve_product_assets(product_id: str) -> dict:
    """Download product image from URL if UNRESOLVED."""
    product = await crud.get_product(product_id)
    if not product:
        return {"error": "Product not found"}
    
    if product.get("asset_status") != "UNRESOLVED":
        return {"status": product["asset_status"], "local_path": product.get("local_image_path")}

    image_url = product.get("image_url")
    if not image_url:
        return {"error": "No image URL for product"}

    try:
        dest = product_image_path(product_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url, timeout=30.0)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            
        await crud.update_product(product_id, 
                                  asset_status="DOWNLOADED", 
                                  local_image_path=str(dest))
        return {"status": "DOWNLOADED", "local_path": str(dest)}
    except Exception as e:
        logger.error(f"Failed to download product image for {product_id}: {e}")
        return {"error": str(e)}

async def upload_product_to_flow(product_id: str) -> dict:
    """Upload the cached product image to Google Flow to get media_id."""
    product = await crud.get_product(product_id)
    if not product:
        return {"error": "Product not found"}
    
    if product.get("media_id"):
        return {"media_id": product["media_id"]}

    local_path = product.get("local_image_path")
    if not local_path or not Path(local_path).exists():
        # Try to resolve/download first
        res = await resolve_product_assets(product_id)
        if "error" in res:
            return res
        local_path = res["local_path"]

    try:
        client = get_flow_client()
        # Note: We need an upload_image_from_path method or similar in FlowClient
        # For now, we use upload_image which takes raw bytes or similar
        with open(local_path, "rb") as f:
            image_data = f.read()
            
        # Mocking the upload call — in real logic, FlowClient.upload_image takes name + data
        # result = await client.upload_image(product["product_short_name"], image_data)
        # media_id = result.get("name")
        
        # Actually, let's look at FlowClient.upload_image signature
        # result = await client.upload_image(f"product_{product_id}", image_data)
        
        # For now, we return NOT VERIFIED as requested if we don't have the final proof
        return {"status": "UPLOAD_PENDING_IMPLEMENTATION", "local_path": local_path}
    except Exception as e:
        logger.error(f"Failed to upload product image for {product_id}: {e}")
        return {"error": str(e)}
