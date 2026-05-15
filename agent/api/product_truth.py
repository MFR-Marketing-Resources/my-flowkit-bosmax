from fastapi import APIRouter, Query
from agent.db import crud
from agent.services.product_truth_service import ProductTruthService

router = APIRouter(prefix="/product-truth", tags=["product-truth"])

@router.get("/reconciliation-audit")
async def get_reconciliation_audit(sample_limit: int = Query(default=20, ge=1, le=100)):
    """
    Catalog-level reconciliation audit (Read-Only).
    Aligned with PRODUCT_TRUTH_RECONCILIATION_CONTRACT.md
    """
    raw_products = await crud.list_products(limit=1000)
    profiles = [ProductTruthService.build_computed_profile(dict(p)) for p in raw_products]
    
    # Simple summary for Phase 1
    total = len(profiles)
    contradictions = sum(1 for p in profiles if p.reconciliation.contradiction_flags)
    confidence_dist = {}
    for p in profiles:
        label = p.reconciliation.confidence_label
        confidence_dist[label] = confidence_dist.get(label, 0) + 1
        
    return {
        "total_products": total,
        "contradiction_count": contradictions,
        "confidence_distribution": confidence_dist,
        "samples": profiles[:sample_limit],
        "no_write_back": True
    }

@router.get("/fastmoss-taxonomy-audit")
async def get_fastmoss_taxonomy_audit(sample_limit: int = Query(default=20, ge=1, le=100)):
    """
    Specific FastMoss taxonomy reconciliation audit.
    Identifies mapping contamination and raw source availability.
    """
    from agent.services.fastmoss_taxonomy_reconciliation_service import FastMossTaxonomyReconciliationService
    report = await FastMossTaxonomyReconciliationService.perform_full_fastmoss_audit(limit=sample_limit)
    return report
