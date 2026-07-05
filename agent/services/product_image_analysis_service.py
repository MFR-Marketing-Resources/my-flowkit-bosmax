from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.config import BASE_DIR
from agent.db import crud
from agent.models.product_intelligence import (
    ProductImageAnalysisResolveRequest,
    ProductIntelligenceImageAnalysis,
)
from agent.services import vision_provider_adapter
from agent.services.ai_provider_settings_service import (
    get_lane_api_key,
    get_lane_model,
    get_lane_provider,
    get_provider_api_key,
    is_lane_execution_enabled,
)


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
SEMANTIC_IMAGE_WARNING = "SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"
PROVIDER_EXECUTION_DISABLED_WARNING = "PROVIDER_EXECUTION_DISABLED"
VISION_PROVIDER_EXECUTION_DISABLED_WARNING = "VISION_PROVIDER_EXECUTION_DISABLED"
ALLOWED_PACKAGE_CLASSES = {
    "bottle",
    "refill_pouch",
    "tube",
    "box",
    "packet",
    "garment",
    "jar",
    "roll_on_bottle",
}
ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
_ANTHROPIC_IMAGE_ANALYSIS_PROMPT = """Return JSON only.
{
  "detected_package": "bottle|refill_pouch|tube|box|packet|garment|jar|roll_on_bottle|null",
  "detected_text": ["exact visible pack text"],
  "detected_brand": "string or null",
  "detected_size_text": "string or null",
  "detected_form_factor": "short string or null",
  "visual_confidence": "HIGH|MEDIUM|LOW",
  "warnings": ["short machine-readable warnings"]
}

Rules:
- Detect only what is visible in the product image.
- Do not infer medical claims or hidden product facts.
- If unsure, use null and lower confidence.
- Keep detected_text short, exact, and limited to what is visibly readable.
- detected_package must be one of the allowed package classes or null.
"""

logger = logging.getLogger(__name__)


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


def _mime_type_for_path(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/jpeg"


def _resolve_vision_model() -> str | None:
    """The operator-selected vision lane model is the ONLY source. There is NO
    hidden fallback: an unconfigured or catalog-invalidated lane model resolves to
    None so the runtime fails closed before any provider call."""
    try:
        return get_lane_model("vision")
    except Exception:
        return None


def _parse_json_response(raw: str) -> dict[str, Any]:
    payload = str(raw or "").strip()
    if payload.startswith("```"):
        payload = payload.split("```")[1]
        if payload.startswith("json"):
            payload = payload[4:]
    payload = payload.strip()
    if not payload.startswith("{"):
        start = payload.find("{")
        if start >= 0:
            payload = payload[start:]
    return json.loads(payload)


def _build_anthropic_content(
    payload: dict[str, Any],
    *,
    local_path: Path | None,
    image_url: str | None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    title = str(payload.get("raw_product_title") or "").strip()
    if title:
        content.append(
            {
                "type": "text",
                "text": f"Product title context: {title}",
            }
        )
    content.append(
        {
            "type": "text",
            "text": _ANTHROPIC_IMAGE_ANALYSIS_PROMPT,
        }
    )

    if local_path and local_path.exists():
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _mime_type_for_path(local_path),
                    "data": base64.b64encode(local_path.read_bytes()).decode("utf-8"),
                },
            }
        )
        return content

    if image_url:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image_url,
                },
            }
        )
        return content

    raise ValueError("IMAGE_SOURCE_UNAVAILABLE_FOR_PROVIDER")


