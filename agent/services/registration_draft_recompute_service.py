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
