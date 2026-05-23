# Google Flow - Network Payload Map

This document catalogs the network communication, API schemas, endpoint mappings, and telemetry headers used by the BOSMAX Flow Kit to orchestrate video and image generations via the extension-to-agent bridge.

---

## 1. Request Context & Shared Schemas

### Client Context (`clientContext`)
Most Google Flow API requests require a `clientContext` object containing active project identification, paygate tier details, and reCAPTCHA tokens.

```json
{
  "projectId": "8ee700c9-9407-4cbe-8b29-b6d4db1c98ee",
  "recaptchaContext": {
    "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
    "token": "03AFcWeA7..." 
  },
  "sessionId": ";1684824823450",
  "tool": "PINHOLE",
  "userPaygateTier": "PAYGATE_TIER_TWO"
}
```

*Note: The reCAPTCHA token is solved asynchronously in the browser context via the extension before submitting the payload.*

---

## 2. Endpoint Catalog

All primary generation APIs are hosted under:
`https://aisandbox-pa.googleapis.com`

An API Key parameter `?key=AIzaSyBt...` is appended to every query path.

### 2.1 Project Creation (tRPC)
* **Endpoint:** `https://labs.google/fx/api/trpc/project.createProject`
* **Method:** `POST`
* **Content-Type:** `application/json`
* **Payload:**
  ```json
  {
    "json": {
      "projectTitle": "BOSMAX Project 2026-05",
      "toolName": "PINHOLE"
    }
  }
  ```
* **Success Response:**
  ```json
  {
    "result": {
      "data": {
        "json": {
          "projectId": "8ee700c9-9407-4cbe-8b29-b6d4db1c98ee"
        }
      }
    }
  }
  ```

### 2.2 Upload Reference Image
* **Endpoint:** `/v1/flow/uploadImage`
* **Method:** `POST`
* **Payload:** Contains binary image stream or base64 multipart upload form data.
* **Success Response:**
  ```json
  {
    "name": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "mediaUri": "https://storage.googleapis.com/..."
  }
  ```

### 2.3 Batch Generate Images (Text-to-Image / Image Edit)
* **Endpoint:** `/v1/projects/{project_id}/flowMedia:batchGenerateImages`
* **Method:** `POST`
* **Payload:**
  ```json
  {
    "clientContext": { ... },
    "requests": [
      {
        "clientContext": { ... },
        "seed": 823451,
        "structuredPrompt": {
          "parts": [{"text": "Sleek metallic vacuum flask close-up"}]
        },
        "imageAspectRatio": "IMAGE_ASPECT_RATIO_PORTRAIT",
        "imageModelName": "veo_nano_banana_pro",
        "imageInputs": [] 
      }
    ]
  }
  ```
* *Note: When acting as an edit or consistent character workflow, `imageInputs` is populated with `IMAGE_INPUT_TYPE_REFERENCE` objects containing the uploaded reference image `mediaId` values.*

### 2.4 Async Video Generation (Frames to Video)
* **Endpoint:** `/v1/video:batchAsyncGenerateVideoStartImage`
* **Method:** `POST`
* **Payload:**
  ```json
  {
    "mediaGenerationContext": {
      "batchId": "c4d5e6f7-a8b9..."
    },
    "clientContext": { ... },
    "requests": [
      {
        "aspectRatio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "seed": 4512,
        "textInput": {
          "structuredPrompt": {
            "parts": [{"text": "cinematic transition, flask rotating"}]
          }
        },
        "videoModelKey": "veo_3_1_lite_portrait",
        "startImage": {
          "mediaId": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
        },
        "metadata": {
          "sceneId": "scene_001"
        }
      }
    ],
    "useV2ModelConfig": true
  }
  ```

### 2.5 Video Status Check
* **Endpoint:** `/v1/video:batchCheckAsyncVideoGenerationStatus`
* **Method:** `POST`
* **Payload:**
  ```json
  {
    "operations": [
      {
        "name": "operations/video/g1h2i3j4-k5l6..."
      }
    ]
  }
  ```
* **Success Response (Generating):**
  ```json
  {
    "operations": [
      {
        "name": "operations/video/g1h2i3j4-k5l6...",
        "done": false
      }
    ]
  }
  ```
* **Success Response (Completed):**
  ```json
  {
    "operations": [
      {
        "name": "operations/video/g1h2i3j4-k5l6...",
        "done": true,
        "response": {
          "media": [
            {
              "name": "v9w8x7y6-z5a4...",
              "mediaUri": "https://storage.googleapis.com/..."
            }
          ]
        }
      }
    ]
  }
  ```

---

## 3. Failure Response and Error States

### 3.1 Rate Limit / Quota Exceeded (HTTP 429)
* **Response Body:**
  ```json
  {
    "error": {
      "code": 429,
      "message": "Resource has been exhausted (e.g. queries per minute limits reached).",
      "status": "RESOURCE_EXHAUSTED"
    }
  }
  ```
* **Handled State:** The orchestrator halts queue processing and enforces a backoff delay.

### 3.2 Paywall / Insufficient Tier Gate (HTTP 403)
* **Response Body:**
  ```json
  {
    "error": {
      "code": 403,
      "message": "Operation not allowed. Upgrade to Tier Two for Veo Quality models.",
      "status": "PERMISSION_DENIED",
      "details": [
        {
          "reason": "PAYGATE_RESTRICTION",
          "requiredTier": "PAYGATE_TIER_TWO"
        }
      ]
    }
  }
  ```
* **Handled State:** Fallback to standard Veo Lite models if allowed, or abort with explicit error notification.

### 3.3 Expired / Missing Captcha (HTTP 400)
* **Response Body:**
  ```json
  {
    "error": {
      "code": 400,
      "message": "Verification failed: reCAPTCHA token missing or expired.",
      "status": "INVALID_ARGUMENT"
    }
  }
  ```
* **Handled State:** Suppress execution, request a fresh token via the extension solver, and resubmit.
