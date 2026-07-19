"""WRNA Round 3 — canonical composition resolver.

Covers the frozen blockers:
- B-01: real higher-authority precedence wiring (Product Truth -> approved
  identity -> operator -> recipe -> WRNA mode), selective suppression with
  provenance, compatible characteristics retained.
- B-02: five structurally distinct mode profiles (uniqueness NEVER via
  profile_id) + deterministic copy/quality governance (reusing the poster
  copy-quality authority).
- B-03: manifest save/reopen roundtrip preserving plan, signature and engine
  prompt (model-level here; the full deliverable DB roundtrip lives in
  test_poster_deliverable_service.py).
"""
import pytest

from agent.models.poster_copy_quality import PosterCopyQualityRequest
from agent.models.poster_render_manifest import PosterRenderManifest
from agent.services import poster_recipe_service
from agent.services.poster_composition_service import (
    PosterCompositionError,
    build_composition_constraints,
    render_composition_instruction,
    resolve_poster_composition,
)
from agent.services.poster_copy_quality_service import evaluate_poster_copy
from agent.services.poster_template_service import (
    build_render_manifest,
    manifest_frame_ratio,
    template_contract,
)

MODES = (
    "PGC_CAMPAIGN",
    "UGC_AUTHENTIC",
    "MODEL_AMBASSADOR",
    "CLEAN_STUDIO_CATALOGUE",
    "LIFESTYLE_EDITORIAL",
)

# Human-presence policies exactly as the Creative Direction authority YAML
# declares them (the identity constraint derives from the REAL policy string).
_AUTHORITY_HUMAN_POLICY = {
    "PGC_CAMPAIGN": "optional_commercial_role",
    "UGC_AUTHENTIC": "optional_natural_interaction",
    "MODEL_AMBASSADOR": "approved_avatar_or_operator_selected_role",
    "CLEAN_STUDIO_CATALOGUE": "none_by_default",
    "LIFESTYLE_EDITORIAL": "optional_contextual_role",
}


class Direction:
    def __init__(self, mode: str):
        self.mode = mode
        self.human_presence_policy = _AUTHORITY_HUMAN_POLICY.get(mode, "")
        self.authority_version = "creative-direction-modes-v1"
        self.representation_policy_version = "malaysian-representation-policy-v1"
        self.product_truth_claim_gate = "RESTRICTED"


_PRODUCT = {
    "product_display_name": "Minyak Warisan Tok",
    "raw_product_title": "Minyak Warisan Tok 25ml",
    "category": "Traditional",
}

_FIELDS = {"hook": "Ringkas dan padat", "cta": "Lihat sekarang"}


def _plan(mode: str, *, constraints=None, fields=None, recipe_id="r", frame_ratio="9:16"):
    return resolve_poster_composition(
        creative_direction=Direction(mode),
        recipe_id=recipe_id,
        frame_ratio=frame_ratio,
        fields=fields if fields is not None else dict(_FIELDS),
        constraints=constraints,
    )


def _constraints(mode: str, **kwargs):
    return build_composition_constraints(
        product=kwargs.pop("product", dict(_PRODUCT)),
        creative_direction=kwargs.pop("creative_direction", Direction(mode)),
        **kwargs,
    )


# ── B-02: structural five-mode distinction (NO profile_id) ───────────────────


def test_each_mode_resolves_a_structured_professional_plan():
    for mode in MODES:
        plan = _plan(mode, recipe_id="wrna_ads_poster_916")
        assert plan["schema_version"] == "wrna-poster-composition-v1"
        assert plan["creative_mode"] == mode
        assert plan["canvas"]["safe_margin"] == "5%"
        assert plan["product"]["label_visibility"] == "required"
        assert plan["copy"]["cta_zone"]
        assert plan["reading_order"]
        assert plan["signature"]
        assert "no text covering product or face" in plan["quality_negative_rules"]


