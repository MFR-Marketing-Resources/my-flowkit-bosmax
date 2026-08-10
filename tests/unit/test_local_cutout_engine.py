"""Focused tests for the local BiRefNet ONNX cutout engine and its authority
integration. None of these load the real 214 MB model or require onnxruntime/
numpy: dependency + model states are simulated, and the inference step is a
mockable seam. The canonical DB is never touched (conftest reroutes to a temp
per-PID DB under pytest).
"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from agent.db import crud
from agent.services import local_cutout_engine as engine
from agent.services import product_visual_onboarding_service as service


@pytest.fixture(autouse=True)
def _reset_engine_state():
    engine._sha_verified.clear()
    engine.reset_session_for_tests()
    yield
    engine._sha_verified.clear()
    engine.reset_session_for_tests()


# ─── helpers ─────────────────────────────────────────────────
def _source_rgb(w=200, h=300):
    img = Image.new("RGB", (w, h), (235, 238, 242))
    ImageDraw.Draw(img).rounded_rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], radius=12, fill=(200, 40, 40))
    return img


def _ellipse_mask(w=200, h=300):
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=255)
    return mask


def _rgba_cutout_bytes(w=24, h=24):
    rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(w // 4, 3 * w // 4):
        for y in range(h // 4, 3 * h // 4):
            rgba.putpixel((x, y), (30, 120, 150, 255))
    buf = BytesIO()
    rgba.save(buf, format="PNG")
    return buf.getvalue()


def _deps_ok(monkeypatch):
    monkeypatch.setattr(engine, "_import_backends", lambda: (object(), object()))


def _stage_cache(monkeypatch, tmp_path, *, write=True):
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CUTOUT_MODEL_CACHE_DIR", str(cache))
    path = cache / engine.MODEL_FILENAME
    if write:
        path.write_bytes(b"not-the-real-model")
    return path


# ─── DEPENDENCY / MODEL readiness (fail-closed) ──────────────
def test_readiness_dependency_missing(monkeypatch, tmp_path):
    def _raise():
        raise ImportError("onnxruntime not installed")

    monkeypatch.setattr(engine, "_import_backends", _raise)
    _stage_cache(monkeypatch, tmp_path)
    state = engine.readiness()
    assert state["state"] == engine.EngineReadiness.DEPENDENCY_MISSING.value
    assert engine.is_ready() is False


def test_readiness_model_missing(monkeypatch, tmp_path):
    _deps_ok(monkeypatch)
    _stage_cache(monkeypatch, tmp_path, write=False)
    assert engine.readiness()["state"] == engine.EngineReadiness.MODEL_MISSING.value


def test_readiness_model_invalid_on_checksum_mismatch(monkeypatch, tmp_path):
    _deps_ok(monkeypatch)
    _stage_cache(monkeypatch, tmp_path, write=True)  # wrong content => wrong SHA
    state = engine.readiness()
    assert state["state"] == engine.EngineReadiness.MODEL_INVALID.value
    assert state["actual_sha256"] != engine.MODEL_SHA256


def test_readiness_ready_when_valid_cached(monkeypatch, tmp_path):
    _deps_ok(monkeypatch)
    _stage_cache(monkeypatch, tmp_path, write=True)
    monkeypatch.setattr(engine, "_sha256_file", lambda _p: engine.MODEL_SHA256)
    assert engine.readiness()["state"] == engine.EngineReadiness.READY.value
    assert engine.is_ready() is True


def test_ensure_model_available_rejects_mismatch_without_download(monkeypatch, tmp_path):
    _deps_ok(monkeypatch)
    _stage_cache(monkeypatch, tmp_path, write=True)
    result = engine.ensure_model_available(download=False)
    assert result["state"] == engine.EngineReadiness.MODEL_INVALID.value


def test_ensure_model_available_missing_without_download(monkeypatch, tmp_path):
    _deps_ok(monkeypatch)
    _stage_cache(monkeypatch, tmp_path, write=False)
    result = engine.ensure_model_available(download=False)
    assert result["state"] == engine.EngineReadiness.MODEL_MISSING.value


# ─── same-canvas + alpha + quality (pure Pillow; no model needed) ────────────
def test_build_result_simple_cutout_ok():
    result = engine.build_result_from_mask(_source_rgb(), _ellipse_mask(), source_sha256="abc")
    assert result.ok() and result.failure_code is None
    assert result.quality_status == engine.QUALITY_OK
    assert (result.output_width, result.output_height) == (200, 300)
    assert result.transparent_pixels > 0 and result.opaque_pixels > 0
    assert result.output_bytes is not None and result.output_sha256
    with Image.open(BytesIO(result.output_bytes)) as decoded:
        assert decoded.format == "PNG"
        assert decoded.mode == "RGBA"
        assert decoded.size == (200, 300)


def test_same_canvas_reconstructs_odd_dimensions():
    src = _source_rgb(137, 211)
    off_size_mask = _ellipse_mask(64, 64)  # deliberately wrong size (valid cutout)
    result = engine.build_result_from_mask(src, off_size_mask, source_sha256="x")
    # source dimensions preserved exactly, never cropped or ratio-changed
    assert result.ok()
    assert (result.output_width, result.output_height) == (137, 211)
    with Image.open(BytesIO(result.output_bytes)) as decoded:
        assert decoded.size == (137, 211)


def test_all_opaque_rejected():
    result = engine.build_result_from_mask(_source_rgb(), Image.new("L", (200, 300), 255), source_sha256="x")
    assert result.failure_code == engine.FAIL_ALL_OPAQUE
    assert result.output_bytes is None


def test_all_transparent_rejected():
    result = engine.build_result_from_mask(_source_rgb(), Image.new("L", (200, 300), 0), source_sha256="x")
    assert result.failure_code == engine.FAIL_ALL_TRANSPARENT
    assert result.output_bytes is None


def test_foreground_too_small_rejected():
    mask = Image.new("L", (200, 300), 0)
    for x in range(3):
        for y in range(3):
            mask.putpixel((x, y), 255)
    result = engine.build_result_from_mask(_source_rgb(), mask, source_sha256="x")
    assert result.failure_code == engine.FAIL_FOREGROUND_TOO_SMALL


def test_foreground_too_large_rejected():
    mask = Image.new("L", (200, 300), 255)
    for x in range(10):
        for y in range(10):
            mask.putpixel((x, y), 0)  # a few transparent pixels only
    result = engine.build_result_from_mask(_source_rgb(), mask, source_sha256="x")
    assert result.failure_code == engine.FAIL_FOREGROUND_TOO_LARGE


def test_validate_rejects_rgb_only():
    buf = BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="PNG")
    checks = engine._validate_alpha_and_quality(buf.getvalue(), (32, 32))
    assert checks["failure_code"] == engine.FAIL_NO_ALPHA


def test_validate_rejects_wrong_dimensions():
    checks = engine._validate_alpha_and_quality(_rgba_cutout_bytes(24, 24), (99, 99))
    assert checks["failure_code"] == engine.FAIL_DIMENSION_MISMATCH


# ─── prepare() end-to-end with a mocked inference seam ───────────────────────
def test_prepare_returns_failure_when_not_ready(monkeypatch):
    monkeypatch.setattr(
        engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.MODEL_MISSING.value}
    )
    result = engine.prepare(_rgba_cutout_bytes(24, 24))
    assert result.failure_code == engine.EngineReadiness.MODEL_MISSING.value
    assert result.output_bytes is None


def test_prepare_end_to_end_with_mock_inference(monkeypatch):
    monkeypatch.setattr(engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.READY.value})
    monkeypatch.setattr(engine, "_infer_mask", lambda rgb: _ellipse_mask(*rgb.size))
    buf = BytesIO()
    _source_rgb(160, 240).save(buf, format="PNG")
    raw = buf.getvalue()

    result = engine.prepare(raw)

    assert result.ok()
    assert result.source_sha256 == engine._sha256_bytes(raw)
    assert (result.output_width, result.output_height) == (160, 240)
    assert result.output_sha256 and result.transparent_pixels > 0


# ─── dispatch policy (_run_auto_cutout) ──────────────────────
@pytest.mark.asyncio
async def test_dispatch_flag_off_uses_compositor(monkeypatch):
    monkeypatch.setattr(service.config, "LOCAL_CUTOUT_ENGINE_ENABLED", False)

    async def fake_compositor(_path):
        return b"det", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5}, "sha", 0.01

    monkeypatch.setattr(service, "_run_cutout_compositor", fake_compositor)
    _raw, _bounds, _sha, _sec, used = await service._run_auto_cutout("src.png")
    assert used == "deterministic-compositor"


@pytest.mark.asyncio
async def test_dispatch_flag_on_uses_local(monkeypatch):
    monkeypatch.setattr(service.config, "LOCAL_CUTOUT_ENGINE_ENABLED", True)
    monkeypatch.setattr(
        service,
        "_build_local_cutout_bytes",
        lambda _p: (b"local", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5}, "lsha"),
    )
    _raw, _bounds, _sha, _sec, used = await service._run_auto_cutout("src.png")
    assert used == "local-birefnet-onnx"


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_local_fails(monkeypatch):
    monkeypatch.setattr(service.config, "LOCAL_CUTOUT_ENGINE_ENABLED", True)

    def _boom(_p):
        raise service.ProductVisualOnboardingError("LOCAL_CUTOUT_ENGINE_UNAVAILABLE", "not ready")

    monkeypatch.setattr(service, "_build_local_cutout_bytes", _boom)

    async def fake_compositor(_path):
        return b"det", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5}, "sha", 0.01

    monkeypatch.setattr(service, "_run_cutout_compositor", fake_compositor)
    _raw, _bounds, _sha, _sec, used = await service._run_auto_cutout("src.png")
    assert used == "deterministic-compositor"


# ─── AUTHORITY: local engine -> AUTO candidate -> PENDING_REVIEW (no approval) ─
@pytest.mark.asyncio
async def test_local_prepare_creates_pending_review_auto_candidate(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)
    product = await crud.create_product(
        raw_product_title="Local Cutout Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    reference = SimpleNamespace(
        local_path=str(source),
        media_id=None,
        mime_type="image/png",
        sha256=service._sha256_bytes(source.read_bytes()),
        width=24,
        height=24,
        source_type="PRODUCT_ROW_LOCAL_PATH",
        provenance="TEST_LOCAL_SOURCE",
    )

    async def resolve(_product):
        return reference

    monkeypatch.setattr(service, "_resolve_source", resolve)
    monkeypatch.setattr(service.config, "LOCAL_CUTOUT_ENGINE_ENABLED", True)

    png = _rgba_cutout_bytes(24, 24)
    monkeypatch.setattr(
        service,
        "_build_local_cutout_bytes",
        lambda _p: (png, {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5}, service._sha256_bytes(png)),
    )

    captured = {}

    async def fake_register(*_a, **_k):
        return {"media_id": "cutout-media-local-1"}

    async def fake_create_pending(product_id, request, **kwargs):
        captured["request"] = request
        captured["kwargs"] = kwargs
        return {"review_status": "PENDING_REVIEW"}

    approvals = {"count": 0}

    async def fake_approve(*_a, **_k):
        approvals["count"] += 1

    monkeypatch.setattr(
        "agent.services.product_truth_lock_service.register_product_truth_cutout_media", fake_register
    )
    monkeypatch.setattr(
        "agent.services.product_truth_lock_service.create_pending_product_truth_lock", fake_create_pending
    )
    monkeypatch.setattr(
        "agent.services.product_truth_lock_service.approve_product_truth_lock", fake_approve, raising=False
    )

    readiness = await service.prepare_product_cutout(product["id"])

    # AUTO candidate landed in PENDING_REVIEW, never approved, no provider spend.
    assert readiness["cutout_status"] == "PENDING_REVIEW"
    assert readiness["provider_operations"] == 0
    assert approvals["count"] == 0
    assert captured["kwargs"]["source_kind"] == service.AUTO_GENERATED
    assert captured["kwargs"]["uploaded_by"] == "system:local-cutout-engine"
    assert captured["kwargs"]["original_filename"].startswith("local-cutout-")
    assert captured["request"].created_by == "system:local-cutout-engine"
    receipt = await crud.get_product_cutout_preparation(product["id"])
    assert receipt["status"] == "PENDING_REVIEW"


# ─── REGRESSION: default is off; deterministic seam unchanged ────────────────
def test_local_engine_default_disabled():
    # The real config value must default OFF so this PR changes no production
    # behavior until the owner opts in.
    import agent.config as real_config

    assert real_config.LOCAL_CUTOUT_ENGINE_ENABLED is False


def test_engine_module_imports_and_fails_closed_without_ml_deps(monkeypatch):
    # Importing/using the engine without onnxruntime must degrade gracefully to a
    # readiness state, never crash the app that merely imports the service.
    def _raise():
        raise ImportError("no onnxruntime in base runtime")

    monkeypatch.setattr(engine, "_import_backends", _raise)
    assert engine.readiness()["state"] == engine.EngineReadiness.DEPENDENCY_MISSING.value


# ─── MODEL REGISTRY / low-memory selection ───────────────────
def test_default_model_is_u2net_low_memory():
    spec = engine.selected_model()
    assert spec.model_id == "u2net"
    assert spec.family == "u2net"
    assert spec.input_size == 320
    assert engine.DEFAULT_MODEL_ID == "u2net"
    assert engine.MODEL_ID == "u2net"


def test_model_switch_via_env_changes_selection_and_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CUTOUT_MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CUTOUT_MODEL_ID", "birefnet-general-lite")
    spec = engine.selected_model()
    assert spec.model_id == "birefnet-general-lite"
    assert spec.family == "birefnet" and spec.input_size == 1024
    assert engine.model_path().name == "birefnet-general-lite.onnx"


def test_unknown_model_id_falls_back_to_default_safely(monkeypatch):
    monkeypatch.setenv("CUTOUT_MODEL_ID", "does-not-exist")
    assert engine.selected_model().model_id == engine.DEFAULT_MODEL_ID


def test_all_registry_models_are_commercially_licensed():
    for spec in engine.MODEL_REGISTRY.values():
        assert any(tok in spec.license for tok in ("Apache", "MIT", "BSD")), (spec.model_id, spec.license)


def test_readiness_reports_selected_model_and_available_ids(monkeypatch, tmp_path):
    _deps_ok(monkeypatch)
    _stage_cache(monkeypatch, tmp_path, write=False)  # MODEL_MISSING is fine; we inspect metadata
    state = engine.readiness()
    assert state["model_id"] == "u2net"
    assert state["input_size"] == 320
    assert "u2netp" in state["available_model_ids"] and "birefnet-general-lite" in state["available_model_ids"]
