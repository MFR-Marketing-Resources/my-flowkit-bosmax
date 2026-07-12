"""Phase-2 capture PASS 2 — Download Project (zero credit) + composer attach menu.

Targets (from pass-1 accessible names):
  A. DETAIL view toolbar `more_vertMore` -> menu -> "Download Project" ->
     capture the browser download (filename/MIME/bytes/sha256/zip signature).
  B. PROJECT view composer plus (`add`) -> attach menu (Add Media / Upload...)
     -> dump + Escape. No upload, no generation, zero credit.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ID = "7bdd0f87-0bec-4efa-bd96-334c5980e638"
PROJECT_URL = f"https://labs.google/fx/tools/flow/project/{PROJECT_ID}"
OUT = Path(__file__).parent / "out" / "ui_contract" / (time.strftime("%Y%m%d_%H%M%S") + "_pass2")
OUT.mkdir(parents=True, exist_ok=True)

CONTROL_DUMP = """
(() => {
  const out = [];
  const els = document.querySelectorAll('button, [role="button"], [role="menuitem"], [role="menu"] *');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const t = (el.textContent || '').trim().slice(0, 70);
    if (!t) continue;
    out.push({tag: el.tagName.toLowerCase(), role: el.getAttribute('role'),
              aria: el.getAttribute('aria-label'), text: t,
              box: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}});
  }
  return out.slice(0, 200);
})()
"""


def log(step_name, **kw):
    rec = {"t": time.strftime("%H:%M:%S"), "step": step_name, **kw}
    print(json.dumps(rec, ensure_ascii=False)[:400])
    with open(OUT / "steps.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def dump(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"))
    frags = page.evaluate(CONTROL_DUMP)
    (OUT / f"{name}.dom.json").write_text(
        json.dumps(frags, ensure_ascii=False, indent=1)[:200_000], encoding="utf-8")
    log("dump", name=name, count=len(frags))
    return frags


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = next((p for p in ctx.pages if PROJECT_ID in p.url), None) or ctx.new_page()
        page.goto(PROJECT_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(9000)
        for _ in range(2):
            if "Application error" in (page.inner_text("body") or "")[:200]:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(12000)
            else:
                break
        log("open", url=page.url)

        # ── B) composer attach menu on PROJECT view (zero credit) ───────────
        try:
            # the composer plus — accessible text 'add' next to "What do you want to create?"
            plus = page.get_by_role("button", name=re.compile(r"^add(_2Create)?$", re.I))
            if plus.count() == 0:
                plus = page.locator('button:has-text("add")').first
            plus.first.click(timeout=6000)
            page.wait_for_timeout(1800)
            dump(page, "07_composer_attach_menu")
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        except Exception as e:  # noqa: BLE001
            log("composer_attach_miss", err=str(e)[:150])

        # ── A) open the finished video detail, then toolbar More -> Download ─
        page.locator('div[role="button"]:has-text("Woman holding bottle")').first.click(timeout=8000)
        page.wait_for_timeout(5000)
        dump(page, "08_detail")

        # toolbar 'more_vertMore' (NOT the nav 'More options')
        more = page.get_by_role("button", name=re.compile(r"^more_vertMore$"))
        if more.count() == 0:
            more = page.locator('button:has-text("more_vert")').last
        more.first.click(timeout=8000)
        page.wait_for_timeout(1500)
        menu = dump(page, "09_detail_more_menu")

        # find + click Download Project, capturing the browser download
        target = page.get_by_text(re.compile(r"download project", re.I)).first
        target.wait_for(state="visible", timeout=8000)
        dl_info = {}
        with page.expect_download(timeout=120_000) as dl_ev:
            target.click()
            log("clicked_download_project")
        dl = dl_ev.value
        dest = OUT / ("download_" + re.sub(r"[^A-Za-z0-9._-]", "_",
                                           dl.suggested_filename or "project.zip"))
        dl.save_as(str(dest))
        data = dest.read_bytes()
        dl_info = {
            "suggested_filename": dl.suggested_filename,
            "url_kind": ("blob" if str(dl.url).startswith("blob:") else str(dl.url)[:40]),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "zip_signature_ok": data[:4] == b"PK\x03\x04",
        }
        log("download_captured", **dl_info)

        # archive content listing (honest artifact inspection)
        if dl_info["zip_signature_ok"]:
            import zipfile
            with zipfile.ZipFile(dest) as z:
                names = z.namelist()
            dl_info["zip_entries"] = names[:20]
            log("zip_inspected", entries=names[:10], total=len(names))

        (OUT / "RESULT.json").write_text(json.dumps(dl_info, indent=1), encoding="utf-8")
        log("DONE", out=str(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
