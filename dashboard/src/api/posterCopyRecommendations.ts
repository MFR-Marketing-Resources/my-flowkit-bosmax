import { postAPI } from "./client";
import type {
	PosterCopyRecommendationsRequest,
	PosterCopyRecommendationsResponse,
} from "../types/posterCopyRecommendations";

export async function fetchPosterCopyRecommendations(
	payload: PosterCopyRecommendationsRequest,
): Promise<PosterCopyRecommendationsResponse> {
	return postAPI<PosterCopyRecommendationsResponse>(
		"/api/poster/copy-recommendations",
		payload,
	);
}