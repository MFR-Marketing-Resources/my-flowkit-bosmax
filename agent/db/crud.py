"""Async CRUD operations with column whitelisting."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from agent.db.schema import get_db, _db_lock

logger = logging.getLogger(__name__)

_VALID_TABLES = frozenset({"character", "project", "video", "scene", "request", "material", "product", "request_telemetry", "request_stage_event", "workspace_execution_package", "creative_asset", "workspace_generation_package", "fastmoss_bulk_draft_status", "production_run", "bulk_generation_run", "bulk_generation_item", "postiz_publish_record", "social_copy_package", "copy_set", "copy_intelligence_seed", "product_intelligence_snapshot", "product_intelligence_field_provenance", "product_intelligence_review_draft", "product_intelligence_review_field_provenance", "copy_generation_batch", "avatar_product_fit", "poster_copy_set", "poster_deliverable", "extend_lineage"})


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
    "creative_asset": {"semantic_role", "display_name", "description", "source_type", "storage_kind", "preview_url", "download_url", "media_id", "local_file_path", "remote_source_url", "product_id", "category", "silo", "product_type", "allowed_modes", "engine_slot_eligibility", "mode_a_metadata_handoff", "visual_dna_summary", "character_dna", "scene_context_dna", "style_mood_dna", "source_prompt_fingerprint", "source_workspace_execution_package_id", "source_prompt_package_snapshot_id", "asset_subtype", "generation_recipe_id", "source_character_asset_id", "source_scene_asset_id", "source_style_asset_id", "contains_rendered_text", "approved_for_video_support", "approved_for_poster", "product_truth_status", "identity_lock_status", "scale_truth_status", "claim_safety_status", "review_status", "status", "updated_at"},
    "fastmoss_bulk_draft_status": {"raw_product_title", "source_url", "tiktok_product_url", "image_url", "category", "claim_risk_level", "mapping_confidence", "image_readiness", "copy_route", "sold_count", "commission_rate", "promotion_status", "draft_id", "committed_product_id", "suspected_existing_product_id", "suspected_existing_product_title", "suspected_existing_product_source", "suspected_existing_product_mapping_source", "duplicate_match_reason", "linked_product_id", "linked_product_title", "duplicate_resolution", "duplicate_resolved_at", "duplicate_resolution_note", "duplicate_ignore_product_id", "error_message", "batch_provenance", "recomputed_at", "recompute_previous_status", "recompute_previous_error", "updated_at"},
    "workspace_generation_package": {"mode", "product_id", "product_name_snapshot", "source_lane", "prompt_package_snapshot_id", "workspace_execution_package_id", "generation_mode", "final_prompt_text", "prompt_blocks_json", "selected_assets_json", "resolved_engine_slots_json", "resolver_output_json", "image_assets_json", "manual_handoff_json", "dom_handoff_payload_json", "blockers_json", "warnings_json", "status", "operator_notes", "batch_run_id", "logical_mode", "variation_strategy", "prompt_fingerprint", "variation_fingerprints_json", "anti_redundancy_json", "production_status", "production_run_id", "production_job_id", "production_error", "artifact_media_ids_json", "approved_at", "sent_to_production_at", "updated_at"},
    "production_run": {"status", "dry_run", "max_parallel_jobs", "interval_min_seconds", "interval_max_seconds", "cooldown_after_n_jobs", "cooldown_seconds", "total_expected", "total_completed", "total_failed", "error_log_json", "config_json", "updated_at"},
    "bulk_generation_run": {"kind", "status", "total_expected", "total_completed", "total_failed", "max_parallel_images", "max_parallel_videos", "confirm_credit_burn", "interval_min_seconds", "interval_max_seconds", "cooldown_after_n_jobs", "cooldown_seconds", "error_log_json", "config_json", "updated_at"},
    "bulk_generation_item": {"bulk_run_id", "item_type", "source_ref", "prompt_snapshot", "payload_json", "status", "job_id", "media_id", "local_path", "creative_asset_id", "error", "retry_count", "started_at", "completed_at", "updated_at"},
    "postiz_publish_record": {"artifact_media_id", "source_local_path", "source_public_url", "upload_mode", "postiz_media_id", "postiz_media_path", "post_type", "scheduled_at", "content", "integration_ids_json", "provider_settings_json", "postiz_response_json", "status", "error", "updated_at"},
    "social_copy_package": {"artifact_media_id", "source_mode", "platform", "caption", "first_comment", "hashtags_json", "call_to_action", "tone", "language", "status", "compliance_status", "blockers_json", "warnings_json", "approval_note", "approved_at", "postiz_record_id", "updated_at"},
    "copy_set": {"angle", "hook", "subhook", "usp_set_json", "cta", "platform", "language", "route_type", "formula_family", "status", "dedupe_key", "source", "provenance_json", "claim_review_json", "reviewer_note", "approved_at", "approved_by", "usage_count", "last_used_at", "used_in_modes", "uniqueness_score", "similar_to_copy_set_id", "similarity_score", "archived", "updated_at"},
    "copy_intelligence_seed": {"source_fingerprint", "source_workbook", "source_sheet", "source_row", "source_product_name", "reference_id", "target_product_id", "match_method", "confidence", "status", "target_avatar", "pain_point", "emotion_trigger", "dream_outcome", "key_ingredients_features", "hook_type", "hook_script", "body_script", "cta_type", "cta_script", "tone", "pronoun", "copy_angle", "provenance_json", "updated_at"},
    "poster_copy_set": {"campaign_id", "objective", "archetype", "angle", "primary_message", "support_message", "proof_points_json", "offer_json", "cta", "disclaimer", "tone", "language", "variants_json", "field_provenance_json", "ai_model", "prompt_version", "status", "version", "parent_poster_copy_set_id", "archived", "reject_reason", "approved_at", "approved_by", "updated_at"},
    "poster_deliverable": {"poster_copy_set_id", "recipe_id", "template_version", "composition_strategy", "render_manifest_json", "background_media_id", "background_local_path", "output_path", "output_sha256", "creative_asset_id", "qa_report_json", "settings_json", "status", "updated_at"},
    "product_intelligence_snapshot": {"product_id", "version", "status", "product_description", "benefits_json", "usp_json", "usage_text", "ingredients_text", "warnings_text", "target_customer_text", "paste_anything_summary", "source_urls_json", "image_evidence_json", "package_notes", "size_or_volume", "product_form_factor", "packaging_description", "product_truth_lock", "claim_gate", "claim_risk_level", "claim_tokens_json", "allowed_claims_json", "blocked_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json", "confidence_score", "completeness_score", "readiness_status", "created_from_review_draft_id", "created_by", "approved_by", "approved_at", "supersedes_snapshot_id", "updated_at"},
    "product_intelligence_field_provenance": {"snapshot_id", "product_id", "field_name", "declared_value", "normalized_value", "source_type", "source_url", "source_lane", "evidence_kind", "extraction_method", "confidence_score", "verification_status", "claim_risk_flag", "reviewer_decision", "reviewer_note", "updated_at"},
    "product_intelligence_review_draft": {"product_id", "review_status", "product_description", "benefits_json", "usp_json", "usage_text", "ingredients_text", "warnings_text", "target_customer_text", "paste_anything_summary", "source_urls_json", "image_evidence_json", "package_notes", "size_or_volume", "product_form_factor", "packaging_description", "product_truth_lock", "claim_gate", "claim_risk_level", "claim_tokens_json", "allowed_claims_json", "blocked_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json", "confidence_score", "completeness_score", "readiness_status", "reviewer_note", "created_by", "reviewed_by", "approved_by", "approved_at", "rejected_by", "rejected_at", "updated_at"},
    "copy_generation_batch": {"product_id", "requested_count", "created_count", "deduped_count", "rejected_count", "source", "provider_lane", "provider_model", "updated_at"},
    "avatar_product_fit": {"avatar_code", "product_category", "fit_score", "suitability_notes", "updated_at"},
    "product_intelligence_review_field_provenance": {"draft_id", "product_id", "field_name", "declared_value", "normalized_value", "source_type", "source_url", "source_lane", "evidence_kind", "extraction_method", "confidence_score", "verification_status", "claim_risk_flag", "reviewer_decision", "reviewer_note", "updated_at"},
    "extend_lineage": {"workspace_generation_package_id", "project_id", "scene_id", "block_index", "block_position", "parent_operation_id", "parent_primary_media_id", "child_operation_id", "child_primary_media_id", "child_workflow_id", "batch_id", "model_key", "aspect_ratio", "start_frame_index", "end_frame_index", "continuation_prompt_hash", "idempotency_key", "polling_state", "retry_attempt", "output_url", "error_code", "error_message", "updated_at", "completed_at"},
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
async def get_product_by_fastmoss_reference_id(reference_id: str):
    """Return the canonical product row committed from a FastMoss reference, if
    any. Enables reference_id -> canonical fallback when a queue row is missing
    or stale. Prefers an active (non-archived) row."""
    if not reference_id:
        return None
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product WHERE fastmoss_reference_id=? "
        "ORDER BY CASE WHEN COALESCE(lifecycle_status,'ACTIVE')='ACTIVE' THEN 0 ELSE 1 END, "
        "created_at DESC LIMIT 1",
        (reference_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None
async def update_product(pid: str, **kw): return await _update("product", "id", pid, **kw)
async def delete_product(pid: str): return await _delete("product", "id", pid)


async def create_product_intelligence_snapshot(product_id: str, version: int, status: str, **kw) -> dict:
    db = await get_db()
    snapshot_id, now = _uuid(), _now()
    cols = ["snapshot_id", "product_id", "version", "status", "created_at", "updated_at"]
    vals = [snapshot_id, product_id, version, status, now, now]
    allowed = _COLUMNS["product_intelligence_snapshot"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO product_intelligence_snapshot ({col_str}) VALUES ({placeholders})",
            vals,
        )
        await db.commit()
    return await _get_with_db(db, "product_intelligence_snapshot", "snapshot_id", snapshot_id)


async def get_product_intelligence_snapshot(snapshot_id: str):
    return await _get("product_intelligence_snapshot", "snapshot_id", snapshot_id)


async def list_product_intelligence_snapshots(
    *,
    product_id: str,
    status: str | None = None,
    limit: int | None = 20,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM product_intelligence_snapshot WHERE product_id=?"
    params: list = [product_id]
    if status:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY version DESC, created_at DESC, snapshot_id DESC"
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def get_latest_approved_product_intelligence_snapshot(product_id: str) -> Optional[dict]:
    db = await get_db()
    cur = await db.execute(
        """
        SELECT *
        FROM product_intelligence_snapshot
        WHERE product_id=? AND status='APPROVED'
        ORDER BY version DESC, approved_at DESC, created_at DESC, snapshot_id DESC
        LIMIT 1
        """,
        (product_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def create_product_intelligence_field_provenance(
    snapshot_id: str,
    product_id: str,
    field_name: str,
    source_type: str,
    evidence_kind: str,
    extraction_method: str,
    verification_status: str,
    **kw,
) -> dict:
    db = await get_db()
    provenance_id, now = _uuid(), _now()
    cols = [
        "provenance_id",
        "snapshot_id",
        "product_id",
        "field_name",
        "source_type",
        "evidence_kind",
        "extraction_method",
        "verification_status",
        "created_at",
        "updated_at",
    ]
    vals = [
        provenance_id,
        snapshot_id,
        product_id,
        field_name,
        source_type,
        evidence_kind,
        extraction_method,
        verification_status,
        now,
        now,
    ]
    allowed = _COLUMNS["product_intelligence_field_provenance"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO product_intelligence_field_provenance ({col_str}) VALUES ({placeholders})",
            vals,
        )
        await db.commit()
    return await _get_with_db(
        db,
        "product_intelligence_field_provenance",
        "provenance_id",
        provenance_id,
    )


async def list_product_intelligence_field_provenance(
    *,
    snapshot_id: str | None = None,
    product_id: str | None = None,
    field_name: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    if not snapshot_id and not product_id:
        raise ValueError("SNAPSHOT_ID_OR_PRODUCT_ID_REQUIRED")
    db = await get_db()
    q = "SELECT * FROM product_intelligence_field_provenance WHERE 1=1"
    params: list = []
    if snapshot_id:
        q += " AND snapshot_id=?"
        params.append(snapshot_id)
    if product_id:
        q += " AND product_id=?"
        params.append(product_id)
    if field_name:
        q += " AND field_name=?"
        params.append(field_name)
    q += " ORDER BY created_at DESC, provenance_id DESC"
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def create_product_intelligence_review_draft(product_id: str, review_status: str, **kw) -> dict:
    db = await get_db()
    draft_id, now = _uuid(), _now()
    cols = ["draft_id", "product_id", "review_status", "created_at", "updated_at"]
    vals = [draft_id, product_id, review_status, now, now]
    allowed = _COLUMNS["product_intelligence_review_draft"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO product_intelligence_review_draft ({col_str}) VALUES ({placeholders})",
            vals,
        )
        await db.commit()
    return await _get_with_db(db, "product_intelligence_review_draft", "draft_id", draft_id)


async def get_product_intelligence_review_draft(draft_id: str):
    return await _get("product_intelligence_review_draft", "draft_id", draft_id)


async def update_product_intelligence_review_draft(draft_id: str, **kw):
    return await _update("product_intelligence_review_draft", "draft_id", draft_id, **kw)


async def list_product_intelligence_review_drafts(
    *,
    product_id: str,
    limit: int | None = 20,
) -> list[dict]:
    db = await get_db()
    q = """
        SELECT *
        FROM product_intelligence_review_draft
        WHERE product_id=?
        ORDER BY updated_at DESC, created_at DESC, draft_id DESC
    """
    params: list[Any] = [product_id]
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def create_product_intelligence_review_field_provenance(
    draft_id: str,
    product_id: str,
    field_name: str,
    source_type: str,
    evidence_kind: str,
    extraction_method: str,
    verification_status: str,
    **kw,
) -> dict:
    db = await get_db()
    review_provenance_id, now = _uuid(), _now()
    cols = [
        "review_provenance_id",
        "draft_id",
        "product_id",
        "field_name",
        "source_type",
        "evidence_kind",
        "extraction_method",
        "verification_status",
        "created_at",
        "updated_at",
    ]
    vals = [
        review_provenance_id,
        draft_id,
        product_id,
        field_name,
        source_type,
        evidence_kind,
        extraction_method,
        verification_status,
        now,
        now,
    ]
    allowed = _COLUMNS["product_intelligence_review_field_provenance"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO product_intelligence_review_field_provenance ({col_str}) VALUES ({placeholders})",
            vals,
        )
        await db.commit()
    return await _get_with_db(
        db,
        "product_intelligence_review_field_provenance",
        "review_provenance_id",
        review_provenance_id,
    )


async def list_product_intelligence_review_field_provenance(
    *,
    draft_id: str | None = None,
    product_id: str | None = None,
    field_name: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    if not draft_id and not product_id:
        raise ValueError("DRAFT_ID_OR_PRODUCT_ID_REQUIRED")
    db = await get_db()
    q = "SELECT * FROM product_intelligence_review_field_provenance WHERE 1=1"
    params: list[Any] = []
    if draft_id:
        q += " AND draft_id=?"
        params.append(draft_id)
    if product_id:
        q += " AND product_id=?"
        params.append(product_id)
    if field_name:
        q += " AND field_name=?"
        params.append(field_name)
    q += " ORDER BY created_at DESC, review_provenance_id DESC"
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def delete_product_intelligence_review_field_provenance_for_draft(draft_id: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM product_intelligence_review_field_provenance WHERE draft_id=?",
            (draft_id,),
        )
        await db.commit()


# ==================================================================
# Copy Intelligence Phase 1 = CRUD foundation for batch ledger,
# avatar-product fit, and copy usage/fatigue/similarity fields.
# ==================================================================

# --- copy_generation_batch ---

async def create_copy_generation_batch(**kw) -> dict:
    db = await get_db()
    bid, now = _uuid(), _now()
    cols = ["batch_id", "created_at", "updated_at"]
    vals = [bid, now, now]
    allowed = _COLUMNS["copy_generation_batch"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO copy_generation_batch ({col_str}) VALUES ({placeholders})",
            vals,
        )
        await db.commit()
    return await _get_with_db(db, "copy_generation_batch", "batch_id", bid)


async def list_copy_generation_batches(
    product_id: str | None = None, limit: int = 50
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM copy_generation_batch"
    params: list[object] = []
    if product_id:
        q += " WHERE product_id=?"
        params.append(product_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


# --- avatar_product_fit ---

async def upsert_avatar_product_fit(**kw) -> dict:
    db = await get_db()
    now = _now()
    avatar_code = kw.get("avatar_code", "")
    product_category = kw.get("product_category", "")
    if not avatar_code or not product_category:
        raise ValueError("avatar_code and product_category are required")
    allowed = _COLUMNS["avatar_product_fit"]
    cols: list[str] = []
    vals: list[object] = []
    for k, v in kw.items():
        if k in allowed and k not in ("avatar_code", "product_category"):
            cols.append(k)
            vals.append(v)
    if "updated_at" not in cols:
        cols.append("updated_at")
        vals.append(now)
    set_clause = ", ".join(f"{c}=?" for c in cols)
    set_vals = list(vals)  # same values for DO UPDATE SET
    async with _db_lock:
        await db.execute(
            f"INSERT INTO avatar_product_fit (avatar_code, product_category, {', '.join(cols)}) "
            f"VALUES (?, ?, {', '.join(['?'] * len(cols))}) "
            f"ON CONFLICT(avatar_code, product_category) DO UPDATE SET {set_clause}",
            [avatar_code, product_category] + vals + set_vals,
        )
        await db.commit()
    cur = await db.execute(
        "SELECT * FROM avatar_product_fit WHERE avatar_code=? AND product_category=?",
        (avatar_code, product_category),
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


async def list_avatar_product_fits(
    avatar_code: str | None = None,
    product_category: str | None = None,
    limit: int = 200,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM avatar_product_fit WHERE 1=1"
    params: list[object] = []
    if avatar_code:
        q += " AND avatar_code=?"
        params.append(avatar_code)
    if product_category:
        q += " AND product_category=?"
        params.append(product_category)
    q += " ORDER BY fit_score DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


# --- Copy Set (Copy Strategy Studio Phase 1) ---

async def create_copy_set(product_id: str, **kw) -> dict:
    """Insert a Copy Set row for a product. product_id is immutable and set here;
    all other columns come through the whitelist so unknown keys are ignored."""
    db = await get_db()
    csid, now = _uuid(), _now()
    cols = ["copy_set_id", "product_id", "created_at", "updated_at"]
    vals = [csid, product_id, now, now]
    allowed = _COLUMNS["copy_set"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(f"INSERT INTO copy_set ({col_str}) VALUES ({placeholders})", vals)
        await db.commit()
    return await _get_with_db(db, "copy_set", "copy_set_id", csid)

async def get_copy_set(copy_set_id: str): return await _get("copy_set", "copy_set_id", copy_set_id)
async def update_copy_set(copy_set_id: str, **kw): return await _update("copy_set", "copy_set_id", copy_set_id, **kw)
async def delete_copy_set(copy_set_id: str): return await _delete("copy_set", "copy_set_id", copy_set_id)

async def list_copy_sets_for_product(product_id: str) -> list:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_set WHERE product_id=? ORDER BY created_at DESC", (product_id,)
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]

async def find_copy_set_by_dedupe_key(dedupe_key: str) -> Optional[dict]:
    if not dedupe_key:
        return None
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_set WHERE dedupe_key=? ORDER BY created_at ASC LIMIT 1",
        (dedupe_key,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


# --- COPYWRITING HUB review-only seed ledger ---

async def create_copy_intelligence_seed(**kw) -> dict:
    """Insert one immutable source row, idempotent on its provenance fingerprint.

    This never writes the product table or copy_set. A repeated import returns
    the original record, preserving the first audit timestamp.
    """
    fingerprint = str(kw.get("source_fingerprint") or "").strip()
    if not fingerprint:
        raise ValueError("source_fingerprint is required")
    db = await get_db()
    existing = await db.execute(
        "SELECT * FROM copy_intelligence_seed WHERE source_fingerprint=?", (fingerprint,)
    )
    row = await existing.fetchone()
    if row:
        return dict(row)
    seed_id, now = _uuid(), _now()
    allowed = _COLUMNS["copy_intelligence_seed"]
    cols = ["seed_id", "created_at", "updated_at"]
    vals: list[object] = [seed_id, now, now]
    for key, value in kw.items():
        if key in allowed and key not in cols:
            cols.append(key)
            vals.append(value)
    async with _db_lock:
        await db.execute(
            f"INSERT INTO copy_intelligence_seed ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
            vals,
        )
        await db.commit()
    return await _get_with_db(db, "copy_intelligence_seed", "seed_id", seed_id)


async def list_copy_intelligence_seeds(
    *, confidence: str | None = None, status: str | None = None,
    search: str | None = None, limit: int = 100,
) -> tuple[int, list[dict]]:
    """Read review-only ledger rows; this helper never writes any table."""
    db = await get_db()
    clauses: list[str] = []
    params: list[object] = []
    if confidence:
        clauses.append("confidence=?")
        params.append(confidence)
    if status:
        clauses.append("status=?")
        params.append(status)
    if search:
        clauses.append(
            "(LOWER(source_product_name) LIKE ? OR LOWER(COALESCE(target_avatar, '')) LIKE ? "
            "OR LOWER(COALESCE(hook_script, '')) LIKE ?)"
        )
        needle = f"%{search.lower()}%"
        params.extend((needle, needle, needle))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total_cursor = await db.execute(
        f"SELECT COUNT(*) FROM copy_intelligence_seed{where}", params
    )
    total = int((await total_cursor.fetchone())[0])
    rows_cursor = await db.execute(
        "SELECT * FROM copy_intelligence_seed"
        f"{where} ORDER BY source_workbook, source_sheet, source_row LIMIT ?",
        [*params, limit],
    )
    return total, [dict(row) for row in await rows_cursor.fetchall()]


# --- Poster Copy Set + Poster Deliverable (POSTER_BUILDER_V2) ---
# Poster copy is a SEPARATE domain from the video copy_set table; these helpers
# never touch copy_set so poster rows can never enter video selection.

async def create_poster_copy_set(product_id: str, **kw) -> dict:
    db = await get_db()
    pid, now = _uuid(), _now()
    cols = ["poster_copy_set_id", "product_id", "created_at", "updated_at"]
    vals = [pid, product_id, now, now]
    allowed = _COLUMNS["poster_copy_set"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO poster_copy_set ({col_str}) VALUES ({placeholders})", vals
        )
        await db.commit()
    return await _get_with_db(db, "poster_copy_set", "poster_copy_set_id", pid)

async def create_poster_copy_set_version(
    product_id: str, parent_poster_copy_set_id: str, parent_status: str, **kw
) -> dict:
    """Insert a child version AND mark the parent superseded in ONE transaction.

    If either statement fails (including a missing parent), both roll back —
    no partial child/parent state can ever persist.
    """
    db = await get_db()
    pid, now = _uuid(), _now()
    kw["parent_poster_copy_set_id"] = parent_poster_copy_set_id
    cols = ["poster_copy_set_id", "product_id", "created_at", "updated_at"]
    vals = [pid, product_id, now, now]
    allowed = _COLUMNS["poster_copy_set"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        try:
            await db.execute(
                f"INSERT INTO poster_copy_set ({col_str}) VALUES ({placeholders})", vals
            )
            cur = await db.execute(
                "UPDATE poster_copy_set SET status=?, updated_at=? "
                "WHERE poster_copy_set_id=? AND status='POSTER_COPY_APPROVED'",
                (parent_status, now, parent_poster_copy_set_id),
            )
            if cur.rowcount != 1:
                raise ValueError(
                    "parent poster_copy_set "
                    f"{parent_poster_copy_set_id} not found or not currently approved"
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return await _get_with_db(db, "poster_copy_set", "poster_copy_set_id", pid)

async def create_poster_copy_set_child_draft(
    product_id: str, parent_poster_copy_set_id: str, **kw
) -> dict:
    """Insert a DRAFT child cloned from a HISTORICAL parent WITHOUT mutating it.

    Used to fork a fresh editable version from a superseded copy set that a saved
    poster still references — the historical record (and the saved poster's
    provenance) is never touched. Unlike ``create_poster_copy_set_version`` there
    is NO parent status change.
    """
    db = await get_db()
    pid, now = _uuid(), _now()
    kw["parent_poster_copy_set_id"] = parent_poster_copy_set_id
    cols = ["poster_copy_set_id", "product_id", "created_at", "updated_at"]
    vals = [pid, product_id, now, now]
    allowed = _COLUMNS["poster_copy_set"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO poster_copy_set ({col_str}) VALUES ({placeholders})", vals
        )
        await db.commit()
    return await _get_with_db(db, "poster_copy_set", "poster_copy_set_id", pid)

async def get_poster_copy_set(poster_copy_set_id: str):
    return await _get("poster_copy_set", "poster_copy_set_id", poster_copy_set_id)

async def update_poster_copy_set(poster_copy_set_id: str, **kw):
    return await _update("poster_copy_set", "poster_copy_set_id", poster_copy_set_id, **kw)

async def list_poster_copy_sets_for_product(product_id: str) -> list:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM poster_copy_set WHERE product_id=? AND archived=0 "
        "ORDER BY created_at DESC",
        (product_id,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]

async def create_poster_deliverable(product_id: str, **kw) -> dict:
    db = await get_db()
    did, now = _uuid(), _now()
    cols = ["poster_deliverable_id", "product_id", "created_at", "updated_at"]
    vals = [did, product_id, now, now]
    allowed = _COLUMNS["poster_deliverable"]
    for k, v in kw.items():
        if k in allowed and k not in cols:
            cols.append(k)
            vals.append(v)
    col_str = ",".join(cols)
    placeholders = ",".join(["?"] * len(cols))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO poster_deliverable ({col_str}) VALUES ({placeholders})", vals
        )
        await db.commit()
    return await _get_with_db(db, "poster_deliverable", "poster_deliverable_id", did)

async def get_poster_deliverable(poster_deliverable_id: str):
    return await _get("poster_deliverable", "poster_deliverable_id", poster_deliverable_id)

async def get_poster_deliverable_by_asset(creative_asset_id: str):
    """Reverse lookup: Creative Library asset → its saved poster deliverable."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM poster_deliverable WHERE creative_asset_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (creative_asset_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None

