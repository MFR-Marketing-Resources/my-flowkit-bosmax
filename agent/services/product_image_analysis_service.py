from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.config import ANTHROPIC_API_KEY, BASE_DIR
from agent.db import crud
from agent.models.product_intelligence import (
    ProductImageAnalysisResolveRequest,
    ProductIntelligenceImageAnalysis,
)


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
SEMANTIC_IMAGE_WARNING = "SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_local_path(value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return candidate.resolve()


def _is_supported_image_path(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


def _is_supported_image_url(image_url: str) -> bool:
    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix.lower()
    return suffix in SUPPORTED_IMAGE_SUFFIXES if suffix else True


def _configured_provider_name() -> str | None:
    provider = os.environ.get("PRODUCT_IMAGE_VISION_PROVIDER", "").strip().lower()
    if not provider:
        return None
    if provider == "anthropic" and ANTHROPIC_API_KEY:
        return "anthropic"
    return None


def _build_reference_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": _normalize_text(source.get("id")) or _normalize_text(source.get("product_id")),
        "raw_product_title": _normalize_text(source.get("raw_product_title")),
        "image_url": _normalize_text(source.get("image_url")),
        "local_image_path": _normalize_text(source.get("local_image_path")),
    }


def _analyze_with_provider(
    provider: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> ProductIntelligenceImageAnalysis | None:
    # No semantic provider is wired for product intelligence in this checkout.
    # Tests may monkeypatch this function to simulate a configured provider.
    _ = (provider, payload, metadata)
    return None


def analyze_product_image_payload(source: dict[str, Any]) -> dict[str, Any]:
    payload = _build_reference_payload(source)
    image_url = payload["image_url"]
    local_image_path = payload["local_image_path"]
    local_path = _coerce_local_path(local_image_path)
    metadata: dict[str, Any] = {}
    evidence: list[str] = []
    warnings: list[str] = []

    if image_url:
        evidence.append("image_reference:image_url_present")
        metadata["image_url_host"] = urlparse(image_url).netloc or None
    if local_image_path:
        evidence.append("image_reference:local_image_path_present")
        metadata["local_image_path_raw"] = local_image_path
    if local_path:
        metadata["local_file_exists"] = local_path.exists()
        metadata["local_file_suffix"] = local_path.suffix.lower() or None
        if local_path.exists():
            evidence.append("image_reference:local_file_exists")
            metadata["local_file_size_bytes"] = local_path.stat().st_size
            metadata["local_file_mime_type"] = mimetypes.guess_type(local_path.name)[0]
        else:
            evidence.append("image_reference:local_file_missing")

    if not image_url and not local_image_path:
        return ProductIntelligenceImageAnalysis(
            status="IMAGE_MISSING",
            image_url=None,
            local_image_path=None,
            detected_package=None,
            detected_text=[],
            detected_brand=None,
            detected_size_text=None,
            detected_form_factor=None,
            visual_confidence="NOT_VERIFIED",
            evidence=["image_reference:missing"],
            warnings=["IMAGE_REFERENCE_MISSING"],
            provider="metadata_only",
            metadata=metadata,
        ).model_dump()

    if local_path and metadata.get("local_file_exists") and not _is_supported_image_path(local_path):
        warnings.append("UNSUPPORTED_IMAGE_FORMAT")
        return ProductIntelligenceImageAnalysis(
            status="UNSUPPORTED_IMAGE_FORMAT",
            image_url=image_url,
            local_image_path=local_image_path,
            detected_package=None,
            detected_text=[],
            detected_brand=None,
            detected_size_text=None,
            detected_form_factor=None,
            visual_confidence="NOT_VERIFIED",
            evidence=evidence,
            warnings=warnings,
            provider="metadata_only",
            metadata=metadata,
        ).model_dump()

    if image_url and not _is_supported_image_url(image_url):
        warnings.append("UNSUPPORTED_IMAGE_FORMAT")
        return ProductIntelligenceImageAnalysis(
            status="UNSUPPORTED_IMAGE_FORMAT",
            image_url=image_url,
            local_image_path=local_image_path,
            detected_package=None,
            detected_text=[],
            detected_brand=None,
            detected_size_text=None,
            detected_form_factor=None,
            visual_confidence="NOT_VERIFIED",
            evidence=evidence,
            warnings=warnings,
            provider="metadata_only",
            metadata=metadata,
        ).model_dump()

    if local_image_path and local_path and not metadata.get("local_file_exists") and not image_url:
        warnings.append("LOCAL_IMAGE_NOT_FOUND")
        return ProductIntelligenceImageAnalysis(
            status="IMAGE_INACCESSIBLE",
            image_url=None,
            local_image_path=local_image_path,
            detected_package=None,
            detected_text=[],
            detected_brand=None,
            detected_size_text=None,
            detected_form_factor=None,
            visual_confidence="NOT_VERIFIED",
            evidence=evidence,
            warnings=warnings,
            provider="metadata_only",
            metadata=metadata,
        ).model_dump()

    provider = _configured_provider_name()
    if not provider:
        warnings.append(SEMANTIC_IMAGE_WARNING)
        return ProductIntelligenceImageAnalysis(
            status="VISION_PROVIDER_NOT_CONFIGURED",
            image_url=image_url,
            local_image_path=local_image_path,
            detected_package=None,
            detected_text=[],
            detected_brand=None,
            detected_size_text=None,
            detected_form_factor=None,
            visual_confidence="NOT_VERIFIED",
            evidence=evidence,
            warnings=warnings,
            provider="not_configured",
            metadata=metadata,
        ).model_dump()

    analyzed = _analyze_with_provider(provider, payload, metadata)
    if analyzed is None:
        return ProductIntelligenceImageAnalysis(
            status="ANALYSIS_FAILED",
            image_url=image_url,
            local_image_path=local_image_path,
            detected_package=None,
            detected_text=[],
            detected_brand=None,
            detected_size_text=None,
            detected_form_factor=None,
            visual_confidence="NOT_VERIFIED",
            evidence=evidence,
            warnings=["SEMANTIC_IMAGE_ANALYSIS_FAILED"],
            provider=provider,
            metadata=metadata,
        ).model_dump()

    if not analyzed.image_url:
        analyzed.image_url = image_url
    if not analyzed.local_image_path:
        analyzed.local_image_path = local_image_path
    if not analyzed.provider:
        analyzed.provider = provider
    analyzed.metadata = {**metadata, **dict(analyzed.metadata)}
    analyzed.evidence = list(dict.fromkeys([*evidence, *analyzed.evidence]))
    analyzed.warnings = list(dict.fromkeys(analyzed.warnings))
    return analyzed.model_dump()


async def get_product_image_analysis_by_id(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        return {
            "status": "PRODUCT_NOT_FOUND",
            "product_id": product_id,
        }
    result = analyze_product_image_payload(dict(product))
    result["product_id"] = product_id
    return result


async def resolve_product_image_analysis_request(
    request_input: ProductImageAnalysisResolveRequest | dict[str, Any],
) -> dict[str, Any]:
    request = (
        request_input
        if isinstance(request_input, ProductImageAnalysisResolveRequest)
        else ProductImageAnalysisResolveRequest.model_validate(request_input)
    )
    if request.product_id:
        product = await crud.get_product(request.product_id)
        if not product:
            return {
                "status": "PRODUCT_NOT_FOUND",
                "product_id": request.product_id,
            }
        return {
            **analyze_product_image_payload(dict(product)),
            "product_id": request.product_id,
        }

    if request.product_payload:
        merged = dict(request.product_payload)
        if request.image_url:
            merged["image_url"] = request.image_url
        if request.local_image_path:
            merged["local_image_path"] = request.local_image_path
        if request.raw_product_title:
            merged["raw_product_title"] = request.raw_product_title
        return analyze_product_image_payload(merged)

    if request.image_url or request.local_image_path:
        return analyze_product_image_payload(
            {
                "image_url": request.image_url,
                "local_image_path": request.local_image_path,
                "raw_product_title": request.raw_product_title,
            }
        )

    return {
        "status": "IMAGE_CONTEXT_REQUIRED",
        "warnings": ["IMAGE_CONTEXT_REQUIRED"],
        "provider": "metadata_only",
    }
