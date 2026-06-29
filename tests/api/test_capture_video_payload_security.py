"""Patch E: the /capture-video-payload debug surface must be gated AND redacted.

The endpoint stores/returns raw Google Flow request bodies (bearer tokens, reCAPTCHA tokens,
cookies, API keys in URLs). It must be OFF by default and never echo secrets even when on.
"""
import asyncio

import pytest
from fastapi import HTTPException

from agent.api import local_agent


def _run(coro):
    return asyncio.run(coro)


def test_redact_scrubs_secrets():
    payload = {
        "url": "https://aisandbox-pa.googleapis.com/v1/video:generate?key=AIzaSyTOPSECRETKEY",
        "Authorization": "Bearer ya29.A0AReallyLongBearerTokenValueThatMustBeRedacted1234567890",
        "body": "grecaptcha=03AGdBq25xVeryLongRecaptchaTokenValue1234567890abcdefGHIJKLMNOP",
        "token": "ya29.AnotherSecretBearerToken",
        "nested": {"cookie": "SID=secretcookievalue", "ok": "short"},
    }
    red = local_agent._redact(payload)
    flat = str(red)
    assert "AIzaSyTOPSECRETKEY" not in flat              # key= URL param scrubbed
    assert "ya29.A0A" not in flat                        # bearer scrubbed
    assert "03AGdBq25xVeryLongRecaptchaTokenValue" not in flat  # long reCAPTCHA token scrubbed
    assert red["Authorization"] == "<redacted>"          # secret-named key fully masked
    assert red["token"] == "<redacted>"
    assert red["nested"]["cookie"] == "<redacted>"
    assert red["nested"]["ok"] == "short"                # short legit values untouched
    assert "key=<redacted>" in red["url"]


def test_capture_gate_blocks_both_handlers_when_disabled(monkeypatch):
    monkeypatch.setattr(local_agent, "DEBUG_ENDPOINTS_ENABLED", False)
    with pytest.raises(HTTPException) as ei:
        _run(local_agent.get_capture_video_payload())
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException) as ei2:
        _run(local_agent.post_capture_video_payload({"body": "x"}))
    assert ei2.value.status_code == 403


def test_capture_when_enabled_stores_and_returns_redacted(monkeypatch):
    monkeypatch.setattr(local_agent, "DEBUG_ENDPOINTS_ENABLED", True)
    local_agent._CAPTURED_VIDEO_PAYLOAD["list"].clear()
    local_agent._CAPTURED_VIDEO_PAYLOAD["marker"] = None
    _run(local_agent.post_capture_video_payload(
        {"url": "x?key=AIzaSyMUSTNOTLEAK",
         "token": "ya29.LongSecretBearerTokenValueHere1234567890abcd"}))
    # stored copy is already redacted (no raw secret ever held)
    stored = str(local_agent._CAPTURED_VIDEO_PAYLOAD["list"])
    assert "AIzaSyMUSTNOTLEAK" not in stored and "ya29.LongSecret" not in stored
    got = _run(local_agent.get_capture_video_payload())
    flat = str(got)
    assert "AIzaSyMUSTNOTLEAK" not in flat and "ya29.LongSecret" not in flat
    assert len(got["captures"]) == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    import inspect
    for fn in fns:
        if "monkeypatch" in inspect.signature(fn).parameters:
            continue  # needs pytest fixture
        fn()
        print("PASS", fn.__name__)
