"""Provider-free P6 historical-DNA retention rules."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from agent.db import creative_production_crud as p6db
from agent.services import creative_production_plan_service as plans


@pytest.mark.asyncio
async def test_failed_item_without_provider_evidence_does_not_consume_dna(
    monkeypatch,
):
    db = await aiosqlite.connect(":memory:")
    try:
        await db.executescript(
            """
            CREATE TABLE creative_production_item (
                item_id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                creative_dna_sha256 TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE creative_generation_attempt (
                item_id TEXT NOT NULL,
                provider_job_id TEXT,
                provider_project_id TEXT,
                credit_spend_intended INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO creative_production_item
                (item_id, product_id, creative_dna_sha256, status)
            VALUES
                ('failed-no-provider', 'product-1', 'dna-no-provider', 'FAILED'),
                ('failed-provider', 'product-1', 'dna-provider', 'FAILED'),
                ('failed-credit-intent', 'product-1', 'dna-credit', 'FAILED'),
                ('planned', 'product-1', 'dna-planned', 'PLANNED'),
                ('cancelled', 'product-1', 'dna-cancelled', 'CANCELLED'),
                ('superseded', 'product-1', 'dna-superseded', 'SUPERSEDED');
            INSERT INTO creative_generation_attempt
                (item_id, provider_job_id, provider_project_id, credit_spend_intended)
            VALUES
                ('failed-provider', 'provider-job-1', NULL, 0),
                ('failed-credit-intent', NULL, NULL, 1);
            """
        )
        await db.commit()
        monkeypatch.setattr(p6db, "get_db", AsyncMock(return_value=db))

        historical = await p6db.list_historical_dna(
            ["product-1"],
            [
                "dna-no-provider",
                "dna-provider",
                "dna-credit",
                "dna-planned",
                "dna-cancelled",
                "dna-superseded",
            ],
        )

        assert historical == {
            "dna-provider",
            "dna-credit",
            "dna-planned",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_dedupe_guard_owner_marks_only_provider_free_failed_item_repreparable(
    monkeypatch,
):
    db = await aiosqlite.connect(":memory:")
    try:
        await db.executescript(
            """
            CREATE TABLE creative_production_item (
                item_id TEXT PRIMARY KEY,
                dedupe_guard_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL
            );
            CREATE TABLE creative_generation_attempt (
                item_id TEXT NOT NULL,
                provider_job_id TEXT,
                provider_project_id TEXT,
                credit_spend_intended INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO creative_production_item
                (item_id, dedupe_guard_key, status)
            VALUES
                ('failed-no-provider', 'dna:free', 'FAILED'),
                ('failed-provider', 'dna:provider', 'FAILED'),
                ('planned', 'dna:planned', 'PLANNED');
            INSERT INTO creative_generation_attempt
                (item_id, provider_job_id, provider_project_id, credit_spend_intended)
            VALUES
                ('failed-provider', 'provider-job-1', NULL, 0);
            """
        )
        await db.commit()
        monkeypatch.setattr(p6db, "get_db", AsyncMock(return_value=db))

        owners = await p6db.list_dedupe_guard_owners(
            ["dna:free", "dna:provider", "dna:planned", "dna:missing"]
        )

        assert owners == {
            "dna:free": {
                "item_id": "failed-no-provider",
                "status": "FAILED",
                "provider_free_failed": True,
            },
            "dna:provider": {
                "item_id": "failed-provider",
                "status": "FAILED",
                "provider_free_failed": False,
            },
            "dna:planned": {
                "item_id": "planned",
                "status": "PLANNED",
                "provider_free_failed": False,
            },
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_controlled_reprepare_resolves_provider_free_guard_collision(
    monkeypatch,
):
    plan_id = "p6plan-controlled-reprepare"
    dna = "a" * 64
    plan = {
        "plan_id": plan_id,
        "status": "PREFLIGHT_READY",
        "target_video_count": 1,
        "target_image_count": 0,
        "target_poster_count": 0,
        "staff_id": "staff-p6-test",
        "staff_display_name_snapshot": "P6 Test",
        "pool_snapshot_json": json.dumps(
            {
                "controlled_reuse_reason": "Provider-free reprepare",
                "controlled_reuse_max_per_dna": 1,
                "product_video_allocations": [
                    {"product_id": "product-p6-test", "video_count": 1}
                ],
            }
        ),
        "execution_policy_json": "{}",
    }
    dimension = {
        "product_id": "product-p6-test",
        "media_type": "VIDEO",
        "production_recipe": "FACELESS",
        "logical_mode": "F2V",
        "copy_set_id": "copy-p6-test",
        "avatar_code": "",
        "scene_family": "",
    }
    inserted: list[dict] = []

    async def list_items(_plan_id: str, **_kwargs):
        return list(inserted)

    async def insert_items(items: list[dict]):
        inserted.extend(items)

    monkeypatch.setattr(plans, "_require_plan", AsyncMock(return_value=plan))
    monkeypatch.setattr(
        plans,
        "run_capacity_preflight",
        AsyncMock(return_value=SimpleNamespace(status="PREFLIGHT_READY")),
    )
    monkeypatch.setattr(
        plans,
        "_capacity_candidates",
        AsyncMock(
            return_value=(
                {"VIDEO": 1, "IMAGE": 0, "POSTER": 0},
                {"VIDEO": [(dna, dimension)], "IMAGE": [], "POSTER": []},
                {},
                [],
                0,
            )
        ),
    )
    monkeypatch.setattr(
        p6db,
        "list_dedupe_guard_owners",
        AsyncMock(
            return_value={
                f"dna:{dna}": {
                    "item_id": "provider-free-failed-item",
                    "status": "FAILED",
                    "provider_free_failed": True,
                }
            }
        ),
    )
    monkeypatch.setattr(p6db, "list_items", list_items)
    monkeypatch.setattr(p6db, "insert_items", insert_items)
    monkeypatch.setattr(plans, "_decode_row", lambda row: row)

    matrix = await plans.materialize_content_matrix(plan_id)

    assert matrix["created"] == 1
    assert inserted[0]["dedupe_guard_key"] == (
        f"reprepare:{plan_id}:0:{dna}"
    )
