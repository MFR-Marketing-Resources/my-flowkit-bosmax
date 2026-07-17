"""Production Queue — executes APPROVED prompt packages through the one
hardened generate lane (ADR-007) with interval + cooldown throttling.

Prompt/production split: the Prompt Queue (workspace_generation_package)
stores polished prompts; NOTHING here runs until a package is explicitly
APPROVED and sent to a production run. Live execution burns Google Flow
credits, so it is fail-closed twice:

  1. every run is created dry_run=1 — dry runs only validate payload mapping;
  2. a live run additionally requires confirm_live_credit_burn=true.

Item lifecycle (workspace_generation_package.production_status):
  NONE → APPROVED → QUEUED → RUNNING → GENERATED → DOWNLOADED
                                     ↘ FAILED / CANCELLED
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import uuid

from agent.db import crud
from agent.services import batch_prompt_planner as planner

logger = logging.getLogger(__name__)

PRODUCTION_STATUSES = (
    "NONE", "APPROVED", "QUEUED", "RUNNING",
    "GENERATED", "DOWNLOADED", "FAILED", "CANCELLED",
)

# Flow media ids are bare UUIDs — composite BOSMAX asset ids are NOT
# (mirrors the manual-lane _FLOW_MEDIA_UUID_RE gate; locked contract).
_FLOW_MEDIA_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# run_id → "PAUSE" | "CANCEL" control signals for the live loop
_run_control: dict[str, str] = {}
# O4: dedupe keys of submissions currently in flight. In-process by design — it
# guards the single provider boundary inside this worker, like _run_control above.
_inflight_dedupe: set[str] = set()

_POLL_SECONDS = 5
_JOB_TIMEOUT_SECONDS = 30 * 60
_INFLIGHT_RETRY_SECONDS = 30

# Round F — the one-serial T2V live lane.
#
# This gate is OPT-IN: it applies only when a caller asks for the
# LIVE_GATE_ONE_SERIAL_T2V lane. The pre-existing live path (ProductionQueuePage)
# is a protected system (G0 §3) and keeps its own semantics untouched — widening
# this gate to cover it would be a separate owner decision, not a Round F change.
LIVE_GATE_ONE_SERIAL_T2V = "ONE_SERIAL_T2V"
LIVE_CONFIRM_PHRASE = "AUTHORIZE_ONE_T2V_LIVE_RUN"
_INFLIGHT_MAX_RETRIES = 20


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _loads(raw, default):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else default
    except Exception:
        return default


# ── Approval ──────────────────────────────────────────────────────────────


async def approve_packages(package_ids: list[str]) -> dict:
    """Prompt-side approval gate: READY_MANUAL packages become APPROVED
    (production_status). Blocked/draft/archived packages are refused."""
    results = []
    approved = 0
    for wgp_id in package_ids:
        row = await crud.get_workspace_generation_package(wgp_id)
        if not row:
            results.append({"package_id": wgp_id, "ok": False, "error": "NOT_FOUND"})
            continue
        if row.get("status") not in ("READY_MANUAL", "READY_DOM_STAGED"):
            results.append({
                "package_id": wgp_id, "ok": False,
                "error": f"NOT_APPROVABLE_STATUS:{row.get('status')}",
            })
            continue
        current = row.get("production_status") or "NONE"
        if current not in ("NONE", "", "CANCELLED", "FAILED"):
            results.append({
                "package_id": wgp_id, "ok": False,
                "error": f"ALREADY_IN_PRODUCTION:{current}",
            })
            continue
        await crud.update_workspace_generation_package(
            wgp_id, production_status="APPROVED", approved_at=_now(), production_error=None,
        )
        approved += 1
        results.append({"package_id": wgp_id, "ok": True, "production_status": "APPROVED"})
    return {"approved": approved, "results": results}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Enqueue ───────────────────────────────────────────────────────────────


async def send_to_production(
    package_ids: list[str],
    *,
    interval_min_seconds: int = 45,
    interval_max_seconds: int = 120,
    cooldown_after_n_jobs: int = 5,
    cooldown_seconds: int = 300,
    aspect: str = "9:16",
    model: str | None = None,
    count: int = 1,
) -> dict:
    """Create a production run from APPROVED packages and queue them.

    The run is created dry_run=1: nothing fires until run_production_queue is
    called, and live credit burn additionally needs explicit confirmation.
    """
    if not package_ids:
        raise ValueError("NO_PACKAGES_SELECTED")
    if interval_min_seconds < 0 or interval_max_seconds < interval_min_seconds:
        raise ValueError("INVALID_INTERVAL_RANGE")

    # Engine/model law: the operator must pick a model from the standard
    # registry (Omni Flash / Veo 3.1 Lite / Fast / Quality). No silent
    # defaulting, unknown model FAILS CLOSED (mirrors the generate lane).
    from agent.services import video_models as _vm
    if not str(model or "").strip():
        raise ValueError("MODEL_REQUIRED")
    try:
        resolved_model = _vm.resolve(model)
    except ValueError:
        raise ValueError(f"ERR_UNKNOWN_MODEL:{model}")

    eligible: list[dict] = []
    refused: list[dict] = []
    for wgp_id in package_ids:
        row = await crud.get_workspace_generation_package(wgp_id)
        if not row:
            refused.append({"package_id": wgp_id, "error": "NOT_FOUND"})
            continue
        if (row.get("production_status") or "NONE") != "APPROVED":
            refused.append({
                "package_id": wgp_id,
                "error": f"NOT_APPROVED:{row.get('production_status') or 'NONE'}",
            })
            continue
        eligible.append(row)
    if not eligible:
        raise ValueError("NO_APPROVED_PACKAGES:" + _json(refused))

    run_id = f"prun_{uuid.uuid4().hex[:16]}"
    config = {
        "package_ids": [r["workspace_generation_package_id"] for r in eligible],
        "aspect": aspect,
        "model": resolved_model["ui_label"],
        "model_key": resolved_model["key"],
        "count": max(1, min(4, int(count or 1))),
    }
    run = await crud.create_production_run(
        run_id,
        dry_run=True,
        max_parallel_jobs=1,
        interval_min_seconds=interval_min_seconds,
        interval_max_seconds=interval_max_seconds,
        cooldown_after_n_jobs=cooldown_after_n_jobs,
        cooldown_seconds=cooldown_seconds,
        total_expected=len(eligible),
        config_json=_json(config),
    )
    now = _now()
    for row in eligible:
        await crud.update_workspace_generation_package(
            row["workspace_generation_package_id"],
            production_status="QUEUED",
            production_run_id=run_id,
            sent_to_production_at=now,
        )
    run["refused"] = refused
    return run


# ── Payload mapping ───────────────────────────────────────────────────────


async def build_execution_payload(pkg: dict, run_config: dict | None = None) -> tuple[dict, list[str]]:
    """Map one prompt package to the one-door GenerateRequest payload.

    logical_mode is preserved on the package; only the engine payload maps
    HYBRID → F2V (product-anchor lane). Returns (payload, blockers) —
    non-empty blockers mean the item must NOT fire.
    """
    cfg = run_config or {}
    blockers: list[str] = []
    logical_mode = (pkg.get("logical_mode") or "").strip().upper()
    if not logical_mode:
        # Legacy packages: derive from stored mode/source_lane without relabelling.
        mode = (pkg.get("mode") or "").strip().upper()
        lane = (pkg.get("source_lane") or "").strip().upper()
        logical_mode = "HYBRID" if (mode == "F2V" and lane == "HYBRID") else mode
    engine_mode = planner.ENGINE_MODES.get(logical_mode)
    if not engine_mode:
        return {}, [f"UNSUPPORTED_LOGICAL_MODE:{logical_mode}"]

    prompt = pkg.get("final_prompt_text") or ""
    if not prompt.strip():
        blockers.append("EMPTY_FINAL_PROMPT")

    # Resolve Flow media ids for image slots. Composite BOSMAX asset ids are
    # not Flow media ids — each slot must resolve to an uploaded UUID.
    image_media_ids: list[str] = []
    slots = _loads(pkg.get("resolved_engine_slots_json"), {})
    if engine_mode in ("F2V", "I2V") and isinstance(slots, dict):
        for slot_key, asset_ref in slots.items():
            if not asset_ref:
                continue
            media_id = await _resolve_flow_media_id(str(asset_ref), pkg)
            if media_id:
                image_media_ids.append(media_id)
            else:
                blockers.append(f"SLOT_NOT_UPLOADED_TO_FLOW:{slot_key}")
    if engine_mode in ("F2V", "I2V") and not image_media_ids:
        blockers.append("NO_FLOW_MEDIA_FOR_IMAGE_MODE")

    duration_s = None
    dom = _loads(pkg.get("dom_handoff_payload_json"), {})
    settings = dom.get("settings") if isinstance(dom, dict) else None
    if isinstance(settings, dict) and settings.get("duration_seconds"):
        try:
            duration_s = int(settings["duration_seconds"])
        except (TypeError, ValueError):
            duration_s = None

    # Model law at fire time: no silent Lite default, unknown model or a
    # duration the engine can't do in one shot FAILS CLOSED as a blocker
    # (mirrors the generate-door validation; USER SETTINGS ARE LAW).
    model = str(cfg.get("model") or "").strip()
    if not model:
        blockers.append("MODEL_REQUIRED")
    elif engine_mode in ("T2V", "I2V", "F2V"):
        from agent.services import video_models as _vm
        try:
            _vm.expected_cost(model, duration_s)
        except ValueError as exc:
            blockers.append(f"ENGINE_VALIDATION:{exc}")

    payload = {
        "mode": engine_mode,
        "prompt": prompt,
        "image_media_ids": image_media_ids or None,
        "aspect": cfg.get("aspect") or "9:16",
        "model": cfg.get("model"),
        "duration_s": duration_s,
        "num_videos": cfg.get("count") or 1,
        "logical_mode": logical_mode,
        "execution_lane": planner.EXECUTION_LANES.get(logical_mode, engine_mode),
    }
    return payload, blockers


async def _resolve_flow_media_id(asset_ref: str, pkg: dict) -> str | None:
    """asset_ref → Flow media UUID, or None when nothing is uploaded yet."""
    if _FLOW_MEDIA_UUID_RE.match(asset_ref):
        return asset_ref
    if asset_ref.startswith("product-image:"):
        product = await crud.get_product(pkg.get("product_id") or "")
        media_id = (product or {}).get("media_id") or ""
        return media_id if _FLOW_MEDIA_UUID_RE.match(media_id) else None
    try:
        asset = await crud.get_creative_asset(asset_ref)
    except Exception:
        asset = None
    media_id = (asset or {}).get("media_id") or ""
    return media_id if _FLOW_MEDIA_UUID_RE.match(media_id) else None


# ── Run control ───────────────────────────────────────────────────────────


def pause_production_run(run_id: str) -> None:
    _run_control[run_id] = "PAUSE"


def cancel_production_run_signal(run_id: str) -> None:
    _run_control[run_id] = "CANCEL"


async def retry_failed_items(run_id: str) -> dict:
    """FAILED items in the run go back to QUEUED; the run returns to PENDING."""
    run = await crud.get_production_run(run_id)
    if not run:
        raise ValueError("RUN_NOT_FOUND")
    if run.get("status") == "RUNNING":
        raise ValueError("RUN_STILL_RUNNING")
    items = await crud.list_production_queue_packages(production_run_id=run_id)
    retried = 0
    for item in items:
        if item.get("production_status") == "FAILED":
            await crud.update_workspace_generation_package(
                item["workspace_generation_package_id"],
                production_status="QUEUED", production_error=None,
                # Explicit retry identity (O4): clearing the prior job id is what
                # authorises a second submission of this package. Without it the
                # duplicate guard in _fire_and_wait would refuse the retry.
                production_job_id=None,
            )
            retried += 1
    if retried:
        await crud.update_production_run(run_id, status="PENDING")
    return {"retried": retried}


# ── Execution ─────────────────────────────────────────────────────────────


async def _persist_generation_identity(wgp_id: str, job_id: str) -> dict:
    """Snapshot the provider identity of `job_id` onto its package, durably.

    Fail-soft: identity is evidence, not a gate — a snapshot error must never
    abort a submission that already spent credits. What it must never do is
    invent an anchor; absent anchors are recorded as absent.
    """
    from agent.services import make_video

    identity: dict = {}
    try:
        job = make_video.get_job(job_id) or {}
        identity = {
            "provider_job_id": job_id,
            "mode": job.get("mode"),
            "requested_model": job.get("model"),
            "num_videos": job.get("num_videos"),
            "project_id": (job.get("binding") or {}).get("project_id"),
            "flow_tab_id": (job.get("binding") or {}).get("flow_tab_id"),
            "anchors": job.get("generation_identity") or {},
            # The decisive field: False means NO retrieved media can ever be bound
            # to this run, so a later "not retrieved" is a capture gap, not a
            # retrieval bug (live g_e71cd329b524).
            "identity_captured": bool(job.get("identity_captured")),
            "gen_tool_matched": bool(job.get("gen_tool_matched")),
            "tools_seen": job.get("tools_seen") or [],
            "submitted_at": _now(),
        }
        await crud.update_workspace_generation_package(
            wgp_id, generation_identity_json=_json(identity),
        )
        if not identity["identity_captured"]:
            logger.warning(
                "OUTPUT_IDENTITY_NOT_CAPTURED wgp=%s job=%s tools_seen=%s — this run "
                "cannot bind any output; add the generation toolName to "
                "agent_video._GEN_TOOLS", wgp_id, job_id, identity["tools_seen"],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("identity snapshot failed wgp=%s job=%s: %s", wgp_id, job_id, exc)
    return identity


async def _persist_binding_outcome(wgp_id: str, job_id: str) -> None:
    """Record WHY binding succeeded or failed, durably, once the job is terminal.

    The submission snapshot says whether an output *could* be bound; this says
    what actually happened to the candidates. Without it the rejection evidence
    (which media were refused, and for which reason) lives only in make_video's
    in-memory _JOBS and is gone on restart — exactly the state that made
    g_e71cd329b524 impossible to adjudicate after the fact.

    Fail-soft and merge-only: never overwrite the submission anchors, never
    raise into a paid job.
    """
    from agent.services import make_video

    try:
        job = make_video.get_job(job_id) or {}
        row = await crud.get_workspace_generation_package(wgp_id) or {}
        identity = _loads(row.get("generation_identity_json"), {}) or {}
        stats = job.get("correlation_stats") or {}
        identity["binding_outcome"] = {
            "job_status": job.get("status"),
            "bound_media_id": job.get("media_id"),
            "bound": bool(job.get("media_id")),
            # The acceptance receipt when bound: what it matched on and why
            # (make_video stores it as output_correlation).
            "evidence": job.get("output_correlation"),
            # The refusal receipt when not bound.
            "rejected_candidate_ids": list(stats.get("round_rejected_ids") or []),
            "unverifiable_ids": list(stats.get("unverifiable_ids") or []),
            "prompt_mismatched": stats.get("prompt_mismatched"),
            "model_mismatched": stats.get("model_mismatched"),
            "seed_mismatched": stats.get("seed_mismatched"),
            "unverifiable": stats.get("unverifiable"),
            "reason": job.get("error") or job.get("original_error"),
            "credit_spent_likely": bool(job.get("credit_spent_likely")),
            "recorded_at": _now(),
        }
        await crud.update_workspace_generation_package(
            wgp_id, generation_identity_json=_json(identity),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("binding outcome snapshot failed wgp=%s job=%s: %s",
                       wgp_id, job_id, exc)


async def _assert_one_serial_t2v_live(
    run: dict,
    *,
    confirm_phrase: str | None,
    expect_package_id: str | None,
) -> dict:
    """Round F gate: refuse anything that is not ONE ready serial T2V item.

    Every check raises rather than returning a flag — the live branch must be
    unreachable unless all of them pass. Readiness is RE-DERIVED here from
    build_execution_payload rather than read from `last_dry_run_report`, so a
    package that changed between the dry run and the live click cannot fire on a
    stale green report. Returns the single validated item.
    """
    if (confirm_phrase or "").strip() != LIVE_CONFIRM_PHRASE:
        raise ValueError("LIVE_CONFIRM_PHRASE_INVALID")

    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    # The live loop fans out over EVERY queued item, so >1 item is a bulk run.
    if len(items) != 1:
        raise ValueError(f"LIVE_REQUIRES_EXACTLY_ONE_ITEM:{len(items)}")
    item = items[0]
    package_id = item["workspace_generation_package_id"]

    if expect_package_id and expect_package_id != package_id:
        raise ValueError(f"LIVE_PACKAGE_MISMATCH:{package_id}")

    product_id = str(item.get("product_id") or "")
    if product_id.startswith("fastmoss-ref:"):
        raise ValueError(f"LIVE_FASTMOSS_REF_FORBIDDEN:{product_id}")

    # Pre-flight duplicate check. O4's guard inside _fire_and_wait is the real
    # provider-boundary defence and is NOT replaced — this only fails faster.
    prior_job = str(item.get("production_job_id") or "").strip()
    if prior_job:
        raise ValueError(f"LIVE_DUPLICATE_SUBMISSION:{prior_job}")

    cfg = _loads(run.get("config_json"), {})
    payload, blockers = await build_execution_payload(item, cfg)
    logical_mode = (payload.get("logical_mode") or "").strip().upper()
    if logical_mode != "T2V":
        raise ValueError(f"LIVE_T2V_ONLY:{logical_mode or 'UNKNOWN'}")
    if blockers:
        raise ValueError(f"LIVE_ITEM_BLOCKED:{','.join(blockers)}")

    # A dry run must actually have been performed and been green. This is the
    # procedural gate (operator followed the drill); the re-derivation above is
    # the authoritative one.
    report = cfg.get("last_dry_run_report")
    if not isinstance(report, dict):
        raise ValueError("LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN")
    if int(report.get("ready") or 0) != 1 or int(report.get("blocked") or 0) != 0:
        raise ValueError(
            f"LIVE_REQUIRES_DRY_RUN_READY:ready={report.get('ready')},"
            f"blocked={report.get('blocked')}"
        )
    return item


async def run_production_queue(
    run_id: str,
    *,
    confirm_live_credit_burn: bool = False,
    live_gate: str | None = None,
    confirm_phrase: str | None = None,
    expect_package_id: str | None = None,
) -> dict:
    """Start a production run.

    Without confirm_live_credit_burn the run stays a DRY RUN: every queued
    item's payload is validated and reported, no generation fires, no credits
    are spent, items stay QUEUED. With confirmation the live loop fires each
    item through make_video.start_generate honouring interval + cooldown.

    live_gate=ONE_SERIAL_T2V opts into the Round F gate, which refuses anything
    that is not exactly one ready T2V item confirmed by the exact phrase.
    """
    run = await crud.get_production_run(run_id)
    if not run:
        raise ValueError("RUN_NOT_FOUND")
    if run.get("status") not in ("PENDING", "PAUSED"):
        raise ValueError(f"RUN_NOT_STARTABLE:{run.get('status')}")

    if not confirm_live_credit_burn:
        report = await _dry_run_report(run)
        cfg = _loads(run.get("config_json"), {})
        cfg["last_dry_run_report"] = report
        await crud.update_production_run(
            run_id, config_json=_json(cfg),
        )
        return {"run_id": run_id, "dry_run": True, "report": report}

    gated_package_id: str | None = None
    if live_gate:
        if live_gate != LIVE_GATE_ONE_SERIAL_T2V:
            raise ValueError(f"LIVE_GATE_UNKNOWN:{live_gate}")
        # Raises on any refusal — before any state change, so a refused live
        # request leaves the run exactly as it was (still dry, still PENDING).
        item = await _assert_one_serial_t2v_live(
            run, confirm_phrase=confirm_phrase, expect_package_id=expect_package_id,
        )
        gated_package_id = item["workspace_generation_package_id"]

    await crud.update_production_run(run_id, dry_run=0, status="RUNNING")
    _run_control.pop(run_id, None)
    asyncio.ensure_future(_live_production_loop(run_id))
    return {
        "run_id": run_id, "dry_run": False, "status": "RUNNING",
        "live_gate": live_gate, "package_id": gated_package_id,
    }


async def _dry_run_report(run: dict) -> dict:
    cfg = _loads(run.get("config_json"), {})
    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    results = []
    ready = 0
    for item in items:
        payload, blockers = await build_execution_payload(item, cfg)
        ok = not blockers
        ready += 1 if ok else 0
        results.append({
            "package_id": item["workspace_generation_package_id"],
            "logical_mode": payload.get("logical_mode"),
            "engine_mode": payload.get("mode"),
            "execution_lane": payload.get("execution_lane"),
            "model": payload.get("model"),
            "duration_s": payload.get("duration_s"),
            "image_media_ids": payload.get("image_media_ids") or [],
            "ok": ok,
            "blockers": blockers,
        })
    return {
        "checked": len(items), "ready": ready,
        "blocked": len(items) - ready, "items": results,
        "note": "DRY RUN — nothing fired, no credits spent.",
    }


async def _live_production_loop(run_id: str) -> None:
    from agent.services import make_video

    run = await crud.get_production_run(run_id)
    cfg = _loads(run.get("config_json"), {})
    interval_min = int(run.get("interval_min_seconds") or 45)
    interval_max = int(run.get("interval_max_seconds") or 120)
    cooldown_n = int(run.get("cooldown_after_n_jobs") or 5)
    cooldown_s = int(run.get("cooldown_seconds") or 300)

    completed = int(run.get("total_completed") or 0)
    failed = int(run.get("total_failed") or 0)
    errors: list[str] = _loads(run.get("error_log_json"), [])
    fired_since_cooldown = 0

    while True:
        signal = _run_control.get(run_id)
        if signal == "CANCEL":
            await _cancel_remaining(run_id)
            await crud.update_production_run(
                run_id, status="CANCELLED",
                total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            _run_control.pop(run_id, None)
            return
        if signal == "PAUSE":
            await crud.update_production_run(
                run_id, status="PAUSED",
                total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            _run_control.pop(run_id, None)
            return

        queued = await crud.list_production_queue_packages(
            production_run_id=run_id, production_status="QUEUED", limit=1,
        )
        if not queued:
            break
        item = queued[0]
        wgp_id = item["workspace_generation_package_id"]

        payload, blockers = await build_execution_payload(item, cfg)
        if blockers:
            failed += 1
            errors.append(f"{wgp_id}: {','.join(blockers)}")
            await crud.update_workspace_generation_package(
                wgp_id, production_status="FAILED",
                production_error=",".join(blockers),
            )
            await crud.update_production_run(
                run_id, total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            continue

        await crud.update_workspace_generation_package(
            wgp_id, production_status="RUNNING",
        )
        try:
            outcome = await _fire_and_wait(make_video, payload, wgp_id)
        except Exception as exc:  # defensive: never kill the loop
            outcome = {"ok": False, "error": f"UNEXPECTED:{exc}"}
        if outcome["ok"]:
            completed += 1
        else:
            failed += 1
            errors.append(f"{wgp_id}: {outcome.get('error')}")
        await crud.update_production_run(
            run_id, total_completed=completed, total_failed=failed,
            error_log_json=_json(errors[-50:]),
        )
        fired_since_cooldown += 1

        remaining = await crud.list_production_queue_packages(
            production_run_id=run_id, production_status="QUEUED", limit=1,
        )
        if not remaining:
            break
        if cooldown_n > 0 and fired_since_cooldown >= cooldown_n:
            fired_since_cooldown = 0
            await asyncio.sleep(cooldown_s)
        else:
            await asyncio.sleep(random.randint(interval_min, max(interval_min, interval_max)))

    final = "COMPLETED" if failed == 0 or completed > 0 else "FAILED"
    await crud.update_production_run(
        run_id, status=final,
        total_completed=completed, total_failed=failed,
        error_log_json=_json(errors[-50:]),
    )
    logger.info("Production run %s finished: %d ok, %d failed", run_id, completed, failed)


def compute_dedupe_key(payload: dict, wgp_id: str) -> str:
    """Stable identity for one logical submission (G0 amendment O4).

    Derived from the inputs that decide what the provider would actually produce:
    the package, the engine/logical mode, model, duration, aspect, count and the
    resolved Flow media bindings, plus the prompt itself. Two attempts that would
    submit the same work therefore collide by construction; a genuinely different
    job (different model, duration, media or prompt) does not.
    """
    basis = {
        "wgp": wgp_id,
        "logical_mode": payload.get("logical_mode"),
        "engine_mode": payload.get("mode"),
        "model": payload.get("model"),
        "duration_s": payload.get("duration_s"),
        "aspect": payload.get("aspect"),
        "num_videos": payload.get("num_videos"),
        "image_media_ids": sorted(payload.get("image_media_ids") or []),
        "prompt_sha": hashlib.sha256((payload.get("prompt") or "").encode("utf-8")).hexdigest(),
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return f"ddk_{digest[:32]}"


async def _fire_and_wait(make_video, payload: dict, wgp_id: str) -> dict:
    """Fire one item through the locked generate door and wait for terminal.

    O4 — idempotency. This is the ONLY provider boundary in the queue, so the
    duplicate-submission guard lives here and cannot be routed around:

      1. Already submitted -> `production_job_id` is written only after a provider
         submission succeeds (see below), so a non-empty value proves this exact
         package already went to the provider. Re-firing it would spend credits
         twice for the same work, so it FAILS CLOSED. `retry_failed_items` clears
         the id deliberately — that is the explicit retry identity, and the only
         supported way to submit a package a second time.
      2. Concurrent duplicate -> a double click, a retried request or two loops
         racing the same package resolve to the same dedupe key. The key is held
         in-process for the lifetime of the submission, so the second caller is
         refused before `start_generate` is reached rather than after.
    """
    fresh = await crud.get_workspace_generation_package(wgp_id) or {}
    prior_job = str(fresh.get("production_job_id") or "").strip()
    if prior_job:
        logger.warning(
            "DUPLICATE_SUBMISSION_BLOCKED wgp=%s already submitted as job=%s", wgp_id, prior_job,
        )
        await crud.update_workspace_generation_package(
            wgp_id,
            production_status="FAILED",
            production_error=f"DUPLICATE_SUBMISSION_BLOCKED:{prior_job}",
        )
        return {"ok": False, "error": f"DUPLICATE_SUBMISSION_BLOCKED:{prior_job}", "job_id": prior_job}

    dedupe_key = compute_dedupe_key(payload, wgp_id)
    if dedupe_key in _inflight_dedupe:
        logger.warning("DUPLICATE_SUBMISSION_IN_FLIGHT wgp=%s key=%s", wgp_id, dedupe_key)
        return {"ok": False, "error": f"DUPLICATE_SUBMISSION_IN_FLIGHT:{dedupe_key}"}
    _inflight_dedupe.add(dedupe_key)
    logger.info("Submission accepted wgp=%s dedupe_key=%s", wgp_id, dedupe_key)
    try:
        return await _fire_and_wait_inner(make_video, payload, wgp_id)
    finally:
        _inflight_dedupe.discard(dedupe_key)


async def _fire_and_wait_inner(make_video, payload: dict, wgp_id: str) -> dict:
    attempts = 0
    while True:
        result = await make_video.start_generate(
            payload["mode"], payload["prompt"],
            image_media_ids=payload.get("image_media_ids"),
            aspect=payload.get("aspect") or "9:16",
            model=payload.get("model"),
            duration_s=payload.get("duration_s"),
            num_videos=payload.get("num_videos") or 1,
        )
        if result.get("status") == "REJECTED" and result.get("error") == "VIDEO_JOB_IN_FLIGHT":
            attempts += 1
            if attempts > _INFLIGHT_MAX_RETRIES:
                await crud.update_workspace_generation_package(
                    wgp_id, production_status="FAILED",
                    production_error="VIDEO_LANE_BUSY_TIMEOUT",
                )
                return {"ok": False, "error": "VIDEO_LANE_BUSY_TIMEOUT"}
            await asyncio.sleep(_INFLIGHT_RETRY_SECONDS)
            continue
        break

    job_id = result.get("job_id")
    if not job_id:
        err = result.get("error") or "NO_JOB_ID"
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error=str(err),
        )
        return {"ok": False, "error": str(err)}

    await crud.update_workspace_generation_package(wgp_id, production_job_id=job_id)
    # Persist the submission's correlation identity the moment it exists. It
    # previously lived only in make_video's in-memory _JOBS, so a restart erased
    # the only record of whether this run's output could ever be bound.
    await _persist_generation_identity(wgp_id, job_id)

    waited = 0
    while waited < _JOB_TIMEOUT_SECONDS:
        job = make_video.get_job(job_id) or {}
        status = job.get("status")
        if status in ("DONE", "FAILED", "REJECTED", "GENERATED_BUT_UNRETRIEVED"):
            break
        await asyncio.sleep(_POLL_SECONDS)
        waited += _POLL_SECONDS
    else:
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error="JOB_TIMEOUT",
        )
        return {"ok": False, "error": "JOB_TIMEOUT"}

    job = make_video.get_job(job_id) or {}
    status = job.get("status")
    # Durably record what happened to the candidates BEFORE branching on status,
    # so a refusal leaves the same audit trail as an acceptance.
    await _persist_binding_outcome(wgp_id, job_id)
    if status == "DONE":
        media_ids = [a.get("media_id") for a in (job.get("artifacts") or []) if a.get("media_id")]
        if not media_ids and job.get("media_id"):
            media_ids = [job["media_id"]]
        await crud.link_artifacts_to_generation_package(job_id, wgp_id)
        await crud.update_workspace_generation_package(
            wgp_id,
            production_status="DOWNLOADED" if job.get("local_path") else "GENERATED",
            artifact_media_ids_json=_json(media_ids),
            production_error=None,
        )
        return {"ok": True}
    if status == "GENERATED_BUT_UNRETRIEVED":
        # Credits were spent and the video exists in Flow — never report a
        # plain failure (locked contract from make_video).
        await crud.update_workspace_generation_package(
            wgp_id, production_status="GENERATED",
            production_error="GENERATED_BUT_UNRETRIEVED",
        )
        return {"ok": True}
    err = job.get("error") or status or "UNKNOWN"
    await crud.update_workspace_generation_package(
        wgp_id, production_status="FAILED", production_error=str(err),
    )
    return {"ok": False, "error": str(err)}


async def _cancel_remaining(run_id: str) -> None:
    items = await crud.list_production_queue_packages(
        production_run_id=run_id, production_status="QUEUED",
    )
    for item in items:
        await crud.update_workspace_generation_package(
            item["workspace_generation_package_id"], production_status="CANCELLED",
        )


async def get_production_run_detail(run_id: str) -> dict | None:
    run = await crud.get_production_run(run_id)
    if not run:
        return None
    items = await crud.list_production_queue_packages(production_run_id=run_id)
    run["items"] = [
        {
            "package_id": i["workspace_generation_package_id"],
            "product_id": i.get("product_id"),
            "product_name_snapshot": i.get("product_name_snapshot"),
            "logical_mode": i.get("logical_mode") or i.get("mode"),
            "production_status": i.get("production_status"),
            "production_job_id": i.get("production_job_id"),
            "production_error": i.get("production_error"),
            "artifact_media_ids": _loads(i.get("artifact_media_ids_json"), []),
            "sent_to_production_at": i.get("sent_to_production_at"),
        }
        for i in items
    ]
    return run
