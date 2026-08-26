"""Request-scoped BENEFIT_COPY_RENDER_V1 execution authority (Round 2).

A finalized rendered copy candidate is resolved into the SAME compiler-copy shape
the canonical prompt compiler already consumes (``compiler_copy_intelligence`` +
``approved_dialogue``) — but as a DISTINCT, honest authority: ``authority_kind =
BENEFIT_COPY_RENDER_V1``, ``v2_enabled = False``, ``binding = None``,
``projection = None``. It NEVER claims a Copy-Register-V2 binding exists and never
touches the product-global pointer. ZERO provider calls.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent.authority import copy_blueprint_v2_authority as _formula
from agent.db import copy_render_crud as _crud
from agent.models.copy_blueprint_v2 import CopyBlueprintV2FeatureFlagState
from agent.models.copy_render_v1 import (
    BENEFIT_COPY_RENDER_AUTHORITY,
    BENEFIT_COPY_RENDER_SOURCE,
)
from agent.services.copy_execution_resolver import (
    CopyExecutionResolution,
    CopyExecutionResolutionError,
)


def _render_feature_flags() -> CopyBlueprintV2FeatureFlagState:
    # A neutral, honest flag state for lineage dumps. Render readiness is carried
    # by copy_ready / authority_kind, NOT by these V2 flags.
    return CopyBlueprintV2FeatureFlagState(
        flag_name="BENEFIT_COPY_RENDER_V1",
        enabled=True,
        shadow_mode=False,
        scope="",
        pilot_scope=(),
        state="ON",
    )


def _map_field(mapping_value: Any, stage_text: Mapping[str, str]) -> str:
    keys = mapping_value if isinstance(mapping_value, (list, tuple)) else [mapping_value]
    return " ".join(str(stage_text.get(str(k), "")).strip() for k in keys if k).strip()


def _map_list(mapping_value: Any, stage_text: Mapping[str, str]) -> list[str]:
    keys = mapping_value if isinstance(mapping_value, (list, tuple)) else [mapping_value]
    out = [str(stage_text.get(str(k), "")).strip() for k in keys if k]
    return [x for x in out if x]


def build_compiler_copy_intelligence(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Self-built compiler copy (NOT via _compiler_copy / bind_copy_blueprint_v2)."""
    import json

    formula_id = artifact["formula_id"]
    contract = _formula.strict_formula_contract(formula_id)
    output_mapping = contract.get("output_mapping") or {}
    slot_purpose = {s["slot_id"]: s.get("purpose", "") for s in (contract.get("slots") or [])}
    stages = artifact["stage_json"]
    if isinstance(stages, str):
        stages = json.loads(stages or "[]")
    stage_text = {str(s["stage_key"]): str(s["text"]) for s in stages}
    approved_execution_text = [
        {
            "stage_key": str(s["stage_key"]),
            "formula_stage_key": str(s["stage_key"]),
            "semantic_role": slot_purpose.get(str(s["stage_key"]), str(s["stage_key"])),
            "text": str(s["text"]),
        }
        for s in stages
    ]
    return {
        "copy_source": BENEFIT_COPY_RENDER_SOURCE,
        "formula_id": formula_id,
        "formula_version": artifact["formula_version"],
        "hook": _map_field(output_mapping.get("hook", []), stage_text),
        "subhook": _map_field(output_mapping.get("subhook", []), stage_text),
        "angle": _map_field(output_mapping.get("angle", []), stage_text),
        "usps": _map_list(output_mapping.get("usp", []), stage_text),
        "cta": _map_field(output_mapping.get("cta", []), stage_text),
        "approved_execution_text": approved_execution_text,
        "target_duration_seconds": int(artifact["duration_seconds"]),
        "estimated_word_count": int(artifact["word_count"]),
        "wps_profile": artifact.get("wps_mode") or "SWEET",
    }


async def resolve_rendered_copy_execution(
    product_id: str, lane: str, candidate_id: str
) -> CopyExecutionResolution:
    """Resolve a finalized rendered candidate into an execution-copy authority."""
    candidate = await _crud.get_candidate(candidate_id)
    if candidate is None:
        raise CopyExecutionResolutionError(
            "BENEFIT_COPY_RENDER_CANDIDATE_NOT_FOUND",
            "Unknown copy-render candidate.",
            details={"candidate_id": candidate_id},
        )
    session = await _crud.get_session(candidate["session_id"])
    if session is None or session["product_id"] != product_id:
        raise CopyExecutionResolutionError(
            "BENEFIT_COPY_RENDER_PRODUCT_MISMATCH",
            "Candidate does not belong to this product.",
            details={"candidate_id": candidate_id},
        )
    if str(session["lane"]) != str(lane):
        raise CopyExecutionResolutionError(
            "BENEFIT_COPY_RENDER_LANE_MISMATCH",
            "Candidate lane does not match the requested lane.",
            details={"session_lane": session["lane"], "requested_lane": lane},
        )
    if candidate["status"] not in ("LOCKED", "FINALIZED"):
        raise CopyExecutionResolutionError(
            "BENEFIT_COPY_RENDER_CANDIDATE_NOT_SELECTED",
            "Only a locked or finalized candidate can be resolved for execution.",
            details={"status": candidate["status"]},
        )
    artifact = await _crud.get_artifact(candidate["artifact_id"])
    if artifact is None:
        raise CopyExecutionResolutionError(
            "BENEFIT_COPY_RENDER_ARTIFACT_MISSING",
            "The rendered artifact for this candidate is missing.",
            details={"artifact_id": candidate["artifact_id"]},
        )

    compiler_copy = build_compiler_copy_intelligence(artifact)
    approved_dialogue = str(artifact["full_copy_text"]).strip()
    if not approved_dialogue:
        raise CopyExecutionResolutionError(
            "BENEFIT_COPY_RENDER_EMPTY_DIALOGUE",
            "The rendered artifact has no dialogue text.",
            details={"artifact_id": artifact["artifact_id"]},
        )
    metadata = {
        "authority_kind": BENEFIT_COPY_RENDER_AUTHORITY,
        "session_id": session["session_id"],
        "candidate_id": candidate_id,
        "artifact_id": artifact["artifact_id"],
        "render_key": artifact["render_key"],
        "recipe_fingerprint": candidate["recipe_fingerprint"],
        "text_digest": artifact["text_digest"],
        "benefit_id": session["benefit_id"],
        "formula_id": artifact["formula_id"],
        "formula_version": artifact["formula_version"],
        "duration_seconds": int(artifact["duration_seconds"]),
        "target_language": artifact["target_language"],
        "wps_authority_version": artifact["wps_authority_version"],
        "wps_authority_digest": artifact["wps_authority_digest"],
    }
    return CopyExecutionResolution(
        lane=lane,
        media_kind="VIDEO",
        copy_policy="REQUIRED",
        feature_flags=_render_feature_flags(),
        v2_enabled=False,
        status="READY",
        binding=None,
        projection=None,
        compiler_copy_intelligence=compiler_copy,
        approved_dialogue=approved_dialogue,
        metadata=metadata,
        authority_kind=BENEFIT_COPY_RENDER_AUTHORITY,
    )