async def update_poster_deliverable(poster_deliverable_id: str, **kw):
    return await _update("poster_deliverable", "poster_deliverable_id", poster_deliverable_id, **kw)

async def list_poster_deliverables_for_product(product_id: str, limit: int = 50) -> list:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM poster_deliverable WHERE product_id=? "
        "ORDER BY created_at DESC LIMIT ?",
        (product_id, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]

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


async def get_workspace_execution_package(workspace_execution_package_id: str) -> dict | None:
    """Load one persisted execution package — the durable-job plan's authority source
    (compiled product-truth prompt, fingerprint, model/aspect, resolved product asset)."""
    db = await get_db()
    return await _get_with_db(
        db, "workspace_execution_package", "workspace_execution_package_id",
        workspace_execution_package_id)


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
    asset_subtype: str | None = None,
    generation_recipe_id: str | None = None,
    source_character_asset_id: str | None = None,
    source_scene_asset_id: str | None = None,
    source_style_asset_id: str | None = None,
    contains_rendered_text: bool = False,
    approved_for_video_support: bool = False,
    approved_for_poster: bool = False,
    product_truth_status: str | None = None,
    identity_lock_status: str | None = None,
    scale_truth_status: str | None = None,
    claim_safety_status: str | None = None,
    review_status: str = "PENDING_REVIEW",
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
                source_prompt_package_snapshot_id,
                asset_subtype, generation_recipe_id, source_character_asset_id,
                source_scene_asset_id, source_style_asset_id, contains_rendered_text,
                approved_for_video_support, approved_for_poster, product_truth_status,
                identity_lock_status, scale_truth_status, claim_safety_status, review_status,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                asset_subtype,
                generation_recipe_id,
                source_character_asset_id,
                source_scene_asset_id,
                source_style_asset_id,
                int(bool(contains_rendered_text)),
                int(bool(approved_for_video_support)),
                int(bool(approved_for_poster)),
                product_truth_status,
                identity_lock_status,
                scale_truth_status,
                claim_safety_status,
                review_status,
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


