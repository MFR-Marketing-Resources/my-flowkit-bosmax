import logging
from fastapi import APIRouter, HTTPException
from agent.db import crud
from agent.services.event_bus import event_bus
from agent.models.request import RequestCreate

router = APIRouter(prefix="/api/smoke", tags=["smoke"])
logger = logging.getLogger(__name__)

@router.post("/true-f2v")
async def smoke_test_true_f2v():
    """Trigger a controlled TRUE_F2V smoke test using a real product."""
    
    # 1. Check if extension is connected
    if not event_bus.extension_connected:
        return {"ok": False, "error": "EXTENSION_OFFLINE", "message": "Flow Kit extension is not connected."}

    # 2. Check if Flow tab is open (based on heartbeat/state)
    if event_bus.extension_state == "OFFLINE":
        return {"ok": False, "error": "FLOW_TAB_NOT_OPEN", "message": "Google Flow tab is not open or extension is inactive."}

    # 3. Find a suitable product
    products = await crud.list_products(limit=100)
    # Prefer Sumikko
    target_product = next((p for p in products if "Sumikko" in (p.get("product_short_name") or "")), None)
    if not target_product:
        # Fallback to first with image_url
        target_product = next((p for p in products if p.get("image_url")), None)
    
    if not target_product:
        raise HTTPException(status_code=400, detail="No suitable product found for smoke test. Catalog might be empty.")

    # 4. Create dummy project/video for smoke test if needed, or use a "Smoke Test" project
    # For now, let's just create a Request. In the real system, a Request needs project_id, video_id, scene_id.
    # We'll use "SMOKE_TEST" placeholders.
    
    smoke_request = {
        "id": f"smoke-{crud._uuid()[:8]}",
        "project_id": "SMOKE_PROJECT",
        "video_id": "SMOKE_VIDEO",
        "scene_id": "SMOKE_SCENE",
        "product_id": target_product["id"],
        "request_type": "TRUE_F2V",
        "mode": "TRUE_F2V",
        "status": "QUEUED",
        "google_flow_stage": "SMOKE_TEST_QUEUED",
        "created_at": crud._now(),
        "queued_at": crud._now()
    }
    
    await crud.upsert_request_telemetry(**smoke_request)
    
    # We also need to create the actual 'request' row so the worker picks it up
    # However, 'request' table has FK constraints.
    # For a smoke test, maybe it's better to use a real project if one exists.
    
    # Let's see if we can find any project
    projects = await crud.list_projects(limit=1)
    if projects:
        proj = projects[0]
        videos = await crud.list_videos(project_id=proj["id"], limit=1)
        if videos:
            vid = videos[0]
            scenes = await crud.list_scenes(video_id=vid["id"], limit=1)
            if scenes:
                # We have a real context!
                smoke_request["project_id"] = proj["id"]
                smoke_request["video_id"] = vid["id"]
                smoke_request["scene_id"] = scenes[0]["id"]
                
                # Create real request
                from agent.db.schema import get_db
                db = await get_db()
                rid = smoke_request["id"]
                now = smoke_request["created_at"]
                await db.execute(
                    "INSERT INTO request (id, project_id, video_id, scene_id, type, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (rid, proj["id"], vid["id"], scenes[0]["id"], "TRUE_F2V", "PENDING", now, now)
                )
                await db.commit()
                
                return {
                    "ok": True, 
                    "message": "Smoke test triggered using real project context.",
                    "request_id": rid,
                    "product": target_product["product_short_name"]
                }

    return {"ok": False, "error": "NO_PROJECT_CONTEXT", "message": "Create at least one project/video manually before running smoke test."}
