/**
 * Google Flow UI Contract V2 — readiness proof model.
 *
 * Governing SOP: docs/BOSMAX_GOOGLE_FLOW_OPERATOR_SOP_FOR_CODEX_V2_UI_CONTRACT.md
 * Contract id:   V2_UPLOAD_SETTINGS_PROMPT_GENERATE
 *
 * This is a PURE, side-effect-free evaluator. It takes a V2 diagnostic object
 * (DOM-observed signals) and returns the readiness decision with per-area
 * proofs and a precise primary blocker. It does NOT click anything and does NOT
 * read the DOM — the content script produces the diagnostic; this module judges
 * it. Keeping it pure makes every V2 readiness rule unit-testable without a live
 * Google Flow tab.
 *
 * Hard rules encoded here (from the V2 SOP):
 *   - Frames / Ingredients buttons are NOT required for editor readiness.
 *   - `subMode` inferred from Start/End markers is synthetic and is NEVER proof.
 *   - `visibleUploadSlots` alone is a WEAK signal and never passes upload proof.
 *   - Upload proof requires a STRONG signal (asset bound to prompt/composer).
 *   - A visible wrong/image model (e.g. Nano Banana) FAILS HARD.
 *   - A hidden/UNKNOWN model may SOFT-PASS only with strong settings proof.
 *   - If Save is visible it must be clicked + persisted; else persist-by-state.
 *   - Generate must be ENABLED (verified, not clicked during UAT).
 */

const GFV2_CONTRACT = "V2_UPLOAD_SETTINGS_PROMPT_GENERATE";

const GFV2_BLOCKERS = Object.freeze({
	EDITOR_NOT_READY: "GFV2_EDITOR_NOT_READY",
	UPLOAD_MEDIA_NOT_FOUND: "GFV2_UPLOAD_MEDIA_NOT_FOUND",
	ASSET_NOT_BOUND_TO_PROMPT: "GFV2_ASSET_NOT_BOUND_TO_PROMPT",
	SETTINGS_PANEL_NOT_FOUND: "GFV2_SETTINGS_PANEL_NOT_FOUND",
	RATIO_9_16_NOT_CONFIRMED: "GFV2_RATIO_9_16_NOT_CONFIRMED",
	COUNT_1X_NOT_CONFIRMED: "GFV2_COUNT_1X_NOT_CONFIRMED",
	VISIBLE_WRONG_MODEL: "GFV2_VISIBLE_WRONG_MODEL",
	SETTINGS_NOT_PERSISTED: "GFV2_SETTINGS_NOT_PERSISTED",
	PROMPT_FIELD_NOT_FOUND: "GFV2_PROMPT_FIELD_NOT_FOUND",
	PROMPT_NOT_ACCEPTED: "GFV2_PROMPT_NOT_ACCEPTED",
	GENERATE_BUTTON_NOT_ENABLED: "GFV2_GENERATE_BUTTON_NOT_ENABLED",
});

function _bool(value) {
	return value === true;
}

// Classify the *visible* model. The only correct family for V2 video is Veo.
// Anything else visible (image models such as Nano Banana / Imagen) is WRONG and
// must fail hard. An empty / "UNKNOWN" / hidden model is "hidden".
function classifyGoogleFlowV2Model(diagnostic) {
	const visible = _bool(diagnostic.model_visible);
	const canon = String(
		diagnostic.model_canonical || diagnostic.model || "",
	)
		.trim()
		.toLowerCase();
	if (!visible || !canon || canon === "unknown") {
		return { state: "hidden", canonical: canon || null };
	}
	if (/veo/.test(canon)) {
		return {
			state: "correct",
			canonical: canon,
			veoLite: /lite/.test(canon) || _bool(diagnostic.model_veo_lite_confirmed),
		};
	}
	// Visible but not Veo → wrong/image model for a video job.
	return { state: "wrong", canonical: canon };
}

