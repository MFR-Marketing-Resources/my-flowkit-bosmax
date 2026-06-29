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


def test_decide_rejects_omni_cost15():
    perm = {"num_images": 0, "total_cost": 15, "num_total": 1, "num_videos": 1}
    kind, _m, action = av.decide(perm)
    assert kind == "reject" and action == av.DENIED


def test_decide_approves_lite_cost10():
    perm = {"num_images": 0, "total_cost": 10, "num_total": 1, "num_videos": 1}
    kind, _m, action = av.decide(perm)
    assert kind == "approve" and action == av.APPROVED


def test_decide_rejects_image_only():
    perm = {"num_images": 4, "total_cost": 8, "num_total": 4, "num_videos": 0}
    assert av.decide(perm)[0] == "reject"


def test_decide_rejects_two_videos():
    perm = {"num_images": 0, "total_cost": 10, "num_total": 2, "num_videos": 2}
    assert av.decide(perm)[0] == "reject"


def test_decide_rejects_video_plus_images():
    perm = {"num_images": 1, "total_cost": 10, "num_total": 1, "num_videos": 1}
    assert av.decide(perm)[0] == "reject"


def test_decide_waits_on_empty():
    kind, _m, action = av.decide(None)
    assert kind == "wait" and action is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
