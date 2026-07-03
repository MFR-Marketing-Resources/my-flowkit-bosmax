"""Contracts for the Postiz adapter (feature-flagged, fail-closed).

Pure/local tests — no network: config gate, MIME whitelist, public-HTTPS URL
law, deterministic /posts payload generation incl. multiple channels of the
same provider, and provider setting templates.
"""
import pytest

from agent.services import postiz_client as pz


def _enable(monkeypatch, **overrides):
    env = {
        "POSTIZ_ENABLED": "true",
        "POSTIZ_BASE_URL": "http://localhost:5000",
        "POSTIZ_API_KEY": "test-key-not-a-secret",
        "POSTIZ_UPLOAD_MODE": "file",
        "POSTIZ_DEFAULT_POST_TYPE": "draft",
    }
    env.update(overrides)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


# ── Config gate (fail closed) ─────────────────────────────────────────────


def test_disabled_flag_fails_closed(monkeypatch):
    monkeypatch.delenv("POSTIZ_ENABLED", raising=False)
    with pytest.raises(pz.PostizConfigError, match="POSTIZ_DISABLED"):
        pz.ensure_enabled_and_configured()


def test_missing_api_key_fails_closed_never_silent(monkeypatch):
    _enable(monkeypatch, POSTIZ_API_KEY=None)
    with pytest.raises(pz.PostizConfigError, match="POSTIZ_API_KEY_MISSING"):
        pz.ensure_enabled_and_configured()


def test_missing_base_url_fails_closed(monkeypatch):
    _enable(monkeypatch, POSTIZ_BASE_URL=None)
    with pytest.raises(pz.PostizConfigError, match="POSTIZ_BASE_URL_MISSING"):
        pz.ensure_enabled_and_configured()


def test_invalid_upload_mode_fails_closed(monkeypatch):
    _enable(monkeypatch, POSTIZ_UPLOAD_MODE="ftp")
    with pytest.raises(pz.PostizConfigError, match="POSTIZ_UPLOAD_MODE_INVALID"):
        pz.ensure_enabled_and_configured()


def test_health_summary_never_leaks_the_api_key(monkeypatch):
    _enable(monkeypatch, POSTIZ_API_KEY="super-secret-value")
    summary = pz.health_summary()
    assert summary["ok"] is True
    assert summary["api_key_present"] is True
    assert "super-secret-value" not in str(summary)


async def test_disabled_flag_blocks_network_entry_points(monkeypatch):
    monkeypatch.setenv("POSTIZ_ENABLED", "false")
    with pytest.raises(pz.PostizConfigError):
        await pz.list_integrations()
    with pytest.raises(pz.PostizConfigError):
        await pz.upload_file("x.jpg")
    with pytest.raises(pz.PostizConfigError):
        await pz.create_post({})


# ── MIME validation ───────────────────────────────────────────────────────


def test_media_mime_whitelist_accepts_image_and_mp4(tmp_path):
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"fake")
    mp4 = tmp_path / "b.mp4"
    mp4.write_bytes(b"fake")
    assert pz.validate_media_file(str(jpg)) == "image/jpeg"
    assert pz.validate_media_file(str(mp4)) == "video/mp4"


def test_media_mime_whitelist_rejects_other_types(tmp_path):
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(pz.PostizValidationError, match="UNSUPPORTED_MEDIA_TYPE"):
        pz.validate_media_file(str(exe))


def test_missing_file_is_rejected_before_upload(tmp_path):
    with pytest.raises(pz.PostizValidationError, match="MEDIA_FILE_NOT_FOUND"):
        pz.validate_media_file(str(tmp_path / "nope.mp4"))


# ── upload-from-url law: public HTTPS only ────────────────────────────────


@pytest.mark.parametrize("bad_url", [
    "http://cdn.example.com/a.mp4",           # not HTTPS
    "https://localhost/a.mp4",
    "https://127.0.0.1/a.mp4",
    "https://10.1.2.3/a.mp4",
    "https://192.168.1.10/a.mp4",
    "https://172.16.9.1/a.mp4",
    "https://media.local/a.mp4",
    "https://intranethost/a.mp4",              # no dots — not public
    "https://[::1]/a.mp4",
])
def test_private_or_non_https_urls_are_rejected(bad_url):
    with pytest.raises(pz.PostizValidationError):
        pz.validate_public_https_url(bad_url)


def test_public_https_media_url_passes():
    pz.validate_public_https_url("https://cdn.example.com/media/abc.mp4")
    pz.validate_public_https_url("https://cdn.example.com/media/abc.jpg")


def test_url_with_disallowed_extension_is_rejected():
    with pytest.raises(pz.PostizValidationError, match="UNSUPPORTED_MEDIA_TYPE"):
        pz.validate_public_https_url("https://cdn.example.com/a.exe")


# ── /posts payload generation ─────────────────────────────────────────────

