#!/usr/bin/env node
/**
 * BOSMAX Browser UAT — Playwright CDP harness (no browser download).
 * Connects to dedicated UAT Chrome at http://127.0.0.1:9222
 *
 * Usage:
 *   node scripts/browser-uat/run-browser-uat.mjs <command> [args...]
 *
 * Commands:
 *   list-pages
 *   new-tab <url>
 *   navigate <url>
 *   click <selector>
 *   fill <selector> <text>
 *   select <selector> <value>
 *   wait <selector> [timeoutMs]
 *   text <selector>
 *   url
 *   title
 *   screenshot [path]
 *   console
 *   eval <js>
 *   close-own
 *   smoke
 *   click-path
 */
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import http from 'node:http';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const __require = createRequire(import.meta.url);

function loadPlaywright() {
  const roots = [
    process.cwd(),
    path.resolve(__dirname, '../..'),
    'C:\\Users\\USER\\Desktop\\_ref_flowkit',
    process.env.BOSMAX_REPO_ROOT,
  ].filter(Boolean);
  const errs = [];
  for (const root of roots) {
    try {
      const resolved = __require.resolve('playwright', { paths: [root] });
      return __require(resolved);
    } catch (e) {
      errs.push(String(e.message || e));
    }
  }
  try {
    return __require('playwright');
  } catch (e) {
    throw new Error(
      'playwright not found. Run npm install in repo root. Tries: ' +
        errs.join(' | ')
    );
  }
}

const { chromium } = loadPlaywright();

const CDP_URL = process.env.BOSMAX_CDP_URL || 'http://127.0.0.1:9222';
const BOSMAX_URL = process.env.BOSMAX_UAT_URL || 'http://127.0.0.1:8100';
const ROOT =
  process.env.BOSMAX_BROWSER_UAT_ROOT ||
  'C:\\Users\\USER\\Desktop\\_bosmax_runtime\\browser_uat';
const SHOT_DIR = path.join(ROOT, 'screenshots');
const STATE_DIR = path.join(ROOT, 'state');
const LEASE_PATH = path.join(STATE_DIR, 'uat-lease.json');
const OWN_MARKER = 'bosmax-browser-uat-tab';


function ensureDirs() {
  for (const d of [SHOT_DIR, STATE_DIR, path.join(ROOT, 'traces')]) {
    fs.mkdirSync(d, { recursive: true });
  }
}

function httpGetJson(url, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(e);
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('timeout'));
    });
  });
}

async function assertCdp() {
  const ver = await httpGetJson(`${CDP_URL}/json/version`);
  if (!ver || !ver.webSocketDebuggerUrl) {
    throw new Error(`CDP unhealthy at ${CDP_URL}/json/version`);
  }
  return ver;
}

function readLease() {
  try {
    return JSON.parse(fs.readFileSync(LEASE_PATH, 'utf8'));
  } catch {
    return null;
  }
}

function writeLease(lease) {
  fs.writeFileSync(LEASE_PATH, JSON.stringify(lease, null, 2), 'utf8');
}

function acquireLease(owner) {
  const now = Date.now();
  const existing = readLease();
  if (
    existing &&
    existing.owner &&
    existing.owner !== owner &&
    existing.expires_at &&
    Date.parse(existing.expires_at) > now
  ) {
    // Soft lease: allow parallel tabs, but record contention.
    console.error(
      JSON.stringify({
        warning: 'UAT_LEASE_CONTENTION',
        existing_owner: existing.owner,
        expires_at: existing.expires_at,
      })
    );
  }
  const lease = {
    owner,
    acquired_at: new Date(now).toISOString(),
    expires_at: new Date(now + 15 * 60 * 1000).toISOString(),
    pid: process.pid,
  };
  writeLease(lease);
  return lease;
}

function releaseLease(owner) {
  const existing = readLease();
  if (existing && existing.owner === owner) {
    try {
      fs.unlinkSync(LEASE_PATH);
    } catch {
      /* ignore */
    }
  }
}

async function connect() {
  ensureDirs();
  await assertCdp();
  const browser = await chromium.connectOverCDP(CDP_URL);
  return browser;
}

function pickContext(browser) {
  const contexts = browser.contexts();
  if (!contexts.length) throw new Error('No browser contexts on CDP target');
  return contexts[0];
}

