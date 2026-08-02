"""The authenticated-browser evidence relay.

The relay exists because TikTok answers the server with a Security Check shell, so the only
place the listing is readable is a tab the OPERATOR has already signed in to. That makes the
extension reply untrusted input arriving from an authenticated session — the two properties
that matter most here, and the ones these tests are built around:

  1. NOTHING outside the allowlist can reach the database, no matter what the browser sends.
  2. Every failure is a NAMED, distinguishable state — because "open your TikTok tab",
     "clear the captcha yourself" and "the bridge is down" have completely different fixes
     and a single generic error would collapse them into one useless message.

Every test here is deterministic: no network, no live extension, no real tab.
"""
from __future__ import annotations

import pytest

from agent.services import tiktokshop_browser_relay as relay

PRODUCT_URL = "https://shop.tiktok.com/view/product/1729543210987654321"

GOOD_EVIDENCE = {
    "canonical_url": PRODUCT_URL,
    "title": "Minyak Warisan Cap Burung 25ml",
    "description": ("Minyak urut tradisional. Bahan: minyak kelapa, halia, serai. "
                    "Amaran: Elak kawasan mata."),
    "brand": "Cap Burung",
    "price_text": "18.90",
    "currency": "MYR",
    "variant_labels": ["25ml"],
    "images": ["https://p16.tiktokcdn.com/img/minyak.jpg"],
    "page_text": ("Minyak Warisan Cap Burung 25ml Minyak urut tradisional. "
                  "Bahan: minyak kelapa, halia, serai. Amaran: Elak kawasan mata."),
    "evidence_methods": ["JSONLD", "META"],
}


class FakeFlowClient:
    """Stands in for the WebSocket bridge. Records what the relay actually sent."""

    def __init__(self, reply, *, connected=True):
        self._reply = reply
        self.connected = connected
        self.sent: list[tuple[str, dict, float]] = []

    async def _send(self, method, params, timeout=0):
        self.sent.append((method, params, timeout))
        if callable(self._reply):
            return self._reply(params)
        return self._reply


def install_client(monkeypatch, client):
    from agent.services import flow_client as module

    monkeypatch.setattr(module, "get_flow_client", lambda: client)
    return client


def browser_reply(params, *, ok=True, evidence=None, error=None, **extra):
    """Shape the extension actually puts on the wire (handler payload under `result`)."""
    return {"result": {
        "ok": ok,
        "error": error,
        "evidence_request_id": params["evidence_request_id"],
        "tab_id": 42,
        "matched_tabs": 1,
        "observed_url": extra.pop("observed_url", PRODUCT_URL),
        "evidence": evidence,
        **extra,
    }}


# ── URL identity ─────────────────────────────────────────────────────────────
def test_only_the_two_authorized_hosts_are_relayable():
    assert relay.relay_supports_url(PRODUCT_URL)
    assert relay.relay_supports_url(
        "https://shop-my.tiktok.com/view/product/1729543210987654321")
    # Reachable by the DIRECT fetcher, but the manifest grants the content script exactly
    # two hosts — claiming otherwise would promise the operator a retry that cannot work.
    assert not relay.relay_supports_url("https://www.tiktok.com/view/product/1")
    assert not relay.relay_supports_url("https://shop.tiktokglobalshop.com/view/product/1")
    assert not relay.relay_supports_url("http://shop.tiktok.com/view/product/1")
    assert not relay.relay_supports_url("https://evil.com/shop.tiktok.com/product/1")


def test_identity_ignores_tracking_query_strings_but_not_the_product():
    """TikTok appends tracking params on every in-app navigation.

    Comparing whole hrefs would reject the operator's own tab.
    """
    wanted = relay.product_identity(PRODUCT_URL)
    same = relay.product_identity(f"{PRODUCT_URL}?enter_from=mall&trace=abc123")
    other = relay.product_identity("https://shop.tiktok.com/view/product/9999999999999")

    assert relay.identities_match(wanted, same)
    assert not relay.identities_match(wanted, other)


def test_the_same_product_matches_across_the_two_authorized_hosts():
    """TikTok's OWN redirect moves a product between the two Shop hosts.

    A stored `shop-my.tiktok.com/pdp/<id>` link opens as
    `shop.tiktok.com/view/product/<id>`. Requiring the same host made the relay reject the
    operator's own correct tab on the first live pilot round — reported as
    NO_MATCHING_TAB while the product sat open on screen. The id is the identity.
    """
    stored = relay.product_identity(
        "https://shop-my.tiktok.com/pdp/1733784168157316566?source=product_detail")
    redirected = relay.product_identity(
        "https://shop.tiktok.com/view/product/1733784168157316566?region=MY&local=en")
    assert relay.identities_match(stored, redirected)

    # The guarantee that actually matters is UNCHANGED: a different product never matches,
    # on either host. That is what stops one listing's evidence reaching another's draft.
    different = relay.product_identity(
        "https://shop.tiktok.com/view/product/1729547196228863761")
    assert not relay.identities_match(stored, different)
    assert not relay.identities_match(
        stored, relay.product_identity(
            "https://shop-my.tiktok.com/pdp/1729547196228863761"))


