"""Safety tests for the bounded NULL-cohort mapping backfill mechanism.

Proves: cannot touch READY/APPROVED/NEEDS_REVIEW/BLOCKED/archived/overwrite rows; refuses
without authorize + matching cohort digest + durable snapshot; checks rowcount; writes a
durable before-snapshot; FAILS CLOSED + rolls back when a persisted readiness status is not
reproducible from stored state; and rolls back via compare-and-swap without clobbering
post-backfill changes. enrich_product is monkeypatched so the guards are tested
deterministically, independent of the authority table.
"""
import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services import mapping_backfill_bounded as bb

_FILLED = {"category": "Beauty", "subcategory": "Skincare", "type": "Serum",
           "product_type": "UNIVERSAL", "product_type_id": "pt1", "silo": "s1",
           "trigger_id": "TR1", "formula": "PAS", "claim_risk_level": "LOW",
           "physics_class": "liquid_bottle", "recommended_grip": "one-hand",
           "scene_context": "clean", "camera_style": "cs", "camera_behavior": "cb",
           "camera_shot": "hero", "mapping_status": "READY", "mapping_missing_fields": [],
           "mapping_confidence": "HIGH", "mapping_source": "keyword",
           "prompt_readiness_status": "READY", "prompt_missing_fields": []}

_ENRICH = {
    "P_ELIGIBLE": _FILLED,
    "P_OVERWRITE": {"category": "DIFFERENT_CAT", "mapping_status": "READY", "mapping_missing_fields": []},
    "P_SYNTH_APPROVED": {"category": "Beauty", "mapping_status": "APPROVED", "mapping_missing_fields": []},
}


@pytest.fixture(autouse=True)
def _patch_enrich(monkeypatch):
    async def fake_enrich(product, *, persist=False):
        assert persist is False, "backfill must call enrich with persist=False"
        out = dict(product)
        pid = product.get("id")
        if pid == "P_NONREPRO":
            out.update(_FILLED)
            # classify (stored mapping_status is None) proposes READY; the re-verify call
            # (stored mapping_status now set) drifts → not reproducible from stored state.
            out["prompt_readiness_status"] = "READY" if product.get("mapping_status") is None else "MISSING_FIELDS"
            return out
        out.update(_ENRICH.get(pid, {}))
        return out
    monkeypatch.setattr(bb, "enrich_product", fake_enrich)


