"""Bulk-import the COPYWRITING HUB sheet into product-intelligence review DRAFTS.

This is the mechanical scale-up of the CP7 proof: for every HUB row that matches
a catalog product, assemble a MULTI-ANGLE persona from the row's own
avatar/pain/dream/emotion and create a review DRAFT. Reuses the existing HUB
parser (`parse_copy_intelligence_hub`) and the validated draft-creation path
(`create_review_draft`) — no new parsing, no parallel store.

HARD BOUNDARIES (fail-closed, mirror the rest of the copy lane):
  * NEVER auto-approves. Drafts land NEEDS_REVISION / DRAFT and must pass the
    existing draft->snapshot gate (incl. the claim floor for HIGH-risk products).
  * IDEMPOTENT. A product that already has an APPROVED snapshot or a live
    (non-rejected) draft is SKIPPED — re-running never duplicates.
  * NO invented product FACTS. Only the row's own avatar/pain/dream/features
    become persona + light knowledge. ingredients / usage / warnings are LEFT
    EMPTY on purpose — those are the claim-critical fields the workbook does not
    carry, so the draft stays incomplete until a human (or verified research)
    fills them. The importer does the bulk persona/angle work; it does not
    pretend to know a product's ingredients.
  * Why multi-angle: the legacy seed-promotion path used the single Pain Point
    as the only angle, which reproduces the exact per-product monoculture this
    whole workstream exists to remove. Here the angle set is the row's Pain
    Point PLUS each distinct Dream Outcome line, so a product gets several real
    angles to compose across.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.services.kalodata_import_service import (
    _normalize_name,
    parse_copy_intelligence_hub,
)

__all__ = [
    "derive_angle_themes",
    "build_persona",
    "build_knowledge_fields",
    "import_hub_to_drafts",
    "MAX_ANGLES",
]

MAX_ANGLES = 5
SOURCE = "COPYWRITING_HUB_BULK_IMPORT"


def _lines(text: Any) -> list[str]:
    if not text:
        return []
    return [ln.strip() for ln in re.split(r"[\r\n]+", str(text)) if ln.strip()]


def _split_soft(text: Any) -> list[str]:
    """Split emotion/feature strings on commas/newlines into distinct tokens."""
    if not text:
        return []
    return [p.strip() for p in re.split(r"[,\n\r;/]+", str(text)) if p.strip()]


def derive_angle_themes(record: dict[str, Any]) -> list[str]:
    """Pain Point + each distinct Dream Outcome line, deduped, capped.

    These become the persona `pains` — the axis Phase A rotates over. Pure text
    from the row; nothing invented. A theme too short to be meaningful (<5 chars)
    or a duplicate is dropped.
    """
    themes = _lines(record.get("pain_point")) + _lines(record.get("dream_outcome"))
    seen: set[str] = set()
    out: list[str] = []
    for t in themes:
        key = _normalize_name(t)
        if key and len(t) > 4 and key not in seen:
            seen.add(key)
            out.append(t)
    return out[:MAX_ANGLES]


def build_persona(record: dict[str, Any]) -> dict[str, Any]:
    audience = str(record.get("target_avatar") or "").strip()
    dreams = _lines(record.get("dream_outcome"))
    return {
        "audience": audience,
        "pains": derive_angle_themes(record),
        "desires": dreams,
        "triggers": _split_soft(record.get("emotion_trigger")),
        "tone": str(record.get("tone") or "").strip() or "mesra, meyakinkan",
        "pronoun": str(record.get("pronoun") or "").strip() or "anda",
    }


def build_knowledge_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Light product knowledge from the row. Deliberately leaves ingredients /
    usage / warnings EMPTY — those are claim-critical and not in the workbook."""
    name = str(record.get("source_product_name") or "").strip()
    features = str(record.get("key_ingredients_features") or "").strip()
    dreams = _lines(record.get("dream_outcome"))
    desc = name + ((". " + features) if features else "")
    return {
        "product_description": desc or None,
        "benefits_json": dreams or None,
        "usp_json": _split_soft(features) or None,
        "target_customer_text": str(record.get("target_avatar") or "").strip() or None,
    }


def _reviewer_note(record: dict[str, Any]) -> str:
    return (
        f"BULK-IMPORTED from COPYWRITING HUB row {record.get('source_row')} "
        f"(owner workbook). Persona angles = Pain Point + Dream Outcome lines "
        f"(the row's own copy intelligence, restructured — nothing invented). "
        f"Product knowledge is LIGHT: description/benefits/usp from the row; "
        f"ingredients / usage / warnings LEFT EMPTY on purpose — they are "
        f"claim-critical and not in the workbook, so fill them (owner or verified "
        f"research) before approving. Review-only draft; must pass the "
        f"draft->snapshot gate (incl. the claim floor for HIGH-risk products)."
    )


