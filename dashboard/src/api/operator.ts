import type { ContentPackSummary } from "../types";
import { fetchAPI } from "./client";

export async function fetchOperatorContentPack(): Promise<ContentPackSummary> {
	return fetchAPI<ContentPackSummary>("/api/operator/content-pack");
}