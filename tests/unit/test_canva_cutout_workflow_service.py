from io import BytesIO
import json

import pytest
from PIL import Image

from agent.db import crud
from agent.services import canva_cutout_workflow_service as service


def _png(size=(1000, 1000), *, alpha=True, transparent=True) -> bytes:
    image = Image.new("RGBA" if alpha else "RGB", size, (255, 255, 255, 0) if alpha else (255, 255, 255))
    if alpha:
        if transparent:
            for x in range(4, 16):
                for y in range(3, 20):
                    image.putpixel((x, y), (40, 80, 120, 255))
        else:
            image = Image.new("RGBA", size, (40, 80, 120, 255))
    stream = BytesIO()
    image.save(stream, format="PNG")
    image.close()
    return stream.getvalue()


async def _product(tmp_path, title="Canva Product"):
    source = tmp_path / f"{title.replace(' ', '_')}.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)
    return await crud.create_product(
        raw_product_title=title,
        source="MANUAL",
        local_image_path=str(source),
        media_id=f"source-{title.replace(' ', '-').lower()}",
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )


def _ready_preflight():
    return {
        "login_status": "READY",
        "magic_grab_status": "READY",
        "background_remover_status": "READY",
        "magic_layers_status": "READY",
        "transparent_export_status": "READY",
    }


@pytest.mark.asyncio
async def test_per_product_canva_start_and_preflight_persist_source_identity(tmp_path):
    product = await _product(tmp_path)

    started = await service.start_canva_cutout(product["id"])

    assert started["workflow"]["current_stage"] == "PREFLIGHT"
    assert started["workflow"]["source_dimensions"] == {"width": 1000, "height": 1000}
    row = await crud.get_canva_cutout_workflow(product["id"])
    assert row["source_width"] == 1000
    assert row["source_height"] == 1000
    assert len(row["source_sha256"]) == 64

    ready = await service.record_canva_preflight(
        product["id"],
        canva_method="MAGIC_GRAB",
        design_id="design-1",
        design_url="https://www.canva.com/design/design-1/edit",
        preflight=_ready_preflight(),
    )

    assert ready["workflow"]["current_stage"] == "OPENING_CANVA"
    assert ready["workflow"]["provenance_source"] == "CANVA_MAGIC_GRAB"
    persisted = await crud.get_canva_cutout_workflow(product["id"])
    assert persisted["design_id"] == "design-1"
    assert "cookie" not in (persisted["preflight_json"] or "").lower()


@pytest.mark.asyncio
async def test_canva_pro_required_blocks_before_editing(tmp_path):
    product = await _product(tmp_path, "Canva Pro Blocked Product")
    await service.start_canva_cutout(product["id"])

    blocked_preflight = _ready_preflight()
    blocked_preflight["transparent_export_status"] = "PRO_REQUIRED"
    blocked = await service.record_canva_preflight(
        product["id"],
        canva_method="MAGIC_GRAB",
        design_id=None,
        design_url=None,
        preflight=blocked_preflight,
    )

    assert blocked["workflow"]["current_stage"] == "CANVA_PRO_REQUIRED"
    assert blocked["workflow"]["last_error_code"] == "CANVA_PRO_REQUIRED"
    assert blocked["readiness"]["canva_cutout_stage"] == "CANVA_PRO_REQUIRED"


def test_canva_png_verification_rejects_rgb_and_opaque_outputs():
    with pytest.raises(service.CanvaCutoutWorkflowError) as rgb_error:
        service._verify_canva_png(_png(alpha=False), (1000, 1000))
    assert rgb_error.value.code == "CANVA_ALPHA_REQUIRED"

    with pytest.raises(service.CanvaCutoutWorkflowError) as opaque_error:
        service._verify_canva_png(_png(alpha=True, transparent=False), (1000, 1000))
    assert opaque_error.value.code == "CANVA_ALPHA_REQUIRED"

    width, height, sha = service._verify_canva_png(_png(), (1000, 1000))
    assert (width, height) == (1000, 1000)
    assert len(sha) == 64


