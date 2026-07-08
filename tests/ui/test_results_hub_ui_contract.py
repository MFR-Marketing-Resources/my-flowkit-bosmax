"""Results Hub UI contract.

The durable deliverable hub must, per finished result, expose the three sections
(preview+download, prompt+settings for manual Google Flow fallback, and social
captions) and REUSE the existing SocialCopyPackagePanel instead of forking a
parallel caption editor. It must be reachable from the app router.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_page_reuses_social_copy_panel():
    src = _read("dashboard/src/pages/ResultsHubPage.tsx")
    assert "SocialCopyPackagePanel" in src
    assert 'from "../components/SocialCopyPackagePanel"' in src


def test_page_has_three_sections():
    src = _read("dashboard/src/pages/ResultsHubPage.tsx")
    assert "Preview" in src and "Download" in src
    assert "Prompt" in src and "Settings" in src
    assert "Captions" in src


def test_page_exposes_prompt_and_copy_for_manual_fallback():
    src = _read("dashboard/src/pages/ResultsHubPage.tsx")
    assert "final_prompt_text" in src
    assert "clipboard" in src  # copy-to-clipboard so operator can re-drive Flow


def test_page_calls_results_api():
    src = _read("dashboard/src/pages/ResultsHubPage.tsx")
    assert "listResults" in src
    assert "getResult" in src


def test_api_client_targets_results_endpoint():
    src = _read("dashboard/src/api/results.ts")
    assert "/api/results" in src
    assert "listResults" in src
    assert "getResult" in src


def test_registered_in_app_routes_and_nav():
    app = _read("dashboard/src/App.tsx")
    assert "ResultsHubPage" in app
    assert 'path="/results"' in app
    assert 'to: "/results"' in app
