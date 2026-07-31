"""Failed-generation reporting honesty: failed_at time windows + defensible provenance.

Counts failures by COALESCE(failed_at, created_at); classifies only PROVABLE frozen-lane
DOM-UI error codes as dead DOM (loose-pattern/CDP => provenance unverified). No history deleted.
"""
from datetime import datetime, timedelta, timezone

from agent.db.schema import get_db
from agent.services import reporting_service as svc

_NOW = datetime.now(timezone.utc)


def _ts(days: int) -> str:
    return (_NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _seed(rows):
    """rows: (rid, error_code, created_days, failed_days_or_None, status='FAILED')."""
    db = await get_db()
    await db.execute("DELETE FROM request")
    for row in rows:
        rid, ec, cd, fd = row[0], row[1], row[2], row[3]
        status = row[4] if len(row) > 4 else "FAILED"
        pid = f"prod-{rid}"
        await db.execute(
            "INSERT OR IGNORE INTO product (id, raw_product_title, product_display_name, product_short_name, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pid, rid, rid, rid, _ts(cd), _ts(cd)))
        await db.execute(
            "INSERT INTO request (id, type, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (rid, "GENERATE_VIDEO", status, _ts(cd), _ts(cd)))
        await db.execute(
            "INSERT INTO request_telemetry (request_id, request_type, mode, status, error_code, product_id, created_at, failed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (rid, "GENERATE_VIDEO", "F2V", status, ec, pid, _ts(cd), _ts(fd) if fd is not None else None))
    await db.commit()


async def test_windows_counted_by_failed_at():
    await _seed([
        ("r-fa-recent", "ERR_X", 40, 0),     # created old, FAILED recently -> recent
        ("r-fa-old", "ERR_X", 0, 40),        # created recent, FAILED long ago -> not recent
        ("r-fa-null", "ERR_X", 0, None),     # failed_at NULL -> falls back to created_at (recent)
    ])
    rep = await svc.failed_generation_report()
    assert rep["windows_counted_by"] == "COALESCE(failed_at, created_at)"
    assert rep["windows"]["last_24h"] == 2      # r-fa-recent + r-fa-null (NOT r-fa-old)
    assert rep["windows"]["last_7d"] == 2
    assert rep["windows"]["all_time"] == 3      # all preserved


async def test_defensible_provenance_classification():
    await _seed([
        ("r-proven", "ERR_F2V_START_BUTTON_NOT_FOUND", 0, 0),   # provable dead DOM
        ("r-cdp", "ERR_CDP_FILE_CHOOSER_TIMEOUT", 0, 0),        # ADR-007 transport -> unverified
        ("r-f2v-generic", "ERR_F2V_SOMETHING_NEW", 0, 0),       # loose pattern -> unverified
        ("r-other", "ERR_RENDER_FAILED", 0, 0),                 # unrelated -> other
        ("r-ok", None, 0, 0, "COMPLETED"),                      # ignored
    ])
    rep = await svc.failed_generation_report()
    assert rep["dead_dom_lane_count"] == 1          # ONLY r-proven
    assert rep["provenance_unverified_count"] == 2  # cdp + generic F2V
    assert rep["other_count"] == 1                  # r-other
    cls = {e["error_code"]: e["classification"] for e in rep["by_error_code"]}
    assert cls["ERR_F2V_START_BUTTON_NOT_FOUND"] == "dead_dom_lane"
    assert cls["ERR_CDP_FILE_CHOOSER_TIMEOUT"] == "legacy_pattern_provenance_unverified"
    assert cls["ERR_F2V_SOMETHING_NEW"] == "legacy_pattern_provenance_unverified"
    assert cls["ERR_RENDER_FAILED"] == "other"


def test_provenance_classifier_unit():
    assert svc.classify_error_provenance("ERR_F2V_START_BUTTON_NOT_FOUND") == "dead_dom_lane"
    assert svc.classify_error_provenance("ERR_F2V_SETTINGS_PANEL_NOT_OPEN") == "dead_dom_lane"
    # loose pattern / transport -> NOT asserted dead
    assert svc.classify_error_provenance("ERR_F2V_ANYTHING_ELSE") == "legacy_pattern_provenance_unverified"
    assert svc.classify_error_provenance("ERR_CDP_FILE_CHOOSER_TIMEOUT") == "legacy_pattern_provenance_unverified"
    assert svc.classify_error_provenance("ERR_FLOW_EDITOR_REQUIRED") == "legacy_pattern_provenance_unverified"
    assert svc.classify_error_provenance("ERR_RENDER_FAILED") == "other"
    assert svc.classify_error_provenance(None) == "other"
    assert svc.is_dead_dom_lane_error("ERR_F2V_START_BUTTON_NOT_FOUND") is True
    assert svc.is_dead_dom_lane_error("ERR_CDP_FILE_CHOOSER_TIMEOUT") is False
