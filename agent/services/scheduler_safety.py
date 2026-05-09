import logging
from typing import Any
from agent.services.product_creative_brief import get_creative_brief

logger = logging.getLogger(__name__)

async def validate_batch_safety(batch_data: dict[str, Any]) -> dict[str, Any]:
    """
    Apply safety gates and scheduler constraints before a batch can be queued.
    """
    errors = []
    
    quantity = batch_data.get("quantity", 0)
    max_parallel = batch_data.get("max_parallel_jobs", 1)
    interval_min = batch_data.get("interval_min_seconds", 0)
    interval_max = batch_data.get("interval_max_seconds", 0)
    product_id = batch_data.get("product_id")
    mode = batch_data.get("mode", "Frames")

    # 1. Basic Scheduler constraints
    if quantity <= 0:
        errors.append("Quantity must be greater than 0.")
    if quantity > 20:
        errors.append(f"Quantity {quantity} exceeds batch limit of 20 for this phase.")
    
    if max_parallel > 1:
        errors.append(f"Max parallel jobs {max_parallel} exceeds limit of 1 for this phase.")
    
    if interval_min < 30:
        errors.append(f"Interval min {interval_min}s is below safety floor of 30s.")
    
    if interval_max < interval_min:
        errors.append(f"Interval max {interval_max}s cannot be less than min {interval_min}s.")

    # 2. Product & Brief Readiness
    if not product_id:
        errors.append("Product ID is required.")
    else:
        brief = await get_creative_brief(product_id)
        if "error" in brief:
            errors.append(f"Product brief not found or invalid: {brief.get('error')}")
        else:
            # Check mode readiness
            readiness = brief.get("readiness", {})
            mode_readiness = readiness.get(mode)
            if mode_readiness != "READY":
                errors.append(f"Product is not READY for mode '{mode}'. Status: {mode_readiness}")
            
            # Check claim risk approval requirement
            risk_level = brief.get("claim_boundaries", {}).get("risk_level", "LOW")
            if risk_level == "HIGH" and not batch_data.get("approval_required"):
                errors.append("HIGH claim risk level requires 'approval_required=true'.")

    return {
        "is_safe": len(errors) == 0,
        "errors": errors
    }

def check_diversity_fingerprints(variants: list[dict[str, Any]]) -> list[str]:
    """Check for duplicate fingerprints within a single batch."""
    seen = set()
    duplicates = []
    for v in variants:
        fp = v.get("diversity_fingerprint")
        if not fp:
            continue
        if fp in seen:
            duplicates.append(fp)
        seen.add(fp)
    return duplicates