# ─── Social Copy Packages ─────────────────────────────────────
# Platform-specific caption/comment copy linked to a generated artifact
# (artifact_media_id). Authored on the generator pages, approved, then
# prefilled into Postiz Publish. No hard FK — copy outlives 48h artifacts.
async def create_social_copy_package(
    package_id: str,
    *,
    artifact_media_id: str,
    platform: str,
    source_mode: str | None = None,
    caption: str = "",
    first_comment: str = "",
    hashtags_json: str = "[]",
    call_to_action: str = "",
    tone: str = "",
    language: str = "ms",
    status: str = "DRAFT",
    compliance_status: str = "OK",
    blockers_json: str = "[]",
    warnings_json: str = "[]",
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO social_copy_package
               (package_id, artifact_media_id, source_mode, platform, caption,
                first_comment, hashtags_json, call_to_action, tone, language,
                status, compliance_status, blockers_json, warnings_json,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (package_id, artifact_media_id, source_mode, platform, caption,
             first_comment, hashtags_json, call_to_action, tone, language,
             status, compliance_status, blockers_json, warnings_json, now, now),
        )
        await db.commit()
    return await _get_with_db(db, "social_copy_package", "package_id", package_id)


async def get_social_copy_package(package_id: str) -> dict | None:
    return await _get("social_copy_package", "package_id", package_id)


async def update_social_copy_package(package_id: str, **kwargs) -> dict | None:
    return await _update("social_copy_package", "package_id", package_id, **kwargs)


async def list_social_copy_packages(
    artifact_media_id: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = await get_db()
    query = "SELECT * FROM social_copy_package WHERE 1=1"
    params: list = []
    if artifact_media_id:
        query += " AND artifact_media_id=?"
        params.append(artifact_media_id)
    if platform:
        query += " AND platform=?"
        params.append(platform)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(query, params)
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


async def find_products_by_tiktok_product_id(tiktok_product_id: str) -> list[dict]:
    """Products whose TikTok URL carries this product id (duplicate identity
    check — the id is the strongest same-product signal)."""
    tid = str(tiktok_product_id or "").strip()
    if not tid.isdigit():
        return []
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product WHERE tiktok_product_url LIKE ?", (f"%{tid}%",))
    return [dict(r) for r in await cur.fetchall()]


async def list_all_bulk_queue_rows() -> list[dict]:
    """Full unpaginated queue scan (duplicate audit / purge)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM fastmoss_bulk_draft_status ORDER BY created_at ASC")
    return [dict(r) for r in await cur.fetchall()]


async def delete_bulk_queue_rows(reference_ids: list[str]) -> int:
    """Delete STAGING queue rows (duplicate purge). Callers must only pass
    never-drafted rows — drafted/approved rows are history and stay."""
    if not reference_ids:
        return 0
    db = await get_db()
    deleted = 0
    async with _db_lock:
        for reference_id in reference_ids:
            cur = await db.execute(
                "DELETE FROM fastmoss_bulk_draft_status "
                "WHERE reference_id=? AND draft_id IS NULL",
                (reference_id,))
            deleted += cur.rowcount
        await db.commit()
    return deleted


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


async def list_artifact_scene_ids(project_id: str) -> list[str]:
    """Distinct scene ids we have durable artifact evidence for in a project."""
    db = await get_db()
    cur = await db.execute(
        """SELECT DISTINCT scene_id FROM generated_artifact
           WHERE project_id=? AND scene_id IS NOT NULL AND scene_id!=''
           ORDER BY rowid DESC""",
        (project_id,),
    )
    rows = await cur.fetchall()
    return [r[0] for r in rows]


async def create_video_production_job(job_id: str, *, project_id: str = None,
                                      scene_id: str = None,
                                      requested_duration_seconds: int = None,
                                      status: str = "PREPARING",
                                      initial_media_id: str = None,
                                      segment_media_ids_json: str = None,
                                      product_id: str = None,
                                      product_name: str = None) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """INSERT INTO video_production_job
               (job_id, project_id, scene_id, requested_duration_seconds, status,
                initial_media_id, segment_media_ids_json, product_id, product_name)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, project_id, scene_id, requested_duration_seconds, status,
             initial_media_id, segment_media_ids_json, product_id, product_name),
        )
        await db.commit()


