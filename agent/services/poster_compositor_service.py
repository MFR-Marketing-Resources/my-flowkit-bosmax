"""Poster compositor service (POSTER_BUILDER_V2).

Production wrapper around scripts/poster-compositor-render.js (Playwright/
Chromium renderer): concurrency-limited, timeout-guarded subprocess execution
with structured errors and machine-checkable render reports.

Offline + credit-free by construction — the renderer reads local files only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from agent.config import BASE_DIR, OUTPUT_DIR
from agent.models.poster_render_manifest import (
    PosterRenderManifest,
    PosterRenderReport,
)

logger = logging.getLogger(__name__)

RENDER_SCRIPT = BASE_DIR / "scripts" / "poster-compositor-render.js"
POSTER_RENDER_DIR = OUTPUT_DIR / "posters"

COMPOSE_TIMEOUT_S = 45
_MAX_CONCURRENT_RENDERS = 2
_render_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RENDERS)

_probe_cache: dict[str, Any] | None = None


class PosterCompositorError(Exception):
    def __init__(self, code: str, message: str = "", *, status_code: int = 502):
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code


def _node_exe() -> str:
    node = shutil.which("node")
    if not node:
        raise PosterCompositorError(
            "COMPOSITOR_NODE_UNAVAILABLE", "node runtime not found on PATH",
            status_code=503,
        )
    return node


async def probe(*, force: bool = False) -> dict[str, Any]:
    """Verify the renderer runtime (node + Chromium). Cached per process."""
    global _probe_cache
    if _probe_cache is not None and not force:
        return _probe_cache
    node = _node_exe()
    if not RENDER_SCRIPT.exists():
        raise PosterCompositorError(
            "COMPOSITOR_SCRIPT_MISSING", str(RENDER_SCRIPT), status_code=503
        )
    proc = await asyncio.create_subprocess_exec(
        node, str(RENDER_SCRIPT), "--probe",
        cwd=str(BASE_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        raise PosterCompositorError("COMPOSITOR_PROBE_TIMEOUT", status_code=503)
    if proc.returncode != 0:
        raise PosterCompositorError(
            "COMPOSITOR_RUNTIME_UNAVAILABLE",
            (out or err or b"").decode("utf-8", "replace").strip(),
            status_code=503,
        )
    try:
        _probe_cache = json.loads(out.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        _probe_cache = {"chromium_installed": True}
    return _probe_cache


async def compose(
    manifest: PosterRenderManifest, *, render_id: str = ""
) -> tuple[Path, PosterRenderReport]:
    """Render one manifest → (output PNG path, render report).

    Raises PosterCompositorError with a structured code on any failure; a
    best-effort report is attached when the renderer produced one.
    """
    await probe()
    render_id = render_id or uuid.uuid4().hex[:12]
    work_dir = POSTER_RENDER_DIR / render_id
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = work_dir / "manifest.json"
    out_path = work_dir / "poster.png"
    report_path = work_dir / "render_report.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    node = _node_exe()
    async with _render_semaphore:
        proc = await asyncio.create_subprocess_exec(
            node,
            str(RENDER_SCRIPT),
            "--manifest", str(manifest_path),
            "--out", str(out_path),
            "--report", str(report_path),
            "--timeout", str(int(COMPOSE_TIMEOUT_S * 1000) - 5000),
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=COMPOSE_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise PosterCompositorError(
                "COMPOSITOR_TIMEOUT", f"render exceeded {COMPOSE_TIMEOUT_S}s"
            )

    report = _read_report(report_path)
    if proc.returncode != 0:
        detail = (err or out or b"").decode("utf-8", "replace").strip()[-500:]
        code = {
            2: "COMPOSITOR_MANIFEST_INVALID",
            3: "COMPOSITOR_TIMEOUT",
        }.get(proc.returncode, "COMPOSITOR_RENDER_FAILED")
        exc = PosterCompositorError(code, detail, status_code=422 if proc.returncode == 2 else 502)
        exc.report = report  # type: ignore[attr-defined]
        raise exc
    if not out_path.exists():
        raise PosterCompositorError("COMPOSITOR_OUTPUT_MISSING", str(out_path))
    if report is None:
        raise PosterCompositorError("COMPOSITOR_REPORT_MISSING", str(report_path))
    return out_path, report


def _read_report(report_path: Path) -> PosterRenderReport | None:
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return PosterRenderReport.model_validate(
            {
                "renderer": data.get("renderer") or "",
                "canvas": data.get("canvas") or {},
                "output_png": data.get("output_png") or {},
                "zones": [
                    {
                        "zone_id": z.get("zone_id") or "",
                        "fitted": bool(z.get("fitted")),
                        "overflowed": bool(z.get("overflowed")),
                        "overlaps_product": bool(z.get("overlaps_product")),
                        "font_scale": float(z.get("font_scale") or 1.0),
                        "rendered_text": z.get("rendered_text") or "",
                    }
                    for z in data.get("zones") or []
                ],
                "missing_zones": data.get("missing_zones") or [],
                "errors": data.get("errors") or [],
                "ok": bool(data.get("ok")),
            }
        )
    except (ValueError, TypeError) as exc:
        logger.warning("poster render report unreadable: %s", exc)
        return None
