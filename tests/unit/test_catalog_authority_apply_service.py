from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent.config import DB_PATH
from agent.db import crud
from agent.services import catalog_authority_apply_service as service


@pytest.mark.asyncio
async def test_apply_is_transactional_and_second_pass_is_idempotent() -> None:
    product = await crud.create_product(
        raw_product_title="Reviewed Blush",
        product_display_name="Reviewed Blush",
        source="MANUAL",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Blush",
        lifecycle_status="ACTIVE",
    )
    database_path = Path(DB_PATH)

    preview = service.apply_catalog_authority(
        database_path,
        expected_product_count=1,
    )
    assert preview.mode == "DRY_RUN"
    assert preview.mutation_performed is False
    assert preview.taxonomy_insert_count + preview.taxonomy_update_count == 1

    first = service.apply_catalog_authority(
        database_path,
        expected_product_count=1,
        apply=True,
        confirmation=service.P58_APPLY_CONFIRMATION,
    )
    assert first.mode == "APPLY"
    assert first.mutation_performed is True
    assert first.taxonomy_verified_count == 1
    assert first.taxonomy_review_required_count == 0

    second = service.apply_catalog_authority(
        database_path,
        expected_product_count=1,
        apply=True,
        confirmation=service.P58_APPLY_CONFIRMATION,
    )
    assert second.mutation_performed is False
    assert second.registry_insert_count == 0
    assert second.registry_update_count == 0
    assert second.taxonomy_insert_count == 0
    assert second.taxonomy_update_count == 0
    assert second.state_fingerprint_before == second.state_fingerprint_after
    assert first.state_fingerprint_after == second.state_fingerprint_after

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        taxonomy = dict(
            connection.execute(
                "SELECT * FROM product_strategy_taxonomy WHERE product_id=?",
                (product["id"],),
            ).fetchone()
        )
        assert taxonomy["product_type_group"] == "blush"
        assert taxonomy["matched_scene_strategy_id"] == "BLUSH"
        assert taxonomy["review_status"] == "VERIFIED"
        assert taxonomy["consumer_status"] == "READY"
        assert taxonomy["authority_source"] == "MANUAL_OVERRIDE"
        assert taxonomy["reviewer_id"] == service.P58_APPLY_REVIEWER_ID
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_apply_requires_confirmation_without_mutating() -> None:
    await crud.create_product(
        raw_product_title="Reviewed Blush",
        source="MANUAL",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Blush",
    )
    database_path = Path(DB_PATH)
    before = service.apply_catalog_authority(
        database_path,
        expected_product_count=1,
    ).state_fingerprint_before

    with pytest.raises(RuntimeError, match="P58_APPLY_CONFIRMATION_REQUIRED"):
        service.apply_catalog_authority(
            database_path,
            expected_product_count=1,
            apply=True,
            confirmation="wrong",
        )

    after = service.apply_catalog_authority(
        database_path,
        expected_product_count=1,
    ).state_fingerprint_before
    assert after == before


@pytest.mark.asyncio
async def test_canonical_path_guard_fails_closed() -> None:
    await crud.create_product(
        raw_product_title="Reviewed Blush",
        source="MANUAL",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Blush",
    )
    database_path = Path(DB_PATH)

    with pytest.raises(
        RuntimeError,
        match="P58_CANONICAL_DATABASE_APPLY_NOT_AUTHORIZED",
    ):
        service.apply_catalog_authority(
            database_path,
            expected_product_count=1,
            apply=True,
            confirmation=service.P58_APPLY_CONFIRMATION,
            canonical_database_path=database_path,
        )


@pytest.mark.asyncio
async def test_canonical_path_guard_allows_non_mutating_preview() -> None:
    await crud.create_product(
        raw_product_title="Reviewed Blush",
        source="MANUAL",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Blush",
    )
    database_path = Path(DB_PATH)
    connection = sqlite3.connect(database_path)
    try:
        expected_product_count = int(
            connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        )
    finally:
        connection.close()

    preview = service.apply_catalog_authority(
        database_path,
        expected_product_count=expected_product_count,
        canonical_database_path=database_path,
    )

    assert preview.mode == "DRY_RUN"
    assert preview.mutation_performed is False
    assert preview.confirmation_required == service.P58_APPLY_CONFIRMATION


@pytest.mark.asyncio
async def test_apply_aborts_when_authority_changes_before_write_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = await crud.create_product(
        raw_product_title="Reviewed Blush",
        product_display_name="Reviewed Blush",
        source="MANUAL",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Blush",
        lifecycle_status="ACTIVE",
    )
    database_path = Path(DB_PATH)
    connection = sqlite3.connect(database_path)
    try:
        expected_product_count = int(
            connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        )
    finally:
        connection.close()
    original_fingerprint = service._state_fingerprint
    call_count = 0

    def drifting_fingerprint(connection: sqlite3.Connection) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return "0" * 64
        return original_fingerprint(connection)

    monkeypatch.setattr(
        service,
        "_state_fingerprint",
        drifting_fingerprint,
    )

    with pytest.raises(
        RuntimeError,
        match="P58_CONCURRENT_AUTHORITY_CHANGE_DETECTED",
    ):
        service.apply_catalog_authority(
            database_path,
            expected_product_count=expected_product_count,
            apply=True,
            confirmation=service.P58_APPLY_CONFIRMATION,
        )

    connection = sqlite3.connect(database_path)
    try:
        taxonomy = connection.execute(
            "SELECT product_type_group, review_status "
            "FROM product_strategy_taxonomy WHERE product_id=?",
            (product["id"],),
        ).fetchone()
        assert taxonomy == ("unknown_product_type", "REVIEW_REQUIRED")
    finally:
        connection.close()
