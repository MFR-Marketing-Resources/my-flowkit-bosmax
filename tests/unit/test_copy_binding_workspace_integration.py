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
    # copy_intelligence, sanitized through to_compiler_copy, and tagged as
    # operator-approved so bank filler cannot displace it in dialogue assembly.
    approved = models.serialize_copy_set(await crud.get_copy_set(csid))
    expected = dict(to_compiler_copy(approved), copy_source=binding.COPY_SOURCE_SELECTED)
    assert captured["copy_intelligence"] == expected
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


# ── Explicit-Fallback-Confirmation V1 ───────────────────────
def _not_selected_compile_result():
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
        "prompt_fingerprint": "fp_fb",
        "warnings": [binding.WARN_NOT_SELECTED],
        "blockers": [],
        "source_of_truth_notes": [],
        "continuation_lineage": [],
        "runtime_config_snapshot": {},
        "copy_binding": binding.not_selected_lineage(),
    }


@pytest.mark.asyncio
async def test_final_without_copyset_without_confirmation_fails_closed():
    # Gate is the FIRST thing in create — no product/package needed to trip it.
    with pytest.raises(binding.CopyBindingError) as exc:
        await wep.create_workspace_execution_package(
            "prod-x", "T2V", 8, "9:16", "Veo 3.1 - Pro", False
        )
    assert exc.value.code == binding.ERR_FALLBACK_CONFIRMATION_REQUIRED
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_final_without_copyset_with_confirmation_succeeds_keeps_not_selected(monkeypatch):
    captured = {}

    async def fake_package(product_id, mode):
        return _minimal_package(product_id, mode)

    async def fake_compile(**kwargs):
        assert kwargs.get("copy_set_id") is None  # preview compiled in fallback mode
        return _not_selected_compile_result()

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(wep, "get_approved_product_package", fake_package)
    monkeypatch.setattr(wep, "compile_workspace_prompt_preview", fake_compile)
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package",
        fake_store,
    )

    result = await wep.create_workspace_execution_package(
        "prod-fb", "T2V", 8, "9:16", "Veo 3.1 - Pro", False, copy_fallback_confirmed=True
    )

    cb = result["copy_binding"]
    # Fallback is still recorded as NOT_SELECTED / landbank_fallback / warning.
    assert cb["copy_binding_status"] == binding.BINDING_NOT_SELECTED
    assert cb["copy_source"] == binding.COPY_SOURCE_LANDBANK_FALLBACK
    assert cb["warning"] == binding.WARN_NOT_SELECTED
    # Confirmation stamped as SEPARATE audit metadata.
    assert cb["copy_fallback_confirmed"] is True
    assert cb["copy_fallback_confirmation_required"] is True
    assert cb["copy_fallback_confirmation_source"] == binding.COPY_FALLBACK_CONFIRMATION_SOURCE
    assert cb["copy_fallback_policy"] == binding.COPY_FALLBACK_POLICY
    # Persisted lineage carries the same confirmation metadata.
    stored = json.loads(captured["request_lineage_payload"])["copy_binding"]
    assert stored["copy_fallback_confirmed"] is True
    assert stored["copy_binding_status"] == binding.BINDING_NOT_SELECTED


@pytest.mark.asyncio
async def test_final_with_approved_copyset_needs_no_confirmation(monkeypatch):
    captured = {}

    async def fake_package(product_id, mode):
        return _minimal_package(product_id, mode)

    async def fake_compile(**kwargs):
        return {
            **_not_selected_compile_result(),
            "copy_binding": {
                "copy_source": binding.COPY_SOURCE_SELECTED,
                "copy_binding_status": binding.BINDING_BOUND,
                "copy_set_id": kwargs.get("copy_set_id"),
                "copy_set_status": models.STATUS_COPY_APPROVED,
                "copy_set_fingerprint": "cs_x",
                "copy_set_angle": "A",
                "copy_set_hook_preview": "H",
                "warning": None,
            },
            "warnings": [],
        }

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(wep, "get_approved_product_package", fake_package)
    monkeypatch.setattr(wep, "compile_workspace_prompt_preview", fake_compile)
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package",
        fake_store,
    )

    # copy_set_id provided + NO confirmation -> gate passes, binds normally.
    result = await wep.create_workspace_execution_package(
        "prod-bound", "T2V", 8, "9:16", "Veo 3.1 - Pro", False, copy_set_id="cs-approved"
    )
    cb = result["copy_binding"]
    assert cb["copy_binding_status"] == binding.BINDING_BOUND
    # No confirmation metadata when a Copy Set is bound.
    assert "copy_fallback_confirmed" not in cb


@pytest.mark.asyncio
async def test_invalid_copyset_fails_closed_even_with_confirmation(monkeypatch):
    product = await _make_product()
    pid = product["id"]
    _patch_package_environment(monkeypatch, product, "T2V")

    # An explicit (but invalid) copy_set_id must fail closed via the resolver —
    # confirmation does NOT bypass it (the gate only applies to a missing id).
    with pytest.raises(binding.CopyBindingError) as exc:
        await wep.create_workspace_execution_package(
            pid, "T2V", 8, "9:16", "Veo 3.1 - Pro", False,
            copy_set_id="ghost-id", copy_fallback_confirmed=True,
        )
    assert exc.value.code == binding.ERR_NOT_FOUND


@pytest.mark.asyncio
async def test_confirmed_fallback_real_compile_no_metadata_leak(monkeypatch):
    product = await _make_product(raw_product_title="Fallback Leakproof Serum")
    pid = product["id"]
    _patch_package_environment(monkeypatch, product, "T2V")

    captured = {}

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package",
        fake_store,
    )

    result = await wep.create_workspace_execution_package(
        pid, "T2V", 8, "9:16", "Veo 3.1 - Pro", False, copy_fallback_confirmed=True
    )

    # Real deterministic compiler ran in fallback mode; the engine-facing prompt
    # text must not carry confirmation/policy audit tokens or internal fields.
    prompt_text = captured["prompt_text"]
    for forbidden in (
        "copy_fallback_confirmed",
        "copy_fallback_confirmation",
        binding.COPY_FALLBACK_POLICY,
        "copy_binding",
        binding.WARN_NOT_SELECTED,
    ):
        assert forbidden not in prompt_text
    # Lineage still records the confirmed fallback (audit only).
    stored = json.loads(captured["request_lineage_payload"])["copy_binding"]
    assert stored["copy_binding_status"] == binding.BINDING_NOT_SELECTED
    assert stored["copy_fallback_confirmed"] is True
