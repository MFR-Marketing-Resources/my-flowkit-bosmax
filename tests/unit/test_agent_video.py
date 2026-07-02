"""Tests for the flowCreationAgent negotiation brain (patch B).

Authority fixture: tests/fixtures/agent_sse_proposal.txt — a REAL pre-approve SSE captured
0-credit. It proves the ask_for_permission proposal carries no model (model appears only
post-approve), so cost is the Lite proxy pre-approve and the model is verified post-approve.
"""
import asyncio
import os

from agent.services import agent_video as av


def _run(coro):
    return asyncio.run(coro)


class _FakeAgentClient:
    """Returns the same SSE for every turn — enough to drive one negotiate decision."""
    def __init__(self, sse):
        self._sse = sse

    async def agent_stream_chat(self, session_id, project_id, turn, text,
                                media_ids=None, permission_action=None):
        return {"data": self._sse}

_FIXT = os.path.join(os.path.dirname(__file__), "..", "fixtures", "agent_sse_proposal.txt")

# Synthetic POST-approve SSE built from the real observed generate_video tool shape.
_POST_APPROVE = (
    'data: {"agentMessage": {"agentEvents": [{"eventId": "x","toolInvocation": '
    '{"toolName": "generate_video_with_references","toolArguments": '
    '{"model_usage_key": "veo_3_1_r2v_lite","model_display_name": "Veo 3.1 - Lite",'
    '"duration": 8.0,"aspect_ratio": "9:16"}}}],"responseId": "x"}}\n'
    'data: {"text": "beginRendering"}\n'
)

# A genuine generation toolInvocation WITHOUT any "beginRendering" text — proves the HARD
# started signal is the fired tool, not the text.
_GEN_TOOL_NO_TEXT = (
    'data: {"agentMessage": {"agentEvents": [{"eventId": "x","toolInvocation": '
    '{"toolName": "generate_video_with_references","toolArguments": '
    '{"model_usage_key": "veo_3_1_r2v_lite","duration": 8.0}}}],"responseId": "x"}}\n'
)

# "beginRendering" appearing in a plain UI surface render with NO generation tool — must NOT
# mark started (the live false-positive that motivated removing it from _STARTED_PHRASES).
_BEGINRENDER_ONLY = (
    'data: {"text": "beginRendering"}\n'
    'data: {"text": "With your current plan you can keep generating."}\n'
)


def test_parse_real_proposal_fixture():
    with open(_FIXT, encoding="utf-8") as f:
        raw = f.read()
    st = av.parse_agent_sse(raw)
    assert st["permission"] == {"num_images": 0, "total_cost": 15,
                                "num_total": 1, "num_videos": 1}
    assert st["started"] is False
    assert st["model"] is None            # model is NOT in the proposal (pre-approve)
    assert "ask_for_permission" in st["tools"]


def test_parse_post_approve_extracts_model_and_started():
    st = av.parse_agent_sse(_POST_APPROVE)
    assert st["started"] is True          # a generate tool fired
    assert st["model"] == "veo_3_1_r2v_lite"
    assert st["duration_used"] == 8       # DUR-1: duration extracted from tool args (8.0 → 8)


def test_parse_beginrendering_text_only_not_started():
    # (A) beginRendering text alone — with NO generation toolInvocation — must NOT start.
    st = av.parse_agent_sse(_BEGINRENDER_ONLY)
    assert st["started"] is False
    assert st["model"] is None


def test_parse_gen_tool_without_beginrendering_started():
    # (B) a proven generation toolInvocation, no "beginRendering" text → still started.
    st = av.parse_agent_sse(_GEN_TOOL_NO_TEXT)
    assert st["started"] is True
    assert st["model"] == "veo_3_1_r2v_lite"
    assert st["duration_used"] == 8


def _perm(cost, nv=1, ni=0):
    return {"num_images": ni, "total_cost": cost, "num_total": nv, "num_videos": nv}


def test_decide_approve_lite_at_ceiling_10():
    k, _m, a = av.decide(_perm(10), "veo_3_1_lite", 8)
    assert k == "approve" and a == av.APPROVED


def test_decide_promo_below_ceiling_approves():
    # cap-gate: a promo price BELOW the ceiling for 1 video approves (was rejected by exact-cost)
    assert av.decide(_perm(8), "veo_3_1_lite", 8)[0] == "approve"


def test_decide_reject_cost_over_ceiling():
    # 15 > the Lite ceiling of 10 → too expensive for 1 video → reject
    assert av.decide(_perm(15), "veo_3_1_lite", 8)[0] == "reject"


def test_decide_omni_10s_promo_15_approves_I6_inverted():
    # I6 INVERTED under cap-gate: Omni credits are promo-variable. A 1-video / 15-credit promo
    # proposal now APPROVES (15 <= 30 ceiling); the duration is verified POST-approve, not by cost.
    assert av.decide(_perm(15), "omni_flash", 10)[0] == "approve"
    assert av.decide(_perm(30), "omni_flash", 10)[0] == "approve"   # at ceiling, 1 video


