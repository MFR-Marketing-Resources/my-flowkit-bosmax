"""SQLite schema — async via aiosqlite."""
import asyncio
import contextlib
import aiosqlite
import logging
from agent.config import DB_PATH

logger = logging.getLogger(__name__)

_db_connection: aiosqlite.Connection | None = None


class _ReentrantDbLock:
    """`_db_lock` with re-entrancy for the task that already holds it.

    B-586-03. Every crud writer serializes on this lock and commits inside it, so a
    multi-statement operation could not be made atomic: wrapping the crud calls in an
    outer `async with _db_lock` deadlocked on the first inner acquire, and NOT wrapping
    them meant each crud call committed its own step, leaving partial state behind after a
    later failure.

    Re-entrancy is scoped to the owning asyncio task, so a DIFFERENT task still blocks
    exactly as `asyncio.Lock` did. Drop-in: same `async with` / `locked()` surface, so no
    crud call site changes.
    """

    __slots__ = ("_lock", "_owner", "_depth")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: object | None = None
        self._depth = 0

    async def acquire(self) -> bool:
        task = asyncio.current_task()
        if self._depth and self._owner is task:
            self._depth += 1
            return True
        await self._lock.acquire()
        self._owner = task
        self._depth = 1
        return True

    def release(self) -> None:
        if self._depth <= 0:
            raise RuntimeError("_db_lock released more times than acquired")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> "_ReentrantDbLock":
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def held_by_current_task(self) -> bool:
        return bool(self._depth) and self._owner is asyncio.current_task()


_db_lock = _ReentrantDbLock()


_BULK_GENERATION_RUN_KINDS = (
    "AVATAR_IMAGE",
    "IMG",
    "VIDEO",
    "MIXED",
    "MONTAGE_DISCRETE",
)
_BULK_GENERATION_RUN_STATUSES = (
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "PARTIAL_FAILED",
    "FAILED",
    "CANCELLED",
    "PAUSED",
    "PREPARED",
    "PARTIAL",
    "GENERATING",
    "COMPLETE",
    "ASSEMBLY_READY",
)
_BULK_GENERATION_ITEM_TYPES = (
    "AVATAR_IMAGE",
    "IMG",
    "T2V",
    "I2V",
    "F2V",
    "MONTAGE_SCENE",
)
_BULK_GENERATION_ITEM_STATUSES = (
    "QUEUED",
    "SUBMITTED",
    "RUNNING",
    "GENERATED",
    "DOWNLOADED",
    "REGISTERED",
    "FAILED",
    "CANCELLED",
    "PLANNED",
    "IMAGE_PENDING_PACKAGE",
    "IMAGE_PENDING",
    "IMAGE_READY",
    "IMAGE_BOUND",
    "PACKAGE_READY",
    "PACKAGE_FAILED",
    "VIDEO_SUBMITTED",
    "VIDEO_READY",
    "GENERATE_RETURNED",
    "GENERATE_FAILED",
    "RESULT_BOUND",
    "BLOCKED",
    "SKIPPED_VIDEO",
)
_BULK_GENERATION_RUN_COLUMNS = (
    "bulk_run_id",
    "kind",
    "status",
    "total_expected",
    "total_completed",
    "total_failed",
    "max_parallel_images",
    "max_parallel_videos",
    "confirm_credit_burn",
    "interval_min_seconds",
    "interval_max_seconds",
    "cooldown_after_n_jobs",
    "cooldown_seconds",
    "error_log_json",
    "config_json",
    "created_at",
    "updated_at",
)
_BULK_GENERATION_ITEM_COLUMNS = (
    "bulk_item_id",
    "bulk_run_id",
    "item_type",
    "source_ref",
    "prompt_snapshot",
    "payload_json",
    "status",
    "job_id",
    "media_id",
    "local_path",
    "creative_asset_id",
    "error",
    "retry_count",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
)


def _check_values_sql(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def _bulk_generation_run_table_sql(table_name: str) -> str:
    return f"""
CREATE TABLE {table_name} (
    bulk_run_id             TEXT PRIMARY KEY,
    kind                    TEXT NOT NULL
                            CHECK(kind IN ({_check_values_sql(_BULK_GENERATION_RUN_KINDS)})),
    status                  TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK(status IN ({_check_values_sql(_BULK_GENERATION_RUN_STATUSES)})),
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
    config_json             TEXT NOT NULL DEFAULT '{{}}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
)
"""


def _bulk_generation_item_table_sql(table_name: str) -> str:
    return f"""
CREATE TABLE {table_name} (
    bulk_item_id            TEXT PRIMARY KEY,
    bulk_run_id             TEXT NOT NULL,
    item_type               TEXT NOT NULL
                            CHECK(item_type IN ({_check_values_sql(_BULK_GENERATION_ITEM_TYPES)})),
    source_ref              TEXT NOT NULL,
    prompt_snapshot         TEXT,
    payload_json            TEXT NOT NULL DEFAULT '{{}}',
    status                  TEXT NOT NULL DEFAULT 'QUEUED'
                            CHECK(status IN ({_check_values_sql(_BULK_GENERATION_ITEM_STATUSES)})),
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
)
"""


def _bulk_generation_table_sql(connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _bulk_generation_table_indexes(connection, table_name: str) -> list[str]:
    rows = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_autoindex_%' ORDER BY name",
        (table_name,),
    ).fetchall()
    return [str(row[0]) for row in rows if row[0]]


def _assert_bulk_generation_columns(
    connection,
    table_name: str,
    expected_columns: tuple[str, ...],
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    actual_columns = tuple(str(row[1]) for row in rows)
    if actual_columns != expected_columns:
        raise RuntimeError(
            f"MONTAGE_LEDGER_SCHEMA_UNRECOGNIZED:{table_name}:"
            f"expected={expected_columns}:actual={actual_columns}"
        )


def _bulk_generation_ledger_needs_migration(connection) -> bool:
    run_sql = _bulk_generation_table_sql(connection, "bulk_generation_run")
    item_sql = _bulk_generation_table_sql(connection, "bulk_generation_item")
    if not run_sql or not item_sql:
        return False
    return not (
        all(f"'{value}'" in run_sql for value in _BULK_GENERATION_RUN_KINDS)
        and all(f"'{value}'" in run_sql for value in _BULK_GENERATION_RUN_STATUSES)
        and all(f"'{value}'" in item_sql for value in _BULK_GENERATION_ITEM_TYPES)
        and all(f"'{value}'" in item_sql for value in _BULK_GENERATION_ITEM_STATUSES)
    )


def _migrate_bulk_generation_ledger(db_path: str) -> bool:
    """Rebuild the shared bulk ledger when its CHECK contract is stale.

    SQLite cannot alter CHECK constraints.  The migration is deliberately
    synchronous so PRAGMA foreign_keys can be disabled before BEGIN IMMEDIATE;
    init_db has already committed the aiosqlite connection before calling this.
    """
    if str(db_path) == ":memory:":
        return False

    import sqlite3

    connection = sqlite3.connect(str(db_path), timeout=60)
    migrated = False
    run_new = "bulk_generation_run__montage_new"
    item_new = "bulk_generation_item__montage_new"
    run_old = "bulk_generation_run__montage_old"
    item_old = "bulk_generation_item__montage_old"
    try:
        if not _bulk_generation_ledger_needs_migration(connection):
            return False
        _assert_bulk_generation_columns(
            connection, "bulk_generation_run", _BULK_GENERATION_RUN_COLUMNS
        )
        _assert_bulk_generation_columns(
            connection, "bulk_generation_item", _BULK_GENERATION_ITEM_COLUMNS
        )
        for table_name in (run_new, item_new, run_old, item_old):
            if _bulk_generation_table_sql(connection, table_name):
                raise RuntimeError(
                    f"MONTAGE_LEDGER_MIGRATION_RESIDUE:{table_name}"
                )

        run_indexes = _bulk_generation_table_indexes(connection, "bulk_generation_run")
        item_indexes = _bulk_generation_table_indexes(connection, "bulk_generation_item")
        quoted_run_columns = ", ".join(f'"{column}"' for column in _BULK_GENERATION_RUN_COLUMNS)
        quoted_item_columns = ", ".join(f'"{column}"' for column in _BULK_GENERATION_ITEM_COLUMNS)

        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA legacy_alter_table=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_bulk_generation_run_table_sql(run_new))
        connection.execute(_bulk_generation_item_table_sql(item_new))
        connection.execute(
            f"INSERT INTO {run_new} ({quoted_run_columns}) "
            f"SELECT {quoted_run_columns} FROM bulk_generation_run"
        )
        connection.execute(
            f"INSERT INTO {item_new} ({quoted_item_columns}) "
            f"SELECT {quoted_item_columns} FROM bulk_generation_item"
        )
        connection.execute("ALTER TABLE bulk_generation_run RENAME TO " + run_old)
        connection.execute("ALTER TABLE bulk_generation_item RENAME TO " + item_old)
        connection.execute("ALTER TABLE " + run_new + " RENAME TO bulk_generation_run")
        connection.execute("ALTER TABLE " + item_new + " RENAME TO bulk_generation_item")
        connection.execute("DROP TABLE " + item_old)
        connection.execute("DROP TABLE " + run_old)
        for index_sql in (*run_indexes, *item_indexes):
            connection.execute(index_sql)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_bulk_generation_item_run "
            "ON bulk_generation_item(bulk_run_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_bulk_generation_item_run_status "
            "ON bulk_generation_item(bulk_run_id, status)"
        )
        connection.commit()
        migrated = True
        logger.info("Migrated: rebuilt bulk generation ledger for Montage lifecycle")
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA legacy_alter_table=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.close()
    return migrated


@contextlib.asynccontextmanager
async def atomic():
    """Run several crud writes as ONE transaction: all of them commit, or none do.

    B-586-03. `create_review_draft` and the provenance batch were separate transactions,
    so a failure between them left a committed draft with no provenance and the code had
    to "compensate" by deleting rows afterwards — a cleanup that could not tell its own
    partial work from a concurrent request's finished work.

    Mechanics: the boundary holds the (re-entrant) write lock for its whole body, so no
    other task can be inside a crud write section at the same time, and inner
    `await db.commit()` calls are suspended for the duration. One commit on success, one
    rollback on failure. Because no other task can write while the lock is held, that
    rollback can only ever discard THIS boundary's own statements.

    Nested use is safe: an inner `atomic()` joins the outer transaction rather than
    committing early.
    """
    db = await get_db()
    async with _db_lock:
        if getattr(db, "_flowkit_atomic_depth", 0):
            # already inside a boundary on this task — join it, do not commit here
            db._flowkit_atomic_depth += 1
            try:
                yield db
            finally:
                db._flowkit_atomic_depth -= 1
            return
        real_commit = db.commit

        async def _suspended_commit() -> None:
            return None

        db.commit = _suspended_commit  # type: ignore[method-assign]
        db._flowkit_atomic_depth = 1
        try:
            yield db
        except BaseException:
            db.commit = real_commit  # type: ignore[method-assign]
            db._flowkit_atomic_depth = 0
            await db.rollback()
            raise
        else:
            db.commit = real_commit  # type: ignore[method-assign]
            db._flowkit_atomic_depth = 0
            await db.commit()

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
    bosmax_product_family TEXT,
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

