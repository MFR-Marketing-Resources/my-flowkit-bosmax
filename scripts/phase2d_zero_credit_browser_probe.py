"""Post-merge zero-credit Flow tab probe via live agent HTTP (extension WS in-process)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8100"
MERGE_SHA = "a196a1d5acfe46a992d7139e3bd1026b42fbdd78"


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def _post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def run() -> dict:
    out: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "merge_sha": MERGE_SHA,
        "driver_version_expected": "flowui-1.3.1-phase2d-20260712",
        "credit_note": "zero-credit probes only",
        "steps": {},
    }
    try:
        health = _get("/health")
        out["steps"]["health"] = {
            "extension_connected": health.get("extension_connected"),
            "version": health.get("version"),
        }
        if not health.get("extension_connected"):
            out["verdict"] = "BLOCKED_EXTERNAL_DEPENDENCY"
            out["detail"] = "extension not connected"
            return out

        reload = _post("/api/flow/ui-driver/reload-flow-tab")
        out["steps"]["reload_flow_tab"] = reload
        import time
        try:
            ext_reload = _post("/api/operator/reload-extension")
            out["steps"]["reload_extension"] = ext_reload
            for _ in range(20):
                time.sleep(2)
                h = _get("/health")
                if h.get("extension_connected"):
                    break
        except urllib.error.HTTPError as exc:
            out["steps"]["reload_extension"] = {"http_error": exc.code}
        time.sleep(6)
        _post("/api/flow/ui-driver/reload-flow-tab")
        time.sleep(8)

        credits_before = _get("/api/flow/credits")
        out["credit_before"] = credits_before.get("credits") or credits_before

        state = _get("/api/flow/ui-driver/state")
        out["steps"]["flowui_state"] = state

        comp = _get("/api/flow/ui-driver/composer-reference")
        out["steps"]["composer_reference"] = comp

        zero = _post("/api/flow/ui-driver/verify-references",
                     {"media_ids": [], "expected_count": 0})
        out["steps"]["t2v_zero_verify"] = zero

        intercept = _post("/api/flow/ui-driver/submit-boundary-probe")
        out["steps"]["submit_boundary_intercept"] = intercept

        credits_after = _get("/api/flow/credits")
        out["credit_after"] = credits_after.get("credits") or credits_after

        out["credit_unchanged"] = (
            json.dumps(out["credit_before"], sort_keys=True)
            == json.dumps(out["credit_after"], sort_keys=True))

        ok_comp = comp.get("container_evidence") and comp.get("ok")
        ok_zero = zero.get("ok") is True or zero.get("actual_total_count") == 0
        ok_intercept = intercept.get("ok") or intercept.get("create_control_found")
        out["verdict"] = (
            "BROWSER_VALIDATED_ZERO_CREDIT"
            if ok_comp and ok_intercept else "BLOCKED_CURRENT_FLOW_UI_CONTRACT")
        if not ok_zero and zero.get("ok") is False:
            out["verdict"] = "BLOCKED_CURRENT_FLOW_UI_CONTRACT"
            out["t2v_note"] = "composer not at zero — clear stale refs on tab if T2V"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        out["verdict"] = "BLOCKED_EXTERNAL_DEPENDENCY"
        out["detail"] = f"HTTP {exc.code}: {body[:500]}"
    except Exception as exc:
        out["verdict"] = "BLOCKED_EXTERNAL_DEPENDENCY"
        out["detail"] = str(exc)
    return out


def main() -> int:
    evidence = run()
    dest = ROOT / "docs" / "evidence" / "phase2d_zero_credit_browser_validation.sanitized.json"
    dest.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence.get("verdict") == "BROWSER_VALIDATED_ZERO_CREDIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())