_MEDIA = [{"id": "m-1", "path": "/uploads/m-1.mp4"}]


def test_payload_supports_multiple_channels_of_the_same_provider():
    payload = pz.build_post_payload(
        post_type="draft",
        integration_ids=["tt-account-1", "tt-account-2", "fb-page-1"],
        media=_MEDIA,
        content="hello",
        integration_providers={
            "tt-account-1": "tiktok", "tt-account-2": "tiktok", "fb-page-1": "facebook",
        },
    )
    assert payload["type"] == "draft"
    assert [p["integration"]["id"] for p in payload["posts"]] == [
        "tt-account-1", "tt-account-2", "fb-page-1",
    ]
    # Both TikTok accounts get the safe TikTok template, independently.
    for post in payload["posts"][:2]:
        assert post["settings"]["privacy_level"] == "SELF_ONLY"
        assert post["settings"]["content_posting_method"] == "DIRECT_POST"
    assert payload["posts"][2]["settings"] == {}
    for post in payload["posts"]:
        assert post["value"][0]["content"] == "hello"
        assert post["value"][0]["image"] == [{"id": "m-1", "path": "/uploads/m-1.mp4"}]


def test_payload_never_hardcodes_channel_ids_and_rejects_empty_selection():
    with pytest.raises(pz.PostizValidationError, match="NO_INTEGRATIONS_SELECTED"):
        pz.build_post_payload(post_type="draft", integration_ids=[], media=_MEDIA)


def test_payload_rejects_duplicate_integration_ids():
    with pytest.raises(pz.PostizValidationError, match="DUPLICATE_INTEGRATION_IDS"):
        pz.build_post_payload(
            post_type="draft", integration_ids=["a", "a"], media=_MEDIA,
        )


def test_schedule_requires_a_date_and_uses_it():
    with pytest.raises(pz.PostizValidationError, match="SCHEDULE_AT_REQUIRED"):
        pz.build_post_payload(post_type="schedule", integration_ids=["a"], media=_MEDIA)
    payload = pz.build_post_payload(
        post_type="schedule", integration_ids=["a"], media=_MEDIA,
        schedule_at="2026-08-01T10:00:00Z",
    )
    assert payload["date"] == "2026-08-01T10:00:00Z"


def test_unknown_post_type_is_rejected():
    with pytest.raises(pz.PostizValidationError, match="UNSUPPORTED_POST_TYPE"):
        pz.build_post_payload(post_type="publish", integration_ids=["a"], media=_MEDIA)


def test_explicit_settings_override_the_provider_template():
    payload = pz.build_post_payload(
        post_type="draft",
        integration_ids=["tt-1"],
        media=_MEDIA,
        integration_providers={"tt-1": "tiktok"},
        provider_settings={"tt-1": {"privacy_level": "PUBLIC_TO_EVERYONE", "duet": True}},
    )
    assert payload["posts"][0]["settings"]["privacy_level"] == "PUBLIC_TO_EVERYONE"


# ── Provider templates / warnings ─────────────────────────────────────────


def test_tiktok_template_has_all_required_fields_with_safe_defaults():
    t = pz.PROVIDER_SETTING_TEMPLATES["tiktok"]
    for field in ("privacy_level", "duet", "stitch", "comment", "autoAddMusic",
                  "brand_content_toggle", "brand_organic_toggle", "content_posting_method"):
        assert field in t, field
    assert t["privacy_level"] == "SELF_ONLY"  # unaudited-app safety default


def test_provider_warnings_surface_tiktok_and_meta_limits():
    w = pz.PROVIDER_WARNINGS
    assert any("audit" in x.lower() for x in w["tiktok"])
    assert any("SELF_ONLY" in x for x in w["tiktok"])
    assert any("verified" in x.lower() for x in w["tiktok"])
    assert any("live" in x.lower() for x in w["facebook"])
    assert any("professional" in x.lower() for x in w["instagram"])


async def test_unexpected_integrations_response_raises(monkeypatch):
    """A wrong base URL/prefix (e.g. hitting the frontend HTML) must raise,
    not return an empty channel list — proven against the live instance."""
    _enable(monkeypatch)

    async def fake_request(method, path, *, cfg, json_body=None, files=None, retries=0):
        return {"raw": "<html>next.js frontend</html>"}

    monkeypatch.setattr(pz, "_request", fake_request)
    with pytest.raises(pz.PostizApiError, match="UNEXPECTED_INTEGRATIONS_RESPONSE"):
        await pz.list_integrations()


def test_api_prefix_defaults_to_selfhosted_and_is_overridable(monkeypatch):
    _enable(monkeypatch)
    assert pz.postiz_config()["api_prefix"] == "/api/public/v1"
    monkeypatch.setenv("POSTIZ_API_PREFIX", "/public/v1")
    assert pz.postiz_config()["api_prefix"] == "/public/v1"
