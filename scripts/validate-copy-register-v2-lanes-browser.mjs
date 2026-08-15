import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const baseUrl = process.env.COPY_REGISTER_BASE_URL || "http://127.0.0.1:8114";
const evidencePath = process.env.COPY_REGISTER_LANE_BROWSER_EVIDENCE_PATH || "";
const browserExecutable = process.env.COPY_REGISTER_BROWSER_EXECUTABLE || [
	"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
	"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].find((candidate) => fs.existsSync(candidate));

const lanes = [
	{ lane: "T2V", route: "/operator/t2v", expected: "/operator/hybrid", state: "DORMANT_REDIRECTED" },
	{ lane: "F2V", route: "/operator/f2v", expected: "/operator/hybrid", state: "DORMANT_REDIRECTED" },
	{ lane: "HYBRID", route: "/operator/hybrid", expected: "/operator/hybrid", state: "ACTIVE" },
	{ lane: "I2V", route: "/operator/i2v", expected: "/operator/hybrid", state: "DORMANT_REDIRECTED" },
	{ lane: "FACELESS", route: "/operator/faceless", expected: "/operator/faceless", state: "ACTIVE" },
	{ lane: "MONTAGE", route: "/operator/montage", expected: "/operator/montage", state: "ACTIVE" },
	{ lane: "PRODUCTION_STUDIO_P6", route: "/production-studio", expected: "/production-studio", state: "ACTIVE" },
	{ lane: "IMAGE_GEN", route: "/operator/img", expected: "/creative/poster-builder", state: "DORMANT_REDIRECTED" },
	{ lane: "IMG_FASTLANE", route: "/assets/img-fastlane", expected: "/creative/poster-builder", state: "DORMANT_REDIRECTED" },
	{ lane: "IMG_COCKPIT", route: "/assets/img-cockpit", expected: "/creative/poster-builder", state: "DORMANT_REDIRECTED" },
	{ lane: "POSTER_BUILDER", route: "/creative/poster-builder", expected: "/creative/poster-builder", state: "ACTIVE" },
];

const browser = await chromium.launch({
	headless: true,
	...(browserExecutable ? { executablePath: browserExecutable } : {}),
});
const results = [];

try {
	for (const descriptor of lanes) {
		const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
		const page = await context.newPage();
		page.setDefaultTimeout(60_000);
		const consoleProblems = [];
		page.on("console", (message) => {
			if (["warning", "error"].includes(message.type())) {
				consoleProblems.push({ type: message.type(), text: message.text() });
			}
		});
		await page.goto(`${baseUrl}${descriptor.route}`, { waitUntil: "domcontentloaded" });
		await page.waitForURL((url) => url.pathname === descriptor.expected);
		await page.locator("main").first().waitFor();
		const finalPath = new URL(page.url()).pathname;
		const heading = await page.locator("h1").first().textContent().catch(() => null);
		results.push({
			...descriptor,
			final_path: finalPath,
			heading,
			console_problems: consoleProblems,
			passed: finalPath === descriptor.expected && consoleProblems.length === 0,
		});
		await context.close();
	}
} finally {
	await browser.close();
}

const report = {
	base_url: baseUrl,
	lane_count: results.length,
	passed: results.length === 11 && results.every((item) => item.passed),
	results,
};
if (evidencePath) {
	fs.mkdirSync(path.dirname(path.resolve(evidencePath)), { recursive: true });
	fs.writeFileSync(evidencePath, `${JSON.stringify(report, null, 2)}\n`);
}
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
