"""Provider-free P6 historical-DNA retention rules."""

from __future__ import annotations

from unittest.mock import AsyncMock

import aiosqlite
import pytest

from agent.db import creative_production_crud as p6db


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
