"""Phase-2 CURRENT-UI CONTRACT CAPTURE — zero credit, stop-before-submit.

Owner-authorized discovery (BOSMAX_SEV0_VIDEO_PIPELINE_PHASED_CLOSURE): capture
the CURRENT Google Flow UI contract needed by the targeted UI driver —

  1. project view: video card identity;
  2. video detail + timeline entry;
  3. Add Clip → Extend (Veo 3.1 - Lite) menu;
  4. Extend prompt field (STOP — never submit);
  5. three-dot menu → Download Project (zero-credit; captures the browser
     download event + bytes metadata);
  6. composer reference-attachment surface (+ Add Media controls).

Every step records: accessible role/name snapshots, aria/data attributes,
sanitized DOM fragments and screenshots into out/ui_contract/<ts>/.

HARD SAFETY: no Generate, no Extend submit, no approval, no credit spend.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ID = "7bdd0f87-0bec-4efa-bd96-334c5980e638"
PROJECT_URL = f"https://labs.google/fx/tools/flow/project/{PROJECT_ID}"
OUT = Path(__file__).parent / "out" / "ui_contract" / time.strftime("%Y%m%d_%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)

FORBIDDEN_CLICK = re.compile(
    r"(generate|approve|submit|create video|kirim|jana)", re.I)


def log(step_name, **kw):
    rec = {"t": time.strftime("%H:%M:%S"), "step": step_name, **kw}
    print(json.dumps(rec, ensure_ascii=False)[:400])
    with open(OUT / "steps.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def snap(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    # accessibility snapshot (roles/names) — the selector-stability authority
    ax = page.accessibility.snapshot(interesting_only=True) or {}
    (OUT / f"{name}.ax.json").write_text(
        json.dumps(ax, ensure_ascii=False, indent=1)[:400_000], encoding="utf-8")
    log("snapshot", name=name)


def dump_candidates(page, name, selector_js):
    """Sanitized DOM fragment dump for a candidate control set."""
    frags = page.evaluate(selector_js)
    (OUT / f"{name}.dom.json").write_text(
        json.dumps(frags, ensure_ascii=False, indent=1)[:200_000], encoding="utf-8")
    log("dom", name=name, count=len(frags) if isinstance(frags, list) else 1)
    return frags


CONTROL_DUMP = """
(() => {
  const out = [];
  const els = document.querySelectorAll('button, [role="button"], [role="menuitem"], a[href], input, textarea, [contenteditable="true"]');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role'),
      aria: el.getAttribute('aria-label'),
      title: el.getAttribute('title'),
      text: (el.textContent || '').trim().slice(0, 60),
      dataAttrs: Object.fromEntries(Array.from(el.attributes)
        .filter(a => a.name.startsWith('data-'))
        .map(a => [a.name, String(a.value).slice(0, 40)])),
      cls: (el.className && String(el.className).slice(0, 60)) || null,
      box: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      visible: r.width > 0 && r.height > 0,
    });
  }
  return out.slice(0, 400);
})()
"""


def click_by_text(page, patterns, step, timeout_ms=8000):
    """Click the first visible control whose accessible name/text matches, with
    the forbidden-action guard. Returns the matched descriptor."""
    for pat in patterns:
        if FORBIDDEN_CLICK.search(pat):
            raise SystemExit(f"SAFETY: refusing forbidden pattern {pat}")
        loc = page.get_by_role("button", name=re.compile(pat, re.I))
        try:
            if loc.count() == 0:
                loc = page.get_by_role("menuitem", name=re.compile(pat, re.I))
            if loc.count() == 0:
                loc = page.get_by_text(re.compile(pat, re.I)).locator(
                    "xpath=ancestor-or-self::*[self::button or @role='button' or @role='menuitem'][1]")
            loc.first.wait_for(state="visible", timeout=timeout_ms)
            desc = {"pattern": pat,
                    "name": (loc.first.get_attribute("aria-label")
                             or loc.first.text_content() or "").strip()[:80]}
            loc.first.click(timeout=timeout_ms)
            log("click", step=step, **desc)
            return desc
        except Exception as e:  # noqa: BLE001 — try the next pattern
            log("click_miss", step=step, pattern=pat, err=str(e)[:120])
    raise SystemExit(f"UI_CONTRACT_MISS: none of {patterns} found for {step}")


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = None
        for p in ctx.pages:
            if PROJECT_ID in p.url:
                page = p
                break
        if page is None:
            page = ctx.new_page()
        page.goto(PROJECT_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(9000)
        # the debug profile sometimes crashes the SPA on first load — reload once
        for _ in range(2):
            body = (page.inner_text("body") or "")[:200]
            if "Application error" in body or "client-side exception" in body:
                log("app_error_reload", body=body[:80])
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(12000)
            else:
                break
        log("open", url=page.url, body_head=(page.inner_text("body") or "")[:80])

        # ── 1) PROJECT VIEW: video cards ────────────────────────────────────
        snap(page, "01_project_view")
        dump_candidates(page, "01_controls", CONTROL_DUMP)

        # ── 6) COMPOSER / reference attach surface (observe only) ──────────
        dump_candidates(page, "01b_composer", """