def test_decide_omni_reject_two_videos_within_cap():
    # the multi-video trap: 2 videos at 30 credits is within the ceiling but MUST reject (num_videos)
    assert av.decide(_perm(30, nv=2), "omni_flash", 10)[0] == "reject"


def test_decide_fast_exact_20():
    assert av.decide(_perm(20), "veo_3_1_fast", 8)[0] == "approve"


def test_decide_quality_exact_100():
    assert av.decide(_perm(100), "veo_3_1_quality", 8)[0] == "approve"


def test_decide_rejects_image_only():
    assert av.decide(_perm(8, nv=0, ni=4), "veo_3_1_lite")[0] == "reject"


def test_decide_rejects_two_videos():
    assert av.decide(_perm(10, nv=2), "veo_3_1_lite")[0] == "reject"


def test_decide_rejects_video_plus_images():
    assert av.decide(_perm(10, ni=1), "veo_3_1_lite")[0] == "reject"


def test_decide_waits_on_empty():
    k, _m, a = av.decide(None, "veo_3_1_lite")
    assert k == "wait" and a is None


# --- dry-lane short-circuit regression (Codex finding): soft-phrase started must NOT
#     suppress would_approve; only a real generation toolInvocation may bail pre-approve. ---

_SOFT_PLUS_PROPOSAL = (
    'data: {"text": "Sure, I\'m generating your video concept now."}\n'   # soft phrase, no tool
    'data: {"agentMessage": {"agentEvents": [{"eventId": "p","toolInvocation": '
    '{"toolName": "ask_for_permission","toolArguments": '
    '{"num_videos": 1,"num_images": 0,"total_cost": 10,"num_total": 1}}}],"responseId": "p"}}\n'
)

_GEN_TOOL_PREAPPROVE = (
    'data: {"agentMessage": {"agentEvents": [{"eventId": "g","toolInvocation": '
    '{"toolName": "generate_video_with_references","toolArguments": '
    '{"model_usage_key": "veo_3_1_r2v_lite","duration": 8.0}}}],"responseId": "g"}}\n'
)


def test_dry_soft_phrase_does_not_suppress_would_approve():
    # soft "i'm generating" text + a valid proposal, NO generation tool → dry must reach would_approve
    res = _run(av.negotiate_and_generate(
        _FakeAgentClient(_SOFT_PLUS_PROPOSAL), "p1", "s1", "make a video", None,
        target_model="veo_3_1_lite", target_duration_s=8, approve=False))
    assert res.get("would_approve") == {"num_videos": 1, "num_images": 0,
                                        "total_cost": 10, "num_total": 1}
    assert not res.get("generation_started")   # MUST NOT short-circuit on soft text


def test_real_gen_tool_preapprove_still_bails():
    # control: a real generation toolInvocation before approval still bails with generation_started
    res = _run(av.negotiate_and_generate(
        _FakeAgentClient(_GEN_TOOL_PREAPPROVE), "p1", "s1", "make a video", None,
        target_model="veo_3_1_lite", target_duration_s=8, approve=False))
    assert res.get("generation_started") is True
    assert "would_approve" not in res


def test_decide_honours_user_count_setting():
    # USER SETTINGS ARE LAW: count=2 means a 2-video proposal is the CORRECT one
    # (approve, ceiling scales 2x) and a 1-video proposal must be rejected.
    kind, _msg, _p = av.decide({"num_videos": 2, "num_images": 0, "total_cost": 20},
                               "veo_3_1_lite", 8, desired_num=2)
    assert kind == "approve"
    kind, msg, _p = av.decide({"num_videos": 1, "num_images": 0, "total_cost": 10},
                              "veo_3_1_lite", 8, desired_num=2)
    assert kind == "reject" and "exactly 2" in msg
    # Cost cap scales with count: 2x Omni Flash 10s ceiling = 60.
    kind, _msg, _p = av.decide({"num_videos": 2, "num_images": 0, "total_cost": 30},
                               "Omni Flash", 10, desired_num=2)
    assert kind == "approve"
    kind, _msg, _p = av.decide({"num_videos": 2, "num_images": 0, "total_cost": 61},
                               "Omni Flash", 10, desired_num=2)
    assert kind == "reject"


def test_classify_agent_failure_reference_missing_phrases():
    # Exact live replies (Faris' screenshots, 2026-07-02) after a dead start media:
    assert av.classify_agent_failure(
        "I'm having trouble accessing the reference image you provided. It seems to "
        "be missing from the project right now. Could you please try selecting or "
        "attaching the product image again?") == "REFERENCE_IMAGE_MISSING"
    assert av.classify_agent_failure(
        "I wasn't able to find the reference image you provided. Could you try "
        "re-attaching the product photo, or let me know which image I should use "
        "as the starting frame?") == "REFERENCE_IMAGE_MISSING"


def test_classify_agent_failure_generic_and_none():
    assert av.classify_agent_failure(
        "Failed. Something went wrong. Please try again.") == "RENDER_FAILED"
    assert av.classify_agent_failure("I'm generating your video now!") is None
    assert av.classify_agent_failure("") is None
    assert av.classify_agent_failure(None) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
