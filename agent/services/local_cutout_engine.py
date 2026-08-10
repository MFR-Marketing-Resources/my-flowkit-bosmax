"""Local, CPU-only product cutout (background removal) engine.

This module owns **HOW** an AUTO product-cutout candidate's transparent PNG bytes
are prepared. It deliberately does **NOT** own **WHO** decides product truth: the
bytes it produces still flow through the existing
``product_visual_onboarding_service`` authority, land as an ``AUTO_GENERATED``
candidate in ``PENDING_REVIEW``, and require explicit human approval to become
canonical. Nothing here approves anything, and nothing here spends provider
credit (``provider_operations`` stays 0 — this engine never calls the paid
provider ledger).

Design:

* **No cloud / no paid provider / no rembg / no torch.** Inference is an ONNX
  foreground-segmentation model run directly through ``onnxruntime`` on CPU, with
  ``numpy`` + ``Pillow`` for pre/post-processing. ``rembg`` was evaluated only as
  the reference implementation for model artifacts + preprocessing; it is NOT a
  runtime dependency.
* **Low-memory by default.** The default model is **u2net** (320x320 input,
  ~0.45 GB peak RSS, ~1s CPU inference) so the engine is safe to activate on a
  16 GB workstation. Heavier / higher-fidelity models (u2netp, BiRefNet-general-
  lite) remain selectable via ``CUTOUT_MODEL_ID`` for beefier hosts. BiRefNet
  peaks ~5 GB and is NOT the default. The ONNX session also runs with the CPU
  memory arena + memory-pattern disabled (measured to cut peak RSS materially)
  — overridable via env.
* **Model artifact is never committed to Git.** Each model is downloaded once by
  an explicit preflight (:func:`ensure_model_available` /
  ``scripts/prepare_cutout_model.py``), validated by SHA-256, and cached under
  ``models/cutout/``.
* **Fail-closed model lifecycle.** Missing model -> ``MODEL_MISSING``; wrong
  checksum -> ``MODEL_INVALID``; broken session -> ``LOAD_FAILED``; missing deps
  -> ``DEPENDENCY_MISSING``. Inference NEVER silently downloads at request time
  and NEVER swaps in a mismatched model. Callers fall back to the deterministic
  compositor.
* **Same-canvas guarantee.** Output dimensions ALWAYS equal source dimensions
  exactly; the alpha mask is fitted back onto the untouched source canvas.
* **Bounded execution.** One reused session, single-flight (bounded concurrency
  = 1), configurable inference timeout.

Engine readiness states here are ENGINE states, distinct from Product Truth
lifecycle states. This module invents no Product Truth status vocabulary.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import threading
import time
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# ─── Engine identity ─────────────────────────────────────────
ENGINE_NAME = "local-onnx-cutout"

# BiRefNet / U2Net share the same normalization (ImageNet mean/std, scale-by-max).
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


# ─── Model registry (deterministic; weights NEVER committed to Git) ──────────
@dataclass(frozen=True)
class CutoutModelSpec:
    model_id: str
    variant: str
    family: str          # "u2net" (no external sigmoid) | "birefnet" (sigmoid)
    filename: str
    source_url: str
    sha256: str
    upstream_md5: str
    size_bytes: int
    input_size: int      # square side; the model's static ONNX input
    license: str


_REL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"

MODEL_REGISTRY: dict[str, CutoutModelSpec] = {
    # Default: low-memory, CPU-fast, commercial-licensed. ~0.45 GB peak.
    "u2net": CutoutModelSpec(
        model_id="u2net", variant="full", family="u2net", filename="u2net.onnx",
        source_url=_REL + "u2net.onnx",
        sha256="8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491",
        upstream_md5="60024c5c889badc19c04ad937298a77b",
        size_bytes=175997641, input_size=320, license="Apache-2.0 (xuebinqin/U-2-Net)",
    ),
    # Ultra-light alternative (~4.5 MB, ~0.3 GB peak); slightly lower fidelity.
    "u2netp": CutoutModelSpec(
        model_id="u2netp", variant="small", family="u2net", filename="u2netp.onnx",
        source_url=_REL + "u2netp.onnx",
        sha256="309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8",
        upstream_md5="8e83ca70e441ab06c318d82300c84806",
        size_bytes=4574861, input_size=320, license="Apache-2.0 (xuebinqin/U-2-Net)",
    ),
    # Higher-fidelity but heavy (~5 GB peak, 1024x1024 static). Beefy hosts only.
    "birefnet-general-lite": CutoutModelSpec(
        model_id="birefnet-general-lite", variant="general-lite", family="birefnet",
        filename="birefnet-general-lite.onnx",
        source_url=_REL + "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        sha256="5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333",
        upstream_md5="4fab47adc4ff364be1713e97b7e66334",
        size_bytes=224005088, input_size=1024, license="MIT (ZhengPeng7/BiRefNet)",
    ),
}

DEFAULT_MODEL_ID = "u2net"


def selected_model_id() -> str:
    return (os.environ.get("CUTOUT_MODEL_ID") or "").strip() or DEFAULT_MODEL_ID


def selected_model() -> CutoutModelSpec:
    return MODEL_REGISTRY.get(selected_model_id(), MODEL_REGISTRY[DEFAULT_MODEL_ID])


# Backward-compatible convenience constants describe the DEFAULT model. Runtime
# behavior always uses ``selected_model()`` so ``CUTOUT_MODEL_ID`` takes effect.
_DEFAULT_SPEC = MODEL_REGISTRY[DEFAULT_MODEL_ID]
MODEL_ID = _DEFAULT_SPEC.model_id
MODEL_VARIANT = _DEFAULT_SPEC.variant
MODEL_FILENAME = _DEFAULT_SPEC.filename
MODEL_SOURCE_URL = _DEFAULT_SPEC.source_url
MODEL_UPSTREAM_MD5 = _DEFAULT_SPEC.upstream_md5
MODEL_SHA256 = _DEFAULT_SPEC.sha256
MODEL_SIZE_BYTES = _DEFAULT_SPEC.size_bytes


class EngineReadiness(str, Enum):
    """ENGINE readiness — NOT a Product Truth candidate status."""

    READY = "READY"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    MODEL_MISSING = "MODEL_MISSING"
    MODEL_INVALID = "MODEL_INVALID"
    LOAD_FAILED = "LOAD_FAILED"


# ─── Quality / failure vocabulary (engine-local; not persisted as truth) ─────
QUALITY_OK = "OK"
FAIL_ENGINE_NOT_READY = "ENGINE_NOT_READY"
FAIL_SOURCE_UNREADABLE = "SOURCE_UNREADABLE"
FAIL_INFERENCE_ERROR = "INFERENCE_ERROR"
FAIL_INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
FAIL_OUTPUT_NOT_PNG = "OUTPUT_NOT_PNG"
FAIL_NO_ALPHA = "NO_ALPHA_CHANNEL"
FAIL_ALL_OPAQUE = "ALL_OPAQUE_NO_TRANSPARENCY"
FAIL_ALL_TRANSPARENT = "ALL_TRANSPARENT_NO_FOREGROUND"
FAIL_DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
FAIL_FOREGROUND_TOO_SMALL = "FOREGROUND_TOO_SMALL"
FAIL_FOREGROUND_TOO_LARGE = "FOREGROUND_TOO_LARGE"
FAIL_EMPTY_BBOX = "EMPTY_ALPHA_BBOX"


@dataclass
class LocalCutoutResult:
    """Narrow adapter result. Raw ML details never leak past this boundary."""

    engine: str
    model_id: str
    model_sha256: str
    source_sha256: str
    source_width: int
    source_height: int
    output_width: int
    output_height: int
    alpha_verified: bool
    transparent_pixels: int
    opaque_pixels: int
    semi_transparent_pixels: int
    quality_status: str
    failure_code: str | None
    output_bytes: bytes | None = None
    output_sha256: str | None = None
    foreground_ratio: float = 0.0
    inference_seconds: float = 0.0

    def ok(self) -> bool:
        return self.failure_code is None and self.quality_status == QUALITY_OK

    def summary(self) -> dict:
        data = asdict(self)
        data.pop("output_bytes", None)
        data["has_output"] = self.output_bytes is not None
        data["output_bytes_len"] = len(self.output_bytes) if self.output_bytes else 0
        return data


# ─── Tunables (env; conservative, measured defaults) ─────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip() == "1"


def _min_foreground_ratio() -> float:
    return _env_float("CUTOUT_MIN_FOREGROUND_RATIO", 0.005)


def _max_foreground_ratio() -> float:
    return _env_float("CUTOUT_MAX_FOREGROUND_RATIO", 0.995)


def _inference_timeout_seconds() -> float:
    return _env_float("CUTOUT_INFERENCE_TIMEOUT_SECONDS", 120.0)


def _ort_threads() -> int:
    return _env_int("CUTOUT_ORT_THREADS", 4)


# ─── Model cache location ────────────────────────────────────
def model_cache_dir() -> Path:
    override = os.environ.get("CUTOUT_MODEL_CACHE_DIR")
    if override:
        return Path(override)
    try:
        from agent.config import BASE_DIR

        return Path(BASE_DIR) / "models" / "cutout"
    except Exception:  # pragma: no cover
        return Path(__file__).resolve().parents[2] / "models" / "cutout"


def model_path(spec: CutoutModelSpec | None = None) -> Path:
    return model_cache_dir() / (spec or selected_model()).filename


# ─── Hashing ─────────────────────────────────────────────────
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ─── Backend imports (lazy; absence => DEPENDENCY_MISSING) ────────────────────
def _import_backends():
    import numpy  # noqa: PLC0415
    import onnxruntime  # noqa: PLC0415

    return numpy, onnxruntime


# ─── Readiness ───────────────────────────────────────────────
_sha_verified: set[str] = set()
_sha_verified_lock = threading.Lock()


def readiness(*, verify_checksum: bool = True) -> dict:
    """Return the engine readiness state for the SELECTED model (read-only)."""
    spec = selected_model()
    path = model_path(spec)
    detail: dict = {
        "engine": ENGINE_NAME,
        "model_id": spec.model_id,
        "requested_model_id": selected_model_id(),
        "model_variant": spec.variant,
        "model_family": spec.family,
        "model_filename": spec.filename,
        "model_path": str(path),
        "model_source": spec.source_url,
        "model_license": spec.license,
        "input_size": spec.input_size,
        "expected_sha256": spec.sha256,
        "expected_size_bytes": spec.size_bytes,
        "available_model_ids": sorted(MODEL_REGISTRY),
    }
    try:
        _import_backends()
    except Exception as exc:
        detail["reason"] = f"{type(exc).__name__}: {exc}"
        return {"state": EngineReadiness.DEPENDENCY_MISSING.value, **detail}

    if not path.exists() or not path.is_file():
        detail["reason"] = "Model artifact is not staged. Run scripts/prepare_cutout_model.py."
        return {"state": EngineReadiness.MODEL_MISSING.value, **detail}

    size = path.stat().st_size
    detail["actual_size_bytes"] = size
    if size == 0:
        detail["reason"] = "Model artifact is empty."
        return {"state": EngineReadiness.MODEL_MISSING.value, **detail}

    if verify_checksum and spec.model_id not in _sha_verified:
        actual = _sha256_file(path)
        detail["actual_sha256"] = actual
        if actual != spec.sha256:
            detail["reason"] = "Model checksum does not match the pinned SHA-256."
            return {"state": EngineReadiness.MODEL_INVALID.value, **detail}
        with _sha_verified_lock:
            _sha_verified.add(spec.model_id)

    return {"state": EngineReadiness.READY.value, **detail}


def is_ready(*, verify_checksum: bool = True) -> bool:
    return readiness(verify_checksum=verify_checksum)["state"] == EngineReadiness.READY.value


# ─── Model download / preflight (explicit; never at request time) ────────────
def ensure_model_available(*, download: bool = True) -> dict:
    """Ensure the SELECTED model exists in the cache, SHA-verified. A downloaded
    file that fails the SHA check is discarded (``MODEL_INVALID``), never used."""
    spec = selected_model()
    path = model_path(spec)
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        actual = _sha256_file(path)
        if actual == spec.sha256:
            with _sha_verified_lock:
                _sha_verified.add(spec.model_id)
            return readiness(verify_checksum=False)
        if not download:
            return {
                "state": EngineReadiness.MODEL_INVALID.value, "model_id": spec.model_id,
                "model_path": str(path), "actual_sha256": actual, "expected_sha256": spec.sha256,
                "reason": "Cached model checksum mismatch; refusing to use it.",
            }
        logger.warning("cutout model %s checksum mismatch; re-staging", spec.model_id)

    if not download:
        return readiness(verify_checksum=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    logger.info("staging cutout model %s %s -> %s", spec.model_id, spec.source_url, path)
    request = urllib.request.Request(spec.source_url, headers={"User-Agent": "bosmax-cutout-preflight/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out, length=1 << 20)

    actual = _sha256_file(tmp)
    if actual != spec.sha256:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {
            "state": EngineReadiness.MODEL_INVALID.value, "model_id": spec.model_id,
            "model_path": str(path), "actual_sha256": actual, "expected_sha256": spec.sha256,
            "reason": "Downloaded model failed SHA-256 verification; not installed.",
        }
    os.replace(tmp, path)
    with _sha_verified_lock:
        _sha_verified.add(spec.model_id)
    logger.info("cutout model %s staged and verified (%s bytes)", spec.model_id, path.stat().st_size)
    return readiness(verify_checksum=False)


# ─── Inference session (per-model singleton, reused, single-flight) ──────────
_sessions: dict[str, object] = {}
_session_lock = threading.Lock()
_infer_executor: ThreadPoolExecutor | None = None
_infer_executor_lock = threading.Lock()


def _build_session(spec: CutoutModelSpec):
    _, ort = _import_backends()
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Low-memory defaults (Phase-B tuned): disabling the CPU arena + mem-pattern
    # materially cuts peak RSS at a small latency cost. Overridable via env.
    opts.enable_cpu_mem_arena = _env_bool("CUTOUT_ORT_ENABLE_ARENA", False)
    opts.enable_mem_pattern = _env_bool("CUTOUT_ORT_ENABLE_MEM_PATTERN", False)
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    threads = _ort_threads()
    if threads > 0:
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(model_path(spec)), sess_options=opts, providers=["CPUExecutionProvider"])


def _get_session(spec: CutoutModelSpec):
    sess = _sessions.get(spec.model_id)
    if sess is None:
        with _session_lock:
            sess = _sessions.get(spec.model_id)
            if sess is None:
                sess = _build_session(spec)
                _sessions[spec.model_id] = sess
    return sess


def _get_infer_executor() -> ThreadPoolExecutor:
    global _infer_executor
    if _infer_executor is None:
        with _infer_executor_lock:
            if _infer_executor is None:
                _infer_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cutout-infer")
    return _infer_executor


def reset_session_for_tests() -> None:
    """Drop cached sessions (test hygiene only)."""
    with _session_lock:
        _sessions.clear()


def _preprocess(rgb_image: "Image.Image", spec: CutoutModelSpec):
    numpy, _ = _import_backends()
    size = (spec.input_size, spec.input_size)
    im = rgb_image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    arr = numpy.array(im).astype(numpy.float64)
    arr = arr / max(float(numpy.max(arr)), 1e-6)
    tmp = numpy.zeros((arr.shape[0], arr.shape[1], 3))
    for c in range(3):
        tmp[:, :, c] = (arr[:, :, c] - _IMAGENET_MEAN[c]) / _IMAGENET_STD[c]
    tmp = tmp.transpose((2, 0, 1))
    return numpy.expand_dims(tmp, 0).astype(numpy.float32)


def _postprocess(logits, source_size: tuple[int, int], spec: CutoutModelSpec) -> "Image.Image":
    numpy, _ = _import_backends()
    pred = logits[:, 0, :, :]
    if spec.family == "birefnet":  # BiRefNet emits logits; U2Net emits [0,1] already
        pred = 1.0 / (1.0 + numpy.exp(-pred))
    lo, hi = float(numpy.min(pred)), float(numpy.max(pred))
    pred = (pred - lo) / (hi - lo) if hi - lo > 1e-9 else numpy.zeros_like(pred)
    pred = numpy.squeeze(pred)
    mask = Image.fromarray((pred * 255).astype("uint8"), mode="L")
    return mask.resize(source_size, Image.Resampling.LANCZOS)


def _infer_mask(rgb_image: "Image.Image") -> "Image.Image":
    """Run the SELECTED ONNX model and return an ``L`` mask at the source size.
    Seam tests monkeypatch to avoid loading a real model."""
    spec = selected_model()
    session = _get_session(spec)
    input_name = session.get_inputs()[0].name
    tensor = _preprocess(rgb_image, spec)
    outputs = session.run(None, {input_name: tensor})
    return _postprocess(outputs[0], rgb_image.size, spec)


# ─── Same-canvas + alpha/quality validation (pure Pillow; numpy-free) ────────
def _restore_to_canvas(mask: "Image.Image", size: tuple[int, int]) -> "Image.Image":
    mask = mask.convert("L")
    if mask.size == size:
        return mask
    return mask.resize(size, Image.Resampling.LANCZOS)


def _validate_alpha_and_quality(png_bytes: bytes, expected_size: tuple[int, int]) -> dict:
    try:
        decoded = Image.open(io.BytesIO(png_bytes))
        decoded.load()
    except Exception:
        return {"quality_status": FAIL_OUTPUT_NOT_PNG, "failure_code": FAIL_OUTPUT_NOT_PNG}

    if (decoded.format or "").upper() != "PNG":
        return {"quality_status": FAIL_OUTPUT_NOT_PNG, "failure_code": FAIL_OUTPUT_NOT_PNG}
    if decoded.mode not in ("RGBA", "LA"):
        return {"quality_status": FAIL_NO_ALPHA, "failure_code": FAIL_NO_ALPHA}
    if decoded.size != expected_size:
        return {"quality_status": FAIL_DIMENSION_MISMATCH, "failure_code": FAIL_DIMENSION_MISMATCH}

    alpha = decoded.getchannel("A")
    amin, amax = alpha.getextrema()
    hist = alpha.histogram()
    transparent = int(hist[0])
    opaque = int(hist[255]) if len(hist) > 255 else 0
    semi = int(sum(hist[1:255]))
    foreground = opaque + semi
    total = expected_size[0] * expected_size[1]

    base = {
        "transparent_pixels": transparent, "opaque_pixels": opaque, "semi_transparent_pixels": semi,
        "foreground_ratio": (foreground / total) if total else 0.0, "alpha_min": amin, "alpha_max": amax,
    }
    if amax <= 0 or foreground <= 0:
        return {**base, "quality_status": FAIL_ALL_TRANSPARENT, "failure_code": FAIL_ALL_TRANSPARENT}
    if amin >= 255 or transparent <= 0:
        return {**base, "quality_status": FAIL_ALL_OPAQUE, "failure_code": FAIL_ALL_OPAQUE}
    if alpha.getbbox() is None:
        return {**base, "quality_status": FAIL_EMPTY_BBOX, "failure_code": FAIL_EMPTY_BBOX}

    ratio = foreground / total if total else 0.0
    if ratio < _min_foreground_ratio():
        return {**base, "quality_status": FAIL_FOREGROUND_TOO_SMALL, "failure_code": FAIL_FOREGROUND_TOO_SMALL}
    if ratio > _max_foreground_ratio():
        return {**base, "quality_status": FAIL_FOREGROUND_TOO_LARGE, "failure_code": FAIL_FOREGROUND_TOO_LARGE}
    return {**base, "quality_status": QUALITY_OK, "failure_code": None}


def build_result_from_mask(
    source_rgb: "Image.Image", mask: "Image.Image", *, source_sha256: str, inference_seconds: float = 0.0,
) -> LocalCutoutResult:
    """Compose RGBA (same-canvas), encode PNG, validate — pure and testable."""
    spec = selected_model()
    source_rgb = source_rgb.convert("RGB")
    sw, sh = source_rgb.size
    canvas_mask = _restore_to_canvas(mask, (sw, sh))
    rgba = source_rgb.convert("RGBA")
    rgba.putalpha(canvas_mask)

    ow, oh = rgba.size
    buffer = io.BytesIO()
    rgba.save(buffer, format="PNG")
    out_bytes = buffer.getvalue()

    checks = _validate_alpha_and_quality(out_bytes, (sw, sh))
    passed = checks.get("failure_code") is None
    return LocalCutoutResult(
        engine=ENGINE_NAME, model_id=spec.model_id, model_sha256=spec.sha256, source_sha256=source_sha256,
        source_width=sw, source_height=sh, output_width=ow, output_height=oh, alpha_verified=passed,
        transparent_pixels=int(checks.get("transparent_pixels", 0)),
        opaque_pixels=int(checks.get("opaque_pixels", 0)),
        semi_transparent_pixels=int(checks.get("semi_transparent_pixels", 0)),
        quality_status=checks.get("quality_status", QUALITY_OK), failure_code=checks.get("failure_code"),
        output_bytes=out_bytes if passed else None,
        output_sha256=_sha256_bytes(out_bytes) if passed else None,
        foreground_ratio=float(checks.get("foreground_ratio", 0.0)), inference_seconds=inference_seconds,
    )


def _failed_result(*, failure_code: str, source_sha256: str, source_size: tuple[int, int] | None = None) -> LocalCutoutResult:
    spec = selected_model()
    sw, sh = source_size or (0, 0)
    return LocalCutoutResult(
        engine=ENGINE_NAME, model_id=spec.model_id, model_sha256=spec.sha256, source_sha256=source_sha256,
        source_width=sw, source_height=sh, output_width=0, output_height=0, alpha_verified=False,
        transparent_pixels=0, opaque_pixels=0, semi_transparent_pixels=0,
        quality_status=failure_code, failure_code=failure_code,
    )


def prepare(source, *, source_sha256: str | None = None) -> LocalCutoutResult:
    """Prepare a same-canvas transparent PNG cutout from a source image.

    ``source`` may be raw image bytes, a path string, or a ``Path``. Always
    returns a :class:`LocalCutoutResult`; never raises for expected failures.
    """
    try:
        if isinstance(source, (bytes, bytearray)):
            raw = bytes(source)
        else:
            raw = Path(source).read_bytes()
        src_image = Image.open(io.BytesIO(raw))
        src_image.load()
        src_rgb = src_image.convert("RGB")
    except Exception as exc:
        logger.warning("cutout source unreadable: %s", exc)
        return _failed_result(failure_code=FAIL_SOURCE_UNREADABLE, source_sha256=source_sha256 or "")
    ssha = source_sha256 or _sha256_bytes(raw)
    source_size = src_rgb.size

    state = readiness()
    if state["state"] != EngineReadiness.READY.value:
        return _failed_result(failure_code=state["state"], source_sha256=ssha, source_size=source_size)

    started = time.perf_counter()
    future: Future = _get_infer_executor().submit(_infer_mask, src_rgb)
    try:
        mask = future.result(timeout=_inference_timeout_seconds())
    except FutureTimeoutError:
        logger.error("cutout inference exceeded timeout")
        return _failed_result(failure_code=FAIL_INFERENCE_TIMEOUT, source_sha256=ssha, source_size=source_size)
    except Exception as exc:
        logger.exception("cutout inference failed: %s", exc)
        code = EngineReadiness.LOAD_FAILED.value if not _sessions else FAIL_INFERENCE_ERROR
        return _failed_result(failure_code=code, source_sha256=ssha, source_size=source_size)
    inference_seconds = time.perf_counter() - started

    return build_result_from_mask(src_rgb, mask, source_sha256=ssha, inference_seconds=inference_seconds)
