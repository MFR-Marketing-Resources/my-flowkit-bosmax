# Postiz Integration — Operator Guide

> **Shortcut:** the dashboard's **Postiz Publish** page includes a built-in
> **Setup Doctor** — open `/postiz` and it walks you through every step below
> (service start, API key, `.env` values, restart, channel connection) with
> live ✓/✗ status and a RE-CHECK button. This guide is the long-form
> reference for the same flow.

BOSMAX-generated images/videos (the Library artifacts under
`output/retrieved/`) can be handed to a self-hosted Postiz scheduler and
turned into drafts/scheduled posts across connected social channels —
**without manually re-uploading files**.

The integration is feature-flagged and fail-closed: with `POSTIZ_ENABLED=false`
(the default) nothing changes anywhere in BOSMAX.

## 1. Run Postiz (external Docker service)

```bash
cd infra/postiz
copy .env.postiz.example .env    # fill JWT_SECRET + POSTGRES_PASSWORD
docker compose up -d
```

The stack includes Postiz + its postgres/redis **and the Temporal workflow
stack** (Temporal 1.28.1 + Elasticsearch visibility + a dedicated postgres),
mirroring the official `gitroomhq/postiz-docker-compose` — current Postiz
images will not boot without Temporal. First boot takes a few minutes.

Open <http://localhost:5000>, register the operator account, then
**Settings → Public API → generate an API key**.

Note: the self-hosted Public API lives under `/api/public/v1` (BOSMAX's
default `POSTIZ_API_PREFIX`). Postiz Cloud uses
`https://api.postiz.com` + `POSTIZ_API_PREFIX=/public/v1`.

## 2. Configure BOSMAX

Add to the BOSMAX `.env` (see `.env.example` at repo root):

```
POSTIZ_ENABLED=true
POSTIZ_BASE_URL=http://127.0.0.1:5000
POSTIZ_API_KEY=<your key>
POSTIZ_UPLOAD_MODE=file          # multipart upload of the local file (default)
POSTIZ_DEFAULT_POST_TYPE=draft   # nothing goes public unless you choose it
```

> **Windows note:** prefer `POSTIZ_BASE_URL=http://127.0.0.1:5000` over
> `localhost` — on machines where `localhost` resolves to IPv6 (`::1`) first,
> requests to the Docker port can hang. The Setup Doctor detects this trap
> (`POSTIZ_LOCALHOST_RESOLVES_IPV6`) and prescribes the same fix.

The agent **loads the repo-root `.env` automatically at startup**
(`agent/config.py`, via `python-dotenv`), so "edit `.env` and restart" is the
whole workflow — a bare `python -m agent.main` picks the values up. Variables
already present in the OS environment stay authoritative; the file only fills
in what's missing. A missing `.env` is harmless. `.env` is gitignored — never
commit it.

Restart the agent (it has no --reload). `GET /api/postiz/health` must return
`ok: true`.

**Two separate authentication layers** — don't conflate them:

1. **BOSMAX → Postiz**: the `POSTIZ_API_KEY` above. It only lets BOSMAX call
   the Postiz Public API (list channels, create drafts). It does **not**
   connect any social account.
2. **Postiz → social platforms**: done inside the Postiz UI via each
   provider's official OAuth (**Add Channel**). Meta/Facebook/Instagram, X,
   TikTok and YouTube only appear in BOSMAX after Postiz has connected them
   (see section 3).

`POSTIZ_UPLOAD_MODE=url` exists for CDN setups only: it requires
`POSTIZ_PUBLIC_MEDIA_BASE_URL` (public **HTTPS**) — localhost/private URLs are
rejected by design because the Postiz backend must fetch them.

## 3. Connect social channels (in Postiz, not BOSMAX)

Channels are connected in the Postiz UI via each provider's official OAuth.
Self-hosted Postiz has **no channel cap** — one "channel" = one connected
account, and you can connect **multiple accounts of the same provider**
(e.g. several TikTok accounts or Facebook Pages). BOSMAX lists them all and
lets you multi-select per publish.

### TikTok (read before connecting)
- Requires your own TikTok **developer app** with the **Content Posting API**
  and **Direct Post** product enabled, an **HTTPS redirect URI**, and a
  **verified media domain**.
- Scopes: `user.info.basic`, `user.info.profile`, `video.create`,
  `video.publish`, `video.upload`.
- **Unaudited apps**: TikTok may force `SELF_ONLY` (private) visibility and
  rate-limit posting until your app passes TikTok's audit. BOSMAX's TikTok
  template therefore defaults to `privacy_level=SELF_ONLY` — widen it only
  after your audit passes. Do **not** treat multi-account public TikTok
  posting as production-ready before that.

### Facebook / Instagram / Threads
- Requires a Meta app in **LIVE mode** (development mode = no public
  visibility), business permissions, and per-Page/account authorization.
- Standalone Instagram posting requires a **professional** (business/creator)
  account.

### YouTube
- OAuth app + quota; BOSMAX's template defaults uploads to `private`.

## 4. Publish from BOSMAX

