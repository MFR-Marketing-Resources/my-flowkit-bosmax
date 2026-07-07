import { postAPI } from "./client";
import type {
	PosterPromptDraftRequest,
	PosterPromptDraftResponse,
} from "../types/posterPromptDraft";
import type { PosterBuilderDraft } from "../types/posterReadiness";

export function draftToPromptRequest(
	productId: string,
	draft: PosterBuilderDraft,
): PosterPromptDraftRequest {
	return {
		product_id: productId,
		...draft,
	};
}

export async function createPosterPromptDraft(
	payload: PosterPromptDraftRequest,
): Promise<PosterPromptDraftResponse> {
	return postAPI<PosterPromptDraftResponse>("/api/poster/prompt-draft", payload);
}