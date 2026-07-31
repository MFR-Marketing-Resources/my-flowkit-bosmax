from fastapi.testclient import TestClient

from agent.main import app
from agent.models.product_type_copy_strategy import (
    CatalogAuthorityMatrixReport,
    CatalogCoverageMatrixReport,
    ProductTypeCopyEligibleReport,
    ProductTypeCopyReportGroup,
    ProductTypeCopyReportProduct,
    ProductTypeCopyStrategyResponse,
)
from agent.services.product_type_copy_strategy_service import (
    ProductTypeCopyStrategyError,
)


_PRODUCT_ID = "future-owner-verified-lip-product"
_URL = f"/api/copywriting/p4/product-type/{_PRODUCT_ID}"


def _preview_response(
    duration_seconds: int = 8,
) -> ProductTypeCopyStrategyResponse:
    return ProductTypeCopyStrategyResponse(
        product_id=_PRODUCT_ID,
        product_name="ACME Velvet Matte Lipstick 4G",
        cluster="beauty_makeup",
        product_type_group="lipstick_lip_tint",
        scene_strategy_id="LIP_COLOR",
        copy_strategy_id="P4_LIP_COLOR_PRODUCT_TYPE_V1",
        duration_seconds=duration_seconds,
        hook_line="Nak lihat kemasan matte?",
        demo_line="Sapu ACME lipstick pada bibir.",
        benefit_line="Kemasan matte lebih jelas.",
        cta_line="Semak shade dan saiz 4g.",
        overlay_text="ACME LIPSTICK • 4G",
        scene_action=(
            "apply one clean pass to the lips; show shade, colour payoff, "
            "texture, and finished-lip result clearly"
        ),
        source_strategy="PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        blocked_reasons=[],
    )


def _eligible_report() -> ProductTypeCopyEligibleReport:
    return ProductTypeCopyEligibleReport(
        total_products=659,
        eligible_count=11,
        blocked_count=648,
        eligible_by_product_type=[
            ProductTypeCopyReportGroup(
                cluster="beauty_makeup",
                product_type_group="lipstick_lip_tint",
                scene_strategy_id="LIP_COLOR",
                count=9,
            ),
            ProductTypeCopyReportGroup(
                cluster="food_cooking",
                product_type_group="rempah_seasoning",
                scene_strategy_id="SPICE_SEASONING",
                count=2,
            ),
        ],
        blocked_by_reason={
            "TAXONOMY_NOT_VERIFIED": 648,
            "COPY_STRATEGY_NOT_REGISTERED": 640,
        },
        missing_copy_strategy_groups=[
            ProductTypeCopyReportGroup(
                cluster="generic_unclassified",
                product_type_group="unknown_product_type",
                scene_strategy_id="GENERIC_FALLBACK",
                count=133,
            )
        ],
        sample_eligible=[
            ProductTypeCopyReportProduct(
                product_id=_PRODUCT_ID,
                product_name="ACME Velvet Matte Lipstick 4G",
                cluster="beauty_makeup",
                product_type_group="lipstick_lip_tint",
                scene_strategy_id="LIP_COLOR",
                blocked_reasons=[],
            )
        ],
        sample_blocked=[
            ProductTypeCopyReportProduct(
                product_id="9c85cd83-32f1-4d8b-98bb-6a78f681ed1a",
                product_name="Sambal Serbaguna",
                cluster="food_ready_to_eat",
                product_type_group="packaged_food",
                scene_strategy_id="PACKAGED_FOOD",
                blocked_reasons=[
                    "TAXONOMY_NOT_VERIFIED",
                    "COPY_STRATEGY_NOT_REGISTERED",
                ],
            )
        ],
    )


def _catalog_coverage_report() -> CatalogCoverageMatrixReport:
    return CatalogCoverageMatrixReport(
        report_version="p5.7_catalog_coverage_v1",
        total_products=659,
        active_products=443,
        archived_products=216,
        product_truth_mapped_count=476,
        p4_supported_count=324,
        unknown_product_type_count=37,
        unknown_product_type_p4_supported_count=0,
        p6_launch_cohort_count=1,
        p6_launch_cohort_product_ids=[_PRODUCT_ID],
        blocked_by_reason={"TAXONOMY_NOT_VERIFIED": 658},
        coverage_groups=[],
        products=[],
        matrix_sha256="a" * 64,
    )


def _catalog_authority_report() -> CatalogAuthorityMatrixReport:
    return CatalogAuthorityMatrixReport(
        report_version="p5.8_final_catalog_authority_v1",
        total_products=659,
        active_products=443,
        archived_products=216,
        product_truth_mapped_count=628,
        p4_supported_count=640,
        unknown_product_type_count=14,
        unknown_product_type_p4_supported_count=0,
        terminal_state_counts={
            "ARCHIVED_NOT_IN_SCOPE": 216,
            "INSUFFICIENT_PRODUCT_TRUTH": 3,
            "P6_READY": 438,
            "REVIEW_BLOCKED_WITH_EXACT_REASON": 2,
        },
        p6_launch_cohort_count=438,
        p6_launch_cohort_product_ids=[_PRODUCT_ID],
        blocked_by_reason={
            "UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM": 1,
        },
        coverage_groups=[],
        products=[],
        matrix_sha256="b" * 64,
    )


