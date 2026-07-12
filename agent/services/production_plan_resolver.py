"""Resolve the COMPLETE, fingerprint-bound authority a full-video job runs.

Production planning must carry every authority field, and the exact initial +
continuation prompts must be resolved and fingerprinted BEFORE authorization
(never a generic runtime fallback).

Authority sources (all proven, reused — nothing re-implemented):
  * persisted execution package  → model / aspect / mode / product asset (id +
    fingerprint + media id) and the compiled product-truth initial prompt;
  * `compile_workspace_prompt_preview` (the one compile door) → per-block prompt
    text: block 1 `initial_generation_prompt_text`, block N>=2
    `flow_extend_prompt_text` (the reviewed continuation prompt for that segment).

Server-side SSOT (PR316): in production (`trust_client_authority=False`) the
client CANNOT override product/asset/prompt authority — those fields are dropped
and re-resolved from the execution package, so a hand-crafted request can never
swap the product or prompt. `trust_client_authority=True` is for hermetic tests
and the explicit recovery path only.

Fingerprint integrity (PR316): every prompt fingerprint is ALWAYS recomputed
server-side from the canonical text. A supplied fingerprint is only an *expected*
value — a mismatch is rejected (never trusted as authority).
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

# Asset authority applies only to IMAGE-anchored initials — a T2V (text-only)
# block-1 has, by contract, ZERO reference images and no asset media id.
_IMAGE_MODE_ONLY_AUTHORITY = (
    "approved_asset_id", "approved_asset_sha256", "initial_asset_media_id",
)

# Authority the client may NOT set in production — always resolved server-side.
_CLIENT_OVERRIDABLE_AUTHORITY = (
    "approved_asset_id", "approved_asset_sha256", "initial_asset_media_id",
    "initial_reference_media_ids", "initial_source_mode",
    "initial_mode", "model", "aspect_ratio", "initial_prompt_text",
    "initial_prompt_fingerprint", "continuation_prompts",
)

_SEGMENT_SECONDS = 8
_MIN_DURATION = 16  # a full-video job is at least an initial + one extend
# Compiled 9-section block header — >1 occurrence means a MULTI-block document,
# which must never be submitted as one generation prompt.
_BLOCK_HEADER_MARKER = "SECTION 1 - ROLE & OBJECTIVE"
# The INITIAL block of a full VIDEO job must itself be a video (it is what the native
# Extend chain continues) — IMG is never a valid block-1 mode here.
_VIDEO_START_MODES = {"T2V", "I2V", "F2V"}

FINGERPRINT_MISMATCH = "PROMPT_FINGERPRINT_MISMATCH"


def _fp(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def duration_is_valid(seconds: int) -> bool:
    """A Native-Extend timeline is an exact sum of 8s blocks, >= one extend."""
    return seconds >= _MIN_DURATION and seconds % _SEGMENT_SECONDS == 0


def _ordered_reference_media_ids(resolved_assets: list[dict],
                                 primary: dict | None) -> list[str]:
    """ORDERED Flow media ids for the initial generation: the anchoring product
    asset first (start-frame role), then the remaining package assets in their
    stored order. Preserves the user's selection exactly — nothing is silently
    dropped or added; count violations fail closed downstream."""
    ordered: list[str] = []
    rest = [a for a in (resolved_assets or []) if a is not primary]
    for asset in ([primary] if primary else []) + rest:
        mid = _clean((asset or {}).get("media_id"))
        if mid and mid not in ordered:
            ordered.append(mid)
    return ordered


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


class AuthorityMismatchError(ValueError):
    """A supplied fingerprint did not match the canonical prompt text."""
    def __init__(self, detail: str) -> None:
        self.code = FINGERPRINT_MISMATCH
        self.detail = detail
        super().__init__(f"{FINGERPRINT_MISMATCH}:{detail}")


async def resolve_production_authority(
    intent: dict[str, Any], *, trust_client_authority: bool = False,
) -> dict[str, Any]:
    """Return a complete authority dict (+ `missing` list). Never raises for a
    merely-incomplete plan — the caller decides (422). Raises AuthorityMismatchError
    only when a supplied fingerprint contradicts its prompt text.

    trust_client_authority=False (production): client-supplied product/asset/prompt
    authority is DROPPED and re-resolved from the execution package (SSOT).
    """
    out: dict[str, Any] = dict(intent)
    if not trust_client_authority:
        for k in _CLIENT_OVERRIDABLE_AUTHORITY:
            out.pop(k, None)

    duration = int(intent.get("requested_duration_seconds") or 16)
    out["requested_duration_seconds"] = duration
    out["duration_valid"] = duration_is_valid(duration)
    segment_count = max(2, duration // _SEGMENT_SECONDS)
    out["segment_count"] = segment_count
    extend_ops = segment_count - 1
    out["operation_counts"] = {
        "initial_generation": 1, "extend": extend_ops, "final_render": 1,
        "total": 1 + extend_ops + 1,
    }
    if not _clean(out.get("engine")):
        out["engine"] = "GOOGLE_FLOW"

    # ── base authority from the persisted execution package (SSOT) ───────────
    pkg = None
    exec_pkg_id = _clean(intent.get("execution_package_id"))
    if exec_pkg_id:
        from agent.db import crud
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
            # ONE generation = ONE block. `pkg.prompt_text` is the FULL compiled
            # document — for a multi-block (EXTEND) package it joins every block,
            # and submitting that made the Flow agent propose one generation per
            # block (live incident). Accept it only when single-block; otherwise
            # leave empty so _compile_block_prompts resolves the exact block-1 text.
            pkg_prompt = pkg.get("prompt_text") or ""
            if pkg_prompt.count(_BLOCK_HEADER_MARKER) <= 1:
                out["initial_prompt_text"] = pkg_prompt
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
        # The package's ordered resolved assets ARE the user's reference
        # selection: block-1 sends EXACTLY this list (anchor first) — nothing is
        # ever silently dropped, added, or reduced downstream.
        if not isinstance(out.get("initial_reference_media_ids"), list):
            ordered = _ordered_reference_media_ids(resolved_assets, asset)
            if ordered:
                out["initial_reference_media_ids"] = ordered
        # SERVER-OWNED source-mode authority (PR321 closure): derived from the
        # package's persisted compiler lineage — a client declaration was already
        # stripped above and can never relax the per-mode reference contract.
        if not _clean(out.get("initial_source_mode")):
            from agent.services import flow_mode_reference_contract as _refc_sm
            out["initial_source_mode"] = _refc_sm.derive_package_source_mode(pkg)

    # T2V asset-authority relaxation applies only to an EXPLICIT text-only mode
    # (package/intent declared) — never to the incomplete-plan fallback below,
    # which must keep reporting the missing asset authority.
    out["initial_mode_explicit"] = _clean(out.get("initial_mode")) in _VIDEO_START_MODES

    # Block-1 make_video mode: a start image → I2V, else T2V. Never IMG.
    if not _clean(out.get("initial_mode")) or out.get("initial_mode") not in _VIDEO_START_MODES:
        out["initial_mode"] = "I2V" if _clean(out.get("initial_asset_media_id")) else "T2V"

    # ── ORDERED initial reference list (same contract as one-block generation) ──
    refs = out.get("initial_reference_media_ids")
    if not isinstance(refs, list):
        refs = ([out["initial_asset_media_id"]]
                if _clean(out.get("initial_asset_media_id")) else [])
    refs = [str(m) for m in refs if _clean(m)]
    if (_clean(out.get("initial_mode")).upper() == "T2V"
            and out.get("initial_mode_explicit") and trust_client_authority):
        # RECOVERY/trust path only: stale client-supplied image junk on an explicit
        # text-only intent is cleared. In PRODUCTION the refs come from the package
        # itself — a T2V package carrying references is a contract violation and
        # REJECTS below (never silently cleared, never attached).
        refs = []
    out["initial_reference_media_ids"] = refs
    if refs and not _clean(out.get("initial_asset_media_id")):
        out["initial_asset_media_id"] = refs[0]

    # ── per-block reviewed prompts (initial + continuations) ─────────────────
    supplied_conts = out.get("continuation_prompts") if trust_client_authority else None
    out["continuation_prompts"] = (
        _normalize_continuations(supplied_conts) if supplied_conts else None)
    if (not _clean(out.get("initial_prompt_text")) or not out.get("continuation_prompts")) \
            and _clean(out.get("product_id")):
        await _compile_block_prompts(out, segment_count)

    # ── fingerprints ALWAYS recomputed server-side; supplied only compared ───
    text = _clean(out.get("initial_prompt_text"))
    supplied_ifp = _clean(intent.get("initial_prompt_fingerprint")) if trust_client_authority else ""
    if text:
        computed = _fp(text)
        if supplied_ifp and supplied_ifp != computed:
            raise AuthorityMismatchError(
                "initial_prompt_fingerprint does not match initial_prompt_text")
        out["initial_prompt_fingerprint"] = computed
    conts = out.get("continuation_prompts") or []
    out["continuation_prompt_fingerprints"] = [c["fingerprint"] for c in conts]

    out["missing"] = _missing_fields(out, extend_ops)
    return out


def _normalize_continuations(items: list[dict]) -> list[dict]:
    """Normalize supplied continuations; the fingerprint is ALWAYS recomputed from
    the prompt text (a supplied fingerprint that disagrees is rejected)."""
    norm = []
    for i, item in enumerate(items):
        prompt = _clean(item.get("prompt"))
        if not prompt:
            continue
        computed = _fp(prompt)
        supplied = _clean(item.get("fingerprint"))
        if supplied and supplied != computed:
            raise AuthorityMismatchError(
                f"continuation fingerprint at position {i + 1} does not match its prompt")
        norm.append({
            "position": int(item.get("position") or (i + 1)),
            "block_index": int(item.get("block_index") or (i + 2)),
            "prompt": prompt,
            "fingerprint": computed,
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
    from agent.services import flow_mode_reference_contract as _refc
    mode = _clean(out.get("initial_mode")).upper()
    explicit_t2v = mode == "T2V" and bool(out.get("initial_mode_explicit"))
    required = [f for f in REQUIRED_AUTHORITY
                if not (explicit_t2v and f in _IMAGE_MODE_ONLY_AUTHORITY)]
    missing = [f for f in required if not _clean(out.get(f))]
    conts = out.get("continuation_prompts") or []
    if len(conts) < extend_ops:
        missing.append("continuation_prompts")
    if not out.get("duration_valid"):
        missing.append("valid_duration_plan")
    # fail-closed: the initial prompt must be exactly ONE block
    if (out.get("initial_prompt_text") or "").count(_BLOCK_HEADER_MARKER) > 1:
        missing.append("single_block_initial_prompt")
    # ── per-mode reference contract (fail-closed, zero credit) ───────────────
    # When the USER's surface mode is known (execution package / explicit
    # intent) the full contract applies; otherwise (recovery/legacy intents)
    # only the transport hard caps — proven single-image flows stay valid.
    refs = out.get("initial_reference_media_ids") or []
    source_mode = _clean(out.get("initial_source_mode")) or None
    if source_mode or mode == "T2V":
        ok, _code, detail = _refc.validate_reference_count(
            mode, len(refs), source_mode=source_mode)
    else:
        detail = _refc.service_hard_violation(mode, len(refs))
        ok = detail is None
    if not ok:
        missing.append(f"initial_reference_contract ({detail})")
    return missing
