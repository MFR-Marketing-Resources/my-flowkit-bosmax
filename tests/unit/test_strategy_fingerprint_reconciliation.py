"""Safety tests for the bounded strategy-fingerprint reconciliation (SEV-1 04C).

Proves the mechanism reconciles ONLY provably-safe fingerprint-only drift, writes ONLY
`product_fingerprint` + `updated_at`, preserves every binding/provenance field, aborts the
whole cohort on any drift, and rolls back via compare-and-swap without clobbering later work.
"""
import json

import pytest

from agent.db.schema import get_db
from agent.services import strategy_fingerprint_reconciliation as sfr

_BIND = {"cluster": "beauty_skincare", "product_type_group": "moisturizer",
         "matched_scene_strategy_id": "SKINCARE", "scene_coverage_status": "COVERED",
         "fallback_used": False, "specific_strategy": True}


@pytest.fixture(autouse=True)
async def _restore_shared_tables():
    """Leave the shared registry exactly as a fresh DB has it (empty).

    The per-test DB reset is unreliable on Windows (WinError 32), and other suites assert
    `list_product_strategy_type_registry() == []`, so this suite must not leak rows.
    """
    yield
    db = await get_db()
    await db.execute("DELETE FROM product_strategy_type_registry")
    await db.execute("DELETE FROM product")
    await db.commit()


@pytest.fixture(autouse=True)
def _patch_binding(monkeypatch):
    """Control the recomputed binding deterministically (independent of authority data)."""
    state = {"binding": dict(_BIND)}

    def fake(product):
        return dict(state["binding"])

    monkeypatch.setattr(sfr, "_strategy_binding", fake)
    return state


