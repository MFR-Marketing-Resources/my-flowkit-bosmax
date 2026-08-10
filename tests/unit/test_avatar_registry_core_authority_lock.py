from __future__ import annotations

import csv
import io
import json
import shutil

import pytest

from agent.services import avatar_registry as ar


@pytest.fixture
def isolated_pool(tmp_path, monkeypatch):
    seed = tmp_path / "system" / "AVATAR_POOL_NORMALIZED.csv"
    seed.parent.mkdir()
    shutil.copyfile(ar._POOL_FILE, seed)
    bridge = tmp_path / "custom" / "AVATAR_POOL_NORMALIZED.csv"
    monkeypatch.setattr(ar, "_POOL_FILE", seed)
    monkeypatch.setattr(ar, "_BRIDGE_FILE", bridge)
    ar.reload_pool()
    yield seed, bridge
    ar._load_pool.cache_clear()


def _custom_row(code: str) -> dict[str, str]:
    return {
        "CharacterName": "Testina", "AvatarCode": code,
        "SkinTone": "Deep dark", "HairStyle": "Long wavy",
        "Wardrobe": "Neon streetwear", "Expression": "Confident",
        "PromptV1": f"Create a photorealistic avatar reference image. Identity: Testina, Code: {code}.",
        "approved_flag": "TRUE", "usage_tags": "test|ugc",
        "AgeBand": "Adult (30-54)",
    }


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def test_effective_pool_is_system_core_without_bridge(isolated_pool):
    pool = ar.list_pool()
    assert len(pool) == len(ar.system_core_codes()) == 250
    assert all(row["registry_source"] == ar.SOURCE_SYSTEM_CORE for row in pool)
    assert all(row["immutable"] and not row["delete_allowed"] for row in pool)


def test_one_custom_row_is_additive_and_resolvable(isolated_pool):
    core_count = len(ar.list_pool())
    ar.add_avatar(_custom_row("BOS_F_TESTINA_NEON_99"))
    assert len(ar.list_pool()) == core_count + 1
    assert ar.resolve_presenter("BOS_F_TESTINA_NEON_99")["registry_source"] == ar.SOURCE_CUSTOM
    assert ar.get_generation_prompt("BOS_F_TESTINA_NEON_99")["avatar_code"] == "BOS_F_TESTINA_NEON_99"


def test_direct_one_row_bridge_cannot_shadow_core(isolated_pool):
    _, bridge = isolated_pool
    bridge.parent.mkdir()
    bridge.write_bytes(_csv_bytes([_custom_row("BOS_F_ONLY_CUSTOM_01")]))
    ar.reload_pool()
    assert len(ar.list_pool()) == len(ar.system_core_codes()) + 1


def test_csv_sync_cannot_replace_or_collide_with_system_core(isolated_pool):
    core_count = len(ar.list_pool())
    result = ar.sync_pool_csv(_csv_bytes([_custom_row("BOS_F_CSV_CUSTOM_01")]))
    assert result["custom_rows"] == 1
    assert result["rows"] == core_count + 1
    with pytest.raises(ValueError, match="SYSTEM_AVATAR_CODE_COLLISION"):
        ar.sync_pool_csv(_csv_bytes([_custom_row(sorted(ar.system_core_codes())[0])]))


def test_direct_bridge_system_collision_fails_closed(isolated_pool):
    _, bridge = isolated_pool
    bridge.parent.mkdir()
    bridge.write_bytes(_csv_bytes([_custom_row(sorted(ar.system_core_codes())[0])]))
    with pytest.raises(RuntimeError, match="SYSTEM_AVATAR_CODE_COLLISION"):
        ar.reload_pool()


def test_system_delete_has_zero_file_mutation(isolated_pool):
    seed, bridge = isolated_pool
    core_code = sorted(ar.system_core_codes())[0]
    seed_before = seed.read_bytes()
    with pytest.raises(ValueError, match="SYSTEM_AVATAR_IMMUTABLE"):
        ar.delete_avatar(core_code)
    assert seed.read_bytes() == seed_before
    assert not bridge.exists()
    assert ar.resolve_presenter(core_code)["registry_source"] == ar.SOURCE_SYSTEM_CORE


def test_custom_delete_preserves_all_system_core(isolated_pool):
    ar.add_avatar(_custom_row("BOS_F_TESTINA_NEON_99"))
    result = ar.delete_avatar("BOS_F_TESTINA_NEON_99")
    assert result["custom_remaining"] == 0
    assert len(ar.list_pool()) == len(ar.system_core_codes())


def test_committed_crosswalk_resolves_with_custom_bridge(isolated_pool):
    ar.add_avatar(_custom_row("BOS_F_CROSSWALK_PROBE_01"))
    authority = json.loads(
        (ar._AUTHORITY_DIR / "creative_avatar_cluster_crosswalk.json").read_text(encoding="utf-8")
    )["crosswalk"]
    expected = {row["avatar_code"] for rows in authority.values() for row in rows}
    effective = {row["avatar_code"] for row in ar.list_pool()}
    assert expected <= effective
