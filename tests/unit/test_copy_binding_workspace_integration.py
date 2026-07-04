"""Integration tests: selected Copy Set -> workspace compile path -> deterministic
compiler (Copy Selection & Compiler Binding Foundation V1).

Proves that:
- a selected approved Copy Set reaches compile_ugc_video_prompt as copy_intelligence,
- the final engine-facing prompt text does NOT leak internal Copy Set metadata,
- no selection preserves fallback and surfaces a COPY_SET_NOT_SELECTED warning,
- an invalid selection fails closed,
- create_workspace_execution_package persists safe copy-binding lineage.

The deterministic compiler is exercised for real in the leak test — no AI provider
is called anywhere in this module.
"""
import json

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.models.copy_set import to_compiler_copy
from agent.services import copy_binding_service as binding
from agent.services import workspace_execution_package_service as wep


async def _make_product(**kw) -> dict:
    return await crud.create_product(
        raw_product_title=kw.pop("raw_product_title", "Binding Serum 5ML"),
        source="MANUAL",
        **kw,
    )


async def _make_approved_copy_set(product_id: str) -> str:
    row = await crud.create_copy_set(
        product_id,
        angle="Segar sepanjang hari",
        hook="Nak rutin kulit nampak segar sepanjang hari?",
        subhook="Rutin ringkas tanpa leceh",
        usp_set_json=json.dumps(
            ["Sesuai untuk rutin harian", "Mudah digunakan", "Formula ringan"]
        ),
        cta="Cuba masukkan dalam rutin kau hari ni.",
        platform="TIKTOK",
        language="BM_MS",
        route_type="DIRECT",
        formula_family="HSO",
        dedupe_key="binding-int-" + product_id,
        source="COPY_SIGNAL_GENERATOR",
        status=models.STATUS_COPY_APPROVED,
    )
    return row["copy_set_id"]


def _minimal_package(product_id: str, mode: str) -> dict:
    return {
        "prompt_package_snapshot_id": "pkg_bind",
        "product_id": product_id,
        "product_name": "Binding Serum 5ML",
        "mode": mode,
        "production_generation_allowed": False,
        "prompt_text": "legacy",
        "prompt_fingerprint": "legacy_fp",
        "asset_slots": [],
        "manual_fallback": {"copy_prompt_available": True},
        "blockers": [],
        "source_of_truth_notes": ["note"],
        "scene_context": "Bilik solek terang, meja kayu ringkas.",
        "claim_safe_rewrite": "Rutin ringkas untuk penampilan segar harian.",
    }


def _patch_package_environment(monkeypatch, product: dict, mode: str):
    async def fake_get_product(pid):
        return product

    async def fake_enrich(prod, persist=False):
        return dict(prod)

    async def fake_package(pid, m):
        return _minimal_package(pid, m)

    async def fake_claim_safe(pid):
        return {"safe_hook_angles": [], "safe_cta_angles": []}

    monkeypatch.setattr(wep, "crud", crud)
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.get_product",
        fake_get_product,
    )
    monkeypatch.setattr(wep, "enrich_product", fake_enrich)
    monkeypatch.setattr(wep, "get_approved_product_package", fake_package)
    monkeypatch.setattr(wep, "get_stored_claim_safe_package", fake_claim_safe)


@pytest.mark.asyncio
async def test_selected_copy_set_reaches_compiler_as_copy_intelligence(monkeypatch):
    product = await _make_product()
    pid = product["id"]
    csid = await _make_approved_copy_set(pid)
    _patch_package_environment(monkeypatch, product, "T2V")

    captured = {}

    def fake_compile_ugc(**kwargs):
        captured.update(kwargs)
        return {
            "final_compiled_prompt_text": "SECTION 1 - ROLE\nClean prompt.",
            "prompt_blocks": [],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "source_mode": "T2V",
            "generation_mode": "SINGLE",
            "total_duration_seconds": 8,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [],
            "dialogue_word_budget_per_block": [],
            "prompt_fingerprint": "fp_bind",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": [],
            "continuation_lineage": [],
            "runtime_config_snapshot": {},
        }

    monkeypatch.setattr(wep, "compile_ugc_video_prompt", fake_compile_ugc)

    result = await wep.compile_workspace_prompt_preview(
        product_id=pid, mode="T2V", duration_seconds=8, copy_set_id=csid
    )

    # The selected approved Copy Set was passed to the deterministic compiler as
    # copy_intelligence, sanitized through to_compiler_copy.
    approved = models.serialize_copy_set(await crud.get_copy_set(csid))
    assert captured["copy_intelligence"] == to_compiler_copy(approved)
    assert result["copy_binding"]["copy_binding_status"] == binding.BINDING_BOUND
    assert result["copy_binding"]["copy_set_id"] == csid


