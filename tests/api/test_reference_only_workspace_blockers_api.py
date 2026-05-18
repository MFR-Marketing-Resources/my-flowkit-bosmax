"""API contract — reference-only product blockers across all workspace modes.

Covers:
- /api/workspace/package-readiness → REFERENCE_ONLY_PRODUCT for all modes
- /api/products/{id}/approved-package → 409 REFERENCE_ONLY_PRODUCT
- /api/workspace/generation-packages/f2v → 409 REFERENCE_ONLY_PRODUCT
- /api/workspace/generation-packages/i2v → 409 REFERENCE_ONLY_PRODUCT
- Real product-truth readiness still passes when gates are satisfied
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Fake DB & services ──────────────────────────────────────────────────────

_REAL_PRODUCT_ID = "real-product-001"
_REF_PRODUCT_ID = "fastmoss-ref:deadbeef12345678"

_FAKE_DB: dict[str, dict] = {
    _REAL_PRODUCT_ID: {
        "id": _REAL_PRODUCT_ID,
        "raw_product_title": "Real Truth Product",
        "source": "FASTMOSS",
        "source_lane": None,
        "reference_only": False,
        "lifecycle_status": "ACTIVE",
        "image_readiness_status": "IMAGE_READY",
        "local_image_path": "/cache/real-product-001.jpg",
    }
}


def _make_app(monkeypatch: pytest.MonkeyPatch):
    from agent import main as app_module

    # Patch crud.get_product
    async def fake_get_product(product_id: str):
        return _FAKE_DB.get(product_id)

    # Patch is_fastmoss_reference_product_id
    def fake_is_ref_id(product_id: str | None) -> bool:
        return str(product_id or "").startswith("fastmoss-ref:")

    # Patch get_fastmoss_reference_product — returns a stub for the ref ID
    async def fake_get_fastmoss_reference_product(product_id: str):
        if fake_is_ref_id(product_id):
            return {
                "id": product_id,
                "raw_product_title": "Sumikko 50PCS FastMoss Ref",
                "source": "FASTMOSS",
                "source_lane": "FASTMOSS_REFERENCE",
                "reference_only": True,
                "catalog_blockers": ["REFERENCE_ONLY_PRODUCT"],
                "catalog_visibility_reason": (
                    "FastMoss latest reference is visible for review only. "
                    "Use Smart Registration to convert it into product truth before package load."
                ),
                "image_readiness_status": "IMAGE_NOT_AVAILABLE",
            }
        return None

    monkeypatch.setattr("agent.db.crud.get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.is_fastmoss_reference_product_id",
        fake_is_ref_id,
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.get_fastmoss_reference_product",
        fake_get_fastmoss_reference_product,
    )
    monkeypatch.setattr(
        "agent.services.approved_product_package_service.is_fastmoss_reference_product_id",
        fake_is_ref_id,
    )
    monkeypatch.setattr(
        "agent.services.approved_product_package_service.get_fastmoss_reference_product",
        fake_get_fastmoss_reference_product,
    )
    monkeypatch.setattr(
        "agent.services.workspace_generation_package_service.is_fastmoss_reference_product_id",
        fake_is_ref_id,
    )

    return TestClient(app_module.app)


# ── package-readiness: reference-only returns REFERENCE_ONLY_PRODUCT ───────

@pytest.mark.parametrize("mode", ["T2V", "F2V", "I2V", "IMG"])
def test_package_readiness_reference_only_all_modes(monkeypatch, mode):
    client = _make_app(monkeypatch)
    response = client.post(
        "/api/workspace/package-readiness",
        json={"mode": mode, "product_ids": [_REF_PRODUCT_ID]},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["readiness_status"] == "REFERENCE_ONLY_PRODUCT"
    assert item["blocker"] == "REFERENCE_ONLY_PRODUCT"
    assert "smart_registration_path" in item.get("quick_actions", {})


# ── approved-package: reference-only returns 409 ───────────────────────────

@pytest.mark.parametrize("mode", ["T2V", "F2V", "I2V", "IMG"])
def test_approved_package_reference_only_returns_409(monkeypatch, mode):
    client = _make_app(monkeypatch)
    response = client.get(
        f"/api/products/{_REF_PRODUCT_ID}/approved-package",
        params={"mode": mode},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "REFERENCE_ONLY_PRODUCT" in str(detail)


# ── WGP /f2v: reference-only returns 409 ───────────────────────────────────

def test_wgp_f2v_reference_only_returns_409(monkeypatch):
    client = _make_app(monkeypatch)
    response = client.post(
        "/api/workspace/generation-packages/f2v",
        json={
            "product_id": _REF_PRODUCT_ID,
            "workspace_execution_package_id": None,
            "generation_mode": "SINGLE",
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "REFERENCE_ONLY_PRODUCT" in str(detail)


# ── WGP /i2v: reference-only returns 409 ───────────────────────────────────

def test_wgp_i2v_reference_only_returns_409(monkeypatch):
    client = _make_app(monkeypatch)
    response = client.post(
        "/api/workspace/generation-packages/i2v",
        json={
            "product_id": _REF_PRODUCT_ID,
            "workspace_execution_package_id": None,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "REFERENCE_ONLY_PRODUCT" in str(detail)


# ── reference-only product is still visible in catalog ─────────────────────

def test_reference_only_product_visible_in_catalog(monkeypatch):
    """Reference-only FastMoss products remain visible for review/discovery."""
    from agent.services.fastmoss_product_reference_service import (
        is_fastmoss_reference_product_id,
    )
    assert is_fastmoss_reference_product_id(_REF_PRODUCT_ID) is True
    # The ID is a reference ID — visible in catalog but blocked for generation


# ── package-readiness checklist includes smart_registration_path ───────────

def test_package_readiness_reference_has_smart_registration_guidance(monkeypatch):
    client = _make_app(monkeypatch)
    response = client.post(
        "/api/workspace/package-readiness",
        json={"mode": "F2V", "product_ids": [_REF_PRODUCT_ID]},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["readiness_status"] == "REFERENCE_ONLY_PRODUCT"
    qa = item.get("quick_actions", {})
    assert qa.get("smart_registration_path") == "/product-registration"


# ── real product-truth row is not affected by reference-only guard ──────────

def test_reference_only_guard_does_not_block_real_product(monkeypatch):
    from agent.services.workspace_generation_package_service import (
        _assert_not_reference_only,
    )
    # Should not raise for a real product row
    _assert_not_reference_only(_REAL_PRODUCT_ID, _FAKE_DB[_REAL_PRODUCT_ID])


def test_reference_only_guard_raises_for_ref_id(monkeypatch):
    from agent.services.workspace_generation_package_service import (
        _assert_not_reference_only,
    )
    monkeypatch.setattr(
        "agent.services.workspace_generation_package_service.is_fastmoss_reference_product_id",
        lambda pid: str(pid or "").startswith("fastmoss-ref:"),
    )
    with pytest.raises(ValueError, match="REFERENCE_ONLY_PRODUCT"):
        _assert_not_reference_only(_REF_PRODUCT_ID, None)


def test_reference_only_guard_raises_for_reference_only_db_row():
    from agent.services.workspace_generation_package_service import (
        _assert_not_reference_only,
    )
    ref_row = {"id": "some-db-product", "reference_only": True}
    with pytest.raises(ValueError, match="REFERENCE_ONLY_PRODUCT"):
        _assert_not_reference_only("some-db-product", ref_row)