async def _seed(extra=()):
    db = await get_db()
    await db.execute("DELETE FROM product")

    async def prod(pid, lifecycle, mapping, category=None):
        await db.execute(
            "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, "
            "lifecycle_status, mapping_status, category, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, pid, pid, pid, lifecycle, mapping, category, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    await prod("P_ELIGIBLE", "ACTIVE", None)
    await prod("P_READY", "ACTIVE", "READY")
    await prod("P_APPROVED", "ACTIVE", "APPROVED")
    await prod("P_BLOCKED", "ACTIVE", "BLOCKED")
    await prod("P_NEEDSREVIEW", "ACTIVE", "NEEDS_REVIEW")
    await prod("P_ARCHIVED", "ARCHIVED", None)
    await prod("P_OVERWRITE", "ACTIVE", None, category="Original Category")
    await prod("P_SYNTH_APPROVED", "ACTIVE", None)
    for pid in extra:
        await prod(pid, "ACTIVE", None)
    await db.commit()


_ALL = ["P_ELIGIBLE", "P_READY", "P_APPROVED", "P_BLOCKED", "P_NEEDSREVIEW",
        "P_ARCHIVED", "P_OVERWRITE", "P_SYNTH_APPROVED"]


async def _status(pid):
    return (await crud.get_product(pid)).get("mapping_status")


async def _authorized(ids, path):
    digest = await bb.compute_cohort_digest(ids)
    return await bb.apply_bounded_backfill(ids, authorize=True, expected_plan_digest=digest,
                                           snapshot_path=str(path))


async def test_preview_only_eligible():
    await _seed()
    plan = await bb.preview_bounded_backfill(_ALL)
    assert [e["product_id"] for e in plan["eligible"]] == ["P_ELIGIBLE"]
    reasons = {s["product_id"]: s["reason"] for s in plan["skipped"]}
    assert reasons["P_ARCHIVED"] == "NOT_ACTIVE"
    assert reasons["P_OVERWRITE"] == "WOULD_OVERWRITE_EXISTING"
    assert reasons["P_SYNTH_APPROVED"] == "REFUSE_SYNTHETIC_APPROVED"
    assert plan["plan_digest"]


async def test_refuses_without_authorize(tmp_path):
    await _seed()
    res = await bb.apply_bounded_backfill(_ALL, authorize=False)
    assert res["authorized"] is False and res["wrote"] is False
    assert await _status("P_ELIGIBLE") is None


async def test_refuses_without_digest_or_snapshot():
    await _seed()
    assert (await bb.apply_bounded_backfill(_ALL, authorize=True))["aborted"] == "PLAN_DIGEST_REQUIRED"
    assert (await bb.apply_bounded_backfill(_ALL, authorize=True, expected_plan_digest="x"))["aborted"] == "DURABLE_SNAPSHOT_PATH_REQUIRED"


async def test_digest_mismatch_aborts_no_write(tmp_path):
    await _seed()
    res = await bb.apply_bounded_backfill(_ALL, authorize=True, expected_plan_digest="WRONG",
                                          snapshot_path=str(tmp_path / "s.json"))
    assert res["aborted"] == "COHORT_DIGEST_MISMATCH" and res["wrote"] is False
    assert await _status("P_ELIGIBLE") is None


async def test_authorized_touches_only_eligible_and_writes_snapshot(tmp_path):
    await _seed()
    before = {pid: await _status(pid) for pid in _ALL}
    snap = tmp_path / "snap.json"
    res = await _authorized(_ALL, snap)
    assert res["wrote"] is True
    assert [c["product_id"] for c in res["changed"]] == ["P_ELIGIBLE"]
    assert (await crud.get_product("P_ELIGIBLE"))["mapping_status"] == "READY"
    for pid in _ALL:
        if pid != "P_ELIGIBLE":
            assert await _status(pid) == before[pid], pid
    assert (await crud.get_product("P_OVERWRITE"))["category"] == "Original Category"
    # durable snapshot exists with before + wrote
    import json
    data = json.loads(snap.read_text())
    assert data["rows"][0]["before"]["id"] == "P_ELIGIBLE"
    assert "updated_at" in data["rows"][0]["before"]
    assert data["rows"][0]["wrote"]["mapping_status"] == "READY"


async def test_readiness_invariant_violation_rolls_back(tmp_path):
    await _seed(extra=["P_NONREPRO"])
    res = await _authorized(["P_NONREPRO"], tmp_path / "s.json")
    assert res["wrote"] is False and res["aborted"] == "READINESS_INVARIANT_VIOLATION"
    assert res["invariant_failures"][0]["product_id"] == "P_NONREPRO"
    # rolled back → still NULL, no false READY persisted
    assert await _status("P_NONREPRO") is None


async def test_idempotent_after_state_change(tmp_path):
    await _seed()
    await _authorized(_ALL, tmp_path / "s1.json")
    res2 = await _authorized(_ALL, tmp_path / "s2.json")  # digest recomputed on now-changed cohort
    assert res2["changed_count"] == 0  # P_ELIGIBLE no longer NULL


async def test_cas_rollback_restores_and_protects(tmp_path):
    await _seed()
    snap = tmp_path / "snap.json"
    await _authorized(_ALL, snap)
    assert await _status("P_ELIGIBLE") == "READY"
    rb = await bb.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 1 and rb["verify_ok"] is True
    assert await _status("P_ELIGIBLE") is None  # restored

    # CAS protection: re-apply, then a legit post-backfill change, then rollback must NOT clobber it
    await _seed()
    snap2 = tmp_path / "snap2.json"
    await _authorized(_ALL, snap2)
    db = await get_db()
    await db.execute("UPDATE product SET mapping_status='APPROVED' WHERE id='P_ELIGIBLE'")
    await db.commit()
    rb2 = await bb.rollback_from_snapshot(str(snap2))
    assert rb2["restored_count"] == 0  # CAS refused
    assert await _status("P_ELIGIBLE") == "APPROVED"  # legit change preserved
