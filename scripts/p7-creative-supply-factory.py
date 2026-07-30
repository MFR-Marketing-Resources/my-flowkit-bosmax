#!/usr/bin/env python3
"""P7 isolated rehearsal and canonical creative-supply mission driver.

The script never calls a media provider. Text spend occurs only under the
explicit ``author`` action and is still constrained by the durable 120-call
service gate. Canonical DB use requires an exact post-merge confirmation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

CANONICAL_CONFIRMATION = "APPLY_P7_TO_MERGED_CANONICAL_DB"
DEFAULT_MISSION_ID = "BOSMAX-P7-CREATIVE-SUPPLY-LIVE-PRODUCTION-ACTIVATION-20260730"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "create",
            "status",
            "author",
            "review",
            "compose",
            "compose-persist",
            "compose-selected",
            "copy-review",
            "component-correct",
            "frame-alias",
            "anchor-create",
            "anchor-review",
            "p6-rehearse",
            "rehearse",
            "requeue-unsubmitted",
            "reconcile-running",
            "manual-register",
            "settle-satisfied",
        ),
    )
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--roster-json", type=Path)
    parser.add_argument("--angle-ledger-json", type=Path)
    parser.add_argument("--review-decisions-json", type=Path)
    parser.add_argument("--copy-review-decisions-json", type=Path)
    parser.add_argument("--component-corrections-json", type=Path)
    parser.add_argument("--manual-components-json", type=Path)
    parser.add_argument("--selected-components-json", type=Path)
    parser.add_argument("--frame-aliases-json", type=Path)
    parser.add_argument("--anchors-json", type=Path)
    parser.add_argument("--anchor-reviews-json", type=Path)
    parser.add_argument("--p6-heroes-json", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--product-id", action="append")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=120)
    parser.add_argument("--mission-id", default=DEFAULT_MISSION_ID)
    parser.add_argument("--canonical-confirmation", default="")
    return parser.parse_args()


def _bootstrap(args: argparse.Namespace):
    repo_root = Path(__file__).resolve().parents[1]
    runtime_dir = args.runtime_dir.resolve()
    canonical_db = (repo_root / "flow_agent.db").resolve()
    target_db = (runtime_dir / "flow_agent.db").resolve()
    if target_db == canonical_db and args.canonical_confirmation != CANONICAL_CONFIRMATION:
        raise SystemExit(
            "CANONICAL_DB_REFUSED: rerun only after merge/deploy with "
            f"--canonical-confirmation {CANONICAL_CONFIRMATION}"
        )
    if not target_db.exists():
        raise SystemExit(f"RUNTIME_DB_NOT_FOUND:{target_db}")
    os.environ["FLOW_AGENT_DIR"] = str(runtime_dir)
    sys.path.insert(0, str(repo_root))
    from agent.config import DB_PATH
    from agent.db.schema import close_db, init_db
    from agent.services import ai_copy_provider_adapter as provider
    from agent.services import creative_supply_factory_service as factory

    if Path(DB_PATH).resolve() != target_db:
        raise SystemExit(f"DB_BINDING_MISMATCH:expected={target_db}:actual={DB_PATH}")
    return repo_root, target_db, init_db, close_db, provider, factory


def _normalize_roster(payload: Any) -> list[dict[str, Any]]:
    products = payload.get("products") if isinstance(payload, dict) else payload
    if not isinstance(products, list):
        raise SystemExit("ROSTER_JSON_INVALID")
    selected = [item for item in products if item.get("selected", True)]
    selected.sort(key=lambda item: int(item.get("selection_rank") or item.get("rank") or 999))
    if len(selected) != 10:
        raise SystemExit(f"TOP10_ROSTER_REQUIRED:actual={len(selected)}")
    return [
        {
            "product_id": str(item["product_id"]),
            "product_name": str(item.get("product_name") or ""),
            "rank": index,
            "role": "HERO" if index <= 2 else "TOP10",
            "selection_basis": str(
                item.get("selection_reason") or item.get("selection_basis") or ""
            ),
        }
        for index, item in enumerate(selected, start=1)
    ]


def _normalize_angles(payload: Any, roster: list[dict[str, Any]]) -> list[dict[str, str]]:
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise SystemExit("ANGLE_LEDGER_JSON_INVALID")
    allowed = {item["product_id"] for item in roster}
    accepted = [
        entry
        for entry in entries
        if str(entry.get("decision") or "").upper() == "ACCEPTED"
        and str(entry.get("product_id") or "") in allowed
    ]
    rank = {item["product_id"]: int(item["rank"]) for item in roster}
    accepted.sort(
        key=lambda entry: (
            rank[str(entry["product_id"])],
            str(entry.get("reviewed_at") or ""),
            str(entry.get("angle_key") or ""),
        )
    )
    return [
        {
            "product_id": str(entry["product_id"]),
            "angle_key": str(entry["angle_key"]),
            "angle_label": str(entry.get("angle_label") or ""),
        }
        for entry in accepted
    ]


def _target_policy() -> dict[str, Any]:
    return {
        "HERO": {
            "components": {"HOOK": 6, "SUBHOOK": 4, "USP_SET": 3, "CTA": 3},
            "minimum_capacity": 500,
        },
        # The mission minima 4x3x2x2 across two angles produce only 96
        # combinations. Five hooks is the smallest truthful uplift: 5x3x2x2x2
        # angles = 120, clearing the required 100 without inventing an angle.
        "TOP10": {
            "components": {"HOOK": 5, "SUBHOOK": 3, "USP_SET": 2, "CTA": 2},
            "minimum_capacity": 100,
        },
    }


async def _create(args, factory) -> dict[str, Any]:
    if not args.roster_json or not args.angle_ledger_json:
        raise SystemExit("CREATE_REQUIRES_ROSTER_AND_ANGLE_LEDGER")
    roster = _normalize_roster(_read_json(args.roster_json))
    angles = _normalize_angles(_read_json(args.angle_ledger_json), roster)
    return await factory.create_run(
        mission_id=args.mission_id,
        roster=roster,
        angle_plan=angles,
        target_policy=_target_policy(),
        provider_budget_max=120,
        reviewer_id=factory.DEFAULT_REVIEWER_ID,
    )


async def _resolve_run_id(args, factory) -> str:
    if args.run_id:
        return args.run_id
    listed = await factory.list_runs()
    runs = listed.get("runs") or []
    if not runs:
        raise SystemExit("NO_CREATIVE_SUPPLY_RUN")
    return str(runs[0]["run_id"])


async def _p6_rehearse(args: argparse.Namespace) -> dict[str, Any]:
    if not args.p6_heroes_json:
        raise SystemExit("P6_REHEARSE_REQUIRES_HEROES_JSON")
    from agent.models.creative_production import (
        CreativePoolSelection,
        DryRunRequest,
        PlanActionRequest,
        ProductVideoAllocation,
        ProductionPlanCreateRequest,
        WaveAssignmentRequest,
    )
    from agent.services import creative_production_compile_service as compiler
    from agent.services import creative_production_plan_service as plans
    from agent.services import creative_production_scheduler_service as scheduler

    payload = _read_json(args.p6_heroes_json)
    heroes = payload.get("heroes") if isinstance(payload, dict) else payload
    if not isinstance(heroes, list) or len(heroes) != 2:
        raise SystemExit("P6_REHEARSE_EXACTLY_TWO_HEROES_REQUIRED")
    authority_report = await plans.build_catalog_authority_matrix()

    async def stable_authority_report():
        return authority_report

    plans.build_catalog_authority_matrix = stable_authority_report
    results = []
    for hero in heroes:
        slug = str(hero["slug"])
        product_id = str(hero["product_id"])
        copy_set_id = str(hero["copy_set_id"])
        frame_id = str(hero["frame_id"])
        key = hashlib.sha256(
            f"{args.mission_id}:{slug}:{product_id}:{copy_set_id}:{frame_id}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        operator_id = "codex-p7-operator"
        plan = await plans.create_plan(
            ProductionPlanCreateRequest(
                request_id=f"p7-{slug}-anchor916-create-{key}",
                operator_id=operator_id,
                name=f"P7 {slug} bounded live-video activation anchor 9:16",
                campaign_key=f"P7_HERO_{slug.upper()}_VIDEO_ANCHOR_916",
                product_ids=[product_id],
                product_video_allocations=[
                    ProductVideoAllocation(
                        product_id=product_id,
                        video_count=1,
                    )
                ],
                target_video_count=1,
                operating_window_hours=12,
                logical_mode="F2V",
                model_keys=["Veo 3.1 - Lite"],
                duration_seconds=[8],
                pools=CreativePoolSelection(
                    copy_set_ids=[copy_set_id],
                    finished_frame_asset_ids=[frame_id],
                ),
            )
        )
        preflight = await plans.run_capacity_preflight(
            plan["plan_id"],
            PlanActionRequest(
                request_id=f"p7-{slug}-anchor916-preflight-{key}",
                operator_id=operator_id,
            ),
        )
        if preflight.status != "PREFLIGHT_READY":
            raise SystemExit(
                f"P6_HERO_PREFLIGHT_BLOCKED:{slug}:"
                + json.dumps(preflight.blockers, sort_keys=True)
            )
        matrix = await plans.materialize_content_matrix(
            plan["plan_id"],
            PlanActionRequest(
                request_id=f"p7-{slug}-anchor916-matrix-{key}",
                operator_id=operator_id,
            ),
        )
        compiled = await compiler.compile_plan(
            plan["plan_id"],
            PlanActionRequest(
                request_id=f"p7-{slug}-anchor916-compile-{key}",
                operator_id=operator_id,
            ),
        )
        if compiled["status"] != "PENDING_APPROVAL":
            raise SystemExit(
                f"P6_HERO_COMPILE_BLOCKED:{slug}:"
                + json.dumps(compiled["failures"], sort_keys=True)
            )
        approved = await plans.approve_plan(
            plan["plan_id"],
            request_id=f"p7-{slug}-anchor916-approve-{key}",
            operator_id=operator_id,
        )
        waves = await plans.assign_waves(
            plan["plan_id"],
            WaveAssignmentRequest(
                request_id=f"p7-{slug}-anchor916-waves-{key}",
                operator_id=operator_id,
                wave_count=1,
                batch_size=1,
            ),
        )
        dry_run = await scheduler.dry_run_plan(
            plan["plan_id"],
            DryRunRequest(
                request_id=f"p7-{slug}-anchor916-dry-{key}",
                operator_id=operator_id,
            ),
        )
        detail = await plans.get_plan_detail(plan["plan_id"])
        results.append(
            {
                "hero": {
                    "slug": slug,
                    "product_id": product_id,
                    "copy_set_id": copy_set_id,
                    "frame_id": frame_id,
                },
                "plan": plan,
                "preflight": preflight.model_dump(mode="json"),
                "matrix": matrix,
                "compiled": compiled,
                "approved": approved,
                "waves": waves,
                "dry_run": dry_run,
                "detail": detail.model_dump(mode="json"),
            }
        )
    return {
        "mission_id": args.mission_id,
        "heroes": results,
        "credit_spend": sum(
            int(item["dry_run"].get("credit_spend") or 0) for item in results
        ),
        "provider_media_calls": sum(
            int(item["dry_run"].get("provider_media_calls") or 0)
            for item in results
        ),
    }


async def _main(args: argparse.Namespace) -> int:
    (
        _repo_root,
        target_db,
        init_db,
        close_db,
        provider,
        factory,
    ) = _bootstrap(args)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    try:
        before_receipt = provider.provider_call_receipt()
        if args.action == "create":
            result = await _create(args, factory)
        elif args.action == "rehearse":
            result = await _create(args, factory)
            run_id = str(result["run"]["run_id"])
            paused = await factory.control(
                run_id, "PAUSE", "P7 isolated durable-state rehearsal."
            )
            resumed = await factory.control(run_id, "RESUME")
            hero_id = str(result["run"]["roster"][0]["product_id"])
            composition = await factory.compose_sample(
                run_id, hero_id, count=4, dry_run=True
            )
            result = {
                "created": result,
                "pause_state": paused["run"]["state"],
                "resume_state": resumed["run"]["state"],
                "deterministic_composition_dry_run": composition,
                "media_provider_calls": 0,
            }
        elif args.action == "status":
            result = await factory.status(await _resolve_run_id(args, factory))
        elif args.action == "author":
            run_id = await _resolve_run_id(args, factory)
            steps = []
            for ordinal in range(max(0, min(args.max_steps, 120))):
                current = await factory.status(run_id)
                if not any(
                    str(task.get("state") or "") == "PENDING"
                    for task in current.get("tasks") or []
                ):
                    break
                updated = await factory.step(run_id)
                steps.append(
                    {
                        "ordinal": ordinal + 1,
                        "provider_budget": updated["provider_budget"],
                        "task_counts": updated["task_counts"],
                        "last_error": updated["run"].get("last_error"),
                    }
                )
                if str(updated["run"].get("state")) in {"BLOCKED", "PAUSED", "CANCELLED"}:
                    break
            result = {"run": await factory.status(run_id), "steps": steps}
        elif args.action == "review":
            if not args.review_decisions_json:
                raise SystemExit("REVIEW_REQUIRES_DECISIONS_JSON")
            run_id = await _resolve_run_id(args, factory)
            decisions = _read_json(args.review_decisions_json)
            if isinstance(decisions, dict):
                decisions = decisions.get("decisions")
            if not isinstance(decisions, list):
                raise SystemExit("REVIEW_DECISIONS_JSON_INVALID")
            events = []
            existing_status = await factory.status(run_id)
            already_reviewed = {
                str(event.get("component_id") or "")
                for event in existing_status.get("review_events") or []
            }
            for decision in decisions:
                if str(decision["component_id"]) in already_reviewed:
                    continue
                reviewed = await factory.review_component(
                    run_id=run_id,
                    task_id=str(decision["task_id"]),
                    component_id=str(decision["component_id"]),
                    decision=str(decision["decision"]),
                    reviewed_content_sha256=str(decision["reviewed_content_sha256"]),
                    reasons=[str(reason) for reason in decision.get("reasons") or []],
                    reviewer_id=str(
                        decision.get("reviewer_id") or factory.DEFAULT_REVIEWER_ID
                    ),
                    include_status=False,
                )
                events.append(reviewed["event"])
            reconciled = await factory.reconcile_missing_deficit_tasks(run_id)
            result = {"events": events, "run": reconciled}
        elif args.action == "compose":
            run_id = await _resolve_run_id(args, factory)
            current = await factory.status(run_id)
            samples = {}
            for product in current["products"]:
                product_id = str(product["product_id"])
                samples[product_id] = await factory.compose_sample(
                    run_id, product_id, count=8, dry_run=True
                )
            result = {"run_id": run_id, "dry_run": True, "samples": samples}
        elif args.action == "compose-persist":
            run_id = await _resolve_run_id(args, factory)
            current = await factory.status(run_id)
            selected_ids = {str(value) for value in args.product_id or []}
            if selected_ids:
                roster_ids = {
                    str(product["product_id"]) for product in current["products"]
                }
                unknown = sorted(selected_ids - roster_ids)
                if unknown:
                    raise SystemExit(
                        f"COMPOSE_PRODUCT_OUTSIDE_ROSTER:{','.join(unknown)}"
                    )
            samples = {}
            for product in current["products"]:
                product_id = str(product["product_id"])
                if selected_ids and product_id not in selected_ids:
                    continue
                samples[product_id] = await factory.compose_sample(
                    run_id, product_id, count=args.count, dry_run=False
                )
            result = {"run_id": run_id, "dry_run": False, "samples": samples}
        elif args.action == "compose-selected":
            if not args.selected_components_json:
                raise SystemExit("COMPOSE_SELECTED_REQUIRES_COMPONENTS_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.selected_components_json)
            selections = (
                payload.get("selections") if isinstance(payload, dict) else payload
            )
            if not isinstance(selections, list):
                raise SystemExit("SELECTED_COMPONENTS_JSON_INVALID")
            composed = []
            for selection in selections:
                composed.append(
                    await factory.compose_selected_components(
                        run_id=run_id,
                        product_id=str(selection["product_id"]),
                        hook_component_id=str(selection["hook_component_id"]),
                        subhook_component_id=str(selection["subhook_component_id"]),
                        usp_set_component_id=str(
                            selection["usp_set_component_id"]
                        ),
                        cta_component_id=str(selection["cta_component_id"]),
                    )
                )
            result = {"run_id": run_id, "composed": composed}
        elif args.action == "copy-review":
            if not args.copy_review_decisions_json:
                raise SystemExit("COPY_REVIEW_REQUIRES_DECISIONS_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.copy_review_decisions_json)
            decisions = payload.get("decisions") if isinstance(payload, dict) else payload
            if not isinstance(decisions, list):
                raise SystemExit("COPY_REVIEW_DECISIONS_JSON_INVALID")
            reviews = []
            for decision in decisions:
                reviews.append(
                    await factory.review_composed_copy_set(
                        run_id=run_id,
                        copy_set_id=str(decision["copy_set_id"]),
                        decision=str(decision["decision"]),
                        reviewed_content_sha256=str(
                            decision["reviewed_content_sha256"]
                        ),
                        reasons=[
                            str(reason) for reason in decision.get("reasons") or []
                        ],
                        reviewer_id=str(
                            decision.get("reviewer_id")
                            or factory.DEFAULT_REVIEWER_ID
                        ),
                    )
                )
            result = {"run_id": run_id, "reviews": reviews}
        elif args.action == "component-correct":
            if not args.component_corrections_json:
                raise SystemExit("COMPONENT_CORRECT_REQUIRES_DECISIONS_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.component_corrections_json)
            decisions = payload.get("decisions") if isinstance(payload, dict) else payload
            if not isinstance(decisions, list):
                raise SystemExit("COMPONENT_CORRECTIONS_JSON_INVALID")
            events = []
            for decision in decisions:
                corrected = await factory.correct_component_review(
                    run_id=run_id,
                    component_id=str(decision["component_id"]),
                    reviewed_content_sha256=str(
                        decision["reviewed_content_sha256"]
                    ),
                    reasons=[
                        str(reason) for reason in decision.get("reasons") or []
                    ],
                    reviewer_id=str(
                        decision.get("reviewer_id")
                        or factory.DEFAULT_REVIEWER_ID
                    ),
                )
                events.append(corrected["event"])
            result = {
                "run_id": run_id,
                "events": events,
                "run": await factory.status(run_id),
            }
        elif args.action == "frame-alias":
            if not args.frame_aliases_json:
                raise SystemExit("FRAME_ALIAS_REQUIRES_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.frame_aliases_json)
            aliases = payload.get("aliases") if isinstance(payload, dict) else payload
            if not isinstance(aliases, list):
                raise SystemExit("FRAME_ALIASES_JSON_INVALID")
            registered = []
            for alias in aliases:
                registered.append(
                    await factory.register_product_only_f2v_frame_alias(
                        run_id=run_id,
                        product_id=str(alias["product_id"]),
                        source_asset_id=str(alias["source_asset_id"]),
                        reviewer_id=str(
                            alias.get("reviewer_id")
                            or factory.DEFAULT_REVIEWER_ID
                        ),
                    )
                )
            result = {"run_id": run_id, "aliases": registered}
        elif args.action == "anchor-create":
            if not args.anchors_json:
                raise SystemExit("ANCHOR_CREATE_REQUIRES_ANCHORS_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.anchors_json)
            anchors = payload.get("anchors") if isinstance(payload, dict) else payload
            if not isinstance(anchors, list):
                raise SystemExit("ANCHORS_JSON_INVALID")
            prepared = []
            for anchor in anchors:
                prepared.append(
                    await factory.prepare_product_only_f2v_anchor_916(
                        run_id=run_id,
                        product_id=str(anchor["product_id"]),
                        source_asset_id=str(anchor["source_asset_id"]),
                    )
                )
            result = {"run_id": run_id, "anchors": prepared}
        elif args.action == "anchor-review":
            if not args.anchor_reviews_json:
                raise SystemExit("ANCHOR_REVIEW_REQUIRES_REVIEWS_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.anchor_reviews_json)
            reviews = payload.get("reviews") if isinstance(payload, dict) else payload
            if not isinstance(reviews, list):
                raise SystemExit("ANCHOR_REVIEWS_JSON_INVALID")
            reviewed = []
            for review in reviews:
                reviewed.append(
                    await factory.review_product_only_f2v_anchor_916(
                        run_id=run_id,
                        asset_id=str(review["asset_id"]),
                        reviewed_output_sha256=str(
                            review["reviewed_output_sha256"]
                        ),
                        reasons=[
                            str(reason) for reason in review.get("reasons") or []
                        ],
                        reviewer_id=str(
                            review.get("reviewer_id")
                            or factory.DEFAULT_REVIEWER_ID
                        ),
                    )
                )
            result = {"run_id": run_id, "reviews": reviewed}
        elif args.action == "p6-rehearse":
            result = await _p6_rehearse(args)
        elif args.action == "requeue-unsubmitted":
            run_id = await _resolve_run_id(args, factory)
            current = await factory.status(run_id)
            eligible = [
                task
                for task in current.get("tasks") or []
                if str(task.get("state") or "") == "FAILED"
                and int(task.get("provider_call_count") or 0) == 0
                and "AICopyProviderNotConfigured"
                in str(task.get("last_error") or "")
            ]
            for task in eligible:
                await factory.requeue_unsubmitted(str(task["task_id"]))
            result = {
                "requeued_task_ids": [str(task["task_id"]) for task in eligible],
                "run": await factory.status(run_id),
            }
        elif args.action == "reconcile-running":
            run_id = await _resolve_run_id(args, factory)
            current = await factory.status(run_id)
            running = [
                task
                for task in current.get("tasks") or []
                if str(task.get("state") or "") == "RUNNING"
            ]
            for task in running:
                await factory.reconcile_interrupted_running_task(
                    str(task["task_id"]),
                    "Local mission driver process was terminated by command timeout.",
                )
            result = {
                "reconciled_task_ids": [str(task["task_id"]) for task in running],
                "conservative_provider_calls_charged": len(running),
                "run": await factory.status(run_id),
            }
        elif args.action == "manual-register":
            if not args.manual_components_json:
                raise SystemExit("MANUAL_REGISTER_REQUIRES_COMPONENTS_JSON")
            run_id = await _resolve_run_id(args, factory)
            payload = _read_json(args.manual_components_json)
            slots = payload.get("slots") if isinstance(payload, dict) else payload
            if not isinstance(slots, list):
                raise SystemExit("MANUAL_COMPONENTS_JSON_INVALID")
            tasks = []
            for slot in slots:
                registered = await factory.register_manual_remediation(
                    run_id=run_id,
                    product_id=str(slot["product_id"]),
                    angle_key=str(slot["angle_key"]),
                    component_type=str(slot["component_type"]),
                    contents=list(slot.get("contents") or []),
                    authored_by=str(
                        slot.get("authored_by") or factory.DEFAULT_REVIEWER_ID
                    ),
                )
                tasks.append(registered["task"])
            result = {"tasks": tasks, "run": await factory.status(run_id)}
        elif args.action == "settle-satisfied":
            run_id = await _resolve_run_id(args, factory)
            result = await factory.settle_satisfied_tasks(run_id)
        else:  # pragma: no cover - argparse owns the choices
            raise SystemExit(f"UNKNOWN_ACTION:{args.action}")

        after_receipt = provider.provider_call_receipt()
        envelope = {
            "action": args.action,
            "database_path": str(target_db),
            "provider_receipt_before": before_receipt,
            "provider_receipt_after": after_receipt,
            "result": result,
        }
        run_id = args.run_id
        if not run_id and isinstance(result, dict):
            run = result.get("run") or result.get("created", {}).get("run")
            if isinstance(run, dict):
                run_id = str(run.get("run_id") or "")
        suffix = f"-{run_id}" if run_id else ""
        if args.action == "compose-persist" and args.product_id:
            product_suffix = "-".join(
                sorted(str(product_id)[:8] for product_id in args.product_id)
            )
            suffix = f"{suffix}-{product_suffix}"
        output = args.evidence_dir / f"p7-{args.action}{suffix}.json"
        _write_json(output, envelope)
        print(json.dumps({"ok": True, "evidence": str(output)}, ensure_ascii=False))
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse())))
