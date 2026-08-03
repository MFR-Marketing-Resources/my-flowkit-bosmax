"""COPY-CORRECTIVE-B3: the provider usage map is drained on every terminal path
and bounded, so a long-running process cannot leak it.
"""
import pytest

from agent.services import ai_copy_provider_adapter as p


def _begin():
    return p._begin_provider_call(
        provider_id="deepseek", model="m", transport="openai_compatible",
        structured_output_requested=False, json_output_mode=None)


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
    assert obj["__usage__"] == {"prompt_tokens": 11}
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
