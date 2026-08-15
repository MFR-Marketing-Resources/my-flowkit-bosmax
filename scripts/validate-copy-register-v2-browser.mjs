import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const baseUrl = process.env.COPY_REGISTER_BASE_URL || "http://127.0.0.1:8112";
const productId = process.env.COPY_REGISTER_PRODUCT_ID;
const expectedProviderState = process.env.COPY_REGISTER_PROVIDER_STATE || "READY";
const evidencePath = process.env.COPY_REGISTER_BROWSER_EVIDENCE_PATH || "";
const browserExecutable = process.env.COPY_REGISTER_BROWSER_EXECUTABLE || [
	"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
	"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].find((candidate) => fs.existsSync(candidate));

if (!productId) {
	throw new Error("COPY_REGISTER_PRODUCT_ID is required");
}
if (!["READY", "NOT_CONFIGURED", "READY_BUT_BLOCKED"].includes(expectedProviderState)) {
	throw new Error(
		"COPY_REGISTER_PROVIDER_STATE must be READY, NOT_CONFIGURED, or READY_BUT_BLOCKED",
	);
}

const targetPath = `/creative/copy-registry?product_id=${encodeURIComponent(productId)}`;
const trackedPaths = [
	"/api/copy-register/v2/formulas",
	"/api/copy-register/v2/provider-status",
	`/api/copy-register/v2/product/${productId}/truth`,
	`/api/copy-register/v2/product/${productId}/blueprints`,
	"/api/copy-register/v2/angle-options",
	"/api/copy-register/v2/blueprints/generate",
	"/approve",
	"/activate",
];

function assert(condition, message) {
	if (!condition) throw new Error(message);
}

function sanitizeResponse(pathname, body) {
	if (!body || typeof body !== "object") return body;
	if (body?.detail?.error) return body;
	if (pathname.endsWith("/provider-status")) return body;
	if (pathname.endsWith("/formulas")) {
		return {
			formula_ids: body.formulas?.map((item) => item.formula_id),
			explicit_formula_required: body.explicit_formula_required,
			default_formula: body.default_formula,
			provider_calls: body.provider_calls,
		};
	}
	if (pathname.endsWith("/truth")) {
		return {
			product_id: body.product_id,
			ready_for_copy: body.ready_for_copy,
			blockers: body.blockers,
			snapshot: body.product_truth?.snapshot,
			fact_count: body.facts?.length,
			legacy_copy_rows_read: body.legacy_copy_rows_read,
		};
	}
	if (pathname.endsWith("/angle-options")) {
		return {
			formula_id: body.formula_id,
			formula_version: body.formula_version,
			angle_count: body.angles?.length,
			fact_count: body.facts?.length,
			provider_calls: body.provider_calls,
			provider_receipt: body.provider_receipt,
			credit_spend: body.credit_spend,
			legacy_copy_rows_read: body.legacy_copy_rows_read,
		};
	}
	if (pathname.endsWith("/blueprints/generate")) {
		return {
			blueprint_id: body.blueprint?.blueprint_id,
			revision: body.blueprint?.revision,
			status: body.status,
			formula_id: body.blueprint?.formula_id,
			formula_version: body.blueprint?.formula_version,
			provider_calls: body.provider_calls,
			credit_spend: body.credit_spend,
			legacy_copy_rows_written: body.legacy_copy_rows_written,
		};
	}
	if (pathname.endsWith("/blueprints")) {
		return {
			product_id: body.product_id,
			blueprint_count: body.items?.length,
			activation: body.activation,
			legacy_copy_rows_read: body.legacy_copy_rows_read,
		};
	}
	if (pathname.endsWith("/approve")) {
		return {
			blueprint_id: body.blueprint?.blueprint_id,
			status: body.status,
			production_valid: body.production_valid,
			automatic_approval: body.automatic_approval,
		};
	}
	if (pathname.endsWith("/activate")) {
		return {
			blueprint_id: body.blueprint_id,
			activated: body.activated,
			required_lane_count: body.required_lane_count,
			automatic_approval: body.automatic_approval,
			provider_calls: body.provider_calls,
			credit_spend: body.credit_spend,
		};
	}
	return body;
}

function requestBody(request) {
	try {
		return request.postDataJSON();
	} catch {
		return request.postData();
	}
}

const browser = await chromium.launch({
	headless: true,
	...(browserExecutable ? { executablePath: browserExecutable } : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(180_000);

const network = [];
const responseTasks = [];
const consoleProblems = [];

page.on("console", (message) => {
	if (["warning", "error"].includes(message.type())) {
		consoleProblems.push({ type: message.type(), text: message.text() });
	}
});
page.on("response", (response) => {
	const request = response.request();
	const url = new URL(response.url());
	if (!trackedPaths.some((path) => url.pathname.includes(path))) return;
	responseTasks.push((async () => {
		let body = null;
		try {
			body = sanitizeResponse(url.pathname, await response.json());
		} catch {
			body = null;
		}
		network.push({
			method: request.method(),
			path: url.pathname,
			status: response.status(),
			request_body: requestBody(request),
			response_body: body,
		});
	})());
});

const result = {
	base_url: baseUrl,
	route: targetPath,
	product_id: productId,
	expected_provider_state: expectedProviderState,
	checks: {},
	network,
	console_problems: consoleProblems,
};

try {
	await page.goto(`${baseUrl}${targetPath}`, { waitUntil: "domcontentloaded" });
	await page.getByTestId("product-truth-proof").waitFor();
	result.checks.product_truth = await page.getByTestId("product-truth-proof").innerText();
	await page.getByTestId("v2-formula-picker").selectOption("PAS");

	if (expectedProviderState === "NOT_CONFIGURED") {
		assert(await page.getByTestId("generate-angle-options").isDisabled(), "angle button must fail closed");
		assert(
			(await page.getByTestId("generate-angle-disabled-reasons").innerText()).includes("Text Assist provider not configured"),
			"missing text_assist disabled reason",
		);
		const unconfiguredRequest = {
			product_id: productId,
			formula_id: "PAS",
			objective: "conversion",
		};
		const unconfiguredResponse = await page.request.post(
			`${baseUrl}/api/copy-register/v2/angle-options`,
			{ data: unconfiguredRequest },
		);
		const stableError = {
			status: unconfiguredResponse.status(),
			body: await unconfiguredResponse.json(),
		};
		network.push({
			method: "POST",
			path: "/api/copy-register/v2/angle-options",
			status: stableError.status,
			request_body: unconfiguredRequest,
			response_body: stableError.body,
		});
		assert(stableError.status === 409, `expected unconfigured 409, got ${stableError.status}`);
		assert(stableError.body?.detail?.error === "COPY_V2_TEXT_AI_NOT_CONFIGURED", "unstable text_assist error code");
		result.checks.unconfigured_error = stableError;
	} else if (expectedProviderState === "READY_BUT_BLOCKED") {
		assert(await page.getByTestId("generate-angle-options").isEnabled(), "angle button should reflect the loaded READY status");
		const angleResponse = page.waitForResponse((response) => response.url().endsWith("/api/copy-register/v2/angle-options"));
		await page.getByTestId("generate-angle-options").click();
		assert((await angleResponse).status() === 409, "configuration-race POST must fail closed");
		const renderedError = await page.getByTestId("copy-registry-error").innerText();
		assert(renderedError.includes("COPY_V2_TEXT_AI_NOT_CONFIGURED"), "stable error code was not rendered");
		assert(
			renderedError.includes("Configure and enable the existing text_assist provider lane before generating V2 copy."),
			"stable error detail was not rendered",
		);
		assert(await page.getByTestId("angle-options").count() === 0, "failed request rendered angle options");
		result.checks.rendered_error = renderedError;
	} else {
		assert(await page.getByTestId("generate-angle-options").isEnabled(), "angle button should be enabled");
		const angleResponse = page.waitForResponse((response) => response.url().endsWith("/api/copy-register/v2/angle-options"));
		await page.getByTestId("generate-angle-options").click();
		assert((await angleResponse).status() === 200, "angle POST failed");
		await page.getByTestId("angle-options").waitFor();
		await page.locator('input[name="v2-angle"]').first().check();
		assert(await page.getByTestId("generate-new-formula-copy").isDisabled(), "blueprint enabled without evidence");
		await page.getByTestId("evidence-facts").locator('input[type="checkbox"]').first().check();
		assert(await page.getByTestId("generate-new-formula-copy").isEnabled(), "blueprint did not enable after angle + evidence");

		const blueprintResponse = page.waitForResponse((response) => response.url().endsWith("/api/copy-register/v2/blueprints/generate"));
		await page.getByTestId("generate-new-formula-copy").click();
		assert((await blueprintResponse).status() === 200, "blueprint POST failed");
		await page.getByTestId("v2-blueprint-card").waitFor();
		const draftText = await page.getByTestId("copy-registry-success").innerText();
		assert(draftText.includes("created as DRAFT"), "DRAFT state was not rendered");
		result.checks.draft = draftText;

		for (const key of ["semantic", "provenance", "safety", "bridge", "duration"]) {
			await page.getByTestId(`approval-check-${key}`).check();
		}
		assert(await page.getByTestId("approve-v2-blueprint").isEnabled(), "approval did not require explicit proof");
		const approvalResponse = page.waitForResponse((response) => response.url().includes("/approve"));
		await page.getByTestId("approve-v2-blueprint").click();
		assert((await approvalResponse).status() === 200, "approval POST failed");
		await page.getByText("V2 PRODUCTION_VALID", { exact: true }).waitFor();

		const activationResponse = page.waitForResponse((response) => response.url().includes("/activate"));
		await page.getByTestId("activate-v2-blueprint").click();
		assert((await activationResponse).status() === 200, "activation POST failed");
		await page.getByText("ACTIVE · 8 REQUIRED LANES", { exact: true }).waitFor();

		await page.reload({ waitUntil: "domcontentloaded" });
		await page.getByTestId("v2-blueprint-card").waitFor();
		assert(await page.getByText("V2 PRODUCTION_VALID", { exact: true }).isVisible(), "approved blueprint did not persist across reload");
		assert(await page.getByText("ACTIVE · 8 REQUIRED LANES", { exact: true }).isVisible(), "activation did not persist across reload");
		assert(await page.getByTestId("activate-v2-blueprint").isDisabled(), "reload re-enabled an already active blueprint");
		result.checks.reload = "PRODUCTION_VALID and ACTIVE · 8 REQUIRED LANES";
	}

	await Promise.all(responseTasks);
	const expectedConsoleDiagnostics = expectedProviderState === "READY_BUT_BLOCKED"
		? consoleProblems.filter((item) => item.type === "error" && item.text.includes("status of 409"))
		: [];
	const unexpectedConsoleProblems = consoleProblems.filter(
		(item) => !expectedConsoleDiagnostics.includes(item),
	);
	result.expected_console_diagnostics = expectedConsoleDiagnostics;
	result.unexpected_console_problems = unexpectedConsoleProblems;
	assert(
		unexpectedConsoleProblems.length === 0,
		`unexpected console warnings/errors: ${JSON.stringify(unexpectedConsoleProblems)}`,
	);
	result.passed = true;
} catch (error) {
	await Promise.all(responseTasks);
	result.passed = false;
	result.error = error instanceof Error ? error.message : String(error);
} finally {
	await browser.close();
}

if (evidencePath) {
	fs.mkdirSync(path.dirname(path.resolve(evidencePath)), { recursive: true });
	fs.writeFileSync(evidencePath, `${JSON.stringify(result, null, 2)}\n`);
}
console.log(JSON.stringify(result, null, 2));
if (!result.passed) process.exitCode = 1;
