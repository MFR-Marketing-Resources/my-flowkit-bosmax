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


def test_setup_doctor_replaces_dead_end_error_screen():
    """Disabled/misconfigured state must render an actionable checklist,
    not raw POSTIZ_DISABLED / *_MISSING codes alone."""
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")
    assert "POSTIZ SETUP DOCTOR" in src
    assert "docker compose up -d" in src        # exact start command visible
    assert "no social channels are connected yet" in src
    assert "RE-CHECK" in src                     # operator can re-verify live
    api = _read("dashboard/src/api/postiz.ts")
    assert "/api/postiz/setup-status" in api


def test_zero_channel_onboarding_panel_guides_operator_to_postiz():
    """Healthy config + zero channels must render a dedicated channel-
    onboarding panel (not the generic setup-required copy): a link out to
    Postiz, a refresh action, a checklist, provider caveats, and a disabled
    send with helper text."""
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")

    # Distinct 'channels missing' state, gated on healthy setup + zero channels.
    assert "healthyNoChannels" in src
    assert "integrations_count === 0" in src

    # Panel title + explanation (exact operator copy).
    assert "No Postiz channels connected yet" in src
    assert (
        "BOSMAX is connected to Postiz, but Postiz has no connected social"
        in src
    )

    # Primary link-out (Postiz owns the OAuth) + secondary refresh.
    assert "Open Postiz to Add Channel" in src
    assert "Refresh channels" in src
    assert 'target="_blank"' in src              # opens in a new tab
    assert 'rel="noopener noreferrer"' in src    # safe external link

    # Concise checklist steps.
    assert "Click Add Channel / Connect Channel" in src
    assert "Return to BOSMAX and click Refresh channels" in src

    # Provider caveats, one recognisable fragment per platform.
    assert "Instagram needs professional/business/creator account" in src
    assert "verified HTTPS media domain" in src              # TikTok
    assert "availability depends on API/app tier" in src     # X/Twitter
    assert "uploads may default private" in src              # YouTube

    # Publishing blocked until a channel exists.
    assert "Connect at least one channel in Postiz before sending." in src


def test_bosmax_links_out_for_channel_oauth_never_implements_it():
    """BOSMAX must send the operator to Postiz for social OAuth, never wire
    Meta/X/TikTok/YouTube OAuth itself."""
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")
    # Link-out fallback target is Postiz's own UI on this machine.
    assert "http://127.0.0.1:5000" in src
    lowered = src.lower()
    for forbidden in (
        "client_id",
        "client_secret",
        "oauth/authorize",
        "graph.facebook.com",
        "api.twitter.com",
        "open.tiktokapis.com",
        "accounts.google.com",
    ):
        assert forbidden not in lowered, (
            f"BOSMAX must not implement provider OAuth directly: {forbidden}"
        )
