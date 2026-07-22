"""B-15 — a phantom render must not be reported as GENERATED_BUT_UNRETRIEVED.

`GENERATED_BUT_UNRETRIEVED` exists so a paid, completed video is never presented
as "no video". But it also fired when the render never materialized at all —
live proof (2026-07-21, job `g_99daae472362`): approval happened, the poll
window saw ZERO completed candidates belonging to this run, and 15+ minutes
later the project contained no media with the run's dialogue. The job was still
labeled GENERATED_BUT_UNRETRIEVED with `credit_spent_likely=True` and a hint
promising the video could be harvested — all three misleading.

Corrected contract, pinned here:
  * timeout with ZERO completed candidates ever evaluated ->
    ``RENDER_NOT_MATERIALIZED``, credit UNKNOWN (never claimed spent, never
    claimed zero), hint says verify the project, not harvest a video that may
    not exist;
  * stale/foreign candidates deterministically REJECTED (identity mismatch) ->
    ``STALE_OR_FOREIGN_CANDIDATES_ONLY``, credit UNKNOWN, never a generated item;
  * unverifiable completed candidates -> stays GENERATED_BUT_UNRETRIEVED;
  * stats never persisted (tab lost mid-poll) -> conservative
    GENERATED_BUT_UNRETRIEVED;
  * the production queue treats the new status as TERMINAL (else the item
    would hang RUNNING to the job timeout).

No provider, no Flow, no credit — pure classification logic.
"""
import inspect

from agent.services import make_video as mv
from agent.services import production_queue_service as pq

_FRESH_STATS = {
    "unverifiable": 0, "prompt_mismatched": 0, "model_mismatched": 0,
    "seed_mismatched": 0, "unverifiable_ids": [], "normalization_failures": {},
    "round_rejected_ids": [],
}

_TIMEOUT_MSG = "video not found/retrieved in time"


def _job(stats="fresh"):
    j = {"approved": True, "identity_captured": True}
    if stats == "fresh":
        j["correlation_stats"] = dict(_FRESH_STATS)
    elif stats is not None:
        j["correlation_stats"] = dict(stats)
    return j


# ── the phantom render: zero completed candidates ever ───────────────────────
def test_timeout_with_zero_candidates_is_render_not_materialized():
    j = _job()
    mv._apply_post_approval_failure(j, _TIMEOUT_MSG)
    assert j["status"] == "RENDER_NOT_MATERIALIZED"
    assert j.get("credit_spent_likely") is not True, "credit overclaimed for a phantom render"
    assert j.get("credit_state") == "UNKNOWN", "ambiguous credit must be stated, not guessed"
    hint = (j.get("recovery_hint") or "").lower()
    assert "verify" in hint
    assert "harvest" not in hint, "hint promises harvesting a video that may not exist"
    assert j.get("error") == _TIMEOUT_MSG


# ── completed media existed: the existing honesty is KEPT ────────────────────
def test_stale_or_foreign_candidates_are_not_reported_as_generated():
    stats = dict(_FRESH_STATS, prompt_mismatched=9,
                 round_rejected_ids=["80afc332-6dd3-4fee-aa34-3fabfa9e567a"])
    j = _job(stats)
    mv._apply_post_approval_failure(
        j, "CURRENT_OUTPUT_IDENTITY_MISMATCH: completed candidate(s) rejected")
    assert j["status"] == "STALE_OR_FOREIGN_CANDIDATES_ONLY"
    assert j.get("credit_spent_likely") is not True
    assert j["credit_state"] == "UNKNOWN"


def test_unverifiable_candidates_stay_generated_but_unretrieved():
    stats = dict(_FRESH_STATS, unverifiable=2, unverifiable_ids=["a", "b"])
    j = _job(stats)
    mv._apply_post_approval_failure(
        j, "OUTPUT_CORRELATION_UNAVAILABLE: finished media cannot be deterministically bound")
    assert j["status"] == "GENERATED_BUT_UNRETRIEVED"


def test_timeout_with_rejected_ids_but_zero_counters_stays_conservative():
    """Belt-and-braces: any evidence a completed candidate existed wins."""
    stats = dict(_FRESH_STATS, round_rejected_ids=["x"])
    j = _job(stats)
    mv._apply_post_approval_failure(j, _TIMEOUT_MSG)
    assert j["status"] == "GENERATED_BUT_UNRETRIEVED"


