"""API surface proof for the provider-free Round 1 namespace."""

from agent.main import app


def test_v3_api_matrix_includes_round3_materialize_without_activation():
    # OpenAPI provides the concrete registered path set across FastAPI
    # versions, including releases that keep included routers nested.  Macro
    # Round 3 (P3) promotes the explicit materialize routes from absent to
    # present; product-global V2 activation and P6 allocation routes remain
    # deliberately ABSENT from this supply-plane router.
    paths = set(app.openapi()["paths"])
    assert "/api/storyboard-landbank/v3/authority/formulas" in paths
    assert "/api/storyboard-landbank/v3/angles" in paths
    assert "/api/storyboard-landbank/v3/storyline-families" in paths
    assert "/api/storyboard-landbank/v3/components" in paths
    assert "/api/storyboard-landbank/v3/recipes" in paths
    assert "/api/storyboard-landbank/v3/recipes/{recipe_id}" in paths
    assert "/api/storyboard-landbank/v3/projections/{projection_id}" in paths
    assert "/api/storyboard-landbank/v3/components/{component_id}/revisions" in paths
    assert "/api/storyboard-landbank/v3/candidates/preview" in paths
    assert "/api/storyboard-landbank/v3/masters/compile" in paths
    assert "/api/storyboard-landbank/v3/projections/compile" in paths
    assert "/api/storyboard-landbank/v3/capacity/{recipe_id}" in paths
    assert "/api/storyboard-landbank/v3/landbank/components" in paths
    assert "/api/storyboard-landbank/v3/review-queue" in paths
    assert "/api/storyboard-landbank/v3/seeds/v2/preview" in paths
    assert "/api/storyboard-landbank/v3/copy-register/provider-status" in paths
    assert "/api/storyboard-landbank/v3/copy-register/assistant/plan" in paths
    assert "/api/storyboard-landbank/v3/copy-register/assistant/plans/{plan_id}/prompt-preview" in paths
    assert "/api/storyboard-landbank/v3/copy-register/assistant/plans/{plan_id}/execute" in paths
    assert "/api/storyboard-landbank/v3/copy-register/landbank" in paths
    assert "/api/storyboard-landbank/v3/copy-register/review-queue" in paths
    assert "/api/storyboard-landbank/v3/copy-register/approval/master/{master_id}" in paths
    assert "/api/storyboard-landbank/v3/copy-register/approval/batch" in paths
    # Round 3 P3: explicit, human-triggered materialize routes are now present.
    assert "/api/storyboard-landbank/v3/copy-register/materialize" in paths
    assert "/api/storyboard-landbank/v3/copy-register/materialize-bulk" in paths
    # This supply-plane router must NEVER expose product-global V2 activation or a
    # P6 allocation route: per-item production selection stays in the P6 seam.
    assert not any(
        "activate" in path or "/p6" in path.lower()
        for path in paths
        if "storyboard-landbank/v3" in path
    )
