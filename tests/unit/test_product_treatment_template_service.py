import pytest

from agent.authority import product_readiness_applicability_registry as registry
from agent.models.product_readiness import ProductReadinessEvaluateRequest
from agent.services import product_treatment_template_service as service


import json

def _profile():
    return next(profile for profile in registry.list_applicability_profiles() if profile.supported)


def _context(
    creative_format: str = "PGC",
    *,
    action_index: int = 0,
) -> ProductReadinessEvaluateRequest:
    return ProductReadinessEvaluateRequest(
        product_id="product-facts-must-not-enter-template",
        allowed_action_index=action_index,
        creative_format=creative_format,
        logical_mode="HYBRID",
        generation_mode="SINGLE",
        model_key="veo_3_1_fast",
        duration_seconds=8,
    )


def test_template_is_deterministic_policy_without_product_facts():
    first = service.resolve_treatment_template(
        context=_context(),
        profile=_profile(),
        requirements=[],
    )
    second = service.resolve_treatment_template(
        context=_context(),
        profile=_profile(),
        requirements=[],
    )

    assert first == second
    assert first.template_id == f"ptt_{first.template_sha256[:24]}"
    assert first.template_version == service.TEMPLATE_VERSION
    assert "product_id" not in first.model_dump()
    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "product-facts-must-not-enter-template" not in serialized
    assert sum(shot.duration_seconds for shot in first.shot_grammar) == 8


def test_ugc_pgc_and_cinematic_have_distinct_structured_shot_grammars():
    templates = {
        creative_format: service.resolve_treatment_template(
            context=_context(creative_format),
            profile=_profile(),
            requirements=[],
        )
        for creative_format in ("UGC", "PGC", "CINEMATIC")
    }

    grammars = {
        creative_format: template.model_dump(mode="json")["shot_grammar"]
        for creative_format, template in templates.items()
    }
    assert grammars["UGC"] != grammars["PGC"]
    assert grammars["PGC"] != grammars["CINEMATIC"]
    assert grammars["UGC"] != grammars["CINEMATIC"]
    assert templates["UGC"].actor_policy == "PRESENTER_REQUIRED"
    assert templates["PGC"].actor_policy == "PRESENTER_FORBIDDEN"
    assert templates["CINEMATIC"].actor_policy == "PRESENTER_OPTIONAL"


def test_unauthorized_action_index_fails_closed():
    with pytest.raises(
        service.ProductTreatmentTemplateError,
        match="ACTION_INDEX_NOT_AUTHORIZED",
    ):
        service.resolve_treatment_template(
            context=_context(action_index=999),
            profile=_profile(),
            requirements=[],
        )
