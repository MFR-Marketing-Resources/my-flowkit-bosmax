import type { ContentPackSummary } from "../types";
import { fetchAPI, postAPI } from "./client";

export async function fetchOperatorContentPack(): Promise<ContentPackSummary> {
	return fetchAPI<ContentPackSummary>("/api/operator/content-pack");
}

// ─── Flow tab readiness (the proven pre-fire drill) ─────────────────────────
// Live lessons: a COLD fresh tab fails CAPTCHA pre-approve; a stale content
// script fails CONTENT_BUILD_MISMATCH at binding. Both are 0-credit failures,
// but surfacing readiness BEFORE the fire click saves the retry loop.

export interface FlowPageState {
	flow_url?: string | null;
	editor_capability_ready?: boolean | null;
	build_match?: boolean | null;
	content_script_loaded?: boolean | null;
	[key: string]: unknown;
}

export async function fetchFlowPageState(mode = "F2V"): Promise<FlowPageState> {
	return postAPI<FlowPageState>("/api/operator/flow-page-state-diagnostic", { mode });
}

/** Ask the extension to open Google Flow and create a FRESH (clean) project.
 *  Navigation is async — poll fetchFlowPageState until a /project/ editor is ready. */
export async function openFlowNewProject(mode = "F2V"): Promise<Record<string, unknown>> {
	return postAPI<Record<string, unknown>>("/api/operator/open-flow-new-project", { mode });
}