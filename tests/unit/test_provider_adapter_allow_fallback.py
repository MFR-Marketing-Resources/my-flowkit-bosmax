"""Amendment 3: the additive ``allow_fallback`` capability on the shared provider
adapter.

``allow_fallback`` defaults to ``True`` so every existing caller keeps the
structure-lane fallback behaviour unchanged. A caller that must guarantee at most
ONE provider call (the Creative Atom Factory) passes ``allow_fallback=False`` to
suppress the fallback for that call — WITHOUT disabling or mutating the global
structure-fallback setting.
"""

import inspect

import pytest

from agent.services import ai_copy_provider_adapter as adapter
from agent.services.ai_copy_provider_adapter import AICopyProviderError


def _install(monkeypatch, counter):
    # Isolate the test to the fallback-branch gating: a configured structure lane
    # with an eligible fallback target, where the low-level call always fails
    # eligibly so we can count how many times it is invoked.
    monkeypatch.setattr(adapter, "is_configured", lambda lane: True)
    monkeypatch.setattr(adapter, "_canonical_text_structure_lane", lambda lane: "structure")
    monkeypatch.setattr(adapter, "_structure_fallback_target", lambda: ("deepseek", "deepseek-v4-pro", "k"))
    monkeypatch.setattr(adapter, "_fallback_is_eligible", lambda err: True)

    def _stub_complete(*args, **kwargs):
        counter["n"] += 1
        raise AICopyProviderError("ERR_CALL_FAILED", "boom", http_status=400)

    monkeypatch.setattr(adapter, "_complete", _stub_complete)


def test_default_is_true():
    sig = inspect.signature(adapter.complete_json_with_receipt)
    assert sig.parameters["allow_fallback"].default is True


def test_structure_fallback_runs_by_default(monkeypatch):
    counter = {"n": 0}
    _install(monkeypatch, counter)
    with pytest.raises(AICopyProviderError):
        adapter.complete_json_with_receipt("sys", "usr", lane="structure")
    # primary failed eligibly -> fallback attempted -> two low-level calls
    assert counter["n"] == 2


def test_allow_fallback_false_suppresses_fallback(monkeypatch):
    counter = {"n": 0}
    _install(monkeypatch, counter)
    with pytest.raises(AICopyProviderError):
        adapter.complete_json_with_receipt("sys", "usr", lane="structure", allow_fallback=False)
    # exactly one provider call; the fallback branch is not entered
    assert counter["n"] == 1
