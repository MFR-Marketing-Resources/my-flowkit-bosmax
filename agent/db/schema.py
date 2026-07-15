"""SQLite schema — async via aiosqlite."""
import asyncio
import aiosqlite
import logging
from agent.config import DB_PATH

logger = logging.getLogger(__name__)

_db_connection: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS character (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT,  -- auto-generated from name via slugify()
    entity_type TEXT NOT NULL DEFAULT 'character' CHECK(entity_type IN ('character','location','creature','visual_asset','generic_troop','faction')),
    description TEXT,
    image_prompt TEXT,
    voice_description TEXT,  -- max ~30 words, e.g. "Deep gravelly voice with a warm laugh"
    reference_image_url TEXT,
    media_id TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS project (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    story       TEXT,
    thumbnail_url TEXT,
    language    TEXT NOT NULL DEFAULT 'en',
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED','DELETED')),
    user_paygate_tier TEXT NOT NULL DEFAULT 'PAYGATE_TIER_ONE',
    narrator_voice TEXT,
    narrator_ref_audio TEXT,
    material TEXT DEFAULT 'realistic',
    allow_music INTEGER NOT NULL DEFAULT 0,
    allow_voice INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS material (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    style_instruction TEXT NOT NULL,
    negative_prompt TEXT,
    scene_prefix TEXT,
    lighting    TEXT DEFAULT 'Studio lighting, highly detailed',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS project_character (
    project_id    TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    character_id  TEXT NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, character_id)
);

CREATE TABLE IF NOT EXISTS video (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    description   TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','PROCESSING','COMPLETED','FAILED')),
    vertical_url  TEXT,
    horizontal_url TEXT,
    thumbnail_url TEXT,
    duration      REAL,
    resolution    TEXT,
    orientation   TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    youtube_id    TEXT,
    privacy       TEXT NOT NULL DEFAULT 'unlisted',
    tags          TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS scene (
    id              TEXT PRIMARY KEY,
    video_id        TEXT NOT NULL REFERENCES video(id) ON DELETE CASCADE,
    display_order   INTEGER NOT NULL DEFAULT 0,
    prompt          TEXT,
    image_prompt    TEXT,
    video_prompt    TEXT,
    character_names TEXT,  -- JSON array of reference entity names (characters, locations, assets)

    parent_scene_id TEXT REFERENCES scene(id) ON DELETE SET NULL,
    chain_type      TEXT NOT NULL DEFAULT 'ROOT' CHECK(chain_type IN ('ROOT','CONTINUATION','INSERT')),
    source          TEXT NOT NULL DEFAULT 'root' CHECK(source IN ('root','user','system')),

    -- Vertical orientation
    vertical_image_url          TEXT,
    vertical_image_media_id TEXT,
    vertical_image_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(vertical_image_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    vertical_video_url          TEXT,
    vertical_video_media_id TEXT,
    vertical_video_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(vertical_video_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    vertical_upscale_url        TEXT,
    vertical_upscale_media_id TEXT,
    vertical_upscale_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK(vertical_upscale_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),

    -- Horizontal orientation
    horizontal_image_url          TEXT,
    horizontal_image_media_id TEXT,
    horizontal_image_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(horizontal_image_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    horizontal_video_url          TEXT,
    horizontal_video_media_id TEXT,
    horizontal_video_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK(horizontal_video_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    horizontal_upscale_url        TEXT,
    horizontal_upscale_media_id TEXT,
    horizontal_upscale_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK(horizontal_upscale_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),

    -- Chain source (for continuation scenes)
    vertical_end_scene_media_id   TEXT,
    horizontal_end_scene_media_id TEXT,

    -- Trim
    trim_start  REAL,
    trim_end    REAL,
    duration    REAL,

    -- Transition (chain scenes only: describes motion from this scene to next)
    transition_prompt TEXT,

    -- Narration
    narrator_text TEXT,

    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS request (
    id            TEXT PRIMARY KEY,
    project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
    video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
    scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
    character_id  TEXT REFERENCES character(id) ON DELETE CASCADE,
    type          TEXT NOT NULL CHECK(type IN ('GENERATE_IMAGE','REGENERATE_IMAGE','EDIT_IMAGE','GENERATE_VIDEO','REGENERATE_VIDEO','GENERATE_VIDEO_REFS','TRUE_F2V','UPSCALE_VIDEO','GENERATE_CHARACTER_IMAGE','REGENERATE_CHARACTER_IMAGE','EDIT_CHARACTER_IMAGE','MANUAL_FLOW_JOB','TELEMETRY_SELF_TEST')),
    orientation   TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','WAITING_FLOW','FLOW_RUNNING','COMPLETED','FAILED')),
    request_id    TEXT,   -- external operation ID
    media_id  TEXT,
    output_url    TEXT,
    error_message TEXT,
    automation_report TEXT,   -- JSON report from Chrome extension executor
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    edit_prompt   TEXT,    -- prompt for EDIT_IMAGE requests
    source_media_id TEXT,  -- source image media_id for EDIT_IMAGE requests
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS request_telemetry (
    request_id    TEXT PRIMARY KEY REFERENCES request(id) ON DELETE CASCADE,
    project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
    video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
    scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
    product_id    TEXT REFERENCES product(id) ON DELETE SET NULL,
    request_type  TEXT NOT NULL,
    mode          TEXT,
    prompt_package_snapshot_id TEXT,
    workspace_execution_package_id TEXT,
    workspace_generation_package_id TEXT,
    prompt_fingerprint TEXT,
    asset_fingerprints TEXT,
    request_lineage_payload TEXT,
    git_sha       TEXT,
    background_build_id TEXT,
    content_build_id TEXT,
    last_checkpoint TEXT,
    runtime_ready INTEGER DEFAULT 0,
    build_match   INTEGER DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'QUEUED',
    google_flow_stage TEXT,
    extension_stage   TEXT,
    worker_stage      TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    queued_at         TEXT,
    started_at        TEXT,
    last_heartbeat_at TEXT,
    completed_at      TEXT,
    failed_at         TEXT,
    duration_seconds  REAL DEFAULT 0,
    idle_seconds      REAL DEFAULT 0,
    processing_seconds REAL DEFAULT 0,
    error_code        TEXT,
    error_message     TEXT
);

CREATE TABLE IF NOT EXISTS request_stage_event (
    id            TEXT PRIMARY KEY,
    request_id    TEXT NOT NULL REFERENCES request(id) ON DELETE CASCADE,
    timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    checkpoint    TEXT,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    message       TEXT,
    git_sha       TEXT,
    background_build_id TEXT,
    content_build_id TEXT,
    runtime_ready INTEGER DEFAULT 0,
    build_match   INTEGER DEFAULT 0,
    selector_used TEXT,
    evidence_pointer TEXT,
    fail_code     TEXT,
    first_fail_stage TEXT,
    source        TEXT NOT NULL CHECK(source IN ('dashboard','backend','worker','extension','google_flow'))
);

CREATE TABLE IF NOT EXISTS workspace_execution_package (
    workspace_execution_package_id TEXT PRIMARY KEY,
    product_id    TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    mode          TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 8,
    aspect_ratio  TEXT NOT NULL DEFAULT '9:16',
    model         TEXT NOT NULL,
    manual_override INTEGER NOT NULL DEFAULT 0,
    prompt_text   TEXT NOT NULL,
    prompt_fingerprint TEXT NOT NULL,
    prompt_package_snapshot_id TEXT NOT NULL,
    asset_slots   TEXT NOT NULL,
    resolved_assets TEXT NOT NULL,
    readiness     TEXT NOT NULL,
    execution_allowed INTEGER NOT NULL DEFAULT 0,
    production_generation_allowed INTEGER NOT NULL DEFAULT 0,
    manual_fallback TEXT NOT NULL,
    blockers      TEXT NOT NULL DEFAULT '[]',
    request_lineage_payload TEXT NOT NULL,
    source_of_truth_notes TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS workspace_generation_package (
    workspace_generation_package_id TEXT PRIMARY KEY,
    mode          TEXT NOT NULL,
    product_id    TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    product_name_snapshot TEXT NOT NULL DEFAULT '',
    source_lane   TEXT NOT NULL DEFAULT 'F2V',
    prompt_package_snapshot_id TEXT NOT NULL DEFAULT '',
    workspace_execution_package_id TEXT REFERENCES workspace_execution_package(workspace_execution_package_id) ON DELETE SET NULL,
    generation_mode TEXT NOT NULL DEFAULT 'SINGLE',
    final_prompt_text TEXT NOT NULL DEFAULT '',
    prompt_blocks_json TEXT NOT NULL DEFAULT '[]',
    selected_assets_json TEXT NOT NULL DEFAULT '{}',
    resolved_engine_slots_json TEXT NOT NULL DEFAULT '{}',
    resolver_output_json TEXT NOT NULL DEFAULT '{}',
    image_assets_json TEXT NOT NULL DEFAULT '{}',
    manual_handoff_json TEXT NOT NULL DEFAULT '{}',
    dom_handoff_payload_json TEXT NOT NULL DEFAULT '{}',
    blockers_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','READY_MANUAL','READY_DOM_STAGED','BLOCKED')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS creative_asset (
    asset_id      TEXT PRIMARY KEY,
    semantic_role TEXT NOT NULL CHECK(semantic_role IN (
        'PRODUCT_REFERENCE',
        'CHARACTER_REFERENCE',
        'SCENE_CONTEXT_REFERENCE',
        'STYLE_REFERENCE',
        'COMPOSITE_FRAME_REFERENCE'
    )),
    display_name  TEXT NOT NULL,
    description   TEXT,
    source_type   TEXT NOT NULL CHECK(source_type IN (
        'UPLOAD',
        'GENERATED_IMAGE',
        'PRODUCT_CACHE',
        'REMOTE_URL',
        'SYSTEM_SEED'
    )),
    storage_kind  TEXT NOT NULL CHECK(storage_kind IN (
        'LOCAL_FILE',
        'REMOTE_URL',
        'MEDIA_ID',
        'PRODUCT_IMAGE_CACHE'
    )),
    preview_url   TEXT,
    download_url  TEXT,
    media_id      TEXT,
    local_file_path TEXT,
    remote_source_url TEXT,
    product_id    TEXT REFERENCES product(id) ON DELETE SET NULL,
    category      TEXT,
    silo          TEXT,
    product_type  TEXT,
    allowed_modes TEXT NOT NULL DEFAULT '[]',
    engine_slot_eligibility TEXT NOT NULL DEFAULT '[]',
    mode_a_metadata_handoff TEXT,
    visual_dna_summary TEXT,
    character_dna TEXT,
    scene_context_dna TEXT,
    style_mood_dna TEXT,
    source_prompt_fingerprint TEXT,
    source_workspace_execution_package_id TEXT,
    source_prompt_package_snapshot_id TEXT,
    asset_subtype TEXT,
    generation_recipe_id TEXT,
    source_character_asset_id TEXT,
    source_scene_asset_id TEXT,
    source_style_asset_id TEXT,
    contains_rendered_text INTEGER NOT NULL DEFAULT 0,
    approved_for_video_support INTEGER NOT NULL DEFAULT 0,
    approved_for_poster INTEGER NOT NULL DEFAULT 0,
    product_truth_status TEXT,
    identity_lock_status TEXT,
    scale_truth_status TEXT,
    claim_safety_status TEXT,
    review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'ARCHIVED')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS product (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL DEFAULT 'FASTMOSS' CHECK(source IN ('FASTMOSS','TIKTOKSHOP','MANUAL','IMPORTED')),
    source_url          TEXT,
    brand               TEXT,
    raw_product_title   TEXT NOT NULL,
    product_display_name TEXT NOT NULL,
    product_short_name  TEXT NOT NULL,
    category            TEXT,
    subcategory         TEXT,
    type                TEXT,
    shop_name           TEXT,
    price               REAL,
    currency            TEXT,
    commission_amount   REAL,
    commission_rate     TEXT,
    price_min           REAL,
    price_max           REAL,
    commission          TEXT,
    image_url           TEXT,
    tiktok_product_url  TEXT,
    fastmoss_source_file TEXT,
    image_asset_status  TEXT,
    product_type        TEXT,
    product_type_id     TEXT,
    silo                TEXT,
    trigger_id          TEXT,
    formula             TEXT,
    copywriting_angle   TEXT,
    claim_risk_level    TEXT,
    mode_recommendations TEXT,
    physics_class       TEXT,
    product_scale       TEXT,
    hand_object_interaction TEXT,
    recommended_grip    TEXT,
    handling_notes      TEXT,
    air_gap_rule        TEXT,
    material_behavior   TEXT,
    surface_behavior    TEXT,
    fragility_level     TEXT,
    camera_handling_notes TEXT,
    scene_context       TEXT,
    camera_style        TEXT,
    camera_behavior     TEXT,
    camera_shot         TEXT,
    unsafe_handling_rules TEXT,
    section_4_hint      TEXT,
    section_5_product_physics_prompt TEXT,
    section_5_physics_hint TEXT,
    section_6_copy_hint TEXT,
    section_9_overlay_hint TEXT,
    mapping_source      TEXT,
    mapping_confidence  TEXT,
    mapping_review_status TEXT,
    mapping_status      TEXT,
    mapping_missing_fields TEXT,
    prompt_readiness_status TEXT,
    prompt_missing_fields TEXT,
    claim_safe_copy_status TEXT,
    claim_safe_copy_payload TEXT,
    claim_safe_copy_updated_at TEXT,
    production_prompt_approval_status TEXT,
    production_prompt_approved_modes TEXT,
    production_prompt_approved_at TEXT,
    production_prompt_approval_note TEXT,
    production_prompt_approval_provenance TEXT,
    lifecycle_status    TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(lifecycle_status IN ('ACTIVE','ARCHIVED')),
    archived_at         TEXT,
    archived_reason     TEXT,
    archived_by         TEXT,
    unarchived_at       TEXT,
    unarchived_reason   TEXT,
    lifecycle_provenance TEXT,
    asset_status        TEXT NOT NULL DEFAULT 'UNRESOLVED' CHECK(asset_status IN ('UNRESOLVED','DOWNLOADED','UPLOADED_TO_FLOW')),
    media_id            TEXT, -- Google Flow media_id after upload
    local_image_path    TEXT, -- Path to cached image
    image_failure_detail TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS batch (
    id                      TEXT PRIMARY KEY,
    product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    brief_id                TEXT,
    quantity                INTEGER NOT NULL DEFAULT 1,
    platform                TEXT DEFAULT 'TikTok',
    objective               TEXT DEFAULT 'conversion',
    language                TEXT DEFAULT 'Malay',
    engine                  TEXT DEFAULT 'VEO_3_1',
    duration                INTEGER DEFAULT 8,
    mode                    TEXT DEFAULT 'Frames',
    variation_level         TEXT DEFAULT 'medium',
    max_parallel_jobs       INTEGER DEFAULT 1,
    interval_min_seconds    INTEGER DEFAULT 45,
    interval_max_seconds    INTEGER DEFAULT 120,
    cooldown_after_n_jobs   INTEGER DEFAULT 5,
    cooldown_seconds        INTEGER DEFAULT 300,
    daily_credit_limit      INTEGER DEFAULT 0,
    approval_required       INTEGER DEFAULT 1,
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','DRAFT_BLOCKED','QUEUED','PROCESSING','COMPLETED','CANCELLED','PAUSED','FAILED')),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS batch_variant (
    variant_id              TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    brief_id                TEXT,
    variation_index         INTEGER NOT NULL,
    hook_angle              TEXT,
    scene_context           TEXT,
    camera_route            TEXT,
    copywriting_formula     TEXT,
    overlay_strategy        TEXT,
    cta_style               TEXT,
    google_flow_mode        TEXT,
    asset_strategy          TEXT,
    diversity_fingerprint   TEXT,
    prompt_9_section        TEXT,
    prompt_package_snapshot_id TEXT,
    prompt_package_snapshot TEXT,
    workspace_execution_package_id TEXT,
    prompt_fingerprint      TEXT,
    asset_fingerprints      TEXT,
    readiness               TEXT DEFAULT 'PENDING',
    blocked_reason          TEXT,
    queue_status            TEXT DEFAULT 'READY' CHECK(queue_status IN ('READY','QUEUED','DRY_RUN_VALIDATED','WAITING_INTERVAL','RUNNING','FLOW_MODE_VERIFIED','PROMPT_INSERTED','GENERATION_STARTED','GENERATED','DOWNLOADED','QA_PASSED','QA_FAILED','FAILED','RETRY_PENDING','CANCELLED')),
    request_id              TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS batch_queue_event (
    event_id                TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    variant_id              TEXT REFERENCES batch_variant(variant_id) ON DELETE SET NULL,
    status                  TEXT NOT NULL,
    message                 TEXT,
    timestamp               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source                  TEXT NOT NULL DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_scene_video ON scene(video_id);
CREATE INDEX IF NOT EXISTS idx_scene_order ON scene(video_id, display_order);
CREATE INDEX IF NOT EXISTS idx_request_status ON request(status);
CREATE INDEX IF NOT EXISTS idx_request_scene ON request(scene_id);
CREATE INDEX IF NOT EXISTS idx_video_project ON video(project_id);
CREATE INDEX IF NOT EXISTS idx_product_source ON product(source);
CREATE INDEX IF NOT EXISTS idx_product_name ON product(product_short_name);
CREATE INDEX IF NOT EXISTS idx_workspace_execution_package_product ON workspace_execution_package(product_id, mode);
CREATE INDEX IF NOT EXISTS idx_creative_asset_role_status ON creative_asset(semantic_role, status);
CREATE INDEX IF NOT EXISTS idx_creative_asset_product ON creative_asset(product_id, status);
CREATE INDEX IF NOT EXISTS idx_batch_product ON batch(product_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_batch ON batch_variant(batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_status ON batch_variant(queue_status);

CREATE TABLE IF NOT EXISTS fastmoss_bulk_draft_status (
    reference_id        TEXT PRIMARY KEY,
    raw_product_title   TEXT NOT NULL,
    source_url          TEXT,
    tiktok_product_url  TEXT,
    image_url           TEXT,
    category            TEXT,
    claim_risk_level    TEXT NOT NULL DEFAULT 'HIGH',
    mapping_confidence  REAL,
    image_readiness     TEXT NOT NULL DEFAULT 'IMAGE_MISSING',
    copy_route          TEXT,
    sold_count          INTEGER,
    commission_rate     TEXT,
    promotion_status    TEXT NOT NULL DEFAULT 'PENDING_DRAFT',
    draft_id            TEXT,
    committed_product_id TEXT,
    suspected_existing_product_id TEXT,
    suspected_existing_product_title TEXT,
    suspected_existing_product_source TEXT,
    suspected_existing_product_mapping_source TEXT,
    duplicate_match_reason TEXT,
    linked_product_id   TEXT,
    linked_product_title TEXT,
    duplicate_resolution TEXT,
    duplicate_resolved_at TEXT,
    duplicate_resolution_note TEXT,
    duplicate_ignore_product_id TEXT,
    error_message       TEXT,
    batch_provenance    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bulk_draft_status ON fastmoss_bulk_draft_status(promotion_status);
CREATE INDEX IF NOT EXISTS idx_bulk_draft_risk ON fastmoss_bulk_draft_status(claim_risk_level);

CREATE TABLE IF NOT EXISTS batch_generation_run (
    batch_run_id      TEXT PRIMARY KEY,
    status            TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
    product_id        TEXT NOT NULL,
    modes_json        TEXT NOT NULL DEFAULT '[]',
    quantity_per_mode INTEGER NOT NULL DEFAULT 10,
    interval_seconds  INTEGER NOT NULL DEFAULT 5,
    generation_mode   TEXT NOT NULL DEFAULT 'SINGLE',
    total_expected    INTEGER NOT NULL DEFAULT 0,
    total_completed   INTEGER NOT NULL DEFAULT 0,
    total_failed      INTEGER NOT NULL DEFAULT 0,
    error_log_json    TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- System library of finished generations (ADR-007 production): every completed
-- video/image retrieved from Google Flow is registered here so artifacts survive
-- restarts and are listable/downloadable from the dashboard gallery.
CREATE TABLE IF NOT EXISTS generated_artifact (
    media_id       TEXT PRIMARY KEY,
    job_id         TEXT,
    mode           TEXT,
    artifact_kind  TEXT NOT NULL DEFAULT 'video' CHECK(artifact_kind IN ('video','image')),
    local_path     TEXT,
    size_mb        REAL,
    project_id     TEXT,
    model_used     TEXT,
    duration_used  INTEGER,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


async def init_db():
    """Initialize database with schema and run migrations."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(SCHEMA)
        # Migration: add slug column to character table + backfill
        cursor = await db.execute("PRAGMA table_info(character)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "slug" not in columns:
            await db.execute("ALTER TABLE character ADD COLUMN slug TEXT")
            logger.info("Migrated: added slug column to character table")
        # Backfill slugs for existing characters (Python-side since SQLite has no slugify)
        cursor = await db.execute("SELECT id, name FROM character WHERE slug IS NULL OR slug = ''")
        chars_without_slug = await cursor.fetchall()
        if chars_without_slug:
            from agent.utils.slugify import slugify as _slugify
            for row in chars_without_slug:
                _slug = _slugify(row[1])
                await db.execute("UPDATE character SET slug=? WHERE id=?", (_slug, row[0]))
            logger.info("Backfilled slug for %d characters", len(chars_without_slug))
        # Migration: add voice_description if missing (added after initial schema)
        cursor = await db.execute("PRAGMA table_info(character)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "voice_description" not in columns:
            await db.execute("ALTER TABLE character ADD COLUMN voice_description TEXT DEFAULT ''")
            logger.info("Migrated: added voice_description column to character table")
        # Migration: add edit_prompt and source_media_id to request table
        cursor = await db.execute("PRAGMA table_info(request)")
        req_columns = {row[1] for row in await cursor.fetchall()}
        if "edit_prompt" not in req_columns:
            await db.execute("ALTER TABLE request ADD COLUMN edit_prompt TEXT")
            logger.info("Migrated: added edit_prompt column to request table")
        if "source_media_id" not in req_columns:
            await db.execute("ALTER TABLE request ADD COLUMN source_media_id TEXT")
            logger.info("Migrated: added source_media_id column to request table")
        # Migration: add queue columns to request table
        cursor = await db.execute("PRAGMA table_info(request)")
        request_columns = {row[1] for row in await cursor.fetchall()}
        if "next_retry_at" not in request_columns:
            await db.execute("ALTER TABLE request ADD COLUMN next_retry_at TEXT")
            logger.info("Migrated: added next_retry_at column to request table")
        if "retry_count" not in request_columns:
            await db.execute("ALTER TABLE request ADD COLUMN retry_count INTEGER DEFAULT 0")
            logger.info("Migrated: added retry_count column to request table")
        # Migration: ensure request table CHECK constraint includes all request types
        # SQLite can't alter CHECK constraints, so recreate the table
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE name='request' AND type='table'")
        row = await cursor.fetchone()
        needs_recreate = False
        if row:
            table_sql = row[0]
            if 'GENERATE_IMAGES' in table_sql and 'GENERATE_IMAGE,' not in table_sql:
                needs_recreate = True  # old GENERATE_IMAGES typo
            if 'REGENERATE_IMAGE' not in table_sql:
                needs_recreate = True  # missing REGENERATE/EDIT types
            if 'MANUAL_FLOW_JOB' not in table_sql or 'TELEMETRY_SELF_TEST' not in table_sql:
                needs_recreate = True  # missing direct/manual request types
            if 'WAITING_FLOW' not in table_sql or 'FLOW_RUNNING' not in table_sql:
                needs_recreate = True  # missing manual flow statuses
        if 'automation_report' not in request_columns:
            needs_recreate = True  # request updates expect this column to exist
        if needs_recreate:
            await db.execute("PRAGMA foreign_keys=OFF")
            await db.execute("ALTER TABLE request RENAME TO _request_old")
            await db.executescript("""
CREATE TABLE IF NOT EXISTS request (
    id            TEXT PRIMARY KEY,
    project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
    video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
    scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
    character_id  TEXT REFERENCES character(id) ON DELETE CASCADE,
    type          TEXT NOT NULL CHECK(type IN ('GENERATE_IMAGE','REGENERATE_IMAGE','EDIT_IMAGE','GENERATE_VIDEO','REGENERATE_VIDEO','GENERATE_VIDEO_REFS','TRUE_F2V','UPSCALE_VIDEO','GENERATE_CHARACTER_IMAGE','REGENERATE_CHARACTER_IMAGE','EDIT_CHARACTER_IMAGE','MANUAL_FLOW_JOB','TELEMETRY_SELF_TEST')),
    orientation   TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','WAITING_FLOW','FLOW_RUNNING','COMPLETED','FAILED')),
    request_id    TEXT,
    media_id      TEXT,
    output_url    TEXT,
    error_message TEXT,
    automation_report TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    edit_prompt   TEXT,
    source_media_id TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_request_status ON request(status);
CREATE INDEX IF NOT EXISTS idx_request_scene ON request(scene_id);
""")
            await db.execute("""
INSERT OR IGNORE INTO request (
    id, project_id, video_id, scene_id, character_id, type, orientation, status,
    request_id, media_id, output_url, error_message, automation_report,
    retry_count, next_retry_at, edit_prompt, source_media_id, created_at, updated_at
)
SELECT
    id,
    project_id,
    video_id,
    scene_id,
    character_id,
    CASE WHEN type='GENERATE_IMAGES' THEN 'GENERATE_IMAGE' ELSE type END,
    orientation,
    status,
    request_id,
    media_id,
    output_url,
    error_message,
    NULL,
    COALESCE(retry_count, 0),
    next_retry_at,
    edit_prompt,
    source_media_id,
    created_at,
    updated_at
FROM _request_old
""")
            await db.execute("DROP TABLE _request_old")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.commit()
            logger.info("Migrated: rebuilt request table for current request types and statuses")
        # Migration: add source column to scene table
        cursor = await db.execute("PRAGMA table_info(scene)")
        scene_columns = {row[1] for row in await cursor.fetchall()}
        if "source" not in scene_columns:
            await db.execute("ALTER TABLE scene ADD COLUMN source TEXT NOT NULL DEFAULT 'root'")
            logger.info("Migrated: added source column to scene table")
        if "narrator_text" not in scene_columns:
            await db.execute("ALTER TABLE scene ADD COLUMN narrator_text TEXT")
            logger.info("Migrated: added narrator_text column to scene table")
        # Migration: add narrator fields to project table
        cursor = await db.execute("PRAGMA table_info(project)")
        project_columns = {row[1] for row in await cursor.fetchall()}
        if "narrator_voice" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN narrator_voice TEXT")
            logger.info("Migrated: added narrator_voice column to project table")
        if "narrator_ref_audio" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN narrator_ref_audio TEXT")
            logger.info("Migrated: added narrator_ref_audio column to project table")
        if "material" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN material TEXT DEFAULT 'realistic'")
            logger.info("Migrated: added material column to project table")
        if "allow_music" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN allow_music INTEGER NOT NULL DEFAULT 0")
            logger.info("Migrated: added allow_music column to project table")
        if "allow_voice" not in project_columns:
            await db.execute("ALTER TABLE project ADD COLUMN allow_voice INTEGER NOT NULL DEFAULT 0")
            logger.info("Migrated: added allow_voice column to project table")
        # Migration: upgrade product table for product intelligence fields and new source enum.
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE name='product' AND type='table'")
        row = await cursor.fetchone()
        product_sql = row[0] if row else ""
        product_columns_cursor = await db.execute("PRAGMA table_info(product)")
        product_columns = {r[1] for r in await product_columns_cursor.fetchall()}
        product_needs_recreate = False
        required_product_columns = {
            "source_url", "brand", "price", "currency", "commission_amount", "commission_rate",
            "image_asset_status", "product_type", "product_type_id", "silo", "trigger_id", "formula", "copywriting_angle",
            "claim_risk_level", "mode_recommendations", "physics_class", "product_scale",
            "hand_object_interaction", "recommended_grip", "handling_notes", "air_gap_rule", "material_behavior",
            "surface_behavior", "fragility_level", "camera_handling_notes", "scene_context", "camera_style",
            "camera_behavior", "camera_shot", "unsafe_handling_rules", "section_4_hint",
            "section_5_product_physics_prompt", "section_5_physics_hint", "section_6_copy_hint", "section_9_overlay_hint",
            "mapping_source", "mapping_confidence", "mapping_review_status", "mapping_status", "mapping_missing_fields",
            "prompt_readiness_status", "prompt_missing_fields", "claim_safe_copy_status", "claim_safe_copy_payload",
            "claim_safe_copy_updated_at", "production_prompt_approval_status", "production_prompt_approved_modes",
            "production_prompt_approved_at", "production_prompt_approval_note", "production_prompt_approval_provenance",
        }
        if "MANUAL_PROJECT" in product_sql:
            product_needs_recreate = True
        if not required_product_columns.issubset(product_columns):
            product_needs_recreate = True
        if product_needs_recreate:
            await db.execute("PRAGMA foreign_keys=OFF")
            await db.execute("ALTER TABLE product RENAME TO _product_old")
            await db.executescript("""
CREATE TABLE IF NOT EXISTS product (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL DEFAULT 'FASTMOSS' CHECK(source IN ('FASTMOSS','TIKTOKSHOP','MANUAL','IMPORTED')),
    source_url          TEXT,
    brand               TEXT,
    raw_product_title   TEXT NOT NULL,
    product_display_name TEXT NOT NULL,
    product_short_name  TEXT NOT NULL,
    category            TEXT,
    subcategory         TEXT,
    type                TEXT,
    shop_name           TEXT,
    price               REAL,
    currency            TEXT,
    commission_amount   REAL,
    commission_rate     TEXT,
    price_min           REAL,
    price_max           REAL,
    commission          TEXT,
    image_url           TEXT,
    tiktok_product_url  TEXT,
    fastmoss_source_file TEXT,
    image_asset_status  TEXT,
    product_type        TEXT,
    product_type_id     TEXT,
    silo                TEXT,
    trigger_id          TEXT,
    formula             TEXT,
    copywriting_angle   TEXT,
    claim_risk_level    TEXT,
    mode_recommendations TEXT,
    physics_class       TEXT,
    product_scale       TEXT,
    hand_object_interaction TEXT,
    recommended_grip    TEXT,
    handling_notes      TEXT,
    air_gap_rule        TEXT,
    material_behavior   TEXT,
    surface_behavior    TEXT,
    fragility_level     TEXT,
    camera_handling_notes TEXT,
    scene_context       TEXT,
    camera_style        TEXT,
    camera_behavior     TEXT,
    camera_shot         TEXT,
    unsafe_handling_rules TEXT,
    section_4_hint      TEXT,
    section_5_product_physics_prompt TEXT,
    section_5_physics_hint TEXT,
    section_6_copy_hint TEXT,
    section_9_overlay_hint TEXT,
    mapping_source      TEXT,
    mapping_confidence  TEXT,
    mapping_review_status TEXT,
    mapping_status      TEXT,
    mapping_missing_fields TEXT,
    prompt_readiness_status TEXT,
    prompt_missing_fields TEXT,
    claim_safe_copy_status TEXT,
    claim_safe_copy_payload TEXT,
    claim_safe_copy_updated_at TEXT,
    production_prompt_approval_status TEXT,
    production_prompt_approved_modes TEXT,
    production_prompt_approved_at TEXT,
    production_prompt_approval_note TEXT,
    production_prompt_approval_provenance TEXT,
    lifecycle_status    TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(lifecycle_status IN ('ACTIVE','ARCHIVED')),
    archived_at         TEXT,
    archived_reason     TEXT,
    archived_by         TEXT,
    unarchived_at       TEXT,
    unarchived_reason   TEXT,
    lifecycle_provenance TEXT,
    asset_status        TEXT NOT NULL DEFAULT 'UNRESOLVED' CHECK(asset_status IN ('UNRESOLVED','DOWNLOADED','UPLOADED_TO_FLOW')),
    media_id            TEXT,
    local_image_path    TEXT,
    image_failure_detail TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_product_source ON product(source);
CREATE INDEX IF NOT EXISTS idx_product_name ON product(product_short_name);
""")
            await db.execute("""
INSERT INTO product (
    id, source, source_url, brand, raw_product_title, product_display_name, product_short_name,
    category, subcategory, type, shop_name, price, currency, commission_amount, commission_rate,
    price_min, price_max, commission, image_url, tiktok_product_url, fastmoss_source_file,
    image_asset_status, lifecycle_status, archived_at, archived_reason, archived_by, unarchived_at, unarchived_reason,
    lifecycle_provenance, asset_status, media_id, local_image_path, image_failure_detail, created_at, updated_at
)
SELECT
    id,
    CASE WHEN source='MANUAL_PROJECT' THEN 'MANUAL' ELSE source END,
    COALESCE(tiktok_product_url, ''),
    NULL,
    raw_product_title,
    product_display_name,
    product_short_name,
    category,
    subcategory,
    type,
    shop_name,
    COALESCE(price_min, price_max),
    'MYR',
    NULL,
    commission,
    price_min,
    price_max,
    commission,
    image_url,
    tiktok_product_url,
    fastmoss_source_file,
    asset_status,
    'ACTIVE',
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    asset_status,
    media_id,
    local_image_path,
    NULL,
    created_at,
    updated_at
FROM _product_old
""")
            await db.execute("DROP TABLE _product_old")
            await db.execute("PRAGMA foreign_keys=ON")
            logger.info("Migrated: upgraded product table for product intelligence fields")

        cursor = await db.execute("PRAGMA table_info(product)")
        product_columns = {row[1] for row in await cursor.fetchall()}
        if "lifecycle_status" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE'")
            logger.info("Migrated: added lifecycle_status column to product table")
        if "archived_at" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN archived_at TEXT")
            logger.info("Migrated: added archived_at column to product table")
        if "archived_reason" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN archived_reason TEXT")
            logger.info("Migrated: added archived_reason column to product table")
        if "archived_by" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN archived_by TEXT")
            logger.info("Migrated: added archived_by column to product table")
        if "unarchived_at" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN unarchived_at TEXT")
            logger.info("Migrated: added unarchived_at column to product table")
        if "unarchived_reason" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN unarchived_reason TEXT")
            logger.info("Migrated: added unarchived_reason column to product table")
        if "lifecycle_provenance" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN lifecycle_provenance TEXT")
            logger.info("Migrated: added lifecycle_provenance column to product table")
        if "claim_safe_copy_status" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN claim_safe_copy_status TEXT")
            logger.info("Migrated: added claim_safe_copy_status column to product table")
        if "claim_safe_copy_payload" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN claim_safe_copy_payload TEXT")
            logger.info("Migrated: added claim_safe_copy_payload column to product table")
        if "claim_safe_copy_updated_at" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN claim_safe_copy_updated_at TEXT")
            logger.info("Migrated: added claim_safe_copy_updated_at column to product table")
        if "production_prompt_approval_status" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN production_prompt_approval_status TEXT")
            logger.info("Migrated: added production_prompt_approval_status column to product table")
        if "production_prompt_approved_modes" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN production_prompt_approved_modes TEXT")
            logger.info("Migrated: added production_prompt_approved_modes column to product table")
        if "production_prompt_approved_at" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN production_prompt_approved_at TEXT")
            logger.info("Migrated: added production_prompt_approved_at column to product table")
        if "production_prompt_approval_note" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN production_prompt_approval_note TEXT")
            logger.info("Migrated: added production_prompt_approval_note column to product table")
        if "production_prompt_approval_provenance" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN production_prompt_approval_provenance TEXT")
            logger.info("Migrated: added production_prompt_approval_provenance column to product table")

        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE name='batch' AND type='table'")
        batch_sql_row = await cursor.fetchone()
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE name='batch_variant' AND type='table'")
        batch_variant_sql_row = await cursor.fetchone()
        batch_fk_needs_recreate = any(
            row and "_product_old" in (row[0] or "")
            for row in (batch_sql_row, batch_variant_sql_row)
        )
        if batch_fk_needs_recreate:
            await db.execute("PRAGMA foreign_keys=OFF")
            await db.execute("ALTER TABLE batch_queue_event RENAME TO _batch_queue_event_old")
            await db.execute("ALTER TABLE batch_variant RENAME TO _batch_variant_old")
            await db.execute("ALTER TABLE batch RENAME TO _batch_old")
            await db.executescript("""
CREATE TABLE IF NOT EXISTS batch (
    id                      TEXT PRIMARY KEY,
    product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    brief_id                TEXT,
    quantity                INTEGER NOT NULL DEFAULT 1,
    platform                TEXT DEFAULT 'TikTok',
    objective               TEXT DEFAULT 'conversion',
    language                TEXT DEFAULT 'Malay',
    engine                  TEXT DEFAULT 'VEO_3_1',
    duration                INTEGER DEFAULT 8,
    mode                    TEXT DEFAULT 'Frames',
    variation_level         TEXT DEFAULT 'medium',
    max_parallel_jobs       INTEGER DEFAULT 1,
    interval_min_seconds    INTEGER DEFAULT 45,
    interval_max_seconds    INTEGER DEFAULT 120,
    cooldown_after_n_jobs   INTEGER DEFAULT 5,
    cooldown_seconds        INTEGER DEFAULT 300,
    daily_credit_limit      INTEGER DEFAULT 0,
    approval_required       INTEGER DEFAULT 1,
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','DRAFT_BLOCKED','QUEUED','PROCESSING','COMPLETED','CANCELLED','PAUSED','FAILED')),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS batch_variant (
    variant_id              TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    brief_id                TEXT,
    variation_index         INTEGER NOT NULL,
    hook_angle              TEXT,
    scene_context           TEXT,
    camera_route            TEXT,
    copywriting_formula     TEXT,
    overlay_strategy        TEXT,
    cta_style               TEXT,
    google_flow_mode        TEXT,
    asset_strategy          TEXT,
    diversity_fingerprint   TEXT,
    prompt_9_section        TEXT,
    readiness               TEXT DEFAULT 'PENDING',
    blocked_reason          TEXT,
    queue_status            TEXT DEFAULT 'READY' CHECK(queue_status IN ('READY','QUEUED','DRY_RUN_VALIDATED','WAITING_INTERVAL','RUNNING','FLOW_MODE_VERIFIED','PROMPT_INSERTED','GENERATION_STARTED','GENERATED','DOWNLOADED','QA_PASSED','QA_FAILED','FAILED','RETRY_PENDING','CANCELLED')),
    request_id              TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS batch_queue_event (
    event_id                TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    variant_id              TEXT REFERENCES batch_variant(variant_id) ON DELETE SET NULL,
    status                  TEXT NOT NULL,
    message                 TEXT,
    timestamp               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source                  TEXT NOT NULL DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_batch_product ON batch(product_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_batch ON batch_variant(batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_status ON batch_variant(queue_status);
""")
            await db.execute("INSERT INTO batch SELECT * FROM _batch_old")
            await db.execute("INSERT INTO batch_variant SELECT * FROM _batch_variant_old")
            await db.execute("INSERT INTO batch_queue_event SELECT * FROM _batch_queue_event_old")
            await db.execute("DROP TABLE _batch_queue_event_old")
            await db.execute("DROP TABLE _batch_variant_old")
            await db.execute("DROP TABLE _batch_old")
            await db.execute("PRAGMA foreign_keys=ON")
            logger.info("Migrated: rebuilt batch tables to refresh product foreign keys")
        product_columns_cursor = await db.execute("PRAGMA table_info(product)")
        product_columns = {r[1] for r in await product_columns_cursor.fetchall()}
        if "image_failure_detail" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN image_failure_detail TEXT")
            logger.info("Migrated: added image_failure_detail column to product table")
        # Migration: add orientation to video table + backfill from scene data
        cursor = await db.execute("PRAGMA table_info(video)")
        video_columns = {row[1] for row in await cursor.fetchall()}
        if "orientation" not in video_columns:
            await db.execute("ALTER TABLE video ADD COLUMN orientation TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL'))")
            # Backfill: detect orientation from completed scene fields
            cursor = await db.execute("SELECT id FROM video")
            video_ids = [row[0] for row in await cursor.fetchall()]
            for vid in video_ids:
                cursor2 = await db.execute(
                    "SELECT horizontal_image_status, vertical_image_status FROM scene WHERE video_id = ? LIMIT 1", (vid,))
                scene = await cursor2.fetchone()
                if scene:
                    if scene[0] == "COMPLETED":
                        await db.execute("UPDATE video SET orientation = 'HORIZONTAL' WHERE id = ?", (vid,))
                    elif scene[1] == "COMPLETED":
                        await db.execute("UPDATE video SET orientation = 'VERTICAL' WHERE id = ?", (vid,))
            logger.info("Migrated: added orientation column to video table with backfill")
        # Migration: create material table if missing
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='material'")
        if not await cursor.fetchone():
            await db.execute("""CREATE TABLE material (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, style_instruction TEXT NOT NULL,
    negative_prompt TEXT, scene_prefix TEXT, lighting TEXT DEFAULT 'Studio lighting, highly detailed',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))""")
            logger.info("Migrated: created material table")
        # Migration: create telemetry tables
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='request_telemetry'")
        if not await cursor.fetchone():
            await db.execute("""CREATE TABLE request_telemetry (
                request_id    TEXT PRIMARY KEY REFERENCES request(id) ON DELETE CASCADE,
                project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
                video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
                scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
                product_id    TEXT REFERENCES product(id) ON DELETE SET NULL,
                request_type  TEXT NOT NULL,
                mode          TEXT,
                status        TEXT NOT NULL DEFAULT 'QUEUED',
                google_flow_stage TEXT,
                extension_stage   TEXT,
                worker_stage      TEXT,
                created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                queued_at         TEXT,
                started_at        TEXT,
                last_heartbeat_at TEXT,
                completed_at      TEXT,
                failed_at         TEXT,
                duration_seconds  REAL DEFAULT 0,
                idle_seconds      REAL DEFAULT 0,
                processing_seconds REAL DEFAULT 0,
                error_code        TEXT,
                error_message     TEXT
            )""")
            logger.info("Migrated: created request_telemetry table")
            
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='request_stage_event'")
        if not await cursor.fetchone():
            await db.execute("""CREATE TABLE request_stage_event (
                id            TEXT PRIMARY KEY,
                request_id    TEXT NOT NULL REFERENCES request(id) ON DELETE CASCADE,
                timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                stage         TEXT NOT NULL,
                status        TEXT NOT NULL,
                message       TEXT,
                source        TEXT NOT NULL CHECK(source IN ('dashboard','backend','worker','extension','google_flow'))
            )""")
            logger.info("Migrated: created request_stage_event table")

        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='request_telemetry'")
        telemetry_row = await cursor.fetchone()
        telemetry_sql = telemetry_row[0] if telemetry_row else ""
        if telemetry_sql and ('_product_old' in telemetry_sql or '_request_old' in telemetry_sql):
            logger.info("Migrating request_telemetry: repairing broken FK reference to renamed tables")
            import sqlite3 as _sqlite3
            _sync_path = str(DB_PATH) if str(DB_PATH) != ":memory:" else None
            if _sync_path:
                await db.commit()
                _sync = _sqlite3.connect(_sync_path)
                try:
                    _sync.execute("PRAGMA foreign_keys=OFF")
                    _sync.execute("""
                        CREATE TABLE request_telemetry_new (
                            request_id    TEXT PRIMARY KEY REFERENCES request(id) ON DELETE CASCADE,
                            project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
                            video_id      TEXT REFERENCES video(id) ON DELETE CASCADE,
                            scene_id      TEXT REFERENCES scene(id) ON DELETE CASCADE,
                            product_id    TEXT REFERENCES product(id) ON DELETE SET NULL,
                            request_type  TEXT NOT NULL,
                            mode          TEXT,
                            git_sha       TEXT,
                            background_build_id TEXT,
                            content_build_id TEXT,
                            last_checkpoint TEXT,
                            runtime_ready INTEGER DEFAULT 0,
                            build_match   INTEGER DEFAULT 0,
                            status        TEXT NOT NULL DEFAULT 'QUEUED',
                            google_flow_stage TEXT,
                            extension_stage   TEXT,
                            worker_stage      TEXT,
                            created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                            queued_at         TEXT,
                            started_at        TEXT,
                            last_heartbeat_at TEXT,
                            completed_at      TEXT,
                            failed_at         TEXT,
                            duration_seconds  REAL DEFAULT 0,
                            idle_seconds      REAL DEFAULT 0,
                            processing_seconds REAL DEFAULT 0,
                            error_code        TEXT,
                            error_message     TEXT
                        )
                    """)
                    _sync.execute("""
                        INSERT INTO request_telemetry_new (
                            request_id, project_id, video_id, scene_id, product_id, request_type, mode, status,
                            git_sha, background_build_id, content_build_id, last_checkpoint, runtime_ready, build_match,
                            google_flow_stage, extension_stage, worker_stage, created_at, queued_at, started_at,
                            last_heartbeat_at, completed_at, failed_at, duration_seconds, idle_seconds,
                            processing_seconds, error_code, error_message
                        )
                        SELECT
                            request_id, project_id, video_id, scene_id, product_id, request_type, mode, status,
                            NULL, NULL, NULL, NULL, 0, 0,
                            google_flow_stage, extension_stage, worker_stage, created_at, queued_at, started_at,
                            last_heartbeat_at, completed_at, failed_at, duration_seconds, idle_seconds,
                            processing_seconds, error_code, error_message
                        FROM request_telemetry
                    """)
                    _sync.execute("DROP TABLE request_telemetry")
                    _sync.execute("ALTER TABLE request_telemetry_new RENAME TO request_telemetry")
                    _sync.commit()
                    _sync.execute("PRAGMA foreign_keys=ON")
                    logger.info("Migrated: request_telemetry FK reference repaired")
                finally:
                    _sync.close()

        cursor = await db.execute("PRAGMA table_info(request_telemetry)")
        telemetry_columns = {row[1] for row in await cursor.fetchall()}
        telemetry_column_defs = {
            "prompt_package_snapshot_id": "TEXT",
            "workspace_execution_package_id": "TEXT",
            "prompt_fingerprint": "TEXT",
            "asset_fingerprints": "TEXT",
            "request_lineage_payload": "TEXT",
            "git_sha": "TEXT",
            "background_build_id": "TEXT",
            "content_build_id": "TEXT",
            "last_checkpoint": "TEXT",
            "runtime_ready": "INTEGER DEFAULT 0",
            "build_match": "INTEGER DEFAULT 0",
        }
        for column_name, column_type in telemetry_column_defs.items():
            if column_name not in telemetry_columns:
                await db.execute(f"ALTER TABLE request_telemetry ADD COLUMN {column_name} {column_type}")
                logger.info("Migrated: added %s column to request_telemetry", column_name)

        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='request_stage_event'")
        stage_event_row = await cursor.fetchone()
        stage_event_sql = stage_event_row[0] if stage_event_row else ""
        if stage_event_sql and '_request_old' in stage_event_sql:
            logger.info("Migrating request_stage_event: repairing broken FK reference to renamed request table")
            import sqlite3 as _sqlite3
            _sync_path = str(DB_PATH) if str(DB_PATH) != ":memory:" else None
            if _sync_path:
                await db.commit()
                _sync = _sqlite3.connect(_sync_path)
                try:
                    _sync.execute("PRAGMA foreign_keys=OFF")
                    _sync.execute("""
                        CREATE TABLE request_stage_event_new (
                            id            TEXT PRIMARY KEY,
                            request_id    TEXT NOT NULL REFERENCES request(id) ON DELETE CASCADE,
                            timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                            checkpoint    TEXT,
                            stage         TEXT NOT NULL,
                            status        TEXT NOT NULL,
                            message       TEXT,
                            git_sha       TEXT,
                            background_build_id TEXT,
                            content_build_id TEXT,
                            runtime_ready INTEGER DEFAULT 0,
                            build_match   INTEGER DEFAULT 0,
                            selector_used TEXT,
                            evidence_pointer TEXT,
                            fail_code     TEXT,
                            first_fail_stage TEXT,
                            source        TEXT NOT NULL CHECK(source IN ('dashboard','backend','worker','extension','google_flow'))
                        )
                    """)
                    _sync.execute("""
                        INSERT INTO request_stage_event_new (
                            id, request_id, timestamp, checkpoint, stage, status, message, git_sha,
                            background_build_id, content_build_id, runtime_ready, build_match,
                            selector_used, evidence_pointer, fail_code, first_fail_stage, source
                        )
                        SELECT
                            id, request_id, timestamp, NULL, stage, status, message, NULL,
                            NULL, NULL, 0, 0, NULL, NULL, NULL, NULL, source
                        FROM request_stage_event
                    """)
                    _sync.execute("DROP TABLE request_stage_event")
                    _sync.execute("ALTER TABLE request_stage_event_new RENAME TO request_stage_event")
                    _sync.commit()
                    _sync.execute("PRAGMA foreign_keys=ON")
                    logger.info("Migrated: request_stage_event FK reference repaired")
                finally:
                    _sync.close()

        cursor = await db.execute("PRAGMA table_info(request_stage_event)")
        stage_event_columns = {row[1] for row in await cursor.fetchall()}
        stage_event_column_defs = {
            "checkpoint": "TEXT",
            "git_sha": "TEXT",
            "background_build_id": "TEXT",
            "content_build_id": "TEXT",
            "runtime_ready": "INTEGER DEFAULT 0",
            "build_match": "INTEGER DEFAULT 0",
            "selector_used": "TEXT",
            "evidence_pointer": "TEXT",
            "fail_code": "TEXT",
            "first_fail_stage": "TEXT",
        }
        for column_name, column_type in stage_event_column_defs.items():
            if column_name not in stage_event_columns:
                await db.execute(f"ALTER TABLE request_stage_event ADD COLUMN {column_name} {column_type}")
                logger.info("Migrated: added %s column to request_stage_event", column_name)

        # Migration: create batch tables if missing
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='batch'")
        if not await cursor.fetchone():
            await db.executescript("""
CREATE TABLE IF NOT EXISTS batch (
    id                      TEXT PRIMARY KEY,
    product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    brief_id                TEXT,
    quantity                INTEGER NOT NULL DEFAULT 1,
    platform                TEXT DEFAULT 'TikTok',
    objective               TEXT DEFAULT 'conversion',
    language                TEXT DEFAULT 'Malay',
    engine                  TEXT DEFAULT 'VEO_3_1',
    duration                INTEGER DEFAULT 8,
    mode                    TEXT DEFAULT 'Frames',
    variation_level         TEXT DEFAULT 'medium',
    max_parallel_jobs       INTEGER DEFAULT 1,
    interval_min_seconds    INTEGER DEFAULT 45,
    interval_max_seconds    INTEGER DEFAULT 120,
    cooldown_after_n_jobs   INTEGER DEFAULT 5,
    cooldown_seconds        INTEGER DEFAULT 300,
    daily_credit_limit      INTEGER DEFAULT 0,
    approval_required       INTEGER DEFAULT 1,
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','DRAFT_BLOCKED','QUEUED','PROCESSING','COMPLETED','CANCELLED','PAUSED','FAILED')),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS batch_variant (
    variant_id              TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    brief_id                TEXT,
    variation_index         INTEGER NOT NULL,
    hook_angle              TEXT,
    scene_context           TEXT,
    camera_route            TEXT,
    copywriting_formula     TEXT,
    overlay_strategy        TEXT,
    cta_style               TEXT,
    google_flow_mode        TEXT,
    asset_strategy          TEXT,
    diversity_fingerprint   TEXT,
    prompt_9_section        TEXT,
    readiness               TEXT DEFAULT 'PENDING',
    blocked_reason          TEXT,
    queue_status            TEXT DEFAULT 'READY' CHECK(queue_status IN ('READY','QUEUED','DRY_RUN_VALIDATED','WAITING_INTERVAL','RUNNING','FLOW_MODE_VERIFIED','PROMPT_INSERTED','GENERATION_STARTED','GENERATED','DOWNLOADED','QA_PASSED','QA_FAILED','FAILED','RETRY_PENDING','CANCELLED')),
    request_id              TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS batch_queue_event (
    event_id                TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    variant_id              TEXT REFERENCES batch_variant(variant_id) ON DELETE SET NULL,
    status                  TEXT NOT NULL,
    message                 TEXT,
    timestamp               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source                  TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_batch_product ON batch(product_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_batch ON batch_variant(batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_status ON batch_variant(queue_status);

CREATE TABLE IF NOT EXISTS fastmoss_bulk_draft_status (
    reference_id        TEXT PRIMARY KEY,
    raw_product_title   TEXT NOT NULL,
    source_url          TEXT,
    tiktok_product_url  TEXT,
    image_url           TEXT,
    category            TEXT,
    claim_risk_level    TEXT NOT NULL DEFAULT 'HIGH',
    mapping_confidence  REAL,
    image_readiness     TEXT NOT NULL DEFAULT 'IMAGE_MISSING',
    copy_route          TEXT,
    sold_count          INTEGER,
    commission_rate     TEXT,
    promotion_status    TEXT NOT NULL DEFAULT 'PENDING_DRAFT',
    draft_id            TEXT,
    committed_product_id TEXT,
    suspected_existing_product_id TEXT,
    suspected_existing_product_title TEXT,
    suspected_existing_product_source TEXT,
    suspected_existing_product_mapping_source TEXT,
    duplicate_match_reason TEXT,
    linked_product_id   TEXT,
    linked_product_title TEXT,
    duplicate_resolution TEXT,
    duplicate_resolved_at TEXT,
    duplicate_resolution_note TEXT,
    duplicate_ignore_product_id TEXT,
    error_message       TEXT,
    batch_provenance    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bulk_draft_status ON fastmoss_bulk_draft_status(promotion_status);
CREATE INDEX IF NOT EXISTS idx_bulk_draft_risk ON fastmoss_bulk_draft_status(claim_risk_level);
""")
            logger.info("Migrated: created batch production tables")
        await db.commit()

        # Migration: rebuild batch_variant CHECK constraint to include DRY_RUN_VALIDATED
        # SQLite cannot ALTER CHECK constraints, so we detect the old constraint and rebuild.
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='batch_variant'"
        )
        row = await cursor.fetchone()
        if row and "DRY_RUN_VALIDATED" not in row[0]:
            logger.info("Migrating batch_variant: rebuilding table to add DRY_RUN_VALIDATED to CHECK constraint")
            # SQLite ALTER TABLE cannot modify CHECK constraints.
            # We must use a synchronous sqlite3 connection so PRAGMA foreign_keys=OFF
            # is set outside any transaction (aiosqlite always wraps in implicit BEGIN).
            import sqlite3 as _sqlite3
            _sync_path = str(DB_PATH) if str(DB_PATH) != ":memory:" else None
            if _sync_path:
                _sync = _sqlite3.connect(_sync_path)
                try:
                    _sync.execute("PRAGMA foreign_keys=OFF")
                    _sync.execute("""
                        CREATE TABLE batch_variant_new (
                            variant_id              TEXT PRIMARY KEY,
                            batch_id                TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
                            product_id              TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
                            brief_id                TEXT,
                            variation_index         INTEGER NOT NULL,
                            hook_angle              TEXT,
                            scene_context           TEXT,
                            camera_route            TEXT,
                            copywriting_formula     TEXT,
                            overlay_strategy        TEXT,
                            cta_style               TEXT,
                            google_flow_mode        TEXT,
                            asset_strategy          TEXT,
                            diversity_fingerprint   TEXT,
                            prompt_9_section        TEXT,
                            readiness               TEXT DEFAULT 'PENDING',
                            blocked_reason          TEXT,
                            queue_status            TEXT DEFAULT 'READY' CHECK(queue_status IN (
                                'READY','QUEUED','DRY_RUN_VALIDATED','WAITING_INTERVAL','RUNNING',
                                'FLOW_MODE_VERIFIED','PROMPT_INSERTED','GENERATION_STARTED',
                                'GENERATED','DOWNLOADED','QA_PASSED','QA_FAILED',
                                'FAILED','RETRY_PENDING','CANCELLED')),
                            request_id              TEXT,
                            created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                            updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                        )
                    """)
                    _sync.execute("""
                        INSERT INTO batch_variant_new
                        SELECT variant_id, batch_id, product_id, brief_id, variation_index,
                               hook_angle, scene_context, camera_route, copywriting_formula,
                               overlay_strategy, cta_style, google_flow_mode, asset_strategy,
                               diversity_fingerprint, prompt_9_section, readiness, blocked_reason,
                               queue_status, request_id, created_at, updated_at
                        FROM batch_variant
                    """)
                    _sync.execute("DROP TABLE batch_variant")
                    _sync.execute("ALTER TABLE batch_variant_new RENAME TO batch_variant")
                    _sync.execute("CREATE INDEX IF NOT EXISTS idx_batch_variant_batch ON batch_variant(batch_id)")
                    _sync.execute("CREATE INDEX IF NOT EXISTS idx_batch_variant_status ON batch_variant(queue_status)")
                    _sync.commit()
                    _sync.execute("PRAGMA foreign_keys=ON")
                    logger.info("Migrated: batch_variant rebuilt with DRY_RUN_VALIDATED in CHECK constraint")
                finally:
                    _sync.close()
            else:
                # In-memory DB (tests): schema already has DRY_RUN_VALIDATED, skip migration
                logger.info("In-memory DB detected: skipping batch_variant migration (schema already correct)")

        cursor = await db.execute("PRAGMA table_info(batch_variant)")
        batch_variant_columns = {row[1] for row in await cursor.fetchall()}
        batch_variant_column_defs = {
            "prompt_package_snapshot_id": "TEXT",
            "prompt_package_snapshot": "TEXT",
            "workspace_execution_package_id": "TEXT",
            "prompt_fingerprint": "TEXT",
            "asset_fingerprints": "TEXT",
        }
        for column_name, column_type in batch_variant_column_defs.items():
            if column_name not in batch_variant_columns:
                await db.execute(f"ALTER TABLE batch_variant ADD COLUMN {column_name} {column_type}")
                logger.info("Migrated: added %s column to batch_variant", column_name)

        # Migration: repair broken batch_queue_event FK reference to _batch_variant_old
        # A previous rename-based migration caused SQLite to auto-update the FK reference
        # from batch_variant → _batch_variant_old.  Detect and rebuild the table.
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='batch_queue_event'"
        )
        bqe_row = await cursor.fetchone()
        if bqe_row and "_batch_variant_old" in bqe_row[0]:
            logger.info("Migrating batch_queue_event: repairing broken FK reference to _batch_variant_old")
            import sqlite3 as _sqlite3
            _sync_path = str(DB_PATH) if str(DB_PATH) != ":memory:" else None
            if _sync_path:
                _sync = _sqlite3.connect(_sync_path)
                try:
                    _sync.execute("PRAGMA foreign_keys=OFF")
                    _sync.execute("""
                        CREATE TABLE batch_queue_event_new (
                            event_id   TEXT PRIMARY KEY,
                            batch_id   TEXT NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
                            variant_id TEXT REFERENCES batch_variant(variant_id) ON DELETE SET NULL,
                            status     TEXT NOT NULL,
                            message    TEXT,
                            timestamp  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                            source     TEXT NOT NULL DEFAULT 'system'
                        )
                    """)
                    _sync.execute("INSERT INTO batch_queue_event_new SELECT * FROM batch_queue_event")
                    _sync.execute("DROP TABLE batch_queue_event")
                    _sync.execute("ALTER TABLE batch_queue_event_new RENAME TO batch_queue_event")
                    _sync.commit()
                    _sync.execute("PRAGMA foreign_keys=ON")
                    logger.info("Migrated: batch_queue_event FK reference repaired")
                finally:
                    _sync.close()

    # Migration: add fastmoss_reference_id column to product table
        cursor = await db.execute("PRAGMA table_info(product)")
        product_cols = {row[1] for row in await cursor.fetchall()}
        if "fastmoss_reference_id" not in product_cols:
            await db.execute("ALTER TABLE product ADD COLUMN fastmoss_reference_id TEXT")
            await db.commit()
            logger.info("Migrated: added fastmoss_reference_id column to product table")

        # Migration: add recompute audit columns to fastmoss_bulk_draft_status
        cursor = await db.execute("PRAGMA table_info(fastmoss_bulk_draft_status)")
        bulk_cols = {row[1] for row in await cursor.fetchall()}
        _bulk_audit_cols = {
            "recomputed_at": "TEXT",
            "recompute_previous_status": "TEXT",
            "recompute_previous_error": "TEXT",
            "suspected_existing_product_id": "TEXT",
            "suspected_existing_product_title": "TEXT",
            "suspected_existing_product_source": "TEXT",
            "suspected_existing_product_mapping_source": "TEXT",
            "duplicate_match_reason": "TEXT",
            "linked_product_id": "TEXT",
            "linked_product_title": "TEXT",
            "duplicate_resolution": "TEXT",
            "duplicate_resolved_at": "TEXT",
            "duplicate_resolution_note": "TEXT",
            "duplicate_ignore_product_id": "TEXT",
        }
        for _col_name, _col_type in _bulk_audit_cols.items():
            if _col_name not in bulk_cols:
                await db.execute(
                    f"ALTER TABLE fastmoss_bulk_draft_status ADD COLUMN {_col_name} {_col_type}"
                )
                logger.info(
                    "Migrated: added %s column to fastmoss_bulk_draft_status", _col_name
                )
        await db.commit()

        # Migration: add missing columns to creative_asset table
        cursor = await db.execute("PRAGMA table_info(creative_asset)")
        ca_cols = {row[1] for row in await cursor.fetchall()}
        _ca_new_cols = {
            "visual_dna_summary": "TEXT",
            "character_dna": "TEXT",
            "scene_context_dna": "TEXT",
            "style_mood_dna": "TEXT",
            "source_prompt_fingerprint": "TEXT",
            "source_workspace_execution_package_id": "TEXT",
            "source_prompt_package_snapshot_id": "TEXT",
            # IMG Asset Factory v1: governed lineage + truth/lifecycle metadata
            "asset_subtype": "TEXT",
            "generation_recipe_id": "TEXT",
            "source_character_asset_id": "TEXT",
            "source_scene_asset_id": "TEXT",
            "source_style_asset_id": "TEXT",
            "contains_rendered_text": "INTEGER NOT NULL DEFAULT 0",
            "approved_for_video_support": "INTEGER NOT NULL DEFAULT 0",
            "approved_for_poster": "INTEGER NOT NULL DEFAULT 0",
            "product_truth_status": "TEXT",
            "identity_lock_status": "TEXT",
            "scale_truth_status": "TEXT",
            "claim_safety_status": "TEXT",
            # Lifecycle default is PENDING_REVIEW everywhere. Pre-existing rows
            # backfilled by this ALTER become PENDING_REVIEW too — they predate the
            # review lifecycle, so honestly marking them "not yet reviewed" is
            # preferred over silently grandfathering them as APPROVED. review_status
            # is metadata only (NOT a selection gate), so legacy assets stay usable.
            "review_status": "TEXT NOT NULL DEFAULT 'PENDING_REVIEW'",
        }
        for _col, _type in _ca_new_cols.items():
            if _col not in ca_cols:
                await db.execute(f"ALTER TABLE creative_asset ADD COLUMN {_col} {_type}")
                logger.info("Migrated: added %s column to creative_asset table", _col)
        await db.commit()

        # Migration: add batch_run_id to workspace_generation_package
        cursor = await db.execute("PRAGMA table_info(workspace_generation_package)")
        wgp_cols = {row[1] for row in await cursor.fetchall()}
        if "batch_run_id" not in wgp_cols:
            await db.execute("ALTER TABLE workspace_generation_package ADD COLUMN batch_run_id TEXT")
            logger.info("Migrated: added batch_run_id column to workspace_generation_package table")
        await db.commit()

        # Migration: add operator_notes + ARCHIVED status to workspace_generation_package
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE name='workspace_generation_package' AND type='table'")
        row = await cursor.fetchone()
        wgp_sql = row[0] if row else ""
        cursor = await db.execute("PRAGMA table_info(workspace_generation_package)")
        wgp_cols2 = {row[1] for row in await cursor.fetchall()}
        if "ARCHIVED" not in wgp_sql:
            import sqlite3 as _sqlite3_wgp
            _db_path_wgp = str(DB_PATH)
            with _sqlite3_wgp.connect(_db_path_wgp) as _sync_wgp:
                _sync_wgp.execute("PRAGMA foreign_keys=OFF")
                _sync_wgp.execute("ALTER TABLE workspace_generation_package RENAME TO _wgp_old")
                _sync_wgp.executescript("""
CREATE TABLE IF NOT EXISTS workspace_generation_package (
    workspace_generation_package_id TEXT PRIMARY KEY,
    mode          TEXT NOT NULL,
    product_id    TEXT NOT NULL,
    product_name_snapshot TEXT NOT NULL DEFAULT '',
    source_lane   TEXT NOT NULL DEFAULT 'F2V',
    prompt_package_snapshot_id TEXT NOT NULL DEFAULT '',
    workspace_execution_package_id TEXT,
    generation_mode TEXT NOT NULL DEFAULT 'SINGLE',
    final_prompt_text TEXT NOT NULL DEFAULT '',
    prompt_blocks_json TEXT NOT NULL DEFAULT '[]',
    selected_assets_json TEXT NOT NULL DEFAULT '{}',
    resolved_engine_slots_json TEXT NOT NULL DEFAULT '{}',
    resolver_output_json TEXT NOT NULL DEFAULT '{}',
    image_assets_json TEXT NOT NULL DEFAULT '{}',
    manual_handoff_json TEXT NOT NULL DEFAULT '{}',
    dom_handoff_payload_json TEXT NOT NULL DEFAULT '{}',
    blockers_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','READY_MANUAL','READY_DOM_STAGED','BLOCKED','ARCHIVED')),
    operator_notes TEXT,
    batch_run_id  TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
""")
                _sync_wgp.execute("""
INSERT INTO workspace_generation_package
    SELECT workspace_generation_package_id, mode, product_id, product_name_snapshot,
           source_lane, prompt_package_snapshot_id, workspace_execution_package_id,
           generation_mode, final_prompt_text, prompt_blocks_json, selected_assets_json,
           resolved_engine_slots_json, resolver_output_json, image_assets_json,
           manual_handoff_json, dom_handoff_payload_json, blockers_json, warnings_json,
           status, NULL, batch_run_id, created_at, updated_at
    FROM _wgp_old
""")
                _sync_wgp.execute("DROP TABLE _wgp_old")
                _sync_wgp.execute("PRAGMA foreign_keys=ON")
                _sync_wgp.commit()
            logger.info("Migrated: workspace_generation_package — added ARCHIVED status + operator_notes column")
        elif "operator_notes" not in wgp_cols2:
            await db.execute("ALTER TABLE workspace_generation_package ADD COLUMN operator_notes TEXT")
            await db.commit()
            logger.info("Migrated: added operator_notes column to workspace_generation_package")

        # P4: Create scheduled_batch_run table if missing
        await db.executescript("""
CREATE TABLE IF NOT EXISTS scheduled_batch_run (
    scheduled_run_id    TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'SCHEDULED'
                        CHECK(status IN ('SCHEDULED','RUNNING','COMPLETED','FAILED','CANCELLED')),
    product_ids_json    TEXT NOT NULL DEFAULT '[]',
    modes_json          TEXT NOT NULL DEFAULT '[]',
    quantity_per_mode   INTEGER NOT NULL DEFAULT 10,
    interval_seconds    INTEGER NOT NULL DEFAULT 5,
    generation_mode     TEXT NOT NULL DEFAULT 'SINGLE',
    character_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    scene_asset_ids_json     TEXT NOT NULL DEFAULT '[]',
    style_asset_ids_json     TEXT NOT NULL DEFAULT '[]',
    img_prompt_template TEXT,
    scheduled_at        TEXT NOT NULL,
    label               TEXT,
    batch_run_id        TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
""")
        await db.commit()

        # Migration: add product_ids_json + config_json to batch_generation_run (P3)
        cursor = await db.execute("PRAGMA table_info(batch_generation_run)")
        bgr_cols = {row[1] for row in await cursor.fetchall()}
        if "product_ids_json" not in bgr_cols:
            await db.execute("ALTER TABLE batch_generation_run ADD COLUMN product_ids_json TEXT DEFAULT '[]'")
            logger.info("Migrated: added product_ids_json column to batch_generation_run")
        if "config_json" not in bgr_cols:
            await db.execute("ALTER TABLE batch_generation_run ADD COLUMN config_json TEXT DEFAULT '{}'")
            logger.info("Migrated: added config_json column to batch_generation_run")
        await db.commit()

        # ── Batch Prompt / Production split ──────────────────────────────
        # Prompt-item variation + production lifecycle columns on
        # workspace_generation_package. All additive; the prompt-side status
        # CHECK stays untouched — production lifecycle lives in its own column:
        # NONE → APPROVED → QUEUED → RUNNING → GENERATED → DOWNLOADED /
        # FAILED / CANCELLED.
        cursor = await db.execute("PRAGMA table_info(workspace_generation_package)")
        wgp_cols3 = {row[1] for row in await cursor.fetchall()}
        _wgp_split_cols = (
            ("logical_mode", "TEXT"),
            ("variation_strategy", "TEXT"),
            ("prompt_fingerprint", "TEXT"),
            ("variation_fingerprints_json", "TEXT DEFAULT '{}'"),
            ("anti_redundancy_json", "TEXT DEFAULT '[]'"),
            ("production_status", "TEXT DEFAULT 'NONE'"),
            ("production_run_id", "TEXT"),
            ("production_job_id", "TEXT"),
            ("production_error", "TEXT"),
            ("artifact_media_ids_json", "TEXT DEFAULT '[]'"),
            ("approved_at", "TEXT"),
            ("sent_to_production_at", "TEXT"),
        )
        for _col, _decl in _wgp_split_cols:
            if _col not in wgp_cols3:
                await db.execute(
                    f"ALTER TABLE workspace_generation_package ADD COLUMN {_col} {_decl}"
                )
                logger.info("Migrated: added %s column to workspace_generation_package table", _col)
        await db.commit()

        # Migration: single-mode law metadata on batch_generation_run
        cursor = await db.execute("PRAGMA table_info(batch_generation_run)")
        bgr_cols2 = {row[1] for row in await cursor.fetchall()}
        if "logical_mode" not in bgr_cols2:
            await db.execute("ALTER TABLE batch_generation_run ADD COLUMN logical_mode TEXT")
            logger.info("Migrated: added logical_mode column to batch_generation_run")
        if "variation_strategy" not in bgr_cols2:
            await db.execute("ALTER TABLE batch_generation_run ADD COLUMN variation_strategy TEXT")
            logger.info("Migrated: added variation_strategy column to batch_generation_run")
        await db.commit()

        # Migration: link generated artifacts back to their source prompt package
        cursor = await db.execute("PRAGMA table_info(generated_artifact)")
        ga_cols = {row[1] for row in await cursor.fetchall()}
        if "workspace_generation_package_id" not in ga_cols:
            await db.execute(
                "ALTER TABLE generated_artifact ADD COLUMN workspace_generation_package_id TEXT"
            )
            logger.info("Migrated: added workspace_generation_package_id column to generated_artifact")
        await db.commit()

        # Production queue run table: executes APPROVED prompt packages through
        # the one hardened generate lane with interval + cooldown throttling.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS production_run (
    production_run_id     TEXT PRIMARY KEY,
    status                TEXT NOT NULL DEFAULT 'PENDING'
                          CHECK(status IN ('PENDING','RUNNING','PAUSED','COMPLETED','FAILED','CANCELLED')),
    dry_run               INTEGER NOT NULL DEFAULT 1,
    max_parallel_jobs     INTEGER NOT NULL DEFAULT 1,
    interval_min_seconds  INTEGER NOT NULL DEFAULT 45,
    interval_max_seconds  INTEGER NOT NULL DEFAULT 120,
    cooldown_after_n_jobs INTEGER NOT NULL DEFAULT 5,
    cooldown_seconds      INTEGER NOT NULL DEFAULT 300,
    total_expected        INTEGER NOT NULL DEFAULT 0,
    total_completed       INTEGER NOT NULL DEFAULT 0,
    total_failed          INTEGER NOT NULL DEFAULT 0,
    error_log_json        TEXT NOT NULL DEFAULT '[]',
    config_json           TEXT NOT NULL DEFAULT '{}',
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
""")
        await db.commit()

        # Postiz publishing audit trail (feature-flagged Postiz adapter).
        # Additive table — records every upload/post handoff so operators can
        # trace a BOSMAX artifact to its Postiz media id + post ids.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS postiz_publish_record (
    record_id             TEXT PRIMARY KEY,
    artifact_media_id     TEXT,
    source_local_path     TEXT,
    source_public_url     TEXT,
    upload_mode           TEXT NOT NULL DEFAULT 'file',
    postiz_media_id       TEXT,
    postiz_media_path     TEXT,
    post_type             TEXT NOT NULL DEFAULT 'draft',
    scheduled_at          TEXT,
    content               TEXT,
    integration_ids_json  TEXT NOT NULL DEFAULT '[]',
    provider_settings_json TEXT NOT NULL DEFAULT '{}',
    postiz_response_json  TEXT NOT NULL DEFAULT '{}',
    status                TEXT NOT NULL DEFAULT 'PENDING'
                          CHECK(status IN ('PENDING','UPLOADED','POST_CREATED','FAILED')),
    error                 TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
""")
        await db.commit()

        # Social Copy Package — platform-specific caption/comment copy linked to
        # a generated artifact (media_id). Authored on the generator pages,
        # approved, then prefilled into Postiz Publish. Like postiz_publish_record
        # this uses a plain artifact_media_id (no hard FK): generated_artifact rows
        # self-purge at 48h while copy packages persist as publishing history.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS social_copy_package (
    package_id            TEXT PRIMARY KEY,
    artifact_media_id     TEXT NOT NULL,
    source_mode           TEXT,
    platform              TEXT NOT NULL
                          CHECK(platform IN ('tiktok','facebook','instagram','threads','x')),
    caption               TEXT NOT NULL DEFAULT '',
    first_comment         TEXT NOT NULL DEFAULT '',
    hashtags_json         TEXT NOT NULL DEFAULT '[]',
    call_to_action        TEXT NOT NULL DEFAULT '',
    tone                  TEXT NOT NULL DEFAULT '',
    language              TEXT NOT NULL DEFAULT 'ms',
    status                TEXT NOT NULL DEFAULT 'DRAFT'
                          CHECK(status IN ('DRAFT','READY','APPROVED','REJECTED','PUBLISHED')),
    compliance_status     TEXT NOT NULL DEFAULT 'OK'
                          CHECK(compliance_status IN ('OK','WARN','BLOCKED')),
    blockers_json         TEXT NOT NULL DEFAULT '[]',
    warnings_json         TEXT NOT NULL DEFAULT '[]',
    approval_note         TEXT,
    approved_at           TEXT,
    postiz_record_id      TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_social_copy_media_id ON social_copy_package(artifact_media_id);
CREATE INDEX IF NOT EXISTS idx_social_copy_status ON social_copy_package(status);
""")
        await db.commit()

        # Generation Result (Results Hub) — DURABLE per-finished-generation record.
        # The heavy artifact FILE still lives in `generated_artifact` and is purged
        # at 48h; THIS row is the lightweight, long-lived deliverable record so the
        # operator can, at any time: (a) copy the exact prompt + settings used to
        # manually re-drive Google Flow if automation breaks, and (b) reach the
        # per-platform social captions for that result. Keyed by Flow media_id, it
        # is written on job completion and is NEVER touched by the artifact purge.
        # Additive: it never rewrites the generation lane or the artifact table.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS generation_result (
    media_id       TEXT PRIMARY KEY,
    job_id         TEXT,
    request_id     TEXT,
    mode           TEXT,
    artifact_kind  TEXT NOT NULL DEFAULT 'video'
                   CHECK(artifact_kind IN ('video','image')),
    product_id     TEXT,
    product_name   TEXT,
    final_prompt_text TEXT NOT NULL DEFAULT '',
    aspect_ratio   TEXT,
    model_label    TEXT,
    duration_s     INTEGER,
    count_setting  INTEGER,
    reference_media_ids_json TEXT NOT NULL DEFAULT '[]',
    workspace_generation_package_id TEXT,
    project_id     TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_generation_result_created ON generation_result(created_at);
CREATE INDEX IF NOT EXISTS idx_generation_result_kind ON generation_result(artifact_kind);
CREATE INDEX IF NOT EXISTS idx_generation_result_product ON generation_result(product_id);
""")
        await db.commit()

        # Native Google Flow Extend LINEAGE — durable parent->child chain record,
        # one row per extend BLOCK submission (evidence: 2026-07-11 capture). The
        # parent/child OPERATION id and primaryMediaId are FOUR SEPARATE columns and
        # are NEVER collapsed: the extend request binds videoInput.mediaId to the
        # parent OPERATION id, while retrieval/concat reference the primaryMediaId —
        # proven distinct in the capture (block-1 op b6371e69 != media 69051c7b).
        # `idempotency_key` is UNIQUE so a duplicate block submission fails closed.
        # Durable like generation_result — never touched by the 48h artifact purge.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS extend_lineage (
    extend_lineage_id               TEXT PRIMARY KEY,
    workspace_generation_package_id TEXT,
    project_id                      TEXT,
    scene_id                        TEXT,
    block_index                     INTEGER,
    block_position                  INTEGER,
    parent_operation_id             TEXT,
    parent_primary_media_id         TEXT,
    child_operation_id              TEXT,
    child_primary_media_id          TEXT,
    child_workflow_id               TEXT,
    batch_id                        TEXT,
    model_key                       TEXT,
    aspect_ratio                    TEXT,
    start_frame_index               INTEGER,
    end_frame_index                 INTEGER,
    continuation_prompt_hash        TEXT,
    idempotency_key                 TEXT,
    polling_state                   TEXT NOT NULL DEFAULT 'NOT_STARTED'
        CHECK(polling_state IN ('NOT_STARTED','SOURCE_READY','EXTEND_SUBMITTED',
              'EXTEND_POLLING','EXTEND_SUCCEEDED','EXTEND_FAILED','HARVEST_FAILED',
              'CANCELLED','BLOCKED')),
    retry_attempt                   INTEGER NOT NULL DEFAULT 0,
    output_url                      TEXT,
    error_code                      TEXT,
    error_message                   TEXT,
    created_at                      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_extend_lineage_child ON extend_lineage(child_operation_id);
CREATE INDEX IF NOT EXISTS idx_extend_lineage_parent ON extend_lineage(parent_operation_id);
CREATE INDEX IF NOT EXISTS idx_extend_lineage_pkg ON extend_lineage(workspace_generation_package_id, block_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_extend_lineage_idem ON extend_lineage(idempotency_key);

-- ONE logical full-video production job (Mission C): the user deliverable is a
-- single full-duration MP4; segment media are internal diagnostics only.
CREATE TABLE IF NOT EXISTS video_production_job (
    job_id                      TEXT PRIMARY KEY,
    project_id                  TEXT,
    scene_id                    TEXT,
    requested_duration_seconds  INTEGER,
    status                      TEXT NOT NULL DEFAULT 'PREPARING',
    error_code                  TEXT,
    initial_media_id            TEXT,
    segment_media_ids_json      TEXT,
    extend_lineage_ids_json     TEXT,
    final_concat_job_name       TEXT,
    final_media_id              TEXT,
    final_local_path            TEXT,
    final_sha256                TEXT,
    final_duration_s            REAL,
    product_id                  TEXT,
    product_name                TEXT,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_video_job_project ON video_production_job(project_id);

-- DB-LEVEL idempotency for every credit-consuming side effect (initial/extend/
-- concat). The PRIMARY KEY makes reserve-before-submit atomic: two tabs/processes
-- racing the same operation cannot both win. submission_state/credit_state/
-- retry_safety are the STRUCTURED truth the UI reads (never string parsing).
CREATE TABLE IF NOT EXISTS video_job_side_effect (
    idempotency_key         TEXT PRIMARY KEY,
    job_id                  TEXT NOT NULL,
    stage                   TEXT NOT NULL,
    submission_state        TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED',
    credit_state            TEXT NOT NULL DEFAULT 'NOT_SPENT',
    retry_safety            TEXT NOT NULL DEFAULT 'SAFE',
    operation_ref           TEXT,
    effective_submit_count  INTEGER NOT NULL DEFAULT 0,
    detail                  TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_video_side_effect_job ON video_job_side_effect(job_id, stage);
""")
        await db.commit()

        # Migration: video_production_job durable-identity + lifecycle-owner columns
        # (create-before-initial). Additive; older rows read NULL and stay inert.
        cursor = await db.execute("PRAGMA table_info(video_production_job)")
        vj_cols = {row[1] for row in await cursor.fetchall()}
        for col, decl in (
            ("logical_job_key", "TEXT"), ("execution_package_id", "TEXT"),
            ("approved_asset_id", "TEXT"), ("approved_asset_sha256", "TEXT"),
            ("engine", "TEXT"), ("model", "TEXT"), ("aspect_ratio", "TEXT"),
            ("plan_fingerprint", "TEXT"), ("whole_plan_json", "TEXT"),
            ("authorization_token", "TEXT"), ("authorization_expires_at", "TEXT"),
            ("initial_operation_id", "TEXT"), ("initial_workflow_id", "TEXT"),
            ("extend_child_operation_id", "TEXT"), ("extend_child_workflow_id", "TEXT"),
            ("stage_state_json", "TEXT"),
            # Production wiring (PR315 final): the reviewed, fingerprint-bound
            # authority the job actually runs. The initial adapter and each Extend
            # use THESE persisted prompts — never a generic fallback.
            ("initial_mode", "TEXT"), ("initial_prompt_text", "TEXT"),
            ("initial_prompt_fingerprint", "TEXT"), ("initial_asset_media_id", "TEXT"),
            ("continuation_prompts_json", "TEXT"),
            # True single-use authorization: consumed ATOMICALLY at start.
            ("authorization_id", "TEXT"), ("authorization_issued_at", "TEXT"),
            ("authorization_consumed_at", "TEXT"),
            ("authorization_consumed_by_job_id", "TEXT"),
            ("authorization_consumed_plan_fingerprint", "TEXT"),
            # PR316 durable make_video boundary: the in-flight one-door lane handle is
            # persisted the instant a submit is accepted, so a mid-flight crash never
            # loses the (possibly credit-spending) job — resume polls this handle,
            # never re-submits.
            ("initial_lane_job_id", "TEXT"), ("initial_lane_project_id", "TEXT"),
            # Unified all-mode contract: the ORDERED reference media ids block-1
            # actually sends (F2V 1-2 / HYBRID 1 / I2V 2-3 / T2V 0).
            ("initial_reference_media_ids_json", "TEXT"),
            # PR321 closure: SERVER-OWNED canonical surface mode (from the package's
            # compiler lineage) + the exact-output correlation evidence of block 1.
            ("initial_source_mode", "TEXT"),
            ("initial_correlation_json", "TEXT"),
        ):
            if col not in vj_cols:
                await db.execute(f"ALTER TABLE video_production_job ADD COLUMN {col} {decl}")
        # unique logical identity — created AFTER the column exists
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_video_job_logical_key "
            "ON video_production_job(logical_job_key)")
        await db.commit()

        # Migration: authoritative credit-debit evidence per side effect. Balance
        # before/after lets credit_state be SPENT only when a real debit is proven,
        # not merely because a call returned. Additive; NULL when unknown.
        cursor = await db.execute("PRAGMA table_info(video_job_side_effect)")
        se_cols = {row[1] for row in await cursor.fetchall()}
        for col, decl in (("credit_balance_before", "REAL"),
                          ("credit_balance_after", "REAL")):
            if col not in se_cols:
                await db.execute(
                    f"ALTER TABLE video_job_side_effect ADD COLUMN {col} {decl}")
        await db.commit()

        # Migration: generated_artifact.scene_id — durable scene evidence so the
        # Extend source resolver can verify clips without a (non-existent) scenes
        # listing endpoint. Nullable; filled by orchestration when a scene is known.
        cursor = await db.execute("PRAGMA table_info(generated_artifact)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "scene_id" not in columns:
            await db.execute("ALTER TABLE generated_artifact ADD COLUMN scene_id TEXT")
            logger.info("Migrated: added scene_id column to generated_artifact")
        await db.commit()

        # COPYWRITING HUB seed ledger. This is intentionally separate from
        # product truth and copy_set: imported workbook text is review-only
        # evidence, never an approved production copy mutation.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS copy_intelligence_seed (
    seed_id                     TEXT PRIMARY KEY,
    source_fingerprint          TEXT NOT NULL UNIQUE,
    source_workbook             TEXT NOT NULL,
    source_sheet                TEXT NOT NULL,
    source_row                  INTEGER NOT NULL,
    source_product_name         TEXT NOT NULL,
    reference_id                TEXT,
    target_product_id           TEXT REFERENCES product(id) ON DELETE SET NULL,
    match_method                TEXT NOT NULL,
    confidence                  TEXT NOT NULL CHECK(confidence IN ('HIGH','MEDIUM','LOW')),
    status                      TEXT NOT NULL CHECK(status IN ('SEEDED','NEEDS_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
    target_avatar               TEXT,
    pain_point                  TEXT,
    emotion_trigger             TEXT,
    dream_outcome               TEXT,
    key_ingredients_features    TEXT,
    hook_type                   TEXT,
    hook_script                 TEXT,
    body_script                 TEXT,
    cta_type                    TEXT,
    cta_script                  TEXT,
    tone                        TEXT,
    pronoun                     TEXT,
    copy_angle                  TEXT,
    provenance_json             TEXT NOT NULL DEFAULT '{}',
    reviewed_by                 TEXT,
    reviewed_at                 TEXT,
    review_note                 TEXT,
    previous_status             TEXT,
    review_action               TEXT,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_copy_intelligence_seed_reference
    ON copy_intelligence_seed(reference_id, status);
""")
        # Additive migration: human-review audit trail on existing seed ledgers.
        # Review-only metadata — it never exposes a row to generation.
        seed_cols_cursor = await db.execute("PRAGMA table_info(copy_intelligence_seed)")
        seed_cols = {row[1] for row in await seed_cols_cursor.fetchall()}
        for _col in ("reviewed_by", "reviewed_at", "review_note", "previous_status", "review_action"):
            if _col not in seed_cols:
                await db.execute(f"ALTER TABLE copy_intelligence_seed ADD COLUMN {_col} TEXT")
                logger.info("Migrated: added %s column to copy_intelligence_seed", _col)
        await db.commit()

        # Copy Set foundation (Copy Strategy Studio Phase 1). Additive table —
        # persists an explicitly-approvable Copy Set (product → angle / hook /
        # subhook / usp / cta) that later feeds the canonical prompt compiler as
        # copy intelligence. It never rewrites the product or workspace tables;
        # approval is explicit and fails closed on unsafe or incomplete copy.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS copy_set (
    copy_set_id       TEXT PRIMARY KEY,
    product_id        TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    angle             TEXT NOT NULL DEFAULT '',
    hook              TEXT NOT NULL DEFAULT '',
    subhook           TEXT NOT NULL DEFAULT '',
    usp_set_json      TEXT NOT NULL DEFAULT '[]',
    cta               TEXT NOT NULL DEFAULT '',
    platform          TEXT NOT NULL DEFAULT 'TIKTOK',
    language          TEXT NOT NULL DEFAULT 'BM_MS',
    route_type        TEXT NOT NULL DEFAULT 'DIRECT',
    formula_family    TEXT NOT NULL DEFAULT 'HSO',
    status            TEXT NOT NULL DEFAULT 'DRAFT_COPY'
                      CHECK(status IN ('DRAFT_COPY','COPY_REVIEW_REQUIRED','COPY_APPROVED','COPY_REJECTED')),
    dedupe_key        TEXT NOT NULL DEFAULT '',
    source            TEXT NOT NULL DEFAULT '',
    provenance_json   TEXT NOT NULL DEFAULT '{}',
    claim_review_json TEXT NOT NULL DEFAULT '{}',
    reviewer_note     TEXT,
    approved_at       TEXT,
    approved_by       TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_copy_set_product ON copy_set(product_id, status);
CREATE INDEX IF NOT EXISTS idx_copy_set_dedupe ON copy_set(dedupe_key);
""")
        await db.commit()

        # Copy Intelligence Phase 1 — additive columns on copy_set (usage,
        # fatigue, similarity, archival). Never alters the status CHECK
        # constraint or existing compiler-bound fields.
        cursor = await db.execute("PRAGMA table_info(copy_set)")
        copy_set_columns = {row[1] for row in await cursor.fetchall()}
        for col, typedef in [
            ("usage_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_used_at", "TEXT"),
            ("used_in_modes", "TEXT NOT NULL DEFAULT '[]'"),
            ("uniqueness_score", "REAL"),
            ("similar_to_copy_set_id", "TEXT"),
            ("similarity_score", "REAL"),
            ("archived", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in copy_set_columns:
                await db.execute(f"ALTER TABLE copy_set ADD COLUMN {col} {typedef}")
                logger.info("Migrated: added %s column to copy_set table", col)

        # Copy Intelligence Phase 1 — batch generation ledger.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS copy_generation_batch (
    batch_id          TEXT PRIMARY KEY,
    product_id        TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    requested_count   INTEGER NOT NULL,
    created_count     INTEGER NOT NULL,
    deduped_count     INTEGER NOT NULL,
    rejected_count    INTEGER NOT NULL,
    source            TEXT NOT NULL,
    provider_lane     TEXT,
    provider_model    TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_copy_generation_batch_product
    ON copy_generation_batch(product_id, created_at);
""")
        await db.commit()

        # Copy Intelligence Phase 1 — avatar-product fit mapping.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS avatar_product_fit (
    avatar_code       TEXT NOT NULL,
    product_category  TEXT NOT NULL,
    fit_score         REAL NOT NULL DEFAULT 1.0,
    suitability_notes TEXT,
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (avatar_code, product_category)
);
""")
        await db.commit()

        # Migrate: ensure updated_at exists on new tables (Phase 1 additive).
        for tbl in ("copy_generation_batch", "avatar_product_fit"):
            cursor = await db.execute(f"PRAGMA table_info({tbl})")
            tbl_columns = {row[1] for row in await cursor.fetchall()}
            if tbl_columns and "updated_at" not in tbl_columns:
                await db.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN updated_at "
                    "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
                )
                logger.info("Migrated: added updated_at column to %s table", tbl)

        # Creative Intelligence Round 2 — read-only Scene / Image Prompt library.
        # Config/reference table only: reconciled workbook IMAGE_PROMPTS templates
        # keyed on the canonical creative cluster. Placeholders [AVATAR]/[PRODUCT]
        # are stored unresolved; nothing here feeds generation.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS creative_scene_prompt (
    template_id                TEXT PRIMARY KEY,
    cluster                    TEXT NOT NULL,
    source_category            TEXT,
    cluster_source             TEXT,
    main_action                TEXT,
    setting                    TEXT,
    full_prompt_template       TEXT,
    base_prompt                TEXT,
    combined_prompt_suggestion TEXT,
    negative_prompt            TEXT,
    variant                    TEXT,
    notes                      TEXT,
    provenance                 TEXT,
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_creative_scene_prompt_cluster
    ON creative_scene_prompt(cluster);
""")
        await db.commit()

        # Creative Intelligence Round 3 — read-only Camera / Video Preset library.
        # Config/reference table only: named HOOK/BODY/CTA/TRANS presets ingested
        # from the workbook CameraSettings sheet. Reference-only — nothing here is
        # written to product camera columns or fed to generation.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS creative_camera_preset (
    preset_code     TEXT PRIMARY KEY,
    preset_name     TEXT,
    shot_type       TEXT,
    distance_angle  TEXT,
    movement        TEXT,
    block_group     TEXT,
    provenance      TEXT,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_creative_camera_preset_block
    ON creative_camera_preset(block_group);
""")
        await db.commit()

        # Product Intelligence Snapshot foundation (Product Intelligence Backbone
        # PR 1). Durable sidecar storage only — this does not change product-row
        # truth, registration commit behavior, or ProductTruthService.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS product_intelligence_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','APPROVED','SUPERSEDED','REJECTED','ARCHIVED')),
    product_description TEXT,
    benefits_json TEXT NOT NULL DEFAULT '[]',
    usp_json TEXT NOT NULL DEFAULT '[]',
    usage_text TEXT,
    ingredients_text TEXT,
    warnings_text TEXT,
    target_customer_text TEXT,
    paste_anything_summary TEXT,
    source_urls_json TEXT NOT NULL DEFAULT '{}',
    image_evidence_json TEXT NOT NULL DEFAULT '{}',
    package_notes TEXT,
    size_or_volume TEXT,
    product_form_factor TEXT,
    packaging_description TEXT,
    product_truth_lock TEXT,
    claim_gate TEXT,
    claim_risk_level TEXT,
    claim_tokens_json TEXT NOT NULL DEFAULT '[]',
    allowed_claims_json TEXT NOT NULL DEFAULT '[]',
    blocked_claims_json TEXT NOT NULL DEFAULT '[]',
    buyer_persona_snapshot_json TEXT NOT NULL DEFAULT '{}',
    copy_strategy_summary_json TEXT NOT NULL DEFAULT '{}',
    confidence_score REAL,
    completeness_score REAL,
    readiness_status TEXT,
    created_from_review_draft_id TEXT,
    created_by TEXT,
    approved_by TEXT,
    approved_at TEXT,
    supersedes_snapshot_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, version)
);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_snapshot_product_status_version
    ON product_intelligence_snapshot(product_id, status, version);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_snapshot_product_created_at
    ON product_intelligence_snapshot(product_id, created_at);

CREATE TABLE IF NOT EXISTS product_intelligence_field_provenance (
    provenance_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES product_intelligence_snapshot(snapshot_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    declared_value TEXT,
    normalized_value TEXT,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_lane TEXT,
    evidence_kind TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    confidence_score REAL,
    verification_status TEXT NOT NULL,
    claim_risk_flag TEXT,
    reviewer_decision TEXT,
    reviewer_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_field_provenance_snapshot
    ON product_intelligence_field_provenance(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_field_provenance_product
    ON product_intelligence_field_provenance(product_id);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_field_provenance_product_field
    ON product_intelligence_field_provenance(product_id, field_name);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_field_provenance_snapshot_field
    ON product_intelligence_field_provenance(snapshot_id, field_name);

CREATE TABLE IF NOT EXISTS product_intelligence_review_draft (
    draft_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    review_status TEXT NOT NULL CHECK(review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION','REJECTED','APPROVED')),
    product_description TEXT,
    benefits_json TEXT NOT NULL DEFAULT '[]',
    usp_json TEXT NOT NULL DEFAULT '[]',
    usage_text TEXT,
    ingredients_text TEXT,
    warnings_text TEXT,
    target_customer_text TEXT,
    paste_anything_summary TEXT,
    source_urls_json TEXT NOT NULL DEFAULT '{}',
    image_evidence_json TEXT NOT NULL DEFAULT '{}',
    package_notes TEXT,
    size_or_volume TEXT,
    product_form_factor TEXT,
    packaging_description TEXT,
    product_truth_lock TEXT,
    claim_gate TEXT,
    claim_risk_level TEXT,
    claim_tokens_json TEXT NOT NULL DEFAULT '[]',
    allowed_claims_json TEXT NOT NULL DEFAULT '[]',
    blocked_claims_json TEXT NOT NULL DEFAULT '[]',
    buyer_persona_snapshot_json TEXT NOT NULL DEFAULT '{}',
    copy_strategy_summary_json TEXT NOT NULL DEFAULT '{}',
    confidence_score REAL,
    completeness_score REAL,
    readiness_status TEXT,
    reviewer_note TEXT,
    created_by TEXT,
    reviewed_by TEXT,
    approved_by TEXT,
    approved_at TEXT,
    rejected_by TEXT,
    rejected_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_draft_product_status
    ON product_intelligence_review_draft(product_id, review_status, created_at);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_draft_product_updated
    ON product_intelligence_review_draft(product_id, updated_at);

CREATE TABLE IF NOT EXISTS product_intelligence_review_field_provenance (
    review_provenance_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES product_intelligence_review_draft(draft_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    declared_value TEXT,
    normalized_value TEXT,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_lane TEXT,
    evidence_kind TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    confidence_score REAL,
    verification_status TEXT NOT NULL,
    claim_risk_flag TEXT,
    reviewer_decision TEXT,
    reviewer_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_field_provenance_draft
    ON product_intelligence_review_field_provenance(draft_id);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_field_provenance_product
    ON product_intelligence_review_field_provenance(product_id);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_field_provenance_draft_field
    ON product_intelligence_review_field_provenance(draft_id, field_name);
""")
        await db.commit()

        # Google Flow bulk generation orchestrator (V1): persistent runs + items.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS bulk_generation_run (
    bulk_run_id             TEXT PRIMARY KEY,
    kind                    TEXT NOT NULL
                            CHECK(kind IN ('AVATAR_IMAGE','IMG','VIDEO','MIXED')),
    status                  TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK(status IN ('PENDING','RUNNING','COMPLETED','PARTIAL_FAILED','FAILED','CANCELLED','PAUSED')),
    total_expected          INTEGER NOT NULL DEFAULT 0,
    total_completed         INTEGER NOT NULL DEFAULT 0,
    total_failed            INTEGER NOT NULL DEFAULT 0,
    max_parallel_images     INTEGER NOT NULL DEFAULT 2,
    max_parallel_videos     INTEGER NOT NULL DEFAULT 1,
    confirm_credit_burn     INTEGER NOT NULL DEFAULT 0,
    interval_min_seconds    INTEGER NOT NULL DEFAULT 5,
    interval_max_seconds    INTEGER NOT NULL DEFAULT 15,
    cooldown_after_n_jobs   INTEGER NOT NULL DEFAULT 5,
    cooldown_seconds        INTEGER NOT NULL DEFAULT 60,
    error_log_json          TEXT NOT NULL DEFAULT '[]',
    config_json             TEXT NOT NULL DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS bulk_generation_item (
    bulk_item_id            TEXT PRIMARY KEY,
    bulk_run_id             TEXT NOT NULL,
    item_type               TEXT NOT NULL
                            CHECK(item_type IN ('AVATAR_IMAGE','IMG','T2V','I2V','F2V')),
    source_ref              TEXT NOT NULL,
    prompt_snapshot         TEXT,
    payload_json            TEXT NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'QUEUED'
                            CHECK(status IN ('QUEUED','SUBMITTED','RUNNING','GENERATED','DOWNLOADED','REGISTERED','FAILED','CANCELLED')),
    job_id                  TEXT,
    media_id                TEXT,
    local_path              TEXT,
    creative_asset_id       TEXT,
    error                   TEXT,
    retry_count             INTEGER NOT NULL DEFAULT 0,
    started_at              TEXT,
    completed_at            TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_bulk_generation_item_run
    ON bulk_generation_item(bulk_run_id);
CREATE INDEX IF NOT EXISTS idx_bulk_generation_item_run_status
    ON bulk_generation_item(bulk_run_id, status);

-- Poster Copy Set (POSTER_BUILDER_V2) — poster-NATIVE copy domain, fully
-- separate from the video copy_set table. Statuses are namespaced
-- POSTER_COPY_* so poster copy can never enter video compilation/selection.
CREATE TABLE IF NOT EXISTS poster_copy_set (
    poster_copy_set_id      TEXT PRIMARY KEY,
    product_id              TEXT NOT NULL,
    campaign_id             TEXT NOT NULL DEFAULT '',
    objective               TEXT NOT NULL DEFAULT '',
    archetype               TEXT NOT NULL DEFAULT '',
    angle                   TEXT NOT NULL DEFAULT '',
    primary_message         TEXT NOT NULL DEFAULT '',
    support_message         TEXT NOT NULL DEFAULT '',
    proof_points_json       TEXT NOT NULL DEFAULT '[]',
    offer_json              TEXT,
    cta                     TEXT NOT NULL DEFAULT '',
    disclaimer              TEXT NOT NULL DEFAULT '',
    tone                    TEXT NOT NULL DEFAULT '',
    language                TEXT NOT NULL DEFAULT 'ms',
    variants_json           TEXT NOT NULL DEFAULT '[]',
    field_provenance_json   TEXT NOT NULL DEFAULT '{}',
    ai_model                TEXT NOT NULL DEFAULT '',
    prompt_version          TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'POSTER_COPY_DRAFT'
                            CHECK(status IN ('POSTER_COPY_DRAFT','POSTER_COPY_REVIEW_REQUIRED','POSTER_COPY_APPROVED','POSTER_COPY_REJECTED','POSTER_COPY_SUPERSEDED')),
    version                 INTEGER NOT NULL DEFAULT 1,
    parent_poster_copy_set_id TEXT NOT NULL DEFAULT '',
    archived                INTEGER NOT NULL DEFAULT 0,
    reject_reason           TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    approved_at             TEXT,
    approved_by             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_poster_copy_set_product
    ON poster_copy_set(product_id, status);

-- Poster Deliverable (POSTER_BUILDER_V2) — one generated/composited poster with
-- its full render manifest so preview/save identity, reconstruction and
-- Creative Library reopening survive the 48h generated_artifact purge.
CREATE TABLE IF NOT EXISTS poster_deliverable (
    poster_deliverable_id   TEXT PRIMARY KEY,
    product_id              TEXT NOT NULL,
    poster_copy_set_id      TEXT NOT NULL DEFAULT '',
    recipe_id               TEXT NOT NULL DEFAULT '',
    template_version        TEXT NOT NULL DEFAULT '',
    composition_strategy    TEXT NOT NULL DEFAULT 'REFERENCE_CONDITIONED'
                            CHECK(composition_strategy IN ('REFERENCE_CONDITIONED','DETERMINISTIC_COMPOSITE')),
    render_manifest_json    TEXT NOT NULL DEFAULT '{}',
    background_media_id     TEXT NOT NULL DEFAULT '',
    background_local_path   TEXT NOT NULL DEFAULT '',
    output_path             TEXT NOT NULL DEFAULT '',
    output_sha256           TEXT NOT NULL DEFAULT '',
    creative_asset_id       TEXT NOT NULL DEFAULT '',
    qa_report_json          TEXT NOT NULL DEFAULT '{}',
    settings_json           TEXT NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'POSTER_DRAFT'
                            CHECK(status IN ('POSTER_DRAFT','POSTER_COMPOSED','POSTER_SAVED')),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_poster_deliverable_product
    ON poster_deliverable(product_id, status);
""")
        await db.commit()

    logger.info("Database initialized at %s", DB_PATH)


async def get_db() -> aiosqlite.Connection:
    """Return the shared database connection, creating it if needed."""
    global _db_connection
    if _db_connection is None:
        _db_connection = await aiosqlite.connect(str(DB_PATH))
        _db_connection.row_factory = aiosqlite.Row
        await _db_connection.execute("PRAGMA journal_mode=WAL")
        await _db_connection.execute("PRAGMA foreign_keys=ON")
        await _db_connection.execute("PRAGMA busy_timeout=5000")
        # Force WAL checkpoint so this connection sees all committed writes
        # from previous processes (e.g. after hot-reload)
        await _db_connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    return _db_connection


async def close_db() -> None:
    """Close the shared database connection."""
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None
        logger.info("Database connection closed")
