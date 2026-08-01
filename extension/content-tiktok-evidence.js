// Sanitized product-evidence reader for an ALREADY-AUTHENTICATED TikTok Shop tab.
//
// WHY THIS FILE EXISTS
// The server-side fetcher (agent/services/tiktokshop_extraction_service.py) receives
// TikTok's ~5.6KB "Security Check" shell for every product URL — an identical byte count
// across DIFFERENT products, which is what proved it is a static bot wall rather than thin
// content. The operator's own browser is already past that wall, so the listing is readable
// there and nowhere else. This script reads what the operator can already see and hands it
// back through the extension bridge.
//
// WHAT IT IS NOT
// It is not a CAPTCHA solver and must never become one. When the security wall is on screen
// it reports SECURITY_CHECK_PRESENT and stops; a human clears it, then the operator presses
// Retry. Automating that check would be both a contract violation and the exact behaviour
// TikTok is entitled to block.
//
// THE TRANSMISSION ALLOWLIST IS THE WHOLE SECURITY MODEL
// This script runs inside an authenticated session, so "read the page" and "read the
// account" are one keystroke apart. It therefore builds an explicit, closed object of
// product facts and returns THAT — it never serialises the document, and it never reads
// document.cookie, localStorage, sessionStorage, IndexedDB or any request header. Those
// APIs are not referenced anywhere below, on purpose: a reviewer can grep this file for
// `cookie` / `Storage` and get zero hits, which is a stronger guarantee than a promise in a
// comment. The backend re-applies the same allowlist (tiktokshop_browser_relay.py) so a
// tampered content script still cannot widen what gets stored.
(() => {
	"use strict";

	// Only the two hosts the mission authorises. The manifest already restricts injection;
	// this is the second, independent check so a manifest edit alone cannot widen reach.
	const ALLOWED_HOSTS = new Set(["shop.tiktok.com", "shop-my.tiktok.com"]);

	if (!ALLOWED_HOSTS.has(location.hostname)) return;
	// Top document only. A product page embeds ad and player frames; letting a subframe
	// answer would let unrelated third-party content impersonate the listing.
	if (window.top !== window) return;
	if (window.__BOSMAX_TIKTOK_EVIDENCE_READY__) return;
	window.__BOSMAX_TIKTOK_EVIDENCE_READY__ = true;

	const MAX_TEXT = 20000;
	const MAX_FIELD = 4000;
	const MAX_IMAGES = 12;
	const MAX_VARIANTS = 24;

	// Same markers the server uses, so "still walled" means the same thing on both sides.
	const SECURITY_MARKERS = [
		"oec-ttweb-captcha",
		"captcha/index.js",
		"verify to continue",
		"drag the puzzle piece",
		"slide to verify",
	];

	const clean = (value) =>
		String(value ?? "")
			.replace(/\s+/g, " ")
			.trim()
			.slice(0, MAX_FIELD);

	function isSecurityChallenge() {
		const title = (document.title || "").toLowerCase();
		if (title === "security check" || title.includes("verify to continue")) return true;
		// A visible captcha container. Checked for VISIBILITY rather than presence: TikTok
		// leaves an empty captcha mount in the DOM of pages that were never challenged, and
		// treating that as a wall would make every healthy page look blocked forever.
		const mounts = document.querySelectorAll(
			"[id*='captcha'],[class*='captcha'],[id*='verify-bar'],[class*='secsdk']",
		);
		for (const mount of mounts) {
			const rect = mount.getBoundingClientRect?.();
			if (rect && rect.width > 40 && rect.height > 40) return true;
		}
		for (const script of document.querySelectorAll("script[src]")) {
			const src = (script.getAttribute("src") || "").toLowerCase();
			if (SECURITY_MARKERS.some((marker) => src.includes(marker))) return true;
		}
		return false;
	}

	function jsonBlobs() {
		const blobs = [];
		const nodes = document.querySelectorAll(
			"script[type='application/ld+json'],script#__UNIVERSAL_DATA_FOR_REHYDRATION__," +
				"script#__NEXT_DATA__,script#__MODERN_ROUTER_DATA__",
		);
		for (const node of nodes) {
			const text = node.textContent || "";
			// Bounded: a rehydration payload can be megabytes, and we only mine a handful of
			// scalar fields out of it.
			if (!text || text.length > 2_000_000) continue;
			try {
				blobs.push(JSON.parse(text));
			} catch {
				/* a payload we cannot parse is simply not evidence */
			}
		}
		return blobs;
	}

	function* walk(node, depth = 0) {
		if (depth > 12 || node === null || typeof node !== "object") return;
		if (Array.isArray(node)) {
			for (const item of node) yield* walk(item, depth + 1);
			return;
		}
		yield node;
		for (const value of Object.values(node)) yield* walk(value, depth + 1);
	}

	function fromStructuredData() {
		const found = { images: [], variant_labels: [], methods: [] };
		for (const blob of jsonBlobs()) {
			for (const node of walk(blob)) {
				const type = String(node["@type"] || "").toLowerCase();
				if (type === "product" || (node.name && node.offers)) {
					found.title ||= clean(node.name);
					found.description ||= clean(node.description);
					const brand = node.brand;
					found.brand ||= clean(
						brand && typeof brand === "object" ? brand.name : brand,
					);
					const image = node.image;
					for (const candidate of Array.isArray(image) ? image : [image]) {
						if (typeof candidate === "string" && candidate.startsWith("http")) {
							found.images.push(candidate);
						}
					}
					for (const offer of walk(node.offers)) {
						if (offer && offer.price !== undefined) {
							found.price_text ||= clean(offer.price);
							found.currency ||= clean(offer.priceCurrency);
						}
					}
					if (!found.methods.includes("JSONLD")) found.methods.push("JSONLD");
				}
				for (const key of [
					"sale_prop_value",
					"salePropValue",
					"specification",
					"variantName",
					"sku_name",
				]) {
					if (typeof node[key] === "string") {
						const label = clean(node[key]);
						if (label && !found.variant_labels.includes(label)) {
							found.variant_labels.push(label);
						}
					}
				}
			}
		}
		return found;
	}

	function fromMetaTags() {
		const read = (selector) =>
			clean(document.querySelector(selector)?.getAttribute("content"));
		const meta = {
			title: read("meta[property='og:title']") || read("meta[name='twitter:title']"),
			description:
				read("meta[property='og:description']") || read("meta[name='description']"),
			image: read("meta[property='og:image']") || read("meta[name='twitter:image']"),
			price_text: read("meta[property='product:price:amount']"),
			currency: read("meta[property='product:price:currency']"),
		};
		return meta;
	}

	// The narrowest element that still contains the listing, with chrome removed. Sending
	// document.body would ship the recommendation rail, the seller's other products and the
	// account menu — "unrelated page content" that the mission forbids transmitting and that
	// would also poison the server's labelled-section parser with a neighbouring product's
	// ingredient list.
	function productRegionText() {
		const candidates = [
			document.querySelector("[class*='product-detail']"),
			document.querySelector("[data-e2e*='product-detail']"),
			document.querySelector("main"),
			document.querySelector("article"),
			document.body,
		].filter(Boolean);

		for (const root of candidates) {
			const clone = root.cloneNode(true);
			for (const junk of clone.querySelectorAll(
				"script,style,noscript,iframe,svg,nav,header,footer,aside," +
					"[role='navigation'],[role='banner'],[role='contentinfo'],[class*='recommend']," +
					"[class*='related'],[class*='comment'],[class*='review-list'],[class*='footer']," +
					"[class*='header'],[class*='nav-']",
			)) {
				junk.remove();
			}
			const text = clean(clone.innerText || clone.textContent || "").slice(0, MAX_TEXT);
			if (text.length >= 40) return text;
		}
		return "";
	}

	function visibleTitle() {
		for (const selector of ["h1", "[data-e2e*='title']", "[class*='product-title']"]) {
			const text = clean(document.querySelector(selector)?.textContent);
			if (text) return text;
		}
		return "";
	}

	// Only images served by TikTok's own CDNs. An arbitrary <img> on the page can be an ad
	// or a tracking pixel, and storing one as the product image would put third-party
	// content into the catalogue.
	const IMAGE_HOST_RE = /^https:\/\/[\w.-]*(tiktokcdn|tiktokcdn-us|ibyteimg|byteimg)\.com\//i;

	function productImages() {
		const urls = [];
		const push = (value) => {
			const url = String(value || "").split(" ")[0];
			if (IMAGE_HOST_RE.test(url) && !urls.includes(url)) urls.push(url);
		};
		for (const img of document.querySelectorAll("img")) {
			const rect = img.getBoundingClientRect?.();
			// Skip icons and pixels: a 16px sprite is chrome, not the product.
			if (rect && (rect.width < 80 || rect.height < 80)) continue;
			push(img.getAttribute("src"));
			push(img.getAttribute("data-src"));
		}
		return urls.slice(0, MAX_IMAGES);
	}

	// Variant chips as the shopper sees them. Kept as LABELS only — the server decides
	// whether a label is a real measurement, and refuses merchandising words like
	// "Standard" so they can never become a stored pack size.
	function variantLabels() {
		const labels = [];
		const nodes = document.querySelectorAll(
			"[class*='sku'] button,[class*='sku'] [role='button'],[class*='sale-prop'] *," +
				"[data-e2e*='sku'] button,[class*='variant'] button",
		);
		for (const node of nodes) {
			const text = clean(node.textContent);
			if (text && text.length <= 80 && !labels.includes(text)) labels.push(text);
			if (labels.length >= MAX_VARIANTS) break;
		}
		return labels;
	}

	// The ONE object that ever leaves this page. Adding a key here is the only way to widen
	// what is transmitted, and the backend rejects keys it does not know.
	function collectEvidence() {
		const structured = fromStructuredData();
		const meta = fromMetaTags();
		const methods = [...structured.methods];
		const title = structured.title || meta.title || visibleTitle();
		const description = structured.description || meta.description || "";
		const pageText = productRegionText();

		if (meta.title || meta.description) methods.push("META");
		if (pageText) methods.push("AUTHENTICATED_DOM");

		const images = [...structured.images, meta.image, ...productImages()]
			.filter((url) => typeof url === "string" && url.startsWith("http"))
			.filter((url, index, all) => all.indexOf(url) === index)
			.slice(0, MAX_IMAGES);

		return {
			canonical_url:
				clean(document.querySelector("link[rel='canonical']")?.getAttribute("href")) ||
				location.origin + location.pathname,
			title: clean(title),
			description: clean(description),
			brand: clean(structured.brand),
			price_text: clean(structured.price_text || meta.price_text),
			currency: clean(structured.currency || meta.currency),
			variant_labels: [...structured.variant_labels, ...variantLabels()]
				.filter((label, index, all) => all.indexOf(label) === index)
				.slice(0, MAX_VARIANTS),
			images,
			page_text: pageText,
			evidence_methods: [...new Set(methods)],
		};
	}

	chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
		if (!message || message.type !== "TIKTOK_COLLECT_PRODUCT_EVIDENCE") return undefined;
		// Only our own background worker may ask. A page script cannot forge this — but an
		// explicit check keeps the trust boundary readable rather than implied.
		if (sender?.id && sender.id !== chrome.runtime.id) return undefined;

		// Echoed verbatim so the backend can prove the payload answers the request it made
		// and not an earlier one that arrived late.
		const requestId = String(message.evidence_request_id || "");
		try {
			if (isSecurityChallenge()) {
				sendResponse({
					ok: false,
					evidence_request_id: requestId,
					error: "TIKTOK_SECURITY_CHECK_PRESENT",
					observed_url: location.origin + location.pathname,
				});
				return true;
			}
			const evidence = collectEvidence();
			const hasEvidence = Boolean(evidence.title || evidence.description);
			sendResponse({
				ok: hasEvidence,
				evidence_request_id: requestId,
				error: hasEvidence ? null : "TIKTOK_EVIDENCE_EMPTY",
				observed_url: location.origin + location.pathname,
				evidence,
			});
		} catch (error) {
			sendResponse({
				ok: false,
				evidence_request_id: requestId,
				error: `TIKTOK_EVIDENCE_COLLECTION_FAILED:${String(error?.message || error).slice(0, 200)}`,
				observed_url: location.origin + location.pathname,
			});
		}
		return true;
	});
})();
