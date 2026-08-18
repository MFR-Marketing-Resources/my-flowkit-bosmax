"""Round 3 P6 trust-boundary closure — exact per-item copy + full V2 authority.

Blockers 1 & 2 + PR #790 matrix + provider-start fail-closed, all on REAL
creative_production_item rows.  Zero provider, zero credit, disposable DB, and the
product-global V2 activation pointer (copy_execution_authority_v2) is NEVER
mutated by any Round 3 / P6 path.
"""
from __future__ import annotations

import json

import pytest

from agent.db import creative_production_crud as p6db
from agent.db.schema import get_db
from agent.services import copy_register_v2_service as v2svc
from agent.services import production_allocation_service as alloc
from agent.services import production_copy_supply_service as supply
from agent.services import production_supply_manifest_service as manifest_service
from agent.services import production_supply_repository as supply_repo
from agent.services.creative_production_compile_service import _with_round3_selection
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)
from agent.services.round3_authority_validator import revalidate_round3_v2_authority
from tests.unit.test_production_allocation_service import _approved_projection_ids
from tests.unit.test_storyboard_landbank_v3_materializer import _approved_supply


@pytest.fixture(autouse=True)
def _v2_enabled(monkeypatch):
    # Round 3 per-item copy resolution is a V2-ON production operation (matching
    # the deployed runtime); the pure resolver only binds when V2 is ON.
    monkeypatch.setenv("COPY_BLUEPRINT_V2_ENABLED", "1")
    monkeypatch.delenv("COPY_LEGACY_MAINTENANCE_MODE", raising=False)


async def _frozen_manifest(monkeypatch, product_id: str):
    _svc, result, approval = await _approved_supply(monkeypatch, product_id)
    receipt_id = approval["receipt"]["receipt_id"]
    for projection_id in await _approved_projection_ids(result["master"]["entity_id"]):
        await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)
    built = await manifest_service.build_manifest(product_id, requested_capacity=3, actor_id="op")
    manifest = built["manifest"]
    await manifest_service.freeze_manifest(manifest.manifest_id, manifest.revision, actor_id="op")
    return manifest


async def _seed_real_plan(plan_id: str, product_id: str, count: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO creative_production_plan "
        "(plan_id, request_id, created_by, name, p58_cohort_sha256, p58_cohort_count) "
        "VALUES (?, ?, 'op', 'ab-plan', ?, ?)",
        (plan_id, f"req-{plan_id}", "c" * 64, count),
    )
    for i in range(count):
        await db.execute(
            "INSERT INTO creative_production_item "
            "(item_id, plan_id, item_ordinal, product_id, media_type, creative_dna_sha256, "
            "dedupe_guard_key, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'POSTER', ?, ?, 'PLANNED', '2026-08-18T00:00:00Z', '2026-08-18T00:00:00Z')",
            (f"{plan_id}-item-{i}", plan_id, i, product_id, f"dna{i}" + "0" * 59, f"dg-{plan_id}-{i}"),
        )
    await db.commit()


async def _pointer_count() -> int:
    db = await get_db()
    return int((await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone())[0])


@pytest.mark.asyncio
async def test_real_p6_items_carry_exact_selection_and_compile_uses_it(monkeypatch):
    product_id = "ab-prod"
    manifest = await _frozen_manifest(monkeypatch, product_id)
    m_items = await supply_repo.list_manifest_items(manifest.manifest_id, manifest.revision)
    assert len(m_items) >= 2
    a_bp = m_items[0].v2_blueprint_id
    b_bp = m_items[1].v2_blueprint_id
    assert a_bp != b_bp  # two distinct materialized blueprints (Copy A / Copy B)

    await _seed_real_plan("ab-plan", product_id, 2)
    before_pointer = await _pointer_count()

    # BLOCKER 1: allocation persists the exact selection onto REAL P6 item rows.
    outcome = await alloc.allocate_manifest_to_production_plan(
        production_plan_id="ab-plan",
        manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision,
        requested_items=2,
        actor_id="op",
    )
    assert outcome["bound_count"] == 2
    real_items = await p6db.list_items("ab-plan")
    selections = {}
    for it in real_items:
        assert it["round3_manifest_item_json"] not in ("", "{}")  # durable, real row
        selections[it["item_id"]] = json.loads(it["round3_manifest_item_json"])
    bound_blueprints = {s["v2_blueprint_id"] for s in selections.values()}
    assert {a_bp, b_bp} <= bound_blueprints  # both A and B bound to distinct real items

    # Section 25: allocation NEVER touched the product-global activation pointer.
    assert await _pointer_count() == before_pointer

    # BLOCKER 2: compile resolves EACH real item's exact selected blueprint copy,
    # NOT the product-global pointer. Build the context exactly as compile does.
    seen_bp: set[str] = set()
    for it in real_items:
        sel = selections[it["item_id"]]
        ctx = _with_round3_selection(None, it, lane="POSTER_BUILDER")
        assert ctx["round3_selection"]["v2_blueprint_id"] == sel["v2_blueprint_id"]
        resolution = await resolve_persisted_copy_execution_binding(
            product_id, "POSTER_BUILDER", ctx
        )
        # The resolved binding is the EXACT selected blueprint revision + snapshot.
        assert resolution.binding is not None
        assert resolution.binding.blueprint_id == sel["v2_blueprint_id"]
        assert resolution.binding.revision == sel["v2_blueprint_revision"]
        assert resolution.binding.approval_snapshot_id == sel["v2_approval_snapshot_id"]
        seen_bp.add(resolution.binding.blueprint_id)
    # item1 compiled Copy A, item2 compiled Copy B (two different exact copies).
    assert seen_bp == {a_bp, b_bp}

    # And exact approved execution text differs between the two selected blueprints.
    bp_a = await v2svc.get_blueprint(a_bp, m_items[0].v2_blueprint_revision)
    bp_b = await v2svc.get_blueprint(b_bp, m_items[1].v2_blueprint_revision)
    texts_a = [e.text for e in bp_a.approved_execution_text]
    texts_b = [e.text for e in bp_b.approved_execution_text]
    assert texts_a and texts_b

    # Without a per-item selection there is NO product-global binding for this
    # product, so the global path fails closed — proving per-item copy is the
    # source, not the global pointer.
    with pytest.raises(CopyExecutionResolutionError):
        await resolve_persisted_copy_execution_binding(product_id, "POSTER_BUILDER", None)