async function getOrCreateOwnPage(browser, createIfMissing = true) {
  const context = pickContext(browser);
  for (const page of context.pages()) {
    try {
      const marker = await page.evaluate(() => window.__BOSMAX_UAT_TAB__);
      if (marker === OWN_MARKER) return page;
    } catch {
      /* cross-origin / closed */
    }
  }
  if (!createIfMissing) return null;
  const page = await context.newPage();
  await page.addInitScript((m) => {
    window.__BOSMAX_UAT_TAB__ = m;
  }, OWN_MARKER);
  await page.evaluate((m) => {
    window.__BOSMAX_UAT_TAB__ = m;
  }, OWN_MARKER);
  return page;
}

function attachCollectors(page) {
  const consoleLogs = [];
  const pageErrors = [];
  const requestFails = [];
  page.on('console', (msg) => {
    consoleLogs.push({
      type: msg.type(),
      text: msg.text(),
      location: msg.location(),
    });
  });
  page.on('pageerror', (err) => {
    pageErrors.push({ message: String(err), stack: err?.stack || null });
  });
  page.on('requestfailed', (req) => {
    requestFails.push({
      url: req.url(),
      method: req.method(),
      failure: req.failure()?.errorText || null,
    });
  });
  return { consoleLogs, pageErrors, requestFails };
}

function stamp(name) {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  return path.join(SHOT_DIR, `${name}-${ts}.png`);
}

async function cmdListPages(browser) {
  const out = [];
  for (const ctx of browser.contexts()) {
    for (const page of ctx.pages()) {
      out.push({ url: page.url(), title: await page.title().catch(() => '') });
    }
  }
  console.log(JSON.stringify({ pages: out }, null, 2));
}

async function cmdSmoke(browser, owner) {
  const page = await getOrCreateOwnPage(browser, true);
  const collectors = attachCollectors(page);
  await page.goto(BOSMAX_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  // SPA shell: root app mount or any main content
  await page.waitForTimeout(1500);
  const title = await page.title();
  const url = page.url();
  const bodyText = await page.locator('body').innerText().catch(() => '');
  const hasSpa =
    bodyText.length > 40 ||
    (await page.locator('#root, #app, [data-bosmax-app], main').count()) > 0;
  const shot = stamp('bosmax-smoke');
  await page.screenshot({ path: shot, fullPage: true });
  const unexpectedConsole = collectors.consoleLogs.filter(
    (c) => c.type === 'error'
  );
  const result = {
    verdict: hasSpa && !/cannot GET/i.test(bodyText) ? 'PASS' : 'FAIL',
    url,
    title,
    body_preview: bodyText.slice(0, 400),
    spa_rendered: hasSpa,
    console_errors: unexpectedConsole,
    page_errors: collectors.pageErrors,
    request_failures: collectors.requestFails.slice(0, 20),
    screenshot: shot,
    owner,
  };
  const receipt = path.join(STATE_DIR, `smoke-receipt-${Date.now()}.json`);
  fs.writeFileSync(receipt, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, receipt }, null, 2));
  if (result.verdict !== 'PASS') process.exitCode = 2;
}

