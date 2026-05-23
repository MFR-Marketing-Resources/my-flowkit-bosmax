const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const REGISTRY_PATH = path.join(ROOT, "extension", "selector-registry.js");
const DOM_PATH = path.join(ROOT, "extension", "content-flow-dom.js");
const MANIFEST_PATH = path.join(ROOT, "extension", "manifest.json");

function loadRegistry() {
	const source = fs.readFileSync(REGISTRY_PATH, "utf8");
	const context = {
		window: {},
		console,
		Object,
		Array,
	};
	vm.runInNewContext(source, context, { filename: REGISTRY_PATH });
	return {
		registry: context.window.__FLOWKIT_SELECTOR_REGISTRY__,
		helpers: context.window.__FLOWKIT_SELECTOR_REGISTRY_HELPERS__,
	};
}

function main() {
	const { registry, helpers } = loadRegistry();
	const domSource = fs.readFileSync(DOM_PATH, "utf8");
	const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));

	assert.ok(registry, "Expected selector registry to load");
	assert.ok(helpers, "Expected selector registry helpers to load");
	assert.equal(typeof registry.version, "string");

	const requiredIds = [
		"flow_config_launcher_compact",
		"flow_config_surface_portal",
		"f2v_collapsed_config_launcher",
		"generate_button_composer_scoped",
		"generate_button_icon_path_fallback",
		"upload_slot_label_scan",
		"asset_picker_modal_surface",
		"upload_acceptance_preview_evidence",
		"upload_fixed_overlay_scan",
	];

	for (const id of requiredIds) {
		const entry = helpers.getEntry(id);
		assert.ok(entry, `Missing registry entry: ${id}`);
		for (const field of [
			"id",
			"surface",
			"verification_status",
			"requires_shadow_piercing",
			"evidence_source",
			"fallback_policy",
		]) {
			assert.ok(field in entry, `Entry ${id} missing field ${field}`);
		}
		assert.ok(Array.isArray(entry.selectors) && entry.selectors.length > 0, `Entry ${id} must declare selectors`);
		assert.equal(helpers.buildEvidencePointer(id), `selector-registry:${registry.version}:${id}`);
	}

	assert.equal(helpers.getEntry("flow_config_launcher_compact").verification_status, "PROVEN");
	assert.equal(helpers.getEntry("upload_slot_label_scan").verification_status, "UNSTABLE");
	assert.equal(helpers.getEntry("generate_button_icon_path_fallback").verification_status, "DEPRECATED");

	for (const token of [
		"function getSelectorRegistryHelpers() {",
		"flow_config_launcher_compact",
		"flow_config_surface_portal",
		"f2v_collapsed_config_launcher",
		"generate_button_composer_scoped",
		"upload_slot_label_scan",
		"asset_picker_modal_surface",
		"upload_acceptance_preview_evidence",
		"selector_registry_ids:",
		"evidence_pointers:",
		"fallback_policies:",
	]) {
		assert.ok(domSource.includes(token), `content-flow-dom.js missing registry consumer token: ${token}`);
	}

	const contentScriptFiles = manifest.content_scripts?.[0]?.js || [];
	assert.deepEqual(
		contentScriptFiles.slice(0, 3),
		["content.js", "selector-registry.js", "content-flow-dom.js"],
		"Manifest must load selector registry before content-flow-dom",
	);

	console.log("PASS Flow selector registry validation");
}

main();
