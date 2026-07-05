from pathlib import Path
from unittest.mock import patch

import pytest

from agent.models.product_intelligence import ProductIntelligenceImageAnalysis
from agent.services.product_image_analysis_service import (
    PROVIDER_EXECUTION_DISABLED_WARNING,
    SEMANTIC_IMAGE_WARNING,
    analyze_product_image_payload,
)

_no_vision_key = patch(
    "agent.services.product_image_analysis_service.get_lane_api_key",
    return_value=None,
)


@_no_vision_key
def test_image_url_without_provider_returns_provider_not_configured_and_no_fake_detections(_mock):
    result = analyze_product_image_payload(
        {
            "id": "prod-001",
            "raw_product_title": "Sabun Dobi Liquid",
            "image_url": "https://example.com/detergent.jpg",
        }
    )

    assert result["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert result["provider"] == "not_configured"
    assert result["detected_package"] is None
    assert result["detected_text"] == []
    assert result["visual_confidence"] == "NOT_VERIFIED"
    assert SEMANTIC_IMAGE_WARNING in result["warnings"]


def test_product_with_no_image_returns_image_missing():
    result = analyze_product_image_payload(
        {
            "id": "prod-002",
            "raw_product_title": "Mystery Product",
        }
    )

    assert result["status"] == "IMAGE_MISSING"
    assert result["provider"] == "metadata_only"
    assert result["detected_package"] is None
    assert result["detected_text"] == []


@_no_vision_key
def test_metadata_only_mode_does_not_invent_package_or_text(_mock, tmp_path: Path):
    image_path = tmp_path / "product.jpg"
    image_path.write_bytes(b"fake-binary-jpg")

    result = analyze_product_image_payload(
        {
            "id": "prod-003",
            "image_url": "https://example.com/product.jpg",
            "local_image_path": str(image_path),
        }
    )

    assert result["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert result["detected_package"] is None
    assert result["detected_text"] == []
    assert result["metadata"]["local_file_exists"] is True
    assert result["metadata"]["local_file_size_bytes"] > 0


def test_configured_provider_returns_analyzed_payload_and_merges_metadata(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "product.jpg"
    image_path.write_bytes(b"fake-binary-jpg")

    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda provider, payload, metadata: ProductIntelligenceImageAnalysis(
            status="ANALYZED",
            image_url=None,
            local_image_path=None,
            detected_package="bottle",
            detected_text=["Hydrating Face Mist", "100ml"],
            detected_brand="Bosmax",
            detected_size_text="100ml",
            detected_form_factor="bottle",
            visual_confidence="HIGH",
            evidence=["provider:anthropic"],
            warnings=[],
            provider=provider,
            metadata={"provider_roundtrip": True},
        ),
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.is_lane_execution_enabled",
        lambda lane: True,
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-004",
            "raw_product_title": "Hydrating Face Mist",
            "image_url": "https://example.com/product.jpg",
            "local_image_path": str(image_path),
        }
    )

    assert result["status"] == "ANALYZED"
    assert result["provider"] == "anthropic"
    assert result["detected_package"] == "bottle"
    assert result["detected_text"] == ["Hydrating Face Mist", "100ml"]
    assert result["visual_confidence"] == "HIGH"
    assert result["metadata"]["local_file_exists"] is True
    assert result["metadata"]["provider_roundtrip"] is True
    assert "provider:anthropic" in result["evidence"]


def test_configured_provider_failure_falls_closed_to_analysis_failed(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda provider, payload, metadata: None,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.is_lane_execution_enabled",
        lambda lane: True,
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-005",
            "raw_product_title": "Sabun Dobi Liquid",
            "image_url": "https://example.com/detergent.jpg",
        }
    )

    assert result["status"] == "ANALYSIS_FAILED"
    assert result["provider"] == "anthropic"
    assert result["detected_package"] is None
    assert result["detected_text"] == []
    assert result["warnings"] == ["SEMANTIC_IMAGE_ANALYSIS_FAILED"]


def test_provider_execution_can_be_disabled_for_non_explicit_read_paths(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda provider, payload, metadata: (_ for _ in ()).throw(
            AssertionError("provider should not execute when disabled")
        ),
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-006",
            "raw_product_title": "Sabun Dobi Liquid",
            "image_url": "https://example.com/detergent.jpg",
        },
        allow_provider_execution=False,
    )

    assert result["status"] == "ANALYSIS_SKIPPED"
    assert result["provider"] == "execution_disabled"
    assert result["detected_package"] is None
    assert PROVIDER_EXECUTION_DISABLED_WARNING in result["warnings"]
    assert "provider_execution:disabled" in result["evidence"]
    assert result["metadata"]["configured_provider"] == "anthropic"


def _set_vision_lane_state(
    monkeypatch,
    *,
    provider,
    model,
    key="sk-vision-live-key",
    execution=True,
):
    """Drive the REAL _configured_vision_runtime resolver by patching the underlying
    lane resolvers (NOT _configured_provider_name), so tests exercise the actual
    provider+model+key completeness gate."""
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_provider",
        lambda lane: provider,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_model",
        lambda lane: model,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_api_key",
        lambda lane: key,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.is_lane_execution_enabled",
        lambda lane: execution,
    )


