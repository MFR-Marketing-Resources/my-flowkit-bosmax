import type {
	ProductAssetGeneratorRequest,
	ProductAssetGeneratorResponse,
} from "../types";
import { postAPI } from "./client";

export async function runProductAssetGeneratorPreview(
	request: ProductAssetGeneratorRequest,
): Promise<ProductAssetGeneratorResponse> {
	return postAPI<ProductAssetGeneratorResponse>(
		"/api/product-asset-generator/preview",
		{
			...request,
			dry_run_only: true,
		} as Record<string, unknown>,
	);
}
