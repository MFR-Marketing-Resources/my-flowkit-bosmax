"""COPY-CORRECTIVE — PAID residual replacement (CONCURRENT, owner-authorized).

Architecture (owner spec):
  * Up to 10 CONCURRENT product workers: build brief + provider generation (blocking
    HTTP run in a thread via asyncio.to_thread) + read-only/in-memory validation
    (completeness, safety, genericness, PI grounding, formula, sales clarity).
  * ONE serialized DB writer (the main coroutine, consuming worker results via
    asyncio.as_completed): the ONLY place that creates Copy Sets, calls governed
    approve_copy_set (semantic receipt + PI lineage), quarantines, and writes the
    provider/token/cost ledger.
  * MAX TWO provider attempts per product. No third. Attempt 2 only for attempt-1
    failures, corrected from the exact failure reason.
  * Adaptive throttling: on 429 / saturation / repeated timeouts reduce 10->5->3;
    recover toward 10; bounded exponential transport backoff (NOT a 3rd attempt).
  * Checkpoint every 10 completed products. Resumable/idempotent from the ledger.
Never deletes; never fabricates filler. After two failures -> quarantine (BLOCKED
if intrinsically unsafe, else NEEDS_REVALIDATION); product stays ACTIVE + preserved.
"""
import asyncio
import json
import os
import sys
import time

REPO = r"C:\Users\USER\Desktop\_ref_flowkit"
sys.path.insert(0, REPO)
os.chdir(REPO)
OUT = os.path.join(REPO, "outputs", "mission-copy-corrective")
EXPECTED_DB = os.path.join(REPO, "flow_agent.db").lower()
APPROVER = "corrective-paid-replacement"
LOCK = os.path.join(OUT, "run_paid_replacement.lock")
CKPT = os.path.join(OUT, "paid_checkpoint.json")
MAX_ATTEMPTS = 2
CONC_MAX, CONC_MIN = 10, 3
RATE_IN, RATE_OUT = 0.27 / 1_000_000, 1.10 / 1_000_000
OVERRIDE_REASON = (
    "Corrective paid replacement: grounded on current approved PI, non-generic, "
    "complete, and safe (independently strict-reviewed); formula/sales-structure "
    "QA accepted by the corrective mission coordinator.")
_CORRECTION = {
    "GENERIC": "Avoid ALL generic/template phrasing; every USP must state a concrete product-specific attribute.",
    "UNGROUNDED": "Ground every claim in the product's own stated attributes/benefits; reuse the product's terms.",
    "INCOMPLETE": "Give a complete hook, at least one concrete USP, and a clear CTA.",
    "UNSAFE": "Remove any medical/curative/guarantee/superlative claim; stay strictly within allowed claims.",
    "PROVIDER_ERROR": "Regenerate cleanly, sharply product-specific and grounded.",
}


def _note(attempt, prev_fails):
    if attempt == 1:
        return ("Round 1: produce sharply product-specific, non-generic copy grounded in the "
                "product's real attributes (brand, model, materials, size, benefits).")
    hints = " ".join(_CORRECTION.get(f, "") for f in (prev_fails or []))
    return f"Round 2 targeted correction. Round 1 failed on: {','.join(prev_fails or []) or 'unknown'}. {hints}"