async def get_video_production_job_by_logical_key(logical_job_key: str) -> dict | None:
    """One job per logical production intent (durable identity, create-before-initial)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM video_production_job WHERE logical_job_key=?", (logical_job_key,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def create_video_production_job_full(job_id: str, *, logical_job_key: str,
                                           status: str = "CREATED", **fields) -> None:
    """Create the lifecycle-owning job BEFORE any credit-consuming operation.

    Idempotent on logical_job_key via INSERT OR IGNORE — a racing duplicate create
    for the same production intent is a no-op (callers then read the existing row).
    """
    cols = {"job_id": job_id, "logical_job_key": logical_job_key, "status": status}
    allowed = {
        "project_id", "scene_id", "requested_duration_seconds", "product_id",
        "product_name", "execution_package_id", "approved_asset_id",
        "approved_asset_sha256", "engine", "model", "aspect_ratio",
        "plan_fingerprint", "whole_plan_json", "initial_media_id",
        "segment_media_ids_json",
        # production authority persisted at plan time (create-before-initial)
        "initial_mode", "initial_prompt_text", "initial_prompt_fingerprint",
        "initial_asset_media_id", "initial_reference_media_ids_json",
        "initial_source_mode",
        "continuation_prompts_json",
    }
    cols.update({k: v for k, v in fields.items() if k in allowed})
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"INSERT OR IGNORE INTO video_production_job ({names}) VALUES ({marks})",
            tuple(cols.values()))
        await db.commit()


async def update_video_production_job_full(job_id: str, **fields) -> None:
    """Update any lifecycle-owner field (superset of update_video_production_job)."""
    allowed = {
        "status", "error_code", "project_id", "scene_id", "initial_media_id",
        "segment_media_ids_json", "extend_lineage_ids_json", "final_concat_job_name",
        "final_media_id", "final_local_path", "final_sha256", "final_duration_s",
        "plan_fingerprint", "whole_plan_json", "authorization_token",
        "authorization_expires_at", "initial_operation_id", "initial_workflow_id",
        "extend_child_operation_id", "extend_child_workflow_id", "stage_state_json",
        "initial_mode", "initial_prompt_text", "initial_prompt_fingerprint",
        "initial_asset_media_id", "initial_reference_media_ids_json",
        "initial_source_mode", "initial_correlation_json",
        "continuation_prompts_json",
        "authorization_id", "authorization_issued_at", "authorization_consumed_at",
        "authorization_consumed_by_job_id", "authorization_consumed_plan_fingerprint",
        "initial_lane_job_id", "initial_lane_project_id",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in updates)
    async with _db_lock:
        await db.execute(
            f"UPDATE video_production_job SET {sets}, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE job_id=?",
            (*updates.values(), job_id))
        await db.commit()


async def consume_job_authorization(job_id: str, token: str, *,
                                    plan_fingerprint: str, now: str) -> dict:
    """Atomically CONSUME a job's single-use authorization at start.

    Returns {"consumed": bool, "already": bool, "row": <job>}. consumed=True means
    THIS call won the single-use race (may enqueue the driver); already=True means
    the token was already consumed for this job (a replayed start — return status,
    never a second job or side effect). A token mismatch returns consumed=False,
    already=False (caller rejects: the plan was re-authorized/rotated).
    """
    db = await get_db()
    async with _db_lock:
        cur = await db.execute(
            "UPDATE video_production_job SET authorization_consumed_at=?, "
            "authorization_consumed_by_job_id=?, authorization_consumed_plan_fingerprint=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            "WHERE job_id=? AND authorization_token=? AND authorization_consumed_at IS NULL",
            (now, job_id, plan_fingerprint, job_id, token))
        await db.commit()
        consumed = cur.rowcount == 1
        r = await db.execute(
            "SELECT * FROM video_production_job WHERE job_id=?", (job_id,))
        row = await r.fetchone()
    row = dict(row) if row else None
    already = bool(
        not consumed and row and row.get("authorization_consumed_at")
        and row.get("authorization_token") == token)
    return {"consumed": consumed, "already": already, "row": row}


# ── DB-level side-effect idempotency (initial / extend / concat) ─────────────
async def reserve_video_job_side_effect(idempotency_key: str, *, job_id: str,
                                        stage: str) -> dict:
    """Atomically reserve a credit-consuming side effect.

    Returns {"reserved": bool, "row": <existing-or-new-row>}. reserved=True means
    THIS caller won the race and may submit; reserved=False means a row already
    existed (another tab/process/attempt) and the caller must RESUME/return by the
    row's structured state — never a second submit.
    """
    db = await get_db()
    async with _db_lock:
        cur = await db.execute(
            "INSERT OR IGNORE INTO video_job_side_effect "
            "(idempotency_key, job_id, stage, submission_state, retry_safety) "
            "VALUES (?,?,?,'NOT_ATTEMPTED','RESUME_ONLY')",
            (idempotency_key, job_id, stage))
        await db.commit()
        reserved = cur.rowcount == 1
        row = await db.execute(
            "SELECT * FROM video_job_side_effect WHERE idempotency_key=?",
            (idempotency_key,))
        row = await row.fetchone()
    return {"reserved": reserved, "row": dict(row) if row else None}


async def list_video_job_side_effects(job_id: str) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM video_job_side_effect WHERE job_id=? ORDER BY created_at", (job_id,))
    return [dict(r) for r in await cur.fetchall()]


async def get_video_job_side_effect(idempotency_key: str) -> dict | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM video_job_side_effect WHERE idempotency_key=?", (idempotency_key,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def update_video_job_side_effect(idempotency_key: str, **fields) -> None:
    allowed = {"submission_state", "credit_state", "retry_safety", "operation_ref",
               "effective_submit_count", "detail",
               "credit_balance_before", "credit_balance_after"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in updates)
    async with _db_lock:
        await db.execute(
            f"UPDATE video_job_side_effect SET {sets}, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE idempotency_key=?",
            (*updates.values(), idempotency_key))
        await db.commit()


async def increment_side_effect_submit_count(idempotency_key: str) -> int:
    """Atomically bump + return the effective submit count (proves exactly-once)."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE video_job_side_effect SET effective_submit_count = "
            "effective_submit_count + 1, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            "WHERE idempotency_key=?", (idempotency_key,))
        await db.commit()
        cur = await db.execute(
            "SELECT effective_submit_count FROM video_job_side_effect WHERE idempotency_key=?",
            (idempotency_key,))
        r = await cur.fetchone()
    return int(r[0]) if r else 0


async def list_non_terminal_authorized_jobs() -> list[dict]:
    """In-flight AUTHORIZED jobs to resume on process restart (durable worker sweep)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM video_production_job WHERE status NOT IN "
        "('CREATED','COMPLETE') AND status NOT LIKE '%FAILED%' "
        "AND authorization_token IS NOT NULL ORDER BY created_at")
    return [dict(r) for r in await cur.fetchall()]


async def get_video_production_job(job_id: str) -> dict | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM video_production_job WHERE job_id=?", (job_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_video_production_jobs(limit: int = 20) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM video_production_job ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (int(limit),))
    return [dict(r) for r in await cur.fetchall()]


async def update_video_production_job(job_id: str, **fields) -> None:
    """Update allowed job fields (status transitions + final identities)."""
    allowed = {"status", "error_code", "scene_id", "initial_media_id",
               "segment_media_ids_json", "extend_lineage_ids_json",
               "final_concat_job_name", "final_media_id", "final_local_path",
               "final_sha256", "final_duration_s"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in updates)
    async with _db_lock:
        await db.execute(
            f"UPDATE video_production_job SET {sets}, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE job_id=?",
            (*updates.values(), job_id),
        )
        await db.commit()


async def set_artifact_scene(media_id: str, scene_id: str) -> None:
    """Persist durable scene evidence for a generated clip."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE generated_artifact SET scene_id=? WHERE media_id=?",
            (scene_id, media_id))
        await db.commit()


