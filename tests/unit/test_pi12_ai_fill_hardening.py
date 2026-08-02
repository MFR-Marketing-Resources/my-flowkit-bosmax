"""Regression tests for the PI-12 audit hardening (B-03): status/schema enforcement on AI-fill
persona/strategy, object coercion, and the runner's generic gate now covering usp/persona/strategy.
"""
import importlib.util
from pathlib import Path

from agent.services.product_intelligence_review_draft_service import (
    _ai_fill_object_ok, _coerce_ai_fill_value, _AI_FILL_OBJECT_FIELDS, AI_FILL_TARGET_FIELDS,
)

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pi12r", REPO / "scripts" / "pi12_grounded_runner.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def test_object_fields_registered():
    assert "buyer_persona_snapshot_json" in AI_FILL_TARGET_FIELDS
    assert "copy_strategy_summary_json" in AI_FILL_TARGET_FIELDS
    assert set(_AI_FILL_OBJECT_FIELDS) == {"buyer_persona_snapshot_json", "copy_strategy_summary_json"}


def test_coerce_object_fields():
    assert _coerce_ai_fill_value("buyer_persona_snapshot_json", {"audience": "x", "empty": ""}) == {"audience": "x"}
    assert _coerce_ai_fill_value("buyer_persona_snapshot_json", "not a dict") is None
    assert _coerce_ai_fill_value("buyer_persona_snapshot_json", {}) is None


def test_persona_schema_requires_audience_and_need():
    assert _ai_fill_object_ok("buyer_persona_snapshot_json", {"audience": "gamers", "needs": ["low latency"]}) is True
    assert _ai_fill_object_ok("buyer_persona_snapshot_json", {"audience": "gamers"}) is False  # no need
    assert _ai_fill_object_ok("buyer_persona_snapshot_json", {"needs": ["x"]}) is False  # no audience
    assert _ai_fill_object_ok("buyer_persona_snapshot_json", {"foo": "bar"}) is False  # arbitrary dict rejected


def test_strategy_schema_requires_a_strategic_field():
    assert _ai_fill_object_ok("copy_strategy_summary_json", {"angles": ["value"]}) is True
    assert _ai_fill_object_ok("copy_strategy_summary_json", {"recommended_formula": "PAS"}) is True
    assert _ai_fill_object_ok("copy_strategy_summary_json", {"foo": "bar"}) is False


def test_runner_generic_gate_covers_usp_persona_strategy():
    # generic marker in USP is now caught
    assert R.is_generic({"usp_json": ["A product for everyday use"]})
    # generic marker in persona is now caught
    assert R.is_generic({"buyer_persona_snapshot_json": {"audience": "suitable for everyone"}})
    # generic marker in strategy is now caught
    assert R.is_generic({"copy_strategy_summary_json": {"angles": ["generic consumer appeal"]}})
    # clean product-specific content is not flagged
    assert not R.is_generic({"product_description": "SkyPlant Eye Balm Stick 9g Korean formula.",
                             "usp_json": ["9g stick format"], "buyer_persona_snapshot_json": {"audience": "eye-care shoppers"},
                             "copy_strategy_summary_json": {"angles": ["nourishing eye care"]}})


def test_runner_generic_gate_precision_no_false_positive_on_modifiers():
    # PRECISION FIX (2026-08-03): bare "everyday use" as a product-specific modifier must NOT be
    # flagged — these are grounded phrases, not template filler.
    assert not R.is_generic({"copy_strategy_summary_json": {"angles": ["Durability for everyday use"]}})
    assert not R.is_generic({"buyer_persona_snapshot_json": {"purchase_context": "ready-to-wear hijab for everyday use"}})
    assert not R.is_generic({"usage_text": "Insert the open end into the sealer and activate the vacuum."})
    # but the full template phrase that describes nothing is STILL caught
    assert R.is_generic({"product_description": "A product for everyday use."})
    assert R.is_generic({"product_description": "Suitable for everyone."})


def test_historical_baseline_floors_at_reconciled_nonprobe():
    # B-01: the fail-closed baseline must floor at the reconciled 529 non-probe total, not the ledger
    # 527 (which misses the 2 inferred retries). max(527, 529) == 529; the mission cap is fully spent.
    assert R.MISSION_HISTORICAL_NONPROBE == 529 == R.CALL_CAP
    assert max(527, R.MISSION_HISTORICAL_NONPROBE) == 529


def test_cap_rejects_next_attempt_when_baseline_full(tmp_path, monkeypatch):
    # B-01: with the 529 non-probe baseline spent, the very next provider attempt is rejected BEFORE
    # any request or reservation is written — no total-532 overshoot.
    monkeypatch.setattr(R, "RECEIPTS", tmp_path / "receipts.jsonl")
    monkeypatch.setattr(R, "_HISTORICAL_BASELINE", R.CALL_CAP)
    st, body = R.call("POST", "/product-intelligence/review-drafts/x/ai-fill-missing", {}, receipt_key="p1")
    assert st == 599 and body.get("error") == "PROVIDER_CAP_REACHED"
    assert not (tmp_path / "receipts.jsonl").exists()  # rejected before the call: nothing reserved


def test_crash_orphan_reservation_still_counted(tmp_path, monkeypatch):
    # B-01: a prior process that reserved an attempt then crashed BEFORE the OUTCOME/ledger write must
    # still count against the cap (not dropped), even though its run_id differs and it has no OUTCOME.
    rf = tmp_path / "receipts.jsonl"
    monkeypatch.setattr(R, "RECEIPTS", rf)
    R._receipt({"attempt_id": "orphan", "run_id": "prior-proc", "key": "p", "phase": "RESERVED"})
    assert R._reserved_count() == 1
    # baseline at cap-1 + this 1 orphan == cap -> the next attempt is rejected (no double-spend)
    monkeypatch.setattr(R, "_HISTORICAL_BASELINE", R.CALL_CAP - 1)
    st, body = R.call("POST", "/x/ai-fill-missing", {}, receipt_key="p2")
    assert st == 599 and body.get("error") == "PROVIDER_CAP_REACHED"
