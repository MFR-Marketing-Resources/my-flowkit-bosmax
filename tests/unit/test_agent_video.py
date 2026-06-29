"""Tests for the flowCreationAgent negotiation brain (patch B).

Authority fixture: tests/fixtures/agent_sse_proposal.txt — a REAL pre-approve SSE captured
0-credit. It proves the ask_for_permission proposal carries no model (model appears only
post-approve), so cost is the Lite proxy pre-approve and the model is verified post-approve.
"""
import os

from agent.services import agent_video as av

_FIXT = os.path.join(os.path.dirname(__file__), "..", "fixtures", "agent_sse_proposal.txt")

# Synthetic POST-approve SSE built from the real observed generate_video tool shape.
_POST_APPROVE = (
    'data: {"agentMessage": {"agentEvents": [{"eventId": "x","toolInvocation": '
    '{"toolName": "generate_video_with_references","toolArguments": '
    '{"model_usage_key": "veo_3_1_r2v_lite","model_display_name": "Veo 3.1 - Lite",'
    '"duration": 8.0,"aspect_ratio": "9:16"}}}],"responseId": "x"}}\n'
    'data: {"text": "beginRendering"}\n'
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
    assert st["started"] is True          # beginRendering + a generate tool
    assert st["model"] == "veo_3_1_r2v_lite"


def _perm(cost, nv=1, ni=0):
    return {"num_images": ni, "total_cost": cost, "num_total": nv, "num_videos": nv}


def test_decide_approve_lite_exact_10():
    k, _m, a = av.decide(_perm(10), "veo_3_1_lite", 8)
    assert k == "approve" and a == av.APPROVED


def test_decide_reject_lite_wrong_cost():
    # a 15-cost proposal is NOT Lite (Lite is exactly 10)
    assert av.decide(_perm(15), "veo_3_1_lite", 8)[0] == "reject"


def test_decide_omni_10s_needs_30_not_15_I6():
    # I6 at decide level: targeting Omni 10s, a 15-cost (4s) proposal MUST be rejected;
    # only the exact 30-cost proposal approves.
    assert av.decide(_perm(15), "omni_flash", 10)[0] == "reject"
    assert av.decide(_perm(30), "omni_flash", 10)[0] == "approve"


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
