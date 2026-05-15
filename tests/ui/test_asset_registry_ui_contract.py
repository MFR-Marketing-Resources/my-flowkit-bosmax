from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_asset_registry_wraps_long_asset_warning_and_provenance_content():
    detail_source = _read("dashboard/src/components/asset-registry/AssetDetailPanel.tsx")
    options_source = _read("dashboard/src/components/asset-registry/AssetOptionsTable.tsx")
    page_source = _read("dashboard/src/pages/AssetRegistryPage.tsx")

    for token in [
        "bosmax-json-block",
        "bosmax-warning-list",
        "bosmax-warning-chip",
        "bosmax-provenance-list",
        "bosmax-kv-row",
        "bosmax-pre-wrap-safe",
    ]:
        assert token in detail_source

    for token in [
        "md:grid-cols-[minmax(0,1.2fr)_160px_110px_110px]",
        "bosmax-wrap-safe",
        "bosmax-pre-wrap-safe",
        "bosmax-warning-list",
        "bosmax-warning-chip",
    ]:
        assert token in options_source

    assert "2xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.95fr)]" in page_source


def test_asset_registry_no_truncate_on_primary_asset_rows():
    source = _read("dashboard/src/components/asset-registry/AssetOptionsTable.tsx")

    assert "truncate text-xs font-semibold" not in source
    assert "truncate text-[10px]" not in source
