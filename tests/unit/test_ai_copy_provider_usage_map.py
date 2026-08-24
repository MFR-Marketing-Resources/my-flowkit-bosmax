"""COPY-CORRECTIVE-B3: the provider usage map is drained on every terminal path
and bounded, so a long-running process cannot leak it.
"""
import pytest

from agent.services import ai_copy_provider_adapter as p


def _begin():
    return p._begin_provider_call(
        provider_id="deepseek", model="m", transport="openai_compatible",
        structured_output_requested=False, json_output_mode=None)


def test_normalize_usage_maps_provider_dimensions_without_using_total_as_output():
    usage = p.normalize_usage({
        "prompt_tokens": 10_189,
        "completion_tokens": 3_000,
        "total_tokens": 13_189,
    })
    assert usage["input_tokens"] == 10_189
    assert usage["output_tokens"] == 3_000
    assert usage["total_tokens"] == 13_189
    assert usage["prompt_tokens"] == 10_189
    assert usage["completion_tokens"] == 3_000


def test_normalize_usage_total_only_has_no_output_dimension():
    usage = p.normalize_usage({"total_tokens": 999_999})
    assert usage == {"total_tokens": 999_999}


def test_pop_usage_drains():
    p._usage_by_call_id[999999] = {"prompt_tokens": 5}
    assert p._pop_usage(999999) == {"prompt_tokens": 5}
    assert 999999 not in p._usage_by_call_id


def test_finish_provider_call_bounds_the_map():
    p._usage_by_call_id.clear()
    for _ in range(600):
        cid = _begin()
        p._finish_provider_call(cid, response_status="SUCCEEDED", http_status=200, usage={"prompt_tokens": 1})
    assert len(p._usage_by_call_id) <= 512


def test_generate_candidate_drains_on_parse_failure(monkeypatch):
    def fake_complete(messages, **kw):
        cid = _begin()
        p._finish_provider_call(cid, response_status="SUCCEEDED", http_status=200, usage={"prompt_tokens": 7})
        return "not json", None, cid

    def boom(*a, **k):
        raise p.AICopyProviderError(p.ERR_RESPONSE_INVALID, detail="bad")

    monkeypatch.setattr(p, "is_configured", lambda: True)
    monkeypatch.setattr(p, "_complete", fake_complete)
    monkeypatch.setattr(p, "_extract_json_object", boom)
    p._usage_by_call_id.clear()
    with pytest.raises(p.AICopyProviderError):
        p.generate_candidate("brief")
    assert p._usage_by_call_id == {}  # the failed call's usage was drained


def test_generate_candidate_drains_and_attaches_on_success(monkeypatch):
    def fake_complete(messages, **kw):
        cid = _begin()
        p._finish_provider_call(cid, response_status="SUCCEEDED", http_status=200, usage={"prompt_tokens": 11})
        return '{"hook": "x"}', None, cid

    monkeypatch.setattr(p, "is_configured", lambda: True)
    monkeypatch.setattr(p, "_complete", fake_complete)
    monkeypatch.setattr(p, "_extract_json_object", lambda t, **k: {"hook": "x"})
    p._usage_by_call_id.clear()
    obj = p.generate_candidate("brief")
    assert obj["__usage__"] == {"prompt_tokens": 11, "input_tokens": 11}
    assert p._usage_by_call_id == {}


def test_complete_json_drains(monkeypatch):
    def fake_complete(messages, **kw):
        cid = _begin()
        p._finish_provider_call(cid, response_status="SUCCEEDED", http_status=200, usage={"prompt_tokens": 3})
        return '{"ok": 1}', None, cid

    monkeypatch.setattr(p, "is_configured", lambda: True)
    monkeypatch.setattr(p, "_complete", fake_complete)
    monkeypatch.setattr(p, "_extract_json_object", lambda t, **k: {"ok": 1})
    p._usage_by_call_id.clear()
    p.complete_json("sys", "user")
    assert p._usage_by_call_id == {}  # complete_json does not surface usage; it drains


def test_complete_json_receipt_is_bound_to_exact_call_under_interleaving(monkeypatch):
    def fake_complete(messages, **kw):
        exact_call = p._begin_provider_call(
            provider_id="deepseek",
            model="exact-model",
            transport="openai_compatible",
            structured_output_requested=True,
            json_output_mode="json_object",
        )
        later_call = p._begin_provider_call(
            provider_id="openai",
            model="later-model",
            transport="openai_compatible",
            structured_output_requested=True,
            json_output_mode="json_object",
        )
        p._finish_provider_call(
            exact_call,
            response_status="SUCCEEDED",
            http_status=200,
            usage={"prompt_tokens": 3},
            finish_reason="stop",
        )
        p._finish_provider_call(
            later_call,
            response_status="SUCCEEDED",
            http_status=201,
            usage={"prompt_tokens": 9},
            finish_reason="stop",
        )
        return '{"ok": 1}', "stop", exact_call

    monkeypatch.setattr(p, "is_configured", lambda: True)
    monkeypatch.setattr(p, "_complete", fake_complete)
    parsed, receipt = p.complete_json_with_receipt("sys", "user")

    assert parsed == {"ok": 1}
    assert receipt["provider_id"] == "deepseek"
    assert receipt["model_id"] == "exact-model"
    assert receipt["http_status"] == 200
    assert receipt["json_parse_status"] == "VALID"
    assert receipt["usage"] == {"prompt_tokens": 3, "input_tokens": 3}
    assert p.provider_call_receipt()["last_call"]["model_id"] == "later-model"
    p._pop_usage(receipt["call_id"] + 1)
    p._pop_provider_call_receipt(receipt["call_id"] + 1)
