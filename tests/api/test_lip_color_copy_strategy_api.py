from fastapi.testclient import TestClient

from agent.main import app
from agent.models.lip_color_copy_strategy import LipColorCopyStrategyResponse
from agent.services.lip_color_copy_strategy_service import (
    LipColorCopyStrategyError,
)


_PRODUCT_ID = "59a0a7cc-3374-4025-951a-9832fe9359e4"
_URL = f"/api/copywriting/p3a/lip-color/{_PRODUCT_ID}"


def _response(duration_seconds: int = 8) -> LipColorCopyStrategyResponse:
    return LipColorCopyStrategyResponse(
        product_id=_PRODUCT_ID,
        product_name="TIME PHORIA Altera Blurring Lip Tint",
        cluster="beauty_makeup",
        product_type_group="lipstick_lip_tint",
        scene_strategy_id="LIP_COLOR",
        copy_strategy_id="P3A_LIP_COLOR_TIME_PHORIA_FASTMOSS_V1",
        duration_seconds=duration_seconds,
        hook_line="Nak bibir nampak blur?",
        demo_line="Sapu Altera Lip Tint sekali.",
        benefit_line="Warna naik, garis bibir nampak lebih lembut.",
        cta_line="Semak shade korang.",
        overlay_text="BLURRING LIP TINT • PILIH SHADE",
        scene_action="apply one clean pass to the lips; show result clearly",
        blocked_reasons=[],
    )


def test_p3a_lip_color_route_returns_typed_preview(monkeypatch):
    async def fake_service(product_id: str, duration_seconds: int):
        assert product_id == _PRODUCT_ID
        assert duration_seconds == 10
        return _response(duration_seconds)

    monkeypatch.setattr(
        "agent.api.copywriting.build_lip_color_copy_strategy",
        fake_service,
    )

    response = TestClient(app).get(f"{_URL}?duration_seconds=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == _PRODUCT_ID
    assert payload["duration_seconds"] == 10
    assert payload["scene_strategy_id"] == "LIP_COLOR"
    assert payload["blocked_reasons"] == []


def test_p3a_lip_color_route_returns_stable_blocked_reasons(monkeypatch):
    async def blocked_service(product_id: str, _duration_seconds: int):
        raise LipColorCopyStrategyError(
            "P3A_PRODUCT_NOT_ALLOWED",
            product_id=product_id,
            status_code=403,
        )

    monkeypatch.setattr(
        "agent.api.copywriting.build_lip_color_copy_strategy",
        blocked_service,
    )

    response = TestClient(app).get(
        "/api/copywriting/p3a/lip-color/"
        "db2dbbeb-79dc-4b78-b1ce-2257257cb7f8"
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "P3A_PRODUCT_NOT_ALLOWED"
    assert detail["blocked_reasons"] == ["P3A_PRODUCT_NOT_ALLOWED"]


def test_p3a_lip_color_route_rejects_unsupported_duration_before_service(
    monkeypatch,
):
    async def unexpected_service(_product_id: str, _duration_seconds: int):
        raise AssertionError("invalid duration reached service")

    monkeypatch.setattr(
        "agent.api.copywriting.build_lip_color_copy_strategy",
        unexpected_service,
    )

    response = TestClient(app).get(f"{_URL}?duration_seconds=12")

    assert response.status_code == 422
