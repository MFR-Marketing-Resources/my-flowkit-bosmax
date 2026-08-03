"""PI-FINAL-B04: the fail-closed COPY_ELIGIBLE gate is enforced at every copy/production
entrypoint. An ineligible product (no accepted snapshot / archived / merged alias) cannot be
selected, generate copy, create a bulk job, enter a batch or queue, be retried, create a poster
copy package, or create workspace generation/execution packages. Eligible active canonical
products continue to work (positive control)."""
import pytest

from agent.db import crud
from agent.services import copy_eligibility_service as elig
from tests.conftest import make_product_copy_eligible


async def _product(title="B04 Gate Product", **kw):
    row = await crud.create_product(
        raw_product_title=title, source="MANUAL",
        product_display_name=title, product_short_name=title, **kw)
    return row["id"]


# ── the gate itself ──────────────────────────────────────────────────────────

async def test_gate_fails_closed_without_snapshot_and_opens_after_acceptance():
    pid = await _product()
    result = await elig.copy_eligibility(pid)
    assert not result["eligible"]
    assert "NO_ACCEPTED_SNAPSHOT" in result["reasons"]
    with pytest.raises(ValueError, match="COPY_INELIGIBLE"):
        await elig.assert_copy_eligible(pid)

    await make_product_copy_eligible(pid)
    result = await elig.copy_eligibility(pid)
    assert result["eligible"], result["reasons"]


async def test_gate_fails_closed_for_merged_alias_and_archived():
    pid = await _product("B04 Alias Product")
    await make_product_copy_eligible(pid)
    db = await crud.get_db()
    await db.execute(
        "UPDATE product SET lifecycle_status='ARCHIVED', "
        "archived_reason='DUPLICATE_MERGED_TO_CANONICAL:xyz' WHERE id=?", (pid,))
    await db.commit()
    result = await elig.copy_eligibility(pid)
    assert not result["eligible"]
    assert "MERGED_ALIAS" in result["reasons"]
    assert "NOT_ACTIVE" in result["reasons"]


async def test_gate_requires_full_copy_critical_set():
    # a snapshot missing allowed_claims/persona/strategy is NOT copy-eligible even
    # though description/benefits/usp exist (the LEGACY_APPROVED_INCOMPLETE shape)
    pid = await _product("B04 Legacy Shape")
    draft = await crud.create_product_intelligence_review_draft(
        product_id=pid, review_status="APPROVED",
        product_description="d", benefits_json='["b"]', usp_json='["u"]',
        claim_gate="CLAIM_SAFE", claim_risk_level="LOW")
    await crud.create_product_intelligence_snapshot(
        product_id=pid, version=1, status="APPROVED",
        product_description="d", benefits_json='["b"]', usp_json='["u"]',
        claim_gate="CLAIM_SAFE", claim_risk_level="LOW",
        created_from_review_draft_id=draft["draft_id"])
    result = await elig.copy_eligibility(pid)
    assert not result["eligible"]
    assert any(r.startswith("MISSING_COPY_CRITICAL:") for r in result["reasons"])


async def test_claim_review_required_needs_recorded_acknowledgement():
    base = dict(lifecycle_status="ACTIVE", archived_reason=None,
                has_approved_snapshot=True,
                copy_critical_present={f: True for f in elig.COPY_CRITICAL_FIELDS})
    unack = elig.evaluate_copy_eligibility(claim_gate="CLAIM_REVIEW_REQUIRED", **base)
    assert not unack["eligible"]
    acked = elig.evaluate_copy_eligibility(
        claim_gate="CLAIM_REVIEW_REQUIRED", claim_review_acknowledged=True, **base)
    assert acked["eligible"]
    blocked = elig.evaluate_copy_eligibility(
        claim_gate="CLAIM_BLOCKED", claim_review_acknowledged=True, **base)
    assert not blocked["eligible"]


# ── entrypoint enforcement (negative paths) ──────────────────────────────────

async def test_copy_set_generate_refused_for_ineligible():
    from agent.services import copy_set_service as svc
    pid = await _product("B04 CopySet Product")
    with pytest.raises(svc.CopySetError) as exc:
        await svc.generate_copy_set({"product_id": pid})
    assert exc.value.code == "COPY_INELIGIBLE"
    assert exc.value.status_code == 409


async def test_copy_set_approve_refused_for_ineligible():
    from agent.services import copy_set_service as svc
    pid = await _product("B04 CopySet Approve")
    await make_product_copy_eligible(pid)
    created = await svc.generate_copy_set({"product_id": pid})
    # product becomes ineligible AFTER the copy set exists
    db = await crud.get_db()
    await db.execute("UPDATE product SET lifecycle_status='ARCHIVED' WHERE id=?", (pid,))
    await db.commit()
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(
            created["copy_set"]["copy_set_id"],
            {"approval_phrase": "APPROVE_COPY_SET", "approved_by": "t"})
    assert exc.value.code == "COPY_INELIGIBLE"


async def test_component_author_and_composer_refused_for_ineligible():
    from agent.services import copy_component_author_service as author_svc
    from agent.services import copy_composer_service as composer_svc
    pid = await _product("B04 Components Product")
    with pytest.raises(ValueError, match="COPY_INELIGIBLE"):
        await author_svc.author_components(pid, "value", "HOOK", count=3)
    with pytest.raises(ValueError, match="COPY_INELIGIBLE"):
        await composer_svc.compose_and_persist(pid, count=1)


