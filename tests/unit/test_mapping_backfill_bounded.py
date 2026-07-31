"""Safety tests for the bounded NULL-cohort mapping backfill mechanism.

Covers the frozen blockers:
  * stored-row truthfulness — persisted statuses must be reproducible from STORED values
    using the pure evaluators only (no enrichment anywhere in verification);
  * atomicity — rowcount mismatch / invariant violation rolls back the ENTIRE cohort;
  * rollback CAS — restores only what the backfill wrote, and compares EVERY restored
    column plus `updated_at`, so later legitimate changes are never clobbered.

`test_real_path_*` uses the REAL mapping rules and REAL enrich_product (no monkeypatch).
"""
import json

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services import mapping_backfill_bounded as bb
from agent.services.product_physics import evaluate_prompt_readiness
from agent.services.product_preflight import (
    CREATIVE_REQUIRED_FIELDS,
    evaluate_mapping_status,
)

# A complete authority set: with these stored, the PURE evaluators yield READY/READY
# (the seeded product also carries image_url, which the backfill never writes).
_FULL_FILL = {
    "category": "Beauty", "subcategory": "Skincare", "type": "Serum",
    "product_type": "UNIVERSAL", "product_type_id": "pt1", "silo": "s1",
    "trigger_id": "TR1", "formula": "PAS", "copywriting_angle": "trust-led",
    "claim_risk_level": "LOW", "mapping_source": "keyword",
    "scene_context": "clean shelf", "camera_style": "product close-up",
    "camera_behavior": "slow push-in", "camera_shot": "hero",
    "physics_class": "liquid_bottle", "product_scale": "palm", "recommended_grip": "one-hand",
    "handling_notes": "stable", "camera_handling_notes": "clean reveal",
    "section_5_product_physics_prompt": "bottle behaves rigidly",
    "section_5_physics_hint": "physics hint", "section_4_hint": "reveal hint",
    "section_6_copy_hint": "copy hint", "section_9_overlay_hint": "overlay hint",
}


async def _seed_product(pid, *, lifecycle="ACTIVE", mapping=None, image=True, **cols):
    db = await get_db()
    base = {"id": pid, "raw_product_title": pid, "product_display_name": pid,
            "product_short_name": pid, "lifecycle_status": lifecycle,
            "mapping_status": mapping, "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z"}
    if image:
        base["image_url"] = f"http://example.com/{pid}.jpg"
    base.update(cols)
    keys = list(base)
    await db.execute(
        f"INSERT INTO product ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
        [base[k] for k in keys])
    await db.commit()


async def _clear():
    db = await get_db()
    await db.execute("DELETE FROM product")
    await db.commit()


async def _status(pid):
    return (await crud.get_product(pid)).get("mapping_status")


async def _authorized(ids, path):
    digest = await bb.compute_cohort_digest(ids)
    return await bb.apply_bounded_backfill(ids, authorize=True, expected_plan_digest=digest,
                                           snapshot_path=str(path))


# ── contract: the writable set must cover everything the evaluators read ──────
def test_writable_fields_cover_evaluator_inputs():
    """Any evaluator input the backfill can't persist could produce an unreproducible
    status. Only fields the backfill must never author may be excluded."""
    never_written = {
        "product_display_name", "product_short_name",  # NOT NULL, always pre-existing
        "image_url", "local_image_path", "image_readiness_status",  # asset lane owns these
    }
    missing = [f for f in CREATIVE_REQUIRED_FIELDS
               if f not in bb.WRITABLE_AUTHORITY_FIELDS and f not in never_written]
    assert missing == [], f"evaluator inputs not persistable by the backfill: {missing}"
    for f in ("copywriting_angle", "claim_risk_level", "section_4_hint",
              "section_6_copy_hint", "section_9_overlay_hint", "physics_class",
              "section_5_product_physics_prompt"):
        assert f in bb.WRITABLE_AUTHORITY_FIELDS, f


def test_transient_enrichment_cannot_hide_a_missing_stored_field():
    """The pure stored-row evaluator refuses READY when a required field is absent from the
    row — precisely what an enrich-based verifier would have masked by re-deriving it."""
    complete = {"product_display_name": "X", "product_short_name": "X",
                "image_url": "http://x/y.jpg", **_FULL_FILL}
    assert bb.evaluate_stored_row(complete)["mapping_status"] == "READY"
    assert bb.evaluate_stored_row(complete)["prompt_readiness_status"] == "READY"
    gap = dict(complete)
    gap["copywriting_angle"] = ""
    assert bb.evaluate_stored_row(gap)["mapping_status"] != "READY"
    assert bb.evaluate_stored_row(gap)["prompt_readiness_status"] != "READY"


# ── guard behaviour (enrichment monkeypatched to isolate the guards) ──────────
@pytest.fixture
def patch_enrich(monkeypatch):
    def _apply(overrides):
        async def fake_enrich(product, *, persist=False):
            assert persist is False, "backfill must call enrich with persist=False"
            return {**product, **overrides.get(product.get("id"), {})}
        monkeypatch.setattr(bb, "enrich_product", fake_enrich)
    return _apply


