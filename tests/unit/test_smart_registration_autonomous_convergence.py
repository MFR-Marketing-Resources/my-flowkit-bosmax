import sqlite3

from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.models.product_registration import RegistrationReviewDraft
from agent.services.product_intelligence_service import (
    resolve_product_intelligence_profile,
)
from agent.services.product_knowledge_service import complete_product_knowledge
from agent.services.product_registration_service import (
    create_registration_review_draft,
)
from agent.services.registration_authority_fingerprint_service import (
    apply_authority_freshness,
    stamp_authority_fingerprint,
)
from agent.services.registration_consistency_service import (
    evaluate_registration_consistency,
)
from agent.services.registration_evidence_quality_service import (
    audit_registration_evidence,
)
from scripts.smart_registration_catalog_audit import audit_catalog


CURTAIN_TITLE = (
    "HOT Langsir Kabinet DESIGN ( RENDA LEKAT ) viral, Skirting Table Top, "
    "Meja Guru, Pejabat ( ready made ) ukuran standard Fabrik Tingkap "
    "Berpetak Soft Cotton Custom"
)


def _draft(**overrides) -> RegistrationReviewDraft:
    payload = {
        "review_draft_id": "draft-curtain",
        "review_status": "NEEDS_HUMAN_REVIEW",
        "source_lane": "FASTMOSS",
        "declared_evidence_fields": {"product_name": CURTAIN_TITLE},
        "canonical_candidate_fields": {
            "normalized_name": CURTAIN_TITLE,
            "category": "Textiles & Soft Furnishings",
            "subcategory": "Household Textiles",
            "type": "Curtains",
            "bosmax_product_family": "HOME_TEXTILE",
            "physical_state": "textile",
            "physics_class": "HOME_TEXTILE_SOFT_GOOD",
            "copy_formula": "HOME_TEXTILE_DIRECT",
        },
    }
    payload.update(overrides)
    return RegistrationReviewDraft.model_validate(payload)


def test_berpetak_does_not_match_pet_but_real_pet_word_still_matches():
    curtain = resolve_product_intelligence_profile(
        {
            "id": "curtain",
            "raw_product_title": "Fabrik tingkap berpetak soft cotton",
            "product_display_name": "Fabrik tingkap berpetak soft cotton",
            "category": "Textiles & Soft Furnishings",
            "subcategory": "Household Textiles",
            "type": "Curtains",
        }
    )
    pet = resolve_product_intelligence_profile(
        {
            "id": "pet-food",
            "raw_product_title": "Premium pet food for kucing",
            "product_display_name": "Premium pet food for kucing",
            "category": "Pet Supplies",
        }
    )

    assert curtain["bosmax_product_family"] == "HOME_TEXTILE"
    assert curtain["physical_state"] == "textile"
    assert pet["bosmax_product_family"] == "PET_CARE_GENERAL"


def test_bercorak_does_not_match_rak_storage_keyword():
    result = resolve_product_intelligence_profile(
        {
            "id": "curtain-bercorak",
            "raw_product_title": (
                "[HOMEBLIND] Langsir EROCA Semi Blackout Bercorak / "
                "Curtains Hook or Ring"
            ),
            "product_display_name": "Langsir EROCA Semi Blackout Bercorak",
            "category": "Textiles & Soft Furnishings",
            "subcategory": "Household Textiles",
            "type": "Curtains",
        }
    )

    assert result["bosmax_product_family"] == "HOME_TEXTILE"


def test_evidence_audit_preserves_raw_values_and_rejects_marketing_metadata():
    result = audit_registration_evidence(
        ProductKnowledgeCompleteRequest(
            product_name=CURTAIN_TITLE,
            category="Textiles & Soft Furnishings",
            subcategory="Household Textiles",
            product_type="Curtains",
            benefits_text=(
                "#KitchenMakeover #LangsirViral\n"
                "15-30s\nKitchen makeover music"
            ),
            target_customer_text="Langsir kabinet viral dengan renda! 🌸",
            ingredients_text="Kitchen glow-up! Order now!",
        ),
        product_family="HOME_TEXTILE",
    )

    assert result.raw_fields["benefits_text"].startswith("#KitchenMakeover")
    assert result.sanitized_fields["benefits_text"] is None
    assert result.decisions["benefits"].status == "INVALID_MARKETING_METADATA"
    assert result.decisions["ingredients_or_materials"].status == "NOT_APPLICABLE"
    assert result.sanitized_fields["materials_text"] == "fabric; lace; soft cotton"
    assert "EVIDENCE_BENEFITS_PRODUCTION_METADATA" in result.issue_codes
    assert "EVIDENCE_INGREDIENTS_CTA_COPY" in result.issue_codes


