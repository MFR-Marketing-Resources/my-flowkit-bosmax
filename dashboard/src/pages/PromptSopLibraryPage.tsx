import { useCallback, useEffect, useRef, useState } from "react";

import {
	addPromptLibraryAttachment,
	archivePromptLibraryItem,
	createPromptLibraryItem,
	deletePromptLibraryAttachment,
	deletePromptLibraryItem,
	getPromptLibraryItem,
	listPromptLibraryItems,
	unarchivePromptLibraryItem,
	updatePromptLibraryItem,
	type PromptLibraryItem,
	type PromptLibraryItemInput,
	type PromptLibraryItemType,
} from "../api/promptLibrary";

const ITEM_TYPES: PromptLibraryItemType[] = [
	"PROMPT",
	"SOP",
	"TUTORIAL",
	"TEMPLATE",
	"REFERENCE",
];

const TYPE_TONE: Record<PromptLibraryItemType, string> = {
	PROMPT: "bg-blue-500/15 text-blue-300",
	SOP: "bg-emerald-500/15 text-emerald-300",
	TUTORIAL: "bg-violet-500/15 text-violet-300",
	TEMPLATE: "bg-amber-500/15 text-amber-300",
	REFERENCE: "bg-slate-500/15 text-slate-300",
};

const EMPTY_FORM: PromptLibraryItemInput = {
	title: "",
	type: "PROMPT",
	category: "",
	description: "",
	content: "",
	tags: [],
	status: "ACTIVE",
};

const INPUT =
	"w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-blue-500 focus:outline-none";

