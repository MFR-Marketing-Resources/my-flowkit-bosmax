"""Production Queue — executes APPROVED prompt packages through the one
hardened generate lane (ADR-007) with interval + cooldown throttling.

Prompt/production split: the Prompt Queue (workspace_generation_package)
stores polished prompts; NOTHING here runs until a package is explicitly
APPROVED and sent to a production run. Live execution burns Google Flow
credits, so it is fail-closed twice:

  1. every run is created dry_run=1 — dry runs only validate payload mapping;
  2. a live run additionally requires confirm_live_credit_burn=true.

Item lifecycle (workspace_generation_package.production_status):
  NONE → APPROVED → QUEUED → RUNNING → GENERATED → DOWNLOADED
                                     ↘ FAILED / CANCELLED
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import uuid

from agent.db import crud
from agent.services import batch_prompt_planner as planner

logger = logging.getLogger(__name__)

PRODUCTION_STATUSES = (
    "NONE", "APPROVED", "QUEUED", "RUNNING",
    "GENERATED", "DOWNLOADED", "FAILED", "CANCELLED",
)

# Flow media ids are bare UUIDs — composite BOSMAX asset ids are NOT
# (mirrors the manual-lane _FLOW_MEDIA_UUID_RE gate; locked contract).
_FLOW_MEDIA_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# run_id → "PAUSE" | "CANCEL" control signals for the live loop
_run_control: dict[str, str] = {}
# O4: dedupe keys of submissions currently in flight. In-process by design — it
# guards the single provider boundary inside this worker, like _run_control above.
_inflight_dedupe: set[str] = set()

_POLL_SECONDS = 5
_JOB_TIMEOUT_SECONDS = 30 * 60
_INFLIGHT_RETRY_SECONDS = 30

# Round F — the one-serial T2V live lane.
#
# This gate is OPT-IN: it applies only when a caller asks for the
# LIVE_GATE_ONE_SERIAL_T2V lane. The pre-existing live path (ProductionQueuePage)
# is a protected system (G0 §3) and keeps its own semantics untouched — widening
# this gate to cover it would be a separate owner decision, not a Round F change.
LIVE_GATE_ONE_SERIAL_T2V = "ONE_SERIAL_T2V"
LIVE_CONFIRM_PHRASE = "AUTHORIZE_ONE_T2V_LIVE_RUN"

# Round F (Option 2) — the one-serial FIRST-FRAME live lane (F2V and HYBRID —
# both fire the live-proven first-frame engine: generate_video_with_first_frame /
# veo_3_1_i2v_lite). Same opt-in contract as the T2V lane above: it applies ONLY
# when a caller asks for LIVE_GATE_ONE_SERIAL_F2V with the DISTINCT phrase, so a
# T2V confirmation can never authorize a first-frame fire and vice-versa. The
# ungated ProductionQueuePage bulk path (G0 §3) stays strictly T2V-only — this
# lane does NOT widen it. A gated pass records authorized_live_mode=<validated
# mode> (F2V or HYBRID, exactly as validated) into the run config so the live
# loop (a second, universal chokepoint) allows exactly that one pre-validated
# item; every other run leaves the flag absent and the loop defaults fail-closed
# to T2V-only.
LIVE_GATE_ONE_SERIAL_F2V = "ONE_SERIAL_F2V"
LIVE_F2V_CONFIRM_PHRASE = "AUTHORIZE_ONE_F2V_LIVE_RUN"

# The one-serial I2V (ingredients/references) live lane. Same opt-in contract,
# DISTINCT phrase. I2V fires generate_video_with_references / veo_3_1_r2v_lite —
# the exact tool+model HYBRID live-proved (g_8845373fbb86) — so the tool-name
# discovery risk is already retired; this lane's residual risk is only the
# ordinary generation quality/binding, guarded by the same deterministic
# correlation. Mode-exact authorization like the first-frame lane.
LIVE_GATE_ONE_SERIAL_I2V = "ONE_SERIAL_I2V"
LIVE_I2V_CONFIRM_PHRASE = "AUTHORIZE_ONE_I2V_LIVE_RUN"

# ── Stage 2A: BULK FAN-OUT gate (N>1 itemized live run) ──────────────────────
# The N-item fan-out MECHANISM already exists (send_to_production takes a LIST of
# package_ids; the live loop iterates every QUEUED item). What did not exist is a
# GATE for it: the three one-serial gates are opt-in, so a caller could reach the
# loop with N items by passing confirm_live_credit_burn=True and NO live_gate —
# no phrase, no readiness, no preview correlation. This gate is the missing
# fail-closed door for the itemized bulk lane.
#
# Its phrase is DISTINCT from every single-run phrase, so a single-run
# authorization can never be replayed as a bulk authorization.
LIVE_GATE_BULK_FANOUT = "BULK_FANOUT"
LIVE_BULK_CONFIRM_PHRASE = "AUTHORIZE_BULK_FANOUT_LIVE_RUN"

# STAGE 3 CREDIT BOUNDARY. Every gate condition above is validated first, then
# execution stops HERE unless bulk live has been runtime-certified. Stage 2A
# ships the validated contract; it deliberately does NOT make credit spend
# reachable, because bulk live fan-out has never been proven against the
# provider. Flipping this without that runtime proof is a credit-safety
# regression, not a feature flag.
BULK_LIVE_EXECUTION_CERTIFIED = False

_TRUTHY = ("1", "true", "yes", "on")


def bulk_live_execution_certified() -> bool:
    """Is bulk live fan-out certified for THIS runtime?

    Certification used to be a source edit: flip the constant to True, restart,
    fire, then remember to revert. That procedure is fragile — a forgotten revert
    silently leaves the credit boundary open in every future run, and it cannot be
    granted per-machine. The owner now grants it at runtime instead:

        BULK_LIVE_EXECUTION_CERTIFIED=1   (.env, then restart the agent)

    The compiled-in default stays False, so a checkout is never certified by
    accident and the contract tests that assert the constant keep passing. The
    constant is still honoured first, which keeps monkeypatch-based tests working.

    Granting this does NOT spend a credit by itself. The operator still has to
    type the exact BULK_FANOUT confirm phrase and press Fire; this only stops the
    server refusing that request outright.
    """
    if BULK_LIVE_EXECUTION_CERTIFIED:
        return True
    return os.environ.get("BULK_LIVE_EXECUTION_CERTIFIED", "0").strip().lower() in _TRUTHY

_INFLIGHT_MAX_RETRIES = 20


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _loads(raw, default):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else default
    except Exception:
        return default


# ── Approval ──────────────────────────────────────────────────────────────


async def approve_packages(package_ids: list[str]) -> dict:
    """Prompt-side approval gate: READY_MANUAL packages become APPROVED
    (production_status). Blocked/draft/archived packages are refused."""
    results = []
    approved = 0
    for wgp_id in package_ids:
        row = await crud.get_workspace_generation_package(wgp_id)
        if not row:
            results.append({"package_id": wgp_id, "ok": False, "error": "NOT_FOUND"})
            continue
        if row.get("status") not in ("READY_MANUAL", "READY_DOM_STAGED"):
            results.append({
                "package_id": wgp_id, "ok": False,
                "error": f"NOT_APPROVABLE_STATUS:{row.get('status')}",
            })
            continue
        current = row.get("production_status") or "NONE"
        if current not in ("NONE", "", "CANCELLED", "FAILED"):
            results.append({
                "package_id": wgp_id, "ok": False,
                "error": f"ALREADY_IN_PRODUCTION:{current}",
            })
            continue
        await crud.update_workspace_generation_package(
            wgp_id, production_status="APPROVED", approved_at=_now(), production_error=None,
        )
        approved += 1
        results.append({"package_id": wgp_id, "ok": True, "production_status": "APPROVED"})
    return {"approved": approved, "results": results}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Enqueue ───────────────────────────────────────────────────────────────


async def send_to_production(
    package_ids: list[str],
    *,
    interval_min_seconds: int = 45,
    interval_max_seconds: int = 120,
    cooldown_after_n_jobs: int = 5,
    cooldown_seconds: int = 300,
    aspect: str = "9:16",
    model: str | None = None,
    count: int = 1,
) -> dict:
    """Create a production run from APPROVED packages and queue them.

    The run is created dry_run=1: nothing fires until run_production_queue is
    called, and live credit burn additionally needs explicit confirmation.
    """
    if not package_ids:
        raise ValueError("NO_PACKAGES_SELECTED")
    if interval_min_seconds < 0 or interval_max_seconds < interval_min_seconds:
        raise ValueError("INVALID_INTERVAL_RANGE")

    # Engine/model law: the operator must pick a model from the standard
    # registry (Omni Flash / Veo 3.1 Lite / Fast / Quality). No silent
    # defaulting, unknown model FAILS CLOSED (mirrors the generate lane).
    from agent.services import video_models as _vm
    if not str(model or "").strip():
        raise ValueError("MODEL_REQUIRED")
    try:
        resolved_model = _vm.resolve(model)
    except ValueError:
        raise ValueError(f"ERR_UNKNOWN_MODEL:{model}")

    eligible: list[dict] = []
    refused: list[dict] = []
    for wgp_id in package_ids:
        row = await crud.get_workspace_generation_package(wgp_id)
        if not row:
            refused.append({"package_id": wgp_id, "error": "NOT_FOUND"})
            continue
        if (row.get("production_status") or "NONE") != "APPROVED":
            refused.append({
                "package_id": wgp_id,
                "error": f"NOT_APPROVED:{row.get('production_status') or 'NONE'}",
            })
            continue
        eligible.append(row)
    if not eligible:
        raise ValueError("NO_APPROVED_PACKAGES:" + _json(refused))

    run_id = f"prun_{uuid.uuid4().hex[:16]}"
    config = {
        "package_ids": [r["workspace_generation_package_id"] for r in eligible],
        "aspect": aspect,
        "model": resolved_model["ui_label"],
        "model_key": resolved_model["key"],
        "count": max(1, min(4, int(count or 1))),
    }
    run = await crud.create_production_run(
        run_id,
        dry_run=True,
        max_parallel_jobs=1,
        interval_min_seconds=interval_min_seconds,
        interval_max_seconds=interval_max_seconds,
        cooldown_after_n_jobs=cooldown_after_n_jobs,
        cooldown_seconds=cooldown_seconds,
        total_expected=len(eligible),
        config_json=_json(config),
    )
    now = _now()
    for row in eligible:
        await crud.update_workspace_generation_package(
            row["workspace_generation_package_id"],
            production_status="QUEUED",
            production_run_id=run_id,
            sent_to_production_at=now,
        )
    run["refused"] = refused
    return run


# ── Payload mapping ───────────────────────────────────────────────────────


async def build_execution_payload(pkg: dict, run_config: dict | None = None) -> tuple[dict, list[str]]:
    """Map one prompt package to the one-door GenerateRequest payload.

    logical_mode is preserved on the package; only the engine payload maps
    HYBRID → F2V (product-anchor lane). Returns (payload, blockers) —
    non-empty blockers mean the item must NOT fire.
    """
    cfg = run_config or {}
    blockers: list[str] = []
    logical_mode = (pkg.get("logical_mode") or "").strip().upper()
    if not logical_mode:
        # Legacy packages: derive from stored mode/source_lane without relabelling.
        mode = (pkg.get("mode") or "").strip().upper()
        lane = (pkg.get("source_lane") or "").strip().upper()
        logical_mode = "HYBRID" if (mode == "F2V" and lane == "HYBRID") else mode
    engine_mode = planner.ENGINE_MODES.get(logical_mode)
    if not engine_mode:
        return {}, [f"UNSUPPORTED_LOGICAL_MODE:{logical_mode}"]
    # EXTEND packages are MULTI-BLOCK: firing one through this single-shot lane
    # would silently render ONE 8s block for a 16s+ request (truncation) and skip
    # the seam/concat pipeline entirely. Multi-block execution belongs to the
    # durable orchestrator lane (/api/flow/video-jobs plan→authorize→advance),
    # which runs the reviewed per-block 9-section prompts with their WPS word
    # budgets. Fail closed here — this lane is SINGLE-only. logical_mode is kept
    # in the refused payload so the loop reports THIS blocker, not a mode error.
    generation_mode = (pkg.get("generation_mode") or "SINGLE").strip().upper()
    if generation_mode == "EXTEND":
        total = pkg.get("requested_total_duration_seconds") or "?"
        return {"logical_mode": logical_mode}, [
            f"EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN:{total}s_USE_VIDEO_JOBS_ORCHESTRATOR"
        ]

    prompt = pkg.get("final_prompt_text") or ""
    if not prompt.strip():
        blockers.append("EMPTY_FINAL_PROMPT")

    # Resolve Flow media ids for image slots. Composite BOSMAX asset ids are
    # not Flow media ids — each slot must resolve to an uploaded UUID.
    image_media_ids: list[str] = []
    slots = _loads(pkg.get("resolved_engine_slots_json"), {})
    if engine_mode in ("F2V", "I2V") and isinstance(slots, dict):
        for slot_key, asset_ref in slots.items():
            if not asset_ref:
                continue
            media_id = await _resolve_flow_media_id(str(asset_ref), pkg)
            if media_id:
                image_media_ids.append(media_id)
            else:
                blockers.append(f"SLOT_NOT_UPLOADED_TO_FLOW:{slot_key}")
    # Dedupe (order-preserving): distinct slots can resolve to the SAME media —
    # live I2V wgp_99e9961ae1ac5413 carried subject + product_reference both
    # auto-seeded from the product image, and the duplicate pushed 3 real refs
    # to 4, tripping the door's I2V cap. A repeated id adds nothing.
    image_media_ids = list(dict.fromkeys(image_media_ids))
    if engine_mode in ("F2V", "I2V") and not image_media_ids:
        blockers.append("NO_FLOW_MEDIA_FOR_IMAGE_MODE")
    # Reference-count contract as a DRY-RUN blocker. The one door rejects a
    # violation synchronously at FIRE time (ERR_REFERENCE_COUNT_CONTRACT), but
    # nothing checked it at dry-run — the exact I2V fire above dry-ran GREEN and
    # then died at the door. Same authority, checked early, fail-closed.
    if engine_mode in ("T2V", "F2V", "I2V"):
        from agent.services import flow_mode_reference_contract as _refc
        _violation = _refc.service_hard_violation(engine_mode, len(image_media_ids))
        if _violation:
            blockers.append(f"REFERENCE_COUNT_CONTRACT:{_violation}")

    duration_s = None
    dom = _loads(pkg.get("dom_handoff_payload_json"), {})
    settings = dom.get("settings") if isinstance(dom, dict) else None
    if isinstance(settings, dict) and settings.get("duration_seconds"):
        try:
            duration_s = int(settings["duration_seconds"])
        except (TypeError, ValueError):
            duration_s = None

    # Model law at fire time: no silent Lite default, unknown model or a
    # duration the engine can't do in one shot FAILS CLOSED as a blocker
    # (mirrors the generate-door validation; USER SETTINGS ARE LAW).
    model = str(cfg.get("model") or "").strip()
    if not model:
        blockers.append("MODEL_REQUIRED")
    elif engine_mode in ("T2V", "I2V", "F2V"):
        from agent.services import video_models as _vm
        try:
            _vm.expected_cost(model, duration_s)
        except ValueError as exc:
            blockers.append(f"ENGINE_VALIDATION:{exc}")

    payload = {
        "mode": engine_mode,
        "prompt": prompt,
        "image_media_ids": image_media_ids or None,
        "aspect": cfg.get("aspect") or "9:16",
        "model": cfg.get("model"),
        "duration_s": duration_s,
        "num_videos": cfg.get("count") or 1,
        "logical_mode": logical_mode,
        "execution_lane": planner.EXECUTION_LANES.get(logical_mode, engine_mode),
    }
    return payload, blockers


async def _resolve_flow_media_id(asset_ref: str, pkg: dict) -> str | None:
    """asset_ref → Flow media UUID, or None when nothing is uploaded yet."""
    if _FLOW_MEDIA_UUID_RE.match(asset_ref):
        return asset_ref
    if asset_ref.startswith("product-image:"):
        product = await crud.get_product(pkg.get("product_id") or "")
        media_id = (product or {}).get("media_id") or ""
        return media_id if _FLOW_MEDIA_UUID_RE.match(media_id) else None
    try:
        asset = await crud.get_creative_asset(asset_ref)
    except Exception:
        asset = None
    media_id = (asset or {}).get("media_id") or ""
    return media_id if _FLOW_MEDIA_UUID_RE.match(media_id) else None


# ── Image-slot upload (dry-run pre-pass; CREDIT-FREE) ─────────────────────
#
# F2V/I2V/HYBRID need their reference image present in Flow as a real media
# UUID before build_execution_payload can resolve the slot. upload_image is an
# asset upload (api_request to /v1/flow/uploadImage) — NOT make_video.start_generate
# and NO Generate click — so this whole path spends ZERO credits. It is invoked
# ONLY from the dry-run pre-pass (_resolve_and_upload_image_slots), never from
# _resolve_flow_media_id / build_execution_payload, which stay pure reads on the
# fire path. There is no workspace_generation_package-keyed durable history
# primitive (crud stage-events are request_id-keyed and queue packages have no
# request_id), so upload evidence is a best-effort log, not a fabricated stage event.


async def _flow_media_is_live(client, media_id: str) -> bool:
    """True if an existing Flow media UUID still resolves (self-heal authority —
    never trust a stored id by pattern alone; mirrors the manual lane)."""
    try:
        check = await client.get_media(str(media_id))
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(check, dict) or check.get("error"):
        return False
    status = check.get("status")
    return status is None or (isinstance(status, int) and status < 400)


async def _upload_local_image(client, local_path: str | None) -> tuple[str | None, str | None]:
    """Upload an on-disk image to Flow → (media_uuid, None) or (None, blocker).
    Credit-free asset upload; never raises — failures become blocker strings."""
    import base64
    import mimetypes
    import os

    if not local_path or not os.path.exists(local_path):
        return None, "IMAGE_FILE_MISSING"
    try:
        raw = open(local_path, "rb").read()
    except Exception:  # noqa: BLE001
        return None, "IMAGE_FILE_UNREADABLE"
    if not raw:
        return None, "IMAGE_FILE_EMPTY"
    b64 = base64.b64encode(raw).decode()
    sha = hashlib.sha256(raw).hexdigest()
    mime = mimetypes.guess_type(local_path)[0] or "image/png"
    try:
        up = await client.upload_image(
            b64, mime_type=mime, project_id="", file_name=os.path.basename(local_path),
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"UPLOAD_FAILED:{str(exc)[:60]}"
    media_id = up.get("_mediaId") if isinstance(up, dict) else None
    if not media_id:
        return None, "UPLOAD_NO_MEDIA_ID"
    # Validate the returned id is a real Flow UUID BEFORE we persist it — never
    # stamp a non-UUID into product.media_id / asset_status=UPLOADED_TO_FLOW (the
    # pure-read _resolve_flow_media_id would reject it anyway, but don't write
    # garbage). Gives a precise blocker instead of a later generic one.
    if not _FLOW_MEDIA_UUID_RE.match(str(media_id)):
        return None, f"UPLOAD_BAD_MEDIA_ID:{str(media_id)[:40]}"
    # Best-effort asset-authority evidence (no queue-package stage-event primitive).
    logger.info(
        "queue image-slot upload: %s -> media_id=%s sha256=%s",
        os.path.basename(local_path), media_id, sha[:16],
    )
    return str(media_id), None


def _aspect_ratio_of(aspect: str | None) -> float | None:
    """'9:16' → 0.5625. None/garbage → None (gate off, never guessed)."""
    try:
        w, h = str(aspect or "").strip().split(":")
        wf, hf = float(w), float(h)
        return (wf / hf) if hf else None
    except Exception:  # noqa: BLE001
        return None


def _image_dimensions(local_path: str) -> tuple[int, int] | None:
    """(width, height) of a PNG/JPEG via PURE stdlib header parsing.

    Deliberately NOT Pillow: the aspect gate first shipped on PIL and was
    silently OFF in production — the runtime venv has no Pillow, so Image.open
    raised, the except returned None, and the exact live failure the gate exists
    for (4:5 catalog photo on a 9:16 run) sailed through ready=1 while every
    PIL-equipped test env passed. Header parsing works in ANY venv. Unknown
    format/corrupt header → None (cannot verify)."""
    import struct

    try:
        with open(local_path, "rb") as f:
            head = f.read(32)
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:3] == b"\xff\xd8\xff":  # JPEG: scan for a SOFn frame header
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    code = marker[1]
                    if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                        continue  # standalone markers, no length
                    seg = f.read(2)
                    if len(seg) < 2:
                        return None
                    (length,) = struct.unpack(">H", seg)
                    if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                        body = f.read(5)
                        if len(body) < 5:
                            return None
                        h, w = struct.unpack(">HH", body[1:5])
                        return int(w), int(h)
                    f.seek(length - 2, 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def _slot_image_aspect_blocker(local_path: str | None, aspect: str | None) -> str | None:
    """Fail-closed FRAMING gate for image slots (dry-run pre-pass only).

    The first live F2V fire (g_7b29b837c259) used the RAW 4:5 catalog product
    photo (1122x1402) as the start frame of a 9:16 run — the proven pipeline
    composes a clean frame at the TARGET aspect first (IMG lane). Wrong-aspect
    frames produce letterboxed/oversized renders, so block readiness when the
    slot's source image aspect differs from the run aspect by >3%. Only enforced
    when BOTH a run aspect and a readable local source image exist — a bare Flow
    UUID slot has no local file here and stays unverified (never guessed)."""
    target = _aspect_ratio_of(aspect)
    if target is None or not local_path:
        return None
    dims = _image_dimensions(local_path)
    if not dims:
        return None  # unreadable/unknown format surfaces as IMAGE_FILE_* later, not here
    w, h = dims
    if not h:
        return None
    actual = w / h
    if abs(actual - target) / target > 0.03:
        return (
            f"SLOT_ASPECT_MISMATCH:{w}x{h}({actual:.3f})_vs_{aspect}({target:.4f})"
            "_COMPOSE_A_TARGET_ASPECT_FRAME_FIRST"
        )
    return None


async def _upload_slot_to_flow_media(asset_ref: str, pkg: dict, client, aspect: str | None = None) -> tuple[str | None, str | None]:
    """Ensure one image slot has a LIVE Flow UUID, uploading the on-disk image and
    persisting the UUID if needed. Returns (media_id, None) or (None, blocker).
    Existing-UUID-first with liveness self-heal; persists so re-runs are idempotent."""
    # Slot value is already a Flow UUID — build_execution_payload resolves it;
    # only re-upload is impossible for a bare id, so trust liveness or fail.
    if _FLOW_MEDIA_UUID_RE.match(asset_ref):
        return (asset_ref, None) if await _flow_media_is_live(client, asset_ref) else (None, "MEDIA_DEAD")

    if asset_ref.startswith("product-image:"):
        product = await crud.get_product(pkg.get("product_id") or "") or {}
        # FRAMING gate BEFORE reuse-or-upload: a wrong-aspect source (raw catalog
        # photo on a 9:16 run) must never reach ready, even if a live Flow UUID
        # for it already exists.
        aspect_blk = _slot_image_aspect_blocker(product.get("local_image_path"), aspect)
        if aspect_blk:
            return None, aspect_blk
        existing = product.get("media_id") or ""
        if _FLOW_MEDIA_UUID_RE.match(existing) and await _flow_media_is_live(client, existing):
            return existing, None
        media_id, blk = await _upload_local_image(client, product.get("local_image_path"))
        if blk:
            return None, blk
        await crud.update_product(
            pkg.get("product_id") or "", media_id=media_id, asset_status="UPLOADED_TO_FLOW",
        )
        return media_id, None

    # Creative asset reference.
    try:
        asset = await crud.get_creative_asset(asset_ref)
    except Exception:  # noqa: BLE001
        asset = None
    asset = asset or {}
    aspect_blk = _slot_image_aspect_blocker(asset.get("local_file_path"), aspect)
    if aspect_blk:
        return None, aspect_blk
    existing = asset.get("media_id") or ""
    if _FLOW_MEDIA_UUID_RE.match(existing) and await _flow_media_is_live(client, existing):
        return existing, None
    media_id, blk = await _upload_local_image(client, asset.get("local_file_path"))
    if blk:
        return None, blk
    await crud.update_creative_asset(asset_ref, media_id=media_id)
    return media_id, None


async def _resolve_and_upload_image_slots(item: dict, cfg: dict) -> list[str]:
    """DRY-RUN PRE-PASS (side-effectful by design; never on the fire path).

    For an F2V/I2V/HYBRID item, upload each not-yet-live slot image to Flow and
    persist the UUID, so the subsequent build_execution_payload READ resolves the
    slot and the item reaches ready. Returns blocker strings for slots that could
    not be resolved (offline extension, missing file, dead media). T2V/IMG have no
    image slots and return [] before touching the Flow client — T2V dry-run is
    unaffected."""
    logical_mode = (item.get("logical_mode") or "").strip().upper()
    if not logical_mode:
        mode = (item.get("mode") or "").strip().upper()
        lane = (item.get("source_lane") or "").strip().upper()
        logical_mode = "HYBRID" if (mode == "F2V" and lane == "HYBRID") else mode
    engine_mode = planner.ENGINE_MODES.get(logical_mode)
    if engine_mode not in ("F2V", "I2V"):
        return []
    slots = _loads(item.get("resolved_engine_slots_json"), {})
    if not isinstance(slots, dict) or not slots:
        return []

    from agent.services.flow_client import get_flow_client
    client = get_flow_client()
    if not getattr(client, "connected", False):
        return ["EXTENSION_OFFLINE_FOR_UPLOAD"]

    blockers: list[str] = []
    run_aspect = str((cfg or {}).get("aspect") or "").strip() or None
    for slot_key, asset_ref in slots.items():
        if not asset_ref:
            continue
        # The FRAMING gate applies to output-frame slots only. I2V ingredient
        # references (subject/scene/style — identity sources, not frames) have
        # no output-aspect contract; forcing them to 9:16 would wrongly block
        # perfectly valid reference imagery.
        slot_aspect = run_aspect if str(slot_key) in ("start_frame", "end_frame") else None
        _media_id, blk = await _upload_slot_to_flow_media(
            str(asset_ref), item, client, aspect=slot_aspect,
        )
        if blk:
            blockers.append(f"SLOT_UPLOAD_FAILED:{slot_key}:{blk}")
    return blockers


# ── Run control ───────────────────────────────────────────────────────────


def pause_production_run(run_id: str) -> None:
    _run_control[run_id] = "PAUSE"


def cancel_production_run_signal(run_id: str) -> None:
    _run_control[run_id] = "CANCEL"


async def retry_failed_items(run_id: str) -> dict:
    """FAILED items in the run go back to QUEUED; the run returns to PENDING."""
    run = await crud.get_production_run(run_id)
    if not run:
        raise ValueError("RUN_NOT_FOUND")
    if run.get("status") == "RUNNING":
        raise ValueError("RUN_STILL_RUNNING")
    items = await crud.list_production_queue_packages(production_run_id=run_id)
    retried = 0
    for item in items:
        if item.get("production_status") == "FAILED":
            await crud.update_workspace_generation_package(
                item["workspace_generation_package_id"],
                production_status="QUEUED", production_error=None,
                # Explicit retry identity (O4): clearing the prior job id is what
                # authorises a second submission of this package. Without it the
                # duplicate guard in _fire_and_wait would refuse the retry.
                production_job_id=None,
            )
            retried += 1
    if retried:
        await crud.update_production_run(run_id, status="PENDING")
    return {"retried": retried}


# ── Execution ─────────────────────────────────────────────────────────────


async def _persist_generation_identity(wgp_id: str, job_id: str) -> dict:
    """Snapshot the provider identity of `job_id` onto its package, durably.

    Fail-soft: identity is evidence, not a gate — a snapshot error must never
    abort a submission that already spent credits. What it must never do is
    invent an anchor; absent anchors are recorded as absent.

    Merge-only (B-11): this snapshot used to build a fresh dict and overwrite
    generation_identity_json wholesale, destroying every key another writer had
    persisted — most damagingly the durable ``bulk_fanout_item`` pairing that
    bulk prepare's reuse branch needs, which turned every bulk re-prepare into a
    permanent BULK_REUSE_IDENTITY_MISSING 409. It now read-merges exactly like
    the terminal writer (_persist_binding_outcome) always has.
    """
    from agent.services import make_video

    identity: dict = {}
    try:
        job = make_video.get_job(job_id) or {}
        row = await crud.get_workspace_generation_package(wgp_id) or {}
        identity = _loads(row.get("generation_identity_json"), {}) or {}
        identity.update({
            "provider_job_id": job_id,
            "mode": job.get("mode"),
            "requested_model": job.get("model"),
            "num_videos": job.get("num_videos"),
            "project_id": (job.get("binding") or {}).get("project_id"),
            "flow_tab_id": (job.get("binding") or {}).get("flow_tab_id"),
            "anchors": job.get("generation_identity") or {},
            # The decisive field: False means NO retrieved media can ever be bound
            # to this run, so a later "not retrieved" is a capture gap, not a
            # retrieval bug (live g_e71cd329b524).
            "identity_captured": bool(job.get("identity_captured")),
            "gen_tool_matched": bool(job.get("gen_tool_matched")),
            "tools_seen": job.get("tools_seen") or [],
            # Present ONLY when identity capture failed: the raw approve stream,
            # so the missing generation toolName (or its absence) is recoverable
            # from this run's record instead of costing another live submission.
            "identity_gap_sse": job.get("identity_gap_sse"),
            "submitted_at": _now(),
        })
        await crud.update_workspace_generation_package(
            wgp_id, generation_identity_json=_json(identity),
        )
        if not identity["identity_captured"]:
            # NOT a verdict. This snapshot runs the instant start_generate returns a
            # job id, while _run_generate is still async and has not parsed the
            # approve stream — so anchors/tools/binding are EXPECTED to be empty here
            # and this branch fires on every healthy run. Emitting the final
            # OUTPUT_IDENTITY_NOT_CAPTURED verdict here (as it used to) produced a
            # false alarm ~1s after submit that misdiagnosed its own cause, blaming a
            # missing _GEN_TOOLS entry for a value that simply did not exist yet
            # (Stage 3B T2V g_ba62f180717c: tools_seen=[], project_id/flow_tab_id
            # null, identity_gap_sse null — 0.98s after fire). The real verdict is
            # emitted post-loop by _persist_binding_outcome, where anchors exist.
            logger.info(
                "IDENTITY_PENDING_EARLY_SNAPSHOT wgp=%s job=%s — anchors not parsed "
                "yet (expected at submit time); verdict deferred to the terminal "
                "binding-outcome read", wgp_id, job_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("identity snapshot failed wgp=%s job=%s: %s", wgp_id, job_id, exc)
    return identity


async def _persist_binding_outcome(wgp_id: str, job_id: str) -> None:
    """Record WHY binding succeeded or failed, durably, once the job is terminal.

    The submission snapshot says whether an output *could* be bound; this says
    what actually happened to the candidates. Without it the rejection evidence
    (which media were refused, and for which reason) lives only in make_video's
    in-memory _JOBS and is gone on restart — exactly the state that made
    g_e71cd329b524 impossible to adjudicate after the fact.

    Fail-soft and merge-only: never overwrite the submission anchors, never
    raise into a paid job.
    """
    from agent.services import make_video

    try:
        job = make_video.get_job(job_id) or {}
        row = await crud.get_workspace_generation_package(wgp_id) or {}
        identity = _loads(row.get("generation_identity_json"), {}) or {}
        # Refresh the anchors. The submission snapshot is taken the instant
        # start_generate returns a job id, but _run_generate is still async and has
        # not parsed the approve stream yet — so the submission row ALWAYS reads
        # identity_captured=false, even for a run that captured everything (live
        # g_b1ed597a9789). The terminal read is the first point the anchors exist.
        if job.get("generation_identity"):
            identity["anchors"] = job.get("generation_identity") or {}
            identity["identity_captured"] = bool(job.get("identity_captured"))
            identity["gen_tool_matched"] = bool(job.get("gen_tool_matched"))
            identity["tools_seen"] = job.get("tools_seen") or []
            identity["identity_gap_sse"] = job.get("identity_gap_sse")
        stats = job.get("correlation_stats") or {}
        identity["binding_outcome"] = {
            "job_status": job.get("status"),
            "bound_media_id": job.get("media_id"),
            "bound": bool(job.get("media_id")),
            # The acceptance receipt when bound: what it matched on and why
            # (make_video stores it as output_correlation).
            "evidence": job.get("output_correlation"),
            # The refusal receipt when not bound.
            "rejected_candidate_ids": list(stats.get("round_rejected_ids") or []),
            "unverifiable_ids": list(stats.get("unverifiable_ids") or []),
            "prompt_mismatched": stats.get("prompt_mismatched"),
            "model_mismatched": stats.get("model_mismatched"),
            "seed_mismatched": stats.get("seed_mismatched"),
            "unverifiable": stats.get("unverifiable"),
            "reason": job.get("error") or job.get("original_error"),
            # C-4: persist the STRUCTURED verdict, not just the derived boolean.
            # The bool alone was unreadable as evidence — it was written in one
            # code path only, so a DONE job that delivered a paid video recorded
            # credit_spent_likely=False. `credit_state` is the authority
            # (NOT_SPENT / MAY_HAVE_SPENT / SPENT / UNKNOWN); the bool is kept for
            # existing readers and is derived from it.
            "credit_state": job.get("credit_state") or "UNKNOWN",
            "credit_spent_likely": bool(job.get("credit_spent_likely")),
            "recorded_at": _now(),
        }
        await crud.update_workspace_generation_package(
            wgp_id, generation_identity_json=_json(identity),
        )
        # THE VERDICT. This is the first point anchors can exist, so it is the only
        # honest place to declare that an output can never be bound. Still
        # fail-closed: a genuinely uncaptured identity is reported loudly, with the
        # observed toolNames and the terminal job status so the cause is
        # adjudicable from the record instead of another paid capture.
        if not identity.get("identity_captured"):
            logger.warning(
                "OUTPUT_IDENTITY_NOT_CAPTURED wgp=%s job=%s job_status=%s "
                "tools_seen=%s gen_tool_matched=%s — no correlation anchor was ever "
                "exposed, so no retrieved media can bind to this run. If a toolName "
                "above is a real generation tool, it is missing from "
                "agent_video._GEN_TOOLS; if the list is EMPTY the run never reached "
                "the approve stream (check the job status and the binding outcome).",
                wgp_id, job_id, identity.get("binding_outcome", {}).get("job_status"),
                identity.get("tools_seen"), identity.get("gen_tool_matched"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("binding outcome snapshot failed wgp=%s job=%s: %s",
                       wgp_id, job_id, exc)


async def _assert_one_serial_t2v_live(
    run: dict,
    *,
    confirm_phrase: str | None,
    expect_package_id: str | None,
) -> dict:
    """Round F gate: refuse anything that is not ONE ready serial T2V item.

    Every check raises rather than returning a flag — the live branch must be
    unreachable unless all of them pass. Readiness is RE-DERIVED here from
    build_execution_payload rather than read from `last_dry_run_report`, so a
    package that changed between the dry run and the live click cannot fire on a
    stale green report. Returns the single validated item.
    """
    if (confirm_phrase or "").strip() != LIVE_CONFIRM_PHRASE:
        raise ValueError("LIVE_CONFIRM_PHRASE_INVALID")

    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    # The live loop fans out over EVERY queued item, so >1 item is a bulk run.
    if len(items) != 1:
        raise ValueError(f"LIVE_REQUIRES_EXACTLY_ONE_ITEM:{len(items)}")
    item = items[0]
    package_id = item["workspace_generation_package_id"]

    if expect_package_id and expect_package_id != package_id:
        raise ValueError(f"LIVE_PACKAGE_MISMATCH:{package_id}")

    product_id = str(item.get("product_id") or "")
    if product_id.startswith("fastmoss-ref:"):
        raise ValueError(f"LIVE_FASTMOSS_REF_FORBIDDEN:{product_id}")

    # Pre-flight duplicate check. O4's guard inside _fire_and_wait is the real
    # provider-boundary defence and is NOT replaced — this only fails faster.
    prior_job = str(item.get("production_job_id") or "").strip()
    if prior_job:
        raise ValueError(f"LIVE_DUPLICATE_SUBMISSION:{prior_job}")

    cfg = _loads(run.get("config_json"), {})
    payload, blockers = await build_execution_payload(item, cfg)
    logical_mode = (payload.get("logical_mode") or "").strip().upper()
    if logical_mode != "T2V":
        raise ValueError(f"LIVE_T2V_ONLY:{logical_mode or 'UNKNOWN'}")
    if blockers:
        raise ValueError(f"LIVE_ITEM_BLOCKED:{','.join(blockers)}")

    # A dry run must actually have been performed and been green. This is the
    # procedural gate (operator followed the drill); the re-derivation above is
    # the authoritative one.
    report = cfg.get("last_dry_run_report")
    if not isinstance(report, dict):
        raise ValueError("LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN")
    if int(report.get("ready") or 0) != 1 or int(report.get("blocked") or 0) != 0:
        raise ValueError(
            f"LIVE_REQUIRES_DRY_RUN_READY:ready={report.get('ready')},"
            f"blocked={report.get('blocked')}"
        )
    return item


async def _assert_one_serial_f2v_live(
    run: dict,
    *,
    confirm_phrase: str | None,
    expect_package_id: str | None,
) -> dict:
    """FIRST-FRAME family gate: refuse anything that is not ONE ready serial
    F2V or HYBRID item.

    A mirror of _assert_one_serial_t2v_live (phrase + accepted modes differ).
    F2V and HYBRID both fire the SAME live-proven first-frame engine
    (generate_video_with_first_frame / veo_3_1_i2v_lite — g_ba088e7195df);
    HYBRID is the product-anchor presenter lane on that engine, so it shares
    this lane's exact credit/risk profile. I2V and T2V still raise
    LIVE_F2V_ONLY. Every check raises rather than returning a flag, and
    readiness is RE-DERIVED from build_execution_payload (never read from a
    stale green report), so the live branch is unreachable unless all of them
    pass. Returns (item, validated_logical_mode) — the dispatcher authorizes
    the loop for EXACTLY that mode, so a HYBRID-authorized run can never fire
    a swapped-in F2V item and vice versa.
    """
    if (confirm_phrase or "").strip() != LIVE_F2V_CONFIRM_PHRASE:
        raise ValueError("LIVE_CONFIRM_PHRASE_INVALID")

    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    if len(items) != 1:
        raise ValueError(f"LIVE_REQUIRES_EXACTLY_ONE_ITEM:{len(items)}")
    item = items[0]
    package_id = item["workspace_generation_package_id"]

    if expect_package_id and expect_package_id != package_id:
        raise ValueError(f"LIVE_PACKAGE_MISMATCH:{package_id}")

    product_id = str(item.get("product_id") or "")
    if product_id.startswith("fastmoss-ref:"):
        raise ValueError(f"LIVE_FASTMOSS_REF_FORBIDDEN:{product_id}")

    prior_job = str(item.get("production_job_id") or "").strip()
    if prior_job:
        raise ValueError(f"LIVE_DUPLICATE_SUBMISSION:{prior_job}")

    cfg = _loads(run.get("config_json"), {})
    payload, blockers = await build_execution_payload(item, cfg)
    logical_mode = (payload.get("logical_mode") or "").strip().upper()
    if logical_mode not in ("F2V", "HYBRID"):
        raise ValueError(f"LIVE_F2V_ONLY:{logical_mode or 'UNKNOWN'}")
    if blockers:
        raise ValueError(f"LIVE_ITEM_BLOCKED:{','.join(blockers)}")

    report = cfg.get("last_dry_run_report")
    if not isinstance(report, dict):
        raise ValueError("LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN")
    if int(report.get("ready") or 0) != 1 or int(report.get("blocked") or 0) != 0:
        raise ValueError(
            f"LIVE_REQUIRES_DRY_RUN_READY:ready={report.get('ready')},"
            f"blocked={report.get('blocked')}"
        )
    return item, logical_mode


async def _assert_one_serial_i2v_live(
    run: dict,
    *,
    confirm_phrase: str | None,
    expect_package_id: str | None,
) -> tuple[dict, str]:
    """INGREDIENTS/references gate: refuse anything that is not ONE ready serial
    I2V item.

    Mirror of the first-frame gate with the I2V phrase and mode literal. I2V
    fires generate_video_with_references / veo_3_1_r2v_lite — live-proved by the
    HYBRID fire (g_8845373fbb86) — through the same one door with the same
    credit profile. Every check raises; readiness is RE-DERIVED from
    build_execution_payload. Returns (item, "I2V") for mode-exact loop
    authorization.
    """
    if (confirm_phrase or "").strip() != LIVE_I2V_CONFIRM_PHRASE:
        raise ValueError("LIVE_CONFIRM_PHRASE_INVALID")

    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    if len(items) != 1:
        raise ValueError(f"LIVE_REQUIRES_EXACTLY_ONE_ITEM:{len(items)}")
    item = items[0]
    package_id = item["workspace_generation_package_id"]

    if expect_package_id and expect_package_id != package_id:
        raise ValueError(f"LIVE_PACKAGE_MISMATCH:{package_id}")

    product_id = str(item.get("product_id") or "")
    if product_id.startswith("fastmoss-ref:"):
        raise ValueError(f"LIVE_FASTMOSS_REF_FORBIDDEN:{product_id}")

    prior_job = str(item.get("production_job_id") or "").strip()
    if prior_job:
        raise ValueError(f"LIVE_DUPLICATE_SUBMISSION:{prior_job}")

    cfg = _loads(run.get("config_json"), {})
    payload, blockers = await build_execution_payload(item, cfg)
    logical_mode = (payload.get("logical_mode") or "").strip().upper()
    if logical_mode != "I2V":
        raise ValueError(f"LIVE_I2V_ONLY:{logical_mode or 'UNKNOWN'}")
    if blockers:
        raise ValueError(f"LIVE_ITEM_BLOCKED:{','.join(blockers)}")

    report = cfg.get("last_dry_run_report")
    if not isinstance(report, dict):
        raise ValueError("LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN")
    if int(report.get("ready") or 0) != 1 or int(report.get("blocked") or 0) != 0:
        raise ValueError(
            f"LIVE_REQUIRES_DRY_RUN_READY:ready={report.get('ready')},"
            f"blocked={report.get('blocked')}"
        )
    return item, logical_mode


def _persisted_dialogue_fingerprint(item: dict) -> str:
    """The per-item dialogue fingerprint, from EITHER durable source.

    B-01: two lanes persist this in different columns, and the gate previously
    read only one of them —

      * the BATCH prompt lane writes ``variation_fingerprints_json`` via
        ``_annotate_batch_prompt_item``;
      * Stage 2C bulk prepare writes the namespaced, versioned
        ``generation_identity_json.bulk_fanout_item`` and never touches
        ``variation_fingerprints_json``.

    Reading only the batch column meant every 2C-prepared package looked like it
    had NO fingerprint, so the gate refused with
    BULK_ITEM_DIALOGUE_FINGERPRINT_MISSING and could never reach its own credit
    boundary. Prefer the bulk identity (written by the lane that built this
    batch), fall back to the batch column, and return "" when neither is present
    so the caller still FAILS CLOSED.
    """
    identity = _loads(item.get("generation_identity_json"), {}) or {}
    bulk_item = identity.get("bulk_fanout_item") or {}
    fp = str(bulk_item.get("dialogue_fingerprint") or "").strip()
    if fp:
        return fp
    fingerprints = _loads(item.get("variation_fingerprints_json"), {}) or {}
    return str(fingerprints.get("dialogue_fingerprint") or "").strip()


async def _assert_bulk_fanout_live(
    run: dict,
    *,
    confirm_phrase: str | None,
    expect_package_ids: list[str] | None,
    expect_dialogue_fingerprints: list[str] | None,
) -> list[dict]:
    """Stage 2A gate: refuse anything that is not N READY, UNIQUE-dialogue items.

    Mirrors the one-serial gates' discipline — every check RAISES, so the live
    branch is unreachable unless all of them pass — but for the itemized bulk
    lane. Readiness is RE-DERIVED from build_execution_payload rather than read
    from ``last_dry_run_report``, so an item that changed after the dry run
    cannot ride a stale green report.

    The caller MUST pin the exact set it previewed: package ids AND the dialogue
    fingerprints the operator actually saw. That binding is what stops a bulk
    authorization from being replayed against a different (or duplicate-dialogue)
    set. Returns the validated items.
    """
    if (confirm_phrase or "").strip() != LIVE_BULK_CONFIRM_PHRASE:
        raise ValueError("LIVE_BULK_CONFIRM_PHRASE_INVALID")

    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    # This gate is the BULK door only. One item must go through its mode-exact
    # one-serial gate, which enforces stricter per-lane rules.
    if len(items) < 2:
        raise ValueError(f"BULK_REQUIRES_MULTIPLE_ITEMS:{len(items)}")

    # The client must pin the exact fan-out set — no implicit "whatever is queued".
    pinned = [str(p) for p in (expect_package_ids or [])]
    if not pinned:
        raise ValueError("BULK_REQUIRES_EXPECT_PACKAGE_IDS")
    queued_ids = [str(i["workspace_generation_package_id"]) for i in items]
    if sorted(pinned) != sorted(queued_ids):
        raise ValueError(
            f"BULK_PACKAGE_SET_MISMATCH:expected={len(pinned)},queued={len(queued_ids)}"
        )

    cfg = _loads(run.get("config_json"), {})
    seen_fingerprints: dict[str, str] = {}
    validated: list[dict] = []
    # B-03: the live loop authorizes T2V by default and widens ONLY for a mode
    # recorded in cfg['authorized_live_mode']. This gate never recorded one, so a
    # validated F2V/HYBRID/I2V bulk set would still have died per item with
    # LIVE_MODE_NOT_AUTHORIZED. Collect the modes actually validated here so the
    # caller can record exactly that authorization — no wider.
    validated_modes: set[str] = set()

    for item in items:
        package_id = str(item["workspace_generation_package_id"])
        product_id = str(item.get("product_id") or "")
        if product_id.startswith("fastmoss-ref:"):
            raise ValueError(f"LIVE_FASTMOSS_REF_FORBIDDEN:{product_id}")
        prior_job = str(item.get("production_job_id") or "").strip()
        if prior_job:
            raise ValueError(f"LIVE_DUPLICATE_SUBMISSION:{package_id}:{prior_job}")

        # An EXTEND item is validated WITHOUT build_execution_payload for the same
        # reason the live loop skips it: that builder is single-shot only and fails
        # EXTEND closed by design, so running it here would refuse the very fan-out
        # this gate exists to validate. The item still has to clear every check
        # below (mode authorization, dialogue fingerprint, uniqueness) — only the
        # single-shot payload mapping is skipped, because the durable /video-jobs
        # lane resolves its own payload from the execution package.
        if _is_extend_package(item):
            payload, blockers = {"logical_mode": _package_logical_mode(item)}, []
        else:
            payload, blockers = await build_execution_payload(item, cfg)
        if blockers:
            raise ValueError(f"BULK_ITEM_BLOCKED:{package_id}:{','.join(blockers)}")
        logical_mode = (payload.get("logical_mode") or "").strip().upper()
        if not logical_mode:
            raise ValueError(f"BULK_ITEM_MODE_UNKNOWN:{package_id}")
        validated_modes.add(logical_mode)

        # Dialogue uniqueness is re-proven from the PERSISTED per-item
        # fingerprint, never assumed from the preview. Two items sharing a
        # dialogue is the exact failure Stage 1 made fail-closed; it must not
        # become a warning just because the operator asked for N.
        dialogue_fp = _persisted_dialogue_fingerprint(item)
        if not dialogue_fp:
            raise ValueError(f"BULK_ITEM_DIALOGUE_FINGERPRINT_MISSING:{package_id}")
        if dialogue_fp in seen_fingerprints:
            raise ValueError(
                f"BULK_DUPLICATE_DIALOGUE:{seen_fingerprints[dialogue_fp]},{package_id}"
            )
        seen_fingerprints[dialogue_fp] = package_id
        validated.append(item)

    # The operator authorizes the dialogue set they SAW. Any drift between the
    # previewed fingerprints and the queued ones voids the authorization.
    pinned_fps = [str(f) for f in (expect_dialogue_fingerprints or [])]
    if not pinned_fps:
        raise ValueError("BULK_REQUIRES_EXPECT_DIALOGUE_FINGERPRINTS")
    if sorted(pinned_fps) != sorted(seen_fingerprints.keys()):
        raise ValueError(
            f"BULK_DIALOGUE_SET_MISMATCH:expected={len(set(pinned_fps))},"
            f"queued={len(seen_fingerprints)}"
        )

    report = cfg.get("last_dry_run_report")
    if not isinstance(report, dict):
        raise ValueError("LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN")
    if int(report.get("ready") or 0) != len(items) or int(report.get("blocked") or 0) != 0:
        raise ValueError(
            f"BULK_REQUIRES_ALL_ITEMS_DRY_RUN_READY:ready={report.get('ready')},"
            f"blocked={report.get('blocked')},items={len(items)}"
        )

    # Mode law: ONE batch = ONE logical mode. A mixed set cannot be authorized,
    # because the live loop admits exactly one mode per run — authorizing the
    # union would silently widen the grant beyond what was validated.
    if len(validated_modes) != 1:
        raise ValueError(
            "BULK_MIXED_MODES_FORBIDDEN:" + ",".join(sorted(validated_modes))
        )
    validated_mode = next(iter(validated_modes))

    # ── STAGE 3 CREDIT BOUNDARY ──
    # Everything above is validated. Execution stops here: bulk live fan-out has
    # never been certified against the provider, so Stage 2A refuses to spend
    # credit even with a perfect gate. This is the LAST check on purpose — the
    # operator gets the full validation verdict, not an early bail.
    if not bulk_live_execution_certified():
        raise ValueError(
            f"BULK_LIVE_EXECUTION_NOT_CERTIFIED:validated_items={len(validated)}:"
            "stage3_runtime_certification_required"
        )
    return validated, validated_mode


async def run_production_queue(
    run_id: str,
    *,
    confirm_live_credit_burn: bool = False,
    live_gate: str | None = None,
    confirm_phrase: str | None = None,
    expect_package_id: str | None = None,
    expect_package_ids: list[str] | None = None,
    expect_dialogue_fingerprints: list[str] | None = None,
) -> dict:
    """Start a production run.

    Without confirm_live_credit_burn the run stays a DRY RUN: every queued
    item's payload is validated and reported, no generation fires, no credits
    are spent, items stay QUEUED. With confirmation the live loop fires each
    item through make_video.start_generate honouring interval + cooldown.

    NOTE — the dry run is no longer read-only for IMAGE modes (F2V/I2V/HYBRID):
    it now runs a credit-free pre-pass that uploads each slot's reference image to
    Flow and persists the resulting media UUID (product.media_id /
    creative_asset.media_id, asset_status=UPLOADED_TO_FLOW) so the item can reach
    ready. This spends ZERO credits (asset upload, not generation) and is
    idempotent (a live UUID is reused, not re-uploaded). T2V dry-run is unchanged.

    live_gate=ONE_SERIAL_T2V opts into the Round F gate, which refuses anything
    that is not exactly one ready T2V item confirmed by the exact phrase.
    """
    run = await crud.get_production_run(run_id)
    if not run:
        raise ValueError("RUN_NOT_FOUND")
    if run.get("status") not in ("PENDING", "PAUSED"):
        raise ValueError(f"RUN_NOT_STARTABLE:{run.get('status')}")

    if not confirm_live_credit_burn:
        report = await _dry_run_report(run)
        cfg = _loads(run.get("config_json"), {})
        cfg["last_dry_run_report"] = report
        await crud.update_production_run(
            run_id, config_json=_json(cfg),
        )
        return {"run_id": run_id, "dry_run": True, "report": report}

    # ── Stage 2B: the ungated MULTI-ITEM bypass is closed ──
    # The one-serial gates are opt-in, so before this check a caller could reach
    # the fan-out loop with N items simply by OMITTING live_gate — no phrase, no
    # readiness, no preview correlation. `allowed_live_modes` in the loop
    # constrains MODE, never COUNT, so an ungated start with N queued items
    # fired all N serially.
    #
    # Owner decision 2026-07-20 (supersedes the earlier "pre-existing bulk path
    # is a protected system" carve-out): a run with MORE THAN ONE queued item
    # must present an explicit bulk gate. SINGLE-item ungated behaviour is
    # deliberately untouched, so the legacy one-item ProductionQueuePage flow
    # keeps working exactly as before.
    if not live_gate:
        _queued = await crud.list_production_queue_packages(
            production_run_id=run_id, production_status="QUEUED",
        )
        if len(_queued) > 1:
            raise ValueError(
                f"BULK_LIVE_REQUIRES_BULK_GATE:{len(_queued)}_items:"
                f"pass_live_gate={LIVE_GATE_BULK_FANOUT}"
            )

    # Loop authorization is fail-closed: clear any prior authorization on EVERY
    # live start (unconditionally, before the gate branch) so an ungated
    # ProductionQueuePage bulk run — or a run resumed-as-bulk after a pause —
    # can never inherit a stale F2V grant. Only a passing F2V gate re-sets it.
    cfg = _loads(run.get("config_json"), {})
    cfg.pop("authorized_live_mode", None)
    gated_package_id: str | None = None
    if live_gate:
        # Both gates raise on any refusal BEFORE the state write below, so a
        # refused live request leaves the run exactly as it was (still dry,
        # still PENDING/PAUSED) — nothing is persisted.
        if live_gate == LIVE_GATE_ONE_SERIAL_T2V:
            item = await _assert_one_serial_t2v_live(
                run, confirm_phrase=confirm_phrase, expect_package_id=expect_package_id,
            )
            gated_package_id = item["workspace_generation_package_id"]
        elif live_gate == LIVE_GATE_ONE_SERIAL_F2V:
            item, validated_mode = await _assert_one_serial_f2v_live(
                run, confirm_phrase=confirm_phrase, expect_package_id=expect_package_id,
            )
            gated_package_id = item["workspace_generation_package_id"]
            # Authorize the loop for EXACTLY the validated mode (F2V or HYBRID —
            # the first-frame family) of THIS one pre-validated item; the gate
            # already guaranteed exactly one QUEUED item.
            cfg["authorized_live_mode"] = validated_mode
        elif live_gate == LIVE_GATE_ONE_SERIAL_I2V:
            item, validated_mode = await _assert_one_serial_i2v_live(
                run, confirm_phrase=confirm_phrase, expect_package_id=expect_package_id,
            )
            gated_package_id = item["workspace_generation_package_id"]
            cfg["authorized_live_mode"] = validated_mode
        elif live_gate == LIVE_GATE_BULK_FANOUT:
            # Stage 2A: validates the whole itemized fan-out set fail-closed and
            # then refuses at the credit boundary (BULK_LIVE_EXECUTION_CERTIFIED).
            # It raises before the state write below, so the run stays dry.
            _bulk_items, validated_mode = await _assert_bulk_fanout_live(
                run,
                confirm_phrase=confirm_phrase,
                expect_package_ids=expect_package_ids,
                expect_dialogue_fingerprints=expect_dialogue_fingerprints,
            )
            # B-03: authorize the loop for EXACTLY the one mode this gate just
            # validated across every item — the same mechanism (and the same
            # scalar) the one-serial F2V/I2V gates already use. Without it a
            # validated F2V/HYBRID/I2V bulk set would hit the loop's T2V-only
            # default and fail per item with LIVE_MODE_NOT_AUTHORIZED. This
            # widens nothing: the mode is derived from the validated items and the
            # batch is mode-uniform by law. An EXTEND item reaches here too and is
            # authorized by the SAME logical mode as any other item — the extend
            # decision is about which execution lane runs it, never about widening
            # which modes may burn credit.
            cfg["authorized_live_mode"] = validated_mode
        else:
            raise ValueError(f"LIVE_GATE_UNKNOWN:{live_gate}")

    await crud.update_production_run(
        run_id, dry_run=0, status="RUNNING", config_json=_json(cfg),
    )
    _run_control.pop(run_id, None)
    asyncio.ensure_future(_live_production_loop(run_id))
    return {
        "run_id": run_id, "dry_run": False, "status": "RUNNING",
        "live_gate": live_gate, "package_id": gated_package_id,
    }


async def _dry_run_report(run: dict) -> dict:
    cfg = _loads(run.get("config_json"), {})
    items = await crud.list_production_queue_packages(
        production_run_id=run["production_run_id"], production_status="QUEUED",
    )
    results = []
    ready = 0
    for item in items:
        # PRE-PASS (dry-run only, credit-free): upload any image-mode slot image to
        # Flow + persist its UUID, so the pure build_execution_payload READ below can
        # resolve it. No-op for T2V/IMG. Its blockers merge into the reported ones.
        upload_blockers = await _resolve_and_upload_image_slots(item, cfg)
        # EXTEND is validated against the DURABLE lane's preconditions, not the
        # single-shot payload mapping — the same authority its fire path uses, so
        # a green extend dry run means the same thing every other green item does.
        if _is_extend_package(item):
            payload, blockers = extend_execution_preconditions(item, cfg)
        else:
            payload, blockers = await build_execution_payload(item, cfg)
        blockers = list(dict.fromkeys(upload_blockers + blockers))
        ok = not blockers
        ready += 1 if ok else 0
        results.append({
            "package_id": item["workspace_generation_package_id"],
            "logical_mode": payload.get("logical_mode"),
            "engine_mode": payload.get("mode"),
            "execution_lane": payload.get("execution_lane"),
            "model": payload.get("model"),
            "duration_s": payload.get("duration_s"),
            "image_media_ids": payload.get("image_media_ids") or [],
            "ok": ok,
            "blockers": blockers,
        })
    return {
        "checked": len(items), "ready": ready,
        "blocked": len(items) - ready, "items": results,
        "note": "DRY RUN — nothing fired, no credits spent.",
    }


async def _live_production_loop(run_id: str) -> None:
    from agent.services import make_video

    run = await crud.get_production_run(run_id)
    cfg = _loads(run.get("config_json"), {})
    # Fail-closed live-mode authorization. Default is T2V-only: the ungated
    # ProductionQueuePage bulk path and every non-F2V-gated run land here. Only a
    # run that passed the ONE_SERIAL_F2V gate carries cfg['authorized_live_mode']=
    # 'F2V' (set in run_production_queue, popped on every other live start), which
    # — and only which — widens the set to admit that one pre-validated F2V item.
    allowed_live_modes = {"T2V"}
    _auth = str(cfg.get("authorized_live_mode") or "").strip().upper()
    if _auth in ("F2V", "HYBRID", "I2V"):
        # A phrased gate validated ONE item of exactly this mode.
        allowed_live_modes = {_auth}
    interval_min = int(run.get("interval_min_seconds") or 45)
    interval_max = int(run.get("interval_max_seconds") or 120)
    cooldown_n = int(run.get("cooldown_after_n_jobs") or 5)
    cooldown_s = int(run.get("cooldown_seconds") or 300)

    completed = int(run.get("total_completed") or 0)
    failed = int(run.get("total_failed") or 0)
    errors: list[str] = _loads(run.get("error_log_json"), [])
    fired_since_cooldown = 0

    while True:
        signal = _run_control.get(run_id)
        if signal == "CANCEL":
            await _cancel_remaining(run_id)
            await crud.update_production_run(
                run_id, status="CANCELLED",
                total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            _run_control.pop(run_id, None)
            return
        if signal == "PAUSE":
            await crud.update_production_run(
                run_id, status="PAUSED",
                total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            _run_control.pop(run_id, None)
            return

        queued = await crud.list_production_queue_packages(
            production_run_id=run_id, production_status="QUEUED", limit=1,
        )
        if not queued:
            break
        item = queued[0]
        wgp_id = item["workspace_generation_package_id"]

        # Bulk EXTEND is MULTI-BLOCK and belongs to the durable /video-jobs
        # orchestrator, so it is routed BEFORE build_execution_payload runs. That
        # builder is the SINGLE-SHOT payload mapper and fails EXTEND closed by
        # design — asking it for an extend payload could only ever produce the
        # 8s truncation it exists to prevent. The logical mode is read straight
        # off the package so the live-mode chokepoint below still judges an
        # extend item by exactly the same authority as every other item.
        is_extend = _is_extend_package(item)
        if is_extend:
            payload, blockers = {"logical_mode": _package_logical_mode(item)}, []
        else:
            payload, blockers = await build_execution_payload(item, cfg)
        # Second, UNIVERSAL chokepoint. Every queued item converges here — both
        # the ungated ProductionQueuePage bulk path (confirm_live_credit_burn=True,
        # no live_gate) and a gated run. The default authorized set is {"T2V"}, so
        # the bulk path and any non-F2V-gated run stay strictly T2V-only exactly as
        # before; only a run that passed the ONE_SERIAL_F2V gate widened the set to
        # {"F2V"} for its one pre-validated item. Refuse before start_generate and
        # mark FAILED so the item leaves the QUEUED set (a bare `continue` on a
        # still-QUEUED item would loop forever).
        logical_mode = (payload.get("logical_mode") or "").strip().upper()
        if logical_mode not in allowed_live_modes:
            failed += 1
            # Preserve the exact proven message on the default/bulk (T2V-only)
            # lane; a stray item inside an authorized-F2V run gets a distinct code.
            reason = (
                f"LIVE_T2V_ONLY:{logical_mode or 'UNKNOWN'}"
                if allowed_live_modes == {"T2V"}
                else f"LIVE_MODE_NOT_AUTHORIZED:{logical_mode or 'UNKNOWN'}"
            )
            errors.append(f"{wgp_id}: {reason}")
            await crud.update_workspace_generation_package(
                wgp_id, production_status="FAILED", production_error=reason,
            )
            await crud.update_production_run(
                run_id, total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            continue
        if blockers:
            failed += 1
            errors.append(f"{wgp_id}: {','.join(blockers)}")
            await crud.update_workspace_generation_package(
                wgp_id, production_status="FAILED",
                production_error=",".join(blockers),
            )
            await crud.update_production_run(
                run_id, total_completed=completed, total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )
            continue

        await crud.update_workspace_generation_package(
            wgp_id, production_status="RUNNING",
        )
        try:
            # EXTEND never touches _fire_and_wait: that helper guards the
            # single-shot provider door, which this lane does not use at all.
            outcome = (
                await _fire_extend_via_video_jobs(item, cfg, wgp_id) if is_extend
                else await _fire_and_wait(make_video, payload, wgp_id)
            )
        except Exception as exc:  # defensive: never kill the loop
            outcome = {"ok": False, "error": f"UNEXPECTED:{exc}"}
        if outcome["ok"]:
            completed += 1
        else:
            failed += 1
            errors.append(f"{wgp_id}: {outcome.get('error')}")
        await crud.update_production_run(
            run_id, total_completed=completed, total_failed=failed,
            error_log_json=_json(errors[-50:]),
        )
        fired_since_cooldown += 1

        remaining = await crud.list_production_queue_packages(
            production_run_id=run_id, production_status="QUEUED", limit=1,
        )
        if not remaining:
            break
        if cooldown_n > 0 and fired_since_cooldown >= cooldown_n:
            fired_since_cooldown = 0
            await asyncio.sleep(cooldown_s)
        else:
            await asyncio.sleep(random.randint(interval_min, max(interval_min, interval_max)))

    final = "COMPLETED" if failed == 0 or completed > 0 else "FAILED"
    await crud.update_production_run(
        run_id, status=final,
        total_completed=completed, total_failed=failed,
        error_log_json=_json(errors[-50:]),
    )
    logger.info("Production run %s finished: %d ok, %d failed", run_id, completed, failed)


def compute_dedupe_key(payload: dict, wgp_id: str) -> str:
    """Stable identity for one logical submission (G0 amendment O4).

    Derived from the inputs that decide what the provider would actually produce:
    the package, the engine/logical mode, model, duration, aspect, count and the
    resolved Flow media bindings, plus the prompt itself. Two attempts that would
    submit the same work therefore collide by construction; a genuinely different
    job (different model, duration, media or prompt) does not.
    """
    basis = {
        "wgp": wgp_id,
        "logical_mode": payload.get("logical_mode"),
        "engine_mode": payload.get("mode"),
        "model": payload.get("model"),
        "duration_s": payload.get("duration_s"),
        "aspect": payload.get("aspect"),
        "num_videos": payload.get("num_videos"),
        "image_media_ids": sorted(payload.get("image_media_ids") or []),
        "prompt_sha": hashlib.sha256((payload.get("prompt") or "").encode("utf-8")).hexdigest(),
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return f"ddk_{digest[:32]}"


async def _fire_and_wait(make_video, payload: dict, wgp_id: str) -> dict:
    """Fire one item through the locked generate door and wait for terminal.

    O4 — idempotency. This is the ONLY provider boundary in the queue, so the
    duplicate-submission guard lives here and cannot be routed around:

      1. Already submitted -> `production_job_id` is written only after a provider
         submission succeeds (see below), so a non-empty value proves this exact
         package already went to the provider. Re-firing it would spend credits
         twice for the same work, so it FAILS CLOSED. `retry_failed_items` clears
         the id deliberately — that is the explicit retry identity, and the only
         supported way to submit a package a second time.
      2. Concurrent duplicate -> a double click, a retried request or two loops
         racing the same package resolve to the same dedupe key. The key is held
         in-process for the lifetime of the submission, so the second caller is
         refused before `start_generate` is reached rather than after.
    """
    fresh = await crud.get_workspace_generation_package(wgp_id) or {}
    prior_job = str(fresh.get("production_job_id") or "").strip()
    if prior_job:
        logger.warning(
            "DUPLICATE_SUBMISSION_BLOCKED wgp=%s already submitted as job=%s", wgp_id, prior_job,
        )
        await crud.update_workspace_generation_package(
            wgp_id,
            production_status="FAILED",
            production_error=f"DUPLICATE_SUBMISSION_BLOCKED:{prior_job}",
        )
        return {"ok": False, "error": f"DUPLICATE_SUBMISSION_BLOCKED:{prior_job}", "job_id": prior_job}

    dedupe_key = compute_dedupe_key(payload, wgp_id)
    if dedupe_key in _inflight_dedupe:
        logger.warning("DUPLICATE_SUBMISSION_IN_FLIGHT wgp=%s key=%s", wgp_id, dedupe_key)
        return {"ok": False, "error": f"DUPLICATE_SUBMISSION_IN_FLIGHT:{dedupe_key}"}
    _inflight_dedupe.add(dedupe_key)
    logger.info("Submission accepted wgp=%s dedupe_key=%s", wgp_id, dedupe_key)
    try:
        return await _fire_and_wait_inner(make_video, payload, wgp_id)
    finally:
        _inflight_dedupe.discard(dedupe_key)


async def _fire_and_wait_inner(make_video, payload: dict, wgp_id: str) -> dict:
    attempts = 0
    while True:
        result = await make_video.start_generate(
            payload["mode"], payload["prompt"],
            image_media_ids=payload.get("image_media_ids"),
            aspect=payload.get("aspect") or "9:16",
            model=payload.get("model"),
            duration_s=payload.get("duration_s"),
            num_videos=payload.get("num_videos") or 1,
        )
        if result.get("status") == "REJECTED" and result.get("error") == "VIDEO_JOB_IN_FLIGHT":
            attempts += 1
            if attempts > _INFLIGHT_MAX_RETRIES:
                await crud.update_workspace_generation_package(
                    wgp_id, production_status="FAILED",
                    production_error="VIDEO_LANE_BUSY_TIMEOUT",
                )
                return {"ok": False, "error": "VIDEO_LANE_BUSY_TIMEOUT"}
            await asyncio.sleep(_INFLIGHT_RETRY_SECONDS)
            continue
        break

    job_id = result.get("job_id")
    if not job_id:
        err = result.get("error") or "NO_JOB_ID"
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error=str(err),
        )
        return {"ok": False, "error": str(err)}

    await crud.update_workspace_generation_package(wgp_id, production_job_id=job_id)
    # Persist the submission's correlation identity the moment it exists. It
    # previously lived only in make_video's in-memory _JOBS, so a restart erased
    # the only record of whether this run's output could ever be bound.
    await _persist_generation_identity(wgp_id, job_id)

    waited = 0
    while waited < _JOB_TIMEOUT_SECONDS:
        job = make_video.get_job(job_id) or {}
        status = job.get("status")
        if status in ("DONE", "FAILED", "REJECTED", "GENERATED_BUT_UNRETRIEVED",
                      "RENDER_NOT_MATERIALIZED", "STALE_OR_FOREIGN_CANDIDATES_ONLY"):
            # RENDER_NOT_MATERIALIZED (B-15) falls through to the generic
            # failure mapping below: production_status=FAILED with the full
            # classifier message as production_error — nothing was produced,
            # so it must never ride the GENERATED credit-spent contract.
            break
        await asyncio.sleep(_POLL_SECONDS)
        waited += _POLL_SECONDS
    else:
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error="JOB_TIMEOUT",
        )
        return {"ok": False, "error": "JOB_TIMEOUT"}

    job = make_video.get_job(job_id) or {}
    status = job.get("status")
    # Durably record what happened to the candidates BEFORE branching on status,
    # so a refusal leaves the same audit trail as an acceptance.
    await _persist_binding_outcome(wgp_id, job_id)
    if status == "DONE":
        media_ids = [a.get("media_id") for a in (job.get("artifacts") or []) if a.get("media_id")]
        if not media_ids and job.get("media_id"):
            media_ids = [job["media_id"]]
        await crud.link_artifacts_to_generation_package(job_id, wgp_id)
        await crud.update_workspace_generation_package(
            wgp_id,
            production_status="DOWNLOADED" if job.get("local_path") else "GENERATED",
            artifact_media_ids_json=_json(media_ids),
            production_error=None,
        )
        return {"ok": True}
    if status == "GENERATED_BUT_UNRETRIEVED":
        # Credits were spent and the video exists in Flow — never report a
        # plain failure (locked contract from make_video).
        await crud.update_workspace_generation_package(
            wgp_id, production_status="GENERATED",
            production_error="GENERATED_BUT_UNRETRIEVED",
        )
        return {"ok": True}
    err = job.get("error") or status or "UNKNOWN"
    await crud.update_workspace_generation_package(
        wgp_id, production_status="FAILED", production_error=str(err),
    )
    return {"ok": False, "error": str(err)}


def _is_extend_package(pkg: dict) -> bool:
    """True when this package is a MULTI-BLOCK Extend request."""
    return str(pkg.get("generation_mode") or "SINGLE").strip().upper() == "EXTEND"


def _package_logical_mode(pkg: dict) -> str:
    """Logical mode read straight off the package.

    Deliberately mirrors build_execution_payload's derivation: an EXTEND package
    never reaches that builder, but the loop's live-mode authorization gate must
    still judge it by exactly the same mode identity as every other item — an
    extend item must not become a way to sidestep the T2V-only default.
    """
    logical_mode = (pkg.get("logical_mode") or "").strip().upper()
    if not logical_mode:
        mode = (pkg.get("mode") or "").strip().upper()
        lane = (pkg.get("source_lane") or "").strip().upper()
        logical_mode = "HYBRID" if (mode == "F2V" and lane == "HYBRID") else mode
    return logical_mode


def extend_execution_preconditions(pkg: dict, cfg: dict) -> tuple[dict, list[str]]:
    """Credit-free readiness for ONE durable EXTEND item: (resolved, blockers).

    The EXTEND counterpart of build_execution_payload — which stays single-shot
    only and is never called for an extend package. The dry run and the fire path
    share THIS function deliberately: a green dry run that then dies at fire time
    is the exact failure the single-shot lane already had to learn (live I2V
    wgp_99e9961ae1ac5413 dry-ran green and died at the door).

    Resolves nothing from the provider and reads no remote state — pure package +
    run-config truth, so it is safe to run in a dry run.
    """
    from agent.api.flow import _VIDEO_ASPECT_TO_RATIO

    blockers: list[str] = []

    # The orchestrator resolves ALL production authority (product, asset, per-block
    # prompts) from the execution package; with no linkage there is nothing to
    # resolve and nothing to review.
    execution_package_id = str(pkg.get("workspace_execution_package_id") or "").strip()
    if not execution_package_id:
        blockers.append("EXTEND_EXECUTION_PACKAGE_MISSING")

    # Total duration comes from the package's OWN compiled block plan — the
    # compiler wrote one block per Extend segment. There is no
    # requested_total_duration_seconds column to read, and guessing a total would
    # plan a different video than the one that was compiled and approved.
    blocks = _loads(pkg.get("prompt_blocks_json"), [])
    total_seconds = sum(
        int(b.get("duration_seconds") or 0)
        for b in blocks if isinstance(b, dict)
    )
    if len(blocks) < 2 or total_seconds <= 0:
        blockers.append(
            f"EXTEND_BLOCK_PLAN_INVALID:blocks={len(blocks)},total={total_seconds}s")

    # USER SETTINGS ARE LAW: an aspect the durable lane has no enum for FAILS
    # CLOSED rather than being silently downgraded to the portrait default.
    aspect = str(cfg.get("aspect") or "9:16").strip()
    aspect_ratio = next(
        (enum for enum, ratio in _VIDEO_ASPECT_TO_RATIO.items() if ratio == aspect),
        None,
    )
    if not aspect_ratio:
        blockers.append(f"EXTEND_UNSUPPORTED_ASPECT:{aspect}")

    # Same model law the single-shot lane enforces: no silent Lite default.
    if not str(cfg.get("model") or "").strip():
        blockers.append("MODEL_REQUIRED")

    resolved = {
        "execution_package_id": execution_package_id,
        "total_seconds": total_seconds,
        "aspect_ratio": aspect_ratio,
        "logical_mode": _package_logical_mode(pkg),
        "execution_lane": "VIDEO_JOBS_ORCHESTRATOR",
    }
    return resolved, blockers


def _error_text(exc: BaseException) -> str:
    """The REAL failure string. HTTPException carries its cause in `.detail`,
    which str() would drop and replace with a bare status code."""
    detail = getattr(exc, "detail", None)
    return str(detail if detail not in (None, "") else exc)[:300]


async def _fail_extend_item(wgp_id: str, reason: str) -> dict:
    """Mark ONE extend item FAILED and hand the loop its outcome.

    Failure isolation: only this package is touched, so the fan-out continues to
    the next item instead of the whole run dying on one stranded video.
    """
    await crud.update_workspace_generation_package(
        wgp_id, production_status="FAILED", production_error=reason,
    )
    return {"ok": False, "error": reason}


async def _fire_extend_via_video_jobs(item: dict, cfg: dict, wgp_id: str) -> dict:
    """Fire ONE multi-block EXTEND item through the durable /video-jobs orchestrator.

    Returns the SAME outcome shape as _fire_and_wait so the queue loop is unchanged.

    This lane submits nothing itself. It plans, authorizes and drives the
    orchestrator, which owns the per-block submissions, the seam/concat pipeline
    and its own credit side-effect ledger. It is deliberately NOT routed through
    _fire_and_wait, because that helper exists to guard the single-shot door
    (make_video.start_generate) — a door that renders exactly one 8s block and
    would silently truncate a 16s/24s request.

    Paying twice is prevented in TWO layers:
      1. the same fail-closed prior-`production_job_id` refusal _fire_and_wait
         applies, replicated here because this path bypasses it. The id is written
         the moment a job exists, so a non-empty value proves this package already
         went out; `retry_failed_items` clearing it stays the ONLY retry identity.
      2. the orchestrator's OWN replay identity, which is stronger than a
         synthetic key: `compute_logical_job_key` hashes execution package,
         product, asset sha, duration, prompt fingerprint, execution_mode and
         `client_request_nonce`. Pinning the nonce to wgp_id makes a re-plan of the
         same package return the SAME vj_* job (`reused=True`) instead of minting a
         second one, and the authorization token is single-use on top of that.
    `compute_dedupe_key` is deliberately NOT reused: it is derived from
    single-shot payload fields (engine mode, num_videos, image_media_ids) that an
    extend item legitimately does not have, so feeding it would mean fabricating
    them.
    """
    # Local imports: agent.api.flow imports this service, so importing it at
    # module level would close an import cycle (the same cross-layer pattern
    # workspace_generation_package_service already uses).
    from agent.api.flow import VideoJobPlanRequest, _drive_video_job, _plan_video_job
    from agent.services import video_production_orchestrator as _orch

    fresh = await crud.get_workspace_generation_package(wgp_id) or {}
    prior_job = str(fresh.get("production_job_id") or "").strip()
    if prior_job:
        logger.warning(
            "DUPLICATE_SUBMISSION_BLOCKED wgp=%s already submitted as job=%s",
            wgp_id, prior_job,
        )
        out = await _fail_extend_item(
            wgp_id, f"DUPLICATE_SUBMISSION_BLOCKED:{prior_job}")
        return {**out, "job_id": prior_job}

    resolved, blockers = extend_execution_preconditions(fresh, cfg)
    if blockers:
        return await _fail_extend_item(wgp_id, ",".join(blockers))
    execution_package_id = resolved["execution_package_id"]
    total_seconds = resolved["total_seconds"]
    aspect_ratio = resolved["aspect_ratio"]

    # PLAN. trust_client_authority=False is the production SSOT path: product,
    # asset and per-block prompt authority are re-resolved server-side from the
    # execution package, so the queue cannot assert authority it does not own.
    try:
        plan = await _plan_video_job(
            VideoJobPlanRequest(
                product_id=str(fresh.get("product_id") or "") or None,
                product_name=str(fresh.get("product_name_snapshot") or "") or None,
                execution_package_id=execution_package_id,
                requested_total_duration_seconds=total_seconds,
                model=cfg.get("model"),
                aspect_ratio=aspect_ratio,
                client_request_nonce=wgp_id,
            ),
            trust_client_authority=False,
        )
    except Exception as exc:  # noqa: BLE001 — one item's failure, not the run's
        return await _fail_extend_item(wgp_id, f"EXTEND_PLAN_FAILED:{_error_text(exc)}")

    job_id = str((plan or {}).get("job_id") or "")
    fingerprint = str((plan or {}).get("plan_fingerprint") or "")
    if not job_id or not fingerprint:
        return await _fail_extend_item(wgp_id, "EXTEND_PLAN_INCOMPLETE")

    # DURABLE HANDLE, written BEFORE authorization — i.e. before any credit stage
    # can start. From here the duplicate refusal above owns this package, so a
    # crash mid-drive can never re-fire it. The existing production_job_id slot
    # holds the vj_* id: no new column, no migration.
    await crud.update_workspace_generation_package(wgp_id, production_job_id=job_id)

    try:
        auth = await _orch.authorize_job(
            job_id, confirmed_plan_fingerprint=fingerprint)
        token = str((auth or {}).get("authorization_token") or "")
        if not token:
            return await _fail_extend_item(wgp_id, "EXTEND_AUTHORIZATION_MISSING_TOKEN")
        # The SAME driver POST /video-jobs/{id}/start schedules. It swallows its
        # own exceptions because orchestrator state is persisted, so the status
        # read below — never this call's return — is the source of truth.
        await _drive_video_job(job_id, token)
    except Exception as exc:  # noqa: BLE001 — one item's failure, not the run's
        return await _fail_extend_item(wgp_id, f"EXTEND_DRIVE_FAILED:{_error_text(exc)}")

    terminal_failures = {_orch.F_INITIAL, _orch.F_EXTEND, _orch.F_FINAL, _orch.F_AUTH}
    # Not terminal, but the job cannot advance without a human. Fail THIS item
    # with that exact reason instead of polling until the timeout.
    stuck = {_orch.S_AUTH_EXPIRED, _orch.S_INITIAL_RECOVERY}

    state: dict = {}
    status = ""
    waited = 0
    while waited < _JOB_TIMEOUT_SECONDS:
        try:
            state = await _orch.get_job_status(job_id) or {}
        except Exception as exc:  # noqa: BLE001
            return await _fail_extend_item(
                wgp_id, f"EXTEND_STATUS_UNAVAILABLE:{_error_text(exc)}")
        status = str(state.get("status") or "")
        if status == _orch.S_COMPLETE or status in terminal_failures or status in stuck:
            break
        await asyncio.sleep(_POLL_SECONDS)
        waited += _POLL_SECONDS
    else:
        return await _fail_extend_item(
            wgp_id, f"EXTEND_JOB_TIMEOUT:{status or 'UNKNOWN'}")

    if status == _orch.S_COMPLETE:
        media_id = state.get("final_media_id")
        await crud.link_artifacts_to_generation_package(job_id, wgp_id)
        # GENERATED, not DOWNLOADED: get_job_status reports the final media id but
        # not a local path, and a download must never be claimed without evidence.
        await crud.update_workspace_generation_package(
            wgp_id,
            production_status="GENERATED",
            artifact_media_ids_json=_json([media_id] if media_id else []),
            production_error=None,
        )
        return {"ok": True, "job_id": job_id}

    # Real terminal reason, carrying the orchestrator's own error_code when it has
    # one — never a generic failure string.
    detail = str(state.get("error_code") or "").strip()
    return await _fail_extend_item(
        wgp_id, f"{status}:{detail}" if detail else status)


async def _cancel_remaining(run_id: str) -> None:
    items = await crud.list_production_queue_packages(
        production_run_id=run_id, production_status="QUEUED",
    )
    for item in items:
        await crud.update_workspace_generation_package(
            item["workspace_generation_package_id"], production_status="CANCELLED",
        )


async def get_production_run_detail(run_id: str) -> dict | None:
    run = await crud.get_production_run(run_id)
    if not run:
        return None
    items = await crud.list_production_queue_packages(production_run_id=run_id)
    run["items"] = [
        {
            "package_id": i["workspace_generation_package_id"],
            "product_id": i.get("product_id"),
            "product_name_snapshot": i.get("product_name_snapshot"),
            "logical_mode": i.get("logical_mode") or i.get("mode"),
            "production_status": i.get("production_status"),
            "production_job_id": i.get("production_job_id"),
            "production_error": i.get("production_error"),
            "artifact_media_ids": _loads(i.get("artifact_media_ids_json"), []),
            "sent_to_production_at": i.get("sent_to_production_at"),
        }
        for i in items
    ]
    return run
