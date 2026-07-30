"""P7.5-B bounded Creative Treatment authority.

No provider, compiler, scheduler, or production-plan surface is imported here.
Every review transition re-resolves upstream authority and fails closed on
staleness, incompatibility, or undeclared same-dialogue variation.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from agent.db import creative_treatment_crud as treatment_crud
from agent.db import crud
from agent.models.creative_treatment import (
    APPROVE_TREATMENT_CONFIRMATION,
    APPROVE_VARIATION_GROUP_CONFIRMATION,
    CreateTreatmentRequest,
    CreateVariationGroupRequest,
    ReviewTreatmentRequest,
    ReviewVariationGroupRequest,
)
from agent.services import avatar_registry
from agent.services.creative_handoff_service import prepare_generation_handoff
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
    require_verified_product_strategy_taxonomy,
)
from agent.services.scene_strategy_library import SCENE_STRATEGIES


class CreativeTreatmentError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class ResolvedAuthority:
    product_truth: dict[str, Any]
    copy_set: dict[str, Any]
    selection: dict[str, Any]
    taxonomy: dict[str, Any]
    scene_strategy: dict[str, Any]
    handoff: dict[str, Any]
    avatar_profile: dict[str, Any] | None
    assets: list[dict[str, Any]]
    dialogue_text: str


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CreativeTreatmentError(
                "NON_FINITE_CANONICAL_NUMBER",
                status_code=422,
            )
        return int(value) if value.is_integer() else value
    return value


def _canonical(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return _normalize_scalar(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CreativeTreatmentError(
            "UPSTREAM_AUTHORITY_JSON_INVALID",
            status_code=422,
        ) from exc


def _dialogue_from_copy(copy_set: dict[str, Any]) -> str:
    usp_values = _parse_json(copy_set.get("usp_set_json"), [])
    usp_parts: list[str] = []
    if isinstance(usp_values, list):
        for item in usp_values:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(
                    item.get("text")
                    or item.get("value")
                    or item.get("usp")
                    or ""
                ).strip()
            else:
                text = ""
            if text:
                usp_parts.append(text)
    parts = [
        str(copy_set.get("hook") or "").strip(),
        str(copy_set.get("subhook") or "").strip(),
        *usp_parts,
        str(copy_set.get("cta") or "").strip(),
    ]
    dialogue = "\n".join(part for part in parts if part)
    if not dialogue:
        raise CreativeTreatmentError("COPY_SET_DIALOGUE_EMPTY", status_code=422)
    return unicodedata.normalize("NFC", dialogue)


def _projection(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields}


def _semantic_projection(
    row: dict[str, Any],
    fields: tuple[str, ...],
    json_fields: tuple[str, ...],
) -> dict[str, Any]:
    result = _projection(row, fields)
    list_fields = {
        "allowed_modes",
        "engine_slot_eligibility",
        "benefits_json",
        "usp_json",
        "allowed_claims_json",
        "blocked_claims_json",
        "usp_set_json",
    }
    for field in json_fields:
        result[field] = _parse_json(
            result.get(field),
            [] if field in list_fields else {},
        )
    return result


PRODUCT_TRUTH_FIELDS = (
    "snapshot_id",
    "product_id",
    "version",
    "status",
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "claim_gate",
    "claim_risk_level",
    "allowed_claims_json",
    "blocked_claims_json",
)
COPY_SET_FIELDS = (
    "copy_set_id",
    "product_id",
    "angle",
    "hook",
    "subhook",
    "usp_set_json",
    "cta",
    "platform",
    "language",
    "route_type",
    "formula_family",
    "status",
    "archived",
)
SELECTION_FIELDS = (
    "product_id",
    "selection_id",
    "cluster",
    "cluster_source",
    "selected_avatar_code",
    "selected_scene_template_id",
    "selected_camera_preset_code",
    "selected_block_purpose",
    "selected_content_type",
    "notes",
    "preview_json",
    "provenance_json",
    "status",
)
ASSET_FIELDS = (
    "asset_id",
    "semantic_role",
    "source_type",
    "storage_kind",
    "preview_url",
    "download_url",
    "media_id",
    "local_file_path",
    "remote_source_url",
    "product_id",
    "allowed_modes",
    "engine_slot_eligibility",
    "source_prompt_fingerprint",
    "source_workspace_execution_package_id",
    "source_prompt_package_snapshot_id",
    "generation_recipe_id",
    "contains_rendered_text",
    "approved_for_video_support",
    "product_truth_status",
    "identity_lock_status",
    "scale_truth_status",
    "claim_safety_status",
    "review_status",
    "status",
)


def _taxonomy_projection(taxonomy: Any) -> dict[str, Any]:
    return {
        "product_id": taxonomy.product_id,
        "taxonomy_version": taxonomy.taxonomy_version,
        "product_fingerprint": taxonomy.product_fingerprint,
        "cluster": taxonomy.cluster,
        "product_type_group": taxonomy.product_type_group,
        "matched_scene_strategy_id": taxonomy.matched_scene_strategy_id,
        "scene_coverage_status": taxonomy.scene_coverage_status,
        "fallback_used": taxonomy.fallback_used,
        "specific_strategy": taxonomy.specific_strategy,
        "classification_confidence": taxonomy.classification_confidence,
        "review_status": taxonomy.review_status,
        "consumer_status": taxonomy.consumer_status,
        "authority_source": taxonomy.authority_source,
        "materialization_status": taxonomy.materialization_status,
        "is_stale": taxonomy.is_stale,
    }


def _validate_sequence(body: CreateTreatmentRequest, strategy: dict[str, Any]) -> None:
    action_sequences = [step.sequence for step in body.action_sequence]
    if action_sequences != list(range(1, len(action_sequences) + 1)):
        raise CreativeTreatmentError(
            "ACTION_SEQUENCE_NOT_CONTIGUOUS",
            status_code=422,
        )
    allowed_actions = list(strategy.get("allowed_actions") or ())
    for step in body.action_sequence:
        if step.allowed_action_index >= len(allowed_actions):
            raise CreativeTreatmentError(
                "ACTION_INDEX_NOT_ALLOWED",
                status_code=422,
                details={"sequence": step.sequence},
            )
        canonical_action = str(allowed_actions[step.allowed_action_index])
        if step.action_text != canonical_action:
            raise CreativeTreatmentError(
                "ACTION_TEXT_NOT_CANONICAL",
                status_code=422,
                details={
                    "sequence": step.sequence,
                    "expected_action_text": canonical_action,
                },
            )
        lowered = step.action_text.casefold()
        for forbidden in strategy.get("forbidden_actions") or ():
            if str(forbidden).casefold() in lowered:
                raise CreativeTreatmentError(
                    "FORBIDDEN_ACTION",
                    status_code=422,
                    details={"sequence": step.sequence},
                )

    shot_sequences = [shot.sequence for shot in body.shot_grammar]
    if shot_sequences != list(range(1, len(shot_sequences) + 1)):
        raise CreativeTreatmentError(
            "SHOT_SEQUENCE_NOT_CONTIGUOUS",
            status_code=422,
        )
    covered: set[int] = set()
    permitted = set(action_sequences)
    for shot in body.shot_grammar:
        referenced = set(shot.action_sequences)
        if not referenced.issubset(permitted):
            raise CreativeTreatmentError(
                "SHOT_REFERENCES_UNKNOWN_ACTION",
                status_code=422,
                details={"shot_sequence": shot.sequence},
            )
        covered.update(referenced)
    if covered != permitted:
        raise CreativeTreatmentError(
            "SHOT_GRAMMAR_ACTION_COVERAGE_INCOMPLETE",
            status_code=422,
        )
    total_duration = sum(shot.duration_seconds for shot in body.shot_grammar)
    if not math.isclose(total_duration, body.duration_seconds, abs_tol=0.001):
        raise CreativeTreatmentError(
            "SHOT_DURATION_TOTAL_MISMATCH",
            status_code=422,
            details={
                "treatment_duration_seconds": body.duration_seconds,
                "shot_duration_seconds": total_duration,
            },
        )


def _validate_format(
    body: CreateTreatmentRequest,
    avatar_profile: dict[str, Any] | None,
) -> None:
    actor_roles = {step.actor_role for step in body.action_sequence}
    if body.format == "UGC":
        if not avatar_profile:
            raise CreativeTreatmentError("UGC_AVATAR_REQUIRED", status_code=422)
        if not str(avatar_profile.get("wardrobe") or "").strip():
            raise CreativeTreatmentError("UGC_WARDROBE_REQUIRED", status_code=422)
        if "PRESENTER" not in actor_roles:
            raise CreativeTreatmentError(
                "UGC_PRESENTER_ACTION_REQUIRED",
                status_code=422,
            )
    elif body.format == "PGC":
        if avatar_profile or "PRESENTER" in actor_roles:
            raise CreativeTreatmentError(
                "PGC_PRODUCT_LED_ACTOR_REQUIRED",
                status_code=422,
            )
    elif avatar_profile and not str(avatar_profile.get("wardrobe") or "").strip():
        raise CreativeTreatmentError(
            "CINEMATIC_AVATAR_WARDROBE_REQUIRED",
            status_code=422,
        )


async def _resolve_assets(
    body: CreateTreatmentRequest,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    for binding in body.asset_bindings:
        if binding.asset_id in seen_ids:
            raise CreativeTreatmentError(
                "DUPLICATE_ASSET_BINDING",
                status_code=422,
            )
        seen_ids.add(binding.asset_id)
        asset = await crud.get_creative_asset(binding.asset_id)
        if not asset:
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_NOT_FOUND",
                status_code=404,
                details={"asset_id": binding.asset_id},
            )
        if asset.get("semantic_role") != binding.role:
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_ROLE_MISMATCH",
                status_code=422,
                details={"asset_id": binding.asset_id},
            )
        if asset.get("status") != "ACTIVE":
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_INACTIVE",
                details={"asset_id": binding.asset_id},
            )
        if asset.get("review_status") != "APPROVED":
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_NOT_APPROVED",
                details={"asset_id": binding.asset_id},
            )
        if not bool(asset.get("approved_for_video_support")):
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_NOT_APPROVED_FOR_VIDEO",
                details={"asset_id": binding.asset_id},
            )
        asset_product_id = str(asset.get("product_id") or "")
        if asset_product_id and asset_product_id != body.product_id:
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_PRODUCT_MISMATCH",
                status_code=422,
                details={"asset_id": binding.asset_id},
            )
        allowed_modes = _parse_json(asset.get("allowed_modes"), [])
        if (
            not isinstance(allowed_modes, list)
            or body.compatibility_profile.logical_mode not in allowed_modes
        ):
            raise CreativeTreatmentError(
                "CREATIVE_ASSET_MODE_INCOMPATIBLE",
                status_code=422,
                details={"asset_id": binding.asset_id},
            )
        seen_roles.add(binding.role)
        projection = _semantic_projection(
            asset,
            ASSET_FIELDS,
            ("allowed_modes", "engine_slot_eligibility"),
        )
        assets.append(
            {
                "role": binding.role,
                "asset_id": binding.asset_id,
                "asset_sha256": canonical_sha256(projection),
                "authority": projection,
            }
        )
    required_roles = set(body.compatibility_profile.required_asset_roles)
    missing_roles = sorted(required_roles - seen_roles)
    if missing_roles:
        raise CreativeTreatmentError(
            "REQUIRED_ASSET_ROLE_MISSING",
            status_code=422,
            details={"missing_roles": missing_roles},
        )
    return sorted(assets, key=lambda item: (item["role"], item["asset_id"]))


async def _resolve_authority(
    body: CreateTreatmentRequest,
) -> ResolvedAuthority:
    snapshot = await crud.get_product_intelligence_snapshot(
        body.product_truth_snapshot_id,
    )
    if not snapshot:
        raise CreativeTreatmentError(
            "PRODUCT_TRUTH_SNAPSHOT_NOT_FOUND",
            status_code=404,
        )
    if (
        snapshot.get("product_id") != body.product_id
        or snapshot.get("status") != "APPROVED"
    ):
        raise CreativeTreatmentError(
            "PRODUCT_TRUTH_SNAPSHOT_NOT_APPROVED",
            status_code=422,
        )
    latest_snapshot = await crud.get_latest_approved_product_intelligence_snapshot(
        body.product_id,
    )
    if (
        not latest_snapshot
        or latest_snapshot.get("snapshot_id") != body.product_truth_snapshot_id
    ):
        raise CreativeTreatmentError("PRODUCT_TRUTH_SNAPSHOT_STALE")

    copy_set = await crud.get_copy_set(body.copy_set_id)
    if not copy_set:
        raise CreativeTreatmentError("COPY_SET_NOT_FOUND", status_code=404)
    if copy_set.get("product_id") != body.product_id:
        raise CreativeTreatmentError("COPY_SET_PRODUCT_MISMATCH", status_code=422)
    if copy_set.get("status") != "COPY_APPROVED" or bool(
        copy_set.get("archived"),
    ):
        raise CreativeTreatmentError("COPY_SET_NOT_APPROVED")

    selection = await crud.get_creative_product_selection(body.product_id)
    if not selection:
        raise CreativeTreatmentError(
            "CREATIVE_SELECTION_NOT_FOUND",
            status_code=404,
        )
    if (
        selection.get("selection_id") != body.creative_selection_id
        or selection.get("status") != "APPROVED"
    ):
        raise CreativeTreatmentError("CREATIVE_SELECTION_NOT_APPROVED")
    try:
        handoff = await prepare_generation_handoff(body.product_id)
    except ValueError as exc:
        raise CreativeTreatmentError(str(exc)) from exc

    try:
        taxonomy_model = await require_verified_product_strategy_taxonomy(
            body.product_id,
        )
    except ProductStrategyTaxonomyError as exc:
        raise CreativeTreatmentError(
            "PRODUCT_STRATEGY_TAXONOMY_NOT_VERIFIED",
            details={"upstream_error": str(exc)},
        ) from exc
    taxonomy = _taxonomy_projection(taxonomy_model)
    if (
        taxonomy["matched_scene_strategy_id"] != body.scene_strategy_id
        or taxonomy["fallback_used"]
        or not taxonomy["specific_strategy"]
        or taxonomy["scene_coverage_status"] == "FALLBACK_ONLY"
        or body.scene_strategy_id == "GENERIC_FALLBACK"
    ):
        raise CreativeTreatmentError(
            "SCENE_STRATEGY_NOT_SPECIFIC_VERIFIED_AUTHORITY",
            status_code=422,
        )
    strategy = SCENE_STRATEGIES.get(body.scene_strategy_id)
    if not strategy:
        raise CreativeTreatmentError(
            "SCENE_STRATEGY_NOT_REGISTERED",
            status_code=422,
        )
    scene_strategy = {
        "strategy_id": body.scene_strategy_id,
        **{key: list(value) if isinstance(value, tuple) else value for key, value in strategy.items()},
        "taxonomy": taxonomy,
    }

    avatar_code = selection.get("selected_avatar_code")
    avatar_profile: dict[str, Any] | None = None
    if avatar_code:
        try:
            avatar_profile = avatar_registry.resolve_presenter(
                avatar_id=str(avatar_code),
            )
        except ValueError as exc:
            raise CreativeTreatmentError(
                "INVALID_AVATAR_CODE",
                status_code=422,
            ) from exc
    _validate_format(body, avatar_profile)
    _validate_sequence(body, strategy)
    assets = await _resolve_assets(body)
    dialogue_text = _dialogue_from_copy(copy_set)
    return ResolvedAuthority(
        product_truth=snapshot,
        copy_set=copy_set,
        selection=selection,
        taxonomy=taxonomy,
        scene_strategy=scene_strategy,
        handoff=handoff,
        avatar_profile=avatar_profile,
        assets=assets,
        dialogue_text=dialogue_text,
    )


def _build_treatment_snapshot(
    *,
    treatment_id: str,
    body: CreateTreatmentRequest,
    authority: ResolvedAuthority,
) -> dict[str, Any]:
    avatar_profile = authority.avatar_profile
    handoff = authority.handoff
    scene = handoff["scene_template"]
    camera = handoff["camera_preset"]
    action_sequence = [
        item.model_dump(mode="json") for item in body.action_sequence
    ]
    shot_grammar = [item.model_dump(mode="json") for item in body.shot_grammar]
    compatibility = body.compatibility_profile.model_dump(mode="json")
    asset_bindings = [
        {
            "role": item["role"],
            "asset_id": item["asset_id"],
            "asset_sha256": item["asset_sha256"],
        }
        for item in authority.assets
    ]
    hashes = {
        "product_truth_sha256": canonical_sha256(
            _semantic_projection(
                authority.product_truth,
                PRODUCT_TRUTH_FIELDS,
                (
                    "benefits_json",
                    "usp_json",
                    "allowed_claims_json",
                    "blocked_claims_json",
                ),
            ),
        ),
        "copy_set_sha256": canonical_sha256(
            _semantic_projection(
                authority.copy_set,
                COPY_SET_FIELDS,
                ("usp_set_json",),
            ),
        ),
        "creative_selection_sha256": canonical_sha256(
            _semantic_projection(
                authority.selection,
                SELECTION_FIELDS,
                ("preview_json", "provenance_json"),
            ),
        ),
        "scene_strategy_sha256": canonical_sha256(authority.scene_strategy),
        "avatar_sha256": canonical_sha256(avatar_profile)
        if avatar_profile
        else None,
        "wardrobe_sha256": canonical_sha256(avatar_profile["wardrobe"])
        if avatar_profile
        else None,
        "scene_template_sha256": canonical_sha256(scene)
        if scene.get("template_id")
        else None,
        "camera_preset_sha256": canonical_sha256(camera)
        if camera.get("preset_code")
        else None,
        "dialogue_sha256": canonical_sha256(authority.dialogue_text),
    }
    visual_projection = {
        "format": body.format,
        "duration_seconds": body.duration_seconds,
        "avatar_profile": avatar_profile,
        "scene_template": scene,
        "camera_preset": camera,
        "asset_bindings": asset_bindings,
        "action_sequence": action_sequence,
        "shot_grammar": shot_grammar,
        "compatibility_profile": compatibility,
    }
    visual_fingerprint = canonical_sha256(visual_projection)
    content = {
        "treatment_id": treatment_id,
        "product_id": body.product_id,
        "format": body.format,
        "generation_mode": body.generation_mode,
        "duration_seconds": body.duration_seconds,
        "product_truth_snapshot_id": body.product_truth_snapshot_id,
        "copy_set_id": body.copy_set_id,
        "creative_selection_id": body.creative_selection_id,
        "scene_strategy_id": body.scene_strategy_id,
        "content_angle": str(authority.copy_set.get("angle") or ""),
        "dialogue_text": authority.dialogue_text,
        "avatar_code": authority.selection.get("selected_avatar_code"),
        "wardrobe_text": (avatar_profile or {}).get("wardrobe"),
        "scene_template_id": scene.get("template_id"),
        "camera_preset_code": camera.get("preset_code"),
        "asset_bindings": asset_bindings,
        "action_sequence": action_sequence,
        "shot_grammar": shot_grammar,
        "compatibility_profile": compatibility,
        "variation_group_id": body.variation_group_id,
        "variation_ordinal": body.variation_ordinal,
        "supersedes_treatment_id": body.supersedes_treatment_id,
        "visual_fingerprint_sha256": visual_fingerprint,
        **hashes,
    }
    return {
        **content,
        "treatment_sha256": canonical_sha256(content),
    }


def _stored_request(row: dict[str, Any]) -> CreateTreatmentRequest:
    return CreateTreatmentRequest(
        product_id=row["product_id"],
        product_truth_snapshot_id=row["product_truth_snapshot_id"],
        copy_set_id=row["copy_set_id"],
        creative_selection_id=row["creative_selection_id"],
        scene_strategy_id=row["scene_strategy_id"],
        format=row["format"],
        generation_mode=row["generation_mode"],
        duration_seconds=row["duration_seconds"],
        action_sequence=_parse_json(row["action_sequence_json"], []),
        shot_grammar=_parse_json(row["shot_grammar_json"], []),
        compatibility_profile=_parse_json(
            row["compatibility_profile_json"],
            {},
        ),
        asset_bindings=[
            {"role": item["role"], "asset_id": item["asset_id"]}
            for item in _parse_json(row["asset_bindings_json"], [])
        ],
        variation_group_id=row.get("variation_group_id"),
        variation_ordinal=row.get("variation_ordinal"),
        supersedes_treatment_id=row.get("supersedes_treatment_id"),
        created_by=row["created_by"],
    )


async def _revalidate(row: dict[str, Any]) -> dict[str, Any]:
    body = _stored_request(row)
    authority = await _resolve_authority(body)
    current = _build_treatment_snapshot(
        treatment_id=row["treatment_id"],
        body=body,
        authority=authority,
    )
    if current["treatment_sha256"] != row["treatment_sha256"]:
        raise CreativeTreatmentError(
            "TREATMENT_AUTHORITY_STALE",
            details={
                "stored_sha256": row["treatment_sha256"],
                "current_sha256": current["treatment_sha256"],
            },
        )
    return current


async def _validate_variation_binding(
    *,
    body: CreateTreatmentRequest,
    dialogue_sha256: str,
) -> None:
    if not body.variation_group_id:
        return
    group = await treatment_crud.get_variation_group(body.variation_group_id)
    if not group:
        raise CreativeTreatmentError("VARIATION_GROUP_NOT_FOUND", status_code=404)
    if (
        group["product_id"] != body.product_id
        or group["copy_set_id"] != body.copy_set_id
        or group["dialogue_sha256"] != dialogue_sha256
    ):
        raise CreativeTreatmentError(
            "VARIATION_GROUP_AUTHORITY_MISMATCH",
            status_code=422,
        )
    if group["status"] != "DRAFT":
        raise CreativeTreatmentError("VARIATION_GROUP_MEMBERSHIP_FROZEN")
    members = await treatment_crud.list_group_members(body.variation_group_id)
    if len(members) >= 5:
        raise CreativeTreatmentError("VARIATION_GROUP_MEMBER_LIMIT")


def _decode_treatment(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in (
        "asset_bindings_json",
        "action_sequence_json",
        "shot_grammar_json",
        "compatibility_profile_json",
    ):
        result[key.removesuffix("_json")] = _parse_json(result.pop(key), [])
    return result


def _decode_audit(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _parse_json(result.pop("evidence_json"), {})
    return result


async def create_treatment(body: CreateTreatmentRequest) -> dict[str, Any]:
    treatment_id = str(uuid.uuid4())
    authority = await _resolve_authority(body)
    snapshot = _build_treatment_snapshot(
        treatment_id=treatment_id,
        body=body,
        authority=authority,
    )
    await _validate_variation_binding(
        body=body,
        dialogue_sha256=snapshot["dialogue_sha256"],
    )
    predecessor = None
    if body.supersedes_treatment_id:
        predecessor = await treatment_crud.get_treatment(
            body.supersedes_treatment_id,
        )
        if (
            not predecessor
            or predecessor["product_id"] != body.product_id
            or predecessor["status"] != "APPROVED"
        ):
            raise CreativeTreatmentError(
                "SUPERSEDED_TREATMENT_NOT_APPROVED",
                status_code=422,
            )
    row = {
        **snapshot,
        "status": "DRAFT",
        "created_by": body.created_by,
        "asset_bindings_json": _canonical_json(snapshot["asset_bindings"]),
        "action_sequence_json": _canonical_json(snapshot["action_sequence"]),
        "shot_grammar_json": _canonical_json(snapshot["shot_grammar"]),
        "compatibility_profile_json": _canonical_json(
            snapshot["compatibility_profile"],
        ),
    }
    created = await treatment_crud.create_treatment(row)
    return _decode_treatment(created)


async def get_treatment(treatment_id: str) -> dict[str, Any]:
    row = await treatment_crud.get_treatment(treatment_id)
    if not row:
        raise CreativeTreatmentError(
            "CREATIVE_TREATMENT_NOT_FOUND",
            status_code=404,
        )
    result = _decode_treatment(row)
    result["audit_events"] = [
        _decode_audit(event)
        for event in await treatment_crud.list_audit_events(
            entity_type="TREATMENT",
            entity_id=treatment_id,
        )
    ]
    return result


async def list_treatments(
    *,
    product_id: str | None,
    status: str | None,
    variation_group_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = await treatment_crud.list_treatments(
        product_id=product_id,
        status=status,
        variation_group_id=variation_group_id,
        limit=limit,
    )
    return [_decode_treatment(row) for row in rows]


async def submit_treatment_review(
    treatment_id: str,
    *,
    actor_id: str,
) -> dict[str, Any]:
    row = await treatment_crud.get_treatment(treatment_id)
    if not row:
        raise CreativeTreatmentError(
            "CREATIVE_TREATMENT_NOT_FOUND",
            status_code=404,
        )
    if row["status"] != "DRAFT":
        raise CreativeTreatmentError("TREATMENT_NOT_DRAFT")
    current = await _revalidate(row)
    transitioned = await treatment_crud.transition_treatment(
        treatment_id=treatment_id,
        source_status="DRAFT",
        target_status="REVIEW_REQUIRED",
        actor_id=actor_id,
        reviewer_note=None,
        evidence={"treatment_sha256": current["treatment_sha256"]},
    )
    if not transitioned:
        raise CreativeTreatmentError("TREATMENT_TRANSITION_CONFLICT")
    return _decode_treatment(transitioned)


async def review_treatment(
    treatment_id: str,
    body: ReviewTreatmentRequest,
) -> dict[str, Any]:
    row = await treatment_crud.get_treatment(treatment_id)
    if not row:
        raise CreativeTreatmentError(
            "CREATIVE_TREATMENT_NOT_FOUND",
            status_code=404,
        )
    if row["status"] != "REVIEW_REQUIRED":
        raise CreativeTreatmentError("TREATMENT_NOT_REVIEW_REQUIRED")
    if body.expected_sha256 != row["treatment_sha256"]:
        raise CreativeTreatmentError("TREATMENT_HASH_CONFIRMATION_MISMATCH")
    if body.decision == "APPROVED":
        if body.confirmation != APPROVE_TREATMENT_CONFIRMATION:
            raise CreativeTreatmentError("TREATMENT_CONFIRMATION_REQUIRED")
        await _revalidate(row)
        same_dialogue = await treatment_crud.list_approved_same_dialogue(
            product_id=row["product_id"],
            dialogue_sha256=row["dialogue_sha256"],
            exclude_treatment_id=treatment_id,
        )
        same_dialogue = [
            item
            for item in same_dialogue
            if item["treatment_id"] != row.get("supersedes_treatment_id")
        ]
        group_id = row.get("variation_group_id")
        if same_dialogue and (
            not group_id
            or any(item.get("variation_group_id") != group_id for item in same_dialogue)
        ):
            raise CreativeTreatmentError(
                "UNDECLARED_SAME_DIALOGUE_VARIATION",
                details={
                    "approved_treatment_ids": [
                        item["treatment_id"] for item in same_dialogue
                    ],
                },
            )
        if group_id:
            group = await treatment_crud.get_variation_group(group_id)
            if not group or group["status"] != "DRAFT":
                raise CreativeTreatmentError("VARIATION_GROUP_MEMBERSHIP_FROZEN")
            members = await treatment_crud.list_group_members(group_id)
            if len(members) > 5:
                raise CreativeTreatmentError("VARIATION_GROUP_MEMBER_LIMIT")
        target = "APPROVED"
    else:
        if not body.reviewer_note:
            raise CreativeTreatmentError(
                "REJECTION_REVIEWER_NOTE_REQUIRED",
                status_code=422,
            )
        target = "REJECTED"
    try:
        transitioned = await treatment_crud.transition_treatment(
            treatment_id=treatment_id,
            source_status="REVIEW_REQUIRED",
            target_status=target,
            actor_id=body.actor_id,
            reviewer_note=body.reviewer_note,
            evidence={"treatment_sha256": row["treatment_sha256"]},
            supersede_treatment_id=(
                row.get("supersedes_treatment_id")
                if target == "APPROVED"
                else None
            ),
        )
    except ValueError as exc:
        raise CreativeTreatmentError(str(exc)) from exc
    if not transitioned:
        raise CreativeTreatmentError("TREATMENT_TRANSITION_CONFLICT")
    return _decode_treatment(transitioned)


async def create_variation_group(
    body: CreateVariationGroupRequest,
) -> dict[str, Any]:
    copy_set = await crud.get_copy_set(body.copy_set_id)
    if not copy_set:
        raise CreativeTreatmentError("COPY_SET_NOT_FOUND", status_code=404)
    if (
        copy_set.get("product_id") != body.product_id
        or copy_set.get("status") != "COPY_APPROVED"
        or bool(copy_set.get("archived"))
    ):
        raise CreativeTreatmentError(
            "COPY_SET_NOT_APPROVED_FOR_VARIATION_GROUP",
            status_code=422,
        )
    dialogue = _dialogue_from_copy(copy_set)
    dialogue_sha256 = canonical_sha256(dialogue)
    if body.supersedes_group_id:
        predecessor = await treatment_crud.get_variation_group(
            body.supersedes_group_id,
        )
        if (
            not predecessor
            or predecessor["status"] != "APPROVED"
            or predecessor["product_id"] != body.product_id
            or predecessor["copy_set_id"] != body.copy_set_id
            or predecessor["dialogue_sha256"] != dialogue_sha256
        ):
            raise CreativeTreatmentError(
                "SUPERSEDED_VARIATION_GROUP_NOT_APPROVED",
                status_code=422,
            )
    return await treatment_crud.create_variation_group(
        {
            "group_id": str(uuid.uuid4()),
            "product_id": body.product_id,
            "copy_set_id": body.copy_set_id,
            "dialogue_sha256": dialogue_sha256,
            "status": "DRAFT",
            "group_sha256": None,
            "member_count": 0,
            "supersedes_group_id": body.supersedes_group_id,
            "created_by": body.created_by,
        },
    )


def _group_snapshot(
    group: dict[str, Any],
    members: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    if not 2 <= len(members) <= 5:
        raise CreativeTreatmentError(
            "VARIATION_GROUP_MEMBER_COUNT_INVALID",
            details={"member_count": len(members)},
        )
    if any(member["status"] != "APPROVED" for member in members):
        raise CreativeTreatmentError("VARIATION_GROUP_MEMBER_NOT_APPROVED")
    dialogue_hashes = {member["dialogue_sha256"] for member in members}
    if dialogue_hashes != {group["dialogue_sha256"]}:
        raise CreativeTreatmentError("VARIATION_GROUP_DIALOGUE_MISMATCH")
    fingerprints = {member["visual_fingerprint_sha256"] for member in members}
    if len(fingerprints) != len(members):
        raise CreativeTreatmentError("VARIATION_GROUP_VISUAL_DUPLICATE")
    ordinals = [member["variation_ordinal"] for member in members]
    if ordinals != list(range(1, len(members) + 1)):
        raise CreativeTreatmentError(
            "VARIATION_GROUP_ORDINALS_NOT_CONTIGUOUS",
        )
    member_projection = [
        {
            "treatment_id": member["treatment_id"],
            "variation_ordinal": member["variation_ordinal"],
            "treatment_sha256": member["treatment_sha256"],
            "dialogue_sha256": member["dialogue_sha256"],
            "visual_fingerprint_sha256": member["visual_fingerprint_sha256"],
        }
        for member in members
    ]
    digest = canonical_sha256(
        {
            "group_id": group["group_id"],
            "product_id": group["product_id"],
            "copy_set_id": group["copy_set_id"],
            "dialogue_sha256": group["dialogue_sha256"],
            "supersedes_group_id": group.get("supersedes_group_id"),
            "members": member_projection,
        },
    )
    return digest, member_projection


async def get_variation_group(group_id: str) -> dict[str, Any]:
    group = await treatment_crud.get_variation_group(group_id)
    if not group:
        raise CreativeTreatmentError("VARIATION_GROUP_NOT_FOUND", status_code=404)
    members = await treatment_crud.list_group_members(group_id)
    result = dict(group)
    result["members"] = [_decode_treatment(member) for member in members]
    result["audit_events"] = [
        _decode_audit(event)
        for event in await treatment_crud.list_audit_events(
            entity_type="VARIATION_GROUP",
            entity_id=group_id,
        )
    ]
    return result


async def list_variation_groups(
    *,
    product_id: str | None,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    return await treatment_crud.list_variation_groups(
        product_id=product_id,
        status=status,
        limit=limit,
    )


async def submit_variation_group_review(
    group_id: str,
    *,
    actor_id: str,
) -> dict[str, Any]:
    group = await treatment_crud.get_variation_group(group_id)
    if not group:
        raise CreativeTreatmentError("VARIATION_GROUP_NOT_FOUND", status_code=404)
    if group["status"] != "DRAFT":
        raise CreativeTreatmentError("VARIATION_GROUP_NOT_DRAFT")
    members = await treatment_crud.list_group_members(group_id)
    for member in members:
        await _revalidate(member)
    digest, projection = _group_snapshot(group, members)
    transitioned = await treatment_crud.transition_variation_group(
        group_id=group_id,
        source_status="DRAFT",
        target_status="REVIEW_REQUIRED",
        actor_id=actor_id,
        reviewer_note=None,
        group_sha256=digest,
        member_count=len(members),
        evidence={"group_sha256": digest, "members": projection},
    )
    if not transitioned:
        raise CreativeTreatmentError("VARIATION_GROUP_TRANSITION_CONFLICT")
    return transitioned


async def review_variation_group(
    group_id: str,
    body: ReviewVariationGroupRequest,
) -> dict[str, Any]:
    group = await treatment_crud.get_variation_group(group_id)
    if not group:
        raise CreativeTreatmentError("VARIATION_GROUP_NOT_FOUND", status_code=404)
    if group["status"] != "REVIEW_REQUIRED":
        raise CreativeTreatmentError("VARIATION_GROUP_NOT_REVIEW_REQUIRED")
    if body.expected_sha256 != group["group_sha256"]:
        raise CreativeTreatmentError("VARIATION_GROUP_HASH_CONFIRMATION_MISMATCH")
    members = await treatment_crud.list_group_members(group_id)
    for member in members:
        await _revalidate(member)
    digest, projection = _group_snapshot(group, members)
    if digest != group["group_sha256"]:
        raise CreativeTreatmentError("VARIATION_GROUP_AUTHORITY_STALE")
    if body.decision == "APPROVED":
        if body.confirmation != APPROVE_VARIATION_GROUP_CONFIRMATION:
            raise CreativeTreatmentError("VARIATION_GROUP_CONFIRMATION_REQUIRED")
        target = "APPROVED"
    else:
        if not body.reviewer_note:
            raise CreativeTreatmentError(
                "REJECTION_REVIEWER_NOTE_REQUIRED",
                status_code=422,
            )
        target = "REJECTED"
    try:
        transitioned = await treatment_crud.transition_variation_group(
            group_id=group_id,
            source_status="REVIEW_REQUIRED",
            target_status=target,
            actor_id=body.actor_id,
            reviewer_note=body.reviewer_note,
            group_sha256=digest,
            member_count=len(members),
            evidence={"group_sha256": digest, "members": projection},
            supersede_group_id=(
                group.get("supersedes_group_id")
                if target == "APPROVED"
                else None
            ),
        )
    except ValueError as exc:
        raise CreativeTreatmentError(str(exc)) from exc
    if not transitioned:
        raise CreativeTreatmentError("VARIATION_GROUP_TRANSITION_CONFLICT")
    return transitioned
