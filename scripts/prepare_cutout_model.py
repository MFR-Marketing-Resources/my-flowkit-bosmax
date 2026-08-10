#!/usr/bin/env python
"""Explicit preflight: stage + SHA-verify the local cutout model.

This is the ONLY sanctioned way a cutout ONNX artifact enters the runtime cache.
Models are never downloaded implicitly at request time. Run once after installing
``requirements-cutout.txt`` and before enabling ``LOCAL_CUTOUT_ENGINE_ENABLED=1``.

    python scripts/prepare_cutout_model.py                     # stage the DEFAULT model (u2net)
    python scripts/prepare_cutout_model.py --model u2netp      # stage a specific registry model
    python scripts/prepare_cutout_model.py --check             # readiness only, no download

The default model is the low-memory ``u2net`` (~0.45 GB peak). Other registry
models (``u2netp``, ``birefnet-general-lite``) are selectable with ``--model`` or
the ``CUTOUT_MODEL_ID`` env var. Weights are cached under ``models/cutout/``
(override with ``CUTOUT_MODEL_CACHE_DIR``) and are git-ignored — never committed.
Exit code 0 => READY, non-zero => a fail-closed engine state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.services import local_cutout_engine as engine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage + verify a local cutout model.")
    parser.add_argument("--check", action="store_true", help="Report readiness only; do not download.")
    parser.add_argument(
        "--model", default=None,
        help=f"Registry model id to stage (default: {engine.DEFAULT_MODEL_ID}). "
             f"Available: {', '.join(sorted(engine.MODEL_REGISTRY))}.",
    )
    args = parser.parse_args()

    if args.model:
        if args.model not in engine.MODEL_REGISTRY:
            print(json.dumps({"state": "UNKNOWN_MODEL_ID", "requested": args.model,
                              "available": sorted(engine.MODEL_REGISTRY)}, indent=2))
            return 1
        os.environ["CUTOUT_MODEL_ID"] = args.model

    if args.check:
        result = engine.readiness(verify_checksum=True)
    else:
        result = engine.ensure_model_available(download=True)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("state") == engine.EngineReadiness.READY.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
