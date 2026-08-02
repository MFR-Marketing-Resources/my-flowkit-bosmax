"""Acquire TikTok Shop product evidence through an operator-authenticated browser tab.

    stored TikTok product URL
      -> BOSMAX Chrome extension (existing WebSocket bridge)
      -> content script in the OPERATOR'S already-authenticated tab
      -> sanitized, allowlisted evidence
      -> this module re-validates it
      -> the SAME deterministic normalizer the direct-fetch lane uses

WHY A RELAY AT ALL
`tiktokshop_extraction_service.fetch_source` reaches TikTok as an anonymous client and gets
the Security Check shell — an identical ~5.6KB wall for every product, which is why the
direct lane fails closed with TIKTOKSHOP_AUTHENTICATED_BROWSER_REQUIRED. The operator's own
browser is already past that wall. This module borrows THAT session's rendered page, and
nothing else about the session.

THE OPERATOR CLEARS THE CAPTCHA, NEVER THE CODE
When the wall is still on screen the content script reports it and this module raises
`TIKTOK_RELAY_SECURITY_CHECK_PRESENT`. There is no solve path and there must never be one.

WHY THE ALLOWLIST IS REPEATED HERE
The content script already builds a closed evidence object, so re-filtering it looks
redundant. It is not: the extension is separately installed and separately reloadable, so
the browser side is not something the server can prove the shape of at call time. Treating
its reply as untrusted input — allowlisted keys, bounded lengths, host-checked image URLs,
identity-checked canonical URL — means a modified, stale or hostile content script still
cannot put anything new into the database. Anything outside the allowlist is dropped and
reported in `dropped_keys` rather than stored.

WHAT IS NEVER ACCEPTED
Cookies, authorization headers, session tokens, storage contents and account identity have
no key in the allowlist, so there is no path for them to arrive. Text fields additionally
run through a credential-shaped redaction pass, because "the field is called page_text" is
not by itself proof of what a future page put in it.
"""
from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

WS_METHOD = "TIKTOK_ACQUIRE_PRODUCT_EVIDENCE"
# Slightly longer than the extension's own 30s ceiling so a browser-side timeout surfaces as
# its specific cause rather than as a generic bridge timeout.
RELAY_TIMEOUT_SECONDS = 40.0

ERR_EXTENSION_DISCONNECTED = "TIKTOK_RELAY_EXTENSION_DISCONNECTED"
ERR_HOST_NOT_SUPPORTED = "TIKTOK_RELAY_HOST_NOT_SUPPORTED"
ERR_NO_MATCHING_TAB = "TIKTOK_RELAY_NO_MATCHING_TAB"
ERR_SECURITY_CHECK_PRESENT = "TIKTOK_RELAY_SECURITY_CHECK_PRESENT"
ERR_CONTENT_SCRIPT_UNREACHABLE = "TIKTOK_RELAY_CONTENT_SCRIPT_UNREACHABLE"
ERR_TIMEOUT = "TIKTOK_RELAY_TIMEOUT"
ERR_MALFORMED_RESPONSE = "TIKTOK_RELAY_MALFORMED_RESPONSE"
ERR_CORRELATION_MISMATCH = "TIKTOK_RELAY_CORRELATION_MISMATCH"
ERR_URL_MISMATCH = "TIKTOK_RELAY_URL_MISMATCH"
ERR_EMPTY_EVIDENCE = "TIKTOK_RELAY_EMPTY_EVIDENCE"
ERR_TAB_NAVIGATED_AWAY = "TIKTOK_RELAY_TAB_NAVIGATED_AWAY"
# Chrome did not grant the two TikTok hosts to the installed extension. Distinct from
# NO_MATCHING_TAB on purpose: a permission-blind extension reports zero tabs even when the
# operator has the product open in front of them, so conflating the two would have them
# reopening tabs forever against a browser that can never see them.
ERR_HOST_PERMISSION_MISSING = "TIKTOK_RELAY_HOST_PERMISSION_MISSING"
# The dedicated evidence tab navigated to a DIFFERENT product than the one requested (a
# redirect that changed the product id). A defect-class contamination guard, never retried.
ERR_PRODUCT_ID_MISMATCH = "TIKTOK_RELAY_PRODUCT_ID_MISMATCH"
# The listing loaded but states no product — delisted / removed. Not operator-actionable:
# reopening the same dead link can never succeed, so it is ledgered and skipped, not retried.
ERR_PRODUCT_DELISTED = "TIKTOK_RELAY_PRODUCT_DELISTED"

