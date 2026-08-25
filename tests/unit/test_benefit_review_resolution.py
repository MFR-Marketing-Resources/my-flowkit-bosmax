"""Amendment 9 — audited manual resolution of REVIEW_REQUIRED benefits.

REVIEW_REQUIRED is not a dead end: an authorized operator may explicitly VERIFY
or BLOCK an ambiguous benefit, provider-free, with a durable audit. A deterministic
HARD safety block is never promotable through this path.
"""

import copy

import pytest

from agent.db import creative_factory_crud as cfdb
from agent.db.schema import get_db
from agent.services import ai_copy_provider_adapter as adapter
from agent.services import creative_factory_service as svc
from tests.conftest import make_product_copy_eligible, seed_product_ready

UNSUPPORTED = "zzz qwerty unrelated random tokens 12345"
UNSAFE = "sembuh penyakit dengan cepat"


async def _setup(product_id="prod_rev"):
    db = await get_db()
    await seed_product_ready(db, product_id)
    snapshot_id = await make_product_copy_eligible(product_id)
    return product_id, snapshot_id


def _valid_envelope():
    return {
        "angles": [
            {
                "angle": f"Sudut {a}",
                "hooks": [f"hook {a}-{i} rutin segar" for i in range(6)],
                "bodies": [f"body {a}-{i} kegunaan harian" for i in range(3)],
                "ctas": [f"cta {a}-{i} cuba hari ini" for i in range(3)],
            }
            for a in range(3)
        ]
    }


class _FakeProvider:
    def __init__(self):
        self.calls = 0

    def complete_json_with_receipt(self, system, user, **kwargs):
        self.calls += 1
        return (copy.deepcopy(_valid_envelope()), {"provider": "fake", "model": "m", "call_id": "c"})


def _real_calls():
    return adapter.provider_call_receipt()["request_count_since_process_start"]


async def test_ambiguous_benefit_is_review_required_and_resolvable():
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, UNSUPPORTED, None)
    assert b["status"] == "REVIEW_REQUIRED"
    ctx = await svc.review_context(b["benefit_id"])
    assert ctx["resolvable"] is True
    assert ctx["approved_snapshot"] is not None
    assert "current_check" in ctx


async def test_authorized_verify_promotes_with_audit_zero_calls_and_build_eligible():
    product_id, snapshot_id = await _setup()
    b = await svc.create_benefit(product_id, UNSUPPORTED, None)
    assert b["status"] == "REVIEW_REQUIRED"

    before = _real_calls()
    resolved = await svc.resolve_review(
        b["benefit_id"], "VERIFY", "staff_reviewer_1", "Valid Malay paraphrase; approved."
    )
    assert _real_calls() == before  # provider-free resolution
    assert resolved["status"] == "VERIFIED"
    assert resolved["provenance"]["resolution"] == "MANUAL"
    assert resolved["provenance"]["reviewer_id"] == "staff_reviewer_1"

    # durable audit row
    reviews = await cfdb.list_reviews(b["benefit_id"])
    assert len(reviews) == 1
    audit = reviews[0]
    assert audit["action"] == "VERIFY"
    assert audit["from_status"] == "REVIEW_REQUIRED"
    assert audit["to_status"] == "VERIFIED"
    assert audit["reviewer_id"] == "staff_reviewer_1"
    assert audit["reviewer_note"]
    assert audit["pi_snapshot_id"] == snapshot_id

    # now build-eligible
    result = await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=_FakeProvider())
    assert result["status"] == "COMPLETED"


async def test_block_transitions_with_audit():
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, UNSUPPORTED, None)
    resolved = await svc.resolve_review(b["benefit_id"], "BLOCK", "staff_reviewer_2", "Not on-brand.")
    assert resolved["status"] == "BLOCKED"
    reviews = await cfdb.list_reviews(b["benefit_id"])
    assert reviews[-1]["action"] == "BLOCK"
    assert reviews[-1]["to_status"] == "BLOCKED"


async def test_blocked_benefit_is_not_resolvable():
    # A benefit already BLOCKED (not REVIEW_REQUIRED) cannot be promoted here.
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, UNSAFE, None)
    assert b["status"] == "BLOCKED"
    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.resolve_review(b["benefit_id"], "VERIFY", "staff_reviewer_3", "attempting bypass")
    assert exc.value.code == "NOT_REVIEW_REQUIRED"


async def test_hard_safety_block_not_promotable_on_verify():
    # A REVIEW_REQUIRED row whose text is actually unsafe must be REFUSED on VERIFY
    # (the endpoint re-asserts the deterministic gate and fails closed).
    product_id, _ = await _setup()
    contrived = await cfdb.create_benefit(
        {
            "benefit_id": cfdb.new_id("BEN"),
            "product_id": product_id,
            "canonical_text": UNSAFE,
            "text_digest": svc._text_digest(UNSAFE),
            "usage_hint": None,
            "status": "REVIEW_REQUIRED",
            "pi_check_json": {},
            "provenance_json": {"resolution": "AUTO"},
        }
    )
    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.resolve_review(contrived["benefit_id"], "VERIFY", "staff_reviewer_4", "should be refused")
    assert exc.value.code == "HARD_SAFETY_BLOCK_NOT_PROMOTABLE"
    # unchanged; no audit VERIFY recorded
    still = await cfdb.get_benefit(contrived["benefit_id"])
    assert still["status"] == "REVIEW_REQUIRED"
    assert await cfdb.list_reviews(contrived["benefit_id"]) == []
