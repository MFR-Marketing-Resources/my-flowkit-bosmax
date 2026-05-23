const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { chromium } = require("playwright");

const FIXTURE_HOST = "127.0.0.1";
const EXTENSION_PATH = path.join(__dirname, "..", "extension");
const BRIDGE_SOURCE = "FLOWKIT_PLAYWRIGHT_TEST_BRIDGE";
const HARNESS_REPORT_PATH = path.join(
	os.tmpdir(),
	"flowkit-playwright-persistent-context-report.json",
);
const ONE_PIXEL_PNG = Buffer.from(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9p8Jr0YAAAAASUVORK5CYII=",
	"base64",
);

function writeHarnessReport(payload) {
	fs.writeFileSync(HARNESS_REPORT_PATH, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function buildFixtureHtml() {
	return `<!doctype html>
<html lang="en" data-flowkit-harness="playwright">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Flow Kit Playwright Harness</title>
    <style>
      body {
        font-family: ui-sans-serif, system-ui, sans-serif;
        margin: 0;
        padding: 32px;
        background: #f3f6fb;
        color: #152033;
      }
      #fixture-root {
        max-width: 900px;
        margin: 0 auto;
        padding: 24px;
        background: #ffffff;
        border: 1px solid #d6deeb;
        border-radius: 16px;
        box-shadow: 0 18px 40px rgba(21, 32, 51, 0.08);
      }
      [data-slot-container] {
        padding: 20px;
        border: 1px dashed #87a0c3;
        border-radius: 12px;
        background: #f8fbff;
      }
      #start-slot-button {
        min-width: 260px;
        min-height: 88px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        border: 1px solid #5a7db8;
        border-radius: 12px;
        background: #eaf1ff;
        color: #152033;
        font-size: 16px;
        font-weight: 700;
        cursor: pointer;
      }
      #start-slot-previews {
        margin-top: 16px;
        min-height: 96px;
        display: flex;
        align-items: center;
        gap: 12px;
      }
      #start-slot-previews img {
        width: 96px;
        height: 96px;
        object-fit: cover;
        border-radius: 10px;
        border: 1px solid #bed0ea;
      }
    </style>
  </head>
  <body>
    <main id="fixture-root">
      <h1>Flow Kit Local Fixture</h1>
      <p>Deterministic persistent-context validation surface.</p>
      <section data-slot-container="start" aria-label="Start slot container">
        <button id="start-slot-button" type="button">
          <span>Start Upload image</span>
          <div id="start-slot-previews" aria-live="polite"></div>
        </button>
      </section>
    </main>
    <script>
      (() => {
        const slotButton = document.getElementById("start-slot-button");
        const slotPreviews = document.getElementById("start-slot-previews");
        const state = {
          openCount: 0,
          lastAcceptedFileName: null,
          lastAcceptedSource: null,
        };

        function appendPreview(file) {
          const preview = document.createElement("div");
          preview.setAttribute("role", "img");
          preview.setAttribute("aria-label", file.name);
          preview.dataset.fileName = file.name;
          preview.style.width = "96px";
          preview.style.height = "96px";
          preview.style.borderRadius = "10px";
          preview.style.backgroundSize = "cover";
          preview.style.backgroundPosition = "center";
          preview.style.backgroundImage = "url(" + URL.createObjectURL(file) + ")";
          slotPreviews.replaceChildren(preview);
          document.body.dataset.lastAcceptedFileName = file.name;
        }

        function acceptFile(file, source, host) {
          console.log("[fixture] acceptFile", source, file && file.name);
          state.lastAcceptedFileName = file.name;
          state.lastAcceptedSource = source;
          document.body.dataset.lastAcceptedSource = source;
          setTimeout(() => {
            appendPreview(file);
            host.remove();
          }, 40);
        }

        function openAssetPicker() {
          state.openCount += 1;
          const host = document.createElement("div");
          host.id = "flowkit-asset-picker-host";
          const root = host.attachShadow({ mode: "open" });

          const dialog = document.createElement("div");
          dialog.setAttribute("role", "dialog");
          dialog.setAttribute("aria-label", "Upload image");
          dialog.style.cssText = "position:fixed;inset:0;display:grid;place-items:center;background:rgba(10,18,32,0.24);";

          const card = document.createElement("div");
          card.style.cssText = "width:420px;padding:20px;border-radius:16px;background:white;box-shadow:0 20px 45px rgba(0,0,0,0.18);";

          const heading = document.createElement("h2");
          heading.textContent = "Upload image";

          const copy = document.createElement("p");
          copy.textContent = "Drop or choose a file for the Start slot.";

          const input = document.createElement("input");
          input.type = "file";
          input.setAttribute("aria-label", "Upload image input");
          input.addEventListener("change", () => {
            const file = input.files && input.files[0];
            console.log("[fixture] input change", Boolean(file), file && file.name);
            if (file) acceptFile(file, "input", host);
          });

          const dropzone = document.createElement("div");
          dropzone.setAttribute("role", "presentation");
          dropzone.setAttribute("aria-label", "Upload image dropzone");
          dropzone.textContent = "Drop image here";
          dropzone.style.cssText = "margin-top:16px;padding:20px;border:2px dashed #87a0c3;border-radius:12px;";

          for (const eventName of ["dragenter", "dragover"]) {
            dropzone.addEventListener(eventName, (event) => {
              event.preventDefault();
            });
          }

          dropzone.addEventListener("drop", (event) => {
            event.preventDefault();
            const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
            console.log("[fixture] drop", Boolean(file), file && file.name);
            if (file) acceptFile(file, "drop", host);
          });

          card.append(heading, copy, input, dropzone);
          dialog.appendChild(card);
          root.appendChild(dialog);
          document.body.appendChild(host);
        }

        slotButton.addEventListener("click", openAssetPicker);
        window.__FLOWKIT_PLAYWRIGHT_FIXTURE__ = state;
      })();
    </script>
  </body>
</html>`;
}

function startFixtureServer() {
	const fixtureHtml = buildFixtureHtml();
	const server = http.createServer((req, res) => {
		if (!req.url || req.url === "/favicon.ico") {
			res.writeHead(204);
			res.end();
			return;
		}

		if (req.url === "/" || req.url.startsWith("/flow-mock")) {
			res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
			res.end(fixtureHtml);
			return;
		}

		if (req.url.startsWith("/assets/one-pixel.png")) {
			res.writeHead(200, { "content-type": "image/png" });
			res.end(ONE_PIXEL_PNG);
			return;
		}

		res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
		res.end("not found");
	});

	return new Promise((resolve, reject) => {
		server.once("error", reject);
		server.listen(0, FIXTURE_HOST, () => {
			server.removeListener("error", reject);
			const address = server.address();
			resolve({
				server,
				fixtureUrl: `http://${FIXTURE_HOST}:${address.port}/flow-mock`,
			});
		});
	});
}

async function waitForServiceWorker(context) {
	let [serviceWorker] = context.serviceWorkers();
	if (!serviceWorker) {
		serviceWorker = await context.waitForEvent("serviceworker");
	}
	return serviceWorker;
}

async function invokeContentScriptBridge(page, action, args = []) {
	return page.evaluate(
		({ bridgeSource, actionName, actionArgs }) =>
			new Promise((resolve, reject) => {
				const requestId = `${actionName}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
				const timeoutId = setTimeout(() => {
					window.removeEventListener("message", handleMessage);
					reject(new Error(`ERR_TEST_BRIDGE_TIMEOUT:${actionName}`));
				}, 20000);

				function handleMessage(event) {
					if (event.source !== window) return;
					const payload = event.data || {};
					if (
						payload.source !== bridgeSource ||
						payload.direction !== "response" ||
						payload.requestId !== requestId
					) {
						return;
					}

					clearTimeout(timeoutId);
					window.removeEventListener("message", handleMessage);
					if (!payload.ok) {
						reject(new Error(payload.error || `ERR_TEST_BRIDGE_FAILED:${actionName}`));
						return;
					}
					resolve(payload.result);
				}

				window.addEventListener("message", handleMessage);
				window.postMessage(
					{
						source: bridgeSource,
						direction: "request",
						requestId,
						action: actionName,
						args: actionArgs,
					},
					"*",
				);
			}),
		{
			bridgeSource: BRIDGE_SOURCE,
			actionName: action,
			actionArgs: args,
		},
	);
}

async function waitForBridgeReady(page) {
	let lastError = null;
	for (let attempt = 0; attempt < 20; attempt += 1) {
		try {
			return await invokeContentScriptBridge(page, "buildDiagnosticPingResponse");
		} catch (error) {
			lastError = error;
			await page.waitForTimeout(150);
		}
	}
	throw lastError || new Error("ERR_TEST_BRIDGE_NOT_READY");
}

async function readFixtureState(page) {
	return page.evaluate(() => ({
		lastAcceptedFileName: document.body.dataset.lastAcceptedFileName || null,
		lastAcceptedSource: document.body.dataset.lastAcceptedSource || null,
		openCount: window.__FLOWKIT_PLAYWRIGHT_FIXTURE__?.openCount || 0,
	}));
}

async function main() {
	console.log("RUN_FIRST npm run test:phase1b:first");
	writeHarnessReport({ status: "RUNNING" });
	let server = null;
	let context = null;
	let page = null;
	let userDataDir = null;
	let fixtureUrl = null;

	try {
		const fixtureServer = await startFixtureServer();
		server = fixtureServer.server;
		fixtureUrl = fixtureServer.fixtureUrl;
		console.log("STEP fixture server ready");
		userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "flowkit-playwright-"));

		context = await chromium.launchPersistentContext(userDataDir, {
			channel: "chromium",
			headless: true,
			args: [
				`--disable-extensions-except=${EXTENSION_PATH}`,
				`--load-extension=${EXTENSION_PATH}`,
			],
		});
		console.log("STEP persistent context launched");

		const serviceWorker = await waitForServiceWorker(context);
		console.log("STEP extension service worker ready");
		const extensionId = serviceWorker.url().split("/")[2];
		assert.ok(extensionId, "Expected MV3 extension id from service worker URL");

		const manifest = await serviceWorker.evaluate(() => chrome.runtime.getManifest());
		assert.equal(manifest.name, "Flow Kit");
		assert.equal(manifest.background.service_worker, "background.js");

		page = await context.newPage();
		page.on("console", (message) => {
			console.log(`[fixture-console] ${message.type()}: ${message.text()}`);
		});
		await page.goto(fixtureUrl, { waitUntil: "domcontentloaded" });
		console.log("STEP fixture page loaded");

		const ping = await waitForBridgeReady(page);
		console.log("STEP diagnostic bridge ready");
		assert.equal(ping.ok, true);
		assert.equal(ping.runtime_ready, true);
		assert.equal(ping.content_script_protocol_version, "FLOWKIT_DOM_V1");
		assert.ok(
			String(ping.content_build_id || "").includes("phase1a"),
			"Expected content build id in diagnostic ping",
		);

		const uploadResult = await invokeContentScriptBridge(page, "simulateFileUpload", [
			"Start",
			{
				previewUrl: `${fixtureUrl.replace("/flow-mock", "")}/assets/one-pixel.png`,
				fileName: "start-fixture.png",
			},
		]);
		console.log("STEP upload bridge completed");

		assert.equal(uploadResult.ok, true, uploadResult.detail || uploadResult.error || "Upload bridge failed");
		assert.equal(uploadResult.modalFound, true);
		assert.ok(
			typeof uploadResult.lastCheckpoint === "string" &&
				uploadResult.lastCheckpoint.length > 0,
			"Expected upload checkpoint evidence",
		);

		await page.waitForSelector('#start-slot-previews [data-file-name="start-fixture.png"]', {
			state: "visible",
			timeout: 8000,
		});

		const fixtureState = await readFixtureState(page);
		console.log("STEP fixture state collected");
		assert.equal(fixtureState.lastAcceptedFileName, "start-fixture.png");
		assert.ok(
			["input", "drop"].includes(fixtureState.lastAcceptedSource),
			"Expected deterministic acceptance source",
		);
		assert.ok(fixtureState.openCount >= 1, "Expected asset picker modal to open");

		console.log("PASS Extension service worker loaded from unpacked path");
		console.log("PASS Content script diagnostic bridge responded on local mock page");
		console.log("PASS Start-slot upload lane accepted fixture asset through persistent context");
		console.log("PASS Playwright persistent-context harness");
		writeHarnessReport({
			status: "PASS",
			run_first_command: "npm run test:phase1b:first",
			fixture_url: fixtureUrl,
			upload_result: uploadResult,
			fixture_state: fixtureState,
			reported_by: path.basename(__filename),
		});
	} finally {
		await page?.close().catch(() => {});
		await context?.close().catch(() => {});
		await new Promise((resolve) => server?.close(() => resolve()));
		if (userDataDir) {
			fs.rmSync(userDataDir, { recursive: true, force: true });
		}
	}
}

main().catch((error) => {
	writeHarnessReport({
		status: "FAIL",
		run_first_command: "npm run test:phase1b:first",
		error: String(error?.message || error),
		stack: error?.stack || null,
		reported_by: path.basename(__filename),
	});
	console.error(error.stack || String(error));
	process.exitCode = 1;
});