def test_modes_structurally_distinct_across_independent_dimensions_without_profile_id():
    plans = {mode: _plan(mode, fields={}) for mode in MODES}

    def dimensions(p):
        # Independent structured dimensions ONLY — profile_id is excluded by
        # construction and must never carry the uniqueness.
        return {
            "anchor": p["product"]["anchor"],
            "dominance": p["product"]["dominance"],
            "reading_order": tuple(p["reading_order"]),
            "human_policy": p["scene"]["human_presence"],
            "face_safe": p["scene"]["face_safe_rule"],
            "copy_side": p["copy"]["copy_side"],
            "hook_treatment": p["typography"]["hook"],
            "usp_treatment": p["typography"]["usp"],
            "cta_treatment": p["typography"]["cta"],
            "typography_intensity": p["typography"]["intensity"],
            "background": p["scene"]["background_complexity"],
            "lighting": p["scene"]["lighting"],
            "prop_density": p["scene"]["prop_density"],
            "negative_space": p["scene"]["negative_space"],
        }

    dims = {mode: dimensions(p) for mode, p in plans.items()}
    # All five full-dimension tuples are distinct.
    assert len({tuple(sorted(d.items())) for d in dims.values()}) == 5
    # Every PAIR of modes differs in at least three independent dimensions —
    # meaningfully different structure, not one token apart.
    modes = list(MODES)
    for i, a in enumerate(modes):
        for b in modes[i + 1:]:
            differing = [k for k in dims[a] if dims[a][k] != dims[b][k]]
            assert len(differing) >= 3, f"{a} vs {b} differ only in {differing}"


def test_identical_inputs_produce_identical_plan_provenance_and_signature():
    recipe = poster_recipe_service.get_recipe("product_hero_night_routine")
    contract = template_contract("product_hero_night_routine")
    kwargs = dict(
        recipe=recipe,
        template_contract=contract,
        operator_human_presence="with_human",
    )
    first = _plan("UGC_AUTHENTIC", constraints=_constraints("UGC_AUTHENTIC", **kwargs))
    second = _plan("UGC_AUTHENTIC", constraints=_constraints("UGC_AUTHENTIC", **kwargs))
    assert first == second
    assert first["signature"] == second["signature"]
    assert first["provenance"] == second["provenance"]
    assert first["warnings"] == second["warnings"]


def test_signature_tracks_actual_inputs():
    assert (
        _plan("PGC_CAMPAIGN", frame_ratio="9:16")["signature"]
        != _plan("PGC_CAMPAIGN", frame_ratio="1:1")["signature"]
    )


# ── B-01: precedence proofs against the REAL authorities ─────────────────────


def test_product_truth_locks_identity_label_and_scale():
    """Proof 1: Product Truth prevents identity/geometry/label/volume/scale
    drift — the mode's relaxed label styling is suppressed with provenance."""
    plan = _plan("UGC_AUTHENTIC", constraints=_constraints("UGC_AUTHENTIC"))
    assert plan["product"]["identity_lock"] is True
    assert plan["product"]["label_style"] == (
        "label fully readable, true packaging, real-world scale"
    )
    assert plan["product"]["real_world_scale"] == "required"
    assert "PRODUCT_TRUTH" in plan["provenance"]["active_locks"]
    supp = {
        (s["property"], s["reason"], s["authority"])
        for s in plan["provenance"]["suppressions"]
    }
    assert ("product.label_style", "PRODUCT_TRUTH_LOCK", "PRODUCT_TRUTH") in supp
    prompt = render_composition_instruction(plan)
    assert "no product form-factor or scale change" in prompt
    assert "label fully readable" in prompt


def test_approved_identity_rule_prevents_unapproved_person():
    """Proof 2: the representation-policy-backed identity rule restricts any
    on-poster person to an approved identity."""
    plan = _plan(
        "MODEL_AMBASSADOR", constraints=_constraints("MODEL_AMBASSADOR")
    )
    assert plan["scene"]["identity_policy"] == "approved identity only"
    assert "APPROVED_IDENTITY" in plan["provenance"]["active_locks"]
    assert any(
        s["reason"] == "APPROVED_IDENTITY_LOCK" for s in plan["provenance"]["suppressions"]
    )
    # A mode without the approved-avatar policy keeps its own identity posture.
    ugc = _plan("UGC_AUTHENTIC", constraints=_constraints("UGC_AUTHENTIC"))
    assert ugc["scene"]["identity_policy"] == "unrestricted natural person"


def test_operator_hard_selection_overrides_wrna_human_policy():
    """Proof 3: the operator's human-presence selection wins over the mode."""
    plan = _plan(
        "UGC_AUTHENTIC",
        constraints=_constraints("UGC_AUTHENTIC", operator_human_presence="product_only"),
    )
    assert plan["scene"]["human_presence"] == "product_only"
    assert plan["scene"]["identity_policy"] == "no person"
    assert "OPERATOR_HUMAN_PRESENCE" in plan["provenance"]["active_locks"]
    assert any(
        s["property"] == "scene.human_presence"
        and s["reason"] == "OPERATOR_HARD_SELECTION"
        and s["mode_value"] == "allowed"
        for s in plan["provenance"]["suppressions"]
    )


