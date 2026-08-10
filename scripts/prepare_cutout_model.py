#!/usr/bin/env python
"""Explicit preflight: stage + SHA-verify the local cutout model.

This is the ONLY sanctioned way the BiRefNet-general-lite ONNX artifact enters
the runtime cache. It is never downloaded implicitly at request time. Run once
after installing ``requirements-cutout.txt`` and before enabling
``LOCAL_CUTOUT_ENGINE_ENABLED=1``.

    python scripts/prepare_cutout_model.py            # download + verify + cache
    python scripts/prepare_cutout_model.py --check     # readiness only, no download

The model is cached under ``models/cutout/`` (override with
``CUTOUT_MODEL_CACHE_DIR``) and is git-ignored — weights are never committed.
Exit code 0 => READY, non-zero => a fail-closed engine state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.services import local_cutout_engine as engine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage + verify the local cutout model.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report readiness only; do not download.",
    )
    args = parser.parse_args()

    if args.check:
        result = engine.readiness(verify_checksum=True)
    else:
        result = engine.ensure_model_available(download=True)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("state") == engine.EngineReadiness.READY.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
