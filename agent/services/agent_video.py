"""flowCreationAgent video negotiation — drive Google Flow's conversational video agent.

The current Flow video API is a conversational agent (flowCreationAgent). We send turn 1
(prompt + start image), then READ each SSE response and respond like a real agent:
- the agent proposes a config via `ask_for_permission` {total_cost, num_videos};
- we steer it (reject + correction) to 1 video / Veo 3.1 Lite, then approve;
- we KEEP READING until the agent's own reply confirms generation actually started.

No claims without evidence: success is only declared when the agent's text says it is
generating (e.g. "generating", "in the queue"). Every turn's raw agent reply is returned.
"""
import json

VEO_LITE_COST = 10  # one Veo 3.1 Lite video; Omni is 15 → steer to Lite
DENIED = "PERMISSION_ACTION_DENIED"
APPROVED = "PERMISSION_ACTION_APPROVED"

# Phrases in the agent's own reply that confirm a generation actually started.
# "beginrendering" is the hard signal: the agent emits a beginRendering event the
# moment the approved video starts rendering (confirmed live — credits drop with it).
_STARTED_PHRASES = ("beginrendering", "started generating", "i'm generating",
                    "generating your", "in the queue", "in queue", "should be ready",
                    "generating the", "kicking off", "i've started")

# Tool names that mean a video generation actually fired.
_GEN_TOOLS = ("generate_video", "generate_videos", "start_generation", "submit_generation",
              "generate_video_with_references", "generate_video_with_first_frame")


def _collect_text(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str):
                out.append(v)
            else:
                _collect_text(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_text(v, out)


def parse_agent_sse(text) -> dict:
    """Parse the SSE stream → {permission, tools, started, error, text}."""
    if isinstance(text, dict):
        if text.get("error"):
            return {"permission": None, "tools": [], "started": False,
                    "error": text["error"], "text": ""}
        text = json.dumps(text)
    permission, tools, error, texts, model = None, [], None, [], None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[5:].strip())
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("error"):
            error = obj["error"]
        _collect_text(obj, texts)
        am = obj.get("agentMessage", {}) if isinstance(obj, dict) else {}
        for ev in (am.get("agentEvents") or []):
            ti = ev.get("toolInvocation")
            if not ti:
                continue
            name = ti.get("toolName")
            tools.append(name)
            if name == "ask_for_permission":
                permission = ti.get("toolArguments", {}) or {}
            elif name in _GEN_TOOLS:
                # Model only appears POST-approve in the generate_video tool args
                # (the ask_for_permission proposal carries no model — confirmed by fixture).
                ta = ti.get("toolArguments", {}) or {}
                model = ta.get("model_usage_key") or ta.get("model_display_name") or model
    joined = " ".join(texts)
    low = joined.lower()
    started = (any(p in low for p in _STARTED_PHRASES)
               or any(t in _GEN_TOOLS for t in tools))
    return {"permission": permission, "tools": tools, "started": started,
            "error": error, "text": joined[:600], "model": model}


def decide(permission: dict, desired_num=1, max_cost=VEO_LITE_COST):
    """Given the agent's proposal, decide the next move.

    NEVER approve unless the proposal is explicitly for a VIDEO (num_videos >= 1).
    An image-only proposal (num_images set, num_videos absent/0) is rejected and
    steered to video — this is the bug that produced 'only images' before.
    """
    if not permission:
        return ("wait", "i want 1 video, not images. veo 3.1 - lite, vertical 9:16", None)
    nv = permission.get("num_videos")
    if nv is None:
        nv = permission.get("num_total")
    ni = permission.get("num_images")
    cost = permission.get("total_cost")
    # Must be a VIDEO proposal — refuse image-only / unclear proposals outright.
    if not nv:  # None or 0
        return ("reject", "i don't want images. i want 1 video, veo 3.1 - lite", DENIED)
    if nv != desired_num:
        return ("reject", "i want 1 video only", DENIED)
    if ni:  # a real video proposal must not also be generating images
        return ("reject", "no images. just 1 video, veo 3.1 - lite", DENIED)
    if cost is not None and cost > max_cost:
        return ("reject", "veo 3.1 - lite only", DENIED)
    return ("approve", "Approve", APPROVED)


async def negotiate_and_generate(client, project_id, session_id, prompt, media_ids,
                                 desired_num=1, max_cost=VEO_LITE_COST, max_turns=16,
                                 approve=True) -> dict:
    """Drive the agent until generation STARTS (verified by its own reply) or it fails.

    approve=False stops just before sending the first APPROVE (no credits) and reports
    the config it would approve. Returns a full transcript — no unverified claims.
    """
    transcript = []
    turn = 0

    async def send(text, perm=None, media=None):
        nonlocal turn
        turn += 1
        resp = await client.agent_stream_chat(
            session_id, project_id, turn, text, media_ids=media, permission_action=perm)
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        st = parse_agent_sse(data)
        raw = data if isinstance(data, str) else json.dumps(data)
        transcript.append({"turn": turn, "sent": text[:50], "perm_sent": perm,
                           "agent_text": st["text"], "permission": st["permission"],
                           "started": st["started"], "error": st["error"],
                           "raw_sse": raw[:40000]})
        return st

    state = await send(prompt, media=media_ids)
    while turn < max_turns:
        if state["error"]:
            return {"ok": False, "stage": "error", "error": state["error"], "transcript": transcript}
        if state["started"]:
            return {"ok": True, "generation_started": True,
                    "model_used": state.get("model"),
                    "agent_text": state["text"], "transcript": transcript}

        kind, msg, perm_action = decide(state["permission"], desired_num, max_cost)
        if kind == "approve":
            if not approve:
                return {"ok": True, "dry": True, "would_approve": state["permission"],
                        "transcript": transcript}
            # Approve EXACTLY ONCE — the generation is triggered server-side; never
            # re-approve (that would double-charge).
            state = await send(msg, perm=perm_action)
            return {"ok": True, "approved": True,
                    "generation_started": state["started"],
                    "model_used": state.get("model"),
                    "agent_text": state["text"], "transcript": transcript}
        if kind == "reject":
            await send("Reject", perm=perm_action)   # decline the wrong proposal
            state = await send(msg)                   # then send the correction
        else:                                         # wait / open question
            state = await send(msg)

    return {"ok": False, "stage": "max_turns",
            "error": "agent never confirmed generation started", "transcript": transcript}
