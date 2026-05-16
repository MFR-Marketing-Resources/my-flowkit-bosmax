"""Async CRUD operations with column whitelisting."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from agent.db.schema import get_db, _db_lock

logger = logging.getLogger(__name__)

_VALID_TABLES = frozenset({"character", "project", "video", "scene", "request", "material", "product", "request_telemetry", "request_stage_event"})


def _validate_table(table: str) -> None:
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table!r}")

# Column whitelists per table — prevents SQL injection via kwargs keys
_COLUMNS = {
    "character": {"name", "slug", "entity_type", "description", "image_prompt", "voice_description", "reference_image_url", "media_id", "updated_at"},
    "project": {"name", "description", "story", "thumbnail_url", "language", "status", "user_paygate_tier", "narrator_voice", "narrator_ref_audio", "material", "allow_music", "allow_voice", "updated_at"},
    "video": {"title", "description", "display_order", "status", "orientation", "vertical_url", "horizontal_url",
              "thumbnail_url", "duration", "resolution", "youtube_id", "privacy", "tags", "updated_at"},
    "scene": {"prompt", "image_prompt", "video_prompt", "character_names", "parent_scene_id", "chain_type",
              "vertical_image_url", "vertical_image_media_id", "vertical_image_status",
              "vertical_video_url", "vertical_video_media_id", "vertical_video_status",
              "vertical_upscale_url", "vertical_upscale_media_id", "vertical_upscale_status",
              "horizontal_image_url", "horizontal_image_media_id", "horizontal_image_status",
              "horizontal_video_url", "horizontal_video_media_id", "horizontal_video_status",
              "horizontal_upscale_url", "horizontal_upscale_media_id", "horizontal_upscale_status",
              "vertical_end_scene_media_id", "horizontal_end_scene_media_id",
              "trim_start", "trim_end", "duration", "display_order", "source", "transition_prompt", "narrator_text", "updated_at"},
    "request": {"status", "request_id", "media_id", "output_url", "error_message", "retry_count", "next_retry_at", "source_media_id", "updated_at", "automation_report"},
    "product": {"source", "source_url", "brand", "raw_product_title", "product_display_name", "product_short_name", "category", "subcategory", "type", "shop_name", "price", "currency", "commission_amount", "commission_rate", "price_min", "price_max", "commission", "image_url", "tiktok_product_url", "fastmoss_source_file", "image_asset_status", "image_failure_detail", "product_type", "product_type_id", "silo", "trigger_id", "formula", "copywriting_angle", "claim_risk_level", "mode_recommendations", "physics_class", "product_scale", "hand_object_interaction", "recommended_grip", "handling_notes", "air_gap_rule", "material_behavior", "surface_behavior", "fragility_level", "camera_handling_notes", "scene_context", "camera_style", "camera_behavior", "camera_shot", "unsafe_handling_rules", "section_4_hint", "section_5_product_physics_prompt", "section_5_physics_hint", "section_6_copy_hint", "section_9_overlay_hint", "mapping_source", "mapping_confidence", "mapping_review_status", "mapping_status", "mapping_missing_fields", "prompt_readiness_status", "prompt_missing_fields", "lifecycle_status", "archived_at", "archived_reason", "archived_by", "unarchived_at", "unarchived_reason", "lifecycle_provenance", "asset_status", "media_id", "local_image_path", "updated_at"},
    "request_telemetry": {"project_id", "video_id", "scene_id", "product_id", "request_type", "mode", "status", "google_flow_stage", "extension_stage", "worker_stage", "queued_at", "started_at", "last_heartbeat_at", "completed_at", "failed_at", "duration_seconds", "idle_seconds", "processing_seconds", "error_code", "error_message"},
    "request_stage_event": {"request_id", "timestamp", "stage", "status", "message", "source"},
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uuid() -> str:
    return str(uuid.uuid4())


def _safe_kwargs(table: str, kwargs: dict) -> dict:
    """Filter kwargs to only allowed columns."""
    allowed = _COLUMNS.get(table, set())
    return {k: v for k, v in kwargs.items() if k in allowed}


async def _update(table: str, pk: str, pk_val: str, **kwargs) -> Optional[dict]:
    _validate_table(table)
    kwargs = _safe_kwargs(table, kwargs)
    if not kwargs:
        return await _get(table, pk, pk_val)
    if "updated_at" in _COLUMNS.get(table, set()) and "updated_at" not in kwargs:
        kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [pk_val]
    db = await get_db()
    async with _db_lock:
        await db.execute(f"UPDATE {table} SET {sets} WHERE {pk}=?", vals)
        await db.commit()
    return await _get_with_db(db, table, pk, pk_val)


async def _get(table: str, pk: str, pk_val: str) -> Optional[dict]:
    _validate_table(table)
    db = await get_db()
    return await _get_with_db(db, table, pk, pk_val)


async def _get_with_db(db, table: str, pk: str, pk_val: str) -> Optional[dict]:
    _validate_table(table)
    cur = await db.execute(f"SELECT * FROM {table} WHERE {pk}=?", (pk_val,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def _delete(table: str, pk: str, pk_val: str) -> bool:
    _validate_table(table)
    db = await get_db()
    async with _db_lock:
        cur = await db.execute(f"DELETE FROM {table} WHERE {pk}=?", (pk_val,))
        await db.commit()
    return cur.rowcount > 0


# ─── Character ──────────────────────────────────────────────

async def create_character(name: str, entity_type: str = "character", description: str = None, image_prompt: str = None, voice_description: str = None, reference_image_url: str = None, media_id: str = None, slug: str = None) -> dict:
    from agent.utils.slugify import slugify
    db = await get_db()
    cid, now = _uuid(), _now()
    _slug = slug or slugify(name)
    async with _db_lock:
        await db.execute(
            "INSERT INTO character (id,name,slug,entity_type,description,image_prompt,voice_description,reference_image_url,media_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, name, _slug, entity_type, description, image_prompt, voice_description, reference_image_url, media_id, now, now))
        await db.commit()
    return await _get_with_db(db, "character", "id", cid)

async def get_character(cid: str): return await _get("character", "id", cid)
async def update_character(cid: str, **kw): return await _update("character", "id", cid, **kw)
async def delete_character(cid: str): return await _delete("character", "id", cid)

async def list_characters() -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM character ORDER BY created_at DESC")
    return [dict(r) for r in await cur.fetchall()]


# ─── Project ────────────────────────────────────────────────

async def create_project(name: str, description: str = None, story: str = None, language: str = "en", user_paygate_tier: str = "PAYGATE_TIER_ONE", id: str = None, material: str = None, allow_music: bool = False, allow_voice: bool = False) -> dict:
    db = await get_db()
    pid, now = id or _uuid(), _now()
    async with _db_lock:
        await db.execute(
            "INSERT INTO project (id,name,description,story,language,user_paygate_tier,material,allow_music,allow_voice,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, name, description, story, language, user_paygate_tier, material, int(allow_music), int(allow_voice), now, now))
        await db.commit()
    return await _get_with_db(db, "project", "id", pid)

async def get_project(pid: str): return await _get("project", "id", pid)
async def update_project(pid: str, **kw): return await _update("project", "id", pid, **kw)
async def delete_project(pid: str): return await _delete("project", "id", pid)

async def list_projects(status: str = None) -> list[dict]:
    db = await get_db()
    if status:
        cur = await db.execute("SELECT * FROM project WHERE status=? ORDER BY created_at DESC", (status,))
    else:
        cur = await db.execute("SELECT * FROM project ORDER BY created_at DESC")
    return [dict(r) for r in await cur.fetchall()]

async def link_character_to_project(project_id: str, character_id: str) -> bool:
    db = await get_db()
    try:
        async with _db_lock:
            await db.execute("INSERT OR IGNORE INTO project_character VALUES (?,?)", (project_id, character_id))
            await db.commit()
        return True
    except Exception as e:
        logger.warning("link_character_to_project failed: %s", e)
        return False

async def unlink_character_from_project(project_id: str, character_id: str) -> bool:
    db = await get_db()
    async with _db_lock:
        cur = await db.execute("DELETE FROM project_character WHERE project_id=? AND character_id=?", (project_id, character_id))
        await db.commit()
    return cur.rowcount > 0

async def get_project_characters(project_id: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT c.* FROM character c JOIN project_character pc ON c.id=pc.character_id WHERE pc.project_id=?",
        (project_id,))
    return [dict(r) for r in await cur.fetchall()]


# ─── Video ──────────────────────────────────────────────────

async def create_video(project_id: str, title: str, description: str = None, display_order: int = 0, orientation: str = None) -> dict:
    db = await get_db()
    vid, now = _uuid(), _now()
    async with _db_lock:
        await db.execute(
            "INSERT INTO video (id,project_id,title,description,display_order,orientation,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (vid, project_id, title, description, display_order, orientation, now, now))
        await db.commit()
    return await _get_with_db(db, "video", "id", vid)

async def get_video(vid: str): return await _get("video", "id", vid)
async def update_video(vid: str, **kw): return await _update("video", "id", vid, **kw)
async def delete_video(vid: str): return await _delete("video", "id", vid)

async def list_videos(project_id: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM video WHERE project_id=? ORDER BY display_order", (project_id,))
    return [dict(r) for r in await cur.fetchall()]


# ─── Scene ──────────────────────────────────────────────────

async def create_scene(video_id: str, display_order: int, prompt: str,
                       image_prompt: str = None, video_prompt: str = None,
                       transition_prompt: str = None,
                       character_names: list[str] = None,
                       parent_scene_id: str = None, chain_type: str = "ROOT",
                       source: str = "root") -> dict:
    db = await get_db()
    sid, now = _uuid(), _now()
    chars_json = json.dumps(character_names) if character_names else None
    async with _db_lock:
        await db.execute(
            """INSERT INTO scene (id,video_id,display_order,prompt,image_prompt,video_prompt,transition_prompt,character_names,
               parent_scene_id,chain_type,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, video_id, display_order, prompt, image_prompt, video_prompt, transition_prompt, chars_json,
             parent_scene_id, chain_type, source, now, now))
        await db.commit()
    return await _get_with_db(db, "scene", "id", sid)

