"""B-604-01 — real tests that execute the PI-11 CORRECTIVE runner logic, including an integration
test against a temporary real SQLite DB fixture. These pin the frozen-blocker guarantees so the
generic-template regression that the owner audit rejected cannot recur.
"""
import importlib.util
import json
import os
import sqlite3
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pi11corr", REPO / "scripts" / "pi11_corrective_runner.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


# ── B-604-03: no generic overwrite of good existing intelligence ─────────────────────────────
def test_product_specific_description_is_preserved_not_templated():
    prior = {"product_description": "SkyPlant Eye Balm Stick 9g Korean Formula for the eye area."}
    rejected_generic = {"product_description": "X is a Beauty & Personal Care / Skincare product. "
                        "Used to hold and dispense its contents. This description is a neutral, "
                        "identity-based summary"}
    plan = C.build_correction_plan({"id": "p1"}, rejected_generic, prior, {}, {})
    assert plan["fields"]["product_description"] == prior["product_description"]
    assert plan["statuses"]["product_description"] == "PRESERVED_SPECIFIC"
    assert plan["decision"] == "RESTORE_APPROVE"


def test_generic_prior_is_neither_preserved_nor_refilled_with_filler():
    prior = {"product_description": "Widget is a Home / Storage product. This description is a "
             "neutral, identity-based summary; product-knowledge details ..."}
    plan = C.build_correction_plan({"id": "p2"}, {}, prior, {}, {})
    assert plan["fields"]["product_description"] is None
    assert plan["statuses"]["product_description"] == "MISSING_NO_SPECIFIC_SOURCE"
    assert plan["fields"]["usage_text"] is None  # NO "everyday purpose" fallback
    assert plan["decision"] == "LEAVE_INCOMPLETE"  # honestly incomplete, not generic-complete


# ── B-604-02: no unverified draft field becomes evidence ─────────────────────────────────────
def test_unverified_prior_ingredients_are_not_carried_as_evidence():
    prior = {"ingredients_text": "Organic herbal extracts (assume standard organic cream base)."}
    prov = {"ingredients_text": {"source_type": "REVIEWER_DISPOSITION", "verification_status": "DRAFT"}}
    plan = C.build_correction_plan({"id": "p3"}, {}, prior, prov, {})
    assert plan["fields"]["ingredients_text"] is None
    assert plan["statuses"]["ingredients_text"] == "SOURCE_UNAVAILABLE"


def test_externally_verified_ingredients_are_carried():
    prior = {"ingredients_text": "Aqua, Glycerin, Niacinamide."}
    prov = {"ingredients_text": {"source_type": "EXTERNAL_EXTRACTION", "verification_status": "EXTERNALLY_VERIFIED"}}
    plan = C.build_correction_plan({"id": "p4"}, {}, prior, prov, {})
    assert plan["fields"]["ingredients_text"] == prior["ingredients_text"]
    assert plan["statuses"]["ingredients_text"] == "CARRIED_EXTERNAL_EVIDENCE"
    assert "ingredients_text" in plan["grounded_facts"]
    assert plan["decision"] == "RESTORE_APPROVE"


# ── B-604-04: no safe allowed claim is moved to blocked ──────────────────────────────────────
def test_per_claim_reconciliation_keeps_safe_moves_only_unsafe():
    prior_allowed = ["Product type: Skincare (source: product identity).", "This cream cures eczema."]
    allowed, blocked, moved = C.reconcile_claims(prior_allowed, [])
    assert "Product type: Skincare (source: product identity)." in allowed
    assert "Product type: Skincare (source: product identity)." not in blocked
    assert "This cream cures eczema." in blocked and "This cream cures eczema." in moved


def test_prior_blocked_claims_are_retained_never_deleted():
    allowed, blocked, moved = C.reconcile_claims(["Safe identity fact (source: identity)."],
                                                 ["Do not claim it cures eczema"])
    assert "Do not claim it cures eczema" in blocked


# ── B-604-05: unsupported persona/strategy cannot leak downstream ────────────────────────────
def test_persona_strategy_is_sanitized_against_claim_gate():
    persona = {"audience": "shoppers", "desires": ["a cream that cures eczema", "gentle daily care"]}
    clean, removed = C.sanitize_planning(persona)
    assert "a cream that cures eczema" not in clean.get("desires", [])
    assert "gentle daily care" in clean.get("desires", [])
    assert any("cures eczema" in r for r in removed)


