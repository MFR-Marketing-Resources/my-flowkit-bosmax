"use strict";

// Unit tests for the Google Flow UI Contract V2 readiness proof model.
// Pure logic — no live Google Flow tab required.

const assert = require("node:assert/strict");
const {
	GFV2_BLOCKERS,
	evaluateGoogleFlowV2Readiness,
} = require("../extension/gfv2-readiness.js");

// A fully-ready V2 diagnostic. Individual tests clone + mutate this.
function readyDiagnostic() {
	return {
		// editor
		flow_tab_found: true,
		editor_surface_present: true,
		content_script_alive: true,
		login_blocker: false,
		composer_present: true,
		// (Frames/Ingredients deliberately ABSENT — must not matter.)
		frames_button_present: false,
		ingredients_button_present: false,
		subMode: "Frames",
		subMode_source: "inferred",
		// upload (strong proof)
		add_to_prompt_completed: true,
		asset_preview_in_prompt: true,
		media_attached: true,
		// settings
		settings_panel_opened: true,
		ratio_9_16_confirmed: true,
		count_1x_confirmed: true,
		model_visible: true,
		model_canonical: "veo 3.1 - lite",
		model_veo_lite_confirmed: true,
		save_button_found: false,
		settings_persisted: true,
		// prompt
		prompt_field_found: true,
		prompt_inserted_length: 1200,
		prompt_reflected: true,
		prompt_editable_after_settings: true,
		product_truth_anchor_present: true,
		// generate
		generate_button_found: true,
		generate_button_enabled: true,
		blocking_modal_detected: false,
	};
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// 1. Frames / Ingredients buttons absent must not fail readiness by itself.
test("frames/ingredients absent does not fail readiness", () => {
	const d = readyDiagnostic();
	d.frames_button_present = false;
	d.ingredients_button_present = false;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.ready, true, "must stay ready without Frames/Ingredients buttons");
	assert.equal(r.proofs.editor.ok, true);
});

// 2. Synthetic subMode=Frames is not strong proof (readiness must not depend on it).
test("synthetic subMode=Frames is not proof", () => {
	const d = readyDiagnostic();
	d.subMode = "Frames";
	d.subMode_source = "inferred";
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(
		r.proofs.editor.submode_inferred_synthetic,
		true,
		"synthetic subMode must be flagged as inferred",
	);
	// And readiness must come from the real proofs, not subMode:
	const d2 = readyDiagnostic();
	d2.add_to_prompt_completed = false;
	d2.asset_preview_in_prompt = false;
	d2.media_attached = false;
	d2.asset_card_bound_to_prompt = false;
	d2.prompt_attachment_chip_present = false;
	d2.subMode = "Frames"; // still "Frames" but no real upload proof
	const r2 = evaluateGoogleFlowV2Readiness(d2);
	assert.equal(r2.ready, false, "subMode=Frames must not rescue missing upload proof");
});

// 3. visibleUploadSlots alone does not pass upload proof.
test("visibleUploadSlots alone does not pass upload proof", () => {
	const d = readyDiagnostic();
	d.add_to_prompt_completed = false;
	d.asset_preview_in_prompt = false;
	d.media_attached = false;
	d.asset_card_bound_to_prompt = false;
	d.prompt_attachment_chip_present = false;
	d.visibleUploadSlots = ["Start"];
	d.body_includes_image = true;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.proofs.upload.ok, false, "weak signals must not pass upload proof");
	assert.equal(r.proofs.upload.weak_signal_only, true);
	assert.equal(r.primary_blocker, GFV2_BLOCKERS.UPLOAD_MEDIA_NOT_FOUND);
});

// 4. Add to Prompt completed passes upload proof.
test("add_to_prompt completed passes upload proof", () => {
	const d = readyDiagnostic();
	d.asset_preview_in_prompt = false;
	d.media_attached = false;
	d.add_to_prompt_completed = true;
	assert.equal(evaluateGoogleFlowV2Readiness(d).proofs.upload.ok, true);
});

// 5. Asset preview/chip in prompt passes upload proof.
test("asset preview/chip in prompt passes upload proof", () => {
	const d = readyDiagnostic();
	d.add_to_prompt_completed = false;
	d.media_attached = false;
	d.asset_preview_in_prompt = false;
	d.prompt_attachment_chip_present = true;
	assert.equal(evaluateGoogleFlowV2Readiness(d).proofs.upload.ok, true);
});

// 6. Settings panel open with 9:16 and 1x passes settings proof (model correct).
test("settings panel + 9:16 + 1x passes settings proof", () => {
	const d = readyDiagnostic();
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.proofs.settings.ok, true);
	assert.equal(r.proofs.settings.model_veo_lite_confirmed, true);
});

// 7. Visible wrong model fails hard.
test("visible wrong (image) model fails hard", () => {
	const d = readyDiagnostic();
	d.model_visible = true;
	d.model_canonical = "nano banana 2";
	d.model_veo_lite_confirmed = false;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.ready, false);
	assert.equal(r.proofs.settings.model_visible_wrong, true);
	assert.equal(r.primary_blocker, GFV2_BLOCKERS.VISIBLE_WRONG_MODEL);
});