async def get_scene(sid: str): return await _get("scene", "id", sid)
async def update_scene(sid: str, **kw): return await _update("scene", "id", sid, **kw)
async def delete_scene(sid: str): return await _delete("scene", "id", sid)

async def list_scenes(video_id: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM scene WHERE video_id=? ORDER BY display_order", (video_id,))
    return [dict(r) for r in await cur.fetchall()]


async def list_scenes_by_media_id(media_id: str) -> list[dict]:
    """Find scenes where any media_id field matches the given UUID."""
    db = await get_db()
    cur = await db.execute(
        """SELECT * FROM scene WHERE
           vertical_image_media_id=? OR horizontal_image_media_id=?
           OR vertical_video_media_id=? OR horizontal_video_media_id=?
           OR vertical_upscale_media_id=? OR horizontal_upscale_media_id=?""",
        (media_id, media_id, media_id, media_id, media_id, media_id))
    return [dict(r) for r in await cur.fetchall()]


async def list_characters_by_media_id(media_id: str) -> list[dict]:
    """Find characters where media_id matches."""
    db = await get_db()
    cur = await db.execute("SELECT * FROM character WHERE media_id=?", (media_id,))
    return [dict(r) for r in await cur.fetchall()]


# ─── Request ────────────────────────────────────────────────

async def create_request(req_type: str, orientation: str = None,
                         scene_id: str = None, character_id: str = None,
                         project_id: str = None, video_id: str = None,
                         source_media_id: str = None, **_kw) -> dict:
    db = await get_db()
    rid, now = _uuid(), _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO request (id,project_id,video_id,scene_id,character_id,type,orientation,source_media_id,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rid, project_id, video_id, scene_id, character_id, req_type, orientation, source_media_id, now, now))
        await db.commit()
    return await _get_with_db(db, "request", "id", rid)

