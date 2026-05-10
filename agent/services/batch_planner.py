import logging
import uuid
import json
from typing import Any
from agent.db import crud
from agent.services.product_creative_brief import get_creative_brief
from agent.services.variation_matrix import generate_variation_plan
from agent.services.prompt_compiler_9_section import compile_9_section_prompt
from agent.services.scheduler_safety import validate_batch_safety, check_diversity_fingerprints

logger = logging.getLogger(__name__)

async def create_batch_draft(batch_data: dict[str, Any]) -> dict[str, Any]:
    """
    Plan a batch of variants based on product intelligence and creative brief.
    Does not queue for execution.
    """
    product_id = batch_data.get("product_id")
    quantity = batch_data.get("quantity", 1)
    
    # 1. Safety Gate
    safety = await validate_batch_safety(batch_data)
    
    # 2. Get Brief
    brief = await get_creative_brief(product_id)
    if "error" in brief:
        return {"error": brief["error"], "safety": safety}

    # 3. Generate Variations
    raw_variants = await generate_variation_plan(product_id, quantity=quantity)
    
    # 4. Compile Prompts & Finalize Variants
    final_variants = []
    for v in raw_variants:
        # Inject batch-specific settings
        v["google_flow_mode"] = batch_data.get("mode", v["google_flow_mode"])
        
        # Compile prompt
        v["prompt_9_section"] = await compile_9_section_prompt(product_id, v)
        final_variants.append(v)
    
    # Check for duplicate fingerprints
    duplicates = check_diversity_fingerprints(final_variants)
    if duplicates:
        safety["is_safe"] = False
        safety["errors"].append(f"Duplicate diversity fingerprints detected: {', '.join(duplicates)}")

    # 5. DB Persistence (Batch record)
    batch_id = str(uuid.uuid4())
    status = "DRAFT" if safety["is_safe"] else "DRAFT_BLOCKED"
    
    db = await crud.get_db()
    from agent.db.schema import _db_lock
    async with _db_lock:
        await db.execute("""
            INSERT INTO batch (
                id, product_id, brief_id, quantity, platform, objective, 
                language, engine, duration, mode, variation_level,
                max_parallel_jobs, interval_min_seconds, interval_max_seconds,
                cooldown_after_n_jobs, cooldown_seconds, daily_credit_limit,
                approval_required, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id, product_id, brief.get("brief_id"), quantity,
            batch_data.get("platform", "TikTok"), batch_data.get("objective", "conversion"),
            batch_data.get("language", "Malay"), batch_data.get("engine", "VEO_3_1"),
            batch_data.get("duration", 8), batch_data.get("mode", "Frames"),
            batch_data.get("variation_level", "medium"),
            batch_data.get("max_parallel_jobs", 1),
            batch_data.get("interval_min_seconds", 45),
            batch_data.get("interval_max_seconds", 120),
            batch_data.get("cooldown_after_n_jobs", 5),
            batch_data.get("cooldown_seconds", 300),
            batch_data.get("daily_credit_limit", 0),
            1 if batch_data.get("approval_required") else 0,
            status
        ))
        
        # 6. DB Persistence (Variants)
        for v in final_variants:
            v["batch_id"] = batch_id
            await db.execute("""
                INSERT INTO batch_variant (
                    variant_id, batch_id, product_id, brief_id, variation_index,
                    hook_angle, scene_context, camera_route, copywriting_formula,
                    overlay_strategy, cta_style, google_flow_mode, asset_strategy,
                    diversity_fingerprint, prompt_9_section, readiness, blocked_reason, queue_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v["variant_id"], batch_id, product_id, v["brief_id"], v["variation_index"],
                v["hook_angle"], v["scene_context"], v["camera_route"], v["copywriting_formula"],
                v["overlay_strategy"], v["cta_style"], v["google_flow_mode"], v["asset_strategy"],
                v["diversity_fingerprint"], v["prompt_9_section"], v["readiness"], 
                json.dumps(v.get("blocked_reason", [])), "READY"
            ))
        
        await db.commit()
    
    return {
        "batch_id": batch_id,
        "brief_id": brief.get("brief_id"),
        "status": status,
        "safety": safety,
        "variants": final_variants,
        "variant_count": len(final_variants),
        "estimated_schedule_window": f"{quantity * batch_data.get('interval_min_seconds', 45)}s - {quantity * batch_data.get('interval_max_seconds', 120)}s"
    }

async def get_batch_detail(batch_id: str) -> dict[str, Any]:
    db = await crud.get_db()
    cursor = await db.execute("SELECT * FROM batch WHERE id = ?", (batch_id,))
    batch = await cursor.fetchone()
    if not batch:
        return {"error": "Batch not found"}
    
    cursor = await db.execute("SELECT * FROM batch_variant WHERE batch_id = ? ORDER BY variation_index", (batch_id,))
    variants = [dict(row) for row in await cursor.fetchall()]
    
    cursor = await db.execute("SELECT * FROM batch_queue_event WHERE batch_id = ? ORDER BY timestamp DESC", (batch_id,))
    events = [dict(row) for row in await cursor.fetchall()]
    
    res = dict(batch)
    res["dry_run_validated"] = any(v.get("queue_status") == "DRY_RUN_VALIDATED" for v in variants)
    res["variants"] = variants
    res["events"] = events
    return res

async def list_batches() -> list[dict[str, Any]]:
    db = await crud.get_db()
    cursor = await db.execute("SELECT * FROM batch ORDER BY created_at DESC")
    return [dict(row) for row in await cursor.fetchall()]