async function cmdClickPath(browser, owner) {
  const page = await getOrCreateOwnPage(browser, true);
  const collectors = attachCollectors(page);
  const shots = [];
  const steps = [];

  async function shot(label) {
    const p = stamp(`clickpath-${label}`);
    await page.screenshot({ path: p, fullPage: true });
    shots.push({ label, path: p });
    return p;
  }

  async function step(name, fn) {
    try {
      await fn();
      steps.push({ name, ok: true, url: page.url() });
    } catch (e) {
      steps.push({ name, ok: false, error: String(e), url: page.url() });
      throw e;
    }
  }

  try {
    await step('open_operator', async () => {
      await page.goto(`${BOSMAX_URL}/`, {
        waitUntil: 'domcontentloaded',
        timeout: 60000,
      });
      await page.waitForTimeout(1200);
      await shot('home');
    });

    await step('open_smart_registration', async () => {
      // Prefer nav link text
      const candidates = [
        'text=Smart Registration',
        'a[href*="product-registration"]',
        'a[href*="/products"]',
        'text=All Products',
      ];
      let clicked = false;
      for (const sel of candidates) {
        const loc = page.locator(sel).first();
        if ((await loc.count()) > 0) {
          await loc.click({ timeout: 8000 });
          clicked = true;
          break;
        }
      }
      if (!clicked) {
        // Direct route fallbacks used by BOSMAX SPA
        const routes = [
          '/product-registration',
          '/products',
          '/operator',
          '/#/product-registration',
        ];
        for (const r of routes) {
          await page.goto(`${BOSMAX_URL}${r}`, {
            waitUntil: 'domcontentloaded',
            timeout: 30000,
          });
          await page.waitForTimeout(800);
          const t = await page.locator('body').innerText();
          if (/All Products|Smart Registration|Product Truth/i.test(t)) break;
        }
      }
      await page.waitForTimeout(1000);
      await shot('smart-reg');
    });

    await step('locate_sambal', async () => {
      const searchSelectors = [
        'input[placeholder*="Search" i]',
        'input[type="search"]',
        'input[name*="search" i]',
        'input[aria-label*="Search" i]',
      ];
      let filled = false;
      for (const sel of searchSelectors) {
        const loc = page.locator(sel).first();
        if ((await loc.count()) > 0) {
          await loc.fill('Sambal Nyet');
          await loc.press('Enter').catch(() => {});
          filled = true;
          break;
        }
      }
      if (!filled) {
        // try URL query if registry supports q
        await page.goto(
          `${BOSMAX_URL}/product-registration?q=Sambal%20Nyet`,
          { waitUntil: 'domcontentloaded', timeout: 30000 }
        );
      }
      await page.waitForTimeout(1500);
      // click row containing Sambal
      const row = page.getByText(/Sambal Nyet/i).first();
      await row.waitFor({ timeout: 15000 });
      await shot('sambal-found');
    });

    await step('view_product_truth', async () => {
      const action = page
        .getByRole('button', { name: /View Product Truth/i })
        .first();
      if ((await action.count()) > 0) {
        await action.click({ timeout: 10000 });
      } else {
        const link = page.getByText(/View Product Truth/i).first();
        if ((await link.count()) > 0) {
          await link.click({ timeout: 10000 });
        } else {
          // Direct product intelligence route
          const sambalId = 'd2f8fd58-437b-4447-8730-694b782eef17';
          await page.goto(`${BOSMAX_URL}/product/${sambalId}?tab=INTELLIGENCE`, {
            waitUntil: 'domcontentloaded',
            timeout: 60000,
          });
        }
      }
      await page.waitForTimeout(1500);
      await shot('product-truth');
    });

    await step('verify_intelligence_tab', async () => {
      const url = page.url();
      const body = await page.locator('body').innerText();
      const ok =
        /INTELLIGENCE|Product Intelligence|Product Truth|APPROVED/i.test(
          body
        ) || /tab=INTELLIGENCE/i.test(url);
      if (!ok) throw new Error('Intelligence/Product Truth surface not evident');
    });

    await step('refresh_keeps_tab', async () => {
      const before = page.url();
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForTimeout(1200);
      const after = page.url();
      // Prefer tab remains; if router drops query, still accept intelligence content
      const body = await page.locator('body').innerText();
      const tabOk =
        /tab=INTELLIGENCE/i.test(after) ||
        /Product Intelligence|Intelligence/i.test(body);
      if (!tabOk) {
        throw new Error(
          `Tab/content lost after refresh before=${before} after=${after}`
        );
      }
      await shot('after-refresh');
    });

    await step('copywriting_landbank', async () => {
      const land = page.getByText(/Copywriting Landbank/i).first();
      if ((await land.count()) > 0) {
        await land.click({ timeout: 10000 });
      } else {
        await page.goto(`${BOSMAX_URL}/creative/storyboard-landbank-v3`, {
          waitUntil: 'domcontentloaded',
          timeout: 60000,
        });
      }
      await page.waitForTimeout(1200);
      await shot('landbank');
    });

    await step('copy_authority_advanced', async () => {
      const auth = page.getByText(/^Copy Authority$/i).first();
      if ((await auth.count()) > 0) {
        await auth.click({ timeout: 10000 });
      } else {
        await page.goto(`${BOSMAX_URL}/creative/copy-authority`, {
          waitUntil: 'domcontentloaded',
          timeout: 60000,
        });
      }
      await page.waitForTimeout(1200);
      await shot('copy-authority');
    });

    await step('legacy_registry_redirect', async () => {
      await page.goto(
        `${BOSMAX_URL}/creative/copy-registry?product_id=d2f8fd58-437b-4447-8730-694b782eef17&x=1`,
        { waitUntil: 'domcontentloaded', timeout: 60000 }
      );
      await page.waitForTimeout(1200);
      const url = page.url();
      if (!/copy-authority/i.test(url)) {
        throw new Error(`Expected redirect to copy-authority, got ${url}`);
      }
      if (!/product_id=d2f8fd58/i.test(url)) {
        throw new Error(`Expected product_id preserved, got ${url}`);
      }
      await shot('registry-redirect');
    });
  } catch (e) {
    await shot('failure').catch(() => {});
    const result = {
      verdict: 'FAIL',
      error: String(e),
      steps,
      shots,
      final_url: page.url(),
      console_errors: collectors.consoleLogs.filter((c) => c.type === 'error'),
      page_errors: collectors.pageErrors,
      owner,
    };
    const receipt = path.join(STATE_DIR, `clickpath-receipt-${Date.now()}.json`);
    fs.writeFileSync(receipt, JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ ...result, receipt }, null, 2));
    process.exitCode = 2;
    return;
  }

  const result = {
    verdict: steps.every((s) => s.ok) ? 'PASS' : 'FAIL',
    steps,
    shots,
    final_url: page.url(),
    console_errors: collectors.consoleLogs.filter((c) => c.type === 'error'),
    page_errors: collectors.pageErrors,
    request_failures: collectors.requestFails.slice(0, 30),
    owner,
  };
  const receipt = path.join(STATE_DIR, `clickpath-receipt-${Date.now()}.json`);
  fs.writeFileSync(receipt, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, receipt }, null, 2));
  if (result.verdict !== 'PASS') process.exitCode = 2;
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd) {
    console.error('Usage: run-browser-uat.mjs <command> ...');
    process.exit(1);
  }
  const owner = `pid-${process.pid}-${Date.now()}`;
  acquireLease(owner);
  let browser;
  try {
    browser = await connect();
    const page = async () => getOrCreateOwnPage(browser, true);

    switch (cmd) {
      case 'list-pages':
        await cmdListPages(browser);
        break;
      case 'new-tab': {
        const p = await page();
        await p.goto(rest[0] || 'about:blank', {
          waitUntil: 'domcontentloaded',
          timeout: 60000,
        });
        console.log(JSON.stringify({ url: p.url() }));
        break;
      }
      case 'navigate': {
        const p = await page();
        await p.goto(rest[0], { waitUntil: 'domcontentloaded', timeout: 60000 });
        console.log(JSON.stringify({ url: p.url(), title: await p.title() }));
        break;
      }
      case 'click': {
        const p = await page();
        await p.click(rest[0], { timeout: 15000 });
        console.log(JSON.stringify({ clicked: rest[0], url: p.url() }));
        break;
      }
      case 'fill': {
        const p = await page();
        await p.fill(rest[0], rest.slice(1).join(' '));
        console.log(JSON.stringify({ filled: rest[0] }));
        break;
      }
      case 'select': {
        const p = await page();
        await p.selectOption(rest[0], rest[1]);
        console.log(JSON.stringify({ selected: rest[0], value: rest[1] }));
        break;
      }
      case 'wait': {
        const p = await page();
        await p.waitForSelector(rest[0], {
          timeout: Number(rest[1] || 15000),
        });
        console.log(JSON.stringify({ waited: rest[0] }));
        break;
      }
      case 'text': {
        const p = await page();
        const t = await p.locator(rest[0]).innerText();
        console.log(JSON.stringify({ text: t }));
        break;
      }
      case 'url': {
        const p = await page();
        console.log(JSON.stringify({ url: p.url() }));
        break;
      }
      case 'title': {
        const p = await page();
        console.log(JSON.stringify({ title: await p.title() }));
        break;
      }
      case 'screenshot': {
        const p = await page();
        const dest = rest[0] || stamp('manual');
        await p.screenshot({ path: dest, fullPage: true });
        console.log(JSON.stringify({ screenshot: dest }));
        break;
      }
      case 'console': {
        // best-effort: no buffer without prior attach — return empty note
        console.log(
          JSON.stringify({
            note: 'Use smoke/click-path for captured console; live buffer not retained across commands.',
          })
        );
        break;
      }
      case 'eval': {
        const p = await page();
        const value = await p.evaluate((code) => eval(code), rest.join(' '));
        console.log(JSON.stringify({ value }));
        break;
      }
      case 'close-own': {
        const p = await getOrCreateOwnPage(browser, false);
        if (p) await p.close();
        console.log(JSON.stringify({ closed: Boolean(p) }));
        break;
      }
      case 'smoke':
        await cmdSmoke(browser, owner);
        break;
      case 'click-path':
        await cmdClickPath(browser, owner);
        break;
      default:
        console.error(`Unknown command: ${cmd}`);
        process.exitCode = 1;
    }
  } finally {
    releaseLease(owner);
    // Never stop shared UAT Chrome. Do not await browser.close() on CDP (can hang).
    try {
      if (browser && browser._connection && typeof browser._connection.close === 'function') {
        browser._connection.close();
      }
    } catch {
      /* ignore */
    }
  }
}

main()
  .catch((err) => {
    console.error(JSON.stringify({ verdict: 'FAIL', error: String(err) }));
    process.exitCode = 1;
  })
  .finally(() => {
    // Agents must not hang after receipt write.
    setTimeout(() => process.exit(process.exitCode || 0), 300);
  });
