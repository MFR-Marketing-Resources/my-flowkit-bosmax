"""Creative Intelligence API — Round 1 (avatar recommendation).

Read-first, non-generative. Exposes:
  * GET  /api/creative-intelligence/avatar-recommendation  (by product_id OR category)
  * POST /api/creative-intelligence/avatar-fit/seed         (idempotent; dry-run default)

No generation, no Product Truth / Copy Set / Copy Registry / Copy Intelligence
mutation. The seed only writes the config table ``avatar_product_fit``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent.services import creative_avatar_recommendation_service as _svc

router = APIRouter(prefix="/creative-intelligence", tags=["creative-intelligence"])


@router.get("/avatar-recommendation")
async def avatar_recommendation(
    product_id: str | None = None,
    category: str | None = None,
) -> dict:
    """Recommended AI avatars for a product or a raw category. Read-only —
    resolves category -> cluster and reuses avatar_fit_service. Never mutates."""
    if product_id:
        try:
            return await _svc.recommend_avatars_for_product(product_id)
        except ValueError as exc:
            if str(exc) == "PRODUCT_NOT_FOUND":
                raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
            raise
    if category is not None:
        return await _svc.recommend_avatars_for_category(category)
    raise HTTPException(status_code=422, detail="product_id or category is required")


@router.post("/avatar-fit/seed")
async def avatar_fit_seed(dry_run: bool = True) -> dict:
    """Seed avatar_product_fit from the pool-validated crosswalk. Idempotent;
    ``dry_run`` (default true) writes nothing and returns the plan. Only writes the
    avatar_product_fit config table — no Product Truth / Copy / generation effect."""
    return await _svc.seed_avatar_product_fit(dry_run=dry_run)
