"""Postiz publishing adapter — feature-flagged, fail-closed (official Public API only).

BOSMAX-generated artifacts (generated_artifact.local_path) are handed off to a
self-hosted Postiz instance so operators can draft/schedule/publish to their
connected social channels without manual re-upload.

Safety contract:
- POSTIZ_ENABLED=false (the default) → every entry point raises
  PostizConfigError("POSTIZ_DISABLED"); nothing else in BOSMAX changes.
- Missing base URL / API key fails CLOSED — never a silent manual-upload
  fallback.
- Default post type is `draft` unless POSTIZ_DEFAULT_POST_TYPE says otherwise.
- upload-from-url mode rejects non-HTTPS and private/localhost URLs
  (Postiz backend must be able to reach the URL publicly).
- Multiple channels per provider are first-class: integrations are a flat
  list keyed by integration id — never "the TikTok account".
- API key is never logged and never returned by any endpoint.
- No auto-retry on /upload or /posts (duplicate-post hazard); one retry on
  transient GET /integrations failures only.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_S = 60.0

# Self-hosted Postiz (docker) proxies the backend under /api — the Public API
# lives at {base}/api/public/v1. Postiz Cloud exposes it at
# https://api.postiz.com/public/v1 → set POSTIZ_API_PREFIX=/public/v1 there.
_DEFAULT_API_PREFIX = "/api/public/v1"

POST_TYPES = ("draft", "schedule", "now")

# MIME whitelist — Postiz upload accepts images and MP4 video.
ALLOWED_MEDIA_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
}


class PostizConfigError(ValueError):
    """Feature disabled or configuration missing — fail closed."""


class PostizValidationError(ValueError):
    """Input rejected before any network call."""


class PostizApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"POSTIZ_API_ERROR:{status_code}:{detail[:300]}")


# ── Config (read at call time so tests/operators can flip env live) ───────


def postiz_config() -> dict:
    return {
        "enabled": os.environ.get("POSTIZ_ENABLED", "false").strip().lower() == "true",
        "base_url": os.environ.get("POSTIZ_BASE_URL", "").strip().rstrip("/"),
        "api_key": os.environ.get("POSTIZ_API_KEY", "").strip(),
        "upload_mode": os.environ.get("POSTIZ_UPLOAD_MODE", "file").strip().lower(),
        "default_post_type": os.environ.get("POSTIZ_DEFAULT_POST_TYPE", "draft").strip().lower(),
        # Optional: public HTTPS base under which BOSMAX artifacts are exposed
        # (CDN/object storage). Required only for upload_mode=url.
        "public_media_base_url": os.environ.get("POSTIZ_PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/"),
        "api_prefix": os.environ.get("POSTIZ_API_PREFIX", _DEFAULT_API_PREFIX).strip().rstrip("/"),
    }


def ensure_enabled_and_configured() -> dict:
    """Fail-closed gate used by every adapter entry point."""
    cfg = postiz_config()
    if not cfg["enabled"]:
        raise PostizConfigError("POSTIZ_DISABLED")
    if not cfg["base_url"]:
        raise PostizConfigError("POSTIZ_BASE_URL_MISSING")
    if not cfg["api_key"]:
        raise PostizConfigError("POSTIZ_API_KEY_MISSING")
    if cfg["upload_mode"] not in ("file", "url"):
        raise PostizConfigError(f"POSTIZ_UPLOAD_MODE_INVALID:{cfg['upload_mode']}")
    if cfg["default_post_type"] not in POST_TYPES:
        raise PostizConfigError(f"POSTIZ_DEFAULT_POST_TYPE_INVALID:{cfg['default_post_type']}")
    return cfg


def health_summary() -> dict:
    """Safe status for the dashboard — never exposes the API key."""
    cfg = postiz_config()
    problems: list[str] = []
    if not cfg["enabled"]:
        problems.append("POSTIZ_DISABLED")
    if not cfg["base_url"]:
        problems.append("POSTIZ_BASE_URL_MISSING")
    if not cfg["api_key"]:
        problems.append("POSTIZ_API_KEY_MISSING")
    return {
        "enabled": cfg["enabled"],
        "base_url": cfg["base_url"] or None,
        "api_key_present": bool(cfg["api_key"]),
        "upload_mode": cfg["upload_mode"],
        "default_post_type": cfg["default_post_type"],
        "public_media_base_url": cfg["public_media_base_url"] or None,
        "ok": not problems,
        "problems": problems,
    }


# ── Input validation (no network) ─────────────────────────────────────────


def validate_media_file(local_path: str) -> str:
    """Return the MIME type for a local artifact file, or raise."""
    path = Path(str(local_path or ""))
    ext = path.suffix.lower()
    mime = ALLOWED_MEDIA_MIME.get(ext)
    if not mime:
        raise PostizValidationError(f"UNSUPPORTED_MEDIA_TYPE:{ext or 'NO_EXTENSION'}")
    if not path.is_file():
        raise PostizValidationError(f"MEDIA_FILE_NOT_FOUND:{path.name}")
    return mime


def validate_public_https_url(url: str) -> None:
    """upload-from-url law: public HTTPS only — Postiz must be able to fetch it."""
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        raise PostizValidationError("URL_MUST_BE_HTTPS")
    host = (parsed.hostname or "").lower()
    if not host:
        raise PostizValidationError("URL_HOST_MISSING")
    if host == "localhost" or host.endswith((".local", ".internal", ".lan")) or "." not in host:
        raise PostizValidationError(f"PRIVATE_URL_REJECTED:{host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # hostname, not an IP literal — fine
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    ):
        raise PostizValidationError(f"PRIVATE_URL_REJECTED:{host}")
    ext = Path(parsed.path).suffix.lower()
    if ext and ext not in ALLOWED_MEDIA_MIME:
        raise PostizValidationError(f"UNSUPPORTED_MEDIA_TYPE:{ext}")


# ── HTTP layer ────────────────────────────────────────────────────────────


def _headers(cfg: dict) -> dict:
    return {"Authorization": cfg["api_key"]}


async def _request(
    method: str,
    path: str,
    *,
    cfg: dict,
    json_body: dict | None = None,
    files: dict | None = None,
    retries: int = 0,
) -> Any:
    url = f"{cfg['base_url']}{cfg['api_prefix']}{path}"
    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
                resp = await client.request(
                    method, url, headers=_headers(cfg), json=json_body, files=files,
                )
            if resp.status_code >= 400:
                # Never echo headers/tokens; body only, truncated.
                raise PostizApiError(resp.status_code, resp.text)
            if not resp.content:
                return None
            try:
                return resp.json()
            except json.JSONDecodeError:
                return {"raw": resp.text[:500]}
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt < retries:
                attempt += 1
                logger.warning("Postiz %s %s transient failure (retry %d): %s",
                               method, path, attempt, type(exc).__name__)
                continue
            raise PostizApiError(0, f"TRANSPORT:{type(exc).__name__}")


# ── Channels ──────────────────────────────────────────────────────────────


async def list_integrations() -> list[dict]:
    """All connected Postiz channels. A provider may appear many times —
    one entry per connected account (multi-TikTok / multi-Page is normal)."""
    cfg = ensure_enabled_and_configured()
    data = await _request("GET", "/integrations", cfg=cfg, retries=1)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and isinstance(data.get("integrations"), list):
        rows = data["integrations"]
    else:
        # A wrong base URL / prefix (e.g. hitting the frontend) must NEVER
        # masquerade as "no channels connected" — fail loudly instead.
        raise PostizApiError(0, f"UNEXPECTED_INTEGRATIONS_RESPONSE:{str(data)[:200]}")
    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        normalized.append({
            "id": row.get("id"),
            "provider": row.get("identifier") or row.get("provider"),
            "name": row.get("name"),
            "picture": row.get("picture"),
            "disabled": bool(row.get("disabled", False)),
            "refresh_needed": bool(row.get("refreshNeeded") or row.get("refresh_needed") or False),
            "profile": row.get("profile"),
        })
    return normalized


# ── Media upload ──────────────────────────────────────────────────────────


async def upload_file(local_path: str) -> dict:
    """Multipart upload of a local BOSMAX artifact file → {id, path}."""
    cfg = ensure_enabled_and_configured()
    mime = validate_media_file(local_path)
    path = Path(local_path)
    with open(path, "rb") as fh:
        data = await _request(
            "POST", "/upload", cfg=cfg,
            files={"file": (path.name, fh, mime)},
        )
    return _normalize_media(data)


async def upload_from_url(url: str) -> dict:
    """Ask Postiz to fetch a public HTTPS URL → {id, path}."""
    cfg = ensure_enabled_and_configured()
    validate_public_https_url(url)
    data = await _request("POST", "/upload-from-url", cfg=cfg, json_body={"url": url})
    return _normalize_media(data)


def _normalize_media(data: Any) -> dict:
    row = data if isinstance(data, dict) else {}
    media = {"id": row.get("id"), "path": row.get("path")}
    if not media["id"]:
        raise PostizApiError(0, f"UPLOAD_RESPONSE_MISSING_ID:{str(row)[:200]}")
    return media


# ── Provider settings templates + operator warnings ──────────────────────

# Safe-by-default templates. TikTok defaults to SELF_ONLY because an
# unaudited TikTok app may force private visibility anyway — the operator
# must consciously widen it after their app passes TikTok's audit.
PROVIDER_SETTING_TEMPLATES: dict[str, dict] = {
    "tiktok": {
        "privacy_level": "SELF_ONLY",
        "duet": False,
        "stitch": False,
        "comment": False,
        "autoAddMusic": False,
        "brand_content_toggle": False,
        "brand_organic_toggle": False,
        "content_posting_method": "DIRECT_POST",
    },
    "facebook": {},
    "instagram": {"post_type": "post"},
    "youtube": {"title": "", "type": "private"},
    "x": {},
    "threads": {},
}

PROVIDER_WARNINGS: dict[str, list[str]] = {
    "tiktok": [
        "TikTok Direct Post requires a TikTok developer app with the Content Posting API, "
        "Direct Post enabled, HTTPS redirect URI and a VERIFIED media domain.",
        "Required scopes: user.info.basic, user.info.profile, video.create, video.publish, video.upload.",
        "UNAUDITED TikTok apps may be forced to SELF_ONLY/private visibility and rate-limited "
        "until the app passes TikTok's audit — do NOT assume public posting works before audit.",
        "Media URLs must be public HTTPS on a domain verified in the TikTok developer console.",
    ],
    "facebook": [
        "Meta app must be in LIVE mode (not development) for public visibility.",
        "Business permissions and Page authorization are required per Page.",
    ],
    "instagram": [
        "Standalone Instagram posting requires a PROFESSIONAL (business/creator) account.",
        "Meta app must be LIVE with the account authorized.",
    ],
    "youtube": [
        "YouTube uploads default to private here — switch type deliberately after verifying quota.",
    ],
    "x": ["X API tier limits apply per app."],
    "threads": ["Threads uses the Meta app — same LIVE-mode requirement."],
}


def provider_templates() -> dict:
    return {
        "templates": PROVIDER_SETTING_TEMPLATES,
        "warnings": PROVIDER_WARNINGS,
    }


# ── Post creation ─────────────────────────────────────────────────────────


def build_post_payload(
    *,
    post_type: str,
    integration_ids: list[str],
    media: list[dict],
    content: str = "",
    schedule_at: str | None = None,
    provider_settings: dict[str, dict] | None = None,
    integration_providers: dict[str, str] | None = None,
) -> dict:
    """Deterministic /posts payload. One asset → many integration ids,
    including several ids of the same provider. Never hardcodes channel ids."""
    ptype = (post_type or "").strip().lower()
    if ptype not in POST_TYPES:
        raise PostizValidationError(f"UNSUPPORTED_POST_TYPE:{post_type}")
    ids = [i for i in (integration_ids or []) if str(i or "").strip()]
    if not ids:
        raise PostizValidationError("NO_INTEGRATIONS_SELECTED")
    if len(set(ids)) != len(ids):
        raise PostizValidationError("DUPLICATE_INTEGRATION_IDS")
    if ptype == "schedule":
        if not schedule_at:
            raise PostizValidationError("SCHEDULE_AT_REQUIRED_FOR_SCHEDULE")
        date_iso = schedule_at
    else:
        date_iso = schedule_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    media_refs = [{"id": m["id"], "path": m.get("path")} for m in (media or [])]
    settings_by_id = provider_settings or {}
    providers_by_id = integration_providers or {}

    posts = []
    for iid in ids:
        provider = (providers_by_id.get(iid) or "").lower()
        settings = settings_by_id.get(iid)
        if settings is None:
            settings = dict(PROVIDER_SETTING_TEMPLATES.get(provider, {}))
        posts.append({
            "integration": {"id": iid},
            "value": [{"content": content or "", "image": media_refs}],
            "settings": settings,
        })

    return {
        "type": ptype,
        "date": date_iso,
        "shortLink": False,
        "posts": posts,
    }


async def create_post(payload: dict) -> Any:
    """Fire the /posts call. No auto-retry (duplicate-post hazard)."""
    cfg = ensure_enabled_and_configured()
    return await _request("POST", "/posts", cfg=cfg, json_body=payload)
