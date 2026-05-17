import type {
	ApprovedProductPackage,
	WorkspaceExecutionPackage,
	WorkspaceMode,
} from "../types";
import { fetchAPI, postAPI } from "./client";

export async function fetchApprovedProductPackage(
	productId: string,
	mode: WorkspaceMode,
): Promise<ApprovedProductPackage> {
	return fetchAPI<ApprovedProductPackage>(
		`/api/products/${encodeURIComponent(productId)}/approved-package?mode=${encodeURIComponent(mode)}`,
	);
}

export async function createWorkspaceExecutionPackage(input: {
	product_id: string;
	mode: WorkspaceMode;
	duration_seconds?: number;
	aspect_ratio?: string;
	model?: string;
	manual_override?: boolean;
}): Promise<WorkspaceExecutionPackage> {
	return postAPI<WorkspaceExecutionPackage>(
		"/api/workspace/execution-package",
		{
			duration_seconds: 8,
			aspect_ratio: "9:16",
			manual_override: false,
			...input,
		},
	);
}

export async function fetchWorkspaceExecutionPackageHistory(
	productId?: string,
	mode?: WorkspaceMode,
	limit = 20,
): Promise<WorkspaceExecutionPackage[]> {
	const params = new URLSearchParams();
	if (productId) params.set("product_id", productId);
	if (mode) params.set("mode", mode);
	params.set("limit", String(limit));
	return fetchAPI<WorkspaceExecutionPackage[]>(
		`/api/workspace/execution-packages?${params.toString()}`,
	);
}
