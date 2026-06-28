from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent.config import BASE_DIR

router = APIRouter(prefix="/api/local-agent", tags=["local-agent"])

LOCAL_AGENT_TASK_NAME = "BOSMAX Flow Kit Local Agent"
LOCAL_AGENT_STATE_DIR = BASE_DIR / ".local-agent"
LOCAL_AGENT_REGISTRATION_FILE = LOCAL_AGENT_STATE_DIR / "registration.json"
LOCAL_AGENT_REPAIR_COMMAND = r".\scripts\install-local-agent.ps1"
LOCAL_AGENT_DASHBOARD_URL = "http://127.0.0.1:8100/operator"
LOCAL_AGENT_HEALTH_URL = "http://127.0.0.1:8100/health"
LOCAL_AGENT_CONTENT_PACK_URL = "http://127.0.0.1:8100/api/operator/content-pack"
LOCAL_AGENT_START_SCRIPT = str((BASE_DIR / "scripts" / "start-local-agent.ps1").resolve())
LOCAL_AGENT_STARTUP_SHORTCUT = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/BOSMAX Flow Kit Local Agent.lnk"
AUTOSTART_METADATA_CACHE_TTL_SECONDS = 300


class LocalAgentRegistration(BaseModel):
    operator_id: str | None = None
    device_id: str
    approval_status: str
    license_status: str
    registered_at: str | None = None
    updated_at: str


class LocalAgentStatus(BaseModel):
    task_name: str
    health_url: str
    dashboard_url: str
    content_pack_url: str
    dashboard_serving_mode: str
    repair_command: str
    extension_connected: bool
    extension_state: str
    offline_reason: str | None = None
    auto_start_enabled: bool = False
    auto_start_mode: str = "DISABLED"
    auto_start_warning: str | None = None
    last_health_check: str | None = None
    license_status: str
    approval_status: str
    registration: LocalAgentRegistration


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_registration() -> LocalAgentRegistration:
    now = _iso_now()
    device_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bosmax-flowkit::{BASE_DIR.resolve()}"))
    return LocalAgentRegistration(
        operator_id=None,
        device_id=device_id,
        approval_status="PENDING_APPROVAL",
        license_status="UNLICENSED",
        registered_at=None,
        updated_at=now,
    )


def get_dashboard_paths() -> tuple[Path, Path]:
    dist_dir = BASE_DIR / "dashboard" / "dist"
    return dist_dir, dist_dir / "index.html"


def get_dashboard_serving_mode() -> str:
    _, index_file = get_dashboard_paths()
    return "BACKEND_SERVED_STATIC" if index_file.exists() else "BACKEND_BUILD_REQUIRED"


def _file_sha1(path: Path) -> str | None:
    try:
        return sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _file_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _dashboard_asset_manifest(dist_dir: Path) -> list[dict[str, str | int | None]]:
    assets_dir = dist_dir / "assets"
    if not assets_dir.exists():
        return []

    manifest: list[dict[str, str | int | None]] = []
    for candidate in sorted(assets_dir.iterdir()):
        if not candidate.is_file():
            continue
        manifest.append(
            {
                "name": candidate.name,
                "size_bytes": candidate.stat().st_size,
                "sha1": _file_sha1(candidate),
                "modified_at": _file_mtime_iso(candidate),
            }
        )
    return manifest[:12]


def _ps_single_quote(value: str) -> str:
    return value.replace("'", "''")


def _autostart_metadata_defaults() -> dict[str, str | bool | None]:
    return {
        "enabled": False,
        "mode": "DISABLED",
        "warning": None,
        "scheduled_task_name": None,
        "startup_shortcut_exists": False,
        "startup_shortcut_matches": False,
    }


_AUTOSTART_METADATA_CACHE = _autostart_metadata_defaults()
_AUTOSTART_METADATA_CACHE_AT = 0.0
_AUTOSTART_METADATA_REFRESH_TASK: asyncio.Task | None = None


