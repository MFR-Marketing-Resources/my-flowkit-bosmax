# BOSMAX MCP Bridge

This package is a local stdio MCP server for Hermes Bot 4. It holds one private
authenticated `httpx` cookie jar and exposes only the four fixed BOSMAX Flow
tools:

- `bosmax_flow_readiness` → `GET /api/flow/direct-video-readiness`
- `bosmax_flow_generate` → `POST /api/flow/generate`
- `bosmax_flow_job_status` → `GET /api/flow/generate-job/{job_id}`
- `bosmax_flow_reretrieve_media` → `POST /api/flow/generate-job/{job_id}/reretrieve-media`

Configure the operator session in the process environment. The loopback default
is opt-in so a missing base URL cannot silently select a target:

```text
BOSMAX_LOCAL_USE=1
# or set BOSMAX_BASE_URL to an HTTPS BOSMAX origin explicitly
BOSMAX_BOT_EMAIL=...
BOSMAX_BOT_PASSWORD=...
```

Run it as a newline-delimited JSON-RPC MCP stdio process:

```text
python -m bosmax_mcp_bridge
```

The bridge never returns credentials, cookie values, response headers, or an
arbitrary endpoint. Generation remains behind BOSMAX's existing authenticated
`/api/flow/generate` route and its existing approval, readiness, provider, and
credit gates.
