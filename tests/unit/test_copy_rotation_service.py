"""Script Library rotation — the selection engine for owner-scale bulk.

Owner contract (2026-07-19): ~200 contents/day with combination-unique output.
These tests pin the selection law: APPROVED + non-archived + usage_count < 15
only; deterministic LRU order (never-used first → oldest last_used_at → least
used → oldest created); wrap-around when pool < batch; EMPTY (fail-closed) when
nothing eligible — never a silent fallback to duplicate/unapproved copy. Clone
re-enters review against the TARGET product and never auto-approves.
"""
import json

import pytest

from agent.services import copy_rotation_service as rot

PID = "prod-rot-1"


def _cs(i, *, status="COPY_APPROVED", usage=0, last_used=None, archived=0, created=None):
    return {
        "copy_set_id": f"cs_{i:02d}",
        "product_id": PID,
        "status": status,
        "usage_count": usage,
        "last_used_at": last_used,
        "archived": archived,
        "created_at": created or f"2026-07-{10 + i:02d}T00:00:00Z",
        "angle": f"angle {i}", "hook": f"hook {i}", "subhook": "",
        "usp_set_json": "[]", "cta": "beli sekarang",
        "platform": "TIKTOK", "language": "BM_MS",
        "route_type": "DIRECT", "formula_family": "HSO",
    }


@pytest.fixture
def pool(monkeypatch):
    state = {"rows": []}

    async def list_for_product(product_id):
        return list(state["rows"])
    monkeypatch.setattr(rot.crud, "list_copy_sets_for_product", list_for_product)
    return state


@pytest.mark.asyncio
async def test_only_approved_unarchived_under_cap_are_eligible(pool):
    pool["rows"] = [
        _cs(1),                                            # eligible
        _cs(2, status="COPY_REVIEW_REQUIRED"),             # not approved
        _cs(3, archived=1),                                # archived
        _cs(4, usage=rot.REUSE_CAP),                       # cap reached (15)
        _cs(5, usage=rot.REUSE_CAP - 1),                   # one use left — eligible
    ]
    res = await rot.select_rotation_copy_sets(PID, 2)
    ids = [r["copy_set_id"] for r in res["items"]]
    assert set(ids) == {"cs_01", "cs_05"}
    assert res["pool_size"] == 2


@pytest.mark.asyncio
async def test_lru_order_never_used_first_then_oldest_use(pool):
    pool["rows"] = [
        _cs(1, last_used="2026-07-18T10:00:00Z", usage=3),
        _cs(2, last_used=None, usage=0),                   # never used → first
        _cs(3, last_used="2026-07-17T10:00:00Z", usage=5), # older use → before cs_01
    ]
    res = await rot.select_rotation_copy_sets(PID, 3)
    assert [r["copy_set_id"] for r in res["items"]] == ["cs_02", "cs_03", "cs_01"]


@pytest.mark.asyncio
async def test_wrap_around_when_pool_smaller_than_batch(pool):
    pool["rows"] = [_cs(1), _cs(2)]
    res = await rot.select_rotation_copy_sets(PID, 5)
    ids = [r["copy_set_id"] for r in res["items"]]
    assert len(ids) == 5
    assert ids == ["cs_01", "cs_02", "cs_01", "cs_02", "cs_01"]
    assert any(w.startswith("POOL_SMALLER_THAN_BATCH:2<5") for w in res["warnings"])


@pytest.mark.asyncio
async def test_empty_pool_fails_closed_with_guidance(pool):
    pool["rows"] = [_cs(1, status="COPY_REVIEW_REQUIRED")]
    res = await rot.select_rotation_copy_sets(PID, 10)
    assert res["items"] == []
    assert res["warnings"] == [
        "NO_APPROVED_COPY_AVAILABLE:generate_and_approve_scripts_first"
    ]


@pytest.mark.asyncio
async def test_selection_is_deterministic(pool):
    pool["rows"] = [_cs(i, usage=i % 3) for i in range(1, 8)]
    a = await rot.select_rotation_copy_sets(PID, 4)
    b = await rot.select_rotation_copy_sets(PID, 4)
    assert [r["copy_set_id"] for r in a["items"]] == [r["copy_set_id"] for r in b["items"]]


# ── Clone to similar product ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clone_reenters_review_for_target_product(monkeypatch):
    source = _cs(1)
    created = {}

    async def get_copy_set(cid):
        return source if cid == "cs_01" else None

    async def get_product(pid):
        return {"id": pid, "product_display_name": "Car Perfume Vanilla B"} if pid == "prod-B" else None

    async def find_by_dedupe(key):
        return None

    async def create_copy_set(product_id, **kw):
        created.update({"product_id": product_id, **kw})
        return {"copy_set_id": "cs_clone", "product_id": product_id, **kw}

    monkeypatch.setattr(rot.crud, "get_copy_set", get_copy_set)
    monkeypatch.setattr(rot.crud, "get_product", get_product)
    monkeypatch.setattr(rot.crud, "find_copy_set_by_dedupe_key", find_by_dedupe)
    monkeypatch.setattr(rot.crud, "create_copy_set", create_copy_set)

    res = await rot.clone_copy_set_to_product("cs_01", "prod-B")
    assert res["created"] is True
    # Never auto-approved: the clone re-enters review for the TARGET product.
    assert created["status"] == "COPY_REVIEW_REQUIRED"
    assert created["source"] == rot.SOURCE_CLONE
    prov = json.loads(created["provenance_json"])
    assert prov["cloned_from_copy_set_id"] == "cs_01"
    assert prov["cloned_from_product_id"] == PID
    # Fresh reuse budget (Phase-1 columns default 0 on insert).
    assert "usage_count" not in created or not created.get("usage_count")


