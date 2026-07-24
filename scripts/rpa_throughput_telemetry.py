"""RPA throughput telemetry — measure the REAL single-account video rate.

Read-only. Spends ZERO credits. Reads a production_run (its per-item packages +
error log) and reports the sustained generation rate, throttle behaviour, and the
honest videos/day extrapolation — so a Phase-1 measurement batch tells us whether
ONE account can reach 200/day or whether multi-account parallelism is needed.

Usage:
    python scripts/rpa_throughput_telemetry.py [RUN_ID]
    # no RUN_ID -> the most recent run that actually fired items live.

The numbers here come from a real fired run; before any live fire this prints
"no live run yet". See docs/rpa-throughput-measurement-runbook.md.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB = r"C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db"
_THROTTLE = re.compile(
    r"RATE.?LIMIT|\b429\b|\b403\b|THROTTLE|QUOTA|CAPTCHA|TOO_MANY|COOLDOWN|SILENCE",
    re.IGNORECASE,
)
_TERMINAL_OK = {"DONE", "COMPLETED", "GENERATED", "QA_PASSED", "DOWNLOADED", "SUCCESS"}


def _dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _loads(v, default):
    try:
        return json.loads(v) if v else default
    except Exception:  # noqa: BLE001
        return default


def _fmt_dur(seconds: float | None) -> str:
    if not seconds or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return (f"{h}h " if h else "") + f"{m}m {s}s"


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    if run_id:
        run = con.execute("SELECT * FROM production_run WHERE production_run_id=?", (run_id,)).fetchone()
    else:
        run = con.execute(
            "SELECT * FROM production_run WHERE dry_run=0 AND COALESCE(total_completed,0)+COALESCE(total_failed,0) > 0 "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    if not run:
        print("No LIVE run with fired items found yet.")
        print("This tool measures a live fired batch. Prepare + certify + fire a")
        print("measurement batch first — see docs/rpa-throughput-measurement-runbook.md.")
        con.close()
        return

    run = dict(run)
    rid = run["production_run_id"]
    pkgs = [dict(r) for r in con.execute(
        "SELECT production_status, production_job_id, production_error, updated_at, created_at "
        "FROM workspace_generation_package WHERE production_run_id=? ORDER BY updated_at",
        (rid,),
    ).fetchall()]
    con.close()

    completed = int(run.get("total_completed") or 0)
    failed = int(run.get("total_failed") or 0)
    expected = int(run.get("total_expected") or 0)
    started = _dt(run.get("created_at"))
    ended = _dt(run.get("updated_at"))
    now = datetime.now(timezone.utc)
    elapsed = ((ended or now) - started).total_seconds() if started else None

    errors = _loads(run.get("error_log_json"), [])
    pkg_errors = [p.get("production_error") for p in pkgs if p.get("production_error")]
    throttle_hits = [e for e in (errors + pkg_errors) if e and _THROTTLE.search(str(e))]

    # per-item completion timeline (updated_at of terminal packages)
    done_times = sorted(
        _dt(p.get("updated_at")) for p in pkgs
        if str(p.get("production_status") or "").upper() in _TERMINAL_OK and _dt(p.get("updated_at"))
    )
    gaps = [
        (done_times[i] - done_times[i - 1]).total_seconds()
        for i in range(1, len(done_times))
    ]
    median_gap = sorted(gaps)[len(gaps) // 2] if gaps else None

    rate_hr = (completed / (elapsed / 3600)) if (elapsed and elapsed > 0 and completed) else None

    def A(s):
        return str(s).encode("ascii", "replace").decode("ascii")

    print("=" * 66)
    print("RPA THROUGHPUT TELEMETRY  (read-only, zero credits)")
    print("=" * 66)
    print(f"  run_id        : {rid}")
    print(f"  status        : {run.get('status')}   dry_run={run.get('dry_run')}")
    print(f"  pacing        : interval {run.get('interval_min_seconds')}-{run.get('interval_max_seconds')}s"
          f" · cooldown {run.get('cooldown_seconds')}s / {run.get('cooldown_after_n_jobs')} jobs")
    print(f"  created_at    : {run.get('created_at')}")
    print(f"  last activity : {run.get('updated_at')}")
    print(f"  elapsed       : {_fmt_dur(elapsed)}")
    print("  " + "-" * 62)
    print(f"  fired items   : {completed + failed}"
          f"{f' of {expected} planned' if expected else ''}"
          f"   (completed {completed} · failed {failed})")
    print(f"  THROTTLE hits : {len(throttle_hits)}  (rate-limit / 403 / quota / captcha)")
    print("  " + "-" * 62)
    fired = completed + failed
    SAMPLE_MIN = 10  # below this, one slow/failed item skews the rate — inconclusive
    if rate_hr:
        print(f"  SUSTAINED RATE: {rate_hr:.1f} videos/hour")
        print(f"  -> extrapolated (24h, if sustained): {rate_hr * 24:.0f}/day")
        print(f"  -> extrapolated (12h productive)   : {rate_hr * 12:.0f}/day")
        if fired < SAMPLE_MIN:
            verdict = (f"SAMPLE TOO SMALL ({fired} items) — INCONCLUSIVE. "
                       f"Run a 20-30 item batch for a trustworthy rate.")
        elif rate_hr * 24 >= 230:
            verdict = "ONE ACCOUNT LIKELY ENOUGH for 200/day"
        elif rate_hr * 24 >= 180:
            verdict = "ONE ACCOUNT MARGINAL — measure longer / consider multi-account"
        else:
            verdict = "ONE ACCOUNT NOT ENOUGH for 200/day -> multi-account parallelism needed"
        print(f"  VERDICT       : {verdict}")
    else:
        print("  SUSTAINED RATE: not computable yet (need completed items + timing).")
    if median_gap:
        print(f"  median gap between completions: {_fmt_dur(median_gap)} "
              f"(~{3600/median_gap:.1f}/hr ceiling)")
    if throttle_hits:
        print("\n  first throttle signals:")
        for e in throttle_hits[:5]:
            print(f"    - {A(e)[:80]}")
    print("\n  NOTE: 24h extrapolation assumes the rate HOLDS unthrottled all day.")
    print("  If THROTTLE hits climb over time, the honest sustained/day is lower —")
    print("  that is exactly the signal that says 'add a second account'.")


if __name__ == "__main__":
    main()
