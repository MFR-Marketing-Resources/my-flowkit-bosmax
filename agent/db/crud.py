"""Async CRUD operations with column whitelisting."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from agent.db.schema import get_db, _db_lock

logger = logging.getLogger(__name__)

_VALID_TABLES = frozenset({"character", "project", "video", "scene", "request", "material", "product", "request_telemetry", "request_stage_event", "workspace_execution_package", "creative_asset", "workspace_generation_package", "fastmoss_bulk_draft_status", "production_run", "postiz_publish_record"})


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
    "product": {"source", "source_url", "brand", "raw_product_title", "product_display_name", "product_short_name", "category", "subcategory", "type", "shop_name", "price", "currency", "commission_amount", "commission_rate", "price_min", "price_max", "commission", "image_url", "tiktok_product_url", "fastmoss_source_file", "image_asset_status", "image_failure_detail", "product_type", "product_type_id", "silo", "trigger_id", "formula", "copywriting_angle", "claim_risk_level", "mode_recommendations", "physics_class", "product_scale", "hand_object_interaction", "recommended_grip", "handling_notes", "air_gap_rule", "material_behavior", "surface_behavior", "fragility_level", "camera_handling_notes", "scene_context", "camera_style", "camera_behavior", "camera_shot", "unsafe_handling_rules", "section_4_hint", "section_5_product_physics_prompt", "section_5_physics_hint", "section_6_copy_hint", "section_9_overlay_hint", "mapping_source", "mapping_confidence", "mapping_review_status", "mapping_status", "mapping_missing_fields", "prompt_readiness_status", "prompt_missing_fields", "claim_safe_copy_status", "claim_safe_copy_payload", "claim_safe_copy_updated_at", "production_prompt_approval_status", "production_prompt_approved_modes", "production_prompt_approved_at", "production_prompt_approval_note", "production_prompt_approval_provenance", "lifecycle_status", "archived_at", "archived_reason", "archived_by", "unarchived_at", "unarchived_reason", "lifecycle_provenance", "asset_status", "media_id", "local_image_path", "updated_at", "fastmoss_reference_id"},
    "request_telemetry": {"project_id", "video_id", "scene_id", "product_id", "request_type", "mode", "prompt_package_snapshot_id", "workspace_execution_package_id", "workspace_generation_package_id", "prompt_fingerprint", "asset_fingerprints", "request_lineage_payload", "git_sha", "background_build_id", "content_build_id", "last_checkpoint", "runtime_ready", "build_match", "status", "google_flow_stage", "extension_stage", "worker_stage", "queued_at", "started_at", "last_heartbeat_at", "completed_at", "failed_at", "duration_seconds", "idle_seconds", "processing_seconds", "error_code", "error_message"},
    "request_stage_event": {"request_id", "timestamp", "checkpoint", "stage", "status", "message", "git_sha", "background_build_id", "content_build_id", "runtime_ready", "build_match", "selector_used", "evidence_pointer", "fail_code", "first_fail_stage", "source"},
    "workspace_execution_package": {"product_id", "mode", "duration_seconds", "aspect_ratio", "model", "manual_override", "prompt_text", "prompt_fingerprint", "prompt_package_snapshot_id", "asset_slots", "resolved_assets", "readiness", "execution_allowed", "production_generation_allowed", "manual_fallback", "blockers", "request_lineage_payload", "source_of_truth_notes", "updated_at"},
    "creative_asset": {"semantic_role", "display_name", "description", "source_type", "storage_kind", "preview_url", "download_url", "media_id", "local_file_path", "remote_source_url", "product_id", "category", "silo", "product_type", "allowed_modes", "engine_slot_eligibility", "mode_a_metadata_handoff", "visual_dna_summary", "character_dna", "scene_context_dna", "style_mood_dna", "source_prompt_fingerprint", "source_workspace_execution_package_id", "source_prompt_package_snapshot_id", "status", "updated_at"},
    "fastmoss_bulk_draft_status": {"raw_product_title", "source_url", "tiktok_product_url", "image_url", "category", "claim_risk_level", "mapping_confidence", "image_readiness", "copy_route", "sold_count", "commission_rate", "promotion_status", "draft_id", "committed_product_id", "suspected_existing_product_id", "suspected_existing_product_title", "suspected_existing_product_source", "suspected_existing_product_mapping_source", "duplicate_match_reason", "linked_product_id", "linked_product_title", "duplicate_resolution", "duplicate_resolved_at", "duplicate_resolution_note", "duplicate_ignore_product_id", "error_message", "batch_provenance", "recomputed_at", "recompute_previous_status", "recompute_previous_error", "updated_at"},
    "workspace_generation_package": {"mode", "product_id", "product_name_snapshot", "source_lane", "prompt_package_snapshot_id", "workspace_execution_package_id", "generation_mode", "final_prompt_text", "prompt_blocks_json", "selected_assets_json", "resolved_engine_slots_json", "resolver_output_json", "image_assets_json", "manual_handoff_json", "dom_handoff_payload_json", "blockers_json", "warnings_json", "status", "operator_notes", "batch_run_id", "logical_mode", "variation_strategy", "prompt_fingerprint", "variation_fingerprints_json", "anti_redundancy_json", "production_status", "production_run_id", "production_job_id", "production_error", "artifact_media_ids_json", "approved_at", "sent_to_production_at", "updated_at"},
    "production_run": {"status", "dry_run", "max_parallel_jobs", "interval_min_seconds", "interval_max_seconds", "cooldown_after_n_jobs", "cooldown_seconds", "total_expected", "total_completed", "total_failed", "error_log_json", "config_json", "updated_at"},
    "postiz_publish_record": {"artifact_media_id", "source_local_path", "source_public_url", "upload_mode", "postiz_media_id", "postiz_media_path", "post_type", "scheduled_at", "content", "integration_ids_json", "provider_settings_json", "postiz_response_json", "status", "error", "updated_at"},
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


async def add_stage_event(request_id: str, stage: str, status: str, message: str = None, source: str = "backend", **extra) -> dict:
    db = await get_db()
    eid, now = _uuid(), _now()
    payload = {
        "id": eid,
        "request_id": request_id,
        "timestamp": now,
        "checkpoint": extra.get("checkpoint"),
        "stage": stage,
        "status": status,
        "message": message,
        "git_sha": extra.get("git_sha"),
        "background_build_id": extra.get("background_build_id"),
        "content_build_id": extra.get("content_build_id"),
        "runtime_ready": extra.get("runtime_ready"),
        "build_match": extra.get("build_match"),
        "selector_used": extra.get("selector_used"),
        "evidence_pointer": extra.get("evidence_pointer"),
        "fail_code": extra.get("fail_code"),
        "first_fail_stage": extra.get("first_fail_stage"),
        "source": source,
    }
    columns = [key for key, value in payload.items() if value is not None]
    values = [payload[key] for key in columns]
    placeholders = ",".join(["?"] * len(columns))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO request_stage_event ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        await db.commit()
    return await _get_with_db(db, "request_stage_event", "id", eid)


async def get_request_telemetry(request_id: str):
    return await _get("request_telemetry", "request_id", request_id)


async def list_request_telemetry(
    project_id: str = None,
    video_id: str = None,
    limit: int = 50,
    *,
    request_type: str = None,
    mode: str = None,
) -> list[dict]:
    db = await get_db()
    q, params = "SELECT * FROM request_telemetry WHERE 1=1", []
    if project_id:
        q += " AND project_id=?"; params.append(project_id)
    if video_id:
        q += " AND video_id=?"; params.append(video_id)
    if request_type:
        q += " AND request_type=?"; params.append(request_type)
    if mode:
        q += " AND mode=?"; params.append(mode)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def create_or_replace_workspace_execution_package(
    workspace_execution_package_id: str,
    *,
    product_id: str,
    mode: str,
    duration_seconds: int,
    aspect_ratio: str,
    model: str,
    manual_override: bool,
    prompt_text: str,
    prompt_fingerprint: str,
    prompt_package_snapshot_id: str,
    asset_slots: str,
    resolved_assets: str,
    readiness: str,
    execution_allowed: bool,
    production_generation_allowed: bool,
    manual_fallback: str,
    blockers: str,
    request_lineage_payload: str,
    source_of_truth_notes: str,
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO workspace_execution_package (
                workspace_execution_package_id, product_id, mode, duration_seconds, aspect_ratio, model,
                manual_override, prompt_text, prompt_fingerprint, prompt_package_snapshot_id, asset_slots,
                resolved_assets, readiness, execution_allowed, production_generation_allowed, manual_fallback,
                blockers, request_lineage_payload, source_of_truth_notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_execution_package_id) DO UPDATE SET
                product_id=excluded.product_id,
                mode=excluded.mode,
                duration_seconds=excluded.duration_seconds,
                aspect_ratio=excluded.aspect_ratio,
                model=excluded.model,
                manual_override=excluded.manual_override,
                prompt_text=excluded.prompt_text,
                prompt_fingerprint=excluded.prompt_fingerprint,
                prompt_package_snapshot_id=excluded.prompt_package_snapshot_id,
                asset_slots=excluded.asset_slots,
                resolved_assets=excluded.resolved_assets,
                readiness=excluded.readiness,
                execution_allowed=excluded.execution_allowed,
                production_generation_allowed=excluded.production_generation_allowed,
                manual_fallback=excluded.manual_fallback,
                blockers=excluded.blockers,
                request_lineage_payload=excluded.request_lineage_payload,
                source_of_truth_notes=excluded.source_of_truth_notes,
                updated_at=excluded.updated_at
            """,
            (
                workspace_execution_package_id,
                product_id,
                mode,
                duration_seconds,
                aspect_ratio,
                model,
                1 if manual_override else 0,
                prompt_text,
                prompt_fingerprint,
                prompt_package_snapshot_id,
                asset_slots,
                resolved_assets,
                readiness,
                1 if execution_allowed else 0,
                1 if production_generation_allowed else 0,
                manual_fallback,
                blockers,
                request_lineage_payload,
                source_of_truth_notes,
                now,
                now,
            ),
        )
        await db.commit()
    return await _get_with_db(db, "workspace_execution_package", "workspace_execution_package_id", workspace_execution_package_id)


