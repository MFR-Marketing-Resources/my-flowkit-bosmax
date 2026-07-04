"""UI source contracts for the Social Copy Package layer.

The generator pages (T2V/F2V/HYBRID/I2V/IMG all render through OperatorPage)
must expose a platform-specific caption/comment authoring panel, and Postiz
Publish must prefill its caption from the approved copy of the selected artifact.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_social_copy_panel_has_platform_specific_fields():
    src = _read("dashboard/src/components/SocialCopyPackagePanel.tsx")
    assert "Social Copy Package" in src
    # All five platforms are selectable.
    for label in ("TikTok", "Instagram", "Facebook", "Threads", "X/Twitter"):
        assert label in src, f"missing platform label {label}"
    # Minimum copy fields.
    assert "Caption" in src
    assert "Pinned comment" in src            # TikTok first-comment label
    assert "First comment" in src             # FB/IG first-comment label
    assert "Hashtags" in src
    assert "Call to action (CTA)" in src
    assert "Tone / style" in src
    # Language is operator-selectable (backend already persists `language`).
    assert "Language" in src
    for lang in ("Malay", "Malay slang", "English", "Mixed"):
        assert lang in src, f"missing language option {lang}"
    # …and the chosen language is sent on both create and update.
    assert "language: form.language" in src
    # Approval workflow + claim-safe surfacing.
    assert "Approve" in src
    assert "Suggest copy" in src
    assert "claim-safe" in src.lower()


def test_social_copy_api_client_targets_the_new_endpoints_only():
    api = _read("dashboard/src/api/socialCopyPackages.ts")
    assert "/api/social-copy-packages" in api
    assert "generateSocialCopyPackage" in api
    assert "approveSocialCopyPackage" in api
    assert "listSocialCopyPackages" in api
    assert "suggestSocialCopy" in api
    # No social OAuth or provider hosts wired in BOSMAX.
    lowered = api.lower()
    for forbidden in ("client_secret", "oauth/authorize", "graph.facebook.com"):
        assert forbidden not in lowered


def test_operator_page_mounts_copy_panel_for_finished_artifact():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "SocialCopyPackagePanel" in src
    # Linked to the just-finished artifact's media id + current mode.
    assert "completedArtifact.mediaId" in src
    assert "sourceMode={mode}" in src


def test_postiz_prefills_caption_from_approved_copy_package():
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")
    assert "listSocialCopyPackages" in src
    assert "Approved social copy for this artifact" in src
    # Fail-safe: no saved copy => clearly manual, never a silent empty caption.
    assert "No saved copy package for this artifact" in src
    # Prefill only pulls APPROVED copy and never silently clobbers manual edits.
    assert 'status: "APPROVED"' in src
    assert "applyCopyPackage" in src
    assert "contentTouched" in src


def test_postiz_prefill_is_provider_aware():
    """Selecting a channel should recommend the matching platform's copy, map
    known providers to platforms, and never override a manual caption."""
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")
    assert "providerToPlatform" in src
    assert "recommendedPlatforms" in src
    assert "Recommended" in src
    # Provider→platform coverage for the required platforms.
    for provider in ("tiktok", "instagram", "facebook", "threads"):
        assert f"{provider}:" in src, f"missing provider mapping {provider}"
    assert "twitter:" in src  # x/twitter → x
    # Auto-suggest must bail out on a manually-edited caption.
    assert "if (contentTouched) return;" in src


def test_existing_postiz_onboarding_contract_survives():
    """Regression guard: the zero-channel onboarding + Setup Doctor copy the
    earlier PRs added must still be present alongside the new prefill panel."""
    src = _read("dashboard/src/pages/PostizPublishPage.tsx")
    assert "No Postiz channels connected yet" in src
    assert "Open Postiz to Add Channel" in src
    assert "POSTIZ SETUP DOCTOR" in src