async def get_request(rid: str): return await _get("request", "id", rid)
async def update_request(rid: str, **kw): return await _update("request", "id", rid, **kw)

async def list_requests(scene_id: str = None, status: str = None,
                        video_id: str = None, project_id: str = None,
                        limit: int = None) -> list[dict]:
    db = await get_db()
    q, params = "SELECT * FROM request WHERE 1=1", []
    if scene_id:
        q += " AND scene_id=?"; params.append(scene_id)
    if status:
        q += " AND status=?"; params.append(status)
    if video_id:
        q += " AND video_id=?"; params.append(video_id)
    if project_id:
        q += " AND project_id=?"; params.append(project_id)
    q += " ORDER BY created_at DESC"
    if limit:
        q += " LIMIT ?"; params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]

async def list_pending_requests() -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM request WHERE status='PENDING' ORDER BY created_at")
    return [dict(r) for r in await cur.fetchall()]


async def list_actionable_requests(exclude_ids: set[str] = None, limit: int = 5) -> list[dict]:
    """Priority-ordered fetch of PENDING requests ready to process."""
    db = await get_db()
    now = _now()
    exclude = exclude_ids or set()

    # Fetch all pending, filter in Python (SQLite doesn't support parameterized IN with variable length)
    cur = await db.execute("""
        SELECT * FROM request
        WHERE status = 'PENDING'
          AND (next_retry_at IS NULL OR next_retry_at <= ?)
        ORDER BY
          CASE type
            WHEN 'GENERATE_CHARACTER_IMAGE' THEN 0
            WHEN 'REGENERATE_CHARACTER_IMAGE' THEN 0
            WHEN 'EDIT_CHARACTER_IMAGE' THEN 0
            WHEN 'GENERATE_IMAGE' THEN 1
            WHEN 'REGENERATE_IMAGE' THEN 1
            WHEN 'EDIT_IMAGE' THEN 1
            WHEN 'GENERATE_VIDEO' THEN 2
            WHEN 'GENERATE_VIDEO_REFS' THEN 2
            WHEN 'UPSCALE_VIDEO' THEN 3
            ELSE 2
          END,
          created_at ASC
    """, (now,))
    rows = [dict(r) for r in await cur.fetchall()]
    # Exclude in-flight IDs
    filtered = [r for r in rows if r["id"] not in exclude]
    return filtered[:limit]