@pytest.mark.asyncio
async def test_canva_result_handoffs_to_existing_manual_lane_and_stays_pending(tmp_path, monkeypatch):
    product = await _product(tmp_path, "Canva Handoff Product")
    await service.start_canva_cutout(product["id"])
    await service.record_canva_preflight(
        product["id"],
        canva_method="MAGIC_GRAB",
        design_id="handoff-design",
        design_url="https://www.canva.com/design/handoff-design/edit",
        preflight=_ready_preflight(),
    )
    captured: dict[str, object] = {}

    async def fake_manual_upload(product_id, **kwargs):
        captured["product_id"] = product_id
        captured.update(kwargs)
        return {"cutout_media_id": "canva-media-1", "cutout_status": "PENDING_REVIEW"}

    monkeypatch.setattr(
        "agent.services.product_visual_onboarding_service.upload_manual_product_cutout",
        fake_manual_upload,
    )

    result = await service.complete_canva_cutout(
        product["id"],
        filename="canva-output.png",
        content_type="image/png",
        raw_bytes=_png(),
        uploaded_by="operator-1",
        canva_method="MAGIC_GRAB",
        design_id="handoff-design",
        design_url="https://www.canva.com/design/handoff-design/edit",
    )

    assert captured["product_id"] == product["id"]
    assert captured["provenance_source"] == "CANVA_MAGIC_GRAB"
    assert result["workflow"]["current_stage"] == "PENDING_HUMAN_REVIEW"
    assert result["workflow"]["alpha_verified"] is True
    assert result["workflow"]["human_review_status"] == "PENDING_REVIEW"
    assert result["readiness"]["exact_commerce_status"] == "CUTOUT_REQUIRED"


@pytest.mark.asyncio
async def test_normal_manual_cutout_supersedes_open_canva_attempt(tmp_path):
    product = await _product(tmp_path, "Manual supersedes Canva")
    await service.start_canva_cutout(product["id"])

    from agent.services.product_visual_onboarding_service import upload_manual_product_cutout

    await upload_manual_product_cutout(
        product["id"],
        filename="manual-override.png",
        content_type="image/png",
        raw_bytes=_png(),
        uploaded_by="operator-2",
    )

    workflow = await crud.get_canva_cutout_workflow(product["id"])
    assert workflow["current_stage"] == "FAILED"
    assert workflow["last_error_code"] == "SUPERSEDED_BY_MANUAL_CUTOUT"


