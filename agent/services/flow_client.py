"""
Flow Client — communicates with Google Flow API via Chrome extension WebSocket bridge.

Agent runs a WS server. Extension connects as client. Agent sends API requests,
extension executes them in browser context (residential IP, cookies, reCAPTCHA).
"""
import asyncio
import json
import logging
import secrets
import time
import uuid
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
        self._extension_ws = None  # Set by WS server when extension connects
        # A local agent can be reached by more than one Flow Kit service worker
        # (for example the dedicated UAT profile and the owner's profile).  The
        # old singleton socket made that a LAST_CONNECTED_EXTENSION_WINS race.
        # Keep every identity-bearing socket and select/pin one explicitly.
        self._extension_sessions: dict[str, dict] = {}
        self._socket_session_ids: dict[int, str] = {}
        self._unidentified_sockets: dict[int, dict] = {}
        self._active_extension_session_id: str | None = None
        self._pinned_extension_session_id: str | None = None
        self._pinned_binding: dict = {}
        self._selection_locked = False
        self._last_arbitration_error: str | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_session_ids: dict[str, str | None] = {}
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

    @staticmethod
    def _safe_ws_open(ws) -> bool:
        """Return false only for an explicitly closed websocket/mock."""
        if ws is None or getattr(ws, "closed", False) is True:
            return False
        ready_state = getattr(ws, "ready_state", None)
        return ready_state not in (2, 3)

    @staticmethod
    def _identity_fields(data: dict | None) -> dict:
        data = data if isinstance(data, dict) else {}
        return {
            "extension_session_id": str(data.get("extension_session_id") or "").strip(),
            "extension_id": str(data.get("extension_id") or "").strip() or None,
            "extension_version": str(data.get("extension_version") or "").strip() or None,
            "extension_build": str(
                data.get("extension_build")
                or data.get("background_build_id")
                or data.get("build_id")
                or ""
            ).strip() or None,
        }

    def set_extension(
        self,
        ws,
        identity: dict | None = None,
        *,
        require_identity: bool = False,
    ):
        """Register a socket without replacing an existing bound socket."""
        self._ws_connect_count += 1
        self._ws_connected_at = time.time()
        socket_key = id(ws)
        fields = self._identity_fields(identity)
        session_id = fields["extension_session_id"]
        if session_id:
            self.register_extension_identity(ws, fields)
            self._record_session_diagnostics(session_id, identity)
        else:
            pending_id = f"__pending_socket_{socket_key}"
            self._socket_session_ids[socket_key] = pending_id
            self._unidentified_sockets[socket_key] = {
                "session_id": pending_id,
                "websocket": ws,
                "connected_at": self._ws_connected_at,
                "identity_ready": False,
                "require_identity": bool(require_identity),
            }
        # This compatibility pointer is only used when there is no selected
        # identity-bearing session.  A new socket must never overwrite a pinned
        # or already-active operation socket.
        if (
            self._extension_ws is None
            and self._active_extension_session_id is None
            and self._pinned_extension_session_id is None
        ):
            self._extension_ws = ws
        logger.info(
            "Extension connected #%d session=%s active=%s pinned=%s",
            self._ws_connect_count,
            session_id or "pending",
            self._active_extension_session_id or "none",
            self._pinned_extension_session_id or "none",
        )
        return session_id or None

    def register_extension_identity(self, ws, identity: dict) -> str | None:
        """Attach the service-worker identity to the socket that sent it."""
        fields = self._identity_fields(identity)
        session_id = fields["extension_session_id"]
        if not session_id:
            return None
        socket_key = id(ws)
        old_id = self._socket_session_ids.get(socket_key)
        if old_id and old_id != session_id:
            self._unidentified_sockets.pop(socket_key, None)
            old_record = self._extension_sessions.get(old_id)
            if old_record and old_record.get("websocket") is ws:
                self._extension_sessions.pop(old_id, None)
        previous_record = self._extension_sessions.get(session_id)
        record = previous_record or {
            "session_id": session_id,
            "connected_at": time.time(),
            "diagnostics": {},
        }
        record.update({
            "websocket": ws,
            "identity_ready": True,
            **fields,
        })
        record["diagnostics"] = {
            **(record.get("diagnostics") or {}),
            **fields,
        }
        self._extension_sessions[session_id] = record
        self._socket_session_ids[socket_key] = session_id
        self._unidentified_sockets.pop(socket_key, None)
        if len(self._extension_sessions) > 1:
            self._selection_locked = True
        if (
            self._extension_ws is None
            and self._active_extension_session_id is None
            and self._pinned_extension_session_id is None
        ):
            self._extension_ws = ws
        elif previous_record and self._extension_ws is previous_record.get("websocket"):
            # A reconnect with the same worker identity replaces the transport
            # inside the existing session. Keep the compatibility pointer on
            # the current socket so the stale socket's later close cannot
            # clear the live connection.
            self._extension_ws = ws
        return session_id

    def _record_session_diagnostics(self, session_id: str | None, payload: dict | None):
        if not session_id or session_id not in self._extension_sessions:
            return
        payload = payload if isinstance(payload, dict) else {}
        allowed = (
            "extension_id", "extension_version", "extension_build",
            "background_build_id", "build_sha", "build_stamped", "build_dirty",
            "extension_root_url", "flow_tab_id", "flow_url", "flow_project_url",
            "flow_project_id", "content_build_id", "content_script_alive",
            "content_script_loaded", "content_script_protocol_version",
            "extension_build_match", "challenge_verified",
            "session_challenge_verified", "same_extension_session", "same_flow_tab",
            "runtime_ready", "build_match", "flow_tab_found", "last_updated_at",
            "flowKeyPresent", "flow_key_present",
        )
        diagnostics = self._extension_sessions[session_id].setdefault("diagnostics", {})
        for key in allowed:
            if key in payload:
                diagnostics[key] = payload[key]
        for key in (
            "extension_id", "extension_version", "extension_build",
        ):
            if payload.get(key):
                self._extension_sessions[session_id][key] = payload[key]

    def clear_extension_socket(self, ws) -> bool:
        """Remove exactly ``ws``; never promote another socket into its place."""
        socket_key = id(ws)
        session_id = self._socket_session_ids.pop(socket_key, None)
        was_aggregate_socket = self._extension_ws is ws
        current_session_socket = False
        if session_id and session_id.startswith("__pending_socket_"):
            self._unidentified_sockets.pop(socket_key, None)
        elif session_id:
            record = self._extension_sessions.get(session_id)
            if record and record.get("websocket") is ws:
                current_session_socket = True
                self._extension_sessions.pop(session_id, None)
        self._unidentified_sockets.pop(socket_key, None)
        if was_aggregate_socket:
            self._extension_ws = None
        if current_session_socket and session_id and self._active_extension_session_id == session_id:
            self._active_extension_session_id = None
        if current_session_socket and session_id and self._pinned_extension_session_id == session_id:
            # Keep the pin as a durable fail-closed marker.  A later socket must
            # be explicitly rebound; it may not silently take this operation.
            self._last_arbitration_error = "PINNED_EXTENSION_SESSION_DISCONNECTED"
        self._ws_disconnect_count += 1
        self._ws_last_disconnect_at = time.time()
        if (
            current_session_socket
            or was_aggregate_socket
            or (session_id is not None and session_id.startswith("__pending_socket_"))
        ):
            self._cancel_pending_for_session(session_id)
        logger.warning(
            "Extension disconnected session=%s current=%s active=%s pinned=%s; no promotion",
            session_id or "pending",
            current_session_socket,
            self._active_extension_session_id or "none",
            self._pinned_extension_session_id or "none",
        )
        return True

    def clear_extension(self):
        """Compatibility clear for callers that do not have the socket object."""
        ws = self._extension_ws
        if ws is not None:
            self.clear_extension_socket(ws)
            return
        self._ws_disconnect_count += 1
        self._ws_last_disconnect_at = time.time()
        # Cancel all pending futures (copy to avoid RuntimeError on concurrent modification)
        self._cancel_pending_for_session(None)

    def _cancel_pending_for_session(self, session_id: str | None):
        pending_copy = [
            (req_id, future)
            for req_id, future in self._pending.items()
            if session_id is None or self._pending_session_ids.get(req_id) == session_id
        ]
        for req_id, future in pending_copy:
            if not future.done():
                future.set_exception(ConnectionError("Extension disconnected"))
            self._pending.pop(req_id, None)
            self._pending_session_ids.pop(req_id, None)
        if pending_copy:
            logger.warning(
                "Extension disconnected session=%s, cleared %d pending requests",
                session_id or "all",
                len(pending_copy),
            )

    def pin_extension_session(self, session_id: str, binding: dict | None = None) -> bool:
        """Pin all subsequent transport calls to one connected extension session."""
        session_id = str(session_id or "").strip()
        record = self._extension_sessions.get(session_id)
        if not session_id or not record or not self._safe_ws_open(record.get("websocket")):
            self._last_arbitration_error = "PINNED_EXTENSION_SESSION_UNAVAILABLE"
            return False
        self._selection_locked = True
        self._active_extension_session_id = session_id
        self._pinned_extension_session_id = session_id
        self._pinned_binding = dict(binding or {})
        self._extension_ws = record["websocket"]
        self._last_arbitration_error = None
        return True

    def unpin_extension_session(self, session_id: str | None = None):
        """Release a completed pin without selecting a replacement socket."""
        if session_id and self._pinned_extension_session_id != session_id:
            return
        released_session_id = self._pinned_extension_session_id
        self._pinned_extension_session_id = None
        self._pinned_binding = {}
        if released_session_id and self._active_extension_session_id == released_session_id:
            self._active_extension_session_id = None
        self._selection_locked = False

    @property
    def extension_diagnostics(self) -> dict:
        """Safe bridge identity diagnostics; websocket objects and secrets omitted."""
        sessions = []
        for session_id, record in self._extension_sessions.items():
            sessions.append({
                "extension_session_id": session_id,
                "extension_id": record.get("extension_id"),
                "extension_version": record.get("extension_version"),
                "extension_build": record.get("extension_build"),
                "connected": self._safe_ws_open(record.get("websocket")),
                "connected_at": record.get("connected_at"),
                **(record.get("diagnostics") or {}),
            })
        return {
            "ws_counts": {
                "connects": self._ws_connect_count,
                "disconnects": self._ws_disconnect_count,
            },
            "connects": self._ws_connect_count,
            "disconnects": self._ws_disconnect_count,
            "active_extension_session_id": self._active_extension_session_id,
            "pinned_extension_session_id": self._pinned_extension_session_id,
            "pinned_binding": {
                key: value
                for key, value in (self._pinned_binding or {}).items()
                if key in {
                    "extension_session_id", "extension_id", "extension_build",
                    "content_build_id", "flow_tab_id", "project_id", "flow_project_id",
                    "challenge_verified", "same_flow_tab",
                }
            },
            "last_arbitration_error": self._last_arbitration_error,
            "extension_sessions": sessions,
        }

    def set_flow_key(self, key: str):
        self._flow_key = key

    @property
    def connected(self) -> bool:
        return bool(
            self._extension_ws is not None
            or any(self._safe_ws_open(item.get("websocket")) for item in self._extension_sessions.values())
            or self._unidentified_sockets
            or getattr(self, "_mock_connected", False)
        )

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
            **self.extension_diagnostics,
        }

    async def handle_message(self, data: dict, websocket=None):
        """Handle incoming message from extension."""
        if data.get("type") == "token_captured":
            session_id = self._socket_session_ids.get(id(websocket)) if websocket else None
            if session_id:
                self._record_session_diagnostics(session_id, {"flow_key_present": bool(data.get("flowKey"))})
            # Preserve the legacy aggregate flag but do not allow an unrelated
            # later socket to become the operation's auth authority.
            if (
                not self._pinned_extension_session_id
                or session_id == self._pinned_extension_session_id
                or session_id == self._active_extension_session_id
            ):
                self._flow_key = data.get("flowKey")
            logger.info("Flow key captured from extension")
            asyncio.create_task(self._sync_tier())
            return

        if data.get("type") == "extension_ready":
            session_id = self.register_extension_identity(websocket, data) if websocket else None
            if session_id:
                self._record_session_diagnostics(session_id, data)
            logger.info("Extension ready, flowKey=%s", "yes" if data.get("flowKeyPresent") else "no")
            asyncio.create_task(self._sync_tier())
            return

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
            return

        if data.get("type") == "pong":
            return

        if data.get("type") == "ping":
            # Respond to keepalive
            target = websocket or self._extension_ws
            if target:
                await target.send(json.dumps({"type": "pong"}))
            return

        # Response to a pending request
        req_id = data.get("id")
        if req_id and req_id in self._pending:
            self._record_session_diagnostics(
                self._pending_session_ids.get(req_id),
                data.get("result") if isinstance(data.get("result"), dict) else data,
            )
            if not self._pending[req_id].done():
                self._pending[req_id].set_result(data)
            return

    async def _sync_tier(self):
        """Detect current tier from credits API and update all active projects."""
        if getattr(self, '_sync_in_progress', False):
            return
        self._sync_in_progress = True
        try:
            result = await self.get_credits()
            data = result.get("data", result)
            tier = data.get("userPaygateTier", "PAYGATE_TIER_ONE")
            logger.info("Syncing tier: %s", tier)

            from agent.db import crud
            projects = await crud.list_projects(status="ACTIVE")
            for p in projects:
                if p.get("user_paygate_tier") != tier:
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

    def _resolve_extension_socket(self, session_id: str | None = None):
        """Resolve a socket without ever promoting an unrelated connection."""
        requested = str(session_id or "").strip() or None
        selected = requested or self._pinned_extension_session_id or self._active_extension_session_id
        if selected:
            record = self._extension_sessions.get(selected)
            if not record or not self._safe_ws_open(record.get("websocket")):
                error = (
                    "PINNED_EXTENSION_SESSION_DISCONNECTED"
                    if self._pinned_extension_session_id == selected
                    else "ACTIVE_EXTENSION_SESSION_DISCONNECTED"
                )
                self._last_arbitration_error = error
                return None, selected, error
            return record.get("websocket"), selected, None

        sessions = [
            (sid, record)
            for sid, record in self._extension_sessions.items()
            if record.get("identity_ready") and self._safe_ws_open(record.get("websocket"))
        ]
        if len(sessions) > 1:
            self._last_arbitration_error = "AMBIGUOUS"
            return None, None, "AMBIGUOUS"
        if len(sessions) == 1 and not self._selection_locked:
            sid, record = sessions[0]
            self._active_extension_session_id = sid
            return record.get("websocket"), sid, None
        if any(item.get("require_identity") for item in self._unidentified_sockets.values()):
            self._last_arbitration_error = "EXTENSION_SESSION_ID_MISSING"
            return None, None, "EXTENSION_SESSION_ID_MISSING"
        if self._extension_ws is not None and not self._extension_sessions:
            # Compatibility for provider-free unit fakes that assign the old
            # pointer directly. Real extension sockets must complete identity
            # handshake before they are eligible for provider work.
            return self._extension_ws, None, None
        self._last_arbitration_error = "EXTENSION_NOT_CONNECTED"
        return None, None, "EXTENSION_NOT_CONNECTED"

    async def _send(
        self,
        method: str,
        params: dict,
        timeout: float = 300,
        *,
        session_id: str | None = None,
    ) -> dict:
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
        target_ws, target_session_id, arbitration_error = self._resolve_extension_socket(session_id)
        if arbitration_error:
            if arbitration_error == "EXTENSION_NOT_CONNECTED" and getattr(self, "_mock_connected", False):
                target_ws = None
            else:
                return {
                    "error": arbitration_error,
                    "primary_blocker": arbitration_error,
                    "bridge_diagnostics": self.extension_diagnostics,
                }
        if not target_ws:
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

        req_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        self._pending_session_ids[req_id] = target_session_id

        try:
            await target_ws.send(json.dumps({
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
            self._pending_session_ids.pop(req_id, None)

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
                "bridge_diagnostics": self.extension_diagnostics,
            }

        result = await self._send("get_status", {}, timeout=timeout)
        if result.get("error"):
            return {
                "connected": True,
                "state": "unknown",
                "flowKeyPresent": False,
                "manualDisconnect": False,
                "metrics": {},
                "error": result["error"],
                "bridge_diagnostics": self.extension_diagnostics,
            }

        data = result.get("result")
        if isinstance(data, dict):
            data.setdefault("connected", self.connected)
            return data

        return {
            "connected": self.connected,
            "state": "unknown",
            "flowKeyPresent": False,
            "manualDisconnect": False,
            "metrics": {},
            "error": "invalid extension status payload",
            "bridge_diagnostics": self.extension_diagnostics,
        }

    async def _probe_extension_session(
        self,
        session_id: str,
        *,
        flow_tab_id: int | None = None,
        project_id: str | None = None,
        timeout: float = 15,
    ) -> dict:
        """Challenge exactly one socket and return its non-secret identity proof."""
        record = self._extension_sessions.get(session_id) or {}
        nonce = secrets.token_urlsafe(24)
        params = {"nonce": nonce}
        if flow_tab_id is not None:
            params["flow_tab_id"] = int(flow_tab_id)
        if project_id:
            params["flow_project_id"] = str(project_id)
        response = await self._send(
            "FLOW_PROVIDER_SESSION_CHALLENGE",
            params,
            timeout=timeout,
            session_id=session_id,
        )
        payload = response.get("result") if isinstance(response, dict) else None
        if not isinstance(payload, dict):
            payload = response if isinstance(response, dict) else {}
        if isinstance(response, dict) and response.get("error"):
            return {
                "ok": False,
                "extension_session_id": session_id,
                "primary_blocker": response.get("error"),
                "flow_transport_connected": True,
            }

        returned_nonce = str(payload.get("challenge_nonce") or "")
        returned_session_id = str(payload.get("extension_session_id") or "").strip()
        returned_tab_id = payload.get("flow_tab_id")
        try:
            returned_tab_id = int(returned_tab_id) if returned_tab_id is not None else None
        except (TypeError, ValueError):
            returned_tab_id = None
        expected_tab_id = int(flow_tab_id) if flow_tab_id is not None else None
        expected_project_id = str(project_id or "").strip()
        returned_project_id = str(payload.get("flow_project_id") or "").strip()
        expected_build = str(record.get("extension_build") or "").strip()
        returned_build = str(payload.get("extension_build") or "").strip()
        nonce_match = secrets.compare_digest(returned_nonce, nonce)
        same_extension_session = bool(
            returned_session_id and returned_session_id == session_id
        )
        same_extension_identity = bool(
            not record.get("extension_id")
            or not payload.get("extension_id")
            or record.get("extension_id") == payload.get("extension_id")
        )
        same_flow_tab = bool(
            payload.get("same_flow_tab") is True
            or (
                returned_tab_id is not None
                and (expected_tab_id is None or returned_tab_id == expected_tab_id)
                and bool(returned_project_id)
            )
        )
        content_alive = payload.get("content_script_alive") is True
        protocol_match = payload.get("content_script_protocol_version") == "FLOWKIT_DOM_V1"
        extension_build_match = bool(
            payload.get("extension_build_match") is True
            and (not expected_build or not returned_build or expected_build == returned_build)
        )
        project_match = bool(returned_project_id) and (
            not expected_project_id or returned_project_id == expected_project_id
        )
        challenge_verified = bool(
            payload.get("ok") is True
            and nonce_match
            and same_extension_session
            and same_extension_identity
            and same_flow_tab
            and content_alive
            and protocol_match
            and extension_build_match
            and project_match
        )
        result = {
            **payload,
            "ok": challenge_verified,
            "backend_extension_session_id": session_id,
            "challenge_nonce_expected": nonce,
            "challenge_nonce_returned": returned_nonce or None,
            "challenge_nonce_match": nonce_match,
            "same_extension_session": same_extension_session,
            "same_flow_tab": same_flow_tab,
            "content_script_alive": content_alive,
            "content_script_protocol_match": protocol_match,
            "extension_build_match": extension_build_match,
            "project_match": project_match,
            "session_challenge_verified": challenge_verified,
            "flow_transport_connected": True,
            "primary_blocker": None if challenge_verified else (
                "FLOW_PROJECT_NOT_FOUND" if not returned_project_id else
                "PROJECT_TAB_MISMATCH" if not project_match else
                "EXTENSION_BUILD_MISMATCH" if not extension_build_match or not protocol_match else
                "FLOW_SESSION_CHALLENGE_FAILED"
            ),
        }
        self._record_session_diagnostics(session_id, result)
        return result

    async def bind_flow_session(
        self,
        project_id: str | None = None,
        flow_tab_id: int | None = None,
        timeout: float = 15,
    ) -> dict:
        """Select exactly one eligible extension session for one Flow project.

        Selection is deliberately an explicit reconciliation step.  A later
        connection cannot steal a bound operation and a disconnected pinned
        session is never replaced implicitly.
        """
        requested_project_id = str(project_id or "").strip() or None
        pinned_record = self._extension_sessions.get(self._pinned_extension_session_id or "")
        pinned_project_id = str(
            (self._pinned_binding or {}).get("project_id")
            or (self._pinned_binding or {}).get("flow_project_id")
            or ""
        ).strip()
        pinned_tab_id = (self._pinned_binding or {}).get("flow_tab_id")
        pinned_is_same_request = bool(
            self._pinned_extension_session_id
            and pinned_record
            and self._safe_ws_open(pinned_record.get("websocket"))
            and (not requested_project_id or requested_project_id == pinned_project_id)
            and (flow_tab_id is None or flow_tab_id == pinned_tab_id)
        )
        if self._pinned_extension_session_id and not pinned_record:
            self._last_arbitration_error = "PINNED_EXTENSION_SESSION_DISCONNECTED"
            return {
                "ok": False,
                "primary_blocker": "PINNED_EXTENSION_SESSION_DISCONNECTED",
                "flow_transport_connected": self.connected,
                "candidate_diagnostics": [],
                "bridge_diagnostics": self.extension_diagnostics,
            }
        if self._pinned_extension_session_id and not self._safe_ws_open(
            pinned_record.get("websocket")
        ):
            self._last_arbitration_error = "PINNED_EXTENSION_SESSION_DISCONNECTED"
            return {
                "ok": False,
                "primary_blocker": "PINNED_EXTENSION_SESSION_DISCONNECTED",
                "flow_transport_connected": self.connected,
                "candidate_diagnostics": [],
                "bridge_diagnostics": self.extension_diagnostics,
            }
        if self._pinned_extension_session_id and not pinned_is_same_request:
            self._last_arbitration_error = "PINNED_EXTENSION_SESSION_MISMATCH"
            return {
                "ok": False,
                "primary_blocker": "PINNED_EXTENSION_SESSION_MISMATCH",
                "flow_transport_connected": self.connected,
                "candidate_diagnostics": [],
                "bridge_diagnostics": self.extension_diagnostics,
            }
        if pinned_is_same_request:
            candidates = [self._pinned_extension_session_id]
        else:
            candidates = [
                session_id
                for session_id, record in self._extension_sessions.items()
                if record.get("identity_ready") and self._safe_ws_open(record.get("websocket"))
            ]
        if not candidates:
            blocker = (
                "EXTENSION_SESSION_ID_MISSING"
                if self._unidentified_sockets
                else "EXTENSION_BRIDGE_NOT_CONNECTED"
            )
            return {
                "ok": False,
                "primary_blocker": blocker,
                "flow_transport_connected": self.connected,
                "candidate_diagnostics": [],
                "bridge_diagnostics": self.extension_diagnostics,
            }
        probes = await asyncio.gather(*(
            self._probe_extension_session(
                session_id,
                flow_tab_id=flow_tab_id,
                project_id=requested_project_id,
                timeout=timeout,
            )
            for session_id in candidates
        ))
        eligible = [probe for probe in probes if probe.get("ok") is True]
        if len(eligible) > 1:
            self._last_arbitration_error = "AMBIGUOUS"
            return {
                "ok": False,
                "primary_blocker": "AMBIGUOUS",
                "flow_transport_connected": True,
                "candidate_diagnostics": probes,
                "bridge_diagnostics": self.extension_diagnostics,
            }
        if not eligible:
            blockers = {str(probe.get("primary_blocker") or "") for probe in probes}
            if blockers and blockers <= {"FLOW_PROJECT_NOT_FOUND"}:
                blocker = "NO_OPEN_EDITOR"
            elif requested_project_id and blockers and blockers <= {"PROJECT_TAB_MISMATCH"}:
                blocker = "PROJECT_TAB_MISMATCH"
            elif "EXTENSION_BUILD_MISMATCH" in blockers:
                blocker = "EXTENSION_BUILD_MISMATCH"
            else:
                blocker = "NO_ELIGIBLE_EXTENSION_SESSION"
            self._last_arbitration_error = blocker
            return {
                "ok": False,
                "primary_blocker": blocker,
                "flow_transport_connected": True,
                "candidate_diagnostics": probes,
                "bridge_diagnostics": self.extension_diagnostics,
            }

        selected = eligible[0]
        session_id = selected["extension_session_id"]
        record = self._extension_sessions[session_id]
        selected = {
            **(record.get("diagnostics") or {}),
            **selected,
            "flowKeyPresent": bool(
                selected.get("flowKeyPresent")
                or (record.get("diagnostics") or {}).get("flowKeyPresent")
            ),
        }
        binding = {
            "extension_session_id": session_id,
            "extension_id": selected.get("extension_id") or record.get("extension_id"),
            "extension_version": selected.get("extension_version") or record.get("extension_version"),
            "extension_build": selected.get("extension_build") or record.get("extension_build"),
            "content_build_id": selected.get("content_build_id"),
            "content_script_protocol_version": selected.get("content_script_protocol_version"),
            "challenge_verified": True,
            "same_extension_session": True,
            "same_flow_tab": True,
            "flow_tab_id": selected.get("flow_tab_id"),
            "project_id": selected.get("flow_project_id"),
            "flow_project_id": selected.get("flow_project_id"),
            "flow_project_url": selected.get("flow_project_url") or selected.get("flow_url"),
        }
        if not self.pin_extension_session(session_id, binding):
            return {
                "ok": False,
                "primary_blocker": "PINNED_EXTENSION_SESSION_UNAVAILABLE",
                "candidate_diagnostics": probes,
                "bridge_diagnostics": self.extension_diagnostics,
            }
        return {**selected, **binding, "ok": True, "binding": binding}

    async def verify_provider_session_challenge(
        self,
        flow_tab_id: int | None = None,
        timeout: float = 15,
        project_id: str | None = None,
    ) -> dict:
        """Bind and prove one exact extension session/project/tab tuple."""
        return await self.bind_flow_session(
            project_id=project_id,
            flow_tab_id=flow_tab_id,
            timeout=timeout,
        )

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