def _inspect_autostart_metadata() -> dict[str, str | bool | None]:
    if os.name != "nt":
        return _autostart_metadata_defaults()

    script_path = _ps_single_quote(LOCAL_AGENT_START_SCRIPT)
    shortcut_path = _ps_single_quote(str(LOCAL_AGENT_STARTUP_SHORTCUT))
    command = f"""
$repoStart = '{script_path}'
$shortcutPath = '{shortcut_path}'
$result = @{{
  enabled = $false
  mode = 'DISABLED'
  warning = $null
  scheduled_task_name = $null
  startup_shortcut_exists = Test-Path $shortcutPath
  startup_shortcut_matches = $false
}}
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {{
  $_.TaskName -like '*Flow Kit*' -or $_.TaskName -like '*BOSMAX*'
}}
foreach ($task in @($tasks)) {{
  foreach ($action in @($task.Actions)) {{
    $execute = if ($null -ne $action.Execute) {{ [string]$action.Execute }} else {{ '' }}
    $arguments = if ($null -ne $action.Arguments) {{ [string]$action.Arguments }} else {{ '' }}
    $combined = $execute + ' ' + $arguments
    if ($combined -like \"*$repoStart*\") {{
      $result.enabled = $true
      $result.mode = 'SCHEDULED_TASK'
      $result.scheduled_task_name = $task.TaskName
      break
    }}
  }}
  if ($result.enabled) {{ break }}
}}
if ($result.startup_shortcut_exists) {{
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $targetPath = if ($null -ne $shortcut.TargetPath) {{ [string]$shortcut.TargetPath }} else {{ '' }}
  $shortcutArguments = if ($null -ne $shortcut.Arguments) {{ [string]$shortcut.Arguments }} else {{ '' }}
  $workingDirectory = if ($null -ne $shortcut.WorkingDirectory) {{ [string]$shortcut.WorkingDirectory }} else {{ '' }}
  $combinedShortcut = $targetPath + ' ' + $shortcutArguments + ' ' + $workingDirectory
  if ($combinedShortcut -like \"*$repoStart*\") {{
    $result.startup_shortcut_matches = $true
    if (-not $result.enabled) {{
      $result.enabled = $true
      $result.mode = 'STARTUP_SHORTCUT'
    }}
  }} elseif (-not $result.enabled) {{
    $result.mode = 'DISABLED'
    $result.warning = 'STARTUP_SHORTCUT_TARGET_MISMATCH'
  }} else {{
    $result.warning = 'STALE_STARTUP_SHORTCUT_PRESENT'
  }}
}}
$result | ConvertTo-Json -Compress
""".strip()

    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return _autostart_metadata_defaults()

    if completed.returncode != 0:
        return _autostart_metadata_defaults()

    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return _autostart_metadata_defaults()

    defaults = _autostart_metadata_defaults()
    defaults.update(payload)
    return defaults


def _refresh_autostart_metadata_cache_sync() -> dict[str, str | bool | None]:
    global _AUTOSTART_METADATA_CACHE, _AUTOSTART_METADATA_CACHE_AT
    metadata = _inspect_autostart_metadata()
    _AUTOSTART_METADATA_CACHE = metadata
    _AUTOSTART_METADATA_CACHE_AT = time.monotonic()
    return metadata


async def _get_autostart_metadata_cached() -> dict[str, str | bool | None]:
    global _AUTOSTART_METADATA_REFRESH_TASK

    cache_fresh = (
        _AUTOSTART_METADATA_CACHE_AT > 0
        and (time.monotonic() - _AUTOSTART_METADATA_CACHE_AT) < AUTOSTART_METADATA_CACHE_TTL_SECONDS
    )
    if cache_fresh:
        return dict(_AUTOSTART_METADATA_CACHE)

    if _AUTOSTART_METADATA_REFRESH_TASK is None or _AUTOSTART_METADATA_REFRESH_TASK.done():
        _AUTOSTART_METADATA_REFRESH_TASK = asyncio.create_task(
            asyncio.to_thread(_refresh_autostart_metadata_cache_sync)
        )

    return dict(_AUTOSTART_METADATA_CACHE)


