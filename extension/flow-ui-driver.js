// flow-ui-driver.js — Owner-authorized CURRENT-UI driver (Phase 2, targeted).
//
// Scope (explicit Owner approval, BOSMAX_SEV0_VIDEO_PIPELINE_PHASED_CLOSURE):
//   * observe the current Flow view state (project vs video-detail/timeline);
//   * verify reference media are VISIBLY present before Block-1 submission;
//   * open the EXACT current video detail + timeline;
//   * Add Clip -> "Extend (Veo 3.1 - Lite)";
//   * insert ONLY the next block prompt into "What happens next?";
//   * submit exactly one Extend (live only with explicit confirm — the backend
//     kill-switch gates it);
//   * open the three-dot menu -> "Download Project".
//
// EVERY selector below is anchored on ACCESSIBLE NAMES captured live on
// 2026-07-12 (out/ui_contract/20260712_17*): no generated CSS classes, no
// nth-child, no screen coordinates. The Material icon ligature text prefixes
// the label (e.g. "addAdd Clip", "downloadDownload Project",
// "keyboard_double_arrow_rightExtend (Veo 3.1 - Lite)") — matching is done on
// the SUFFIX label. This file must never implement per-mode transports.
//
// It is a DRIVER ONLY: no retrieval authority, no correlation authority, no
// credit decisions — those live server-side.
(() => {
	"use strict";
	if (window.__FLOWUI_DRIVER_ACTIVE__) return; // re-injection guard (last wins)
	window.__FLOWUI_DRIVER_ACTIVE__ = true;

	const VERSION = "flowui-1.0.0-20260712";

	// ── captured accessible-name contract (single source of truth) ──────────
	const NAMES = {
		ADD_CLIP: "Add Clip",
		EXTEND_PREFIX: "Extend (", // "Extend (Veo 3.1 - Lite)" — model in parens
		EXTEND_PROMPT_PLACEHOLDER: "What happens next?",
		DETAIL_MORE: "More", // toolbar more_vert in video detail
		DOWNLOAD_PROJECT: "Download Project",
		BACK_TO_PROJECTS: "Back to projects", // proves DETAIL view
		SUBMIT_CREATE: "Create", // arrow_forwardCreate — the CREDIT submit
		COMPOSER_NEW: "What do you want to create?",
		EDIT_COMPOSER: "Describe your edits",
	};

	const vis = (el) => {
		if (!el) return false;
		const r = el.getBoundingClientRect();
		return r.width > 0 && r.height > 0;
	};
	const label = (el) =>
		((el.getAttribute && el.getAttribute("aria-label")) || el.textContent || "")
			.trim();

	function findByLabel(selector, want, { suffix = true } = {}) {
		const wantLc = want.toLowerCase();
		for (const el of document.querySelectorAll(selector)) {
			if (!vis(el)) continue;
			const l = label(el).toLowerCase();
			// icon ligature prefixes the label -> match by suffix/containment
			if (suffix ? l.endsWith(wantLc) || l.includes(wantLc) : l === wantLc) {
				return el;
			}
		}
		return null;
	}

	const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

	async function waitFor(fn, timeoutMs, stepMs = 250) {
		const t0 = Date.now();
		for (;;) {
			const v = fn();
			if (v) return v;
			if (Date.now() - t0 > timeoutMs) return null;
			await sleep(stepMs);
		}
	}

	// ── state observation ────────────────────────────────────────────────────
	function observeState() {
		const detail = findByLabel("button", NAMES.BACK_TO_PROJECTS);
		const addClip = findByLabel("button, [role=menuitem]", NAMES.ADD_CLIP);
		const extendItem = findByLabel("[role=menuitem], button", NAMES.EXTEND_PREFIX);
		const promptBox = Array.from(
			document.querySelectorAll('[contenteditable="true"], textarea, div[role="textbox"]'),
		).find((el) => vis(el) &&
			(el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.textContent || "")
				.includes(NAMES.EXTEND_PROMPT_PLACEHOLDER));
		const titleInput = document.querySelector('input[aria-label], input[type="text"]');
		// visible media thumbnails in the project grid (video/image tiles)
		const tiles = Array.from(document.querySelectorAll('div[role="button"], a'))
			.filter((el) => vis(el) && el.querySelector("img, video"));
		return {
			ok: true,
			driver_version: VERSION,
			url: location.href,
			view: detail ? "VIDEO_DETAIL" : "PROJECT",
			title: titleInput ? titleInput.value || null : null,
			has_add_clip: !!addClip,
			extend_menu_visible: !!extendItem,
			extend_prompt_visible: !!promptBox,
			visible_media_tiles: tiles.length,
		};
	}

	// media VISIBLY present check — the reference-first gate evidence.
	// A media id is considered visible when any rendered tile/img/video src or
	// data attribute carries it (Flow uses the media UUID in asset URLs).
	function verifyMediaVisible(mediaIds) {
		const html = document.documentElement.innerHTML;
		const results = {};
		for (const mid of mediaIds || []) {
			results[mid] = html.includes(mid);
		}
		const missing = Object.entries(results)
			.filter(([, v]) => !v)
			.map(([k]) => k);
		return {
			ok: missing.length === 0,
			driver_version: VERSION,
			checked: mediaIds || [],
			visible: results,
			missing,
			visible_count: (mediaIds || []).length - missing.length,
			expected_count: (mediaIds || []).length,
		};
	}

	// ── actions (all anchored on captured names; forbidden ones guarded) ────
	async function openVideoDetail(titleSubstr) {
		const want = String(titleSubstr || "").toLowerCase();
		const card = await waitFor(() => {
			for (const el of document.querySelectorAll('div[role="button"]')) {
				if (!vis(el)) continue;
				if (label(el).toLowerCase().includes(want)) return el;
			}
			return null;
		}, 8000);
		if (!card) return { ok: false, error: "VIDEO_CARD_NOT_FOUND", want: titleSubstr };
		card.click();
		const detail = await waitFor(
			() => findByLabel("button", NAMES.BACK_TO_PROJECTS), 10000);
		if (!detail) return { ok: false, error: "DETAIL_VIEW_NOT_CONFIRMED" };
		return { ok: true, state: observeState() };
	}

	async function addClipExtend(modelLabel) {
		const addBtn = await waitFor(
			() => findByLabel("button", NAMES.ADD_CLIP), 8000);
		if (!addBtn) return { ok: false, error: "ADD_CLIP_NOT_FOUND" };
		addBtn.click();
		const wantExtend = modelLabel
			? `Extend (${modelLabel})`.toLowerCase()
			: NAMES.EXTEND_PREFIX.toLowerCase();
		const item = await waitFor(() => {
			for (const el of document.querySelectorAll('[role="menuitem"], button')) {
				if (!vis(el)) continue;
				const l = label(el).toLowerCase();
				if (l.includes(wantExtend)) return el;
			}
			return null;
		}, 6000);
		if (!item) return { ok: false, error: "EXTEND_MENU_ITEM_NOT_FOUND",
			wanted: wantExtend };
		const itemLabel = label(item);
		item.click();
		const box = await waitFor(() => {
			const st = observeState();
			return st.extend_prompt_visible ? st : null;
		}, 8000);
		if (!box) return { ok: false, error: "EXTEND_PROMPT_NOT_VISIBLE" };
		return { ok: true, menu_item: itemLabel, state: box };
	}

	function extendPromptEl() {
		return Array.from(
			document.querySelectorAll('[contenteditable="true"], textarea, div[role="textbox"]'),
		).find((el) => vis(el) &&
			(el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.textContent || "")
				.includes(NAMES.EXTEND_PROMPT_PLACEHOLDER));
	}

	async function setExtendPrompt(text) {
		const el = await waitFor(extendPromptEl, 6000);
		if (!el) return { ok: false, error: "EXTEND_PROMPT_NOT_VISIBLE" };
		el.focus();
		// select-all + insertText produces framework-visible input events
		document.execCommand("selectAll", false, null);
		document.execCommand("insertText", false, String(text || ""));
		await sleep(300);
		const readBack = (el.value !== undefined ? el.value : el.textContent) || "";
		const okText = readBack.trim() === String(text || "").trim();
		return {
			ok: okText,
			error: okText ? null : "EXTEND_PROMPT_READBACK_MISMATCH",
			read_back: readBack.slice(0, 4000),
			length: readBack.length,
		};
	}

	async function submitExtend(confirm) {
		// CREDIT ACTION — double-guarded: backend kill-switch + explicit confirm.
		if (confirm !== true) {
			return { ok: false, error: "EXTEND_SUBMIT_CONFIRM_REQUIRED" };
		}
		const st = observeState();
		if (!st.extend_prompt_visible) {
			return { ok: false, error: "EXTEND_PROMPT_NOT_VISIBLE" };
		}
		// the submit is the composer arrow ("arrow_forwardCreate") in the extend state
		const btn = findByLabel("button", NAMES.SUBMIT_CREATE);
		if (!btn) return { ok: false, error: "EXTEND_SUBMIT_BUTTON_NOT_FOUND" };
		btn.click();
		await sleep(1500);
		return { ok: true, submitted: true, state: observeState() };
	}

	async function downloadProject() {
		// zero-credit: three-dot toolbar More -> Download Project (captured 2026-07-12;
		// produces a browser-side ZIP blob — the background captures the download).
		const more = await waitFor(() => {
			// prefer the DETAIL toolbar "More" (exact label), never nav "More options"
			for (const el of document.querySelectorAll("button")) {
				if (!vis(el)) continue;
				const l = label(el);
				if (/(^|\s|_vert)More$/.test(l) && !/options/i.test(l)) return el;
			}
			return null;
		}, 8000);
		if (!more) return { ok: false, error: "DETAIL_MORE_MENU_NOT_FOUND" };
		more.click();
		const item = await waitFor(
			() => findByLabel('[role="menuitem"], button', NAMES.DOWNLOAD_PROJECT), 6000);
		if (!item) return { ok: false, error: "DOWNLOAD_PROJECT_ITEM_NOT_FOUND" };
		item.click();
		return { ok: true, clicked: label(item) };
	}

	// ── verb dispatch ────────────────────────────────────────────────────────
	const VERBS = {
		FLOWUI_STATE: async () => observeState(),
		FLOWUI_VERIFY_MEDIA_VISIBLE: async (a) => verifyMediaVisible(a.media_ids),
		FLOWUI_OPEN_VIDEO: async (a) => openVideoDetail(a.title_substr),
		FLOWUI_ADD_CLIP_EXTEND: async (a) => addClipExtend(a.model_label),
		FLOWUI_SET_EXTEND_PROMPT: async (a) => setExtendPrompt(a.text),
		FLOWUI_SUBMIT_EXTEND: async (a) => submitExtend(a.confirm === true),
		FLOWUI_DOWNLOAD_PROJECT: async () => downloadProject(),
	};

	chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
		if (!msg || msg.type !== "FLOWUI" || !VERBS[msg.verb]) return false;
		Promise.resolve(VERBS[msg.verb](msg.args || {}))
			.then((res) => sendResponse(res))
			.catch((e) => sendResponse({ ok: false, error: "FLOWUI_DRIVER_ERROR",
				detail: String((e && e.message) || e).slice(0, 200) }));
		return true; // async response
	});
})();