def test_recipe_required_human_cannot_be_removed_by_studio_mode():
    """Proof 4: the in-hand scale-cue recipe re-introduces the hand the Studio
    mode prohibits (recipe > WRNA mode)."""
    recipe = poster_recipe_service.get_recipe("product_scale_portability")
    contract = template_contract("product_scale_portability")
    plan = _plan(
        "CLEAN_STUDIO_CATALOGUE",
        constraints=_constraints(
            "CLEAN_STUDIO_CATALOGUE", recipe=recipe, template_contract=contract
        ),
        recipe_id="product_scale_portability",
    )
    assert plan["scene"]["human_presence"] == "required-hands-scale-cue"
    assert "RECIPE_REQUIRED_HUMAN" in plan["provenance"]["active_locks"]
    assert any(
        s["reason"] == "RECIPE_REQUIRED_HUMAN" and s["mode_value"] == "prohibited"
        for s in plan["provenance"]["suppressions"]
    )
    # A hands-only cue brings no face — no face-safe zone is activated.
    assert plan["scene"]["face_safe_rule"] == "not applicable"


def test_recipe_safe_region_overrides_incompatible_mode_anchor():
    """Proof 5: the recipe's real product-safe region wins over the mode
    anchor, and the frame-spanning product band stacks the copy zones."""
    recipe = poster_recipe_service.get_recipe("product_hero_night_routine")
    contract = template_contract("product_hero_night_routine")
    plan = _plan(
        "PGC_CAMPAIGN",
        constraints=_constraints(
            "PGC_CAMPAIGN", recipe=recipe, template_contract=contract
        ),
        recipe_id="product_hero_night_routine",
    )
    assert plan["product"]["anchor"] == "middle-center"
    supp = {(s["property"], s["reason"]) for s in plan["provenance"]["suppressions"]}
    assert ("product.anchor", "RECIPE_SAFE_REGION_LOCK") in supp
    assert ("copy.copy_side", "RECIPE_SAFE_REGION_LOCK") in supp
    assert plan["copy"]["copy_side"] == "stacked"
    assert "PRODUCT_COPY_ZONE_CONFLICT_RESOLVED" in plan["warnings"]
    assert "RECIPE_SAFE_REGION" in plan["provenance"]["active_locks"]


def test_compatible_mode_characteristics_survive_unrelated_suppression():
    """Proof 6: suppressing the anchor/copy side leaves the mode's lighting,
    background and typography intact; a mode already compatible with the
    recipe gets NO suppression at all for those properties."""
    recipe = poster_recipe_service.get_recipe("product_hero_night_routine")
    contract = template_contract("product_hero_night_routine")
    constrained = _plan(
        "PGC_CAMPAIGN",
        constraints=_constraints(
            "PGC_CAMPAIGN", recipe=recipe, template_contract=contract
        ),
        recipe_id="product_hero_night_routine",
    )
    unconstrained = _plan("PGC_CAMPAIGN")
    for path in (
        ("scene", "lighting"),
        ("scene", "background_complexity"),
        ("typography", "intensity"),
        ("typography", "hook"),
        ("typography", "cta"),
    ):
        assert constrained[path[0]][path[1]] == unconstrained[path[0]][path[1]]
    # Studio is ALREADY center-anchored and stacked — the same recipe suppresses
    # nothing structural for it (only truth/identity-level locks may appear).
    studio = _plan(
        "CLEAN_STUDIO_CATALOGUE",
        constraints=_constraints(
            "CLEAN_STUDIO_CATALOGUE", recipe=recipe, template_contract=contract
        ),
        recipe_id="product_hero_night_routine",
    )
    structural = [
        s for s in studio["provenance"]["suppressions"]
        if s["property"] in ("product.anchor", "copy.copy_side")
    ]
    assert structural == []
    assert "PRODUCT_COPY_ZONE_CONFLICT_RESOLVED" not in studio["warnings"]