def test_consistency_engine_blocks_pet_copy_against_home_textile_physics():
    result = evaluate_registration_consistency(
        {
            "bosmax_product_family": "PET_CARE_GENERAL",
            "physical_state": "solid_or_kibble",
            "physics_class": "HOME_TEXTILE_SOFT_GOOD",
            "copy_formula": "PETCARE_DIRECT",
            "category": "Textiles & Soft Furnishings",
            "type": "Curtains",
        }
    )

    assert result.status == "BLOCKED_REVIEW_REQUIRED"
    assert "CONSISTENCY_FAMILY_TAXONOMY_CONFLICT" in result.issue_codes
    assert "CONSISTENCY_FAMILY_PHYSICS_CONFLICT" in result.issue_codes


def test_authority_fingerprint_marks_old_or_changed_drafts_stale():
    draft = stamp_authority_fingerprint(_draft())
    assert draft.draft_freshness_status == "FRESH"
    assert draft.authority_fingerprint

    draft.declared_evidence_fields["benefits_text"] = "Changed source evidence"
    stale = apply_authority_freshness(draft)

    assert stale.draft_freshness_status == "STALE_RECOMPUTE_REQUIRED"
    assert "AUTHORITY_INPUT_FINGERPRINT_CHANGED" in stale.recompute_required_reasons


def test_semantic_vision_skip_cannot_be_ready_for_image_dependent_modes():
    draft = _draft(
        system_inferred_fields={
            "image_analysis_status": "ANALYSIS_SKIPPED",
            "image_analysis_visual_confidence": "NOT_VERIFIED",
        },
        readiness_by_mode={
            "IMG": {"status": "READY", "detail": "Reference exists."},
            "I2V": {"status": "READY", "detail": "Reference exists."},
            "F2V": {"status": "READY", "detail": "Reference exists."},
            "T2V": {"status": "READY", "detail": "Text is present."},
        },
    )

    stamped = stamp_authority_fingerprint(draft)

    assert stamped.readiness_by_mode["IMG"]["status"] == "BLOCKED"
    assert stamped.readiness_by_mode["I2V"]["status"] == "BLOCKED"
    assert stamped.readiness_by_mode["F2V"]["status"] == "BLOCKED"
    assert stamped.readiness_by_mode["T2V"]["status"] == "READY"


def test_curtain_recompute_converges_taxonomy_physics_and_copy_without_provider():
    completion = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name=CURTAIN_TITLE,
            source_lane="FASTMOSS_PROMOTED",
            category="Textiles & Soft Furnishings",
            subcategory="Household Textiles",
            benefits_text=(
                "#KitchenMakeover #LangsirViral\n"
                "15-30s\nKitchen makeover music"
            ),
            target_customer_text="Langsir kabinet viral dengan renda! 🌸",
            ingredients_text="Kitchen glow-up! Order now!",
            image_url="https://example.com/curtain.jpg",
        )
    )
    draft = create_registration_review_draft(completion)

    assert draft.canonical_candidate_fields["type"] == "Curtains"
    assert draft.canonical_candidate_fields["bosmax_product_family"] == "HOME_TEXTILE"
    assert draft.canonical_candidate_fields["physical_state"] == "textile"
    assert draft.canonical_candidate_fields["physics_class"] == "HOME_TEXTILE_SOFT_GOOD"
    assert draft.canonical_candidate_fields["copy_formula"] == "TEXTURE_COMFORT"
    assert draft.strategy_taxonomy is not None
    assert draft.strategy_taxonomy.cluster == "home_textiles"
    assert draft.strategy_taxonomy.product_type_group == "curtain"
    assert draft.strategy_taxonomy.matched_scene_strategy_id == "CURTAIN"
    assert draft.consistency_status == "CONSISTENT"
    assert draft.evidence_quality_status == "REVIEW_REQUIRED"
    assert "benefits" not in draft.canonical_candidate_fields
    assert "target_customer" not in draft.canonical_candidate_fields
    assert draft.canonical_candidate_fields["ingredients_applicability"] == "NOT_APPLICABLE"
    assert (
        draft.canonical_candidate_fields["materials_or_components"]
        == "fabric; lace; soft cotton"
    )


