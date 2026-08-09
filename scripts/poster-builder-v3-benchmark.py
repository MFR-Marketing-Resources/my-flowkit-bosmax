"""No-spend Campaign Poster Builder V3 benchmark.

This is the default rehearsal artifact for PR-C. It reads the canonical
product/reference/intelligence authorities, compiles one clean-key-visual
request and derives three local manifest fingerprints. It does not ensure or
approve a reference pack, call Google Flow, compose PNGs, or mutate the DB.

Usage:
    python scripts/poster-builder-v3-benchmark.py
    python scripts/poster-builder-v3-benchmark.py --product-id <uuid>
    python scripts/poster-builder-v3-benchmark.py --cohort-evidence <json>
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_PRODUCT_ID = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
DEFAULT_COHORT_EVIDENCE = ROOT / "docs" / "evidence" / "poster-builder-v3-e1-benchmark-cohort.json"


def _runtime_sha() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _copy_for_manifest(candidate: object) -> dict:
    def value(key: str, default: object = "") -> object:
        if isinstance(candidate, dict):
            return candidate.get(key, default)
        return getattr(candidate, key, default)

    return {
        "poster_copy_set_id": "DRY_RUN_COPY_ROUTE",
        "version": 1,
        "primary_message": value("primary_message"),
        "support_message": value("support_message"),
        "proof_points": value("approved_proof_points", []),
        "cta": value("cta"),
        "disclaimer": "",
        "field_provenance": value("copy_provenance", {}),
    }


async def run(product_id: str) -> dict:
    from agent.db import crud
    from agent.models.image_generation_contract import ImagePromptCompileRequest
    from agent.models.poster_campaign_qa import CampaignDryRunReport
    from agent.services.image_prompt_compiler import compile_image_prompt
    from agent.services.poster_campaign_design_service import (
        build_campaign_design_brief,
        generate_campaign_copy_routes,
    )
    from agent.services.poster_campaign_qa_service import (
        build_pre_provider_lint,
        manifest_fingerprint,
    )
    from agent.services.poster_design_system import resolve_design_route
    from agent.services.poster_template_service import build_render_manifest
    from agent.services.product_reference_pack_service import get_reference_pack

    product = await crud.get_product(product_id)
    if not product:
        return CampaignDryRunReport(
            status="DRY_RUN_BLOCKED",
            runtime_sha=_runtime_sha(),
            product_id=product_id,
            expected_review_gates=["PRODUCT_REGISTERED"],
            maximum_provider_operations=1,
            max_retry_operations=0,
            manifest_fingerprints=["0" * 64] * 3,
            blockers=["PRODUCT_NOT_FOUND"],
        ).model_dump(mode="json")

    pack = await get_reference_pack(product_id)
    blockers: list[str] = []
    if pack is None:
        blockers.append("REFERENCE_PACK_NOT_MATERIALIZED")
    brief = await build_campaign_design_brief(
        product_id,
        objective="Product Hero",
        selected_angle="",
        fail_closed=False,
    )
    routes = generate_campaign_copy_routes(brief)
    candidate = routes.candidates[0] if routes.candidates else None
    if candidate is None:
        blockers.append("COPY_ROUTE_NOT_AVAILABLE")
    compile_response = None
    if pack is not None:
        compile_response = compile_image_prompt(
            dict(product),
            pack,
            ImagePromptCompileRequest(
                product_id=product_id,
                output_intent="CLEAN_KEY_VISUAL",
                model="NANO_BANANA_PRO",
                creative_mode="CREATIVE_CAMPAIGN",
                objective="Product Hero",
                composition="Provider-integrated product hero with one clear visual thesis.",
                camera="Vertical 9:16, natural product perspective, readable label.",
                lighting="Physically coherent commercial light with contact shadow.",
                scene_direction="Prompt-directed Malaysian campaign context; no legacy scene asset required.",
                copy_space={
                    "headline_line_budget": brief.headline_line_budget,
                    "support_line_budget": 1,
                    "proof_line_budget": len(getattr(candidate, "approved_proof_points", []) or []) if candidate else 0,
                    "cta_line_budget": 1,
                    "text_hierarchy": "HEADLINE > SUPPORT > PROOF > CTA",
                    "copy_zone_strategy": "DELIBERATE_NEGATIVE_SPACE",
                    "copy_safe_margin": "5%",
                    "avoid_product_overlap": True,
                },
                requested_outputs=1,
            ),
        )
        blockers.extend(compile_response.blockers)
    if candidate is not None and pack is not None:
        lint = build_pre_provider_lint(
            product_id=product_id,
            reference_pack=pack,
            brief=brief,
            candidate=candidate,
            compiled_prompt=compile_response.compiled_prompt,
            model="NANO_BANANA_PRO",
            output_intent="CLEAN_KEY_VISUAL",
            max_provider_operations=1,
            max_retry_operations=0,
            live=False,
        )
        blockers.extend(lint.blockers)

    objective = "Product Hero"
    angle = getattr(candidate, "singular_proposition", "") if candidate else ""
    design = resolve_design_route(
        dict(product),
        objective=objective,
        selected_angle=angle,
        copy_chars=sum(
            len(str(getattr(candidate, key, "") or ""))
            for key in ("primary_message", "support_message", "cta")
        ) if candidate else 0,
        headline_lines=brief.headline_line_budget,
    )
    fingerprints: list[str] = []
    if candidate is not None:
        copy_set = _copy_for_manifest(candidate)
        route_variants = design.get("route_variants") or []
        if len(route_variants) < 3:
            blockers.append("DESIGN_ROUTE_VARIANTS_INCOMPLETE")
        for variant in route_variants[:3]:
            manifest = build_render_manifest(
                recipe_id="product_hero_night_routine",
                copy_set=copy_set,
                background_media_id="DRY_RUN_CLEAN_KEY_VISUAL",
                image_model="NANO_BANANA_PRO",
                creative_direction={
                    "mode": "CREATIVE_CAMPAIGN",
                    "authority_version": "poster-design-system-v1",
                    "representation_policy_version": "product-reference-pack-v1",
                    "design_route": design["design_route"],
                    "layout_variant": variant,
                },
                composition_plan={"typography": {"headline_line_budget": brief.headline_line_budget}},
                design_route=design["design_route"],
                layout_variant=variant,
            )
            fingerprints.append(manifest_fingerprint(manifest))
    while len(fingerprints) < 3:
        fingerprints.append(hashlib.sha256(f"missing-variant-{len(fingerprints)}".encode()).hexdigest())
    role_hashes = {
        binding.role: binding.sha256 or "UNVERIFIED"
        for binding in (pack.references if pack is not None else [])
    }
    report = CampaignDryRunReport(
        status="DRY_RUN_READY" if not blockers else "DRY_RUN_BLOCKED",
        runtime_sha=_runtime_sha(),
        product_id=product_id,
        approved_snapshot_id=brief.approved_snapshot_id,
        approved_snapshot_version=brief.approved_snapshot_version,
        copy_candidate_scores=[
            {
                "route_id": item.route_id,
                "score": item.score.total,
                "status": item.status,
                "production_eligible": item.production_eligible,
            }
            for item in routes.candidates
        ],
        selected_copy_route=candidate.route_id if candidate else "",
        selected_design_route=design.get("design_route", ""),
        selected_model="NANO_BANANA_PRO",
        output_intent="CLEAN_KEY_VISUAL",
        prompt_fingerprint=compile_response.prompt_fingerprint if compile_response else "",
        reference_pack_id=pack.pack_id if pack is not None else "",
        reference_role_hashes=role_hashes,
        maximum_provider_operations=1,
        max_retry_operations=0,
        manifest_fingerprints=fingerprints[:3],
        expected_review_gates=[
            "REFERENCE_PACK_APPROVED",
            "GENERATED_OUTPUT_MACHINE_CHECKED",
            "GENERATED_OUTPUT_HUMAN_APPROVED",
            "WORLD_CLASS_POSTER_REVIEW",
        ],
        provider_operation_count=0,
        blockers=sorted(set(blockers)),
    )
    return report.model_dump(mode="json")


def run_cohort_evidence(path: Path) -> dict:
    """Read a zero-spend scout artifact and print only a future plan.

    This path has no async DB access and no transport import.  It is therefore
    safe to use as the Phase E1 dry-run gate even when the canonical runtime is
    online: it can never submit a provider operation.
    """
    from agent.services.poster_benchmark_cohort_service import (
        BENCHMARK_EXP_IDS,
        build_phase_e2_operation_plan,
        select_recommendations,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    classes = payload.get("benchmark_classes") if isinstance(payload, dict) else {}
    classes = classes if isinstance(classes, dict) else {}
    candidates_by_exp = {
        exp_id: list((classes.get(exp_id) or {}).get("top_3_candidates") or [])
        for exp_id in BENCHMARK_EXP_IDS
    }
    recommendations = select_recommendations(candidates_by_exp)
    plan = build_phase_e2_operation_plan(recommendations)
    return {
        "status": "COHORT_DRY_RUN_READY" if plan["status"] == "READY_FOR_AUTHORIZATION" else "COHORT_DRY_RUN_BLOCKED",
        "runtime_sha": _runtime_sha(),
        "evidence_path": str(path),
        "recommendations": recommendations,
        "operation_plan": plan,
        "provider_operation_count": 0,
        "db_mutation_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID)
    parser.add_argument(
        "--cohort-evidence",
        default=None,
        help="read-only E1 cohort JSON; emits a five-slot future plan without submitting",
    )
    parser.add_argument(
        "--agent-dir",
        default=None,
        help="read-only agent data root; defaults to FLOW_AGENT_DIR or this worktree",
    )
    args = parser.parse_args()
    try:
        if args.agent_dir:
            import os

            os.environ["FLOW_AGENT_DIR"] = str(Path(args.agent_dir).resolve())

        if args.cohort_evidence:
            result = run_cohort_evidence(Path(args.cohort_evidence).resolve())
            print("LIVE_BENCHMARK_AUTHORIZATION_REQUIRED")
            print("CREDIT_EXPOSURE = NOT VERIFIED")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "COHORT_DRY_RUN_READY" else 2

        async def execute_and_close() -> dict:
            from agent.db.schema import close_db

            try:
                return await run(args.product_id)
            finally:
                await close_db()

        result = asyncio.run(execute_and_close())
    except Exception as exc:  # report the rehearsal failure without side effects
        result = {
            "status": "DRY_RUN_BLOCKED",
            "runtime_sha": _runtime_sha(),
            "product_id": args.product_id,
            "provider_operation_count": 0,
            "maximum_provider_operations": 1,
            "max_retry_operations": 0,
            "blockers": [f"DRY_RUN_ERROR:{type(exc).__name__}:{exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "DRY_RUN_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
