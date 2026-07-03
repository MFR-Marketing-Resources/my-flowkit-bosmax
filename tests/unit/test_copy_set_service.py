"""Unit tests for the Copy Set service (Copy Strategy Studio Phase 1).

Covers: resolver chain (landbank vs copy-signal), dedupe idempotency, status
derivation, explicit approval gate, fail-closed claim/risk validation, edit/
reject/regenerate transitions, and compiler compatibility of the Copy Set
payload — WITHOUT touching the Google Flow execution lane or the prompt compiler.
"""
from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.services import copy_set_service as svc
from agent.services.canonical_prompt_compiler import normalize_copy_intelligence


async def _make_product(**kw) -> str:
    product = await crud.create_product(
        raw_product_title=kw.pop("raw_product_title", "Test Serum 5ML"),
        source="MANUAL",
        **kw,
    )
    return product["id"]


def _fake_signal(**over):
    base = dict(
        copy_signals={
            "hook": "Nak kulit nampak segar sepanjang hari?",
            "usp_1": "Sesuai untuk rutin harian yang ringkas",
            "usp_2": "Mudah digunakan tanpa leceh",
            "usp_3": "Formula ringan senang diserap",
            "cta": "Cuba masukkan dalam rutin kau hari ni.",
        },
        route="DIRECT",
        review_status="AUTO_APPROVED",
        claim_gate="CLAIM_SAFE",
        copy_quality_status="COMMERCIAL_COPY_READY",
        text_to_video_readiness_status="READY",
        warnings=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


def _no_landbank(monkeypatch):
    monkeypatch.setattr(svc.copy_landbank_service, "lookup", lambda *a, **k: None)


def _fake_generator(monkeypatch, response):
    async def fake_gen(_payload):
        return response
    monkeypatch.setattr(svc, "generate_copy_signal_response", fake_gen)


@pytest.mark.asyncio
async def test_generate_uses_copy_signal_and_persists(monkeypatch):
    pid = await _make_product(copywriting_angle="Segar sepanjang hari")
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())

    result = await svc.generate_copy_set({"product_id": pid})

    assert result["created"] is True
    assert result["dedupe_match"] is False
    cs = result["copy_set"]
    assert cs["hook"] == "Nak kulit nampak segar sepanjang hari?"
    assert cs["cta"].endswith("hari ni.")
    assert cs["usp_set"] == [
        "Sesuai untuk rutin harian yang ringkas",
        "Mudah digunakan tanpa leceh",
        "Formula ringan senang diserap",
    ]
    assert cs["angle"] == "Segar sepanjang hari"
    assert cs["source"] == models.SOURCE_SIGNAL_GENERATOR
    assert cs["status"] == models.STATUS_DRAFT_COPY  # clean + complete + DIRECT
    assert cs["route_type"] == "DIRECT"


@pytest.mark.asyncio
async def test_generate_is_idempotent_on_dedupe_key(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())

    first = await svc.generate_copy_set({"product_id": pid})
    second = await svc.generate_copy_set({"product_id": pid})

    assert first["created"] is True
    assert second["created"] is False
    assert second["dedupe_match"] is True
    assert second["copy_set"]["copy_set_id"] == first["copy_set"]["copy_set_id"]


@pytest.mark.asyncio
async def test_generate_prefers_landbank(monkeypatch):
    pid = await _make_product()
    monkeypatch.setattr(
        svc.copy_landbank_service,
        "lookup",
        lambda product_id, angle=None: {
            "angle": "Nilai stok rumah",
            "hook": "Stok rumah lagi berbaloi bila beli format besar",
            "subhook": "Isi ulang senang masuk rutin basuh",
            "usps": ["Jimat jangka panjang", "Praktikal untuk demo"],
            "cta": "Pilih variasi dan tambah ke cart.",
            "formula_family": "HSO",
            "copy_id": "c-001",
            "language": "BM_MS",
        },
    )

    result = await svc.generate_copy_set({"product_id": pid})
    cs = result["copy_set"]
    assert cs["source"] == models.SOURCE_LANDBANK
    assert cs["subhook"] == "Isi ulang senang masuk rutin basuh"
    assert cs["provenance"]["copy_id"] == "c-001"