// 8a. model=UNKNOWN soft-passes ONLY with strong settings proof.
test("model UNKNOWN soft-passes with strong settings proof", () => {
	const d = readyDiagnostic();
	d.model_visible = false;
	d.model_canonical = "UNKNOWN";
	d.model_veo_lite_confirmed = false;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.proofs.settings.model_hidden_safe_pass, true);
	assert.equal(r.proofs.settings.ok, true);
	assert.equal(r.ready, true);
});

// 8b. model=UNKNOWN must NOT pass when settings proof is weak (panel not opened).
test("model UNKNOWN does not soft-pass without strong settings proof", () => {
	const d = readyDiagnostic();
	d.model_visible = false;
	d.model_canonical = "UNKNOWN";
	d.settings_panel_opened = false;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.proofs.settings.model_hidden_safe_pass, false);
	assert.equal(r.proofs.settings.ok, false);
	assert.equal(r.primary_blocker, GFV2_BLOCKERS.SETTINGS_PANEL_NOT_FOUND);
});

// 9a. Save visible path requires Save clicked + persisted.
test("save visible requires save clicked and persisted", () => {
	const d = readyDiagnostic();
	d.save_button_found = true;
	d.save_clicked = false;
	d.settings_persisted = true;
	const r1 = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r1.proofs.settings.ok, false, "save visible but not clicked must fail");
	assert.equal(r1.primary_blocker, GFV2_BLOCKERS.SETTINGS_NOT_PERSISTED);
	d.save_clicked = true;
	const r2 = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r2.proofs.settings.ok, true, "save clicked + persisted passes");
});

// 9b/10. Save absent path verifies persistence by state.
test("save absent passes via settings_persisted state", () => {
	const d = readyDiagnostic();
	d.save_button_found = false;
	d.settings_persisted = true;
	assert.equal(evaluateGoogleFlowV2Readiness(d).proofs.settings.ok, true);
	d.settings_persisted = false;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.proofs.settings.ok, false);
	assert.equal(r.primary_blocker, GFV2_BLOCKERS.SETTINGS_NOT_PERSISTED);
});

// 11. Prompt inserted and reflected passes; missing field fails.
test("prompt inserted+reflected passes; missing field fails", () => {
	const ok = evaluateGoogleFlowV2Readiness(readyDiagnostic());
	assert.equal(ok.proofs.prompt.ok, true);
	const dNoField = readyDiagnostic();
	dNoField.prompt_field_found = false;
	const rNoField = evaluateGoogleFlowV2Readiness(dNoField);
	assert.equal(rNoField.proofs.prompt.ok, false);
	assert.equal(rNoField.primary_blocker, GFV2_BLOCKERS.PROMPT_FIELD_NOT_FOUND);
	const dEmpty = readyDiagnostic();
	dEmpty.prompt_inserted_length = 0;
	assert.equal(
		evaluateGoogleFlowV2Readiness(dEmpty).primary_blocker,
		GFV2_BLOCKERS.PROMPT_NOT_ACCEPTED,
	);
});

// 12/13. Generate enabled verified (not clicked); disabled/missing fails.
test("generate enabled verified; disabled fails", () => {
	const ok = evaluateGoogleFlowV2Readiness(readyDiagnostic());
	assert.equal(ok.proofs.generate.ok, true);
	assert.equal(ok.ready, true, "fully-ready diagnostic must be READY (stop-before-generate)");
	const dDisabled = readyDiagnostic();
	dDisabled.generate_button_enabled = false;
	const r = evaluateGoogleFlowV2Readiness(dDisabled);
	assert.equal(r.proofs.generate.ok, false);
	assert.equal(r.primary_blocker, GFV2_BLOCKERS.GENERATE_BUTTON_NOT_ENABLED);
	const dModal = readyDiagnostic();
	dModal.blocking_modal_detected = true;
	assert.equal(evaluateGoogleFlowV2Readiness(dModal).proofs.generate.ok, false);
});

// Editor-not-ready blocker fires before anything else.
test("editor not ready blocks first", () => {
	const d = readyDiagnostic();
	d.composer_present = false;
	const r = evaluateGoogleFlowV2Readiness(d);
	assert.equal(r.primary_blocker, GFV2_BLOCKERS.EDITOR_NOT_READY);
});

function main() {
	let failed = 0;
	for (const [name, fn] of tests) {
		try {
			fn();
			console.log(`PASS ${name}`);
		} catch (err) {
			failed += 1;
			console.error(`FAIL ${name}\n  ${err.message}`);
		}
	}
	// Print a sample V2 diagnostic + verdict for the deliverable.
	const sample = evaluateGoogleFlowV2Readiness(readyDiagnostic());
	console.log(
		"\nSAMPLE_V2_READINESS=" + JSON.stringify(sample.runtime_readiness),
	);
	console.log("SAMPLE_READY=" + sample.ready + " BLOCKER=" + sample.primary_blocker);
	if (failed > 0) {
		console.error(`\n${failed} failing case(s)`);
		process.exit(1);
	}
	console.log("\nPASS test-gfv2-readiness");
}

main();
