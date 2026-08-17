"""API surface proof for the provider-free Round 1 namespace."""

from agent.main import app


def test_round1_v3_api_matrix_is_registered_without_future_round_routes():
    # Newer FastAPI releases expose included-router sentinels alongside the
    # concrete routes; only concrete routes carry a path.
    paths = {route.path for route in app.routes if hasattr(route, "path")}
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
    assert not any("approve" in path or "materialize" in path or "p6" in path.lower() for path in paths if "storyboard-landbank/v3" in path)