# ── B-604-06: size requires exact provenance ─────────────────────────────────────────────────
def test_size_needs_exact_provenance_else_source_unavailable():
    v, s = C.provenance_gated_knowledge("size_or_volume", "9g", None)
    assert v is None and s == "SOURCE_UNAVAILABLE"
    v2, s2 = C.provenance_gated_knowledge(
        "size_or_volume", "9g", {"source_type": "EXTERNAL_EXTRACTION", "verification_status": "VERIFIED"})
    assert v2 == "9g" and s2 == "CARRIED_EXTERNAL_EVIDENCE"


# ── B-604-01: rerun is idempotent by evidence digest ─────────────────────────────────────────
def test_plan_is_idempotent_by_digest():
    prior = {"product_description": "SkyPlant Eye Balm Stick 9g Korean Formula."}
    a = C.build_correction_plan({"id": "p"}, {}, prior, {}, {})
    b = C.build_correction_plan({"id": "p"}, {}, prior, {}, {})
    assert C.plan_digest(a) == C.plan_digest(b)


# ── B-604-01 integration: temporary real DB fixture; fixtures & lifecycle untouched ───────────
def _seed_tempdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE product(id TEXT PRIMARY KEY, raw_product_title TEXT, size_or_volume TEXT, lifecycle_status TEXT);
        CREATE TABLE product_intelligence_snapshot(
            snapshot_id TEXT, product_id TEXT, version INTEGER, status TEXT, approved_by TEXT,
            product_description TEXT, ingredients_text TEXT, warnings_text TEXT, benefits_json TEXT,
            usp_json TEXT, usage_text TEXT, target_customer_text TEXT, allowed_claims_json TEXT,
            blocked_claims_json TEXT, buyer_persona_snapshot_json TEXT, copy_strategy_summary_json TEXT,
            readiness_status TEXT, claim_gate TEXT);
        CREATE TABLE product_intelligence_field_provenance(field_name TEXT, snapshot_id TEXT, source_type TEXT, verification_status TEXT);
        CREATE TABLE product_intelligence_review_draft(product_id TEXT, reviewed_by TEXT, approved_by TEXT, created_at TEXT, updated_at TEXT, product_description TEXT);
        """)
    # archived product with a GOOD pre-PI-11 snapshot (v1) then the REJECTED generic PI-11 snapshot (v2)
    con.execute("INSERT INTO product(id,raw_product_title,size_or_volume,lifecycle_status) VALUES(?,?,?,?)",
                ("archp", "SkyPlant Eye Balm Stick 9g", "9g", "ARCHIVED"))
    con.execute("INSERT INTO product_intelligence_snapshot(snapshot_id,product_id,version,status,approved_by,product_description) "
                "VALUES('s1','archp',1,'SUPERSEDED','human-reviewer','SkyPlant Eye Balm Stick 9g Korean Formula for the eye area.')")
    con.execute("INSERT INTO product_intelligence_snapshot(snapshot_id,product_id,version,status,approved_by,product_description,readiness_status) "
                "VALUES('s2','archp',2,'APPROVED','claude-owner-delegated-pi11','SkyPlant is a Beauty product. This description is a neutral, identity-based summary','READY_WITH_GOVERNED_ABSENCE')")
    con.commit()
    con.row_factory = sqlite3.Row
    return path, con


def test_integration_restores_good_snapshot_and_never_reactivates_or_writes():
    path, con = _seed_tempdb()
    try:
        before = con.execute("SELECT COUNT(*) FROM product_intelligence_snapshot").fetchone()[0]
        ctx = C.load_context(con, "archp")
        # the restore source is the GOOD v1, not the rejected PI-11 v2
        assert ctx["prior"]["snapshot_id"] == "s1"
        plan = C.build_correction_plan(ctx["product"], ctx["current_pi11"], ctx["prior"],
                                       ctx["prior_prov"], ctx["cur_prov"])
        assert plan["fields"]["product_description"] == "SkyPlant Eye Balm Stick 9g Korean Formula for the eye area."
        assert plan["decision"] == "RESTORE_APPROVE"
        # lifecycle is never a planned field -> archived cannot be reactivated by the plan
        assert "lifecycle_status" not in plan["fields"]
        # dry-run path is read-only: nothing written
        res = C.dry_run(con, ["archp"])
        assert res[0]["decision"] == "RESTORE_APPROVE"
        after = con.execute("SELECT COUNT(*) FROM product_intelligence_snapshot").fetchone()[0]
        assert after == before
        assert con.execute("SELECT lifecycle_status FROM product WHERE id='archp'").fetchone()[0] == "ARCHIVED"
    finally:
        con.close()
        os.unlink(path)
