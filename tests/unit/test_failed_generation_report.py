"""Failed-generation reporting honesty: time windows + ADR-007 dead-DOM classification.

Seeds FAILED telemetry at known ages (relative to the test's own now) and asserts the
windows, the dead-DOM-lane split, and that NO history is deleted (all-time preserved).
"""
from datetime import datetime, timedelta, timezone

from agent.db import crud
from agent.db.schema import get_db
from agent.services import reporting_service as svc

_NOW = datetime.now(timezone.utc)


def _ts(days: int) -> str:
    return (_NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _seed():
    db = await get_db()
    await db.execute("DELETE FROM request")  # cascades request_telemetry

    async def failed(rid, mode, error_code, days, status="FAILED"):
        pid = f"prod-{rid}"
        await db.execute(
            "INSERT OR IGNORE INTO product (id, raw_product_title, product_display_name, product_short_name, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (pid, rid, rid, rid, _ts(days), _ts(days)),
        )
        await db.execute(
            "INSERT INTO request (id, type, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (rid, "GENERATE_VIDEO", status, _ts(days), _ts(days)),
        )
        await db.execute(
            "INSERT INTO request_telemetry (request_id, request_type, mode, status, error_code, product_id, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (rid, "GENERATE_VIDEO", mode, status, error_code, pid, _ts(days)),
        )

    await failed("r-recent-dead", "F2V", "ERR_F2V_START_BUTTON_NOT_FOUND", 0)  # <24h, dead-DOM
    await failed("r-3d-other", "T2V", "ERR_RENDER_FAILED", 3)                   # <7d, non-dead
    await failed("r-40d-dead", "F2V", "ERR_F2V_SETTINGS_PANEL_NOT_OPEN", 40)    # old, dead-DOM
    # a COMPLETED row must be ignored entirely
    await failed("r-ok", "T2V", None, 0, status="COMPLETED")
    await db.commit()


async def test_windows_are_honest_and_history_preserved():
    await _seed()
    rep = await svc.failed_generation_report()
    w = rep["windows"]
    assert w["last_24h"] == 1          # only r-recent-dead
    assert w["last_7d"] == 2           # + r-3d-other
    assert w["last_30d"] == 2          # 40d one excluded
    assert w["all_time"] == 3          # all FAILED preserved (COMPLETED ignored)
    assert rep["distinct_products_all_time"] == 3


async def test_dead_dom_lane_classified_not_deleted():
    await _seed()
    rep = await svc.failed_generation_report()
    assert rep["dead_dom_lane_count"] == 2       # the two ERR_F2V_* rows
    assert rep["non_dead_lane_count"] == 1       # ERR_RENDER_FAILED
    flags = {e["error_code"]: e["dead_dom_lane"] for e in rep["by_error_code"]}
    assert flags["ERR_F2V_START_BUTTON_NOT_FOUND"] is True
    assert flags["ERR_F2V_SETTINGS_PANEL_NOT_OPEN"] is True
    assert flags["ERR_RENDER_FAILED"] is False


def test_dead_dom_lane_classifier_unit():
    assert svc.is_dead_dom_lane_error("ERR_F2V_ANYTHING") is True
    assert svc.is_dead_dom_lane_error("ERR_CDP_FILE_CHOOSER_TIMEOUT") is True
    assert svc.is_dead_dom_lane_error("ERR_FLOW_EDITOR_REQUIRED") is True
    assert svc.is_dead_dom_lane_error("ERR_RENDER_FAILED") is False
    assert svc.is_dead_dom_lane_error(None) is False
    assert svc.is_dead_dom_lane_error("") is False
