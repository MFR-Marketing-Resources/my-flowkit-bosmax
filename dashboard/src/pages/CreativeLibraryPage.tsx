import { useEffect, useMemo, useState } from "react";
import {
	archiveCreativeAsset,
	createCreativeAsset,
	fetchCreativeAssets,
	unarchiveCreativeAsset,
	updateCreativeAsset,
} from "../api/creativeAssets";
import type {
	CreativeAsset,
	CreativeAssetEngineSlot,
	CreativeAssetSemanticRole,
	CreativeAssetStatus,
	WorkspaceMode,
} from "../types";

const ROLE_OPTIONS: CreativeAssetSemanticRole[] = [
	"PRODUCT_REFERENCE",
	"CHARACTER_REFERENCE",
	"SCENE_CONTEXT_REFERENCE",
	"STYLE_REFERENCE",
	"COMPOSITE_FRAME_REFERENCE",
];
const STATUS_OPTIONS: Array<CreativeAssetStatus | "ALL"> = [
	"ALL",
	"ACTIVE",
	"ARCHIVED",
];
const MODE_OPTIONS: WorkspaceMode[] = ["T2V", "F2V", "I2V", "IMG"];
const SLOT_OPTIONS: CreativeAssetEngineSlot[] = [
	"subject",
	"scene",
	"style",
	"start_frame",
	"end_frame",
];

interface CreateFormState {
	display_name: string;
	semantic_role: CreativeAssetSemanticRole;
	description: string;
	product_id: string;
	category: string;
	silo: string;
	product_type: string;
	allowed_modes: WorkspaceMode[];
	engine_slot_eligibility: CreativeAssetEngineSlot[];
	visual_dna_summary: string;
	character_dna: string;
	scene_context_dna: string;
	style_mood_dna: string;
	mode_a_metadata_handoff: string;
	remote_source_url: string;
}

const INITIAL_FORM: CreateFormState = {
	display_name: "",
	semantic_role: "CHARACTER_REFERENCE",
	description: "",
	product_id: "",
	category: "",
	silo: "",
	product_type: "",
	allowed_modes: ["I2V"],
	engine_slot_eligibility: ["scene"],
	visual_dna_summary: "",
	character_dna: "",
	scene_context_dna: "",
	style_mood_dna: "",
	mode_a_metadata_handoff: "",
	remote_source_url: "",
};

function toggleArrayValue<T extends string>(items: T[], value: T): T[] {
	return items.includes(value)
		? items.filter((item) => item !== value)
		: [...items, value];
}

async function loadCreativeLibraryAssets(
	roleFilter: CreativeAssetSemanticRole | "ALL",
	statusFilter: CreativeAssetStatus | "ALL",
	search: string,
	setError: (value: string | null) => void,
	setItems: (value: CreativeAsset[]) => void,
	setSelectedAssetId: (
		value: string | null | ((current: string | null) => string | null),
	) => void,
) {
	setError(null);
	try {
		const response = await fetchCreativeAssets({
			semantic_role: roleFilter === "ALL" ? undefined : roleFilter,
			status: statusFilter === "ALL" ? undefined : statusFilter,
			search: search || undefined,
			limit: 250,
		});
		setItems(response.items);
		setSelectedAssetId((current) =>
			current && response.items.some((item) => item.asset_id === current)
				? current
				: (response.items[0]?.asset_id ?? null),
		);
	} catch (err) {
		setError(
			err instanceof Error ? err.message : "Failed to load Creative Library.",
		);
	}
}

