"""Unit tests for the bound-editor-session + single-flight logic (patches A/G/H).

Pure logic — no network, no credits. Exercises _bind_editor_session fail-closed paths
and the single-flight video lane in start_generate via a fake client.
"""
import asyncio

import agent.services.make_video as mv


class _FakeClient:
    def __init__(self, harvest, page_diag=None):
        self._harvest = harvest
        self._page_diag = page_diag

    async def harvest_video_urls(self, tab_id=None):
        return self._harvest

    async def flow_page_state_diagnostic(self, mode=None):
        return self._page_diag or {}


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


def test_bind_broken_editor_page_raises():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"visible_error_markers": ["Something went wrong"], "build_match": True},
    )
    try:
        _run(mv._bind_editor_session(client))
        assert False, "expected BROKEN_EDITOR_PAGE"
    except RuntimeError as e:
        assert "BROKEN_EDITOR_PAGE" in str(e)


def test_bind_tolerates_error_marker_on_usable_editor():
    # Live d80e72fd: one failed media TILE renders "Something went wrong" inside an
    # otherwise fully usable editor (composer present + editable). Binding must
    # proceed — only an UNUSABLE surface with markers is a broken page.
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"visible_error_markers": ["Something went wrong"], "build_match": True,
                   "editor_capability_ready": True,
                   "composer_found": True, "composer_editable": True},
    )
    b = _run(mv._bind_editor_session(client))
    assert b["project_id"] == "abc-123"


def test_bind_content_build_mismatch_raises():
    url = "https://labs.google/fx/tools/flow/project/abc-123"
    client = _FakeClient(
        _harvest("abc-123", url, 42),
        page_diag={"visible_error_markers": [], "build_match": False},
    )
    try:
        _run(mv._bind_editor_session(client))
        assert False, "expected CONTENT_BUILD_MISMATCH"
    except RuntimeError as e:
        assert "CONTENT_BUILD_MISMATCH" in str(e)


def test_bind_with_recovery_reopens_stored_project_on_drift():
    # Flow drifted the tab to home (NO_OPEN_EDITOR). Recovery re-opens the STORED project the
    # user was working in, then re-binds successfully — it must NOT mint a new project.
    url = "https://labs.google/fx/tools/flow/project/heal-1"
    state = {"opened": False}

    class _DriftClient:
        async def harvest_video_urls(self, tab_id=None):
            if state["opened"]:
                return _harvest("heal-1", url, 7)
            return _harvest(None, "https://labs.google/fx/tools/flow", 7)  # root → NO_OPEN_EDITOR

        async def flow_page_state_diagnostic(self, mode=None):
            return {"stored_flow_project_url": url, "visible_error_markers": [], "build_match": True}

        async def open_target_flow_project(self, flow_project_url):
            assert flow_project_url == url
            state["opened"] = True  # the tab navigates back to the project
            return {"ok": False, "error": "FLOW_PROJECT_EDITOR_NOT_READY"}  # false-negative, ignored

    orig = mv.asyncio
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    try:
        b = _run(mv._bind_with_recovery(_DriftClient()))
        assert b["project_id"] == "heal-1" and b["flow_project_url"] == url
        assert state["opened"] is True
    finally:
        mv.asyncio = orig


def test_bind_with_recovery_fails_closed_on_broken_editor():
    # A broken editor (not a drift) must NOT trigger re-open recovery — fail closed.
    url = "https://labs.google/fx/tools/flow/project/abc"
    client = _FakeClient(
        _harvest("abc", url, 1),
        page_diag={"visible_error_markers": ["Something went wrong"], "build_match": True},
    )
    try:
        _run(mv._bind_with_recovery(client))
        assert False, "expected BROKEN_EDITOR_PAGE (no recovery)"
    except RuntimeError as e:
        assert "BROKEN_EDITOR_PAGE" in str(e)


