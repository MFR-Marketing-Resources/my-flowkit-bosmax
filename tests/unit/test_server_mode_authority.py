"""PR321 closure Defect 1 — SERVER-OWNED source-mode authority.

Every test runs the NORMAL production resolution (`trust_client_authority=False`)
against a REAL persisted execution package: the canonical source mode is derived
from the package's compiler lineage — never from a client declaration — and the
full per-mode reference contract is enforced:

  F2V/FRAMES 1-2 · HYBRID exactly 1 · I2V/INGREDIENTS 2-3 · T2V 0
"""
import json

import pytest
from fastapi import HTTPException

from agent.db import crud
from agent.services import flow_mode_reference_contract as refc
from agent.services import production_plan_resolver as resolver

_N = {"n": 0}


def _assets(pid, count):
    slots = ["subject", "scene", "style"][:count]
    return json.dumps([
        {"asset_id": f"product-image:{pid}:{slot}", "asset_fingerprint": f"sha-{slot}",
         "slot_key": slot, "media_id": f"media-{slot}"}
        for slot in slots])


async def _package(mode, source_mode, ref_count, *, lineage_omitted=False):
    """A REAL persisted execution package (the production authority fixture)."""
    _N["n"] += 1
    product = await crud.create_product(f"Authority Product {_N['n']}")
    pid = product["id"]
    pkg_id = f"wep_auth_{_N['n']}"
    lineage = "{}" if lineage_omitted else json.dumps(
        {"compiler": {"source_mode": source_mode}})
    await crud.create_or_replace_workspace_execution_package(
        pkg_id, product_id=pid, mode=mode, duration_seconds=16,
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT", model="veo_3_1_extension_lite",
        manual_override=False, prompt_text="PERSISTED block-1 prompt",
        prompt_fingerprint="pf", prompt_package_snapshot_id="snap",
        asset_slots=json.dumps([f"s{i}" for i in range(ref_count)]),
        resolved_assets=_assets(pid, ref_count),
        readiness="READY", execution_allowed=True, production_generation_allowed=True,
        manual_fallback="{}", blockers="[]", request_lineage_payload=lineage,
        source_of_truth_notes="[]")
    return pid, pkg_id


async def _resolve_production(pid, pkg_id):
    """The NORMAL production path — exactly what plan_video_job runs (trust=False)."""
    return await resolver.resolve_production_authority({
        "product_id": pid, "execution_package_id": pkg_id,
        "requested_duration_seconds": 16,
        # a client trying to smuggle authority — production strips ALL of it
        "initial_source_mode": "F2V",
        "initial_reference_media_ids": ["attacker-a", "attacker-b"],
    }, trust_client_authority=False)


def _contract_violated(out):
    return [m for m in out["missing"] if m.startswith("initial_reference_contract")]


# ── required tests 1-6: the production mode matrix ───────────────────────────
async def test_production_hybrid_package_one_reference_passes():
    pid, pkg = await _package("F2V", "HYBRID", 1)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "HYBRID"
    assert out["initial_reference_media_ids"] == ["media-subject"]
    assert _contract_violated(out) == []


async def test_production_hybrid_package_two_references_rejects():
    pid, pkg = await _package("F2V", "HYBRID", 2)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "HYBRID"
    assert _contract_violated(out), "HYBRID is exactly ONE product image"


async def test_production_i2v_package_one_reference_rejects():
    pid, pkg = await _package("I2V", "INGREDIENTS", 1)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "INGREDIENTS"
    assert _contract_violated(out), "INGREDIENTS requires 2-3 references"


async def test_production_i2v_package_two_and_three_references_pass():
    for count in (2, 3):
        pid, pkg = await _package("I2V", "INGREDIENTS", count)
        out = await _resolve_production(pid, pkg)
        assert out["initial_source_mode"] == "INGREDIENTS"
        assert len(out["initial_reference_media_ids"]) == count
        assert _contract_violated(out) == []


async def test_production_frames_package_one_and_two_references_pass():
    for count in (1, 2):
        pid, pkg = await _package("F2V", "FRAMES", count)
        out = await _resolve_production(pid, pkg)
        assert out["initial_source_mode"] == "FRAMES"
        assert _contract_violated(out) == []


async def test_production_t2v_package_with_any_reference_rejects():
    # Required test 6: a T2V package carrying a reference REJECTS in production —
    # never silently cleared, never attached, never converted.
    pid, pkg = await _package("T2V", "T2V", 1)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "T2V"
    assert out["initial_mode"] == "T2V"
    assert _contract_violated(out), "production T2V with a reference must reject"


async def test_production_t2v_package_without_references_passes():
    pid, pkg = await _package("T2V", "T2V", 0)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "T2V"
    assert out["initial_reference_media_ids"] == []
    assert _contract_violated(out) == []


# ── legacy packages (no persisted lineage) get the compiler's documented default ──
async def test_legacy_f2v_package_defaults_to_hybrid_lineage():
    pid, pkg = await _package("F2V", None, 1, lineage_omitted=True)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "HYBRID"
    assert _contract_violated(out) == []


async def test_legacy_i2v_package_defaults_to_ingredients_lineage():
    pid, pkg = await _package("I2V", None, 1, lineage_omitted=True)
    out = await _resolve_production(pid, pkg)
    assert out["initial_source_mode"] == "INGREDIENTS"
    assert _contract_violated(out), "legacy I2V package with 1 ref fails the contract"


# ── required test 8 continued: the production PLAN endpoint rejects with 422 ──
async def test_plan_video_job_production_rejects_i2v_contract_violation():
    from agent.api import flow
    pid, pkg = await _package("I2V", "INGREDIENTS", 1)
    body = flow.VideoJobPlanRequest(
        product_id=pid, execution_package_id=pkg,
        requested_total_duration_seconds=16, client_request_nonce="authz-e2e")
    with pytest.raises(HTTPException) as exc:
        await flow.plan_video_job(body)          # NORMAL production endpoint
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INCOMPLETE_PRODUCTION_PLAN"
    assert "initial_reference_contract" in str(exc.value.detail["detail"])


# ── the derivation helper's own contract ─────────────────────────────────────
def test_derive_package_source_mode_priority_and_defaults():
    lineage = json.dumps({"compiler": {"source_mode": "FRAMES"}})
    assert refc.derive_package_source_mode(
        {"mode": "F2V", "request_lineage_payload": lineage}) == "FRAMES"
    # legacy fallbacks = the compiler's documented per-mode defaults
    assert refc.derive_package_source_mode(
        {"mode": "F2V", "request_lineage_payload": "{}"}) == "HYBRID"
    assert refc.derive_package_source_mode(
        {"mode": "I2V", "request_lineage_payload": None}) == "INGREDIENTS"
    assert refc.derive_package_source_mode(
        {"mode": "T2V", "request_lineage_payload": "not-json"}) == "T2V"
    assert refc.derive_package_source_mode(None) is None
    assert refc.normalize_source_mode("F2V") == "FRAMES"
    assert refc.normalize_source_mode("hybrid") == "HYBRID"
    assert refc.normalize_source_mode("junk") is None
