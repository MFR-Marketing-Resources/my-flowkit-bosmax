import type {
	F2VGenerationPackageRequest,
	I2VGenerationPackageRequest,
	WorkspaceGenerationPackage,
	WorkspaceGenerationPackageListResponse,
} from "../types";
import { fetchAPI, patchAPI, postAPI } from "./client";

export async function deleteWorkspaceGenerationPackage(
	packageId: string,
): Promise<void> {
	await fetchAPI<void>(`/api/workspace/generation-packages/${encodeURIComponent(packageId)}`, {
		method: "DELETE",
	});
}

const BASE = "/api/workspace/generation-packages";

export async function listWorkspaceGenerationPackages(params?: {
	mode?: string;
	status?: string;
	product_id?: string;
	batch_run_id?: string;
	limit?: number;
}): Promise<WorkspaceGenerationPackageListResponse> {
	const qs = new URLSearchParams();
	if (params?.mode) qs.set("mode", params.mode);
	if (params?.status) qs.set("status", params.status);
	if (params?.product_id) qs.set("product_id", params.product_id);
	if (params?.batch_run_id) qs.set("batch_run_id", params.batch_run_id);
	if (params?.limit != null) qs.set("limit", String(params.limit));
	const query = qs.toString() ? `?${qs.toString()}` : "";
	return fetchAPI<WorkspaceGenerationPackageListResponse>(`${BASE}${query}`);
}

export async function getWorkspaceGenerationPackage(
	packageId: string,
): Promise<WorkspaceGenerationPackage> {
	return fetchAPI<WorkspaceGenerationPackage>(
		`${BASE}/${encodeURIComponent(packageId)}`,
	);
}

export async function createF2VGenerationPackage(
	input: F2VGenerationPackageRequest,
): Promise<WorkspaceGenerationPackage> {
	return postAPI<WorkspaceGenerationPackage>(`${BASE}/f2v`, input);
}

export async function createI2VGenerationPackage(
	input: I2VGenerationPackageRequest,
): Promise<WorkspaceGenerationPackage> {
	return postAPI<WorkspaceGenerationPackage>(`${BASE}/i2v`, input);
}

export async function createFromExecutionPackage(
	workspaceExecutionPackageId: string,
	mode: "F2V" | "I2V" = "F2V",
): Promise<WorkspaceGenerationPackage> {
	const qs = new URLSearchParams({
		workspace_execution_package_id: workspaceExecutionPackageId,
		mode,
	});
	return postAPI<WorkspaceGenerationPackage>(
		`${BASE}/from-execution-package?${qs.toString()}`,
		{},
	);
}

export async function patchWorkspaceGenerationPackage(
	packageId: string,
	patch: { status?: string; operator_notes?: string | null },
): Promise<WorkspaceGenerationPackage> {
	return patchAPI<WorkspaceGenerationPackage>(
		`${BASE}/${encodeURIComponent(packageId)}`,
		patch,
	);
}
