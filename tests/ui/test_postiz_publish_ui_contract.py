"""UI source contracts for the Postiz Publish page (feature-flagged adapter)."""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_postiz_page_exists_with_fail_closed_and_safety_tokens():
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")
    assert "POSTIZ PUBLISH" in src
    assert "Draft (safe)" in src           # draft is the visible safe default
    assert "dry run" in src                # payload preview without posting
    assert "SELF_ONLY" in src              # TikTok unaudited-app safety default
    assert "multiple accounts of the same provider" in src


def test_postiz_api_client_targets_official_public_endpoints_only():
    api = _read("dashboard/src/api/postiz.ts")
    assert "/api/postiz/publish" in api
    assert "/api/postiz/integrations" in api


def test_postiz_route_is_registered_without_touching_existing_nav():
    app = _read("dashboard/src/App.tsx")
    assert '"/postiz"' in app
    assert "PostizPublishPage" in app
    # Locked tokens from the side-panel contract must survive our nav edit.
    assert "function EmbeddedRouteReporter() {" in app
    assert 'type: "FLOWKIT_DASHBOARD_ROUTE_SYNC"' in app