# ── sanitization: the whole security model ───────────────────────────────────
def test_session_material_has_no_path_into_the_database():
    """The allowlist is closed. A compromised or modified content script gains nothing."""
    hostile = dict(GOOD_EVIDENCE)
    hostile.update({
        "cookies": "sessionid=abc123; sid_tt=deadbeef",
        "localStorage": {"token": "x"},
        "sessionStorage": {"y": "z"},
        "authorization": "Bearer super-secret",
        "account": {"user_id": "7712345", "email": "operator@example.com"},
        "document_html": "<html>everything</html>",
    })

    clean = relay.sanitize_evidence(hostile, requested_url=PRODUCT_URL)

    assert set(clean) <= relay.ALLOWED_EVIDENCE_KEYS | {
        "dropped_keys", "tab_id", "matched_tabs", "replayed", "evidence_request_id"}
    for forbidden in ("cookies", "localStorage", "sessionStorage", "authorization",
                      "account", "document_html"):
        assert forbidden not in clean
    # Dropped LOUDLY: a silent filter would make a widening content script invisible.
    assert set(clean["dropped_keys"]) == {
        "account", "authorization", "cookies", "document_html", "localStorage",
        "sessionStorage"}
    assert "super-secret" not in str(clean)
    assert "deadbeef" not in str(clean)


def test_credential_shaped_text_inside_an_allowlisted_field_is_redacted():
    """The allowlist governs KEYS. This covers the value that arrives in a legal key."""
    leaky = dict(GOOD_EVIDENCE)
    leaky["page_text"] = ("Minyak urut tradisional. sessionid=abc123secret "
                          "msToken=zzz9 Authorization: Bearer leaked-token")

    clean = relay.sanitize_evidence(leaky, requested_url=PRODUCT_URL)

    assert "abc123secret" not in clean["page_text"]
    assert "zzz9" not in clean["page_text"]
    assert "leaked-token" not in clean["page_text"]
    assert relay._REDACTED in clean["page_text"]
    assert "Minyak urut tradisional." in clean["page_text"]


def test_only_tiktok_cdn_images_survive():
    """An arbitrary <img> is an ad or a tracking pixel, not the product."""
    payload = dict(GOOD_EVIDENCE)
    payload["images"] = [
        "https://tracker.example.com/pixel.gif",
        "http://p16.tiktokcdn.com/insecure.jpg",
        "https://p16.tiktokcdn.com/img/real.jpg",
        "https://p16.tiktokcdn.com/img/real.jpg",   # duplicate
        "javascript:alert(1)",
    ]
    clean = relay.sanitize_evidence(payload, requested_url=PRODUCT_URL)
    assert clean["images"] == ["https://p16.tiktokcdn.com/img/real.jpg"]