async def list_known_media_ids() -> set:
    """Every Flow media id BOSMAX has EVER produced, retrieved, or lineaged.

    This is the DURABLE retrieval-exclusion set (SEV-0 fix, live incident
    g_09ced57d5d4b): a freshly generated clip mints a brand-new Flow id, so it can
    NEVER be in here — while any clip we already know (old test videos, previous
    runs, extend parents/children) always is. DOM snapshots under-report in a
    history-laden project (the editor lists more OLD media after each tab reload
    than the pre-poll snapshot saw), so DOM-diff alone must never be the only
    freshness authority. Per-source fail-soft: one missing table never empties
    the whole set.
    """
    db = await get_db()
    ids: set = set()
    for query in (
        "SELECT media_id FROM generated_artifact WHERE media_id IS NOT NULL",
        "SELECT media_id FROM generation_result WHERE media_id IS NOT NULL",
        "SELECT parent_operation_id FROM extend_lineage WHERE parent_operation_id IS NOT NULL",
        "SELECT child_operation_id FROM extend_lineage WHERE child_operation_id IS NOT NULL",
        "SELECT parent_primary_media_id FROM extend_lineage WHERE parent_primary_media_id IS NOT NULL",
        "SELECT child_primary_media_id FROM extend_lineage WHERE child_primary_media_id IS NOT NULL",
    ):
        try:
            cur = await db.execute(query)
            ids |= {row[0] for row in await cur.fetchall() if row[0]}
        except Exception:  # noqa: BLE001 — a missing legacy table must not empty the set
            continue
    return ids


