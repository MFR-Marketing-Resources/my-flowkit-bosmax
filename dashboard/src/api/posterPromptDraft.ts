import { postAPI } from "./client";
import type {
	PosterPromptDraftRequest,
	PosterPromptDraftResponse,
} from "../types/posterPromptDraft";
import type { PosterBuilderDraft } from "../types/posterReadiness";

export function formatPosterPromptDraftError(err: unknown): string {
	if (!(err instanceof Error)) return "Prompt draft failed";
	const raw = err.message;
	const jsonStart = raw.indexOf("{");
	if (jsonStart < 0) return raw;
	try {
		const body = JSON.parse(raw.slice(jsonStart)) as {
			detail?: { message?: string; field_errors?: string[] };
		};
		const detail = body.detail;
		if (detail?.message) {
			const fields = detail.field_errors?.length
				? detail.field_errors.join("; ")
				: "";
			return fields ? `${detail.message} ${fields}` : detail.message;
		}
	} catch {
		/* fall through */
	}
	return raw;
}

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