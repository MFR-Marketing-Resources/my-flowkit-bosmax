// Prompt & SOP Library API — standalone human-reference CRUD + attachments.
// Decoupled from all generation surfaces.
import { deleteAPI, getAPI, patchAPI, postAPI, postMultipartAPI } from "./client";

export type PromptLibraryItemType =
	| "PROMPT"
	| "SOP"
	| "TUTORIAL"
	| "TEMPLATE"
	| "REFERENCE";
export type PromptLibraryStatus = "ACTIVE" | "ARCHIVED";

export interface PromptLibraryAttachment {
	id: string;
	item_id: string;
	file_name: string;
	mime: string;
	ext: string;
	size_bytes: number;
	created_at: string | null;
	preview_url: string;
	download_url: string;
}

export interface PromptLibraryItem {
	id: string;
	title: string;
	type: PromptLibraryItemType;
	category: string;
	description: string;
	content: string;
	tags: string[];
	status: PromptLibraryStatus;
	created_at: string | null;
	updated_at: string | null;
	attachments?: PromptLibraryAttachment[];
}

export interface PromptLibraryMeta {
	item_types: string[];
	statuses: string[];
	supported_attachment_extensions: string[];
}

export interface PromptLibraryItemInput {
	title: string;
	type: PromptLibraryItemType;
	category?: string;
	description?: string;
	content?: string;
	tags?: string[];
	status?: PromptLibraryStatus;
}

export async function fetchPromptLibraryMeta(): Promise<PromptLibraryMeta> {
	return getAPI("/api/prompt-library/meta");
}

export async function listPromptLibraryItems(params: {
	type?: string;
	category?: string;
	status?: string;
	search?: string;
	tag?: string;
} = {}): Promise<{ items: PromptLibraryItem[]; total: number }> {
	const q = new URLSearchParams();
	if (params.type) q.set("type", params.type);
	if (params.category) q.set("category", params.category);
	if (params.status) q.set("status", params.status);
	if (params.search) q.set("search", params.search);
	if (params.tag) q.set("tag", params.tag);
	const qs = q.toString();
	return getAPI(`/api/prompt-library/items${qs ? `?${qs}` : ""}`);
}

export async function getPromptLibraryItem(id: string): Promise<PromptLibraryItem> {
	return getAPI(`/api/prompt-library/items/${encodeURIComponent(id)}`);
}

export async function createPromptLibraryItem(
	body: PromptLibraryItemInput,
): Promise<PromptLibraryItem> {
	return postAPI("/api/prompt-library/items", body);
}

export async function updatePromptLibraryItem(
	id: string,
	body: Partial<PromptLibraryItemInput>,
): Promise<PromptLibraryItem> {
	return patchAPI(`/api/prompt-library/items/${encodeURIComponent(id)}`, body);
}

export async function archivePromptLibraryItem(id: string): Promise<PromptLibraryItem> {
	return postAPI(`/api/prompt-library/items/${encodeURIComponent(id)}/archive`, {});
}

export async function unarchivePromptLibraryItem(id: string): Promise<PromptLibraryItem> {
	return postAPI(`/api/prompt-library/items/${encodeURIComponent(id)}/unarchive`, {});
}

export async function deletePromptLibraryItem(id: string): Promise<void> {
	return deleteAPI(`/api/prompt-library/items/${encodeURIComponent(id)}`);
}

export async function addPromptLibraryAttachment(
	itemId: string,
	file: File,
): Promise<PromptLibraryAttachment> {
	const form = new FormData();
	form.append("file", file);
	return postMultipartAPI(
		`/api/prompt-library/items/${encodeURIComponent(itemId)}/attachments`,
		form,
	);
}

export async function deletePromptLibraryAttachment(
	itemId: string,
	attachmentId: string,
): Promise<void> {
	return deleteAPI(
		`/api/prompt-library/items/${encodeURIComponent(itemId)}/attachments/${encodeURIComponent(attachmentId)}`,
	);
}
