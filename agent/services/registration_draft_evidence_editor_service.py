from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.models.product_registration import (
    RegistrationReviewDraft,
    RegistrationReviewDraftEvidencePatchRequest,
)
from agent.services.product_knowledge_service import _persist_intake_image
from agent.services.registration_draft_recompute_service import (
    derive_draft_image_asset_state,
    recompute_review_draft,
)
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService


EDITABLE_EVIDENCE_FIELDS = (
    "product_name",
    "product_knowledge_text",
    "benefits_text",
    "usage_text",
    "target_customer_text",
    "ingredients_text",
    "warnings_text",
    "paste_anything_about_product",
    "price",
    "currency",
    "commission_amount",
    "commission_rate",
    "size_or_volume",
    "package_notes",
    "product_url",
    "source_url",
    "tiktok_product_url",
    "tiktok_shop_url",
    "image_url",
    "local_image_path",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: list[str]) -> list[str]:
    return [entry for entry in (_clean_text(item) for item in value) if entry]


def _apply_request_to_evidence(
    draft: RegistrationReviewDraft,
    request: RegistrationReviewDraftEvidencePatchRequest,
) -> RegistrationReviewDraft:
    payload = request.model_dump()
    for field in EDITABLE_EVIDENCE_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if value is not None:
            draft.declared_evidence_fields[field] = value

    if request.image_base64:
        local_image_path = _persist_intake_image(
            request.image_base64,
            request.image_filename,
        )
        draft.declared_evidence_fields["local_image_path"] = local_image_path

    if request.hook_angles is not None:
        draft.declared_evidence_fields["hook_angles"] = _clean_list(request.hook_angles)
    if request.cta_angles is not None:
        draft.declared_evidence_fields["cta_angles"] = _clean_list(request.cta_angles)

    now = _now()
    draft.last_evidence_edit_at = now
    draft.draft_freshness_status = "STALE"
    image_asset_status, image_asset_detail = derive_draft_image_asset_state(
        draft.declared_evidence_fields,
    )
    draft.image_asset_status = image_asset_status
    draft.image_asset_detail = image_asset_detail
    draft.system_inferred_fields["image_asset_status"] = image_asset_status
    draft.system_inferred_fields["image_asset_detail"] = image_asset_detail
    return draft


def patch_registration_draft_evidence(
    draft_id: str,
    request: RegistrationReviewDraftEvidencePatchRequest,
) -> RegistrationReviewDraft | None:
    draft = RegistrationDraftStorageService.get_draft(draft_id)
    if not draft:
        return None
    if draft.review_status == "COMMITTED":
        raise ValueError("DRAFT_ALREADY_COMMITTED")

    updated = _apply_request_to_evidence(draft, request)
    if request.recompute:
        updated = recompute_review_draft(updated)

    return RegistrationDraftStorageService.save_draft(updated)
