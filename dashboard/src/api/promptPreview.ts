import type { PromptPreviewRequest, PromptPreviewResponse } from "../types";
import { postAPI } from "./client";

export async function runOfflinePromptPreview(
	request: PromptPreviewRequest,
): Promise<PromptPreviewResponse> {
	return postAPI<PromptPreviewResponse>("/api/prompt-preview/offline", {
		...request,
		dry_run_only: true,
	} as Record<string, unknown>);
}
