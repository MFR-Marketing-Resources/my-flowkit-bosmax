"""Flow Kit — FastAPI + WebSocket server entry point."""
import asyncio
import json
import logging
import signal
from contextlib import asynccontextmanager
from pathlib import Path

import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from agent.config import API_HOST, API_PORT, BASE_DIR, WS_HOST, WS_PORT
from agent.db.schema import init_db, close_db
from agent.api.characters import router as characters_router
from agent.api.projects import router as projects_router
from agent.api.videos import router as videos_router
from agent.api.scenes import router as scenes_router
from agent.api.requests import router as requests_router
from agent.api.flow import router as flow_router
from agent.api.reviews import router as reviews_router
from agent.api.tts import router as tts_router
from agent.api.materials import router as materials_router
from agent.api.music import router as music_router
from agent.api.models import router as models_router
from agent.api.active_project import router as active_project_router
from agent.api.local_agent import (
    CRITICAL_ROUTE_PATHS,
    LOCAL_AGENT_DASHBOARD_URL,
    LOCAL_AGENT_EXTENSION_STATUS_TIMEOUT_SECONDS,
    LOCAL_AGENT_REPAIR_COMMAND,
    get_dashboard_serving_mode,
    load_registration,
    router as local_agent_router,
)
from agent.api.operator import router as operator_router
from agent.api.products import router as products_router
from agent.api.poster_readiness import router as poster_readiness_router
from agent.api.poster_prompt import router as poster_prompt_router
from agent.api.poster_copy_sets import router as poster_copy_sets_router
from agent.api.poster_compose import router as poster_compose_router
from agent.api.workspace_packages import router as workspace_packages_router
from agent.api.scene_context_registry import router as scene_context_registry_router
from agent.api.workspace_generation_packages import router as workspace_generation_packages_router
from agent.api.production_queue import router as production_queue_router
from agent.api.bulk_generation import router as bulk_generation_router
from agent.api.postiz import router as postiz_router
from agent.api.social_copy_packages import router as social_copy_packages_router
from agent.api.results import router as results_router
from agent.api.prompt_preview import router as prompt_preview_router
from agent.api.asset_registry import router as asset_registry_router
from agent.api.creative_assets import (
    eligibility_router as creative_asset_eligibility_router,
    router as creative_assets_router,
)
from agent.api.img_factory import router as img_factory_router
from agent.api.bosmax_authority import router as bosmax_authority_router
from agent.api.copy_signals import router as copy_signals_router
from agent.api.copy_sets import router as copy_sets_router
from agent.api.copywriting import router as copywriting_router
from agent.api.product_asset_generator import router as product_asset_generator_router
from agent.api.product_image_analysis import router as product_image_analysis_router
from agent.api.product_intelligence import router as product_intelligence_router
from agent.api.creative_intelligence import router as creative_intelligence_router
from agent.worker.processor import get_worker_controller
from agent.services.flow_client import get_flow_client
from agent.services.event_bus import event_bus
from agent.api.telemetry import router as telemetry_router
from agent.api.diagnostics import router as diagnostics_router
from agent.api.smoke import router as smoke_router
from agent.api.creative_brief import router as creative_brief_router
from agent.api.batches import router as batches_router
from agent.api.batch_executor import router as batch_executor_router
from agent.api.product_truth import router as product_truth_router
from agent.api.product_registration import router as product_registration_router
from agent.api.fastmoss_import import router as fastmoss_import_router
from agent.api.fastmoss_bulk import router as fastmoss_bulk_router
from agent.api.kalodata_import import router as kalodata_import_router
from agent.api.product_knowledge import router as product_knowledge_router
from agent.api.ai_provider_settings import router as ai_provider_settings_router
from agent.sdk import init_sdk
from agent.services.ai_provider_settings_service import apply_runtime_provider_environment

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ─── WebSocket Server for Extension ─────────────────────────

def _clear_extension_if_current(client, websocket) -> bool:
    """Keep replacement extension sockets live when an older socket closes."""
    if getattr(client, "_extension_ws", None) is not websocket:
        logger.info("Superseded extension socket disconnected; preserving active bridge")
        return False
    client.clear_extension()
    return True


