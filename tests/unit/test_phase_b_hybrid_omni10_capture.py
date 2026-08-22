"""Provider-free contract tests for the owner-authorized Phase B capture gate."""

from __future__ import annotations

import json

import pytest

from agent.services import agent_video, make_video


def test_capture_boundary_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HYBRID_REFERENCE_OMNI_10S_CAPTURE_ENABLED", raising=False)
    result = __import__("asyncio").run(
        make_video.start_generate(
            "F2V",
            "capture probe",
            project_id="project",
            image_media_ids=["fresh-ref"],
            aspect="9:16",
            model="omni_flash",
            duration_s=10,
            num_videos=1,
            product_id=make_video.HYBRID_REFERENCE_OMNI_10S_CAPTURE_PRODUCT_ID,
            source_mode="HYBRID",
            surface_lane="HYBRID",
            request_id="phase-b-disabled",
            idempotency_key="phase-b-disabled",
            capture_class=make_video.HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS,
            capture_confirmed=True,
        )
    )
    assert result["status"] == "REJECTED"
    assert result["error"] == "CAPTURE_FEATURE_DISABLED"
    assert result["pre_provider"]["provider_calls"] == 0


def test_capture_gate_requires_exact_contract(monkeypatch):
    monkeypatch.setenv("HYBRID_REFERENCE_OMNI_10S_CAPTURE_ENABLED", "1")
    result = __import__("asyncio").run(
        make_video.start_generate(
            "F2V",
            "capture probe",
            project_id="project",
            image_media_ids=["ref-a", "ref-b"],
            aspect="9:16",
            model="omni_flash",
            duration_s=10,
            num_videos=1,
            product_id=make_video.HYBRID_REFERENCE_OMNI_10S_CAPTURE_PRODUCT_ID,
            source_mode="HYBRID",
            surface_lane="HYBRID",
            request_id="phase-b-two-refs",
            idempotency_key="phase-b-two-refs",
            capture_class=make_video.HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS,
            capture_confirmed=True,
        )
    )
    assert result["status"] == "REJECTED"
    assert result["error"] == "CAPTURE_REFERENCE_COUNT_MUST_BE_1"
    assert result["pre_provider"]["provider_calls"] == 0


def test_capture_evidence_proves_reference_order_and_redacts_secrets():
    ref = "fresh-flow-media-1"
    raw = "data: " + json.dumps(
        {
            "agentMessage": {
                "responseId": "response-1",
                "agentEvents": [
                    {
                        "toolInvocation": {
                            "toolName": "generate_video_from_references",
                            "toolCallId": "tool-1",
                            "toolArguments": {
                                "model_usage_key": "omni_flash",
                                "duration": 10,
                                "generation_type": "reference_frame_2_video",
                                "referenceImages": [{"mediaId": ref}],
                                "prompt": "do not persist this prompt",
                                "recaptchaToken": "do-not-persist-token",
                            },
                        }
                    }
                ],
            }
        }
    )
    evidence = agent_video.build_reference_contract_capture_evidence(
        {
            "model_used": "omni_flash",
            "duration_used": 10,
            "model_ok": True,
            "duration_ok": True,
            "gen_seed": 42,
            "tool_call_id": "tool-1",
            "response_id": "response-1",
            "transcript": [{"raw_sse": raw}],
        },
        [ref],
        project_id="project-1",
    )
    encoded = json.dumps(evidence, ensure_ascii=False)
    assert evidence["provider_generation_tools"] == ["generate_video_from_references"]
    assert evidence["reference_media_ids_seen_in_generation_tool"] == [ref]
    assert evidence["reference_forwarded_to_generation"] is True
    assert evidence["reference_aware_tool_observed"] is True
    assert evidence["model_selector_fields"] == [
        {"field": "model_usage_key", "value": "omni_flash"}
    ]
    assert evidence["duration_fields"] == [{"field": "duration", "value": 10}]
    assert "do-not-persist-token" not in encoded
    assert "do not persist this prompt" not in encoded


