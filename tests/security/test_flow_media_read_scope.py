from agent.security.access_control import required_permission


def test_flow_media_get_uses_minimum_assets_read_scope():
    assert required_permission(
        "/api/flow/media/f14dcdba-4b95-4ad4-a024-94c421231724",
        "GET",
    ) == "assets.read"


def test_other_flow_routes_keep_production_scope():
    assert required_permission("/api/flow/credits", "GET") == "production.read"
    assert required_permission("/api/flow/generate", "POST") == "production.execute"
