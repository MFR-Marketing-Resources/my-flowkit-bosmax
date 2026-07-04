"""Unit tests for the Copy Set -> compiler binding resolver
(Copy Selection & Compiler Binding Foundation V1).

Covers the fail-closed resolution law: an explicitly selected Copy Set must
exist, belong to the product, and be COPY_APPROVED, else the bind fails closed.
No selection returns clean fallback + a COPY_SET_NOT_SELECTED warning. Only
to_compiler_copy fields ever cross into copy_intelligence — never ids, status,
provenance, or the dedupe key.
"""
import json

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.services import copy_binding_service as binding


async def _make_product(**kw) -> str:
    product = await crud.create_product(
        raw_product_title=kw.pop("raw_product_title", "Binding Test Serum 5ML"),
        source="MANUAL",
        **kw,
    )
    return product["id"]


async def _make_copy_set(product_id: str, *, status: str, **over) -> str:
    fields = dict(
        angle="Segar sepanjang hari",
        hook="Nak kulit nampak segar sepanjang hari?",
        subhook="Rutin ringkas tanpa leceh",
        usp_set_json=json.dumps(
            ["Sesuai untuk rutin harian", "Mudah digunakan", "Formula ringan"]
        ),
        cta="Cuba masukkan dalam rutin kau hari ni.",
        platform="TIKTOK",
        language="BM_MS",
        route_type="DIRECT",
        formula_family="HSO",
        dedupe_key="dedupe-" + product_id,
        source="COPY_SIGNAL_GENERATOR",
        status=status,
    )
    fields.update(over)
    row = await crud.create_copy_set(product_id, **fields)
    return row["copy_set_id"]


@pytest.mark.asyncio
async def test_no_selection_returns_fallback_with_warning():
    pid = await _make_product()
    result = await binding.resolve_compiler_copy_intelligence(pid, None)

    assert result["copy_intelligence"] is None
    assert result["warning"] == binding.WARN_NOT_SELECTED
    lineage = result["lineage"]
    assert lineage["copy_binding_status"] == binding.BINDING_NOT_SELECTED
    assert lineage["copy_source"] == binding.COPY_SOURCE_LANDBANK_FALLBACK
    assert lineage["copy_set_id"] is None


@pytest.mark.asyncio
async def test_approved_copy_set_binds_clean_copy_intelligence():
    pid = await _make_product()
    csid = await _make_copy_set(pid, status=models.STATUS_COPY_APPROVED)

    result = await binding.resolve_compiler_copy_intelligence(pid, csid)

    ci = result["copy_intelligence"]
    assert ci is not None
    assert ci["hook"] == "Nak kulit nampak segar sepanjang hari?"
    assert ci["cta"].endswith("hari ni.")
    assert ci["usps"] == ["Sesuai untuk rutin harian", "Mudah digunakan", "Formula ringan"]
    # No internal metadata may cross into compiler input.
    for forbidden in ("copy_set_id", "status", "dedupe_key", "provenance", "claim_review"):
        assert forbidden not in ci

    lineage = result["lineage"]
    assert lineage["copy_binding_status"] == binding.BINDING_BOUND
    assert lineage["copy_source"] == binding.COPY_SOURCE_SELECTED
    assert lineage["copy_set_id"] == csid
    assert lineage["copy_set_status"] == models.STATUS_COPY_APPROVED
    # The raw dedupe key (which embeds product id + copy) is never surfaced verbatim.
    assert lineage["copy_set_fingerprint"].startswith("cs_")
    assert "dedupe-" not in lineage["copy_set_fingerprint"]
    assert result["warning"] is None


@pytest.mark.asyncio
async def test_draft_copy_set_fails_closed():
    pid = await _make_product()
    csid = await _make_copy_set(pid, status=models.STATUS_DRAFT_COPY)
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid, csid)
    assert exc.value.code == binding.ERR_NOT_APPROVED


@pytest.mark.asyncio
async def test_review_required_copy_set_fails_closed():
    pid = await _make_product()
    csid = await _make_copy_set(pid, status=models.STATUS_COPY_REVIEW_REQUIRED)
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid, csid)
    assert exc.value.code == binding.ERR_NOT_APPROVED


@pytest.mark.asyncio
async def test_rejected_copy_set_fails_closed():
    pid = await _make_product()
    csid = await _make_copy_set(pid, status=models.STATUS_COPY_REJECTED)
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid, csid)
    assert exc.value.code == binding.ERR_NOT_APPROVED


@pytest.mark.asyncio
async def test_product_mismatch_fails_closed():
    pid_a = await _make_product()
    pid_b = await _make_product(raw_product_title="Other Product")
    csid = await _make_copy_set(pid_a, status=models.STATUS_COPY_APPROVED)
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid_b, csid)
    assert exc.value.code == binding.ERR_PRODUCT_MISMATCH


@pytest.mark.asyncio
async def test_missing_copy_set_fails_closed():
    pid = await _make_product()
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid, "does-not-exist")
    assert exc.value.code == binding.ERR_NOT_FOUND
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_approved_but_empty_copy_set_fails_binding():
    pid = await _make_product()
    # Directly forge an APPROVED row with no usable copy (bypasses the approval
    # gate). The resolver must refuse to hand an empty copy dict to the compiler.
    row = await crud.create_copy_set(
        pid, status=models.STATUS_COPY_APPROVED, dedupe_key="empty-" + pid
    )
    with pytest.raises(binding.CopyBindingError) as exc:
        await binding.resolve_compiler_copy_intelligence(pid, row["copy_set_id"])
    assert exc.value.code == binding.ERR_BINDING_FAILED
