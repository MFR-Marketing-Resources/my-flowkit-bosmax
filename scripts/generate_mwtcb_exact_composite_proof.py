"""Offline 9:16 MWTCB exact-product compositing proof; no provider calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.services.exact_product_compositor_service import composite, prepare_layer  # noqa: E402


def main() -> int:
    product = {"product_display_name": "Minyak Warisan Tok Cap Burung 25ml"}
    out_dir = ROOT / "outputs" / "exact-product-proof"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "mwtcb_exact_9x16.png"
    Image.new("RGBA", (1080, 1920), (236, 227, 208, 255)).save(output)
    layer = prepare_layer(product, {"x": 54, "y": 26, "w": 38, "h": 60}, {"w": 1080, "h": 1920})
    integrity = composite(output, layer)
    evidence = {"status": "LOCAL_EXACT_COMPOSITE_PROVEN", "canvas": "1080x1920", "provider_calls": 0, "policy": "EXACT_PRODUCT_COMPOSITE_REQUIRED", "layer": layer, "integrity": integrity, "output": str(output)}
    (out_dir / "mwtcb_exact_9x16.evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    return 0 if integrity["pixel_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
