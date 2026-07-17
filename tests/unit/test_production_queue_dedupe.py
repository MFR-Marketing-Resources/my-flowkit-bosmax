"""O4 — duplicate-submission protection on the Production Queue provider boundary.

G0 parked O4 with "must be resolved before Round F is authorized". Before this,
`production_job_id` was only ever WRITTEN (never read), so nothing stopped the same
package being fired at the provider twice — a double click, a retried request or two
loops racing the same item would each spend credits for identical work.

These tests never touch a provider: `make_video` is a fake that records calls, so a
regression shows up as an extra recorded submission rather than a real credit burn.
"""
import asyncio

import pytest

from agent.services import production_queue_service as pq

PAYLOAD = {
    "mode": "T2V",
    "prompt": "a synthetic prompt",
    "model": "Veo 3.1 - Lite",
    "duration_s": 8,
    "aspect": "9:16",
    "num_videos": 1,
    "logical_mode": "T2V",
    "image_media_ids": None,
}


class _FakeMakeVideo:
    """Stands in for the provider. Counts submissions; never calls anything."""

    def __init__(self, job_id="job_1", status="DONE"):
        self.calls = []
        self._job_id = job_id
        self._status = status

    async def start_generate(self, mode, prompt, **kw):
        self.calls.append({"mode": mode, "prompt": prompt, **kw})
        return {"status": "ACCEPTED", "job_id": self._job_id}

    def get_job(self, job_id):
        return {"status": self._status, "artifacts": [{"media_id": "m1"}]}


@pytest.fixture
def wgp_rows(monkeypatch):
    """In-memory workspace_generation_package rows, patched over crud."""
    rows = {"wgp_1": {"workspace_generation_package_id": "wgp_1", "production_job_id": None}}

    async def get_wgp(wgp_id):
        return rows.get(wgp_id)

    async def update_wgp(wgp_id, **kw):
        rows.setdefault(wgp_id, {"workspace_generation_package_id": wgp_id}).update(kw)
        return rows[wgp_id]

    async def link_artifacts(job_id, wgp_id):
        return None

    monkeypatch.setattr(pq.crud, "get_workspace_generation_package", get_wgp)
    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", update_wgp)
    monkeypatch.setattr(pq.crud, "link_artifacts_to_generation_package", link_artifacts)
    pq._inflight_dedupe.clear()
    return rows


# ── dedupe key identity ──────────────────────────────────────────────────────


def test_dedupe_key_is_stable_for_identical_logical_work():
    assert pq.compute_dedupe_key(PAYLOAD, "wgp_1") == pq.compute_dedupe_key(dict(PAYLOAD), "wgp_1")


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "Veo 3.1 - Quality"),
        ("duration_s", 16),
        ("prompt", "a DIFFERENT prompt"),
        ("aspect", "16:9"),
        ("num_videos", 2),
        ("mode", "I2V"),
        ("image_media_ids", ["11111111-1111-1111-1111-111111111111"]),
    ],
)
def test_dedupe_key_changes_when_the_work_changes(field, value):
    """A genuinely different job must NOT collide — otherwise the guard would
    block legitimate distinct submissions."""
    other = {**PAYLOAD, field: value}
    assert pq.compute_dedupe_key(other, "wgp_1") != pq.compute_dedupe_key(PAYLOAD, "wgp_1")


def test_dedupe_key_is_package_scoped():
    assert pq.compute_dedupe_key(PAYLOAD, "wgp_1") != pq.compute_dedupe_key(PAYLOAD, "wgp_2")


def test_dedupe_key_ignores_media_id_ordering():
    a = {**PAYLOAD, "image_media_ids": ["b", "a"]}
    b = {**PAYLOAD, "image_media_ids": ["a", "b"]}
    assert pq.compute_dedupe_key(a, "wgp_1") == pq.compute_dedupe_key(b, "wgp_1")


# ── the guard ────────────────────────────────────────────────────────────────