(() => {
  const out = [];
  for (const el of document.querySelectorAll('textarea, [contenteditable="true"], input[type="file"], [aria-label]')) {
    const a = el.getAttribute('aria-label') || '';
    const t = (el.textContent||'').trim().slice(0,40);
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || /add|media|upload|prompt|describe|attach|image/i.test(a + ' ' + t)) {
      const r = el.getBoundingClientRect();
      out.push({tag: el.tagName.toLowerCase(), type: el.getAttribute('type'), aria: a,
                text: t, visible: r.width>0&&r.height>0,
                box:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}});
    }
  }
  return out.slice(0,120);
})()
""")

        # ── 2) OPEN VIDEO DETAIL: click the finished video card ────────────
        # cards render as clickable tiles with a play affordance + title text
        opened = False
        for sel in ['div[role="button"]:has-text("Woman holding bottle")',
                    'button:has-text("Woman holding bottle")',
                    'text="Woman holding bottle spea"',
                    '[aria-label*="Woman holding" i]']:
            try:
                page.locator(sel).first.click(timeout=5000)
                opened = True
                log("click", step="open_video_card", sel=sel)
                break
            except Exception as e:  # noqa: BLE001
                log("click_miss", step="open_video_card", sel=sel, err=str(e)[:100])
        if not opened:
            # generic: first video-ish tile
            page.locator('img, video').first.click(timeout=5000)
            log("click", step="open_video_card", sel="first media tile")
        page.wait_for_timeout(5000)
        snap(page, "02_video_detail")
        dump_candidates(page, "02_controls", CONTROL_DUMP)

        # ── 3) TIMELINE + Add Clip → Extend menu ───────────────────────────
        # the detail view (per owner screenshot) already shows the timeline with
        # an "Add Clip / Extend (Veo 3.1 - Lite)" popup entry point at the strip end
        try:
            click_by_text(page, [r"^Add to scene$", r"scene", r"timeline"],
                          "open_timeline", timeout_ms=4000)
            page.wait_for_timeout(4000)
        except SystemExit:
            log("info", note="no explicit timeline button — detail may already show timeline")
        snap(page, "03_timeline")
        dump_candidates(page, "03_controls", CONTROL_DUMP)

        # the plus / add-clip affordance on the timeline strip
        try:
            click_by_text(page, [r"add clip", r"^\+$", r"add$"],
                          "add_clip", timeout_ms=6000)
            page.wait_for_timeout(2500)
            snap(page, "04_add_clip_menu")
            dump_candidates(page, "04_menu", CONTROL_DUMP)
        except SystemExit:
            log("info", note="Add Clip control not found by name — menu may need the timeline plus icon")

        # the Extend menu item — CLICK IS ZERO-CREDIT (opens the prompt box);
        # we stop firmly before any submit.
        try:
            click_by_text(page, [r"extend \(veo", r"^extend"],
                          "extend_menu_item", timeout_ms=6000)
            page.wait_for_timeout(3000)
            snap(page, "05_extend_prompt_ready")
            dump_candidates(page, "05_controls", CONTROL_DUMP)
            log("STOP", note="EXTEND PROMPT SURFACE CAPTURED — no text entered, no submit")
            page.keyboard.press("Escape")
            page.wait_for_timeout(1500)
        except SystemExit:
            log("info", note="Extend item not reached this pass")

        # ── 5) THREE-DOT MENU → Download Project (zero credit, captured) ───
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        dl_info = {}
        try:
            click_by_text(page, [r"more", r"options", r"^⋮$"],
                          "three_dot_menu", timeout_ms=6000)
            page.wait_for_timeout(1800)
            snap(page, "06_three_dot_menu")
            dump_candidates(page, "06_menu", CONTROL_DUMP)
            with page.expect_download(timeout=90_000) as dl_ev:
                click_by_text(page, [r"download project"], "download_project")
            dl = dl_ev.value
            dest = OUT / ("download_" + re.sub(r"[^A-Za-z0-9._-]", "_", dl.suggested_filename or "project.zip"))
            dl.save_as(str(dest))
            import hashlib
            data = dest.read_bytes()
            dl_info = {"suggested_filename": dl.suggested_filename,
                       "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest(),
                       "zip_signature": data[:4].hex() == "504b0304"}
            log("download_captured", **dl_info)
        except Exception as e:  # noqa: BLE001
            log("download_miss", err=str(e)[:200])

        (OUT / "RESULT.json").write_text(json.dumps(
            {"project": PROJECT_ID, "download": dl_info, "out": str(OUT)},
            indent=1), encoding="utf-8")
        log("DONE", out=str(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