async def test_preview_only_eligible(patch_enrich):
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL, "P_OVERWRITE": {"category": "DIFFERENT"}})
    await _seed_product("P_ELIGIBLE")
    await _seed_product("P_READY", mapping="READY")
    await _seed_product("P_APPROVED", mapping="APPROVED")
    await _seed_product("P_BLOCKED", mapping="BLOCKED")
    await _seed_product("P_NEEDSREVIEW", mapping="NEEDS_REVIEW")
    await _seed_product("P_ARCHIVED", lifecycle="ARCHIVED")
    await _seed_product("P_OVERWRITE", category="Original Category")

    ids = ["P_ELIGIBLE", "P_READY", "P_APPROVED", "P_BLOCKED", "P_NEEDSREVIEW",
           "P_ARCHIVED", "P_OVERWRITE"]
    plan = await bb.preview_bounded_backfill(ids)
    assert [e["product_id"] for e in plan["eligible"]] == ["P_ELIGIBLE"]
    reasons = {s["product_id"]: s["reason"] for s in plan["skipped"]}
    assert reasons["P_ARCHIVED"] == "NOT_ACTIVE"
    assert reasons["P_OVERWRITE"] == "WOULD_OVERWRITE_EXISTING"
    for p in ("P_READY", "P_APPROVED", "P_BLOCKED", "P_NEEDSREVIEW"):
        assert reasons[p].startswith("MAPPING_NOT_NULL")
    assert plan["plan_digest"]


async def test_authorize_false_and_missing_gates_write_nothing(patch_enrich, tmp_path):
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")
    assert (await bb.apply_bounded_backfill(["P_ELIGIBLE"], authorize=False))["wrote"] is False
    assert (await bb.apply_bounded_backfill(["P_ELIGIBLE"], authorize=True))["aborted"] == "PLAN_DIGEST_REQUIRED"
    assert (await bb.apply_bounded_backfill(["P_ELIGIBLE"], authorize=True,
                                            expected_plan_digest="x"))["aborted"] == "DURABLE_SNAPSHOT_PATH_REQUIRED"
    res = await bb.apply_bounded_backfill(["P_ELIGIBLE"], authorize=True,
                                          expected_plan_digest="WRONG",
                                          snapshot_path=str(tmp_path / "s.json"))
    assert res["aborted"] == "COHORT_DIGEST_MISMATCH"
    assert await _status("P_ELIGIBLE") is None


async def test_rowcount_mismatch_rolls_back_whole_cohort(patch_enrich, tmp_path, monkeypatch):
    """A phantom row (rowcount 0) must abort the ENTIRE cohort — no partial commit."""
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")

    real_classify = bb.classify_row

    async def classify_with_ghost(product):
        if product is None:  # the ghost id resolves to no row
            return {"product_id": "P_GHOST", "eligible": True, "proposed_status": "READY",
                    "proposed_prompt_readiness": "READY",
                    "write_fields": {"mapping_status": "READY"}}
        return await real_classify(product)

    monkeypatch.setattr(bb, "classify_row", classify_with_ghost)
    res = await _authorized(["P_ELIGIBLE", "P_GHOST"], tmp_path / "s.json")
    assert res["wrote"] is False and res["aborted"] == "ROWCOUNT_MISMATCH"
    assert res["rowcount_failures"][0]["product_id"] == "P_GHOST"
    assert await _status("P_ELIGIBLE") is None  # rolled back with the cohort


async def test_authorized_write_is_stored_row_truthful(patch_enrich, tmp_path):
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")
    await _seed_product("P_READY", mapping="READY")

    snap = tmp_path / "snap.json"
    res = await _authorized(["P_ELIGIBLE", "P_READY"], snap)
    assert res["wrote"] is True
    assert [c["product_id"] for c in res["changed"]] == ["P_ELIGIBLE"]
    assert await _status("P_READY") == "READY"  # protected row untouched

    v = await bb.verify_stored_row("P_ELIGIBLE")
    assert v["ok"] is True, v["mismatch"]
    stored = await crud.get_product("P_ELIGIBLE")
    assert stored["mapping_status"] == "READY"
    assert stored["copywriting_angle"] == "trust-led"           # actually persisted
    assert stored["section_5_product_physics_prompt"]            # actually persisted
    data = json.loads(snap.read_text())
    row = data["rows"][0]
    assert row["product_id"] == "P_ELIGIBLE"
    assert row["after"]["updated_at"] == data["applied_updated_at"]
    assert row["before"]["updated_at"] == "2026-01-01T00:00:00Z"


async def test_idempotent_second_apply(patch_enrich, tmp_path):
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")
    await _authorized(["P_ELIGIBLE"], tmp_path / "s1.json")
    second = await _authorized(["P_ELIGIBLE"], tmp_path / "s2.json")
    assert second["changed_count"] == 0


