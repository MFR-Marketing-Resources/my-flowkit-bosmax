from fastapi.testclient import TestClient

from agent.main import app
from agent.models.rempah_copy_strategy import RempahCopyStrategyResponse
from agent.services.rempah_copy_strategy_service import (
    RempahCopyStrategyError,
)


_PRODUCT_ID = "0a26caf0-1bc6-43a9-a267-7d2a1dbaccab"
_URL = f"/api/copywriting/p3b/rempah/{_PRODUCT_ID}"


def _response(duration_seconds: int = 8) -> RempahCopyStrategyResponse:
    return RempahCopyStrategyResponse(
        product_id=_PRODUCT_ID,
        product_name="Rempah Nasi Khowmok (140g+- / pack)",
        cluster="food_cooking",
        product_type_group="rempah_seasoning",
        scene_strategy_id="SPICE_SEASONING",
        copy_strategy_id="P3B_REMPAH_NASI_KHOWMOK_V1",
        duration_seconds=duration_seconds,
        hook_line="Nak nasi khowmok lagi wangi?",
        demo_line="Masukkan rempah dan gaul rata.",
        benefit_line="Aroma nasi lebih naik.",
        cta_line="Semak pek 140g.",
        overlay_text="REMPAH NASI KHOWMOK • PEK 140G",
        scene_action=(
            "sprinkle the seasoning into a pan; stir the seasoning through "
            "the dish; show the finished nasi khowmok result clearly"
        ),
        blocked_reasons=[],
    )


def test_p3b_rempah_route_returns_typed_preview(monkeypatch):
    async def fake_service(product_id: str, duration_seconds: int):
        assert product_id == _PRODUCT_ID
        assert duration_seconds == 10
        return _response(duration_seconds)

    monkeypatch.setattr(
        "agent.api.copywriting.build_rempah_copy_strategy",
        fake_service,
    )

    response = TestClient(app).get(f"{_URL}?duration_seconds=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == _PRODUCT_ID
    assert payload["duration_seconds"] == 10
    assert payload["scene_strategy_id"] == "SPICE_SEASONING"
    assert payload["product_type_group"] == "rempah_seasoning"
    assert payload["blocked_reasons"] == []


def test_p3b_rempah_route_defaults_to_eight_seconds(monkeypatch):
    async def fake_service(product_id: str, duration_seconds: int):
        assert product_id == _PRODUCT_ID
        assert duration_seconds == 8
        return _response(duration_seconds)

    monkeypatch.setattr(
        "agent.api.copywriting.build_rempah_copy_strategy",
        fake_service,
    )

    response = TestClient(app).get(_URL)

    assert response.status_code == 200
    assert response.json()["duration_seconds"] == 8


def test_p3b_rempah_route_returns_stable_blocked_reasons(monkeypatch):
    async def blocked_service(product_id: str, _duration_seconds: int):
        raise RempahCopyStrategyError(
            "P3B_PRODUCT_NOT_ALLOWED",
            product_id=product_id,
            status_code=403,
        )

    monkeypatch.setattr(
        "agent.api.copywriting.build_rempah_copy_strategy",
        blocked_service,
    )

    response = TestClient(app).get(
        "/api/copywriting/p3b/rempah/"
        "9c85cd83-32f1-4d8b-98bb-6a78f681ed1a"
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "P3B_PRODUCT_NOT_ALLOWED"
    assert detail["blocked_reasons"] == ["P3B_PRODUCT_NOT_ALLOWED"]


def test_p3b_rempah_route_returns_taxonomy_blockers(monkeypatch):
    async def blocked_service(product_id: str, _duration_seconds: int):
        raise RempahCopyStrategyError(
            "P3B_TAXONOMY_NOT_VERIFIED",
            product_id=product_id,
            blocked_reasons=[
                "P3B_TAXONOMY_NOT_VERIFIED",
                "P3B_TAXONOMY_NOT_READY",
            ],
        )

    monkeypatch.setattr(
        "agent.api.copywriting.build_rempah_copy_strategy",
        blocked_service,
    )

    response = TestClient(app).get(_URL)

    assert response.status_code == 409
    assert response.json()["detail"]["blocked_reasons"] == [
        "P3B_TAXONOMY_NOT_VERIFIED",
        "P3B_TAXONOMY_NOT_READY",
    ]


def test_p3b_rempah_route_rejects_unsupported_duration_before_service(
    monkeypatch,
):
    async def unexpected_service(_product_id: str, _duration_seconds: int):
        raise AssertionError("invalid duration reached service")

    monkeypatch.setattr(
        "agent.api.copywriting.build_rempah_copy_strategy",
        unexpected_service,
    )

    response = TestClient(app).get(f"{_URL}?duration_seconds=12")

    assert response.status_code == 422