export default function PromptSopLibraryPage() {
	const [items, setItems] = useState<PromptLibraryItem[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);

	const [search, setSearch] = useState("");
	const [typeFilter, setTypeFilter] = useState<string>("ALL");
	const [statusFilter, setStatusFilter] = useState<string>("ACTIVE");

	const [editorOpen, setEditorOpen] = useState(false);
	const [editingId, setEditingId] = useState<string | null>(null);
	const [form, setForm] = useState<PromptLibraryItemInput>(EMPTY_FORM);
	const [tagsInput, setTagsInput] = useState("");
	const [detail, setDetail] = useState<PromptLibraryItem | null>(null);
	const [copiedId, setCopiedId] = useState<string | null>(null);
	const fileRef = useRef<HTMLInputElement | null>(null);

	const load = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const res = await listPromptLibraryItems({
				search: search || undefined,
				type: typeFilter === "ALL" ? undefined : typeFilter,
				status: statusFilter === "ALL" ? undefined : statusFilter,
			});
			setItems(res.items);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load library");
		} finally {
			setLoading(false);
		}
	}, [search, typeFilter, statusFilter]);

	useEffect(() => {
		void load();
	}, [load]);

	const openCreate = () => {
		setEditingId(null);
		setForm(EMPTY_FORM);
		setTagsInput("");
		setDetail(null);
		setError(null);
		setEditorOpen(true);
	};

	const openEdit = useCallback(async (id: string) => {
		setBusy(true);
		setError(null);
		try {
			const item = await getPromptLibraryItem(id);
			setEditingId(id);
			setForm({
				title: item.title,
				type: item.type,
				category: item.category,
				description: item.description,
				content: item.content,
				tags: item.tags,
				status: item.status,
			});
			setTagsInput(item.tags.join(", "));
			setDetail(item);
			setEditorOpen(true);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to open item");
		} finally {
			setBusy(false);
		}
	}, []);

	const save = useCallback(async () => {
		setBusy(true);
		setError(null);
		const tags = tagsInput
			.split(",")
			.map((t) => t.trim())
			.filter(Boolean);
		try {
			if (editingId) {
				const updated = await updatePromptLibraryItem(editingId, { ...form, tags });
				setDetail(updated);
			} else {
				const created = await createPromptLibraryItem({ ...form, tags });
				setEditingId(created.id);
				setDetail(created);
			}
			await load();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Save failed");
		} finally {
			setBusy(false);
		}
	}, [editingId, form, tagsInput, load]);

	const refreshDetail = useCallback(async (id: string) => {
		try {
			setDetail(await getPromptLibraryItem(id));
		} catch {
			/* ignore refresh error */
		}
	}, []);

	const onAddAttachment = useCallback(
		async (file: File) => {
			if (!editingId) return;
			setBusy(true);
			setError(null);
			try {
				await addPromptLibraryAttachment(editingId, file);
				await refreshDetail(editingId);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Attachment upload failed");
			} finally {
				setBusy(false);
				if (fileRef.current) fileRef.current.value = "";
			}
		},
		[editingId, refreshDetail],
	);

	const onRemoveAttachment = useCallback(
		async (attachmentId: string) => {
			if (!editingId) return;
			setBusy(true);
			try {
				await deletePromptLibraryAttachment(editingId, attachmentId);
				await refreshDetail(editingId);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Attachment delete failed");
			} finally {
				setBusy(false);
			}
		},
		[editingId, refreshDetail],
	);

	const onCopy = useCallback(async (item: PromptLibraryItem) => {
		try {
			await navigator.clipboard.writeText(item.content || "");
			setCopiedId(item.id);
			window.setTimeout(() => setCopiedId(null), 1500);
		} catch {
			setError("Clipboard copy is not available in this context.");
		}
	}, []);

	const onToggleArchive = useCallback(
		async (item: PromptLibraryItem) => {
			setBusy(true);
			try {
				if (item.status === "ARCHIVED") await unarchivePromptLibraryItem(item.id);
				else await archivePromptLibraryItem(item.id);
				await load();
				if (detail?.id === item.id) await refreshDetail(item.id);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Archive toggle failed");
			} finally {
				setBusy(false);
			}
		},
		[load, detail, refreshDetail],
	);

	const onDelete = useCallback(
		async (item: PromptLibraryItem) => {
			if (!window.confirm(`Delete "${item.title}" and its attachments? This cannot be undone.`)) {
				return;
			}
			setBusy(true);
			try {
				await deletePromptLibraryItem(item.id);
				if (editingId === item.id) {
					setEditorOpen(false);
					setEditingId(null);
				}
				await load();
			} catch (err) {
				setError(err instanceof Error ? err.message : "Delete failed");
			} finally {
				setBusy(false);
			}
		},
		[load, editingId],
	);

	return (
		<div className="min-h-screen bg-slate-950 p-6 text-slate-100">
			<div className="mx-auto max-w-6xl">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div>
						<h1 className="text-2xl font-semibold text-white">Prompt &amp; SOP Library</h1>
						<p className="mt-1 max-w-2xl text-sm text-slate-400">
							A reusable internal reference library for prompts, SOPs, tutorials,
							templates, and references. Human reference storage only — it does not
							feed generation.
						</p>
					</div>
					<button
						type="button"
						onClick={openCreate}
						className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
					>
						New item
					</button>
				</div>

				{error && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-300">
						{error}
					</div>
				)}

				<div className="mt-5 flex flex-wrap gap-3">
					<input
						className={`${INPUT} max-w-xs`}
						placeholder="Search title, description, content…"
						value={search}
						onChange={(e) => setSearch(e.target.value)}
					/>
					<select className={`${INPUT} max-w-[10rem]`} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
						<option value="ALL">All types</option>
						{ITEM_TYPES.map((t) => (
							<option key={t} value={t}>
								{t}
							</option>
						))}
					</select>
					<select className={`${INPUT} max-w-[10rem]`} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
						<option value="ACTIVE">Active</option>
						<option value="ARCHIVED">Archived</option>
						<option value="ALL">All statuses</option>
					</select>
				</div>

				<div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
					{loading ? (
						<div className="text-sm text-slate-500">Loading…</div>
					) : items.length === 0 ? (
						<div className="text-sm text-slate-500">No items yet.</div>
					) : (
						items.map((item) => (
							<div
								key={item.id}
								className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4"
							>
								<div className="flex items-start justify-between gap-3">
									<button
										type="button"
										onClick={() => void openEdit(item.id)}
										className="text-left"
									>
										<div className="font-medium text-white">{item.title}</div>
										<div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
											<span className={`rounded-full px-2 py-0.5 ${TYPE_TONE[item.type]}`}>
												{item.type}
											</span>
											{item.category && (
												<span className="text-slate-400">{item.category}</span>
											)}
											{item.status === "ARCHIVED" && (
												<span className="text-amber-300">archived</span>
											)}
										</div>
									</button>
								</div>
								{item.description && (
									<p className="mt-2 line-clamp-2 text-sm text-slate-400">{item.description}</p>
								)}
								<div className="mt-3 flex flex-wrap gap-2 text-xs">
									<button
										type="button"
										onClick={() => void onCopy(item)}
										className="rounded-lg border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800"
									>
										{copiedId === item.id ? "Copied!" : "Copy content"}
									</button>
									<button
										type="button"
										onClick={() => void openEdit(item.id)}
										className="rounded-lg border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800"
									>
										View / Edit
									</button>
									<button
										type="button"
										onClick={() => void onToggleArchive(item)}
										className="rounded-lg border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800"
									>
										{item.status === "ARCHIVED" ? "Unarchive" : "Archive"}
									</button>
									<button
										type="button"
										onClick={() => void onDelete(item)}
										className="rounded-lg border border-red-500/30 px-2 py-1 text-red-300 hover:bg-red-500/10"
									>
										Delete
									</button>
								</div>
							</div>
						))
					)}
				</div>
			</div>

			{editorOpen && (
				<div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4">
					<div className="my-8 w-full max-w-2xl rounded-3xl border border-slate-800 bg-slate-950 p-6">
						<div className="flex items-center justify-between">
							<h2 className="text-lg font-semibold text-white">
								{editingId ? "Edit item" : "New item"}
							</h2>
							<button
								type="button"
								onClick={() => setEditorOpen(false)}
								className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800"
							>
								Close
							</button>
						</div>

						<div className="mt-4 grid grid-cols-1 gap-3">
							<label className="text-xs text-slate-400">
								Title
								<input
									className={`${INPUT} mt-1`}
									value={form.title}
									onChange={(e) => setForm({ ...form, title: e.target.value })}
								/>
							</label>
							<div className="grid grid-cols-2 gap-3">
								<label className="text-xs text-slate-400">
									Type
									<select
										className={`${INPUT} mt-1`}
										value={form.type}
										onChange={(e) => setForm({ ...form, type: e.target.value as PromptLibraryItemType })}
									>
										{ITEM_TYPES.map((t) => (
											<option key={t} value={t}>
												{t}
											</option>
										))}
									</select>
								</label>
								<label className="text-xs text-slate-400">
									Category
									<input
										className={`${INPUT} mt-1`}
										value={form.category ?? ""}
										onChange={(e) => setForm({ ...form, category: e.target.value })}
									/>
								</label>
							</div>
							<label className="text-xs text-slate-400">
								Description / usage notes
								<textarea
									className={`${INPUT} mt-1 min-h-[60px]`}
									value={form.description ?? ""}
									onChange={(e) => setForm({ ...form, description: e.target.value })}
								/>
							</label>
							<label className="text-xs text-slate-400">
								Main content
								<textarea
									className={`${INPUT} mt-1 min-h-[160px] font-mono`}
									value={form.content ?? ""}
									onChange={(e) => setForm({ ...form, content: e.target.value })}
								/>
							</label>
							<label className="text-xs text-slate-400">
								Tags (comma-separated)
								<input
									className={`${INPUT} mt-1`}
									value={tagsInput}
									onChange={(e) => setTagsInput(e.target.value)}
								/>
							</label>
						</div>

						<div className="mt-4 flex flex-wrap gap-2">
							<button
								type="button"
								disabled={busy}
								onClick={() => void save()}
								className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
							>
								{busy ? "Saving…" : editingId ? "Save changes" : "Create item"}
							</button>
							{detail && (
								<button
									type="button"
									disabled={busy}
									onClick={() => void onCopy(detail)}
									className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
								>
									{copiedId === detail.id ? "Copied!" : "Copy content"}
								</button>
							)}
						</div>

						<div className="mt-6 border-t border-slate-800 pt-4">
							<h3 className="text-sm font-semibold text-white">Attachments</h3>
							{!editingId ? (
								<p className="mt-1 text-xs text-slate-500">
									Save the item first to add attachments.
								</p>
							) : (
								<>
									<div className="mt-2 flex flex-col gap-2">
										{(detail?.attachments ?? []).length === 0 && (
											<p className="text-xs text-slate-500">No attachments.</p>
										)}
										{(detail?.attachments ?? []).map((att) => (
											<div
												key={att.id}
												className="flex items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-sm"
											>
												<div className="min-w-0">
													<div className="truncate text-slate-200">{att.file_name}</div>
													<div className="text-xs text-slate-500">
														{att.ext.toUpperCase()} · {Math.max(1, Math.round(att.size_bytes / 1024))} KB
													</div>
												</div>
												<div className="flex shrink-0 gap-2 text-xs">
													<a
														href={att.preview_url}
														target="_blank"
														rel="noreferrer"
														className="rounded-lg border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800"
													>
														Preview
													</a>
													<a
														href={att.download_url}
														className="rounded-lg border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800"
													>
														Download
													</a>
													<button
														type="button"
														onClick={() => void onRemoveAttachment(att.id)}
														className="rounded-lg border border-red-500/30 px-2 py-1 text-red-300 hover:bg-red-500/10"
													>
														Remove
													</button>
												</div>
											</div>
										))}
									</div>
									<div className="mt-3">
										<input
											ref={fileRef}
											type="file"
											className="hidden"
											onChange={(e) => {
												const file = e.target.files?.[0];
												if (file) void onAddAttachment(file);
											}}
										/>
										<button
											type="button"
											disabled={busy}
											onClick={() => fileRef.current?.click()}
											className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
										>
											Add attachment
										</button>
									</div>
								</>
							)}
						</div>
					</div>
				</div>
			)}
		</div>
	);
}