async def test_batch_lane_refused_for_ineligible():
    from agent.services import batch_planner, batch_queue
    pid = await _product("B04 Batch Product")
    draft = await batch_planner.create_batch_draft({"product_id": pid, "quantity": 1})
    assert str(draft.get("error", "")).startswith("COPY_INELIGIBLE")


async def test_workspace_batch_generation_refused_for_ineligible():
    from agent.services import workspace_generation_package_service as wgps
    pid = await _product("B04 Workspace Batch")
    with pytest.raises(ValueError, match="COPY_INELIGIBLE"):
        await wgps.start_batch_generation(product_id=pid, modes=["IMG"], quantity_per_mode=1)


async def test_approved_product_package_refused_for_ineligible():
    from agent.services import approved_product_package_service as apps
    pid = await _product("B04 Package Product")
    with pytest.raises(ValueError, match="COPY_INELIGIBLE"):
        await apps.get_approved_product_package(pid, "T2V")


async def test_production_queue_approve_refuses_ineligible_package():
    from agent.services import production_queue_service as pqs
    pid = await _product("B04 Queue Product")
    import uuid as _uuid
    package = await crud.create_workspace_generation_package(
        f"wgp_{_uuid.uuid4().hex[:12]}",
        mode="T2V", product_id=pid, product_name_snapshot="B04 Queue Product",
        source_lane="T2V", prompt_package_snapshot_id="",
        workspace_execution_package_id=None, generation_mode="SINGLE",
        final_prompt_text="prompt", prompt_blocks_json="[]",
        selected_assets_json="{}", resolved_engine_slots_json="{}",
        resolver_output_json="{}", image_assets_json="{}",
        manual_handoff_json="{}", dom_handoff_payload_json="{}",
        blockers_json="[]", warnings_json="[]", status="READY_MANUAL")
    out = await pqs.approve_packages([package["workspace_generation_package_id"]])
    entry = out["results"][0]
    assert entry["ok"] is False
    assert str(entry["error"]).startswith("COPY_INELIGIBLE")


async def test_poster_copy_lanes_refused_for_ineligible():
    from agent.services.poster_copy_ai_service import PosterCopyAIError, recommend_objectives
    from agent.services.poster_copy_set_service import (
        PosterCopySetError, PosterCopySetService,
    )
    from agent.models.poster_copy_set import PosterCopySetCreateRequest
    pid = await _product("B04 Poster Product")
    with pytest.raises(PosterCopyAIError) as exc:
        await recommend_objectives(pid)
    assert exc.value.code == "COPY_INELIGIBLE"
    assert exc.value.status_code == 409
    with pytest.raises(PosterCopySetError) as exc2:
        await PosterCopySetService.create_draft(PosterCopySetCreateRequest(
            product_id=pid, objective="Intro", archetype="PRODUCT_HERO",
            angle="Hero", primary_message="msg", cta="Beli"))
    assert exc2.value.code == "COPY_INELIGIBLE"


# ── stale-asset quarantine ───────────────────────────────────────────────────

async def test_quarantine_sweep_marks_and_rotation_excludes():
    from agent.services import copy_set_service as svc
    from agent.services import copy_rotation_service as rot
    pid = await _product("B04 Quarantine Product")
    await make_product_copy_eligible(pid)
    created = await svc.generate_copy_set({"product_id": pid})
    cs_id = created["copy_set"]["copy_set_id"]
    await svc.approve_copy_set(cs_id, {"approval_phrase": "APPROVE_COPY_SET", "approved_by": "t"})
    assert [r["copy_set_id"] for r in await rot.list_eligible_copy_sets(pid)] == [cs_id]

    # the product loses eligibility -> sweep quarantines its copy assets
    db = await crud.get_db()
    await db.execute("UPDATE product SET lifecycle_status='ARCHIVED' WHERE id=?", (pid,))
    await db.commit()
    sweep = await elig.quarantine_stale_copy_assets()
    assert sweep["marked_pi_ineligible"] >= 1
    row = await crud.get_copy_set(cs_id)
    assert row["pi_eligibility_status"] == elig.PI_INELIGIBLE
    assert "NOT_ACTIVE" in (row["pi_ineligible_reasons"] or "")
    assert await rot.list_eligible_copy_sets(pid) == []

    # recovery: product becomes eligible again -> assets need revalidation, still excluded
    await db.execute("UPDATE product SET lifecycle_status='ACTIVE' WHERE id=?", (pid,))
    await db.commit()
    sweep2 = await elig.quarantine_stale_copy_assets()
    assert sweep2["marked_needs_revalidation"] >= 1
    row = await crud.get_copy_set(cs_id)
    assert row["pi_eligibility_status"] == elig.NEEDS_REVALIDATION
    assert await rot.list_eligible_copy_sets(pid) == []


# ── positive control: eligible products keep working ────────────────────────

async def test_eligible_product_full_copy_path_still_works():
    from agent.services import copy_set_service as svc
    from agent.services import copy_rotation_service as rot
    pid = await _product("B04 Positive Control")
    await make_product_copy_eligible(pid)
    created = await svc.generate_copy_set({"product_id": pid})
    cs_id = created["copy_set"]["copy_set_id"]
    approved = await svc.approve_copy_set(
        cs_id, {"approval_phrase": "APPROVE_COPY_SET", "approved_by": "t"})
    approved_row = approved.get("copy_set") or approved
    assert approved_row["status"] == "COPY_APPROVED"
    pool = await rot.list_eligible_copy_sets(pid)
    assert [r["copy_set_id"] for r in pool] == [cs_id]
