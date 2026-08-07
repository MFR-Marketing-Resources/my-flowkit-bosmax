"""Deterministic, additive B3 creative-config treatment backfill.

The runner treats approved Creative Setup selections as immutable authority. It
selects one stable avatar x scene tuple per product, derives the bridge camera
from the scene, and only hands products that pass the cheap prerequisite census
to the existing review-gated Product Treatment Factory. It never overwrites an
approved selection or treatment and never enables provider/media generation.

Use ``--apply`` only after a verified ``flow_agent.db.prerecipe-*`` backup has
been created. The default mode is read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.services import creative_recipe_service
from agent.services import creative_scene_prompt_service


@dataclass(frozen=True)
class RecipeTuple:
    avatar_code: str
    scene_template_id: str
    camera_preset_code: str


def _json_list(value: object, fallback: object) -> list[str]:
    try:
        decoded = json.loads(value) if value else None
    except (TypeError, ValueError):
        decoded = None
    source = decoded if isinstance(decoded, list) else [fallback]
    return list(dict.fromkeys(str(item).strip() for item in source if str(item or "").strip()))


def select_recipe_tuple(
    selection: dict[str, Any],
    templates_by_id: dict[str, dict[str, Any]],
) -> tuple[RecipeTuple | None, str | None]:
    """Choose the first stable approved tuple and derive its camera from scene."""

    avatars = _json_list(
        selection.get("selected_avatar_codes_json"),
        selection.get("selected_avatar_code"),
    )
    scenes = _json_list(
        selection.get("selected_scene_template_ids_json"),
        selection.get("selected_scene_template_id"),
    )
    if not avatars or not scenes:
        return None, "SELECTION_TUPLE_INCOMPLETE"
    scene_id = scenes[0]
    template = templates_by_id.get(scene_id)
    if template is None:
        return None, "SCENE_TEMPLATE_NOT_FOUND"
    try:
        camera_code = creative_recipe_service.camera_for_variant(
            template.get("variant")
        )
    except (TypeError, ValueError):
        return None, "SCENE_CAMERA_DERIVATION_FAILED"
    if not camera_code:
        return None, "SCENE_CAMERA_DERIVATION_FAILED"
    return RecipeTuple(avatars[0], scene_id, camera_code), None


def _distinct_products(
    db: sqlite3.Connection,
    query: str,
    parameter: str | None = None,
) -> set[str]:
    params = (parameter,) if parameter is not None else ()
    return {str(row[0]) for row in db.execute(query, params)}


def _dna_coverage(db: sqlite3.Connection) -> dict[str, int]:
    rows = db.execute(
        "SELECT product_id, creative_dimensions_json "
        "FROM creative_production_item"
    ).fetchall()
    complete: set[tuple[str, str, str, str]] = set()
    for product_id, payload in rows:
        try:
            dimensions = json.loads(payload or "{}")
        except (TypeError, ValueError):
            dimensions = {}
        fields = (
            dimensions.get("avatar_code"),
            dimensions.get("scene_template_id"),
            dimensions.get("camera_preset_code"),
        )
        if all(fields):
            complete.add((str(product_id), *(str(value) for value in fields)))
    return {
        "production_items": len(rows),
        "complete_tuple_items": len(complete),
        "complete_tuple_products": len({row[0] for row in complete}),
        "distinct_complete_tuples": len(complete),
    }


def read_snapshot(db_path: Path) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        selection_rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM creative_product_selection "
                "WHERE status='APPROVED' ORDER BY product_id"
            )
        ]
        treatment_rows = [
            dict(row)
            for row in db.execute("SELECT * FROM creative_treatment")
        ]
        templates_by_id = {
            str(template["template_id"]): template
            for template in creative_scene_prompt_service.library_templates()
            if template.get("template_id")
        }
        existing_by_tuple: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        treatments_by_product: dict[str, list[dict[str, Any]]] = {}
        for treatment in treatment_rows:
            product_id = str(treatment["product_id"])
            treatments_by_product.setdefault(product_id, []).append(treatment)
            tuple_key = (
                product_id,
                str(treatment.get("avatar_code") or ""),
                str(treatment.get("scene_template_id") or ""),
                str(treatment.get("camera_preset_code") or ""),
            )
            if all(tuple_key[1:]):
                existing_by_tuple.setdefault(tuple_key, []).append(treatment)

        truth_products = _distinct_products(
            db,
            "SELECT DISTINCT product_id FROM product_intelligence_snapshot "
            "WHERE status='APPROVED'",
        )
        copy_products = _distinct_products(
            db,
            "SELECT DISTINCT product_id FROM copy_set "
            "WHERE status='COPY_APPROVED' AND archived=0",
        )
        asset_products_by_role = {
            role: _distinct_products(
                db,
                "SELECT DISTINCT product_id FROM creative_asset "
                "WHERE semantic_role=? AND status='ACTIVE' "
                "AND review_status='APPROVED' "
                "AND approved_for_video_support=1",
                role,
            )
            for role in ("PRODUCT_REFERENCE", "CHARACTER_REFERENCE")
        }

        blockers: Counter[str] = Counter()
        target_rows: list[dict[str, Any]] = []
        eligible_products: list[str] = []
        target_tuple_already_present = 0
        for selection in selection_rows:
            product_id = str(selection["product_id"])
            recipe, reason = select_recipe_tuple(selection, templates_by_id)
            if recipe is None:
                blockers[reason or "SELECTION_TUPLE_INVALID"] += 1
                continue
            target_key = (
                product_id,
                recipe.avatar_code,
                recipe.scene_template_id,
                recipe.camera_preset_code,
            )
            existing = existing_by_tuple.get(target_key, [])
            if existing:
                target_tuple_already_present += 1
                continue
            if any(str(row.get("status")) == "APPROVED" for row in treatments_by_product.get(product_id, [])):
                blockers["APPROVED_TREATMENT_EXISTS_UNTOUCHED"] += 1
                continue
            if product_id not in truth_products:
                blockers["PRODUCT_TRUTH_NOT_APPROVED"] += 1
                continue
            if product_id not in copy_products:
                blockers["COPY_SET_NOT_APPROVED"] += 1
                continue
            if product_id not in asset_products_by_role["PRODUCT_REFERENCE"]:
                blockers["PRODUCT_REFERENCE_VIDEO_ASSET_REQUIRED"] += 1
                continue
            if product_id not in asset_products_by_role["CHARACTER_REFERENCE"]:
                blockers["CHARACTER_REFERENCE_VIDEO_ASSET_REQUIRED"] += 1
                continue
            target_rows.append(
                {
                    "product_id": product_id,
                    "recipe": recipe,
                    "tuple_key": target_key,
                }
            )
            eligible_products.append(product_id)

        complete_treatments = [
            row
            for row in treatment_rows
            if row.get("avatar_code")
            and row.get("scene_template_id")
            and row.get("camera_preset_code")
        ]
        return {
            "selection": {
                "approved": len(selection_rows),
                "complete_config": sum(
                    1
                    for row in selection_rows
                    if _json_list(row.get("selected_avatar_codes_json"), row.get("selected_avatar_code"))
                    and _json_list(row.get("selected_scene_template_ids_json"), row.get("selected_scene_template_id"))
                    and _json_list(row.get("selected_camera_preset_codes_json"), row.get("selected_camera_preset_code"))
                ),
                "newly_written": 0,
                "already_present": len(selection_rows),
            },
            "treatments": {
                "total": len(treatment_rows),
                "approved": sum(1 for row in treatment_rows if row.get("status") == "APPROVED"),
                "complete_tuple": len(complete_treatments),
                "target_tuple_already_present": target_tuple_already_present,
                "newly_written": 0,
                "already_present": target_tuple_already_present,
            },
            "dna_tuple_coverage": _dna_coverage(db),
            "eligible_products": eligible_products,
            "target_rows": target_rows,
            "blockers": dict(sorted(blockers.items())),
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        }
    finally:
        db.close()


def _verify_backup(backup_path: Path) -> None:
    if not backup_path.is_file() or backup_path.stat().st_size <= 0:
        raise RuntimeError(f"VERIFIED_BACKUP_REQUIRED:{backup_path}")
    db = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        db.close()
    if result != "ok":
        raise RuntimeError(f"BACKUP_INTEGRITY_FAILED:{result}")


async def _materialize(products: list[str]) -> None:
    if not products:
        return
    from agent.models.product_treatment_factory import (
        CreateFactoryPlanRequest,
        FactoryProductContext,
        FactoryContextDefaults,
        PrepareFactoryPlanRequest,
    )
    from agent.services import product_treatment_factory_service as factory

    for offset in range(0, len(products), 200):
        cohort = products[offset : offset + 200]
        request = CreateFactoryPlanRequest(
            products=[
                FactoryProductContext(
                    product_id=product_id,
                    format="UGC",
                    logical_mode="T2V",
                    generation_mode="SINGLE",
                    model_key="veo_3_1_fast",
                    duration_seconds=8,
                )
                for product_id in cohort
            ],
            target_video_count=len(cohort),
            defaults=FactoryContextDefaults(
                format="UGC",
                logical_mode="T2V",
                generation_mode="SINGLE",
                model_key="veo_3_1_fast",
                duration_seconds=8,
            ),
            created_by="b3-creative-config-backfill",
            provider_calls_enabled=False,
            media_generation_enabled=False,
        )
        plan = await factory.create_plan(request)
        await factory.prepare_plan(
            plan.plan_id,
            PrepareFactoryPlanRequest(
                actor_id="b3-creative-config-backfill",
                max_tasks=len(cohort) * 10,
                materialize_copy_composition=False,
                materialize_treatment_candidates=True,
                provider_calls_enabled=False,
                media_generation_enabled=False,
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("flow_agent.db"))
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db_path = args.db.resolve()
    before = read_snapshot(db_path)
    if args.apply:
        if args.backup is None:
            raise SystemExit("--backup is required with --apply")
        _verify_backup(args.backup.resolve())
        asyncio.run(_materialize(before["eligible_products"]))
    after = read_snapshot(db_path)
    if args.apply:
        before_tuples = before["treatments"]["total"]
        after_tuples = after["treatments"]["total"]
        after["treatments"]["newly_written"] = max(0, after_tuples - before_tuples)
        after["treatments"]["already_present"] = (
            before["treatments"]["target_tuple_already_present"]
        )
    after.pop("eligible_products", None)
    after.pop("target_rows", None)
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "before": before, "after": after}, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