def test_text_assist_can_repair_invalid_nonempty_field_as_review_only(
    monkeypatch,
):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: {
            "product_knowledge_summary": None,
            "benefits": [],
            "usage_summary": None,
            "target_customer": None,
            "usp_list": [],
            "size_or_volume": None,
            "package_notes": None,
            "materials_or_components": "fabric; lace; soft cotton",
            "ingredients_applicability": "NOT_APPLICABLE",
            "field_repairs": [
                {
                    "field": "benefits",
                    "proposed_value": [
                        "Soft cotton curtain with ready-made lace trim"
                    ],
                    "evidence_used": [
                        "product_name:Fabrik",
                        "product_name:Renda",
                        "product_name:Soft Cotton",
                    ],
                    "confidence": "MEDIUM",
                    "reason": "Replaces production metadata with product facts.",
                    "action": "REPAIR_INVALID_OR_PLACEHOLDER",
                    "needs_review": True,
                }
            ],
            "taxonomy_suggestion": {
                "category": "Textiles & Soft Furnishings",
                "subcategory": "Household Textiles",
                "type": "Curtains",
                "registry_entry_key": "home_textiles/curtain",
                "evidence_used": ["product_name:Langsir"],
                "confidence": "MEDIUM",
                "reason": "Langsir is a curtain and matches the active registry entry.",
                "needs_review": True,
            },
            "warnings_or_limitations": [],
            "confidence": "MEDIUM",
            "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
            "needs_review": True,
        },
    )
    completion = complete_product_knowledge(
        ProductKnowledgeCompleteRequest(
            product_name=CURTAIN_TITLE,
            source_lane="MANUAL",
            category="Textiles & Soft Furnishings",
            subcategory="Household Textiles",
            benefits_text="#LangsirViral\n15-30s\nMakeover music",
            paste_anything_about_product=(
                "Langsir fabrik soft cotton dengan renda lekat, ready made."
            ),
        ),
        enable_text_assist=True,
    )
    draft = create_registration_review_draft(completion)

    assert draft.canonical_candidate_fields["benefits"] == [
        "Soft cotton curtain with ready-made lace trim"
    ]
    benefits_status = draft.evidence_field_status["benefits"]
    assert benefits_status.status == "AI_SUGGESTED"
    assert benefits_status.repair_action == "REPAIR_INVALID_OR_PLACEHOLDER"
    assert benefits_status.needs_review is True
    assert draft.canonical_candidate_fields["taxonomy_repair"][
        "registry_entry_key"
    ] == "home_textiles/curtain"
    assert draft.approval_checklist["benefits"] is False


def test_catalog_audit_is_credit_free_deterministic_and_counts_every_row():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE product (
            id TEXT PRIMARY KEY,
            raw_product_title TEXT,
            product_display_name TEXT,
            category TEXT,
            subcategory TEXT,
            type TEXT,
            benefits TEXT,
            ingredients TEXT,
            image_url TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO product VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "curtain",
                CURTAIN_TITLE,
                CURTAIN_TITLE,
                "Textiles & Soft Furnishings",
                "Household Textiles",
                "Curtains",
                "#LangsirViral\n15-30s\nMusic",
                "Order now!",
                "https://example.com/curtain.jpg",
            ),
            (
                "pet",
                "Premium pet food for kucing",
                "Premium pet food for kucing",
                "Pet Supplies",
                "Pet Food",
                "Cat Food",
                "Protein source stated on pack",
                "Chicken",
                "",
            ),
        ],
    )

    first = audit_catalog(connection)
    second = audit_catalog(connection)

    assert first == second
    assert first["summary"]["total_products"] == 2
    assert first["summary"]["provider_calls"] == 0
    assert first["summary"]["write_operations"] == 0
    curtain = next(row for row in first["products"] if row["product_id"] == "curtain")
    assert curtain["family"] == "HOME_TEXTILE"
    assert "EVIDENCE_BENEFITS_PRODUCTION_METADATA" in curtain["issue_codes"]
    assert "CONSISTENCY_FAMILY_TAXONOMY_CONFLICT" not in curtain["issue_codes"]
