"""Real-product Poster Builder V2 proof runs (repair PR — OFFLINE, CREDIT-FREE).

Runs the ACTUAL V2 service path (poster copy set → compose → QA → save-to-library
→ reopen-by-asset) for two required REAL BOSMAX products using repository assets:

  1. Minyak Warisan Tok Cap Burung 25ml — background = an APPROVED
     reference-conditioned generated scene that already exists in the repo
     (real product held by an avatar; generated in a prior credit-approved run).
  2. BOSMAX Serum 5 ML (registered product title: Bosmax Herbs 5 ML) —
     background = its APPROVED registered product-lock photo. No generated
     scene exists, so NO new generation is fired; that limitation is recorded.

Also records the FONT_UNAVAILABLE fail-closed proof: a manifest declaring a
nonexistent font family must FAIL the render, never silently substitute.

No Google Flow call, no image-generation lane, no credit spend, no network.

Usage (from the repo root; uses an ISOLATED scratch agent dir + DB):
    python scripts/generate_real_product_poster_proof.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EVIDENCE_DIR = ROOT / "scripts" / "fixtures" / "poster-compositor" / "real-products"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _sanitize_manifest_json(render_manifest_json: str, staged_rel: str) -> str:
    """Strip the ephemeral absolute staged background path from a manifest so
    committed evidence carries a relative placeholder, not a machine path."""
    try:
        manifest = json.loads(render_manifest_json)
    except ValueError:
        return render_manifest_json
    if "background_local_path" in manifest:
        manifest["background_local_path"] = staged_rel
    return json.dumps(manifest, indent=2, ensure_ascii=False)

# Real repository assets (registered in the shared catalog; read-only inputs).
_MAIN_TREE = Path(os.environ.get("FLOWKIT_MAIN_TREE", r"C:\Users\USER\Desktop\_ref_flowkit"))
RUNS = [
    {
        "run_id": "minyak_warisan_tok_25ml",
        "display": "Minyak Warisan Tok Cap Burung 25ml",
        "category": "Traditional",
        "recipe_id": "heritage_infographic",
        "background_src": _MAIN_TREE / ".local-agent" / "creative-assets" / "ca_0d56e05025f94eae.jpg",
        "background_kind": "APPROVED reference-conditioned generated scene (asset ca_0d56e05025f94eae, real product held by avatar)",
        "copy": {
            "objective": "Heritage and trust",
            "archetype": "HERITAGE_TRUST",
            "angle": "Warisan keluarga",
            "primary_message": "Minyak Warisan Tok — Cap Burung",
            "support_message": "Sedia di rumah anda, bila-bila masa.",
            "proof_points": ["Minyak tradisional", "Botol 25ml"],
            "cta": "Dapatkan sekarang",
        },
    },
    {
        "run_id": "bosmax_serum_5ml",
        "display": "BOSMAX Serum 5 ML",
        "category": "Traditional",
        "recipe_id": "product_hero_night_routine",
        "background_src": _MAIN_TREE / "data" / "products" / "images" / "90349f8c-9e14-4efe-988e-76ec60ea31f4.png",
        "background_kind": "APPROVED registered BOSMAX Serum product-lock photo (stored product title: Bosmax Herbs 5 ML; no generated scene exists and no new generation fired)",
        "copy": {
            "objective": "Product introduction",
            "archetype": "PRODUCT_HERO",
            "angle": "Produk sebenar",
            "primary_message": "BOSMAX Serum — untuk rutin anda",
            "support_message": "Botol 5 ML.",
            "proof_points": ["Botol 5 ML"],
            "cta": "Cuba hari ini",
        },
    },
]


def _bootstrap_isolated_agent_dir() -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="poster_proof_agent_"))
    os.environ["FLOW_AGENT_DIR"] = str(scratch)
    (scratch / "output").mkdir(parents=True, exist_ok=True)
    renderer_path = scratch / "scripts" / "poster-compositor-render.js"
    renderer_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "scripts" / "poster-compositor-render.js", renderer_path)
    return scratch


async def _run() -> int:
    scratch = _bootstrap_isolated_agent_dir()
    # Import AFTER FLOW_AGENT_DIR is set — config resolves paths at import time.
    from agent.config import OUTPUT_DIR
    from agent.db import crud
    from agent.db.schema import init_db, close_db
    from agent.models.poster_copy_set import (
        POSTER_COPY_APPROVAL_PHRASE,
        PosterCopySetCreateRequest,
    )
    from agent.services.poster_copy_set_service import PosterCopySetService
    from agent.services.poster_deliverable_service import PosterDeliverableService

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    results = []
    try:
        for spec in RUNS:
            bg_src = spec["background_src"]
            if not bg_src.exists():
                print(f"SKIP {spec['run_id']}: real asset missing: {bg_src}")
                continue
            # Real asset staged into the ALLOWED output root (path allowlist).
            bg = OUTPUT_DIR / f"{spec['run_id']}_bg{bg_src.suffix}"
            shutil.copyfile(bg_src, bg)

            product = await crud.create_product(
                spec["display"], source="MANUAL",
                product_display_name=spec["display"], category=spec["category"],
            )
            pcs = await PosterCopySetService.create_draft(
                PosterCopySetCreateRequest(
                    product_id=product["id"], language="ms", **spec["copy"],
                )
            )
            pcs = await PosterCopySetService.approve(
                pcs["poster_copy_set_id"],
                approval_phrase=POSTER_COPY_APPROVAL_PHRASE,
                approved_by="operator-proof-run",
            )
            composed = await PosterDeliverableService.compose_poster(
                product_id=product["id"],
                poster_copy_set_id=pcs["poster_copy_set_id"],
                recipe_id=spec["recipe_id"],
                background_local_path=str(bg),
                image_model="EXISTING_REAL_ASSET_NO_GENERATION",
            )
            deliverable = composed["deliverable"]
            saved = await PosterDeliverableService.save_to_library(
                deliverable["poster_deliverable_id"]
            )
            # Creative Library ROUND TRIP on the real path.
            recon = await PosterDeliverableService.get_by_creative_asset(
                saved["creative_asset_id"]
            )
            assert (
                recon["deliverable"]["poster_deliverable_id"]
                == deliverable["poster_deliverable_id"]
            ), "round trip returned a different deliverable"

            out_png = EVIDENCE_DIR / f"{spec['run_id']}.poster.png"
            shutil.copyfile(deliverable["output_path"], out_png)
            product_truth_review = {
                "status": "REFERENCE_CONDITIONED_UNVERIFIED",
                "verified": ["deterministic text render", "output dimensions", "text-zone geometry"],
                "human_review_required": [
                    "actual product placement inside the author-defined safe region",
                    "product identity and label readability",
                    "product scale and distortion in the background",
                ],
            }
            staged_rel = f"<staged_output>/{spec['run_id']}_bg{bg_src.suffix}"
            renderer = composed["render_report"].get("renderer", "")
            evidence = {
                "run_id": spec["run_id"],
                # Honest label: an offline deterministic compositor run over a
                # REAL approved asset — NOT a live generation call.
                "evidence_type": "REAL-ASSET COMPOSITOR PROOF",
                "source_asset_id": bg_src.stem,
                "source_asset_sha256": _sha256_file(bg_src),
                "background_staged_from": staged_rel,
                "renderer_version": renderer,
                "commit_sha": _git_commit(),
                "reproducible_command": (
                    "python scripts/generate_real_product_poster_proof.py"
                ),
                "evidence_paths": {
                    "poster_png": f"{spec['run_id']}.poster.png",
                    "manifest": f"{spec['run_id']}.manifest.json",
                    "qa_report": f"{spec['run_id']}.qa_report.json",
                    "product_truth_review": f"{spec['run_id']}.product_truth_review.json",
                },
                "product": spec["display"],
                "recipe_id": spec["recipe_id"],
                "background": spec["background_kind"],
                "credit_spend": False,
                "composition_strategy": deliverable["composition_strategy"],
                "output_sha256": deliverable["output_sha256"],
                "qa_report": composed["qa_report"],
                "render_report": composed["render_report"],
                "product_truth_review": product_truth_review,
                "round_trip_by_asset": True,
                "poster_copy_set": {
                    "id": pcs["poster_copy_set_id"],
                    "version": pcs["version"],
                    "status": pcs["status"],
                },
            }
            (EVIDENCE_DIR / f"{spec['run_id']}.evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (EVIDENCE_DIR / f"{spec['run_id']}.manifest.json").write_text(
                _sanitize_manifest_json(deliverable["render_manifest_json"], staged_rel)
                + "\n",
                encoding="utf-8",
            )
            (EVIDENCE_DIR / f"{spec['run_id']}.qa_report.json").write_text(
                json.dumps(composed["qa_report"], indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (EVIDENCE_DIR / f"{spec['run_id']}.product_truth_review.json").write_text(
                json.dumps(product_truth_review, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"OK {spec['run_id']}: qa_ok={composed['qa_report']['ok']} "
                  f"sha={deliverable['output_sha256'][:12]}")
            results.append(spec["run_id"])
    finally:
        await close_db()

    # ── FONT_UNAVAILABLE fail-closed runtime proof ───────────────────────────
    manifest_path = EVIDENCE_DIR / "_font_fail.manifest.json"
    if results:
        base = json.loads(
            (EVIDENCE_DIR / f"{results[0]}.manifest.json").read_text(encoding="utf-8")
        )
        for token in base.get("font_tokens", {}).values():
            token["family"] = "'NoSuchFontFamilyXYZ'"
        manifest_path.write_text(json.dumps(base), encoding="utf-8")
        report_path = EVIDENCE_DIR / "font_fail.render_report.json"
        proc = subprocess.run(
            ["node", str(ROOT / "scripts" / "poster-compositor-render.js"),
             "--manifest", str(manifest_path),
             "--out", str(scratch / "font_fail.png"),
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=90,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert proc.returncode != 0, "missing font must FAIL the render"
        assert any("FONT_UNAVAILABLE" in e for e in report["errors"]), report["errors"]
        print(f"OK font-fail-closed: exit={proc.returncode} "
              f"missing={report['fonts']['missing_families']}")
        manifest_path.unlink()

    # ── Contact sheet (labels + both posters, committed as compressed JPEG) ──
    if len(results) >= 1:
        from PIL import Image, ImageDraw
        posters = [Image.open(EVIDENCE_DIR / f"{r}.poster.png") for r in results]
        thumb_h = 960
        thumbs = [p.resize((int(p.width * thumb_h / p.height), thumb_h)) for p in posters]
        pad = 24
        sheet = Image.new(
            "RGB",
            (sum(t.width for t in thumbs) + pad * (len(thumbs) + 1), thumb_h + 72),
            "#101010",
        )
        x = pad
        d = ImageDraw.Draw(sheet)
        for r, t in zip(results, thumbs):
            sheet.paste(t, (x, 48))
            d.text((x, 16), r, fill="#e8e8e8")
            x += t.width + pad
        sheet.save(EVIDENCE_DIR / "real_products_contact_sheet.jpg", quality=72)
        print("OK contact sheet written")

    print(f"DONE: {len(results)} real-product runs -> {EVIDENCE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
