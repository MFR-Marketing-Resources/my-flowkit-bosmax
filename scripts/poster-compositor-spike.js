/**
 * Phase 2A — Poster compositor spike (Playwright/Chromium renderer).
 *
 * Proves the deterministic-compositor concept ONLY: a clean, product-anchored
 * background PNG + an overlay_spec (recipe zones) -> a crisp 1080x1920 poster PNG
 * where text is drawn by the browser (real fonts), NOT by diffusion.
 *
 * Scope guardrails (Phase 2A):
 *  - LOCAL files only. No network, no image-generation lane, no credit spend.
 *  - No backend endpoint, no UI, no 2B service, no 2C UI.
 *  - Not production quality; fonts are system fonts (Noto bundling is Phase 2D).
 *
 * Product-identity rule (audit correction #3): the background PRESERVES the real
 * product label/logo/cap/packaging (product truth); only GENERATED MARKETING
 * TEXT is absent so the compositor owns it. Overlay zones must never cover the
 * product hero (product_safe_region) — enforced + asserted below.
 *
 * Usage:
 *   node scripts/poster-compositor-spike.js --probe          # runtime availability
 *   node scripts/poster-compositor-spike.js --make-sample-bg # write sample_background.png
 *   node scripts/poster-compositor-spike.js                  # compose -> spike_output.png + rendered_zones.json
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const CANVAS = { w: 1080, h: 1920 };
const FIXTURES = path.join(__dirname, "fixtures", "poster-compositor");
const OVERLAY_PATH = path.join(FIXTURES, "sample_overlay_spec.json");
const SAFE_PATH = path.join(FIXTURES, "sample_product_safe_region.json");
const BG_PATH = path.join(FIXTURES, "sample_background.png");
const OUT_PNG = path.join(FIXTURES, "spike_output.png");
const OUT_ZONES = path.join(FIXTURES, "rendered_zones.json");

// font_role -> concrete style. System fonts for the spike (Noto bundling = Phase 2D).
const FONT_ROLE = {
	display: { size: 76, weight: 800 },
	headline: { size: 76, weight: 800 },
	subhead: { size: 34, weight: 600 },
	chip: { size: 26, weight: 600 },
	button: { size: 30, weight: 800 },
	caption: { size: 22, weight: 500 },
	body: { size: 28, weight: 400 },
};

function escapeHtml(s) {
	return String(s == null ? "" : s)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;");
}

function readJson(p) {
	return JSON.parse(fs.readFileSync(p, "utf8"));
}

/** Rectangles (percent) intersect? */
function intersects(a, b) {
	return !(
		a.x + a.w <= b.x ||
		b.x + b.w <= a.x ||
		a.y + a.h <= b.y ||
		b.y + b.h <= a.y
	);
}

async function withPage(fn) {
	const browser = await chromium.launch();
	try {
		const page = await browser.newPage({
			viewport: { width: CANVAS.w, height: CANVAS.h },
			deviceScaleFactor: 1,
		});
		return await fn(page);
	} finally {
		await browser.close();
	}
}

/** Simulate a CLEAN, product-anchored background: warm scene + a product
 * placeholder (with its OWN label preserved) in the product_safe_region, and NO
 * marketing headline/CTA text. */