async def reset_stale_processing(cutoff_minutes: int = 10) -> int:
    """Reset PROCESSING requests older than cutoff back to PENDING."""
    db = await get_db()
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cutoff_minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')
    async with _db_lock:
        cursor = await db.execute(
            "UPDATE request SET status='PENDING', error_message='reset: stale processing' WHERE status='PROCESSING' AND updated_at < ?",
            (cutoff,))
        await db.commit()
        return cursor.rowcount


# ─── Material ────────────────────────────────────────────────

async def create_material(id: str, name: str, style_instruction: str,
                          negative_prompt: str = None, scene_prefix: str = None,
                          lighting: str = None) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO material (id,name,style_instruction,negative_prompt,scene_prefix,lighting,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (id, name, style_instruction, negative_prompt, scene_prefix,
             lighting or "Studio lighting, highly detailed", now))
        await db.commit()
    return await _get_with_db(db, "material", "id", id)

async def get_material(mid: str): return await _get("material", "id", mid)
async def delete_material(mid: str): return await _delete("material", "id", mid)
async def list_materials() -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM material ORDER BY created_at")
    return [dict(r) for r in await cur.fetchall()]


# ─── Product ─────────────────────────────────────────────────

async def create_product(raw_product_title: str, source: str = "FASTMOSS", product_display_name: str = None, product_short_name: str = None, **kw) -> dict:
    db = await get_db()
    pid, now = _uuid(), _now()
    # Basic auto-fill if missing
    display = product_display_name or " ".join(raw_product_title.split()[:9])
    short = product_short_name or " ".join(raw_product_title.split()[:4])
    
    cols = ["id", "source", "raw_product_title", "product_display_name", "product_short_name", "created_at", "updated_at"]
    vals = [pid, source, raw_product_title, display, short, now, now]
    
    allowed = _COLUMNS["product"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
            
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    
    async with _db_lock:
        await db.execute(f"INSERT INTO product ({col_str}) VALUES ({placeholders})", vals)
        await db.commit()
    return await _get_with_db(db, "product", "id", pid)

async def get_product(pid: str): return await _get("product", "id", pid)
async def update_product(pid: str, **kw): return await _update("product", "id", pid, **kw)
async def delete_product(pid: str): return await _delete("product", "id", pid)

async def count_products(source: str = None, query: str = None) -> int:
    db = await get_db()
    q, params = "SELECT COUNT(*) FROM product WHERE 1=1", []
    if source:
        q += " AND source=?"; params.append(source)
    if query:
        q += " AND (product_short_name LIKE ? OR product_display_name LIKE ? OR raw_product_title LIKE ?)"
        lk = f"%{query}%"
        params.extend([lk, lk, lk])
    cur = await db.execute(q, params)
    row = await cur.fetchone()
    return row[0] if row else 0

async def list_products(
    source: str = None,
    query: str = None,
    limit: int = None,
    offset: int = None,
    include_archived: bool = True,
    lifecycle_status: str | None = None,
) -> list[dict]:
    db = await get_db()
    q, params = "SELECT * FROM product WHERE 1=1", []
    if source:
        q += " AND source=?"; params.append(source)
    if query:
        q += " AND (product_short_name LIKE ? OR product_display_name LIKE ? OR raw_product_title LIKE ?)"
        lk = f"%{query}%"
        params.extend([lk, lk, lk])
    if lifecycle_status:
        q += " AND COALESCE(lifecycle_status, 'ACTIVE')=?"
        params.append(lifecycle_status)
    elif not include_archived:
        q += " AND COALESCE(lifecycle_status, 'ACTIVE')='ACTIVE'"
    q += " ORDER BY created_at DESC"
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)
    if offset is not None:
        q += " OFFSET ?"
        params.append(offset)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


