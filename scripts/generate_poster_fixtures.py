"""Generate per-archetype poster compositor fixtures (POSTER_BUILDER_V2).

For EVERY launch recipe: build a synthetic clean product-anchored background
(product placeholder rect inside that recipe's product_safe_region, no
marketing text), a sample Bahasa Melayu poster copy manifest via the REAL
template service, render it through the REAL production compositor
(Playwright/Chromium), and record the machine-checkable render report.

Offline, credit-free, network-free. PNGs are regenerated locally (gitignored);
the *.render_report.json files are the committed proof consumed by
tests/ui/test_poster_compositor_service_contract.py.

Usage:  python scripts/generate_poster_fixtures.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.services import poster_recipe_service  # noqa: E402
from agent.services import poster_compositor_service as compositor  # noqa: E402
from agent.services.poster_template_service import (  # noqa: E402
    build_render_manifest,
    template_contract,
)

FIXTURE_DIR = ROOT / "scripts" / "fixtures" / "poster-compositor" / "archetypes"

# Sample poster-native copy per archetype — safe BM, no medical wording, no
# prices (OFFER V1 is non-price by contract).
SAMPLE_COPY: dict[str, dict] = {
    "PRODUCT_HERO": {
        "primary_message": "Minyak warisan keluarga",
        "support_message": "Sedia di tangan bila anda perlukan.",
        "proof_points": ["Saiz poket", "Mudah dibawa"],
        "cta": "Dapatkan sekarang",
        "disclaimer": "Untuk kegunaan luaran sahaja.",
    },
    "PORTABILITY": {
        "primary_message": "Kecil di poket, sedia di tangan",
        "support_message": "",
        "proof_points": ["Saiz poket", "Ringan dibawa"],
        "cta": "Cuba hari ini",
        "disclaimer": "",
    },
    "HERITAGE_TRUST": {
        "primary_message": "Warisan turun-temurun",
        "support_message": "Resipi asal yang dikekalkan.",
        "proof_points": ["Sejak 1975", "Resipi asal", "Dipercayai ramai"],
        "cta": "Kenali warisan",
        "disclaimer": "Produk tradisional.",
    },
    "ROUTINE_USE": {
        "primary_message": "Peneman rutin harian",
        "support_message": "Untuk seisi keluarga, setiap hari.",
        "proof_points": ["Rutin pagi", "Rutin malam"],
        "cta": "Jadikan rutin",
        "disclaimer": "",
    },
    "OFFER": {
        "primary_message": "Tawaran istimewa minggu ini",
        "support_message": "",
        "proof_points": ["Stok terhad", "Penghantaran pantas"],
        "cta": "Tempah sekarang",
        "disclaimer": "Tertakluk pada terma.",
    },
    "PROBLEM_AWARE_SAFE": {
        "primary_message": "Tenang di penghujung hari",
        "support_message": "Suasana rehat yang anda cari.",
        "proof_points": ["Rutin santai", "Aroma lembut"],
        "cta": "Rasai sendiri",
        "disclaimer": "",
    },
}

# Warm scene palettes per archetype family.
_SCENE_RGB = {
    "PRODUCT_HERO": (238, 227, 210),
    "PORTABILITY": (232, 236, 238),
    "HERITAGE_TRUST": (243, 234, 214),
    "ROUTINE_USE": (236, 230, 222),
    "OFFER": (240, 238, 234),
    "PROBLEM_AWARE_SAFE": (230, 228, 236),
}
_PRODUCT_RGB = (47, 111, 94)


def make_scene_png(path: Path, safe: dict, rgb: tuple, w: int = 540, h: int = 960) -> None:
    """Synthetic clean scene: warm gradient-free field + a product placeholder
    rect inside the product_safe_region (its own 'label' band, no marketing
    text) — stands in for a clean diffusion scene."""
    x0 = int(w * float(safe["x"]) / 100)
    y0 = int(h * float(safe["y"]) / 100)
    x1 = int(w * (float(safe["x"]) + float(safe["w"])) / 100)
    y1 = int(h * (float(safe["y"]) + float(safe["h"])) / 100)
    band0 = y0 + int((y1 - y0) * 0.45)
    band1 = y0 + int((y1 - y0) * 0.6)
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            if x0 <= x < x1 and y0 <= y < y1:
                if band0 <= y < band1:
                    row += bytes((244, 236, 216))  # label band (preserved identity)
                else:
                    row += bytes(_PRODUCT_RGB)
            else:
                row += bytes(rgb)
        rows.append(b"\x00" + bytes(row))

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


async def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for recipe in poster_recipe_service.list_recipes():
        rid = recipe.recipe_id
        contract = template_contract(rid)
        safe = contract["product_safe_region"]
        bg = FIXTURE_DIR / f"{rid}.background.png"
        make_scene_png(bg, safe, _SCENE_RGB.get(recipe.archetype, (235, 230, 222)))
        copy = dict(SAMPLE_COPY[recipe.archetype])
        copy.update(
            {
                "poster_copy_set_id": f"fixture-{rid}",
                "version": 1,
                "language": "ms",
                "ai_model": "fixture",
                "prompt_version": "poster-copy-ai-v1",
            }
        )
        manifest = build_render_manifest(
            recipe_id=rid, copy_set=copy, background_local_path=str(bg)
        )
        try:
            out_path, report = await compositor.compose(
                manifest, render_id=f"fixture_{rid}"
            )
        except compositor.PosterCompositorError as exc:
            failures.append(f"{rid}: {exc.code} {exc}")
            continue
        # Copy artifacts into the fixture dir (PNG local-only; report committed).
        shutil.copyfile(out_path, FIXTURE_DIR / f"{rid}.poster.png")
        payload = report.model_dump(mode="json")
        payload["credit_spend"] = False
        payload["network"] = False
        payload["recipe_id"] = rid
        payload["template_version"] = contract["template_version"]
        (FIXTURE_DIR / f"{rid}.render_report.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        status = "OK" if report.ok else "NOT-OK"
        print(f"{status} {rid}: zones={len(report.zones)} fitted="
              f"{all(z.fitted for z in report.zones)}")
        if not report.ok:
            failures.append(f"{rid}: report not ok")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print(f"ALL {len(poster_recipe_service.list_recipes())} archetype fixtures rendered OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