async def ws_handler(websocket):
    """Handle a Chrome extension WebSocket connection."""
    client = get_flow_client()
    client.set_extension(websocket)
    logger.info("Extension connected from %s", websocket.remote_address)

    # Send callback secret so extension can authenticate HTTP callbacks
    await websocket.send(json.dumps({"type": "callback_secret", "secret": _CALLBACK_SECRET}))

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
                await client.handle_message(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from extension")
            except Exception as e:
                logger.exception("Error handling extension message: %s", e)
    except websockets.ConnectionClosed:
        pass
    finally:
        if _clear_extension_if_current(client, websocket):
            logger.info("Extension disconnected")


async def run_ws_server():
    """Run WebSocket server for extension connections."""
    async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
        logger.info("WebSocket server listening on ws://%s:%d", WS_HOST, WS_PORT)
        await asyncio.Future()  # run forever


# ─── FastAPI App ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        from agent.services import bulk_generation_service as _bulk_svc

        _rec = await _bulk_svc.recover_stuck_bulk_runs()
        if _rec.get("count"):
            logger.info("Bulk generation recover_stuck: %s", _rec)
    except Exception as _bulk_e:  # pragma: no cover
        logger.warning("Bulk generation recover_stuck skipped: %s", _bulk_e)
    # Runtime-storage banner:
    # live counts + git context, so a wrong-worktree launch (the audit's empty
    # :8100 backend) is obvious at boot instead of after operator confusion.
    try:
        from agent import config as _cfg
        from agent.db import crud as _crud
        import subprocess as _sp

        def _git(*a):
            try:
                return _sp.check_output(
                    ["git", *a], cwd=str(_cfg.BASE_DIR),
                    stderr=_sp.DEVNULL, text=True,
                ).strip()
            except Exception:
                return "unknown"

        _pc = await _crud.count_products()
        _qs = await _crud.get_bulk_queue_stats()
        _qc = int(_qs.get("total", 0))
        logger.info(
            "RUNTIME_STORAGE base_dir=%s db=%s products=%d queue=%d branch=%s sha=%s",
            _cfg.BASE_DIR, _cfg.DB_PATH, _pc, _qc,
            _git("rev-parse", "--abbrev-ref", "HEAD"), _git("rev-parse", "--short", "HEAD"),
        )
        if _pc == 0 and _qc > 0:
            logger.warning(
                "RUNTIME_STORAGE_WARNING active DB has queue rows but ZERO products "
                "(%s) — likely the WRONG worktree DB. Verify base_dir above.",
                _cfg.DB_PATH,
            )
    except Exception as _e:  # pragma: no cover - never block startup
        logger.warning("RUNTIME_STORAGE banner unavailable: %s", _e)
    # Route-registration self-check (incident 2026-07-09): a stale process
    # serving a newer dashboard mis-routed the eligibility audit into
    # /creative-assets/{asset_id}. Make a broken/stale route table loud at boot.
    try:
        _route_paths = {getattr(_r, "path", "") for _r in app.routes}
        _missing = [_p for _p in CRITICAL_ROUTE_PATHS if _p not in _route_paths]
        if _missing:
            logger.critical(
                "ROUTE_TABLE_INCOMPLETE missing critical routes: %s — this build "
                "will mis-serve dashboard calls; verify checkout + restart.",
                _missing,
            )
        else:
            logger.info(
                "ROUTE_TABLE_OK %d routes, all %d critical routes registered",
                len(_route_paths), len(CRITICAL_ROUTE_PATHS),
            )
    except Exception as _route_e:  # pragma: no cover - never block startup
        logger.warning("Route-table self-check unavailable: %s", _route_e)
    apply_runtime_provider_environment()
    logger.info("AI provider runtime environment hydrated from registry state")

    # Load custom materials from DB into in-memory registry
    from agent.db.crud import list_materials as db_list_materials
    from agent.materials import register_material, _BUILTIN_IDS
    try:
        custom_materials = await db_list_materials()
        for m in custom_materials:
            if m["id"] not in _BUILTIN_IDS:
                register_material(m)
                logger.info("Loaded custom material from DB: %s", m["id"])
    except Exception as e:
        logger.warning("Failed to load custom materials: %s", e)

    ops = init_sdk(get_flow_client())
    logger.info("SDK initialized (OperationService ready)")
    logger.info("Flow Kit starting on %s:%d", API_HOST, API_PORT)

    controller = get_worker_controller()

    # Windows event loops do not implement add_signal_handler.
    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, controller.request_shutdown)
    except NotImplementedError:
        logger.info("SIGTERM handler unavailable on this platform; continuing without it")

    # Start background tasks
    ws_task = asyncio.create_task(run_ws_server())
    worker_task = asyncio.create_task(controller.start())
    from agent.services.workspace_generation_package_service import _scheduler_loop
    scheduler_task = asyncio.create_task(_scheduler_loop())

    async def _resume_durable_video_jobs():
        # Restart recovery: RESUME (poll only) any in-flight authorized full-video
        # job — never a fresh credit submit. Best-effort; boot never blocks on it.
        try:
            from agent.services import video_production_orchestrator as _orch
            from agent.api.flow import (_production_initial_generator,
                                        _resume_initial_generation)
            from agent.config import OUTPUT_DIR
            client = get_flow_client()
            resumed = await _orch.resume_in_flight_jobs(
                client, generate_initial=_production_initial_generator,
                resume_initial=_resume_initial_generation,
                out_dir=OUTPUT_DIR / "retrieved")
            if resumed:
                logger.info("Resumed %d in-flight full-video job(s) after restart",
                            len(resumed))
        except Exception:  # noqa: BLE001 — recovery must never crash startup
            logger.debug("durable video-job resume sweep skipped", exc_info=True)

    resume_task = asyncio.create_task(_resume_durable_video_jobs())
    logger.info("WS server + worker + batch scheduler started")

    yield

    controller.request_shutdown()
    await controller.drain()
    ws_task.cancel()
    worker_task.cancel()
    scheduler_task.cancel()
    await close_db()
    logger.info("Flow Kit stopped")