@pytest.mark.asyncio
async def test_generate_flags_review_when_incomplete(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(
        monkeypatch,
        _fake_signal(copy_signals={"hook": "Ada hook", "usp_1": "Satu USP", "cta": ""}),
    )

    result = await svc.generate_copy_set({"product_id": pid})
    cs = result["copy_set"]
    assert cs["status"] == models.STATUS_COPY_REVIEW_REQUIRED
    assert "cta" in cs["claim_review"]["completeness"]["missing_fields"]


@pytest.mark.asyncio
async def test_explicit_overrides_win(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())

    result = await svc.generate_copy_set(
        {"product_id": pid, "hook": "Hook operator manual", "cta": "CTA operator manual"}
    )
    cs = result["copy_set"]
    assert cs["hook"] == "Hook operator manual"
    assert cs["cta"] == "CTA operator manual"


@pytest.mark.asyncio
async def test_approve_requires_exact_phrase(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]

    with pytest.raises(svc.CopySetPermissionError) as exc:
        await svc.approve_copy_set(cs["copy_set_id"], {"approval_phrase": "WRONG"})
    assert exc.value.code == "INVALID_APPROVAL_PHRASE"


@pytest.mark.asyncio
async def test_approve_fails_closed_on_unsafe_copy(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]

    # Inject an unsafe claim via edit, then attempt approval.
    await svc.patch_copy_set(
        cs["copy_set_id"], {"cta": "This will cure you and results are guaranteed"}
    )
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(
            cs["copy_set_id"], {"approval_phrase": models.APPROVAL_PHRASE}
        )
    assert exc.value.code == "COPY_SET_UNSAFE"
    assert "MEDICAL_CLAIM" in exc.value.detail["violations"]

    stored = await svc.get_copy_set(cs["copy_set_id"])
    assert stored["status"] != models.STATUS_COPY_APPROVED


@pytest.mark.asyncio
async def test_approve_fails_closed_on_incomplete_copy(monkeypatch):
    pid = await _make_product()
    row = await crud.create_copy_set(pid, hook="Only a hook", status=models.STATUS_DRAFT_COPY)
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(row["copy_set_id"], {"approval_phrase": models.APPROVAL_PHRASE})
    assert exc.value.code == "COPY_SET_INCOMPLETE"


@pytest.mark.asyncio
async def test_approve_success_sets_approved_metadata(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]

    approved = await svc.approve_copy_set(
        cs["copy_set_id"],
        {"approval_phrase": models.APPROVAL_PHRASE, "reviewer_note": "looks good", "approved_by": "faris"},
    )
    assert approved["status"] == models.STATUS_COPY_APPROVED
    assert approved["approved_at"]
    assert approved["approved_by"] == "faris"


@pytest.mark.asyncio
async def test_edit_reverts_prior_approval(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]
    await svc.approve_copy_set(cs["copy_set_id"], {"approval_phrase": models.APPROVAL_PHRASE})

    edited = await svc.patch_copy_set(cs["copy_set_id"], {"hook": "Hook baru selepas approve"})
    assert edited["status"] != models.STATUS_COPY_APPROVED
    assert edited["approved_at"] is None


@pytest.mark.asyncio
async def test_reject_sets_rejected(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]

    rejected = await svc.reject_copy_set(cs["copy_set_id"], {"reviewer_note": "angle salah"})
    assert rejected["status"] == models.STATUS_COPY_REJECTED
    assert rejected["reviewer_note"] == "angle salah"


@pytest.mark.asyncio
async def test_regenerate_keeps_id_and_resets_status(monkeypatch):
    pid = await _make_product()
    _no_landbank(monkeypatch)
    _fake_generator(monkeypatch, _fake_signal())
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]
    await svc.approve_copy_set(cs["copy_set_id"], {"approval_phrase": models.APPROVAL_PHRASE})

    regenerated = await svc.regenerate_copy_set(cs["copy_set_id"])
    assert regenerated["copy_set_id"] == cs["copy_set_id"]
    assert regenerated["status"] != models.STATUS_COPY_APPROVED
    assert regenerated["approved_at"] is None
    assert regenerated["provenance"]["regenerated_from"] == cs["copy_set_id"]


@pytest.mark.asyncio
async def test_copy_set_payload_is_compiler_compatible(monkeypatch):
    pid = await _make_product()
    monkeypatch.setattr(
        svc.copy_landbank_service,
        "lookup",
        lambda product_id, angle=None: {
            "angle": "Nilai stok rumah",
            "hook": "Stok rumah lagi berbaloi bila beli format besar",
            "subhook": "Isi ulang senang masuk rutin basuh",
            "usps": ["Jimat jangka panjang", "Praktikal untuk demo"],
            "cta": "Pilih variasi dan tambah ke cart.",
            "formula_family": "HSO",
            "copy_id": "c-001",
            "language": "BM_MS",
        },
    )
    cs = (await svc.generate_copy_set({"product_id": pid}))["copy_set"]

    copy_input = models.to_compiler_copy(cs)
    compiled = normalize_copy_intelligence(copy_input, product={"copywriting_angle": cs["angle"]})

    assert compiled["hook"] == cs["hook"]
    assert compiled["subhook"] == cs["subhook"]
    assert compiled["cta"] == cs["cta"]
    assert compiled["usps"] == cs["usp_set"]
    assert compiled["formula_family"] == "HSO"
    # No internal metadata may cross into compiler input.
    assert "status" not in copy_input
    assert "copy_set_id" not in copy_input
    assert "dedupe_key" not in copy_input


def test_scan_copy_safety_flags_categories():
    unsafe = svc.scan_copy_safety(
        {"hook": "Guaranteed cure", "usp_set": ["clinically proven"], "cta": "before and after"}
    )
    assert unsafe["safe"] is False
    for code in ("MEDICAL_CLAIM", "GUARANTEED_RESULT", "CLINICAL_AUTHORITY_PROOF", "BEFORE_AFTER_IMPLICATION"):
        assert code in unsafe["violations"]

    safe = svc.scan_copy_safety(
        {"hook": "Nak rutin nampak kemas?", "usp_set": ["Senang guna"], "cta": "Cuba hari ni."}
    )
    assert safe["safe"] is True


def test_scan_copy_safety_flags_metadata_leak():
    # The literal product id value leaking into copy is a metadata leak.
    leak = svc.scan_copy_safety(
        {"hook": "Produk abc123def456 memang power", "usp_set": [], "cta": ""},
        product_id="abc123def456",
    )
    assert "INTERNAL_METADATA_LEAK" in leak["violations"]
    assert leak["detail"]["INTERNAL_METADATA_LEAK"] == "product_id"
