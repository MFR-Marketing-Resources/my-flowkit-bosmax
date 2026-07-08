import { postAPI } from "./client";

export interface PosterCopyFitRequest {
	language: string;
	hook: string;
	subhook: string;
	usp_1: string;
	usp_2: string;
	usp_3: string;
	cta: string;
}

export interface PosterCopyFitFields {
	hook: string;
	subhook: string;
	usp_1: string;
	usp_2: string;
	usp_3: string;
	cta: string;
}

export interface PosterCopyFitResponse {
	applied: boolean;
	provider_configured: boolean;
	fields: PosterCopyFitFields;
	changed_fields: string[];
	still_over_limit: string[];
	warnings: string[];
}

/** AI-condense over-length poster copy to the poster limits. Suggestion-only —
 * the caller applies the returned fields to the draft; nothing is persisted. */
export async function fitPosterCopy(
	payload: PosterCopyFitRequest,
): Promise<PosterCopyFitResponse> {
	return postAPI<PosterCopyFitResponse>("/api/poster/copy/fit", payload);
}