@pytest.mark.asyncio
async def test_clone_to_same_product_refused(monkeypatch):
    async def get_copy_set(cid):
        return _cs(1)

    async def get_product(pid):
        return {"id": pid}
    monkeypatch.setattr(rot.crud, "get_copy_set", get_copy_set)
    monkeypatch.setattr(rot.crud, "get_product", get_product)
    with pytest.raises(ValueError, match="CLONE_TARGET_IS_SOURCE_PRODUCT"):
        await rot.clone_copy_set_to_product("cs_01", PID)


@pytest.mark.asyncio
async def test_clone_dedupe_match_returns_existing_not_a_new_row(monkeypatch):
    async def get_copy_set(cid):
        return _cs(1)

    async def get_product(pid):
        return {"id": pid}

    async def find_by_dedupe(key):
        return _cs(9)
    monkeypatch.setattr(rot.crud, "get_copy_set", get_copy_set)
    monkeypatch.setattr(rot.crud, "get_product", get_product)
    monkeypatch.setattr(rot.crud, "find_copy_set_by_dedupe_key", find_by_dedupe)

    res = await rot.clone_copy_set_to_product("cs_01", "prod-B")
    assert res["created"] is False and res["dedupe_match"] is True


# ── Similarity backfill scan (P3) ─────────────────────────────────────────


def _dup_cs(i, hook, **kw):
    row = _cs(i, **kw)
    row["hook"] = hook
    row["subhook"] = "sebab minyak ni memang power untuk bayi"
    row["usp_set_json"] = '["cepat serap", "bau lembut"]'
    return row


@pytest.fixture
def backfill_pool(monkeypatch):
    state = {"rows": [], "updates": []}

    async def list_for_product(product_id):
        return list(state["rows"])

    async def update_copy_set(copy_set_id, **kw):
        state["updates"].append({"copy_set_id": copy_set_id, **kw})
        return {"copy_set_id": copy_set_id, **kw}

    monkeypatch.setattr(rot.crud, "list_copy_sets_for_product", list_for_product)
    monkeypatch.setattr(rot.crud, "update_copy_set", update_copy_set)
    return state


@pytest.mark.asyncio
async def test_backfill_flags_later_duplicate_pointing_to_earlier(backfill_pool):
    backfill_pool["rows"] = [
        _dup_cs(1, "Pernah tak anak menangis malam sebab perut kembung"),
        _dup_cs(2, "Pernah tak anak menangis malam sebab perut kembung sangat"),
        _dup_cs(3, "Ramai mak ayah tak sedar silap ni bila sapu minyak"),
    ]
    res = await rot.backfill_similarity_scan(PID)
    by_id = {i["copy_set_id"]: i for i in res["items"]}
    # Directional: the ORIGINAL (earliest) is never flagged; the later
    # near-copy points back at it.
    assert by_id["cs_01"]["flagged"] is False
    assert by_id["cs_02"]["flagged"] is True
    assert by_id["cs_02"]["similar_to_copy_set_id"] == "cs_01"
    assert by_id["cs_02"]["similarity_score"] >= 0.80
    assert by_id["cs_03"]["flagged"] is False
    assert res["flagged"] == 1
    # Dry-run: NOTHING written.
    assert res["apply"] is False and res["updated"] == 0
    assert backfill_pool["updates"] == []


@pytest.mark.asyncio
async def test_backfill_apply_persists_only_changed_rows(backfill_pool):
    original = _dup_cs(1, "Pernah tak anak menangis malam sebab perut kembung")
    dup = _dup_cs(2, "Pernah tak anak menangis malam sebab perut kembung sangat")
    backfill_pool["rows"] = [original, dup]

    first = await rot.backfill_similarity_scan(PID, apply=True)
    assert first["updated"] == 2  # both rows gain fresh metadata
    written = {u["copy_set_id"]: u for u in backfill_pool["updates"]}
    assert written["cs_02"]["similar_to_copy_set_id"] == "cs_01"
    assert written["cs_01"]["similar_to_copy_set_id"] is None
    assert 0.0 <= written["cs_01"]["uniqueness_score"] <= 1.0

    # Re-run with metadata already in place: no rewrites.
    for row in backfill_pool["rows"]:
        row.update({
            k: written[row["copy_set_id"]][k]
            for k in ("uniqueness_score", "similar_to_copy_set_id", "similarity_score")
        })
    backfill_pool["updates"].clear()
    second = await rot.backfill_similarity_scan(PID, apply=True)
    assert second["updated"] == 0
    assert backfill_pool["updates"] == []


@pytest.mark.asyncio
async def test_backfill_threshold_is_honored(backfill_pool):
    backfill_pool["rows"] = [
        _dup_cs(1, "Pernah tak anak menangis malam sebab perut kembung"),
        _dup_cs(2, "Pernah tak anak menangis petang sebab perut kembung"),
    ]
    loose = await rot.backfill_similarity_scan(PID, threshold=0.5)
    strict = await rot.backfill_similarity_scan(PID, threshold=0.999)
    assert loose["flagged"] >= 1
    assert strict["flagged"] == 0
    # Status untouched in every mode — annotation only.
    assert all("status" not in u for u in backfill_pool["updates"])
