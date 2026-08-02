"""B-604-08 — mutation-proving tests for the PI-11 CORRECTIVE restore-only apply path, run against
a disposable real SQLite DB (the per-test throwaway configured by tests/conftest.py) through the
REAL FastAPI lifecycle: corrective review draft -> field dispositions -> validate -> approve
immutable vNext. Proves apply mutates only the intended product, never promotes unsupported prose,
leaves archived/fixtures untouched, is idempotent, and cleans up on failure.
"""
import asyncio
import importlib.util
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_intelligence import router as pi_router
from agent.api.products import router as products_router
from agent.db import crud
from agent.db.schema import get_db

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pi11corr", REPO / "scripts" / "pi11_corrective_runner.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

_SUPPORT = {"source_type": "EXTERNAL_EXTRACTION", "verification_status": "VERIFIED",
            "source_url": "https://s/x", "extraction_method": "dom_scrape"}


def _client():
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    app.include_router(pi_router, prefix="/api")
    return TestClient(app)


class _Adapter:
    def __init__(self, tc):
        self.tc = tc

    def request(self, method, path, body=None, timeout=60):
        r = self.tc.request(method, "/api" + path, json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}


def _supported_prior():
    return {
        "product_description": "Marble-pattern PVC wall sticker 30x60cm, waterproof, easy to cut.",
        "benefits_json": json.dumps(["waterproof surface", "cuts to size"]),
        "usp_json": json.dumps(["self-adhesive", "30x60cm tiles"]),
        "target_customer_text": "Home decorators refreshing walls affordably.",
        "buyer_persona_snapshot_json": json.dumps({"persona": "budget home decorators"}),
        "copy_strategy_summary_json": json.dumps({"angle": "affordable refresh"}),
        "source_urls_json": json.dumps({"source_url": "https://s/x"}),
        "image_evidence_json": json.dumps({"image_url": "https://img/x.jpg"}),
        "allowed_claims_json": json.dumps([]),
        "blocked_claims_json": json.dumps([]),
    }


def _full_support():
    return {f: dict(_SUPPORT) for f in C.RESTORABLE_REQUIRED}


def _seed_product(title="Corrective Test"):
    prod = asyncio.run(crud.create_product(
        raw_product_title=title, source="MANUAL", product_display_name=title, product_short_name=title))
    return prod["id"]


def _approvable_plan(pid):
    product = {"id": pid, "category": "Home & Living", "subcategory": "Decor", "type": "Wall Sticker",
               "claim_risk_level": "LOW"}
    return C.build_correction_plan(product, None, _supported_prior(), _full_support(),
                                   assert_identity_claims=True)


def _count_corrective_snaps(pid):
    async def _q():
        db = await get_db()
        cur = await db.execute(
            "SELECT COUNT(*) FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' "
            "AND approved_by LIKE 'claude-owner-delegated-pi11-corrective%'", (pid,))
        return (await cur.fetchone())[0]
    return asyncio.run(_q())


def test_apply_creates_vnext_only_for_intended_product():
    a = _seed_product("Intended A")
    b = _seed_product("Untouched B")
    plan = _approvable_plan(a)
    assert plan["decision"] == "RESTORE_APPROVE"
    res = C.apply_one(_Adapter(_client()), a, plan)
    assert res["result"] == "APPROVED", res
    assert _count_corrective_snaps(a) == 1
    assert _count_corrective_snaps(b) == 0  # only the intended product mutated


def test_leave_incomplete_is_not_applied():
    pid = _seed_product("Generic Only")
    # no supported prior -> LEAVE_INCOMPLETE
    plan = C.build_correction_plan({"id": pid, "category": "Home", "claim_risk_level": "LOW"}, None, {}, {})
    assert plan["decision"] == "LEAVE_INCOMPLETE"
    res = C.apply_one(_Adapter(_client()), pid, plan)
    assert res["result"] == "SKIPPED_NOT_APPROVABLE"
    assert _count_corrective_snaps(pid) == 0


def test_archived_lifecycle_unchanged():
    pid = _seed_product("Archived Product")

    async def _archive():
        db = await get_db()
        await db.execute("UPDATE product SET lifecycle_status='ARCHIVED' WHERE id=?", (pid,))
        await db.commit()
    asyncio.run(_archive())
    C.apply_one(_Adapter(_client()), pid, _approvable_plan(pid))

    async def _life():
        db = await get_db()
        cur = await db.execute("SELECT lifecycle_status FROM product WHERE id=?", (pid,))
        return (await cur.fetchone())[0]
    assert asyncio.run(_life()) == "ARCHIVED"  # corrective apply never touches the product row


def test_idempotent_skips_already_corrected():
    pid = _seed_product("Idempotent")
    plan = _approvable_plan(pid)
    r1 = C.apply_one(_Adapter(_client()), pid, plan)
    assert r1["result"] == "APPROVED"
    # second run, told it is already corrected -> no new snapshot
    r2 = C.apply_one(_Adapter(_client()), pid, plan, already_corrected=True)
    assert r2["result"] == "SKIPPED_ALREADY_CORRECTED"
    assert _count_corrective_snaps(pid) == 1
    # and the plan itself is idempotent
    assert C.plan_digest(plan) == C.plan_digest(_approvable_plan(pid))


def test_failure_leaves_no_partial_snapshot():
    pid = _seed_product("Failure Path")
    plan = _approvable_plan(pid)
    # force a mid-lifecycle failure: disposition a NON-eligible field -> server 422 -> abort+cleanup
    plan["disposition_map"] = {"product_description": {"disposition": "SOURCE_UNAVAILABLE"}}
    res = C.apply_one(_Adapter(_client()), pid, plan)
    assert res["result"] == "FAIL"
    assert _count_corrective_snaps(pid) == 0  # no partial approved snapshot survives

    async def _open_drafts():
        db = await get_db()
        cur = await db.execute(
            "SELECT COUNT(*) FROM product_intelligence_review_draft WHERE product_id=? "
            "AND review_status NOT IN ('REJECTED','SUPERSEDED','APPROVED')", (pid,))
        return (await cur.fetchone())[0]
    assert asyncio.run(_open_drafts()) == 0  # the corrective draft was rejected, not left open
