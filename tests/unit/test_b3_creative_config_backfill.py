from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "b3-creative-config-backfill.py"
_SPEC = importlib.util.spec_from_file_location("b3_creative_config_backfill", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

RecipeTuple = _MODULE.RecipeTuple
required_asset_roles_for_mode = _MODULE.required_asset_roles_for_mode
select_recipe_tuple = _MODULE.select_recipe_tuple
video_asset_blockers_for_mode = _MODULE.video_asset_blockers_for_mode


def test_t2v_does_not_require_visual_asset_roles() -> None:
    assert required_asset_roles_for_mode("T2V") == ()
    assert video_asset_blockers_for_mode("product-1", "T2V", {}) == ()


def test_reference_modes_keep_their_visual_asset_requirements() -> None:
    assert video_asset_blockers_for_mode("product-1", "F2V", {}) == (
        "COMPOSITE_FRAME_REFERENCE_VIDEO_ASSET_REQUIRED",
    )
    assert video_asset_blockers_for_mode("product-1", "I2V", {}) == (
        "PRODUCT_REFERENCE_VIDEO_ASSET_REQUIRED",
        "SCENE_CONTEXT_REFERENCE_VIDEO_ASSET_REQUIRED",
    )


def test_select_recipe_tuple_derives_camera_from_scene() -> None:
    selection = {
        "selected_avatar_codes_json": '["AVATAR_A", "AVATAR_B"]',
        "selected_scene_template_ids_json": '["SCN-01", "SCN-05"]',
        "selected_camera_preset_codes_json": '["WRONG_CALLER_CAMERA"]',
    }
    tuple_value, reason = select_recipe_tuple(
        selection,
        {"SCN-01": {"template_id": "SCN-01", "variant": "Variation 1 - Present"}},
    )
    assert reason is None
    assert tuple_value == RecipeTuple("AVATAR_A", "SCN-01", "BODY_A")


def test_select_recipe_tuple_fails_closed_for_missing_avatar_or_scene() -> None:
    tuple_value, reason = select_recipe_tuple(
        {
            "selected_avatar_codes_json": "[]",
            "selected_scene_template_ids_json": '["SCN-01"]',
        },
        {"SCN-01": {"template_id": "SCN-01", "variant": "Variation 1 - Present"}},
    )
    assert tuple_value is None
    assert reason == "SELECTION_TUPLE_INCOMPLETE"


def test_dry_run_report_omits_internal_recipe_rows_before_json_serialization(
    monkeypatch,
    capsys,
) -> None:
    snapshot = {
        "eligible_products": ["product-1"],
        "target_rows": [{"recipe": RecipeTuple("AVATAR_A", "SCN-01", "BODY_A")}],
        "treatments": {"total": 0},
    }
    snapshots = iter([snapshot.copy(), snapshot.copy()])
    monkeypatch.setattr(_MODULE, "read_snapshot", lambda _path: next(snapshots))
    monkeypatch.setattr(sys, "argv", ["b3-creative-config-backfill.py"])

    _MODULE.main()

    report = json.loads(capsys.readouterr().out)
    assert "eligible_products" not in report["before"]
    assert "target_rows" not in report["before"]
    assert "eligible_products" not in report["after"]
    assert "target_rows" not in report["after"]
