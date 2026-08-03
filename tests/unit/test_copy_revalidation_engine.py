"""COPY-CORRECTIVE-B03/B04: deterministic (free) semantic grounding + atomic
revalidation of salvageable pre-existing copy.
"""
import json

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.services.copy_set_validity_service import (
    assess_semantic_grounding,
    evaluate_copy_set_id,
    quarantine_copy_set,
    revalidate_copy_set,
)

_SNAP = {
    "product_description": "Serum vitamin C mencerahkan kulit kusam dan melembapkan",
    "benefits_json": '["mencerahkan kulit kusam", "melembapkan sepanjang hari"]',
    "usp_json": '["vitamin C sepuluh peratus", "menyerap cepat"]',
    "target_customer_text": "wanita kulit kusam",
    "buyer_persona_snapshot_json": '{"audience": "wanita bekerja"}',
    "copy_strategy_summary_json": '{"angles": ["kulit cerah"]}',
}


# ── Deterministic grounding (pure, set-level, cross-language tolerant) ────────
def test_grounding_true_when_copy_maps_to_pi():
    g = assess_semantic_grounding(
        hook="Kulit lebih cerah dengan vitamin C",
        subhook="menyerap cepat tanpa melekit",
        usp_list=["Vitamin mencerahkan kulit kusam", "Melembapkan sepanjang masa"],
        snapshot=_SNAP,
    )
    assert g["grounded"] is True
    assert g["overlap_count"] >= 2


def test_grounding_false_for_generic_unmapped_copy():
    g = assess_semantic_grounding(
        hook="Identiti jelas produk",
        subhook="pilihan praktikal",
        usp_list=["Nilai yang mudah difahami", "Sesuai rutin"],
        snapshot=_SNAP,
    )
    assert g["grounded"] is False
    assert "WEAK_GROUNDING" in g["reasons"]


def test_grounding_cross_language_via_title():
    # PI is ENGLISH, copy is MALAY — grounded through shared + product-title anchors
    # (the real false-negative class that over-strict token matching produced).
    snap = {
        "product_description": "A long Muslimah sport jersey in quick-dry microfiber",
        "benefits_json": '["Quick-dry fabric", "Long modest cut"]',
        "usp_json": '["Microfiber quick-dry"]',
    }
    g = assess_semantic_grounding(
        hook="Susah cari baju sukan yang labuh?",
        usp_list=[
            "Jersi QAYRAA diperbuat daripada mikrofiber quick dry, ringan dan labuh",
            "Bersukan dengan tenang dan penuh keyakinan",
        ],
        snapshot=snap,
        product_title="QAYRAA P1 Jersi Muslimah Microfiber Quick Dry Baju Sukan Labuh",
    )
    assert g["grounded"] is True
    assert g["overlap_count"] >= 2


def test_grounding_false_when_no_usp_or_empty_pi():
    assert assess_semantic_grounding(hook="Kulit cerah", usp_list=[], snapshot=_SNAP)["grounded"] is False
    g = assess_semantic_grounding(
        hook="Kulit cerah vitamin", usp_list=["Vitamin mencerahkan"], snapshot={}
    )
    assert g["grounded"] is False
    assert "EMPTY_PI_AUTHORITY" in g["reasons"]


# ── Atomic revalidation (integration) ────────────────────────────────────────
async def _eligible_product() -> str:
    from tests.conftest import make_product_copy_eligible

    product = await crud.create_product(raw_product_title="Reval Serum 5ML", source="MANUAL")
    pid = product["id"]
    await make_product_copy_eligible(pid)
    return pid


async def _quarantined_approved_set(pid: str) -> str:
    row = await crud.create_copy_set(
        pid,
        angle="Kulit segar",
        hook="Kulit lembap 12 jam tanpa melekit",
        subhook="Untuk kulit kombinasi",
        usp_set_json=json.dumps(["Menyerap dalam 10 saat", "Untuk kulit kombinasi", "Tanpa pewangi"]),
        cta="Dapatkan sekarang",
        platform="TIKTOK",
        language="BM_MS",
        route_type="DIRECT",
        formula_family="HSO",
        dedupe_key="reval-" + pid,
        status=models.STATUS_COPY_APPROVED,
        claim_review_json=json.dumps({"completeness": {"complete": True}, "safety": {"safe": True}}),
        pi_eligibility_status="NEEDS_REVALIDATION",
        pi_ineligible_reasons="COPY_FINAL_CURSOR_MASS_APPROVAL_PENDING_STRICT_REVIEW",
    )
    return row["copy_set_id"]


@pytest.mark.asyncio
async def test_revalidate_makes_quarantined_approved_set_valid():
    pid = await _eligible_product()
    cid = await _quarantined_approved_set(pid)

    # Invalid before: quarantined + no semantic receipt.
    before = await evaluate_copy_set_id(cid)
    assert before["valid"] is False
    assert any("QUARANTINED" in r or "SEMANTIC_REVIEW" in r for r in before["reasons"])

    await revalidate_copy_set(
        cid,
        reviewer="corrective-revalidation-engine",
        rationale="Deterministically grounded on current approved PI; non-generic; complete; safe.",
    )

    after = await evaluate_copy_set_id(cid)
    assert after["valid"] is True, after["reasons"]
    stored = await crud.get_copy_set(cid)
    assert not (stored["pi_eligibility_status"] or "")  # quarantine cleared
    assert stored["pi_snapshot_id"]  # lineage stamped


@pytest.mark.asyncio
async def test_quarantine_marks_needs_revalidation():
    pid = await _eligible_product()
    row = await crud.create_copy_set(
        pid, status=models.STATUS_COPY_APPROVED, dedupe_key="q-" + pid, hook="x"
    )
    cid = row["copy_set_id"]
    await quarantine_copy_set(cid, reason="COPY_FINAL_CURSOR_MASS_APPROVAL_PENDING_STRICT_REVIEW")
    stored = await crud.get_copy_set(cid)
    assert stored["pi_eligibility_status"] == "NEEDS_REVALIDATION"
    assert "MASS_APPROVAL" in (stored["pi_ineligible_reasons"] or "")
