"""Isolated zero-credit rehearsal for the Product-to-Treatment Factory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    parser.add_argument("--format", choices=("UGC", "PGC", "CINEMATIC"), default="PGC")
    parser.add_argument(
        "--logical-mode",
        choices=("T2V", "F2V", "I2V", "HYBRID"),
        default="HYBRID",
    )
    parser.add_argument(
        "--generation-mode",
        choices=("SINGLE", "EXTEND"),
        default="SINGLE",
    )
    parser.add_argument("--model-key", default="veo_3_1_fast")
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument("--action-index", type=int, default=0)
    parser.add_argument("--actor-id", default="factory-rehearsal")
    parser.add_argument("--prepare", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FLOW_AGENT_DIR"] = str(data_dir)

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