def test_a_tab_showing_a_different_product_is_refused():
    """The guard against one listing's evidence landing on another product's draft."""
    payload = dict(GOOD_EVIDENCE)
    payload["canonical_url"] = "https://shop.tiktok.com/view/product/8888888888888"
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        relay.sanitize_evidence(payload, requested_url=PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_URL_MISMATCH


def test_evidence_with_no_title_and_no_description_is_refused_not_stored():
    """An empty "success" is how a good draft gets silently overwritten with nothing."""
    payload = dict(GOOD_EVIDENCE, title="", description="")
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        relay.sanitize_evidence(payload, requested_url=PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_EMPTY_EVIDENCE


def test_oversized_fields_are_bounded_and_methods_are_marked_authenticated():
    payload = dict(GOOD_EVIDENCE)
    payload["page_text"] = "x" * 999_999
    payload["title"] = "y" * 99_999
    payload["variant_labels"] = [f"label-{i}" for i in range(500)]
    payload["evidence_methods"] = ["json ld!!", "META"]

    clean = relay.sanitize_evidence(payload, requested_url=PRODUCT_URL)

    assert len(clean["page_text"]) <= relay.MAX_PAGE_TEXT_CHARS
    assert len(clean["title"]) <= relay.MAX_FIELD_CHARS
    assert len(clean["variant_labels"]) <= relay.MAX_VARIANTS
    # AUTHENTICATED_DOM first, so every provenance row this lane writes is recognisable
    # as a browser read rather than an anonymous fetch.
    assert clean["evidence_methods"][0] == "AUTHENTICATED_DOM"
    assert "JSONLD" in clean["evidence_methods"]


def test_a_non_object_reply_is_malformed_not_a_crash():
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        relay.sanitize_evidence("<html>nope</html>", requested_url=PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_MALFORMED_RESPONSE


# ── transport failures: each one distinguishable ─────────────────────────────
@pytest.mark.asyncio
async def test_a_disconnected_extension_is_named_not_a_generic_failure(monkeypatch):
    install_client(monkeypatch, FakeFlowClient({}, connected=False))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_EXTENSION_DISCONNECTED
    assert excinfo.value.operator_actionable
    assert excinfo.value.product_url == PRODUCT_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("browser_error,expected", [
    ("TIKTOK_SECURITY_CHECK_PRESENT", relay.ERR_SECURITY_CHECK_PRESENT),
    ("TIKTOK_NO_MATCHING_TAB", relay.ERR_NO_MATCHING_TAB),
    ("TIKTOK_CONTENT_SCRIPT_UNREACHABLE:no receiver",
     relay.ERR_CONTENT_SCRIPT_UNREACHABLE),
    ("TIKTOK_TAB_NAVIGATED_AWAY", relay.ERR_TAB_NAVIGATED_AWAY),
    ("TIKTOK_EVIDENCE_EMPTY", relay.ERR_EMPTY_EVIDENCE),
    ("TIKTOK_HOST_PERMISSION_MISSING", relay.ERR_HOST_PERMISSION_MISSING),
])
async def test_each_browser_state_maps_to_its_own_code(monkeypatch, browser_error,
                                                      expected):
    install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, ok=False, error=browser_error)))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == expected
    # Every one of these is fixed by the operator in Chrome, so the API can offer a Retry.
    assert excinfo.value.operator_actionable


@pytest.mark.asyncio
async def test_the_captcha_is_reported_and_never_solved(monkeypatch):
    """The contract line that must never be softened."""
    client = install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, ok=False,
                                     error="TIKTOK_SECURITY_CHECK_PRESENT")))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_SECURITY_CHECK_PRESENT
    # ONE acquisition attempt. No retry loop, no second verb, nothing that could be read
    # as an attempt to work around the challenge.
    assert len(client.sent) == 1
    assert client.sent[0][0] == relay.WS_METHOD


@pytest.mark.asyncio
async def test_a_permission_blind_extension_is_not_reported_as_an_empty_browser(
        monkeypatch):
    """The failure that cost a live pilot round.

    Chrome does not reliably grant newly-added host permissions to an already-installed
    unpacked extension on runtime.reload(). A permission-blind extension gets `undefined`
    for every tab.url, so a url-filtered query matches nothing — identical to "no tab
    open". Told the latter, an operator reopens tabs forever against a browser that can
    never see them.
    """
    install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, ok=False,
                                     error="TIKTOK_HOST_PERMISSION_MISSING")))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_HOST_PERMISSION_MISSING
    assert excinfo.value.code != relay.ERR_NO_MATCHING_TAB
    assert excinfo.value.operator_actionable


@pytest.mark.asyncio
async def test_no_matching_tab_carries_counts_that_expose_a_permission_blind_browser(
        monkeypatch):
    """Counts only — never a tab inventory, which would be the operator's browsing history.

    `tabs_with_readable_url` far below `total_tabs` is the fingerprint of a browser that is
    hiding urls from the extension even when Chrome claims the permission is granted.
    """
    install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, ok=False, error="TIKTOK_NO_MATCHING_TAB",
                                     open_tiktok_tabs=0, host_permission_granted=True,
                                     total_tabs=37, tabs_with_readable_url=2)))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_NO_MATCHING_TAB
    detail = excinfo.value.detail
    assert "total_tabs=37" in detail
    assert "tabs_with_readable_url=2" in detail
    assert "host_permission_granted=True" in detail
    # and no URL from the operator's browser leaked into the detail
    assert "http" not in detail


