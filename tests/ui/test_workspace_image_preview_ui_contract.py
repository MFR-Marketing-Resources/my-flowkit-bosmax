from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workspace_image_preview_slots_fail_closed():
    slot_source = _read("dashboard/src/components/workspace/WorkspaceImageAssetSlot.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_source = _read("dashboard/src/components/workspace/IMGModule.tsx")

    for token in [
        "Image preview failed",
        "Open Preview",
        "Download",
        "Replace image",
        "onError",
    ]:
        assert token in slot_source

    assert "Image preview failed. Upload a manual Start Frame replacement" in f2v_source
    assert "WorkspaceImageAssetSlot" in f2v_source
    assert "WorkspaceImageAssetSlot" in i2v_source
    assert "WorkspaceImageAssetSlot" in img_source


def test_compact_visual_combobox_is_shared_across_production_pickers():
    picker_source = _read("dashboard/src/components/workspace/VisualAssetPicker.tsx")
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    binding_source = _read(
        "dashboard/src/components/workspace/CanonicalReferenceBindingControls.tsx"
    )
    fastlane_source = _read("dashboard/src/pages/ImgFastlanePage.tsx")

    for token in [
        'aria-haspopup="listbox"',
        'role="listbox"',
        "max-h-72",
        "VisualAssetPreview",
        "Close preview",
        "onChange(item.value)",
    ]:
        assert token in picker_source

    assert "VisualAssetPicker" in binding_source
    assert "[field]: value || null" in binding_source
    assert operator_source.count('status: "APPROVED"') >= 2
    assert "VisualAssetPicker" in fastlane_source
    assert "handlePickSceneContext" in fastlane_source
    assert "/api/flow/retrieved/" in fastlane_source


def test_product_and_rpa_visual_summary_use_browser_safe_product_image_route():
    product_picker_source = _read(
        "dashboard/src/components/workspace/SearchableProductSelect.tsx"
    )
    rpa_source = _read("dashboard/src/pages/RpaProductionStudioPage.tsx")

    assert "VisualAssetPreview" in product_picker_source
    assert "/api/products/${encodeURIComponent(product.id)}/image" in product_picker_source
    assert 'data-testid="product-option"' in product_picker_source
    assert "onSelect(product)" in product_picker_source

    assert 'data-testid="studio-selected-product-visual"' in rpa_source
    assert "VisualAssetPreview" in rpa_source
    assert "/api/products/${encodeURIComponent(selectedProduct.id)}/image" in rpa_source
