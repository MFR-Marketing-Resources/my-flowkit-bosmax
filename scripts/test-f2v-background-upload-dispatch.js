const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const BACKGROUND_PATH = path.join(__dirname, "..", "extension", "background.js");

function assert(condition, message) {
	if (!condition) {
		throw new Error(`ASSERTION_FAILED: ${message}`);
	}
}

function extractFunctionSource(source, functionName) {
	const marker = `function ${functionName}(`;
	const startIdx = source.indexOf(marker);
	assert(startIdx >= 0, `missing ${functionName} in background.js`);
	const firstBrace = source.indexOf("{", startIdx);
	assert(firstBrace > startIdx, `missing body brace for ${functionName}`);
	let depth = 0;
	let endIdx = -1;
	for (let i = firstBrace; i < source.length; i += 1) {
		const ch = source[i];
		if (ch === "{") depth += 1;
		else if (ch === "}") {
			depth -= 1;
			if (depth === 0) {
				endIdx = i;
				break;
			}
		}
	}
	assert(endIdx > firstBrace, `unbalanced braces for ${functionName}`);
	return source.slice(startIdx, endIdx + 1);
}

function loadHelpers() {
	const source = fs.readFileSync(BACKGROUND_PATH, "utf8");
	const sandbox = {};
	vm.createContext(sandbox);
	vm.runInContext(
		[
			extractFunctionSource(source, "resolveF2VUploadAssetSource"),
			extractFunctionSource(source, "shouldUseF2VCdpUpload"),
			"this.__helpers = { resolveF2VUploadAssetSource, shouldUseF2VCdpUpload };",
		].join("\n"),
		sandbox,
	);
	return { source, ...sandbox.__helpers };
}

function testAssetSourceResolution(resolveF2VUploadAssetSource) {
	assert(
		resolveF2VUploadAssetSource({
			startAsset: { localFilePath: "C:\\tmp\\hero.png", downloadUrl: "https://bad.example/ignored.png" },
		}) === "C:\\tmp\\hero.png",
		"localFilePath must be authoritative",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { downloadUrl: "https://cdn.example/hero.png" } }) ===
			"https://cdn.example/hero.png",
		"downloadUrl must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { previewUrl: "https://cdn.example/preview.png" } }) ===
			"https://cdn.example/preview.png",
		"previewUrl must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { mediaId: "media_123" } }) === "media_123",
		"mediaId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { assetId: "asset_123" } }) === "asset_123",
		"assetId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: "https://cdn.example/direct.png" }) ===
			"https://cdn.example/direct.png",
		"string startAsset must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ product_id: "prod_snake" }) === "prod_snake",
		"snake_case product_id must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ productId: "prodCamel" }) === "prodCamel",
		"camelCase productId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startImageMediaId: "img_777" }) === "img_777",
		"startImageMediaId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({}) === null,
		"jobs with no upload asset must remain on the DOM lane",
	);
}

function testCdpDispatchGate(shouldUseF2VCdpUpload) {
	assert(
		shouldUseF2VCdpUpload({ startAsset: { localFilePath: "C:\\tmp\\hero.png" } }, "C:\\tmp\\hero.png") === true,
		"resolvable asset must default to CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ product_id: "prod_123" }, "prod_123") === true,
		"product_id fallback must default to CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ startAsset: { localFilePath: "C:\\tmp\\hero.png" }, skipUpload: true }, "C:\\tmp\\hero.png") === false,
		"skipUpload=true must disable CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ startAsset: { localFilePath: "C:\\tmp\\hero.png" }, use_cdp_upload: false }, "C:\\tmp\\hero.png") === false,
		"explicit opt-out must disable CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ use_cdp_upload: true }, null) === true,
		"explicit opt-in must preserve the CDP lane",
	);
	assert(
		shouldUseF2VCdpUpload({}, null) === false,
		"jobs without upload assets must not be forced onto CDP upload",
	);
}

function testStaticDispatchWiring(source) {
	assert(
		source.includes("const f2vWantsCdpUpload = shouldUseF2VCdpUpload("),
		"handleExecuteFlowJob must use shouldUseF2VCdpUpload helper",
	);
	assert(
		source.includes("assetSource: f2vUploadAssetSource || req?.assetSource"),
		"CDP dispatch must override runner assetSource with authoritative job asset",
	);
	assert(
		source.includes('"[FlowAgent] F2V upload lane:"'),
		"dispatch must emit the F2V upload lane log line",
	);
}

function main() {
	const { source, resolveF2VUploadAssetSource, shouldUseF2VCdpUpload } = loadHelpers();
	testAssetSourceResolution(resolveF2VUploadAssetSource);
	testCdpDispatchGate(shouldUseF2VCdpUpload);
	testStaticDispatchWiring(source);
	console.log("PASS test-f2v-background-upload-dispatch");
}

main();
