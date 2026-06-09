from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.models.product_registration import RegistrationReviewDraft
from agent.services.product_knowledge_service import complete_product_knowledge
from agent.services.product_registration_service import create_registration_review_draft


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_clean(entry) for entry in value) if item]
    if isinstance(value, str):
        return [item for item in (_clean(entry) for entry in value.splitlines()) if item]
    return []


def derive_draft_image_asset_state(
    declared_evidence_fields: dict[str, Any],
) -> tuple[str, str]:
    image_url = _clean(declared_evidence_fields.get("image_url"))
    local_image_path = _clean(declared_evidence_fields.get("local_image_path"))
    if local_image_path:
        candidate = Path(local_image_path)
        if candidate.exists():
            return "IMAGE_CACHE_READY", "Cached draft image is available locally."
        if image_url:
            return "IMAGE_REFERENCE_READY", "Image URL exists but the cached local file is not present."
    if image_url:
        return "IMAGE_REFERENCE_READY", "Image URL is available for draft review."
    return "IMAGE_REFERENCE_MISSING", "No draft image evidence is currently attached."


def _build_completion_request_from_draft(
    draft: RegistrationReviewDraft,
) -> ProductKnowledgeCompleteRequest:
    evidence = dict(draft.declared_evidence_fields or {})
    payload = {
        "product_name": evidence.get("product_name"),
        "product_knowledge_text": evidence.get("product_knowledge_text"),
        "benefits_text": evidence.get("benefits_text"),
        "usage_text": evidence.get("usage_text"),
        "target_customer_text": evidence.get("target_customer_text"),
        "ingredients_text": evidence.get("ingredients_text"),
        "warnings_text": evidence.get("warnings_text"),
        "price": evidence.get("price"),
        "currency": evidence.get("currency"),
        "commission_amount": evidence.get("commission_amount"),
        "commission_rate": evidence.get("commission_rate"),
        "size_or_volume": evidence.get("size_or_volume"),
        "package_notes": evidence.get("package_notes"),
        "source_lane": evidence.get("source_lane") or draft.source_lane,
        "image_url": evidence.get("image_url"),
        "product_url": evidence.get("product_url"),
        "source_url": evidence.get("source_url"),
        "tiktok_product_url": evidence.get("tiktok_product_url"),
        "tiktok_shop_url": evidence.get("tiktok_shop_url"),
        "local_image_path": evidence.get("local_image_path"),
        "paste_anything_about_product": evidence.get("paste_anything_about_product"),
        "category": evidence.get("category"),
        "allow_live_image_analysis": True,
    }
    return ProductKnowledgeCompleteRequest.model_validate(payload)


def recompute_review_draft(draft: RegistrationReviewDraft) -> RegistrationReviewDraft:
    completion = complete_product_knowledge(_build_completion_request_from_draft(draft))
    refreshed = create_registration_review_draft(completion)

    refreshed.review_draft_id = draft.review_draft_id
    refreshed.created_at = draft.created_at
    refreshed.source_lane = str(draft.declared_evidence_fields.get("source_lane") or draft.source_lane)
    refreshed.declared_evidence_fields = dict(draft.declared_evidence_fields or {})
    refreshed.user_actions = [
        "APPROVE_CANDIDATE_FIELD",
        "REJECT_CANDIDATE_FIELD",
        "SAVE_DRAFT_EVIDENCE",
        "RECOMPUTE_DRAFT",
        "UPLOAD_DRAFT_IMAGE",
        "CLEAR_DRAFT",
    ]
    refreshed.approval_checklist = {
        field: False for field in refreshed.canonical_candidate_fields.keys()
    }
    refreshed.rejection_checklist = {
        field: False for field in refreshed.canonical_candidate_fields.keys()
    }

    hook_override = _clean_list(refreshed.declared_evidence_fields.get("hook_angles"))
    if hook_override:
        refreshed.canonical_candidate_fields["hook_angles"] = hook_override
        refreshed.system_inferred_fields["hook_angles_source"] = "MANUAL_OVERRIDE"
    else:
        refreshed.system_inferred_fields["hook_angles_source"] = "GENERATED"

    cta_override = _clean_list(refreshed.declared_evidence_fields.get("cta_angles"))
    if cta_override:
        refreshed.canonical_candidate_fields["cta_angles"] = cta_override
        refreshed.system_inferred_fields["cta_angles_source"] = "MANUAL_OVERRIDE"
    else:
        refreshed.system_inferred_fields["cta_angles_source"] = "GENERATED"

    # AUTO-BACKFILL: promote system-suggested values into declared_evidence_fields
    # for any field that is currently empty/missing. This means the system fills
    # in what it already knows so the user never has to re-enter inferred data.
    _backfill_suggested_to_declared(refreshed, completion)

    image_asset_status, image_asset_detail = derive_draft_image_asset_state(
        refreshed.declared_evidence_fields,
    )
    refreshed.image_asset_status = image_asset_status
    refreshed.image_asset_detail = image_asset_detail
    refreshed.system_inferred_fields["image_asset_status"] = image_asset_status
    refreshed.system_inferred_fields["image_asset_detail"] = image_asset_detail

    now = _now()
    refreshed.last_evidence_edit_at = draft.last_evidence_edit_at or draft.updated_at or now
    refreshed.last_recomputed_at = now
    refreshed.draft_freshness_status = "FRESH"
    return refreshed


def _backfill_suggested_to_declared(
    refreshed: RegistrationReviewDraft,
    completion: Any,
) -> None:
    """Promote system-inferred/suggested values into declared_evidence_fields
    for any field that is currently absent or empty. Only fills blanks — never
    overwrites a value the user already declared.
    """
    ev = refreshed.declared_evidence_fields

    def _fill(key: str, suggested_value: Any) -> None:
        existing = str(ev.get(key) or "").strip()
        if not existing and suggested_value:
            ev[key] = suggested_value
            refreshed.system_inferred_fields[f"{key}_auto_filled"] = True

    # Size / volume
    _fill("size_or_volume", _clean(getattr(completion, "suggested_size_or_volume", None)))

    # Category
    _fill("category", _clean(getattr(completion, "suggested_category", None)))

    # Package notes
    _fill("package_notes", _clean(getattr(completion, "suggested_package_notes", None)))

    # Currency — default MYR when absent
    existing_currency = str(ev.get("currency") or "").strip()
    if not existing_currency:
        ev["currency"] = "MYR"
        refreshed.system_inferred_fields["currency_auto_filled"] = True

    # Normalised product name — push back if blank
    _fill("product_name", _clean(getattr(completion, "suggested_normalized_name", None)))

    # Target customer
    _fill(
        "target_customer_text",
        _clean(getattr(completion, "suggested_target_customer", None)),
    )

    # Hook/CTA angles (only fill if nothing declared yet)
    if not _clean_list(ev.get("hook_angles")):
        suggested_hooks = list(getattr(completion, "suggested_hook_angles", None) or [])
        if suggested_hooks:
            ev["hook_angles"] = suggested_hooks
            refreshed.system_inferred_fields["hook_angles_auto_filled"] = True

    if not _clean_list(ev.get("cta_angles")):
        suggested_ctas = list(getattr(completion, "suggested_cta_angles", None) or [])
        if suggested_ctas:
            ev["cta_angles"] = suggested_ctas
            refreshed.system_inferred_fields["cta_angles_auto_filled"] = True
