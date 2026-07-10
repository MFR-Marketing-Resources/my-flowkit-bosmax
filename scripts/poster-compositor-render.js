/**
 * Poster compositor renderer (POSTER_BUILDER_V2 — production service renderer).
 *
 * Manifest-driven deterministic text/component rendering: a clean generated
 * background PNG/JPEG + a poster-render-manifest-v1 → 1080×1920 poster PNG
 * where ALL marketing text (headline / support / chips / CTA / disclaimer) is
 * drawn by Chromium with shrink-to-fit, plus a machine-checkable zone report.
 *
 * Hard guarantees:
 *  - OFFLINE: local files only; no network, no generation lane, no credit spend.
 *  - HOST-SCOPED determinism: layout is deterministic on a given host with the
 *    manifest's font tokens resolved against SYSTEM fonts (no webfont
 *    download). Cross-host byte identity is NOT claimed. Every required
 *    primary font family is verified via document.fonts.check() before
 *    rendering — a missing family FAILS the render (FONT_UNAVAILABLE), it is
 *    never silently substituted.
 *  - Structured report ALWAYS written (even on failure) with errors[].
 *  - Watchdog timeout → exit 3. Manifest/background errors → exit 2.
 *    Render errors → exit 4. Success → exit 0.
 *
 * Usage:
 *   node scripts/poster-compositor-render.js --probe
 *   node scripts/poster-compositor-render.js --manifest m.json --out out.png --report report.json [--timeout 30000]
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const RENDERER_ID = "HTML_CHROMIUM_SERVICE_V1";

function arg(name, fallback) {
	const i = process.argv.indexOf(`--${name}`);
	return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function fail(code, report, reportPath, message) {
	report.errors.push(message);
	report.ok = false;
	try {
		if (reportPath) fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
	} catch (_e) {
		/* report write is best-effort on the failure path */
	}
	console.error("COMPOSITOR_ERROR:", message);
	process.exit(code);
}

