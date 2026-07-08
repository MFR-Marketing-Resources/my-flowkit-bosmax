import { postAPI } from "./client";
import type {
	PosterCopyQualityReport,
	PosterCopyQualityRequest,
} from "../types/posterCopyQuality";

/** Expert poster copy quality guard. Read-only analysis — no generation, no
 * credit spend. */
export async function fetchPosterCopyQuality(
	payload: PosterCopyQualityRequest,
): Promise<PosterCopyQualityReport> {
	return postAPI<PosterCopyQualityReport>("/api/poster/copy/quality", payload);
}
