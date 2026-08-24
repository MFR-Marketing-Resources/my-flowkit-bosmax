"""
Flow Client — communicates with Google Flow API via Chrome extension WebSocket bridge.

Agent runs a WS server. Extension connects as client. Agent sends API requests,
extension executes them in browser context (residential IP, cookies, reCAPTCHA).
"""
import asyncio
import contextvars
import json
import logging
import secrets
import time
import uuid
from contextlib import contextmanager
from typing import Optional
from urllib.parse import quote

from agent.config import (
    GOOGLE_FLOW_API, GOOGLE_API_KEY, ENDPOINTS,
    VIDEO_MODELS, UPSCALE_MODELS, IMAGE_MODELS, VIDEO_POLL_TIMEOUT,
    EXTEND_VIDEO_MODELS,
)
from agent.services.headers import random_headers

logger = logging.getLogger(__name__)


def resolve_image_model_name(model: str | None) -> str:
    """Map an image-model key OR ui_label (e.g. "NANO_BANANA_2" / "Nano Banana 2")
    to Google Flow's internal imageModelName from models.json.

    Defaults to Nano Banana Pro (today's hardcoded behaviour). Fails CLOSED on an
    unknown model, or on an alias whose internal id is not yet configured
    (e.g. Nano Banana 2 Lite before its id is captured) — it NEVER silently
    substitutes a different model, so a picker can offer 2 Lite honestly.
    """
    key = (model or "NANO_BANANA_PRO").strip().upper().replace(" ", "_").replace("-", "_")
    value = IMAGE_MODELS.get(key)
    if value is None:
        raise ValueError(
            f"ERR_UNKNOWN_IMAGE_MODEL: {model!r} (known: {', '.join(IMAGE_MODELS)})"
        )
    if not str(value).strip() or "PENDING" in str(value).upper():
        raise ValueError(
            f"ERR_IMAGE_MODEL_ALIAS_PENDING: {key} internal id not set in models.json"
        )
    return value


# ADR-007: the canonical production modes generate API-first only; the extension
# DOM-clicking generation lane is DEAD for them. execute_flow_job() refuses to
# dispatch any of these over the bridge (source modes HYBRID/FRAMES/INGREDIENTS
# map to transport F2V/F2V/I2V and are refused under either label).
_CANONICAL_DOM_FORBIDDEN_MODES = frozenset(
    {"IMG", "T2V", "I2V", "F2V", "HYBRID", "FRAMES", "INGREDIENTS"}
)


def resolve_video_model_key(user_paygate_tier: str, gen_type: str, aspect_ratio: str,
                            override: str | None = None) -> str | None:
    """SSOT videoModelKey resolution for the direct batchAsync video RPCs.

    An explicitly captured key (``override``) wins; otherwise the captured
    models.json slot for (tier, gen_type, aspect) applies. Returns None when no
    captured key exists — callers FAIL CLOSED on None and never guess a key.
    """
    if override and str(override).strip():
        return str(override).strip()
    return VIDEO_MODELS.get(user_paygate_tier, {}).get(gen_type, {}).get(aspect_ratio)