async def list_extend_source_candidates(limit: int = 8) -> list[dict]:
    """Finished VIDEO clips usable as native-Extend parents, newest first.

    A generated clip's library media id IS its Flow operation id (captured
    contract), so each row here is a complete Extend parent candidate once its
    scene id is resolved. Joined with generation_result for operator-readable
    product context — no raw-id copying required in the normal workflow.
    """
    db = await get_db()
    cur = await db.execute(
        """SELECT ga.media_id, ga.job_id, ga.project_id, ga.created_at,
                  gr.product_id, gr.product_name, gr.request_id,
                  gr.workspace_generation_package_id
           FROM generated_artifact ga
           LEFT JOIN generation_result gr ON gr.media_id = ga.media_id
           WHERE ga.artifact_kind='video' AND ga.project_id IS NOT NULL
           ORDER BY ga.created_at DESC, ga.rowid DESC LIMIT ?""",
        (int(limit),),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_generated_artifact(media_id: str) -> dict:
    """Delete ONE artifact (DB row + local file) by Flow media id, immediately.
    Used when a registry profile is deleted so its temp reference image does not
    linger in the Library until the 48h retention sweep. Safe no-op if absent."""
    import os
    db = await get_db()
    cursor = await db.execute(
        "SELECT local_path FROM generated_artifact WHERE media_id=?", (media_id,))
    row = await cursor.fetchone()
    if row is None:
        return {"deleted": 0, "file_removed": False}
    local_path = row[0]
    file_removed = False
    if local_path:
        try:
            os.remove(local_path)
            file_removed = True
        except OSError:
            pass  # already gone — row cleanup below still applies
    async with _db_lock:
        await db.execute(
            "DELETE FROM generated_artifact WHERE media_id=?", (media_id,))
        await db.commit()
    return {"deleted": 1, "file_removed": file_removed}


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


# ── Generation Result (Results Hub durable deliverable record) ───────────────
# Durable, lightweight companion to `generated_artifact`. The heavy file is
# purged at 48h; THIS row survives so the prompt/settings/caption stay reachable
# (manual Flow fallback + social publishing). Keyed by Flow media_id.

async def insert_generation_result(
    media_id: str,
    *,
    job_id: str = None,
    request_id: str = None,
    mode: str = None,
    artifact_kind: str = "video",
    product_id: str = None,
    product_name: str = None,
    final_prompt_text: str = "",
    aspect_ratio: str = None,
    model_label: str = None,
    duration_s: int = None,
    count_setting: int = None,
    reference_media_ids: list = None,
    workspace_generation_package_id: str = None,
    project_id: str = None,
) -> None:
    """Persist a durable deliverable record for a finished generation. Idempotent
    on media_id; a re-write UPDATES the snapshot but PRESERVES the first
    created_at so Results ordering is stable. Never touched by the 48h purge."""
    import json as _json
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """INSERT INTO generation_result
               (media_id, job_id, request_id, mode, artifact_kind, product_id,
                product_name, final_prompt_text, aspect_ratio, model_label,
                duration_s, count_setting, reference_media_ids_json,
                workspace_generation_package_id, project_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(media_id) DO UPDATE SET
                 job_id=excluded.job_id, request_id=excluded.request_id,
                 mode=excluded.mode, artifact_kind=excluded.artifact_kind,
                 product_id=excluded.product_id, product_name=excluded.product_name,
                 final_prompt_text=excluded.final_prompt_text,
                 aspect_ratio=excluded.aspect_ratio, model_label=excluded.model_label,
                 duration_s=excluded.duration_s, count_setting=excluded.count_setting,
                 reference_media_ids_json=excluded.reference_media_ids_json,
                 workspace_generation_package_id=excluded.workspace_generation_package_id,
                 project_id=excluded.project_id""",
            (media_id, job_id, request_id, mode, artifact_kind, product_id,
             product_name, final_prompt_text or "", aspect_ratio, model_label,
             duration_s, count_setting, _json.dumps(reference_media_ids or []),
             workspace_generation_package_id, project_id, _now()),
        )
        await db.commit()