def _normalize_text_list(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _normalize_text(item)
        if not text or text in normalized:
            continue
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_provider_result(
    provider: str,
    parsed: dict[str, Any],
    model: str,
) -> ProductIntelligenceImageAnalysis:
    detected_package = _normalize_text(parsed.get("detected_package"))
    if detected_package not in ALLOWED_PACKAGE_CLASSES:
        detected_package = None

    visual_confidence = str(parsed.get("visual_confidence") or "").strip().upper()
    if visual_confidence not in ALLOWED_CONFIDENCE:
        visual_confidence = "LOW"

    warnings = _normalize_text_list(parsed.get("warnings"), limit=8)
    detected_form_factor = _normalize_text(parsed.get("detected_form_factor"))
    if not detected_form_factor and detected_package:
        detected_form_factor = detected_package

    return ProductIntelligenceImageAnalysis(
        status="ANALYZED",
        detected_package=detected_package,
        detected_text=_normalize_text_list(parsed.get("detected_text")),
        detected_brand=_normalize_text(parsed.get("detected_brand")),
        detected_size_text=_normalize_text(parsed.get("detected_size_text")),
        detected_form_factor=detected_form_factor,
        visual_confidence=visual_confidence,
        evidence=[
            f"provider:{provider}",
            f"provider:model:{model}",
        ],
        warnings=warnings,
        provider=provider,
        metadata={},
    )


def _extract_response_text(response: Any) -> str:
    parts: list[str] = []
    for block in list(getattr(response, "content", []) or []):
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _analyze_with_anthropic(
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> ProductIntelligenceImageAnalysis | None:
    try:
        import anthropic

        model = _resolve_vision_model()
        if not model:
            # No operator-selected vision model — fail closed, never a hidden default.
            return None
        local_path = _coerce_local_path(_normalize_text(payload.get("local_image_path")))
        image_url = _normalize_text(payload.get("image_url"))
        client = anthropic.Anthropic(api_key=get_lane_api_key("vision"))
        content = _build_anthropic_content(
            payload,
            local_path=local_path,
            image_url=image_url,
        )
        response = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": content}],
        )
        parsed = _parse_json_response(_extract_response_text(response))
        return _normalize_provider_result("anthropic", parsed, model)
    except Exception as exc:  # fail closed; outer layer maps to ANALYSIS_FAILED
        logger.warning("Anthropic product image analysis failed: %s", exc)
        return None


def _analyze_with_openai_compatible_vision(
    provider: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> ProductIntelligenceImageAnalysis | None:
    """OpenAI-compatible multimodal path (OpenAI / Gemini / Qwen-VL) via the
    vision provider adapter. Prepares the image as a base64 data URL (local file)
    or a remote https URL, then normalizes into the stable analysis schema.
    Fail-closed: any error returns None (outer layer maps to ANALYSIS_FAILED)."""
    _ = metadata
    try:
        model = _resolve_vision_model()
        api_key = get_lane_api_key("vision")
        if not api_key or not model:
            return None

        local_path = _coerce_local_path(_normalize_text(payload.get("local_image_path")))
        image_url = _normalize_text(payload.get("image_url"))
        image_data_url: str | None = None
        image_remote_url: str | None = None
        if local_path and local_path.exists():
            mime = _mime_type_for_path(local_path)
            encoded = base64.b64encode(local_path.read_bytes()).decode("utf-8")
            image_data_url = f"data:{mime};base64,{encoded}"
        elif image_url:
            image_remote_url = image_url
        else:
            return None

        raw = vision_provider_adapter.run_vision_completion(
            provider,
            model,
            api_key,
            prompt_text=_ANTHROPIC_IMAGE_ANALYSIS_PROMPT,
            title=_normalize_text(payload.get("raw_product_title")),
            image_data_url=image_data_url,
            image_remote_url=image_remote_url,
        )
        parsed = _parse_json_response(raw)
        return _normalize_provider_result(provider, parsed, model)
    except Exception as exc:  # fail closed; outer layer maps to ANALYSIS_FAILED
        logger.warning("%s product image analysis failed: %s", provider, exc)
        return None


def _configured_vision_runtime() -> tuple[str, str] | None:
    """Vision runtime is runnable ONLY with a COMPLETE lane: provider + model +
    key. Any missing piece → None (fail closed, no hidden default). Execution-
    enabled is gated separately downstream so the caller can distinguish
    NOT_CONFIGURED from ANALYSIS_SKIPPED."""
    provider = get_lane_provider("vision")
    model = _resolve_vision_model()
    key = get_lane_api_key("vision")
    if provider and model and key:
        return provider, model
    return None


def _configured_provider_name() -> str | None:
    """Configured vision provider — ONLY when provider + model + key are all
    present. A stale/corrupt lane with a provider+key but no model is NOT
    configured and must never reach a provider call."""
    runtime = _configured_vision_runtime()
    return runtime[0] if runtime else None


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
    if provider == "anthropic":
        return _analyze_with_anthropic(payload, metadata)
    # OpenAI-compatible multimodal providers (openai / gemini / qwen) share ONE
    # wired transport in vision_provider_adapter. Transport eligibility was already
    # enforced when the lane was configured (catalog LANE_TRANSPORT_SUPPORT), so a
    # provider only reaches here when its transport is genuinely implemented.
    if provider in {"openai", "gemini", "qwen"}:
        return _analyze_with_openai_compatible_vision(provider, payload, metadata)
    # Unknown / unwired provider — fail closed, never guess.
    _ = (payload, metadata)
    return None


def analyze_product_image_payload(
    source: dict[str, Any],
    *,
    allow_provider_execution: bool = True,
) -> dict[str, Any]:
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

    if not allow_provider_execution:
        warnings.append(PROVIDER_EXECUTION_DISABLED_WARNING)
        evidence.append("provider_execution:disabled")
        metadata["configured_provider"] = provider
        return ProductIntelligenceImageAnalysis(
            status="ANALYSIS_SKIPPED",
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
            provider="execution_disabled",
            metadata=metadata,
        ).model_dump()

    if not is_lane_execution_enabled("vision"):
        warnings.extend(
            warning
            for warning in [
                PROVIDER_EXECUTION_DISABLED_WARNING,
                VISION_PROVIDER_EXECUTION_DISABLED_WARNING,
            ]
            if warning not in warnings
        )
        evidence.append("provider_execution:vision_lane_disabled")
        metadata["configured_provider"] = provider
        return ProductIntelligenceImageAnalysis(
            status="ANALYSIS_SKIPPED",
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
            provider="execution_disabled",
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