-- Server-owned visual identity contract.  This is intentionally separate from
-- prompt/product metadata: exact IMG output is allowed only when these bytes,
-- masks, bounds, and review gates validate at generation time.
CREATE TABLE IF NOT EXISTS product_visual_truth_lock (
    product_id              TEXT PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    canonical_media_id      TEXT NOT NULL,
    canonical_sha256        TEXT NOT NULL CHECK(length(canonical_sha256) = 64),
    source_width            INTEGER NOT NULL CHECK(source_width > 0),
    source_height           INTEGER NOT NULL CHECK(source_height > 0),
    canonical_source_path   TEXT NOT NULL,
    canonical_cutout_media_id TEXT NOT NULL,
    canonical_cutout_sha256 TEXT NOT NULL CHECK(length(canonical_cutout_sha256) = 64),
    canonical_cutout_path   TEXT NOT NULL,
    alpha_mask_json         TEXT NOT NULL DEFAULT '{}',
    anchor_point_json       TEXT NOT NULL DEFAULT '{}',
    min_scale               REAL NOT NULL CHECK(min_scale > 0),
    max_scale               REAL NOT NULL CHECK(max_scale > 0),
    allowed_bbox_json       TEXT NOT NULL DEFAULT '{}',
    allowed_rotation        REAL NOT NULL DEFAULT 0 CHECK(allowed_rotation >= 0 AND allowed_rotation <= 45),
    allowed_perspective     REAL NOT NULL DEFAULT 0 CHECK(allowed_perspective >= 0 AND allowed_perspective <= 1),
    identity_lock           INTEGER NOT NULL DEFAULT 0 CHECK(identity_lock IN (0,1)),
    geometry_lock           INTEGER NOT NULL DEFAULT 0 CHECK(geometry_lock IN (0,1)),
    label_lock              INTEGER NOT NULL DEFAULT 0 CHECK(label_lock IN (0,1)),
    logo_lock               INTEGER NOT NULL DEFAULT 0 CHECK(logo_lock IN (0,1)),
    colour_lock             INTEGER NOT NULL DEFAULT 0 CHECK(colour_lock IN (0,1)),
    scale_lock              INTEGER NOT NULL DEFAULT 0 CHECK(scale_lock IN (0,1)),
    review_status           TEXT NOT NULL DEFAULT 'DRAFT' CHECK(review_status IN ('DRAFT','PENDING_REVIEW','APPROVED','REJECTED')),
    failure_state           TEXT NOT NULL DEFAULT '',
    provenance_json         TEXT NOT NULL DEFAULT '{}',
    schema_version          TEXT NOT NULL DEFAULT '1.0',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_product_truth_lock_review ON product_visual_truth_lock(review_status);

-- Immutable audit history for replaced Product Truth candidates.  The active
-- contract remains the single product_visual_truth_lock row; this table only
-- preserves prior bytes and provenance for review, rejection, and supersession.
CREATE TABLE IF NOT EXISTS product_visual_truth_lock_history (
    history_id                  TEXT PRIMARY KEY,
    product_id                  TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    source_kind                 TEXT NOT NULL CHECK(source_kind IN ('AUTO_GENERATED','USER_UPLOAD','CANONICAL_REFERENCE')),
    review_status               TEXT NOT NULL,
    canonical_media_id          TEXT,
    canonical_sha256            TEXT,
    source_width                INTEGER,
    source_height               INTEGER,
    canonical_source_path       TEXT,
    canonical_cutout_media_id   TEXT,
    canonical_cutout_sha256     TEXT,
    canonical_cutout_path       TEXT,
    alpha_mask_json             TEXT NOT NULL DEFAULT '{}',
    anchor_point_json           TEXT NOT NULL DEFAULT '{}',
    allowed_bbox_json           TEXT NOT NULL DEFAULT '{}',
    provenance_json             TEXT NOT NULL DEFAULT '{}',
    superseded_by_media_id      TEXT,
    superseded_reason           TEXT,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_product_truth_lock_history_product
    ON product_visual_truth_lock_history(product_id, created_at DESC);

-- Provider-facing creative reference pack.  This is intentionally separate
-- from product_visual_truth_lock: exact compositor truth and generative
-- campaign evidence have different approval and QA lifecycles.
CREATE TABLE IF NOT EXISTS product_reference_pack (
    product_id              TEXT PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    pack_id                 TEXT NOT NULL UNIQUE,
    schema_version          TEXT NOT NULL DEFAULT 'product_reference_pack_v1',
    pack_status             TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(pack_status IN ('DRAFT','PENDING_REVIEW','APPROVED','REJECTED')),
    machine_qa_status        TEXT NOT NULL DEFAULT 'WARN'
        CHECK(machine_qa_status IN ('PASS','WARN','FAIL')),
    machine_qa_json          TEXT NOT NULL DEFAULT '{}',
    physical_width_mm       REAL,
    physical_height_mm      REAL,
    physical_depth_mm       REAL,
    volume_ml               REAL,
    scale_evidence_source   TEXT NOT NULL DEFAULT 'UNVERIFIED',
    scale_confidence        TEXT NOT NULL DEFAULT 'UNVERIFIED'
        CHECK(scale_confidence IN ('UNVERIFIED','LOW','MEDIUM','HIGH')),
    geometry_json            TEXT NOT NULL DEFAULT '{}',
    references_json          TEXT NOT NULL DEFAULT '[]',
    provenance_json          TEXT NOT NULL DEFAULT '{}',
    human_review_json        TEXT NOT NULL DEFAULT '{}',
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_product_reference_pack_status
    ON product_reference_pack(pack_status, updated_at);

-- Deterministic product cutout preparation receipt.  This is operational
-- evidence only; product_visual_truth_lock remains the exact-IMG authority and
-- its APPROVED state can only be reached through the explicit human gate.
CREATE TABLE IF NOT EXISTS product_cutout_preparation (
    product_id       TEXT PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'NOT_PREPARED'
        CHECK(status IN ('NOT_PREPARED','PREPARING','PENDING_REVIEW','APPROVED','PREPARATION_FAILED','BLOCKED')),
    source_sha256    TEXT,
    cutout_media_id  TEXT,
    cutout_sha256    TEXT,
    failure_code     TEXT,
    failure_message  TEXT,
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    last_started_at  TEXT,
    last_finished_at TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_product_cutout_preparation_status
    ON product_cutout_preparation(status, updated_at);

-- Bounded, provider-free bulk preparation progress.  Product IDs are a frozen
-- preview receipt, not a free-form client-side selection; the execution worker
-- re-checks every identity/lifecycle gate before touching a row.
CREATE TABLE IF NOT EXISTS product_visual_onboarding_run (
    run_id              TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'PREVIEW'
        CHECK(status IN ('PREVIEW','QUEUED','RUNNING','COMPLETED','PARTIAL_FAILED','FAILED')),
    total_expected      INTEGER NOT NULL DEFAULT 0,
    total_processed     INTEGER NOT NULL DEFAULT 0,
    total_pending_review INTEGER NOT NULL DEFAULT 0,
    total_failed        INTEGER NOT NULL DEFAULT 0,
    total_blocked       INTEGER NOT NULL DEFAULT 0,
    total_skipped       INTEGER NOT NULL DEFAULT 0,
    batch_size          INTEGER NOT NULL DEFAULT 5,
    product_ids_json    TEXT NOT NULL DEFAULT '[]',
    error_log_json      TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_product_visual_onboarding_run_status
    ON product_visual_onboarding_run(status, updated_at);

-- Canva-assisted cutout workflow ledger.  Canva UI work remains operator- or
-- browser-controller-owned; this table persists only bounded workflow
-- evidence and never stores credentials, cookies, or provider session data.
CREATE TABLE IF NOT EXISTS canva_cutout_workflow (
    product_id          TEXT PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    workflow_id         TEXT NOT NULL UNIQUE,
    source_sha256       TEXT NOT NULL CHECK(length(source_sha256) = 64),
    source_width        INTEGER NOT NULL CHECK(source_width > 0),
    source_height       INTEGER NOT NULL CHECK(source_height > 0),
    canva_method        TEXT NOT NULL DEFAULT 'UNSELECTED'
                        CHECK(canva_method IN ('UNSELECTED','MAGIC_GRAB','BACKGROUND_REMOVER','MAGIC_LAYERS')),
    design_id           TEXT,
    design_url          TEXT,
    current_stage       TEXT NOT NULL DEFAULT 'NOT_STARTED'
                        CHECK(current_stage IN (
                            'NOT_STARTED','PREFLIGHT','CANVA_PRO_REQUIRED','OPENING_CANVA',
                            'MAGIC_GRAB','BACKGROUND_REMOVER','MAGIC_LAYERS','CLEAN_CANVAS',
                            'READY_TO_EXPORT','EXPORTING','VERIFYING_ALPHA','CUTOUT_READY',
                            'PENDING_HUMAN_REVIEW','APPROVED','FAILED','PAUSED','CANCELLED'
                        )),
    attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    last_error_code     TEXT,
    last_error          TEXT,
    preflight_json      TEXT NOT NULL DEFAULT '{}',
    output_path         TEXT,
    output_sha256       TEXT CHECK(output_sha256 IS NULL OR length(output_sha256) = 64),
    output_width        INTEGER CHECK(output_width IS NULL OR output_width > 0),
    output_height       INTEGER CHECK(output_height IS NULL OR output_height > 0),
    alpha_verified      INTEGER NOT NULL DEFAULT 0 CHECK(alpha_verified IN (0,1)),
    human_review_status TEXT NOT NULL DEFAULT 'NOT_STARTED'
                        CHECK(human_review_status IN ('NOT_STARTED','PENDING_REVIEW','APPROVED','REJECTED')),
    provenance_source   TEXT CHECK(provenance_source IS NULL OR provenance_source IN (
                            'CANVA_MAGIC_GRAB','CANVA_BG_REMOVER','CANVA_MAGIC_LAYERS'
                        )),
    started_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_canva_cutout_workflow_stage
    ON canva_cutout_workflow(current_stage, updated_at);

-- Resumable, optional Canva queue.  A run is a durable operator queue, not a
-- claim that BOSMAX drove Canva.  Item progress survives restart and permits
-- per-product bypass without disturbing the remaining cohort.
CREATE TABLE IF NOT EXISTS canva_cutout_bulk_run (
    run_id                   TEXT PRIMARY KEY,
    status                   TEXT NOT NULL DEFAULT 'PREVIEW'
                             CHECK(status IN ('PREVIEW','QUEUED','RUNNING','PAUSED',
                                 'BLOCKED_CANVA_PRO_REQUIRED','COMPLETED','FAILED','CANCELLED')),
    preview_digest            TEXT NOT NULL CHECK(length(preview_digest) = 64),
    total_expected            INTEGER NOT NULL DEFAULT 0,
    total_processed           INTEGER NOT NULL DEFAULT 0,
    total_ready               INTEGER NOT NULL DEFAULT 0,
    total_pending_review      INTEGER NOT NULL DEFAULT 0,
    total_failed              INTEGER NOT NULL DEFAULT 0,
    total_blocked             INTEGER NOT NULL DEFAULT 0,
    total_bypassed            INTEGER NOT NULL DEFAULT 0,
    next_index                INTEGER NOT NULL DEFAULT 0,
    product_ids_json          TEXT NOT NULL DEFAULT '[]',
    priority_product_ids_json TEXT NOT NULL DEFAULT '[]',
    preflight_json            TEXT NOT NULL DEFAULT '{}',
    last_error_code           TEXT,
    last_error                TEXT,
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_canva_cutout_bulk_run_status
    ON canva_cutout_bulk_run(status, updated_at);

CREATE TABLE IF NOT EXISTS canva_cutout_bulk_item (
    item_id             TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES canva_cutout_bulk_run(run_id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    ordinal             INTEGER NOT NULL CHECK(ordinal >= 0),
    priority            INTEGER NOT NULL DEFAULT 0,
    workflow_id         TEXT,
    current_stage       TEXT NOT NULL DEFAULT 'NOT_STARTED'
                        CHECK(current_stage IN (
                            'NOT_STARTED','PREFLIGHT','CANVA_PRO_REQUIRED','OPENING_CANVA',
                            'MAGIC_GRAB','BACKGROUND_REMOVER','MAGIC_LAYERS','CLEAN_CANVAS',
                            'READY_TO_EXPORT','EXPORTING','VERIFYING_ALPHA','CUTOUT_READY',
                            'PENDING_HUMAN_REVIEW','APPROVED','FAILED','PAUSED','CANCELLED','BYPASSED'
                        )),
    last_error          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(run_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_canva_cutout_bulk_item_run
    ON canva_cutout_bulk_item(run_id, ordinal);

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

-- Operator-uploaded source media for Smart Registration (ADDITIVE — separate from
-- the single primary image_url/local_image_path lane, which is untouched). Holds
-- up to 10 extra images + 3 videos per draft; product_id is back-filled at commit.
CREATE TABLE IF NOT EXISTS product_source_media (
    media_id      TEXT PRIMARY KEY,
    draft_id      TEXT NOT NULL,
    product_id    TEXT REFERENCES product(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK(kind IN ('image','video')),
    ordinal       INTEGER NOT NULL DEFAULT 0,
    local_path    TEXT,
    remote_url    TEXT,
    filename      TEXT,
    mime          TEXT,
    bytes         INTEGER,
    width         INTEGER,
    height        INTEGER,
    duration_sec  REAL,
    status        TEXT NOT NULL DEFAULT 'STORED',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_source_media_draft ON product_source_media(draft_id);
CREATE INDEX IF NOT EXISTS idx_product_source_media_product ON product_source_media(product_id, kind);

CREATE TABLE IF NOT EXISTS fastmoss_bulk_draft_status (
    reference_id        TEXT PRIMARY KEY,
    raw_product_title   TEXT NOT NULL,
    source_url          TEXT,
    tiktok_product_url  TEXT,
    image_url           TEXT,
    category            TEXT,
    cluster             TEXT,
    product_type_group  TEXT,
    claim_risk_level    TEXT NOT NULL DEFAULT 'HIGH',
    mapping_confidence  REAL,
    image_readiness     TEXT NOT NULL DEFAULT 'IMAGE_MISSING',
    copy_route          TEXT,
    sold_count          INTEGER,
    commission_rate     TEXT,
    sell_price          REAL,
    commission_amount   REAL,
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
    ruleset_version     TEXT,
    input_fingerprint   TEXT,
    computed_ruleset_version TEXT,
    computed_input_fingerprint TEXT,
    recompute_state     TEXT NOT NULL DEFAULT 'STALE',
    recompute_reason    TEXT,
    review_hold_reason  TEXT,
    recompute_started_at TEXT,
    recompute_attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bulk_draft_status ON fastmoss_bulk_draft_status(promotion_status);
CREATE INDEX IF NOT EXISTS idx_bulk_draft_risk ON fastmoss_bulk_draft_status(claim_risk_level);
-- Created after additive migration below so legacy databases without
-- recompute_state can run this schema script safely.

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

-- Per-submit provenance for bounded Creative Campaign image operations.  The
-- local record id is deliberately separate from provider_operation_id: a
-- missing provider id remains UNPROVEN rather than being fabricated.
CREATE TABLE IF NOT EXISTS image_generation_operation (
    operation_record_id       TEXT PRIMARY KEY,
    job_id                    TEXT NOT NULL,
    product_id                TEXT,
    mode                      TEXT NOT NULL DEFAULT 'IMG',
    provider                  TEXT NOT NULL DEFAULT 'GOOGLE_FLOW',
    model                     TEXT,
    variant_index             INTEGER NOT NULL,
    provider_operation_id     TEXT,
    transport_batch_id        TEXT,
    operation_id_status       TEXT NOT NULL,
    provider_media_id         TEXT,
    response_status           TEXT NOT NULL,
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_image_generation_operation_job
    ON image_generation_operation(job_id, variant_index);
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
    bosmax_product_family TEXT,
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
        if "bosmax_product_family" not in product_columns:
            await db.execute("ALTER TABLE product ADD COLUMN bosmax_product_family TEXT")
            logger.info("Migrated: added bosmax_product_family column to product table")

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

        # Cost/engine instrumentation (BOSMAX Command Centre): capture per-generation
        # provider/engine/model + credit estimates on the durable, every-outcome
        # telemetry ledger so the (deferred) cost dashboard has history. Additive and
        # nullable — older rows read NULL. Monetary estimated_cost/actual_cost are
        # reserved for a future credit->currency rate (the system stores credits today,
        # not money); credits_spent is filled where a real debit is known.
        cursor = await db.execute("PRAGMA table_info(request_telemetry)")
        telemetry_cost_columns = {row[1] for row in await cursor.fetchall()}
        telemetry_cost_column_defs = {
            "provider": "TEXT",
            "engine": "TEXT",
            "model_label": "TEXT",
            "credits_spent": "REAL",
            "estimated_credits": "REAL",
            "estimated_cost": "REAL",
            "actual_cost": "REAL",
        }
        for column_name, column_type in telemetry_cost_column_defs.items():
            if column_name not in telemetry_cost_columns:
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
    cluster             TEXT,
    product_type_group  TEXT,
    claim_risk_level    TEXT NOT NULL DEFAULT 'HIGH',
    mapping_confidence  REAL,
    image_readiness     TEXT NOT NULL DEFAULT 'IMAGE_MISSING',
    copy_route          TEXT,
    sold_count          INTEGER,
    commission_rate     TEXT,
    sell_price          REAL,
    commission_amount   REAL,
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
    ruleset_version     TEXT,
    input_fingerprint   TEXT,
    computed_ruleset_version TEXT,
    computed_input_fingerprint TEXT,
    recompute_state     TEXT NOT NULL DEFAULT 'STALE',
    recompute_reason    TEXT,
    review_hold_reason  TEXT,
    recompute_started_at TEXT,
    recompute_attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bulk_draft_status ON fastmoss_bulk_draft_status(promotion_status);
CREATE INDEX IF NOT EXISTS idx_bulk_draft_risk ON fastmoss_bulk_draft_status(claim_risk_level);
CREATE INDEX IF NOT EXISTS idx_bulk_draft_recompute_state ON fastmoss_bulk_draft_status(recompute_state);
""")
            logger.info("Migrated: created batch production tables")
        await db.commit()

        # Scene Context Promotion Round 3 — auditable review events only.
        # This ledger is deliberately separate from the active scene registry.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS scene_context_promotion_review_event (
    review_id TEXT PRIMARY KEY,
    source_template_id TEXT NOT NULL,
    candidate_fingerprint TEXT NOT NULL,
    cluster TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('PENDING','APPROVED_FOR_FUTURE_PROMOTION','REJECTED')),
    reviewer_note TEXT,
    reviewed_via_product_id TEXT REFERENCES product(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scene_context_promotion_review_event_current
    ON scene_context_promotion_review_event(source_template_id, candidate_fingerprint, reviewed_at DESC);

CREATE TABLE IF NOT EXISTS scene_context_promotion_activation_event (
    activation_id TEXT PRIMARY KEY,
    source_template_id TEXT NOT NULL,
    candidate_fingerprint TEXT NOT NULL,
    review_id TEXT NOT NULL,
    reviewed_via_product_id TEXT REFERENCES product(id) ON DELETE SET NULL,
    cluster TEXT NOT NULL,
    scene_code TEXT NOT NULL,
    scene_name TEXT NOT NULL,
    activated_by TEXT NOT NULL,
    activation_note TEXT,
    bridge_digest_before TEXT,
    bridge_digest_after TEXT NOT NULL,
    activated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scene_context_promotion_activation_exact
    ON scene_context_promotion_activation_event(source_template_id, candidate_fingerprint, activated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scene_context_promotion_activation_exact
    ON scene_context_promotion_activation_event(source_template_id, candidate_fingerprint);
CREATE INDEX IF NOT EXISTS idx_scene_context_promotion_activation_product
    ON scene_context_promotion_activation_event(reviewed_via_product_id, activated_at DESC);
CREATE INDEX IF NOT EXISTS idx_scene_context_promotion_activation_scene_code
    ON scene_context_promotion_activation_event(scene_code, activated_at DESC);
CREATE INDEX IF NOT EXISTS idx_scene_context_promotion_activation_at
    ON scene_context_promotion_activation_event(activated_at DESC);
""")
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='scene_context_promotion_review'"
        )
        if await cursor.fetchone():
            await db.execute("""
                INSERT OR IGNORE INTO scene_context_promotion_review_event (
                    review_id, source_template_id, candidate_fingerprint, cluster,
                    decision, reviewer_note, reviewed_via_product_id, created_at,
                    reviewed_at
                )
                SELECT review_id, source_template_id, candidate_fingerprint, cluster,
                       decision, reviewer_note, reviewed_via_product_id, created_at,
                       reviewed_at
                FROM scene_context_promotion_review
            """)
            await db.execute("DROP TABLE scene_context_promotion_review")
            logger.info("Migrated: scene context promotion reviews to append-only events")
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
            "cluster": "TEXT",
            "product_type_group": "TEXT",
            "sell_price": "REAL",
            "commission_amount": "REAL",
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
            "ruleset_version": "TEXT",
            "input_fingerprint": "TEXT",
            "computed_ruleset_version": "TEXT",
            "computed_input_fingerprint": "TEXT",
            "recompute_state": "TEXT NOT NULL DEFAULT 'STALE'",
            "recompute_reason": "TEXT",
            "review_hold_reason": "TEXT",
            "recompute_started_at": "TEXT",
            "recompute_attempt_count": "INTEGER NOT NULL DEFAULT 0",
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
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_bulk_draft_recompute_state "
            "ON fastmoss_bulk_draft_status(recompute_state)"
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

        # Migration: durable generation identity on the prompt package. The
        # correlation anchors previously lived ONLY in make_video's in-memory
        # _JOBS dict, so they died on restart and nothing recorded whether an
        # output could ever be bound. Persisting them is what lets a retrieval
        # refuse foreign media instead of guessing.
        #
        # MUST stay AFTER the ARCHIVED rebuild above: that path RENAMEs the table
        # and recreates it from a hardcoded column list, so any column added
        # earlier in init_db is silently dropped on a fresh DB.
        cursor = await db.execute("PRAGMA table_info(workspace_generation_package)")
        wgp_cols3 = {row[1] for row in await cursor.fetchall()}
        if "generation_identity_json" not in wgp_cols3:
            await db.execute(
                "ALTER TABLE workspace_generation_package "
                "ADD COLUMN generation_identity_json TEXT")
            await db.commit()
            logger.info("Migrated: added generation_identity_json to "
                        "workspace_generation_package table")

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
            # PI-FINAL-B04 stale-asset containment: nullable quarantine state
            # (PI_INELIGIBLE / NEEDS_REVALIDATION / BLOCKED; NULL = clear) plus the
            # eligibility reasons frozen at quarantine time. Additive on purpose -
            # the status CHECK constraint is never altered and the approval state
            # machine is untouched.
            ("pi_eligibility_status", "TEXT"),
            ("pi_ineligible_reasons", "TEXT"),
            # COPY-FINAL-B02 durable PI snapshot lineage on Copy Sets.
            ("pi_snapshot_id", "TEXT"),
            ("pi_snapshot_version", "INTEGER"),
            ("pi_grounding_digest", "TEXT"),
            ("grounded_at", "TEXT"),
            ("revalidated_at", "TEXT"),
            ("revalidated_by", "TEXT"),
            ("revalidation_decision", "TEXT"),
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

        # Script Library P2 — content combination ledger. One row per
        # PRODUCED combination (script x avatar/visuals x scene); the UNIQUE
        # fingerprint is the mathematical anti-duplicate guarantee: the batch
        # planner refuses to produce the same combination twice.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS content_combination (
    combination_id    TEXT PRIMARY KEY,
    product_id        TEXT NOT NULL,
    logical_mode      TEXT NOT NULL,
    copy_set_id       TEXT,
    script_key        TEXT NOT NULL DEFAULT '',
    visual_key_json   TEXT NOT NULL DEFAULT '{}',
    combination_fingerprint TEXT NOT NULL,
    workspace_generation_package_id TEXT,
    batch_run_id      TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_content_combination_fingerprint
    ON content_combination(combination_fingerprint);
CREATE INDEX IF NOT EXISTS idx_content_combination_product
    ON content_combination(product_id, created_at);
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

        # Phase B1 — the ATOMIC component pool.
        #
        # `copy_set` stores a FROZEN bundle (angle+hook+subhook+usp+cta in one
        # row), so N variations cost N LLM calls and diversity collapses as N
        # grows (measured: 58 sets, subhook 58/58 distinct = zero reuse, ~90%
        # one theme). `copy_intelligence_seed` is NOT an alternative home: each
        # of its rows also bundles hook+body+cta together, and it holds imported
        # competitor ads (research), not authored building blocks.
        #
        # This table stores ONE part, reusable across many composed copy sets,
        # so capacity becomes MULTIPLICATIVE: per angle,
        # hooks x subhooks x usp_sets x ctas, summed over angles, times formulas.
        #
        # component_type MIRRORS the consumer's slots exactly. A composed copy
        # must satisfy CopySetResponse (angle, hook, subhook, usp_set, cta) —
        # there is NO `body` field there, so HOOK/SUBHOOK/USP_SET/CTA are the
        # only valid types. `angle` is not a component; it is the Phase A key
        # components are grouped BY.
        #
        # angle_key ties a component to a Phase A derived angle. It is NULLABLE
        # by design: '' means "applies to every angle of this product", which is
        # how CTAs normally behave. Composition is otherwise angle-COHERENT — a
        # colic hook must never pair with a body about post-work body aches.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS copy_component (
    component_id      TEXT PRIMARY KEY,
    product_id        TEXT NOT NULL,
    angle_key         TEXT NOT NULL DEFAULT '',
    angle_label       TEXT NOT NULL DEFAULT '',
    component_type    TEXT NOT NULL,
    content           TEXT NOT NULL,
    formula_affinity  TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'COMPONENT_REVIEW_REQUIRED',
    claim_review_json TEXT NOT NULL DEFAULT '{}',
    dedupe_key        TEXT NOT NULL,
    usage_count       INTEGER NOT NULL DEFAULT 0,
    last_used_at      TEXT,
    source            TEXT NOT NULL DEFAULT '',
    provenance_json   TEXT NOT NULL DEFAULT '{}',
    reviewer_note     TEXT,
    approved_at       TEXT,
    approved_by       TEXT,
    archived          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_copy_component_dedupe
    ON copy_component(product_id, component_type, dedupe_key);
CREATE INDEX IF NOT EXISTS idx_copy_component_pool
    ON copy_component(product_id, angle_key, component_type, status, archived);

-- P7 Creative Supply Factory. These tables are orchestration and review
-- ledgers only: they never store provider credentials, mutate Product Truth,
-- or open a media-generation path.
CREATE TABLE IF NOT EXISTS creative_supply_run (
    run_id                    TEXT PRIMARY KEY,
    mission_id                TEXT NOT NULL,
    roster_sha256             TEXT NOT NULL,
    cohort_sha256             TEXT NOT NULL,
    roster_json               TEXT NOT NULL,
    angle_plan_json           TEXT NOT NULL,
    target_policy_json        TEXT NOT NULL,
    state                     TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(state IN ('DRAFT','READY','RUNNING','PAUSED','COMPLETED','BLOCKED','CANCELLED')),
    provider_budget_max       INTEGER NOT NULL DEFAULT 120
        CHECK(provider_budget_max BETWEEN 1 AND 120),
    provider_calls_used       INTEGER NOT NULL DEFAULT 0
        CHECK(provider_calls_used >= 0),
    reviewer_id               TEXT NOT NULL,
    pause_reason              TEXT,
    last_error                TEXT,
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS creative_supply_task (
    task_id                   TEXT PRIMARY KEY,
    run_id                    TEXT NOT NULL REFERENCES creative_supply_run(run_id) ON DELETE CASCADE,
    product_id                TEXT NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    angle_key                 TEXT NOT NULL,
    angle_label               TEXT NOT NULL,
    component_type            TEXT NOT NULL
        CHECK(component_type IN ('HOOK','SUBHOOK','USP_SET','CTA')),
    task_kind                 TEXT NOT NULL DEFAULT 'AUTHOR_DEFICIT'
        CHECK(task_kind IN ('AUTHOR_DEFICIT','LEGACY_AUDIT')),
    deficit_round             INTEGER NOT NULL DEFAULT 1 CHECK(deficit_round >= 0),
    target_approved_count     INTEGER NOT NULL CHECK(target_approved_count >= 1),
    requested_count           INTEGER NOT NULL CHECK(requested_count BETWEEN 0 AND 12),
    attempt_count             INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 2),
    provider_call_count       INTEGER NOT NULL DEFAULT 0 CHECK(provider_call_count BETWEEN 0 AND 2),
    state                     TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(state IN (
            'PENDING','RUNNING','REVIEW_REQUIRED','COMPLETED',
            'RETRY_ELIGIBLE','FAILED','BLOCKED','CANCELLED'
        )),
    transient_failure_proven  INTEGER NOT NULL DEFAULT 0
        CHECK(transient_failure_proven IN (0,1)),
    idempotency_key           TEXT NOT NULL UNIQUE,
    provider_receipt_json     TEXT NOT NULL DEFAULT '{}',
    result_json               TEXT NOT NULL DEFAULT '{}',
    last_error                TEXT,
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(run_id, product_id, angle_key, component_type, task_kind, deficit_round)
);

CREATE TABLE IF NOT EXISTS creative_supply_review_event (
    event_id                  TEXT PRIMARY KEY,
    run_id                    TEXT NOT NULL REFERENCES creative_supply_run(run_id) ON DELETE CASCADE,
    task_id                   TEXT NOT NULL REFERENCES creative_supply_task(task_id) ON DELETE CASCADE,
    component_id              TEXT NOT NULL REFERENCES copy_component(component_id) ON DELETE RESTRICT,
    product_id                TEXT NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    angle_key                 TEXT NOT NULL,
    component_type            TEXT NOT NULL,
    decision                  TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
    reviewed_content_sha256   TEXT NOT NULL,
    reasons_json              TEXT NOT NULL,
    safety_json               TEXT NOT NULL,
    provider_provenance_json  TEXT NOT NULL,
    reviewer_id               TEXT NOT NULL,
    reviewed_at               TEXT NOT NULL,
    UNIQUE(task_id, component_id)
);

CREATE INDEX IF NOT EXISTS idx_creative_supply_run_state
    ON creative_supply_run(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_creative_supply_task_next
    ON creative_supply_task(run_id, state, created_at);
CREATE INDEX IF NOT EXISTS idx_creative_supply_task_slot
    ON creative_supply_task(run_id, product_id, angle_key, component_type);
CREATE INDEX IF NOT EXISTS idx_creative_supply_review_product
    ON creative_supply_review_event(run_id, product_id, reviewed_at);
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

        # Creative Intelligence Round 4 — saved creative selection (per product).
        # Review-gated planning artifact only: records the chosen avatar + scene
        # template + camera preset for a product. NEVER writes product rows/camera
        # columns and NEVER triggers or feeds generation.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS creative_product_selection (
    product_id                  TEXT PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    selection_id                TEXT NOT NULL,
    cluster                     TEXT,
    cluster_source              TEXT,
    selected_avatar_code        TEXT,
    selected_scene_template_id  TEXT,
    selected_camera_preset_code TEXT,
    selected_block_purpose      TEXT,
    selected_content_type       TEXT,
    notes                       TEXT,
    preview_json                TEXT,
    provenance_json             TEXT,
    status                      TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(status IN ('DRAFT','APPROVED','REJECTED')),
    reviewer_note               TEXT,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    reviewed_at                 TEXT,
    -- Multi-select: the FULL chosen set as JSON arrays. The singular selected_*
    -- columns above remain the backward-compatible PRIMARY (=first of each list).
    selected_avatar_codes_json         TEXT,
    selected_scene_template_ids_json   TEXT,
    selected_camera_preset_codes_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_creative_product_selection_status
    ON creative_product_selection(status);

-- P7.5-B Creative Treatment authority. These tables are intentionally
-- independent of P6: they bind approved upstream authority into immutable,
-- review-gated treatment snapshots without changing any upstream schema.
CREATE TABLE IF NOT EXISTS creative_variation_group (
    group_id          TEXT PRIMARY KEY,
    product_id        TEXT NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    copy_set_id       TEXT NOT NULL REFERENCES copy_set(copy_set_id) ON DELETE RESTRICT,
    dialogue_sha256   TEXT NOT NULL CHECK(length(dialogue_sha256) = 64),
    status            TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(status IN ('DRAFT','REVIEW_REQUIRED','APPROVED','REJECTED','SUPERSEDED')),
    group_sha256      TEXT CHECK(group_sha256 IS NULL OR length(group_sha256) = 64),
    member_count      INTEGER NOT NULL DEFAULT 0 CHECK(member_count BETWEEN 0 AND 5),
    supersedes_group_id TEXT REFERENCES creative_variation_group(group_id) ON DELETE RESTRICT,
    created_by        TEXT NOT NULL,
    submitted_by      TEXT,
    reviewed_by       TEXT,
    reviewer_note     TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    submitted_at      TEXT,
    reviewed_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_creative_variation_group_product_status
    ON creative_variation_group(product_id, status, created_at);

CREATE TABLE IF NOT EXISTS creative_treatment (
    treatment_id                 TEXT PRIMARY KEY,
    product_id                   TEXT NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    version                      INTEGER NOT NULL CHECK(version >= 1),
    status                       TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(status IN ('DRAFT','REVIEW_REQUIRED','APPROVED','REJECTED','SUPERSEDED')),
    format                       TEXT NOT NULL CHECK(format IN ('UGC','PGC','CINEMATIC')),
    generation_mode              TEXT NOT NULL CHECK(generation_mode IN ('SINGLE','EXTEND')),
    duration_seconds             REAL NOT NULL CHECK(duration_seconds > 0),
    product_truth_snapshot_id    TEXT NOT NULL
        REFERENCES product_intelligence_snapshot(snapshot_id) ON DELETE RESTRICT,
    product_truth_sha256         TEXT NOT NULL CHECK(length(product_truth_sha256) = 64),
    copy_set_id                  TEXT NOT NULL REFERENCES copy_set(copy_set_id) ON DELETE RESTRICT,
    copy_set_sha256              TEXT NOT NULL CHECK(length(copy_set_sha256) = 64),
    creative_selection_id        TEXT NOT NULL,
    creative_selection_sha256    TEXT NOT NULL CHECK(length(creative_selection_sha256) = 64),
    scene_strategy_id            TEXT NOT NULL,
    scene_strategy_sha256        TEXT NOT NULL CHECK(length(scene_strategy_sha256) = 64),
    content_angle                TEXT NOT NULL,
    dialogue_text                TEXT NOT NULL,
    dialogue_sha256              TEXT NOT NULL CHECK(length(dialogue_sha256) = 64),
    avatar_code                  TEXT,
    avatar_sha256                TEXT CHECK(avatar_sha256 IS NULL OR length(avatar_sha256) = 64),
    wardrobe_text                TEXT,
    wardrobe_sha256              TEXT CHECK(wardrobe_sha256 IS NULL OR length(wardrobe_sha256) = 64),
    scene_template_id            TEXT,
    scene_template_sha256        TEXT CHECK(
        scene_template_sha256 IS NULL OR length(scene_template_sha256) = 64
    ),
    camera_preset_code           TEXT,
    camera_preset_sha256         TEXT CHECK(
        camera_preset_sha256 IS NULL OR length(camera_preset_sha256) = 64
    ),
    asset_bindings_json          TEXT NOT NULL,
    action_sequence_json         TEXT NOT NULL,
    shot_grammar_json            TEXT NOT NULL,
    compatibility_profile_json   TEXT NOT NULL,
    segment_plan_json             TEXT NOT NULL DEFAULT '[]',
    visual_fingerprint_sha256    TEXT NOT NULL CHECK(length(visual_fingerprint_sha256) = 64),
    variation_group_id           TEXT REFERENCES creative_variation_group(group_id) ON DELETE RESTRICT,
    variation_ordinal            INTEGER CHECK(variation_ordinal BETWEEN 1 AND 5),
    treatment_sha256             TEXT NOT NULL CHECK(length(treatment_sha256) = 64),
    supersedes_treatment_id       TEXT REFERENCES creative_treatment(treatment_id) ON DELETE RESTRICT,
    created_by                   TEXT NOT NULL,
    submitted_by                 TEXT,
    reviewed_by                  TEXT,
    reviewer_note                TEXT,
    created_at                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    submitted_at                 TEXT,
    reviewed_at                  TEXT,
    UNIQUE(product_id, version),
    UNIQUE(variation_group_id, variation_ordinal),
    CHECK(
        (variation_group_id IS NULL AND variation_ordinal IS NULL)
        OR (variation_group_id IS NOT NULL AND variation_ordinal IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_creative_treatment_product_status
    ON creative_treatment(product_id, status, version);
CREATE INDEX IF NOT EXISTS idx_creative_treatment_group
    ON creative_treatment(variation_group_id, variation_ordinal);
CREATE INDEX IF NOT EXISTS idx_creative_treatment_dialogue
    ON creative_treatment(product_id, dialogue_sha256, status);

CREATE TABLE IF NOT EXISTS creative_treatment_audit_event (
    event_id         TEXT PRIMARY KEY,
    entity_type      TEXT NOT NULL CHECK(entity_type IN ('TREATMENT','VARIATION_GROUP')),
    entity_id        TEXT NOT NULL,
    action           TEXT NOT NULL,
    actor_id         TEXT NOT NULL,
    source_status    TEXT,
    target_status    TEXT,
    evidence_json    TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_creative_treatment_audit_entity
    ON creative_treatment_audit_event(entity_type, entity_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_creative_treatment_approved_hash_immutable
BEFORE UPDATE OF treatment_sha256 ON creative_treatment
WHEN OLD.status IN ('APPROVED','SUPERSEDED')
     AND NEW.treatment_sha256 <> OLD.treatment_sha256
BEGIN
    SELECT RAISE(ABORT, 'APPROVED_TREATMENT_HASH_IMMUTABLE');
END;

CREATE TRIGGER IF NOT EXISTS trg_creative_treatment_approved_content_immutable
BEFORE UPDATE OF
    product_id, version, format, generation_mode, duration_seconds,
    product_truth_snapshot_id, product_truth_sha256,
    copy_set_id, copy_set_sha256,
    creative_selection_id, creative_selection_sha256,
    scene_strategy_id, scene_strategy_sha256,
    content_angle, dialogue_text, dialogue_sha256,
    avatar_code, avatar_sha256, wardrobe_text, wardrobe_sha256,
    scene_template_id, scene_template_sha256,
    camera_preset_code, camera_preset_sha256,
    asset_bindings_json, action_sequence_json, shot_grammar_json,
    compatibility_profile_json, segment_plan_json, visual_fingerprint_sha256,
    variation_group_id, variation_ordinal, supersedes_treatment_id
ON creative_treatment
WHEN OLD.status IN ('APPROVED','SUPERSEDED')
BEGIN
    SELECT RAISE(ABORT, 'APPROVED_TREATMENT_CONTENT_IMMUTABLE');
END;

CREATE TRIGGER IF NOT EXISTS trg_creative_variation_group_approved_hash_immutable
BEFORE UPDATE OF group_sha256 ON creative_variation_group
WHEN OLD.status IN ('APPROVED','SUPERSEDED')
     AND NEW.group_sha256 <> OLD.group_sha256
BEGIN
    SELECT RAISE(ABORT, 'APPROVED_VARIATION_GROUP_HASH_IMMUTABLE');
END;

-- Official cluster -> product-type registry. This is configuration authority,
-- not Product Truth: assignments may only become VERIFIED when their exact
-- pair is ACTIVE here and uses the registered scene/coverage binding.
CREATE TABLE IF NOT EXISTS product_strategy_type_registry (
    cluster                    TEXT NOT NULL,
    product_type_group         TEXT NOT NULL,
    display_name               TEXT NOT NULL,
    matched_scene_strategy_id  TEXT NOT NULL,
    scene_coverage_status      TEXT NOT NULL
        CHECK(scene_coverage_status IN ('COVERED','PARTIAL','FALLBACK_ONLY')),
    registry_status            TEXT NOT NULL
        CHECK(registry_status IN ('ACTIVE','REVIEW_REQUIRED')),
    auto_classification_enabled INTEGER NOT NULL DEFAULT 0
        CHECK(auto_classification_enabled IN (0,1)),
    authority_source           TEXT NOT NULL
        CHECK(authority_source IN ('SYSTEM_SEED','MANUAL_REGISTRATION')),
    reviewer_id                TEXT,
    reviewer_note              TEXT,
    reviewed_at                TEXT,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (cluster, product_type_group),
    CHECK(
        registry_status <> 'ACTIVE'
        OR (
            cluster <> 'generic_unclassified'
            AND product_type_group <> 'unknown_product_type'
            AND matched_scene_strategy_id <> 'GENERIC_FALLBACK'
            AND scene_coverage_status <> 'FALLBACK_ONLY'
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_product_strategy_type_registry_status
    ON product_strategy_type_registry(registry_status, cluster);

-- Official product-strategy taxonomy sidecar. This keeps Product Truth rows
-- unchanged while giving downstream consumers one durable, review-gated
-- contract. Manual overrides are protected by the materialization service.
CREATE TABLE IF NOT EXISTS product_strategy_taxonomy (
    product_id                 TEXT PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    taxonomy_version           TEXT NOT NULL,
    product_fingerprint        TEXT NOT NULL,
    cluster                    TEXT NOT NULL,
    product_type_group         TEXT NOT NULL,
    matched_scene_strategy_id  TEXT NOT NULL,
    scene_coverage_status      TEXT NOT NULL
        CHECK(scene_coverage_status IN ('COVERED','PARTIAL','FALLBACK_ONLY')),
    fallback_used              INTEGER NOT NULL CHECK(fallback_used IN (0,1)),
    specific_strategy          INTEGER NOT NULL CHECK(specific_strategy IN (0,1)),
    classification_confidence  TEXT NOT NULL
        CHECK(classification_confidence IN ('HIGH','MEDIUM','LOW')),
    review_status              TEXT NOT NULL
        CHECK(review_status IN ('VERIFIED','REVIEW_REQUIRED')),
    consumer_status            TEXT NOT NULL
        CHECK(consumer_status IN ('READY','BLOCKED_REVIEW_REQUIRED')),
    authority_source           TEXT NOT NULL
        CHECK(authority_source IN ('AUTO_DERIVED','MANUAL_OVERRIDE')),
    materialization_status     TEXT NOT NULL
        CHECK(materialization_status IN ('PLACEHOLDER','MATERIALIZED')),
    review_reasons_json        TEXT NOT NULL DEFAULT '[]',
    reviewer_id                TEXT,
    reviewer_note              TEXT,
    derived_at                 TEXT,
    reviewed_at                TEXT,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK(scene_coverage_status <> 'FALLBACK_ONLY' OR fallback_used = 1),
    CHECK(
        (
            review_status = 'VERIFIED'
            AND consumer_status = 'READY'
            AND authority_source = 'MANUAL_OVERRIDE'
            AND materialization_status = 'MATERIALIZED'
        )
        OR (
            review_status = 'REVIEW_REQUIRED'
            AND consumer_status = 'BLOCKED_REVIEW_REQUIRED'
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_product_strategy_taxonomy_review
    ON product_strategy_taxonomy(review_status, scene_coverage_status);
CREATE INDEX IF NOT EXISTS idx_product_strategy_taxonomy_cluster
    ON product_strategy_taxonomy(cluster, product_type_group);

-- New products cannot exist without an explicit taxonomy state. The trigger is
-- deliberately fail-closed: it inserts a REVIEW_REQUIRED placeholder which a
-- reviewed materialization pass later replaces.
CREATE TRIGGER IF NOT EXISTS trg_product_strategy_taxonomy_after_product_insert
AFTER INSERT ON product
BEGIN
    INSERT OR IGNORE INTO product_strategy_taxonomy (
        product_id,
        taxonomy_version,
        product_fingerprint,
        cluster,
        product_type_group,
        matched_scene_strategy_id,
        scene_coverage_status,
        fallback_used,
        specific_strategy,
        classification_confidence,
        review_status,
        consumer_status,
        authority_source,
        materialization_status,
        review_reasons_json,
        derived_at
    ) VALUES (
        NEW.id,
        'product_strategy_taxonomy_v1',
        'PENDING_MATERIALIZATION',
        'generic_unclassified',
        'unknown_product_type',
        'GENERIC_FALLBACK',
        'FALLBACK_ONLY',
        1,
        0,
        'LOW',
        'REVIEW_REQUIRED',
        'BLOCKED_REVIEW_REQUIRED',
        'AUTO_DERIVED',
        'PLACEHOLDER',
        '["NOT_MATERIALIZED"]',
        strftime('%Y-%m-%dT%H:%M:%SZ','now')
    );
END;
""")
        await db.commit()
        # P7.5-P6 closure: widen the immutable treatment authority to governed
        # EXTEND and persist its derived segment plan. SQLite cannot modify a
        # CHECK constraint in place, so legacy tables are rebuilt transactionally.
        treatment_cursor = await db.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='creative_treatment'"
        )
        treatment_table = await treatment_cursor.fetchone()
        treatment_columns_cursor = await db.execute(
            "PRAGMA table_info(creative_treatment)"
        )
        treatment_columns = {
            row[1] for row in await treatment_columns_cursor.fetchall()
        }
        treatment_sql = str(treatment_table[0] if treatment_table else "")
        treatment_needs_rebuild = bool(treatment_table) and (
            "segment_plan_json" not in treatment_columns
            or "generation_mode IN ('SINGLE','EXTEND')" not in treatment_sql
        )
        if treatment_needs_rebuild:
            await db.execute("PRAGMA foreign_keys=OFF")
            try:
                await db.executescript("""
BEGIN IMMEDIATE;
CREATE TABLE creative_treatment_p75_p6_new (
    treatment_id                 TEXT PRIMARY KEY,
    product_id                   TEXT NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    version                      INTEGER NOT NULL CHECK(version >= 1),
    status                       TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK(status IN ('DRAFT','REVIEW_REQUIRED','APPROVED','REJECTED','SUPERSEDED')),
    format                       TEXT NOT NULL CHECK(format IN ('UGC','PGC','CINEMATIC')),
    generation_mode              TEXT NOT NULL CHECK(generation_mode IN ('SINGLE','EXTEND')),
    duration_seconds             REAL NOT NULL CHECK(duration_seconds > 0),
    product_truth_snapshot_id    TEXT NOT NULL
        REFERENCES product_intelligence_snapshot(snapshot_id) ON DELETE RESTRICT,
    product_truth_sha256         TEXT NOT NULL CHECK(length(product_truth_sha256) = 64),
    copy_set_id                  TEXT NOT NULL REFERENCES copy_set(copy_set_id) ON DELETE RESTRICT,
    copy_set_sha256              TEXT NOT NULL CHECK(length(copy_set_sha256) = 64),
    creative_selection_id        TEXT NOT NULL,
    creative_selection_sha256    TEXT NOT NULL CHECK(length(creative_selection_sha256) = 64),
    scene_strategy_id            TEXT NOT NULL,
    scene_strategy_sha256        TEXT NOT NULL CHECK(length(scene_strategy_sha256) = 64),
    content_angle                TEXT NOT NULL,
    dialogue_text                TEXT NOT NULL,
    dialogue_sha256              TEXT NOT NULL CHECK(length(dialogue_sha256) = 64),
    avatar_code                  TEXT,
    avatar_sha256                TEXT CHECK(avatar_sha256 IS NULL OR length(avatar_sha256) = 64),
    wardrobe_text                TEXT,
    wardrobe_sha256              TEXT CHECK(wardrobe_sha256 IS NULL OR length(wardrobe_sha256) = 64),
    scene_template_id            TEXT,
    scene_template_sha256        TEXT CHECK(
        scene_template_sha256 IS NULL OR length(scene_template_sha256) = 64
    ),
    camera_preset_code           TEXT,
    camera_preset_sha256         TEXT CHECK(
        camera_preset_sha256 IS NULL OR length(camera_preset_sha256) = 64
    ),
    asset_bindings_json          TEXT NOT NULL,
    action_sequence_json         TEXT NOT NULL,
    shot_grammar_json            TEXT NOT NULL,
    compatibility_profile_json   TEXT NOT NULL,
    segment_plan_json             TEXT NOT NULL DEFAULT '[]',
    visual_fingerprint_sha256    TEXT NOT NULL CHECK(length(visual_fingerprint_sha256) = 64),
    variation_group_id           TEXT REFERENCES creative_variation_group(group_id) ON DELETE RESTRICT,
    variation_ordinal            INTEGER CHECK(variation_ordinal BETWEEN 1 AND 5),
    treatment_sha256             TEXT NOT NULL CHECK(length(treatment_sha256) = 64),
    supersedes_treatment_id       TEXT REFERENCES creative_treatment_p75_p6_new(treatment_id) ON DELETE RESTRICT,
    created_by                   TEXT NOT NULL,
    submitted_by                 TEXT,
    reviewed_by                  TEXT,
    reviewer_note                TEXT,
    created_at                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    submitted_at                 TEXT,
    reviewed_at                  TEXT,
    UNIQUE(product_id, version),
    UNIQUE(variation_group_id, variation_ordinal),
    CHECK(
        (variation_group_id IS NULL AND variation_ordinal IS NULL)
        OR (variation_group_id IS NOT NULL AND variation_ordinal IS NOT NULL)
    )
);
INSERT INTO creative_treatment_p75_p6_new (
    treatment_id, product_id, version, status, format,
    generation_mode, duration_seconds,
    product_truth_snapshot_id, product_truth_sha256,
    copy_set_id, copy_set_sha256,
    creative_selection_id, creative_selection_sha256,
    scene_strategy_id, scene_strategy_sha256,
    content_angle, dialogue_text, dialogue_sha256,
    avatar_code, avatar_sha256, wardrobe_text, wardrobe_sha256,
    scene_template_id, scene_template_sha256,
    camera_preset_code, camera_preset_sha256,
    asset_bindings_json, action_sequence_json, shot_grammar_json,
    compatibility_profile_json, segment_plan_json, visual_fingerprint_sha256,
    variation_group_id, variation_ordinal, treatment_sha256,
    supersedes_treatment_id, created_by, submitted_by, reviewed_by,
    reviewer_note, created_at, updated_at, submitted_at, reviewed_at
)
SELECT
    treatment_id, product_id, version, status, format,
    generation_mode, duration_seconds,
    product_truth_snapshot_id, product_truth_sha256,
    copy_set_id, copy_set_sha256,
    creative_selection_id, creative_selection_sha256,
    scene_strategy_id, scene_strategy_sha256,
    content_angle, dialogue_text, dialogue_sha256,
    avatar_code, avatar_sha256, wardrobe_text, wardrobe_sha256,
    scene_template_id, scene_template_sha256,
    camera_preset_code, camera_preset_sha256,
    asset_bindings_json, action_sequence_json, shot_grammar_json,
    compatibility_profile_json, '[]', visual_fingerprint_sha256,
    variation_group_id, variation_ordinal, treatment_sha256,
    supersedes_treatment_id, created_by, submitted_by, reviewed_by,
    reviewer_note, created_at, updated_at, submitted_at, reviewed_at
FROM creative_treatment;
DROP TABLE creative_treatment;
ALTER TABLE creative_treatment_p75_p6_new RENAME TO creative_treatment;
CREATE INDEX idx_creative_treatment_product_status
    ON creative_treatment(product_id, status, version);
CREATE INDEX idx_creative_treatment_group
    ON creative_treatment(variation_group_id, variation_ordinal);
CREATE INDEX idx_creative_treatment_dialogue
    ON creative_treatment(product_id, dialogue_sha256, status);
CREATE TRIGGER trg_creative_treatment_approved_hash_immutable
BEFORE UPDATE OF treatment_sha256 ON creative_treatment
WHEN OLD.status IN ('APPROVED','SUPERSEDED')
     AND NEW.treatment_sha256 <> OLD.treatment_sha256
BEGIN
    SELECT RAISE(ABORT, 'APPROVED_TREATMENT_HASH_IMMUTABLE');
END;
CREATE TRIGGER trg_creative_treatment_approved_content_immutable
BEFORE UPDATE OF
    product_id, version, format, generation_mode, duration_seconds,
    product_truth_snapshot_id, product_truth_sha256,
    copy_set_id, copy_set_sha256,
    creative_selection_id, creative_selection_sha256,
    scene_strategy_id, scene_strategy_sha256,
    content_angle, dialogue_text, dialogue_sha256,
    avatar_code, avatar_sha256, wardrobe_text, wardrobe_sha256,
    scene_template_id, scene_template_sha256,
    camera_preset_code, camera_preset_sha256,
    asset_bindings_json, action_sequence_json, shot_grammar_json,
    compatibility_profile_json, segment_plan_json, visual_fingerprint_sha256,
    variation_group_id, variation_ordinal, supersedes_treatment_id
ON creative_treatment
WHEN OLD.status IN ('APPROVED','SUPERSEDED')
BEGIN
    SELECT RAISE(ABORT, 'APPROVED_TREATMENT_CONTENT_IMMUTABLE');
END;
COMMIT;
""")
                logger.info(
                    "Migrated: widened creative_treatment generation_mode and "
                    "added segment_plan_json"
                )
            finally:
                await db.execute("PRAGMA foreign_keys=ON")

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
    hook_angles_json TEXT NOT NULL DEFAULT '[]',
    cta_angles_json TEXT NOT NULL DEFAULT '[]',
    pain_points_json TEXT NOT NULL DEFAULT '[]',
    subhook_json TEXT NOT NULL DEFAULT '[]',
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
    review_status TEXT NOT NULL CHECK(review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION','REJECTED','APPROVED','SUPERSEDED')),
    product_description TEXT,
    benefits_json TEXT NOT NULL DEFAULT '[]',
    usp_json TEXT NOT NULL DEFAULT '[]',
    hook_angles_json TEXT NOT NULL DEFAULT '[]',
    cta_angles_json TEXT NOT NULL DEFAULT '[]',
    pain_points_json TEXT NOT NULL DEFAULT '[]',
    subhook_json TEXT NOT NULL DEFAULT '[]',
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
    revision_of_draft_id TEXT,
    revision_of_snapshot_id TEXT,
    revision_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_draft_product_status
    ON product_intelligence_review_draft(product_id, review_status, created_at);
CREATE INDEX IF NOT EXISTS idx_product_intelligence_review_draft_product_updated
    ON product_intelligence_review_draft(product_id, updated_at);

CREATE TABLE IF NOT EXISTS product_registration_review_draft (
    draft_id TEXT PRIMARY KEY,
    review_status TEXT NOT NULL,
    source_lane TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_registration_review_draft_updated
    ON product_registration_review_draft(updated_at);

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
    inherited_from_draft_id TEXT,
    inherited_from_snapshot_id TEXT,
    inherited_at TEXT,
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

        # SSOT Phase A: durable homes for copy seeds (hook/cta/pain) that
        # previously dropped at commit. Existing DBs already have these
        # intelligence tables, so the CREATE ... IF NOT EXISTS above only helps
        # fresh DBs — add the columns idempotently for existing ones.
        for _pi_table in (
            "product_intelligence_snapshot",
            "product_intelligence_review_draft",
        ):
            _pi_cursor = await db.execute(f"PRAGMA table_info({_pi_table})")
            _pi_columns = {row[1] for row in await _pi_cursor.fetchall()}
            for _pi_new_col in (
                "hook_angles_json",
                "cta_angles_json",
                "pain_points_json",
                "subhook_json",
            ):
                if _pi_new_col not in _pi_columns:
                    await db.execute(
                        f"ALTER TABLE {_pi_table} ADD COLUMN {_pi_new_col} TEXT NOT NULL DEFAULT '[]'"
                    )
                    logger.info(
                        "Migrated: added %s column to %s", _pi_new_col, _pi_table
                    )
        await db.commit()

        # Google Flow bulk generation orchestrator (V1): persistent runs + items.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS bulk_generation_run (
    bulk_run_id             TEXT PRIMARY KEY,
    kind                    TEXT NOT NULL
                            CHECK(kind IN ('AVATAR_IMAGE','IMG','VIDEO','MIXED','MONTAGE_DISCRETE')),
    status                  TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK(status IN ('PENDING','RUNNING','COMPLETED','PARTIAL_FAILED','FAILED','CANCELLED','PAUSED','PREPARED','PARTIAL','GENERATING','COMPLETE','ASSEMBLY_READY')),
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
                            CHECK(item_type IN ('AVATAR_IMAGE','IMG','T2V','I2V','F2V','MONTAGE_SCENE')),
    source_ref              TEXT NOT NULL,
    prompt_snapshot         TEXT,
    payload_json            TEXT NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'QUEUED'
                            CHECK(status IN ('QUEUED','SUBMITTED','RUNNING','GENERATED','DOWNLOADED','REGISTERED','FAILED','CANCELLED','PLANNED','IMAGE_PENDING_PACKAGE','IMAGE_PENDING','IMAGE_READY','IMAGE_BOUND','PACKAGE_READY','PACKAGE_FAILED','VIDEO_SUBMITTED','VIDEO_READY','GENERATE_RETURNED','GENERATE_FAILED','RESULT_BOUND','BLOCKED','SKIPPED_VIDEO')),
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
        _migrate_bulk_generation_ledger(str(DB_PATH))

        # P6 Batch Creative Production Orchestrator — durable control plane.
        #
        # These tables are additive. Existing workspace_generation_package,
        # production_run, bulk_generation_* and legacy batch rows remain intact.
        # The orchestrator owns business planning, immutable creative identity,
        # lane capacity/leases, attempt idempotency, recovery and output QA while
        # the existing ADR-007 services remain the only media-execution door.
        await db.executescript("""
CREATE TABLE IF NOT EXISTS creative_production_plan (
    plan_id                    TEXT PRIMARY KEY,
    request_id                 TEXT NOT NULL UNIQUE,
    created_by                 TEXT NOT NULL,
    name                       TEXT NOT NULL,
    campaign_key               TEXT NOT NULL DEFAULT '',
    product_scope_json         TEXT NOT NULL DEFAULT '[]',
    p58_cohort_sha256          TEXT NOT NULL,
    p58_cohort_count           INTEGER NOT NULL,
    target_video_count         INTEGER NOT NULL DEFAULT 0 CHECK(target_video_count BETWEEN 0 AND 200),
    target_image_count         INTEGER NOT NULL DEFAULT 0 CHECK(target_image_count BETWEEN 0 AND 200),
    target_poster_count        INTEGER NOT NULL DEFAULT 0 CHECK(target_poster_count BETWEEN 0 AND 200),
    operating_window_hours     INTEGER NOT NULL DEFAULT 12 CHECK(operating_window_hours BETWEEN 1 AND 24),
    allocation_strategy        TEXT NOT NULL DEFAULT 'ROUND_ROBIN',
    variation_strategy         TEXT NOT NULL DEFAULT 'SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS',
    logical_mode               TEXT NOT NULL DEFAULT 'T2V'
                               CHECK(logical_mode IN ('T2V','HYBRID','F2V','I2V')),
    model_keys_json            TEXT NOT NULL DEFAULT '[]',
    duration_seconds_json      TEXT NOT NULL DEFAULT '[]',
    pool_snapshot_json         TEXT NOT NULL DEFAULT '{}',
    plan_snapshot_json         TEXT NOT NULL DEFAULT '{}',
    execution_policy_json      TEXT NOT NULL DEFAULT '{}',
    capacity_snapshot_json     TEXT NOT NULL DEFAULT '{}',
    compile_snapshot_json      TEXT NOT NULL DEFAULT '{}',
    blockers_json              TEXT NOT NULL DEFAULT '[]',
    status                     TEXT NOT NULL DEFAULT 'DRAFT'
                               CHECK(status IN (
                                   'DRAFT','PREFLIGHT_BLOCKED','PREFLIGHT_READY',
                                   'PENDING_APPROVAL','APPROVED','SCHEDULED',
                                   'RUNNING','PAUSED','COMPLETED',
                                   'COMPLETED_WITH_FAILURES','CANCELLED','FAILED'
                               )),
    control_action             TEXT NOT NULL DEFAULT 'NONE'
                               CHECK(control_action IN ('NONE','PAUSE_REQUESTED','CANCEL_REQUESTED')),
    control_version            INTEGER NOT NULL DEFAULT 0,
    approved_by                TEXT,
    approved_at                TEXT,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS creative_production_wave (
    wave_id                    TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL REFERENCES creative_production_plan(plan_id) ON DELETE CASCADE,
    wave_ordinal               INTEGER NOT NULL,
    name                       TEXT NOT NULL,
    scheduled_at               TEXT,
    status                     TEXT NOT NULL DEFAULT 'PLANNED'
                               CHECK(status IN (
                                   'PLANNED','APPROVED','QUEUED','RUNNING','PAUSED',
                                   'COMPLETED','COMPLETED_WITH_FAILURES','CANCELLED','FAILED'
                               )),
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(plan_id, wave_ordinal)
);

CREATE TABLE IF NOT EXISTS creative_production_batch (
    production_batch_id        TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL REFERENCES creative_production_plan(plan_id) ON DELETE CASCADE,
    wave_id                    TEXT REFERENCES creative_production_wave(wave_id) ON DELETE SET NULL,
    batch_ordinal              INTEGER NOT NULL,
    label                      TEXT NOT NULL,
    status                     TEXT NOT NULL DEFAULT 'PLANNED'
                               CHECK(status IN (
                                   'PLANNED','PENDING_APPROVAL','APPROVED','QUEUED',
                                   'RUNNING','COMPLETED','COMPLETED_WITH_FAILURES',
                                   'CANCELLED','FAILED'
                               )),
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(plan_id, batch_ordinal)
);

CREATE TABLE IF NOT EXISTS creative_production_item (
    item_id                    TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL REFERENCES creative_production_plan(plan_id) ON DELETE CASCADE,
    wave_id                    TEXT REFERENCES creative_production_wave(wave_id) ON DELETE SET NULL,
    production_batch_id        TEXT REFERENCES creative_production_batch(production_batch_id) ON DELETE SET NULL,
    item_ordinal               INTEGER NOT NULL,
    product_id                 TEXT NOT NULL REFERENCES product(id) ON DELETE RESTRICT,
    media_type                 TEXT NOT NULL CHECK(media_type IN ('VIDEO','IMAGE','POSTER')),
    logical_mode               TEXT NOT NULL DEFAULT 'T2V',
    creative_dimensions_json   TEXT NOT NULL DEFAULT '{}',
    creative_dna_sha256        TEXT NOT NULL,
    dedupe_guard_key           TEXT NOT NULL UNIQUE,
    controlled_reuse_reason    TEXT,
    prompt_fingerprint         TEXT,
    workspace_generation_package_id TEXT
                               REFERENCES workspace_generation_package(workspace_generation_package_id)
                               ON DELETE SET NULL,
    prompt_package_json        TEXT NOT NULL DEFAULT '{}',
    execution_policy_json      TEXT NOT NULL DEFAULT '{}',
    status                     TEXT NOT NULL DEFAULT 'PLANNED'
                               CHECK(status IN (
                                   'PLANNED','COMPILED','DEDUPE_BLOCKED','PENDING_APPROVAL',
                                   'APPROVED','WAVE_ASSIGNED','QUEUED','DISPATCHING',
                                   'SUBMITTED','GENERATING','GENERATED','RETRIEVING',
                                   'RETRIEVED','QA_PENDING','QA_APPROVED','QA_REJECTED',
                                   'REPLACEMENT_PLANNED','FAILED','CANCELLED','SUPERSEDED'
                               )),
    output_media_id            TEXT,
    replacement_for_item_id    TEXT REFERENCES creative_production_item(item_id) ON DELETE SET NULL,
    replaced_by_item_id        TEXT REFERENCES creative_production_item(item_id) ON DELETE SET NULL,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(plan_id, item_ordinal)
);

CREATE TABLE IF NOT EXISTS creative_execution_lane (
    lane_id                    TEXT PRIMARY KEY,
    provider                   TEXT NOT NULL,
    engine                     TEXT NOT NULL,
    eligible_media_types_json  TEXT NOT NULL DEFAULT '[]',
    runtime_metadata_json      TEXT NOT NULL DEFAULT '{}',
    verified_max_inflight      INTEGER NOT NULL DEFAULT 1 CHECK(verified_max_inflight BETWEEN 1 AND 32),
    interval_seconds           INTEGER NOT NULL DEFAULT 45 CHECK(interval_seconds >= 0),
    cooldown_after_n_jobs      INTEGER NOT NULL DEFAULT 5 CHECK(cooldown_after_n_jobs >= 0),
    cooldown_seconds           INTEGER NOT NULL DEFAULT 300 CHECK(cooldown_seconds >= 0),
    health_status              TEXT NOT NULL DEFAULT 'UNKNOWN'
                               CHECK(health_status IN ('UNKNOWN','HEALTHY','DEGRADED','UNAVAILABLE')),
    enabled                    INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    runtime_proof_status       TEXT NOT NULL DEFAULT 'UNVERIFIED'
                               CHECK(runtime_proof_status IN ('UNVERIFIED','VERIFIED','EXPIRED','REVOKED')),
    evidence_reference         TEXT NOT NULL DEFAULT '',
    last_success_at            TEXT,
    last_failure_at            TEXT,
    completed_job_count        INTEGER NOT NULL DEFAULT 0 CHECK(completed_job_count >= 0),
    next_available_at          TEXT,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS creative_generation_attempt (
    attempt_id                 TEXT PRIMARY KEY,
    item_id                    TEXT NOT NULL REFERENCES creative_production_item(item_id) ON DELETE CASCADE,
    attempt_number             INTEGER NOT NULL CHECK(attempt_number >= 1),
    idempotency_key            TEXT NOT NULL UNIQUE,
    action_request_id          TEXT NOT NULL,
    lane_id                    TEXT REFERENCES creative_execution_lane(lane_id) ON DELETE SET NULL,
    attempt_state              TEXT NOT NULL DEFAULT 'NOT_SUBMITTED'
                               CHECK(attempt_state IN (
                                   'NOT_SUBMITTED','SUBMISSION_STARTED',
                                   'SUBMISSION_OUTCOME_UNCERTAIN','PROVIDER_JOB_KNOWN',
                                   'GENERATED_NOT_RETRIEVED','RETRIEVED_NOT_REGISTERED',
                                   'REGISTERED','QA_REJECTED','REPLACEMENT_REQUESTED',
                                   'FAILED','CANCELLED','SUPERSEDED'
                               )),
    payload_snapshot_json      TEXT NOT NULL DEFAULT '{}',
    payload_sha256             TEXT NOT NULL,
    provider                   TEXT NOT NULL DEFAULT '',
    engine                     TEXT NOT NULL DEFAULT '',
    model_key                  TEXT NOT NULL DEFAULT '',
    duration_seconds           INTEGER,
    credit_spend_intended      INTEGER NOT NULL DEFAULT 0 CHECK(credit_spend_intended IN (0,1)),
    credit_confirmation        TEXT,
    last_actor_id              TEXT,
    last_action_request_id     TEXT,
    provider_job_id            TEXT,
    provider_project_id        TEXT,
    provider_correlation_id    TEXT,
    provider_snapshot_json     TEXT NOT NULL DEFAULT '{}',
    provider_snapshot_updated_at TEXT,
    artifact_media_id          TEXT,
    failure_stage              TEXT,
    failure_code               TEXT,
    recovery_class             TEXT,
    supersedes_attempt_id      TEXT REFERENCES creative_generation_attempt(attempt_id) ON DELETE SET NULL,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    submission_started_at      TEXT,
    provider_known_at          TEXT,
    generated_at               TEXT,
    retrieved_at               TEXT,
    registered_at              TEXT,
    completed_at               TEXT,
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(item_id, attempt_number),
    UNIQUE(item_id, action_request_id)
);

CREATE TABLE IF NOT EXISTS creative_execution_lane_lease (
    lease_id                   TEXT PRIMARY KEY,
    lane_id                    TEXT NOT NULL REFERENCES creative_execution_lane(lane_id) ON DELETE CASCADE,
    attempt_id                 TEXT NOT NULL UNIQUE
                               REFERENCES creative_generation_attempt(attempt_id) ON DELETE CASCADE,
    lease_slot                 INTEGER NOT NULL CHECK(lease_slot >= 0),
    lease_token                TEXT NOT NULL UNIQUE,
    owner_instance_id          TEXT NOT NULL,
    acquired_at                TEXT NOT NULL,
    expires_at                 TEXT NOT NULL,
    released_at                TEXT,
    release_reason             TEXT
);

CREATE TABLE IF NOT EXISTS creative_output_qa (
    qa_id                      TEXT PRIMARY KEY,
    item_id                    TEXT NOT NULL REFERENCES creative_production_item(item_id) ON DELETE CASCADE,
    attempt_id                 TEXT NOT NULL REFERENCES creative_generation_attempt(attempt_id) ON DELETE CASCADE,
    artifact_media_id          TEXT NOT NULL,
    status                     TEXT NOT NULL DEFAULT 'QA_PENDING'
                               CHECK(status IN ('QA_PENDING','QA_APPROVED','QA_REJECTED')),
    checklist_json             TEXT NOT NULL DEFAULT '{}',
    reviewer_id                TEXT,
    reviewer_note              TEXT,
    reviewed_at                TEXT,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(item_id, attempt_id, artifact_media_id)
);

CREATE TABLE IF NOT EXISTS creative_production_audit_event (
    event_id                   TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL REFERENCES creative_production_plan(plan_id) ON DELETE CASCADE,
    item_id                    TEXT REFERENCES creative_production_item(item_id) ON DELETE SET NULL,
    attempt_id                 TEXT REFERENCES creative_generation_attempt(attempt_id) ON DELETE SET NULL,
    request_id                 TEXT NOT NULL,
    actor_id                   TEXT NOT NULL,
    action                     TEXT NOT NULL,
    source_state               TEXT,
    target_state               TEXT,
    evidence_json              TEXT NOT NULL DEFAULT '{}',
    created_at                 TEXT NOT NULL,
    UNIQUE(plan_id, request_id, action)
);

CREATE INDEX IF NOT EXISTS idx_creative_production_plan_status_updated
    ON creative_production_plan(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_creative_production_item_plan_status
    ON creative_production_item(plan_id, status, item_ordinal);
CREATE INDEX IF NOT EXISTS idx_creative_production_item_product_dna
    ON creative_production_item(product_id, creative_dna_sha256);
CREATE INDEX IF NOT EXISTS idx_creative_generation_attempt_state
    ON creative_generation_attempt(attempt_state, updated_at);
CREATE INDEX IF NOT EXISTS idx_creative_generation_attempt_provider_job
    ON creative_generation_attempt(provider_job_id);
CREATE INDEX IF NOT EXISTS idx_creative_execution_lane_health
    ON creative_execution_lane(enabled, runtime_proof_status, health_status);
CREATE INDEX IF NOT EXISTS idx_creative_execution_lane_lease_expiry
    ON creative_execution_lane_lease(lane_id, expires_at, released_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_creative_execution_lane_active_slot
    ON creative_execution_lane_lease(lane_id, lease_slot)
    WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_creative_output_qa_status
    ON creative_output_qa(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_creative_production_audit_plan
    ON creative_production_audit_event(plan_id, created_at);

INSERT OR IGNORE INTO creative_execution_lane (
    lane_id, provider, engine, eligible_media_types_json,
    runtime_metadata_json, verified_max_inflight, interval_seconds,
    cooldown_after_n_jobs, cooldown_seconds, health_status, enabled,
    runtime_proof_status, evidence_reference
) VALUES (
    'google-flow-video-primary', 'GOOGLE_FLOW', 'ADR_007_API_FIRST',
    '["VIDEO"]', '{"execution_door":"make_video.start_generate"}',
    1, 83, 5, 300, 'UNKNOWN', 1, 'VERIFIED',
    '.ai/status/CURRENT_STATE.md + ADR-007'
);

INSERT OR IGNORE INTO creative_execution_lane (
    lane_id, provider, engine, eligible_media_types_json,
    runtime_metadata_json, verified_max_inflight, interval_seconds,
    cooldown_after_n_jobs, cooldown_seconds, health_status, enabled,
    runtime_proof_status, evidence_reference
) VALUES (
    'google-flow-image-primary', 'GOOGLE_FLOW', 'IMAGE_API_FIRST',
    '["IMAGE","POSTER"]', '{}',
    1, 45, 5, 300, 'UNKNOWN', 0, 'UNVERIFIED',
    'runtime proof required before live assignment'
);
""")
        await db.executescript("""
CREATE TABLE IF NOT EXISTS product_treatment_factory_plan (
    plan_id                    TEXT PRIMARY KEY,
    plan_identity_sha256       TEXT NOT NULL UNIQUE CHECK(length(plan_identity_sha256)=64),
    cohort_sha256              TEXT NOT NULL CHECK(length(cohort_sha256)=64),
    context_sha256             TEXT NOT NULL CHECK(length(context_sha256)=64),
    status                     TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','SCANNED','PREPARING','PAUSED','COMPLETED','COMPLETED_WITH_BLOCKERS','FAILED')),
    product_count              INTEGER NOT NULL CHECK(product_count >= 1),
    request_json               TEXT NOT NULL,
    authority_versions_json    TEXT NOT NULL,
    readiness_summary_json     TEXT NOT NULL DEFAULT '{}',
    capacity_summary_json      TEXT NOT NULL DEFAULT '{}',
    failure_count              INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
    provider_calls_enabled     INTEGER NOT NULL DEFAULT 0 CHECK(provider_calls_enabled=0),
    media_generation_enabled   INTEGER NOT NULL DEFAULT 0 CHECK(media_generation_enabled=0),
    created_by                 TEXT NOT NULL,
    pause_reason               TEXT,
    created_at                 TEXT NOT NULL,
    scanned_at                 TEXT,
    preparation_started_at     TEXT,
    completed_at               TEXT,
    updated_at                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_treatment_factory_task (
    task_id                    TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL REFERENCES product_treatment_factory_plan(plan_id) ON DELETE CASCADE,
    product_id                 TEXT NOT NULL,
    task_type                  TEXT NOT NULL CHECK(task_type IN ('PRODUCT_TRUTH_REVIEW','EVIDENCE_REVIEW','COPY_GROUNDING','COPY_COMPOSITION','COPY_REVIEW','CREATIVE_SELECTION','ASSET_SUPPLY','TREATMENT_CANDIDATE','TREATMENT_REVIEW','P6_CAPACITY')),
    status                     TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','READY','RUNNING','REVIEW_REQUIRED','SATISFIED','PAUSED','FAILED','SUPERSEDED')),
    task_identity_sha256       TEXT NOT NULL UNIQUE CHECK(length(task_identity_sha256)=64),
    required_authority_sha256  TEXT NOT NULL CHECK(length(required_authority_sha256)=64),
    blocker_code               TEXT,
    next_action                TEXT,
    template_id                TEXT,
    template_sha256            TEXT CHECK(template_sha256 IS NULL OR length(template_sha256)=64),
    treatment_id               TEXT,
    treatment_sha256           TEXT CHECK(treatment_sha256 IS NULL OR length(treatment_sha256)=64),
    snapshot_json              TEXT NOT NULL DEFAULT '{}',
    result_json                TEXT NOT NULL DEFAULT '{}',
    error_code                 TEXT,
    attempt_count              INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    created_at                 TEXT NOT NULL,
    started_at                 TEXT,
    satisfied_at               TEXT,
    superseded_at              TEXT,
    updated_at                 TEXT NOT NULL,
    UNIQUE(plan_id, product_id, task_type, required_authority_sha256)
);

CREATE TABLE IF NOT EXISTS product_treatment_factory_event (
    event_id                   TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL REFERENCES product_treatment_factory_plan(plan_id) ON DELETE CASCADE,
    task_id                    TEXT REFERENCES product_treatment_factory_task(task_id) ON DELETE SET NULL,
    event_identity_sha256      TEXT NOT NULL UNIQUE CHECK(length(event_identity_sha256)=64),
    actor_id                   TEXT NOT NULL,
    action                     TEXT NOT NULL,
    source_state               TEXT,
    target_state               TEXT,
    evidence_json              TEXT NOT NULL DEFAULT '{}',
    created_at                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_treatment_factory_plan_status ON product_treatment_factory_plan(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_product_treatment_factory_task_plan_status ON product_treatment_factory_task(plan_id, status, product_id);
CREATE INDEX IF NOT EXISTS idx_product_treatment_factory_task_product_type ON product_treatment_factory_task(product_id, task_type, status);
CREATE INDEX IF NOT EXISTS idx_product_treatment_factory_event_plan ON product_treatment_factory_event(plan_id, created_at);
""")
        plan_cursor = await db.execute(
            "PRAGMA table_info(creative_production_plan)"
        )
        plan_columns = {row[1] for row in await plan_cursor.fetchall()}
        if "plan_snapshot_json" not in plan_columns:
            await db.execute(
                "ALTER TABLE creative_production_plan "
                "ADD COLUMN plan_snapshot_json TEXT NOT NULL DEFAULT '{}'"
            )
            logger.info(
                "Migrated: added plan_snapshot_json column to "
                "creative_production_plan"
            )
        cursor = await db.execute("PRAGMA table_info(creative_generation_attempt)")
        attempt_columns = {row[1] for row in await cursor.fetchall()}
        attempt_observation_columns = {
            "provider_project_id": "TEXT",
            "provider_correlation_id": "TEXT",
            "provider_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            "provider_snapshot_updated_at": "TEXT",
        }
        for column_name, column_type in attempt_observation_columns.items():
            if column_name not in attempt_columns:
                await db.execute(
                    "ALTER TABLE creative_generation_attempt "
                    f"ADD COLUMN {column_name} {column_type}"
                )
                logger.info(
                    "Migrated: added %s column to creative_generation_attempt",
                    column_name,
                )
        await db.commit()

        # ── B-586-04: one OPEN Product Intelligence draft per product ──────────
        # Enforced by the DATABASE, not by a post-hoc cleanup. The previous
        # application-level rule ("smallest draft_id wins, delete the losers") was
        # unsound twice over: it deleted evidence, and it contradicted the reader's
        # own recency authority, so it could delete exactly the draft
        # `_latest_open_draft` would have served.
        #
        # Three idempotent steps. Each re-runs harmlessly on an already-migrated DB.
        from agent.services.product_intelligence_draft_lifecycle import (
            SQL_CANONICAL_ORDER,
            SQL_OPEN_PREDICATE,
            UNIQUE_OPEN_DRAFT_INDEX,
        )

        # (1) The CHECK constraint must permit SUPERSEDED before any row can use it.
        # SQLite cannot ALTER a CHECK, so this is the documented table rebuild.
        # `legacy_alter_table=ON` is REQUIRED: without it SQLite 3.25+ rewrites the
        # child table's REFERENCES clause to point at the renamed _old table, which
        # would silently detach provenance from its draft.
        draft_ddl_cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='product_intelligence_review_draft'"
        )
        draft_ddl_row = await draft_ddl_cursor.fetchone()
        draft_ddl = (draft_ddl_row[0] if draft_ddl_row else "") or ""
        if draft_ddl and "'SUPERSEDED'" not in draft_ddl:
            rebuilt_ddl = draft_ddl.replace(
                "CHECK(review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION',"
                "'REJECTED','APPROVED'))",
                "CHECK(review_status IN ('DRAFT','READY_FOR_REVIEW','NEEDS_REVISION',"
                "'REJECTED','APPROVED','SUPERSEDED'))",
            )
            if rebuilt_ddl == draft_ddl:
                # The live CHECK is not the shape this migration was written against.
                # Fail loudly rather than guess at a constraint we do not recognise.
                raise RuntimeError(
                    "B-586-04: unrecognised review_status CHECK constraint; refusing to "
                    "rebuild product_intelligence_review_draft blindly"
                )
            cols_cursor = await db.execute(
                "PRAGMA table_info(product_intelligence_review_draft)")
            draft_columns = [row[1] for row in await cols_cursor.fetchall()]
            col_list = ", ".join(f'"{c}"' for c in draft_columns)
            await db.execute("PRAGMA foreign_keys=OFF")
            await db.execute("PRAGMA legacy_alter_table=ON")
            try:
                await db.execute(
                    "ALTER TABLE product_intelligence_review_draft "
                    "RENAME TO _product_intelligence_review_draft_old")
                await db.execute(rebuilt_ddl)
                await db.execute(
                    f"INSERT INTO product_intelligence_review_draft ({col_list}) "
                    f"SELECT {col_list} FROM _product_intelligence_review_draft_old")
                await db.execute(
                    "DROP TABLE _product_intelligence_review_draft_old")
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_product_intelligence_review_draft_product_status "
                    "ON product_intelligence_review_draft"
                    "(product_id, review_status, created_at)")
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_product_intelligence_review_draft_product_updated "
                    "ON product_intelligence_review_draft(product_id, updated_at)")
                await db.commit()
            finally:
                await db.execute("PRAGMA legacy_alter_table=OFF")
                await db.execute("PRAGMA foreign_keys=ON")
            fk_cursor = await db.execute("PRAGMA foreign_key_check")
            fk_violations = await fk_cursor.fetchall()
            if fk_violations:
                raise RuntimeError(
                    "B-586-04: review-draft rebuild left foreign key violations: "
                    f"{fk_violations[:5]}")
            logger.info("Migrated: review_status now permits SUPERSEDED")

        # (2) Converge any product that already holds >1 open draft. Nothing is
        # deleted: the non-canonical rows keep every column and every provenance row
        # and are marked SUPERSEDED, which asserts only that another draft became
        # canonical. No reviewer identity, approved_at or rejected_at is written —
        # convergence is not a review decision.
        dup_cursor = await db.execute(
            "SELECT product_id FROM product_intelligence_review_draft "
            f"WHERE {SQL_OPEN_PREDICATE} "
            "GROUP BY product_id HAVING COUNT(*) > 1")
        duplicate_products = [row[0] for row in await dup_cursor.fetchall()]
        for dup_product_id in duplicate_products:
            keep_cursor = await db.execute(
                "SELECT draft_id FROM product_intelligence_review_draft "
                f"WHERE product_id=? AND {SQL_OPEN_PREDICATE} "
                f"ORDER BY {SQL_CANONICAL_ORDER} LIMIT 1",
                (dup_product_id,))
            keep_row = await keep_cursor.fetchone()
            if not keep_row:
                continue
            await db.execute(
                "UPDATE product_intelligence_review_draft "
                "SET review_status='SUPERSEDED', updated_at=updated_at "
                f"WHERE product_id=? AND draft_id<>? AND {SQL_OPEN_PREDICATE}",
                (dup_product_id, keep_row[0]))
        if duplicate_products:
            await db.commit()
            logger.info("Migrated: converged %d product(s) onto one open draft",
                        len(duplicate_products))

        # (3) The constraint itself. Partial UNIQUE index over open rows only, so a
        # product may keep any number of APPROVED / REJECTED / SUPERSEDED drafts as
        # history while never holding two live ones.
        await db.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_OPEN_DRAFT_INDEX} "
            "ON product_intelligence_review_draft(product_id) "
            "WHERE review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')")
        await db.commit()

        # ── PI-FINAL-B01: revision lineage columns are part of the durable schema ──
        # `create_revision_draft` writes revision_of_draft_id / revision_of_snapshot_id /
        # revision_reason. They are in the CREATE TABLE DDL for fresh databases; this
        # idempotent ALTER upgrades any older valid database that predates them, so no
        # manual SQL is ever required after deployment.
        draft_cols_cursor = await db.execute(
            "PRAGMA table_info(product_intelligence_review_draft)")
        draft_existing_cols = {row[1] for row in await draft_cols_cursor.fetchall()}
        for lineage_col in ("revision_of_draft_id", "revision_of_snapshot_id", "revision_reason"):
            if lineage_col not in draft_existing_cols:
                await db.execute(
                    "ALTER TABLE product_intelligence_review_draft "
                    f"ADD COLUMN {lineage_col} TEXT")
                logger.info(
                    "Migrated: added %s column to product_intelligence_review_draft",
                    lineage_col)
        prov_cols_cursor = await db.execute(
            "PRAGMA table_info(product_intelligence_review_field_provenance)")
        prov_existing_cols = {row[1] for row in await prov_cols_cursor.fetchall()}
        for lineage_col in ("inherited_from_draft_id", "inherited_from_snapshot_id", "inherited_at"):
            if lineage_col not in prov_existing_cols:
                await db.execute(
                    "ALTER TABLE product_intelligence_review_field_provenance "
                    f"ADD COLUMN {lineage_col} TEXT")
                logger.info(
                    "Migrated: added %s column to product_intelligence_review_field_provenance",
                    lineage_col)
        # Multi-select creative setup: JSON-array columns holding the FULL chosen
        # set. The singular selected_* columns stay as the backward-compatible
        # PRIMARY (=first of each list) that the generation pipeline still reads.
        sel_cols_cursor = await db.execute(
            "PRAGMA table_info(creative_product_selection)")
        sel_existing_cols = {row[1] for row in await sel_cols_cursor.fetchall()}
        for multi_col in (
            "selected_avatar_codes_json",
            "selected_scene_template_ids_json",
            "selected_camera_preset_codes_json",
        ):
            if multi_col not in sel_existing_cols:
                await db.execute(
                    "ALTER TABLE creative_product_selection "
                    f"ADD COLUMN {multi_col} TEXT")
                logger.info(
                    "Migrated: added %s column to creative_product_selection", multi_col)
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