// A. Editor proof — Flow session/editor surface is usable. Frames/Ingredients
//    buttons and the synthetic Video/Frames string are explicitly NOT required.
function evaluateEditorProof(d) {
	const ok = Boolean(
		_bool(d.flow_tab_found) &&
			_bool(d.editor_surface_present) &&
			_bool(d.content_script_alive) &&
			!_bool(d.login_blocker) &&
			_bool(d.composer_present),
	);
	return {
		ok,
		// Recorded only as a weak/diagnostic signal; never a gate.
		frames_button_present: _bool(d.frames_button_present),
		ingredients_button_present: _bool(d.ingredients_button_present),
		submode_inferred_synthetic: String(d.subMode_source || "") === "inferred",
	};
}

// B. Upload proof — STRONG signals only. visibleUploadSlots / "Image" body text /
//    side-panel categories are weak and cannot pass on their own.
function evaluateUploadProof(d) {
	const strong = Boolean(
		_bool(d.add_to_prompt_completed) ||
			_bool(d.asset_preview_in_prompt) ||
			_bool(d.media_attached) ||
			_bool(d.asset_card_bound_to_prompt) ||
			_bool(d.prompt_attachment_chip_present),
	);
	const weakOnly =
		!strong &&
		Boolean(
			(Array.isArray(d.visibleUploadSlots) &&
				d.visibleUploadSlots.length > 0) ||
				_bool(d.body_includes_image) ||
				_bool(d.side_panel_asset_categories),
		);
	return { ok: strong, strong, weak_signal_only: weakOnly };
}

// C. Settings proof — panel opened, 9:16 + 1x confirmed, model handled, persisted.
function evaluateSettingsProof(d) {
	const panelOpened = _bool(d.settings_panel_opened);
	const ratioOk = _bool(d.ratio_9_16_confirmed);
	const countOk = _bool(d.count_1x_confirmed);
	const model = classifyGoogleFlowV2Model(d);

	let modelOk = false;
	let modelSoftPass = false;
	if (model.state === "wrong") {
		modelOk = false;
	} else if (model.state === "correct") {
		modelOk = true;
	} else {
		// hidden/UNKNOWN: soft-pass ONLY with strong panel proof (panel + ratio + count).
		modelSoftPass = Boolean(panelOpened && ratioOk && countOk);
		modelOk = modelSoftPass;
	}

	const saveVisible = _bool(d.save_button_found);
	const persistOk = saveVisible
		? Boolean(_bool(d.save_clicked) && _bool(d.settings_persisted))
		: _bool(d.settings_persisted);

	const ok = Boolean(panelOpened && ratioOk && countOk && modelOk && persistOk);
	return {
		ok,
		settings_panel_opened: panelOpened,
		ratio_9_16_confirmed: ratioOk,
		count_1x_confirmed: countOk,
		model_state: model.state,
		model_canonical: model.canonical,
		model_visible_wrong: model.state === "wrong",
		model_veo_lite_confirmed: model.state === "correct" && Boolean(model.veoLite),
		model_hidden_safe_pass: modelSoftPass,
		save_button_found: saveVisible,
		settings_saved_or_persisted: persistOk,
	};
}

// D. Prompt proof — field found, non-empty text inserted and reflected, accepted.
function evaluatePromptProof(d) {
	const fieldFound = _bool(d.prompt_field_found);
	const insertedLen = Number(d.prompt_inserted_length || 0);
	const reflected = _bool(d.prompt_reflected);
	const editableAfterSettings =
		d.prompt_editable_after_settings === undefined
			? true
			: _bool(d.prompt_editable_after_settings);
	const ok = Boolean(
		fieldFound && insertedLen > 0 && reflected && editableAfterSettings,
	);
	return {
		ok,
		prompt_field_found: fieldFound,
		prompt_inserted_length: insertedLen,
		prompt_reflected: reflected,
		// Product truth anchor is recorded for the compiler gate; surfaced but
		// not enforced here (enforced at prompt-compile time per the SOP).
		product_truth_anchor_present: _bool(d.product_truth_anchor_present),
	};
}

// E. Generate-enabled proof — found, enabled, no blocking modal, bindings intact.
//    Submit is NOT part of readiness and is never auto-clicked during UAT.
function evaluateGenerateProof(d) {
	const found = _bool(d.generate_button_found);
	const enabled = _bool(d.generate_button_enabled);
	const noModal = !_bool(d.blocking_modal_detected);
	const ok = Boolean(found && enabled && noModal);
	return {
		ok,
		generate_button_found: found,
		generate_button_enabled: enabled,
		blocking_modal_detected: _bool(d.blocking_modal_detected),
	};
}