# ─── Telemetry ───────────────────────────────────────────────

async def upsert_request_telemetry(request_id: str, **kw) -> dict:
    db = await get_db()
    existing = await _get_with_db(db, "request_telemetry", "request_id", request_id)
    if existing:
        return await _update("request_telemetry", "request_id", request_id, **kw)
    
    # Create new
    now = _now()
    cols = ["request_id", "created_at"]
    vals = [request_id, now]
    
    allowed = _COLUMNS["request_telemetry"]
    for k, v in kw.items():
        if k in allowed:
            cols.append(k)
            vals.append(v)
            
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    
    async with _db_lock:
        await db.execute(f"INSERT INTO request_telemetry ({col_str}) VALUES ({placeholders})", vals)
        await db.commit()
    return await _get_with_db(db, "request_telemetry", "request_id", request_id)


async def add_stage_event(request_id: str, stage: str, status: str, message: str = None, source: str = "backend") -> dict:
    db = await get_db()
    eid, now = _uuid(), _now()
    async with _db_lock:
        await db.execute(
            "INSERT INTO request_stage_event (id, request_id, timestamp, stage, status, message, source) VALUES (?,?,?,?,?,?,?)",
            (eid, request_id, now, stage, status, message, source))
        await db.commit()
    return await _get_with_db(db, "request_stage_event", "id", eid)


async def get_request_telemetry(request_id: str):
    return await _get("request_telemetry", "request_id", request_id)


async def list_request_telemetry(project_id: str = None, video_id: str = None, limit: int = 50) -> list[dict]:
    db = await get_db()
    q, params = "SELECT * FROM request_telemetry WHERE 1=1", []
    if project_id:
        q += " AND project_id=?"; params.append(project_id)
    if video_id:
        q += " AND video_id=?"; params.append(video_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def get_stage_history(request_id: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM request_stage_event WHERE request_id=? ORDER BY timestamp ASC", (request_id,))
    return [dict(r) for r in await cur.fetchall()]


async def get_telemetry_summary() -> dict:
    db = await get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "%"
    
    cur = await db.execute("""
        SELECT 
            COUNT(*) as total_today,
            SUM(CASE WHEN status='QUEUED' THEN 1 ELSE 0 END) as queued,
            SUM(CASE WHEN status='PROCESSING' THEN 1 ELSE 0 END) as processing,
            SUM(CASE WHEN status='WAITING_FLOW' THEN 1 ELSE 0 END) as waiting_flow,
            SUM(CASE WHEN status='FLOW_RUNNING' THEN 1 ELSE 0 END) as flow_running,
            SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) as failed
        FROM request_telemetry 
        WHERE created_at LIKE ?
    """, (today,))
    row = await cur.fetchone()
    summary = {
        "total_today": row["total_today"] or 0,
        "queued": row["queued"] or 0,
        "processing": row["processing"] or 0,
        "waiting_flow": row["waiting_flow"] or 0,
        "flow_running": row["flow_running"] or 0,
        "completed": row["completed"] or 0,
        "failed": row["failed"] or 0
    } if row else {
        "total_today": 0, "queued": 0, "processing": 0, 
        "waiting_flow": 0, "flow_running": 0, "completed": 0, "failed": 0
    }
    
    cur = await db.execute("SELECT status, google_flow_stage, error_message FROM request_telemetry ORDER BY created_at DESC LIMIT 1")
    last = await cur.fetchone()
    if last:
        summary["last_job_status"] = last["status"] or ""
        summary["last_stage"] = last["google_flow_stage"] or ""
        summary["last_error"] = last["error_message"] or ""
    else:
        summary["last_job_status"] = ""
        summary["last_stage"] = ""
        summary["last_error"] = ""
        
    summary["idle_seconds"] = 0 
    
    return summary
