"""Runtime avatar_registry usage_tags parsing.

The CSV Factory normalizes usage_tags to pipe-delimited output; the runtime
presenter reader must parse BOTH the legacy comma form and the new pipe form
(and any mix), or factory-synced rows would be read as one combined tag.
"""
from __future__ import annotations

import pytest

from agent.services import avatar_registry


@pytest.mark.parametrize("raw,expected", [
    ("UGC|desk|office", ["UGC", "desk", "office"]),          # new pipe form
    ("UGC, desk, office", ["UGC", "desk", "office"]),        # legacy comma form
    ("UGC, desk|office", ["UGC", "desk", "office"]),         # mixed delimiters
    ("UGC|ugc|desk", ["UGC", "desk"]),                       # case-insensitive dedupe
    (" UGC | desk ", ["UGC", "desk"]),                       # whitespace stripped
    ("", []),                                                  # empty
    (None, []),                                                # missing cell
    ("UGC||desk,,office", ["UGC", "desk", "office"]),        # empty segments dropped
])
def test_parse_usage_tags(raw, expected):
    assert avatar_registry._parse_usage_tags(raw) == expected


def test_normalize_profile_reads_pipe_delimited_tags():
    """The pipe-delimited factory output round-trips into separate tags."""
    profile = avatar_registry._normalize_profile({
        "AvatarCode": "BOS_F_OFFICE_01",
        "CharacterName": "Aisyah",
        "usage_tags": "UGC|desk|office",
    })
    assert profile["usage_tags"] == ["UGC", "desk", "office"]


def test_normalize_profile_still_reads_legacy_comma_tags():
    profile = avatar_registry._normalize_profile({
        "AvatarCode": "BOS_F_OFFICE_01",
        "CharacterName": "Aisyah",
        "usage_tags": "UGC, desk, office",
    })
    assert profile["usage_tags"] == ["UGC", "desk", "office"]
