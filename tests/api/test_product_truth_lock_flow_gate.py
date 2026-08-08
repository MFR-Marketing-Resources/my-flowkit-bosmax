from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from agent.api import flow
from agent.api import product_truth
from agent.models.product_truth_lock import (
    ProductTruthLockApprovalRequest,
    ProductTruthLockOnboardingRequest,
)


def _product(product_id: str = "p1") -> dict:
    return {
        "id": product_id,
        "product_display_name": "Test product",
        "category": "General",
        "image_url": "https://example.invalid/canonical.png",
    }


@pytest.mark.asyncio
async def test_generate_exact_img_blocks_before_flow_client_without_truth_lock(monkeypatch):
    async def get_product(product_id):
        return _product(product_id)

    monkeypatch.setattr(flow.crud, "get_product", get_product)
    monkeypatch.setattr(flow, "get_flow_client", lambda: (_ for _ in ()).throw(AssertionError("client must not be checked")))

    from agent.services import exact_product_compositor_service as exact_svc

    def missing_lock(_product):
        raise exact_svc.ExactProductCompositeError(
            "PRODUCT_TRUTH_LOCK_REQUIRED", "approved lock required"
        )

    monkeypatch.setattr(exact_svc, "validate_canonical_or_raise", missing_lock)

    with pytest.raises(HTTPException) as exc:
        await flow.generate(
            flow.GenerateRequest(
                mode="IMG",
                prompt="clean product hero scene",
                product_id="p1",
                visual_lane_id="PRODUCT_ONLY_HERO",
            )
        )
    assert exc.value.status_code == 422
    assert "PRODUCT_TRUTH_LOCK_REQUIRED" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_generate_exact_img_rejects_client_product_reference(monkeypatch):
    async def get_product(product_id):
        return _product(product_id)

    monkeypatch.setattr(flow.crud, "get_product", get_product)
    monkeypatch.setattr(flow, "get_flow_client", lambda: (_ for _ in ()).throw(AssertionError("provider path must not open")))

    from agent.services import exact_product_compositor_service as exact_svc

    monkeypatch.setattr(exact_svc, "validate_canonical_or_raise", lambda _product: {"ok": True})

    with pytest.raises(HTTPException) as exc:
        await flow.generate(
            flow.GenerateRequest(
                mode="IMG",
                prompt="clean product hero scene",
                product_id="p1",
                visual_lane_id="PRODUCT_ONLY_HERO",
                refs={
                    "productAsset": {
                        "mediaId": "client-selected-media",
                    }
                },
            )
        )
    assert exc.value.status_code == 422
    assert "PRODUCT_REFERENCE_FORBIDDEN_EXACT_MODE" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_generate_standard_img_replaces_client_product_reference(monkeypatch):
    async def get_product(product_id):
        return _product(product_id)

    grounded = SimpleNamespace(
        product_reference={
            "media_id": "11111111-1111-4111-8111-111111111111",
            "local_path": None,
            "image_url": "https://example.invalid/server-selected.png",
            "source_type": "PRODUCT_DATABASE_RECORD",
        }
    )

    async def fake_start_generate(*_args, **kwargs):
        fake_start_generate.received = kwargs
        return {"job_id": "img-job-1"}

    class FakeClient:
        connected = True

        async def get_media(self, _media_id):
            return {"status": 200}

    monkeypatch.setattr(flow.crud, "get_product", get_product)
    monkeypatch.setattr(flow, "get_flow_client", lambda: FakeClient())
    from agent.services import make_video

    monkeypatch.setattr(make_video, "start_generate", fake_start_generate)
    monkeypatch.setattr(flow, "_bridge_generate_job_telemetry", lambda *_args, **_kwargs: _noop())

    def fake_resolve(*_args, **_kwargs):
        return grounded

    from agent.services import product_visual_grounding_resolver as resolver

    monkeypatch.setattr(resolver, "resolve_product_visual_grounding", fake_resolve)

    result = await flow.generate(
        flow.GenerateRequest(
            mode="IMG",
            prompt="show the product with a person",
            product_id="p1",
            visual_lane_id="IMG_AVATAR_PRODUCT_COMPOSITE",
            refs={
                "productAsset": {
                    "productId": "p1",
                    "mediaId": "client-wrong-media",
                    "semanticRole": "PRODUCT_REFERENCE",
                }
            },
        )
    )
    assert result["job_id"] == "img-job-1"
    assert fake_start_generate.received["image_media_ids"] == ["11111111-1111-4111-8111-111111111111"]


