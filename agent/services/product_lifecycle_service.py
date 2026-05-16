from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from agent.db import crud


LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_ARCHIVED = "ARCHIVED"
LIFECYCLE_DELETED_TEST_ONLY = "DELETED_TEST_ONLY"

ARCHIVE_CONFIRMATION = "ARCHIVE_PRODUCT"
UNARCHIVE_CONFIRMATION = "UNARCHIVE_PRODUCT"
DELETE_TEST_ROW_CONFIRMATION = "DELETE_TEST_ROW_ONLY"

ARCHIVEABLE_SOURCES = {"FASTMOSS", "MANUAL", "TIKTOKSHOP", "IMPORTED"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lifecycle_status(product: dict[str, Any] | None) -> str:
    return str((product or {}).get("lifecycle_status") or LIFECYCLE_ACTIVE).upper()


def is_archived(product: dict[str, Any] | None) -> bool:
    return lifecycle_status(product) == LIFECYCLE_ARCHIVED


def _title_candidates(product: dict[str, Any]) -> list[str]:
    return [
        str(product.get("raw_product_title") or ""),
        str(product.get("product_display_name") or ""),
        str(product.get("product_short_name") or ""),
    ]


def is_test_delete_eligible(product: dict[str, Any] | None) -> bool:
    if not product:
        return False
    titles = [title.strip().upper() for title in _title_candidates(product) if title and title.strip()]
    return any(title.endswith("TEST_DO_NOT_USE") for title in titles)


def _load_provenance(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [{"event": "LEGACY_LIFECYCLE_VALUE", "raw": raw}]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _dump_provenance(entries: list[dict[str, Any]]) -> str:
    return json.dumps(entries, ensure_ascii=True)


def _with_event(
    product: dict[str, Any],
    *,
    action: str,
    reason: str,
    actor: str,
    from_status: str,
    to_status: str,
) -> str:
    provenance = _load_provenance(product.get("lifecycle_provenance"))
    provenance.append(
        {
            "timestamp": _utcnow(),
            "action": action,
            "reason": reason,
            "actor": actor,
            "from_status": from_status,
            "to_status": to_status,
            "source": str(product.get("source") or "UNKNOWN"),
        }
    )
    return _dump_provenance(provenance)


def _capabilities(product: dict[str, Any]) -> dict[str, bool]:
    source = str(product.get("source") or "").upper()
    status = lifecycle_status(product)
    can_archive = source in ARCHIVEABLE_SOURCES and status == LIFECYCLE_ACTIVE
    can_unarchive = source in ARCHIVEABLE_SOURCES and status == LIFECYCLE_ARCHIVED
    can_delete = source != "FASTMOSS" and status != LIFECYCLE_ARCHIVED and is_test_delete_eligible(product)
    return {
        "can_archive": can_archive,
        "can_unarchive": can_unarchive,
        "can_delete_test_only": can_delete,
    }


def lifecycle_payload(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": product.get("id"),
        "lifecycle_status": lifecycle_status(product),
        "archived_at": product.get("archived_at"),
        "archived_reason": product.get("archived_reason"),
        "archived_by": product.get("archived_by"),
        "unarchived_at": product.get("unarchived_at"),
        "unarchived_reason": product.get("unarchived_reason"),
        "source": product.get("source"),
        "lifecycle_provenance": _load_provenance(product.get("lifecycle_provenance")),
        **_capabilities(product),
    }


async def get_product_lifecycle(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return lifecycle_payload(product)


async def archive_product(
    product_id: str,
    *,
    reason: str,
    confirmation_phrase: str,
    actor: str = "SYSTEM_API",
) -> dict[str, Any]:
    if confirmation_phrase != ARCHIVE_CONFIRMATION:
        raise HTTPException(status_code=400, detail="ARCHIVE_CONFIRMATION_REQUIRED")
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if lifecycle_status(product) == LIFECYCLE_ARCHIVED:
        return lifecycle_payload(product)

    updated = await crud.update_product(
        product_id,
        lifecycle_status=LIFECYCLE_ARCHIVED,
        archived_at=_utcnow(),
        archived_reason=reason,
        archived_by=actor,
        unarchived_at=None,
        unarchived_reason=None,
        updated_at=product.get("updated_at"),
        lifecycle_provenance=_with_event(
            product,
            action="ARCHIVE",
            reason=reason,
            actor=actor,
            from_status=lifecycle_status(product),
            to_status=LIFECYCLE_ARCHIVED,
        ),
    )
    return lifecycle_payload(updated)


async def unarchive_product(
    product_id: str,
    *,
    reason: str,
    confirmation_phrase: str,
    actor: str = "SYSTEM_API",
) -> dict[str, Any]:
    if confirmation_phrase != UNARCHIVE_CONFIRMATION:
        raise HTTPException(status_code=400, detail="UNARCHIVE_CONFIRMATION_REQUIRED")
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if lifecycle_status(product) != LIFECYCLE_ARCHIVED:
        raise HTTPException(status_code=409, detail="PRODUCT_NOT_ARCHIVED")

    updated = await crud.update_product(
        product_id,
        lifecycle_status=LIFECYCLE_ACTIVE,
        unarchived_at=_utcnow(),
        unarchived_reason=reason,
        updated_at=product.get("updated_at"),
        lifecycle_provenance=_with_event(
            product,
            action="UNARCHIVE",
            reason=reason,
            actor=actor,
            from_status=lifecycle_status(product),
            to_status=LIFECYCLE_ACTIVE,
        ),
    )
    return lifecycle_payload(updated)


async def delete_test_row(
    product_id: str,
    *,
    reason: str,
    confirmation_phrase: str,
    actor: str = "SYSTEM_API",
) -> dict[str, Any]:
    if confirmation_phrase != DELETE_TEST_ROW_CONFIRMATION:
        raise HTTPException(status_code=400, detail="DELETE_TEST_ROW_CONFIRMATION_REQUIRED")
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if str(product.get("source") or "").upper() == "FASTMOSS":
        raise HTTPException(status_code=403, detail="FASTMOSS_DELETE_FORBIDDEN")
    if not is_test_delete_eligible(product):
        raise HTTPException(status_code=403, detail="TEST_ROW_DELETE_FORBIDDEN")

    deleted = await crud.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="PRODUCT_DELETE_FAILED")

    return {
        "product_id": product_id,
        "deleted": True,
        "lifecycle_status": LIFECYCLE_DELETED_TEST_ONLY,
        "reason": reason,
        "source": product.get("source"),
        "deleted_by": actor,
        "deleted_at": _utcnow(),
        "lifecycle_provenance": _load_provenance(
            _with_event(
                product,
                action="DELETE_TEST_ROW_ONLY",
                reason=reason,
                actor=actor,
                from_status=lifecycle_status(product),
                to_status=LIFECYCLE_DELETED_TEST_ONLY,
            )
        ),
    }
