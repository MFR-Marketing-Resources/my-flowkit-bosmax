const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repoRoot = path.resolve(__dirname, "..");
const extensionDir = path.join(repoRoot, "extension");
const backgroundPath = path.join(extensionDir, "background.js");
const cdpVisibleClickerPath = path.join(extensionDir, "cdp-visible-clicker.js");

function readUtf8(filePath) {
	return fs.readFileSync(filePath, "utf8");
}

function extractImportBlockFiles(backgroundSource) {
	const files = [];
	const importRegex = /importScripts\(([^)]+)\)/g;
	for (const match of backgroundSource.matchAll(importRegex)) {
		const args = match[1] || "";
		for (const fileMatch of args.matchAll(/["']([^"']+)["']/g)) {
			files.push(fileMatch[1]);
		}
	}
	return files;
}

function buildConsole(logs) {
	const toMessage = (args) =>
		args
			.map((item) => {
				if (typeof item === "string") {
					return item;
				}
				try {
					return JSON.stringify(item);
				} catch {
					return String(item);
				}
			})
			.join(" ");

	return {
		log: (...args) => logs.push({ level: "log", message: toMessage(args) }),
		info: (...args) => logs.push({ level: "info", message: toMessage(args) }),
		warn: (...args) => logs.push({ level: "warn", message: toMessage(args) }),
		error: (...args) => logs.push({ level: "error", message: toMessage(args) }),
	};
}

function buildContext(logs) {
	const context = {
		console: buildConsole(logs),
		self: {},
		globalThis: null,
		setTimeout,
		clearTimeout,
	};
	context.self = context;
	context.globalThis = context;
	context.importScripts = (...files) => {
		for (const file of files) {
			const target = path.join(extensionDir, file);
			if (!fs.existsSync(target)) {
				throw new Error(`IMPORT_FILE_MISSING:${file}`);
			}
			const source = readUtf8(target);
			vm.runInContext(source, context, { filename: target });
		}
	};
	return vm.createContext(context);
}

function main() {
	const backgroundSource = readUtf8(backgroundPath);
	const importBlockFiles = extractImportBlockFiles(backgroundSource);
	const logs = [];
	const context = buildContext(logs);
	const cdpVisibleClickerPresent = fs.existsSync(cdpVisibleClickerPath);
	let cdpVisibleClickerLoaded = false;
	let importError = null;

	try {
		if (cdpVisibleClickerPresent) {
			vm.runInContext(readUtf8(cdpVisibleClickerPath), context, {
				filename: cdpVisibleClickerPath,
			});
			cdpVisibleClickerLoaded = true;
		}
		for (const file of importBlockFiles) {
			context.importScripts(file);
		}
	} catch (error) {
		importError = String(error && error.message ? error.message : error);
	}

	const runnerApi =
		context.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ ||
		context.self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ ||
		null;
	const result = {
		ok: !importError && Boolean(runnerApi),
		import_block_files: importBlockFiles,
		cdp_visible_clicker_present: cdpVisibleClickerPresent,
		cdp_visible_clicker_loaded: cdpVisibleClickerLoaded,
		runner_loaded: Boolean(runnerApi),
		runner_api_keys: runnerApi ? Object.keys(runnerApi) : [],
		import_ok_logged: logs.some((entry) =>
			entry.message.includes("[BOSMAX_F2V_FLOW_QUEUE_RUNNER] import_ok"),
		),
		background_import_ok_in_source: backgroundSource.includes(
			"[BOSMAX_F2V_FLOW_QUEUE_RUNNER] background_import_ok",
		),
		background_runner_import_in_source: backgroundSource.includes(
			'importScripts("f2v-flow-queue-runner.js")',
		),
		import_error: importError,
		logs,
	};

	process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
	process.exitCode = result.ok ? 0 : 1;
}

main();
