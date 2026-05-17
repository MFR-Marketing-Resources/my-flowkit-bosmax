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
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    message       TEXT,
    source        TEXT NOT NULL CHECK(source IN ('dashboard','backend','worker','extension','google_flow'))
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
CREATE INDEX IF NOT EXISTS idx_batch_product ON batch(product_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_batch ON batch_variant(batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_variant_status ON batch_variant(queue_status);
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
            "claim_safe_copy_updated_at",
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
                            google_flow_stage, extension_stage, worker_stage, created_at, queued_at, started_at,
                            last_heartbeat_at, completed_at, failed_at, duration_seconds, idle_seconds,
                            processing_seconds, error_code, error_message
                        )
                        SELECT
                            request_id, project_id, video_id, scene_id, product_id, request_type, mode, status,
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
                            stage         TEXT NOT NULL,
                            status        TEXT NOT NULL,
                            message       TEXT,
                            source        TEXT NOT NULL CHECK(source IN ('dashboard','backend','worker','extension','google_flow'))
                        )
                    """)
                    _sync.execute("""
                        INSERT INTO request_stage_event_new (
                            id, request_id, timestamp, stage, status, message, source
                        )
                        SELECT
                            id, request_id, timestamp, stage, status, message, source
                        FROM request_stage_event
                    """)
                    _sync.execute("DROP TABLE request_stage_event")
                    _sync.execute("ALTER TABLE request_stage_event_new RENAME TO request_stage_event")
                    _sync.commit()
                    _sync.execute("PRAGMA foreign_keys=ON")
                    logger.info("Migrated: request_stage_event FK reference repaired")
                finally:
                    _sync.close()

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
