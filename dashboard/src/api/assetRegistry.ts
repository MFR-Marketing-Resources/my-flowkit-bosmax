import type {
	AssetCatalogResponse,
	AssetCompatibilityRequest,
	AssetCompatibilityResponse,
	AssetDetailResponse,
	AssetOptionsResponse,
	AssetSelectionRequest,
	AssetSelectionResponse,
} from "../types";
import { fetchAPI, postAPI } from "./client";

export async function fetchAssetCatalog(): Promise<AssetCatalogResponse> {
	return fetchAPI<AssetCatalogResponse>("/api/asset-registry/catalog");
}

export async function fetchAssetsByType(
	assetType: string,
): Promise<AssetOptionsResponse> {
	return fetchAPI<AssetOptionsResponse>(
		`/api/asset-registry/assets?asset_type=${encodeURIComponent(assetType)}`,
	);
}

export async function fetchAssetDetail(
	assetId: string,
): Promise<AssetDetailResponse> {
	return fetchAPI<AssetDetailResponse>(
		`/api/asset-registry/assets/${encodeURIComponent(assetId)}`,
	);
}

export async function resolveAssetSelection(
	request: AssetSelectionRequest,
): Promise<AssetSelectionResponse> {
	return postAPI<AssetSelectionResponse>(
		"/api/asset-registry/resolve-selection",
		request as unknown as Record<string, unknown>,
	);
}

export async function checkAssetCompatibility(
	request: AssetCompatibilityRequest,
): Promise<AssetCompatibilityResponse> {
	return postAPI<AssetCompatibilityResponse>(
		"/api/asset-registry/compatibility-check",
		request as unknown as Record<string, unknown>,
	);
}
