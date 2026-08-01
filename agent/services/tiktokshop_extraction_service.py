"""TikTok Shop source-first extraction — replaces TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED.

    stored TikTok/source URL
      -> DOM or embedded structured JSON extraction
      -> deterministic normalization
      -> exact variant resolution
      -> field-scoped provenance
      -> configured DeepSeek text_assist
      -> review-required candidates

THE RULE THAT SHAPES EVERYTHING: EXTRACTED != PROPOSED
Two kinds of field, handled differently and never mixed:

  * EXTRACTED fields are copied from the page and nothing else. Price, commission, size,
    ingredients and warnings are in this class. If the page does not state them they stay
    ABSENT. A model is never asked to supply them, because a plausible-sounding warning or
    ingredient list is indistinguishable from a real one once it is stored, and this
    catalogue feeds product claims.
  * PROPOSED fields (benefits, usage, target customer, packaging prose) may be drafted by
    the configured text_assist lane FROM THE EXTRACTED TEXT ONLY, and they land as
    review-required candidates. They are never auto-accepted and never approved here.

Vision is NOT required and is not called. The mission allows it only as an optional
fallback, and every field this module produces is obtainable from the page source, so
adding an image model would spend tokens to re-derive what was already read.

WHY THE SIZE RULES LOOK FUSSY
A TikTok listing's variant label is frequently a merchandising word ("Standard", "Default",
"1 Set"), not a measurement. Accepting one as `size_or_volume` writes a fake pack size into
the product truth that later drives scale locks in prompts — this is the same class of
defect as the roll-on/25ml incident. So a size is accepted ONLY when it is a real quantity
WITH a unit AND that exact string is present in the fetched source.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
from html import unescape
from typing import Any
from urllib.parse import urlparse

# ── network safety ───────────────────────────────────────────────────────────
ERR_URL_MISSING = "TIKTOKSHOP_SOURCE_URL_MISSING"
ERR_URL_SCHEME = "TIKTOKSHOP_URL_SCHEME_NOT_ALLOWED"
ERR_URL_HOST = "TIKTOKSHOP_URL_HOST_NOT_ALLOWED"
ERR_URL_PRIVATE = "TIKTOKSHOP_URL_RESOLVES_TO_PRIVATE_ADDRESS"
ERR_FETCH_FAILED = "TIKTOKSHOP_FETCH_FAILED"
ERR_CONTENT_TYPE = "TIKTOKSHOP_UNSUPPORTED_CONTENT_TYPE"
ERR_TOO_LARGE = "TIKTOKSHOP_RESPONSE_TOO_LARGE"
ERR_TOO_MANY_REDIRECTS = "TIKTOKSHOP_TOO_MANY_REDIRECTS"
ERR_NO_EVIDENCE = "TIKTOKSHOP_NO_EXTRACTABLE_EVIDENCE"

# Only TikTok's own hosts. An open fetcher pointed at an arbitrary URL is an SSRF
# primitive; restricting the host is what stops "import this product" from becoming
# "GET anything the agent host can reach".
ALLOWED_HOST_SUFFIXES = (".tiktok.com", "tiktok.com", ".tiktokshop.com", "tiktokshop.com",
                         ".tiktokglobalshop.com", "tiktokglobalshop.com")
MAX_REDIRECTS = 3
FETCH_TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ALLOWED_CONTENT_TYPES = ("text/html", "application/json", "application/xhtml+xml",
                         "text/plain")


class TikTokShopExtractionError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def _host_allowed(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    return any(host == suffix.lstrip(".") or host.endswith(suffix)
               for suffix in ALLOWED_HOST_SUFFIXES)


def _resolves_public(host: str) -> bool:
    """Every resolved address must be publicly routable.

    Checked per hop, not once: a redirect to an internal host, or a DNS name that
    resolves to 127.0.0.1 / 169.254.169.254 / a VPC address, is the standard way an
    allowlisted fetcher still ends up reading cloud metadata.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast
                or address.is_unspecified):
            return False
    return True


