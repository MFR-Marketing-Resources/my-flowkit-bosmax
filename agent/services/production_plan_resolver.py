"""Resolve the COMPLETE, fingerprint-bound authority a full-video job runs.

Mission 2/3 of the PR315 final wiring: production planning must carry every
authority field, and the exact initial + continuation prompts must be resolved
and fingerprinted BEFORE authorization (never a generic runtime fallback).

Authority sources (all proven, reused — nothing re-implemented):
  * persisted execution package  → model / aspect / mode / product asset (id +
    fingerprint + media id) and the compiled product-truth initial prompt;
  * `compile_workspace_prompt_preview` (the one compile door) → per-block prompt
    text: block 1 `initial_generation_prompt_text`, block N>=2
    `flow_extend_prompt_text` (the reviewed continuation prompt for that segment).

Contract: explicitly-supplied intent values WIN (hermetic tests pass a complete
authority set and never touch the DB / compiler). Anything still missing after
resolution is reported in `missing` — the caller fails closed with a structured
422 and never issues an authorization for an incomplete plan.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Fields the caller (plan_job / API) treats as REQUIRED production authority.
REQUIRED_AUTHORITY = (
    "product_id", "execution_package_id", "approved_asset_id",
    "approved_asset_sha256", "initial_asset_media_id", "initial_mode",
    "initial_prompt_text", "initial_prompt_fingerprint",
    "engine", "model", "aspect_ratio", "requested_duration_seconds",
)

_SEGMENT_SECONDS = 8
# The INITIAL block of a full VIDEO job must itself be a video (it is what the native
# Extend chain continues) — IMG is never a valid block-1 mode here.
_VIDEO_START_MODES = {"T2V", "I2V", "F2V"}


def _fp(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _primary_product_asset(resolved_assets: list[dict]) -> dict | None:
    """The product-image asset that anchors block-1 generation (its Flow media id
    is the I2V start frame). Prefer an explicit product-image asset id."""
    if not resolved_assets:
        return None
    for asset in resolved_assets:
        if _clean(asset.get("asset_id")).startswith("product-image:"):
            return asset
    for asset in resolved_assets:
        if asset.get("media_id") and asset.get("asset_fingerprint"):
            return asset
    return resolved_assets[0]


async def resolve_production_authority(intent: dict[str, Any]) -> dict[str, Any]:
    """Return a complete authority dict (+ `missing` list). Never raises for a
    merely-incomplete plan — the caller decides (422). Explicit intent wins."""
    from agent.db import crud

    out: dict[str, Any] = dict(intent)
    duration = int(intent.get("requested_duration_seconds") or 16)
    out["requested_duration_seconds"] = duration
    segment_count = max(2, duration // _SEGMENT_SECONDS)
    out["segment_count"] = segment_count
    extend_ops = segment_count - 1
    out["operation_counts"] = {
        "initial_generation": 1, "extend": extend_ops, "final_render": 1,
        "total": 1 + extend_ops + 1,
    }
    out.setdefault("engine", None)
    if not _clean(out.get("engine")):
        out["engine"] = "GOOGLE_FLOW"

    # ── base authority from the persisted execution package ──────────────────
    pkg = None
    exec_pkg_id = _clean(intent.get("execution_package_id"))
    if exec_pkg_id:
        pkg = await crud.get_workspace_execution_package(exec_pkg_id)
    if pkg:
        if not _clean(out.get("model")):
            out["model"] = pkg.get("model")
        if not _clean(out.get("aspect_ratio")):
            out["aspect_ratio"] = pkg.get("aspect_ratio")
        if not _clean(out.get("initial_mode")):
            out["initial_mode"] = pkg.get("mode")
        if not _clean(out.get("product_id")):
            out["product_id"] = pkg.get("product_id")
        if not _clean(out.get("initial_prompt_text")):
            out["initial_prompt_text"] = pkg.get("prompt_text")
        try:
            resolved_assets = json.loads(pkg.get("resolved_assets") or "[]")
        except (TypeError, ValueError):
            resolved_assets = []
        asset = _primary_product_asset(resolved_assets)
        if asset:
            if not _clean(out.get("approved_asset_id")):
                out["approved_asset_id"] = asset.get("asset_id")
            if not _clean(out.get("approved_asset_sha256")):
                out["approved_asset_sha256"] = asset.get("asset_fingerprint")
            if not _clean(out.get("initial_asset_media_id")):
                out["initial_asset_media_id"] = asset.get("media_id")

    # Block-1 make_video mode: a start image → I2V, else T2V. pkg.mode wins.
    if not _clean(out.get("initial_mode")) or out.get("initial_mode") not in _VIDEO_START_MODES:
        out["initial_mode"] = "I2V" if _clean(out.get("initial_asset_media_id")) else "T2V"

    # ── per-block reviewed prompts (initial + continuations) ─────────────────
    provided = intent.get("continuation_prompts")
    if provided:
        out["continuation_prompts"] = _normalize_continuations(provided)
    else:
        out["continuation_prompts"] = None
    if (not _clean(out.get("initial_prompt_text")) or not out.get("continuation_prompts")) \
            and _clean(out.get("product_id")):
        await _compile_block_prompts(out, segment_count)

    if _clean(out.get("initial_prompt_text")) and not _clean(out.get("initial_prompt_fingerprint")):
        out["initial_prompt_fingerprint"] = _fp(out["initial_prompt_text"])

    conts = out.get("continuation_prompts") or []
    out["continuation_prompt_fingerprints"] = [c["fingerprint"] for c in conts]

    out["missing"] = _missing_fields(out, extend_ops)
    return out


def _normalize_continuations(items: list[dict]) -> list[dict]:
    norm = []
    for i, item in enumerate(items):
        prompt = _clean(item.get("prompt"))
        if not prompt:
            continue
        norm.append({
            "position": int(item.get("position") or (i + 1)),
            "block_index": int(item.get("block_index") or (i + 2)),
            "prompt": prompt,
            "fingerprint": _clean(item.get("fingerprint")) or _fp(prompt),
            "is_final": bool(item.get("is_final")),
        })
    return norm


async def _compile_block_prompts(out: dict[str, Any], segment_count: int) -> None:
    """Reuse the one compile door to get block-1 initial + block-N continuation
    prompts. Fail-soft: on any compiler error the fields stay unset and land in
    `missing` (the caller then returns a structured 422 — no generic fallback)."""
    from agent.services.workspace_execution_package_service import (
        compile_workspace_prompt_preview,
    )
    mode = out.get("initial_mode") or "I2V"
    blocks = [{"block_index": i + 1, "duration_seconds": _SEGMENT_SECONDS}
              for i in range(segment_count)]
    try:
        compiled = await compile_workspace_prompt_preview(
            product_id=out["product_id"], mode=mode,
            duration_seconds=_SEGMENT_SECONDS, generation_mode="EXTEND",
            blocks=blocks,
            requested_total_duration_seconds=int(out["requested_duration_seconds"]),
        )
    except Exception:  # noqa: BLE001 — incomplete plan, not a crash
        return
    prompt_blocks = compiled.get("prompt_blocks") or []
    if not prompt_blocks:
        return
    first = prompt_blocks[0]
    if not _clean(out.get("initial_prompt_text")):
        out["initial_prompt_text"] = (
            _clean(first.get("initial_generation_prompt_text"))
            or _clean(first.get("engine_prompt_text")))
    if not out.get("continuation_prompts"):
        conts = []
        for block in prompt_blocks[1:]:
            text = _clean(block.get("flow_extend_prompt_text"))
            if not text:
                continue
            conts.append({
                "position": int(block.get("block_index") or 0) - 1,
                "block_index": int(block.get("block_index") or 0),
                "prompt": text,
                "fingerprint": _fp(text),
                "is_final": bool(block.get("is_final")),
            })
        out["continuation_prompts"] = conts or None


def _missing_fields(out: dict[str, Any], extend_ops: int) -> list[str]:
    missing = [f for f in REQUIRED_AUTHORITY if not _clean(out.get(f))]
    conts = out.get("continuation_prompts") or []
    if len(conts) < extend_ops:
        missing.append("continuation_prompts")
    return missing
