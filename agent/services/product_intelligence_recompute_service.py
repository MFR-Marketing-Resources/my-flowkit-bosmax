"""Recompute Product Intelligence for an EXISTING product from its stored source link.

    stored product (by id)
      -> its stored tiktok_product_url / source_url
      -> deterministic TikTok extraction
      -> ensure_product_intelligence (reuses the product's OPEN draft)
      -> exact per-field provenance
      -> DeepSeek candidates for the fields still empty
      -> review-required draft

WHY THIS EXISTS SEPARATELY FROM /import-tiktokshop
That route is an INTAKE door: it calls `crud.create_product`. Pointing an operator at it to
refresh a product they already have would mint a duplicate catalogue row every time. This
service is product-ID scoped and never creates a product, never touches lifecycle, and
never opens a second draft — the B-586-04 UNIQUE index would reject the second one anyway,
which is the point of having made it a database rule.

WHAT IS A FACT AND WHAT IS A PROPOSAL
Extraction writes DECLARED evidence: values the page actually states, carrying per-field
provenance that records HOW each one was obtained (JSON-LD, meta tag, labelled section).
DeepSeek then fills only the fields still EMPTY, and those land with
`verification_status=AI_PROPOSED` — the same contract `ai_fill_missing_review_draft`
already uses, so a proposal is durable across a reload and still visibly unratified.
Neither path approves anything: an approved snapshot is only ever produced by the operator
pressing Approve.
"""
from __future__ import annotations

import json
from typing import Any

ERR_PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
ERR_NO_SOURCE_URL = "PRODUCT_HAS_NO_SOURCE_URL"

# Where a product's own source link may live, most specific first.
SOURCE_URL_FIELDS = ("tiktok_product_url", "source_url")

# Candidate source key -> review-draft column. DeepSeek may only ever fill these.
# Materials, warnings, size, price and commission are deliberately ABSENT: those are
# extracted from the page or declared by the operator, never generated.
CANDIDATE_TARGETS = {
    "product_description": "product_description",
    "benefits_text": "benefits_json",
    "usp_list": "usp_json",
    "usage_text": "usage_text",
    "target_customer_text": "target_customer_text",
    "package_notes": "package_notes",
    "product_form_factor": "product_form_factor",
    "packaging_description": "packaging_description",
}
_LIST_COLUMNS = ("benefits_json", "usp_json")


class RecomputeError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def resolve_source_url(product: dict[str, Any]) -> str | None:
    for field in SOURCE_URL_FIELDS:
        value = str(product.get(field) or "").strip()
        if value:
            return value
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return str(value).strip() not in ("", "[]", "{}")


def _coerce(column: str, value: Any) -> Any:
    if column in _LIST_COLUMNS:
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace("\r", "").split("\n") if p.strip()]
            return parts or [value.strip()]
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()] if str(value).strip() else []
    return str(value).strip()


async def _persist_candidates(draft_id: str, product_id: str,
                              candidates: dict[str, Any]) -> dict[str, Any]:
    """Store proposals as review-required draft values with AI provenance.

    Only fields the draft leaves EMPTY are filled. Overwriting a value a human already
    reviewed with a fresh model guess would quietly undo their work, so an occupied field
    is reported as skipped rather than replaced.
    """
    from agent.db import crud
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftUpdateRequest,
    )
    from agent.services import ai_copy_provider_adapter as provider
    from agent.services.product_intelligence_review_draft_service import (
        get_review_draft_by_id,
        update_review_draft,
    )

    draft = await get_review_draft_by_id(draft_id)
    if draft is None:
        return {"proposed": [], "skipped": []}

    provider_id = model_id = None
    try:
        status = provider.provider_status()
        provider_id, model_id = status.get("provider_id"), status.get("model_id")
    except Exception:  # noqa: BLE001 - receipt metadata only
        pass

    updates: dict[str, Any] = {}
    proposed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    from agent.services.tiktokshop_extraction_service import is_marketplace_boilerplate

    for source_key, value in (candidates or {}).items():
        column = CANDIDATE_TARGETS.get(source_key)
        if not column or not _has_value(value):
            continue
        if _has_value(getattr(draft, column, None)):
            skipped.append({"field": column, "reason": "EXISTING_EVIDENCE_PRESERVED"})
            continue
        # B-08B-D1: an EMPTY description may only be filled with product-specific text.
        # The model's brief contains the listing's og:description, so a lazy proposal can
        # be the marketplace SEO template verbatim — the same junk the extraction gate
        # rejects must not walk in through the candidate door instead.
        if column == "product_description" and is_marketplace_boilerplate(value):
            skipped.append({"field": column,
                            "reason": "REJECTED_MARKETPLACE_BOILERPLATE"})
            continue
        updates[column] = _coerce(column, value)
        proposed.append({"field": column, "value": updates[column]})

    if updates:
        await update_review_draft(
            draft_id, ProductIntelligenceReviewDraftUpdateRequest(**updates))
        for item in proposed:
            await crud.create_product_intelligence_review_field_provenance(
                draft_id=draft_id,
                product_id=product_id,
                field_name=item["field"],
                source_type="AI_ENRICHMENT",
                evidence_kind="MODEL_PROPOSED_CANDIDATE",
                extraction_method=f"deepseek:{model_id or 'unknown'}",
                # NOT PENDING_REVIEW: a machine proposal and an operator's own typing must
                # not be indistinguishable in the evidence table.
                verification_status="AI_PROPOSED",
                declared_value=json.dumps(item["value"], ensure_ascii=False,
                                          default=str),
                source_lane=provider.LANE,
                reviewer_note=("tiktokshop_recompute | grounded in acquired listing "
                               f"evidence | provider={provider_id} model={model_id}"),
            )
    return {"proposed": proposed, "skipped": skipped,
            "provider": provider_id, "model": model_id}