def test_capture_evidence_records_sanitized_outbound_settings_turns():
    evidence = agent_video.build_reference_contract_capture_evidence(
        {
            "negotiation_state": {
                "target_settings_communicated": True,
                "target_settings_resteered": True,
                "permission_after_target_steer": True,
                "target_settings_acknowledged": True,
                "target_model_key": "omni_flash",
                "target_model_label": "Omni Flash",
                "target_duration_s": 10,
                "desired_num": 1,
            },
            "transcript": [
                {
                    "turn": 1,
                    "sent": "Use exactly Gemini Omni Flash at 10 seconds. prompt secret",
                    "sent_text_sha256": "hash-1",
                    "sent_text_length": 88,
                    "sent_media_ids": ["ref-1"],
                    "perm_sent": None,
                    "target_settings_steer": False,
                    "raw_sse": "",
                },
                {
                    "turn": 2,
                    "sent": "Reject",
                    "sent_text_sha256": "hash-2",
                    "sent_text_length": 6,
                    "sent_media_ids": ["ref-1"],
                    "perm_sent": agent_video.DENIED,
                    "target_settings_steer": False,
                    "raw_sse": "",
                },
            ],
        },
        ["ref-1"],
        project_id="project-1",
    )
    assert evidence["negotiation_state"]["target_settings_acknowledged"] is True
    assert evidence["target_settings_directive"].startswith(
        "Use exactly Gemini Omni Flash at 10 seconds."
    )
    assert evidence["outbound_turns"][0]["sent_media_ids"] == ["ref-1"]
    assert evidence["outbound_turns"][1]["permission_action"] == agent_video.DENIED
    assert evidence["outbound_turns"][0]["sent_contract"] == (
        "TARGET_SETTINGS_AND_CREATIVE_PROMPT"
    )
    assert "prompt secret" not in json.dumps(evidence)


def test_capture_classification_does_not_promote_wrong_transport():
    job = {
        "approved": True,
        "status": "DONE",
        "model_ok": True,
        "duration_ok": True,
        "capture_contract_evidence": {
            "text_only_tool_observed": True,
            "reference_aware_tool_observed": False,
            "reference_forwarded_to_generation": False,
        },
    }
    assert make_video._classify_reference_contract_capture(job) == "WRONG_TRANSPORT"


def test_capture_classification_relabels_approved_wrong_model():
    job = {
        "approved": True,
        "status": "FAILED",
        "model_ok": False,
        "duration_ok": False,
        "error": "FAILED_WRONG_MODEL: expected omni_flash, got veo_3_1_r2v_lite",
        "capture_contract_evidence": {
            "text_only_tool_observed": False,
            "reference_aware_tool_observed": True,
            "reference_forwarded_to_generation": True,
        },
    }
    assert (
        make_video._classify_reference_contract_capture(job)
        == "CAPTURE_WRONG_MODEL_AFTER_APPROVAL"
    )
    job["capture_contract_verdict"] = "PROVIDER_REJECTED"
    public = make_video._durable_public_state(
        {"job_id": "g_historical", "status": "FAILED", "error_code": job["error"]},
        job,
    )
    assert public["capture_contract_verdict"] == "CAPTURE_WRONG_MODEL_AFTER_APPROVAL"
    assert public["capture_contract_verdict_legacy"] == "PROVIDER_REJECTED"
    assert public["capture_contract_verdict_provenance"]["kind"] == (
        "DERIVED_VIEW_NO_HISTORICAL_REWRITE"
    )


@pytest.mark.parametrize("model,duration", [("veo_3_1_lite", 10), ("omni_flash", 8)])
def test_production_readiness_remains_fail_closed_for_unproven_10s(model, duration):
    plan = make_video._direct_lane_plan(
        "F2V", "HYBRID", model, duration, "9:16",
        ref_count=1, num_videos=1, require_flag=False,
    )
    if duration == 10:
        assert plan["reason"] == make_video.DIRECT_10S_CONTRACT_NOT_CERTIFIED
    else:
        assert plan["reason"] != make_video.DIRECT_10S_CONTRACT_NOT_CERTIFIED
