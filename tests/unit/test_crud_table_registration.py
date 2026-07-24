"""Every table with crud helpers must ALSO be in the table allowlist.

Found the hard way: `copy_component` was added to `_COLUMNS` (the writable-column
whitelist) but not to `_VALID_TABLES` (the table-name allowlist). Insert
succeeded, then the read-back through `_get_with_db` raised
"Invalid table name: 'copy_component'". The API returned 422 while the row was
already written — so a live B2 run spent provider tokens, persisted one
component, and then aborted the rest of the batch.

Two separate registries for the same table is the trap. This test makes
forgetting one of them fail loudly instead of half-writing data.
"""
from agent.db import crud


def test_every_columns_table_is_in_the_valid_tables_allowlist():
    missing = sorted(set(crud._COLUMNS) - set(crud._VALID_TABLES))
    assert not missing, (
        "tables have a writable-column whitelist but are NOT in _VALID_TABLES, "
        f"so any read-back will raise: {missing}"
    )


def test_copy_component_is_registered_in_both():
    assert "copy_component" in crud._COLUMNS
    assert "copy_component" in crud._VALID_TABLES


def test_validate_table_still_rejects_unknown_names():
    """The allowlist must keep doing its real job — this is an injection guard."""
    import pytest

    with pytest.raises(ValueError, match="Invalid table name"):
        crud._validate_table("copy_component; DROP TABLE product")
    with pytest.raises(ValueError, match="Invalid table name"):
        crud._validate_table("not_a_table")
