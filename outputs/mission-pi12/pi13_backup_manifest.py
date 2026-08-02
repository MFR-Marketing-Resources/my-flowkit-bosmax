#!/usr/bin/env python
"""PI-13 B-03: durable backup manifest with restore test (no DB file committed, only the manifest)."""
import hashlib, json, os, shutil, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "flow_agent.db"
BACKUP = REPO / ".ai" / "backups" / "flow_agent_PRE_PI13_20260802T192007Z.db"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


live_sha = sha(LIVE)
bk_sha = sha(BACKUP)
st = os.stat(BACKUP)
# restore test: copy backup to a temp path, verify sha matches, discard (does NOT touch live DB)
restore_status = "UNTESTED"
try:
    tmp = Path(tempfile.gettempdir()) / "pi13_restore_test.db"
    shutil.copy2(BACKUP, tmp)
    restore_status = "PASS (temp restore sha == backup sha)" if sha(tmp) == bk_sha else "FAIL (sha mismatch)"
    tmp.unlink(missing_ok=True)
except Exception as e:
    restore_status = f"ERROR: {e}"

manifest = {
    "live_db_path": str(LIVE),
    "live_db_sha256": live_sha,
    "backup_path": str(BACKUP),
    "backup_sha256": bk_sha,
    "file_size_bytes": st.st_size,
    "created_at_mtime_utc": __import__("datetime").datetime.fromtimestamp(st.st_mtime, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "backup_method": "cp flow_agent.db .ai/backups/flow_agent_PRE_PI13_20260802T192007Z.db",
    "restore_command": "1) stop runtime (start-local-agent stop / kill pid) 2) cp .ai/backups/flow_agent_PRE_PI13_20260802T192007Z.db flow_agent.db 3) start-local-agent.ps1 -ForceRestart",
    "restore_test_status": restore_status,
    "backup_equals_live_at_capture": live_sha == bk_sha,
}
json.dump(manifest, open(REPO / "outputs/mission-pi12/pi13_backup_manifest.json", "w", encoding="utf-8"), indent=1)
print(json.dumps(manifest, indent=1))
