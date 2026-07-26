"""Exact product final-output orchestration + compositor honesty tests."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.exact_product_output import router
from agent.services.exact_product_compositor_service import (
    ExactProductCompositeError,
    augment_prompt_scene_only,
    compose_final_from_plate,
    composite,
    prepare_layer,
    requires_exact_composite,
    validate_canonical_or_raise,
)
from agent.services import exact_product_final_output_service as final_svc


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _make_source(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source.png"
    original = Image.new("RGBA", (40, 60), (250, 250, 250, 255))
    for y in range(10, 55):
        for x in range(10, 30):
            original.putpixel((x, y), (12, 100, 70, 255))
    original.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return source, digest


def _entry(source: Path, digest: str) -> dict:
    return {
        "product_id": "MWCB_25ML_CAP_BURUNG",
        "on_the_fly_flags": {"exact_product_composite_required": True},
        "canonical_product_photo": {
            "source_path": str(source),
            "sha256": digest,
            "dimensions": "40x60",
        },
    }


def test_exact_product_cutout_composite_preserves_transformed_pixels(tmp_path, monkeypatch):
    source, digest = _make_source(tmp_path)
    entry = _entry(source, digest)
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.resolve_schema_entry",
        lambda _: entry,
    )
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.BASE_DIR", tmp_path
    )
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.OUTPUT_DIR", tmp_path / "out"
    )
    (tmp_path / "out").mkdir()
    layer = prepare_layer({}, {"x": 10, "y": 10, "w": 60, "h": 70}, {"w": 1080, "h": 1920})
    assert layer["source_sha256"] == digest
    assert layer["transform"]["perspective_skew_x"] == 0.0
    assert layer["transform"]["rotation_degrees"] == 0.0
    target = tmp_path / "poster.png"
    Image.new("RGBA", (1080, 1920), (255, 240, 220, 255)).save(target)
    integrity = composite(target, layer)
    assert integrity["composition_ok"] is True
    assert integrity["write_verified"] is True
    assert integrity["product_region_match"] is True
    assert integrity["exact_product_count"] == 1
    assert integrity["pixel_match"] is True


def test_hash_mismatch_fails_before_compose(tmp_path, monkeypatch):
    source, digest = _make_source(tmp_path)
    entry = _entry(source, "0" * 64)
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.resolve_schema_entry",
        lambda _: entry,
    )
    with pytest.raises(ExactProductCompositeError) as ei:
        validate_canonical_or_raise({"product_display_name": "x"})
    assert ei.value.code == "CANONICAL_PRODUCT_SOURCE_INVALID"


def test_scene_only_prompt_forbids_product_and_strips_preserve(tmp_path, monkeypatch):
    prompt = (
        "CLEAN SCENE MODE. PRESERVE the real product label exactly.\n"
        "Feature the product heroically."
    )
    out = augment_prompt_scene_only(prompt)
    assert "EXACT_PRODUCT_COMPOSITE_REQUIRED" in out
    assert "Do not render" in out or "do not render" in out.lower()
    assert "PRESERVE the real product label" not in out


def test_compose_final_from_plate_lineage(tmp_path, monkeypatch):
    source, digest = _make_source(tmp_path)
    entry = _entry(source, digest)
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.resolve_schema_entry",
        lambda _: entry,
    )
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.BASE_DIR", tmp_path
    )
    out_root = tmp_path / "out"
    out_root.mkdir()
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.OUTPUT_DIR", out_root
    )
    plate = tmp_path / "plate.png"
    Image.new("RGBA", (540, 960), (200, 210, 220, 255)).save(plate)
    result = compose_final_from_plate(
        {"id": "p1", "product_display_name": "Minyak Warisan Cap Burung 25ml"},
        plate,
        lane="studio",
    )
    assert result["ok"] is True
    assert result["raw_plate_approvable"] is False
    assert result["final_approvable"] is True
    assert result["canonical_source_sha256"] == digest
    assert Path(result["output_path"]).exists()
    assert result["qa"]["product_region_match"] is True
    # aspect preserved: placed box matches cutout intrinsic ratio
    tr = result["transform"]
    from agent.services import exact_product_compositor_service as epc
    layer = epc.prepare_layer(
        {"id": "p1", "product_display_name": "Minyak Warisan Cap Burung 25ml"},
        epc.LANE_SAFE_REGIONS["studio"],
        {"w": 540, "h": 960},
    )
    cut_im = Image.open(layer["asset_ref"])
    expected = cut_im.width / max(1, cut_im.height)
    assert abs((tr["w"] / tr["h"]) - expected) < 0.02


def test_non_exact_requires_false(monkeypatch):
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.resolve_schema_entry",
        lambda _: {"on_the_fly_flags": {}},
    )
    assert requires_exact_composite({"id": "x"}) is False


@pytest.mark.asyncio
async def test_final_output_service_registers_artifact(tmp_path, monkeypatch):
    source, digest = _make_source(tmp_path)
    entry = _entry(source, digest)
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.resolve_schema_entry",
        lambda _: entry,
    )
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.BASE_DIR", tmp_path
    )
    out_root = tmp_path / "out"
    out_root.mkdir()
    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service.OUTPUT_DIR", out_root
    )
    monkeypatch.setattr(
        "agent.services.exact_product_final_output_service.OUTPUT_DIR", out_root
    )
    monkeypatch.setattr(
        "agent.services.exact_product_final_output_service._ALLOWED_PLATE_ROOTS",
        (out_root,),
    )
    plate = out_root / "retrieved" / "plate.png"
    plate.parent.mkdir(parents=True)
    Image.new("RGBA", (540, 960), (180, 190, 200, 255)).save(plate)

    product = {
        "id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
    }

    async def fake_get(pid):
        return product

    inserted = {}

    async def fake_insert(**kwargs):
        inserted.update(kwargs)

    async def fake_artifact(mid):
        return {"media_id": mid, "local_path": str(plate)}

    monkeypatch.setattr(final_svc.crud, "get_product", fake_get)
    monkeypatch.setattr(final_svc.crud, "insert_generated_artifact", fake_insert)
    monkeypatch.setattr(final_svc.crud, "get_generated_artifact", fake_artifact)

    result = await final_svc.compose_final_for_product(
        product_id=product["id"],
        background_media_id="plate-1",
        lane="poster",
    )
    assert result["ok"] is True
    assert len(result["media_id"]) == 36 and result["media_id"].count("-") == 4
    assert result["lineage"]["raw_plate_approvable"] is False
    assert result["lineage"]["canonical_source_sha256"] == digest
    assert inserted["artifact_kind"] == "image"
    assert inserted["mode"] == "IMG_EXACT_COMPOSITE"


def test_api_policy_non_exact(monkeypatch):
    async def fake_policy(pid):
        return {
            "product_id": pid,
            "exact_product_composite_required": False,
            "send_product_reference_to_flow": True,
            "scene_only_prompt_block": "",
        }

    monkeypatch.setattr(final_svc, "get_policy_for_product", fake_policy)
    r = _client().get("/api/exact-product/policy/abc")
    assert r.status_code == 200
    assert r.json()["exact_product_composite_required"] is False


def test_api_compose_maps_error(monkeypatch):
    async def boom(**kwargs):
        raise ExactProductCompositeError("CANONICAL_PRODUCT_SOURCE_INVALID", status_code=422)

    monkeypatch.setattr(final_svc, "compose_final_for_product", boom)
    r = _client().post(
        "/api/exact-product/compose-from-plate",
        json={"product_id": "x", "background_media_id": "m1", "lane": "studio"},
    )
    assert r.status_code == 422
    body = r.json()
    detail = body.get("detail", body)
    assert detail.get("error") == "CANONICAL_PRODUCT_SOURCE_INVALID"


def test_api_scene_only_prompt(monkeypatch):
    async def pol(pid):
        return {
            "product_id": pid,
            "exact_product_composite_required": True,
            "canonical_valid": True,
            "scene_only_prompt_block": "- EXACT",
        }

    monkeypatch.setattr(final_svc, "get_policy_for_product", pol)
    monkeypatch.setattr(
        final_svc,
        "build_scene_only_prompt",
        lambda p: p + "\nEXACT_PRODUCT_COMPOSITE_REQUIRED",
    )
    r = _client().post(
        "/api/exact-product/scene-only-prompt",
        json={"product_id": "p", "prompt": "studio background"},
    )
    assert r.status_code == 200
    assert "EXACT_PRODUCT_COMPOSITE_REQUIRED" in r.json()["prompt"]
    assert r.json()["send_product_reference_to_flow"] is False
