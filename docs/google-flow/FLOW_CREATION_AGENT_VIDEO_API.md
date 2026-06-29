# Google Flow Video API — flowCreationAgent (current, Omni/V2 era)

> **Captured live 2026-06-29** from a real video generation on a Google AI Pro account
> via the extension webRequest hook. This SUPERSEDES the direct
> `/v1/video:batchAsyncGenerateVideoStartImage` API (now dead — returns 400/500).

## The architecture changed
The old direct video API (`videoModelKey` + `startImage` → `batchAsyncGenerateVideoStartImage`)
is **gone**. The current Omni/V2 Flow UI generates video through a **conversational agent**
(`flowCreationAgent`) over Server-Sent Events. You no longer pass a model key — the agent
picks the model from the user's settings (e.g. "Veo 3.1 Lite") and the prompt.

## The captured flow

### 1. Upload the start image (unchanged)
`POST https://aisandbox-pa.googleapis.com/v1/flow/uploadImage` → `mediaId` (UUID).

### 2. Create an agent session
`POST https://aisandbox-pa.googleapis.com/v1/flowCreationAgent/sessions`
```json
{ "projectId": "projects/8911da64-e242-4591-82bc-b3edcfbd464d" }
```
→ returns an `agentSessionId`. NOTE the `projects/{id}` prefix on projectId.

### 3. Generate via streamChat (SSE) — turn 1 carries the prompt + image
`POST https://aisandbox-pa.googleapis.com/v1/flowCreationAgent:streamChat?alt=sse`
```json
{
  "agentSessionId": "ec681daa-5efd-4b4a-aaf7-547b55b0f3fa",
  "agentClientContext": {
    "projectId": "projects/8911da64-e242-4591-82bc-b3edcfbd464d",
    "clientSessionId": ";1782701395661",
    "recaptchaContext": {
      "token": "<solved reCAPTCHA token>",
      "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB"
    },
    "turnNumber": 1
  },
  "userMessage": {
    "userPrompt": { "parts": [ { "text": "<full video prompt text>" } ] },
    "mediaReferences": [ { "mediaId": "f4196cf1-aeaf-49bb-934e-89c75164305e" } ]
  }
}
```
- `mediaReferences[].mediaId` = the uploaded start image (the product anchor).
- `userPrompt.parts[].text` = the full prompt (the captured one was a BOSMAX prompt:
  vertical 9:16, CHARACTER/ANCHOR/DIALOG SCRIPT/OVERLAY TEXT).
- Response is an **SSE stream** (`alt=sse`) — the agent streams back its plan, asks for
  **permission**, then generates.

### 4. Subsequent turns steer the agent (permission flow)
Later `streamChat` turns (turnNumber 2,3,4...) carry short messages and a
`permissionAction`:
```json
{ ...agentClientContext (turnNumber: N)...,
  "userMessage": { "userPrompt": { "parts": [ { "text": "Reject" } ] } },
  "permissionAction": "PERMISSION_ACTION_DENIED" }
```
Observed values: `"Reject"` + `PERMISSION_ACTION_DENIED`, and plain text like
`"only 1 video"`. The operator used these to steer the agent down to a single video.
The actual generate-approval action (PERMISSION_ACTION_APPROVED or equivalent) and the
SSE **response** shape are NOT yet captured — webRequest only captured request bodies,
not the SSE responses. **TODO: capture the SSE response stream** to map: how the agent
signals "ready to generate", how to approve, and how the finished video media is returned.

## Endpoints (current)
| Purpose | Endpoint |
|---|---|
| Create agent session | `/v1/flowCreationAgent/sessions` |
| Generate / chat (SSE) | `/v1/flowCreationAgent:streamChat?alt=sse` |
| Upload start image | `/v1/flow/uploadImage` |
| Project create (tRPC) | `https://labs.google/fx/api/trpc/project.createProject` |

## Implications for BOSMAX
- The direct `generate_video` / `models.json` videoModelKey path is **obsolete** for the
  current Flow. Rebuild the video lane around `flowCreationAgent` (session → streamChat
  with prompt + mediaReferences → handle SSE + permission → collect video).
- Image generation (`/v1/projects/{id}/flowMedia:batchGenerateImages`, `GEM_PIX_2`) still
  works directly — only VIDEO moved to the agent.
- reCAPTCHA is still solved by the extension (`RECAPTCHA_APPLICATION_TYPE_WEB`).
- Next capture needed: the **SSE response** (turn on response logging) to finish the spec.
