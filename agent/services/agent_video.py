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
RATE_LIMITED = "RATE_LIMITED"

# Google anti-abuse / rate-limiter signature on the flowCreationAgent stream. This fires
# PRE-APPROVE (0 credits): a 403 PERMISSION_DENIED carrying reCAPTCHA / PUBLIC_ERROR_
# UNUSUAL_ACTIVITY. It is NOT a negotiation decline and NOT a credit charge — surfacing it
# as "agent did not approve a video" reads like a rejection and hides the real, zero-cost
# cause (CURRENT_STATE OPEN ITEM #2: cool down ~1-2h, never hammer retries).
_RATE_LIMIT_SIGNS = (
    "public_error_unusual_activity",
    "recaptcha evaluation failed",
    "unusual_activity",
    "unusual activity",
)

# SOFT natural-language phrases that hint a generation started. These are secondary —
# the HARD proof is a generation toolInvocation (below). "beginrendering" was REMOVED:
# the agent also emits beginRendering for plain UI surface renders (e.g. a "with your
# current plan" chat message), so it false-positives outside actual generation.
_STARTED_PHRASES = ("started generating", "i'm generating",
                    "generating your", "in the queue", "in queue", "should be ready",
                    "generating the", "kicking off", "i've started")

# Tool names that mean a video generation actually fired (the HARD started signal).
# The generation toolNames whose toolArguments carry the correlation anchors
# (prompt / seed / model / tool_call_id). parse_agent_sse captures identity ONLY
# for a toolName in this tuple; a generation firing under any other name leaves
# every anchor None and its output can never be bound.
# CAUTION: the F2V/I2V/plain names below are ASSUMED, never confirmed by an
# approved live SSE. T2V proved that matters — its real tool turned out to be
# `generate_video_from_text` (captured live 2026-07-17), not any assumed name.
# Treat the unconfirmed entries as provisional until a live approved-SSE proves
# each one, exactly as was done for T2V.
_GEN_TOOLS = ("generate_video", "generate_videos", "start_generation", "submit_generation",
              "generate_video_with_references", "generate_video_with_first_frame",
              # T2V text-only. Captured live 2026-07-17 from g_b1ed597a9789's approve
              # stream (tools_seen=["generate_video_from_text"]) — the SSE capture
              # AGENTS.md recorded as "pending". Its absence here is why every T2V
              # anchor came back None and no T2V output could EVER be bound: with
              # sse_prompt=None the only anchor left is the raw prompt, which never
              # equals the compiled prompt the provider stores. Its toolArguments
              # carry prompt + model_usage_key (veo_3_1_t2v_lite) + model_display_name.
              "generate_video_from_text")

# Prepended to the first agent message for a no-reference (T2V) run so the agent
# generates text-to-video and does not attach a stray reference from a shared/dirty
# Flow project (which routed a T2V to generate_video_with_references/R2V live and the
# render failed — g_7d71f6b020cb). Applied ONLY when there is no reference media; the
# F2V/I2V path never sees it. A nudge on the agent's FIRST tool choice, not a hard gate.
_TEXT_ONLY_DIRECTIVE = (
    "Generate this strictly as a TEXT-TO-VIDEO. Do not attach, select, or reuse any "
    "existing image, start frame, or project media as a reference — produce the video "
    "purely from the description below.\n\n")

# Post-approve failure knowledge (captured live 2026-07-02, Faris' screenshots):
# when the render dies server-side the agent posts a "Failed / Something went
# wrong" toast and then EXPLAINS itself in chat. The most common cause is a
# reference image the agent can no longer access (stale/deleted media). These
# phrases classify that reply so the pipeline fails FAST with the true cause
# instead of polling an empty project for 12 minutes. Typing "regenerate" is
# WRONG for the reference case — it refires the same dead reference and burns
# credits again; the correct recovery is re-attach/re-upload the image.
_REFERENCE_MISSING_PHRASES = (
    "trouble accessing the reference image",
    "wasn't able to find the reference image",
    "unable to find the reference image",
    "couldn't find the reference image",
    "it seems to be missing from the project",
    "missing from the project right now",
    "attaching the product image again",
    "re-attaching the product photo",
    "which image i should use as the starting frame",
)
_RENDER_FAILED_PHRASES = (
    "something went wrong. please try again",
    "generation failed",
    "failed to generate",
    "video generation was unsuccessful",
)


