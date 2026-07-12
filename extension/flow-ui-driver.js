// flow-ui-driver.js — Owner Phase-2B: composer-driven references, exact video id, Extend verbs.
(() => {
	"use strict";
	if (window.__FLOWUI_DRIVER_ACTIVE__) return;
	window.__FLOWUI_DRIVER_ACTIVE__ = true;

	const VERSION = "flowui-1.1.0-phase2b-20260712";

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

	function collectComposerContextRoots(composer, depth = 5) {
		const roots = [];
		const seen = new Set();
		let cur = composer;
		for (let i = 0; i < depth && cur; i++) {
			if (!seen.has(cur)) {
				seen.add(cur);
				roots.push(cur);
			}
			cur = cur.parentElement;
		}
		return roots;
	}

	function nodeCarriesMediaId(node, mediaId) {
		const mid = String(mediaId || "");
		if (!mid) return false;
		const attrs = [];
		if (node.src) attrs.push(node.src);
		if (node.currentSrc) attrs.push(node.currentSrc);
		if (node.getAttribute) {
			for (const a of node.getAttributeNames()) {
				attrs.push(node.getAttribute(a));
			}
		}
		return attrs.some((v) => v && String(v).includes(mid));
	}

	function collectComposerReferenceThumbnails(composer) {
		const roots = collectComposerContextRoots(composer, 6);
		const composerRect = composer.getBoundingClientRect();
		const thumbs = [];
		const seen = new Set();
		for (const root of roots) {
			if (!root.querySelectorAll) continue;
			for (const node of root.querySelectorAll("img, video, picture, canvas")) {
				if (!vis(node) || seen.has(node)) continue;
				const rect = node.getBoundingClientRect();
				if (rect.width < 20 || rect.height < 20) continue;
				const hNear =
					rect.right >= composerRect.left - 180 &&
					rect.left <= composerRect.right + 240;
				const vNear =
					Math.abs(
						rect.top + rect.height / 2 -
							(composerRect.top + composerRect.height / 2),
					) <= Math.max(composerRect.height * 3, 280);
				if (!hNear || !vNear) continue;
				seen.add(node);
				thumbs.push({ node, rect });
			}
		}
		thumbs.sort((a, b) => a.rect.left - b.rect.left || a.rect.top - b.rect.top);
		return thumbs;
	}

	function composerReferenceState() {
		const composer = findComposerElement();
		if (!composer) {
			return {
				ok: false,
				error: "COMPOSER_NOT_FOUND",
				composer_found: false,
				thumbnails: [],
				count: 0,
			};
		}
		const thumbs = collectComposerReferenceThumbnails(composer);
		const mapped = thumbs.map((t, index) => {
			const ids = [];
			for (const attr of ["src", "data-media-id", "data-asset-id"]) {
				const v = t.node.getAttribute && t.node.getAttribute(attr);
				if (v) ids.push(v);
			}
			if (t.node.src) ids.push(t.node.src);
			return { index, ids };
		});
		return {
			ok: true,
			composer_found: true,
			driver_version: VERSION,
			thumbnails: mapped,
			count: thumbs.length,
			scope: "composer_reference_container",
		};
	}

	function verifyComposerMediaVisible(mediaIds) {
		const state = composerReferenceState();
		if (!state.ok) return { ...state, expected_count: (mediaIds || []).length };
		const ids = mediaIds || [];
		const thumbs = collectComposerReferenceThumbnails(findComposerElement());
		const results = {};
		const order = [];
		for (const mid of ids) {
			const hit = thumbs.find((t) => nodeCarriesMediaId(t.node, mid));
			results[mid] = Boolean(hit);
			if (hit) order.push(mid);
		}
		const missing = Object.entries(results)
			.filter(([, v]) => !v)
			.map(([k]) => k);
		let orderOk = true;
		if (ids.length > 1 && order.length === ids.length) {
			orderOk = ids.every((mid, i) => order[i] === mid);
		}
		return {
			ok: missing.length === 0 && orderOk,
			driver_version: VERSION,
			scope: "composer_reference_container",
			checked: ids,
			visible: results,
			missing,
			order_ok: orderOk,
			visible_count: ids.length - missing.length,
			expected_count: ids.length,
			composer_thumbnail_count: state.count,
		};
	}

	async function clearComposerReferences() {
		const composer = findComposerElement();
		if (!composer) return { ok: false, error: "COMPOSER_NOT_FOUND" };
		const roots = collectComposerContextRoots(composer, 6);
		let cleared = 0;
		for (let pass = 0; pass < 8; pass++) {
			let clicked = false;
			for (const root of roots) {
				for (const btn of root.querySelectorAll(
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
				if (clicked) break;
			}
			const left = composerReferenceState().count;
			if (left === 0) {
				return { ok: true, cleared, count: 0, scope: "composer_reference_container" };
			}
			if (!clicked) break;
		}
		const remaining = composerReferenceState().count;
		if (remaining > 0) {
			return {
				ok: false,
				error: "STALE_REFERENCE_CLEAR_FAILED",
				remaining,
				cleared,
			};
		}
		return { ok: true, cleared, count: 0 };
	}

	async function verifyComposerZero() {
		const cleared = await clearComposerReferences();
		if (!cleared.ok && cleared.error !== "STALE_REFERENCE_CLEAR_FAILED") {
			return cleared;
		}
		const state = composerReferenceState();
		if (state.count !== 0) {
			return {
				ok: false,
				error: "STALE_REFERENCES_PRESENT",
				composer_thumbnail_count: state.count,
			};
		}
		return { ok: true, composer_thumbnail_count: 0, scope: "composer_reference_container" };
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

	function subtreeContainsId(root, mediaOperationId) {
		if (!root || !mediaOperationId) return false;
		const want = String(mediaOperationId);
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

	async function openVideoByMediaId(mediaOperationId, expectedProjectId) {
		const want = String(mediaOperationId || "").trim();
		if (!want) return { ok: false, error: "CURRENT_VIDEO_NOT_FOUND", detail: "empty id" };
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
			media_operation_id: want,
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
		FLOWUI_VERIFY_MEDIA_VISIBLE: async (a) => verifyComposerMediaVisible(a.media_ids),
		FLOWUI_OPEN_VIDEO: async (a) =>
			openVideoByMediaId(a.parent_media_operation_id, a.expected_project_id),
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