/**
 * Evaluate full V2 readiness. Returns:
 *   {
 *     contract, ready, proofs: { editor, upload, settings, prompt, generate },
 *     primary_blocker, runtime_readiness
 *   }
 * primary_blocker is the FIRST failing gate in SOP order; null when ready.
 */
function evaluateGoogleFlowV2Readiness(diagnostic = {}) {
	const d = diagnostic && typeof diagnostic === "object" ? diagnostic : {};
	const editor = evaluateEditorProof(d);
	const upload = evaluateUploadProof(d);
	const settings = evaluateSettingsProof(d);
	const prompt = evaluatePromptProof(d);
	const generate = evaluateGenerateProof(d);

	let primary_blocker = null;
	if (!editor.ok) {
		primary_blocker = GFV2_BLOCKERS.EDITOR_NOT_READY;
	} else if (!upload.ok) {
		primary_blocker = GFV2_BLOCKERS.UPLOAD_MEDIA_NOT_FOUND;
	} else if (!settings.settings_panel_opened) {
		primary_blocker = GFV2_BLOCKERS.SETTINGS_PANEL_NOT_FOUND;
	} else if (settings.model_visible_wrong) {
		// Hard fail — never let a visible wrong/image model through.
		primary_blocker = GFV2_BLOCKERS.VISIBLE_WRONG_MODEL;
	} else if (!settings.ratio_9_16_confirmed) {
		primary_blocker = GFV2_BLOCKERS.RATIO_9_16_NOT_CONFIRMED;
	} else if (!settings.count_1x_confirmed) {
		primary_blocker = GFV2_BLOCKERS.COUNT_1X_NOT_CONFIRMED;
	} else if (!settings.ok) {
		primary_blocker = GFV2_BLOCKERS.SETTINGS_NOT_PERSISTED;
	} else if (!prompt.prompt_field_found) {
		primary_blocker = GFV2_BLOCKERS.PROMPT_FIELD_NOT_FOUND;
	} else if (!prompt.ok) {
		primary_blocker = GFV2_BLOCKERS.PROMPT_NOT_ACCEPTED;
	} else if (!generate.ok) {
		primary_blocker = GFV2_BLOCKERS.GENERATE_BUTTON_NOT_ENABLED;
	}

	const ready = Boolean(
		editor.ok && upload.ok && settings.ok && prompt.ok && generate.ok,
	);

	return {
		contract: GFV2_CONTRACT,
		ready,
		primary_blocker,
		proofs: { editor, upload, settings, prompt, generate },
		runtime_readiness: {
			flow_editor_open: editor.ok,
			upload_media_available: Boolean(d.upload_media_found),
			asset_uploaded: Boolean(d.asset_uploaded || d.media_attached),
			asset_added_to_prompt: upload.ok,
			settings_panel_opened: settings.settings_panel_opened,
			aspect_9_16_confirmed: settings.ratio_9_16_confirmed,
			count_1x_confirmed: settings.count_1x_confirmed,
			model_veo_lite_confirmed: settings.model_veo_lite_confirmed,
			model_hidden_safe_pass: settings.model_hidden_safe_pass,
			settings_saved_or_persisted: settings.settings_saved_or_persisted,
			prompt_field_found: prompt.prompt_field_found,
			prompt_accepted: prompt.ok,
			generate_button_enabled: generate.generate_button_enabled,
		},
	};
}

const _api = {
	GFV2_CONTRACT,
	GFV2_BLOCKERS,
	classifyGoogleFlowV2Model,
	evaluateEditorProof,
	evaluateUploadProof,
	evaluateSettingsProof,
	evaluatePromptProof,
	evaluateGenerateProof,
	evaluateGoogleFlowV2Readiness,
};

// Node (tests) + browser (content script, when later wired) dual export.
if (typeof module !== "undefined" && module.exports) {
	module.exports = _api;
}
if (typeof self !== "undefined") {
	self.__GFV2_READINESS__ = _api;
}