def test_missing_stats_stays_conservative():
    """Tab lost mid-poll: stats never persisted — the video may well exist."""
    j = _job(stats=None)
    mv._apply_post_approval_failure(j, "EDITOR_TAB_LOST: bound tab gone")
    assert j["status"] == "GENERATED_BUT_UNRETRIEVED"


def test_non_timeout_retrieval_errors_with_clean_stats_stay_conservative():
    """Only the plain not-found timeout may claim the render never appeared."""
    j = _job()
    mv._apply_post_approval_failure(j, "PROJECT_DRIFT: tab moved")
    assert j["status"] == "GENERATED_BUT_UNRETRIEVED"


# ── the helper the classifier branches on ────────────────────────────────────
def test_zero_completed_candidates_semantics():
    assert mv._zero_completed_candidates(dict(_FRESH_STATS)) is True
    assert mv._zero_completed_candidates(dict(_FRESH_STATS, prompt_mismatched=1)) is False
    assert mv._zero_completed_candidates(dict(_FRESH_STATS, unverifiable=1)) is False
    assert mv._zero_completed_candidates(dict(_FRESH_STATS, round_rejected_ids=["x"])) is False
    assert mv._zero_completed_candidates(None) is False
    assert mv._zero_completed_candidates("junk") is False


# ── the production queue must treat the new status as terminal ───────────────
def test_production_queue_breaks_on_render_not_materialized():
    src = inspect.getsource(pq)
    assert '"RENDER_NOT_MATERIALIZED"' in src, "poll loop would hang RUNNING to JOB_TIMEOUT"
    assert '"STALE_OR_FOREIGN_CANDIDATES_ONLY"' in src


def test_certification_flag_untouched():
    assert pq.BULK_LIVE_EXECUTION_CERTIFIED is False


# ── C-4 · credit truth on EVERY terminal state ───────────────────────────────
# `credit_spent_likely` used to be written in exactly ONE code path
# (GENERATED_BUT_UNRETRIEVED), so every other terminal state reported it False —
# including a DONE job that delivered a real paid video. Live proof: job
# g_edf503991e7c bound an 8s 720x1280 mp4 and still reported
# credit_spent_likely=False. Now every terminal outcome stamps an explicit
# `credit_state` from ONE vocabulary shared with video_production_orchestrator,
# and the boolean is DERIVED from it.

def test_credit_vocabulary_matches_the_orchestrator_exactly():
    """One vocabulary, not two — the lanes must never disagree on a word."""
    from agent.services import video_production_orchestrator as orch
    assert (mv.CREDIT_NOT_SPENT, mv.CREDIT_MAY_HAVE_SPENT,
            mv.CREDIT_SPENT, mv.CREDIT_UNKNOWN) == (
        orch.CR_NOT_SPENT, orch.CR_MAY_HAVE_SPENT, orch.CR_SPENT, orch.CR_UNKNOWN)


def test_stamp_derives_the_boolean_from_the_state():
    for state, expected in (
        (mv.CREDIT_SPENT, True),
        (mv.CREDIT_MAY_HAVE_SPENT, True),
        (mv.CREDIT_NOT_SPENT, False),
        (mv.CREDIT_UNKNOWN, False),
    ):
        j = {}
        mv._stamp_credit(j, state)
        assert j["credit_state"] == state
        assert j["credit_spent_likely"] is expected, state


def test_every_terminal_state_in_make_video_stamps_credit():
    """No terminal outcome may leave the credit verdict unwritten — an absent
    field is what made the old boolean unreadable as evidence."""
    import inspect
    src = inspect.getsource(mv)
    # every place a terminal status is set must be accompanied by a stamp
    assert src.count("_stamp_credit(") >= 7, "a terminal state is missing its credit stamp"
    # and the boolean must never be hand-written as a kwarg again (prose in a
    # docstring is fine — this targets `credit_spent_likely=True,` in a call)
    import re
    assert not re.search(r"credit_spent_likely\s*=\s*True\s*,", src), \
        "hand-set boolean reintroduced — derive it via _stamp_credit"


def test_a_delivered_video_is_never_reported_as_free():
    """The exact live regression: DONE with an artifact reporting no credit."""
    import inspect
    src = inspect.getsource(mv)
    done_video = src.index('status="DONE", stage="done", media_id=first["media_id"]')
    window = src[done_video:done_video + 500]
    assert "_stamp_credit(job, CREDIT_MAY_HAVE_SPENT)" in window


def test_production_queue_persists_the_structured_state_not_just_the_bool():
    src = inspect.getsource(pq)
    assert '"credit_state": job.get("credit_state")' in src
