"""Full Phase-2D zero-credit browser validation via live :8100 HTTP."""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8100"
# Sanitized project URLs (truncated IDs in evidence)
PROJECT_MANUAL = (
    "https://labs.google/fx/tools/flow/project/"
    "7bdd0f87-0bec-4efa-bd96-334c5980e638"
)
PROJECT_JOB = "c6c87bdd-7af2-415b-9826-315d53fc8d9b"
MEDIA_RESOURCE_FALLBACK = "69051c7b-1a50-4560-89a8-50795e12ff5c"
JOB_ID_SAMPLE = "vj_0f587cf4389c"


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
    except Exception:
        return "unknown"


def _get(path: str, timeout: int = 45) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post(path: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post_raw(path: str, body: dict | None = None, timeout: int = 180) -> tuple[int, str]:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def _sanitize(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    if isinstance(obj, str):
        s = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            lambda m: m.group(0)[:8] + "…",
            obj,
            flags=re.I,
        )
        s = re.sub(r"C:\\\\Users\\\\[^\\\\]+", "C:\\\\Users\\\\<user>", s)
        s = re.sub(r"/c/Users/[^/]+", "/c/Users/<user>", s, flags=re.I)
        if "ya29." in s or "Bearer " in s:
            return "<redacted>"
        return s[:2000] if len(s) > 2000 else s
    return obj


def _pick_product_image() -> str | None:
    import sqlite3

    db = ROOT / "flow_agent.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(db)
    for row in conn.execute(
        "SELECT local_image_path FROM product "
        "WHERE local_image_path IS NOT NULL AND length(local_image_path) > 10 "
        "LIMIT 20",
    ):
        p = Path(str(row[0]))
        if not p.is_absolute():
            p = ROOT / p
        if p.is_file():
            return str(p.resolve())
    return None


def _prepare_flow_tab(recovery: list[str]) -> None:
    import time as _t

    try:
        _post("/api/operator/reload-extension")
        recovery.append("reload_extension")
        for _ in range(25):
            _t.sleep(2)
            if _get("/health").get("extension_connected"):
                break
    except urllib.error.HTTPError:
        recovery.append("reload_extension_failed")
    _t.sleep(3)
    _post("/api/operator/open-target-flow-project", {
        "flow_project_url": PROJECT_MANUAL,
    })
    recovery.append("open_project_manual")
    _t.sleep(8)
    _post("/api/flow/ui-driver/reload-flow-tab")
    recovery.append("reload_flow_tab")
    for attempt in range(12):
        _t.sleep(5)
        st = _get("/api/flow/ui-driver/state")
        inner = (st.get("state") or st) if isinstance(st, dict) else {}
        if inner.get("composer_found"):
            recovery.append(f"composer_ready_attempt_{attempt + 1}")
            break
    else:
        recovery.append("composer_wait_exhausted")
        _post("/api/operator/open-target-flow-project", {
            "flow_project_url": PROJECT_MANUAL,
        })
        _t.sleep(8)
        _post("/api/flow/ui-driver/reload-flow-tab")
        _t.sleep(12)


def run() -> dict:
    runtime_sha = _git_head()
    out: dict = {
        "validation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_main_sha": runtime_sha,
        "runtime_sha": runtime_sha,
        "extension_manifest_version": "0.2.0",
        "driver_version_expected": "flowui-1.3.2-phase2d-20260712",
        "recovery_actions": [],
        "tests": {},
        "final_status": "PENDING",
    }
    failures: list[str] = []

    try:
        cap_code, cap_body = _post_raw(
            "/api/local-agent/capture-video-payload",
            {"marker": "hook-loaded"},
        )
        out["capture_video_payload_http"] = cap_code
        if cap_code != 200:
            failures.append(f"capture_marker_http_{cap_code}")

        health = _get("/health")
        out["backend_health"] = {
            "ok": True,
            "extension_connected": health.get("extension_connected"),
            "version": health.get("version"),
        }
        if not health.get("extension_connected"):
            failures.append("extension_disconnected")
            out["final_status"] = "BLOCKED_EXTERNAL_DEPENDENCY"
            return out

        _prepare_flow_tab(out["recovery_actions"])

        credits_before = _get("/api/flow/credits")
        out["credit_before"] = credits_before.get("credits") or credits_before

        state = _get("/api/flow/ui-driver/state")
        out["driver_state"] = _sanitize(state)
        st = (state.get("state") or state) if isinstance(state, dict) else {}
        if isinstance(st, dict):
            dv = st.get("driver_version")
            out["ui_driver_version"] = dv
            if dv and "1.3.2" not in str(dv):
                failures.append("stale_driver_version")

        comp = _get("/api/flow/ui-driver/composer-reference")
        out["composer_container"] = _sanitize(comp)
        if not (comp.get("ok") and comp.get("container_evidence")):
            failures.append("composer_container")

        # T2V zero — clear stale first
        try:
            _post("/api/flow/ui-driver/clear-composer-references")
        except Exception:
            pass
        time.sleep(2)
        t2v_code, t2v_body = _post_raw(
            "/api/flow/ui-driver/verify-references",
            {"media_ids": [], "expected_count": 0},
        )
        if t2v_code == 200:
            t2v = json.loads(t2v_body)
            out["t2v_exact_zero"] = _sanitize(t2v)
            if not t2v.get("ok"):
                failures.append("t2v_zero")
        else:
            out["t2v_exact_zero"] = {"http": t2v_code, "detail": _sanitize(t2v_body[:300])}
            failures.append("t2v_zero_http")

        img = _pick_product_image()
        if not img:
            failures.append("no_approved_product_image")
            out["hybrid_exact_one"] = {"ok": False, "error": "NO_LOCAL_PRODUCT_IMAGE"}
        else:
            _post("/api/flow/ui-driver/reload-flow-tab")
            time.sleep(5)
            code, body = _post_raw(
                "/api/flow/ui-driver/hybrid-one-probe",
                {"local_file_path": img},
                timeout=180,
            )
            if code == 200:
                hybrid = json.loads(body)
                out["hybrid_exact_one"] = _sanitize(hybrid)
                if not hybrid.get("ok"):
                    failures.append("hybrid_one")
            else:
                out["hybrid_exact_one"] = {
                    "http": code, "detail": _sanitize(body[:500]),
                }
                failures.append("hybrid_one_http")

        intercept = _post("/api/flow/ui-driver/submit-boundary-probe", timeout=60)
        out["submit_boundary"] = _sanitize(intercept)
        if not (intercept.get("ok") or intercept.get("intercept_only")):
            failures.append("submit_boundary")
        try:
            _post("/api/flow/ui-driver/clear-composer-references")
        except Exception:
            pass

        # Exact video open — durable artifact authority first (recovered
        # Video 1 = latest generated_artifact video bound to its project).
        target_media = MEDIA_RESOURCE_FALLBACK
        target_project = PROJECT_JOB
        seg_ids: list[str] = []
        try:
            import sqlite3
            conn = sqlite3.connect(ROOT / "flow_agent.db")
            art = conn.execute(
                "SELECT media_id, project_id FROM generated_artifact "
                "WHERE artifact_kind = 'video' AND project_id IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
            if art and art[0] and art[1]:
                target_media, target_project = str(art[0]), str(art[1])
                out["open_target_authority"] = "generated_artifact"
            row = conn.execute(
                "SELECT segment_media_ids_json FROM video_production_job "
                "WHERE project_id = ? LIMIT 1",
                (PROJECT_JOB,),
            ).fetchone()
            if row and row[0]:
                seg_ids = [str(x) for x in json.loads(row[0])]
        except Exception:
            pass
        _post("/api/operator/open-target-flow-project", {
            "flow_project_url": (
                f"https://labs.google/fx/tools/flow/project/{target_project}"
            ),
        })
        time.sleep(12)
        _post("/api/flow/ui-driver/reload-flow-tab")
        time.sleep(6)
        harvest = {"video_ids": []}
        try:
            harvest = _get("/api/flow/ui-driver/live-media-ids")
        except urllib.error.HTTPError:
            out["recovery_actions"].append("live_media_ids_route_missing")
        except Exception:
            pass
        out["live_media_harvest"] = _sanitize(harvest)
        media_id = target_media
        out["media_id_used_truncated"] = media_id[:8] + "…"
        open_ok = False
        for attempt in range(3):
            open_payload = {
                "parent_media_resource_id": target_media,
                "expected_project_id": target_project,
            }
            open_code, open_body = _post_raw(
                "/api/flow/ui-driver/open-video-probe",
                open_payload,
                timeout=75,
            )
            if open_code == 200:
                parsed = json.loads(open_body)
                out["exact_video_open"] = _sanitize(parsed)
                open_ok = bool(parsed.get("ok"))
                if open_ok:
                    break
            else:
                out["exact_video_open"] = {
                    "http": open_code,
                    "detail": _sanitize(open_body[:400]),
                    "media_tried": target_media[:8] + "…",
                }
            time.sleep(3)
            _post("/api/flow/ui-driver/reload-flow-tab")
            time.sleep(6)
        if not open_ok:
            failures.append("exact_video_open")
        typed_media_id = seg_ids[0] if seg_ids else media_id

        typed_code, typed_body = _post_raw(
            "/api/flow/native-extend/resolve-source",
            {
                "media_id": typed_media_id,
                "project_id": PROJECT_JOB,
            },
        )
        if typed_code == 200:
            typed = json.loads(typed_body)
            out["typed_identifiers"] = _sanitize({
                "media_resource_id": typed.get("media_id") or typed_media_id[:8] + "…",
                "workflow_id": typed.get("workflow_id"),
                "primary_media_id": typed.get("primary_media_id"),
                "operation_id": typed.get("source_operation_id"),
                "scene_id": (typed.get("scene_id") or "")[:8] + "…" if typed.get("scene_id") else None,
                "project_id": PROJECT_JOB[:8] + "…",
            })
        else:
            out["typed_identifiers"] = {"http": typed_code, "detail": _sanitize(typed_body[:300])}
            failures.append("typed_identifiers")

        # Download — after open-video detail when possible; else project grid retries
        if not open_ok:
            _post("/api/operator/open-target-flow-project", {
                "flow_project_url": (
                    f"https://labs.google/fx/tools/flow/project/{target_project}"
                ),
            })
            time.sleep(10)
            _post("/api/flow/ui-driver/reload-flow-tab")
            time.sleep(6)
        else:
            time.sleep(2)
        dl_ok = False
        dl_code = 0
        dl_contexts: list[tuple[str, str | None]] = []
        if open_ok:
            dl_contexts.append(("job_detail", None))
        dl_contexts.append(("manual_export", PROJECT_MANUAL))
        for ctx_name, project_url in dl_contexts:
            if project_url:
                _post("/api/operator/open-target-flow-project", {
                    "flow_project_url": project_url,
                })
                time.sleep(10)
                _post("/api/flow/ui-driver/reload-flow-tab")
                time.sleep(6)
            for attempt in range(2):
                dl_code, dl_body = _post_raw(
                    "/api/flow/ui-driver/download-project",
                    {
                        "register": False,
                        "require_final_lineage": False,
                        "project_id": PROJECT_JOB[:8] + "…",
                    },
                    timeout=200,
                )
                if dl_code == 200:
                    dl = json.loads(dl_body)
                    out["download_project"] = _sanitize({
                        "ok": dl.get("ok"),
                        "bytes": dl.get("bytes"),
                        "sha256": dl.get("sha256"),
                        "is_zip": dl.get("is_zip"),
                        "zip_entry_count": len(dl.get("zip_entries") or []),
                        "artifact_kind": dl.get("artifact_kind"),
                        "attempt": attempt + 1,
                        "context": ctx_name,
                    })
                    dl_ok = bool(dl.get("ok") and dl.get("bytes"))
                    if dl_ok:
                        break
                else:
                    out["download_project"] = {
                        "http": dl_code,
                        "detail": _sanitize(dl_body[:400]),
                        "attempt": attempt + 1,
                        "context": ctx_name,
                    }
                time.sleep(4)
            if dl_ok:
                break
        if not dl_ok:
            if dl_code != 200:
                failures.append("download_project_http")
            else:
                failures.append("download_project")
            if out.get("download_project", {}).get("is_zip") is False:
                failures.append("download_not_zip")

        credits_after = _get("/api/flow/credits")
        out["credit_after"] = credits_after.get("credits") or credits_after
        out["credit_unchanged"] = (
            json.dumps(out["credit_before"], sort_keys=True)
            == json.dumps(out["credit_after"], sort_keys=True)
        )
        if not out["credit_unchanged"]:
            failures.append("credit_changed")
            out["final_status"] = "BLOCKED_EXTERNAL_DEPENDENCY"
            return out

        if failures:
            out["failure_codes"] = failures
            out["final_status"] = "BLOCKED_CURRENT_FLOW_UI_CONTRACT"
        else:
            out["final_status"] = "PHASE_2D_REAL_BROWSER_VALIDATION_PASSED"

    except Exception as exc:
        out["final_status"] = "BLOCKED_EXTERNAL_DEPENDENCY"
        out["error"] = str(exc)[:300]

    return out


def main() -> int:
    evidence = run()
    dest = ROOT / "docs" / "evidence" / "phase2d_real_browser_validation.sanitized.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    ok = evidence.get("final_status") == "PHASE_2D_REAL_BROWSER_VALIDATION_PASSED"
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())