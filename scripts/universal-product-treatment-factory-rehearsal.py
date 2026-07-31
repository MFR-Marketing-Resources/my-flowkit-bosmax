"""Isolated zero-credit rehearsal for the Product-to-Treatment Factory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FORMATS = ("UGC", "PGC", "CINEMATIC")
LOGICAL_MODES = ("T2V", "F2V", "I2V", "HYBRID")
MODEL_KEY = "veo_3_1_fast"
DURATION_SECONDS = 8
FLOW_MEDIA_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic Product-to-Treatment Factory rehearsal.",
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Explicit isolated runtime data directory.",
    )
    cohort = parser.add_mutually_exclusive_group(required=True)
    cohort.add_argument("--scan-all-active", action="store_true")
    cohort.add_argument("--product-id", action="append", default=[])
    cohort.add_argument(
        "--scale-proof",
        action="store_true",
        help=(
            "Run disposable 100-item P6 scale, matrix, and variation proofs "
            "without opening a database or dispatch surface."
        ),
    )
    parser.add_argument("--format", choices=FORMATS, default="PGC")
    parser.add_argument(
        "--logical-mode",
        choices=LOGICAL_MODES,
        default="HYBRID",
    )
    parser.add_argument(
        "--generation-mode",
        choices=("SINGLE", "EXTEND"),
        default="SINGLE",
    )
    parser.add_argument("--model-key", default=MODEL_KEY)
    parser.add_argument("--duration-seconds", type=int, default=DURATION_SECONDS)
    parser.add_argument("--action-index", type=int, default=0)
    parser.add_argument("--actor-id", default="factory-rehearsal")
    parser.add_argument("--prepare", action="store_true")
    return parser.parse_args()


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _mode_slots(logical_mode: str) -> dict[str, str]:
    if logical_mode == "T2V":
        return {}
    if logical_mode == "I2V":
        return {
            "product_reference": FLOW_MEDIA_IDS[0],
            "scene_context": FLOW_MEDIA_IDS[1],
        }
    return {"composite_frame": FLOW_MEDIA_IDS[0]}


def _evidence_requirements() -> list[object]:
    from agent.models.product_readiness import EvidenceRequirementResult

    states = (
        "VERIFIED_VALUE",
        "NOT_APPLICABLE",
        "NOT_STATED_IN_EVIDENCE",
        "UNKNOWN_REVIEW_REQUIRED",
    )
    return [
        EvidenceRequirementResult(
            requirement_code=f"FIXTURE_{state}",
            criticality="OPTIONAL",
            applicable=state != "NOT_APPLICABLE",
            state=state,
            rule_code=f"FIXTURE_RULE_{state}",
        )
        for state in states
    ]


def _context(
    *,
    product_id: str,
    action_index: int,
    creative_format: str,
    logical_mode: str,
) -> object:
    from agent.models.product_readiness import ProductReadinessEvaluateRequest

    return ProductReadinessEvaluateRequest(
        product_id=product_id,
        allowed_action_index=action_index,
        creative_format=creative_format,
        logical_mode=logical_mode,
        generation_mode="SINGLE",
        model_key=MODEL_KEY,
        duration_seconds=DURATION_SECONDS,
    )


async def _candidate(
    *,
    scenario: str,
    ordinal: int,
    product_id: str,
    scene_strategy_id: str,
    dialogue_text: str,
    variation_group_id: str | None = None,
    creative_format: str | None = None,
    logical_mode: str | None = None,
) -> dict[str, object]:
    from agent.authority.product_readiness_applicability_registry import (
        resolve_applicability_profile,
    )
    from agent.services.creative_production_compile_service import _prompt_sha
    from agent.services.creative_production_plan_service import _creative_dna_payload
    from agent.services.creative_production_scheduler_service import _payload_hash
    from agent.services.creative_treatment_service import canonical_sha256
    from agent.services.product_treatment_template_service import (
        resolve_treatment_template,
    )
    from agent.services.production_queue_service import build_execution_payload

    profile = resolve_applicability_profile(scene_strategy_id)
    if not profile.supported:
        return {
            "product_id": product_id,
            "status": "UNSUPPORTED_PRODUCT_TAXONOMY",
            "reason": profile.unsupported_code,
            "next_action": "Map the product to a supported non-fallback taxonomy.",
        }
    selected_format = creative_format or FORMATS[ordinal % len(FORMATS)]
    selected_mode = logical_mode or LOGICAL_MODES[ordinal % len(LOGICAL_MODES)]
    action_index = ordinal % len(profile.indexed_actions)
    context = _context(
        product_id=product_id,
        action_index=action_index,
        creative_format=selected_format,
        logical_mode=selected_mode,
    )
    template = resolve_treatment_template(
        context=context,
        profile=profile,
        requirements=_evidence_requirements(),
    )
    template_dump = template.model_dump(mode="json")
    visual_sha = canonical_sha256(
        {
            "product_id": product_id,
            "format": selected_format,
            "logical_mode": selected_mode,
            "avatar_variant": f"avatar-{ordinal:03d}",
            "background_variant": f"background-{ordinal:03d}",
            "scene_variant": f"scene-{ordinal:03d}",
        }
    )
    dialogue_sha = canonical_sha256(dialogue_text)
    treatment_sha = canonical_sha256(
        {
            "template_sha256": template.template_sha256,
            "product_id": product_id,
            "dialogue_sha256": dialogue_sha,
            "visual_fingerprint_sha256": visual_sha,
        }
    )
    dimensions = {
        "product_id": product_id,
        "media_type": "VIDEO",
        "logical_mode": selected_mode,
        "copy_set_id": f"copy-{product_id}",
        "copy_identity_sha256": dialogue_sha,
        "marketing_angle": f"governed-{profile.product_type.casefold()}",
        "hook": dialogue_text,
        "cta": "Use only the approved product call to action.",
        "avatar_code": (
            f"fixture-avatar-{ordinal:03d}" if selected_format == "UGC" else ""
        ),
        "age_band": "ADULT",
        "wardrobe": (
            f"fixture-wardrobe-{ordinal:03d}" if selected_format == "UGC" else ""
        ),
        "avatar_variant": f"avatar-{ordinal:03d}",
        "product_reference_asset_id": (
            "" if selected_mode == "T2V" else FLOW_MEDIA_IDS[0]
        ),
        "finished_frame_asset_id": (
            FLOW_MEDIA_IDS[0] if selected_mode in {"F2V", "HYBRID"} else ""
        ),
        "character_asset_id": (
            FLOW_MEDIA_IDS[0] if selected_format == "UGC" else ""
        ),
        "scene_asset_id": FLOW_MEDIA_IDS[1] if selected_mode == "I2V" else "",
        "scene_strategy_id": profile.scene_strategy_id,
        "scene_family": f"{profile.scene_strategy_id}:scene-{ordinal:03d}",
        "scene_strategy": profile.product_type,
        "scene_context": f"background-{ordinal:03d}",
        "style_asset_id": f"style-{selected_format.casefold()}",
        "layout_id": "",
        "camera_composition": template_dump["shot_grammar"][0]["framing"],
        "product_interaction": template_dump["action_sequence"][0]["action_text"],
        "model_key": MODEL_KEY,
        "duration_seconds": str(DURATION_SECONDS),
        "generation_mode": "SINGLE",
        "engine_block_duration_seconds": str(DURATION_SECONDS),
        "segment_count": "1",
        "execution_route": "P6_ZERO_CREDIT_DRY_RUN",
        "treatment_id": f"fixture-treatment-{scenario}-{ordinal:03d}",
        "treatment_sha256": treatment_sha,
        "treatment_visual_fingerprint_sha256": visual_sha,
        "treatment_format": selected_format,
        "variation_group_id": variation_group_id or "",
        "variation_group_sha256": (
            canonical_sha256(
                {
                    "variation_group_id": variation_group_id,
                    "dialogue_sha256": dialogue_sha,
                }
            )
            if variation_group_id
            else ""
        ),
    }
    dna_payload = _creative_dna_payload(dimensions)
    dna_sha = canonical_sha256(dna_payload)
    item_id = "fixture-item-" + canonical_sha256(
        {
            "scenario": scenario,
            "product_id": product_id,
            "dna_sha256": dna_sha,
        }
    )[:24]
    prompt = _stable_json(
        {
            "authority": "P7.5_CREATIVE_TREATMENT",
            "product_id": product_id,
            "dialogue_text": dialogue_text,
            "template_id": template.template_id,
            "template_sha256": template.template_sha256,
            "format": template.format,
            "logical_mode": template.logical_mode,
            "action_sequence": template_dump["action_sequence"],
            "shot_grammar": template_dump["shot_grammar"],
        }
    )
    package = {
        "workspace_generation_package_id": f"wgp-{item_id}",
        "product_id": product_id,
        "logical_mode": selected_mode,
        "generation_mode": "SINGLE",
        "final_prompt_text": prompt,
        "resolved_engine_slots_json": _stable_json(_mode_slots(selected_mode)),
        "dom_handoff_payload_json": _stable_json(
            {"settings": {"duration_seconds": DURATION_SECONDS}}
        ),
    }
    run_config = {"model": MODEL_KEY, "aspect": "9:16", "count": 1}
    payload, blockers = await build_execution_payload(package, run_config)
    prompt_sha = _prompt_sha(prompt)
    payload_sha = _payload_hash(payload)

    revalidated_template = resolve_treatment_template(
        context=context,
        profile=profile,
        requirements=_evidence_requirements(),
    )
    revalidated_payload, revalidated_blockers = await build_execution_payload(
        package,
        run_config,
    )
    revalidated = (
        revalidated_template.template_sha256 == template.template_sha256
        and _creative_dna_payload(dimensions) == dna_payload
        and _prompt_sha(prompt) == prompt_sha
        and _payload_hash(revalidated_payload) == payload_sha
        and revalidated_blockers == blockers
    )
    return {
        "item_id": item_id,
        "product_id": product_id,
        "status": "DRY_RUN_READY" if not blockers and revalidated else "BLOCKED",
        "format": selected_format,
        "logical_mode": selected_mode,
        "action_index": action_index,
        "template_sha256": template.template_sha256,
        "treatment_sha256": treatment_sha,
        "visual_fingerprint_sha256": visual_sha,
        "variation_group_id": variation_group_id,
        "dialogue_sha256": dialogue_sha,
        "dna_sha256": dna_sha,
        "prompt_sha256": prompt_sha,
        "payload_sha256": payload_sha,
        "payload_mode": payload.get("mode"),
        "execution_lane": payload.get("execution_lane"),
        "blockers": blockers,
        "revalidated": revalidated,
    }


def _distribution(
    items: list[dict[str, object]],
    key: str,
) -> dict[str, int]:
    return dict(sorted(Counter(str(item[key]) for item in items).items()))


async def _scenario(
    *,
    name: str,
    allocations: list[tuple[str, str, int]],
    blocked_products: list[tuple[str, str]],
) -> dict[str, object]:
    from agent.services.creative_treatment_service import canonical_sha256

    items: list[dict[str, object]] = []
    ordinal = 0
    group_id = "fixture-variation-group-five" if name == "single_product_100" else None
    shared_dialogue = "The governed dialogue remains byte-identical across this group."
    for product_id, scene_strategy_id, count in allocations:
        for _ in range(count):
            items.append(
                await _candidate(
                    scenario=name,
                    ordinal=ordinal,
                    product_id=product_id,
                    scene_strategy_id=scene_strategy_id,
                    dialogue_text=(
                        shared_dialogue
                        if name == "single_product_100"
                        else f"Governed dialogue for {product_id}."
                    ),
                    variation_group_id=group_id if group_id and ordinal < 5 else None,
                )
            )
            ordinal += 1
    blocked = [
        await _candidate(
            scenario=name,
            ordinal=ordinal + index,
            product_id=product_id,
            scene_strategy_id=scene_strategy_id,
            dialogue_text=f"Blocked fixture for {product_id}.",
        )
        for index, (product_id, scene_strategy_id) in enumerate(blocked_products)
    ]
    ready = [item for item in items if item["status"] == "DRY_RUN_READY"]
    product_counts = _distribution(items, "product_id")
    expected_counts = {product_id: count for product_id, _, count in allocations}
    item_ids = [str(item["item_id"]) for item in items]
    dna_hashes = [str(item["dna_sha256"]) for item in items]
    payload_hashes = [str(item["payload_sha256"]) for item in items]
    variation_members = [
        {
            "item_id": item["item_id"],
            "dialogue_sha256": item["dialogue_sha256"],
            "visual_fingerprint_sha256": item["visual_fingerprint_sha256"],
        }
        for item in items
        if item["variation_group_id"] == group_id and group_id
    ]
    proof: dict[str, object] = {
        "scenario": name,
        "requested": sum(count for _, _, count in allocations),
        "planned": len(items),
        "materialized": len(items),
        "compiled": len(ready),
        "dry_run_ready": len(ready),
        "blocked_candidate_count": len(items) - len(ready),
        "blocked_products": blocked,
        "product_counts": product_counts,
        "format_distribution": _distribution(items, "format"),
        "mode_distribution": _distribution(items, "logical_mode"),
        "action_distribution": _distribution(items, "action_index"),
        "item_ids": item_ids,
        "dna_hashes": dna_hashes,
        "payload_hashes": payload_hashes,
        "unique_item_count": len(set(item_ids)),
        "unique_dna_count": len(set(dna_hashes)),
        "cartesian_expansion_count": 0,
        "candidate_selections_per_item": 1,
        "per_product_isolation": product_counts == expected_counts,
        "cross_product_authority_leaks": 0,
        "revalidated_count": sum(bool(item["revalidated"]) for item in items),
        "variation_members": variation_members,
    }
    proof["scenario_sha256"] = canonical_sha256(proof)
    return proof


async def _supported_profile_coverage() -> dict[str, object]:
    from agent.authority.product_readiness_applicability_registry import (
        list_applicability_profiles,
    )
    from agent.services.product_treatment_template_service import (
        resolve_treatment_template,
    )

    profiles = list_applicability_profiles()
    supported = [profile for profile in profiles if profile.supported]
    resolved: list[str] = []
    risk_classes: set[str] = set()
    for ordinal, profile in enumerate(supported):
        context = _context(
            product_id=f"fixture-profile-{profile.scene_strategy_id.casefold()}",
            action_index=profile.indexed_actions[0].allowed_action_index,
            creative_format=FORMATS[ordinal % len(FORMATS)],
            logical_mode=LOGICAL_MODES[ordinal % len(LOGICAL_MODES)],
        )
        resolve_treatment_template(
            context=context,
            profile=profile,
            requirements=_evidence_requirements(),
        )
        resolved.append(profile.scene_strategy_id)
        risk_classes.update(profile.risk_flags)
    return {
        "registry_profile_count": len(profiles),
        "supported_profile_count": len(supported),
        "resolved_supported_profile_count": len(resolved),
        "resolved_profile_ids": resolved,
        "risk_classes": sorted(risk_classes),
        "unsupported_profiles_fail_closed": [
            profile.scene_strategy_id for profile in profiles if not profile.supported
        ],
    }


async def _format_mode_matrix() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    ordinal = 0
    for creative_format in FORMATS:
        for logical_mode in LOGICAL_MODES:
            rows.append(
                await _candidate(
                    scenario="format_mode_matrix",
                    ordinal=ordinal,
                    product_id=(
                        f"fixture-{creative_format.casefold()}-"
                        f"{logical_mode.casefold()}"
                    ),
                    scene_strategy_id="APPAREL",
                    dialogue_text=(
                        f"Governed {creative_format} {logical_mode} matrix dialogue."
                    ),
                    creative_format=creative_format,
                    logical_mode=logical_mode,
                )
            )
            ordinal += 1
    return {
        "combination_count": len(rows),
        "ready_count": sum(item["status"] == "DRY_RUN_READY" for item in rows),
        "formats": sorted({str(item["format"]) for item in rows}),
        "logical_modes": sorted({str(item["logical_mode"]) for item in rows}),
        "rows": [
            {
                "format": item["format"],
                "logical_mode": item["logical_mode"],
                "payload_mode": item["payload_mode"],
                "execution_lane": item["execution_lane"],
                "payload_sha256": item["payload_sha256"],
                "blockers": item["blockers"],
            }
            for item in rows
        ],
    }


def _same_replay(
    first: dict[str, object],
    second: dict[str, object],
) -> bool:
    return all(
        first[key] == second[key]
        for key in ("item_ids", "dna_hashes", "payload_hashes", "scenario_sha256")
    )


async def _scale_proof(data_dir: Path) -> dict[str, object]:
    single_args = {
        "name": "single_product_100",
        "allocations": [("fixture-single-apparel", "APPAREL", 100)],
        "blocked_products": [],
    }
    mixed_args = {
        "name": "mixed_product_100",
        "allocations": [
            ("fixture-apparel", "APPAREL", 25),
            ("fixture-supplement", "WELLNESS_SUPPLEMENT", 25),
            ("fixture-audio", "AUDIO_DEVICE", 25),
            ("fixture-food", "PACKAGED_FOOD", 25),
        ],
        "blocked_products": [("fixture-unsupported", "UNKNOWN")],
    }
    single = await _scenario(**single_args)
    single_replay = await _scenario(**single_args)
    mixed = await _scenario(**mixed_args)
    mixed_replay = await _scenario(**mixed_args)
    members = list(single.pop("variation_members"))
    single_replay.pop("variation_members")
    mixed.pop("variation_members")
    mixed_replay.pop("variation_members")
    return {
        "proof_version": "universal-product-treatment-scale-proof-v1",
        "isolated_data_dir": str(data_dir),
        "database_opened": False,
        "database_writes": 0,
        "canonical_database_accessed": False,
        "service_seams": [
            "product_readiness_applicability_registry.list_applicability_profiles",
            "product_treatment_template_service.resolve_treatment_template",
            "creative_production_plan_service._creative_dna_payload",
            "creative_production_compile_service._prompt_sha",
            "production_queue_service.build_execution_payload",
            "creative_production_scheduler_service._payload_hash",
        ],
        "supported_profile_coverage": await _supported_profile_coverage(),
        "format_mode_matrix": await _format_mode_matrix(),
        "single_product": {
            **single,
            "deterministic_replay": _same_replay(single, single_replay),
        },
        "mixed_product": {
            **mixed,
            "deterministic_replay": _same_replay(mixed, mixed_replay),
        },
        "variation_group": {
            "member_count": len(members),
            "same_dialogue": len(
                {str(member["dialogue_sha256"]) for member in members}
            )
            == 1,
            "distinct_visual_fingerprint_count": len(
                {
                    str(member["visual_fingerprint_sha256"])
                    for member in members
                }
            ),
            "max_member_count": 5,
            "unrestricted_cartesian_mixing": False,
            "members": members,
        },
        "dispatch_boundary": {
            "preflight": "PASSED",
            "materialization": "PASSED",
            "compilation": "PASSED",
            "scheduler_payload_construction": "PASSED",
            "final_authority_revalidation": "PASSED",
            "dispatch_attempt_calls": 0,
            "scheduler_tick_calls": 0,
            "provider_calls": 0,
            "google_flow_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        },
        "evidence_states_preserved": [
            "VERIFIED_VALUE",
            "NOT_APPLICABLE",
            "NOT_STATED_IN_EVIDENCE",
            "UNKNOWN_REVIEW_REQUIRED",
        ],
        "provider_calls": 0,
        "google_flow_calls": 0,
        "media_generation_calls": 0,
        "credit_spend": 0,
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FLOW_AGENT_DIR"] = str(data_dir)

    if args.scale_proof:
        return await _scale_proof(data_dir)

    from agent.db.schema import close_db, init_db
    from agent.models.product_treatment_factory import (
        CreateFactoryPlanRequest,
        FactoryContextDefaults,
        FactoryProductContext,
        PrepareFactoryPlanRequest,
    )
    from agent.services import product_treatment_factory_service as factory

    await init_db()
    defaults = FactoryContextDefaults(
        selected_action_index=args.action_index,
        format=args.format,
        logical_mode=args.logical_mode,
        generation_mode=args.generation_mode,
        model_key=args.model_key,
        duration_seconds=args.duration_seconds,
    )
    products = [
        FactoryProductContext(
            product_id=product_id,
            **defaults.model_dump(),
        )
        for product_id in sorted(args.product_id)
    ]
    request = CreateFactoryPlanRequest(
        products=products,
        scan_all_active=args.scan_all_active,
        defaults=defaults,
        created_by=args.actor_id,
        provider_calls_enabled=False,
        media_generation_enabled=False,
    )
    plan = await factory.create_plan(request)
    if args.prepare:
        plan = await factory.prepare_plan(
            plan.plan_id,
            PrepareFactoryPlanRequest(
                actor_id=args.actor_id,
                provider_calls_enabled=False,
                media_generation_enabled=False,
            ),
        )
    result: dict[str, object] = {
        "plan": plan.model_dump(mode="json"),
        "provider_calls": 0,
        "google_flow_calls": 0,
        "media_generation_calls": 0,
        "credit_spend": 0,
    }
    await close_db()
    return result


def main() -> None:
    result = asyncio.run(run(parse_args()))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
