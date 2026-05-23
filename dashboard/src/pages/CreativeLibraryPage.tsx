import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
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
import { PRODUCT_ASSET_GENERATOR_PRESETS } from "./ProductAssetGeneratorPage";

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
	allowed_modes: ["I2V"],
	engine_slot_eligibility: ["subject"],
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
	const location = useLocation();
	const [items, setItems] = useState<CreativeAsset[]>([]);
	const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
	const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

	// Close lightbox on ESC key
	useEffect(() => {
		if (!lightboxUrl) return;
		const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setLightboxUrl(null); };
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, [lightboxUrl]);

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
	const productAssetGeneratorRouteBase =
		new URLSearchParams(location.search).get("portal") === "side"
			? "/product-asset-generator?portal=side"
			: "/product-asset-generator";
	const productAssetGeneratorPresetSeparator =
		productAssetGeneratorRouteBase.includes("?") ? "&" : "?";

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
				display_name: form.display_name,
				semantic_role: form.semantic_role,
				description: form.description,
				allowed_modes: form.allowed_modes,
				engine_slot_eligibility: form.engine_slot_eligibility,
				visual_dna_summary: form.visual_dna_summary,
				character_dna: form.character_dna,
				scene_context_dna: form.scene_context_dna,
				style_mood_dna: form.style_mood_dna,
				mode_a_metadata_handoff: form.mode_a_metadata_handoff,
				remote_source_url: form.remote_source_url,
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
		<>
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
				<div className="flex flex-wrap items-start justify-between gap-3">
					<div>
						<div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
							Preset Library
						</div>
						<div className="mt-2 max-w-4xl text-sm text-slate-300">
							Use governed image presets instead of starting from a blank manual
							prompt. Product-holding presets force database product truth first
							so scale, packaging, and handling do not drift.
						</div>
					</div>
					<div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-3 py-3 text-[11px] text-amber-100">
						Database product truth is the primary source for scale truth,
						product physics, and label-safe handling.
					</div>
				</div>
				<div className="mt-4 grid gap-4 xl:grid-cols-2">
					{PRODUCT_ASSET_GENERATOR_PRESETS.map((preset) => (
						<article
							key={preset.id}
							className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4"
						>
							<div className="flex flex-wrap items-start justify-between gap-3">
								<div>
									<div className="text-sm font-semibold text-slate-100">
										{preset.label}
									</div>
									<div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
										{preset.id}
									</div>
								</div>
								<span
									className={`rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${preset.requiresDatabaseProduct ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"}`}
								>
									{preset.requiresDatabaseProduct
										? "DATABASE PRODUCT REQUIRED"
										: "CUSTOM PRODUCT ALLOWED"}
								</span>
							</div>
							<div className="mt-3 text-sm text-slate-300">
								{preset.description}
							</div>
							<div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
								<div>
									<div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
										Required Inputs
									</div>
									<div className="mt-2 flex flex-wrap gap-2">
										{preset.requiredInputs.map((item) => (
											<span
												key={`${preset.id}:${item}`}
												className="rounded-full border border-slate-700 bg-slate-950 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300"
											>
												{item}
											</span>
										))}
									</div>
								</div>
								<Link
									to={`${productAssetGeneratorRouteBase}${productAssetGeneratorPresetSeparator}preset=${preset.id}`}
									className="inline-flex items-center justify-center rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-200"
								>
									Launch Preset
								</Link>
							</div>
							<div className="mt-3 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3 text-[11px] text-slate-300">
								{preset.guidance}
							</div>
						</article>
					))}
				</div>
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
				<div className="mt-4">
					<textarea
						value={form.visual_dna_summary}
						onChange={(e) =>
							setForm((current) => ({
								...current,
								visual_dna_summary: e.target.value,
							}))
						}
						placeholder="Visual DNA summary (optional — helps prompt builder pick the right tone)"
						className="h-20 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					/>
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
									<div
										className="group relative cursor-zoom-in overflow-hidden rounded-2xl border border-slate-800"
										onClick={() => setLightboxUrl(selectedAsset.preview_url)}
									>
										<img
											src={selectedAsset.preview_url}
											alt={selectedAsset.display_name}
											className="h-48 w-full object-cover transition duration-200 group-hover:brightness-75"
										/>
										<div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition duration-200 group-hover:opacity-100">
											<div className="rounded-full bg-black/60 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-sm">
												🔍 Click to expand
											</div>
										</div>
									</div>
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
			{/* ── Lightbox modal ── */}
			{lightboxUrl && (
				<div
					className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
					onClick={() => setLightboxUrl(null)}
				>
					<div
						className="relative max-h-[90vh] max-w-[90vw]"
						onClick={(e) => e.stopPropagation()}
					>
						<img
							src={lightboxUrl}
							alt="Preview"
							className="max-h-[88vh] max-w-[88vw] rounded-2xl object-contain shadow-2xl"
						/>
						<button
							onClick={() => setLightboxUrl(null)}
							className="absolute -right-3 -top-3 flex h-8 w-8 items-center justify-center rounded-full bg-slate-800 text-slate-200 shadow-lg hover:bg-slate-700"
						>
							✕
						</button>
					</div>
				</div>
			)}
		</>
	);
}