def test_p4_product_type_route_returns_typed_preview(monkeypatch):
    async def fake_service(product_id: str, duration_seconds: int):
        assert product_id == _PRODUCT_ID
        assert duration_seconds == 10
        return _preview_response(duration_seconds)

    monkeypatch.setattr(
        "agent.api.copywriting.build_product_type_copy_strategy",
        fake_service,
    )

    response = TestClient(app).get(f"{_URL}?duration_seconds=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == _PRODUCT_ID
    assert payload["duration_seconds"] == 10
    assert payload["copy_strategy_id"] == "P4_LIP_COLOR_PRODUCT_TYPE_V1"
    assert payload["source_strategy"] == "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY"
    assert payload["blocked_reasons"] == []


def test_p4_product_type_route_defaults_to_eight_seconds(monkeypatch):
    async def fake_service(product_id: str, duration_seconds: int):
        assert product_id == _PRODUCT_ID
        assert duration_seconds == 8
        return _preview_response(duration_seconds)

    monkeypatch.setattr(
        "agent.api.copywriting.build_product_type_copy_strategy",
        fake_service,
    )

    response = TestClient(app).get(_URL)

    assert response.status_code == 200
    assert response.json()["duration_seconds"] == 8


def test_p4_product_type_route_returns_stable_blocked_reasons(monkeypatch):
    async def blocked_service(product_id: str, _duration_seconds: int):
        raise ProductTypeCopyStrategyError(
            "TAXONOMY_NOT_VERIFIED",
            product_id=product_id,
            blocked_reasons=[
                "TAXONOMY_NOT_VERIFIED",
                "TAXONOMY_NOT_READY",
            ],
        )

    monkeypatch.setattr(
        "agent.api.copywriting.build_product_type_copy_strategy",
        blocked_service,
    )

    response = TestClient(app).get(_URL)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "TAXONOMY_NOT_VERIFIED"
    assert detail["product_id"] == _PRODUCT_ID
    assert detail["blocked_reasons"] == [
        "TAXONOMY_NOT_VERIFIED",
        "TAXONOMY_NOT_READY",
    ]


def test_p4_product_type_route_returns_stable_unsupported_duration(monkeypatch):
    async def blocked_service(product_id: str, duration_seconds: int):
        assert duration_seconds == 12
        raise ProductTypeCopyStrategyError(
            "UNSUPPORTED_DURATION",
            product_id=product_id,
            status_code=422,
        )

    monkeypatch.setattr(
        "agent.api.copywriting.build_product_type_copy_strategy",
        blocked_service,
    )

    response = TestClient(app).get(f"{_URL}?duration_seconds=12")

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "UNSUPPORTED_DURATION"


def test_p4_product_type_route_returns_product_not_found(monkeypatch):
    async def blocked_service(product_id: str, _duration_seconds: int):
        raise ProductTypeCopyStrategyError(
            "PRODUCT_NOT_FOUND",
            product_id=product_id,
            status_code=404,
        )

    monkeypatch.setattr(
        "agent.api.copywriting.build_product_type_copy_strategy",
        blocked_service,
    )

    response = TestClient(app).get(_URL)

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "PRODUCT_NOT_FOUND"


def test_p4_eligible_report_route_returns_typed_counts(monkeypatch):
    async def fake_report():
        return _eligible_report()

    monkeypatch.setattr(
        "agent.api.copywriting.build_product_type_copy_eligible_report",
        fake_report,
    )

    response = TestClient(app).get("/api/copywriting/p4/eligible-report")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "total_products",
        "eligible_count",
        "blocked_count",
        "eligible_by_product_type",
        "blocked_by_reason",
        "missing_copy_strategy_groups",
        "sample_eligible",
        "sample_blocked",
    }
    assert payload["total_products"] == 659
    assert payload["eligible_count"] == 11
    assert payload["blocked_count"] == 648
    assert payload["eligible_count"] + payload["blocked_count"] == payload[
        "total_products"
    ]
    assert payload["eligible_by_product_type"][0]["count"] == 9
    assert payload["missing_copy_strategy_groups"][0]["count"] == 133
    assert payload["sample_blocked"][0]["blocked_reasons"] == [
        "TAXONOMY_NOT_VERIFIED",
        "COPY_STRATEGY_NOT_REGISTERED",
    ]


def test_p5_7_catalog_coverage_route_returns_explicit_launch_cohort(
    monkeypatch,
):
    async def fake_report():
        return _catalog_coverage_report()

    monkeypatch.setattr(
        "agent.api.copywriting.build_catalog_coverage_matrix",
        fake_report,
    )

    response = TestClient(app).get(
        "/api/copywriting/p5-7/catalog-coverage"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_products"] == 659
    assert payload["unknown_product_type_p4_supported_count"] == 0
    assert payload["p6_launch_cohort_product_ids"] == [_PRODUCT_ID]
    assert payload["matrix_sha256"] == "a" * 64


def test_p5_8_catalog_authority_route_returns_terminal_state_counts(
    monkeypatch,
):
    async def fake_report():
        return _catalog_authority_report()

    monkeypatch.setattr(
        "agent.api.copywriting.build_catalog_authority_matrix",
        fake_report,
    )

    response = TestClient(app).get(
        "/api/copywriting/p5-8/catalog-authority"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_products"] == 659
    assert payload["terminal_state_counts"] == {
        "ARCHIVED_NOT_IN_SCOPE": 216,
        "INSUFFICIENT_PRODUCT_TRUTH": 3,
        "P6_READY": 438,
        "REVIEW_BLOCKED_WITH_EXACT_REASON": 2,
    }
    assert payload["unknown_product_type_p4_supported_count"] == 0
    assert payload["p6_launch_cohort_count"] == 438
    assert payload["matrix_sha256"] == "b" * 64