@pytest.mark.asyncio
async def test_canva_bulk_pause_resume_cancel_is_durable_and_bounded(tmp_path):
    product = await _product(tmp_path, "Canva Bulk Product")
    preview = await service.preview_canva_cutout_bulk(limit=100)
    assert product["id"] in preview["eligible_product_ids"]
    assert preview["bounded_batch"]["default_size"] == 3

    queued = await service.prepare_canva_cutout_bulk(
        confirm=True,
        preview_digest=preview["preview_digest"],
        max_products=1,
        priority_product_ids=[product["id"]],
        preflight={
            "login_status": "UNKNOWN",
            "magic_grab_status": "UNKNOWN",
            "background_remover_status": "UNKNOWN",
            "magic_layers_status": "UNKNOWN",
            "transparent_export_status": "UNKNOWN",
        },
    )
    assert queued["status"] == "PAUSED"
    run_id = queued["run_id"]

    resumed = await service.resume_canva_cutout_bulk(run_id, preflight=_ready_preflight())
    assert resumed["status"] == "RUNNING"
    paused = await service.pause_canva_cutout_bulk(run_id)
    assert paused["status"] == "PAUSED"
    resumed_again = await service.resume_canva_cutout_bulk(run_id, preflight=_ready_preflight())
    assert resumed_again["status"] == "RUNNING"

    cancelled = await service.cancel_canva_cutout_bulk(run_id)
    assert cancelled["status"] == "CANCELLED"
    persisted = await service.get_canva_cutout_bulk_run(run_id)
    assert persisted["status"] == "CANCELLED"
    assert persisted["items"][0]["current_stage"] == "CANCELLED"

    blocked = await service.prepare_canva_cutout_bulk(
        confirm=True,
        preview_digest=preview["preview_digest"],
        max_products=1,
        priority_product_ids=[product["id"]],
        preflight={**_ready_preflight(), "transparent_export_status": "PRO_REQUIRED"},
    )
    assert blocked["status"] == "BLOCKED_CANVA_PRO_REQUIRED"
    assert blocked["items"][0]["current_stage"] == "CANVA_PRO_REQUIRED"
    released = await service.resume_canva_cutout_bulk(blocked["run_id"], preflight=_ready_preflight())
    assert released["status"] == "RUNNING"
    assert released["items"][0]["current_stage"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_bounded_three_product_preflight_stops_at_canva_pro_gate(tmp_path):
    profiles = (
        "Hero promotional pack",
        "Simple label jar",
        "Irregular shape bottle",
    )
    blocked = []
    for title in profiles:
        product = await _product(tmp_path, title)
        await service.start_canva_cutout(product["id"])
        result = await service.record_canva_preflight(
            product["id"],
            canva_method="MAGIC_GRAB",
            design_id=None,
            design_url=None,
            preflight={
                **_ready_preflight(),
                "transparent_export_status": "PRO_REQUIRED",
            },
        )
        blocked.append(result["workflow"])

    assert len(blocked) == 3
    assert {item["current_stage"] for item in blocked} == {"CANVA_PRO_REQUIRED"}
    assert all(item["last_error_code"] == "CANVA_PRO_REQUIRED" for item in blocked)
    assert all(item["output_sha256"] is None for item in blocked)


@pytest.mark.asyncio
async def test_canva_approval_and_fallback_mirrors_only_canva_current_candidate(tmp_path, monkeypatch):
    canva_product = await _product(tmp_path, "Canva approval candidate")
    await service.start_canva_cutout(canva_product["id"])
    await crud.upsert_canva_cutout_workflow(
        canva_product["id"],
        current_stage="PENDING_HUMAN_REVIEW",
        human_review_status="PENDING_REVIEW",
    )
    manual_product = await _product(tmp_path, "Manual approval candidate")
    await service.start_canva_cutout(manual_product["id"])
    await crud.upsert_canva_cutout_workflow(
        manual_product["id"],
        current_stage="PENDING_HUMAN_REVIEW",
        human_review_status="PENDING_REVIEW",
    )

    async def fake_lock(product_id):
        if product_id == canva_product["id"]:
            return {"provenance_json": json.dumps({"canva_provenance_source": "CANVA_MAGIC_GRAB"})}
        return {"provenance_json": json.dumps({"source": "USER_UPLOAD"})}

    monkeypatch.setattr(crud, "get_product_truth_lock", fake_lock)

    approved = await service.mark_canva_workflow_approved(canva_product["id"])
    untouched = await service.mark_canva_workflow_approved(manual_product["id"])

    assert approved["current_stage"] == "APPROVED"
    assert untouched["current_stage"] == "PENDING_HUMAN_REVIEW"

    fallback_product = await _product(tmp_path, "Canva fallback candidate")
    await service.start_canva_cutout(fallback_product["id"])
    await crud.upsert_canva_cutout_workflow(
        fallback_product["id"],
        current_stage="PENDING_HUMAN_REVIEW",
        human_review_status="PENDING_REVIEW",
    )

    async def fake_fallback_lock(product_id):
        if product_id == fallback_product["id"]:
            return {"provenance_json": json.dumps({"canva_provenance_source": "CANVA_MAGIC_GRAB"})}
        return await fake_lock(product_id)

    monkeypatch.setattr(crud, "get_product_truth_lock", fake_fallback_lock)
    fallback = await service.mark_canva_workflow_fallback(fallback_product["id"], "Canva output rejected; use same product source.")
    assert fallback["current_stage"] == "FAILED"
    assert fallback["last_error_code"] == "SAME_PRODUCT_FALLBACK_SELECTED"