async def _seed(*, pid="P1", verified=True, materialized=True, registry=True,
                registry_active=True, registry_scene="SKINCARE", stored_fp="OLD_FP"):
    db = await get_db()
    await db.execute("DELETE FROM product")
    # Scope registry changes to THIS fixture's pair only — wiping the shared table leaks
    # into other suites when the per-test DB reset is unreliable (Windows WinError 32).
    await db.execute(
        "DELETE FROM product_strategy_type_registry WHERE cluster=? AND product_type_group=?",
        (_BIND["cluster"], _BIND["product_type_group"]))
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name,"
        " lifecycle_status, category, subcategory, type, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pid, pid, pid, pid, "ACTIVE", "Beauty", "Skincare", "Moisturizer",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    if verified:
        review, consumer, authority = "VERIFIED", "READY", "MANUAL_OVERRIDE"
    else:
        review, consumer, authority = "REVIEW_REQUIRED", "BLOCKED_REVIEW_REQUIRED", "AUTO_DERIVED"
    await db.execute(
        "UPDATE product_strategy_taxonomy SET product_fingerprint=?, cluster=?, product_type_group=?,"
        " matched_scene_strategy_id=?, scene_coverage_status=?, fallback_used=0, specific_strategy=1,"
        " review_status=?, consumer_status=?, authority_source=?,"
        " materialization_status=?, reviewer_id=?, reviewer_note=?, reviewed_at=?, updated_at=?"
        " WHERE product_id=?",
        (stored_fp, _BIND["cluster"], _BIND["product_type_group"], _BIND["matched_scene_strategy_id"],
         _BIND["scene_coverage_status"], review, consumer, authority,
         "MATERIALIZED" if materialized else "PLACEHOLDER",
         "faris", "owner ratified", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", pid))
    if registry:
        await db.execute(
            "INSERT INTO product_strategy_type_registry (cluster, product_type_group, display_name,"
            " matched_scene_strategy_id, scene_coverage_status, registry_status,"
            " auto_classification_enabled, authority_source) VALUES (?,?,?,?,?,?,?,?)",
            (_BIND["cluster"], _BIND["product_type_group"], "Moisturizer", registry_scene,
             "COVERED", "ACTIVE" if registry_active else "REVIEW_REQUIRED", 0, "SYSTEM_SEED"))
    await db.commit()


async def _tax(pid="P1"):
    db = await get_db()
    cur = await db.execute("SELECT * FROM product_strategy_taxonomy WHERE product_id=?", (pid,))
    row = await cur.fetchone()
    await cur.close()
    return dict(row)


async def _authorized(ids, path):
    digest = await sfr.compute_plan_digest(ids)
    return await sfr.apply_reconciliation(ids, authorize=True, expected_plan_digest=digest,
                                          snapshot_path=str(path))


# ── classification ───────────────────────────────────────────────────────────
async def test_fingerprint_only_stale_row_is_safe():
    await _seed()
    c = await sfr.classify_row("P1")
    assert c["cohort"] == sfr.COHORT_SAFE and c["eligible"] is True
    assert c["fingerprint_stale"] is True and c["binding_changed"] is False


async def test_binding_drift_is_excluded(_patch_binding):
    await _seed()
    _patch_binding["binding"]["product_type_group"] = "facial_cleanser"
    c = await sfr.classify_row("P1")
    assert c["cohort"] == sfr.COHORT_BINDING_CHANGED and c["eligible"] is False


async def test_inactive_registry_pair_is_excluded():
    await _seed(registry_active=False)
    c = await sfr.classify_row("P1")
    assert c["cohort"] == sfr.COHORT_REGISTRY_INVALID and c["eligible"] is False


async def test_missing_registry_pair_is_excluded():
    await _seed(registry=False)
    assert (await sfr.classify_row("P1"))["cohort"] == sfr.COHORT_REGISTRY_INVALID


async def test_registry_scene_mismatch_is_excluded():
    await _seed(registry_scene="OTHER_SCENE")
    assert (await sfr.classify_row("P1"))["cohort"] == sfr.COHORT_REGISTRY_INVALID


async def test_non_materialized_row_is_excluded():
    await _seed(verified=False, materialized=False)
    assert (await sfr.classify_row("P1"))["cohort"] == sfr.COHORT_PREEXISTING_BLOCKED


async def test_previously_blocked_row_is_excluded():
    await _seed(verified=False)
    assert (await sfr.classify_row("P1"))["cohort"] == sfr.COHORT_PREEXISTING_BLOCKED


async def test_already_current_row_is_noop(tmp_path):
    await _seed()
    fp = (await sfr.classify_row("P1"))["current_fingerprint"]
    db = await get_db()
    await db.execute("UPDATE product_strategy_taxonomy SET product_fingerprint=? WHERE product_id='P1'", (fp,))
    await db.commit()
    c = await sfr.classify_row("P1")
    assert c["cohort"] == sfr.COHORT_ALREADY_CURRENT and c["eligible"] is False
    res = await _authorized(["P1"], tmp_path / "s.json")
    assert res["changed_count"] == 0


async def test_missing_row_is_unexpected():
    await _seed()
    assert (await sfr.classify_row("NOPE"))["cohort"] == sfr.COHORT_MISSING


# ── gates ────────────────────────────────────────────────────────────────────
async def test_authorize_false_writes_nothing(tmp_path):
    await _seed()
    res = await sfr.apply_reconciliation(["P1"], authorize=False)
    assert res["authorized"] is False and res["wrote"] is False
    assert (await _tax())["product_fingerprint"] == "OLD_FP"


async def test_digest_and_snapshot_required(tmp_path):
    await _seed()
    assert (await sfr.apply_reconciliation(["P1"], authorize=True))["aborted"] == "PLAN_DIGEST_REQUIRED"
    assert (await sfr.apply_reconciliation(["P1"], authorize=True,
            expected_plan_digest="x"))["aborted"] == "DURABLE_SNAPSHOT_PATH_REQUIRED"


async def test_digest_drift_aborts_without_writing(tmp_path):
    await _seed()
    res = await sfr.apply_reconciliation(["P1"], authorize=True, expected_plan_digest="WRONG",
                                         snapshot_path=str(tmp_path / "s.json"))
    assert res["aborted"] == "PLAN_DIGEST_MISMATCH" and res["wrote"] is False
    assert (await _tax())["product_fingerprint"] == "OLD_FP"


async def test_product_timestamp_drift_aborts(tmp_path):
    await _seed()
    digest = await sfr.compute_plan_digest(["P1"])
    db = await get_db()
    await db.execute("UPDATE product SET updated_at='2099-01-01T00:00:00Z' WHERE id='P1'")
    await db.commit()
    res = await sfr.apply_reconciliation(["P1"], authorize=True, expected_plan_digest=digest,
                                         snapshot_path=str(tmp_path / "s.json"))
    assert res["aborted"] == "PLAN_DIGEST_MISMATCH"


async def test_taxonomy_timestamp_drift_aborts(tmp_path):
    await _seed()
    digest = await sfr.compute_plan_digest(["P1"])
    db = await get_db()
    await db.execute("UPDATE product_strategy_taxonomy SET updated_at='2099-01-01T00:00:00Z' WHERE product_id='P1'")
    await db.commit()
    res = await sfr.apply_reconciliation(["P1"], authorize=True, expected_plan_digest=digest,
                                         snapshot_path=str(tmp_path / "s.json"))
    assert res["aborted"] == "PLAN_DIGEST_MISMATCH"


async def test_registry_drift_aborts(tmp_path):
    await _seed()
    digest = await sfr.compute_plan_digest(["P1"])
    db = await get_db()
    await db.execute("UPDATE product_strategy_type_registry SET registry_status='REVIEW_REQUIRED'")
    await db.commit()
    res = await sfr.apply_reconciliation(["P1"], authorize=True, expected_plan_digest=digest,
                                         snapshot_path=str(tmp_path / "s.json"))
    assert res["aborted"] == "PLAN_DIGEST_MISMATCH"


# ── apply ────────────────────────────────────────────────────────────────────
async def test_apply_writes_only_two_columns_and_preserves_provenance(tmp_path):
    await _seed()
    before = await _tax()
    snap = tmp_path / "snap.json"
    res = await _authorized(["P1"], snap)
    assert res["wrote"] is True and res["changed_count"] == 1
    after = await _tax()
    changed = {k for k in after if str(before.get(k)) != str(after.get(k))}
    assert changed == {"product_fingerprint", "updated_at"}, changed
    for f in sfr.PROVENANCE_FIELDS + sfr.BINDING_FIELDS:
        assert after[f] == before[f], f
    assert after["reviewer_id"] == "faris" and after["reviewer_note"] == "owner ratified"
    assert after["review_status"] == "VERIFIED" and after["consumer_status"] == "READY"
    data = json.loads(snap.read_text())
    assert data["writable_columns"] == ["product_fingerprint", "updated_at"]
    assert data["rows"][0]["before"]["product_fingerprint"] == "OLD_FP"


async def test_apply_does_not_touch_product_table(tmp_path):
    await _seed()
    db = await get_db()
    cur = await db.execute("SELECT * FROM product WHERE id='P1'")
    before = dict(await cur.fetchone())
    await cur.close()
    await _authorized(["P1"], tmp_path / "s.json")
    cur = await db.execute("SELECT * FROM product WHERE id='P1'")
    after = dict(await cur.fetchone())
    await cur.close()
    assert before == after


async def test_excluded_row_is_not_written(tmp_path):
    await _seed(verified=False)
    res = await _authorized(["P1"], tmp_path / "s.json")
    assert res["changed_count"] == 0 and res["excluded_count"] == 1
    assert (await _tax())["product_fingerprint"] == "OLD_FP"


async def test_second_apply_is_idempotent(tmp_path):
    await _seed()
    await _authorized(["P1"], tmp_path / "s1.json")
    second = await _authorized(["P1"], tmp_path / "s2.json")
    assert second["changed_count"] == 0


async def test_rowcount_mismatch_rolls_back_whole_cohort(tmp_path, monkeypatch):
    await _seed()
    real = sfr.classify_row

    async def with_ghost(pid):
        if pid == "GHOST":
            return {"product_id": "GHOST", "cohort": sfr.COHORT_SAFE, "eligible": True,
                    "stored_fingerprint": "X", "current_fingerprint": "Y",
                    "taxonomy_updated_at": "2026-01-03T00:00:00Z",
                    "stored_binding": dict(_BIND),
                    "provenance": {f: None for f in sfr.PROVENANCE_FIELDS}}
        return await real(pid)

    monkeypatch.setattr(sfr, "classify_row", with_ghost)
    res = await _authorized(["P1", "GHOST"], tmp_path / "s.json")
    assert res["wrote"] is False and res["aborted"] == "ROWCOUNT_MISMATCH"
    assert (await _tax())["product_fingerprint"] == "OLD_FP"  # cohort rolled back


# ── rollback ─────────────────────────────────────────────────────────────────
async def test_cas_rollback_restores_only_the_two_columns(tmp_path):
    await _seed()
    snap = tmp_path / "snap.json"
    await _authorized(["P1"], snap)
    assert (await _tax())["product_fingerprint"] != "OLD_FP"
    rb = await sfr.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 1 and rb["verify_ok"] is True
    after = await _tax()
    assert after["product_fingerprint"] == "OLD_FP"
    assert after["review_status"] == "VERIFIED" and after["reviewer_id"] == "faris"


async def test_cas_rollback_refuses_to_clobber_later_work(tmp_path):
    await _seed()
    snap = tmp_path / "snap.json"
    await _authorized(["P1"], snap)
    db = await get_db()
    await db.execute("UPDATE product_strategy_taxonomy SET updated_at='2099-01-01T00:00:00Z' WHERE product_id='P1'")
    await db.commit()
    rb = await sfr.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 0
    assert rb["skipped_cas"][0]["reason"] == "CHANGED_SINCE_RECONCILIATION"
    assert (await _tax())["updated_at"] == "2099-01-01T00:00:00Z"


# ── bounded operational driver (scripts/strategy_fingerprint_reconciliation_04c.py) ──
# The mechanism above is fail-closed and was never defective. The first canonical 04C run
# still repaired nothing: the ad-hoc driver computed the plan digest over the full 284-ID
# authorized cohort, then invoked apply with the filtered 283-row SAFE subset — two cohorts,
# two digests, a correct PLAN_DIGEST_MISMATCH refusal and zero repair. These tests pin the
# committed driver's invariant that makes that class of mismatch structurally impossible.
import importlib.util as _ilu
from pathlib import Path as _Path

_DRIVER_PATH = _Path(__file__).resolve().parents[2] / "scripts" / "strategy_fingerprint_reconciliation_04c.py"
_spec = _ilu.spec_from_file_location("sfr_04c_driver", _DRIVER_PATH)
driver = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(driver)


async def _seed_second(pid, *, verified):
    """Add a second product sharing the seeded registry pair (does not wipe the first)."""
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name,"
        " lifecycle_status, category, subcategory, type, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pid, pid, pid, pid, "ACTIVE", "Beauty", "Skincare", "Moisturizer",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    review, consumer = ("VERIFIED", "READY") if verified else ("REVIEW_REQUIRED", "BLOCKED_REVIEW_REQUIRED")
    await db.execute(
        "UPDATE product_strategy_taxonomy SET product_fingerprint=?, cluster=?, product_type_group=?,"
        " matched_scene_strategy_id=?, scene_coverage_status=?, fallback_used=0, specific_strategy=1,"
        " review_status=?, consumer_status=?, authority_source='MANUAL_OVERRIDE',"
        " materialization_status='MATERIALIZED', updated_at='2026-01-03T00:00:00Z'"
        " WHERE product_id=?",
        ("OLD_FP", _BIND["cluster"], _BIND["product_type_group"], _BIND["matched_scene_strategy_id"],
         _BIND["scene_coverage_status"], review, consumer, pid))
    await db.commit()


async def test_driver_binds_the_digest_to_the_exact_cohort_it_applies(tmp_path, monkeypatch):
    """THE regression test: whatever cohort reaches apply, the digest must be that cohort's."""
    await _seed()
    await _seed_second("P2", verified=False)  # forces eligible(1) != cohort(2)
    seen = {}

    async def capture(ids, **kw):
        seen["ids"] = list(ids)
        seen["digest"] = kw["expected_plan_digest"]
        return {"authorized": True, "wrote": True, "changed_count": 0, "excluded_count": 0}

    monkeypatch.setattr(sfr, "apply_reconciliation", capture)
    cohort = ("P2", "P1")
    await driver.apply_bound(cohort, tmp_path / "s.json")

    assert seen["ids"] == list(cohort), "driver must not filter the cohort before applying"
    assert seen["digest"] == await sfr.compute_plan_digest(seen["ids"])


async def test_driver_apply_repairs_safe_row_and_excludes_blocked_row(tmp_path):
    await _seed()
    await _seed_second("P2", verified=False)
    res = await driver.apply_bound(("P1", "P2"), tmp_path / "s.json")
    assert res["wrote"] is True
    assert res["changed_count"] == 1 and res["excluded_count"] == 1
    assert res["excluded"][0]["product_id"] == "P2"
    assert (await _tax("P1"))["product_fingerprint"] != "OLD_FP"
    assert (await _tax("P2"))["product_fingerprint"] == "OLD_FP"  # untouched


async def test_historical_subset_digest_mismatch_reproduces_and_writes_nothing(tmp_path):
    """The exact defect that produced the canonical PLAN_DIGEST_MISMATCH abort."""
    await _seed()
    await _seed_second("P2", verified=False)
    full_cohort_digest = await sfr.compute_plan_digest(["P1", "P2"])
    res = await sfr.apply_reconciliation(
        ["P1"], authorize=True, expected_plan_digest=full_cohort_digest,
        snapshot_path=str(tmp_path / "s.json"))
    assert res["wrote"] is False and res["aborted"] == "PLAN_DIGEST_MISMATCH"
    assert res["live_digest"] != full_cohort_digest
    assert (await _tax("P1"))["product_fingerprint"] == "OLD_FP"


def test_cohort_loader_verifies_the_accepted_set_hash(tmp_path):
    ids = ["b", "a", "c"]
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"ids": ids}), encoding="utf-8")
    sha = driver.cohort_set_sha256(ids)
    assert driver.load_authorized_cohort(good, sha) == ("a", "b", "c")

    with pytest.raises(driver.CohortAuthorizationError) as exc:
        driver.load_authorized_cohort(good, "0" * 64)
    assert "COHORT_ARTIFACT_SHA_MISMATCH" in str(exc.value)


def test_cohort_loader_refuses_duplicate_ids(tmp_path):
    dupes = ["a", "a", "b"]
    p = tmp_path / "dupes.json"
    p.write_text(json.dumps({"ids": dupes}), encoding="utf-8")
    with pytest.raises(driver.CohortAuthorizationError) as exc:
        driver.load_authorized_cohort(p, driver.cohort_set_sha256(dupes))
    assert "COHORT_CONTAINS_DUPLICATE_IDS" in str(exc.value)


def test_accepted_04b_cohort_artifact_still_matches_its_published_hash():
    """The owner-accepted 284-ID artifact must remain byte-authentic on disk.

    Evidence under `outputs/` is deliberately uncommitted, so this guard only runs where
    the canonical artifact is actually present (the operator's machine).
    """
    if not driver.COHORT_ARTIFACT.exists():
        pytest.skip("accepted 04B cohort artifact not present in this checkout")
    cohort = driver.load_authorized_cohort()
    assert len(cohort) == 284
    assert driver.cohort_set_sha256(cohort) == driver.COHORT_SHA256
