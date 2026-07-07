export type PosterFlowAspectRatio = "9:16" | "1:1" | "16:9" | "4:3" | "3:4";

export type PosterFlowVariantCount = 1 | 2 | 3 | 4;

export interface PosterFlowMirrorSettings {
	aspect_ratio: PosterFlowAspectRatio;
	count: PosterFlowVariantCount;
	image_model: string;
}

export const DEFAULT_POSTER_FLOW_MIRROR_SETTINGS: PosterFlowMirrorSettings = {
	aspect_ratio: "9:16",
	count: 1,
	image_model: "Nano Banana 2",
};

export function isPosterFlowAspectRatio(value: string): value is PosterFlowAspectRatio {
	return ["9:16", "1:1", "16:9", "4:3", "3:4"].includes(value);
}