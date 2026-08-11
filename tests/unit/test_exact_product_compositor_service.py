"""Exact product final-output orchestration + compositor honesty tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
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
from agent.services import product_truth_lock_service as truth_lock_service


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


def _install_approved_lock(tmp_path: Path, product_id: str, source: Path) -> Path:
    """Offline fixture for an explicitly reviewed cutout; no heuristic approval."""
    cutout = tmp_path / f"{product_id}-approved-cutout.png"
    with Image.open(source).convert("RGBA") as src:
        rgba = Image.new("RGBA", src.size, (0, 0, 0, 0))
        source_px = src.load()
        target_px = rgba.load()
        for y in range(src.height):
            for x in range(src.width):
                r, g, b, a = source_px[x, y]
                if a >= 200 and not (r >= 235 and g >= 235 and b >= 230):
                    target_px[x, y] = (r, g, b, 255)
        rgba.save(cutout)
    alpha_sha = hashlib.sha256(rgba.getchannel("A").tobytes()).hexdigest()
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    cutout_sha = hashlib.sha256(cutout.read_bytes()).hexdigest()
    db_path = tmp_path / f"{product_id}-truth.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE product_visual_truth_lock (
                product_id TEXT PRIMARY KEY, canonical_media_id TEXT NOT NULL,
                canonical_sha256 TEXT NOT NULL, source_width INTEGER NOT NULL,
                source_height INTEGER NOT NULL, canonical_source_path TEXT NOT NULL,
                canonical_cutout_media_id TEXT NOT NULL, canonical_cutout_sha256 TEXT NOT NULL,
                canonical_cutout_path TEXT NOT NULL, alpha_mask_json TEXT NOT NULL,
                anchor_point_json TEXT NOT NULL, min_scale REAL NOT NULL, max_scale REAL NOT NULL,
                allowed_bbox_json TEXT NOT NULL, allowed_rotation REAL NOT NULL,
                allowed_perspective REAL NOT NULL, identity_lock INTEGER NOT NULL,
                geometry_lock INTEGER NOT NULL, label_lock INTEGER NOT NULL, logo_lock INTEGER NOT NULL,
                colour_lock INTEGER NOT NULL, scale_lock INTEGER NOT NULL, review_status TEXT NOT NULL,
                failure_state TEXT NOT NULL, provenance_json TEXT NOT NULL, schema_version TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO product_visual_truth_lock VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                product_id, f"media-{product_id}", source_sha, rgba.width, rgba.height, str(source),
                f"cutout-{product_id}", cutout_sha, str(cutout),
                json.dumps({"source": "cutout_alpha", "sha256": alpha_sha, "width": rgba.width, "height": rgba.height}),
                json.dumps({"x": 0.5, "y": 0.5}), 0.01, 100.0,
                json.dumps({"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.9}),
                0.0, 0.0, 1, 1, 1, 1, 1, 1, "APPROVED", "",
                json.dumps({"source": "offline-test", "review": "approved-fixture"}), "1.0",
            ),
        )
        conn.commit()
    truth_lock_service.DB_PATH = db_path
    return cutout


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
    _install_approved_lock(tmp_path, "p1", source)
    layer = prepare_layer({"id": "p1"}, {"x": 10, "y": 10, "w": 60, "h": 70}, {"w": 1080, "h": 1920})
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
    _install_approved_lock(tmp_path, "p1", source)
    source.write_bytes(b"stale-source")
    with pytest.raises(ExactProductCompositeError) as ei:
        validate_canonical_or_raise({"id": "p1", "_exact_product_required": True})
    assert ei.value.code == "CANONICAL_PRODUCT_SOURCE_INVALID"


def test_scene_only_prompt_forbids_product_and_strips_preserve(tmp_path, monkeypatch):
    prompt = (
        "CLEAN SCENE MODE. PRESERVE the real product label exactly.\n"
        "Feature the product heroically."
    )
    out = augment_prompt_scene_only(prompt)
    assert "EXACT_PRODUCT_COMPOSITE_REQUIRED" in out
    assert "Do not generate, render" in out
    assert "PRESERVE the real product label" not in out


def test_scene_only_prompt_removes_marketing_copy_sections():
    prompt = "\n".join(
        (
            "=== PRODUCT TRUTH LOCK ===",
            "Sambal Nyet Berapi by Khairulaming; preserve label truth.",
            "=== POSTER RECIPE ===",
            "Recipe: Product Hero.",
            "=== COPY SLOTS ===",
            "- [HEADLINE] headline: Sambal Nyet Berapi: Pedasnya Memang Gila!",
            "- [CTA] cta: Jom cuba sekarang!",
            "=== TEXT OVERLAY ===",
            "Language: ms. Text density: medium.",
            "=== OPERATOR NOTES ===",
            "Guided Poster Builder",
        )
    )

    out = augment_prompt_scene_only(prompt)

    assert "=== PRODUCT TRUTH LOCK ===" not in out
    assert "=== COPY SLOTS ===" not in out
    assert "=== TEXT OVERLAY ===" not in out
    assert "Sambal Nyet Berapi: Pedasnya Memang Gila!" not in out
    assert "Jom cuba sekarang!" not in out
    assert "EXACT_PRODUCT_COMPOSITE_REQUIRED" in out


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
    _install_approved_lock(tmp_path, "p1", source)
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
    crop = cut_im.getchannel("A").getbbox()
    assert crop is not None
    expected = (crop[2] - crop[0]) / max(1, crop[3] - crop[1])
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
    _install_approved_lock(tmp_path, product["id"], source)

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
    async def fake_policy(pid, **kwargs):
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
    async def pol(pid, **kwargs):
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

def test_cutout_preserves_cream_cartouche_label(tmp_path, monkeypatch):
    """Regression: cream bird panel must not become 10px median mosaic."""
    from PIL import Image, ImageDraw
    from agent.services import exact_product_compositor_service as mod

    # Synthetic label: teal frame + cream cartouche with sharp black "bird" mark
    im = Image.new("RGB", (240, 480), (240, 238, 232))
    d = ImageDraw.Draw(im)
    # red cap
    d.rectangle((90, 20, 150, 70), fill=(200, 30, 30))
    # teal body
    d.rectangle((70, 90, 170, 400), fill=(40, 130, 140))
    # cream cartouche
    d.rectangle((95, 140, 145, 280), fill=(205, 197, 173))
    # sharp bird-like dark mark (must survive cutout)
    d.polygon([(120, 160), (105, 200), (120, 190), (135, 200)], fill=(20, 25, 30))
    d.text((100, 220), "CAP", fill=(10, 10, 10))
    d.text((102, 250), "25ml", fill=(10, 10, 10))
    # green liquid tint under label
    d.rectangle((80, 300, 160, 390), fill=(30, 140, 70))
    src = tmp_path / "canon.jpg"
    im.save(src, quality=95)

    cut = mod._build_canonical_cutout(src)
    assert cut.mode == "RGBA"
    px = cut.load()
    w, h = cut.size
    opaque = cream = dark = 0
    cream_xy = []
    colors = set()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            opaque += 1
            colors.add((r, g, b))
            if r >= 150 and g >= 140 and (r - b) >= 12:
                cream += 1
                cream_xy.append((x, y))
            if (r + g + b) / 3.0 < 50:
                dark += 1
    assert opaque > 500
    assert cream > 80, f"cream cartouche lost: {cream}"
    assert dark > 20, f"dark label mark lost: {dark}"
    # cream panel should retain source cream tone (not replaced by teal median)
    assert any(abs(c[0] - 205) < 25 and abs(c[1] - 197) < 25 for c in colors), colors
    assert len(colors) >= 8, f"label collapsed to mosaic blocks uniq={len(colors)}"


def test_cutout_can_preserve_canonical_source_canvas(tmp_path):
    from PIL import Image, ImageDraw
    from agent.services.exact_product_compositor_service import _build_canonical_cutout

    im = Image.new("RGB", (120, 240), (240, 238, 232))
    d = ImageDraw.Draw(im)
    d.rectangle((45, 10, 75, 35), fill=(200, 30, 30))
    d.rectangle((35, 50, 85, 210), fill=(40, 130, 140))
    d.rectangle((45, 80, 75, 150), fill=(205, 197, 173))
    d.rectangle((40, 160, 80, 200), fill=(30, 140, 70))
    src = tmp_path / "canvas.jpg"
    im.save(src, quality=95)

    cut = _build_canonical_cutout(src, preserve_canvas=True)

    assert cut.size == im.size
    assert cut.getchannel("A").getbbox() is not None


def test_prepare_layer_uses_cutout_v13_cache_key(tmp_path, monkeypatch):
    from agent.services import exact_product_compositor_service as mod
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (200, 400), (245, 245, 240))
    d = ImageDraw.Draw(im)
    d.rectangle((70, 15, 130, 55), fill=(210, 25, 25))
    d.rectangle((60, 70, 140, 340), fill=(35, 125, 135))
    d.rectangle((80, 110, 120, 220), fill=(205, 197, 173))
    d.rectangle((70, 250, 130, 320), fill=(25, 130, 60))
    src = tmp_path / "c.jpg"
    im.save(src, quality=95)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
    (tmp_path / "out").mkdir(parents=True)

    product = {
        "id": "p1",
        "_exact_product_required": True,
        "on_the_fly_flags": {"exact_product_composite_required": True},
        "canonical_product_photo": {
            "sha256": sha,
            "local_path": str(src),
            "schema_key": "MWCB_25ML_CAP_BURUNG",
        },
        "product_schema_key": "MWCB_25ML_CAP_BURUNG",
    }
    cutout = _install_approved_lock(tmp_path, "p1", src)
    layer = mod.prepare_layer(
        product,
        {"x": 10, "y": 10, "w": 80, "h": 80},
        {"w": 400, "h": 800},
    )
    assert layer
    assert layer["asset_ref"] == str(cutout)


def test_trim_background_edge_fringe_removes_wall_halo():
    """Right-edge wall pixels on hard alpha must be trimmed, not left as halo."""
    from PIL import Image, ImageDraw
    from agent.services.exact_product_compositor_service import (
        _trim_background_edge_fringe,
        _harden_cutout_alpha_after_resize,
    )

    im = Image.new("RGBA", (80, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # product core teal
    d.rectangle((20, 20, 55, 140), fill=(40, 130, 140, 255))
    # dirty right-edge wall fringe (opaque bg)
    d.rectangle((56, 25, 62, 135), fill=(210, 205, 198, 255))
    cleaned = _trim_background_edge_fringe(im, passes=4)
    px = cleaned.load()
    # fringe column should be mostly gone
    fringe_left = sum(1 for y in range(25, 135) if px[58, y][3] >= 200)
    core_left = sum(1 for y in range(25, 135) if px[40, y][3] >= 200)
    assert core_left > 80, core_left
    assert fringe_left < 15, fringe_left

    # LANCZOS soft halo hardened
    soft = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(soft)
    d2.rectangle((8, 8, 30, 70), fill=(40, 130, 140, 255))
    # synthetic translucent halo column
    for y in range(10, 68):
        soft.putpixel((31, y), (200, 195, 190, 90))
        soft.putpixel((32, y), (200, 195, 190, 40))
    hard = _harden_cutout_alpha_after_resize(soft.resize((80, 160), Image.Resampling.LANCZOS))
    hp = hard.load()
    soft_count = sum(
        1
        for y in range(hard.height)
        for x in range(hard.width)
        if 1 <= hp[x, y][3] < 200
    )
    assert soft_count == 0, soft_count


def test_cutout_right_edge_not_wall_dominated(tmp_path):
    """Canonical-like cutout must not keep a thick opaque wall fringe on the right."""
    from PIL import Image, ImageDraw
    from agent.services.exact_product_compositor_service import _build_canonical_cutout

    im = Image.new("RGB", (240, 480), (235, 232, 226))  # wall
    d = ImageDraw.Draw(im)
    d.rectangle((95, 25, 145, 70), fill=(200, 30, 30))  # cap
    d.rectangle((80, 85, 160, 400), fill=(40, 130, 140))  # teal
    d.rectangle((100, 130, 140, 260), fill=(205, 197, 173))  # cream
    d.rectangle((90, 290, 150, 380), fill=(30, 140, 70))  # liquid
    src = tmp_path / "c.jpg"
    im.save(src, quality=95)
    cut = _build_canonical_cutout(src)
    px = cut.load()
    w, h = cut.size
    # measure rightmost opaque x per row; band of wall color just inside edge
    wallish = 0
    rows = 0
    for y in range(int(h * 0.25), int(h * 0.85)):
        right = None
        for x in range(w - 1, -1, -1):
            if px[x, y][3] >= 200:
                right = x
                break
        if right is None:
            continue
        rows += 1
        for k in range(0, 3):
            x = right - k
            if x < 0:
                continue
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            mx, mn = max(r, g, b), min(r, g, b)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            # wall-like AND not teal/red/green/cream product
            if lum >= 160 and (mx - mn) <= 40 and not (g >= 70 and b >= 70 and (g + b) / 2 >= r + 12):
                wallish += 1
    assert rows > 20
    # allow tiny AA residue but not thick dirty fringe
    assert wallish < max(12, rows // 3), f"wallish={wallish} rows={rows}"

def test_bridge_cap_to_body_reconnects_floating_cap():
    from PIL import Image, ImageDraw
    from agent.services.exact_product_compositor_service import _bridge_cap_to_body
    im = Image.new("RGBA", (60, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((20, 5, 40, 25), fill=(200, 30, 30, 255))  # top cap
    d.rectangle((15, 70, 45, 150), fill=(40, 130, 140, 255))  # body with gap
    d.rectangle((22, 100, 38, 108), fill=(200, 40, 40, 255))  # red label text trap
    out = _bridge_cap_to_body(im)
    assert out.getpixel((30, 45))[3] >= 200
    # still one main vertical span from cap into body
    assert out.getpixel((30, 60))[3] >= 200

def test_trim_clears_warm_wall_fringe_on_right():
    from PIL import Image, ImageDraw
    from agent.services.exact_product_compositor_service import (
        _trim_background_edge_fringe,
        _keep_main_product_silhouette,
    )
    im = Image.new("RGBA", (80, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((20, 20, 55, 140), fill=(40, 130, 140, 255))  # bottle
    d.rectangle((55, 40, 70, 100), fill=(200, 195, 175, 255))  # warm wall fringe right
    out = _keep_main_product_silhouette(_trim_background_edge_fringe(im, passes=4))
    # wall fringe gone
    assert out.getpixel((62, 70))[3] < 128
    # bottle remains
    assert out.getpixel((35, 80))[3] >= 200

def test_solidify_neck_ignores_lower_red_label_ink():
    from PIL import Image, ImageDraw
    from agent.services.exact_product_compositor_service import _solidify_neck_band
    im = Image.new("RGBA", (80, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((25, 5, 55, 30), fill=(200, 30, 30, 255))  # cap
    d.rectangle((20, 80, 60, 180), fill=(40, 130, 140, 255))  # body
    d.rectangle((30, 120, 50, 130), fill=(200, 40, 40, 255))  # red label text
    out = _solidify_neck_band(im)
    # base of body must stay teal, not flooded with synthetic green fill
    assert out.getpixel((40, 170))[:3] == (40, 130, 140)


def test_mwcb_cutout_neck_and_right_edge_free_of_pink_wall_fringe():
    """MWCB canonical cutout must not contain pink studio wall pixels in neck or right edge."""
    from pathlib import Path
    from PIL import Image
    import numpy as np
    from agent.services.exact_product_compositor_service import prepare_layer

    canonical_src = Path(
        r"C:\Users\USER\Desktop\Claude Cowork Bosmax Agents- Images database\02-Product\02-Minyak Cap Burung\MWTCB.jpg"
    )
    if not canonical_src.exists():
        return
    pytest.skip("Legacy MWCB heuristic is not an approved Product Truth Lock fixture")
    product = {
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
        "product_schema_key": "MWCB_25ML_CAP_BURUNG",
    }
    layer = prepare_layer(
        product,
        {"x": 28.0, "y": 22.0, "w": 44.0, "h": 52.0},
        {"w": 1080, "h": 1920},
    )
    cutout_path = Path(layer["asset_ref"])
    assert cutout_path.exists()
    cut = Image.open(cutout_path)
    c_arr = np.array(cut)
    w, h = cut.size
    alpha = c_arr[:, :, 3]

    # Check for pink studio wall edge fringe (R >= 215, G >= 110, B >= 110, R - G >= 45 on silhouette boundary)
    pink_edge_wall_count = 0
    for y in range(h):
        xs = np.where(alpha[y, :] >= 200)[0]
        if len(xs) == 0:
            continue
        for x in xs:
            dist = min(x - xs[0], xs[-1] - x)
            if dist > 2:
                continue
            r, g, b = c_arr[y, x][:3]
            if r >= 215 and g >= 110 and b >= 110 and (int(r) - int(g)) >= 45:
                pink_edge_wall_count += 1

    assert pink_edge_wall_count <= 5, f"Found {pink_edge_wall_count} pink wall fringe pixels on cutout edge"
