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
const contentSource = fs.readFileSync(
	path.join(repoRoot, "extension", "content-flow-dom.js"),
	"utf8",
);
const readinessSource = fs.readFileSync(
	path.join(scriptDir, "browser-uat", "flow-provider-readiness.mjs"),
	"utf8",
);
const operatorSource = fs.readFileSync(
	path.join(repoRoot, "agent", "api", "operator.py"),
	"utf8",
);

function ownerReadyObservation(overrides = {}) {
	return {
		provider_browser_authority_mode: "OWNER_PROFILE_EXTENSION_BRIDGE",
		dedicated_cdp_browser_ready: false,
		browser_uat_ready: false,
		runtime_current_main: true,
		flow_transport_connected: true,
		flow_transport_bound_to_provider_browser: true,
		extension_session_id: "owner-session-43",
		extension_session_present: true,
		same_extension_session: true,
		session_challenge_verified: true,
		challenge_nonce_match: true,
		same_flow_tab: true,
		flow_project_tab_found: true,
		content_script_loaded: true,
		content_script_alive: true,
		extension_build_match: true,
		flow_auth_status: "AUTHENTICATED",
		numeric_credit_balance: 1068,
		ui_composer_required: false,
		composer_found: false,
		composer_runtime_ready: false,
		video_job_in_flight: false,
		...overrides,
	};
}

// A: dedicated CDP is not provider authority, but the owner challenge is valid.
{
	const result = classifyFlowProviderReadiness(ownerReadyObservation());
	assert.equal(result.flow_provider_uat_ready, true);
	assert.equal(result.primary_blocker, "FLOW_PROVIDER_UAT_READY");
}

// B: a response from a different extension session fails closed.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({ same_extension_session: false }),
	);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "EXTENSION_SESSION_MISMATCH");
}

// C: a response from the wrong Flow tab is not provider authority.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({ same_flow_tab: false }),
	);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "FLOW_PROJECT_NOT_FOUND");
}

// D: the backend nonce must round-trip through the target content script.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({
			session_challenge_verified: false,
			challenge_nonce_match: false,
		}),
	);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "FLOW_SESSION_CHALLENGE_FAILED");
}

// E: numeric credits without same-session challenge proof are insufficient.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({
			session_challenge_verified: false,
			challenge_nonce_match: true,
		}),
	);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "FLOW_SESSION_CHALLENGE_FAILED");
}

// F: exact-product AGENT_T2V does not require UI Composer selectors.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({
			ui_composer_required: false,
			composer_found: false,
			composer_runtime_ready: false,
		}),
	);
	assert.equal(result.flow_provider_uat_ready, true);
}

// G: actual UI Composer routes retain their composer readiness gate.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({
			ui_composer_required: true,
			composer_found: false,
			composer_runtime_ready: false,
		}),
	);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "FLOW_COMPOSER_NOT_READY");
}

// H: stale runtime is always a blocker, even with a valid browser bridge.
{
	const result = classifyFlowProviderReadiness(
		ownerReadyObservation({ runtime_current_main: false }),
	);
	assert.equal(result.flow_provider_uat_ready, false);
	assert.equal(result.primary_blocker, "RUNTIME_NOT_CURRENT_MAIN");
}

// I: current main + Profile 43 bridge + Flow project + challenge + credits is ready.
{
	const result = classifyFlowProviderReadiness(ownerReadyObservation({
		runtime_current_main: true,
		flow_auth_status: "AUTHENTICATED",
		numeric_credit_balance: 1068,
	}));
	assert.equal(result.FLOW_PROVIDER_UAT_READY, true);
	assert.equal(result.primary_blocker, "FLOW_PROVIDER_UAT_READY");
}

// The dedicated CDP lane remains available and explicit; it is not silently
// substituted for owner-profile authority.
assert.match(bootstrapSource, /provider-authority-mode|FLOW_PROVIDER_BROWSER_AUTHORITY/);
assert.match(startSource, /ChromeProfileDir/);
assert.match(startSource, /ForceRestartUatOnly/);
assert.match(startSource, /load-extension/);
assert.doesNotMatch(bootstrapSource, /[A-Za-z]:\\[^\r\n]*\\Default\\/i);
assert.doesNotMatch(bootstrapSource, /Copy-Item|Move-Item|robocopy|xcopy/i);
assert.match(startSource, /user-data-dir=\$\(\$script:ChromeProfileDir\)/i);

// Proof is transport-level and content-tab-level, never an OS-level profile claim.
assert.match(backgroundSource, /EXTENSION_SESSION_ID/);
assert.match(backgroundSource, /FLOW_PROVIDER_SESSION_CHALLENGE/);
assert.match(backgroundSource, /extension_session_id/);
assert.match(contentSource, /FLOW_PROVIDER_SESSION_CHALLENGE/);
assert.match(contentSource, /content_build_id/);
assert.match(operatorSource, /flow-provider-readiness/);
assert.match(operatorSource, /RUNTIME_NOT_CURRENT_MAIN/);
assert.match(readinessSource, /OWNER_PROFILE_EXTENSION_BRIDGE/);
assert.match(readinessSource, /same_extension_session/);
assert.match(readinessSource, /FLOW_PROVIDER_UAT_READY/);

console.log("FLOW_PROVIDER_READINESS_TESTS_PASS cases=A,B,C,D,E,F,G,H,I");
