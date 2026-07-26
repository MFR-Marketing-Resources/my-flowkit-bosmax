"""Behavioural tests for exact product final-output orchestration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from agent.services import exact_product_final_output_service as svc
from agent.services.exact_product_compositor_service import ExactProductCompositeError


def test_policy_blocks_product_ref_uses_requires_exact_composite():
    with patch.object(svc, "requires_exact_composite", return_value=True):
        assert svc.policy_blocks_product_ref({"id": "x"}) is True
    with patch.object(svc, "requires_exact_composite", return_value=False):
        assert svc.policy_blocks_product_ref({"id": "x"}) is False


def test_build_scene_only_prompt_is_non_empty_scene_directive():
    prompt = svc.build_scene_only_prompt(
        "Product bottle of minyak on wood table, brand CAP BURUNG label visible"
    )
    assert isinstance(prompt, str) and len(prompt) > 20
    low = prompt.lower()
    assert any(
        tok in low
        for tok in (
            "no product",
            "without product",
            "product-free",
            "scene only",
            "scene-only",
            "do not",
            "no bottle",
            "empty",
            "background",
        )
    )


def test_assert_not_raw_plate_save_blocks_when_marked_approvable():
    with pytest.raises(ExactProductCompositeError):
        svc.assert_not_raw_plate_save({"raw_plate_approvable": True})
    # non-approvable lineage is allowed
    svc.assert_not_raw_plate_save({"raw_plate_approvable": False})
    svc.assert_not_raw_plate_save(None)


@pytest.mark.asyncio
async def test_compose_final_for_product_registers_new_media_id(tmp_path: Path, monkeypatch):
    plate = tmp_path / "plate.jpg"
    Image.new("RGB", (512, 512), (200, 200, 200)).save(plate, quality=90)
    final_png = tmp_path / "final.png"
    Image.new("RGBA", (100, 200), (0, 128, 0, 255)).save(final_png)

    product = {
        "id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
    }
    fake_compose = {
        "output_path": str(final_png),
        "output_sha256": "abc123",
        "schema_key": "MWCB_25ML_CAP_BURUNG",
        "canonical_source_sha256": "src",
        "cutout_sha256": "cut",
        "raw_plate_sha256": "plate",
        "raw_plate_path": str(plate),
        "transform": {"x": 0, "y": 0, "w": 100, "h": 200},
        "qa": {"product_region_match": True},
        "truth_status": "EXACT_COMPOSITE",
    }

    monkeypatch.setattr(svc, "resolve_product", AsyncMock(return_value=product))
    monkeypatch.setattr(svc, "requires_exact_composite", lambda p: True)
    monkeypatch.setattr(svc, "validate_canonical_or_raise", lambda p: {"ok": True})
    monkeypatch.setattr(
        svc,
        "_resolve_plate",
        AsyncMock(return_value=("", plate)),
    )
    monkeypatch.setattr(svc, "compose_final_from_plate", lambda *a, **k: fake_compose)
    monkeypatch.setattr(svc.crud, "insert_generated_artifact", AsyncMock(return_value=None))

    out = await svc.compose_final_for_product(
        product_id=product["id"],
        background_local_path=str(plate),
        lane="studio",
    )
    assert out["ok"] is True
    assert out["media_id"] and out["media_id"] != ""
    assert out["lineage"]["raw_plate_approvable"] is False
    assert out["lineage"]["final_approvable"] is True
    assert out["url"].startswith("/api/flow/retrieved/")
