import { fetchAPI } from "./client";
import type { PosterReadinessResponse } from "../types/posterReadiness";

export async function fetchPosterReadiness(
	productId: string,
): Promise<PosterReadinessResponse> {
	return fetchAPI<PosterReadinessResponse>(
		`/api/products/${encodeURIComponent(productId)}/poster-readiness`,
	);
}