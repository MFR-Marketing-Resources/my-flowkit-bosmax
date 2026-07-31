from __future__ import annotations

import json

import pytest

from agent.authority import product_readiness_applicability_registry as registry
from agent.models.product_readiness import (
    AssetReadinessAuthority,
    CopyReadinessAuthority,
    EvidenceProvenanceAuthority,
    ProductReadinessEvaluateRequest,
    ProductTaxonomyReadinessAuthority,
    ProductTruthReadinessAuthority,
    ResolvedProductReadinessInput,
    SelectionReadinessAuthority,
    TreatmentReadinessAuthority,
)
from agent.services import product_readiness_applicability_service as service
from agent.services.creative_treatment_service import canonical_sha256
from agent.services.scene_strategy_library import SCENE_STRATEGIES


def _provenance(
    field_name: str,
    value: object,
    *,
    suffix: str = "1",
    decision: str = "APPROVED",
    verification_status: str = "REVIEWED_APPROVED",
) -> EvidenceProvenanceAuthority:
    normalized = (
        value
        if isinstance(value, str)
        else json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    projection = {
        "provenance_id": f"prov-{field_name}-{suffix}",
        "field_name": field_name,
        "declared_value": normalized,
        "normalized_value": normalized,
        "source_type": "TEST_REVIEWED_SOURCE",
        "source_url": "https://example.com/evidence",
        "source_lane": "TEST",
        "evidence_kind": "REVIEWED_FACT",
        "extraction_method": "MANUAL_REVIEW",
        "confidence_score": 1.0,
        "verification_status": verification_status,
        "claim_risk_flag": None,
        "reviewer_decision": decision,
    }
    return EvidenceProvenanceAuthority(
        **projection,
        provenance_sha256=canonical_sha256(projection),
    )


def _base_fields() -> dict[str, object]:
    return {
        "product_identity": {
            "id": "product-1",
            "product_display_name": "Reviewed product",
        },
        "product_description": "Reviewed product description.",
        "benefits_json": ["reviewed benefit"],
        "usp_json": ["reviewed USP"],
        "target_customer_text": "Reviewed target customer.",
        "allowed_claims_json": ["reviewed claim"],
        "ingredients_text": "Reviewed composition.",
        "usage_text": "Reviewed use instructions.",
        "warnings_text": "Reviewed warnings and limitations.",
        "package_notes": "Reviewed materials and components.",
        "size_or_volume": "Reviewed physical scale.",
        "product_form_factor": "Reviewed physical state.",
        "packaging_description": "Reviewed package identity.",
    }


def _resolved(
    scene_strategy_id: str,
    *,
    allowed_action_index: int = 0,
    creative_format: str = "PGC",
    logical_mode: str = "T2V",
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    field_overrides: dict[str, object] | None = None,
    provenance_overrides: dict[str, list[EvidenceProvenanceAuthority]] | None = None,
    claim_gate: str = "CLAIM_SAFE",
    stale: bool = False,
    selection_status: str = "APPROVED",
    avatar_code: str | None = "avatar-reviewed",
    p6_ready: bool = True,
    fallback_used: bool = False,
    specific_strategy: bool = True,
) -> ResolvedProductReadinessInput:
    fields = _base_fields()
    fields.update(field_overrides or {})
    provenance: list[EvidenceProvenanceAuthority] = []
    for field_name, value in fields.items():
        overrides = (provenance_overrides or {}).get(field_name)
        if overrides is not None:
            provenance.extend(overrides)
        elif value not in (None, "", [], {}):
            provenance.append(_provenance(field_name, value))
    profile = registry.resolve_applicability_profile(scene_strategy_id)
    required_roles = list(
        profile.required_asset_roles_by_mode.get(logical_mode, [])
    )
    eligible_by_role = {
        role: [f"asset-{role.casefold()}"] for role in required_roles
    }
    return ResolvedProductReadinessInput(
        context=ProductReadinessEvaluateRequest(
            product_id="product-1",
            allowed_action_index=allowed_action_index,
            creative_format=creative_format,
            logical_mode=logical_mode,
            generation_mode=generation_mode,
            model_key="veo_3_1_fast",
            duration_seconds=duration_seconds,
        ),
        product_authority_sha256="1" * 64,
        taxonomy=ProductTaxonomyReadinessAuthority(
            taxonomy_version="taxonomy-v1",
            taxonomy_fingerprint="2" * 64,
            cluster=profile.product_family,
            product_type_group=profile.product_type,
            matched_scene_strategy_id=scene_strategy_id,
            scene_coverage_status=(
                "FALLBACK_ONLY" if fallback_used else "SPECIFIC"
            ),
            fallback_used=fallback_used,
            specific_strategy=specific_strategy,
            review_status="VERIFIED",
            consumer_status="READY",
            materialization_status="MATERIALIZED",
        ),
        product_truth=ProductTruthReadinessAuthority(
            snapshot_id="snapshot-1",
            snapshot_sha256="3" * 64,
            snapshot_status="APPROVED",
            field_values=fields,
            provenance=provenance,
            claim_gate=claim_gate,
            claim_risk_level="LOW",
            is_stale=stale,
        ),
        copy=CopyReadinessAuthority(
            grounding_ready=True,
            grounding_source="APPROVED_SNAPSHOT",
            approved_copy_set_ids=["copy-1"],
        ),
        selection=SelectionReadinessAuthority(
            selection_id="selection-1",
            status=selection_status,
            selected_avatar_code=avatar_code,
            selected_scene_template_id="scene-1",
            selected_camera_preset_code="camera-1",
            selection_sha256="4" * 64,
        ),
        assets=AssetReadinessAuthority(
            required_roles=required_roles,
            eligible_asset_ids_by_role=eligible_by_role,
            missing_roles=[],
            authority_sha256="5" * 64,
        ),
        treatment=TreatmentReadinessAuthority(
            approved_treatment_ids=["treatment-1"],
            selected_treatment_ids=["treatment-1"] if p6_ready else [],
            availability_sha256="6" * 64,
            p6_ready=p6_ready,
            blocker_codes=[] if p6_ready else ["TREATMENT_CAPACITY_INSUFFICIENT"],
        ),
    )


def _requirement(result, code: str):
    return next(
        item for item in result.evidence_requirements
        if item.requirement_code == code
    )


def test_registry_profiles_every_scene_strategy_or_explicitly_refuses_fallback():
    response = service.get_applicability_profiles()
    by_id = {item.scene_strategy_id: item for item in response.profiles}

    assert set(SCENE_STRATEGIES).issubset(by_id)
    assert all(
        profile.supported
        for key, profile in by_id.items()
        if key not in {"GENERIC_FALLBACK", "UNKNOWN"}
    )
    assert by_id["GENERIC_FALLBACK"].unsupported_code == (
        "APPLICABILITY_PROFILE_UNSUPPORTED"
    )
    assert by_id["UNKNOWN"].supported is False
    assert response.registry_sha256 == service.get_applicability_profiles().registry_sha256


@pytest.mark.parametrize(
    ("scene_strategy_id", "action_index"),
    [
        ("ELECTRONICS_SMALL_DEVICE", 2),
        ("APPAREL", 0),
        ("FASHION_ACCESSORY", 0),
    ],
)
def test_non_consumable_archetypes_never_require_ingredients(
    scene_strategy_id: str,
    action_index: int,
):
    result = service.evaluate_resolved_readiness(
        _resolved(
            scene_strategy_id,
            allowed_action_index=action_index,
            field_overrides={"ingredients_text": ""},
            provenance_overrides={"ingredients_text": []},
        )
    )

    ingredients = _requirement(result, "INGREDIENTS_OR_COMPOSITION")
    assert ingredients.state == "NOT_APPLICABLE"
    assert result.primary_status == "TREATMENT_READY"


@pytest.mark.parametrize(
    ("scene_strategy_id", "action_index"),
    [
        ("SPICE_SEASONING", 3),
        ("SERUM", 0),
    ],
)
def test_consumable_and_cosmetic_composition_remains_fail_closed(
    scene_strategy_id: str,
    action_index: int,
):
    result = service.evaluate_resolved_readiness(
        _resolved(
            scene_strategy_id,
            allowed_action_index=action_index,
            field_overrides={"ingredients_text": ""},
            provenance_overrides={
                "ingredients_text": [
                    _provenance(
                        "ingredients_text",
                        "",
                        decision="NOT_STATED_IN_EVIDENCE",
                    )
                ]
            },
        )
    )

    ingredients = _requirement(result, "INGREDIENTS_OR_COMPOSITION")
    assert ingredients.state == "NOT_STATED_IN_EVIDENCE"
    assert result.primary_status == "EVIDENCE_REQUIRED"
    assert "EVIDENCE_NOT_STATED:INGREDIENTS_OR_COMPOSITION" in {
        item.code for item in result.blockers
    }


def test_usage_is_action_aware_for_static_hero_vs_demonstration():
    static_result = service.evaluate_resolved_readiness(
        _resolved(
            "SPICE_SEASONING",
            allowed_action_index=3,
            field_overrides={"usage_text": ""},
            provenance_overrides={"usage_text": []},
        )
    )
    demonstration_result = service.evaluate_resolved_readiness(
        _resolved(
            "SPICE_SEASONING",
            allowed_action_index=2,
            field_overrides={"usage_text": ""},
            provenance_overrides={
                "usage_text": [
                    _provenance(
                        "usage_text",
                        "",
                        decision="NOT_STATED_IN_EVIDENCE",
                    )
                ]
            },
        )
    )

    assert _requirement(
        static_result, "USAGE_OR_INSTRUCTIONS"
    ).state == "NOT_APPLICABLE"
    assert static_result.primary_status == "TREATMENT_READY"
    assert _requirement(
        demonstration_result, "USAGE_OR_INSTRUCTIONS"
    ).state == "NOT_STATED_IN_EVIDENCE"
    assert demonstration_result.primary_status == "EVIDENCE_REQUIRED"


@pytest.mark.parametrize(
    ("scene_strategy_id", "action_index"),
    [
        ("HOUSEHOLD_CLEANER", 0),
        ("WELLNESS_SUPPLEMENT", 0),
    ],
)
def test_warnings_are_risk_aware_and_never_inferred_safe(
    scene_strategy_id: str,
    action_index: int,
):
    result = service.evaluate_resolved_readiness(
        _resolved(
            scene_strategy_id,
            allowed_action_index=action_index,
            field_overrides={"warnings_text": ""},
            provenance_overrides={
                "warnings_text": [
                    _provenance(
                        "warnings_text",
                        "",
                        decision="NOT_STATED_IN_EVIDENCE",
                    )
                ]
            },
        )
    )

    warnings = _requirement(result, "WARNINGS_OR_LIMITATIONS")
    assert warnings.applicable is True
    assert warnings.state == "NOT_STATED_IN_EVIDENCE"
    assert result.primary_status == "EVIDENCE_REQUIRED"


def test_allowed_claims_empty_requires_explicit_intentional_human_decision():
    unreviewed_empty = service.evaluate_resolved_readiness(
        _resolved(
            "APPAREL",
            field_overrides={"allowed_claims_json": []},
            provenance_overrides={"allowed_claims_json": []},
        )
    )
    explicit_empty = service.evaluate_resolved_readiness(
        _resolved(
            "APPAREL",
            field_overrides={"allowed_claims_json": []},
            provenance_overrides={
                "allowed_claims_json": [
                    _provenance(
                        "allowed_claims_json",
                        [],
                        decision="NO_ALLOWED_CLAIMS_INTENTIONAL",
                    )
                ]
            },
        )
    )

    assert _requirement(
        unreviewed_empty, "ALLOWED_CLAIMS"
    ).state == "UNKNOWN_REVIEW_REQUIRED"
    assert unreviewed_empty.primary_status == "REVIEW_REQUIRED"
    assert _requirement(
        explicit_empty, "ALLOWED_CLAIMS"
    ).state == "VERIFIED_VALUE"
    assert explicit_empty.primary_status == "TREATMENT_READY"


def test_unknown_and_generic_taxonomy_never_become_production_ready():
    result = service.evaluate_resolved_readiness(
        _resolved(
            "GENERIC_FALLBACK",
            fallback_used=True,
            specific_strategy=False,
        )
    )

    assert result.primary_status == "UNSUPPORTED_PRODUCT_TAXONOMY"
    assert result.readiness_layers[0].state == "BLOCKED"
    assert result.applicability_profile.supported is False


def test_stale_and_conflicting_evidence_resolve_to_unknown_review_required():
    stale = service.evaluate_resolved_readiness(
        _resolved("APPAREL", stale=True)
    )
    conflict = service.evaluate_resolved_readiness(
        _resolved(
            "APPAREL",
            provenance_overrides={
                "allowed_claims_json": [
                    _provenance("allowed_claims_json", ["claim A"], suffix="a"),
                    _provenance("allowed_claims_json", ["claim B"], suffix="b"),
                ]
            },
        )
    )

    assert stale.primary_status == "REVIEW_REQUIRED"
    assert _requirement(
        stale, "ALLOWED_CLAIMS"
    ).state == "UNKNOWN_REVIEW_REQUIRED"
    assert conflict.primary_status == "REVIEW_REQUIRED"
    assert _requirement(
        conflict, "ALLOWED_CLAIMS"
    ).state == "UNKNOWN_REVIEW_REQUIRED"


def test_reviewed_provenance_must_match_the_current_snapshot_value():
    result = service.evaluate_resolved_readiness(
        _resolved(
            "APPAREL",
            field_overrides={"allowed_claims_json": ["current claim"]},
            provenance_overrides={
                "allowed_claims_json": [
                    _provenance("allowed_claims_json", ["stale claim"])
                ]
            },
        )
    )

    assert _requirement(
        result, "ALLOWED_CLAIMS"
    ).state == "UNKNOWN_REVIEW_REQUIRED"
    assert result.primary_status == "REVIEW_REQUIRED"


def test_claim_blocked_floor_survives_otherwise_ready_authority():
    result = service.evaluate_resolved_readiness(
        _resolved("APPAREL", claim_gate="CLAIM_BLOCKED")
    )

    assert result.primary_status == "REVIEW_REQUIRED"
    assert "CLAIM_BLOCKED" in {item.code for item in result.blockers}
    assert next(
        layer for layer in result.readiness_layers
        if layer.layer == "claim_safety"
    ).state == "REVIEW_REQUIRED"


def test_format_actor_policies_are_distinct_and_fail_closed():
    ugc = service.evaluate_resolved_readiness(
        _resolved("APPAREL", creative_format="UGC", avatar_code=None)
    )
    pgc = service.evaluate_resolved_readiness(
        _resolved("APPAREL", creative_format="PGC", avatar_code=None)
    )
    cinematic = service.evaluate_resolved_readiness(
        _resolved("APPAREL", creative_format="CINEMATIC", avatar_code=None)
    )

    assert ugc.primary_status == "REVIEW_REQUIRED"
    assert "UGC_AVATAR_SELECTION_REQUIRED" in {
        item.code for item in ugc.blockers
    }
    assert pgc.primary_status == "TREATMENT_READY"
    assert cinematic.primary_status == "TREATMENT_READY"


def test_reference_mode_routes_missing_visual_authority_to_asset_required():
    resolved = _resolved("APPAREL", logical_mode="HYBRID")
    resolved.assets.missing_roles = ["PRODUCT_REFERENCE"]
    resolved.assets.eligible_asset_ids_by_role = {"PRODUCT_REFERENCE": []}

    result = service.evaluate_resolved_readiness(resolved)

    assert _requirement(
        result, "VISUAL_ASSET_IDENTITY"
    ).state == "UNKNOWN_REVIEW_REQUIRED"
    assert result.primary_status == "ASSET_REQUIRED"
    assert "VIDEO_ASSET_ROLE_REQUIRED:PRODUCT_REFERENCE" in {
        item.code for item in result.blockers
    }


def test_generation_mode_mismatch_is_exact_and_fail_closed():
    result = service.evaluate_resolved_readiness(
        _resolved(
            "APPAREL",
            generation_mode="EXTEND",
            duration_seconds=8,
        )
    )

    assert result.primary_status == "REVIEW_REQUIRED"
    assert "GENERATION_MODE_OR_DURATION_MISMATCH" in {
        item.code for item in result.blockers
    }


def test_projection_hash_is_deterministic_and_changes_with_authority():
    first = service.evaluate_resolved_readiness(_resolved("APPAREL"))
    second = service.evaluate_resolved_readiness(_resolved("APPAREL"))
    changed_input = _resolved("APPAREL")
    changed_input.product_truth.field_values["benefits_json"] = [
        "different reviewed benefit"
    ]
    changed_input.product_truth.provenance = [
        item
        for item in changed_input.product_truth.provenance
        if item.field_name != "benefits_json"
    ]
    changed_input.product_truth.provenance.append(
        _provenance("benefits_json", ["different reviewed benefit"])
    )
    changed = service.evaluate_resolved_readiness(changed_input)

    assert first.readiness_sha256 == second.readiness_sha256
    assert first.readiness_sha256 != changed.readiness_sha256
