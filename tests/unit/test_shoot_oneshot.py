"""Tests for the one-shot async video pipeline (`agent.services.shoot_oneshot`).

Mocks flow_client so the full chain — create-project -> start-frame (AI/upload) ->
generate-video -> poll -> download — is exercised without a live extension, Google,
or a paid account. Covers happy paths (both frame modes), fail-loud guards, and the
public job view. `_download` is stubbed so tests touch no network.
"""
import asyncio

from agent.services import shoot_oneshot as so


class _FakeClient:
    """Canned flow_client responses mirroring real Google Flow payload shapes."""
    connected = True

    def __init__(self, video_result=None, image_result=None):
        self.polls = 0
        self._video_result = video_result
        self._image_result = image_result

    async def create_project(self, *a, **k):
        return {"data": {"projectId": "proj-123"}}

    async def generate_images(self, **k):
        if self._image_result is not None:
            return self._image_result
        return {"data": {"media": [{
            "name": "media-ai",
            "image": {"generatedImage": {"fifeUrl": "http://x/img", "mediaId": "media-ai"}},
        }]}}

    async def upload_image(self, *a, **k):
        return {"_mediaId": "media-upload", "data": {}}

    async def generate_video(self, **k):
        if self._video_result is not None:
            return self._video_result
        return {"data": {"operations": [
            {"operation": {"name": "op-1"}, "status": "MEDIA_GENERATION_STATUS_PENDING"}]}}

    async def check_video_status(self, ops):
        # PENDING on the first poll, SUCCESSFUL on the second (carries the video media).
        self.polls += 1
        done = self.polls >= 2
        op = {
            "operation": {"name": "op-1"},
            "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL" if done else "MEDIA_GENERATION_STATUS_PENDING",
        }
        if done:
            op["video"] = {"fifeUrl": "http://x/video.mp4", "mediaId": "vid-1"}
        return {"data": {"operations": [op]}}


async def _fake_download(url, job_id):
    return f"/fake/{job_id}.mp4"


def _fresh_job():
    return {"job_id": "t", "status": so.SUBMITTED, "stage": "", "video_url": None,
            "local_path": None, "media_id": None, "error": None}


def _run(monkeypatch, envelope, tier="PAYGATE_TIER_ONE", client=None):
    client = client or _FakeClient()
    monkeypatch.setattr(so, "get_flow_client", lambda: client)
    monkeypatch.setattr(so, "_download", _fake_download)
    monkeypatch.setattr(so, "POLL_INTERVAL", 0.01)
    job = _fresh_job()
    asyncio.run(so._run(job, envelope, tier))
    return job


# ── happy paths ──────────────────────────────────────────────

def test_ai_frame_mode_reaches_successful(monkeypatch):
    job = _run(monkeypatch, {
        "prompt": "push in", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "start_frame": {"mode": "ai", "image_prompt": "clean shot"}})
    assert job["status"] == so.SUCCESSFUL
    assert job["video_url"] == "http://x/video.mp4"
    assert job["media_id"] == "vid-1"
    assert job["local_path"] == "/fake/t.mp4"
    assert job["error"] is None


def test_upload_frame_mode_reaches_successful(monkeypatch):
    job = _run(monkeypatch, {
        "prompt": "push in", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "start_frame": {"mode": "upload", "image_base64": "Zm9v", "mime_type": "image/jpeg"}})
    assert job["status"] == so.SUCCESSFUL
    assert job["video_url"]


# ── fail-loud guards ─────────────────────────────────────────

def test_empty_prompt_fails_loud(monkeypatch):
    job = _run(monkeypatch, {"prompt": "   ", "start_frame": {"mode": "ai"}})
    assert job["status"] == so.FAILED
    assert "empty" in job["error"].lower()


def test_upload_mode_without_image_fails_loud(monkeypatch):
    job = _run(monkeypatch, {"prompt": "push in", "start_frame": {"mode": "upload"}})
    assert job["status"] == so.FAILED
    assert "image_base64" in job["error"]


def test_video_rejection_surfaces_as_failed(monkeypatch):
    client = _FakeClient(video_result={"error": "No model for tier=PAYGATE_TIER_NOT_PAID"})
    job = _run(monkeypatch,
               {"prompt": "x", "start_frame": {"mode": "ai", "image_prompt": "y"}},
               tier="PAYGATE_TIER_NOT_PAID", client=client)
    assert job["status"] == so.FAILED
    assert "No model" in job["error"]


def test_missing_start_media_fails_loud(monkeypatch):
    client = _FakeClient(image_result={"data": {"media": []}})
    job = _run(monkeypatch,
               {"prompt": "x", "start_frame": {"mode": "ai", "image_prompt": "y"}},
               client=client)
    assert job["status"] == so.FAILED
    assert "media_id" in job["error"]


# ── public job view ──────────────────────────────────────────

def test_get_job_hides_internal_task_handle(monkeypatch):
    monkeypatch.setattr(so, "get_flow_client", lambda: _FakeClient())
    monkeypatch.setattr(so, "_download", _fake_download)
    monkeypatch.setattr(so, "POLL_INTERVAL", 0.01)

    async def _go():
        res = await so.start_job(
            {"prompt": "x", "start_frame": {"mode": "ai", "image_prompt": "y"}},
            "PAYGATE_TIER_ONE")
        jid = res["job_id"]
        await so._JOBS[jid]["_task"]   # let the background pipeline finish
        return so.get_job(jid)

    view = asyncio.run(_go())
    assert "_task" not in view
    assert view["status"] in (so.SUCCESSFUL, so.FAILED)