export default function CreativeLibraryPage() {
	const [items, setItems] = useState<CreativeAsset[]>([]);
	const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
	const [roleFilter, setRoleFilter] = useState<
		CreativeAssetSemanticRole | "ALL"
	>("ALL");
	const [statusFilter, setStatusFilter] = useState<CreativeAssetStatus | "ALL">(
		"ACTIVE",
	);
	const [search, setSearch] = useState("");
	const [form, setForm] = useState<CreateFormState>(INITIAL_FORM);
	const [selectedFile, setSelectedFile] = useState<File | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const selectedAsset = useMemo(
		() => items.find((item) => item.asset_id === selectedAssetId) ?? null,
		[items, selectedAssetId],
	);

	useEffect(() => {
		void loadCreativeLibraryAssets(
			roleFilter,
			statusFilter,
			search,
			setError,
			setItems,
			setSelectedAssetId,
		);
	}, [roleFilter, statusFilter, search]);

	useEffect(() => {
		if (!selectedAsset) return;
		setForm({
			display_name: selectedAsset.display_name,
			semantic_role: selectedAsset.semantic_role,
			description: selectedAsset.description ?? "",
			product_id: selectedAsset.product_id ?? "",
			category: selectedAsset.category ?? "",
			silo: selectedAsset.silo ?? "",
			product_type: selectedAsset.product_type ?? "",
			allowed_modes: selectedAsset.allowed_modes,
			engine_slot_eligibility: selectedAsset.engine_slot_eligibility,
			visual_dna_summary: selectedAsset.visual_dna_summary ?? "",
			character_dna: selectedAsset.character_dna ?? "",
			scene_context_dna: selectedAsset.scene_context_dna ?? "",
			style_mood_dna: selectedAsset.style_mood_dna ?? "",
			mode_a_metadata_handoff:
				typeof selectedAsset.mode_a_metadata_handoff === "string"
					? selectedAsset.mode_a_metadata_handoff
					: selectedAsset.mode_a_metadata_handoff
						? JSON.stringify(selectedAsset.mode_a_metadata_handoff, null, 2)
						: "",
			remote_source_url: selectedAsset.remote_source_url ?? "",
		});
		setSelectedFile(null);
	}, [selectedAsset]);

	async function handleCreate() {
		setIsSubmitting(true);
		setError(null);
		try {
			const created = await createCreativeAsset({
				...form,
				file: selectedFile,
				source_type: selectedFile ? "UPLOAD" : "REMOTE_URL",
				storage_kind: selectedFile ? "LOCAL_FILE" : "REMOTE_URL",
			});
			setSelectedAssetId(created.asset_id);
			setForm(INITIAL_FORM);
			setSelectedFile(null);
			await loadCreativeLibraryAssets(
				roleFilter,
				statusFilter,
				search,
				setError,
				setItems,
				setSelectedAssetId,
			);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to create creative asset.",
			);
		} finally {
			setIsSubmitting(false);
		}
	}

	async function handleSaveMetadata() {
		if (!selectedAsset) return;
		setIsSubmitting(true);
		setError(null);
		try {
			await updateCreativeAsset(selectedAsset.asset_id, {
				display_name: form.display_name,
				description: form.description,
				product_id: form.product_id || null,
				category: form.category || null,
				silo: form.silo || null,
				product_type: form.product_type || null,
				allowed_modes: form.allowed_modes,
				engine_slot_eligibility: form.engine_slot_eligibility,
				visual_dna_summary: form.visual_dna_summary || null,
				character_dna: form.character_dna || null,
				scene_context_dna: form.scene_context_dna || null,
				style_mood_dna: form.style_mood_dna || null,
				mode_a_metadata_handoff: form.mode_a_metadata_handoff || null,
			});
			await loadCreativeLibraryAssets(
				roleFilter,
				statusFilter,
				search,
				setError,
				setItems,
				setSelectedAssetId,
			);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to update creative asset.",
			);
		} finally {
			setIsSubmitting(false);
		}
	}

	async function handleArchiveToggle() {
		if (!selectedAsset) return;
		setIsSubmitting(true);
		setError(null);
		try {
			if (selectedAsset.status === "ARCHIVED") {
				await unarchiveCreativeAsset(selectedAsset.asset_id);
			} else {
				await archiveCreativeAsset(selectedAsset.asset_id);
			}
			await loadCreativeLibraryAssets(
				roleFilter,
				statusFilter,
				search,
				setError,
				setItems,
				setSelectedAssetId,
			);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to update asset lifecycle.",
			);
		} finally {
			setIsSubmitting(false);
		}
	}

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
					Creative Library
				</div>
				<div className="mt-2 max-w-4xl text-sm text-slate-300">
					Upload and store reusable creative images for workspace use: Character
					/ Creator, Scene Context / Environment, Style / Mood, and Composite
					Frame references. Asset Registry remains read-only provenance. This
					page is the operator-facing write surface.
				</div>
				{error ? (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				) : null}
			</section>

			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
					Upload New Asset
				</div>
				<div className="grid gap-4 xl:grid-cols-2">
					<div className="space-y-3">
						<input
							value={form.display_name}
							onChange={(e) =>
								setForm((current) => ({
									...current,
									display_name: e.target.value,
								}))
							}
							placeholder="Display name"
							className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
						/>
						<select
							value={form.semantic_role}
							onChange={(e) =>
								setForm((current) => ({
									...current,
									semantic_role: e.target.value as CreativeAssetSemanticRole,
								}))
							}
							className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
						>
							{ROLE_OPTIONS.map((role) => (
								<option key={role} value={role}>
									{role}
								</option>
							))}
						</select>
						<textarea
							value={form.description}
							onChange={(e) =>
								setForm((current) => ({
									...current,
									description: e.target.value,
								}))
							}
							placeholder="Description"
							className="h-24 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
						/>
						<input
							type="file"
							accept="image/*"
							onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
							className="block w-full rounded-xl border border-dashed border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-500/15 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-blue-200"
						/>
						<input
							value={form.remote_source_url}
							onChange={(e) =>
								setForm((current) => ({
									...current,
									remote_source_url: e.target.value,
								}))
							}
							placeholder="Remote source URL (optional if file upload used)"
							className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
						/>
					</div>
					<div className="space-y-3">
						<div className="grid gap-3 md:grid-cols-2">
							<input
								value={form.product_id}
								onChange={(e) =>
									setForm((current) => ({
										...current,
										product_id: e.target.value,
									}))
								}
								placeholder="Product ID (optional)"
								className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							/>
							<input
								value={form.category}
								onChange={(e) =>
									setForm((current) => ({
										...current,
										category: e.target.value,
									}))
								}
								placeholder="Category"
								className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							/>
							<input
								value={form.silo}
								onChange={(e) =>
									setForm((current) => ({
										...current,
										silo: e.target.value,
									}))
								}
								placeholder="Silo"
								className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							/>
							<input
								value={form.product_type}
								onChange={(e) =>
									setForm((current) => ({
										...current,
										product_type: e.target.value,
									}))
								}
								placeholder="Product Type"
								className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							/>
						</div>
						<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Allowed Modes
							</div>
							<div className="mt-3 flex flex-wrap gap-2">
								{MODE_OPTIONS.map((mode) => (
									<button
										type="button"
										key={mode}
										onClick={() =>
											setForm((current) => ({
												...current,
												allowed_modes: toggleArrayValue(
													current.allowed_modes,
													mode,
												),
											}))
										}
										className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${form.allowed_modes.includes(mode) ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-400"}`}
									>
										{mode}
									</button>
								))}
							</div>
						</div>
						<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Engine Slot Eligibility
							</div>
							<div className="mt-3 flex flex-wrap gap-2">
								{SLOT_OPTIONS.map((slot) => (
									<button
										type="button"
										key={slot}
										onClick={() =>
											setForm((current) => ({
												...current,
												engine_slot_eligibility: toggleArrayValue(
													current.engine_slot_eligibility,
													slot,
												),
											}))
										}
										className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${form.engine_slot_eligibility.includes(slot) ? "border-emerald-400/60 bg-emerald-500/10 text-emerald-200" : "border-slate-700 bg-slate-950 text-slate-400"}`}
									>
										{slot}
									</button>
								))}
							</div>
						</div>
					</div>
				</div>
				<div className="mt-4 grid gap-3 xl:grid-cols-2">
					<textarea
						value={form.visual_dna_summary}
						onChange={(e) =>
							setForm((current) => ({
								...current,
								visual_dna_summary: e.target.value,
							}))
						}
						placeholder="Visual DNA summary"
						className="h-24 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					/>
					<div className="space-y-2">
						<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
							Mode A metadata handoff
						</div>
						<textarea
							value={form.mode_a_metadata_handoff}
							onChange={(e) =>
								setForm((current) => ({
									...current,
									mode_a_metadata_handoff: e.target.value,
								}))
							}
							placeholder="Mode A metadata handoff (JSON or text)"
							className="h-24 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
						/>
					</div>
				</div>
				<div className="mt-4">
					<button
						type="button"
						onClick={() => void handleCreate()}
						disabled={
							isSubmitting ||
							!form.display_name ||
							(!selectedFile && !form.remote_source_url)
						}
						className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-blue-100 disabled:opacity-50"
					>
						{isSubmitting ? "Saving..." : "Create Creative Asset"}
					</button>
				</div>
			</section>

			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.9fr)]">
					<div className="min-w-0 space-y-4">
						<div className="grid gap-3 md:grid-cols-3">
							<select
								value={roleFilter}
								onChange={(e) =>
									setRoleFilter(
										e.target.value as CreativeAssetSemanticRole | "ALL",
									)
								}
								className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							>
								<option value="ALL">All Roles</option>
								{ROLE_OPTIONS.map((role) => (
									<option key={role} value={role}>
										{role}
									</option>
								))}
							</select>
							<select
								value={statusFilter}
								onChange={(e) =>
									setStatusFilter(e.target.value as CreativeAssetStatus | "ALL")
								}
								className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							>
								{STATUS_OPTIONS.map((status) => (
									<option key={status} value={status}>
										{status}
									</option>
								))}
							</select>
							<input
								value={search}
								onChange={(e) => setSearch(e.target.value)}
								placeholder="Search assets"
								className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
							/>
						</div>
						<div className="overflow-x-auto rounded-2xl border border-slate-800">
							<table className="min-w-full divide-y divide-slate-800 text-sm">
								<thead className="bg-slate-900/70 text-[10px] uppercase tracking-[0.18em] text-slate-500">
									<tr>
										<th className="px-3 py-3 text-left">Asset</th>
										<th className="px-3 py-3 text-left">Semantic Role</th>
										<th className="px-3 py-3 text-left">Status</th>
										<th className="px-3 py-3 text-left">Modes</th>
									</tr>
								</thead>
								<tbody className="divide-y divide-slate-800 bg-slate-950/40 text-slate-200">
									{items.map((item) => (
										<tr
											key={item.asset_id}
											onClick={() => setSelectedAssetId(item.asset_id)}
											className={`cursor-pointer transition ${selectedAssetId === item.asset_id ? "bg-blue-500/10" : "hover:bg-slate-900/60"}`}
										>
											<td className="px-3 py-3">
												<div className="font-semibold">{item.display_name}</div>
												<div className="text-xs text-slate-400">
													{item.asset_id}
												</div>
											</td>
											<td className="px-3 py-3 text-xs">
												{item.semantic_role}
											</td>
											<td className="px-3 py-3 text-xs">
												<span
													className={`rounded-full border px-2 py-1 ${item.status === "ACTIVE" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-amber-500/30 bg-amber-500/10 text-amber-100"}`}
												>
													{item.status}
												</span>
											</td>
											<td className="px-3 py-3 text-xs text-slate-400">
												{item.allowed_modes.join(", ") || "ALL"}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</div>
					<div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
						<div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
							Detail Panel
						</div>
						{selectedAsset ? (
							<>
								{selectedAsset.preview_url ? (
									<img
										src={selectedAsset.preview_url}
										alt={selectedAsset.display_name}
										className="h-48 w-full rounded-2xl border border-slate-800 object-cover"
									/>
								) : (
									<div className="flex h-48 items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-950 text-xs text-slate-500">
										Preview unavailable
									</div>
								)}
								<div className="grid gap-3">
									<input
										value={form.display_name}
										onChange={(e) =>
											setForm((current) => ({
												...current,
												display_name: e.target.value,
											}))
										}
										className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
									/>
									<textarea
										value={form.description}
										onChange={(e) =>
											setForm((current) => ({
												...current,
												description: e.target.value,
											}))
										}
										className="h-24 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
									/>
									<div className="text-xs text-slate-400">
										Semantic Role: {selectedAsset.semantic_role}
									</div>
									<div className="text-xs text-slate-400">
										Eligible Slots:{" "}
										{selectedAsset.engine_slot_eligibility.join(", ") || "ALL"}
									</div>
									<div className="text-xs text-slate-400">
										Mode A Metadata Handoff
									</div>
									<textarea
										value={form.mode_a_metadata_handoff}
										onChange={(e) =>
											setForm((current) => ({
												...current,
												mode_a_metadata_handoff: e.target.value,
											}))
										}
										className="h-24 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
									/>
								</div>
								<div className="flex flex-wrap gap-2">
									<button
										type="button"
										onClick={() => void handleSaveMetadata()}
										disabled={isSubmitting}
										className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-semibold text-blue-100 disabled:opacity-50"
									>
										Save Metadata
									</button>
									<button
										type="button"
										onClick={() => void handleArchiveToggle()}
										disabled={isSubmitting}
										className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm font-semibold text-amber-100 disabled:opacity-50"
									>
										{selectedAsset.status === "ARCHIVED"
											? "Unarchive Asset"
											: "Archive Asset"}
									</button>
								</div>
							</>
						) : (
							<div className="text-sm text-slate-400">
								Select a creative asset to inspect metadata, preview, and
								lifecycle.
							</div>
						)}
					</div>
				</div>
			</section>
		</div>
	);
}