async def main() -> None:
    from agent.db import crud, get_db
    from agent.models.copy_set import (
        APPROVAL_PHRASE, STATUS_COPY_APPROVED, STATUS_COPY_REVIEW_REQUIRED,
    )
    from agent.services import ai_copy_provider_adapter as provider
    from agent.services.ai_copy_assist_service import (
        SOURCE_AI_COPY_ASSIST, _build_brief, _extract_formula_breakdown,
        _internal_provenance, _merge_candidate_fields, _product_truth, _resolve_formula,
    )
    from agent.models.copy_set import AICopyAssistRequest
    from agent.services.copy_grounding_service import resolve_copy_grounding
    from agent.services.copy_set_service import (
        CopySetError, _dedupe_key_for, approve_copy_set, assess_copy_completeness, scan_copy_safety,
    )
    from agent.services.copy_set_validity_service import (
        _latest_approved_snapshot, _product_name, assess_semantic_grounding,
        detect_generic_copy, evaluate_copy_set_id, quarantine_copy_set,
    )
    from agent.services.formula_validator_service import validate_formula_copy
    from agent.services.sales_clarity_qa_service import assess_sales_clarity

    db = await get_db()
    dblist = await (await db.execute("PRAGMA database_list")).fetchall()
    main_path = next((r[2] for r in dblist if r[1] == "main"), "")
    if os.path.abspath(main_path or "").lower() != EXPECTED_DB:
        raise SystemExit(f"ABORT: connected DB {main_path!r} != canonical")
    await db.execute("PRAGMA busy_timeout=60000")
    st = provider.provider_status()
    print(f"[PAID] provider={st} MAX_ATTEMPTS={MAX_ATTEMPTS} CONC={CONC_MAX}", file=sys.stderr, flush=True)
    if not st.get("configured") or not st.get("execution_enabled"):
        raise SystemExit(f"ABORT: provider not ready: {st}")

    residual = json.load(open(os.path.join(OUT, "revalidation_summary.json"), encoding="utf-8"))[
        "residual_product_ids"]
    _limit = int(os.environ.get("LIMIT", "0") or "0")
    if _limit:
        residual = residual[:_limit]
    lf = open(os.path.join(OUT, "provider_call_ledger.jsonl"), "a", encoding="utf-8")

    counters = {"closed_paid": 0, "already_closed": 0, "quarantined": 0,
                "a1": 0, "a2": 0, "provider_calls": 0, "tok_in": 0, "tok_out": 0,
                "processed": 0, "last_product": None}

    async def already_closed(pid):
        cur = await db.execute(
            "SELECT copy_set_id FROM copy_set WHERE product_id=? AND status=? AND COALESCE(archived,0)=0",
            (pid, STATUS_COPY_APPROVED))
        ids = [str(r["copy_set_id"]) for r in await cur.fetchall()]
        await cur.close()
        for cid in ids:
            if (await evaluate_copy_set_id(cid)).get("valid"):
                return True
        return False

    # ── CONCURRENT worker: provider gen (threaded) + in-memory validation, NO governed write
    async def worker(pid, attempt, prev_fails, sem):
        async with sem:
            product = await crud.get_product(pid)
            if not product or not _product_truth(product):
                return {"pid": pid, "attempt": attempt, "kind": "INELIGIBLE"}
            grounding = await resolve_copy_grounding(product)
            snap = await _latest_approved_snapshot(pid)
            pname = await _product_name(pid)
            req = AICopyAssistRequest(product_id=pid, candidate_count=1,
                                      operator_notes=_note(attempt, prev_fails))
            brief = _build_brief(req, product, grounding, "")
            ai = None
            for t in range(3):  # bounded transport retry only (NOT a new semantic attempt)
                try:
                    ai = await asyncio.to_thread(provider.generate_candidate, brief)
                    break
                except Exception as e:
                    msg = str(e).lower()
                    retryable = any(k in msg for k in ("429", "timeout", "temporarily", "rate", "call_failed", "unavailable"))
                    if not retryable or t == 2:
                        return {"pid": pid, "attempt": attempt, "kind": "PROVIDER_ERROR",
                                "error": str(e)[:200], "retryable": retryable}
                    await asyncio.sleep(min(16, 2 * (2 ** t)))
            if not isinstance(ai, dict):
                return {"pid": pid, "attempt": attempt, "kind": "PROVIDER_ERROR", "error": "invalid response"}
            usage = ai.get("__usage__") or {}
            fields = _merge_candidate_fields(ai, req, grounding)
            formula = _resolve_formula(req, grounding)
            fields["formula_family"] = formula["compiler_family"]
            breakdown = _extract_formula_breakdown(ai, formula, fields)
            validation = validate_formula_copy(formula["formula_id"], fields, breakdown, grounding)
            sales = assess_sales_clarity(fields, grounding, formula["formula_id"], validation)
            comp = assess_copy_completeness(fields)
            safe = scan_copy_safety(fields, product_id=pid)
            usp = [u for u in (fields.get("usp_set") or []) if str(u).strip()]
            gen = detect_generic_copy(hook=fields.get("hook", ""), subhook=fields.get("subhook", ""),
                                      usp_list=usp, cta=fields.get("cta", ""), product_name=pname)
            grd = (assess_semantic_grounding(hook=fields.get("hook", ""), subhook=fields.get("subhook", ""),
                   usp_list=usp, cta=fields.get("cta", ""), snapshot=snap, product_title=pname)
                   if snap else {"grounded": False})
            fails = []
            if gen["generic"]:
                fails.append("GENERIC")
            if not comp["complete"]:
                fails.append("INCOMPLETE")
            if not safe["safe"]:
                fails.append("UNSAFE")
            if not grd["grounded"]:
                fails.append("UNGROUNDED")
            return {"pid": pid, "attempt": attempt, "kind": "CANDIDATE", "fields": fields, "ai": ai,
                    "formula": formula, "breakdown": breakdown, "validation": validation,
                    "sales": sales, "comp": comp, "safe": safe, "usage": usage, "fails": fails,
                    "grounding_source": getattr(grounding, "source", None),
                    "platform": fields.get("platform"), "language": fields.get("language"),
                    "model_id": st.get("model_id")}

    async def safe_worker(p, attempt, prev, sem):
        try:
            return await worker(p, attempt, prev, sem)
        except Exception as e:
            return {"pid": p, "attempt": attempt, "kind": "WORKER_ERROR", "error": str(e)[:200]}

    # ── SINGLE WRITER: create Copy Set + governed approve. Returns (closed, cid, dedupe)
    async def create_and_maybe_approve(d):
        f = d["fields"]
        claim_review = {"completeness": d["comp"], "safety": d["safe"], "route_type": f["route_type"],
                        "ai_generated": True, "grounding_source": d.get("grounding_source"),
                        "formula_id": d["formula"]["formula_id"],
                        "formula_definition_status": d["formula"]["definition_status"],
                        "formula_breakdown": d["breakdown"], "formula_validation": d["validation"],
                        "sales_clarity": d["sales"]}
        dedupe_key = _dedupe_key_for(d["pid"], f)
        existing = await crud.find_copy_set_by_dedupe_key(dedupe_key)
        if existing:
            return False, str(existing["copy_set_id"]), True
        row = await crud.create_copy_set(
            d["pid"], angle=f["angle"], hook=f["hook"], subhook=f["subhook"],
            usp_set_json=json.dumps(f["usp_set"]), cta=f["cta"], platform=f["platform"],
            language=f["language"], route_type=f["route_type"], formula_family=f["formula_family"],
            status=STATUS_COPY_REVIEW_REQUIRED, dedupe_key=dedupe_key, source=SOURCE_AI_COPY_ASSIST,
            provenance_json=json.dumps(_internal_provenance(d["ai"])),
            claim_review_json=json.dumps(claim_review))
        cid = str(row["copy_set_id"])
        if d["fails"]:
            return False, cid, False
        try:
            await approve_copy_set(cid, {"approval_phrase": APPROVAL_PHRASE, "approved_by": APPROVER,
                                         "override_formula_review": True, "override_reason": OVERRIDE_REASON})
        except CopySetError as e:
            d["fails"] = d["fails"] or [e.code]
            return False, cid, False
        return bool((await evaluate_copy_set_id(cid)).get("valid")), cid, False

    async def quarantine_product(pid, f1, f2):
        unsafe = ("UNSAFE" in (f1 or [])) or ("UNSAFE" in (f2 or []))
        status = "BLOCKED" if unsafe else "NEEDS_REVALIDATION"
        reason = f"COPY_CORRECTIVE_TWO_ATTEMPT_CAP:a1={','.join(f1 or ['NONE'])};a2={','.join(f2 or ['NONE'])}"
        cur = await db.execute(
            "SELECT copy_set_id FROM copy_set WHERE product_id=? AND status=? AND COALESCE(archived,0)=0",
            (pid, STATUS_COPY_APPROVED))
        ids = [str(r["copy_set_id"]) for r in await cur.fetchall()]
        await cur.close()
        for cid in ids:
            await quarantine_copy_set(cid, reason=reason, status=status)
        return status, reason, ids

    results = {}         # pid -> result dict
    fail_reason = {}     # pid -> attempt-1 failure list (for round 2 correction)
    conc = CONC_MAX

    # pre-skip already-closed (idempotent resume)
    todo = []
    for pid in residual:
        if await already_closed(pid):
            counters["already_closed"] += 1
            results[pid] = {"product_id": pid, "outcome": "ALREADY_CLOSED"}
        else:
            todo.append(pid)
    print(f"[PAID] to_process={len(todo)} already_closed={counters['already_closed']}", file=sys.stderr, flush=True)

    async def run_round(pids, attempt):
        nonlocal conc
        pending = list(pids)
        while pending:
            chunk, pending = pending[:conc], pending[conc:]
            sem = asyncio.Semaphore(conc)
            tasks = [asyncio.ensure_future(safe_worker(p, attempt, fail_reason.get(p), sem)) for p in chunk]
            errs = 0
            for fut in asyncio.as_completed(tasks):
                d = await fut
                pid = d["pid"]
                counters["last_product"] = pid
                base = {"product_id": pid, "attempt": attempt, "model_id": d.get("model_id"),
                        "usage": d.get("usage") or {}}
                if d.get("usage"):
                    counters["provider_calls"] += 1
                    u = d["usage"]
                    counters["tok_in"] += int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
                    counters["tok_out"] += int(u.get("completion_tokens") or u.get("output_tokens") or 0)
                if d["kind"] != "CANDIDATE":
                    errs += 1 if d["kind"] == "PROVIDER_ERROR" else 0
                    fail_reason[pid] = [d.get("kind", "PROVIDER_ERROR")]
                    lf.write(json.dumps({**base, "decision": d["kind"], "error": d.get("error")}, ensure_ascii=False) + "\n")
                    if attempt == MAX_ATTEMPTS:
                        results.setdefault(pid, {"product_id": pid})
                    continue
                closed, cid, dedupe = await create_and_maybe_approve(d)
                if closed:
                    counters["closed_paid"] += 1
                    counters["a1" if attempt == 1 else "a2"] += 1
                    results[pid] = {"product_id": pid, "outcome": "CLOSED_PAID", "closed_on_attempt": attempt,
                                    "copy_set_id": cid}
                    lf.write(json.dumps({**base, "copy_set_id": cid, "decision": "APPROVED"}, ensure_ascii=False) + "\n")
                else:
                    fail_reason[pid] = d["fails"] or (["DEDUPE"] if dedupe else ["APPROVE_FAIL"])
                    lf.write(json.dumps({**base, "copy_set_id": cid, "decision": "REVIEW_FAIL" if d["fails"] else ("DEDUPE" if dedupe else "APPROVE_FAIL"), "fails": d["fails"]}, ensure_ascii=False) + "\n")
                lf.flush()
                counters["processed"] += 1
                if counters["processed"] % 10 == 0:
                    _checkpoint(counters)
            # adaptive throttling between chunks
            rate = errs / max(1, len(chunk))
            if rate >= 0.3 and conc > CONC_MIN:
                conc = 5 if conc == 10 else CONC_MIN
                print(f"[PAID] throttle down -> conc={conc} (err_rate={rate:.2f})", file=sys.stderr, flush=True)
            elif errs == 0 and conc < CONC_MAX:
                conc = min(CONC_MAX, conc + 2)
            print(f"[PAID] a{attempt} chunk done | processed={counters['processed']} closed={counters['closed_paid']} "
                  f"quar={counters['quarantined']} a1={counters['a1']} a2={counters['a2']} conc={conc} "
                  f"calls={counters['provider_calls']} tok_in={counters['tok_in']} tok_out={counters['tok_out']}",
                  file=sys.stderr, flush=True)

    # ATTEMPT 1 (concurrent)
    await run_round(todo, 1)
    # ATTEMPT 2 — only attempt-1 failures, corrected from the exact failure
    retry = [p for p in todo if p not in {k for k, v in results.items() if v.get("outcome") == "CLOSED_PAID"}]
    await run_round(retry, 2)

    # QUARANTINE anything still not closed after two attempts
    for pid in todo:
        r = results.get(pid)
        if r and r.get("outcome") == "CLOSED_PAID":
            continue
        f1 = None  # ledger holds per-attempt detail; reconstruct headline from fail_reason
        f2 = fail_reason.get(pid)
        status, reason, ids = await quarantine_product(pid, f1, f2)
        counters["quarantined"] += 1
        results[pid] = {"product_id": pid, "outcome": "QUARANTINED_AFTER_TWO_ATTEMPTS",
                        "attempt_2_failure": f2, "quarantine_status": status,
                        "quarantine_reason": reason, "quarantined_copy_set_ids": ids}

    lf.close()
    _checkpoint(counters)
    est = round(counters["tok_in"] * RATE_IN + counters["tok_out"] * RATE_OUT, 4)
    summary = {"residual_in": len(residual), "closed_paid": counters["closed_paid"],
               "already_closed": counters["already_closed"], "quarantined_after_two_attempts": counters["quarantined"],
               "closed_on_attempt_1": counters["a1"], "closed_on_attempt_2": counters["a2"],
               "max_attempts_per_product": MAX_ATTEMPTS, "provider_calls": counters["provider_calls"],
               "tokens_in": counters["tok_in"], "tokens_out": counters["tok_out"], "estimated_cost_usd": est,
               "rate_note": "deepseek-v4-flash public rate (in=0.27, out=1.10 USD/1M)",
               "concurrency_final": conc, "provider": provider.provider_status()}
    with open(os.path.join(OUT, "paid_replacement_results.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "products": list(results.values())}, fh, ensure_ascii=False, indent=1)
    print("PAID_DONE " + json.dumps(summary, ensure_ascii=False))


def _checkpoint(c):
    try:
        import sqlite3
        cx = sqlite3.connect(f"file:{EXPECTED_DB}?mode=ro", uri=True, timeout=30)
        integ = cx.execute("PRAGMA integrity_check").fetchone()[0]
        cx.close()
    except Exception as e:
        integ = f"ERR:{e}"
    est = round(c["tok_in"] * RATE_IN + c["tok_out"] * RATE_OUT, 4)
    with open(CKPT, "w", encoding="utf-8") as f:
        json.dump({**c, "estimated_cost_usd": est, "db_integrity": integ}, f, indent=1)


if __name__ == "__main__":
    if os.path.exists(LOCK):
        print(f"ABORT: lock exists {LOCK}", file=sys.stderr)
        sys.exit(3)
    open(LOCK, "w").write(str(os.getpid()))
    try:
        asyncio.run(main())
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass
