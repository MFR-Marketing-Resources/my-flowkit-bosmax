import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

type Domain = {
	name: string;
	status: string;
	ownedPaths: string[];
};

const MODULE_STATUS_PATH = "docs/MODULE_STATUS.yaml";
const ALLOWED_GOVERNANCE_PATHS = new Set([
	"docs/MODULE_STATUS.yaml",
	"scripts/mandor-check.ts",
]);

function fail(code: string, details?: string): never {
	if (details) {
		console.error(`${code}: ${details}`);
	} else {
		console.error(code);
	}
	process.exit(1);
}

function parseModuleStatus(raw: string): Domain[] {
	const lines = raw.split(/\r?\n/);
	const domains: Domain[] = [];
	let current: Domain | null = null;
	let inOwnedPaths = false;

	for (const originalLine of lines) {
		const line = originalLine.replace(/\t/g, "  ");
		const trimmed = line.trim();
		if (!trimmed || trimmed.startsWith("#")) {
			continue;
		}

		if (trimmed === "domains:") {
			continue;
		}

		const domainStart = line.match(/^\s*-\s+name:\s+([A-Za-z0-9_-]+)\s*$/);
		if (domainStart) {
			current = {
				name: domainStart[1],
				status: "",
				ownedPaths: [],
			};
			domains.push(current);
			inOwnedPaths = false;
			continue;
		}

		if (!current) {
			continue;
		}

		const statusMatch = line.match(/^\s*status:\s+([A-Z_]+)\s*$/);
		if (statusMatch) {
			current.status = statusMatch[1];
			inOwnedPaths = false;
			continue;
		}

		if (line.match(/^\s*owned_paths:\s*$/)) {
			inOwnedPaths = true;
			continue;
		}

		const ownedPathMatch = inOwnedPaths
			? line.match(/^\s*-\s+(.+?)\s*$/)
			: null;
		if (ownedPathMatch) {
			current.ownedPaths.push(ownedPathMatch[1]);
		}
	}

	return domains;
}

function getChangedPaths(): string[] {
	const staged = execFileSync("git", ["diff", "--cached", "--name-only"], {
		encoding: "utf8",
	})
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter(Boolean);

	if (staged.length > 0) {
		return staged;
	}

	const porcelain = execFileSync(
		"git",
		["status", "--porcelain", "--untracked-files=all"],
		{ encoding: "utf8" },
	)
		.split(/\r?\n/)
		.map((line) => line.trimEnd())
		.filter(Boolean);

	return porcelain
		.map((line) => line.slice(3).trim())
		.filter(Boolean)
		.filter((line) => !line.startsWith("dashboard/node_modules/"))
		.filter((line) => !line.startsWith("data/product_registration/"))
		.filter((line) => !line.startsWith("data/fastmoss/imports/"))
		.filter((line) => !line.startsWith(".gemini/"))
		.filter((line) => !line.startsWith(".claude/"))
		.filter((line) => !line.startsWith("scratch/"))
		.filter((line) => !line.startsWith("scripts/fixtures/poster-compositor/"))
		.filter((line) => !line.endsWith(".db"))
		.filter((line) => !line.endsWith(".sqlite"))
		.filter((line) => !line.endsWith(".db-shm"))
		.filter((line) => !line.endsWith(".db-wal"));
}

function resolveDomainsForPaths(
	domains: Domain[],
	changedPaths: string[],
): { unresolved: string[]; resolvedDomains: Set<string> } {
	const resolvedDomains = new Set<string>();
	const unresolved: string[] = [];

	for (const changedPath of changedPaths) {
		if (ALLOWED_GOVERNANCE_PATHS.has(changedPath)) {
			resolvedDomains.add("workspace");
			continue;
		}

		const matches = domains.filter(
			(domain) =>
				domain.status === "IN_PROGRESS" &&
				domain.ownedPaths.includes(changedPath),
		);

		if (matches.length !== 1) {
			unresolved.push(changedPath);
			continue;
		}

		resolvedDomains.add(matches[0].name);
	}

	return { unresolved, resolvedDomains };
}

if (!existsSync(MODULE_STATUS_PATH)) {
	fail("FAIL_MODULE_STATUS_MISSING");
}

const domains = parseModuleStatus(readFileSync(MODULE_STATUS_PATH, "utf8"));
if (domains.length === 0) {
	fail(
		"FAIL_DOMAIN_UNRESOLVED",
		"No domains parsed from docs/MODULE_STATUS.yaml",
	);
}

const changedPaths = getChangedPaths();
if (changedPaths.length === 0) {
	fail("FAIL_DOMAIN_UNRESOLVED", "No changed files found");
}

const { unresolved, resolvedDomains } = resolveDomainsForPaths(
	domains,
	changedPaths,
);
if (unresolved.length > 0) {
	fail("FAIL_UNRELATED_DIFF_FOUND", unresolved.join(", "));
}

if (resolvedDomains.size !== 1 || !resolvedDomains.has("workspace")) {
	fail(
		"FAIL_DOMAIN_UNRESOLVED",
		`Resolved domains: ${Array.from(resolvedDomains).join(", ") || "none"}`,
	);
}

console.log(
	`PASS_MODULE_STATUS_DOMAIN_RESOLVED domain=workspace paths=${changedPaths.length}`,
);
