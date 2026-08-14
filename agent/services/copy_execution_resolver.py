"""Phase 3 Copy Architecture V2 consumer boundary.

This module is deliberately the only consumer-facing V2 resolver.  It does
not read CopySet rows, write database state, approve copy, invoke a compiler,
or call a provider.  With the feature flag OFF it returns a compatibility
receipt and leaves the caller's legacy path untouched.  With the flag ON it
requires a complete V2 request context and fails closed on every missing or
stale lineage element.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel

from agent.authority.copy_lane_matrix import get_lane_descriptor
from agent.models.copy_blueprint_v2 import (
    AdapterContext,
    CopyBlueprintV2,
    CopyBlueprintV2FeatureFlagState,
    CopyExecutionBinding,
    EvidenceFact,
    EvidenceRegistry,
    ImageCopyProjection,
    ProductTruthLineage,
    VideoCopyProjection,
)
from agent.services.copy_blueprint_v2_service import (
    CopyBlueprintV2Error,
    bind_copy_blueprint_v2,
    project_image_copy,
    project_video_copy,
)


class CopyExecutionResolutionError(ValueError):
    """Stable, structured, fail-closed consumer error."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        self.code = code
        self.details = details
        self.status_code = 409
        super().__init__(message)


@dataclass(frozen=True)
class CopyExecutionResolution:
    """Read-only result carried from the resolver into a consumer seam."""

    lane: str
    media_kind: str
    copy_policy: str
    feature_flags: CopyBlueprintV2FeatureFlagState
    v2_enabled: bool
    status: str
    binding: CopyExecutionBinding | None = None
    projection: VideoCopyProjection | ImageCopyProjection | None = None
    compiler_copy_intelligence: dict[str, Any] | None = None
    approved_dialogue: str | None = None
    metadata: dict[str, Any] | None = None

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    def to_metadata(
        self,
        *,
        consumer_context: Mapping[str, Any] | BaseModel | None = None,
    ) -> dict[str, Any]:
        """Return JSON-safe lineage for durable package/queue handoff."""

        base = dict(self.metadata or {})
        base.update(
            {
                "version": "2",
                "lane": self.lane,
                "media_kind": self.media_kind,
                "copy_policy": self.copy_policy,
                "feature_flag_state": self.feature_flags.model_dump(mode="json"),
                "v2_enabled": self.v2_enabled,
                "status": self.status,
            }
        )
        if self.binding is not None:
            base["binding"] = self.binding.model_dump(mode="json")
        if self.projection is not None:
            base["projection"] = self.projection.model_dump(mode="json")
        if consumer_context is not None and self.v2_enabled:
            # Durable handoffs need the original, validated blueprint context
            # to re-enter the same resolver at the next consumer boundary.
            # The binding remains the authoritative identity; this context is
            # only the immutable revalidation input and is never accepted as a
            # caller-supplied binding.
            base["consumer_context"] = _context_dict(consumer_context)
        return base


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _context_dict(request_context: Any) -> dict[str, Any]:
    if request_context is None:
        return {}
    if isinstance(request_context, BaseModel):
        return request_context.model_dump(mode="python")
    if isinstance(request_context, Mapping):
        return dict(request_context)
    raise CopyExecutionResolutionError(
        "COPY_V2_REQUEST_CONTEXT_INVALID",
        "Copy Architecture V2 request context must be an object.",
    )


def _flag_state(
    context: Mapping[str, Any],
    explicit: CopyBlueprintV2FeatureFlagState | Mapping[str, Any] | None,
) -> CopyBlueprintV2FeatureFlagState:
    raw = explicit if explicit is not None else context.get("feature_flags")
    if raw is None:
        scope = str(context.get("scope") or "").strip()
        pilot_scope = tuple(str(item) for item in (context.get("pilot_scope") or ()))
        return CopyBlueprintV2FeatureFlagState.from_environment(
            scope=scope,
            pilot_scope=pilot_scope,
        )
    if isinstance(raw, CopyBlueprintV2FeatureFlagState):
        return raw
    values = _as_dict(raw)
    enabled = bool(values.get("enabled", False))
    shadow_mode = bool(values.get("shadow_mode", False))
    scope = str(values.get("scope") or context.get("scope") or "").strip()
    pilot_scope = tuple(
        str(item)
        for item in (values.get("pilot_scope") or context.get("pilot_scope") or ())
    )
    if shadow_mode and enabled:
        state = "SHADOW"
    elif enabled and scope and scope in pilot_scope:
        state = "PILOT"
    elif enabled:
        state = "ON"
    else:
        state = "OFF"
    values.update(
        {
            "enabled": enabled,
            "shadow_mode": shadow_mode,
            "scope": scope,
            "pilot_scope": pilot_scope,
            "state": state,
        }
    )
    return CopyBlueprintV2FeatureFlagState.model_validate(values)