def classify_agent_failure(text) -> str | None:
    """Classify an agent reply into a failure kind, or None if it is not a failure.
    'REFERENCE_IMAGE_MISSING' → re-attach/re-upload the start image (NEVER just
    'regenerate'); 'RENDER_FAILED' → generic server-side render failure."""
    low = str(text or "").lower()
    if not low:
        return None
    if any(p in low for p in _REFERENCE_MISSING_PHRASES):
        return "REFERENCE_IMAGE_MISSING"
    if any(p in low for p in _RENDER_FAILED_PHRASES):
        return "RENDER_FAILED"
    return None


def classify_provider_error(error) -> str | None:
    """Classify a raw provider/transport error from the SSE stream.
    'RATE_LIMITED' = Google anti-abuse block (403 reCAPTCHA / PUBLIC_ERROR_UNUSUAL_ACTIVITY),
    which always fires pre-approve and spends ZERO credits. None = unclassified (surface raw)."""
    low = str(error or "").lower()
    if not low:
        return None
    if any(s in low for s in _RATE_LIMIT_SIGNS):
        return RATE_LIMITED
    return None


def provider_error_message(error) -> str:
    """Operator-facing message for a provider/transport error. A rate-limiter block is
    relabelled honestly (zero credits, cool down) instead of reading as a decline."""
    if classify_provider_error(error) == RATE_LIMITED:
        return ("RATE_LIMITED: Google anti-abuse rate limiter (reCAPTCHA / unusual "
                "activity) blocked the request before approval — 0 credits were spent. "
                "Cool down ~1-2h before retrying; do not hammer retries.")
    return str(error)


async def probe_render_failure(client, project_id, session_id, turn_number) -> dict:
    """Cheap in-session status probe (no media, no permission → zero credits):
    ask the agent whether the last generation finished, and classify its reply.
    Returns {classification, agent_text, turn_number(next)}. Never raises."""
    try:
        resp = await client.agent_stream_chat(
            session_id, project_id, turn_number,
            "Quick status check: did the last video generation finish successfully, "
            "or did it fail? Answer briefly, do not generate anything new.")
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        st = parse_agent_sse(data)
        return {
            "classification": classify_agent_failure(st.get("text")),
            "agent_text": (st.get("text") or "")[:400],
            "turn_number": turn_number + 1,
        }
    except Exception as e:  # noqa: BLE001 — the probe must never kill retrieval
        return {"classification": None, "agent_text": f"probe_error: {e}",
                "turn_number": turn_number + 1}


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
    gen_prompt, gen_seed, tool_call_id, response_id = None, None, None, None
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
                # PR321 closure: capture EVERY exact identity the generation tool
                # invocation exposes (SSE contract carries toolCallId + responseId;
                # prompt/seed when the agent passes them) — the correlation anchors
                # for deterministic current-run output binding.
                gen_prompt = (ta.get("prompt") or ta.get("video_prompt")
                              or ta.get("prompt_text") or gen_prompt)
                gen_seed = ta.get("seed", gen_seed)
                tool_call_id = ti.get("toolCallId") or tool_call_id
                response_id = am.get("responseId") or response_id
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
            "duration_used": duration_used,
            "gen_prompt": gen_prompt, "gen_seed": gen_seed,
            "tool_call_id": tool_call_id, "response_id": response_id}


