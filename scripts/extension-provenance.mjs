#!/usr/bin/env node
/**
 * Read-only provenance receipt for the unpacked extension.
 *
 * Unlike build-stamp.js this command never writes into extension/.  It binds
 * the exact bytes on disk to a sorted content manifest, while also reporting
 * the current git HEAD and any extension-folder dirtiness.  A dirty folder is
 * therefore still useful evidence, but is never misreported as a clean commit
 * build.
 *
 * Usage: node scripts/extension-provenance.mjs [repo-root]
 */
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptRoot = resolve(join(fileURLToPath(new URL(".", import.meta.url)), ".."));
const repoRoot = resolve(process.argv[2] || scriptRoot);
const extensionRoot = join(repoRoot, "extension");

function git(...args) {
	return execFileSync("git", args, {
		cwd: repoRoot,
		encoding: "utf8",
		stderr: "ignore",
	}).trim();
}

function walk(dir, out = []) {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const absolute = join(dir, entry.name);
		if (entry.isDirectory()) walk(absolute, out);
		else if (entry.isFile() && entry.name !== "build-stamp.js") out.push(absolute);
	}
	return out;
}

const files = walk(extensionRoot)
	.map((absolute) => relative(repoRoot, absolute).replaceAll("\\", "/"))
	.sort();
const manifest = files
	.map((name) => {
		const bytes = readFileSync(join(repoRoot, name));
		const sha256 = createHash("sha256").update(bytes).digest("hex");
		return `${name}\0${bytes.length}\0${sha256}`;
	})
	.join("\n");
const dirtyOutput = execFileSync(
	"git",
	["status", "--porcelain", "--", "extension"],
	{ cwd: repoRoot, encoding: "utf8", stderr: "ignore" },
);
const dirtyFiles = dirtyOutput
	.split(/\r?\n/)
	.map((line) => line.slice(3).trim())
	.filter(Boolean);

console.log(JSON.stringify({
	provenance_status: dirtyFiles.length ? "WORKTREE_DIRTY_DETERMINISTIC" : "COMMIT_TREE_DETERMINISTIC",
	git_head: git("rev-parse", "HEAD"),
	git_branch: git("rev-parse", "--abbrev-ref", "HEAD"),
	last_extension_commit: git("log", "-1", "--format=%H", "--", "extension"),
	extension_dirty: dirtyFiles.length > 0,
	extension_dirty_files: dirtyFiles,
	extension_file_count: files.length,
	extension_tree_sha256: createHash("sha256").update(manifest).digest("hex"),
	manifest_sha256: createHash("sha256").update(manifest).digest("hex"),
	stamp_file_excluded: true,
}, null, 2));