# Every code an operator can personally fix by acting in the browser. The API layer turns
# these into 409 (act, then retry) instead of 502 (server fault), so "open the tab" never
# looks like "the backend is broken".
OPERATOR_ACTIONABLE_CODES = frozenset({
    ERR_EXTENSION_DISCONNECTED,
    ERR_NO_MATCHING_TAB,
    ERR_SECURITY_CHECK_PRESENT,
    ERR_CONTENT_SCRIPT_UNREACHABLE,
    ERR_TAB_NAVIGATED_AWAY,
    ERR_TIMEOUT,
    # A half-rendered listing and a tab sitting on the wrong product are both fixed in the
    # browser — scroll/reload, or open the right product — so they get the same
    # act-then-Retry treatment rather than reading as a backend fault.
    ERR_EMPTY_EVIDENCE,
    ERR_URL_MISMATCH,
    # Fixed in chrome://extensions (re-grant site access, or remove and re-add the
    # unpacked extension) — an operator step, not a server fault.
    ERR_HOST_PERMISSION_MISSING,
})
# Deliberately NOT actionable: ERR_HOST_NOT_SUPPORTED (a stored link on the wrong host —
# retrying can never help), ERR_MALFORMED_RESPONSE and ERR_CORRELATION_MISMATCH (defects,
# not operator steps). Those stay 502 and show no Retry.

# The two hosts the mission authorises, and the only two in the extension manifest.
RELAY_HOSTS = ("shop.tiktok.com", "shop-my.tiktok.com")

# The closed set of evidence keys. Adding a key here is the ONLY way to widen what the
# browser can contribute to the catalogue.
ALLOWED_EVIDENCE_KEYS = frozenset({
    "canonical_url", "title", "description", "brand", "price_text", "currency",
    "variant_labels", "images", "page_text", "evidence_methods",
})
_TEXT_KEYS = ("title", "description", "brand", "price_text", "currency")

MAX_FIELD_CHARS = 4000
MAX_PAGE_TEXT_CHARS = 20000
MAX_IMAGES = 12
MAX_VARIANTS = 24
MAX_METHODS = 8

# Images must come from TikTok's own CDNs. An arbitrary <img> on a listing can be an ad or a
# tracking pixel; storing one as the product image would put third-party content into the
# catalogue under this product's name.
_IMAGE_HOST_RE = re.compile(
    r"^https://[\w.-]*(?:tiktokcdn|tiktokcdn-us|ibyteimg|byteimg)\.com/", re.IGNORECASE)

# Defence in depth over the allowlist: strip anything shaped like session material out of
# free text before it can be persisted as evidence.
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:\b(?:sessionid[_a-z]*|sid_tt|sid_guard|uid_tt|msToken|passport_csrf_token|"
    r"csrf_session_id|access_token|refresh_token|authorization|cookie|set-cookie)\b"
    # `(?:bearer\s+)?` matters: without it "Authorization: Bearer <token>" redacts only the
    # word "Bearer" and leaves the actual secret sitting in the text.
    r"\s*[:=]\s*(?:bearer\s+)?\S+"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{8,})")
_REDACTED = "[REDACTED]"


