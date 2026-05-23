# Google Flow - Authenticated Editor Network Payload Map

This document describes the network payload communication patterns, endpoints, and schema structures. Because the live scouting run focused on UI DOM inspection and screenshot capture, the network details here are structured based on codebase definitions and classified accordingly.

---

## 1. Request Structure and Metadata (INFERRED_FROM_CODE)

All requests submitted by the extension-agent bridge to Google Flow APIs require a standardized client context containing session telemetry and safety parameters.

### Client Context Schema
```json
{
  "clientContext": {
    "projectId": "6d37e3eb-a8f5-4ea4-ba01-d25514213d4c",
    "recaptchaContext": {
      "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
      "token": "[CAPTCHA_TOKEN_INJECTED_BY_EXTENSION]"
    },
    "sessionId": ";1779531298912",
    "tool": "PINHOLE",
    "userPaygateTier": "PAYGATE_TIER_TWO"
  }
}
```

---

## 2. API Endpoint Inventory

### 2.1 Project Creation (tRPC) (INFERRED_FROM_CODE)
* **Endpoint:** `https://labs.google/fx/api/trpc/project.createProject`
* **Method:** `POST`
* **Query Params:** `?batch=1`
* **Payload:**
  ```json
  {
    "json": {
      "projectTitle": "BOSMAX Project 2026-05-23",
      "toolName": "PINHOLE"
    }
  }
  ```

### 2.2 Upload Reference Asset (INFERRED_FROM_CODE)
* **Endpoint:** `https://aisandbox-pa.googleapis.com/v1/flow/uploadImage`
* **Method:** `POST`
* **Headers:** Browser authorization cookies are automatically attached by Chrome.
* **Payload:** Form data containing base64 data stream.

### 2.3 Image Generation (INFERRED_FROM_CODE)
* **Endpoint:** `https://aisandbox-pa.googleapis.com/v1/projects/{project_id}/flowMedia:batchGenerateImages`
* **Method:** `POST`
* **Payload:**
  ```json
  {
    "clientContext": { ... },
    "requests": [
      {
        "clientContext": { ... },
        "seed": 9182,
        "structuredPrompt": {
          "parts": [{"text": "flask mockup, rotating"}]
        },
        "imageAspectRatio": "IMAGE_ASPECT_RATIO_PORTRAIT",
        "imageModelName": "veo_nano_banana_pro"
      }
    ]
  }
  ```

### 2.4 Video Generation (F2V) (INFERRED_FROM_CODE)
* **Endpoint:** `https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoStartImage`
* **Method:** `POST`
* **Payload:**
  ```json
  {
    "mediaGenerationContext": {
      "batchId": "6d37e3eb-a8f5-4ea4-ba01-d25514213d4c"
    },
    "clientContext": { ... },
    "requests": [
      {
        "aspectRatio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "seed": 8832,
        "textInput": {
          "structuredPrompt": {
            "parts": [{"text": "flask details, spin"}]
          }
        },
        "videoModelKey": "veo_3_1_lite_portrait",
        "startImage": {
          "mediaId": "upload-media-id-uuid-goes-here"
        }
      }
    ],
    "useV2ModelConfig": true
  }
  ```

---

## 3. Telemetry Schema (VERIFIED_LIVE)

The active FastAPI backend telemetry schema was verified live by querying the diagnostics export endpoints. The logs conform to the schema:

```json
{
  "request_id": "manual_7bf23aea",
  "status": "WAITING_FLOW",
  "queued_at": "2026-05-23T18:18:10",
  "last_heartbeat_at": "2026-05-23T18:18:10",
  "error_message": null,
  "stage_events": [
    {
      "timestamp": "2026-05-23T18:18:10",
      "stage": "MANUAL_SUBMIT_ACCEPTED",
      "status": "WAITING_FLOW",
      "message": "Operator workspace submitted manual Flow job."
    }
  ]
}
```

---

## 4. Gating and Paywall Observations (NOT VERIFIED)
No paywall, pricing blocks, or billing quota limitations were triggered during the DOM scanning session.