Dashboard → **Postiz Publish** (SYSTEM/WORKSPACE nav):
1. Pick a generated artifact (image/video from the Library).
2. Pick one or more channels — multiple channels of the same provider is fine.
3. Pick `draft` (default) / `schedule` (+ date-time) / `now`.
4. Review the per-provider settings + warnings, submit.

API equivalents:

| Endpoint | Purpose |
|---|---|
| `GET /api/postiz/health` | config check (never returns the key) |
| `GET /api/postiz/integrations` | connected channels |
| `GET /api/postiz/provider-templates` | safe-default settings + warnings |
| `POST /api/postiz/publish` | upload artifact + create draft/schedule/now post (`dry_run: true` = payload preview only) |
| `GET /api/postiz/publish-records` | audit trail (media ids, post ids, errors) |

Every publish writes a `postiz_publish_record` row (artifact → Postiz media id
→ post response) so nothing is untraceable.

## 5. Known limitations (do not skip)

- **TikTok**: unaudited app ⇒ private-only posting; media/redirect domains
  must be verified HTTPS. Public multi-account TikTok posting is **NOT
  VERIFIED** until your app authorization + audit exist.
- **Meta**: app must be Live; permissions are per-asset (Page/IG account).
- **upload-from-url**: only public HTTPS; BOSMAX's local
  `/api/flow/retrieved/...` URLs will NOT work for this mode.
- No auto-retry on upload/post calls (duplicate-post hazard) — failed
  publishes stay visible in the audit trail for manual retry.
- BOSMAX never bypasses OAuth, never scrapes providers, and never invents
  channels: everything comes from the official Postiz Public API.

## 6. Runtime provisioning & recovery (prevent recurrence)

**Why this keeps breaking.** The agent reads its configuration from the
repo-root `.env` (`agent/config.py`). `.env` is **gitignored on purpose** — it
holds the local `POSTIZ_API_KEY`, which must never be committed. But because Git
does not track it, **`.env` does not travel when you create or reset a runtime
worktree** (`git worktree add`, a fresh clone, a hard reset). A new runtime
worktree therefore starts with **no `.env`**, the agent loads zero `POSTIZ_*`
values, and the Setup Doctor regresses to `POSTIZ_DISABLED` /
`POSTIZ_BASE_URL_MISSING` / `POSTIZ_API_KEY_MISSING`. Repo/PR cleanup can never
fix this, because the missing piece is untracked local config — not code.

**Fix it in one step (safe, repeatable, no secrets printed):**

```powershell
# Run against the runtime worktree that serves :8100.
# Copies an existing key from another local .env if this worktree has none.
scripts/setup-postiz-runtime.ps1 -RuntimeRoot C:\path\to\runtime_worktree `
    -SourceEnv  C:\path\to\other\.env
```

The script:

- writes only the `POSTIZ_*` keys, preserving every other line in an existing
  `.env`, and backs up any file it changes to `.env.backup-YYYYMMDD-HHMMSS`;
- **preserves** an existing `POSTIZ_API_KEY`, else **copies** one from
  `-SourceEnv` **without printing it**, else writes the `<paste key>`
  placeholder and tells you the owner step;
- prints status only (`KEY_PRESENT`, `BASE_URL_SET`, `ENV_PATH`, `CHANGED`) —
  never the key, never the whole file.

Then **restart the agent** so the new values load (the agent has no `--reload`):

```powershell
scripts/start-local-agent.ps1 -ForceRestart
```

**Verify it (read-only, no secrets, no posting):**

```powershell
scripts/doctor-postiz-runtime.ps1 -RuntimeRoot C:\path\to\runtime_worktree
```

It checks the runtime `.env` names, probes the Postiz base URL (with the same
`localhost`→`127.0.0.1` IPv6 fallback the agent uses), reads
`GET /api/postiz/setup-status`, and prints a single `DOCTOR_VERDICT`:

| Verdict | Meaning | Exit |
|---|---|---|
| `READY` | Configured and ≥1 channel connected. | 0 |
| `OWNER_CHANNEL_OAUTH_REQUIRED` | **Config is correct** (`problems: []`) but `integrations_count: 0`. This is the normal "connect a channel" state, **not** a failure — do section 3's OAuth in the Postiz UI. | 0 |
| `CONFIG_PROBLEMS` | Setup Doctor reported problem codes — re-run the setup script + restart. | 1 |
| `AGENT_DOWN` | The BOSMAX agent isn't answering — start it. | 1 |

> **Reading the Setup Doctor:** `problems: []` together with `ready: false` and
> `integrations_count: 0` is **healthy** — it means only the owner OAuth channel
> connect is left. A red state always carries a `problems` code. A `<paste key>`
> placeholder (no real key pasted yet) reads as `POSTIZ_API_KEY_MISSING`
> everywhere — a **config problem** (`CONFIG_PROBLEMS`), never mistaken for a
> present key or the connect-a-channel state.

**Security (non-negotiable):** never commit or upload `.env`, `.env.backup-*`,
`.env.bak`, or the API key; never paste the key into logs, screenshots, or PRs.
All of these are gitignored — keep them that way.
