#!/usr/bin/env node
/**
 * Stamp the unpacked extension folder with the git identity it was built from.
 *
 * WHY THIS EXISTS
 * The extension ships as an unpacked folder with no build step, so nothing ever
 * bound the loaded code to a commit. What filled that gap was a hand-typed
 * constant (`BOSMAX_BUILD_PROOF`) naming a branch and commit — and it went
 * stale: it advertised `fix/mv3-message-port-lifecycle` / 47ce0422 long after
 * main had moved on, and it was surfaced to the backend as provenance. A field
 * that asserts a false identity is worse than no field, because a reader trusts
 * it. This script replaces declaration with derivation.
 *
 * WHAT IT DOES NOT DO
 * It does NOT touch BUILD_ID. BUILD_ID's job is to prove that the background
 * service worker and the injected content script came from the SAME folder
 * (`build_match`), and that gate guards generation via
 * make_video._bind_editor_session -> CONTENT_BUILD_MISMATCH. Re-pointing it at
 * a per-commit SHA would change a proven gate's semantics for no gain. The git
 * identity is therefore an ADDITIONAL, separate field.
 *
 * DIRTY TREES ARE REPORTED AS DIRTY
 * If the working tree has uncommitted changes, the folder on disk does not
 * correspond to the SHA. Saying `sha: X` in that state would recreate the same
 * class of lie in a subtler form, so `dirty: true` is recorded and the SHA is
 * explicitly not a sufficient identity on its own.
 *
 * OUTPUT   extension/build-stamp.js  (generated, gitignored)
 * USAGE    node scripts/stamp-extension-build.mjs
 *          then reload the unpacked extension in Chrome.
 *
 * The output file is deliberately NOT committed. A committed stamp goes stale
 * the moment the next commit lands — which is precisely the failure this
 * replaces. If the file is absent the extension still loads: background.js
 * imports it inside try/catch and reports `stamped: false`, which is honest.
 */
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_FILE = join(REPO_ROOT, "extension", "build-stamp.js");

function git(...args) {
	return execFileSync("git", args, { cwd: REPO_ROOT, encoding: "utf8" }).trim();
}

function main() {
	let sha;
	let branch;
	let dirty;
	try {
		sha = git("rev-parse", "HEAD");
		branch = git("rev-parse", "--abbrev-ref", "HEAD");
		// Only the extension folder matters here: an edit to the dashboard does not
		// make the LOADED extension diverge from its commit.
		dirty = git("status", "--porcelain", "--", "extension").length > 0;
	} catch (err) {
		console.error(
			"[stamp-extension-build] ERR_GIT_UNAVAILABLE — refusing to write a stamp " +
				"that cannot be derived. The extension will report stamped:false, which " +
				"is the correct answer when provenance is unknown.",
			err?.message ?? err,
		);
		process.exit(1);
	}

	const stamp = {
		stamped: true,
		sha,
		short_sha: sha.slice(0, 8),
		branch,
		dirty,
		stamped_at: new Date().toISOString(),
	};

	const body = `// GENERATED FILE — DO NOT EDIT, DO NOT COMMIT.
// Written by scripts/stamp-extension-build.mjs. Regenerate after every pull or
// checkout, then reload the unpacked extension in Chrome. A stale stamp is a
// lie about which code is loaded, which is the exact defect this replaced.
self.__FLOWKIT_BUILD_STAMP__ = Object.freeze(${JSON.stringify(stamp, null, "\t")});
`;

	writeFileSync(OUT_FILE, body, "utf8");
	console.log(
		`[stamp-extension-build] wrote extension/build-stamp.js sha=${stamp.short_sha} ` +
			`branch=${stamp.branch} dirty=${stamp.dirty}`,
	);
	if (dirty) {
		console.warn(
			"[stamp-extension-build] WARNING: extension/ has uncommitted changes, so the " +
				"loaded folder does NOT match this SHA. The stamp records dirty:true — do " +
				"not treat this build as release-identified.",
		);
	}
}

main();