async def get_generation_result(media_id: str) -> dict | None:
    """Single durable deliverable record by Flow media id."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM generation_result WHERE media_id=?", (media_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_generation_results(limit: int = 60, mode: str = None,
                                  kind: str = None) -> list:
    """Newest-first durable deliverable records for the Results Hub."""
    db = await get_db()
    query = "SELECT * FROM generation_result"
    clauses, params = [], []
    if mode:
        clauses.append("mode=?")
        params.append(mode)
    if kind:
        clauses.append("artifact_kind=?")
        params.append(kind)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(query, params)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def caption_summary_for_media_ids(media_ids: list) -> dict:
    """One-query caption rollup: {media_id: {"count": n, "approved": m}} for the
    given artifacts. Lets the Results list show caption status without N+1."""
    ids = [m for m in (media_ids or []) if m]
    if not ids:
        return {}
    db = await get_db()
    placeholders = ",".join("?" for _ in ids)
    cur = await db.execute(
        f"""SELECT artifact_media_id AS mid,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END) AS approved
            FROM social_copy_package
            WHERE artifact_media_id IN ({placeholders})
            GROUP BY artifact_media_id""",
        ids,
    )
    rows = await cur.fetchall()
    return {
        r["mid"]: {"count": r["total"], "approved": r["approved"] or 0}
        for r in rows
    }


# ── Native Google Flow Extend LINEAGE (durable parent->child chain) ─────────
# Additive, durable per-block record. Parent/child OPERATION id and primaryMediaId
# are four separate columns (never collapsed). `idempotency_key` is UNIQUE so a
# duplicate block submission is rejected (EXTEND_DUPLICATE_SUBMISSION_BLOCKED).

async def insert_extend_lineage(
    extend_lineage_id: str,
    *,
    workspace_generation_package_id: str = None,
    project_id: str = None,
    scene_id: str = None,
    block_index: int = None,
    block_position: int = None,
    parent_operation_id: str = None,
    parent_primary_media_id: str = None,
    child_operation_id: str = None,
    child_primary_media_id: str = None,
    child_workflow_id: str = None,
    batch_id: str = None,
    model_key: str = None,
    aspect_ratio: str = None,
    start_frame_index: int = None,
    end_frame_index: int = None,
    continuation_prompt_hash: str = None,
    idempotency_key: str = None,
    polling_state: str = "NOT_STARTED",
) -> dict:
    """Create a durable extend-lineage row. Raises the underlying sqlite
    IntegrityError if idempotency_key already exists — callers map that to
    EXTEND_DUPLICATE_SUBMISSION_BLOCKED. Never touched by the 48h artifact purge."""
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO extend_lineage
               (extend_lineage_id, workspace_generation_package_id, project_id,
                scene_id, block_index, block_position, parent_operation_id,
                parent_primary_media_id, child_operation_id, child_primary_media_id,
                child_workflow_id, batch_id, model_key, aspect_ratio,
                start_frame_index, end_frame_index, continuation_prompt_hash,
                idempotency_key, polling_state, retry_attempt, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (extend_lineage_id, workspace_generation_package_id, project_id,
             scene_id, block_index, block_position, parent_operation_id,
             parent_primary_media_id, child_operation_id, child_primary_media_id,
             child_workflow_id, batch_id, model_key, aspect_ratio,
             start_frame_index, end_frame_index, continuation_prompt_hash,
             idempotency_key, polling_state, now, now),
        )
        await db.commit()
    return await _get("extend_lineage", "extend_lineage_id", extend_lineage_id)


async def update_extend_lineage(extend_lineage_id: str, **kwargs) -> Optional[dict]:
    """Whitelisted update (mirrors _update); auto-stamps updated_at."""
    return await _update("extend_lineage", "extend_lineage_id", extend_lineage_id, **kwargs)


async def get_extend_lineage(extend_lineage_id: str) -> Optional[dict]:
    return await _get("extend_lineage", "extend_lineage_id", extend_lineage_id)


async def get_extend_lineage_by_child(child_operation_id: str) -> Optional[dict]:
    """Lineage row whose child (block N output) has this operation/media id — the
    id that block N+1 binds as its videoInput.mediaId parent."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM extend_lineage WHERE child_operation_id=? "
        "ORDER BY created_at DESC LIMIT 1", (child_operation_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_extend_lineage_by_idempotency(idempotency_key: str) -> Optional[dict]:
    """Existing row for an idempotency key — the dedup lookup that blocks a
    duplicate credit-consuming submission before it is fired."""
    if not idempotency_key:
        return None
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM extend_lineage WHERE idempotency_key=?", (idempotency_key,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_extend_lineage(workspace_generation_package_id: str = None,
                              project_id: str = None) -> list:
    """Lineage rows for a package/project, ordered by block index (chain order)."""
    db = await get_db()
    query = "SELECT * FROM extend_lineage"
    clauses, params = [], []
    if workspace_generation_package_id:
        clauses.append("workspace_generation_package_id=?")
        params.append(workspace_generation_package_id)
    if project_id:
        clauses.append("project_id=?")
        params.append(project_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY block_index ASC, created_at ASC"
    cur = await db.execute(query, params)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Bulk generation orchestrator (Google Flow V1) ─────────────────────────


async def create_bulk_generation_run(
    bulk_run_id: str,
    *,
    kind: str,
    total_expected: int = 0,
    max_parallel_images: int = 2,
    max_parallel_videos: int = 1,
    confirm_credit_burn: bool = False,
    interval_min_seconds: int = 5,
    interval_max_seconds: int = 15,
    cooldown_after_n_jobs: int = 5,
    cooldown_seconds: int = 60,
    config_json: str = "{}",
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO bulk_generation_run
               (bulk_run_id, kind, status, total_expected, total_completed, total_failed,
                max_parallel_images, max_parallel_videos, confirm_credit_burn,
                interval_min_seconds, interval_max_seconds, cooldown_after_n_jobs,
                cooldown_seconds, error_log_json, config_json, created_at, updated_at)
               VALUES (?,?,?,?,0,0,?,?,?,?,?,?,?,'[]',?,?,?)""",
            (
                bulk_run_id,
                kind,
                "PENDING",
                total_expected,
                max_parallel_images,
                max_parallel_videos,
                1 if confirm_credit_burn else 0,
                interval_min_seconds,
                interval_max_seconds,
                cooldown_after_n_jobs,
                cooldown_seconds,
                config_json,
                now,
                now,
            ),
        )
        await db.commit()
    return await get_bulk_generation_run(bulk_run_id)


async def get_bulk_generation_run(bulk_run_id: str) -> Optional[dict]:
    return await _get("bulk_generation_run", "bulk_run_id", bulk_run_id)


async def update_bulk_generation_run(bulk_run_id: str, **kwargs) -> Optional[dict]:
    return await _update("bulk_generation_run", "bulk_run_id", bulk_run_id, **kwargs)


async def list_bulk_generation_runs(limit: int = 50) -> list[dict]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM bulk_generation_run ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def create_bulk_generation_item(
    bulk_item_id: str,
    *,
    bulk_run_id: str,
    item_type: str,
    source_ref: str,
    prompt_snapshot: str | None = None,
    payload_json: str = "{}",
    status: str = "QUEUED",
) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            """INSERT INTO bulk_generation_item
               (bulk_item_id, bulk_run_id, item_type, source_ref, prompt_snapshot,
                payload_json, status, retry_count, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,0,?,?)""",
            (
                bulk_item_id,
                bulk_run_id,
                item_type,
                source_ref,
                prompt_snapshot,
                payload_json,
                status,
                now,
                now,
            ),
        )
        await db.commit()
    return await get_bulk_generation_item(bulk_item_id)


async def get_bulk_generation_item(bulk_item_id: str) -> Optional[dict]:
    return await _get("bulk_generation_item", "bulk_item_id", bulk_item_id)


async def update_bulk_generation_item(bulk_item_id: str, **kwargs) -> Optional[dict]:
    return await _update("bulk_generation_item", "bulk_item_id", bulk_item_id, **kwargs)


async def list_bulk_generation_items(
    bulk_run_id: str,
    *,
    status: str | None = None,
    limit: int = 500,
) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM bulk_generation_item WHERE bulk_run_id=?"
    params: list = [bulk_run_id]
    if status:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY created_at ASC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def claim_next_bulk_item(
    bulk_run_id: str,
    *,
    from_status: str = "QUEUED",
    to_status: str = "SUBMITTED",
) -> Optional[dict]:
    db = await get_db()
    now = _now()
    async with _db_lock:
        cur = await db.execute(
            """SELECT bulk_item_id FROM bulk_generation_item
               WHERE bulk_run_id=? AND status=?
               ORDER BY created_at ASC LIMIT 1""",
            (bulk_run_id, from_status),
        )
        row = await cur.fetchone()
        if not row:
            return None
        item_id = row["bulk_item_id"]
        cur2 = await db.execute(
            """UPDATE bulk_generation_item SET status=?, updated_at=?
               WHERE bulk_item_id=? AND status=?""",
            (to_status, now, item_id, from_status),
        )
        if cur2.rowcount != 1:
            await db.commit()
            return None
        await db.commit()
    return await get_bulk_generation_item(item_id)


async def bulk_item_status_counts(bulk_run_id: str) -> dict[str, int]:
    db = await get_db()
    cur = await db.execute(
        """SELECT status, COUNT(*) AS n FROM bulk_generation_item
           WHERE bulk_run_id=? GROUP BY status""",
        (bulk_run_id,),
    )
    rows = await cur.fetchall()
    return {str(r["status"]): int(r["n"]) for r in rows}