async def acquire_extraction(source_url: str, *, propose: bool,
                             allow_browser_relay: bool) -> dict[str, Any]:
    """Direct fetch first; the authenticated browser relay when the anonymous fetch cannot
    show us the listing.

    The order is deliberate. A plain HTTPS GET costs nothing, needs no browser and no
    operator, and still works for any listing TikTok serves anonymously — so it stays the
    default. The relay is the EXCEPTION path.

    RELAY_TRIGGER_CODES — the two direct-fetch failures that mean "we were never shown the
    real listing", both of which the AUTHENTICATED tab can still read:
      * AUTHENTICATED_BROWSER_REQUIRED — TikTok served the anonymous fetcher a Security
        Check shell;
      * NO_EVIDENCE — TikTok served the anonymous fetcher a NON-challenge empty page (its
        anti-bot does this for real, readable products). Treating that as a dead source
        wrongly hid readable products behind the anonymous fetch; the authenticated tab
        reads them. (Live-proven on the PI-10 trust test.)
    EVERY OTHER direct-fetch error (bad content type, a genuinely dead link, a host we do
    not support) is a real source defect and is raised UNCHANGED. Only ONE relay attempt is
    made — no fallback loop. A failed relay acquisition raises out of here before anything is
    written, so it can never mutate a PI row.
    """
    import asyncio

    from agent.services import tiktokshop_browser_relay as relay
    from agent.services import tiktokshop_extraction_service as tiktok

    relay_trigger_codes = {
        tiktok.ERR_AUTHENTICATED_BROWSER_REQUIRED,
        tiktok.ERR_NO_EVIDENCE,
    }

    try:
        # Synchronous httpx off the event loop: on this single-process agent an inline fetch
        # stalls /health for its whole duration (the PR #404 starvation).
        extraction = await asyncio.to_thread(
            tiktok.extract_product, source_url, propose=propose)
        extraction.setdefault("acquisition_mode", "DIRECT_FETCH")
        return extraction
    except tiktok.TikTokShopExtractionError as exc:
        if exc.code not in relay_trigger_codes or not allow_browser_relay:
            raise
        if not relay.relay_supports_url(source_url):
            # Honest refusal rather than "open the tab and retry", which would be advice
            # that can never succeed: the manifest grants the content script exactly two
            # TikTok Shop hosts and this link is on neither.
            raise relay.TikTokRelayError(
                relay.ERR_HOST_NOT_SUPPORTED, source_url[:200],
                product_url=source_url) from exc
        # navigate=True: drive the ONE dedicated evidence tab to this product's stored,
        # id-verified URL, then read it — so the unattended bulk no longer depends on the
        # operator opening every tab by hand. The reader path (operator-opened tab) stays
        # available via navigate=False for anyone who still wants it.
        return await relay.extract_product_via_browser(
            source_url, propose=propose, navigate=True)