def validate_source_url(url: str) -> str:
    if not str(url or "").strip():
        raise TikTokShopExtractionError(ERR_URL_MISSING)
    parsed = urlparse(str(url).strip())
    if parsed.scheme != "https":
        raise TikTokShopExtractionError(ERR_URL_SCHEME, parsed.scheme or "(none)")
    if not _host_allowed(parsed.hostname or ""):
        raise TikTokShopExtractionError(ERR_URL_HOST, parsed.hostname or "(none)")
    if not _resolves_public(parsed.hostname or ""):
        raise TikTokShopExtractionError(ERR_URL_PRIVATE, parsed.hostname or "(none)")
    return parsed.geturl()


def fetch_source(url: str) -> dict[str, Any]:
    """Fetch the listing with every hop revalidated. Never follows redirects blindly."""
    import httpx

    current = validate_source_url(url)
    with httpx.Client(follow_redirects=False, timeout=FETCH_TIMEOUT_SECONDS) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                response = client.get(current, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; BOSMAX-ProductIntake/1.0)",
                    "Accept": "text/html,application/json;q=0.9",
                })
            except Exception as exc:  # noqa: BLE001
                raise TikTokShopExtractionError(ERR_FETCH_FAILED, str(exc)) from exc
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location") or ""
                if not location:
                    raise TikTokShopExtractionError(ERR_FETCH_FAILED, "redirect_no_location")
                # revalidate the TARGET, not just the original url
                current = validate_source_url(str(httpx.URL(current).join(location)))
                continue
            if response.status_code >= 400:
                raise TikTokShopExtractionError(
                    ERR_FETCH_FAILED, f"http_{response.status_code}")
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
            if content_type and not any(content_type.startswith(allowed)
                                        for allowed in ALLOWED_CONTENT_TYPES):
                raise TikTokShopExtractionError(ERR_CONTENT_TYPE, content_type)
            body = response.content
            if len(body) > MAX_RESPONSE_BYTES:
                raise TikTokShopExtractionError(ERR_TOO_LARGE, str(len(body)))
            return {"final_url": current, "status_code": response.status_code,
                    "content_type": content_type,
                    "text": body.decode(response.encoding or "utf-8", errors="replace")}
    raise TikTokShopExtractionError(ERR_TOO_MANY_REDIRECTS, current)