class TikTokRelayError(Exception):
    def __init__(self, code: str, detail: str = "", product_url: str = ""):
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail
        # Carried so the UI can render the exact link the operator must open. Telling
        # someone to "open the stored product link" without showing it is an instruction
        # they cannot follow from the screen they are on.
        self.product_url = product_url

    @property
    def operator_actionable(self) -> bool:
        return self.code in OPERATOR_ACTIONABLE_CODES


def relay_supports_url(url: str) -> bool:
    """True when this URL is on a host the relay (and the manifest) covers."""
    return product_identity(url) is not None


def product_identity(url: str) -> dict[str, str | None] | None:
    """Host + product id for a TikTok Shop product URL, or None when unusable.

    Whole-href comparison would fail on the tracking query strings TikTok appends on every
    in-app navigation; host-only comparison would let ANY open TikTok tab answer for a
    completely different product. The stable identity is the long numeric id in the path.
    """
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    host = (parsed.hostname or "").lower()
    if host not in RELAY_HOSTS:
        return None
    path = (parsed.path or "").rstrip("/")
    match = re.search(r"(\d{8,})", path)
    return {"host": host, "path": path, "product_id": match.group(1) if match else None}


def identities_match(wanted: dict[str, Any] | None,
                     candidate: dict[str, Any] | None) -> bool:
    """The product id is the identity; the host is not.

    Mirrors `tiktokIdentityMatches` in background.js and must stay in step with it. TikTok
    redirects between the two authorized Shop hosts for the SAME product
    (`shop-my.tiktok.com/pdp/<id>` opens as `shop.tiktok.com/view/product/<id>`), so a
    same-host requirement rejects the operator's own correct tab. A 19-digit TikTok Shop
    product id is globally unique, so id equality is what actually prevents one listing's
    evidence landing on another product; both hosts are permission-gated by the manifest
    either way. With no id on either side we require an exact host+path match rather than
    guessing.
    """
    if not wanted or not candidate:
        return False
    if wanted.get("product_id") and candidate.get("product_id"):
        return wanted["product_id"] == candidate["product_id"]
    return (wanted.get("host") == candidate.get("host")
            and wanted.get("path") == candidate.get("path"))


def _redact(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())[:limit]
    return _CREDENTIAL_RE.sub(_REDACTED, text)


def sanitize_evidence(payload: Any, *, requested_url: str) -> dict[str, Any]:
    """Reduce an extension reply to allowlisted, bounded, identity-checked product facts.

    Raises TikTokRelayError rather than returning a partially trusted dict: a caller that
    forgot to check a flag must not be able to persist unvalidated browser output.
    """
    if not isinstance(payload, dict):
        raise TikTokRelayError(ERR_MALFORMED_RESPONSE, "evidence_not_an_object")

    wanted = product_identity(requested_url)
    if wanted is None:
        raise TikTokRelayError(ERR_HOST_NOT_SUPPORTED, requested_url)

    dropped = sorted(set(payload) - ALLOWED_EVIDENCE_KEYS)

    canonical = str(payload.get("canonical_url") or "").strip()
    if canonical and not identities_match(wanted, product_identity(canonical)):
        # The page identified itself as a DIFFERENT product. Storing it would attach one
        # listing's evidence to another product's draft — silent cross-contamination.
        raise TikTokRelayError(ERR_URL_MISMATCH, canonical[:200])

    clean: dict[str, Any] = {key: _redact(payload.get(key), MAX_FIELD_CHARS)
                             for key in _TEXT_KEYS}
    clean["page_text"] = _redact(payload.get("page_text"), MAX_PAGE_TEXT_CHARS)

    images: list[str] = []
    for candidate in (payload.get("images") or [])[: MAX_IMAGES * 4]:
        url = str(candidate or "").strip()
        if _IMAGE_HOST_RE.match(url) and url not in images:
            images.append(url)
        if len(images) >= MAX_IMAGES:
            break
    clean["images"] = images

    variants: list[str] = []
    for candidate in (payload.get("variant_labels") or [])[: MAX_VARIANTS * 4]:
        label = _redact(candidate, 120)
        if label and label not in variants:
            variants.append(label)
        if len(variants) >= MAX_VARIANTS:
            break
    clean["variant_labels"] = variants

    # AUTHENTICATED_DOM is forced first so every provenance row this lane writes begins
    # `TIKTOKSHOP_AUTHENTICATED_DOM…` — a reviewer can tell relayed evidence from
    # server-fetched evidence without reading code.
    methods = ["AUTHENTICATED_DOM"]
    for candidate in (payload.get("evidence_methods") or [])[:MAX_METHODS]:
        token = re.sub(r"[^A-Z0-9_]", "", str(candidate or "").upper())[:32]
        if token and token not in methods:
            methods.append(token)
    clean["evidence_methods"] = methods

    if not clean["title"] and not clean["description"]:
        raise TikTokRelayError(ERR_EMPTY_EVIDENCE, canonical or requested_url)

    clean["canonical_url"] = canonical or requested_url
    clean["dropped_keys"] = dropped
    return clean


