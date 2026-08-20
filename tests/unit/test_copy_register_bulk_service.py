"""Unit tests for Lapis 2 Phase 1 bulk DRAFT copy generation (provider-free).

The generate flow is mocked so these tests exercise the driver's own logic —
eligibility, idempotency, DRAFT-only outcome, per-item fail-closed isolation, and the
deterministic formula recommender — without any provider call or credit spend.
"""
from agent.db.schema import get_db
from agent.services import copy_register_bulk_service as svc
from agent.services import copy_register_v2_service as v2
from agent.services.copy_formula_recommender import recommend_formula


async def _seed_product(pid: str, ptype: str = "lipstick_lip_tint", active: bool = True):
    db = await get_db()
    # INSERT OR REPLACE: the autouse DB reset is unreliable on Windows (file can be
    # held), so re-seeding the same id across tests must not raise. These tests only
    # ever look up their own requested ids, so leftover rows are harmless.
    await db.execute(
        "INSERT OR REPLACE INTO product (id, raw_product_title, product_display_name, "
        "product_short_name, lifecycle_status, copywriting_product_type_code, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            pid, f"Product {pid}", f"Product {pid}", f"Product {pid}",
            "ACTIVE" if active else "ARCHIVED", ptype,
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        ),
    )
    await db.commit()


# ── recommender (pure, deterministic) ──────────────────────────────────────────

def test_recommend_formula_is_deterministic_and_explicit():
    assert recommend_formula({"copywriting_product_type_code": "lipstick_lip_tint"})["formula_id"] == "BAB"
    assert recommend_formula({"copywriting_product_type_code": "wellness_supplement"})["formula_id"] == "PAS"
    assert recommend_formula(
        {"copywriting_product_type_code": "packaged_snack", "category": "Food & Beverage"}
    )["formula_id"] == "HSO"
    # unmatched -> explicit broad default (AIDA), recorded as matched_rule == -1
    fallback = recommend_formula({"copywriting_product_type_code": "womens_pants"})
    assert fallback["formula_id"] == "AIDA"
    assert fallback["matched_rule"] == -1
    assert fallback["rationale"]  # every choice carries an auditable reason
    # same input -> same output
    assert recommend_formula({"copywriting_product_type_code": "lipstick_lip_tint"}) == \
        recommend_formula({"copywriting_product_type_code": "lipstick_lip_tint"})


# ── create_run: eligibility + idempotency ──────────────────────────────────────

async def test_create_run_queues_eligible_and_skips_the_rest(monkeypatch):
    await _seed_product("PL1")
    await _seed_product("PL2")  # already has a blueprint -> SKIPPED
    await _seed_product("PA3", active=False)  # archived -> SKIPPED

    async def fake_list_blueprints(pid):
        return [object()] if pid == "PL2" else []

    monkeypatch.setattr(v2, "list_blueprints", fake_list_blueprints)

    run = await svc.create_run(["PL1", "PL2", "PA3", "PZZ"], "pilot")
    by_id = {i["product_id"]: i for i in run["items"]}
    assert by_id["PL1"]["status"] == "QUEUED"
    assert by_id["PL2"]["status"] == "SKIPPED" and by_id["PL2"]["error_code"] == "EXISTING_BLUEPRINT"
    assert by_id["PA3"]["status"] == "SKIPPED" and by_id["PA3"]["error_code"] == "PRODUCT_NOT_ACTIVE"
    assert by_id["PZZ"]["status"] == "SKIPPED" and by_id["PZZ"]["error_code"] == "PRODUCT_NOT_ACTIVE"
    assert run["status"] == "PENDING"
    assert run["total_expected"] == 4 and run["skipped"] == 3


async def test_create_run_rejects_empty_cohort():
    import pytest

    with pytest.raises(ValueError):
        await svc.create_run([], "x")


# ── run loop: DRAFT-only success + fail-closed isolation ────────────────────────

class _FakeBlueprint:
    blueprint_id = "bp_new"
    revision = 1


async def test_run_loop_generates_drafts_and_records_formula(monkeypatch):
    await _seed_product("PL1")
    monkeypatch.setattr(v2, "list_blueprints", lambda pid: _empty())
    monkeypatch.setattr(svc, "_PACE_SECONDS", 0)

    calls = {}

    async def fake_angles(pid, formula, objective):
        calls["formula"] = formula
        calls["objective"] = objective
        return {"angles": [{"angle_id": "ang1", "definition": "A grounded angle.", "evidence_fact_ids": ["f1", "f2"]}]}

    async def fake_gen(**kw):
        calls["gen_kwargs"] = kw
        return _FakeBlueprint()

    monkeypatch.setattr(v2, "generate_angle_options", fake_angles)
    monkeypatch.setattr(v2, "generate_blueprint", fake_gen)

    run = await svc.create_run(["PL1"], "pilot")
    await svc._run_loop(run["run_id"])
    done = await svc.get_run(run["run_id"])

    assert done["status"] == "COMPLETED"
    assert done["drafted"] == 1 and done["failed"] == 0
    item = done["items"][0]
    assert item["status"] == "DRAFTED"
    assert item["blueprint_id"] == "bp_new"
    assert item["formula_id"] == "BAB"  # lipstick -> BAB from the recommender
    assert item["angle_id"] == "ang1"
    # the driver passed the recommender's explicit formula + the mirrored contract
    assert calls["formula"] == "BAB"
    assert calls["objective"] == "conversion"
    assert calls["gen_kwargs"]["objective_id"] == "conversion"
    assert calls["gen_kwargs"]["angle_id"] == "ang1"
    assert calls["gen_kwargs"]["evidence_fact_ids"] == ["f1", "f2"]


async def test_run_loop_fails_closed_per_item(monkeypatch):
    await _seed_product("PF1")
    monkeypatch.setattr(v2, "list_blueprints", lambda pid: _empty())
    monkeypatch.setattr(svc, "_PACE_SECONDS", 0)

    async def boom(pid, formula, objective):
        raise v2.CopyRegisterV2Error("COPY_V2_FORMULA_REQUIRED", "no formula")

    monkeypatch.setattr(v2, "generate_angle_options", boom)

    run = await svc.create_run(["PF1"], "pilot")
    await svc._run_loop(run["run_id"])
    done = await svc.get_run(run["run_id"])

    assert done["status"] == "FAILED"  # 0 drafted, 1 failed
    assert done["failed"] == 1 and done["drafted"] == 0
    item = done["items"][0]
    assert item["status"] == "FAILED"
    assert item["error_code"] == "COPY_V2_FORMULA_REQUIRED"
    assert item["blueprint_id"] is None  # nothing produced, nothing approved


async def _empty():
    return []
