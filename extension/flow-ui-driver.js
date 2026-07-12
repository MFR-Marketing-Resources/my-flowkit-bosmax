// flow-ui-driver.js — Owner Phase-2B: composer-driven references, exact video id, Extend verbs.
(() => {
	"use strict";
	if (window.__FLOWUI_DRIVER_ACTIVE__) return;
	window.__FLOWUI_DRIVER_ACTIVE__ = true;

	const VERSION = "flowui-1.3.0-phase2d-20260712";

	const NAMES = {
		ADD_CLIP: "Add Clip",
		EXTEND_PREFIX: "Extend (",
		EXTEND_PROMPT_PLACEHOLDER: "What happens next?",
		DETAIL_MORE: "More",
		DOWNLOAD_PROJECT: "Download Project",
		BACK_TO_PROJECTS: "Back to projects",
		SUBMIT_CREATE: "Create",
		COMPOSER_NEW: "What do you want to create?",
		UPLOAD_MEDIA: "Upload media",
		COMPOSER_ADD: "add",
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

	function findComposerElement() {
		const candidates = Array.from(
			document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"]'),
		);
		const specific = candidates.find(
			(el) => el.getAttribute("aria-label") === "Editable text" && vis(el),
		);
		if (specific) return specific;
		const withPlaceholder = candidates.find((el) => {
			if (!vis(el)) return false;
			const text =
				el.textContent ||
				el.getAttribute("placeholder") ||
				el.getAttribute("data-placeholder") ||
				"";
			return text.includes(NAMES.COMPOSER_NEW);
		});
		if (withPlaceholder) return withPlaceholder;
		return candidates.find(vis) || null;
	}

	function composerAddButtonWithin(root) {
		if (!root || !root.querySelectorAll) return null;
		for (const el of root.querySelectorAll('button, [role="button"]')) {
			if (!vis(el)) continue;
			const l = label(el).toLowerCase();
			if (l === "add" || l.endsWith("add") || /\badd\b/.test(l)) return el;
		}
		return null;
	}

	/** Proven composer-reference panel: FIRST ancestor containing composer + add control. */
	function findComposerReferenceContainer(composer) {
		if (!composer) return null;
		let el = composer.parentElement;
		while (el && el !== document.body) {
			if (!el.contains(composer)) break;
			if (composerAddButtonWithin(el)) return el;
			el = el.parentElement;
		}
		return null;
	}

	const CONTAINER_EVIDENCE =
		"composer_panel:editable_text_plus_add_control_ancestor";

	function isInsideProjectVideoCard(node) {
		let p = node;
		while (p && p !== document.body) {
			if (p.getAttribute && p.getAttribute("role") === "button") {
				const t = (p.textContent || "").toLowerCase();
				if (t.includes("play_circle") || /\d{1,2}:\d{2}/.test(t)) return true;
			}
			p = p.parentElement;
		}
		return false;
	}

	function extractMediaTokensFromThumb(node) {
		const tokens = [];
		if (!node) return tokens;
		if (node.src) tokens.push(String(node.src));
		if (node.currentSrc) tokens.push(String(node.currentSrc));
		if (node.getAttribute) {
			for (const a of node.getAttributeNames()) {
				const v = node.getAttribute(a);
				if (v) tokens.push(String(v));
			}
		}
		return tokens;
	}

	function thumbMatchesExpectedId(node, expectedId) {
		const want = String(expectedId || "");
		if (!want) return false;
		return extractMediaTokensFromThumb(node).some((t) => t.includes(want));
	}

	function collectComposerReferenceThumbnails(composer) {
		const container = findComposerReferenceContainer(composer);
		if (!container) return { container: null, thumbs: [] };
		const thumbs = [];
		const seen = new Set();
		const nodes = container.querySelectorAll("img, video, picture");
		for (const node of nodes) {
			if (!vis(node) || seen.has(node)) continue;
			if (isInsideProjectVideoCard(node)) continue;
			const rect = node.getBoundingClientRect();
			if (rect.width < 24 || rect.height < 24) continue;
			seen.add(node);
			thumbs.push({ node, rect });
		}
		thumbs.sort((a, b) => a.rect.left - b.rect.left || a.rect.top - b.rect.top);
		return { container, thumbs };
	}

	function nodeCarriesMediaId(node, mediaId) {
		return thumbMatchesExpectedId(node, mediaId);
	}

	function composerReferenceState() {
		const composer = findComposerElement();
		if (!composer) {
			return {
				ok: false,
				error: "COMPOSER_NOT_FOUND",
				composer_found: false,
				thumbnails: [],
				actual_total_count: 0,
			};
		}
		const { container, thumbs } = collectComposerReferenceThumbnails(composer);
		if (!container) {
			return {
				ok: false,
				error: "COMPOSER_REFERENCE_CONTAINER_NOT_FOUND",
				composer_found: true,
				thumbnails: [],
				actual_total_count: 0,
			};
		}
		const mapped = thumbs.map((t, index) => ({
			index,
			ids: extractMediaTokensFromThumb(t.node),
		}));
		return {
			ok: true,
			composer_found: true,
			driver_version: VERSION,
			thumbnails: mapped,
			actual_total_count: thumbs.length,
			expected_count: null,
			container_evidence: CONTAINER_EVIDENCE,
			scope: "composer_reference_container",
		};
	}

	function verifyComposerMediaVisible(mediaIds) {
		const composer = findComposerElement();
		if (!composer) {
			return { ok: false, error: "COMPOSER_NOT_FOUND", expected_count: (mediaIds || []).length };
		}
		const { container, thumbs } = collectComposerReferenceThumbnails(composer);
		if (!container) {
			return {
				ok: false,
				error: "COMPOSER_REFERENCE_CONTAINER_NOT_FOUND",
				expected_count: (mediaIds || []).length,
			};
		}
		const expected = (mediaIds || []).map(String);
		const expected_count = expected.length;
		const actual_total_count = thumbs.length;
		const observed_ids = [];
		const matched = {};
		const duplicate_ids = [];
		for (const mid of expected) matched[mid] = 0;

		for (const t of thumbs) {
			let hit = null;
			for (const mid of expected) {
				if (thumbMatchesExpectedId(t.node, mid)) {
					hit = mid;
					break;
				}
			}
			if (hit) {
				matched[hit] += 1;
				if (matched[hit] > 1) duplicate_ids.push(hit);
				observed_ids.push(hit);
			} else {
				observed_ids.push(
					(extractMediaTokensFromThumb(t.node)[0] || "unknown").slice(0, 80),
				);
			}
		}

		const missing = expected.filter((mid) => matched[mid] < 1);
		const unexpected_ids = [];
		for (let i = 0; i < thumbs.length; i++) {
			const t = thumbs[i];
			const matchedAny = expected.some((mid) => thumbMatchesExpectedId(t.node, mid));
			if (!matchedAny) {
				unexpected_ids.push(observed_ids[i]);
			}
		}

		let order_ok = true;
		if (expected_count > 1) {
			const orderHits = [];
			for (const t of thumbs) {
				for (const mid of expected) {
					if (thumbMatchesExpectedId(t.node, mid)) {
						orderHits.push(mid);
						break;
					}
				}
			}
			order_ok =
				orderHits.length === expected_count &&
				orderHits.every((mid, i) => mid === expected[i]);
		}

		const count_ok = actual_total_count === expected_count;
		const ok =
			count_ok &&
			missing.length === 0 &&
			unexpected_ids.length === 0 &&
			duplicate_ids.length === 0 &&
			order_ok;

		return {
			ok,
			driver_version: VERSION,
			scope: "composer_reference_container",
			container_evidence: CONTAINER_EVIDENCE,
			checked: expected,
			observed_ids,
			expected_count,
			actual_total_count,
			missing,
			unexpected_ids,
			duplicate_ids,
			order_ok,
			visible: Object.fromEntries(expected.map((m) => [m, matched[m] >= 1])),
		};
	}

	async function clearComposerReferences() {
		const composer = findComposerElement();
		if (!composer) return { ok: false, error: "COMPOSER_NOT_FOUND" };
		const { container } = collectComposerReferenceThumbnails(composer);
		if (!container) {
			return { ok: false, error: "COMPOSER_REFERENCE_CONTAINER_NOT_FOUND" };
		}
		let cleared = 0;
		for (let pass = 0; pass < 8; pass++) {
			const { thumbs } = collectComposerReferenceThumbnails(composer);
			if (!thumbs.length) {
				return {
					ok: true,
					cleared,
					actual_total_count: 0,
					container_evidence: CONTAINER_EVIDENCE,
				};
			}
			let clicked = false;
			for (const btn of container.querySelectorAll(
				'button, [role="button"], [role="menuitem"]',
			)) {
				if (!vis(btn)) continue;
				const l = label(btn).toLowerCase();
				if (
					!/^(remove|delete|close|clear)/.test(l) &&
					!l.includes("remove") &&
					!l.includes("close")
				) {
					continue;
				}
				btn.click();
				clicked = true;
				cleared += 1;
				await sleep(400);
				break;
			}
			if (!clicked) break;
		}
		const left = composerReferenceState().actual_total_count;
		if (left > 0) {
			return {
				ok: false,
				error: "STALE_REFERENCE_CLEAR_FAILED",
				actual_total_count: left,
				cleared,
			};
		}
		return {
			ok: true,
			cleared,
			actual_total_count: 0,
			container_evidence: CONTAINER_EVIDENCE,
		};
	}

	async function verifyComposerZero() {
		const cleared = await clearComposerReferences();
		if (!cleared.ok && cleared.error !== "STALE_REFERENCE_CLEAR_FAILED") {
			return cleared;
		}
		const state = composerReferenceState();
		if (state.actual_total_count !== 0) {
			return {
				ok: false,
				error: "STALE_REFERENCES_PRESENT",
				actual_total_count: state.actual_total_count,
			};
		}
		return {
			ok: true,
			actual_total_count: 0,
			container_evidence: CONTAINER_EVIDENCE,
			scope: "composer_reference_container",
		};
	}

	async function openComposerAttachUpload() {
		const composer = findComposerElement();
		if (!composer) return { ok: false, error: "COMPOSER_NOT_FOUND" };
		const addBtn = findByLabel("button", NAMES.COMPOSER_ADD) ||
			Array.from(document.querySelectorAll("button")).find((el) => {
				if (!vis(el)) return false;
				const l = label(el).toLowerCase();
				return l === "add" || l.endsWith("add");
			});
		if (!addBtn) return { ok: false, error: "COMPOSER_ATTACH_CONTROL_NOT_FOUND" };
		addBtn.click();
		await sleep(400);
		const upload = await waitFor(
			() => findByLabel('[role="menuitem"], button', NAMES.UPLOAD_MEDIA),
			5000,
		);
		if (!upload) return { ok: false, error: "UPLOAD_MEDIA_NOT_FOUND" };
		upload.click();
		return { ok: true, ready_for_file_chooser: true, menu_item: label(upload) };
	}

	async function setComposerPrompt(text) {
		const el = findComposerElement();
		if (!el) return { ok: false, error: "COMPOSER_NOT_FOUND" };
		el.focus();
		document.execCommand("selectAll", false, null);
		document.execCommand("insertText", false, String(text || ""));
		await sleep(300);
		const readBack = (el.value !== undefined ? el.value : el.textContent) || "";
		const okText = readBack.trim() === String(text || "").trim();
		return {
			ok: okText,
			error: okText ? null : "COMPOSER_PROMPT_READBACK_MISMATCH",
			read_back: readBack.slice(0, 4000),
			length: readBack.length,
		};
	}

	async function submitComposerCreate(confirm, interceptOnly) {
		if (confirm !== true) {
			return { ok: false, error: "COMPOSER_SUBMIT_CONFIRM_REQUIRED" };
		}
		const composer = findComposerElement();
		if (!composer) return { ok: false, error: "COMPOSER_NOT_FOUND" };
		const btn =
			findByLabel("button", NAMES.SUBMIT_CREATE) ||
			Array.from(document.querySelectorAll("button")).find((el) => {
				if (!vis(el)) return false;
				const l = label(el).toLowerCase();
				return l.includes("create") && (l.includes("arrow") || l.endsWith("create"));
			});
		if (!btn) return { ok: false, error: "COMPOSER_SUBMIT_BUTTON_NOT_FOUND" };
		if (interceptOnly === true) {
			return {
				ok: true,
				intercept_only: true,
				would_invoke: label(btn),
				submit_control: "composer_create",
			};
		}
		btn.click();
		await sleep(1500);
		return { ok: true, submitted: true, clicked: label(btn), state: observeState() };
	}

	function subtreeContainsId(root, mediaResourceId) {
		if (!root || !mediaResourceId) return false;
		const want = String(mediaResourceId);
		if (root.querySelectorAll) {
			for (const node of root.querySelectorAll(
				"img, video, source, [data-media-id], [href]",
			)) {
				if (nodeCarriesMediaId(node, want)) return true;
			}
		}
		const html = root.innerHTML || "";
		return html.includes(want);
	}

	function readProjectIdFromUrl() {
		const m = String(location.href || "").match(/\/project\/([a-f0-9-]{36})/i);
		return m ? m[1] : null;
	}

	async function openVideoByMediaResourceId(mediaResourceId, expectedProjectId) {
		const want = String(mediaResourceId || "").trim();
		if (!want) {
			return { ok: false, error: "CURRENT_VIDEO_NOT_FOUND", detail: "empty id" };
		}
		const card = await waitFor(() => {
			for (const el of document.querySelectorAll('div[role="button"]')) {
				if (!vis(el)) continue;
				if (!subtreeContainsId(el, want)) continue;
				return el;
			}
			return null;
		}, 10000);
		if (!card) {
			return { ok: false, error: "CURRENT_VIDEO_NOT_FOUND", want };
		}
		card.click();
		const detail = await waitFor(
			() => findByLabel("button", NAMES.BACK_TO_PROJECTS),
			10000,
		);
		if (!detail) return { ok: false, error: "DETAIL_VIEW_NOT_CONFIRMED" };
		const detailRoot = detail.closest("main") || detail.parentElement || document.body;
		if (!subtreeContainsId(detailRoot, want)) {
			return { ok: false, error: "CURRENT_VIDEO_IDENTITY_MISMATCH", want };
		}
		const projectId = readProjectIdFromUrl();
		if (expectedProjectId && projectId && projectId !== expectedProjectId) {
			return {
				ok: false,
				error: "CURRENT_VIDEO_PROJECT_MISMATCH",
				expected: expectedProjectId,
				actual: projectId,
			};
		}
		return {
			ok: true,
			media_resource_id: want,
			parent_open_identity_type: "media_resource_id",
			project_id: projectId,
			state: observeState(),
		};
	}

	function observeState() {
		const detail = findByLabel("button", NAMES.BACK_TO_PROJECTS);
		const addClip = findByLabel("button, [role=menuitem]", NAMES.ADD_CLIP);
		const extendItem = findByLabel("[role=menuitem], button", NAMES.EXTEND_PREFIX);
		const promptBox = Array.from(
			document.querySelectorAll('[contenteditable="true"], textarea, div[role="textbox"]'),
		).find(
			(el) =>
				vis(el) &&
				(el.getAttribute("aria-label") ||
					el.getAttribute("placeholder") ||
					el.textContent ||
					""
				).includes(NAMES.EXTEND_PROMPT_PLACEHOLDER),
		);
		const titleInput = document.querySelector('input[aria-label], input[type="text"]');
		return {
			ok: true,
			driver_version: VERSION,
			url: location.href,
			view: detail ? "VIDEO_DETAIL" : "PROJECT",
			title: titleInput ? titleInput.value || null : null,
			has_add_clip: !!addClip,
			extend_menu_visible: !!extendItem,
			extend_prompt_visible: !!promptBox,
			composer_found: !!findComposerElement(),
		};
	}

	async function addClipExtend(modelLabel) {
		const addBtn = await waitFor(() => findByLabel("button", NAMES.ADD_CLIP), 8000);
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
		if (!item) {
			return { ok: false, error: "EXTEND_MENU_ITEM_NOT_FOUND", wanted: wantExtend };
		}
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
		).find(
			(el) =>
				vis(el) &&
				(el.getAttribute("aria-label") ||
					el.getAttribute("placeholder") ||
					el.textContent ||
					""
				).includes(NAMES.EXTEND_PROMPT_PLACEHOLDER),
		);
	}

	async function setExtendPrompt(text) {
		const el = await waitFor(extendPromptEl, 6000);
		if (!el) return { ok: false, error: "EXTEND_PROMPT_NOT_VISIBLE" };
		el.focus();
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
		if (confirm !== true) {
			return { ok: false, error: "EXTEND_SUBMIT_CONFIRM_REQUIRED" };
		}
		const st = observeState();
		if (!st.extend_prompt_visible) {
			return { ok: false, error: "EXTEND_PROMPT_NOT_VISIBLE" };
		}
		const btn = findByLabel("button", NAMES.SUBMIT_CREATE);
		if (!btn) return { ok: false, error: "EXTEND_SUBMIT_BUTTON_NOT_FOUND" };
		btn.click();
		await sleep(1500);
		return { ok: true, submitted: true, state: observeState() };
	}

	async function downloadProject() {
		const more = await waitFor(() => {
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
			() => findByLabel('[role="menuitem"], button', NAMES.DOWNLOAD_PROJECT),
			6000,
		);
		if (!item) return { ok: false, error: "DOWNLOAD_PROJECT_ITEM_NOT_FOUND" };
		item.click();
		return { ok: true, clicked: label(item) };
	}

	const VERBS = {
		FLOWUI_STATE: async () => observeState(),
		FLOWUI_COMPOSER_REFERENCE_STATE: async () => composerReferenceState(),
		FLOWUI_VERIFY_COMPOSER_MEDIA: async (a) => verifyComposerMediaVisible(a.media_ids),
		FLOWUI_VERIFY_COMPOSER_ZERO: async () => verifyComposerZero(),
		FLOWUI_CLEAR_COMPOSER_REFERENCES: async () => clearComposerReferences(),
		FLOWUI_OPEN_COMPOSER_UPLOAD: async () => openComposerAttachUpload(),
		FLOWUI_SET_COMPOSER_PROMPT: async (a) => setComposerPrompt(a.text),
		FLOWUI_SUBMIT_COMPOSER_CREATE: async (a) =>
			submitComposerCreate(a.confirm === true, a.intercept_only === true),
		FLOWUI_VERIFY_MEDIA_VISIBLE: async (a) => verifyComposerMediaVisible(a.media_ids),
		FLOWUI_OPEN_VIDEO: async (a) =>
			openVideoByMediaResourceId(
				a.parent_media_resource_id || a.parent_media_operation_id,
				a.expected_project_id,
			),
		FLOWUI_ADD_CLIP_EXTEND: async (a) => addClipExtend(a.model_label),
		FLOWUI_SET_EXTEND_PROMPT: async (a) => setExtendPrompt(a.text),
		FLOWUI_SUBMIT_EXTEND: async (a) => submitExtend(a.confirm === true),
		FLOWUI_DOWNLOAD_PROJECT: async () => downloadProject(),
	};

	chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
		if (!msg || msg.type !== "FLOWUI" || !VERBS[msg.verb]) return false;
		Promise.resolve(VERBS[msg.verb](msg.args || {}))
			.then((res) => sendResponse(res))
			.catch((e) =>
				sendResponse({
					ok: false,
					error: "FLOWUI_DRIVER_ERROR",
					detail: String((e && e.message) || e).slice(0, 200),
				}),
			);
		return true;
	});
})();