function escapeHtml(s) {
	return String(s == null ? "" : s)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function mimeFor(file) {
	const ext = path.extname(file).toLowerCase();
	if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
	if (ext === ".webp") return "image/webp";
	return "image/png";
}

function intersects(a, b) {
	return !(
		a.x + a.w <= b.x ||
		b.x + b.w <= a.x ||
		a.y + a.h <= b.y ||
		b.y + b.h <= a.y
	);
}

const DEFAULT_FONT_STACK = "'Segoe UI', Arial, sans-serif";
// CSS generic families always resolve; only named families need verification.
const GENERIC_FAMILIES = new Set(["sans-serif", "serif", "monospace", "system-ui", "cursive", "fantasy"]);

function primaryFamily(familyStack) {
	const first = String(familyStack || DEFAULT_FONT_STACK).split(",")[0].trim();
	return first.replace(/^['"]|['"]$/g, "");
}

function requiredFontFamilies(manifest) {
	const tokens = manifest.font_tokens || {};
	const families = (manifest.zones || []).map((z) => {
		const token = tokens[z.font_token] || tokens.body || {};
		return primaryFamily(token.family);
	});
	return Array.from(new Set(families)).filter((f) => f && !GENERIC_FAMILIES.has(f.toLowerCase()));
}

function fontCss(token) {
	return (
		`font-family:${token.family || "'Segoe UI', Arial, sans-serif"};` +
		`font-size:${token.size || 28}px;font-weight:${token.weight || 400};` +
		`color:${token.color || "#1c1c1c"};line-height:${token.line_height || 1.2};` +
		`letter-spacing:${token.letter_spacing || "0px"};`
	);
}

function componentCss(zone, styles, palette) {
	if (zone.component === "chip") {
		const c = styles.chip || {};
		return (
			`background:${palette.chip_bg || c.background || "rgba(255,255,255,0.88)"};` +
			`border:${c.border || "1px solid rgba(0,0,0,0.1)"};border-radius:${c.border_radius || "999px"};` +
			`padding:${c.padding || "10px 22px"};box-shadow:${c.shadow || "none"};`
		);
	}
	if (zone.component === "cta_button") {
		const c = styles.cta_button || {};
		return (
			`background:${palette.accent || c.background || "#b23b2e"};` +
			`border-radius:${c.border_radius || "16px"};padding:${c.padding || "18px 34px"};` +
			`box-shadow:${c.shadow || "none"};`
		);
	}
	return "";
}

function buildHtml(manifest, bgDataUri) {
	const canvas = manifest.canvas || { w: 1080, h: 1920 };
	const styles = manifest.component_styles || {};
	const palette = manifest.palette || {};
	const tokens = manifest.font_tokens || {};
	const zones = (manifest.zones || [])
		.map((z) => {
			const token = tokens[z.font_token] || tokens.body || {};
			const justify =
				z.align === "center" ? "center" : z.align === "right" ? "flex-end" : "flex-start";
			const inline = z.component === "chip" || z.component === "cta_button";
			// Inline components hug their text (pill/button); plain text fills the zone.
			const spanCss =
				fontCss(token) +
				componentCss(z, styles, palette) +
				(inline ? "display:inline-flex;align-items:center;max-width:100%;" : "") +
				"box-sizing:border-box;overflow:hidden;";
			return (
				`<div data-zone="${escapeHtml(z.zone_id)}" data-base-size="${token.size || 28}" ` +
				`style="position:absolute;left:${z.rect.x}%;top:${z.rect.y}%;width:${z.rect.w}%;height:${z.rect.h}%;` +
				`display:flex;align-items:center;justify-content:${justify};box-sizing:border-box;` +
				`padding:0 10px;overflow:visible;text-align:${z.align};">` +
				`<span data-text style="${spanCss}">${escapeHtml(z.text)}</span></div>`
			);
		})
		.join("\n");
	return (
		`<!doctype html><html><head><meta charset="utf-8"><style>` +
		`html,body{margin:0;padding:0}` +
		`#canvas{position:relative;width:${canvas.w}px;height:${canvas.h}px;overflow:hidden;background:#fff}` +
		`</style></head><body><div id="canvas">` +
		`<img src="${bgDataUri}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"/>` +
		zones +
		`</div></body></html>`
	);
}

// Runs INSIDE the page: shrink-to-fit each zone, then measure final boxes.
function pageFitAndMeasure(fitPolicy) {
	const minScale = fitPolicy.min_scale || 0.6;
	const step = fitPolicy.step || 0.05;
	const results = [];
	for (const el of document.querySelectorAll("[data-zone]")) {
		const span = el.querySelector("[data-text]");
		const base = parseFloat(el.getAttribute("data-base-size")) || 28;
		let scale = 1.0;
		const zoneRect = () => el.getBoundingClientRect();
		const fits = () => {
			const zr = zoneRect();
			const sr = span.getBoundingClientRect();
			return sr.height <= zr.height + 1 && sr.width <= zr.width + 1;
		};
		while (!fits() && scale - step >= minScale - 1e-9) {
			scale = Math.round((scale - step) * 100) / 100;
			span.style.fontSize = base * scale + "px";
		}
		const zr = zoneRect();
		const sr = span.getBoundingClientRect();
		results.push({
			zone_id: el.getAttribute("data-zone"),
			box: { x: zr.x, y: zr.y, w: zr.width, h: zr.height },
			textBox: { x: sr.x, y: sr.y, w: sr.width, h: sr.height },
			font_scale: scale,
			fitted: sr.height <= zr.height + 1 && sr.width <= zr.width + 1,
			rendered_text: span.textContent,
		});
	}
	return results;
}

function pngDimensions(file) {
	const b = fs.readFileSync(file);
	return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
}

async function probe() {
	const p = chromium.executablePath();
	const ok = fs.existsSync(p);
	console.log(
		JSON.stringify({
			node: process.version,
			renderer: RENDERER_ID,
			chromium_path: p,
			chromium_installed: ok,
			font_determinism_scope: "HOST_SCOPED",
		}),
	);
	process.exit(ok ? 0 : 1);
}

async function main() {
	if (process.argv.includes("--probe")) return probe();

	const manifestPath = arg("manifest");
	const outPath = arg("out");
	const reportPath = arg("report");
	const timeoutMs = parseInt(arg("timeout", "30000"), 10);

	const report = {
		renderer: RENDERER_ID,
		canvas: null,
		output_png: {},
		zones: [],
		missing_zones: [],
		errors: [],
		credit_spend: false,
		network: false,
		ok: false,
	};

	// Watchdog: never hang the calling service.
	const watchdog = setTimeout(() => {
		fail(3, report, reportPath, `render timeout after ${timeoutMs}ms`);
	}, timeoutMs);
	watchdog.unref();

	if (!manifestPath || !outPath || !reportPath)
		fail(2, report, reportPath, "usage: --manifest <json> --out <png> --report <json>");

	let manifest;
	try {
		manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
	} catch (e) {
		fail(2, report, reportPath, `invalid manifest: ${e.message}`);
	}
	if (manifest.schema_version !== "poster-render-manifest-v1")
		fail(2, report, reportPath, `unsupported manifest schema: ${manifest.schema_version}`);
	const canvas = manifest.canvas || { w: 1080, h: 1920 };
	report.canvas = canvas;
	const bgPath = manifest.background_local_path;
	if (!bgPath || !fs.existsSync(bgPath))
		fail(2, report, reportPath, `background image not found: ${bgPath}`);
	if (!Array.isArray(manifest.zones) || manifest.zones.length === 0)
		fail(2, report, reportPath, "manifest has no zones to render");

	const bgDataUri = `data:${mimeFor(bgPath)};base64,` + fs.readFileSync(bgPath).toString("base64");

	let browser;
	let renderError = null;
	try {
		browser = await chromium.launch();
		const page = await browser.newPage({
			viewport: { width: canvas.w, height: canvas.h },
			deviceScaleFactor: 1,
		});
		await page.setContent(buildHtml(manifest, bgDataUri), { waitUntil: "load", timeout: timeoutMs });

		// FAIL-CLOSED font verification: every named primary family the manifest
		// uses must resolve on THIS host — no silent substitute fonts under a
		// "deterministic layout" claim.
		const required = requiredFontFamilies(manifest);
		const missingFonts = await page.evaluate((families) => {
			function fontFamilyLooksAvailable(family) {
				const probeText = "WwMm@#%&1234567890ilI|!";
				const escapedFamily = String(family).replace(/[\\"]/g, "\\\\$&");
				const probe = document.createElement("span");
				const baseline = document.createElement("span");
				for (const element of [probe, baseline]) {
					element.textContent = probeText;
					element.style.cssText =
						"position:absolute;visibility:hidden;white-space:nowrap;font-size:72px;font-weight:400;line-height:1;";
					document.body.appendChild(element);
				}
				try {
					return ["monospace", "serif", "sans-serif"].some((fallback) => {
						probe.style.fontFamily = `"${escapedFamily}", ${fallback}`;
						baseline.style.fontFamily = fallback;
						return (
							document.fonts.check(`16px "${escapedFamily}"`) &&
							probe.getBoundingClientRect().width !==
								baseline.getBoundingClientRect().width
						);
					});
				} finally {
					probe.remove();
					baseline.remove();
				}
			}
			return families.filter((family) => !fontFamilyLooksAvailable(family));
		}, required);
		report.fonts = {
			determinism_scope: "HOST_SCOPED",
			required_families: required,
			missing_families: missingFonts,
		};
		if (missingFonts.length > 0) {
			throw new Error(
				`FONT_UNAVAILABLE: required font families missing on this host: ${missingFonts.join(", ")}`,
			);
		}

		const measured = await page.evaluate(pageFitAndMeasure, manifest.fit_policy || {});
		await page.screenshot({
			path: outPath,
			clip: { x: 0, y: 0, width: canvas.w, height: canvas.h },
			timeout: timeoutMs,
		});

		const safe = (manifest.product_layer || {}).safe_region || { x: 0, y: 0, w: 0, h: 0 };
		const toPct = (px, total) => (px / total) * 100;
		const expected = new Set(manifest.zones.map((z) => z.zone_id));
		for (const m of measured) {
			expected.delete(m.zone_id);
			const rectPct = {
				x: toPct(m.box.x, canvas.w),
				y: toPct(m.box.y, canvas.h),
				w: toPct(m.box.w, canvas.w),
				h: toPct(m.box.h, canvas.h),
			};
			report.zones.push({
				zone_id: m.zone_id,
				rect_pct: rectPct,
				fitted: m.fitted,
				overflowed: !m.fitted,
				overlaps_product: intersects(rectPct, safe),
				font_scale: m.font_scale,
				rendered_text: m.rendered_text,
			});
		}
		report.missing_zones = Array.from(expected);
		const dims = pngDimensions(outPath);
		report.output_png = { file: path.basename(outPath), width: dims.width, height: dims.height };
		report.ok =
			report.missing_zones.length === 0 &&
			dims.width === canvas.w &&
			dims.height === canvas.h &&
			report.zones.every((z) => z.fitted && !z.overlaps_product);
	} catch (e) {
		renderError = e;
	} finally {
		// ALWAYS close the browser before any exit path (no orphaned Chromium).
		clearTimeout(watchdog);
		if (browser) await browser.close().catch(() => {});
	}
	if (renderError) fail(4, report, reportPath, `render failed: ${renderError.message}`);
	fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
	console.log(
		`RENDERED ${outPath} (${report.output_png.width}x${report.output_png.height}) ok=${report.ok}`,
	);
	process.exit(0);
}

main().catch((e) => {
	console.error("COMPOSITOR_FATAL:", e.message);
	process.exit(4);
});