def test_operator_introduced_person_activates_face_safety_in_studio():
    """A person forced into the faceless Studio mode gains a protected face
    zone and the top-center hook relocates below it (deterministic record)."""
    plan = _plan(
        "CLEAN_STUDIO_CATALOGUE",
        constraints=_constraints(
            "CLEAN_STUDIO_CATALOGUE", operator_human_presence="with_human"
        ),
    )
    assert plan["scene"]["human_presence"] == "with_human"
    assert plan["scene"]["face_safe_rule"] == "upper-center protected"
    assert "below face-safe band" in plan["copy"]["hook_zone"]
    assert "FACE_COPY_ZONE_CONFLICT_RESOLVED" in plan["warnings"]


# ── B-02: deterministic copy/quality governance (pass + fail cases) ──────────


def test_density_and_duplicate_warnings_fire_and_stay_stable():
    plan = _plan(
        "PGC_CAMPAIGN",
        fields={"hook": "x" * 49, "cta": "y" * 25},
    )
    assert plan["warnings"] == [
        "HOOK_DENSITY_EXCEEDS_COMPOSITION_LIMIT",
        "CTA_DENSITY_EXCEEDS_COMPOSITION_LIMIT",
    ]
    clean = _plan("PGC_CAMPAIGN", fields={"hook": "x" * 48, "cta": "y" * 24})
    assert clean["warnings"] == []
    dup = _plan("PGC_CAMPAIGN", fields={"hook": "Sama", "cta": "Sama"})
    assert dup["warnings"] == ["DUPLICATE_COPY_DETECTED"]


def test_usp_overflow_buried_cta_and_edge_placement_warnings():
    plan = _plan(
        "PGC_CAMPAIGN",
        fields={
            "hook": "Baik",
            "subhook": "s" * 40,
            "usp_1": "a" * 30,
            "usp_2": "b" * 30,
            "usp_3": "c" * 30,
            "usp_4": "d" * 30,
            "cta": "Beli",
        },
    )
    assert "USP_COUNT_EXCEEDS_COMPOSITION_LIMIT" in plan["warnings"]
    assert "CTA_BURIED_BY_LOWER_PRIORITY_COPY" in plan["warnings"]
    edge = _plan("PGC_CAMPAIGN", fields={"hook": "z" * 60, "cta": "Beli"})
    assert "UNSAFE_EDGE_PLACEMENT" in edge["warnings"]
    small = _plan(
        "PGC_CAMPAIGN",
        fields={"hook": "Baik", "subhook": "kecil", "usp_1": "satu", "cta": "Beli"},
    )
    assert "CTA_BURIED_BY_LOWER_PRIORITY_COPY" not in small["warnings"]
    assert "UNSAFE_EDGE_PLACEMENT" not in small["warnings"]


def test_chip_and_claim_badge_governance_reuses_quality_authority():
    """The established poster copy-quality validator (not a duplicate) drives
    chip-overflow warnings and the claim-as-badge blocker."""
    overflow = evaluate_poster_copy(
        PosterCopyQualityRequest(
            poster_headline="Tajuk padu",
            poster_chips=["Satu", "Dua", "Tiga", "Empat"],
            poster_cta="Beli sekarang",
            max_chips=3,
        )
    )
    plan = _plan(
        "PGC_CAMPAIGN",
        constraints=_constraints("PGC_CAMPAIGN", copy_quality_report=overflow),
    )
    assert "CHIP_BADGE_TREATMENT_UNCONTROLLED" in plan["warnings"]
    assert plan["blockers"] == []

    claim = evaluate_poster_copy(
        PosterCopyQualityRequest(
            poster_headline="Tajuk padu",
            poster_chips=["Legakan sakit"],
            poster_cta="Beli sekarang",
        )
    )
    blocked = _plan(
        "PGC_CAMPAIGN",
        constraints=_constraints("PGC_CAMPAIGN", copy_quality_report=claim),
    )
    assert blocked["blockers"] == ["UNSUPPORTED_CLAIM_BADGE"]

    clean = evaluate_poster_copy(
        PosterCopyQualityRequest(
            poster_headline="Tajuk padu",
            poster_chips=["Saiz poket"],
            poster_cta="Beli sekarang",
        )
    )
    ok = _plan(
        "PGC_CAMPAIGN",
        constraints=_constraints("PGC_CAMPAIGN", copy_quality_report=clean),
    )
    assert "CHIP_BADGE_TREATMENT_UNCONTROLLED" not in ok["warnings"]
    assert ok["blockers"] == []


# ── Legacy + fail-closed routes ──────────────────────────────────────────────


def test_no_mode_preserves_legacy_empty_plan():
    assert (
        resolve_poster_composition(
            creative_direction=None, recipe_id="r", frame_ratio="9:16", fields={}
        )
        == {}
    )
    assert render_composition_instruction({}) == ""