@pytest.mark.asyncio
async def test_no_copy_set_preserves_fallback_with_warning(monkeypatch):
    product = await _make_product()
    pid = product["id"]
    _patch_package_environment(monkeypatch, product, "T2V")

    captured = {}

    def fake_compile_ugc(**kwargs):
        captured.update(kwargs)
        return {
            "final_compiled_prompt_text": "SECTION 1 - ROLE\nFallback prompt.",
            "prompt_blocks": [],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "source_mode": "T2V",
            "generation_mode": "SINGLE",
            "total_duration_seconds": 8,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [],
            "dialogue_word_budget_per_block": [],
            "prompt_fingerprint": "fp_fallback",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": [],
            "continuation_lineage": [],
            "runtime_config_snapshot": {},
        }

    monkeypatch.setattr(wep, "compile_ugc_video_prompt", fake_compile_ugc)

    result = await wep.compile_workspace_prompt_preview(
        product_id=pid, mode="T2V", duration_seconds=8, copy_set_id=None
    )

    assert captured["copy_intelligence"] is None  # compiler applies its own fallback
    assert result["copy_binding"]["copy_binding_status"] == binding.BINDING_NOT_SELECTED
    assert binding.WARN_NOT_SELECTED in result["warnings"]


@pytest.mark.asyncio
async def test_invalid_selected_copy_set_fails_closed(monkeypatch):
    product = await _make_product()
    pid = product["id"]
    _patch_package_environment(monkeypatch, product, "T2V")

    with pytest.raises(binding.CopyBindingError) as exc:
        await wep.compile_workspace_prompt_preview(
            product_id=pid, mode="T2V", duration_seconds=8, copy_set_id="missing-id"
        )
    assert exc.value.code == binding.ERR_NOT_FOUND


@pytest.mark.asyncio
async def test_final_prompt_text_has_no_internal_metadata_leak(monkeypatch):
    """Runs the REAL deterministic compiler and asserts the engine-facing prompt
    text carries none of the Copy Set's internal metadata."""
    product = await _make_product(raw_product_title="Leakproof Serum")
    pid = product["id"]
    csid = await _make_approved_copy_set(pid)
    _patch_package_environment(monkeypatch, product, "T2V")

    result = await wep.compile_workspace_prompt_preview(
        product_id=pid, mode="T2V", duration_seconds=8, copy_set_id=csid
    )

    final_text = result["final_compiled_prompt_text"]
    approved = models.serialize_copy_set(await crud.get_copy_set(csid))
    for forbidden in (
        csid,
        approved["dedupe_key"],
        "dedupe_key",
        "provenance",
        "copy_set_id",
        models.STATUS_COPY_APPROVED,
        models.APPROVAL_PHRASE,
        "claim_review",
    ):
        assert forbidden not in final_text
    # Lineage still records the binding for audit (outside the prompt text).
    assert result["copy_binding"]["copy_binding_status"] == binding.BINDING_BOUND
    assert result["copy_binding"]["copy_set_id"] == csid


@pytest.mark.asyncio
async def test_execution_package_persists_copy_binding_lineage(monkeypatch):
    product = await _make_product()
    pid = product["id"]
    csid = await _make_approved_copy_set(pid)
    captured = {}

    async def fake_package(product_id, mode):
        return {
            **_minimal_package(product_id, mode),
            "asset_slots": [],
            "production_generation_allowed": False,
        }

    async def fake_compile_preview(**kwargs):
        return {
            "final_compiled_prompt_text": "SECTION 1 - ROLE\nClean prompt.",
            "prompt_blocks": [],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "source_mode": "T2V",
            "generation_mode": "SINGLE",
            "total_duration_seconds": 8,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [],
            "dialogue_word_budget_per_block": [],
            "prompt_fingerprint": "fp_exec",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": [],
            "continuation_lineage": [],
            "runtime_config_snapshot": {},
            "copy_binding": {
                "copy_source": binding.COPY_SOURCE_SELECTED,
                "copy_binding_status": binding.BINDING_BOUND,
                "copy_set_id": csid,
                "copy_set_status": models.STATUS_COPY_APPROVED,
                "copy_set_fingerprint": "cs_abc123",
                "copy_set_angle": "Segar sepanjang hari",
                "copy_set_hook_preview": "Nak rutin kulit nampak segar",
                "warning": None,
            },
        }

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(wep, "get_approved_product_package", fake_package)
    monkeypatch.setattr(wep, "compile_workspace_prompt_preview", fake_compile_preview)
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package",
        fake_store,
    )

    result = await wep.create_workspace_execution_package(
        pid, "T2V", 8, "9:16", "Veo 3.1 - Pro", False, copy_set_id=csid
    )

    assert result["copy_binding"]["copy_set_id"] == csid
    lineage = result["request_lineage_payload"]["copy_binding"]
    assert lineage["copy_binding_status"] == binding.BINDING_BOUND
    assert lineage["copy_set_id"] == csid
    # Persisted request lineage carries the same safe binding metadata.
    stored_lineage = json.loads(captured["request_lineage_payload"])
    assert stored_lineage["copy_binding"]["copy_set_id"] == csid
