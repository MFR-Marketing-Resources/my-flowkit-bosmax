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
	"flowkit-cdp-file-chooser-report.json",
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
    <title>Flow Kit CDP File Chooser Harness</title>
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
        align-items: center;
        justify-content: center;
        border: 1px solid #5a7db8;
        border-radius: 12px;
        background: #eaf1ff;
        color: #152033;
        font-size: 16px;
        font-weight: 700;
        cursor: pointer;
      }
      #start-slot-input {
        position: absolute;
        width: 1px;
        height: 1px;
        opacity: 0;
        pointer-events: none;
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
      <h1>Flow Kit CDP File Chooser Fixture</h1>
      <p>Deterministic native file chooser validation surface.</p>
      <section data-slot-container="start" aria-label="Start slot container">
        <button id="start-slot-button" type="button">Start Upload image</button>
        <input id="start-slot-input" type="file" aria-label="Upload image input" accept="image/*" />
        <div id="start-slot-previews" aria-live="polite"></div>
      </section>
    </main>
    <script>
      (() => {
        const state = {
          chooserOpenCount: 0,
          lastAcceptedFileName: null,
          lastAcceptedSource: null,
        };
        const slotButton = document.getElementById("start-slot-button");
        const slotInput = document.getElementById("start-slot-input");
        const slotPreviews = document.getElementById("start-slot-previews");

        function appendPreview(file) {
          const image = document.createElement("img");
          image.alt = file.name;
          image.dataset.fileName = file.name;
          image.src = URL.createObjectURL(file);
          slotPreviews.replaceChildren(image);
          document.body.dataset.lastAcceptedFileName = file.name;
        }

        slotButton.addEventListener("click", () => {
          state.chooserOpenCount += 1;
          document.body.dataset.chooserOpenCount = String(state.chooserOpenCount);
          slotInput.click();
        });

        slotInput.addEventListener("change", () => {
          const file = slotInput.files && slotInput.files[0];
          if (!file) return;
          state.lastAcceptedFileName = file.name;
          state.lastAcceptedSource = "cdp-input";
          document.body.dataset.lastAcceptedSource = "cdp-input";
          appendPreview(file);
        });

        window.__FLOWKIT_CDP_FIXTURE__ = state;
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

		if (req.url === "/" || req.url.startsWith("/flow-cdp")) {
			res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
			res.end(fixtureHtml);
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
				fixtureUrl: `http://${FIXTURE_HOST}:${address.port}/flow-cdp`,
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
		chooserOpenCount: Number(document.body.dataset.chooserOpenCount || "0"),
		lastAcceptedFileName: document.body.dataset.lastAcceptedFileName || null,
		lastAcceptedSource: document.body.dataset.lastAcceptedSource || null,
	}));
}

function writeFixtureFile(dirPath) {
	const filePath = path.join(dirPath, "cdp-start-fixture.png");
	fs.writeFileSync(filePath, ONE_PIXEL_PNG);
	return filePath;
}

async function main() {
	console.log("RUN_FIRST npm run test:phase2:first");
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

		userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "flowkit-cdp-playwright-"));
		const fixtureFilePath = writeFixtureFile(userDataDir);

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
		const manifest = await serviceWorker.evaluate(() => chrome.runtime.getManifest());
		assert.equal(manifest.name, "Flow Kit");
		assert.ok(manifest.permissions.includes("debugger"), "Expected debugger permission for CDP proof");

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

		const beginResult = await invokeContentScriptBridge(page, "beginCdpFileChooserProof", [
			{
				filePath: fixtureFilePath,
				expectedFileName: "cdp-start-fixture.png",
				slotLabel: "Start",
			},
		]);
		console.log("STEP cdp proof armed");
		assert.equal(beginResult.ok, true);
		assert.equal(beginResult.armed, true);

		await page.click("#start-slot-button");
		console.log("STEP native file chooser requested");

		const proofResult = await invokeContentScriptBridge(page, "waitForCdpFileChooserProofResult");
		console.log("STEP cdp proof completed");
		assert.equal(proofResult.ok, true, proofResult.error || "CDP proof failed");
		assert.equal(proofResult.method, "Page.fileChooserOpened");
		assert.ok(Number(proofResult.backendNodeId) > 0, "Expected backendNodeId from CDP event");
		assert.equal(proofResult.expectedFileName, "cdp-start-fixture.png");

		await page.waitForSelector('#start-slot-previews [data-file-name="cdp-start-fixture.png"]', {
			state: "visible",
			timeout: 8000,
		});

		const fixtureState = await readFixtureState(page);
		console.log("STEP fixture state collected");
		assert.equal(fixtureState.lastAcceptedFileName, "cdp-start-fixture.png");
		assert.equal(fixtureState.lastAcceptedSource, "cdp-input");
		assert.ok(fixtureState.chooserOpenCount >= 1, "Expected native chooser trigger");

		console.log("PASS Background debugger attached and intercepted file chooser");
		console.log("PASS DOM.setFileInputFiles populated native chooser target");
		console.log("PASS CDP file chooser proof of concept");
		writeHarnessReport({
			status: "PASS",
			run_first_command: "npm run test:phase2:first",
			fixture_url: fixtureUrl,
			fixture_file_path: fixtureFilePath,
			proof_result: proofResult,
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
		run_first_command: "npm run test:phase2:first",
		error: String(error?.message || error),
		stack: error?.stack || null,
		reported_by: path.basename(__filename),
	});
	console.error(error.stack || String(error));
	process.exitCode = 1;
});