def _raw_for_extractor(clean: dict[str, Any]) -> dict[str, Any]:
    """Shape sanitized evidence exactly like `tiktokshop_extraction_service.extract_raw`.

    Reusing that module's `normalize` / `propose_candidates` is the point: every safety rule
    already proven there — a pack size must be a real measurement present in the source, a
    merchandising label like "Standard" is never a size, ingredients and warnings come only
    from an explicitly labelled section, price is never model-supplied — applies identically
    to relayed evidence. A second parser here would be a second place for those rules to
    drift out of agreement.
    """
    raw: dict[str, Any] = {
        "images": clean["images"],
        "variant_labels": clean["variant_labels"],
        "evidence_methods": clean["evidence_methods"],
        "page_text": clean["page_text"],
    }
    for key in _TEXT_KEYS:
        if clean.get(key):
            raw[key] = clean[key]
    return raw


async def acquire_evidence(product_url: str, *,
                           timeout: float = RELAY_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Ask the extension for one product's evidence. Returns sanitized evidence only."""
    from agent.services.flow_client import get_flow_client

    def fail(code: str, detail: str = "") -> TikTokRelayError:
        return TikTokRelayError(code, detail, product_url=str(product_url or ""))

    identity = product_identity(product_url)
    if identity is None:
        raise fail(ERR_HOST_NOT_SUPPORTED, str(product_url)[:200])

    client = get_flow_client()
    if not client.connected:
        raise fail(ERR_EXTENSION_DISCONNECTED,
                   "BOSMAX Chrome extension is not connected to the agent")

    # Application-level correlation ON TOP of the bridge's own request id. The bridge id
    # only proves "this frame answers that frame"; this one proves the PAGE answered the
    # acquisition we asked for, so a late reply from a previous attempt cannot be adopted.
    evidence_request_id = str(uuid.uuid4())
    # `_send` is the established extension transport (its request-id correlation, timeout
    # and disconnect handling are the proven path used by every other extension verb). A
    # second bridge would duplicate all of it; the mission explicitly forbids that.
    reply = await client._send(  # noqa: SLF001 - documented shared transport
        WS_METHOD,
        {"evidence_request_id": evidence_request_id, "product_url": product_url},
        timeout=timeout,
    )

    if not isinstance(reply, dict):
        raise fail(ERR_MALFORMED_RESPONSE, type(reply).__name__)
    transport_error = str(reply.get("error") or "")
    if transport_error and "Timeout" in transport_error:
        raise fail(ERR_TIMEOUT, transport_error[:200])
    if transport_error == "Extension not connected":
        raise fail(ERR_EXTENSION_DISCONNECTED, transport_error)

    # The extension wraps handler output; `result` is the handler's own payload.
    payload = reply.get("result") if isinstance(reply.get("result"), dict) else reply
    echoed = str(payload.get("evidence_request_id") or "")
    if echoed and echoed != evidence_request_id:
        raise fail(ERR_CORRELATION_MISMATCH, echoed[:80])

    browser_error = str(payload.get("error") or transport_error or "")
    if payload.get("ok") is not True:
        if "SECURITY_CHECK" in browser_error:
            raise fail(ERR_SECURITY_CHECK_PRESENT,
                       str(payload.get("observed_url") or product_url)[:200])
        if "HOST_PERMISSION_MISSING" in browser_error:
            raise fail(ERR_HOST_PERMISSION_MISSING,
                       "chrome did not grant shop.tiktok.com / shop-my.tiktok.com "
                       "to the installed extension")
        if "NO_MATCHING_TAB" in browser_error:
            # Counts only — never a tab inventory. `tabs_with_readable_url` is what tells a
            # permission-blind browser apart from an empty one when Chrome reports the
            # permission as granted but still hides tab urls.
            raise fail(ERR_NO_MATCHING_TAB,
                       f"open_tiktok_tabs={payload.get('open_tiktok_tabs', 0)} "
                       f"host_permission_granted={payload.get('host_permission_granted')} "
                       f"total_tabs={payload.get('total_tabs')} "
                       f"tabs_with_readable_url={payload.get('tabs_with_readable_url')} "
                       f"visible_products={payload.get('visible_products')}")
        if "CONTENT_SCRIPT_UNREACHABLE" in browser_error:
            raise fail(ERR_CONTENT_SCRIPT_UNREACHABLE, browser_error[:200])
        if "NAVIGATED_AWAY" in browser_error:
            raise fail(ERR_TAB_NAVIGATED_AWAY,
                       str(payload.get("observed_url") or "")[:200])
        if "CORRELATION_MISMATCH" in browser_error:
            raise fail(ERR_CORRELATION_MISMATCH, browser_error[:200])
        if "EVIDENCE_EMPTY" in browser_error:
            raise fail(ERR_EMPTY_EVIDENCE, browser_error[:200])
        raise fail(ERR_MALFORMED_RESPONSE,
                   browser_error[:200] or "unknown_browser_failure")

    try:
        clean = sanitize_evidence(payload.get("evidence"), requested_url=product_url)
    except TikTokRelayError as exc:
        # Re-raise carrying the link, so a sanitation refusal is as actionable on screen as
        # a transport one.
        raise fail(exc.code, exc.detail) from exc
    clean["tab_id"] = payload.get("tab_id")
    clean["matched_tabs"] = payload.get("matched_tabs")
    clean["replayed"] = bool(payload.get("replayed"))
    clean["evidence_request_id"] = evidence_request_id
    return clean


WS_NAVIGATE_METHOD = "TIKTOK_NAVIGATE_PRODUCT_TAB"
NAVIGATE_TIMEOUT_SECONDS = 50.0

# Typed navigation outcome -> how the backend treats it. PAGE_READY is the only success;
# everything else raises a typed relay error the orchestrator ledgers per product.
# EXTRACTION_FAILED (empty read / not-yet-ready / unknown probe error) maps to the truthful
# EMPTY_EVIDENCE code — an act-then-retry state — NEVER to a delisted claim (bug B-597-01):
# a page we could not read is not a page the merchant removed.
_NAV_OUTCOME_TO_ERROR = {
    "SECURITY_CHECK_REQUIRES_HUMAN": ERR_SECURITY_CHECK_PRESENT,
    "PRODUCT_DELISTED": ERR_PRODUCT_DELISTED,
    "PRODUCT_ID_MISMATCH": ERR_PRODUCT_ID_MISMATCH,
    "NAVIGATION_TIMEOUT": ERR_TIMEOUT,
    "EXTRACTION_FAILED": ERR_EMPTY_EVIDENCE,
}


async def navigate_product_tab(product_url: str, *,
                               timeout: float = NAVIGATE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Drive the ONE dedicated evidence tab to a stored, id-verified product URL.

    The backend derives `expected_product_id` from the product's OWN stored link and hands it
    to the extension, so the id match is enforced on BOTH sides of the bridge: a swapped or
    mistyped URL can never move the tab to a different listing. Returns the extension's typed
    outcome on PAGE_READY; raises the mapped `TikTokRelayError` on every other outcome so a
    failed navigation is ledgered and skipped, never silently treated as acquired.
    """
    from agent.services.flow_client import get_flow_client

    def fail(code: str, detail: str = "") -> "TikTokRelayError":
        return TikTokRelayError(code, detail, product_url=str(product_url or ""))

    identity = product_identity(product_url)
    if identity is None:
        raise fail(ERR_HOST_NOT_SUPPORTED, str(product_url)[:200])
    expected_product_id = str(identity.get("product_id") or "")

    client = get_flow_client()
    if not client.connected:
        raise fail(ERR_EXTENSION_DISCONNECTED,
                   "BOSMAX Chrome extension is not connected to the agent")

    reply = await client._send(  # noqa: SLF001 - documented shared transport
        WS_NAVIGATE_METHOD,
        {"product_url": product_url, "expected_product_id": expected_product_id},
        timeout=timeout,
    )
    if not isinstance(reply, dict):
        raise fail(ERR_MALFORMED_RESPONSE, type(reply).__name__)
    transport_error = str(reply.get("error") or "")
    if transport_error and "Timeout" in transport_error:
        raise fail(ERR_TIMEOUT, transport_error[:200])
    if transport_error == "Extension not connected":
        raise fail(ERR_EXTENSION_DISCONNECTED, transport_error)

    payload = reply.get("result") if isinstance(reply.get("result"), dict) else reply
    outcome = str(payload.get("outcome") or "")
    if payload.get("ok") is True and outcome == "PAGE_READY":
        return {
            "outcome": outcome,
            "observed_product_id": payload.get("observed_product_id"),
            "observed_url": payload.get("observed_url"),
            "tab_id": payload.get("tab_id"),
        }
    mapped = _NAV_OUTCOME_TO_ERROR.get(outcome, ERR_MALFORMED_RESPONSE)
    detail = str(payload.get("error") or outcome or "unknown_navigation_failure")[:200]
    raise fail(mapped, detail)


WS_DIAGNOSE_METHOD = "TIKTOK_DIAGNOSE_EVIDENCE_TAB"
DIAGNOSE_TIMEOUT_SECONDS = 80.0

# Evidence-tab diagnostic classifications. Read-only: naming WHY the tab read empty so the
# right fix is chosen from proof instead of a guess.
DIAG_BACKGROUND_RENDERING_BLOCKED = "BACKGROUND_RENDERING_BLOCKED"
DIAG_EXTRACTOR_DEFECT = "EXTRACTOR_SELECTOR_OR_TIMING_DEFECT"
DIAG_SESSION_GATE = "SESSION_GATE_REQUIRES_HUMAN"
DIAG_PAGE_RENDER_TIMEOUT = "PAGE_RENDER_TIMEOUT"
DIAG_PRODUCT_READABLE = "PRODUCT_READABLE"
DIAG_SECURITY_CHECK = "SECURITY_CHECK_REQUIRES_HUMAN"
DIAG_PRODUCT_DELISTED = "PRODUCT_DELISTED"


async def diagnose_evidence_tab(product_url: str, *,
                                timeout: float = DIAGNOSE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Ask the extension to self-diagnose the dedicated tab (sanitized). Never raises on a
    non-ready page — the whole point is to classify WHY it is not ready. No provider call, no
    PI mutation."""
    from agent.services.flow_client import get_flow_client

    identity = product_identity(product_url)
    if identity is None:
        raise TikTokRelayError(ERR_HOST_NOT_SUPPORTED, str(product_url)[:200],
                               product_url=str(product_url or ""))
    client = get_flow_client()
    if not client.connected:
        raise TikTokRelayError(ERR_EXTENSION_DISCONNECTED,
                               "BOSMAX Chrome extension is not connected to the agent",
                               product_url=str(product_url or ""))
    reply = await client._send(  # noqa: SLF001 - documented shared transport
        WS_DIAGNOSE_METHOD,
        {"product_url": product_url, "expected_product_id": str(identity.get("product_id") or "")},
        timeout=timeout,
    )
    if not isinstance(reply, dict):
        raise TikTokRelayError(ERR_MALFORMED_RESPONSE, type(reply).__name__,
                               product_url=str(product_url or ""))
    payload = reply.get("result") if isinstance(reply.get("result"), dict) else reply
    return {"classification": classify_tab_diagnostic(payload), "diagnostic": payload}


def classify_tab_diagnostic(result: dict[str, Any]) -> str:
    """PURE classification from the sanitized diagnostic (testable without a browser).

    Decisive markers first (wall / removed / gate), then the background-vs-active comparison:
    a product that appears ONLY after activation is a background-render block; a product
    present but unread is an extractor defect; nothing readable after activation + settle is a
    render timeout — never a delisted claim."""
    bg = (result.get("background") or {}).get("content") or {}
    act = (result.get("active") or {}).get("content") or {}
    extraction = result.get("extraction") or {}

    if bg.get("security_check_marker") or act.get("security_check_marker"):
        return DIAG_SECURITY_CHECK
    if act.get("removed_listing_marker"):
        return DIAG_PRODUCT_DELISTED
    if act.get("login_marker") or act.get("region_gate_marker") or act.get("continue_in_app_marker"):
        return DIAG_SESSION_GATE

    bg_product = bool(bg.get("product_root_present"))
    act_product = bool(act.get("product_root_present"))
    ext_ok = bool(extraction.get("ok"))

    if act_product and ext_ok and not bg_product:
        return DIAG_BACKGROUND_RENDERING_BLOCKED
    if act_product and ext_ok and bg_product:
        return DIAG_PRODUCT_READABLE
    if act_product and not ext_ok:
        return DIAG_EXTRACTOR_DEFECT
    return DIAG_PAGE_RENDER_TIMEOUT


async def extract_product_via_browser(product_url: str, *,
                                      propose: bool = True,
                                      navigate: bool = False) -> dict[str, Any]:
    """Full result in the SAME shape `tiktokshop_extraction_service.extract_product` returns.

    Same keys, same normalizer, same provenance builder — so the recompute service treats a
    relayed acquisition and a direct fetch identically and cannot develop two code paths
    that disagree about what a field means.

    With `navigate=True` (the unattended bulk path) the dedicated evidence tab is driven to
    the product first, then the EXISTING reader acquires from that now-open tab. With
    `navigate=False` the historical operator-opened-tab path is preserved unchanged.
    """
    from agent.services import tiktokshop_extraction_service as tiktok

    nav = None
    if navigate:
        nav = await navigate_product_tab(product_url)
    clean = await acquire_evidence(product_url)
    raw = _raw_for_extractor(clean)
    source_url = clean.get("canonical_url") or product_url

    normalized = tiktok.normalize(raw, source_url=source_url)
    result = dict(normalized)
    result.update(tiktok.propose_candidates(normalized, raw) if propose
                  else {"candidates": {}, "candidate_status": "SKIPPED"})
    result["provenance"] = tiktok.build_provenance(result)
    result["field_provenance_overrides"] = tiktok.field_provenance_overrides(result)
    result["acquisition_mode"] = "AUTHENTICATED_BROWSER_RELAY"
    result["relay"] = {
        "tab_id": clean.get("tab_id"),
        "matched_tabs": clean.get("matched_tabs"),
        "replayed": clean.get("replayed"),
        "dropped_keys": clean.get("dropped_keys") or [],
        "evidence_request_id": clean.get("evidence_request_id"),
        "navigated": bool(nav),
        "navigation_outcome": (nav or {}).get("outcome"),
        "navigation_observed_product_id": (nav or {}).get("observed_product_id"),
    }
    return result
