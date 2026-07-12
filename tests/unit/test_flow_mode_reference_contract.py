"""Unified all-mode reference contract (product authority, non-negotiable):

| F2V / FRAMES | 1-2 | · | HYBRID | exactly 1 | · | I2V / INGREDIENTS | 2-3 | · | T2V | 0 |

Any other count fails closed BEFORE generation — at the operator lane (full
contract via `validate_reference_count`) and at the one-door service itself
(transport hard caps via `service_hard_violation` / `start_generate`).
"""
import asyncio

from agent.services import flow_mode_reference_contract as refc
from agent.services import make_video as mv


def _run(coro):
    return asyncio.run(coro)


# ── the canonical mode matrix ────────────────────────────────────────────────
def test_mode_matrix_bounds():
    assert refc.reference_bounds("F2V") == (1, 2)
    assert refc.reference_bounds("I2V") == (2, 3)
    assert refc.reference_bounds("T2V") == (0, 0)
    assert refc.reference_bounds("F2V", source_mode="HYBRID") == (1, 1)
    assert refc.reference_bounds("F2V", source_mode="FRAMES") == (1, 2)
    assert refc.reference_bounds("I2V", source_mode="INGREDIENTS") == (2, 3)
    assert refc.reference_bounds("IMG") is None  # image lane: no video contract


def test_valid_counts_accepted_per_mode():
    for mode, source, count in [
        ("F2V", None, 1), ("F2V", None, 2),
        ("F2V", "HYBRID", 1),
        ("I2V", None, 2), ("I2V", None, 3),
        ("T2V", None, 0),
        ("IMG", None, 5),  # no contract
    ]:
        ok, code, detail = refc.validate_reference_count(mode, count, source_mode=source)
        assert ok, f"{mode}/{source}/{count} should be valid: {detail}"
        assert code is None


def test_invalid_counts_fail_closed_per_mode():
    cases = [
        ("F2V", None, 0), ("F2V", None, 3),
        ("F2V", "HYBRID", 0), ("F2V", "HYBRID", 2),
        ("I2V", None, 0), ("I2V", None, 1), ("I2V", None, 4),
        ("T2V", None, 1), ("T2V", None, 3),
    ]
    for mode, source, count in cases:
        ok, code, detail = refc.validate_reference_count(mode, count, source_mode=source)
        assert not ok, f"{mode}/{source}/{count} must be blocked"
        expected = (refc.ERR_T2V_REFERENCES_FORBIDDEN if mode == "T2V"
                    else refc.ERR_REFERENCE_COUNT_CONTRACT)
        assert code == expected
        assert detail  # human explanation, never a bare code


def test_t2v_violation_names_the_text_only_contract():
    ok, code, detail = refc.validate_reference_count("T2V", 2)
    assert not ok and code == refc.ERR_T2V_REFERENCES_FORBIDDEN
    assert "text-only" in detail


# ── one-door service hard caps (transport level, mode-blind callers) ─────────
def test_service_hard_caps():
    assert refc.service_hard_violation("T2V", 0) is None
    assert refc.service_hard_violation("T2V", 1)          # text-only, forbidden
    assert refc.service_hard_violation("F2V", 2) is None
    assert refc.service_hard_violation("F2V", 3)
    assert refc.service_hard_violation("I2V", 3) is None
    assert refc.service_hard_violation("I2V", 4)
    assert refc.service_hard_violation("IMG", 9) is None  # image lane exempt
    # lower bounds are NOT service caps (operator-layer concern)
    assert refc.service_hard_violation("I2V", 1) is None


def test_start_generate_rejects_t2v_with_references_synchronously():
    out = _run(mv.start_generate("T2V", "text only prompt",
                                 image_media_ids=["stale-ref-1"]))
    assert out["status"] == "REJECTED"
    assert refc.ERR_T2V_REFERENCES_FORBIDDEN in out["error"]


def test_start_generate_rejects_over_cap_reference_counts():
    f2v = _run(mv.start_generate("F2V", "p", image_media_ids=["a", "b", "c"]))
    assert f2v["status"] == "REJECTED"
    assert refc.ERR_REFERENCE_COUNT_CONTRACT in f2v["error"]
    i2v = _run(mv.start_generate("I2V", "p", image_media_ids=["a", "b", "c", "d"]))
    assert i2v["status"] == "REJECTED"
    assert refc.ERR_REFERENCE_COUNT_CONTRACT in i2v["error"]


def test_start_generate_ignores_empty_reference_entries(monkeypatch):
    # Blank/None entries never count toward the contract (T2V with only empties
    # is clean). Stub the runner so nothing actually executes.
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(mv, "_run_generate", _noop)
    monkeypatch.setattr(mv, "_VIDEO_LANE_JOB", None)
    out = _run(mv.start_generate("T2V", "p", image_media_ids=[None, ""]))
    assert out["status"] == "SUBMITTED"
    monkeypatch.setattr(mv, "_VIDEO_LANE_JOB", None)  # release the claimed lane
