"""Proves the WPS/chaining enforcement is ACTIVE in the live backend compile path.

These tests drive the real ``compile_workspace_prompt_preview`` chokepoint (the
single backend function that calls ``compile_ugc_video_prompt``) with the real
compiler — only product/package I/O is mocked — so a green run proves the new
``engine_duration_target`` / ``requested_total_duration_seconds`` params are
threaded end-to-end and the enforcement metadata is returned.
"""

import pytest

from agent.services.workspace_execution_package_service import (
    compile_workspace_prompt_preview,
)


def _install_product_mocks(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Wiring Product",
            "product_display_name": "Wiring Product",
        }

    async def fake_enrich(product, persist=False):
        return dict(product)

    async def fake_package(product_id: str, mode: str):
        return {
            "mode": mode,
            "claim_safe_rewrite": "Produk ini selesa digunakan setiap hari.",
        }

    async def fake_claim_safe(product_id: str):
        return {
            "safe_hook_angles": ["Cuba produk ini sekarang."],
            "safe_cta_angles": ["Dapatkan hari ini."],
        }

    def fake_scan(text, product_id):
        return {}  # no scan hits

    base = "agent.services.workspace_execution_package_service."
    monkeypatch.setattr(base + "crud.get_product", fake_get_product)
    monkeypatch.setattr(base + "enrich_product", fake_enrich)
    monkeypatch.setattr(base + "get_approved_product_package", fake_package)
    monkeypatch.setattr(base + "get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr(base + "scan_prompt_text", fake_scan)


async def _preview(monkeypatch, **kwargs):
    _install_product_mocks(monkeypatch)
    params = dict(
        product_id="prod-wiring",
        mode="F2V",
        duration_seconds=8,
        generation_mode="EXTEND",
        target_language="BM_MS",
    )
    params.update(kwargs)
    return await compile_workspace_prompt_preview(**params)


# ── Wiring is active: preview path passes the params and returns the chain ──
async def test_preview_google_flow_24s_resolves_three_block_chain(monkeypatch):
    result = await _preview(
        monkeypatch,
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=24,
    )
    assert result["resolved_block_chain"] == [8, 8, 8]
    assert result["total_duration_seconds"] == 24
    assert result["resolved_block_chain_source"] == "ENGINE_DURATION_POLICY"
    assert result["wps_chaining_enforced"] is True
    assert len(result["dialogue_word_budget_per_block"]) == 3
    assert len(result["actual_dialogue_word_count_per_block"]) == 3
    # 3+ blocks cannot be represented by the current 2-block UI → deterministic blocker.
    assert any(
        b.startswith("CHAIN_REQUIRES_MULTI_BLOCK_UI") for b in result["blockers"]
    )


async def test_preview_grok_16s_resolves_ten_six_chain(monkeypatch):
    result = await _preview(
        monkeypatch,
        engine_duration_target="GROK",
        requested_total_duration_seconds=16,
    )
    assert result["resolved_block_chain"] == [10, 6]
    assert result["engine_duration_target"] == "GROK"
    assert result["wps_chaining_enforced"] is True
    # 2-block chain fits the legacy UI → no unsupported-UI blocker.
    assert not any(
        b.startswith("CHAIN_REQUIRES_MULTI_BLOCK_UI") for b in result["blockers"]
    )


# ── engine_target (mode) is NOT overloaded ──────────────────────────────────
async def test_engine_target_mode_is_not_overloaded_by_vendor(monkeypatch):
    result = await _preview(
        monkeypatch,
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
    )
    assert result["engine_target"] == "F2V"            # still the MODE
    assert result["engine_duration_target"] == "GOOGLE_FLOW"  # vendor is separate


# ── Total derived from blocks when not explicitly supplied ──────────────────
async def test_total_derived_from_blocks_when_absent(monkeypatch):
    result = await _preview(
        monkeypatch,
        engine_duration_target="GOOGLE_FLOW",
        blocks=[
            {"block_index": 1, "duration_seconds": 8},
            {"block_index": 2, "duration_seconds": 8},
        ],
    )
    assert result["resolved_block_chain"] == [8, 8]
    assert result["requested_total_duration_seconds"] == 16
    assert "WPS_TOTAL_DERIVED_FROM_BLOCKS" in result["warnings"]


# ── Fail-safe paths (no silent ignore) ──────────────────────────────────────
async def test_engine_without_total_and_without_blocks_fails_safe(monkeypatch):
    with pytest.raises(ValueError, match="WPS_CHAINING_REQUIRES_TOTAL_DURATION"):
        await _preview(
            monkeypatch,
            engine_duration_target="GROK",
            generation_mode="SINGLE",
            blocks=[],
        )


async def test_unsupported_engine_duration_combo_fails_safe(monkeypatch):
    with pytest.raises(ValueError, match="UNSUPPORTED_ENGINE_DURATION"):
        await _preview(
            monkeypatch,
            engine_duration_target="GROK",
            requested_total_duration_seconds=8,  # 8s is Google-Flow-only
        )


async def test_unknown_engine_fails_safe(monkeypatch):
    with pytest.raises(ValueError, match="INVALID_ENGINE_DURATION_TARGET"):
        await _preview(
            monkeypatch,
            engine_duration_target="SORA",
            requested_total_duration_seconds=24,
        )


async def test_img_mode_with_engine_duration_target_fails_safe(monkeypatch):
    with pytest.raises(ValueError, match="WPS_CHAINING_NOT_SUPPORTED_FOR_IMG"):
        await _preview(
            monkeypatch,
            mode="IMG",
            engine_duration_target="GOOGLE_FLOW",
            requested_total_duration_seconds=24,
        )


# ── Legacy behavior preserved when new params absent ────────────────────────
async def test_legacy_path_unchanged_without_engine_duration_target(monkeypatch):
    result = await _preview(
        monkeypatch,
        generation_mode="EXTEND",
        blocks=[
            {"block_index": 1, "duration_seconds": 8},
            {"block_index": 2, "duration_seconds": 8},
        ],
    )
    assert result["wps_chaining_enforced"] is False
    assert result["engine_duration_target"] is None
    assert result["resolved_block_chain_source"] == "LEGACY_BLOCKS"
    assert "WPS_TOTAL_DERIVED_FROM_BLOCKS" not in result["warnings"]
    # Standard return keys preserved.
    for key in (
        "final_compiled_prompt_text",
        "prompt_blocks",
        "shot_plan",
        "warnings",
        "blockers",
        "runtime_config_snapshot",
        "engine_target",
    ):
        assert key in result
