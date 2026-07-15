import { getAPI } from "./client";

export interface RecommendedAvatar {
	avatar_code: string;
	character_name?: string;
	variant?: string;
	environment?: string;
	fit_score: number;
	fit_source: string;
	suitability_notes?: string | null;
}

export interface AvatarRecommendation {
	product_id?: string;
	product_name?: string | null;
	category?: string | null;
	cluster: string;
	cluster_source: string;
	avatar_count: number;
	avatars: RecommendedAvatar[];
}

export function getAvatarRecommendationForProduct(productId: string) {
	return getAPI<AvatarRecommendation>(
		`/api/creative-intelligence/avatar-recommendation?product_id=${encodeURIComponent(productId)}`,
	);
}
