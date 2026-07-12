from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from fastapi import APIRouter, Request
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
LOCAL_AGENT_EXTENSION_STATUS_TIMEOUT_SECONDS = 1.0
LOCAL_AGENT_START_SCRIPT = str((BASE_DIR / "scripts" / "start-local-agent.ps1").resolve())
LOCAL_AGENT_STARTUP_SHORTCUT = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/BOSMAX Flow Kit Local Agent.lnk"


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


@router.post("/capture-video-payload")
async def capture_video_payload(payload: dict[str, Any]):
    """Extension debug hook (webRequest observe). Ack only — no credit, no queue."""
    LOCAL_AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker = payload.get("marker")
    if marker == "hook-loaded":
        return {"ok": True, "marker": marker}
    return {"ok": True, "accepted": True, "has_url": bool(payload.get("url"))}


@router.get("/status", response_model=LocalAgentStatus)
async def get_local_agent_status():
    from agent.services.flow_client import get_flow_client
    client = get_flow_client()
    registration = load_registration()
    extension_status = await client.get_status(
        timeout=LOCAL_AGENT_EXTENSION_STATUS_TIMEOUT_SECONDS,
    )
    autostart = _inspect_autostart_metadata()

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


# ─── Version proof (incident 2026-07-09 guardrail) ──────────────────────────
# The eligibility-audit 404 was a stale-process failure: the running backend
# predated the route while the served dashboard called it. This endpoint makes
# frontend/backend version skew and source-vs-process staleness observable.

_PROCESS_STARTED_AT_DT = datetime.now(timezone.utc)
_PROCESS_STARTED_AT = _PROCESS_STARTED_AT_DT.isoformat()

# Routes whose absence means the process is stale or the app assembly broke.
CRITICAL_ROUTE_PATHS: tuple[str, ...] = (
    "/api/creative-asset-eligibility/audit",
    "/api/creative-assets/eligibility-audit",
    "/api/flow/execute-flow-job",
    "/api/flow/generate",
    "/api/workspace/execution-package",
)


class LocalAgentVersionProof(BaseModel):
    pid: int
    process_started_at: str
    git_head: str | None
    git_branch: str | None
    route_count: int
    critical_routes: dict[str, bool]
    dashboard_bundle: str | None
    source_stale_since_start: bool
    stale_source_sample: list[str]


def _git_output(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=str(BASE_DIR), stderr=subprocess.DEVNULL,
            text=True, timeout=5,
        ).strip() or None
    except Exception:
        return None


def _served_dashboard_bundle() -> str | None:
    try:
        import re

        index_html = (BASE_DIR / "dashboard" / "dist" / "index.html").read_text(
            encoding="utf-8"
        )
        m = re.search(r"assets/(index-[\w-]+\.js)", index_html)
        return m.group(1) if m else None
    except Exception:
        return None


def _stale_backend_sources() -> list[str]:
    """Backend source files modified AFTER this process imported its code.

    A non-empty list means the running route table/services may not match the
    tree on disk — exactly the failure that produced the audit 404."""
    stale: list[str] = []
    started = _PROCESS_STARTED_AT_DT.timestamp()
    try:
        for path in (BASE_DIR / "agent").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.stat().st_mtime > started:
                stale.append(str(path.relative_to(BASE_DIR)))
                if len(stale) >= 5:
                    break
    except Exception:
        pass
    return stale


@router.get("/version-proof", response_model=LocalAgentVersionProof)
async def get_local_agent_version_proof(request: Request) -> LocalAgentVersionProof:
    # Enumerate the SERVED paths authoritatively. In this runtime's process
    # topology `request.app.routes` can under-report (observed 13 vs the 351
    # that /openapi.json and actual routing expose), which false-flagged present
    # routes as missing and fired a spurious "restart the agent" banner. The
    # OpenAPI schema is the same source /openapi.json serves, so union it in;
    # a route genuinely absent from BOTH is still reported missing (guardrail
    # intent preserved).
    route_paths = {getattr(r, "path", "") for r in request.app.routes}
    try:
        route_paths |= set(request.app.openapi().get("paths", {}).keys())
    except Exception:  # openapi generation must never break the health guardrail
        pass
    stale = _stale_backend_sources()
    return LocalAgentVersionProof(
        pid=os.getpid(),
        process_started_at=_PROCESS_STARTED_AT,
        git_head=_git_output("rev-parse", "HEAD"),
        git_branch=_git_output("rev-parse", "--abbrev-ref", "HEAD"),
        route_count=len(route_paths),
        critical_routes={p: p in route_paths for p in CRITICAL_ROUTE_PATHS},
        dashboard_bundle=_served_dashboard_bundle(),
        source_stale_since_start=bool(stale),
        stale_source_sample=stale,
    )