def _forbid_provider_calls(monkeypatch):
    """Fail loudly if ANY provider path is reached (dispatch, adapter, or SDK)."""
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("no provider dispatch may occur when model is missing")
        ),
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.vision_provider_adapter.run_vision_completion",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("vision_provider_adapter.run_vision_completion must not be called")
        ),
    )


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "qwen"])
def test_missing_model_fails_closed_before_any_provider_call(monkeypatch, provider):
    # Provider + key + execution present, but NO selected model. The audit blocker:
    # this must NOT fall back to any env model and must NOT reach a provider.
    _set_vision_lane_state(monkeypatch, provider=provider, model=None)
    _forbid_provider_calls(monkeypatch)

    result = analyze_product_image_payload(
        {
            "id": f"prod-nomodel-{provider}",
            "raw_product_title": "Stale Lane Product",
            "image_url": "https://example.com/product.jpg",
        }
    )

    assert result["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert result["provider"] == "not_configured"
    assert result["detected_package"] is None
    # No fallback model leaked into evidence.
    assert all("provider:model:" not in item for item in result["evidence"])
    assert SEMANTIC_IMAGE_WARNING in result["warnings"]


def _enable_vision(monkeypatch, provider: str, model: str = "some-vision-model"):
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: provider,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.is_lane_execution_enabled",
        lambda lane: True,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_api_key",
        lambda lane: "sk-vision-live-key",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.get_lane_model",
        lambda lane: model,
    )


def test_anthropic_real_path_uses_selected_model_no_fallback(monkeypatch):
    # Exercises the REAL _analyze_with_anthropic (SDK faked) to prove the selected
    # Claude model is used and no env fallback is substituted.
    import sys
    import types

    _set_vision_lane_state(monkeypatch, provider="anthropic", model="claude-sonnet-5")
    captured: dict = {}

    class _Msg:
        content = [types.SimpleNamespace(text='{"detected_package": "jar", "visual_confidence": "HIGH"}')]

    class _Messages:
        def create(self, *, model, max_tokens, messages):
            captured["model"] = model
            return _Msg()

    class _FakeAnthropic:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _Messages()

    fake_module = types.ModuleType("anthropic")
    fake_module.Anthropic = _FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    result = analyze_product_image_payload(
        {
            "id": "prod-anthropic-real",
            "raw_product_title": "Night Cream",
            "image_url": "https://example.com/jar.jpg",
        }
    )

    assert result["status"] == "ANALYZED"
    assert result["provider"] == "anthropic"
    assert captured["model"] == "claude-sonnet-5"
    assert "provider:model:claude-sonnet-5" in result["evidence"]


def test_openai_vision_provider_routes_through_adapter_and_uses_selected_model(monkeypatch):
    _enable_vision(monkeypatch, "openai", model="gpt-4o")
    seen: dict = {}

    def fake_run(provider, model, api_key, **kwargs):
        seen["provider"] = provider
        seen["model"] = model
        seen["api_key"] = api_key
        seen["kwargs"] = kwargs
        return '{"detected_package": "bottle", "detected_text": ["Face Mist"], "visual_confidence": "HIGH"}'

    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.vision_provider_adapter.run_vision_completion",
        fake_run,
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-openai",
            "raw_product_title": "Hydrating Face Mist",
            "image_url": "https://example.com/product.jpg",
        }
    )

    assert result["status"] == "ANALYZED"
    assert result["provider"] == "openai"
    assert result["detected_package"] == "bottle"
    # Product image analysis used the operator-selected vision lane model.
    assert seen["provider"] == "openai"
    assert seen["model"] == "gpt-4o"
    assert "provider:model:gpt-4o" in result["evidence"]
    # An image source was prepared for the multimodal request.
    assert seen["kwargs"].get("image_remote_url") == "https://example.com/product.jpg"


def test_qwen_vision_provider_failure_falls_closed(monkeypatch):
    _enable_vision(monkeypatch, "qwen", model="qwen-vl-max")

    def boom(*args, **kwargs):
        raise RuntimeError("qwen transport error")

    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.vision_provider_adapter.run_vision_completion",
        boom,
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-qwen",
            "raw_product_title": "Sabun Dobi",
            "image_url": "https://example.com/detergent.jpg",
        }
    )

    assert result["status"] == "ANALYSIS_FAILED"
    assert result["provider"] == "qwen"
    assert result["warnings"] == ["SEMANTIC_IMAGE_ANALYSIS_FAILED"]


def test_gemini_vision_provider_analyzes_via_openai_compatible_path(monkeypatch):
    _enable_vision(monkeypatch, "gemini", model="gemini-2.0-flash")
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.vision_provider_adapter.run_vision_completion",
        lambda *a, **k: '{"detected_package": "box", "visual_confidence": "MEDIUM"}',
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-gemini",
            "image_url": "https://example.com/box.jpg",
        }
    )

    assert result["status"] == "ANALYZED"
    assert result["provider"] == "gemini"
    assert result["detected_package"] == "box"
    assert "provider:model:gemini-2.0-flash" in result["evidence"]


def test_vision_lane_toggle_can_disable_provider_execution_even_for_explicit_analysis(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._configured_provider_name",
        lambda: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service.is_lane_execution_enabled",
        lambda lane: False,
    )
    monkeypatch.setattr(
        "agent.services.product_image_analysis_service._analyze_with_provider",
        lambda provider, payload, metadata: (_ for _ in ()).throw(
            AssertionError("provider should not execute when vision lane is disabled")
        ),
    )

    result = analyze_product_image_payload(
        {
            "id": "prod-007",
            "raw_product_title": "Hydrating Face Mist",
            "image_url": "https://example.com/product.jpg",
        }
    )

    assert result["status"] == "ANALYSIS_SKIPPED"
    assert result["provider"] == "execution_disabled"
    assert "VISION_PROVIDER_EXECUTION_DISABLED" in result["warnings"]
    assert "provider_execution:vision_lane_disabled" in result["evidence"]