def lane_for_request(
    mode: str | None = None,
    *,
    source_mode: str | None = None,
    lane: str | None = None,
    visual_lane_id: str | None = None,
) -> str:
    """Map the current transport request to one of the eleven matrix lanes."""

    explicit = str(lane or visual_lane_id or "").strip()
    if explicit:
        token = explicit.upper().replace("-", "_")
        if "POSTER" in token:
            return "POSTER_BUILDER"
        if "FASTLANE" in token:
            return "IMG_FASTLANE"
        if "COCKPIT" in token:
            return "IMG_COCKPIT"
        return get_lane_descriptor(token).lane_id
    normalized_mode = str(mode or "").strip().upper()
    normalized_source = str(source_mode or "").strip().upper()
    if normalized_mode == "FACELESS":
        return "FACELESS"
    if normalized_mode == "MONTAGE":
        return "MONTAGE"
    if normalized_mode in {"P6", "PRODUCTION_STUDIO", "PRODUCTION_STUDIO_P6"}:
        return "PRODUCTION_STUDIO_P6"
    if normalized_mode == "IMG":
        return "IMAGE_GEN"
    if normalized_mode == "T2V":
        return "T2V"
    if normalized_mode == "I2V":
        return "I2V"
    if normalized_mode == "F2V":
        return "HYBRID" if normalized_source == "HYBRID" else "F2V"
    if normalized_mode == "HYBRID":
        return "HYBRID"
    raise CopyExecutionResolutionError(
        "COPY_V2_UNKNOWN_LANE",
        f"Cannot resolve a Copy Architecture V2 lane from mode={mode!r}.",
    )


def _adapter_context(
    context: Mapping[str, Any],
    *,
    product_id: str,
    lineage: ProductTruthLineage | None,
) -> AdapterContext:
    raw = _as_dict(context.get("adapter_context") or context.get("context"))
    if not raw:
        raw = {
            key: context[key]
            for key in (
                "readiness_validated",
                "provenance_validated",
                "safety_validated",
                "semantic_review_validated",
            )
            if key in context
        }
    if lineage is not None and "product_truth_lineage" not in raw:
        raw["product_truth_lineage"] = lineage.model_dump(mode="python")
    if "product_id" not in raw:
        raw["product_id"] = product_id
    if lineage is None:
        raise CopyExecutionResolutionError(
            "COPY_V2_PRODUCT_TRUTH_LINEAGE_MISSING",
            "V2 consumer binding requires current Product Truth lineage.",
        )
    try:
        return AdapterContext.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - normalize to stable contract code
        raise CopyExecutionResolutionError(
            "COPY_V2_ADAPTER_CONTEXT_INVALID",
            "V2 adapter context is incomplete or invalid.",
            details=str(exc),
        ) from exc


def _approved_dialogue(blueprint: CopyBlueprintV2) -> str:
    text_by_stage = {
        item.stage_key: item.text for item in blueprint.approved_execution_text
    }
    ordered: list[str] = []
    for stage in blueprint.stages:
        text = text_by_stage.get(stage.stage_key)
        if not text:
            raise CopyExecutionResolutionError(
                "COPY_V2_APPROVED_TEXT_MISSING",
                "Every ordered formula stage needs immutable approved execution text.",
                details={"stage_key": stage.stage_key},
            )
        ordered.append(text)
    if not ordered:
        raise CopyExecutionResolutionError(
            "COPY_V2_APPROVED_TEXT_MISSING",
            "V2 production binding cannot execute without approved stage text.",
        )
    return " ".join(ordered)


def _compiler_copy(blueprint: CopyBlueprintV2) -> dict[str, Any]:
    """Build only derived compatibility fields; authored text stays immutable."""

    derived = blueprint.derived_projections()
    return {
        "copy_source": "copy_blueprint_v2",
        "formula_id": blueprint.formula_id,
        "formula_version": blueprint.formula_version,
        "blueprint_id": blueprint.blueprint_id,
        "revision": blueprint.revision,
        "hook": derived.hook,
        "usps": [derived.body] if derived.body else [],
        "cta": derived.cta,
        "approved_execution_text": [
            {"stage_key": item.stage_key, "text": item.text}
            for item in blueprint.approved_execution_text
        ],
    }