def decide(permission, target_model=None, target_duration_s=None, desired_num=1,
           has_reference=False):
    """Steer the agent to the USER-SELECTED model+duration and approve under a CAP-GATE
    (Layer A): num_videos==1, num_images==0, and cost <= ceiling(model, duration).

    Cost is NOT an exact duration proxy any more — credits are promo-variable and the agent
    proposes by credits (often multi-video). So the gate uses the registry value as a CEILING
    (a promo cheaper price still passes), refuses multi-video / images, and NEVER puts a credit
    target in the steer text (that makes the agent inflate the video count to hit the number).
    The actual model AND duration are verified POST-approve (the proposal carries neither).

    STEER WORDING LAW (SEV-0/live incident): a correction must NEVER say "no images" —
    the agent reads that as "drop the attached reference image" and rewrites the run as a
    text-only generation with the wrong product. When a reference is attached, every steer
    explicitly PRESERVES it; the image-output ban is phrased as "no separate image
    generations", which the agent does not confuse with the reference.
    """
    spec = video_models.resolve(target_model)
    dur = target_duration_s if target_duration_s is not None else spec["default_duration_s"]
    # The ceiling scales with the USER-SELECTED count (production setting fidelity):
    # count=2 means a 2-video proposal is the CORRECT one and costs ~2× the unit cap.
    ceiling = video_models.expected_cost(spec["key"], dur) * max(1, int(desired_num or 1))
    video_word = "video" if desired_num == 1 else "videos"
    # STEER WORDING LAW, opposite direction (live g_7d71f6b020cb): the has_reference
    # branch PRESERVES the F2V/I2V reference (unchanged). The no-reference branch must
    # now be equally explicit that a T2V run is TEXT-ONLY — otherwise, in a shared/dirty
    # Flow project, the agent acquires a stray reference and fires
    # generate_video_with_references (R2V) for what must be text-only. The F2V path is
    # byte-identical; only the T2V (else) wording gains a positive text-only instruction.
    keep_ref = (" using the attached reference image" if has_reference
                else " generated only from the text prompt, with no reference image")
    steer = (f"{spec['agent_label']}, {dur} second {video_word}, "
             f"{desired_num} {video_word} only{keep_ref}, no separate image generations")
    if not permission:
        return ("wait", steer, None)
    nv = permission.get("num_videos")
    if nv is None:
        nv = permission.get("num_total")
    ni = permission.get("num_images")
    cost = permission.get("total_cost")
    if not nv:  # None or 0 — image-only / unclear
        return ("reject", f"do not generate images — generate the {video_word}{keep_ref}. {steer}", DENIED)
    if nv != desired_num:  # reject any count that differs from the USER's setting
        return ("reject", f"i want exactly {desired_num} {video_word}, not {nv}. {steer}", DENIED)
    if ni:  # a real video proposal must not also generate images
        return ("reject", f"do not generate images — generate the {video_word}{keep_ref}. {steer}", DENIED)
    if cost is not None and cost > ceiling:  # CAP, not exact — promos may be cheaper
        return ("reject",
                f"too expensive for {desired_num} {video_word} — "
                f"i want {desired_num} {spec['ui_label']} only", DENIED)
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
            # Exact generation identities from the fired tool (PR321 closure) —
            # the deterministic output-correlation anchors.
            "gen_prompt": st.get("gen_prompt"),
            "gen_seed": st.get("gen_seed"),
            "tool_call_id": st.get("tool_call_id"),
            "response_id": st.get("response_id"),
            # Every toolName the SSE actually exposed. Identity above is only
            # captured for names in _GEN_TOOLS; when a generation fires under a
            # name that is NOT in that tuple, every anchor comes back None and
            # the run can never be bound (live g_e71cd329b524: T2V, all five
            # anchors null while approved=True and the render fired). Carrying
            # the observed names makes that gap diagnosable from the run itself
            # instead of requiring another paid capture — this is the evidence
            # AGENTS.md's "text-only generation tool name pending one captured
            # approved-SSE" is waiting for.
            "tools_seen": list(st.get("tools") or []),
            "gen_tool_matched": bool(st.get("started_tool")),
        }

    # Text-only guard on the FIRST message (the reactive steer above only fires on a
    # rejected proposal; the agent's first tool choice is made from this send alone).
    # With no reference media, instruct text-to-video explicitly so the agent cannot
    # pick up a stray reference from a shared/dirty project and route to R2V. The
    # directive is prepended only to what is SENT — the creative `prompt` (and thus the
    # correlation anchor make_video captures) is untouched. F2V/I2V (media present) is
    # unchanged.
    initial_text = prompt if media_ids else _TEXT_ONLY_DIRECTIVE + prompt
    state = await send(initial_text, media=media_ids)
    while turn < max_turns:
        if state["error"]:
            return {"ok": False, "stage": "error",
                    "error_class": classify_provider_error(state["error"]),
                    "error": provider_error_message(state["error"]),
                    "error_raw": state["error"], "transcript": transcript}
        # PRE-approve bail: only a real generation toolInvocation (started_tool) may short-circuit
        # here. Soft text alone must NOT — else it suppresses would_approve on the dry lane (I4a).
        if state["started_tool"]:
            return {"ok": True, "generation_started": True,
                    **_verdict(state),
                    "agent_text": state["text"], "transcript": transcript}

        kind, msg, perm_action = decide(state["permission"], target_model,
                                        target_duration_s, desired_num,
                                        has_reference=bool(media_ids))
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
                    # The render can die INSIDE the approve stream (e.g. missing
                    # reference image) — surface it so the caller fails fast.
                    "failure_classification": classify_agent_failure(state["text"]),
                    "turns_used": turn,
                    "agent_text": state["text"], "transcript": transcript}
        if kind == "reject":
            await send("Reject", perm=perm_action)   # decline the wrong proposal
            state = await send(msg)                   # then send the correction
        else:                                         # wait / open question
            state = await send(msg)

    return {"ok": False, "stage": "max_turns",
            "error": "agent never confirmed generation started", "transcript": transcript}
