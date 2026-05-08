import json
import logging
from fastapi import APIRouter
from agent.db import crud
from agent.api.local_agent import get_local_agent_status, get_dashboard_serving_mode
from agent.services.event_bus import event_bus

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])
logger = logging.getLogger(__name__)

@router.post("/export")
async def export_diagnostics():
    """Generate a comprehensive diagnostics bundle."""
    try:
        agent_status = await get_local_agent_status()
        telemetry_summary = await crud.get_telemetry_summary()
        recent_requests = await crud.list_request_telemetry(limit=20)
        
        # Collect recent stage events for the last 5 requests
        events = []
        for req in recent_requests[:5]:
            req_events = await crud.get_stage_history(req["id"])
            events.extend(req_events)

        extension_state = event_bus.extension_state
        
        bundle = {
            "local_agent_status": agent_status.model_dump(),
            "telemetry_summary": telemetry_summary,
            "recent_requests": recent_requests,
            "recent_stage_events": events,
            "extension_state": extension_state,
            "dashboard_mode": get_dashboard_serving_mode(),
            "timestamp": crud._now()
        }
        
        return bundle
    except Exception as e:
        logger.error(f"Diagnostics export failed: {e}")
        return {"error": str(e)}