class FlowClient:
    """Sends commands to Chrome extension via WebSocket."""

    def __init__(self):
        # `_extension_ws` remains a read-only compatibility mirror for older
        # tests/callers.  Transport selection is owned by `_connections` and is
        # never last-connected-wins: the mirror is populated only while exactly
        # one connection exists.
        self._extension_ws = None
        self._connections: dict[str, dict] = {}
        self._connection_epoch = 0
        self._compatibility_connection_id: Optional[str] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_owners: dict[str, str] = {}
        self._operation_leases: dict[str, dict] = {}
        self._active_operation_lease_id = contextvars.ContextVar(
            f"flow_operation_lease_{id(self)}",
            default=None,
        )
        self._flow_key: Optional[str] = None
        # Flow's current project payload exposes both the DOM media UUID and a
        # separate mediaGenerationId/clipId.  Keep the mapping learned by the
        # authenticated extension harvest so /v1/media receives the generation
        # key, not the delivery-tile UUID.
        self._media_generation_ids: dict[str, str] = {}
        # WS stats
        self._ws_connect_count = 0
        self._ws_disconnect_count = 0
        self._ws_connected_at: Optional[float] = None
        self._ws_last_disconnect_at: Optional[float] = None
        self.last_state = "OFFLINE"

    def _connection_record(self, connection) -> Optional[dict]:
        """Return the live registry record for an id or exact WebSocket."""
        if isinstance(connection, dict):
            connection = connection.get("connection_id")
        if isinstance(connection, str):
            return self._connections.get(connection)
        for record in self._connections.values():
            if record.get("websocket") is connection:
                return record
        return None

    def register_extension_connection(
        self,
        websocket,
        *,
        connection_id: str | None = None,
        callback_secret: str | None = None,
        installation_id: str | None = None,
        extension_session_id: str | None = None,
        metadata: dict | None = None,
        synthetic: bool = False,
    ) -> str:
        """Register one server-owned bridge connection without replacing peers."""
        existing = self._connection_record(websocket)
        if existing is not None:
            return str(existing["connection_id"])

        connection_id = str(connection_id or uuid.uuid4()).strip()
        if not connection_id or connection_id in self._connections:
            raise ValueError("ERR_EXTENSION_CONNECTION_ID_CONFLICT")
        callback_secret = str(callback_secret or secrets.token_urlsafe(32))
        if any(
            secrets.compare_digest(
                callback_secret,
                str(record.get("callback_secret") or ""),
            )
            for record in self._connections.values()
        ):
            raise ValueError("ERR_EXTENSION_CALLBACK_SECRET_CONFLICT")
        self._connection_epoch += 1
        now = time.time()
        self._connections[connection_id] = {
            "connection_id": connection_id,
            "connection_epoch": self._connection_epoch,
            "websocket": websocket,
            "callback_secret": callback_secret,
            "installation_id": str(installation_id or "").strip() or None,
            "extension_session_id": str(extension_session_id or "").strip() or None,
            "connected_at": now,
            "ready": False,
            "flow_key": None,
            "metadata": dict(metadata or {}),
            "synthetic": bool(synthetic),
        }
        self._ws_connect_count += 1
        self._ws_connected_at = min(
            float(record["connected_at"]) for record in self._connections.values()
        )
        self._extension_ws = (
            websocket if len(self._connections) == 1 else None
        )
        if len(self._connections) != 1:
            self._flow_key = None
        logger.info(
            "Extension connection registered id=%s epoch=%d active=%d",
            connection_id,
            self._connection_epoch,
            len(self._connections),
        )
        return connection_id

    def unregister_extension_connection(self, connection_id: str, *, websocket=None) -> bool:
        """Remove one exact connection and fail only requests owned by it."""
        record = self._connections.get(str(connection_id))
        if record is None or (
            websocket is not None and record.get("websocket") is not websocket
        ):
            return False

        self._connections.pop(str(connection_id), None)
        self._ws_disconnect_count += 1
        self._ws_last_disconnect_at = time.time()
        owned_request_ids = [
            request_id
            for request_id, owner_id in self._pending_owners.items()
            if owner_id == str(connection_id)
        ]
        for request_id in owned_request_ids:
            future = self._pending.get(request_id)
            if future is not None and not future.done():
                future.set_exception(ConnectionError("ERR_EXTENSION_CONNECTION_CLOSED"))
            self._pending_owners.pop(request_id, None)

        if self._compatibility_connection_id == str(connection_id):
            self._compatibility_connection_id = None
        if len(self._connections) == 1:
            remaining = next(iter(self._connections.values()))
            self._extension_ws = remaining.get("websocket")
            self._flow_key = remaining.get("flow_key")
            self._ws_connected_at = float(remaining["connected_at"])
        else:
            self._extension_ws = None
            self._flow_key = None
            self._ws_connected_at = None
        logger.warning(
            "Extension connection unregistered id=%s failed_pending=%d active=%d",
            connection_id,
            len(owned_request_ids),
            len(self._connections),
        )
        return True

    def set_extension(self, ws):
        """Compatibility wrapper that registers one synthetic connection."""
        existing = self._connection_record(ws)
        if existing is not None:
            return str(existing["connection_id"])
        if (
            self._compatibility_connection_id
            and self._connection_record(self._compatibility_connection_id) is not None
        ):
            raise RuntimeError("ERR_EXTENSION_CONNECTION_AMBIGUOUS")
        connection_id = self.register_extension_connection(ws, synthetic=True)
        self._compatibility_connection_id = connection_id
        return connection_id

    def clear_extension(self):
        """Clean up only the synthetic connection created by set_extension()."""
        connection_id = self._compatibility_connection_id
        record = self._connection_record(connection_id) if connection_id else None
        if record is None or record.get("synthetic") is not True:
            # Preserve direct-assignment cleanup used by old disconnected tests,
            # but never mutate real registry records or their pending work.
            if not self._connections:
                self._extension_ws = None
            return False
        return self.unregister_extension_connection(
            connection_id,
            websocket=record.get("websocket"),
        )

    def _select_connection(
        self,
        *,
        connection_id: str | None = None,
        installation_id: str | None = None,
        extension_session_id: str | None = None,
    ) -> dict:
        lease_id = self._active_operation_lease_id.get()
        if lease_id:
            lease = self._operation_leases.get(str(lease_id))
            if lease is None or lease.get("released") is True:
                raise ConnectionError("ERR_OPERATION_LEASE_NOT_ACTIVE")
            record = self._connections.get(str(lease.get("connection_id") or ""))
            if (
                record is None
                or record.get("connection_epoch") != lease.get("connection_epoch")
            ):
                raise ConnectionError("ERR_EXTENSION_CONNECTION_CLOSED")
            for key in ("installation_id", "extension_session_id"):
                expected = lease.get(key)
                if expected and record.get(key) != expected:
                    raise ConnectionError("ERR_OPERATION_LEASE_IDENTITY_MISMATCH")
            if connection_id and record.get("connection_id") != str(connection_id):
                raise ConnectionError("ERR_OPERATION_LEASE_CONNECTION_MISMATCH")
            if (
                installation_id
                and record.get("installation_id") != str(installation_id)
            ):
                raise ConnectionError("ERR_OPERATION_LEASE_IDENTITY_MISMATCH")
            if (
                extension_session_id
                and record.get("extension_session_id") != str(extension_session_id)
            ):
                raise ConnectionError("ERR_OPERATION_LEASE_IDENTITY_MISMATCH")
            return record

        candidates = list(self._connections.values())
        if connection_id is not None:
            candidates = [
                record for record in candidates
                if record.get("connection_id") == str(connection_id)
            ]
        if installation_id is not None:
            candidates = [
                record for record in candidates
                if record.get("installation_id") == str(installation_id)
            ]
        if extension_session_id is not None:
            candidates = [
                record for record in candidates
                if record.get("extension_session_id") == str(extension_session_id)
            ]
        if not candidates:
            if connection_id or installation_id or extension_session_id:
                raise ConnectionError("ERR_EXTENSION_CONNECTION_NOT_FOUND")
            raise ConnectionError("Extension not connected")
        if len(candidates) != 1:
            raise ConnectionError("ERR_EXTENSION_CONNECTION_AMBIGUOUS")
        return candidates[0]

    def acquire_operation_lease(
        self,
        *,
        connection_id: str | None = None,
        installation_id: str | None = None,
        extension_session_id: str | None = None,
    ) -> dict:
        """Snapshot one exact connection for a logical provider operation."""
        record = self._select_connection(
            connection_id=connection_id,
            installation_id=installation_id,
            extension_session_id=extension_session_id,
        )
        lease_id = str(uuid.uuid4())
        lease = {
            "lease_id": lease_id,
            "connection_id": record["connection_id"],
            "connection_epoch": record["connection_epoch"],
            "installation_id": record.get("installation_id"),
            "extension_session_id": record.get("extension_session_id"),
            "acquired_at": time.time(),
            "released": False,
        }
        self._operation_leases[lease_id] = lease
        return dict(lease)

    @contextmanager
    def activate_operation_lease(self, lease):
        lease_id = str(
            lease.get("lease_id") if isinstance(lease, dict) else lease or ""
        )
        record = self._operation_leases.get(lease_id)
        if record is None or record.get("released") is True:
            raise ConnectionError("ERR_OPERATION_LEASE_NOT_ACTIVE")
        token = self._active_operation_lease_id.set(lease_id)
        try:
            yield dict(record)
        finally:
            self._active_operation_lease_id.reset(token)

    def bind_operation_lease(self, lease, **bindings) -> dict:
        """Bind immutable tab/project/build facts to an acquired lease."""
        lease_id = str(
            lease.get("lease_id") if isinstance(lease, dict) else lease or ""
        )
        record = self._operation_leases.get(lease_id)
        if record is None or record.get("released") is True:
            raise ConnectionError("ERR_OPERATION_LEASE_NOT_ACTIVE")
        allowed = {
            "connection_id",
            "connection_epoch",
            "installation_id",
            "extension_session_id",
            "extension_build",
            "flow_tab_id",
            "flow_url",
            "flow_project_id",
        }
        for key, value in bindings.items():
            if key not in allowed or value is None:
                continue
            current = record.get(key)
            if current is not None and current != value:
                raise ValueError(f"ERR_OPERATION_LEASE_BINDING_MISMATCH:{key}")
            record[key] = value
        return dict(record)

    def release_operation_lease(self, lease) -> bool:
        lease_id = str(
            lease.get("lease_id") if isinstance(lease, dict) else lease or ""
        )
        record = self._operation_leases.pop(lease_id, None)
        if record is None or record.get("released") is True:
            return False
        return True

    def set_flow_key(self, key: str):
        self._flow_key = key

    @property
    def connected(self) -> bool:
        return bool(self._connections) or getattr(self, "_mock_connected", False)

    @property
    def ws_stats(self) -> dict:
        uptime = None
        if self._ws_connected_at and self.connected:
            uptime = int(time.time() - self._ws_connected_at)
        return {
            "connected": self.connected,
            "connects": self._ws_connect_count,
            "disconnects": self._ws_disconnect_count,
            "uptime_s": uptime,
            "connections": len(self._connections),
            "ambiguous": len(self._connections) > 1,
        }

    async def handle_message(self, data: dict, *, connection_id: str | None = None):
        """Handle incoming message from extension."""
        try:
            record = (
                self._connection_record(connection_id)
                if connection_id is not None
                else self._select_connection()
            )
        except ConnectionError as exc:
            logger.warning("Rejected unowned extension message: %s", exc)
            return False
        if record is None:
            return False

        source_connection_id = str(record["connection_id"])

        if data.get("type") == "token_captured":
            record["flow_key"] = data.get("flowKey")
            if len(self._connections) == 1:
                self._flow_key = record.get("flow_key")
            logger.info("Flow key captured from extension connection %s", source_connection_id)
            lease = self.acquire_operation_lease(connection_id=source_connection_id)

            async def _sync_token_owner():
                try:
                    with self.activate_operation_lease(lease):
                        await self._sync_tier()
                finally:
                    self.release_operation_lease(lease)

            asyncio.create_task(_sync_token_owner())
            return True

        if data.get("type") == "extension_ready":
            reported_connection_id = str(data.get("connection_id") or "").strip()
            identity_updates = {
                key: data.get(key)
                for key in (
                    "installation_id",
                    "extension_session_id",
                    "extension_build",
                    "extension_id",
                    "build_sha",
                )
                if data.get(key) is not None and str(data.get(key)).strip()
            }
            identity_conflict = bool(
                reported_connection_id
                and reported_connection_id != source_connection_id
            ) or any(
                record.get(key) is not None and record.get(key) != value
                for key, value in identity_updates.items()
            )
            if identity_conflict:
                logger.error(
                    "Extension identity changed on live connection %s; closing owner",
                    source_connection_id,
                )
                self.unregister_extension_connection(
                    source_connection_id,
                    websocket=record.get("websocket"),
                )
                return False
            record["ready"] = True
            record.update(identity_updates)
            logger.info(
                "Extension ready connection=%s flowKey=%s",
                source_connection_id,
                "yes" if data.get("flowKeyPresent") else "no",
            )
            lease = self.acquire_operation_lease(connection_id=source_connection_id)

            async def _sync_ready_owner():
                try:
                    with self.activate_operation_lease(lease):
                        await self._sync_tier()
                finally:
                    self.release_operation_lease(lease)

            asyncio.create_task(_sync_ready_owner())
            return True

        if data.get("type") == "media_urls_refresh":
            self._remember_media_generation_ids({
                "result": {"diag": {
                    "mediaGenerationIds": data.get("mediaGenerationIds", {})
                }}
            })
            for entry in data.get("urls", []) or []:
                if isinstance(entry, dict) and entry.get("mediaGenerationId"):
                    entry_media_id = str(entry.get("mediaId") or "").strip()
                    if entry_media_id:
                        self._media_generation_ids[entry_media_id] = str(
                            entry["mediaGenerationId"]
                        ).strip()
            asyncio.create_task(self._refresh_media_urls(data.get("urls", [])))
            return True

        if data.get("type") == "pong":
            return True

        if data.get("type") == "ping":
            # Respond to keepalive
            websocket = record.get("websocket")
            if websocket:
                await websocket.send(json.dumps({"type": "pong"}))
            return True

        # Response to a pending request
        req_id = data.get("id")
        if req_id and req_id in self._pending:
            if self._pending_owners.get(req_id) != source_connection_id:
                logger.warning(
                    "Rejected cross-connection response id=%s source=%s owner=%s",
                    str(req_id)[:8],
                    source_connection_id,
                    self._pending_owners.get(req_id),
                )
                return False
            if not self._pending[req_id].done():
                self._pending[req_id].set_result(data)
            return True
        return False

    async def _sync_tier(self):
        """Detect current tier from credits API and update all active projects."""
        if getattr(self, '_sync_in_progress', False):
            return
        self._sync_in_progress = True
        try:
            result = await self.get_credits()
            data = result.get("data", result)
            tier = data.get("userPaygateTier", "PAYGATE_TIER_ONE")

            def _tier_owner_is_current() -> bool:
                lease_id = self._active_operation_lease_id.get()
                lease = self._operation_leases.get(str(lease_id or ""))
                try:
                    owner = self._select_connection() if lease is not None else None
                except ConnectionError:
                    owner = None
                return bool(
                    lease is not None
                    and lease.get("released") is not True
                    and owner is not None
                    and len(self._connections) == 1
                    and owner.get("connection_id") == lease.get("connection_id")
                    and owner.get("connection_epoch") == lease.get("connection_epoch")
                )

            if not _tier_owner_is_current():
                logger.warning(
                    "Skipped global tier sync without one live leased connection"
                )
                return
            logger.info("Syncing tier: %s", tier)

            from agent.db import crud
            projects = await crud.list_projects(status="ACTIVE")
            if not _tier_owner_is_current():
                logger.warning(
                    "Aborted global tier sync after bridge ownership changed"
                )
                return
            for p in projects:
                if p.get("user_paygate_tier") != tier:
                    if not _tier_owner_is_current():
                        logger.warning(
                            "Aborted global tier update after bridge ownership changed"
                        )
                        return
                    await crud.update_project(p["id"], user_paygate_tier=tier)
                    logger.info("Updated project %s tier: %s -> %s",
                                p["id"][:12], p.get("user_paygate_tier"), tier)
        except Exception as e:
            logger.warning("Failed to sync tier: %s", e)
        finally:
            self._sync_in_progress = False

    _UUID_RE = __import__("re").compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    _SAFE_URL_RE = __import__("re").compile(
        r'^https://(?:storage\.googleapis\.com|lh3\.googleusercontent\.com|'
        r'(?:[a-z0-9-]+\.)?flow-content\.google)/', __import__("re").I)

    async def _refresh_media_urls(self, urls: list[dict]):
        """Update scene/character URLs in DB from fresh TRPC-captured signed URLs.

        Each entry: {mediaId: str, mediaType: 'image'|'video', url: str}
        """
        from agent.db import crud
        from agent.services.event_bus import event_bus

        updated = 0
        for entry in urls:
            media_id = entry.get("mediaId", "")
            media_type = entry.get("mediaType", "")
            url = entry.get("url", "")
            if not media_id or not url:
                continue
            # Validate media_id is UUID and url is from trusted domains
            if not self._UUID_RE.match(media_id):
                logger.warning("Rejected invalid media_id: %s", media_id[:20])
                continue
            if not self._SAFE_URL_RE.match(url):
                logger.warning("Rejected untrusted URL domain for media %s", media_id[:12])
                continue
            if media_type not in ("image", "video"):
                continue

            # Try matching against scenes (check both orientations)
            scenes = await crud.list_scenes_by_media_id(media_id)
            for scene in scenes:
                updates = {}
                if media_type == "image":
                    # Update whichever orientation matches
                    if scene.get("vertical_image_media_id") == media_id:
                        updates["vertical_image_url"] = url
                    if scene.get("horizontal_image_media_id") == media_id:
                        updates["horizontal_image_url"] = url
                elif media_type == "video":
                    if scene.get("vertical_video_media_id") == media_id:
                        updates["vertical_video_url"] = url
                    if scene.get("horizontal_video_media_id") == media_id:
                        updates["horizontal_video_url"] = url
                    if scene.get("vertical_upscale_media_id") == media_id:
                        updates["vertical_upscale_url"] = url
                    if scene.get("horizontal_upscale_media_id") == media_id:
                        updates["horizontal_upscale_url"] = url
                if updates:
                    await crud.update_scene(scene["id"], **updates)
                    updated += 1

            # Try matching against characters
            chars = await crud.list_characters_by_media_id(media_id)
            for char in chars:
                if media_type == "image" and char.get("media_id") == media_id:
                    await crud.update_character(char["id"], reference_image_url=url)
                    updated += 1

        if updated:
            logger.info("Refreshed %d media URLs from TRPC intercept", updated)
            await event_bus.emit("urls_refreshed", {"count": updated})

    async def refresh_project_urls(self, project_id: str) -> dict:
        """Refresh media URLs for a project.

        Note: Google Flow's get_media API returns encoded content (base64),
        not fresh signed URLs. URL refresh requires TRPC intercept from
        the extension when the user opens the project in Chrome.
        The video reviewer falls back to get_media content directly.
        """
        logger.info("URL refresh requested for project %s — TRPC endpoint no longer available, "
                     "use extension passive intercept (open project in Chrome)", project_id[:12])
        return {"refreshed": 0, "found": 0, "note": "TRPC endpoint unavailable. "
                "Video reviewer uses get_media fallback automatically. "
                "For URL refresh, open the project in Google Flow in Chrome."}

    async def _send(self, method: str, params: dict, timeout: float = 300) -> dict:
        """Send request to extension and wait for response.

        Always returns a dict. On error, returns {"error": "<reason>"} — callers
        must check result.get("error") or use _is_ws_error() before reading data.
        Never raises; exceptions are caught and returned as error dicts.
        """
        # Final Prompt Approval Gate — exhaustive provider-boundary backstop.
        # captchaAction VIDEO_GENERATION marks exactly the 4 credit-bearing video
        # methods (generate_video / _from_references / upscale_video /
        # generate_video_extend); image/chat/concat use another or no action. No
        # credit-bearing video dispatch may cross this boundary without an
        # authorised dispatch. Non-raising (honours the never-raise contract),
        # inert unless EXECUTION_APPROVAL_GATE_ENFORCED.
        if isinstance(params, dict) and params.get("captchaAction") == "VIDEO_GENERATION":
            from agent.services import execution_approval_service as _eas
            _gate_block = _eas.video_dispatch_unauthorized_reason(
                method=str(params.get("url") or "video_generation"))
            if _gate_block:
                return {"error": _gate_block,
                        "detail": "Credit-bearing video generation blocked: no "
                                  "authorised dispatch (Final Prompt Approval Gate)."}
        if not self._connections:
            if getattr(self, "_mock_connected", False):
                req_id = str(uuid.uuid4())
                url = (params or {}).get("url") or ""
                url_lower = url.lower()
                
                # Project creation
                if "project.createproject" in url_lower or method == "trpc_request":
                    pid = f"proj_{req_id[:8]}"
                    return {
                        "status": 200,
                        "projectId": pid,
                        "data": {"projectId": pid},
                        "result": {"data": {"json": {"projectId": pid}}}
                    }
                
                # Image upload
                if "uploadimage" in url_lower or "upload_image" in url_lower or method == "upload_image":
                    mid = f"projects/flow-prod/locations/us-central1/media/ref_{req_id[:8]}"
                    return {
                        "status": 200,
                        "_mediaId": mid,
                        "data": {"media": {"name": mid}}
                    }
                
                # Image generation
                if "generate_images" in url_lower or "generateimages" in url_lower:
                    mid = f"projects/flow-prod/locations/us-central1/media/gen_{req_id[:8]}"
                    # Ensure mock JPG exists on disk
                    from agent.config import OUTPUT_DIR
                    retrieved_dir = OUTPUT_DIR / "retrieved"
                    retrieved_dir.mkdir(parents=True, exist_ok=True)
                    out_jpg = retrieved_dir / f"gen_{req_id[:8]}.jpg"
                    if not out_jpg.exists():
                        # Copy MWCB canonical image as mock generated image
                        import shutil
                        from pathlib import Path
                        canonical_src = r"C:\Users\USER\Desktop\Claude Cowork Bosmax Agents- Images database\02-Product\02-Minyak Cap Burung\MWTCB.jpg"
                        if Path(canonical_src).exists():
                            shutil.copy(canonical_src, out_jpg)
                        else:
                            out_jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x10\x00\x10\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9")
                    return {
                        "status": 200,
                        "data": {
                            "images": [{
                                "name": mid,
                                "mediaId": f"gen_{req_id[:8]}",
                                "fifeUrl": f"http://localhost:8100/api/flow/retrieved/gen_{req_id[:8]}",
                                "servingUri": f"http://localhost:8100/api/flow/retrieved/gen_{req_id[:8]}"
                            }]
                        }
                    }
                
                # Default API response fallback
                return {
                    "status": 200,
                    "data": {
                        "jobId": f"g_uat_job_{req_id[:8]}",
                        "userPaygateTier": "PAYGATE_TIER_ONE",
                        "credits": 100
                    }
                }
            return {"error": "Extension not connected"}

        try:
            connection = self._select_connection()
        except ConnectionError as exc:
            error = str(exc)
            if error == "ERR_EXTENSION_CONNECTION_AMBIGUOUS":
                return {
                    "error": error,
                    "connection_count": len(self._connections),
                }
            return {"error": error}
        return await self._send_on_connection(
            connection,
            method,
            params,
            timeout=timeout,
            _approval_checked=True,
        )

    async def _send_on_connection(
        self,
        connection,
        method: str,
        params: dict,
        timeout: float = 300,
        *,
        _approval_checked: bool = False,
    ) -> dict:
        """Send once through one captured registry record and own its response."""
        if (
            not _approval_checked
            and isinstance(params, dict)
            and params.get("captchaAction") == "VIDEO_GENERATION"
        ):
            from agent.services import execution_approval_service as _eas
            gate_block = _eas.video_dispatch_unauthorized_reason(
                method=str(params.get("url") or "video_generation")
            )
            if gate_block:
                return {
                    "error": gate_block,
                    "detail": (
                        "Credit-bearing video generation blocked: no authorised "
                        "dispatch (Final Prompt Approval Gate)."
                    ),
                }

        record = self._connection_record(connection)
        if record is None:
            return {"error": "ERR_EXTENSION_CONNECTION_CLOSED"}
        connection_id = str(record["connection_id"])
        connection_epoch = record["connection_epoch"]
        websocket = record.get("websocket")
        if websocket is None:
            return {"error": "ERR_EXTENSION_CONNECTION_CLOSED"}

        req_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        self._pending_owners[req_id] = connection_id

        try:
            current = self._connections.get(connection_id)
            if (
                current is None
                or current.get("connection_epoch") != connection_epoch
                or current.get("websocket") is not websocket
            ):
                return {"error": "ERR_EXTENSION_CONNECTION_CLOSED"}
            await websocket.send(json.dumps({
                "id": req_id,
                "method": method,
                "params": params,
            }))
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return {"error": f"Timeout ({timeout}s) waiting for {method}"}
        except Exception as e:
            return {"error": str(e)}
        finally:
            self._pending.pop(req_id, None)
            self._pending_owners.pop(req_id, None)

    def resolve_extension_callback(self, callback_secret: str, data: dict | None) -> dict:
        """Authenticate and resolve an HTTP callback for its owning connection."""
        supplied_secret = str(callback_secret or "")
        matched = None
        for record in self._connections.values():
            if supplied_secret and secrets.compare_digest(
                supplied_secret,
                str(record.get("callback_secret") or ""),
            ):
                matched = record
        if matched is None:
            return {
                "authenticated": False,
                "resolved": False,
                "reason": "callback_authentication_required",
            }

        request_id = data.get("id") if isinstance(data, dict) else None
        if not request_id or request_id not in self._pending:
            return {
                "authenticated": True,
                "resolved": False,
                "reason": "no_matching_pending_request",
                "connection_id": matched["connection_id"],
            }
        if self._pending_owners.get(request_id) != matched["connection_id"]:
            return {
                "authenticated": True,
                "resolved": False,
                "reason": "request_owner_mismatch",
                "connection_id": matched["connection_id"],
            }
        future = self._pending[request_id]
        if future.done():
            return {
                "authenticated": True,
                "resolved": False,
                "reason": "request_already_resolved",
                "connection_id": matched["connection_id"],
            }
        future.set_result(data)
        return {
            "authenticated": True,
            "resolved": True,
            "connection_id": matched["connection_id"],
        }

    def _build_url(self, endpoint_key: str, **kwargs) -> str:
        """Build full API URL."""
        path = ENDPOINTS[endpoint_key].format(**kwargs)
        sep = "&" if "?" in path else "?"
        return f"{GOOGLE_FLOW_API}{path}{sep}key={GOOGLE_API_KEY}"

    async def execute_flow_job(self, job_data: dict) -> dict:
        """Trigger DOM automation in the extension for a generation job."""
        # ADR-007 defense-in-depth (SEV-0 runtime-skew closure): canonical
        # production modes generate API-first only; the DOM lane is dead for
        # them. Refuse to dispatch one over the bridge even when a backend caller
        # reaches here directly (durable SDK visual-feedback in
        # agent/sdk/services/operations.py; batch execute-variant in
        # agent/services/batch_executor.py) — so a stale/absent extension guard
        # during a restart window can never let a canonical job run the dead
        # lane. Returns the same error-dict shape those callers already handle
        # (report.get("error")). Non-generating smoke probes use
        # smoke_execute_flow_job (a separate method) and are unaffected.
        _jd = job_data or {}
        # OR-logic across mode AND source_mode (matches the extension predicates):
        # catch a canonical value under EITHER field, not just the first present.
        _canonical = next(
            (
                m
                for m in (str(_jd.get(k) or "").strip().upper() for k in ("mode", "source_mode"))
                if m in _CANONICAL_DOM_FORBIDDEN_MODES
            ),
            "",
        )
        if (not _jd.get("smoke_test")) and _canonical:
            return {
                "ok": False,
                "error": "ERR_CANONICAL_MODE_LEGACY_DOM_ROUTE_FORBIDDEN",
                "mode": _canonical,
                "detail": (
                    "Canonical production modes generate API-first "
                    "(make_video.start_generate); the DOM lane is dead."
                ),
            }
        return await self._send("EXECUTE_FLOW_JOB", {"job": job_data}, timeout=120)

    async def debug_flow_dom_execution(self, mode: str, job: Optional[dict] = None) -> dict:
        """Trigger a debug action for DOM automation."""
        return await self._send("DEBUG_FLOW_DOM_EXECUTION", {"params": {"mode": mode, "job": job}}, timeout=30)

    async def check_flow_composer_ready(self, mode: Optional[str] = None) -> dict:
        """Check whether the real Google Flow composer is available and editable."""
        result = await self._send("CHECK_FLOW_COMPOSER_READY", {"mode": mode}, timeout=20)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        payload = result.get("result")
        if isinstance(payload, dict):
            return payload

        return {"ok": False, "error": "invalid composer readiness payload"}

    async def flow_page_state_diagnostic(self, mode: Optional[str] = None) -> dict:
        """Read visible page state from the controlled Google Flow tab without clicking or generating."""
        result = await self._send("FLOW_PAGE_STATE_DIAGNOSTIC", {"mode": mode}, timeout=20)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        payload = result.get("result")
        if isinstance(payload, dict):
            return payload

        return {"ok": False, "error": "invalid flow page state diagnostic payload"}

    async def reload_flow_tab(self, tab_id: int | None = None) -> dict:
        """Reload the detected Flow tab and re-inject the DOM helper without executing generation."""
        params = {} if tab_id is None else {"tab_id": tab_id}
        result = await self._send("RELOAD_FLOW_TAB", params, timeout=15)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        payload = result.get("result")
        if isinstance(payload, dict):
            return payload

        return {"ok": False, "error": "invalid reload flow tab payload"}

    async def reload_extension(self) -> dict:
        """Reload the extension runtime (chrome.runtime.reload) so on-disk JS changes take effect."""
        result = await self._send("RELOAD_EXTENSION", {}, timeout=15)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        payload = result.get("result")
        if isinstance(payload, dict):
            return payload

        return {"ok": False, "error": "invalid reload extension payload"}

    async def create_agent_session(self, project_id: str) -> dict:
        """Create a flowCreationAgent session (current Omni/V2 video path)."""
        url = self._build_url("create_agent_session")
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": {"projectId": f"projects/{project_id}"},
        }, timeout=30)

    async def agent_stream_chat(self, session_id: str, project_id: str,
                                turn_number: int, text: str,
                                media_ids: Optional[list[str]] = None,
                                permission_action: Optional[str] = None) -> dict:
        """Send one conversational turn to the flowCreationAgent (video generation).

        Turn 1 carries the prompt + mediaReferences. Later turns steer the agent
        ("i want 1 video only", "veo 3.1 - lite only") or approve/reject via
        permission_action. Returns the SSE stream as text.
        """
        url = self._build_url("agent_stream_chat")
        body = {
            "agentSessionId": session_id,
            "agentClientContext": {
                "projectId": f"projects/{project_id}",
                "clientSessionId": f";{int(time.time() * 1000)}",
                "recaptchaContext": {
                    "token": "",  # extension injects the solved token
                    "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
                },
                "turnNumber": turn_number,
            },
            "userMessage": {"userPrompt": {"parts": [{"text": text}]}},
        }
        if media_ids:
            body["userMessage"]["mediaReferences"] = [{"mediaId": m} for m in media_ids]
        if permission_action:
            body["permissionAction"] = permission_action
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "CHAT_GENERATION",  # captured from live UI (not VIDEO_GENERATION)
        }, timeout=120)

    async def harvest_video_urls(self, tab_id: int | None = None) -> dict:
        """Scan the (bound) Flow editor tab for finished media: video/image/media ids
        and GCS urls. Maps to the extension's HARVEST_VIDEO_URLS WS method.

        Returns the raw WS envelope — callers unwrap .get("result", ...) themselves
        (make_video patch A/G expects flow_tab_found/flow_tab_id/diag inside it and
        fail-closes on NO_FLOW_TAB / BOUND_TAB_GONE)."""
        params: dict = {}
        if tab_id is not None:
            params["tab_id"] = tab_id
        result = await self._send("HARVEST_VIDEO_URLS", params, timeout=30)
        self._remember_media_generation_ids(result)
        return result

    def _remember_media_generation_ids(self, result: dict) -> None:
        """Cache the current Flow UUID -> generation-resource mapping.

        The extension returns this alongside the DOM harvest.  It is deliberately
        best-effort: older extension builds omit it and the caller still gets the
        original response for diagnostics.
        """
        if not isinstance(result, dict):
            return
        payload = result.get("result", result)
        if not isinstance(payload, dict):
            return
        diag = payload.get("diag", payload)
        mapping = diag.get("mediaGenerationIds") if isinstance(diag, dict) else None
        if not isinstance(mapping, dict):
            return
        for media_id, generation_id in mapping.items():
            media_id = str(media_id or "").strip()
            generation_id = str(generation_id or "").strip()
            if media_id and generation_id:
                self._media_generation_ids[media_id] = generation_id

    async def open_target_flow_project(self, flow_project_url: str) -> dict:
        """Open or focus an exact Google Flow project editor URL before readiness checks."""
        result = await self._send("OPEN_TARGET_FLOW_PROJECT", {"flow_project_url": flow_project_url}, timeout=45)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        payload = result.get("result")
        if isinstance(payload, dict):
            return payload

        return {"ok": False, "error": "invalid open target flow project payload"}

    async def open_flow_new_project(self, mode: Optional[str] = None) -> dict:
        """Open Google Flow root, create a new project, and wait for a ready editor."""
        result = await self._send("OPEN_FLOW_NEW_PROJECT", {"mode": mode}, timeout=75)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        payload = result.get("result")
        if isinstance(payload, dict):
            return payload

        return {"ok": False, "error": "invalid open flow new project payload"}

    async def smoke_execute_flow_job(self, job_data: dict, timeout: float = 5) -> dict:
        """Verify the EXECUTE_FLOW_JOB bridge path without triggering generation."""
        smoke_job = dict(job_data)
        smoke_job["smoke_test"] = True
        started = time.monotonic()
        result = await self._send("EXECUTE_FLOW_JOB", {"job": smoke_job}, timeout=timeout)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if result.get("error"):
            error = result["error"]
            status = "FAIL_TIMEOUT" if "Timeout" in error else "FAIL_ERROR"
            return {
                "ok": False,
                "status": status,
                "error": error,
                "round_trip_ms": elapsed_ms,
            }

        payload = result.get("result")
        if isinstance(payload, dict):
            smoke_result = dict(payload)
            smoke_result.setdefault("round_trip_ms", elapsed_ms)
            return smoke_result

        return {
            "ok": False,
            "status": "FAIL_ERROR",
            "error": "invalid smoke payload",
            "round_trip_ms": elapsed_ms,
        }

    def _client_context(self, project_id: str, user_paygate_tier: str = "PAYGATE_TIER_TWO") -> dict:
        """Build clientContext with recaptcha placeholder."""
        return {
            "projectId": str(project_id),
            "recaptchaContext": {
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
                "token": "",  # Extension injects real token
            },
            "sessionId": f";{int(time.time() * 1000)}",
            "tool": "PINHOLE",
            "userPaygateTier": user_paygate_tier,
        }

    # ─── High-level API Methods ──────────────────────────────

    async def create_project(self, project_title: str, tool_name: str = "PINHOLE") -> dict:
        """Create a project on Google Flow via tRPC endpoint.

        Returns the full response including projectId.
        """
        url = "https://labs.google/fx/api/trpc/project.createProject"
        body = {"json": {"projectTitle": project_title, "toolName": tool_name}}

        return await self._send("trpc_request", {
            "url": url,
            "method": "POST",
            "headers": {
                "content-type": "application/json",
                "accept": "*/*",
            },
            "body": body,
        }, timeout=30)

    async def get_project_initial_data(self, project_id: str) -> dict:
        """Read the authenticated Flow project payload through the browser relay."""
        query = quote(json.dumps({"json": {"projectId": str(project_id)}}), safe="")
        url = f"https://labs.google/fx/api/trpc/flow.projectInitialData?input={query}"
        return await self._send("trpc_request", {
            "url": url,
            "method": "GET",
            "headers": {"accept": "*/*"},
        }, timeout=30)

    async def list_project_media(self, project_id: str) -> dict:
        """Return current project media from Flow's authenticated tRPC payload.

        Current agent-created videos use their delivery UUID as ``media.name``
        and expose the exact generation prompt/model/seed here even when the
        legacy ``/v1/media/{uuid}`` endpoint returns HTTP 400.
        """
        result = await self.get_project_initial_data(project_id)
        status = result.get("status") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get("error")
                or (isinstance(status, int) and status >= 400)):
            return {
                "status": status,
                "project_id": str(project_id),
                "media": [],
                "error": (result.get("error") if isinstance(result, dict)
                          else "invalid project initial data response"),
            }
        payload = result.get("data", result)
        try:
            project = payload["result"]["data"]["json"]
            contents = project.get("projectContents") or {}
            media = contents.get("media") or []
        except (KeyError, TypeError):
            return {
                "status": status,
                "project_id": str(project_id),
                "media": [],
                "error": "invalid project initial data payload",
            }
        observed_project_id = str(project.get("projectId") or "").strip()
        return {
            "status": status,
            "project_id": observed_project_id,
            "media": [item for item in media if isinstance(item, dict)],
        }

    async def generate_images(self, prompt: str, project_id: str,
                               aspect_ratio: str = "IMAGE_ASPECT_RATIO_PORTRAIT",
                               user_paygate_tier: str = "PAYGATE_TIER_TWO",
                               character_media_ids: list[str] = None,
                               image_model: str = "NANO_BANANA_PRO") -> dict:
        """Generate image(s).

        If character_media_ids is provided, uses edit_image flow (batchGenerateImages
        with imageInputs) — same endpoint, but includes character references.
        Without characters, uses plain generate_images.

        Response structure:
            data.media[].name = mediaId (used for video gen)
        """
        ts = int(time.time() * 1000)
        ctx = self._client_context(project_id, user_paygate_tier)

        request_item = {
            "clientContext": {**ctx, "sessionId": f";{ts}"},
            "seed": ts % 1000000,
            "structuredPrompt": {"parts": [{"text": prompt}]},
            "imageAspectRatio": aspect_ratio,
            "imageModelName": resolve_image_model_name(image_model),
        }

        # Add character references if provided (edit_image flow)
        if character_media_ids:
            request_item["imageInputs"] = [
                {"name": mid, "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE"}
                for mid in character_media_ids
            ]

        batch_id = f"{uuid.uuid4()}" if character_media_ids else None
        body = {
            "clientContext": ctx,
            "requests": [request_item],
        }
        if batch_id:
            body["mediaGenerationContext"] = {"batchId": batch_id}
            body["useNewMedia"] = True

        url = self._build_url("generate_images", project_id=project_id)
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "IMAGE_GENERATION",
        })

    async def edit_image(self, prompt: str, source_media_id: str,
                          project_id: str,
                          aspect_ratio: str = "IMAGE_ASPECT_RATIO_PORTRAIT",
                          user_paygate_tier: str = "PAYGATE_TIER_ONE",
                          character_media_ids: list[str] = None,
                          image_model: str = "NANO_BANANA_PRO") -> dict:
        """Edit an existing image using IMAGE_INPUT_TYPE_BASE_IMAGE.

        If character_media_ids is provided, appends them as IMAGE_INPUT_TYPE_REFERENCE
        after the base image. Order: [base_image, char_A, char_B, ...].
        This helps Google Flow detect characters for consistent edits.
        """
        ts = int(time.time() * 1000)
        ctx = self._client_context(project_id, user_paygate_tier)

        image_inputs = [
            {"name": source_media_id, "imageInputType": "IMAGE_INPUT_TYPE_BASE_IMAGE"}
        ]
        if character_media_ids:
            for mid in character_media_ids:
                image_inputs.append({"name": mid, "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE"})

        request_item = {
            "clientContext": {**ctx, "sessionId": f";{ts}"},
            "seed": ts % 1000000,
            "structuredPrompt": {"parts": [{"text": prompt}]},
            "imageAspectRatio": aspect_ratio,
            "imageModelName": resolve_image_model_name(image_model),
            "imageInputs": image_inputs,
        }

        body = {
            "clientContext": ctx,
            "mediaGenerationContext": {"batchId": f"{uuid.uuid4()}"},
            "useNewMedia": True,
            "requests": [request_item],
        }

        url = self._build_url("generate_images", project_id=project_id)
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "IMAGE_GENERATION",
        })

    async def generate_video(self, start_image_media_id: str, prompt: str,
                              project_id: str, scene_id: str,
                              aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                              end_image_media_id: str = None,
                              user_paygate_tier: str = "PAYGATE_TIER_TWO",
                              video_model_key: str = None,
                              seed: int = None) -> dict:
        """Generate video from start image (i2v).

        Two sub-types:
        - frame_2_video (i2v): startImage only
        - start_end_frame_2_video (i2v_fl): startImage + endImage (for scene chaining)

        ``video_model_key`` (USER SETTINGS ARE LAW): an explicitly captured key
        overrides the models.json default; with neither the call FAILS CLOSED.
        ``seed`` lets the caller record the exact fired seed for output binding.
        """
        gen_type = "start_end_frame_2_video" if end_image_media_id else "frame_2_video"
        model_key = resolve_video_model_key(user_paygate_tier, gen_type, aspect_ratio,
                                            override=video_model_key)

        if not model_key:
            return {"error": f"No model for tier={user_paygate_tier} type={gen_type} ratio={aspect_ratio}"}

        request = {
            "aspectRatio": aspect_ratio,
            "seed": int(seed) if seed is not None else int(time.time()) % 10000,
            "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model_key,
            "startImage": {"mediaId": start_image_media_id},
            "metadata": {"sceneId": scene_id},
        }

        if end_image_media_id:
            request["endImage"] = {"mediaId": end_image_media_id}

        endpoint_key = "generate_video_start_end" if end_image_media_id else "generate_video"
        body = {
            "mediaGenerationContext": {"batchId": f"{uuid.uuid4()}"},
            "clientContext": self._client_context(project_id, user_paygate_tier),
            "requests": [request],
            "useV2ModelConfig": True,
        }

        url = self._build_url(endpoint_key)
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "VIDEO_GENERATION",
        }, timeout=60)  # Submit only — polling is separate

    async def generate_video_from_references(self, reference_media_ids: list[str],
                                              prompt: str, project_id: str, scene_id: str,
                                              aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                                              user_paygate_tier: str = "PAYGATE_TIER_TWO",
                                              video_model_key: str = None,
                                              seed: int = None) -> dict:
        """Generate video from multiple reference images (r2v).

        Uses referenceImages instead of startImage — the model composes
        a video from all provided reference character images.

        ``video_model_key`` (USER SETTINGS ARE LAW): an explicitly captured key
        overrides the models.json default; with neither the call FAILS CLOSED.
        ``seed`` lets the caller record the exact fired seed for output binding.

        Args:
            reference_media_ids: List of character media_ids (from uploadImage)
        """
        gen_type = "reference_frame_2_video"
        model_key = resolve_video_model_key(user_paygate_tier, gen_type, aspect_ratio,
                                            override=video_model_key)

        if not model_key:
            return {"error": f"No model for tier={user_paygate_tier} type={gen_type} ratio={aspect_ratio}"}

        request = {
            "aspectRatio": aspect_ratio,
            "seed": int(seed) if seed is not None else int(time.time()) % 10000,
            "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model_key,
            "referenceImages": [
                {"mediaId": mid, "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"}
                for mid in reference_media_ids
            ],
            "metadata": {},
        }

        body = {
            "mediaGenerationContext": {"batchId": f"{uuid.uuid4()}"},
            "clientContext": self._client_context(project_id, user_paygate_tier),
            "requests": [request],
            "useV2ModelConfig": True,
        }

        url = self._build_url("generate_video_references")
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "VIDEO_GENERATION",
        }, timeout=60)

    async def upscale_video(self, media_id: str, scene_id: str,
                             aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                             resolution: str = "VIDEO_RESOLUTION_4K") -> dict:
        """Upscale a video."""
        model_key = UPSCALE_MODELS.get(resolution, "veo_3_1_upsampler_4k")

        body = {
            "clientContext": {
                "sessionId": f";{int(time.time() * 1000)}",
                "recaptchaContext": {
                    "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
                    "token": "",
                },
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "resolution": resolution,
                "seed": int(time.time()) % 100000,
                "metadata": {"sceneId": scene_id},
                "videoInput": {"mediaId": media_id},
                "videoModelKey": model_key,
            }],
        }

        url = self._build_url("upscale_video")
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "VIDEO_GENERATION",
        }, timeout=60)

    async def generate_video_extend(self, *, source_operation_id: str, project_id: str,
                                    scene_id: str, position: int, prompt: str,
                                    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                                    start_frame_index: int = 1, end_frame_index: int = 24,
                                    seed: int = None, batch_id: str = None,
                                    user_paygate_tier: str = "PAYGATE_TIER_TWO") -> dict:
        """Native Google Flow Extend — continue a prior clip into the next block.

        Emits the exact captured contract (live 2026-07-11, record 608):
        POST /v1/video:batchAsyncGenerateVideoExtendVideo. Continuity is carried by
        ``videoInput.{mediaId,startFrameIndex,endFrameIndex}`` — the parent's
        OPERATION id + trim window — NOT by prompt phrasing. The prompt is the FULL
        structured block prompt (same shape as the initial block), never a compact
        "extend this video" phrase.

        NOTE the boundary: ``source_operation_id`` is the parent clip's OPERATION id
        (what `videoInput.mediaId` binds — block-1 op `b6371e69`), NOT its
        `primaryMediaId` (`69051c7b`). Callers must pass the operation id.

        Model FAILS CLOSED: an aspect ratio without captured evidence resolves to no
        model key and returns an error — never a silent downgrade to another model.
        Rides the same authenticated extension relay as every other video RPC
        (``_send('api_request', …)``) so no extension change is needed.
        """
        model_key = EXTEND_VIDEO_MODELS.get(aspect_ratio)
        if not model_key:
            return {"error": f"UNKNOWN_EXTEND_MODEL:{aspect_ratio}"}
        if not source_operation_id:
            return {"error": "EXTEND_PARENT_MEDIA_ID_MISSING"}
        if not (project_id and scene_id):
            return {"error": "EXTEND_PROJECT_CONTEXT_MISSING"}

        request = {
            "aspectRatio": aspect_ratio,
            "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model_key,
            "seed": int(seed) if seed is not None else int(time.time()) % 100000,
            "metadata": {"sceneId": scene_id},
            "videoInput": {
                "mediaId": source_operation_id,
                "startFrameIndex": int(start_frame_index),
                "endFrameIndex": int(end_frame_index),
            },
        }
        body = {
            "mediaGenerationContext": {
                "batchId": batch_id or f"{uuid.uuid4()}",
                "audioFailurePreference": "BLOCK_SILENCED_VIDEOS",
                "sceneContext": {"sceneId": scene_id, "position": int(position)},
            },
            "clientContext": self._client_context(project_id, user_paygate_tier),
            "requests": [request],
            "useV2ModelConfig": True,
        }
        url = self._build_url("generate_video_extend")
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
            "captchaAction": "VIDEO_GENERATION",
        }, timeout=60)  # Submit only — synchronous response returns the child id; polling is separate

    async def check_video_status_by_media(self, media: list) -> dict:
        """Poll async video status by MEDIA id — native-extend poll contract
        (captured): body ``{"media":[{"name":<childMediaId>,"projectId":<pid>}]}``.

        Deliberately NOT ``check_video_status`` (which sends ``{"operations":[…]}``
        for the classic generate lane): the extension bridge proxies bytes blindly,
        so a wrong body shape yields an empty poll, not an error.
        """
        url = self._build_url("check_video_status")
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": {"media": media},
        }, timeout=30)

    async def check_video_status(self, operations: list[dict]) -> dict:
        """Check status of video generation operations."""
        body = {"operations": operations}
        url = self._build_url("check_video_status")
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
        }, timeout=30)  # No captcha needed

    async def get_credits(self) -> dict:
        """Get user credits and tier."""
        url = self._build_url("get_credits")
        return await self._send("api_request", {
            "url": url,
            "method": "GET",
            "headers": random_headers(),
        }, timeout=15)

    async def get_status(self, timeout: float = 5) -> dict:
        """Query live extension runtime state over the WebSocket bridge."""
        if not self.connected:
            return {
                "connected": False,
                "state": "off",
                "flowKeyPresent": False,
                "manualDisconnect": False,
                "metrics": {},
            }

        async def _query_selected() -> dict:
            result = await self._send("get_status", {}, timeout=timeout)
            if result.get("error"):
                response = {
                    "connected": True,
                    "state": "unknown",
                    "flowKeyPresent": False,
                    "manualDisconnect": False,
                    "metrics": {},
                    "error": result["error"],
                }
                if "connection_count" in result:
                    response["connection_count"] = result["connection_count"]
                return response

            data = result.get("result")
            if isinstance(data, dict):
                data = dict(data)
                try:
                    record = self._select_connection()
                except ConnectionError:
                    record = None
                if record is not None:
                    reported_connection_id = str(data.get("connection_id") or "").strip()
                    if (
                        reported_connection_id
                        and reported_connection_id != record["connection_id"]
                    ):
                        return {
                            "connected": True,
                            "state": "unknown",
                            "flowKeyPresent": False,
                            "manualDisconnect": False,
                            "metrics": {},
                            "error": "ERR_EXTENSION_CONNECTION_IDENTITY_MISMATCH",
                        }
                    data["connection_id"] = record["connection_id"]
                    data["connection_epoch"] = record["connection_epoch"]
                    for key in ("installation_id", "extension_session_id"):
                        observed = str(data.get(key) or "").strip() or None
                        current = record.get(key)
                        if observed and current and observed != current:
                            return {
                                "connected": True,
                                "state": "unknown",
                                "flowKeyPresent": False,
                                "manualDisconnect": False,
                                "metrics": {},
                                "error": "ERR_EXTENSION_CONNECTION_IDENTITY_MISMATCH",
                            }
                        if observed:
                            record[key] = observed
                        data[key] = record.get(key)
                data.setdefault("connected", self.connected)
                return data

            return {
                "connected": self.connected,
                "state": "unknown",
                "flowKeyPresent": False,
                "manualDisconnect": False,
                "metrics": {},
                "error": "invalid extension status payload",
            }

        if not self._connections or self._active_operation_lease_id.get():
            return await _query_selected()
        try:
            lease = self.acquire_operation_lease()
        except ConnectionError as exc:
            error = str(exc)
            response = {
                "connected": True,
                "state": "unknown",
                "flowKeyPresent": False,
                "manualDisconnect": False,
                "metrics": {},
                "error": error,
            }
            if error == "ERR_EXTENSION_CONNECTION_AMBIGUOUS":
                response["connection_count"] = len(self._connections)
            return response
        try:
            with self.activate_operation_lease(lease):
                return await _query_selected()
        finally:
            self.release_operation_lease(lease)

    async def verify_provider_session_challenge(
        self,
        flow_tab_id: int | None = None,
        timeout: float = 15,
    ) -> dict:
        """Prove that the live extension session owns the live Flow project tab.

        The backend supplies a short-lived nonce to the connected extension. The
        extension routes it to the selected project-editor content script and
        returns the nonce together with the tab's current project URL/build.
        Comparing the returned extension session id with the status snapshot is
        the provider-authority proof; no CDP browser or cookie inspection is
        involved.
        """
        async def _verify_selected() -> dict:
            status = await self.get_status(timeout=5)
            if status.get("error") in {
                "ERR_EXTENSION_CONNECTION_AMBIGUOUS",
                "ERR_EXTENSION_CONNECTION_CLOSED",
                "ERR_EXTENSION_CONNECTION_NOT_FOUND",
                "ERR_OPERATION_LEASE_NOT_ACTIVE",
                "ERR_EXTENSION_CONNECTION_IDENTITY_MISMATCH",
            }:
                return {
                    "ok": False,
                    "primary_blocker": status["error"],
                    "flow_transport_connected": bool(self._connections),
                }
            if status.get("connected") is not True:
                return {
                    "ok": False,
                    "primary_blocker": "EXTENSION_BRIDGE_NOT_CONNECTED",
                    "flow_transport_connected": False,
                }

            backend_session_id = str(status.get("extension_session_id") or "").strip()
            if not backend_session_id:
                return {
                    "ok": False,
                    "primary_blocker": "EXTENSION_SESSION_MISMATCH",
                    "flow_transport_connected": True,
                    "backend_extension_session_id": None,
                }

            nonce = secrets.token_urlsafe(24)
            params = {"nonce": nonce}
            if flow_tab_id is not None:
                params["flow_tab_id"] = int(flow_tab_id)
            response = await self._send(
                "FLOW_PROVIDER_SESSION_CHALLENGE",
                params,
                timeout=timeout,
            )
            payload = response.get("result") if isinstance(response, dict) else None
            if not isinstance(payload, dict):
                payload = response if isinstance(response, dict) else {}

            returned_nonce = str(payload.get("challenge_nonce") or "")
            returned_session_id = str(payload.get("extension_session_id") or "").strip()
            returned_tab_id = payload.get("flow_tab_id")
            try:
                returned_tab_id = int(returned_tab_id) if returned_tab_id is not None else None
            except (TypeError, ValueError):
                returned_tab_id = None
            expected_tab_id = int(flow_tab_id) if flow_tab_id is not None else None
            nonce_match = secrets.compare_digest(returned_nonce, nonce)
            same_extension_session = bool(
                returned_session_id and returned_session_id == backend_session_id
            )
            same_flow_tab = bool(
                payload.get("same_flow_tab") is True
                or (
                    returned_tab_id is not None
                    and (expected_tab_id is None or returned_tab_id == expected_tab_id)
                    and bool(payload.get("flow_project_id"))
                )
            )
            content_alive = payload.get("content_script_alive") is True
            challenge_verified = bool(
                payload.get("ok") is True
                and nonce_match
                and same_extension_session
                and same_flow_tab
                and content_alive
            )
            status_build = str(
                status.get("extension_build")
                or status.get("background_build_id")
                or ""
            )
            result_build = str(payload.get("extension_build") or "")
            extension_build_match = bool(
                payload.get("extension_build_match") is True
                and (not status_build or not result_build or status_build == result_build)
            )
            return {
                **payload,
                "ok": challenge_verified,
                "backend_connection_id": status.get("connection_id"),
                "backend_connection_epoch": status.get("connection_epoch"),
                "backend_installation_id": status.get("installation_id"),
                "backend_extension_session_id": backend_session_id,
                "challenge_nonce_expected": nonce,
                "challenge_nonce_returned": returned_nonce or None,
                "challenge_nonce_match": nonce_match,
                "same_extension_session": same_extension_session,
                "same_flow_tab": same_flow_tab,
                "content_script_alive": content_alive,
                "extension_build_match": extension_build_match,
                "session_challenge_verified": challenge_verified,
                "flow_transport_connected": True,
                "primary_blocker": (
                    None
                    if challenge_verified
                    else str(
                        payload.get("primary_blocker")
                        or "FLOW_SESSION_CHALLENGE_FAILED"
                    )
                ),
            }

        if self._active_operation_lease_id.get():
            return await _verify_selected()
        try:
            lease = self.acquire_operation_lease()
        except ConnectionError as exc:
            error = str(exc)
            return {
                "ok": False,
                "primary_blocker": (
                    error
                    if error.startswith("ERR_")
                    else "EXTENSION_BRIDGE_NOT_CONNECTED"
                ),
                "flow_transport_connected": bool(self._connections),
            }
        try:
            with self.activate_operation_lease(lease):
                return await _verify_selected()
        finally:
            self.release_operation_lease(lease)

    async def validate_media_id(self, media_id: str) -> bool:
        """Check if a mediaId is still valid.

        Production calls: GET /v1/media/{mediaId}?key=...&clientContext.tool=PINHOLE
        Returns True on 200, False otherwise.
        """
        result = await self.get_media(media_id)
        status = result.get("status", 500)
        return isinstance(status, int) and status == 200

    async def get_media(self, media_id: str, media_generation_id: str | None = None) -> dict:
        """Fetch media metadata from Google Flow.

        Current Flow project payloads distinguish the delivery tile's ``mediaId``
        (the UUID found in ``media.getMediaUrlRedirect``) from the generation
        resource key used by ``/v1/media``.  Prefer the authenticated mapping
        captured by ``harvest_video_urls``; fall back to the supplied id for
        legacy payloads and test clients.
        """
        generation_key = str(
            media_generation_id
            or self._media_generation_ids.get(str(media_id))
            or media_id
        ).strip()
        # The web client accepts Flow's resource-name form but strips this
        # namespace before constructing the /v1/media path.
        if "flowMedia/" in generation_key:
            generation_key = generation_key.split("flowMedia/", 1)[1]
        encoded_key = quote(generation_key, safe="/")
        url = (f"{GOOGLE_FLOW_API}/v1/media/{encoded_key}"
               f"?key={GOOGLE_API_KEY}&clientContext.tool=PINHOLE")
        return await self._send("api_request", {
            "url": url,
            "method": "GET",
            "headers": random_headers(),
        }, timeout=15)

    async def get_media_download_url(self, media_id: str) -> dict:
        """Resolve a Flow tile UUID through the authenticated browser redirect.

        This is the delivery fallback for current image/video tiles whose
        metadata endpoint is not addressable from the UUID alone.  The extension
        follows the authenticated labs.google redirect and returns only the final
        signed URL; bytes are downloaded by the agent, never buffered in the
        extension WebSocket.
        """
        url = ("https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name="
               + quote(str(media_id), safe=""))
        result = await self._send("MEDIA_URL_REDIRECT", {"url": url}, timeout=30)
        payload = result.get("result", result) if isinstance(result, dict) else result
        return payload if isinstance(payload, dict) else {"ok": False, "error": "invalid media redirect payload"}

    async def create_scene(self, project_id: str, workflow_ids: list[str]) -> dict:
        """Create a Flow SCENE (the timeline container) from workflow ids.

        Captured live contract (concat_completion_smoke_20260711_100555):
        POST /v1/flow/projects/{projectId}/scenes  body {"workflowIds": [...]}
        -> {scene:{sceneId,...}, sceneWorkflows:[{workflow{name, metadata{
        primaryMediaId, batchId}}, sceneId, sceneWorkflowMetadata{totalDuration,...}}]}
        NOTE: there is NO GET listing for project scenes on this host — the page
        lists scenes via labs.google trpc (outside the relay host guard). Scene ids
        must come from our own records (lineage / artifacts / this response).
        """
        url = f"{GOOGLE_FLOW_API}/v1/flow/projects/{project_id}/scenes"
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": {"workflowIds": list(workflow_ids or [])},
        }, timeout=30)

    # ── FLOWUI current-UI driver relay (Owner Phase-2, targeted) ─────────────
    # Thin verb relays to extension/flow-ui-driver.js. No credit authority here:
    # the single credit verb (submit_extend) requires confirm=True end-to-end and
    # is additionally gated by the server-side kill switch in the driver service.
    async def flowui_state(self, tab_id: int | None = None) -> dict:
        return await self._send("FLOWUI_STATE", {"tab_id": tab_id}, timeout=20)

    async def flowui_verify_media_visible(self, media_ids: list,
                                          tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_VERIFY_COMPOSER_MEDIA",
            {"media_ids": list(media_ids or []), "tab_id": tab_id}, timeout=25)

    async def flowui_verify_composer_zero(self, tab_id: int | None = None) -> dict:
        return await self._send("FLOWUI_VERIFY_COMPOSER_ZERO",
                                {"tab_id": tab_id}, timeout=40)

    async def flowui_composer_attach_file(self, file_path: str, *,
                                          expected_file_name: str | None = None,
                                          slot_label: str = "ComposerRef",
                                          tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_COMPOSER_ATTACH_FILE",
            {"file_path": file_path, "expected_file_name": expected_file_name,
             "slot_label": slot_label, "tab_id": tab_id}, timeout=60)

    async def flowui_set_composer_prompt(self, text: str,
                                         tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_SET_COMPOSER_PROMPT", {"text": text, "tab_id": tab_id},
            timeout=30)

    async def flowui_submit_composer_create(self, *, confirm: bool,
                                            intercept_only: bool = False,
                                            tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_SUBMIT_COMPOSER_CREATE",
            {"confirm": bool(confirm), "intercept_only": bool(intercept_only),
             "tab_id": tab_id},
            timeout=40)

    async def flowui_open_video(self, parent_media_resource_id: str, *,
                                expected_project_id: str | None = None,
                                tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_OPEN_VIDEO",
            {"parent_media_resource_id": parent_media_resource_id,
             "parent_media_operation_id": parent_media_resource_id,
             "expected_project_id": expected_project_id, "tab_id": tab_id},
            timeout=60)

    async def flowui_add_clip_extend(self, model_label: str,
                                     tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_ADD_CLIP_EXTEND", {"model_label": model_label, "tab_id": tab_id},
            timeout=30)

    async def flowui_set_extend_prompt(self, text: str,
                                       tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_SET_EXTEND_PROMPT", {"text": text, "tab_id": tab_id}, timeout=30)

    async def flowui_submit_extend(self, *, confirm: bool,
                                   tab_id: int | None = None) -> dict:
        return await self._send(
            "FLOWUI_SUBMIT_EXTEND", {"confirm": bool(confirm), "tab_id": tab_id},
            timeout=40)

    async def flowui_download_project(self, tab_id: int | None = None,
                                      timeout_ms: int = 120000) -> dict:
        return await self._send(
            "FLOWUI_DOWNLOAD_PROJECT_CAPTURE",
            {"tab_id": tab_id, "timeout_ms": timeout_ms},
            timeout=max(60, int(timeout_ms / 1000) + 30))

    async def list_scene_workflows(self, scene_id: str, project_id: str = "") -> dict:
        """List one scene's workflows + media (read-only, zero credit).

        Captured contract: GET /v1/flow/scene/{sceneId}/workflows →
        {sceneWorkflows:[...], media:[{name, projectId, workflowId, ...}]}.
        media[].name is the generated clip's operation id (== workflows'
        metadata.primaryMediaId) — the exact value native Extend needs as its parent.
        """
        # Captured live contract: workflows listing takes sceneId + projectId query
        # params (and nothing else). project_id is required for the live call.
        url = (f"{GOOGLE_FLOW_API}/v1/flow/scene/{scene_id}/workflows"
               f"?sceneId={scene_id}" + (f"&projectId={project_id}" if project_id else ""))
        return await self._send("api_request", {
            "url": url,
            "method": "GET",
            "headers": random_headers(),
        }, timeout=20)

    async def run_video_concatenation(self, input_videos: list[dict]) -> dict:
        """Submit the FINAL TIMELINE render — concatenate segment media into ONE video.

        Captured live contract (concat_completion_smoke_20260711_100555 rid=9924.2526):
        POST /v1:runVideoFxConcatenation
        body {"inputVideos":[{"mediaGenerationId", "length":"8000000000" (ns string),
              "startTimeOffset":"0.000000000s", "endTimeOffset":"8.000000000s"}, ...]}
        -> {"operation":{"operation":{"name":"projects/<n>/locations/us-central1/jobs/<id>"}}}
        """
        url = f"{GOOGLE_FLOW_API}/v1:runVideoFxConcatenation"
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": {"inputVideos": input_videos},
        }, timeout=60)

    async def check_video_concatenation_status(self, operation_envelope: dict) -> dict:
        """Poll the final-timeline render job (body = the submit response VERBATIM).

        Captured terminal contract (rid=9924.2542): non-terminal
        {"status":"MEDIA_GENERATION_STATUS_ACTIVE", ...} then
        {"status":"MEDIA_GENERATION_STATUS_SUCCESSFUL", "inputsCount":N,
         "encodedVideo":"<base64 mp4>"} — the ONE combined MP4 arrives INLINE.
        """
        url = f"{GOOGLE_FLOW_API}/v1:runVideoFxCheckConcatenationStatus"
        return await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": operation_envelope,
        }, timeout=120)

    async def upload_image(self, image_base64: str, mime_type: str = "image/jpeg",
                            project_id: str = "", file_name: str = "image.jpg") -> dict:
        """Upload an image for use as start/end frame.

        Uses /v1/flow/uploadImage endpoint.
        Response: {media: {name: "uuid", ...}, workflow: {...}}
        We store media.name as the mediaId for video generation.
        """
        body = {
            "clientContext": {
                "projectId": project_id,
                "tool": "PINHOLE",
            },
            "fileName": file_name,
            "imageBytes": image_base64,
            "isHidden": False,
            "isUserUploaded": True,
            "mimeType": mime_type,
        }

        url = self._build_url("upload_image")
        result = await self._send("api_request", {
            "url": url,
            "method": "POST",
            "headers": random_headers(),
            "body": body,
        }, timeout=60)

        # Extract media.name for convenience (used as mediaId in video gen)
        if not _is_ws_error(result):
            data = result.get("data", {})
            if isinstance(data, dict):
                media = data.get("media", {})
                if isinstance(media, dict) and media.get("name"):
                    result["_mediaId"] = media["name"]

        return result


def _is_ws_error(result: dict) -> bool:
    return bool(result.get("error")) or (isinstance(result.get("status"), int) and result["status"] >= 400)


# Singleton
_client: Optional[FlowClient] = None


def get_flow_client() -> FlowClient:
    global _client
    if _client is None:
        _client = FlowClient()
    return _client
