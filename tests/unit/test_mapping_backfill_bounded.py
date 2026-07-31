"""Safety tests for the bounded NULL-cohort mapping backfill mechanism.

Proves the mechanism CANNOT touch READY/APPROVED/NEEDS_REVIEW/BLOCKED/archived/overwrite
rows, refuses to write without authorize=True, is idempotent, and rolls back deterministically.
enrich_product is monkeypatched so the guards are tested independently of the authority table.
"""
import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services import mapping_backfill_bounded as bb

# id -> controlled enrich_product output (only consulted for mapping_status IS NULL rows)
_ENRICH = {
    "P_ELIGIBLE": {"category": "Beauty", "subcategory": "Skincare", "type": "Serum",
                   "product_type": "UNIVERSAL", "product_type_id": "pt1", "silo": "s1",
                   "trigger_id": "TR1", "formula": "PAS", "claim_risk_level": "LOW",
                   "physics_class": "liquid_bottle", "recommended_grip": "one-hand",
                   "scene_context": "clean", "camera_style": "cs", "camera_behavior": "cb",
                   "camera_shot": "hero", "mapping_status": "READY",
                   "mapping_missing_fields": [], "mapping_confidence": "HIGH",
                   "mapping_source": "keyword", "prompt_readiness_status": "READY",
                   "prompt_missing_fields": []},
    "P_OVERWRITE": {"category": "DIFFERENT_CAT", "mapping_status": "READY",
                    "mapping_missing_fields": []},  # differs from stored non-empty category
    "P_SYNTH_APPROVED": {"category": "Beauty", "mapping_status": "APPROVED",
                         "mapping_missing_fields": []},
}


@pytest.fixture(autouse=True)
def _patch_enrich(monkeypatch):
    async def fake_enrich(product, *, persist=False):
        assert persist is False, "backfill must call enrich with persist=False"
        out = dict(product)
        out.update(_ENRICH.get(product.get("id"), {}))
        return out
    monkeypatch.setattr(bb, "enrich_product", fake_enrich)


async def _seed():
    db = await get_db()
    await db.execute("DELETE FROM product")

    async def prod(pid, lifecycle, mapping, category=None):
        await db.execute(
            "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, "
            "lifecycle_status, mapping_status, category, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, pid, pid, pid, lifecycle, mapping, category,
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
    await prod("P_ELIGIBLE", "ACTIVE", None)
    await prod("P_READY", "ACTIVE", "READY")
    await prod("P_APPROVED", "ACTIVE", "APPROVED")
    await prod("P_BLOCKED", "ACTIVE", "BLOCKED")
    await prod("P_NEEDSREVIEW", "ACTIVE", "NEEDS_REVIEW")
    await prod("P_ARCHIVED", "ARCHIVED", None)
    await prod("P_OVERWRITE", "ACTIVE", None, category="Original Category")
    await prod("P_SYNTH_APPROVED", "ACTIVE", None)
    await db.commit()


_ALL = ["P_ELIGIBLE", "P_READY", "P_APPROVED", "P_BLOCKED", "P_NEEDSREVIEW",
        "P_ARCHIVED", "P_OVERWRITE", "P_SYNTH_APPROVED"]


async def _status(pid):
    return (await crud.get_product(pid)).get("mapping_status")


async def test_preview_only_eligible_is_eligible():
    await _seed()
    plan = await bb.preview_bounded_backfill(_ALL)
    assert [e["product_id"] for e in plan["eligible"]] == ["P_ELIGIBLE"]
    reasons = {s["product_id"]: s["reason"] for s in plan["skipped"]}
    assert reasons["P_READY"].startswith("MAPPING_NOT_NULL")
    assert reasons["P_APPROVED"].startswith("MAPPING_NOT_NULL")
    assert reasons["P_BLOCKED"].startswith("MAPPING_NOT_NULL")
    assert reasons["P_NEEDSREVIEW"].startswith("MAPPING_NOT_NULL")
    assert reasons["P_ARCHIVED"] == "NOT_ACTIVE"
    assert reasons["P_OVERWRITE"] == "WOULD_OVERWRITE_EXISTING"
    assert reasons["P_SYNTH_APPROVED"] == "REFUSE_SYNTHETIC_APPROVED"


async def test_apply_without_authorize_writes_nothing():
    await _seed()
    res = await bb.apply_bounded_backfill(_ALL, authorize=False)
    assert res["authorized"] is False and res["wrote"] is False
    # nothing changed
    assert await _status("P_ELIGIBLE") is None


async def test_apply_authorized_touches_only_eligible():
    await _seed()
    before = {pid: await _status(pid) for pid in _ALL}
    res = await bb.apply_bounded_backfill(_ALL, authorize=True)
    assert res["wrote"] is True
    assert [c["product_id"] for c in res["changed"]] == ["P_ELIGIBLE"]
    # eligible row filled + READY
    elig = await crud.get_product("P_ELIGIBLE")
    assert elig["mapping_status"] == "READY"
    assert elig["silo"] == "s1" and elig["formula"] == "PAS"
    # every protected / skipped row is byte-identical to before
    for pid in _ALL:
        if pid == "P_ELIGIBLE":
            continue
        assert await _status(pid) == before[pid], pid
    assert (await crud.get_product("P_OVERWRITE"))["category"] == "Original Category"


async def test_idempotent_second_run_changes_nothing():
    await _seed()
    await bb.apply_bounded_backfill(_ALL, authorize=True)
    res2 = await bb.apply_bounded_backfill(_ALL, authorize=True)
    assert res2["changed_count"] == 0  # P_ELIGIBLE is no longer NULL


async def test_rollback_restores_before_state():
    await _seed()
    res = await bb.apply_bounded_backfill(_ALL, authorize=True)
    assert await _status("P_ELIGIBLE") == "READY"
    n = await bb.rollback_snapshot(res["before_snapshot"])
    assert n == 1
    restored = await crud.get_product("P_ELIGIBLE")
    assert restored["mapping_status"] is None
    assert restored["silo"] is None and restored["formula"] is None