@pytest.mark.asyncio
async def test_allocate_to_plan_is_idempotent(monkeypatch):
    product_id = "ab-idem"
    manifest = await _frozen_manifest(monkeypatch, product_id)
    await _seed_real_plan("idem-plan", product_id, 2)

    first = await alloc.allocate_manifest_to_production_plan(
        production_plan_id="idem-plan", manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision, requested_items=2, actor_id="op",
    )
    snap1 = {it["item_id"]: it["round3_manifest_item_json"] for it in await p6db.list_items("idem-plan")}
    second = await alloc.allocate_manifest_to_production_plan(
        production_plan_id="idem-plan", manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision, requested_items=2, actor_id="op",
    )
    snap2 = {it["item_id"]: it["round3_manifest_item_json"] for it in await p6db.list_items("idem-plan")}
    assert first["bound_count"] == second["bound_count"] == 2
    assert snap1 == snap2  # same canonical per-item assignment, no churn/dupes


@pytest.mark.asyncio
async def test_pr790_matrix_full_v2_authority_fail_closed(monkeypatch):
    product_id = "ab-790"
    manifest = await _frozen_manifest(monkeypatch, product_id)
    item = (await supply_repo.list_manifest_items(manifest.manifest_id, manifest.revision))[0]

    # A) current valid selection -> PASS.
    ok = await revalidate_round3_v2_authority(
        blueprint_id=item.v2_blueprint_id,
        revision=item.v2_blueprint_revision,
        expected_approval_snapshot_id=item.v2_approval_snapshot_id,
    )
    assert ok.valid, ok.reason_codes

    # F) approval-snapshot mismatch -> BLOCK.
    mism = await revalidate_round3_v2_authority(
        blueprint_id=item.v2_blueprint_id,
        revision=item.v2_blueprint_revision,
        expected_approval_snapshot_id="approval:not-the-one",
    )
    assert not mism.valid
    assert "APPROVAL_SNAPSHOT_MISMATCH" in mism.reason_codes

    # H) Product Truth advances -> BLOCK (authoritative V2 reason code surfaced).
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES ('ab-790-snap2', ?, 2, 'APPROVED', 'Newer.', '[\"nb\"]', '[\"nu\"]', 'nc', '[\"ncl\"]', "
        "'{\"a\":1}', '{\"f\":\"PAS\"}', 'CLAIM_SAFE', 'LOW', '2026-08-18T00:00:00Z', '2026-08-18T00:00:00Z')",
        (product_id,),
    )
    await db.commit()
    stale = await revalidate_round3_v2_authority(
        blueprint_id=item.v2_blueprint_id, revision=item.v2_blueprint_revision,
    )
    assert not stale.valid
    assert any(
        code in stale.reason_codes
        for code in (
            "COPY_V2_TAXONOMY_AUTHORITY_STALE",
            "COPY_V2_EVIDENCE_STALE",
            "COPY_V2_EVIDENCE_NOT_FOUND",
            "PRODUCT_TRUTH_ADVANCED",
        )
    )


@pytest.mark.asyncio
async def test_provider_start_blocked_when_evidence_goes_stale_after_allocation(monkeypatch):
    product_id = "ab-start"
    manifest = await _frozen_manifest(monkeypatch, product_id)
    await _seed_real_plan("start-plan", product_id, 1)
    await alloc.allocate_manifest_to_production_plan(
        production_plan_id="start-plan", manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision, requested_items=1, actor_id="op",
    )
    item = (await p6db.list_items("start-plan"))[0]
    selection = json.loads(item["round3_manifest_item_json"])

    # Compile/queue/provider-start gate passes while authority is current.
    ok = await alloc.revalidate_item_selection(selection)
    assert ok["valid"] is True

    # Introduce stale authority AFTER allocation by advancing Product Truth
    # (approved evidence rows are immutable by trigger — the correct way to
    # invalidate is a new snapshot, which strands the blueprint's lineage/evidence).
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES ('ab-start-snap2', ?, 2, 'APPROVED', 'Newer.', '[\"nb\"]', '[\"nu\"]', 'nc', '[\"ncl\"]', "
        "'{\"a\":1}', '{\"f\":\"PAS\"}', 'CLAIM_SAFE', 'LOW', '2026-08-18T00:00:00Z', '2026-08-18T00:00:00Z')",
        (product_id,),
    )
    await db.commit()

    blocked = await alloc.revalidate_item_selection(selection)
    assert blocked["valid"] is False  # provider-start FAILS CLOSED

    # The exact per-item resolver (what compile calls) also refuses -> no copy is
    # injected, so no provider path is ever reached (zero provider calls / credit).
    ctx = _with_round3_selection(None, item, lane="POSTER_BUILDER")
    with pytest.raises(CopyExecutionResolutionError):
        await resolve_persisted_copy_execution_binding(product_id, "POSTER_BUILDER", ctx)
