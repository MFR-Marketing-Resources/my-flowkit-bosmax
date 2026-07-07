"""One-off target product poster verification (local DB)."""
from __future__ import annotations

import asyncio
import sys

IDS = {
    "Bosmax Oil 10 ML": "b460ffbd-7d9d-4f6b-a570-0e9b1056439a",
    "Bosmax Herbs 5 ML": "90349f8c-9e14-4efe-988e-76ec60ea31f4",
    "Minyak Warisan 25ml": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
}

SAFE_REQUEST = {
    "poster_objective": "Awareness",
    "poster_type": "Product hero",
    "visual_route": "Studio heritage",
    "frame_ratio": "9:16",
    "language": "ms",
    "angle": "Heritage",
    "hook": "Warisan keluarga",
    "subhook": "Saiz mudah",
    "usp_1": "25ml",
    "usp_2": "Jimat",
    "usp_3": "Pilihan",
    "cta": "Beli sekarang",
    "operator_notes": "",
}


async def main() -> int:
    from agent.db import crud
    from agent.models.poster_prompt_draft import PosterPromptDraftRequest
    from agent.services.poster_prompt_draft_service import (
        PosterPromptDraftService,
        PosterPromptDraftValidationError,
    )
    from agent.services.poster_readiness_service import PosterReadinessService

    for label, pid in IDS.items():
        print(f"\n=== {label} ({pid}) ===")
        row = await crud.get_product(pid)
        if not row:
            print("PRODUCT_NOT_FOUND")
            continue
        product = dict(row)
        readiness = await PosterReadinessService.evaluate_product(product, enrich=False)
        print(f"poster_status={readiness.poster_status.value}")
        print(f"blockers={readiness.blockers}")
        req = PosterPromptDraftRequest(product_id=pid, **SAFE_REQUEST)
        try:
            draft = await PosterPromptDraftService.build_draft(req)
            print(f"safe_copy: package={draft.prompt_package_status} prompt_len={len(draft.poster_prompt or '')}")
        except PosterPromptDraftValidationError as e:
            print(f"safe_copy: VALIDATION {e} {e.field_errors}")
        unsafe = PosterPromptDraftRequest(
            product_id=pid,
            **{**SAFE_REQUEST, "hook": "Ubat penyakit cure guaranteed"},
        )
        try:
            await PosterPromptDraftService.build_draft(unsafe)
            print("unsafe_copy: UNEXPECTED_SUCCESS")
        except PosterPromptDraftValidationError as e:
            print(f"unsafe_copy: rejected {str(e)[:80]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"Target DB verification unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc