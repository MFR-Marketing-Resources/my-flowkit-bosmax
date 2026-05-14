import type { BosmaxPromptToolContextResponse } from "../types";
import { fetchAPI } from "./client";

export async function fetchBosmaxPromptToolContext(): Promise<BosmaxPromptToolContextResponse> {
	return fetchAPI<BosmaxPromptToolContextResponse>(
		"/api/bosmax-authority/prompt-tool-context",
	);
}