app = FastAPI(title="Flow Kit", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products_router, prefix="/api")
app.include_router(copywriting_router, prefix="/api")
app.include_router(poster_readiness_router, prefix="/api")
app.include_router(poster_prompt_router, prefix="/api")
app.include_router(poster_copy_sets_router, prefix="/api")
app.include_router(poster_compose_router, prefix="/api")
app.include_router(workspace_packages_router, prefix="/api")
app.include_router(scene_context_registry_router, prefix="/api")
app.include_router(workspace_generation_packages_router, prefix="/api")
app.include_router(production_queue_router, prefix="/api")
app.include_router(bulk_generation_router, prefix="/api")
app.include_router(postiz_router, prefix="/api")
app.include_router(social_copy_packages_router, prefix="/api")
app.include_router(results_router, prefix="/api")
app.include_router(prompt_preview_router, prefix="/api")
app.include_router(asset_registry_router, prefix="/api")
app.include_router(creative_assets_router, prefix="/api")
app.include_router(creative_asset_eligibility_router, prefix="/api")
app.include_router(img_factory_router, prefix="/api")
app.include_router(bosmax_authority_router, prefix="/api")
app.include_router(copy_signals_router, prefix="/api")
app.include_router(copy_sets_router, prefix="/api")
app.include_router(product_asset_generator_router, prefix="/api")
app.include_router(product_image_analysis_router, prefix="/api")
app.include_router(product_intelligence_router, prefix="/api")
app.include_router(creative_intelligence_router, prefix="/api")
app.include_router(characters_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(videos_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(requests_router, prefix="/api")
app.include_router(flow_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(tts_router, prefix="/api")
app.include_router(materials_router, prefix="/api")
app.include_router(music_router, prefix="/api")
app.include_router(models_router)
app.include_router(active_project_router)
app.include_router(local_agent_router)
app.include_router(operator_router)
app.include_router(telemetry_router)
app.include_router(diagnostics_router)
app.include_router(smoke_router)
app.include_router(creative_brief_router, prefix="/api")
app.include_router(batches_router, prefix="/api")
app.include_router(batch_executor_router, prefix="/api")
app.include_router(product_truth_router, prefix="/api")
app.include_router(product_registration_router, prefix="/api")
app.include_router(fastmoss_import_router, prefix="/api")
app.include_router(fastmoss_bulk_router, prefix="/api")
app.include_router(kalodata_import_router, prefix="/api")
app.include_router(product_knowledge_router, prefix="/api")
app.include_router(ai_provider_settings_router)



import secrets as _secrets
_CALLBACK_SECRET = _secrets.token_urlsafe(32)


@app.post("/api/ext/callback")
async def ext_callback(request: Request):
    """HTTP callback for extension to deliver API responses.

    Replaces ws.send() for response delivery — immune to WS disconnect.
    Extension POSTs {id, status, data, error} here instead of sending via WS.
    Requires X-Callback-Secret header matching the secret sent to extension on WS connect.
    """
    data = await request.json()
    client = get_flow_client()
    req_id = data.get("id")
    logger.info("ext/callback: id=%s pending=%d match=%s",
                str(req_id)[:8] if req_id else "none",
                len(client._pending),
                "yes" if req_id and req_id in client._pending else "no")
    if req_id and req_id in client._pending:
        future = client._pending[req_id]
        try:
            future.set_result(data)
        except asyncio.InvalidStateError:
            pass
        return {"ok": True}
    return {"ok": False, "reason": "no matching pending request"}


@app.get("/health")
async def health():
    client = get_flow_client()
    extension_status = await client.get_status(
        timeout=LOCAL_AGENT_EXTENSION_STATUS_TIMEOUT_SECONDS,
    )
    registration = load_registration()
    return {
        "status": "ok",
        "version": "0.2.0",
        "extension_connected": client.connected,
        "extension_state": extension_status.get("state", "off"),
        "flow_key_present": bool(extension_status.get("flowKeyPresent")),
        "extension_manual_disconnect": bool(extension_status.get("manualDisconnect")),
        "extension_metrics": extension_status.get("metrics", {}),
        "extension_status_error": extension_status.get("error"),
        "dashboard_serving_mode": get_dashboard_serving_mode(),
        "dashboard_url": LOCAL_AGENT_DASHBOARD_URL,
        "repair_command": LOCAL_AGENT_REPAIR_COMMAND,
        "registration": registration.model_dump(),
        "ws": client.ws_stats,
    }


# ─── Dashboard WebSocket ──────────────────────────────────────

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    """WebSocket endpoint for dashboard clients (Chrome extension side panel)."""
    # Reject cross-origin connections (only allow localhost)
    origin = (websocket.headers.get("origin") or "").lower()
    if origin and not any(origin.startswith(p) for p in (
        "http://127.0.0.1", "http://localhost", "chrome-extension://",
    )):
        await websocket.close(code=4003, reason="Origin not allowed")
        return
    await websocket.accept()

    q = event_bus.subscribe()
    try:
        # Send initial snapshot
        client = get_flow_client()
        controller = get_worker_controller()
        from agent.db import crud
        pending_requests = await crud.list_requests(status="PENDING")
        processing_requests = await crud.list_requests(status="PROCESSING")
        # Update event_bus state from client
        event_bus.extension_connected = client.connected
        event_bus.extension_state = client.last_state if hasattr(client, "last_state") else ("IDLE" if client.connected else "OFFLINE")

        snapshot = {
            "type": "snapshot",
            "health": {
                "status": "ok",
                "extension_connected": event_bus.extension_connected,
                "extension_state": event_bus.extension_state,
            },
            "requests": pending_requests + processing_requests,
            "worker": {
                "active": controller.active_count,
                "slots": max(0, 5 - controller.active_count),
            },
        }
        await websocket.send_text(json.dumps(snapshot))

        # Forward events from event_bus to this client
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Dashboard WS client disconnected: %s", e)
    finally:
        event_bus.unsubscribe(q)


_DASHBOARD_DIST_DIR = BASE_DIR / "dashboard" / "dist"
_DASHBOARD_INDEX_FILE = _DASHBOARD_DIST_DIR / "index.html"
_PRODUCT_IMAGE_DIR = BASE_DIR / "data" / "products" / "images"


def _resolve_dashboard_asset(path: str) -> Path | None:
    if not path:
        return None

    candidate = (_DASHBOARD_DIST_DIR / path).resolve()
    try:
        candidate.relative_to(_DASHBOARD_DIST_DIR.resolve())
    except ValueError:
        return None

    if candidate.is_file():
        return candidate
    return None


@app.get("/api/assets/product-images/{filename}")
async def product_image_asset(filename: str):
    candidate = (_PRODUCT_IMAGE_DIR / filename).resolve()
    try:
        candidate.relative_to(_PRODUCT_IMAGE_DIR.resolve())
    except ValueError:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if not candidate.is_file():
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return FileResponse(candidate)


@app.get("/")
@app.get("/operator")
@app.get("/dashboard")
@app.get("/{full_path:path}")
async def dashboard_app(full_path: str = ""):
    if full_path.startswith(("api/", "api", "ws/", "ws")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if not _DASHBOARD_INDEX_FILE.exists():
        return JSONResponse(
            {
                "status": "build_required",
                "message": "Dashboard production bundle is missing. Run .\\scripts\\install-local-agent.ps1.",
                "expected_bundle": str(_DASHBOARD_INDEX_FILE),
            },
            status_code=503,
        )

    asset = _resolve_dashboard_asset(full_path)
    if asset:
        # Hashed assets (e.g. index-abc123.js) — safe to cache forever
        if "assets" in asset.parts:
            return FileResponse(asset, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        return FileResponse(asset)

    # index.html — served as raw HTML with hard no-cache headers so every reload
    # fetches the latest file, preventing stale bundle-hash references in browser cache.
    html_content = _DASHBOARD_INDEX_FILE.read_text(encoding="utf-8")
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


if __name__ == "__main__":
    import os
    import uvicorn
    reload_enabled = os.environ.get("GLA_RELOAD", "0") == "1"
    uvicorn.run(
        "agent.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=reload_enabled,
        reload_excludes=["*.db", "*.db-wal", "*.db-shm", "output/*"],
    )
