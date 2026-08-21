#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { classifyFlowProviderReadiness } from "./browser-uat/flow-provider-readiness.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const bootstrapSource = fs.readFileSync(
	path.join(scriptDir, "browser-uat", "bootstrap-flow-provider-uat.ps1"),
	"utf8",
);
const startSource = fs.readFileSync(
	path.join(scriptDir, "browser-uat", "start-browser-uat.ps1"),
	"utf8",
);
const backgroundSource = fs.readFileSync(
	path.join(repoRoot, "extension", "background.js"),
	"utf8",
);
const readinessSource = fs.readFileSync(
	path.join(scriptDir, "browser-uat", "flow-provider-readiness.mjs"),
	"utf8",
);

function readyObservation() {
	return {
		browser_uat_ready: true,
		runtime_current_main: true,
		extension_loaded: true,
		extension_service_worker_alive: true,
		flow_project_tab_found: true,
		flow_auth_status: "AUTHENTICATED",
		flow_transport_connected: true,
		flow_transport_bound_to_uat_browser: true,
		video_job_in_flight: false,
	};
}

// A: generic CDP/browser readiness is not provider readiness.
{
	const result = classifyFlowProviderReadiness({
		browser_uat_ready: true,
		runtime_current_main: true,
		extension_loaded: false,
	});
	assert.equal(result.browser_uat_ready, true);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "UAT_EXTENSION_NOT_LOADED");
}

// B: the extension alone is not enough without a real Flow project editor.
{
	const result = classifyFlowProviderReadiness({
		...readyObservation(),
		flow_project_tab_found: false,
	});
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "UAT_FLOW_PROJECT_NOT_OPEN");
}

// C: a project page with unauthenticated credits must fail closed.
{
	const result = classifyFlowProviderReadiness({
		...readyObservation(),
		flow_auth_status: "UNAUTHENTICATED",
	});
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "UAT_FLOW_UNAUTHENTICATED");
}

// D: backend connected from a different browser/session is not bound proof.
{
	const result = classifyFlowProviderReadiness({
		...readyObservation(),
		flow_transport_bound_to_uat_browser: false,
	});
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "UAT_FLOW_TRANSPORT_NOT_BOUND");
}

// E: only the same dedicated browser/session with all provider proofs is ready.
{
	const result = classifyFlowProviderReadiness(readyObservation());
	assert.equal(result.flow_provider_uat_ready, true);
	assert.equal(result.primary_blocker, "UAT_PROVIDER_READY");
}

// F: bootstrap uses the fixed dedicated profile and only force-restarts the
// exact UAT Chrome after the readiness receipt proves the extension is absent.
assert.match(startSource, /ChromeProfileDir/);
assert.match(startSource, /ForceRestartUatOnly/);
assert.match(startSource, /load-extension/);
assert.match(bootstrapSource, /ForceRestartUatOnly/);
assert.match(bootstrapSource, /ChromeProfileDir|chrome-profile/);
assert.match(bootstrapSource, /OWNER_UAT_EXTENSION_INSTALL_REQUIRED/);

// G: no personal profile, cookie store, or account data is copied/touched.
assert.doesNotMatch(bootstrapSource, /[A-Za-z]:\\[^\r\n]*\\Default\\/i);
assert.doesNotMatch(bootstrapSource, /Copy-Item|Move-Item|robocopy|xcopy/i);
assert.match(startSource, /user-data-dir=\$\(\$script:ChromeProfileDir\)/i);

// The backend/worker correlation fields are part of the transport bridge, not
// product or Faceless logic.
assert.match(backgroundSource, /extension_id/);
assert.match(backgroundSource, /extension_session_id/);
assert.match(backgroundSource, /extension_version/);
assert.match(readinessSource, /const observedExtensionBuild = extensionIdentityProof/);
assert.match(readinessSource, /extension_build_expected/);

console.log("FLOW_PROVIDER_READINESS_TESTS_PASS cases=A,B,C,D,E,F,G");