@pytest.mark.asyncio
async def test_a_bridge_timeout_is_reported_as_a_timeout(monkeypatch):
    install_client(monkeypatch, FakeFlowClient(
        {"error": "Timeout (40s) waiting for TIKTOK_ACQUIRE_PRODUCT_EVIDENCE"}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_TIMEOUT


@pytest.mark.asyncio
async def test_a_reply_that_answers_a_different_request_is_rejected(monkeypatch):
    """A late reply from an earlier attempt must never be adopted as this one's answer."""
    install_client(monkeypatch, FakeFlowClient({"result": {
        "ok": True,
        "evidence_request_id": "some-other-request",
        "evidence": GOOD_EVIDENCE,
    }}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence(PRODUCT_URL)
    assert excinfo.value.code == relay.ERR_CORRELATION_MISMATCH


@pytest.mark.asyncio
async def test_every_request_carries_a_fresh_correlation_id(monkeypatch):
    client = install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, evidence=GOOD_EVIDENCE)))
    first = await relay.acquire_evidence(PRODUCT_URL)
    second = await relay.acquire_evidence(PRODUCT_URL)
    assert first["evidence_request_id"] != second["evidence_request_id"]
    assert client.sent[0][1]["product_url"] == PRODUCT_URL


@pytest.mark.asyncio
async def test_an_unsupported_host_never_reaches_the_bridge(monkeypatch):
    client = install_client(monkeypatch, FakeFlowClient({}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.acquire_evidence("https://www.tiktok.com/view/product/1")
    assert excinfo.value.code == relay.ERR_HOST_NOT_SUPPORTED
    # Not operator-actionable: no amount of opening tabs fixes a link on the wrong host.
    assert not excinfo.value.operator_actionable
    assert client.sent == []


# ── end to end over a deterministic fixture ──────────────────────────────────
@pytest.mark.asyncio
async def test_relayed_evidence_runs_the_same_deterministic_rules_as_a_direct_fetch(
        monkeypatch):
    """One normalizer for both lanes.

    If the browser lane had its own parser, the size/ingredient/warning rules would be free
    to drift apart from the direct lane's, and the same listing could mean two things
    depending on how it was fetched.
    """
    from agent.services import ai_copy_provider_adapter as adapter

    monkeypatch.setattr(adapter, "complete_json", lambda system, user: {})
    install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, evidence=GOOD_EVIDENCE)))

    result = await relay.extract_product_via_browser(PRODUCT_URL)

    assert result["acquisition_mode"] == "AUTHENTICATED_BROWSER_RELAY"
    assert result["fields"]["size_or_volume"] == "25ml"
    assert "minyak kelapa" in result["fields"]["materials_text"].lower()
    assert "mata" in result["fields"]["warnings_text"].lower()
    assert result["fields"]["price"] == 18.90
    # Provenance says HOW: a reviewer can tell a browser read from an anonymous fetch.
    methods = {row["extraction_method"] for row in result["provenance"]}
    assert any("AUTHENTICATED_DOM" in method for method in methods)
    overrides = result["field_provenance_overrides"]
    assert overrides["ingredients_text"]["extraction_method"] == \
        "TIKTOKSHOP_LABELLED_SECTION"
    assert overrides["product_description"]["verification_status"] == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_a_merchandising_label_relayed_from_the_browser_is_still_not_a_pack_size(
        monkeypatch):
    """The roll-on/25ml defect class, re-checked on the new lane.

    "Standard" is a merchandising word. Accepting it as `size_or_volume` writes a fake pack
    size into the product truth that later drives scale locks in prompts.
    """
    from agent.services import ai_copy_provider_adapter as adapter

    monkeypatch.setattr(adapter, "complete_json", lambda system, user: {})
    payload = dict(GOOD_EVIDENCE, variant_labels=["Standard"],
                   title="Sarung Kusyen Biru", description="Sarung kusyen warna biru.",
                   page_text="Sarung Kusyen Biru Sarung kusyen warna biru.")
    install_client(monkeypatch, FakeFlowClient(
        lambda params: browser_reply(params, evidence=payload)))

    result = await relay.extract_product_via_browser(PRODUCT_URL)

    assert "size_or_volume" not in result["fields"]
    assert result["unresolved"]["size_or_volume"] in (
        "REJECTED_NOT_A_MEASUREMENT", "REJECTED_NO_UNIT", "ABSENT_IN_SOURCE")
    # and nothing was invented for the labelled sections either
    assert result["unresolved"]["ingredients_text"] == "NOT_STATED_IN_SOURCE"
    assert result["unresolved"]["warnings_text"] == "NOT_STATED_IN_SOURCE"


# ─── TIKTOK_NAVIGATE_PRODUCT_TAB — the bounded single-tab navigation seam ─────
# The navigate RPC exists so the bulk does not depend on the operator opening every tab by
# hand. Its whole safety story is that it can only ever drive ONE dedicated tab to a
# specific, already-known product listing — so these tests pin exactly that.

NAV_URL = "https://shop.tiktok.com/view/product/1729543210987654321"