def test_bind_with_recovery_passthrough_when_already_bound():
    # Already on a healthy editor → bind succeeds first try, no recovery needed.
    url = "https://labs.google/fx/tools/flow/project/ok-1"
    b = _run(mv._bind_with_recovery(_FakeClient(_harvest("ok-1", url, 5))))
    assert b == {"project_id": "ok-1", "flow_tab_id": 5, "flow_project_url": url}


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


def test_run_negotiate_image_prompt_branching():
    """image_prompt=None -> pure T2V dry (no start frame, media=None);
    image_prompt=<text> -> start frame generated (media=[id]). (patch I4a contract)"""
    import agent.api.flow as flowmod
    cap = {}

    async def fake_negotiate(client, pid, sid, prompt, media, **kw):
        cap["media"] = media
        return {"transcript": [], "approved": False}

    async def fake_img(*a, **k):
        cap["img_called"] = True
        return {"media": [{"name": "img-123"}]}

    class _C:
        async def create_project(self, *a):
            return {"projectId": "p1"}

        async def create_agent_session(self, *a):
            return {"sessionInfo": {"agentSessionId": "s1"}}

    orig = (mv.agent_video.negotiate_and_generate,
            flowmod._generate_image_with_recovery, mv.get_flow_client)
    mv.agent_video.negotiate_and_generate = fake_negotiate
    flowmod._generate_image_with_recovery = fake_img
    mv.get_flow_client = lambda: _C()
    try:
        mv._JOBS.clear()
        mv._JOBS["jn"] = {"status": "SUBMITTED"}
        cap.clear()
        _run(mv._run_negotiate("jn", "p", None, True, None, None, "p1"))
        assert cap.get("media") is None and "img_called" not in cap

        mv._JOBS["jt"] = {"status": "SUBMITTED"}
        cap.clear()
        _run(mv._run_negotiate("jt", "p", "make image", True, None, None, "p1"))
        assert cap.get("img_called") is True and cap.get("media") == ["img-123"]
    finally:
        (mv.agent_video.negotiate_and_generate,
         flowmod._generate_image_with_recovery, mv.get_flow_client) = orig
        mv._JOBS.clear()


class _ShimAsyncio:
    """Delegates to real asyncio but makes sleep() instant — skips the 120s render wait."""
    def __init__(self, real):
        self._real = real

    async def sleep(self, *a, **k):
        return None

    def __getattr__(self, n):
        return getattr(self._real, n)


def _setup_generate_mocks(nres):
    """Patch make_video deps so _run_generate reaches the post-approve verification without
    network or the render wait. negotiate returns `nres`; retrieval finds a video instantly."""
    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "diag": {"projectId": "p1", "videoIds": ["vid-1"]}}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return nres

    async def fake_save(client, cands, exclude):
        return ("vid-1", "/out/vid-1.mp4", 1.0)

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._save_video_by_get_media = fake_save
    mv.asyncio = _ShimAsyncio(mv.asyncio)

    def restore():
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media, mv.asyncio) = orig
    return restore