async def recompute_product_intelligence(
    product_id: str, *, propose: bool = True, allow_browser_relay: bool = True,
) -> dict[str, Any]:
    """The whole existing-product lane. Never creates a product."""
    from agent.db import crud
    from agent.services.product_intake_service import (
        ensure_product_intelligence,
        evidence_from_product_payload,
    )

    product = await crud.get_product(product_id)
    if not product:
        raise RecomputeError(ERR_PRODUCT_NOT_FOUND, product_id)
    source_url = resolve_source_url(product)
    if not source_url:
        raise RecomputeError(ERR_NO_SOURCE_URL, product_id)

    # NOTHING is written before this returns. Every acquisition failure — walled, empty,
    # relay unavailable — raises out of here, so a failed Recompute cannot blank a field,
    # open a draft or leave a provenance row behind.
    extraction = await acquire_extraction(
        source_url, propose=propose, allow_browser_relay=allow_browser_relay)

    extracted = dict(extraction.get("fields") or {})
    # raw_product_title / brand / price / currency / image_url are PRODUCT columns, not
    # intelligence. Recompute deliberately does not rewrite the operator's product row.
    evidence_payload = {k: v for k, v in extracted.items()
                        if k not in ("raw_product_title", "brand", "price", "currency")}

    # B-08B-D1 second half: a refresh FILLS, it never REPLACES. The intake seam applies
    # every non-blank payload field over the open draft, which is right for first intake
    # and wrong for a recompute — on the first live pilot it swapped three curated
    # descriptions for TikTok's og:description. Divergent extracted text is therefore
    # reported as skipped (value shown to the reviewer in the response) rather than
    # silently replacing stored evidence. Fields the draft leaves empty still fill —
    # that is the legitimate purpose of a recompute.
    from agent.services import tiktokshop_extraction_service as tiktok_svc
    from agent.services.product_intake_service import _latest_open_draft

    evidence_skipped: list[dict[str, Any]] = []
    open_draft, _terminal = await _latest_open_draft(product_id)
    if open_draft:
        for source_key in [k for k in evidence_payload if k != "image_url"]:
            target = tiktok_svc._SOURCE_KEY_TO_TARGET.get(source_key)  # noqa: SLF001
            if target and _has_value(open_draft.get(target)):
                evidence_skipped.append({
                    "field": target,
                    "reason": "EXISTING_EVIDENCE_PRESERVED",
                    "extracted_value_not_stored":
                        str(evidence_payload.pop(source_key))[:400],
                })

    evidence_payload["source_url"] = extraction.get("source_url") or source_url

    intake = await ensure_product_intelligence(
        product_id,
        evidence_from_product_payload(
            evidence_payload, lane="PRODUCTS_TIKTOKSHOP_RECOMPUTE",
            field_overrides=extraction.get("field_provenance_overrides") or {}),
        lane="PRODUCTS_TIKTOKSHOP_RECOMPUTE",
    )

    draft_id = intake.get("intelligence_draft_id")
    candidate_result: dict[str, Any] = {"proposed": [], "skipped": []}
    if draft_id and propose and extraction.get("candidates"):
        candidate_result = await _persist_candidates(
            str(draft_id), product_id, extraction.get("candidates") or {})

    return {
        "product_id": product_id,
        "draft_id": draft_id,
        "source_url": extraction.get("source_url") or source_url,
        "intake_outcome": intake.get("outcome"),
        "extracted_fields": extracted,
        # Fields where the page stated a value but the draft's existing evidence won.
        # Surfaced (with the discarded text) so a reviewer can adopt it deliberately;
        # hiding it would make preservation indistinguishable from a failed extraction.
        "evidence_skipped": evidence_skipped,
        "unresolved": extraction.get("unresolved") or {},
        "variant": extraction.get("variant"),
        "variant_resolution": extraction.get("variant_resolution"),
        "size_resolution": extraction.get("size_resolution"),
        "evidence_methods": extraction.get("evidence_methods") or [],
        "candidate_status": extraction.get("candidate_status"),
        "candidates_persisted": candidate_result.get("proposed") or [],
        "candidates_skipped": candidate_result.get("skipped") or [],
        "provider": candidate_result.get("provider"),
        "model": candidate_result.get("model"),
        "refused_model_fields": extraction.get("refused_model_fields") or [],
        # DIRECT_FETCH or AUTHENTICATED_BROWSER_RELAY — recorded because "where this
        # evidence came from" is a reviewable fact, not an implementation detail.
        "acquisition_mode": extraction.get("acquisition_mode") or "DIRECT_FETCH",
        "relay": extraction.get("relay"),
        # never set here — an approved snapshot is only ever produced by the operator
        "approved": False,
    }