async def test_rollback_restores_written_columns(patch_enrich, tmp_path):
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")
    snap = tmp_path / "snap.json"
    await _authorized(["P_ELIGIBLE"], snap)
    assert await _status("P_ELIGIBLE") == "READY"

    rb = await bb.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 1 and rb["verify_ok"] is True
    assert await _status("P_ELIGIBLE") is None
    assert (await crud.get_product("P_ELIGIBLE"))["copywriting_angle"] in (None, "")


async def test_rollback_skips_when_updated_at_drifted(patch_enrich, tmp_path):
    """Any later write (updated_at drift) must make rollback fail closed for that row."""
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")
    snap = tmp_path / "snap.json"
    await _authorized(["P_ELIGIBLE"], snap)

    db = await get_db()
    await db.execute("UPDATE product SET updated_at='2099-01-01T00:00:00Z' WHERE id='P_ELIGIBLE'")
    await db.commit()

    rb = await bb.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 0
    assert rb["skipped_cas"][0]["reason"] == "CHANGED_SINCE_BACKFILL"
    assert await _status("P_ELIGIBLE") == "READY"  # newer work preserved


async def test_rollback_preserves_operator_change_to_written_field(patch_enrich, tmp_path):
    await _clear()
    patch_enrich({"P_ELIGIBLE": _FULL_FILL})
    await _seed_product("P_ELIGIBLE")
    snap = tmp_path / "snap.json"
    await _authorized(["P_ELIGIBLE"], snap)

    db = await get_db()  # operator legitimately re-categorises after the backfill
    await db.execute("UPDATE product SET category='Operator Choice' WHERE id='P_ELIGIBLE'")
    await db.commit()

    rb = await bb.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 0
    assert (await crud.get_product("P_ELIGIBLE"))["category"] == "Operator Choice"


async def test_rollback_never_touches_a_column_it_did_not_write(patch_enrich, tmp_path):
    """`category` pre-exists (never written by the backfill), so an operator change to it
    must survive rollback of the columns that WERE written."""
    await _clear()
    fill = {k: v for k, v in _FULL_FILL.items() if k != "category"}
    patch_enrich({"P_KEEPCAT": {**fill, "category": "Original Category"}})
    await _seed_product("P_KEEPCAT", category="Original Category")
    snap = tmp_path / "snap.json"
    res = await _authorized(["P_KEEPCAT"], snap)
    assert res["wrote"] is True
    assert "category" not in json.loads(snap.read_text())["rows"][0]["before"]

    db = await get_db()
    await db.execute("UPDATE product SET category='Operator Recategorised' WHERE id='P_KEEPCAT'")
    await db.commit()

    rb = await bb.rollback_from_snapshot(str(snap))
    assert rb["restored_count"] == 1  # written columns restored
    assert (await crud.get_product("P_KEEPCAT"))["category"] == "Operator Recategorised"


# ── REAL PATH: real mapping rules + real enrich_product, no monkeypatch ───────
async def test_real_path_stored_row_is_directly_reproducible(tmp_path):
    """End-to-end against the REAL authority table and REAL enrich_product. Whatever status
    the real rules produce, the STORED row must reproduce it under the pure evaluators."""
    await _clear()
    await _seed_product(
        "P_REAL",
        raw_product_title="SkyPlant Fragrant Multi-Effect Nourish Eye Balm Stick 9g Korean",
        product_display_name="SkyPlant Nourish Eye Balm Stick 9g",
        product_short_name="Eye Balm Stick",
        category="Beauty & Personal Care", subcategory="Skincare", type="Eye Treatments",
        source="MANUAL", asset_status="DOWNLOADED",
    )

    plan = await bb.preview_bounded_backfill(["P_REAL"])   # real enrich_product runs here
    assert plan["eligible_count"] == 1, plan["skipped"]

    res = await _authorized(["P_REAL"], tmp_path / "real.json")
    assert res["wrote"] is True and res["changed_count"] == 1

    stored = await crud.get_product("P_REAL")
    # run the PURE evaluators directly over the stored row — no enrichment at all
    mapping = evaluate_mapping_status(stored)
    readiness = evaluate_prompt_readiness(stored, stored)
    expected_prompt = readiness["prompt_readiness_status"]
    if mapping["mapping_status"] == "BLOCKED":
        expected_prompt = "MISSING_FIELDS"
    elif mapping["mapping_status"] == "NEEDS_REVIEW" and expected_prompt == "READY":
        expected_prompt = "NEEDS_REVIEW"

    assert stored["mapping_status"] == mapping["mapping_status"]
    assert stored["prompt_readiness_status"] == expected_prompt

    # if it claims READY, every field required for READY must actually be stored
    if stored["mapping_status"] == "READY":
        for f in CREATIVE_REQUIRED_FIELDS:
            assert str(stored.get(f) or "").strip(), f"READY but stored {f} is empty"