def test_first_submission_is_allowed_and_reaches_the_provider_once(wgp_rows):
    mv = _FakeMakeVideo()
    out = asyncio.run(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
    assert out["ok"] is True
    assert len(mv.calls) == 1, "exactly one provider submission expected"
    assert wgp_rows["wgp_1"]["production_job_id"] == "job_1"


def test_resubmitting_an_already_submitted_package_is_refused(wgp_rows):
    """The core O4 property: credits are never spent twice for the same work."""
    mv = _FakeMakeVideo()
    asyncio.run(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
    assert len(mv.calls) == 1

    again = asyncio.run(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
    assert again["ok"] is False
    assert again["error"].startswith("DUPLICATE_SUBMISSION_BLOCKED:job_1")
    assert len(mv.calls) == 1, "the provider must NOT be called a second time"
    assert wgp_rows["wgp_1"]["production_error"].startswith("DUPLICATE_SUBMISSION_BLOCKED")


def test_concurrent_duplicate_attempts_fail_closed(wgp_rows):
    """Two racing submissions of the same item: exactly one may reach the provider."""
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowMakeVideo(_FakeMakeVideo):
        async def start_generate(self, mode, prompt, **kw):
            self.calls.append({"mode": mode})
            started.set()
            await release.wait()
            return {"status": "ACCEPTED", "job_id": "job_1"}

    mv = _SlowMakeVideo()

    async def scenario():
        first = asyncio.create_task(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
        await started.wait()  # first submission is in flight, holding the key
        second = await pq._fire_and_wait(mv, PAYLOAD, "wgp_1")
        release.set()
        return second, await first

    second, first = asyncio.run(scenario())
    assert second["ok"] is False
    assert second["error"].startswith("DUPLICATE_SUBMISSION_IN_FLIGHT")
    assert first["ok"] is True
    assert len(mv.calls) == 1, "concurrent duplicate must not reach the provider"


def test_retry_clears_the_job_id_so_a_retried_item_may_resubmit(wgp_rows):
    """Retry is the ONE supported second submission — via explicit retry identity."""
    mv = _FakeMakeVideo()
    asyncio.run(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
    assert len(mv.calls) == 1

    # what retry_failed_items does: clear the prior job id
    wgp_rows["wgp_1"]["production_job_id"] = None

    out = asyncio.run(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
    assert out["ok"] is True
    assert len(mv.calls) == 2, "an explicit retry is allowed to resubmit"


def test_inflight_key_is_released_even_when_the_submission_fails(wgp_rows):
    """A failed submission must not poison the key and wedge the item forever."""

    class _Boom(_FakeMakeVideo):
        async def start_generate(self, mode, prompt, **kw):
            raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError):
        asyncio.run(pq._fire_and_wait(_Boom(), PAYLOAD, "wgp_1"))
    assert pq._inflight_dedupe == set(), "the in-flight key must be released"

    mv = _FakeMakeVideo()
    out = asyncio.run(pq._fire_and_wait(mv, PAYLOAD, "wgp_1"))
    assert out["ok"] is True and len(mv.calls) == 1


def test_retry_failed_items_clears_the_prior_job_id(monkeypatch):
    """Proves the retry path itself supplies the explicit retry identity."""
    updates = {}

    async def get_run(run_id):
        return {"production_run_id": run_id, "status": "PENDING"}

    async def list_pkgs(production_run_id=None, **kw):
        return [{"workspace_generation_package_id": "wgp_1", "production_status": "FAILED"}]

    async def update_wgp(wgp_id, **kw):
        updates.update(kw)

    async def update_run(run_id, **kw):
        return None

    monkeypatch.setattr(pq.crud, "get_production_run", get_run)
    monkeypatch.setattr(pq.crud, "list_production_queue_packages", list_pkgs)
    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", update_wgp)
    monkeypatch.setattr(pq.crud, "update_production_run", update_run)

    out = asyncio.run(pq.retry_failed_items("prun_1"))
    assert out["retried"] == 1
    assert "production_job_id" in updates and updates["production_job_id"] is None
    assert updates["production_status"] == "QUEUED"
