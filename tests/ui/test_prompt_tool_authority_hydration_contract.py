from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
	return (ROOT / relative_path).read_text(encoding="utf-8")


def test_prompt_tool_hydration_prefers_bosmax_authority_adapter():
	bosmax_api = _read("dashboard/src/api/bosmaxAuthority.ts")
	hydration = _read("dashboard/src/components/prompt-tool/usePromptToolHydration.ts")

	assert "/api/bosmax-authority/prompt-tool-context" in bosmax_api
	assert "fetchBosmaxPromptToolContext" in hydration
	assert "authority" in hydration
	assert "styleReferenceOptions" in hydration
	assert "overlayHintOptions" in hydration
	assert "productHandlingOptions" in hydration
	assert "productPhysicsOptions" in hydration
	assert "sourceRouteOptions" in hydration
	assert "durationOptions" in hydration


def test_prompt_preview_and_product_asset_generator_consume_authority_context():
	prompt_form = _read("dashboard/src/components/prompt-preview/PromptPreviewForm.tsx")
	asset_form = _read("dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx")

	for source in [prompt_form, asset_form]:
		assert "getProductContext" in source
		assert "getCopySignals" in source
		assert "Authority Product Context" in source
		assert "Authority Copy Signals" in source
		assert "Source Warnings" in source
		assert "product handling" in source.lower()
		assert "product physics" in source.lower()
		assert "manual fallback" in source.lower()
		assert "NOT_FOUND" in source


def test_manual_paste_lane_remains_and_no_forbidden_execution_controls_exist():
	targets = [
		"dashboard/src/api/bosmaxAuthority.ts",
		"dashboard/src/components/prompt-tool/usePromptToolHydration.ts",
		"dashboard/src/components/prompt-preview/PromptPreviewForm.tsx",
		"dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx",
	]
	combined = "\n".join(_read(path) for path in targets)

	assert "Product Payload JSON" in combined
	assert "Manual override remains available" in combined

	for token in [
		"Send to Flow",
		"Generate in Flow",
		"Upload to Flow",
		"Extend Now",
		"Insert Now",
		"Batch Execute",
		"chrome.runtime",
	]:
		assert token not in combined