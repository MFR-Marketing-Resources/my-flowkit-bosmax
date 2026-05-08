from __future__ import annotations

import json
import uuid
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
    dashboard_serving_mode: str
    repair_command: str
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
    return LocalAgentStatus(
        task_name=LOCAL_AGENT_TASK_NAME,
        health_url=LOCAL_AGENT_HEALTH_URL,
        dashboard_url=LOCAL_AGENT_DASHBOARD_URL,
        dashboard_serving_mode=get_dashboard_serving_mode(),
        repair_command=LOCAL_AGENT_REPAIR_COMMAND,
        registration=load_registration(),
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
