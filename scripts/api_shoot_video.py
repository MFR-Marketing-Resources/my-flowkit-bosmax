#!/usr/bin/env python3
"""One-shot Google Flow video via the aisandbox API path (no UI clicking).

Pipeline: credits/tier check -> create project -> start-frame image ->
generate video (Veo 3.1 i2v) -> poll -> print video URL.

DESIGN NOTES (proven 2026-06-28/29 — see memory project_aisandbox_api_generation_proof):
  - The whole generation mechanism (token + reCAPTCHA + aisandbox API) is alive.
    Image generation works even on freemium (NOT_PAID), zero credits burned.
  - Veo VIDEO is entitlement-gated: only PAYGATE_TIER_ONE / PAYGATE_TIER_TWO have
    a video model. A NOT_PAID account returns Google 500 / "No model for tier".
    => Video needs a PAID account (Pro/Ultra). This script refuses to burn on
       an unpaid tier.
  - reCAPTCHA is flaky on cold start (first call times out); retry warms it up.

SAFETY: dry-run by default. Nothing that burns a credit runs unless you pass
        --confirm-burn AND the account tier is paid.

USAGE:
  # 1) Dry run — proves wiring, tells you if the account can shoot. No credit.
  python scripts/api_shoot_video.py

  # 2) Real shoot (after you top up Pro/Ultra) — burns ~1 credit.
  python scripts/api_shoot_video.py --confirm-burn \
      --image-prompt "Clean vertical 9:16 product shot, soft commercial light." \
      --prompt "Gentle slow push-in, subtle motion, premium feel."

  # Use an existing start image instead of generating one:
  python scripts/api_shoot_video.py --confirm-burn --start-media-id <media_id>
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8100"
PAID_TIERS = ("PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO")
CAPTCHA_RETRIES = 5
POLL_INTERVAL = 10
POLL_TIMEOUT = 360


def _req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, (e.code, e.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return None, (0, str(e))


def _is_captcha_fail(err):
    return err and err[0] in (403, 0) and "CAPTCHA_FAILED" in str(err[1])


def _post_with_captcha_retry(path, body, label):
    """POST, retrying past reCAPTCHA cold-start timeouts."""
    last = None
    for attempt in range(1, CAPTCHA_RETRIES + 1):
        d, err = _req("POST", path, body)
        if d is not None:
            return d, None
        last = err
        if _is_captcha_fail(err):
            print(f"   [{label}] reCAPTCHA cold-start (attempt {attempt}) — retrying...")
            time.sleep(2)
            continue
        # a non-captcha error (e.g. Google 500 entitlement) — stop retrying
        return None, err
    return None, last


def _find(obj, *keys):
    """Recursively find the first truthy value for any of `keys`."""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and v:
                    return v
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
    return None


def _find_operations(obj):
    ops = _find(obj, "operations")
    return ops if isinstance(ops, list) else []


def die(msg, code=1):
    print("\n[X] " + msg)
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="Shoot one Veo video via the aisandbox API.")
    ap.add_argument("--confirm-burn", action="store_true",
                    help="Actually generate the video (burns ~1 credit). Requires a paid tier.")
    ap.add_argument("--image-prompt", default="Clean vertical 9:16 studio product shot, soft commercial lighting.")
    ap.add_argument("--prompt", default="Gentle slow push-in on the product, soft natural light, subtle motion, premium commercial feel.")
    ap.add_argument("--start-media-id", default=None, help="Use this image media_id as the start frame instead of generating one.")
    ap.add_argument("--aspect", default="VIDEO_ASPECT_RATIO_PORTRAIT")
    args = ap.parse_args()

    print("=" * 64)
    print(" Google Flow — one-shot video via aisandbox API (no UI clicking)")
    print("=" * 64)

    # --- 0) health / token ------------------------------------------------
    health, err = _req("GET", "/health", timeout=8)
    if err:
        die(f"Backend tak boleh dicapai di {BASE} — pastikan local agent berjalan. ({err})")
    if not health.get("flow_key_present"):
        die("Token Flow tiada (flow_key_present=false). Buka tab Flow & log masuk dulu.")
    if not health.get("extension_connected"):
        die("Extension tak bersambung. Pastikan extension aktif + tab Flow terbuka.")
    print("[ok] Backend hidup, token captured, extension bersambung.")

    # --- 1) tier / credits (FREE, read-only) ------------------------------
    credits, err = _req("GET", "/api/flow/credits", timeout=30)
    if err:
        die(f"Gagal baca credits: {err}")
    tier = credits.get("userPaygateTier", "?")
    bal = credits.get("credits", "?")
    print(f"[ok] Akaun: tier={tier}  credits={bal}  sku={credits.get('sku')}")

    tier_paid = tier in PAID_TIERS
    if tier_paid:
        print(f"     -> Tier BERBAYAR ({tier}) — Veo video DISOKONG. Sedia tembak.")
    else:
        print(f"     -> Tier '{tier}' BUKAN berbayar — Veo video DIGATE oleh Google.")
        if args.confirm_burn:
            die("Tak boleh tembak video atas akaun belum berbayar. Top up Pro/Ultra dulu, "
                "lepas tu jalankan semula dengan --confirm-burn.")

    # --- 2) create project ------------------------------------------------
    proj, err = _req("POST", "/api/flow/create-project-raw",
                     {"project_title": "API shoot " + time.strftime("%Y%m%d-%H%M%S")})
    if err:
        die(f"Gagal create project: {err}")
    pid = _find(proj, "projectId", "project_id", "id")
    if not pid:
        die(f"Project id tak dijumpai dalam respons: {json.dumps(proj)[:300]}")
    print(f"[ok] Project dicipta: {pid}")

    # --- 3) start frame ---------------------------------------------------
    if args.start_media_id:
        start_media = args.start_media_id
        print(f"[ok] Guna start-frame sedia ada: {start_media}")
    else:
        img_tier = tier if tier_paid else "PAYGATE_TIER_TWO"
        img, err = _post_with_captcha_retry("/api/flow/generate-image", {
            "prompt": args.image_prompt, "project_id": pid,
            "aspect_ratio": "IMAGE_ASPECT_RATIO_PORTRAIT", "user_paygate_tier": img_tier,
        }, "image")
        if err:
            die(f"Gagal generate start-frame: {err}")
        start_media = _find(img, "mediaId", "name")
        fife = _find(img, "fifeUrl")
        if not start_media:
            die(f"Start media id tak dijumpai: {json.dumps(img)[:300]}")
        print(f"[ok] Start-frame dijana: {start_media}")
        if fife:
            print(f"     URL imej: {fife}")

    # --- 4) GATE ----------------------------------------------------------
    if not args.confirm_burn:
        print("\n" + "-" * 64)
        print(" DRY-RUN SIAP. Semua wiring OK sampai gate generate-video.")
        if tier_paid:
            print(" Tier berbayar dikesan — untuk TEMBAK video sebenar (makan ~1 kredit):")
        else:
            print(" Tier belum berbayar — TOP UP Pro/Ultra dulu, kemudian:")
        print("   python scripts/api_shoot_video.py --confirm-burn")
        print("-" * 64)
        return

    # --- 5) generate video (BURNS A CREDIT) -------------------------------
    print("\n[..] Submit video (Veo 3.1 i2v) — reCAPTCHA + Google...")
    sub, err = _post_with_captcha_retry("/api/flow/generate-video", {
        "start_image_media_id": start_media, "prompt": args.prompt,
        "project_id": pid, "scene_id": "api-shoot-1",
        "aspect_ratio": args.aspect, "user_paygate_tier": tier,
    }, "video")
    if err:
        die(f"Submit video gagal: {err}\n"
            "Jika 500 INTERNAL atas akaun berbayar — kemungkinan model/tier perlu dilaras.")
    ops = _find_operations(sub)
    if not ops:
        die(f"Tiada operations dalam respons submit: {json.dumps(sub)[:300]}")
    op_name = _find(ops[0], "name") or "?"
    print(f"[ok] Video di-submit. operation={str(op_name)[:40]}  — polling...")

    # --- 6) poll ----------------------------------------------------------
    elapsed = 0
    current = ops
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        st, err = _req("POST", "/api/flow/check-status", {"operations": current}, timeout=30)
        if err:
            print(f"   poll {elapsed}s: ralat sementara {err[0]} — sambung...")
            continue
        new_ops = _find_operations(st)
        if new_ops:
            current = new_ops
        statuses = [o.get("status", "") for o in current]
        done = sum(s == "MEDIA_GENERATION_STATUS_SUCCESSFUL" for s in statuses)
        if any(s == "MEDIA_GENERATION_STATUS_FAILED" for s in statuses):
            die(f"Google laporkan operation FAILED. Full: {json.dumps(st)[:600]}")
        if done == len(current) and current:
            url = _find(st, "fifeUrl", "servingUrl", "url")
            print("\n" + "=" * 64)
            print(" [✓] VIDEO SIAP — dijana via aisandbox API, tanpa klik UI.")
            print("=" * 64)
            print(f" Project : https://labs.google/fx/tools/flow  (project {pid})")
            if url:
                print(f" Video URL: {url}")
            else:
                print(" (Buka projek di website Flow untuk tonton/download video.)")
            return
        print(f"   poll {elapsed}s/{POLL_TIMEOUT}s: {done}/{len(current)} siap...")

    die(f"Timeout poll selepas {POLL_TIMEOUT}s — video mungkin masih render; "
        "buka projek di website Flow untuk semak.")


if __name__ == "__main__":
    main()