@pytest.mark.asyncio
async def test_navigate_sends_the_expected_product_id_derived_from_the_url(monkeypatch):
    """The id the extension must match is derived from the product's OWN stored link — the
    cross-product contamination guard lives on both sides of the bridge."""
    client = install_client(monkeypatch, FakeFlowClient(
        {"ok": True, "outcome": "PAGE_READY", "observed_product_id": "1729543210987654321"}))
    result = await relay.navigate_product_tab(NAV_URL)
    assert result["outcome"] == "PAGE_READY"
    method, params, _ = client.sent[-1]
    assert method == relay.WS_NAVIGATE_METHOD
    assert params["product_url"] == NAV_URL
    assert params["expected_product_id"] == "1729543210987654321"


@pytest.mark.asyncio
async def test_navigate_refuses_a_url_off_the_allowlist_before_touching_the_bridge(monkeypatch):
    client = install_client(monkeypatch, FakeFlowClient({"ok": True, "outcome": "PAGE_READY"}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.navigate_product_tab("https://example.com/view/product/123456789")
    assert excinfo.value.code == relay.ERR_HOST_NOT_SUPPORTED
    assert client.sent == []  # never reached the extension


@pytest.mark.asyncio
async def test_navigate_disconnected_extension_is_named(monkeypatch):
    install_client(monkeypatch, FakeFlowClient({}, connected=False))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.navigate_product_tab(NAV_URL)
    assert excinfo.value.code == relay.ERR_EXTENSION_DISCONNECTED


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected", [
    ("SECURITY_CHECK_REQUIRES_HUMAN", "TIKTOK_RELAY_SECURITY_CHECK_PRESENT"),
    ("PRODUCT_DELISTED", "TIKTOK_RELAY_PRODUCT_DELISTED"),
    ("PRODUCT_ID_MISMATCH", "TIKTOK_RELAY_PRODUCT_ID_MISMATCH"),
    ("NAVIGATION_TIMEOUT", "TIKTOK_RELAY_TIMEOUT"),
    # B-597-01: an unreadable page is empty evidence (act-then-retry), never delisted.
    ("EXTRACTION_FAILED", "TIKTOK_RELAY_EMPTY_EVIDENCE"),
])
async def test_navigate_every_failure_outcome_maps_to_its_own_code(monkeypatch, outcome, expected):
    install_client(monkeypatch, FakeFlowClient({"ok": False, "outcome": outcome}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.navigate_product_tab(NAV_URL)
    assert excinfo.value.code == expected


@pytest.mark.asyncio
async def test_navigate_delisted_and_mismatch_are_not_operator_actionable(monkeypatch):
    """A dead link and a redirect-to-another-product cannot be fixed by opening a tab, so
    they must NOT be advertised as act-then-retry states."""
    assert relay.ERR_PRODUCT_DELISTED not in relay.OPERATOR_ACTIONABLE_CODES
    assert relay.ERR_PRODUCT_ID_MISMATCH not in relay.OPERATOR_ACTIONABLE_CODES


@pytest.mark.asyncio
async def test_navigate_unknown_outcome_is_malformed_not_a_crash(monkeypatch):
    install_client(monkeypatch, FakeFlowClient({"ok": False, "outcome": "SOMETHING_NEW"}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.navigate_product_tab(NAV_URL)
    assert excinfo.value.code == relay.ERR_MALFORMED_RESPONSE


@pytest.mark.asyncio
async def test_navigate_extraction_failed_is_empty_evidence_not_delisted(monkeypatch):
    """B-597-01 backend half: an EXTRACTION_FAILED navigation (an empty/unreadable page)
    maps to the truthful EMPTY_EVIDENCE code, NEVER to a delisted claim."""
    install_client(monkeypatch, FakeFlowClient(
        {"ok": False, "outcome": "EXTRACTION_FAILED", "error": "TIKTOK_EVIDENCE_EMPTY"}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.navigate_product_tab(NAV_URL)
    assert excinfo.value.code == relay.ERR_EMPTY_EVIDENCE
    assert excinfo.value.code != relay.ERR_PRODUCT_DELISTED


@pytest.mark.asyncio
async def test_navigate_only_an_explicit_delisted_outcome_is_delisted(monkeypatch):
    """The ONLY path to ERR_PRODUCT_DELISTED is the extension asserting PRODUCT_DELISTED."""
    install_client(monkeypatch, FakeFlowClient({"ok": False, "outcome": "PRODUCT_DELISTED"}))
    with pytest.raises(relay.TikTokRelayError) as excinfo:
        await relay.navigate_product_tab(NAV_URL)
    assert excinfo.value.code == relay.ERR_PRODUCT_DELISTED
