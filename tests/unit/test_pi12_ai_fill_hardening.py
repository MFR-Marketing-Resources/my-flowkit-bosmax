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
