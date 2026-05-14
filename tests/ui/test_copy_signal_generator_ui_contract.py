from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_copy_signal_generator_ui_shows_scale_and_camera_lock_fields():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )
    result_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx"
    )

    combined = form_source + "\n" + result_source
    for token in [
        "Product Scale Prompt",
        "Scale Truth Status",
        "Camera Capture Mode",
        "UGC iPhone Raw Camera Lock",
        "Cinematic Camera Prompt",
        "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED",
    ]:
        assert token in combined


def test_copy_signal_generator_ui_contains_no_forbidden_execution_controls():
    targets = [
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx",
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx",
    ]
    banned_tokens = [
        "Generate in Flow",
        "Send to Flow",
        "Upload to Flow",
        "Extend Now",
        "Insert Now",
        "Batch Execute",
    ]
    combined = "\n".join(_read(path) for path in targets)
    for token in banned_tokens:
        assert token not in combined