def load_registration() -> LocalAgentRegistration:
    LOCAL_AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not LOCAL_AGENT_REGISTRATION_FILE.exists():
        registration = _default_registration()
        LOCAL_AGENT_REGISTRATION_FILE.write_text(
            json.dumps(registration.model_dump(), indent=2),
            encoding="utf-8",
        )
        return registration

    try:
        payload = json.loads(LOCAL_AGENT_REGISTRATION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        registration = _default_registration()
        LOCAL_AGENT_REGISTRATION_FILE.write_text(
            json.dumps(registration.model_dump(), indent=2),
            encoding="utf-8",
        )
        return registration

    registration = LocalAgentRegistration(**payload)
    if not registration.updated_at:
        registration.updated_at = _iso_now()
        LOCAL_AGENT_REGISTRATION_FILE.write_text(
            json.dumps(registration.model_dump(), indent=2),
            encoding="utf-8",
        )
    return registration


@router.get("/status", response_model=LocalAgentStatus)
async def get_local_agent_status():
    from agent.services.flow_client import get_flow_client
    client = get_flow_client()
    registration = load_registration()
    extension_status = await client.get_status(probe_timeout=0)
    autostart = await _get_autostart_metadata_cached()

    offline_reason = None
    if not client.connected:
        offline_reason = "EXTENSION_DISCONNECTED"

    return LocalAgentStatus(
        task_name=str(autostart.get("scheduled_task_name") or LOCAL_AGENT_TASK_NAME),
        health_url=LOCAL_AGENT_HEALTH_URL,
        dashboard_url=LOCAL_AGENT_DASHBOARD_URL,
        content_pack_url=LOCAL_AGENT_CONTENT_PACK_URL,
        dashboard_serving_mode=get_dashboard_serving_mode(),
        repair_command=LOCAL_AGENT_REPAIR_COMMAND,
        extension_connected=client.connected,
        extension_state=(extension_status.get("state") or ("idle" if client.connected else "off")).upper(),
        offline_reason=offline_reason,
        auto_start_enabled=bool(autostart.get("enabled")),
        auto_start_mode=str(autostart.get("mode") or "DISABLED"),
        auto_start_warning=str(autostart.get("warning")) if autostart.get("warning") else None,
        last_health_check=_iso_now(),
        license_status=registration.license_status,
        approval_status=registration.approval_status,
        registration=registration,
    )



@router.get("/registration", response_model=LocalAgentRegistration)
async def get_local_agent_registration():
    return load_registration()


@router.get("/extension-self-test")
async def get_local_agent_extension_self_test(
    mode: str = "F2V",
    attempt_open_project: bool = True,
):
    from agent.config import API_HOST, API_PORT, DB_PATH, WS_HOST, WS_PORT
    from agent.services.flow_client import get_flow_client

    client = get_flow_client()
    dist_dir, index_file = get_dashboard_paths()
    try:
        extension_status = await asyncio.wait_for(client.get_status(), timeout=8)
    except TimeoutError:
        extension_status = {
            "ok": False,
            "connected": getattr(client, "connected", False),
            "error": "ERR_EXTENSION_STATUS_TIMEOUT",
        }
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        extension_status = {
            "ok": False,
            "connected": getattr(client, "connected", False),
            "error": f"ERR_EXTENSION_STATUS_EXCEPTION: {exc}",
        }

    try:
        extension_self_test = await asyncio.wait_for(
            client.get_extension_self_test(
                mode=mode,
                attempt_open_project=attempt_open_project,
            ),
            timeout=20,
        )
    except TimeoutError:
        extension_self_test = {
            "ok": False,
            "connected": getattr(client, "connected", False),
            "error": "ERR_EXTENSION_SELF_TEST_TIMEOUT",
        }
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        extension_self_test = {
            "ok": False,
            "connected": getattr(client, "connected", False),
            "error": f"ERR_EXTENSION_SELF_TEST_EXCEPTION: {exc}",
        }

    return {
        "timestamp": _iso_now(),
        "backend": {
            "base_dir": str(BASE_DIR.resolve()),
            "db_path": str(DB_PATH.resolve()),
            "api_host": API_HOST,
            "api_port": API_PORT,
            "ws_host": WS_HOST,
            "ws_port": WS_PORT,
        },
        "dashboard": {
            "serving_mode": get_dashboard_serving_mode(),
            "dist_dir": str(dist_dir.resolve()),
            "index_file": str(index_file.resolve()),
            "index_exists": index_file.exists(),
            "index_sha1": _file_sha1(index_file),
            "index_modified_at": _file_mtime_iso(index_file),
            "asset_manifest": _dashboard_asset_manifest(dist_dir),
        },
        "extension_status": extension_status,
        "extension_self_test": extension_self_test,
    }


@router.get("/build-proof")
async def get_local_agent_build_proof(mode: str = "F2V"):
    """No-credit, fail-closed build-identity handshake.

    Proves the build currently loaded on the ACTIVE Flow tab. Never reads
    persisted request telemetry (which goes stale across reloads). Returns
    verdict PASS only when background and content builds both equal the repo
    canonical build id, the extension asserts build_match, and the handshake is
    fresh; otherwise BLOCK with an exact reason (NO_FLOW_TAB, MISSING_CONTENT_SCRIPT,
    BUILD_MISMATCH, BACKGROUND_BUILD_MISMATCH, STALE_HANDSHAKE, ...).
    """
    from datetime import datetime, timezone
    from agent.services.flow_client import get_flow_client
    from agent.services.build_proof import (
        BLOCK,
        REASON_EXTENSION_OFFLINE,
        REASON_NO_SELF_TEST,
        evaluate_build_proof,
        read_canonical_build_id,
    )

    expected_build_id = read_canonical_build_id(BASE_DIR)
    client = get_flow_client()
    if not getattr(client, "connected", False):
        return {
            "verdict": BLOCK,
            "reason": REASON_EXTENSION_OFFLINE,
            "detail": "Extension WebSocket is not connected.",
            "expected_build_id": expected_build_id,
            "evaluated_at": _iso_now(),
        }
    try:
        self_test = await asyncio.wait_for(
            client.get_extension_self_test(mode=mode, attempt_open_project=False),
            timeout=20,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return {
            "verdict": BLOCK,
            "reason": REASON_NO_SELF_TEST,
            "detail": f"Self-test failed: {exc}",
            "expected_build_id": expected_build_id,
            "evaluated_at": _iso_now(),
        }

    verdict = evaluate_build_proof(
        self_test, expected_build_id, now=datetime.now(timezone.utc)
    )
    return verdict.as_dict()


@router.get("/reload-flow-tab")
async def get_reload_flow_tab():
    from agent.services.flow_client import get_flow_client
    client = get_flow_client()
    if not client.connected:
        return {"ok": False, "error": "Extension not connected"}
    try:
        return await asyncio.wait_for(client.reload_flow_tab(), timeout=15)
    except Exception as exc:
        return {"ok": False, "error": f"Reload failed: {exc}"}


@router.get("/reload-extension")
async def get_reload_extension():
    from agent.services.flow_client import get_flow_client
    client = get_flow_client()
    if not client.connected:
        return {"ok": False, "error": "Extension not connected"}
    try:
        return await asyncio.wait_for(client._send("RELOAD_EXTENSION", {}), timeout=15)
    except Exception as exc:
        return {"ok": False, "error": f"Extension reload failed: {exc}"}


@router.get("/diagnostic-inputs")
async def get_diagnostic_inputs():
    from agent.services.flow_client import get_flow_client
    client = get_flow_client()
    if not client.connected:
        return {"ok": False, "error": "Extension not connected"}
    js_code = """
    (function() {
      function getElDiagnostics(el) {
        var r = el.getBoundingClientRect();
        var s = window.getComputedStyle(el);
        return {
          tagName: el.tagName,
          id: el.id,
          className: el.className,
          contentEditable: el.contentEditable,
          dataSlateEditor: el.getAttribute('data-slate-editor'),
          placeholder: el.getAttribute('placeholder'),
          ariaLabel: el.getAttribute('aria-label'),
          width: r.width,
          height: r.height,
          left: r.left,
          top: r.top,
          display: s ? s.display : 'none',
          visibility: s ? s.visibility : 'hidden',
          opacity: s ? s.opacity : '0'
        };
      }
      var nodes = document.querySelectorAll('textarea, [contenteditable="true"], input, [data-slate-editor="true"]');
      var results = [];
      for (var i = 0; i < nodes.length; i++) {
        results.push(getElDiagnostics(nodes[i]));
      }
      return results;
    })()
    """
    try:
        raw = await asyncio.wait_for(
            client._send("DEBUG_FLOW_DOM_EXECUTION", {
                "params": {
                    "mode": "eval",
                    "job": {"js": js_code}
                }
            }),
            timeout=20
        )
        return raw
    except Exception as exc:
        return {"ok": False, "error": f"Diagnostic failed: {exc}"}


@router.get("/repair", response_class=HTMLResponse)
async def get_repair_page():
    status = await get_local_agent_status()
    registration = status.registration
    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <title>BOSMAX Flow Kit Local Agent Repair</title>
          <style>
            body {{
              margin: 0;
              padding: 32px;
              background: #0f172a;
              color: #e2e8f0;
              font-family: Consolas, 'Cascadia Code', monospace;
              line-height: 1.6;
            }}
            .card {{
              max-width: 760px;
              margin: 0 auto;
              padding: 24px;
              border: 1px solid #334155;
              border-radius: 16px;
              background: #111827;
            }}
            h1 {{ margin-top: 0; font-size: 24px; }}
            code {{
              display: block;
              margin: 12px 0;
              padding: 12px 14px;
              background: #020617;
              border-radius: 10px;
              border: 1px solid #1e293b;
              white-space: pre-wrap;
            }}
            .muted {{ color: #94a3b8; }}
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Local Agent Repair</h1>
            <p>Use this page only when the local agent is offline or dashboard health checks fail.</p>
            <p>PowerShell is only needed for repair/install diagnostics.</p>
            <p>Run the installer from the repository root to rebuild the production dashboard, re-register the Windows startup task, and restart the local agent.</p>
            <code>{LOCAL_AGENT_REPAIR_COMMAND}</code>
            <p class="muted">Dashboard URL: {status.dashboard_url}</p>
            <p class="muted">Health URL: {status.health_url}</p>
            <p class="muted">Device ID: {registration.device_id}</p>
            <p class="muted">Approval Status: {registration.approval_status}</p>
            <p class="muted">License Status: {registration.license_status}</p>
          </div>
        </body>
        </html>
        """.strip()
    )
