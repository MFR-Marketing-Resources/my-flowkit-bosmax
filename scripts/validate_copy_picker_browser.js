import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

const PORT = 4173;
const DIST_DIR = path.resolve("dashboard/dist");
const EVIDENCE_DIR = path.resolve("scripts/browser_evidence");

if (!fs.existsSync(EVIDENCE_DIR)) {
	fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
}

function getGitCommitSha() {
	try {
		return execSync("git rev-parse HEAD", { encoding: "utf8" }).trim();
	} catch (err) {
		console.error("Error deriving Git commit SHA:", err);
		return "UNKNOWN_COMMIT_SHA";
	}
}

function getBuiltAssetFile() {
	try {
		const htmlPath = path.join(DIST_DIR, "index.html");
		if (fs.existsSync(htmlPath)) {
			const html = fs.readFileSync(htmlPath, "utf8");
			const match = html.match(/src=["']\/?(assets\/index-[A-Za-z0-9_-]+\.js)["']/);
			if (match) {
				return `dist/${match[1]}`;
			}
		}
	} catch (err) {
		console.error("Error detecting compiled asset file:", err);
	}
	return "dist/assets/index.js";
}

function createServer() {
	return http.createServer((req, res) => {
		let filePath = path.join(DIST_DIR, req.url === "/" ? "index.html" : req.url.split("?")[0]);
		if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
			filePath = path.join(DIST_DIR, "index.html");
		}
		const ext = path.extname(filePath);
		const contentType =
			{
				".html": "text/html",
				".js": "application/javascript",
				".css": "text/css",
				".json": "application/json",
				".png": "image/png",
			}[ext] || "application/octet-stream";

		fs.readFile(filePath, (err, data) => {
			if (err) {
				res.writeHead(500);
				res.end("Error loading file");
			} else {
				res.writeHead(200, { "Content-Type": contentType });
				res.end(data);
			}
		});
	});
}

// 25 copy sets across 4 angles
const mockCopySets = Array.from({ length: 25 }, (_, i) => {
	const angles = ["Empathy", "Urgency", "Social Proof", "Problem-Agitate"];
	const angle = angles[i % angles.length];
	const isApproved = i < 20;
	return {
		copy_set_id: `cs-prod-${String(i + 1).padStart(2, "0")}`,
		product_id: "prod-mwcb",
		angle,
		hook: `Formulasi Herba Khusus Untuk Lenguh Sendi (${angle}) #${i + 1}`,
		subhook: `Minyak Warisan Cap Burung 25ml — resapan pantas tanpa rasa melekit #${i + 1}`,
		usp_set: ["100% Bahan Asli", "Lulus KKM", "Resapan Pantas"],
		cta: "Dapatkan Sekarang Dengan Diskaun 30%",
		platform: "TIKTOK",
		language: "MS",
		route_type: "UGC",
		formula_family: "PAS",
		status: isApproved ? "COPY_APPROVED" : "COPY_REVIEW_REQUIRED",
		dedupe_key: `dedupe-${i + 1}`,
		source: "manual",
		provenance: {},
		claim_review: { safety: { safe: true } },
		approved_at: isApproved ? "2026-07-28 08:00:00" : undefined,
		approved_by: isApproved ? "operator" : undefined,
	};
});

const mockProducts = [
	{
		id: "prod-mwcb",
		raw_product_title: "Minyak Warisan Cap Burung 25ml",
		product_display_name: "MINYAK WARISAN CAP BURUNG 25ML",
		product_short_name: "MWCB 25ML",
		reference_only: false,
		source: "MANUAL",
	},
];

const mockAvatars = [
	{ avatar_code: "BOS_F_ALYA_01", display_name: "Alya (Melayu Wanita 25-30)" },
	{ avatar_code: "BOS_M_ADAM_01", display_name: "Adam (Melayu Lelaki 30-35)" },
];

const mockPromptConfig = {
	defaults: {
		generation_mode: "SINGLE",
		target_language: "MS",
		camera_style: "DEFAULT_UGC",
		character_presence: "VISIBLE_CREATOR",
		creator_persona: "DEFAULT_CREATOR",
		block_duration_seconds: 8,
	},
	allowed_block_durations_seconds: [6, 8, 10, 12, 15, 20],
	language_wps_policy: { MS: { body_wps: 2.2 } },
	shot_count_policy: { "8": { min: 2, max: 4 } },
	persona_registry: [{ id: "P1", name: "Malay Female Presenter" }],
	persona_composer: {
		genders: [{ id: "FEMALE", label_ms: "Wanita" }],
		ethnicities: [{ id: "MALAY", label: "Melayu" }],
		age_ranges: [{ id: "YOUNG_ADULT", label: "20-30 tahun" }],
		bundles: [{ id: "CASUAL_HOME", label: "Kasual Rumah", allowed_genders: ["FEMALE"] }],
	},
};

async function runBrowserValidation() {
	const server = createServer();
	await new Promise((resolve) => server.listen(PORT, resolve));
	console.log(`Local test server running at http://localhost:${PORT}`);

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	const capturedCompilePayloads = [];

	// Intercept API routes wildcard
	await page.route("**/*", (route) => {
		const url = route.request().url();
		const method = route.request().method();

		if (
			method === "POST" &&
			(url.includes("/api/workspace/ugc-video-prompt-compile") ||
				url.includes("/api/workspace/execution-package"))
		) {
			try {
				const postData = route.request().postData();
				if (postData) {
					capturedCompilePayloads.push(JSON.parse(postData));
				}
			} catch (err) {}
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({
					final_compiled_prompt_text: "SECTION 1 - ROLE & OBJECTIVE...",
					prompt_blocks: [
						{
							block_index: 1,
							duration_seconds: 8,
							engine_prompt_text:
								"SECTION 3 - CONTINUITY & STATE LOCK\nThe presenter is a Malaysian young adult woman with light-medium skin...",
						},
					],
					compiler_version: "v1",
					total_duration_seconds: 8,
					camera_style: "UGC_IPHONE_RAW",
					character_presence: "VISIBLE_CREATOR",
					creator_persona: "BOS_F_ALYA_01",
					avatar_id: "BOS_F_ALYA_01",
				}),
			});
		}

		if (url.includes("/api/workspace/prompt-compiler-config")) {
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify(mockPromptConfig),
			});
		}
		if (url.includes("/api/products")) {
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({ items: mockProducts, products: mockProducts }),
			});
		}
		if (url.includes("/api/copy-sets")) {
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({ items: mockCopySets }),
			});
		}
		if (url.includes("/api/workspace/avatar-registry")) {
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({ avatars: mockAvatars }),
			});
		}
		if (url.includes("/api/workspace/scene-context-registry") || url.includes("/api/workspace/scene-registry")) {
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({ scenes: [] }),
			});
		}
		if (url.includes("/api/workspace/package-readiness") || url.includes("/api/workspace/packages/readiness") || url.includes("/api/copywriting-readiness")) {
			return route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({
					ready_for_generation: true,
					items: [
						{
							product_id: "prod-mwcb",
							readiness_status: "READY",
							detail: "Product is ready for video generation.",
							blocker: null,
							checklist: [
								{ key: "product", label: "Product Info", ready: true, detail: "Product exists" },
								{ key: "copy", label: "Copywriting", ready: true, detail: "Approved copy exists" },
							],
							quick_actions: {
								smart_registration_path: "",
								approved_packages_path: "",
								products_path: "",
							},
						},
					],
				}),
			});
		}
		return route.continue();
	});

	const results = [];

	try {
		console.log("Navigating to Operator Page (/operator/t2v)...");
		await page.goto(`http://localhost:${PORT}/operator/t2v`, { waitUntil: "networkidle" });
		await page.waitForTimeout(1000);

		// Click product selector dropdown trigger if product is not selected
		const selectTrigger = page.locator("text=Search and select product...").or(page.locator("text=Minyak Warisan Cap Burung"));
		if ((await selectTrigger.count()) > 0) {
			console.log("Found product selector trigger, clicking...");
			await selectTrigger.first().click();
			await page.waitForTimeout(300);

			const option = page.locator('[data-product-id="prod-mwcb"]').or(page.locator("text=Minyak Warisan Cap Burung 25ml"));
			if ((await option.count()) > 0) {
				console.log("Selecting MWCB product option...");
				await option.first().click();
				await page.waitForTimeout(500);
			}
		}

		await page.screenshot({ path: path.join(EVIDENCE_DIR, "01_operator_page_loaded.png") });

		// Check 1: 10-item pagination on load
		const rowsPage1 = await page.$$('[data-testid="copy-set-row"]');
		console.log(`Page 1 visible rows: ${rowsPage1.length}`);
		const paginationMatch = await page.locator("text=Showing 1–10 of 25").count();

		results.push({
			surface: "Operator Workspace — Copy Selection",
			route: "/operator/t2v",
			check: "10-item pagination on load",
			expected: 10,
			actual: rowsPage1.length,
			passed: rowsPage1.length === 10 && paginationMatch > 0,
		});

		// Check 2: Angle Narrowing Filter
		console.log("Testing Angle Filter...");
		await page.selectOption('[data-testid="copy-angle-filter"]', "Empathy");
		await page.waitForTimeout(300);
		const filteredRows = await page.$$('[data-testid="copy-set-row"]');
		const empathyCount = mockCopySets.filter((c) => c.angle === "Empathy").length;
		console.log(`Filtered rows for Empathy: ${filteredRows.length} (expected: ${empathyCount})`);

		results.push({
			surface: "Operator Workspace — Copy Selection",
			route: "/operator/t2v",
			check: "Angle Narrowing Filter (Empathy)",
			expected: empathyCount,
			actual: filteredRows.length,
			passed: filteredRows.length === empathyCount,
		});

		await page.screenshot({ path: path.join(EVIDENCE_DIR, "02_angle_filtered_empathy.png") });

		// Check 3: Reset angle filter to ALL and test pagination navigation
		await page.selectOption('[data-testid="copy-angle-filter"]', "ALL");
		await page.click("button:has-text('Next')");
		await page.waitForTimeout(300);
		const rowsPage2 = await page.$$('[data-testid="copy-set-row"]');
		console.log(`Page 2 visible rows: ${rowsPage2.length}`);

		results.push({
			surface: "Operator Workspace — Copy Selection",
			route: "/operator/t2v",
			check: "Pagination Next Page (Page 2)",
			expected: 10,
			actual: rowsPage2.length,
			passed: rowsPage2.length === 10,
		});

		await page.screenshot({ path: path.join(EVIDENCE_DIR, "03_pagination_page_2.png") });

		// Check 4: Compact Details Toggle
		const firstDetailsBtn = (await page.$$('[data-testid="toggle-copy-details"]'))[0];
		await firstDetailsBtn.click();
		await page.waitForTimeout(200);
		const detailsTextCount = await page.locator("text=Subhook:").count();

		results.push({
			surface: "Operator Workspace — Copy Selection",
			route: "/operator/t2v",
			check: "Compact Details Toggle (Expand/Collapse)",
			expected: true,
			actual: detailsTextCount > 0,
			passed: detailsTextCount > 0,
		});

		// Check 6 & 7: Avatar Persona Composer & Avatar Registry Authority UI elements in T2V mode
		console.log("Verifying Avatar Persona Composer notice & Avatar Registry dropdown in T2V mode...");

		const composerHeader = await page.locator("text=Avatar Persona Composer (Drafting / Staging Helper Only)").count();
		const avatarRegistrySelect = page.locator("#operator-avatar-registry");
		const hasAvatarSelect = (await avatarRegistrySelect.count()) > 0;
		console.log(`Avatar registry select count: ${await avatarRegistrySelect.count()}`);

		results.push({
			surface: "Operator Workspace — Avatar Authority",
			route: "/operator/t2v",
			check: "Avatar Persona Composer Staging Notice",
			expected: true,
			actual: composerHeader > 0,
			passed: composerHeader > 0,
		});

		results.push({
			surface: "Operator Workspace — Avatar Authority",
			route: "/operator/t2v",
			check: "Avatar Registry Authority Dropdown Present",
			expected: true,
			actual: hasAvatarSelect,
			passed: hasAvatarSelect,
		});

		// Check 8: Select Avatar Registry option FIRST, then trigger prompt compilation
		console.log("Verifying Avatar Registry payload precedence over composer persona...");
		if (hasAvatarSelect) {
			await avatarRegistrySelect.selectOption("BOS_F_ALYA_01");
			await page.waitForTimeout(300);
		}

		// Bind copy set first
		const firstSelectBtn = (await page.$$("button:has-text('Select for Final Prompt')"))[0];
		if (firstSelectBtn) {
			await firstSelectBtn.click();
			await page.waitForTimeout(300);
		}
		const boundNotice = await page.locator("text=Copy Set bound to final prompt generation").count();

		results.push({
			surface: "Operator Workspace — Copy Selection",
			route: "/operator/t2v",
			check: "Approved Copy Set Selection Binding",
			expected: true,
			actual: boundNotice > 0,
			passed: boundNotice > 0,
		});

		await page.screenshot({ path: path.join(EVIDENCE_DIR, "04_copy_set_selected_bound.png") });

		// Trigger prompt preview load via Step 3 Load Package button
		const loadBtn = page.locator('[data-testid="action-load-hybrid-package"]').or(page.locator("button:has-text('Load T2V Package')")).or(page.locator("button:has-text('Load Package')"));
		if ((await loadBtn.count()) > 0) {
			console.log("Clicking Load T2V Package button to trigger compile request...");
			await loadBtn.first().click();
			await page.waitForTimeout(500);
		}

		const lastPayload = capturedCompilePayloads[capturedCompilePayloads.length - 1];
		const payloadAvatarId = lastPayload?.avatar_id;
		const payloadCreatorPersona = lastPayload?.creator_persona;
		console.log("Captured Compile Payload:", JSON.stringify(lastPayload));

		const authorityPassed =
			payloadAvatarId === "BOS_F_ALYA_01" &&
			payloadCreatorPersona === "BOS_F_ALYA_01" &&
			!String(payloadCreatorPersona).startsWith("AVX_");

		results.push({
			surface: "Operator Workspace — Avatar Authority",
			route: "/operator/t2v",
			check: "Avatar Registry Payload Precedence (API Payload Level)",
			expected: "BOS_F_ALYA_01",
			actual: payloadCreatorPersona || "none",
			passed: authorityPassed,
		});

		await page.screenshot({ path: path.join(EVIDENCE_DIR, "05_avatar_registry_authority.png") });

	} catch (err) {
		console.error("Browser validation error:", err);
	} finally {
		await browser.close();
		server.close();
	}

	const allPassed = results.every((r) => r.passed);
	const summary = {
		timestamp: new Date().toISOString(),
		loaded_commit_sha: getGitCommitSha(),
		compiled_bundle_asset: getBuiltAssetFile(),
		all_passed: allPassed,
		results,
	};

	fs.writeFileSync("scripts/browser_uat_results.json", JSON.stringify(summary, null, 2));
	console.log("\n============================================");
	console.log(`Browser Validation Result: ${allPassed ? "PASS" : "FAIL"}`);
	console.log("============================================\n");
	console.log(JSON.stringify(summary, null, 2));
}

runBrowserValidation();
