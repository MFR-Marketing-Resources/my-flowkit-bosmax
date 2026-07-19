"""Native Extend instrumentation + credit-honesty classification.

Two zero-credit fixes born from the live runtime attempt vj_bb28f65c189e, whose
native Extend failed with EXTEND_CHILD_MEDIA_ID_MISSING and whose raw response
was captured nowhere:

1. `_sanitize_extend_response` — whitelists ONLY structural forensic fields from
   a generate_video_extend response (never the raw body), so the NEXT authorized
   attempt has evidence to diagnose an empty/no-child response. No secrets leak.
2. The orchestrator must NOT classify a POST-RPC extend failure
   (EXTEND_CHILD_MEDIA_ID_MISSING et al.) as NOT_ATTEMPTED / NOT_SPENT / SAFE —
   the RPC was called, so a credit-bearing child MAY have started.
"""
import json

from agent.services import google_flow_native_extend_runtime as nx
from agent.services import video_production_orchestrator as orch


# ── _sanitize_extend_response ────────────────────────────────────────────────
def test_sanitizer_captures_child_from_successful_shape():
    # the real 07-11 successful response delivers the child via
    # workflows[0].metadata.primaryMediaId
    resp = {"remainingCredits": 1610,
            "workflows": [{"name": "737b10c8", "metadata": {"primaryMediaId": "164c65b0"}}]}
    out = nx._sanitize_extend_response(resp)
    assert out["workflow_primary_media_ids"] == ["164c65b0"]
    assert out["workflow_count"] == 1
    assert out["has_error"] is False
    assert out["remaining_credits"] == 1610


def test_sanitizer_captures_empty_no_child_shape():
    # the failing shape: no media, no workflows -> the exact forensic evidence
    # that was missing for vj_bb28f65c189e
    out = nx._sanitize_extend_response({"media": [], "workflows": []})
    assert out["media_count"] == 0
    assert out["workflow_count"] == 0
    assert out["workflow_primary_media_ids"] == []
    assert "media" in out["top_level_keys"] and "workflows" in out["top_level_keys"]


def test_sanitizer_never_leaks_secret_values():
    # a response carrying token-like fields: the sanitizer must not persist the
    # VALUES (only whitelisted structural fields + key names).
    resp = {
        "recaptchaContext": "SECRET_RECAPTCHA_TOKEN_ZZZ",
        "authToken": "Bearer_LEAKED_XYZ",
        "sessionId": "PRIVATE_SESSION_123",
        "workflows": [{"name": "wf", "metadata": {"primaryMediaId": "child"}}],
        "remainingCredits": 5,
    }
    blob = json.dumps(nx._sanitize_extend_response(resp))
    assert "SECRET_RECAPTCHA_TOKEN_ZZZ" not in blob
    assert "Bearer_LEAKED_XYZ" not in blob
    assert "PRIVATE_SESSION_123" not in blob
    # but the useful structural evidence is preserved
    assert "child" in blob and "5" in blob


def test_sanitizer_never_leaks_secrets_nested_inside_error():
    # the real leak site: tokens nested INSIDE the error body (message/details),
    # which the removed `error_repr` used to stringify wholesale.
    resp = {
        "error": {
            "code": 403,
            "status": "PERMISSION_DENIED",
            "message": "token=SECRET_TOKEN recaptcha=SECRET_CAPTCHA",
            "details": {"sessionId": "SECRET_SESSION"},
        }
    }
    out = nx._sanitize_extend_response(resp)
    blob = json.dumps(out)
    assert "SECRET_TOKEN" not in blob
    assert "SECRET_CAPTCHA" not in blob
    assert "SECRET_SESSION" not in blob
    # safe structural metadata IS kept
    assert out["has_error"] is True
    assert out["error_type"] == "dict"
    assert out["error_code"] == 403
    assert out["error_status"] == "PERMISSION_DENIED"
    assert out["error_keys"] == ["code", "details", "message", "status"]
    # the raw message/details are never surfaced as their own fields
    assert "error_repr" not in out
    assert "message" not in blob or "token=" not in blob


def test_sanitizer_never_leaks_secret_when_error_is_a_string():
    out = nx._sanitize_extend_response({"error": "request rejected; sessionToken=SECRET_ABC123"})
    blob = json.dumps(out)
    assert "SECRET_ABC123" not in blob
    assert out["has_error"] is True
    assert out["error_type"] == "str"
    assert out["error_code"] is None and out["error_status"] is None


def test_sanitizer_handles_unusable_response():
    assert nx._sanitize_extend_response(None)["unusable_response_type"] == "NoneType"
    assert nx._sanitize_extend_response("garbage")["unusable_response_type"] == "str"
    # data-envelope form is unwrapped
    out = nx._sanitize_extend_response({"data": {"workflows": [{"name": "w"}]}})
    assert out["workflow_count"] == 1


# ── POST-RPC credit-honesty classification set ───────────────────────────────
def test_post_rpc_code_set_is_correct():
    # every code raised AFTER generate_video_extend must be in the set
    assert nx.EXTEND_CHILD_MEDIA_ID_MISSING in orch._EXTEND_POST_RPC_CODES
    assert nx.EXTEND_REQUEST_REJECTED in orch._EXTEND_POST_RPC_CODES
    assert nx.EXTEND_LINEAGE_MISMATCH in orch._EXTEND_POST_RPC_CODES
    assert nx.EXTEND_OPERATION_TIMEOUT in orch._EXTEND_POST_RPC_CODES
    assert nx.EXTEND_OPERATION_FAILED in orch._EXTEND_POST_RPC_CODES
    # PRE-RPC contract/validation codes must NOT be in it (they stay SAFE, the
    # #423 UNSUPPORTED_MODEL retryable contract)
    assert nx.EXTEND_UNSUPPORTED_MODEL not in orch._EXTEND_POST_RPC_CODES
    assert nx.EXTEND_CAPTURE_CONTRACT_DRIFT not in orch._EXTEND_POST_RPC_CODES
    assert nx.EXTEND_PARENT_MEDIA_ID_MISSING not in orch._EXTEND_POST_RPC_CODES
