"""Unit tests for the bound-editor-session + single-flight logic (patches A/G/H).

Pure logic — no network, no credits. Exercises _bind_editor_session fail-closed paths
and the single-flight video lane in start_generate via a fake client.
"""
import asyncio

import agent.services.make_video as mv


class _FakeClient:
    def __init__(self, harvest):
        self._harvest = harvest

    async def harvest_video_urls(self):
        return self._harvest


def _run(coro):
    return asyncio.run(coro)


def _harvest(project_id=None, url=None, tab_id=1, found=True, error=None):
    inner = {"flow_tab_found": found, "flow_tab_id": tab_id,
             "flow_url": url, "diag": {"projectId": project_id}}
    if error:
        inner = {"error": error}
    return {"result": inner}


def test_bind_ok():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    b = _run(mv._bind_editor_session(_FakeClient(_harvest("abc-123", url, 42))))
    assert b == {"project_id": "abc-123", "flow_tab_id": 42, "flow_project_url": url}


def test_bind_no_editor_url_raises():
    # tab on Flow home (no /project/) → fail-closed
    h = _harvest("abc", "https://labs.google/fx/tools/flow")
    try:
        _run(mv._bind_editor_session(_FakeClient(h)))
        assert False, "expected NO_OPEN_EDITOR"
    except RuntimeError as e:
        assert "NO_OPEN_EDITOR" in str(e)


def test_bind_no_tab_raises():
    try:
        _run(mv._bind_editor_session(_FakeClient(_harvest(error="NO_FLOW_TAB"))))
        assert False, "expected NO_OPEN_EDITOR"
    except RuntimeError as e:
        assert "NO_OPEN_EDITOR" in str(e)


def test_bind_project_mismatch_raises():
    url = "https://labs.google/fx/tools/flow/project/real"
    try:
        _run(mv._bind_editor_session(_FakeClient(_harvest("real", url)),
                                     requested_project_id="other"))
        assert False, "expected PROJECT_TAB_MISMATCH"
    except RuntimeError as e:
        assert "PROJECT_TAB_MISMATCH" in str(e)


def test_single_flight_rejects_second_video_job():
    mv._JOBS.clear()
    mv._JOBS["g_active"] = {"status": "GENERATING", "created": mv.time.time()}
    mv._VIDEO_LANE_JOB = "g_active"
    try:
        res = _run(mv.start_generate("T2V", "x"))
        assert res.get("status") == "REJECTED"
        assert res.get("error") == "VIDEO_JOB_IN_FLIGHT"
        assert res.get("active_job") == "g_active"
    finally:
        mv._VIDEO_LANE_JOB = None
        mv._JOBS.clear()


def test_img_not_blocked_by_video_lane():
    # IMG is exempt from single-flight; it must NOT be rejected even if the lane is busy.
    # (We can't run the full IMG job without network, so assert the guard only fires for video.)
    mv._JOBS.clear()
    mv._JOBS["g_active"] = {"status": "GENERATING", "created": mv.time.time()}
    mv._VIDEO_LANE_JOB = "g_active"
    try:
        assert "IMG" not in mv._VIDEO_MODES
        assert mv._job_active("g_active") is True
    finally:
        mv._VIDEO_LANE_JOB = None
        mv._JOBS.clear()


def test_gc_drops_old_finished_jobs():
    mv._JOBS.clear()
    mv._JOBS["old"] = {"status": "DONE", "created": mv.time.time() - (mv._JOB_TTL + 10)}
    mv._JOBS["fresh"] = {"status": "DONE", "created": mv.time.time()}
    mv._JOBS["running"] = {"status": "GENERATING", "created": mv.time.time() - 99999}
    mv._gc_jobs()
    assert "old" not in mv._JOBS
    assert "fresh" in mv._JOBS
    assert "running" in mv._JOBS  # never GC an active job
    mv._JOBS.clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
