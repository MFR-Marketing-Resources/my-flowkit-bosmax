"""One-off target product poster verification (local DB)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

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


def _package_status_value(draft) -> str:
    status = draft.prompt_package_status
    return status.value if hasattr(status, "value") else str(status)


def _format_unsafe_success(draft) -> str:
    prompt_len = len(draft.poster_prompt or "")
    pkg = _package_status_value(draft)
    if prompt_len > 0:
        return f"UNEXPECTED_SUCCESS package={pkg} prompt_len={prompt_len}"
    return f"blocked package={pkg} prompt_len=0"


async def main() -> int:
    from agent.db.schema import close_db
    from agent.db import crud
    from agent.models.poster_prompt_draft import PosterPromptDraftRequest
    from agent.services.poster_prompt_draft_service import (
        PosterPromptDraftService,
        PosterPromptDraftValidationError,
    )
    from agent.services.poster_readiness_service import PosterReadinessService

    try:
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
                print(
                    f"safe_copy: package={_package_status_value(draft)} "
                    f"prompt_len={len(draft.poster_prompt or '')}"
                )
            except PosterPromptDraftValidationError as e:
                print(f"safe_copy: VALIDATION {e} {e.field_errors}")
            unsafe = PosterPromptDraftRequest(
                product_id=pid,
                **{**SAFE_REQUEST, "hook": "Ubat penyakit cure guaranteed"},
            )
            try:
                draft = await PosterPromptDraftService.build_draft(unsafe)
                print(f"unsafe_copy: {_format_unsafe_success(draft)}")
            except PosterPromptDraftValidationError as e:
                print(f"unsafe_copy: rejected {str(e)[:80]}")
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"Target DB verification unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc