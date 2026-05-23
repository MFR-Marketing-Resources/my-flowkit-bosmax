import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
	WorkspaceMode,
} from "../types";

const ROLE_OPTIONS: CreativeAssetSemanticRole[] = [
	"PRODUCT_REFERENCE",
	"CHARACTER_REFERENCE",
	"SCENE_CONTEXT_REFERENCE",
	"STYLE_REFERENCE",
	"COMPOSITE_FRAME_REFERENCE",
];
const MODE_OPTIONS: WorkspaceMode[] = ["T2V", "F2V", "I2V", "IMG"];
const SLOT_OPTIONS: CreativeAssetEngineSlot[] = [
	"subject",
	"scene",
	"style",
	"start_frame",
	"end_frame",
];

interface FormState {
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

const INITIAL_FORM: FormState = {
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

function toggleArrayValue<T extends string>(arr: T[], val: T): T[] {
	return arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val];
}

export default function CreativeLibraryWorkspacePage() {
	const navigate = useNavigate();
	const [searchParams] = useSearchParams();
	const editId = searchParams.get("id");
	const isEditMode = Boolean(editId);

	const [asset, setAsset] = useState<CreativeAsset | null>(null);
	const [isLoadingAsset, setIsLoadingAsset] = useState(false);
	const [form, setForm] = useState<FormState>(INITIAL_FORM);
	const [selectedFile, setSelectedFile] = useState<File | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [successMsg, setSuccessMsg] = useState<string | null>(null);
	const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

	useEffect(() => {
		if (!lightboxUrl) return;
		const handler = (e: KeyboardEvent) => {
			if (e.key === "Escape") setLightboxUrl(null);
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, [lightboxUrl]);

	useEffect(() => {
		if (!editId) {
			setAsset(null);
			setForm(INITIAL_FORM);
			return;
		}
		setIsLoadingAsset(true);
		setError(null);
		void fetchCreativeAssets({ limit: 500 })
			.then((response) => {
				const found = response.items.find((item) => item.asset_id === editId);
				if (found) {
					setAsset(found);
					setForm({
						display_name: found.display_name,
						semantic_role: found.semantic_role,
						description: found.description ?? "",
						allowed_modes: found.allowed_modes,
						engine_slot_eligibility: found.engine_slot_eligibility,
						visual_dna_summary: found.visual_dna_summary ?? "",
						character_dna: found.character_dna ?? "",
						scene_context_dna: found.scene_context_dna ?? "",
						style_mood_dna: found.style_mood_dna ?? "",
						mode_a_metadata_handoff:
							typeof found.mode_a_metadata_handoff === "string"
								? found.mode_a_metadata_handoff
								: found.mode_a_metadata_handoff
									? JSON.stringify(found.mode_a_metadata_handoff, null, 2)
									: "",
						remote_source_url: found.remote_source_url ?? "",
					});
				} else {
					setError(`Asset ${editId} not found.`);
				}
			})
			.catch((err: unknown) =>
				setError(err instanceof Error ? err.message : "Failed to load asset."),
			)
			.finally(() => setIsLoadingAsset(false));
	}, [editId]);

	async function handleCreate() {
		setIsSubmitting(true);
		setError(null);
		try {
			await createCreativeAsset({
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
			navigate("/assets/creative-library");
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to create creative asset.",
			);
		} finally {
			setIsSubmitting(false);
		}
	}

	async function handleSaveMetadata() {
		if (!asset) return;
		setIsSubmitting(true);
		setError(null);
		setSuccessMsg(null);
		try {
			await updateCreativeAsset(asset.asset_id, {
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
			setSuccessMsg("Metadata saved.");
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to update creative asset.",
			);
		} finally {
			setIsSubmitting(false);
		}
	}

	async function handleArchiveToggle() {
		if (!asset) return;
		setIsSubmitting(true);
		setError(null);
		try {
			if (asset.status === "ARCHIVED") {
				await unarchiveCreativeAsset(asset.asset_id);
			} else {
				await archiveCreativeAsset(asset.asset_id);
			}
			navigate("/assets/creative-library");
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to update asset lifecycle.",
			);
		} finally {
			setIsSubmitting(false);
		}
	}

	function field(
		key: keyof FormState,
		value: string,
		placeholder: string,
		rows = 3,
	) {
		return (
			<div>
				<label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
					{placeholder}
				</label>
				<textarea
					rows={rows}
					value={value}
					onChange={(e) =>
						setForm((cur) => ({ ...cur, [key]: e.target.value }))
					}
					placeholder={placeholder}
					className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
				/>
			</div>
		);
	}

	return (
		<>
			<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
				{/* Header */}
				<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
					<div className="mb-4 flex items-start justify-between gap-4">
						<div>
							<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
								Creative Library
							</div>
							<div className="mt-1 text-xs text-slate-400">
								{isEditMode && asset
									? `Editing: ${asset.display_name}`
									: "Create new asset"}
							</div>
						</div>
					</div>
					{/* Sub-tab switcher */}
					<div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
						<button
							type="button"
							onClick={() => navigate("/assets/creative-library")}
							className="flex-1 rounded-lg py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
						>
							Library — Asset Database
						</button>
						<button
							type="button"
							className="flex-1 rounded-lg bg-slate-800 py-2 text-[11px] font-bold uppercase tracking-[0.16em] text-slate-100 shadow-sm"
						>
							Workspace — Create / Edit
						</button>
					</div>
					{error && (
						<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
							{error}
						</div>
					)}
					{successMsg && (
						<div className="mt-4 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-200">
							{successMsg}
						</div>
					)}
				</section>

				{isLoadingAsset ? (
					<div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-10 text-center text-sm text-slate-400">
						Loading asset...
					</div>
				) : (
					<>
						{/* Edit mode: preview image */}
						{isEditMode && asset?.preview_url && (
							<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
								<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
									Current Image
								</div>
								<div
									role="button"
									tabIndex={0}
									className="group relative max-w-sm cursor-zoom-in overflow-hidden rounded-2xl border border-slate-800"
									onClick={() => setLightboxUrl(asset.preview_url)}
									onKeyDown={(e) => {
										if (e.key === "Enter" || e.key === " ")
											setLightboxUrl(asset.preview_url);
									}}
								>
									<img
										src={asset.preview_url}
										alt={asset.display_name}
										className="h-64 w-full object-cover transition duration-200 group-hover:brightness-75"
									/>
									<div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition duration-200 group-hover:opacity-100">
										<div className="rounded-full bg-black/60 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-sm">
											Click to expand
										</div>
									</div>
								</div>
							</section>
						)}

						{/* Main form */}
						<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
							<div className="mb-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
								{isEditMode ? "Edit Metadata" : "Asset Details"}
							</div>

							<div className="grid gap-6 xl:grid-cols-2">
								{/* Left column — core fields */}
								<div className="space-y-4">
									<div>
										<label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
											Display Name
										</label>
										<input
											value={form.display_name}
											onChange={(e) =>
												setForm((cur) => ({
													...cur,
													display_name: e.target.value,
												}))
											}
											placeholder="Display name"
											className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
										/>
									</div>

									{isEditMode ? (
										<div className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-400">
											Semantic Role:{" "}
											<span className="text-slate-200">{asset?.semantic_role}</span>
										</div>
									) : (
										<div>
											<label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
												Semantic Role
											</label>
											<select
												value={form.semantic_role}
												onChange={(e) =>
													setForm((cur) => ({
														...cur,
														semantic_role:
															e.target.value as CreativeAssetSemanticRole,
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
										</div>
									)}

									{field("description", form.description, "Description", 3)}

									{!isEditMode && (
										<>
											<div>
												<label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
													Upload Image
												</label>
												<input
													type="file"
													accept="image/*"
													onChange={(e) =>
														setSelectedFile(e.target.files?.[0] ?? null)
													}
													className="block w-full rounded-xl border border-dashed border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-500/15 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-blue-200"
												/>
											</div>
											<div>
												<label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
													Remote Source URL
												</label>
												<input
													value={form.remote_source_url}
													onChange={(e) =>
														setForm((cur) => ({
															...cur,
															remote_source_url: e.target.value,
														}))
													}
													placeholder="https://... (optional if file upload used)"
													className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
												/>
											</div>
										</>
									)}
								</div>

								{/* Right column — mode + slot toggles */}
								<div className="space-y-4">
									<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
										<div className="mb-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
											Allowed Modes
										</div>
										<div className="flex flex-wrap gap-2">
											{MODE_OPTIONS.map((mode) => (
												<button
													type="button"
													key={mode}
													onClick={() =>
														setForm((cur) => ({
															...cur,
															allowed_modes: toggleArrayValue(
																cur.allowed_modes,
																mode,
															),
														}))
													}
													className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${
														form.allowed_modes.includes(mode)
															? "border-blue-400/60 bg-blue-500/10 text-blue-200"
															: "border-slate-700 bg-slate-950 text-slate-400"
													}`}
												>
													{mode}
												</button>
											))}
										</div>
									</div>

									<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
										<div className="mb-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
											Engine Slot Eligibility
										</div>
										<div className="flex flex-wrap gap-2">
											{SLOT_OPTIONS.map((slot) => (
												<button
													type="button"
													key={slot}
													onClick={() =>
														setForm((cur) => ({
															...cur,
															engine_slot_eligibility: toggleArrayValue(
																cur.engine_slot_eligibility,
																slot,
															),
														}))
													}
													className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${
														form.engine_slot_eligibility.includes(slot)
															? "border-emerald-400/60 bg-emerald-500/10 text-emerald-200"
															: "border-slate-700 bg-slate-950 text-slate-400"
													}`}
												>
													{slot}
												</button>
											))}
										</div>
									</div>
								</div>
							</div>

							{/* DNA / Prompt fields */}
							<div className="mt-6 space-y-4">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Prompt DNA
								</div>
								{field(
									"visual_dna_summary",
									form.visual_dna_summary,
									"Visual DNA Summary — overall look and feel",
									3,
								)}
								{field(
									"character_dna",
									form.character_dna,
									"Character DNA — full photorealistic avatar prompt (for CHARACTER_REFERENCE)",
									5,
								)}
								{field(
									"scene_context_dna",
									form.scene_context_dna,
									"Scene Context DNA — background / environment description (for SCENE_CONTEXT_REFERENCE)",
									5,
								)}
								{field(
									"style_mood_dna",
									form.style_mood_dna,
									"Style / Mood DNA — lighting, tone, camera style (for STYLE_REFERENCE)",
									3,
								)}
								<div>
									<label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
										Mode A Metadata Handoff (JSON)
									</label>
									<textarea
										rows={4}
										value={form.mode_a_metadata_handoff}
										onChange={(e) =>
											setForm((cur) => ({
												...cur,
												mode_a_metadata_handoff: e.target.value,
											}))
										}
										placeholder="{}"
										className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 placeholder:text-slate-600"
									/>
								</div>
							</div>

							{/* Actions */}
							<div className="mt-6 flex flex-wrap gap-3">
								{isEditMode ? (
									<>
										<button
											type="button"
											onClick={() => void handleSaveMetadata()}
											disabled={isSubmitting}
											className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-5 py-3 text-sm font-semibold text-blue-100 disabled:opacity-50"
										>
											{isSubmitting ? "Saving..." : "Save Metadata"}
										</button>
										<button
											type="button"
											onClick={() => void handleArchiveToggle()}
											disabled={isSubmitting}
											className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-3 text-sm font-semibold text-amber-100 disabled:opacity-50"
										>
											{asset?.status === "ARCHIVED"
												? "Unarchive Asset"
												: "Archive Asset"}
										</button>
									</>
								) : (
									<button
										type="button"
										onClick={() => void handleCreate()}
										disabled={
											isSubmitting ||
											!form.display_name ||
											(!selectedFile && !form.remote_source_url)
										}
										className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-5 py-3 text-sm font-semibold text-blue-100 disabled:opacity-50"
									>
										{isSubmitting ? "Saving..." : "Create Creative Asset"}
									</button>
								)}
							</div>
						</section>
					</>
				)}
			</div>

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
