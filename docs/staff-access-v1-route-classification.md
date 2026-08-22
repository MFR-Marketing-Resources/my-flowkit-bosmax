# Staff & Access V1 route classification

The human access guard runs before FastAPI route handlers. Route classification is
fail-closed: any `/api/` path not explicitly classified as authentication,
internal service transport, or health/provenance is an authenticated human API.

| Class | Current surface | Authority |
| --- | --- | --- |
| A — public authentication | `/api/auth/*` | CSRF/origin proof for state changes; no session required |
| B — authenticated human | All other `/api/*` paths by default, including products, copy, assets, production, poster, reporting, publishing, jobs, staff, roles, sessions, audit, settings, and provider routes | HttpOnly session → ACTIVE UserAccount → ACTIVE StaffProfile → role permissions |
| C — internal service | `/api/ext/*`; extension/local-agent status and capture routes; operator content-pack/runtime status; telemetry stage; extension file materialization; product-image transport | Existing transport contract; no human-session dependency |
| D — health/provenance | `/health`; `/api/local-agent/version-proof`; `/api/operator/runtime-storage-status`; `/api/flow/bind-check`; static dashboard/media shell | Read-only health/provenance or app shell |

Mutation requests in A and B require the double-submit CSRF cookie/header or a
validated same-origin local request. B permissions are derived from the module
prefix and HTTP/action marker (`production.execute`, `copy.approve`,
`jobs.control`, and so on). Unknown human paths require
`system.settings.manage`, so a new route cannot silently become public.

Internal classification is intentionally narrow. The broad Flow generation,
production, provider, reporting, and dashboard APIs remain class B even when an
extension is involved; only the transport callback/status/materialization
surfaces needed by the extension are class C.