async def _already_has_intelligence(product_id: str) -> bool:
    """Approved snapshot OR a live (non-rejected) draft -> skip, idempotent.

    Reads crud directly (not the service wrapper) so the bulk loop does not pay
    an extra product-existence fetch per product across hundreds of rows.
    """
    from agent.db import crud

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    if snap:
        return True
    rows = await crud.list_product_intelligence_review_drafts(product_id=product_id, limit=20)
    return any(str((r or {}).get("review_status", "")) not in ("REJECTED", "") for r in (rows or []))


async def import_hub_to_drafts(
    path: str | Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Create review drafts for every HUB row that matches a catalog product.

    Returns a report: matched / created / skipped_existing / unmatched, plus a
    small sample. `dry_run` matches + assembles but writes nothing.
    """
    from agent.db import crud
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftCreateRequest,
    )
    from agent.services import product_intelligence_review_draft_service as draft_svc

    records = parse_copy_intelligence_hub(Path(path))

    products = await crud.list_products(limit=10000, include_archived=False)
    by_name: dict[str, str] = {}
    for p in products:
        nm = _normalize_name(str(p.get("product_display_name") or p.get("raw_product_title") or ""))
        if nm and nm not in by_name:
            by_name[nm] = p["id"]

    matched = created = skipped = unmatched = 0
    no_angles = 0
    samples: list[dict[str, Any]] = []

    for rec in records:
        if limit is not None and created >= limit and not dry_run:
            break
        pid = by_name.get(_normalize_name(str(rec.get("source_product_name") or "")))
        if not pid:
            unmatched += 1
            continue
        matched += 1

        persona = build_persona(rec)
        if not persona["pains"]:
            no_angles += 1
            continue

        if await _already_has_intelligence(pid):
            skipped += 1
            continue

        if dry_run:
            if len(samples) < 5:
                samples.append({
                    "product_id": pid,
                    "name": str(rec.get("source_product_name"))[:60],
                    "angles": persona["pains"],
                })
            created += 1  # would-create count under dry-run
            continue

        knowledge = build_knowledge_fields(rec)
        strategy = {
            "hook": str(rec.get("hook_script") or "").strip() or None,
            "cta": str(rec.get("cta_script") or "").strip() or None,
            "source": SOURCE,
        }
        # Only pass fields that carry a real value. The model forbids extras and
        # create_review_draft dumps with exclude_unset over a product-seeded
        # payload, so passing an explicit None would CLOBBER a seeded default.
        fields: dict[str, Any] = {
            "buyer_persona_snapshot_json": persona,
            "copy_strategy_summary_json": strategy,
            "paste_anything_summary": (
                "COPYWRITING HUB import — workbook evidence (review before approving):\n"
                f"Avatar: {rec.get('target_avatar') or '-'}\n"
                f"Pain: {rec.get('pain_point') or '-'}\n"
                f"Dream: {rec.get('dream_outcome') or '-'}\n"
                f"Features: {rec.get('key_ingredients_features') or '-'}\n"
                f"Hook: {rec.get('hook_script') or '-'}\n"
                f"CTA: {rec.get('cta_script') or '-'}"
            ),
            "reviewer_note": _reviewer_note(rec),
            "created_by": SOURCE,
            "product_description": knowledge["product_description"],
            "benefits_json": knowledge["benefits_json"],
            "usp_json": knowledge["usp_json"],
            "target_customer_text": knowledge["target_customer_text"],
        }
        request = ProductIntelligenceReviewDraftCreateRequest(
            **{k: v for k, v in fields.items() if v is not None}
        )
        try:
            draft = await draft_svc.create_review_draft(pid, request)
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the batch
            skipped += 1
            continue
        created += 1
        if len(samples) < 5:
            samples.append({
                "product_id": pid,
                "name": str(rec.get("source_product_name"))[:60],
                "draft_id": draft.draft_id,
                "review_status": draft.review_status,
                "angles": persona["pains"],
            })

    return {
        "source": str(path),
        "hub_rows": len(records),
        "matched": matched,
        "created": created,
        "skipped_existing": skipped,
        "unmatched": unmatched,
        "rows_without_angles": no_angles,
        "dry_run": bool(dry_run),
        "samples": samples,
    }