def test_unsupported_mode_fails_closed():
    class Bogus:
        mode = "NOT_A_MODE"

    with pytest.raises(PosterCompositionError, match="UNSUPPORTED_COMPOSITION_MODE"):
        resolve_poster_composition(
            creative_direction=Bogus(), recipe_id="r", frame_ratio="9:16", fields={}
        )


def test_engine_prompt_is_engine_facing_without_internal_metadata():
    plan = _plan("PGC_CAMPAIGN", constraints=_constraints("PGC_CAMPAIGN"))
    prompt = render_composition_instruction(plan)
    assert "product anchored" in prompt
    assert "safe margin" in prompt
    for leaked in (
        "profile_id",
        "schema_version",
        "signature",
        plan["signature"],
        "wrna-poster-composition",
        "PRODUCT_TRUTH_LOCK",
        "constraint_schema",
    ):
        assert leaked not in prompt


# ── B-03: manifest save/reopen roundtrip (model level) ───────────────────────

_COPY = {
    "poster_copy_set_id": "pcs-1",
    "version": 3,
    "primary_message": "Minyak warisan keluarga",
    "support_message": "Sedia bila anda perlukan.",
    "proof_points": ["Saiz poket", "Mudah dibawa"],
    "cta": "Beli sekarang",
    "disclaimer": "Untuk kegunaan luaran sahaja.",
    "language": "ms",
}


def test_manifest_roundtrip_preserves_plan_signature_and_engine_prompt():
    recipe = poster_recipe_service.get_recipe("product_hero_night_routine")
    contract = template_contract("product_hero_night_routine")
    constraints = _constraints(
        "LIFESTYLE_EDITORIAL", recipe=recipe, template_contract=contract
    )
    plan_a = resolve_poster_composition(
        creative_direction=Direction("LIFESTYLE_EDITORIAL"),
        recipe_id="product_hero_night_routine",
        frame_ratio=manifest_frame_ratio(),
        fields={"hook": _COPY["primary_message"], "cta": _COPY["cta"]},
        constraints=constraints,
    )
    prompt_a = render_composition_instruction(plan_a)
    manifest = build_render_manifest(
        recipe_id="product_hero_night_routine",
        copy_set=_COPY,
        background_local_path="C:/tmp/bg.png",
        creative_direction={
            "mode": "LIFESTYLE_EDITORIAL",
            "authority_version": "creative-direction-modes-v1",
            "representation_policy_version": "malaysian-representation-policy-v1",
        },
        composition_plan=plan_a,
    )
    # save (serialize exactly as the deliverable row persists it) → reopen.
    raw = manifest.model_dump_json()
    restored = PosterRenderManifest.model_validate_json(raw)
    plan_b = restored.provenance.composition_plan
    assert plan_b == plan_a
    assert plan_b["signature"] == plan_a["signature"]
    assert render_composition_instruction(plan_b) == prompt_a
    # Provenance summary matches the canonical plan (no hand-rolled signature).
    assert restored.provenance.composition_signature == plan_a["signature"]
    assert restored.provenance.composition_profile_id == plan_a["profile_id"]
    assert (
        restored.provenance.composition_schema_version
        == "wrna-poster-composition-v1"
    )
    # Binding + authority versions preserved through the roundtrip.
    assert restored.provenance.poster_copy_set_id == "pcs-1"
    assert restored.provenance.poster_copy_set_version == 3
    assert restored.provenance.recipe_id == "product_hero_night_routine"
    assert restored.provenance.creative_mode == "LIFESTYLE_EDITORIAL"
    assert (
        restored.provenance.creative_direction_authority_version
        == "creative-direction-modes-v1"
    )
    assert plan_b["authority_versions"]["creative_direction"] == "creative-direction-modes-v1"
    # The plan carries the ACTUAL canvas ratio, not a fabricated default.
    assert plan_b["canvas"]["frame_ratio"] == "9:16"


def test_manifest_without_plan_preserves_honest_absence():
    manifest = build_render_manifest(
        recipe_id="product_hero_night_routine",
        copy_set=_COPY,
        background_local_path="C:/tmp/bg.png",
    )
    assert manifest.provenance.composition_plan == {}
    assert manifest.provenance.composition_signature == ""
    assert manifest.provenance.composition_profile_id == ""
    assert manifest.provenance.composition_schema_version == ""
