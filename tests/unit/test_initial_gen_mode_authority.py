"""Execution-boundary source-mode contract for the durable-job initial segment.

_initial_gen_preconditions must re-validate the FULL per-source-mode reference
contract (min AND max) for TYPED jobs — so HYBRID = exactly one product image is
enforced HERE, not just the transport upper-cap (which would let 0 or 2 through).
LEGACY_UNTYPED jobs (no persisted source_mode) keep the lenient transport cap so a
job that never declared a source mode is not rejected by bounds it never chose.
"""
import json

import pytest

from agent.api.flow import _initial_gen_preconditions, InitialGenerationError
from agent.services import flow_mode_reference_contract as _refc


@pytest.mark.parametrize("sm,expected", [
    ("HYBRID", "TYPED"), ("FRAMES", "TYPED"), ("F2V", "TYPED"),
    ("INGREDIENTS", "TYPED"), ("I2V", "TYPED"), ("T2V", "TYPED"),
    (None, "LEGACY_UNTYPED"), ("", "LEGACY_UNTYPED"), ("garbage", "LEGACY_UNTYPED"),
])
def test_certify_source_mode(sm, expected):
    assert _refc.certify_source_mode(sm) == expected


def _job(**over) -> dict:
    base = {
        "initial_prompt_text": "a calm hero shot of the product",
        "initial_mode": "F2V",
        "initial_source_mode": "HYBRID",
        "product_id": "p1",
        "approved_asset_id": "a1",
        "approved_asset_sha256": "s1",
        "initial_reference_media_ids_json": json.dumps(["r1"]),
        "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
    }
    base.update(over)
    return base


def test_hybrid_typed_exactly_one_ref_passes():
    prompt, mode, refs, aspect = _initial_gen_preconditions(_job())
    assert mode == "F2V" and refs == ["r1"]


def test_hybrid_typed_two_refs_now_rejected():
    # 2 refs passes the F2V transport max-cap (2) but violates HYBRID = exactly 1.
    with pytest.raises(InitialGenerationError):
        _initial_gen_preconditions(_job(
            initial_reference_media_ids_json=json.dumps(["r1", "r2"])))


def test_hybrid_typed_zero_refs_rejected():
    with pytest.raises(InitialGenerationError):
        _initial_gen_preconditions(_job(
            initial_reference_media_ids_json=json.dumps([])))


@pytest.mark.parametrize("n,ok", [(1, True), (2, True), (3, False)])
def test_f2v_typed_bounds(n, ok):
    job = _job(initial_mode="F2V", initial_source_mode="FRAMES",
               initial_reference_media_ids_json=json.dumps([f"r{i}" for i in range(n)]))
    if ok:
        _initial_gen_preconditions(job)
    else:
        with pytest.raises(InitialGenerationError):
            _initial_gen_preconditions(job)


@pytest.mark.parametrize("n,ok", [(2, True), (3, True), (1, False), (4, False)])
def test_i2v_typed_bounds(n, ok):
    job = _job(initial_mode="I2V", initial_source_mode="INGREDIENTS",
               initial_reference_media_ids_json=json.dumps([f"r{i}" for i in range(n)]))
    if ok:
        _initial_gen_preconditions(job)
    else:
        with pytest.raises(InitialGenerationError):
            _initial_gen_preconditions(job)


def test_t2v_typed_zero_refs_passes():
    prompt, mode, refs, aspect = _initial_gen_preconditions(_job(
        initial_mode="T2V", initial_source_mode="T2V",
        approved_asset_id=None, approved_asset_sha256=None,
        initial_reference_media_ids_json=json.dumps([])))
    assert mode == "T2V" and refs == []


def test_legacy_untyped_i2v_single_ref_stays_lenient():
    # No source_mode → transport cap only. I2V default + 1 ref must NOT be rejected
    # by the min-2 source bound it never declared (no regression on legacy jobs).
    job = _job(initial_mode="I2V", initial_source_mode=None,
               initial_reference_media_ids_json=json.dumps(["r1"]))
    _prompt, mode, refs, _aspect = _initial_gen_preconditions(job)
    assert mode == "I2V" and refs == ["r1"]


def test_reference_order_preserved():
    _p, _m, refs, _a = _initial_gen_preconditions(_job(
        initial_mode="I2V", initial_source_mode="INGREDIENTS",
        initial_reference_media_ids_json=json.dumps(["first", "second", "third"])))
    assert refs == ["first", "second", "third"]
