"""Round 3 review-ledger persistence contracts."""
from __future__ import annotations

import sqlite3

import pytest

from agent.db import crud
from agent.db import schema


def _item(decision: str, note: str | None = None, fingerprint: str = "fp") -> dict:
    return {
        "source_template_id": "SCN-BEAUTY-01",
        "candidate_fingerprint": fingerprint,
        "cluster": "Beauty",
        "decision": decision,
        "reviewer_note": note,
        "reviewed_via_product_id": None,
    }


async def _event_rows() -> list[dict]:
    db = await crud.get_db()
    cur = await db.execute(
        "SELECT decision, reviewer_note, candidate_fingerprint FROM "
        "scene_context_promotion_review_event ORDER BY rowid ASC"
    )
    return [dict(row) for row in await cur.fetchall()]


@pytest.mark.asyncio
async def test_decision_transitions_are_append_only_and_exact_retries_are_idempotent(monkeypatch):
    monkeypatch.setattr(crud, "_now", lambda: "2026-07-26T12:00:00Z")

    await crud.record_scene_context_promotion_reviews([_item("PENDING", "first")])
    await crud.record_scene_context_promotion_reviews([_item("APPROVED_FOR_FUTURE_PROMOTION", "approved")])
    await crud.record_scene_context_promotion_reviews([_item("APPROVED_FOR_FUTURE_PROMOTION", "approved")])

    assert await _event_rows() == [
        {"decision": "PENDING", "reviewer_note": "first", "candidate_fingerprint": "fp"},
        {"decision": "APPROVED_FOR_FUTURE_PROMOTION", "reviewer_note": "approved", "candidate_fingerprint": "fp"},
    ]


@pytest.mark.asyncio
async def test_same_second_event_ordering_selects_the_latest_rowid(monkeypatch):
    monkeypatch.setattr(crud, "_now", lambda: "2026-07-26T12:00:00Z")

    await crud.record_scene_context_promotion_reviews([_item("PENDING", "first")])
    await crud.record_scene_context_promotion_reviews([_item("REJECTED", "second")])

    latest = (await crud.get_scene_context_promotion_reviews(["SCN-BEAUTY-01"]))[0]
    assert latest["decision"] == "REJECTED"
    assert latest["reviewer_note"] == "second"


@pytest.mark.asyncio
async def test_transaction_rolls_back_all_events_when_a_bulk_item_fails():
    before = await _event_rows()

    with pytest.raises(sqlite3.IntegrityError):
        await crud.record_scene_context_promotion_reviews([
            _item("PENDING", "valid"),
            _item("NOT_A_VALID_DECISION", "invalid", fingerprint="other"),
        ])

    assert await _event_rows() == before


@pytest.mark.asyncio
async def test_legacy_review_table_is_migrated_to_event_ledger_and_removed():
    db = await crud.get_db()
    await db.executescript("""
        CREATE TABLE scene_context_promotion_review (
            review_id TEXT PRIMARY KEY,
            source_template_id TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            cluster TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_note TEXT,
            reviewed_via_product_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reviewed_at TEXT NOT NULL
        );
        INSERT INTO scene_context_promotion_review VALUES (
            'legacy-review', 'SCN-LEGACY-01', 'legacy-fp', 'Beauty',
            'PENDING', 'preserved', NULL, '2026-01-01T00:00:00Z',
            '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
    """)
    await db.commit()

    await schema.init_db()

    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='scene_context_promotion_review'"
    )
    assert await cur.fetchone() is None
    cur = await db.execute(
        "SELECT source_template_id, candidate_fingerprint, reviewer_note "
        "FROM scene_context_promotion_review_event WHERE review_id='legacy-review'"
    )
    assert dict(await cur.fetchone()) == {
        "source_template_id": "SCN-LEGACY-01",
        "candidate_fingerprint": "legacy-fp",
        "reviewer_note": "preserved",
    }