def _error_from_v2(error: CopyBlueprintV2Error) -> CopyExecutionResolutionError:
    return CopyExecutionResolutionError(error.code, str(error), details=error.details)


def resolve_copy_execution_binding(
    product_id: str,
    lane: str,
    request_context: Mapping[str, Any] | BaseModel | None = None,
    feature_flag_state: CopyBlueprintV2FeatureFlagState | Mapping[str, Any] | None = None,
) -> CopyExecutionResolution:
    """Resolve the universal V2 copy policy/binding at a consumer boundary.

    The function is synchronous and side-effect free so every API/service seam
    can call the exact same contract before persistence or provider work.
    """

    context = _context_dict(request_context)
    try:
        descriptor = get_lane_descriptor(lane)
    except ValueError as exc:
        raise CopyExecutionResolutionError("COPY_V2_UNKNOWN_LANE", str(exc)) from exc
    flags = _flag_state(context, feature_flag_state)
    if not flags.enabled or flags.state == "OFF":
        return CopyExecutionResolution(
            lane=descriptor.lane_id,
            media_kind=descriptor.media_kind,
            copy_policy=descriptor.copy_policy,
            feature_flags=flags,
            v2_enabled=False,
            status="LEGACY_COMPATIBLE",
            metadata={
                "policy_source": "copy_architecture_v2",
                "legacy_fallback": True,
                "legacy_path_unchanged": True,
            },
        )

    current_lineage_raw = (
        context.get("current_product_truth")
        or context.get("product_truth_lineage")
    )
    try:
        current_lineage = (
            ProductTruthLineage.model_validate(current_lineage_raw)
            if current_lineage_raw is not None
            else None
        )
    except Exception as exc:  # noqa: BLE001
        raise CopyExecutionResolutionError(
            "COPY_V2_PRODUCT_TRUTH_LINEAGE_INVALID",
            "Current Product Truth lineage is invalid.",
            details=str(exc),
        ) from exc
    if current_lineage is not None and current_lineage.product_id != product_id:
        raise CopyExecutionResolutionError(
            "COPY_V2_PRODUCT_MISMATCH",
            "Current Product Truth lineage belongs to another product.",
        )
    if current_lineage is None:
        raise CopyExecutionResolutionError(
            "COPY_V2_PRODUCT_TRUTH_LINEAGE_MISSING",
            "V2 execution requires current Product Truth lineage.",
        )
    if current_lineage.snapshot_status != "APPROVED":
        raise CopyExecutionResolutionError(
            "COPY_V2_PRODUCT_TRUTH_STALE",
            "V2 execution requires an approved current Product Truth snapshot.",
        )

    adapter = _adapter_context(context, product_id=product_id, lineage=current_lineage)
    raw_blueprint = context.get("blueprint") or context.get("copy_blueprint")
    raw_binding = context.get("binding") or context.get("copy_execution_binding")
    if raw_binding is not None:
        raise CopyExecutionResolutionError(
            "COPY_V2_BINDING_INPUT_FORBIDDEN",
            "Consumers submit a blueprint context; the resolver creates the binding.",
        )

    facts = context.get("evidence_facts") or context.get("facts") or ()
    try:
        registry = EvidenceRegistry(
            facts=tuple(EvidenceFact.model_validate(item) for item in facts)
        )
    except Exception as exc:  # noqa: BLE001
        raise CopyExecutionResolutionError(
            "COPY_V2_EVIDENCE_INVALID",
            "Evidence registry is invalid for the V2 consumer request.",
            details=str(exc),
        ) from exc

    if descriptor.copy_policy == "NOT_REQUIRED":
        if raw_blueprint is not None:
            raise CopyExecutionResolutionError(
                "COPY_V2_BINDING_NOT_REQUIRED",
                f"{descriptor.lane_id} explicitly declares COPY_NOT_REQUIRED.",
            )
        try:
            projection = project_image_copy(descriptor.lane_id, context=adapter)
        except CopyBlueprintV2Error as exc:
            raise _error_from_v2(exc) from exc
        return CopyExecutionResolution(
            lane=descriptor.lane_id,
            media_kind=descriptor.media_kind,
            copy_policy=descriptor.copy_policy,
            feature_flags=flags,
            v2_enabled=True,
            status="READY",
            projection=projection,
            metadata={
                "policy_source": "copy_architecture_v2",
                "copy_free_explicit": True,
                "readiness_validated": adapter.readiness_validated,
                "provenance_validated": adapter.provenance_validated,
                "safety_validated": adapter.safety_validated,
                "semantic_review_validated": adapter.semantic_review_validated,
            },
        )

    adapter_raw = _as_dict(context.get("adapter_context") or context.get("context"))
    semantic_review_declared = "semantic_review_validated" in adapter_raw or (
        "semantic_review_validated" in context
    )
    if not semantic_review_declared:
        raise CopyExecutionResolutionError(
            "COPY_V2_SEMANTIC_REVIEW_REQUIRED",
            "COPY_REQUIRED V2 execution requires explicit semantic review proof.",
        )
    if not adapter.semantic_review_validated:
        raise CopyExecutionResolutionError(
            "COPY_V2_SEMANTIC_REVIEW_REQUIRED",
            "COPY_REQUIRED V2 execution requires completed semantic review.",
        )

    if raw_blueprint is None:
        raise CopyExecutionResolutionError(
            "COPY_V2_BLUEPRINT_REQUIRED",
            f"{descriptor.lane_id} requires an explicit V2 blueprint context.",
        )
    try:
        blueprint = CopyBlueprintV2.model_validate(raw_blueprint)
    except Exception as exc:  # noqa: BLE001
        raise CopyExecutionResolutionError(
            "COPY_V2_BLUEPRINT_INVALID",
            "V2 blueprint is invalid and cannot bind.",
            details=str(exc),
        ) from exc
    if blueprint.product_id != product_id:
        raise CopyExecutionResolutionError(
            "COPY_V2_PRODUCT_MISMATCH",
            "V2 blueprint belongs to another product.",
        )
    try:
        binding = bind_copy_blueprint_v2(
            blueprint,
            lane=descriptor.lane_id,
            current_product_truth=current_lineage,
            evidence_registry=registry,
            feature_flags=flags,
            compiler_binding_version=str(
                context.get("compiler_binding_version") or "copy-execution-binding-v2"
            ),
            bound_at=str(
                context.get("bound_at")
                or datetime.now(timezone.utc).isoformat()
            ),
        )
        projection = (
            project_video_copy(binding, blueprint, context=adapter)
            if descriptor.media_kind == "VIDEO"
            else project_image_copy(
                descriptor.lane_id,
                context=adapter,
                binding=binding,
                blueprint=blueprint,
            )
        )
    except CopyBlueprintV2Error as exc:
        raise _error_from_v2(exc) from exc
    approved_dialogue = _approved_dialogue(blueprint)
    return CopyExecutionResolution(
        lane=descriptor.lane_id,
        media_kind=descriptor.media_kind,
        copy_policy=descriptor.copy_policy,
        feature_flags=flags,
        v2_enabled=True,
        status="READY",
        binding=binding,
        projection=projection,
        compiler_copy_intelligence=_compiler_copy(blueprint),
        approved_dialogue=approved_dialogue,
        metadata={
            "policy_source": "copy_architecture_v2",
            "blueprint_id": blueprint.blueprint_id,
            "revision": blueprint.revision,
            "formula_id": blueprint.formula_id,
            "formula_version": blueprint.formula_version,
            "approval_snapshot_id": (
                blueprint.approval_snapshot.approval_snapshot_id
                if blueprint.approval_snapshot
                else None
            ),
            "revalidation_action": "NONE",
            "semantic_review_action": "NONE",
            "approved_copy_immutable": True,
            "compiler_mutation_allowed": False,
            "semantic_review_validated": adapter.semantic_review_validated,
        },
    )


def copy_v2_handoff_context(
    request_context: Mapping[str, Any] | BaseModel | None,
    resolution: CopyExecutionResolution,
) -> dict[str, Any] | None:
    """Return the validated re-entry context for a durable V2 handoff.

    The binding object is still the durable identity.  Persisting this
    context lets a later consumer revalidate the same blueprint/evidence
    envelope without accepting a caller-supplied binding or changing the
    legacy path when V2 is disabled.
    """

    if not resolution.v2_enabled:
        return None
    context = _context_dict(request_context)
    context["lane"] = resolution.lane
    if resolution.binding is not None:
        context["bound_at"] = resolution.binding.bound_at
    return context


__all__ = [
    "CopyExecutionResolution",
    "CopyExecutionResolutionError",
    "copy_v2_handoff_context",
    "lane_for_request",
    "resolve_copy_execution_binding",
]
