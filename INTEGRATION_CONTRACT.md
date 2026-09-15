# Flow Kit Integration Contract

This contract defines the Phase 1 one-shot shoot integration surface. It is intentionally API-only: no full web UI, no cloud deployment, and no changes to the existing working Flow endpoints are required by this contract.

## Non-breaking scope

The following existing endpoints remain owned by the existing `/api/flow` router and are not replaced by this contract:

- `POST /api/flow/upload-image-base64`
- `POST /api/flow/upload-image`
- `POST /api/flow/generate-image`
- `POST /api/flow/generate-video`
- `POST /api/flow/check-status`
- `GET /api/flow/media/{id}`

`GET /health` already exists and is left in place.

## One-shot route

### `POST /shoot-oneshot`

Uploads a base64 image to Flow, submits a start-image video generation request, stores the job using the existing `request`/telemetry infrastructure, and returns immediately with a local `job_id`.

The local request row uses the existing `MANUAL_FLOW_JOB` type to avoid changing request schema constraints. Flow identifiers from the request payload are stored in the job report payload so arbitrary Google Flow project ids do not have to match local database foreign keys.

### Request

```json
{
  "image_base64": "<raw base64 or data URL>",
  "prompt": "Camera pushes in slowly on the product...",
  "project_id": "<google-flow-project-id>",
  "scene_id": "optional-local-or-external-scene-id",
  "file_name": "oneshot.png",
  "mime_type": "image/png",
  "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
  "user_paygate_tier": "PAYGATE_TIER_ONE",
  "timeout_seconds": 120
}
```

Required fields:

- `image_base64`
- `prompt`
- `project_id`

Optional fields:

- `scene_id`
- `file_name`, default `oneshot.png`
- `mime_type`, default `image/png`
- `aspect_ratio`, default `VIDEO_ASPECT_RATIO_PORTRAIT`
- `user_paygate_tier`, default `PAYGATE_TIER_ONE`
- `timeout_seconds`, default `120`, min `10`, max `600`

### Success response

```json
{
  "job_id": "<local-request-id>",
  "status": "PENDING",
  "status_url": "/job/<local-request-id>"
}
```

## Job route

### `GET /job/{id}`

Returns local one-shot job state from the existing request table plus the stored one-shot report.

### Response

```json
{
  "job_id": "<local-request-id>",
  "status": "WAITING_FLOW",
  "request_type": "MANUAL_FLOW_JOB",
  "project_id": "<google-flow-project-id>",
  "scene_id": "<optional-scene-id>",
  "uploaded_media_id": "<flow-media-id>",
  "output_url": null,
  "error_code": null,
  "error_message": null,
  "report": {
    "contract": "shoot-oneshot",
    "project_id": "<google-flow-project-id>",
    "scene_id": "<optional-scene-id>",
    "upload_result": {},
    "video_result": {}
  },
  "created_at": "2026-06-29T00:00:00Z",
  "updated_at": "2026-06-29T00:00:00Z"
}
```

Status values use the existing request status model:

- `PENDING`
- `PROCESSING`
- `WAITING_FLOW`
- `FAILED`

The one-shot job is considered successfully submitted when status becomes `WAITING_FLOW`. Final Flow operation polling can continue through the existing Flow status mechanisms using the stored `video_result` details.

## Error contract

All contract errors use this shape:

```json
{
  "detail": {
    "error_code": "ERROR_CODE",
    "message": "Human readable message",
    "details": {}
  }
}
```

Required error codes:

| Code | Typical HTTP status | Meaning |
| --- | ---: | --- |
| `EXTENSION_DISCONNECTED` | 503 | Chrome extension bridge is not connected or disconnects during job work. |
| `MISSING_FLOW_KEY` | 503 | Extension is connected but has not provided a Flow key/token state. |
| `NO_MODEL` | 422 | No configured Flow video model exists for the requested tier/aspect ratio. |
| `INVALID_IMAGE` | 400 | Image payload is empty, malformed, or invalid base64. |
| `JOB_FAILED` | 500/job status | Flow returned an unexpected failure or missing media id. |
| `TIMEOUT` | 500/job status | Upload or video submission exceeded the configured timeout. |

Additional lookup error:

| Code | Typical HTTP status | Meaning |
| --- | ---: | --- |
| `JOB_NOT_FOUND` | 404 | `/job/{id}` does not match a stored request. |

## Validation notes

Base64 upload path:

- Existing `POST /api/flow/upload-image-base64` implementation is not modified by this contract branch.
- The route remains registered through `flow_router` under `/api`.
- Manual live verification still requires a connected Chrome extension and Flow key.

One-shot path:

- `POST /shoot-oneshot` returns a `job_id` immediately after creating a local `MANUAL_FLOW_JOB` request row.
- The upload and video submission run asynchronously and can be inspected through `GET /job/{job_id}`.
- Live Flow submission still requires a connected Chrome extension, captured Flow key, valid base64 image, valid project id, and a configured video model.

## Example smoke commands

```bash
curl -sS http://127.0.0.1:8100/health
```

```bash
curl -sS -X POST http://127.0.0.1:8100/api/flow/upload-image-base64 \
  -H 'Content-Type: application/json' \
  -d '{"image_base64":"<base64>","file_name":"smoke.png","mime_type":"image/png","project_id":"<flow-project-id>"}'
```

```bash
curl -sS -X POST http://127.0.0.1:8100/shoot-oneshot \
  -H 'Content-Type: application/json' \
  -d '{"image_base64":"<base64>","prompt":"Simple product push-in shot","project_id":"<flow-project-id>"}'
```

Expected one-shot response includes:

```json
{
  "job_id": "<local-request-id>",
  "status": "PENDING",
  "status_url": "/job/<local-request-id>"
}
```