def _gen(job_id, nres):
    mv._JOBS.clear()
    mv._JOBS[job_id] = {"status": "SUBMITTED"}
    restore = _setup_generate_mocks(nres)
    try:
        _run(mv._run_generate(job_id, "T2V", "p", "p1", None, None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        return dict(mv._JOBS[job_id])
    finally:
        restore()
        mv._JOBS.clear()


def test_duration_mismatch_hard_fails():  # DUR-3
    job = _gen("jd", {"approved": True, "model_ok": True, "duration_ok": False,
                      "model_used": "veo_3_1_r2v_lite", "duration_used": 4})
    assert job["status"] == "FAILED"
    assert "FAILED_WRONG_DURATION" in job["error"]


def test_duration_match_completes():  # DUR-2
    job = _gen("jm", {"approved": True, "model_ok": True, "duration_ok": True,
                      "model_used": "veo_3_1_r2v_lite", "duration_used": 8})
    assert job["status"] == "DONE"
    assert job.get("duration_used") == 8
    assert job.get("model_ok") is True and job.get("duration_ok") is True   # fully exposed
    assert "duration_unverified" not in job and "model_unverified" not in job


def test_duration_absent_marks_unverified_not_fail():  # DUR-4
    job = _gen("ju", {"approved": True, "model_ok": True, "duration_ok": None,
                      "model_used": "veo_3_1_r2v_lite", "duration_used": None})
    assert job["status"] == "DONE"               # absent duration is NOT a hard fail
    assert job.get("duration_unverified") is True
    assert "model_unverified" not in job         # model WAS verified, only duration absent


def test_unrecognized_tool_marks_both_unverified():
    # An unrecognized generation tool → model AND duration both unknown (None). NOT a hard fail,
    # but both flags are set + model_ok/duration_ok exposed, so it is never reported as verified.
    job = _gen("jx", {"approved": True, "model_ok": None, "duration_ok": None,
                      "model_used": None, "duration_used": None})
    assert job["status"] == "DONE"
    assert job.get("model_unverified") is True and job.get("duration_unverified") is True
    assert job.get("model_ok") is None and job.get("duration_ok") is None


def test_wrong_model_still_hard_fails():  # regression: FAILED_WRONG_MODEL preserved
    job = _gen("jw", {"approved": True, "model_ok": False, "duration_ok": True,
                      "model_used": "omni", "duration_used": 8})
    assert job["status"] == "FAILED"
    assert "FAILED_WRONG_MODEL" in job["error"]


# --- GENERATED_BUT_UNRETRIEVED false-negative fix ---------------------------------------------

def _setup_generate_mocks_custom(nres, harvest_result, save_result=(None, None, None)):
    """Like _setup_generate_mocks but with a CUSTOM harvest result and save outcome, so we can
    drive the retrieval phase into a lost-tab (EDITOR_TAB_LOST) vs a successful harvest."""
    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def harvest_video_urls(self, tab_id=None):
            return harvest_result

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return nres

    async def fake_save(client, cands, exclude):
        return save_result

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._save_video_by_get_media = fake_save
    mv.asyncio = _ShimAsyncio(mv.asyncio)

    def restore():
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media, mv.asyncio) = orig
    return restore


def _gen2(job_id, nres, harvest_result, save_result=(None, None, None)):
    mv._JOBS.clear()
    mv._JOBS[job_id] = {"status": "SUBMITTED"}
    restore = _setup_generate_mocks_custom(nres, harvest_result, save_result)
    try:
        _run(mv._run_generate(job_id, "T2V", "p", "p1", None, None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        return dict(mv._JOBS[job_id])
    finally:
        restore()
        mv._JOBS.clear()


def test_generate_marks_generated_but_unretrieved_on_editor_tab_lost_after_approval():
    # approved + reached GENERATING, then harvest reports the bound tab is gone → the video was
    # likely generated (credits likely spent) but unretrieved. Must NOT be a plain FAILED.
    nres = {"approved": True, "model_ok": True, "duration_ok": True,
            "model_used": "veo_3_1_r2v_lite", "duration_used": 8}
    job = _gen2("jg", nres, {"result": {"error": "BOUND_TAB_GONE"}})
    assert job["status"] == "GENERATED_BUT_UNRETRIEVED"
    assert job.get("media_id") is None
    assert job.get("local_path") is None
    assert job.get("artifact") is None
    assert job.get("credit_spent_likely") is True
    assert job.get("recovery_required") is True
    assert job.get("recovery_hint")
    assert "EDITOR_TAB_LOST" in (job.get("original_error") or "")


def test_generate_keeps_failed_for_preapproval_error():
    # The agent did not approve → failure happens BEFORE rendering. Stays plain FAILED.
    nres = {"approved": False, "error": "agent declined"}
    job = _gen2("jf", nres,
                {"result": {"flow_tab_found": True, "flow_tab_id": 1, "diag": {"projectId": "p1"}}})
    assert job["status"] == "FAILED"
    assert job["status"] != "GENERATED_BUT_UNRETRIEVED"
    assert job.get("credit_spent_likely") is None  # not flagged for a pre-approval failure
    assert "approve" in (job.get("error") or "").lower()


def test_generate_done_when_video_retrieved():
    # Successful harvest + saved mp4 → DONE preserved with real media_id / local_path.
    nres = {"approved": True, "model_ok": True, "duration_ok": True,
            "model_used": "veo_3_1_r2v_lite", "duration_used": 8}
    harvest = {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                          "diag": {"projectId": "p1", "videoIds": ["vid-1"]}}}
    job = _gen2("jd2", nres, harvest, save_result=("vid-1", "/out/vid-1.mp4", 1.0))
    assert job["status"] == "DONE"
    assert job.get("media_id") == "vid-1"
    assert job.get("local_path") == "/out/vid-1.mp4"
    assert job.get("artifact") == "video"


def test_retrieval_reloads_stale_tab_and_never_claims_preexisting_video():
    # Two live-proven retrieval invariants in one flow:
    # 1. Omni/V2 editor DOM does not live-update (g_01b041b563dc): the finished video
    #    only becomes harvestable after a tab reload — filed under imageIds — so the
    #    loop must reload the bound tab periodically.
    # 2. A video that ALREADY existed in the project before this job (g_745e95ede679
    #    false-DONE: claimed the previous run's mp4 at try 1) must NEVER be accepted —
    #    the pre-poll snapshot puts it in the exclude set.
    state = {"reloads": 0}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self):
            state["reloads"] += 1
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            # 'old-video' is visible from the very first (snapshot) harvest; the fresh
            # render only surfaces after a reload — and lands in imageIds, not videoIds.
            diag = {"projectId": "p1", "videoIds": [], "mediaIds": [],
                    "imageIds": ["old-video"]}
            if state["reloads"]:
                diag["imageIds"] = ["old-video", "fresh-video"]
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1, "diag": diag}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return {"approved": True, "model_ok": True, "duration_ok": True,
                "model_used": "veo_3_1_r2v_lite", "duration_used": 8}

    async def fake_save(client, cands, exclude):
        usable = [m for m in cands if m not in exclude]
        assert "old-video" not in usable, "pre-existing video must be excluded from retrieval"
        if "fresh-video" in usable:
            return ("fresh-video", "/out/v.mp4", 1.9)
        return (None, None, None)

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._save_video_by_get_media = fake_save
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["jr"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("jr", "T2V", "p", "p1", None, None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        job = dict(mv._JOBS["jr"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media, mv.asyncio) = orig
        mv._JOBS.clear()

    assert state["reloads"] >= 1          # the loop refreshed the stale tab
    assert job["status"] == "DONE"        # and retrieved the video that surfaced after it
    assert job.get("media_id") == "fresh-video"
    assert job.get("media_id") != "old-video"   # never the pre-existing one
    assert job.get("preexisting_media_excluded") == 1
    assert job.get("artifact") == "video"


def test_retrieval_probe_fails_fast_on_reference_image_missing():
    # A dead start media gets APPROVED but the render dies server-side; the project
    # stays empty and the agent explains only in chat (live: Faris' screenshots).
    # The retrieval loop must probe the agent session and fail FAST with the true
    # cause instead of blind-polling to the 12-minute timeout.
    probes = {"count": 0}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self):
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1,
                               "diag": {"projectId": "p1", "videoIds": [],
                                        "imageIds": [], "mediaIds": []}}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        return {"approved": True, "model_ok": True, "duration_ok": True,
                "model_used": "veo_3_1_r2v_lite", "duration_used": 8, "turns_used": 4}

    async def fake_save(client, cands, exclude):
        return (None, None, None)

    async def fake_probe(client, project_id, session_id, turn_number):
        probes["count"] += 1
        assert session_id == "s1" and turn_number >= 5
        return {"classification": "REFERENCE_IMAGE_MISSING",
                "agent_text": "trouble accessing the reference image",
                "turn_number": turn_number + 1}

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media,
            mv.agent_video.probe_render_failure, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._save_video_by_get_media = fake_save
    mv.agent_video.probe_render_failure = fake_probe
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["jp"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("jp", "F2V", "p", "p1", ["ref-1"], None, "9:16", None,
                              model="veo_3_1_lite", duration_s=8))
        job = dict(mv._JOBS["jp"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media,
         mv.agent_video.probe_render_failure, mv.asyncio) = orig
        mv._JOBS.clear()

    assert probes["count"] == 1                       # probed at try 9, not after timeout
    assert job["status"] == "FAILED"                  # honest fail-fast, not UNRETRIEVED
    assert "FAILED_REFERENCE_IMAGE_MISSING" in (job.get("error") or "")
    assert "re-upload" in (job.get("error") or "")


def test_retrieval_collects_user_count_videos():
    # count=2: retrieval must bring home BOTH videos, expose them on job.artifacts,
    # and only then report DONE. Artifact records must be written for each.
    recorded = []

    state = {"reloads": 0}

    class _C:
        async def create_agent_session(self, *a):
            return {"data": {"sessionInfo": {"agentSessionId": "s1"}}}

        async def reload_flow_tab(self):
            state["reloads"] += 1
            return {"ok": True}

        async def harvest_video_urls(self, tab_id=None):
            # Empty at snapshot time; both fresh renders surface after a reload.
            ids = ["vid-A", "vid-B"] if state["reloads"] else []
            diag = {"projectId": "p1", "videoIds": ids, "imageIds": [], "mediaIds": []}
            return {"result": {"flow_tab_found": True, "flow_tab_id": 1, "diag": diag}}

    async def fake_bind(client, pid=None):
        return {"project_id": "p1", "flow_tab_id": 1, "flow_project_url": "u"}

    async def fake_negotiate(*a, **k):
        assert k.get("desired_num") == 2, "user count must reach the negotiation"
        return {"approved": True, "model_ok": True, "duration_ok": True,
                "model_used": "veo_3_1_r2v_lite", "duration_used": 8}

    async def fake_save(client, cands, exclude):
        usable = [m for m in cands if m not in exclude]
        if usable:
            return (usable[0], f"/out/{usable[0]}.mp4", 1.5)
        return (None, None, None)

    async def fake_record(job, mode, artifacts):
        recorded.extend(a["media_id"] for a in artifacts)

    orig = (mv.get_flow_client, mv._bind_editor_session,
            mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media,
            mv._record_artifacts, mv.asyncio)
    mv.get_flow_client = lambda: _C()
    mv._bind_editor_session = fake_bind
    mv.agent_video.negotiate_and_generate = fake_negotiate
    mv._save_video_by_get_media = fake_save
    mv._record_artifacts = fake_record
    mv.asyncio = _ShimAsyncio(mv.asyncio)
    mv._JOBS.clear()
    mv._JOBS["jc"] = {"status": "SUBMITTED"}
    try:
        _run(mv._run_generate("jc", "F2V", "p", "p1", ["ref-1"], None, "16:9", None,
                              model="veo_3_1_lite", duration_s=8, num_videos=2))
        job = dict(mv._JOBS["jc"])
    finally:
        (mv.get_flow_client, mv._bind_editor_session,
         mv.agent_video.negotiate_and_generate, mv._save_video_by_get_media,
         mv._record_artifacts, mv.asyncio) = orig
        mv._JOBS.clear()

    assert job["status"] == "DONE"
    ids = [a["media_id"] for a in job.get("artifacts") or []]
    assert ids == ["vid-A", "vid-B"]          # BOTH videos retrieved
    assert recorded == ["vid-A", "vid-B"]     # and registered in the system library
    assert job.get("partial") is not True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