async def _noop():
    return None


@pytest.mark.asyncio
async def test_workspace_img_gate_removes_client_product_and_binds_server_product(monkeypatch):
    async def get_product(product_id):
        return _product(product_id)

    def fake_resolve(*_args, **_kwargs):
        return SimpleNamespace(
            product_reference={
                "media_id": "server-media",
                "local_path": None,
                "image_url": None,
                "source_type": "PRODUCT_DATABASE_RECORD",
            }
        )

    monkeypatch.setattr(flow.crud, "get_product", get_product)
    from agent.services import product_visual_grounding_resolver as resolver

    monkeypatch.setattr(resolver, "resolve_product_visual_grounding", fake_resolve)
    prompt, refs, exact = await flow._apply_img_product_truth_gate(
        product_id="p1",
        visual_lane_id="IMG_WORKSPACE",
        prompt="scene",
        request_refs={
            "subjectAsset": {
                "productId": "p1",
                "assetSource": "PRODUCT_IMAGE_URL",
                "downloadUrl": "https://example.invalid/client.png",
            }
        },
    )
    assert prompt == "scene"
    assert exact is False
    assert "subjectAsset" not in refs
    assert refs["productAsset"]["mediaId"] == "server-media"


@pytest.mark.asyncio
async def test_product_truth_onboarding_route_never_approves_lock(monkeypatch):
    captured = {}

    async def fake_onboard(product_id, request):
        captured["product_id"] = product_id
        captured["request"] = request
        return {"review_status": "PENDING_REVIEW", "exact_allowed": False}

    monkeypatch.setattr(product_truth, "create_pending_product_truth_lock", fake_onboard)

    result = await product_truth.onboard_visual_product_truth_lock(
        "p1",
        ProductTruthLockOnboardingRequest(
            canonical_cutout_media_id="cutout-1",
            anchor_point={"x": 0.5, "y": 0.5},
            min_scale=0.5,
            max_scale=1.0,
            allowed_bbox={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
            created_by="operator-1",
        ),
    )

    assert result["review_status"] == "PENDING_REVIEW"
    assert result["exact_allowed"] is False
    assert captured["product_id"] == "p1"


@pytest.mark.asyncio
async def test_product_truth_cutout_upload_only_registers_review_media(monkeypatch):
    captured = {}

    async def fake_register(product_id, **kwargs):
        captured["product_id"] = product_id
        captured.update(kwargs)
        return {
            "product_id": product_id,
            "media_id": "stored-cutout-1",
            "status": "STORED",
            "review_status": "PENDING_REVIEW",
        }

    monkeypatch.setattr(product_truth, "register_product_truth_cutout_media", fake_register)

    upload = UploadFile(filename="cutout.png", file=__import__("io").BytesIO(b"png-bytes"))
    result = await product_truth.upload_visual_product_truth_cutout("p1", upload)

    assert result["media_id"] == "stored-cutout-1"
    assert result["review_status"] == "PENDING_REVIEW"
    assert captured["product_id"] == "p1"
    assert captured["filename"] == "cutout.png"
    assert captured["raw_bytes"] == b"png-bytes"


@pytest.mark.asyncio
async def test_product_truth_approval_route_is_separate(monkeypatch):
    captured = {}

    async def fake_approve(product_id, request):
        captured["product_id"] = product_id
        captured["request"] = request
        return {"review_status": "APPROVED", "exact_allowed": True}

    monkeypatch.setattr(product_truth, "approve_product_truth_lock", fake_approve)

    result = await product_truth.approve_visual_product_truth_lock(
        "p1",
        ProductTruthLockApprovalRequest(
            reviewed_by="human-reviewer",
            review_note="Verified",
            confirm_identity=True,
            confirm_label_logo=True,
            confirm_geometry_scale=True,
        ),
    )

    assert result["review_status"] == "APPROVED"
    assert captured["product_id"] == "p1"
