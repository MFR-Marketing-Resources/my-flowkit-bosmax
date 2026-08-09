"""E1 evidence gates: no-spend replay, runtime font proof and contrast."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from agent.models.poster_render_manifest import PosterRenderReport, ZoneRenderResult
from agent.services.poster_campaign_qa_service import build_campaign_post_composition_qa
from agent.services.poster_benchmark_cohort_service import (
    build_phase_e2_operation_plan,
    assess_benchmark_candidate,
    select_recommendations,
)
from agent.services.poster_replay_evidence_service import verify_existing_artifact
from agent.services.poster_template_service import build_render_manifest


def _copy_set() -> dict:
    return {
        "poster_copy_set_id": "pcs-e1",
        "version": 1,
        "primary_message": "Warisan untuk keluarga",
        "support_message": "Formula tradisional pilihan keluarga.",
        "proof_points": ["Mudah dibawa"],
        "cta": "Dapatkan sekarang",
        "disclaimer": "Untuk kegunaan luaran sahaja.",
        "field_provenance": {"primary_message": "APPROVED_SNAPSHOT"},
    }


def _manifest() -> object:
    return build_render_manifest(
        recipe_id="product_hero_night_routine",
        copy_set=_copy_set(),
        background_media_id="media-e1",
        background_local_path="",
        image_model="NANO_BANANA_PRO",
        creative_direction={
            "mode": "CREATIVE_CAMPAIGN",
            "authority_version": "poster-design-system-v1",
            "representation_policy_version": "product-reference-pack-v1",
            "design_route": "HERITAGE_EDITORIAL",
            "layout_variant": "EDITORIAL_ASYMMETRY",
        },
        composition_plan={"typography": {"headline_line_budget": 2}},
        design_route="HERITAGE_EDITORIAL",
        layout_variant="EDITORIAL_ASYMMETRY",
    )


def _render_report(manifest, *, fonts: dict) -> PosterRenderReport:
    return PosterRenderReport(
        renderer="HTML_CHROMIUM_SERVICE_V1",
        canvas={"w": 1080, "h": 1920},
        output_png={"width": 1080, "height": 1920},
        zones=[
            ZoneRenderResult(
                zone_id=zone.zone_id,
                fitted=True,
                overflowed=False,
                overlaps_product=False,
                rendered_text=zone.text,
            )
            for zone in manifest.zones
        ],
        fonts=fonts,
        ok=True,
    )


def _font_proof(manifest, *, fallback: bool = False, missing: bool = False) -> dict:
    families = sorted(
        {
            str((manifest.font_tokens.get(zone.font_token) or {}).get("family", ""))
            for zone in manifest.zones
        }
    )
    required = [
        {
            "family": family,
            "weight": 700,
            "document_fonts_check": not missing,
            "availability_check": not missing,
            "fallback_detected": fallback,
        }
        for family in families
    ]
    zones = [
        {
            "zone_id": zone.zone_id,
            "document_fonts_check": not missing,
            "fallback_detected": fallback,
        }
        for zone in manifest.zones
    ]
    return {
        "evidence_schema_version": "poster-font-render-proof-v1",
        "document_fonts_ready": True,
        "required": required,
        "zone_evidence": zones,
        "missing_families": families if missing else [],
    }


def _write_canvas(tmp_path: Path, color: tuple[int, int, int]) -> Path:
    path = tmp_path / f"canvas-{color[0]}-{color[1]}-{color[2]}.png"
    Image.new("RGBA", (1080, 1920), (*color, 255)).save(path)
    return path


def test_runtime_font_proof_requires_all_family_weight_and_zone_evidence():
    manifest = _manifest()
    clean = build_campaign_post_composition_qa(
        manifest=manifest,
        report=_render_report(manifest, fonts=_font_proof(manifest)),
        copy_set=_copy_set(),
        settings={"pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE"},
        output_sha256="a" * 64,
    )
    assert clean.checks["font_loaded_proof"].status == "PASS"

    fallback = build_campaign_post_composition_qa(
        manifest=manifest,
        report=_render_report(manifest, fonts=_font_proof(manifest, fallback=True)),
        copy_set=_copy_set(),
        settings={"pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE"},
        output_sha256="a" * 64,
    )
    assert fallback.checks["font_loaded_proof"].status == "BLOCK"

    absent = build_campaign_post_composition_qa(
        manifest=manifest,
        report=_render_report(manifest, fonts={}),
        copy_set=_copy_set(),
        settings={"pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE"},
        output_sha256="a" * 64,
    )
    assert absent.checks["font_loaded_proof"].status == "UNVERIFIED"


def test_deterministic_contrast_passes_blocks_and_stays_unverified_when_unmeasurable(tmp_path):
    manifest = _manifest()
    report = _render_report(manifest, fonts=_font_proof(manifest))
    output = _write_canvas(tmp_path, (0, 0, 0))

    # The authored text is dark, so a dark canvas is a deterministic block.
    low = build_campaign_post_composition_qa(
        manifest=manifest,
        report=report,
        copy_set=_copy_set(),
        settings={"pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE"},
        output_sha256="a" * 64,
        background_path=str(output),
        output_path=str(output),
    )
    assert low.checks["contrast_threshold"].status == "BLOCK"

    white = _write_canvas(tmp_path, (255, 255, 255))
    high = build_campaign_post_composition_qa(
        manifest=manifest,
        report=report,
        copy_set=_copy_set(),
        settings={"pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE"},
        output_sha256="a" * 64,
        background_path=str(white),
        output_path=str(white),
    )
    assert high.checks["contrast_threshold"].status == "PASS"

    ambiguous = build_campaign_post_composition_qa(
        manifest=manifest,
        report=report,
        copy_set=_copy_set(),
        settings={"pipeline": "CLEAN_KEY_VISUAL_THEN_DETERMINISTIC_COPY_COMPOSITE"},
        output_sha256="a" * 64,
        background_path=str(tmp_path / "missing.png"),
        output_path=str(white),
    )
    assert ambiguous.checks["contrast_threshold"].status == "UNVERIFIED"


def test_campaign_provenance_round_trips_and_legacy_manifest_remains_loadable():
    manifest = build_render_manifest(
        recipe_id="product_hero_night_routine",
        copy_set=_copy_set(),
        background_local_path="C:/tmp/bg.png",
        campaign_provenance={
            "clean_key_visual_prompt_fingerprint": "c" * 64,
            "approved_snapshot_id": "snapshot-e1",
            "approved_snapshot_version": 5,
            "design_brief_version": "poster-campaign-brief-v1",
            "copy_route_id": "route-e1",
            "reference_pack_id": "pack-e1",
            "reference_role_hashes": {"PRODUCT_CANONICAL": "d" * 64},
            "requested_provider_model": "NANO_BANANA_PRO",
            "provider_batch_id": "batch-e1",
            "provider_operation_id_status": "UNPROVEN_PROVIDER_OPERATION_ID",
            "provider_operation_budget": 1,
            "actual_retry_count": 0,
            "raw_key_visual_media_id": "media-e1",
            "raw_key_visual_sha256": "e" * 64,
        },
    )
    restored = type(manifest).model_validate_json(manifest.model_dump_json())
    assert restored.provenance.reference_pack_id == "pack-e1"
    assert restored.provenance.provider_operation_budget == 1
    legacy = manifest.model_dump()
    for key in (
        "clean_key_visual_prompt_fingerprint",
        "approved_snapshot_id",
        "approved_snapshot_version",
        "design_brief_version",
        "copy_route_id",
        "reference_pack_id",
        "reference_role_hashes",
        "requested_provider_model",
        "provider_batch_id",
        "provider_operation_id",
        "provider_operation_id_status",
        "provider_operation_budget",
        "actual_retry_count",
        "raw_key_visual_media_id",
        "raw_key_visual_sha256",
    ):
        legacy["provenance"].pop(key, None)
    loaded_legacy = type(manifest).model_validate(legacy)
    assert loaded_legacy.provenance.reference_pack_id == ""


def test_replay_verifier_handles_match_mismatch_and_missing_without_side_effects(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"poster-replay")
    import hashlib

    expected = hashlib.sha256(b"poster-replay").hexdigest()
    match = verify_existing_artifact(artifact, expected)
    assert match["status"] == "REPLAY_VERIFIED"
    assert match["provider_operation_count"] == 0
    assert match["db_mutation_count"] == 0

    mismatch = verify_existing_artifact(artifact, "0" * 64)
    assert mismatch["status"] == "ARTIFACT_HASH_MISMATCH"
    assert mismatch["provider_operation_count"] == 0
    assert mismatch["db_mutation_count"] == 0

    missing = verify_existing_artifact(tmp_path / "missing.bin", expected)
    assert missing["status"] == "MISSING_ARTIFACT"
    assert missing["provider_operation_count"] == 0
    assert missing["db_mutation_count"] == 0


def test_cohort_scale_requires_physical_evidence_not_volume_only():
    evidence = {
        "physical_width_mm": None,
        "physical_height_mm": None,
        "physical_depth_mm": None,
        "volume_ml": 25,
        "scale_evidence_source": "PRODUCT_RECORD_OR_AUTHORITY_SCHEMA",
        "approved_scale_reference_with_known_dimensions": False,
        "status": "UNVERIFIED",
    }
    candidate = {
        "product_id": "prod-e1",
        "display_name": "E1 product",
        "product_exists": True,
        "active_eligible": True,
        "approved_snapshot": True,
        "copy_eligible": True,
        "approved_copy_set_id": "pcs-e1",
        "copy_route_score": 80,
        "reference_pack_approved": True,
        "canonical_reference_available": True,
        "available_reference_roles": [
            "PRODUCT_CANONICAL",
            "PRODUCT_LABEL_CROP",
            "PRODUCT_LOGO_CROP",
        ],
        "label_logo_required": True,
        "claim_provenance_approved": True,
        "campaign_brief_ready": True,
        "human_review_path_available": True,
        "physical_measurement_evidence": evidence,
    }
    assessed = assess_benchmark_candidate(candidate)
    assert evidence["volume_ml"] == 25
    assert assessed["readiness_decision"] == "BLOCKED"
    assert "PHYSICAL_SCALE_EVIDENCE_UNVERIFIED" in assessed["blockers"]


def test_cohort_selects_one_ready_candidate_per_class_and_plans_five_slots():
    candidate = {
        "product_id": "prod-e1",
        "display_name": "E1 product",
        "product_exists": True,
        "active_eligible": True,
        "approved_snapshot": True,
        "copy_eligible": True,
        "approved_copy_set_id": "pcs-e1",
        "copy_route_score": 80,
        "reference_pack_approved": True,
        "canonical_reference_available": True,
        "available_reference_roles": [
            "PRODUCT_CANONICAL",
            "PRODUCT_LABEL_CROP",
            "PRODUCT_LOGO_CROP",
        ],
        "label_logo_required": True,
        "claim_provenance_approved": True,
        "campaign_brief_ready": True,
        "human_review_path_available": True,
        "physical_measurement_evidence": {
            "physical_width_mm": 20,
            "physical_height_mm": 80,
            "physical_depth_mm": 20,
            "approved_scale_reference_with_known_dimensions": False,
        },
    }
    recommendations = select_recommendations({exp_id: [candidate] for exp_id in ("EXP-01", "EXP-02", "EXP-03", "EXP-04", "EXP-05")})
    assert all(item is not None for item in recommendations.values())
    plan = build_phase_e2_operation_plan(recommendations)
    assert plan["status"] == "READY_FOR_AUTHORIZATION"
    assert len(plan["operations"]) == 5
    assert plan["maximum_future_provider_operations"] == 5
    assert plan["provider_operation_count"] == 0
    assert plan["max_retry_operations"] == 0