# ── extraction ───────────────────────────────────────────────────────────────
_JSONLD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL)
_EMBEDDED_RE = re.compile(
    r"<script[^>]*id=[\"'](?:__UNIVERSAL_DATA_FOR_REHYDRATION__|__NEXT_DATA__|"
    r"__MODERN_ROUTER_DATA__)[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']([^\"']+)[\"'][^>]+content=[\"']([^\"']*)[\"']",
    re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _json_blobs(html: str) -> list[Any]:
    blobs: list[Any] = []
    for pattern in (_JSONLD_RE, _EMBEDDED_RE):
        for raw in pattern.findall(html or ""):
            try:
                blobs.append(json.loads(unescape(raw.strip())))
            except (ValueError, TypeError):
                continue
    return blobs


def _meta_map(html: str) -> dict[str, str]:
    return {key.strip().lower(): unescape(value).strip()
            for key, value in _META_RE.findall(html or "")}


def _clean(value: Any) -> str:
    text = unescape(_TAG_RE.sub(" ", str(value or "")))
    return " ".join(text.split()).strip()


def extract_raw(page_text: str) -> dict[str, Any]:
    """Pull whatever the page actually states. No inference, no defaults."""
    raw: dict[str, Any] = {"images": [], "variant_labels": [], "evidence_methods": []}
    meta = _meta_map(page_text)

    for blob in _json_blobs(page_text):
        for node in _walk(blob):
            node_type = str(node.get("@type") or "").lower()
            if node_type == "product" or ("name" in node and "offers" in node):
                raw.setdefault("title", _clean(node.get("name")))
                raw.setdefault("description", _clean(node.get("description")))
                brand = node.get("brand")
                if isinstance(brand, dict):
                    raw.setdefault("brand", _clean(brand.get("name")))
                elif brand:
                    raw.setdefault("brand", _clean(brand))
                image = node.get("image")
                for candidate in (image if isinstance(image, list) else [image]):
                    if isinstance(candidate, str) and candidate.startswith("http"):
                        raw["images"].append(candidate)
                offers = node.get("offers")
                for offer in _walk(offers) if offers is not None else ():
                    if "price" in offer:
                        raw.setdefault("price_text", _clean(offer.get("price")))
                        raw.setdefault("currency", _clean(offer.get("priceCurrency")))
                if "JSONLD" not in raw["evidence_methods"]:
                    raw["evidence_methods"].append("JSONLD")
            # variant / SKU labels wherever the embedded payload puts them
            for key in ("sale_prop_value", "specification", "variantName", "sku_name",
                        "salePropValue"):
                if key in node and isinstance(node[key], str):
                    label = _clean(node[key])
                    if label and label not in raw["variant_labels"]:
                        raw["variant_labels"].append(label)

    if meta:
        raw.setdefault("title", _clean(meta.get("og:title") or meta.get("twitter:title")))
        raw.setdefault("description", _clean(
            meta.get("og:description") or meta.get("description")))
        image = meta.get("og:image") or meta.get("twitter:image")
        if image and image.startswith("http"):
            raw["images"].append(image)
        if meta.get("product:price:amount"):
            raw.setdefault("price_text", _clean(meta["product:price:amount"]))
            raw.setdefault("currency", _clean(meta.get("product:price:currency")))
        if "META" not in raw["evidence_methods"]:
            raw["evidence_methods"].append("META")

    raw["images"] = list(dict.fromkeys(raw["images"]))
    raw["page_text"] = _clean(page_text)[:20000]
    raw = {k: v for k, v in raw.items() if v not in (None, "")}
    raw.setdefault("evidence_methods", [])
    return raw


# ── normalization ────────────────────────────────────────────────────────────
# A real measurement: a number with a recognised unit. `1 Set`, `Standard`, `Default`
# and `One Size` are merchandising labels and are NOT sizes.
_SIZE_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s?(ml|mL|ML|l|L|g|G|kg|KG|mg|MG|gram|grams|gm|litre|liter|"
    r"oz|fl\.?\s?oz|cm|mm|pcs|piece|pieces|sheet|sheets|tablet|tablets|capsule|capsules)\b")
_NON_SIZE_LABELS = {"standard", "default", "one size", "normal", "regular", "basic",
                    "free size", "no size", "n/a", "na", "-", "set", "1 set"}


def normalize_size(candidate: Any, *, source_text: str) -> tuple[str | None, str]:
    """Accept a pack size ONLY when it is a real quantity present in the source.

    Returns (value_or_None, reason). The reason is recorded so a rejected size is an
    auditable decision rather than a silent absence.
    """
    text = _clean(candidate)
    if not text:
        return None, "ABSENT_IN_SOURCE"
    if text.strip().lower() in _NON_SIZE_LABELS:
        return None, "REJECTED_NOT_A_MEASUREMENT"
    match = _SIZE_RE.search(text)
    if not match:
        return None, "REJECTED_NO_UNIT"
    measured = match.group(0)
    # source-first: the exact measurement must appear in what we actually fetched
    haystack = _clean(source_text).lower().replace(" ", "")
    if measured.lower().replace(" ", "") not in haystack:
        return None, "REJECTED_NOT_SUPPORTED_BY_SOURCE"
    return measured, "EXTRACTED"


def resolve_variant(raw: dict[str, Any]) -> tuple[str | None, str]:
    """Exactly one variant, or none.

    With several variant labels and nothing pinning one of them, picking any is a guess
    that becomes the product's pack truth. Ambiguity is reported instead.
    """
    labels = [label for label in raw.get("variant_labels") or []
              if _clean(label).lower() not in _NON_SIZE_LABELS]
    if not labels:
        return None, "NO_VARIANT_STATED"
    if len(labels) > 1:
        return None, "AMBIGUOUS_MULTIPLE_VARIANTS"
    return labels[0], "EXACT_VARIANT_RESOLVED"


def _money(value: Any) -> float | None:
    text = re.sub(r"[^\d.]", "", str(value or "").replace(",", ""))
    try:
        return float(text) if text else None
    except ValueError:
        return None


# Fields that may ONLY be copied from the page. A model never supplies these.
EXTRACT_ONLY_FIELDS = ("price", "currency", "commission_rate", "commission_amount",
                       "size_or_volume", "ingredients_text", "warnings_text",
                       "image_url")
# Fields the text_assist lane may DRAFT from extracted text, as review-required.
# `usp_list` (not `usp_json`) because PROMOTION_MAP maps the SOURCE key `usp_list` onto the
# `usp_json` column; emitting the column name here would silently drop every USP.
PROPOSABLE_FIELDS = ("product_description", "benefits_text", "usp_list", "usage_text",
                     "target_customer_text", "package_notes", "product_form_factor",
                     "packaging_description")

# ── deterministic materials / warnings ───────────────────────────────────────
# Labelled sections only. A model is never asked for these: a fabricated warning or
# ingredient list is indistinguishable from a real one once stored, and this catalogue
# feeds product claims. Malay and English labels, because the live catalogue is both.
_INGREDIENT_LABELS = ("ingredients", "ingredient", "composition", "bahan-bahan", "bahan",
                      "komposisi", "kandungan", "material", "materials", "components")
_WARNING_LABELS = ("warning", "warnings", "caution", "cautions", "precaution",
                   "precautions", "amaran", "perhatian", "awas", "peringatan")
# Stop at the next labelled section so one block does not swallow the rest of the page.
_SECTION_STOP = ("ingredients", "ingredient", "composition", "bahan", "komposisi",
                 "kandungan", "material", "components", "warning", "caution",
                 "precaution", "amaran", "perhatian", "awas", "peringatan", "usage",
                 "how to use", "cara guna", "direction", "directions", "storage",
                 "penyimpanan", "shipping", "delivery", "size", "saiz", "weight",
                 "expiry", "manufactured", "brand", "description")
_MAX_SECTION_CHARS = 600


def extract_labelled_section(text: str, labels: tuple[str, ...]) -> str | None:
    """Return the text following `Label:` up to the next known section label.

    Deliberately narrow: it requires an explicit label followed by a separator. Guessing
    which sentence "looks like" an ingredient list is how invented ingredients get stored.
    """
    haystack = _clean(text)
    if not haystack:
        return None
    for label in labels:
        match = re.search(rf"(?<![A-Za-z]){re.escape(label)}\s*[:：]\s*(.+)",
                          haystack, re.IGNORECASE)
        if not match:
            continue
        tail = match.group(1)[:_MAX_SECTION_CHARS]
        cut = len(tail)
        for stop in _SECTION_STOP:
            stop_match = re.search(rf"(?<![A-Za-z]){re.escape(stop)}\s*[:：]", tail,
                                   re.IGNORECASE)
            if stop_match:
                cut = min(cut, stop_match.start())
        value = tail[:cut].strip(" .,;:-–—|/")
        if len(value) >= 3:
            return value
    return None


def normalize(raw: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    """Deterministic. Same page in, same fields out — no model involved."""
    source_text = " ".join(str(raw.get(key) or "") for key in
                           ("title", "description", "page_text"))
    variant, variant_reason = resolve_variant(raw)
    size_source = variant if variant else (raw.get("title") or "")
    size, size_reason = normalize_size(size_source, source_text=source_text)
    if size is None and raw.get("description"):
        size, size_reason = normalize_size(raw.get("description"),
                                           source_text=source_text)

    fields: dict[str, Any] = {}
    if raw.get("title"):
        fields["raw_product_title"] = raw["title"]
    if raw.get("brand"):
        fields["brand"] = raw["brand"]
    if raw.get("description"):
        fields["product_description"] = raw["description"]
    price = _money(raw.get("price_text"))
    if price is not None:
        fields["price"] = price
        if raw.get("currency"):
            fields["currency"] = str(raw["currency"]).upper()[:8]
    if size:
        fields["size_or_volume"] = size
    if raw.get("images"):
        fields["image_url"] = raw["images"][0]

    # Materials / components and warnings: deterministic, labelled-section only.
    unresolved: dict[str, str] = {}
    materials = extract_labelled_section(source_text, _INGREDIENT_LABELS)
    if materials:
        fields["materials_text"] = materials
    else:
        unresolved["ingredients_text"] = "NOT_STATED_IN_SOURCE"
    warnings = extract_labelled_section(source_text, _WARNING_LABELS)
    if warnings:
        fields["warnings_text"] = warnings
    else:
        unresolved["warnings_text"] = "NOT_STATED_IN_SOURCE"
    if not size:
        unresolved["size_or_volume"] = size_reason
    if variant is None:
        unresolved["variant"] = variant_reason

    return {
        "fields": fields,
        # An explicit "we looked and the page does not say" — distinct from "we never
        # looked". Without it, an absent warning is indistinguishable from an unchecked
        # one, and a reviewer cannot tell which fields still need a human.
        "unresolved": unresolved,
        "images": raw.get("images") or [],
        "variant": variant,
        "variant_resolution": variant_reason,
        "size_resolution": size_reason,
        "evidence_methods": raw.get("evidence_methods") or [],
        "source_url": source_url,
        # deliberately NOT populated by extraction unless the page stated them
        "absent_extract_only_fields": [name for name in EXTRACT_ONLY_FIELDS
                                       if name not in fields],
    }


# ── review-required candidates ───────────────────────────────────────────────
CANDIDATE_SYSTEM = (
    "You draft REVIEW-REQUIRED product copy candidates for a Malaysian e-commerce "
    "catalogue, strictly from supplied marketplace listing text.\n"
    "ABSOLUTE RULES:\n"
    "1. Use ONLY facts present in the supplied text. Invent nothing.\n"
    "2. NEVER output ingredients, warnings, safety advice, dosages, dimensions, weights, "
    "pack sizes, prices or health/medical claims. If the text contains them, still omit "
    "them - another system handles those verbatim.\n"
    "3. If the text does not support a field, omit that field entirely. An omitted field "
    "is correct; a guessed one is a defect.\n"
    "4. Return ONLY a JSON object with any of these keys: "
    + ", ".join(PROPOSABLE_FIELDS) + ".\n"
    "5. Every value must be a plain string. Keep each under 400 characters."
)


def build_candidate_brief(normalized: dict[str, Any], raw: dict[str, Any]) -> str:
    return json.dumps({
        "listing_title": raw.get("title"),
        "listing_description": raw.get("description"),
        "brand": raw.get("brand"),
        "resolved_variant": normalized.get("variant"),
        "listing_text_excerpt": (raw.get("page_text") or "")[:4000],
    }, ensure_ascii=False, indent=2)


def propose_candidates(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """One text_assist call. Fail-SOFT: extraction already succeeded without it.

    A provider outage must not throw away a perfectly good deterministic extraction, so an
    unconfigured or failing lane downgrades to "no candidates" rather than failing the
    import.
    """
    from agent.services import ai_copy_provider_adapter as adapter

    try:
        proposed = adapter.complete_json(CANDIDATE_SYSTEM,
                                         build_candidate_brief(normalized, raw))
    except adapter.AICopyProviderNotConfigured:
        return {"candidates": {}, "candidate_status": "PROVIDER_NOT_CONFIGURED"}
    except Exception as exc:  # noqa: BLE001
        return {"candidates": {}, "candidate_status": f"PROVIDER_CALL_FAILED:{exc}"[:300]}

    candidates: dict[str, str] = {}
    for field in PROPOSABLE_FIELDS:
        value = proposed.get(field)
        if isinstance(value, list):
            value = "\n".join(str(v).strip() for v in value if str(v).strip())
        text = _clean(value)
        if text:
            candidates[field] = text
    # A model that returned an extract-only field is ignored for that field, loudly.
    refused = sorted(set(proposed) & set(EXTRACT_ONLY_FIELDS))
    return {"candidates": candidates, "candidate_status": "REVIEW_REQUIRED",
            "refused_model_fields": refused}


def extract_product(url: str, *, page_text: str | None = None,
                    propose: bool = True) -> dict[str, Any]:
    """The whole lane. `page_text` lets tests drive it without any network call."""
    if page_text is None:
        fetched = fetch_source(url)
        page_text = fetched["text"]
        final_url = fetched["final_url"]
    else:
        final_url = str(url or "").strip()
    raw = extract_raw(page_text)
    if not raw.get("title") and not raw.get("description"):
        raise TikTokShopExtractionError(ERR_NO_EVIDENCE, final_url)
    normalized = normalize(raw, source_url=final_url)
    result = dict(normalized)
    result.update(propose_candidates(normalized, raw) if propose
                  else {"candidates": {}, "candidate_status": "SKIPPED"})
    result["provenance"] = build_provenance(result)
    result["field_provenance_overrides"] = field_provenance_overrides(result)
    return result


# Extracted source key -> the review-draft COLUMN that PROMOTION_MAP will write it to.
# Provenance rows are keyed by target column, so an override map keyed by the source name
# would never match and the exact method would be silently dropped.
_SOURCE_KEY_TO_TARGET = {
    "product_description": "product_description",
    "size_or_volume": "size_or_volume",
    "materials_text": "ingredients_text",
    "warnings_text": "warnings_text",
    "package_notes": "package_notes",
    "packaging_description": "packaging_description",
    "product_form_factor": "product_form_factor",
    "benefits_text": "benefits_json",
    "usp_list": "usp_json",
    "usage_text": "usage_text",
    "target_customer_text": "target_customer_text",
}


def field_provenance_overrides(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Per-field evidence identity for the intake seam, keyed by target column.

    This is what stops the whole draft collapsing to one lane-wide `TIKTOKSHOP_LINK`
    label. `price` read from JSON-LD and a description scraped from an OpenGraph tag are
    different strengths of evidence and a reviewer has to be able to tell them apart.
    """
    methods = "+".join(result.get("evidence_methods") or []) or "DOM"
    overrides: dict[str, dict[str, str]] = {}
    for source_key in (result.get("fields") or {}):
        target = _SOURCE_KEY_TO_TARGET.get(source_key)
        if not target:
            continue
        overrides[target] = {
            "source_type": "IMPORTED_TIKTOKSHOP",
            "evidence_kind": "IMPORTED_MARKETPLACE_LINK",
            "extraction_method": f"TIKTOKSHOP_{methods}",
            "verification_status": "PENDING_REVIEW",
        }
    # Materials and warnings are read from an explicitly LABELLED section, which is a
    # stronger, more auditable claim than "it appeared somewhere on the page".
    for source_key, target in (("materials_text", "ingredients_text"),
                               ("warnings_text", "warnings_text")):
        if source_key in (result.get("fields") or {}):
            overrides[target]["extraction_method"] = "TIKTOKSHOP_LABELLED_SECTION"
    return overrides


def build_provenance(result: dict[str, Any]) -> list[dict[str, str]]:
    """Field-scoped provenance: every value says where it came from and how strong it is.

    Extracted values and model proposals get DIFFERENT extraction methods so a reviewer can
    tell "the page says this" apart from "a model suggested this" without reading code.
    """
    source_url = result.get("source_url") or ""
    methods = "+".join(result.get("evidence_methods") or []) or "DOM"
    rows: list[dict[str, str]] = []
    for field in (result.get("fields") or {}):
        rows.append({
            "field_name": field, "source_url": source_url,
            "source_type": "IMPORTED_TIKTOKSHOP",
            "evidence_kind": "IMPORTED_MARKETPLACE_LINK",
            "extraction_method": f"TIKTOKSHOP_{methods}",
            "verification_status": "PENDING_REVIEW",
        })
    for field in (result.get("candidates") or {}):
        rows.append({
            "field_name": field, "source_url": source_url,
            "source_type": "IMPORTED_TIKTOKSHOP",
            "evidence_kind": "MODEL_PROPOSED_CANDIDATE",
            "extraction_method": "TIKTOKSHOP_TEXT_ASSIST",
            "verification_status": "PENDING_REVIEW",
        })
    return rows
