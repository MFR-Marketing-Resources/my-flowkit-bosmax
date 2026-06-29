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

from agent.services import video_models

VEO_LITE_COST = 10  # legacy default; pricing now lives in video_models (cost = f(model, duration))
DENIED = "PERMISSION_ACTION_DENIED"
APPROVED = "PERMISSION_ACTION_APPROVED"

# SOFT natural-language phrases that hint a generation started. These are secondary —
# the HARD proof is a generation toolInvocation (below). "beginrendering" was REMOVED:
# the agent also emits beginRendering for plain UI surface renders (e.g. a "with your
# current plan" chat message), so it false-positives outside actual generation.
_STARTED_PHRASES = ("started generating", "i'm generating",
                    "generating your", "in the queue", "in queue", "should be ready",
                    "generating the", "kicking off", "i've started")

# Tool names that mean a video generation actually fired (the HARD started signal).
# NOTE: `generate_video_from_text` (Omni T2V) is NOT added yet — current evidence only shows
# it in thinking/denied-tool TEXT, not as a real toolInvocation.toolName in an APPROVED SSE.
# Pending one approved-SSE capture before adding it.
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
    permission, tools, error, texts, model, duration_used = None, [], None, [], None, None
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
                # Model + duration appear POST-approve in the generate_video tool args
                # (the ask_for_permission proposal carries NEITHER — confirmed by fixture).
                ta = ti.get("toolArguments", {}) or {}
                model = ta.get("model_usage_key") or ta.get("model_display_name") or model
                dur = ta.get("duration", ta.get("duration_s"))
                if dur is not None:
                    try:
                        duration_used = int(round(float(dur)))
                    except (TypeError, ValueError):
                        pass
    joined = " ".join(texts)
    low = joined.lower()
    # started_tool is the HARD proof — a real generation toolInvocation fired. `started` keeps
    # the soft phrases too, but ONLY for post-approve confirmation / transcript. The PRE-approve
    # bail must use started_tool so soft text can never short-circuit a proposal (dry-lane fix).
    started_tool = any(t in _GEN_TOOLS for t in tools)
    started = (any(p in low for p in _STARTED_PHRASES) or started_tool)
    return {"permission": permission, "tools": tools, "started": started,
            "started_tool": started_tool,
            "error": error, "text": joined[:600], "model": model,
            "duration_used": duration_used}


def decide(permission, target_model=None, target_duration_s=None, desired_num=1):
    """Steer the agent to the USER-SELECTED model+duration and approve under a CAP-GATE
    (Layer A): num_videos==1, num_images==0, and cost <= ceiling(model, duration).

    Cost is NOT an exact duration proxy any more — credits are promo-variable and the agent
    proposes by credits (often multi-video). So the gate uses the registry value as a CEILING
    (a promo cheaper price still passes), refuses multi-video / images, and NEVER puts a credit
    target in the steer text (that makes the agent inflate the video count to hit the number).
    The actual model AND duration are verified POST-approve (the proposal carries neither).
    """
    spec = video_models.resolve(target_model)
    dur = target_duration_s if target_duration_s is not None else spec["default_duration_s"]
    ceiling = video_models.expected_cost(spec["key"], dur)
    steer = f"{spec['agent_label']}, {dur} second video, 1 video only, no images"
    if not permission:
        return ("wait", steer, None)
    nv = permission.get("num_videos")
    if nv is None:
        nv = permission.get("num_total")
    ni = permission.get("num_images")
    cost = permission.get("total_cost")
    if not nv:  # None or 0 — image-only / unclear
        return ("reject", f"no images. {steer}", DENIED)
    if nv != desired_num:  # reject multi-video even if total cost is within the cap
        return ("reject", f"i want exactly {desired_num} video, not {nv}. {steer}", DENIED)
    if ni:  # a real video proposal must not also generate images
        return ("reject", f"no images. {steer}", DENIED)
    if cost is not None and cost > ceiling:  # CAP, not exact — promos may be cheaper
        return ("reject", f"too expensive for 1 video — i want 1 {spec['ui_label']} only", DENIED)
    return ("approve", "Approve", APPROVED)


async def negotiate_and_generate(client, project_id, session_id, prompt, media_ids,
                                 target_model=None, target_duration_s=None,
                                 desired_num=1, max_turns=16, approve=True) -> dict:
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

    def _verdict(st):
        # Post-approve model + duration verification (the proposal carries neither).
        mu = st.get("model")
        du = st.get("duration_used")
        tgt_dur = (target_duration_s if target_duration_s is not None
                   else video_models.resolve(target_model)["default_duration_s"])
        return {
            "model_used": mu,
            "model_ok": (video_models.model_matches(mu, target_model) if mu else None),
            "duration_used": du,
            "duration_ok": (None if du is None else (du == tgt_dur)),
        }

    state = await send(prompt, media=media_ids)
    while turn < max_turns:
        if state["error"]:
            return {"ok": False, "stage": "error", "error": state["error"], "transcript": transcript}
        # PRE-approve bail: only a real generation toolInvocation (started_tool) may short-circuit
        # here. Soft text alone must NOT — else it suppresses would_approve on the dry lane (I4a).
        if state["started_tool"]:
            return {"ok": True, "generation_started": True,
                    **_verdict(state),
                    "agent_text": state["text"], "transcript": transcript}

        kind, msg, perm_action = decide(state["permission"], target_model,
                                        target_duration_s, desired_num)
        if kind == "approve":
            if not approve:
                return {"ok": True, "dry": True, "would_approve": state["permission"],
                        "transcript": transcript}
            # Approve EXACTLY ONCE — the generation is triggered server-side; never
            # re-approve (that would double-charge).
            state = await send(msg, perm=perm_action)
            return {"ok": True, "approved": True,
                    "generation_started": state["started"],
                    **_verdict(state),
                    "agent_text": state["text"], "transcript": transcript}
        if kind == "reject":
            await send("Reject", perm=perm_action)   # decline the wrong proposal
            state = await send(msg)                   # then send the correction
        else:                                         # wait / open question
            state = await send(msg)

    return {"ok": False, "stage": "max_turns",
            "error": "agent never confirmed generation started", "transcript": transcript}
