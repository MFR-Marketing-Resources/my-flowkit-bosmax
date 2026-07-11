"""Extension relay contract: the native-Extend request + its ~33.5KB synchronous
response ride the EXISTING authenticated api_request relay with ZERO extension
changes. This is a source-invariant regression guard — if a future edit adds a
field allow-list, a response size cap, a path-specific host guard, or drops the
recaptcha injection, the extend lane silently breaks; these assertions fail first.

Proven by reading the relay (background.js handleApiRequest, rules.json, manifest.json)
against the agent-side builder — see also test_flow_client_extend_builder.py for the
envelope the agent emits.
"""
import os
import re

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_api_request_host_guard_is_path_agnostic():
    bg = _read("extension", "background.js")
    # host-only guard -> the batchAsyncGenerateVideoExtendVideo PATH is covered exactly
    # like batchAsyncGenerateVideoStartImage; it is NOT path-specific.
    assert 'startsWith("https://aisandbox-pa.googleapis.com/")' in bg
    assert "batchAsyncGenerateVideoExtendVideo" not in bg  # no per-endpoint special-casing


def test_request_body_forwarded_whole_no_field_allowlist():
    bg = _read("extension", "background.js")
    # the entire body is serialized — no field filtering that could drop videoInput etc.
    assert "JSON.stringify(finalBody)" in bg
    # recaptcha token is injected into the top-level clientContext the Extend body carries
    assert "finalBody.clientContext.recaptchaContext.token = captchaToken" in bg


def test_response_read_in_full_and_not_truncated():
    bg = _read("extension", "background.js")
    assert "await response.text()" in bg          # full body, no size cap
    assert "JSON.parse(responseText)" in bg        # parsed whole
    # the ONLY truncation is the human log summary, never the data returned to the agent
    assert re.search(r"responseSummary\s*=\s*responseText\s*\?\s*responseText\.slice\(0,\s*300\)", bg)
    assert re.search(r"data:\s*responseData", bg)   # agent receives the full parsed response


def test_dnr_and_host_permissions_cover_the_extend_path():
    rules = _read("extension", "rules.json")
    manifest = _read("extension", "manifest.json")
    # DNR Origin/Referer rewrite matches on the HOST (substring) -> covers /v1/video:* incl. Extend
    assert '"urlFilter": "aisandbox-pa.googleapis.com"' in rules
    assert '"https://aisandbox-pa.googleapis.com/*"' in manifest


def test_extend_endpoint_is_on_the_covered_host():
    cfg = _read("agent", "config.py")
    # the Extend RPC path resolves under GOOGLE_FLOW_API (aisandbox host) like every /v1/video:* RPC
    assert '"generate_video_extend": "/v1/video:batchAsyncGenerateVideoExtendVideo"' in cfg