async def list_workspace_execution_packages(
    *,
    product_id: str | None = None,
    mode: str | None = None,
    limit: int = 20,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM workspace_execution_package WHERE 1=1"
    params: list = []
    if product_id:
        q += " AND product_id=?"
        params.append(product_id)
    if mode:
        q += " AND mode=?"
        params.append(mode)
    q += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def create_creative_asset(
    *,
    asset_id: str,
    semantic_role: str,
    display_name: str,
    description: str | None,
    source_type: str,
    storage_kind: str,
    preview_url: str | None,
    download_url: str | None,
    media_id: str | None,
    local_file_path: str | None,
    remote_source_url: str | None,
    product_id: str | None,
    category: str | None,
    silo: str | None,
    product_type: str | None,
    allowed_modes: str,
    engine_slot_eligibility: str,
    mode_a_metadata_handoff: str | None,
    visual_dna_summary: str | None,
    character_dna: str | None,
    scene_context_dna: str | None,
    style_mood_dna: str | None,
    source_prompt_fingerprint: str | None,
    source_workspace_execution_package_id: str | None,
    source_prompt_package_snapshot_id: str | None,
    status: str,
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO creative_asset (
                asset_id, semantic_role, display_name, description, source_type, storage_kind,
                preview_url, download_url, media_id, local_file_path, remote_source_url, product_id,
                category, silo, product_type, allowed_modes, engine_slot_eligibility,
                mode_a_metadata_handoff, visual_dna_summary, character_dna, scene_context_dna,
                style_mood_dna, source_prompt_fingerprint, source_workspace_execution_package_id,
                source_prompt_package_snapshot_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                semantic_role,
                display_name,
                description,
                source_type,
                storage_kind,
                preview_url,
                download_url,
                media_id,
                local_file_path,
                remote_source_url,
                product_id,
                category,
                silo,
                product_type,
                allowed_modes,
                engine_slot_eligibility,
                mode_a_metadata_handoff,
                visual_dna_summary,
                character_dna,
                scene_context_dna,
                style_mood_dna,
                source_prompt_fingerprint,
                source_workspace_execution_package_id,
                source_prompt_package_snapshot_id,
                status,
                now,
                now,
            ),
        )
        await db.commit()
    return await _get_with_db(db, "creative_asset", "asset_id", asset_id)


async def get_creative_asset(asset_id: str):
    return await _get("creative_asset", "asset_id", asset_id)


async def update_creative_asset(asset_id: str, **kw):
    return await _update("creative_asset", "asset_id", asset_id, **kw)


async def list_creative_assets(
    *,
    semantic_role: str | None = None,
    status: str | None = None,
    product_id: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM creative_asset WHERE 1=1"
    params: list[object] = []
    if semantic_role:
        q += " AND semantic_role=?"
        params.append(semantic_role)
    if status:
        q += " AND status=?"
        params.append(status)
    if product_id:
        q += " AND product_id=?"
        params.append(product_id)
    if search:
        like = f"%{search.lower()}%"
        q += " AND (lower(display_name) LIKE ? OR lower(coalesce(description, '')) LIKE ? OR lower(coalesce(category, '')) LIKE ? OR lower(coalesce(silo, '')) LIKE ? OR lower(coalesce(product_id, '')) LIKE ?)"
        params.extend([like, like, like, like, like])
    q += " ORDER BY updated_at DESC LIMIT ?"
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


# ─── Workspace Generation Package ───────────────────────────

async def create_workspace_generation_package(
    workspace_generation_package_id: str,
    *,
    mode: str,
    product_id: str,
    product_name_snapshot: str,
    source_lane: str,
    prompt_package_snapshot_id: str,
    workspace_execution_package_id: str | None,
    generation_mode: str,
    final_prompt_text: str,
    prompt_blocks_json: str,
    selected_assets_json: str,
    resolved_engine_slots_json: str,
    resolver_output_json: str,
    image_assets_json: str,
    manual_handoff_json: str,
    dom_handoff_payload_json: str,
    blockers_json: str,
    warnings_json: str,
    status: str,
    batch_run_id: str | None = None,
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO workspace_generation_package (
                workspace_generation_package_id, mode, product_id, product_name_snapshot,
                source_lane, prompt_package_snapshot_id, workspace_execution_package_id,
                generation_mode, final_prompt_text, prompt_blocks_json, selected_assets_json,
                resolved_engine_slots_json, resolver_output_json, image_assets_json,
                manual_handoff_json, dom_handoff_payload_json, blockers_json, warnings_json,
                status, batch_run_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                workspace_generation_package_id, mode, product_id, product_name_snapshot,
                source_lane, prompt_package_snapshot_id, workspace_execution_package_id,
                generation_mode, final_prompt_text, prompt_blocks_json, selected_assets_json,
                resolved_engine_slots_json, resolver_output_json, image_assets_json,
                manual_handoff_json, dom_handoff_payload_json, blockers_json, warnings_json,
                status, batch_run_id, now, now,
            ),
        )
        await db.commit()
    return await _get_with_db(db, "workspace_generation_package", "workspace_generation_package_id", workspace_generation_package_id)


async def get_workspace_generation_package(wgp_id: str):
    return await _get("workspace_generation_package", "workspace_generation_package_id", wgp_id)


async def update_workspace_generation_package(wgp_id: str, **kw):
    return await _update("workspace_generation_package", "workspace_generation_package_id", wgp_id, **kw)


async def list_workspace_generation_packages(
    mode: str | None = None,
    status: str | None = None,
    product_id: str | None = None,
    batch_run_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = await get_db()
    q, params = "SELECT * FROM workspace_generation_package WHERE 1=1", []
    if mode:
        q += " AND mode=?"; params.append(mode)
    if status:
        q += " AND status=?"; params.append(status)
    if product_id:
        q += " AND product_id=?"; params.append(product_id)
    if batch_run_id:
        q += " AND batch_run_id=?"; params.append(batch_run_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def create_batch_generation_run(
    batch_run_id: str,
    *,
    product_id: str,
    modes_json: str,
    quantity_per_mode: int,
    interval_seconds: int,
    generation_mode: str,
    total_expected: int,
    product_ids_json: str = "[]",
    config_json: str = "{}",
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO batch_generation_run
               (batch_run_id, status, product_id, modes_json, quantity_per_mode,
                interval_seconds, generation_mode, total_expected, total_completed,
                total_failed, error_log_json, product_ids_json, config_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,0,0,'[]',?,?,?,?)""",
            (batch_run_id, "PENDING", product_id, modes_json, quantity_per_mode,
             interval_seconds, generation_mode, total_expected,
             product_ids_json, config_json, now, now),
        )
        await db.commit()
    cur = await db.execute("SELECT * FROM batch_generation_run WHERE batch_run_id=?", (batch_run_id,))
    row = await cur.fetchone()
    return dict(row) if row else {}


async def update_batch_generation_run(
    batch_run_id: str,
    *,
    status: str | None = None,
    total_completed: int | None = None,
    total_failed: int | None = None,
    error_log_json: str | None = None,
) -> None:
    db = await get_db()
    now = _now()
    parts, params = [], []
    if status is not None:
        parts.append("status=?"); params.append(status)
    if total_completed is not None:
        parts.append("total_completed=?"); params.append(total_completed)
    if total_failed is not None:
        parts.append("total_failed=?"); params.append(total_failed)
    if error_log_json is not None:
        parts.append("error_log_json=?"); params.append(error_log_json)
    if not parts:
        return
    parts.append("updated_at=?"); params.append(now)
    params.append(batch_run_id)
    async with _db_lock:
        await db.execute(f"UPDATE batch_generation_run SET {', '.join(parts)} WHERE batch_run_id=?", params)
        await db.commit()


# ── Production queue (prompt/production split) ───────────────────────────


async def create_production_run(
    production_run_id: str,
    *,
    dry_run: bool = True,
    max_parallel_jobs: int = 1,
    interval_min_seconds: int = 45,
    interval_max_seconds: int = 120,
    cooldown_after_n_jobs: int = 5,
    cooldown_seconds: int = 300,
    total_expected: int = 0,
    config_json: str = "{}",
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO production_run
               (production_run_id, status, dry_run, max_parallel_jobs,
                interval_min_seconds, interval_max_seconds, cooldown_after_n_jobs,
                cooldown_seconds, total_expected, total_completed, total_failed,
                error_log_json, config_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,0,0,'[]',?,?,?)""",
            (production_run_id, "PENDING", 1 if dry_run else 0, max_parallel_jobs,
             interval_min_seconds, interval_max_seconds, cooldown_after_n_jobs,
             cooldown_seconds, total_expected, config_json, now, now),
        )
        await db.commit()
    return await _get_with_db(db, "production_run", "production_run_id", production_run_id)


async def get_production_run(production_run_id: str):
    return await _get("production_run", "production_run_id", production_run_id)


async def update_production_run(production_run_id: str, **kw):
    return await _update("production_run", "production_run_id", production_run_id, **kw)


async def list_production_runs(limit: int = 50) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM production_run ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def list_production_queue_packages(
    production_run_id: str | None = None,
    production_status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Prompt packages viewed through their production lifecycle."""
    db = await get_db()
    q, params = "SELECT * FROM workspace_generation_package WHERE 1=1", []
    if production_run_id:
        q += " AND production_run_id=?"; params.append(production_run_id)
    if production_status:
        q += " AND production_status=?"; params.append(production_status)
    else:
        q += " AND production_status IS NOT NULL AND production_status NOT IN ('', 'NONE')"
    q += " ORDER BY sent_to_production_at ASC, created_at ASC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def link_artifacts_to_generation_package(job_id: str, wgp_id: str) -> int:
    """Post-hoc link: stamp artifacts registered by a generate job with their
    source prompt package. Leaves make_video untouched (locked lane)."""
    if not job_id or not wgp_id:
        return 0
    db = await get_db()
    async with _db_lock:
        cur = await db.execute(
            "UPDATE generated_artifact SET workspace_generation_package_id=? WHERE job_id=?",
            (wgp_id, job_id),
        )
        await db.commit()
    return cur.rowcount


async def list_recent_prompt_fingerprints(
    product_id: str,
    logical_mode: str,
    limit: int = 500,
) -> list[dict]:
    """Recent redundancy history for a product+mode: fingerprints only."""
    db = await get_db()
    cur = await db.execute(
        """SELECT workspace_generation_package_id, prompt_fingerprint,
                  variation_fingerprints_json, created_at
           FROM workspace_generation_package
           WHERE product_id=? AND (logical_mode=? OR (logical_mode IS NULL AND mode=?))
             AND status != 'ARCHIVED'
           ORDER BY created_at DESC LIMIT ?""",
        (product_id, logical_mode, logical_mode, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_batch_generation_run(batch_run_id: str) -> dict | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM batch_generation_run WHERE batch_run_id=?", (batch_run_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


# ── Postiz publishing audit trail ─────────────────────────────────────────


async def create_postiz_publish_record(
    record_id: str,
    *,
    artifact_media_id: str | None,
    source_local_path: str | None,
    source_public_url: str | None,
    upload_mode: str,
    post_type: str,
    scheduled_at: str | None,
    content: str | None,
    integration_ids_json: str,
    provider_settings_json: str,
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO postiz_publish_record
               (record_id, artifact_media_id, source_local_path, source_public_url,
                upload_mode, post_type, scheduled_at, content, integration_ids_json,
                provider_settings_json, postiz_response_json, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,'{}','PENDING',?,?)""",
            (record_id, artifact_media_id, source_local_path, source_public_url,
             upload_mode, post_type, scheduled_at, content, integration_ids_json,
             provider_settings_json, now, now),
        )
        await db.commit()
    return await _get_with_db(db, "postiz_publish_record", "record_id", record_id)


async def update_postiz_publish_record(record_id: str, **kw):
    return await _update("postiz_publish_record", "record_id", record_id, **kw)


async def list_postiz_publish_records(limit: int = 50) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM postiz_publish_record ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ─── Scheduled Batch Runs ─────────────────────────────────────

async def create_scheduled_batch_run(
    scheduled_run_id: str,
    *,
    product_ids_json: str,
    modes_json: str,
    quantity_per_mode: int,
    interval_seconds: int,
    generation_mode: str,
    character_asset_ids_json: str,
    scene_asset_ids_json: str,
    style_asset_ids_json: str,
    img_prompt_template: str | None,
    scheduled_at: str,
    label: str | None,
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO scheduled_batch_run
               (scheduled_run_id, status, product_ids_json, modes_json,
                quantity_per_mode, interval_seconds, generation_mode,
                character_asset_ids_json, scene_asset_ids_json, style_asset_ids_json,
                img_prompt_template, scheduled_at, label, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scheduled_run_id, "SCHEDULED", product_ids_json, modes_json,
             quantity_per_mode, interval_seconds, generation_mode,
             character_asset_ids_json, scene_asset_ids_json, style_asset_ids_json,
             img_prompt_template, scheduled_at, label, now, now),
        )
        await db.commit()
    cur = await db.execute(
        "SELECT * FROM scheduled_batch_run WHERE scheduled_run_id=?", (scheduled_run_id,)
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


async def list_scheduled_batch_runs(
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM scheduled_batch_run"
    params: list = []
    if status:
        q += " WHERE status=?"
        params.append(status)
    q += " ORDER BY scheduled_at ASC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def update_scheduled_batch_run(
    scheduled_run_id: str,
    *,
    status: str | None = None,
    batch_run_id: str | None = None,
) -> None:
    db = await get_db()
    now = _now()
    parts, params = [], []
    if status is not None:
        parts.append("status=?"); params.append(status)
    if batch_run_id is not None:
        parts.append("batch_run_id=?"); params.append(batch_run_id)
    if not parts:
        return
    parts.append("updated_at=?"); params.append(now)
    params.append(scheduled_run_id)
    async with _db_lock:
        await db.execute(
            f"UPDATE scheduled_batch_run SET {', '.join(parts)} WHERE scheduled_run_id=?",
            params,
        )
        await db.commit()


async def get_due_scheduled_batch_runs(now_iso: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM scheduled_batch_run WHERE status='SCHEDULED' AND scheduled_at <= ?",
        (now_iso,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def list_batch_generation_runs(
    product_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM batch_generation_run"
    params: list = []
    if product_id:
        q += " WHERE product_id=?"
        params.append(product_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


# ─── FastMoss Bulk Queue ─────────────────────────────────────

async def create_bulk_queue_row(reference_id: str, raw_product_title: str, **kw) -> dict:
    db = await get_db()
    now = _now()
    cols = ["reference_id", "raw_product_title", "created_at", "updated_at"]
    vals = [reference_id, raw_product_title, now, now]
    allowed = _COLUMNS["fastmoss_bulk_draft_status"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT OR IGNORE INTO fastmoss_bulk_draft_status ({col_str}) VALUES ({placeholders})",
            vals,
        )
        await db.commit()
    cur = await db.execute(
        "SELECT * FROM fastmoss_bulk_draft_status WHERE reference_id=?", [reference_id]
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


async def get_bulk_queue_row(reference_id: str) -> Optional[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM fastmoss_bulk_draft_status WHERE reference_id=?", [reference_id]
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def update_bulk_queue_row(reference_id: str, **kw) -> Optional[dict]:
    return await _update("fastmoss_bulk_draft_status", "reference_id", reference_id, **kw)


async def list_bulk_queue(
    promotion_status: str | None = None,
    claim_risk_level: str | None = None,
    image_readiness: str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    db = await get_db()
    query, params = "SELECT * FROM fastmoss_bulk_draft_status WHERE 1=1", []
    if promotion_status:
        query += " AND promotion_status=?"; params.append(promotion_status)
    if claim_risk_level:
        query += " AND claim_risk_level=?"; params.append(claim_risk_level)
    if image_readiness:
        query += " AND image_readiness=?"; params.append(image_readiness)
    if category:
        query += " AND category=?"; params.append(category)
    if q:
        query += " AND raw_product_title LIKE ?"; params.append(f"%{q}%")
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])
    cur = await db.execute(query, params)
    return [dict(r) for r in await cur.fetchall()]


async def count_bulk_queue(
    promotion_status: str | None = None,
    claim_risk_level: str | None = None,
    image_readiness: str | None = None,
    category: str | None = None,
    q: str | None = None,
) -> int:
    db = await get_db()
    query, params = "SELECT COUNT(*) FROM fastmoss_bulk_draft_status WHERE 1=1", []
    if promotion_status:
        query += " AND promotion_status=?"; params.append(promotion_status)
    if claim_risk_level:
        query += " AND claim_risk_level=?"; params.append(claim_risk_level)
    if image_readiness:
        query += " AND image_readiness=?"; params.append(image_readiness)
    if category:
        query += " AND category=?"; params.append(category)
    if q:
        query += " AND raw_product_title LIKE ?"; params.append(f"%{q}%")
    cur = await db.execute(query, params)
    row = await cur.fetchone()
    return row[0] if row else 0


async def get_bulk_queue_stats() -> dict:
    db = await get_db()
    cur = await db.execute(
        "SELECT promotion_status, COUNT(*) as cnt FROM fastmoss_bulk_draft_status GROUP BY promotion_status"
    )
    status_rows = await cur.fetchall()
    cur = await db.execute(
        "SELECT claim_risk_level, COUNT(*) as cnt FROM fastmoss_bulk_draft_status GROUP BY claim_risk_level"
    )
    risk_rows = await cur.fetchall()
    cur = await db.execute("SELECT COUNT(*) FROM fastmoss_bulk_draft_status")
    total = (await cur.fetchone())[0]
    return {
        "total": total,
        "by_status": {row[0]: row[1] for row in status_rows},
        "by_risk": {row[0]: row[1] for row in risk_rows},
    }


# ─── Generated Artifact Library (ADR-007 production) ─────────

async def insert_generated_artifact(media_id: str, job_id: str = None, mode: str = None,
                                    artifact_kind: str = "video", local_path: str = None,
                                    size_mb: float = None, project_id: str = None,
                                    model_used: str = None, duration_used: int = None) -> None:
    """Register a finished generation in the system library (idempotent on media_id)."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """INSERT OR REPLACE INTO generated_artifact
               (media_id, job_id, mode, artifact_kind, local_path, size_mb,
                project_id, model_used, duration_used, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (media_id, job_id, mode, artifact_kind, local_path, size_mb,
             project_id, model_used, duration_used, _now()),
        )
        await db.commit()


async def get_generated_artifact(media_id: str) -> dict | None:
    """Single artifact row by Flow media id (Postiz handoff resolver)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM generated_artifact WHERE media_id=?", (media_id,)
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_generated_artifacts(limit: int = 50, mode: str = None,
                                    kind: str = None) -> list:
    """Newest-first library listing for the dashboard gallery."""
    db = await get_db()
    query = """SELECT media_id, job_id, mode, artifact_kind, local_path, size_mb,
                      project_id, model_used, duration_used, created_at
               FROM generated_artifact"""
    clauses = []
    params: tuple = ()
    if mode:
        clauses.append("mode = ?")
        params += (str(mode).upper(),)
    if kind:
        clauses.append("artifact_kind = ?")
        params += (str(kind).lower(),)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params += (int(limit),)
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    keys = ("media_id", "job_id", "mode", "artifact_kind", "local_path", "size_mb",
            "project_id", "model_used", "duration_used", "created_at")
    return [dict(zip(keys, row)) for row in rows]


async def purge_expired_artifacts(retention_hours: int = 48) -> dict:
    """Retention law: finished artifacts live 48 hours, then the FILE and the
    library row are deleted. Runs lazily on every library listing (no scheduler
    needed) and is safe to call repeatedly."""
    import os
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    db = await get_db()
    cursor = await db.execute(
        "SELECT media_id, local_path FROM generated_artifact WHERE created_at < ?",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    removed_files = 0
    for _media_id, local_path in rows:
        if local_path:
            try:
                os.remove(local_path)
                removed_files += 1
            except OSError:
                pass  # already gone — row cleanup below still applies
    if rows:
        async with _db_lock:
            await db.execute(
                "DELETE FROM generated_artifact WHERE created_at < ?", (cutoff,))
            await db.commit()
    return {"purged_rows": len(rows), "purged_files": removed_files,
            "retention_hours": retention_hours, "cutoff": cutoff}