async function makeSampleBackground() {
	const safe = readJson(SAFE_PATH).product_safe_region;
	const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;padding:0}
    #c{position:relative;width:${CANVAS.w}px;height:${CANVAS.h}px;overflow:hidden;
       background:linear-gradient(160deg,#efe6da 0%,#e6d3bf 55%,#d8c2a6 100%)}
    #prod{position:absolute;left:${safe.x}%;top:${safe.y}%;width:${safe.w}%;height:${safe.h}%;
       display:flex;align-items:center;justify-content:center;border-radius:24px;
       background:linear-gradient(180deg,#2f6f5e,#1f5145);box-shadow:0 30px 60px rgba(0,0,0,.25);
       color:#f4ecd8;font-family:'Segoe UI',Arial,sans-serif;text-align:center}
    #prod b{font-size:34px;letter-spacing:1px}
  </style></head><body><div id="c">
    <div id="prod"><div><b>MINYAK WARISAN</b><br/>TOK CAP BURUNG<br/><small>25ml · label preserved</small></div></div>
  </div></body></html>`;
	await withPage(async (page) => {
		await page.setContent(html, { waitUntil: "load" });
		await page.screenshot({ path: BG_PATH, clip: { x: 0, y: 0, ...{ width: CANVAS.w, height: CANVAS.h } } });
	});
	console.log("WROTE " + BG_PATH);
}

function buildComposeHtml(bgDataUri, overlay) {
	const zones = overlay.zones
		.map((z) => {
			const f = FONT_ROLE[z.font_role] || FONT_ROLE.body;
			const justify =
				z.align === "center" ? "center" : z.align === "right" ? "flex-end" : "flex-start";
			return `<div data-zone="${z.zone_id}" style="position:absolute;left:${z.x}%;top:${z.y}%;width:${z.w}%;height:${z.h}%;
        display:flex;align-items:center;justify-content:${justify};box-sizing:border-box;padding:0 10px;overflow:hidden;
        font-family:'Segoe UI',Arial,sans-serif;font-weight:${f.weight};font-size:${f.size}px;line-height:1.1;
        text-align:${z.align};color:#161616;">
        <span data-text style="max-height:100%;overflow:hidden">${escapeHtml(z.text)}</span></div>`;
		})
		.join("\n");
	return `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;padding:0}
    #canvas{position:relative;width:${CANVAS.w}px;height:${CANVAS.h}px;overflow:hidden;background:#fff}
  </style></head><body><div id="canvas">
    <img src="${bgDataUri}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"/>
    ${zones}
  </div></body></html>`;
}

function pngDimensions(file) {
	// PNG IHDR: width @ byte 16, height @ byte 20 (big-endian uint32).
	const b = fs.readFileSync(file);
	return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
}

async function compose() {
	if (!fs.existsSync(BG_PATH)) await makeSampleBackground();
	const overlay = readJson(OVERLAY_PATH);
	const safe = readJson(SAFE_PATH).product_safe_region;
	const bgDataUri =
		"data:image/png;base64," + fs.readFileSync(BG_PATH).toString("base64");

	const measured = await withPage(async (page) => {
		await page.setContent(buildComposeHtml(bgDataUri, overlay), { waitUntil: "load" });
		await page.screenshot({ path: OUT_PNG, clip: { x: 0, y: 0, width: CANVAS.w, height: CANVAS.h } });
		return page.$$eval("[data-zone]", (els) =>
			els.map((el) => {
				const r = el.getBoundingClientRect();
				const span = el.querySelector("[data-text]");
				const sr = span.getBoundingClientRect();
				return {
					zone_id: el.getAttribute("data-zone"),
					box: { x: r.x, y: r.y, w: r.width, h: r.height },
					textBox: { x: sr.x, y: sr.y, w: sr.width, h: sr.height },
				};
			}),
		);
	});

	const toPct = (px, total) => (px / total) * 100;
	const zones = measured.map((m) => {
		const rectPct = {
			x: toPct(m.box.x, CANVAS.w),
			y: toPct(m.box.y, CANVAS.h),
			w: toPct(m.box.w, CANVAS.w),
			h: toPct(m.box.h, CANVAS.h),
		};
		// Text fits inside its zone (no vertical overflow) — 1px tolerance.
		const fitted = m.textBox.h <= m.box.h + 1;
		// Invariant: the zone must NOT overlap the product hero region.
		const overlaps_product = intersects(rectPct, safe);
		return {
			zone_id: m.zone_id,
			rect_pct: rectPct,
			fitted,
			overflowed: !fitted,
			overlaps_product,
		};
	});

	const dims = pngDimensions(OUT_PNG);
	const report = {
		renderer: "HTML_CHROMIUM_v1_spike",
		phase: "2A",
		canvas: CANVAS,
		output_png: { file: path.basename(OUT_PNG), width: dims.width, height: dims.height },
		product_safe_region: safe,
		zones,
		credit_spend: false,
		network: false,
		note: "Local spike. Not production. System fonts (Noto bundling = Phase 2D).",
	};
	fs.writeFileSync(OUT_ZONES, JSON.stringify(report, null, 2) + "\n");
	console.log("WROTE " + OUT_PNG + " (" + dims.width + "x" + dims.height + ")");
	console.log("WROTE " + OUT_ZONES);

	// Fail loudly if any invariant is violated (so a bad author is caught).
	const overlaps = zones.filter((z) => z.overlaps_product).map((z) => z.zone_id);
	const overflow = zones.filter((z) => z.overflowed).map((z) => z.zone_id);
	if (dims.width !== CANVAS.w || dims.height !== CANVAS.h)
		throw new Error(`bad dimensions ${dims.width}x${dims.height}`);
	if (overlaps.length) throw new Error("zones overlap product_safe_region: " + overlaps.join(","));
	if (overflow.length) throw new Error("zones overflow: " + overflow.join(","));
	console.log("OK all zones fitted + clear of product region");
}

function probe() {
	const p = chromium.executablePath();
	const ok = fs.existsSync(p);
	console.log(JSON.stringify({ node: process.version, chromium_path: p, chromium_installed: ok }));
	if (!ok) process.exit(1);
}

(async () => {
	const arg = process.argv[2] || "";
	if (arg === "--probe") return probe();
	if (arg === "--make-sample-bg") return makeSampleBackground();
	await compose();
})().catch((e) => {
	console.error("SPIKE_ERROR:", e.message);
	process.exit(1);
});
