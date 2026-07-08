import { ArrowRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { handleAssetUpload } from "../../api/assets";
import { fetchCreativeAssets } from "../../api/creativeAssets";
import {
	createWorkspaceExecutionPackage,
	resolveI2VSemanticSlots,
} from "../../api/workspacePackages";
import type {
	CreativeAsset,
	I2VRecipeId,
	I2VSemanticResolvedAsset,
	I2VSemanticSlotResolverResponse,
	Orientation,
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";
import ModelSelect, { type VideoModel } from "./ModelSelect";
import WorkspaceImageAssetSlot from "./WorkspaceImageAssetSlot";

interface I2VModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
	onWorkspacePackageUpdated?: (pkg: WorkspaceExecutionPackage) => void;
	videoModels: VideoModel[];
	selectedCopySetId?: string | null;
}

const CANONICAL_PROMPT_SECTIONS = [
	"SECTION 1 - ROLE & OBJECTIVE",
	"SECTION 2 - PRODUCT TRUTH LOCK",
	"SECTION 3 - CONTINUITY & STATE LOCK",
	"SECTION 4 - VISUAL STORY",
	"SECTION 5 - SHOT & CAMERA RULES",
	"SECTION 6 - SPOKEN DIALOGUE",
	"SECTION 7 - VOICE & DELIVERY",
	"SECTION 8 - CTA & END FRAME",
	"SECTION 9 - NO_OVERLAY",
] as const;

type PromptAuditBlock = NonNullable<
	WorkspaceExecutionPackage["prompt_blocks"]
>[number];

interface PromptAuditSection {
	heading: string;
	sectionNumber: number | null;
	title: string;
	body: string;
}

function parsePromptSections(text: string): PromptAuditSection[] {
	const normalized = (text ?? "").replace(/\r\n/g, "\n");
	const matches = [...normalized.matchAll(/^SECTION [1-9] - .+$/gm)];
	if (matches.length === 0) {
		return [];
	}

	return matches.map((match, index) => {
		const heading = match[0].trim();
		const start = (match.index ?? 0) + match[0].length;
		const end =
			index + 1 < matches.length
				? (matches[index + 1].index ?? normalized.length)
				: normalized.length;
		const sectionNumberMatch = heading.match(/^SECTION (\d+)/);
		return {
			heading,
			sectionNumber: sectionNumberMatch ? Number(sectionNumberMatch[1]) : null,
			title: heading.replace(/^SECTION \d+ - /, ""),
			body: normalized.slice(start, end).trim(),
		};
	});
}

function PromptAuditCard({
	label,
	text,
	block,
}: {
	label: string;
	text: string;
	block?: PromptAuditBlock;
}) {
	const [copied, setCopied] = useState(false);
	const sections = parsePromptSections(text);
	const presentHeadings = new Set(sections.map((section) => section.heading));
	const missingSections = CANONICAL_PROMPT_SECTIONS.filter(
		(heading) => !presentHeadings.has(heading),
	);
	const metaChips = [
		block?.block_role ? `Role ${block.block_role}` : null,
		block?.duration_seconds ? `${block.duration_seconds}s` : null,
		block?.shot_count
			? `${block.shot_count} shot${block.shot_count > 1 ? "s" : ""}`
			: null,
	].filter(Boolean) as string[];

	const handleCopy = () => {
		navigator.clipboard.writeText(text || "").then(() => {
			setCopied(true);
			window.setTimeout(() => setCopied(false), 2200);
		});
	};

	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 overflow-hidden">
			<div className="flex flex-col gap-3 border-b border-slate-800 px-4 py-3 md:flex-row md:items-start md:justify-between">
				<div className="space-y-2">
					<div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
						{label}
					</div>
					<div className="flex flex-wrap gap-2">
						<span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
							{sections.length}/9 sections
						</span>
						{metaChips.map((chip) => (
							<span
								key={chip}
								className="rounded-full border border-slate-800 bg-slate-900/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
							>
								{chip}
							</span>
						))}
						{missingSections.length === 0 ? (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
								Canonical 9-section structure
							</span>
						) : (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
								Missing{" "}
								{missingSections
									.map((heading) => heading.replace("SECTION ", "S"))
									.join(", ")}
							</span>
						)}
					</div>
				</div>
				<button
					type="button"
					onClick={handleCopy}
					className={`rounded-lg border px-3 py-2 text-[11px] font-semibold transition-colors ${copied ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-blue-500/30 bg-blue-500/10 text-blue-100 hover:bg-blue-500/20"}`}
				>
					{copied ? "Copied" : "Copy Prompt"}
				</button>
			</div>
			{sections.length > 0 ? (
				<div className="divide-y divide-slate-800">
					{sections.map((section) => (
						<details
							key={section.heading}
							open={
								section.sectionNumber === 4 ||
								section.sectionNumber === 6 ||
								section.sectionNumber === 8
							}
							className="group"
						>
							<summary className="cursor-pointer list-none px-4 py-3">
								<div className="flex items-center justify-between gap-3">
									<div className="flex items-center gap-2">
										<span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
											S{section.sectionNumber ?? "?"}
										</span>
										<span className="text-xs font-semibold text-slate-100">
											{section.title}
										</span>
									</div>
									<span className="text-[10px] uppercase tracking-[0.16em] text-slate-500 group-open:text-slate-300">
										Expand
									</span>
								</div>
							</summary>
							<pre className="border-t border-slate-800 px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
								{section.body || "(empty section)"}
							</pre>
						</details>
					))}
				</div>
			) : (
				<pre className="px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
					{text || "(no prompt text)"}
				</pre>
			)}
		</div>
	);
}

const RECIPE_OPTIONS: Array<{
	id: I2VRecipeId;
	label: string;
	description: string;
}> = [
	{
		id: "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
		label: "Product Held By Character In Scene",
		description:
			"Product stays primary. Character demonstrates it. Scene context defines the environment.",
	},
	{
		id: "CHARACTER_FIRST_PRODUCT_DEMO",
		label: "Character First Product Demo",
		description:
			"Character is primary. Product becomes the demo object. Scene context preserves continuity.",
	},
	{
		id: "STYLE_MOOD_DOMINANT_PRODUCT_SPOT",
		label: "Style Mood Dominant Product Spot",
		description:
			"Product stays primary while scene context and style mood dominate the visual direction.",
	},
];

type SlotKey = "subject" | "scene" | "style";

function toUploadedAsset(
	asset:
		| WorkspaceExecutionPackage["resolved_assets"][number]
		| null
		| undefined,
): UploadedAsset | null {
	if (!asset) return null;
	return {
		mediaId: asset.media_id ?? null,
		fileName: asset.file_name,
		label: asset.label,
		previewUrl: asset.preview_url,
		downloadUrl: asset.download_url,
		localFilePath: asset.local_file_path ?? undefined,
		assetId: asset.asset_id,
		assetFingerprint: asset.asset_fingerprint,
		assetSource: asset.asset_source,
		isDefaultPackageAsset: true,
		previewRenderableStatus: asset.preview_renderable_status,
		previewErrorDetail: asset.preview_error_detail ?? null,
		localImagePathPresent: asset.local_image_path_present,
		remoteImageUrlPresent: asset.remote_image_url_present,
	};
}

function resolverAssetToUploadedAsset(
	asset: I2VSemanticResolvedAsset | undefined,
): UploadedAsset | null {
	if (!asset) return null;
	return {
		mediaId: asset.media_id ?? null,
		fileName: asset.display_name || asset.asset_id,
		label: asset.display_name || asset.asset_id,
		previewUrl: asset.preview_url ?? undefined,
		downloadUrl: asset.download_url ?? undefined,
		localFilePath: asset.local_file_path ?? undefined,
		assetId: asset.asset_id,
		assetFingerprint: asset.asset_fingerprint ?? undefined,
		assetSource: asset.asset_source ?? undefined,
		isDefaultPackageAsset: true,
		previewRenderableStatus: asset.preview_url ? "RENDERABLE" : "NOT_AVAILABLE",
		previewErrorDetail: asset.preview_url
			? null
			: "Preview URL is not available.",
		localImagePathPresent: asset.local_image_path_present ?? undefined,
		remoteImageUrlPresent: asset.remote_image_url_present ?? undefined,
	};
}

function mappedSemanticRoleLabel(
	resolver: I2VSemanticSlotResolverResponse | null,
	slotKey: SlotKey,
) {
	if (!resolver) return "Manual / unresolved";
	return resolver.engine_slot_mapping[slotKey] || "Manual / unresolved";
}

export default function I2VModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
	onWorkspacePackageUpdated,
	videoModels,
	selectedCopySetId = null,
}: I2VModuleProps) {
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [model, setModel] = useState("Veo 3.1 - Lite");
	const [count, setCount] = useState(1);
	const [isUploading, setIsUploading] = useState(false);
	const [isRefreshingPackage, setIsRefreshingPackage] = useState(false);

	const [subjectAsset, setSubjectAsset] = useState<UploadedAsset | null>(null);
	const [sceneAsset, setSceneAsset] = useState<UploadedAsset | null>(null);
	const [styleAsset, setStyleAsset] = useState<UploadedAsset | null>(null);
	const [manualSlotOverrides, setManualSlotOverrides] = useState<
		Record<SlotKey, boolean>
	>({
		subject: false,
		scene: false,
		style: false,
	});

	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneContextAssets, setSceneContextAssets] = useState<CreativeAsset[]>(
		[],
	);
	const [styleReferenceAssets, setStyleReferenceAssets] = useState<
		CreativeAsset[]
	>([]);
	const [selectedRecipeId, setSelectedRecipeId] = useState<I2VRecipeId>(
		"PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
	);
	const [selectedCharacterAssetId, setSelectedCharacterAssetId] = useState("");
	const [selectedSceneContextAssetId, setSelectedSceneContextAssetId] =
		useState("");
	const [selectedStyleReferenceAssetId, setSelectedStyleReferenceAssetId] =
		useState("");
	const [resolverPreview, setResolverPreview] =
		useState<I2VSemanticSlotResolverResponse | null>(null);
	const [resolverError, setResolverError] = useState<string | null>(null);
	const packagePromptText =
		workspacePackage?.prompt_blocks?.[0]?.engine_prompt_text ??
		workspacePackage?.prompt_text ??
		"";

	useEffect(() => {
		void Promise.all([
			fetchCreativeAssets({
				semantic_role: "CHARACTER_REFERENCE",
				status: "ACTIVE",
				allowed_mode: "I2V",
			}),
			fetchCreativeAssets({
				semantic_role: "SCENE_CONTEXT_REFERENCE",
				status: "ACTIVE",
				allowed_mode: "I2V",
			}),
			fetchCreativeAssets({
				semantic_role: "STYLE_REFERENCE",
				status: "ACTIVE",
				allowed_mode: "I2V",
			}),
		])
			.then(([characters, scenes, styles]) => {
				setCharacterAssets(characters.items);
				setSceneContextAssets(scenes.items);
				setStyleReferenceAssets(styles.items);
			})
			.catch(() => {});
	}, []);

	useEffect(() => {
		if (workspacePackage?.mode !== "I2V") return;
		setManualPrompt(workspacePackage.prompt_text);
		setSubjectAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "subject",
				),
			),
		);
		setSceneAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "scene",
				),
			),
		);
		setStyleAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "style",
				),
			),
		);
		setIsManualOverride(false);
		setManualSlotOverrides({
			subject: false,
			scene: false,
			style: false,
		});
		const resolver =
			workspacePackage.semantic_slot_resolver ??
			workspacePackage.request_lineage_payload.semantic_slot_resolver ??
			null;
		setResolverPreview(resolver);
		setSelectedRecipeId(
			(resolver?.recipe_id as I2VRecipeId | undefined) ||
				"PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
		);
		setSelectedCharacterAssetId(
			resolver?.creative_asset_ids?.character_reference || "",
		);
		setSelectedSceneContextAssetId(
			resolver?.creative_asset_ids?.scene_context_reference || "",
		);
		setSelectedStyleReferenceAssetId(
			resolver?.creative_asset_ids?.style_reference || "",
		);
	}, [workspacePackage]);

	useEffect(() => {
		if (!resolverPreview) return;
		const nextSubject = resolverAssetToUploadedAsset(
			resolverPreview.resolved_assets.find(
				(asset) => asset.slot_key === "subject",
			),
		);
		const nextScene = resolverAssetToUploadedAsset(
			resolverPreview.resolved_assets.find(
				(asset) => asset.slot_key === "scene",
			),
		);
		const nextStyle = resolverAssetToUploadedAsset(
			resolverPreview.resolved_assets.find(
				(asset) => asset.slot_key === "style",
			),
		);

		if (!manualSlotOverrides.subject && nextSubject)
			setSubjectAsset(nextSubject);
		if (!manualSlotOverrides.scene && nextScene) setSceneAsset(nextScene);
		if (!manualSlotOverrides.style && nextStyle) setStyleAsset(nextStyle);
	}, [manualSlotOverrides, resolverPreview]);

	useEffect(() => {
		if (!workspacePackage?.product_id || workspacePackage.mode !== "I2V") {
			setResolverPreview(null);
			return;
		}

		void resolveI2VSemanticSlots({
			product_id: workspacePackage.product_id,
			recipe_id: selectedRecipeId,
			character_reference_asset_id: selectedCharacterAssetId || null,
			scene_context_reference_asset_id: selectedSceneContextAssetId || null,
			style_reference_asset_id: selectedStyleReferenceAssetId || null,
		})
			.then((result) => {
				setResolverPreview(result);
				setResolverError(null);
			})
			.catch((error: unknown) => {
				setResolverPreview(null);
				setResolverError(
					error instanceof Error
						? error.message
						: "Failed to resolve semantic slots.",
				);
			});
	}, [
		selectedCharacterAssetId,
		selectedRecipeId,
		selectedSceneContextAssetId,
		selectedStyleReferenceAssetId,
		workspacePackage?.mode,
		workspacePackage?.product_id,
	]);

	const handleFileChange = async (
		type: SlotKey,
		e: React.ChangeEvent<HTMLInputElement>,
	) => {
		const file = e.target.files?.[0];
		if (!file) return;

		setIsUploading(true);
		try {
			const asset = await handleAssetUpload(file);
			if (type === "subject") setSubjectAsset(asset);
			else if (type === "scene") setSceneAsset(asset);
			else setStyleAsset(asset);
			setManualSlotOverrides((current) => ({ ...current, [type]: true }));
			setIsManualOverride(Boolean(workspacePackage));
		} catch (error) {
			console.error("Upload failed:", error);
			alert("Upload failed. Check if local agent is running.");
		} finally {
			setIsUploading(false);
		}
	};

	const resolverBlockers = resolverPreview?.blockers ?? [];
	const executionBlocked =
		Boolean(workspacePackage) && resolverBlockers.length > 0;

	// I2V business rule (BOSMAX): at least 2 reference/ingredient images, 3rd optional.
	const i2vImageCount = [subjectAsset, sceneAsset, styleAsset].filter(
		Boolean,
	).length;

	const resolverStatusTone = executionBlocked
		? "border-amber-500/30 bg-amber-500/10 text-amber-100"
		: "border-emerald-500/30 bg-emerald-500/10 text-emerald-100";

	const handleExecute = async () => {
		// Block a partial I2V LOCALLY before /generate — never submit fewer than 2 images.
		if (i2vImageCount < 2) {
			alert("I2V requires at least 2 reference images.");
			return;
		}
		let effectivePackage = workspacePackage;
		if (workspacePackage?.product_id) {
			setIsRefreshingPackage(true);
			try {
				effectivePackage = await createWorkspaceExecutionPackage({
					product_id: workspacePackage.product_id,
					mode: "I2V",
					duration_seconds: workspacePackage.duration_seconds,
					aspect_ratio: workspacePackage.aspect_ratio,
					model, // current dropdown selection, not the stale package model
					manual_override: isManualOverride,
					recipe_id: selectedRecipeId,
					character_reference_asset_id: selectedCharacterAssetId || null,
					scene_context_reference_asset_id: selectedSceneContextAssetId || null,
					style_reference_asset_id: selectedStyleReferenceAssetId || null,
					// CRITICAL: preserve the operator's approved Copy Set through the
					// semantic rebuild (it was previously dropped, stripping the binding).
					copy_set_id: selectedCopySetId,
					copy_fallback_confirmed: false,
				});
				onWorkspacePackageUpdated?.(effectivePackage);
			} catch (error) {
				const msg =
					error instanceof Error
						? error.message
						: "Failed to refresh semantic execution package.";
				alert(
					/FALLBACK_CONFIRMATION_REQUIRED|409/i.test(msg)
						? "Select an approved Copy Set (or use Step 3–4 to confirm fallback) before generating I2V — the semantic rebuild will not silently use generic copy."
						: msg,
				);
				setIsRefreshingPackage(false);
				return;
			}
			setIsRefreshingPackage(false);
		}

		onExecute({
			lane: "WORKSPACE_FLOW_EDITOR_RUNTIME",
			stop_after_stage: "PROMPT_EDITABLE_AFTER_INSERT",
			prompt: manualPrompt,
			orientation,
			model,
			count,
			refs: {
				subjectAsset,
				sceneAsset,
				styleAsset,
			},
			product_id: effectivePackage?.product_id,
			prompt_package_snapshot_id: effectivePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				effectivePackage?.workspace_execution_package_id,
			prompt_fingerprint: effectivePackage?.prompt_fingerprint,
			asset_fingerprints:
				effectivePackage?.request_lineage_payload.asset_fingerprints ?? [],
			request_lineage_payload: {
				...(effectivePackage?.request_lineage_payload ?? {}),
				manual_slot_overrides: {
					subject: manualSlotOverrides.subject
						? (subjectAsset?.assetId ?? null)
						: null,
					scene: manualSlotOverrides.scene
						? (sceneAsset?.assetId ?? null)
						: null,
					style: manualSlotOverrides.style
						? (styleAsset?.assetId ?? null)
						: null,
				},
			},
			mode: "I2V",
		});
	};

	const resolvedRecipe = useMemo(
		() => RECIPE_OPTIONS.find((item) => item.id === selectedRecipeId),
		[selectedRecipeId],
	);

	return (
		<div
			className={`space-y-6 ${compact ? "" : "xl:grid xl:grid-cols-[minmax(0,1fr)_18rem] xl:items-start xl:gap-6 xl:space-y-0"}`}
		>
			<div className="space-y-6 pb-12">
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						1. Semantic Asset Resolver
					</h3>
					<div className="grid gap-3">
						<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-3 text-[11px] text-blue-200/70 space-y-1">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-300/80">
								I2V — All 3 Slots Are Reference Images
							</div>
							<p>
								Subject = avatar/character · Scene = product · Style = scene
								context/environment.
							</p>
							<p>
								The model SEES all three images. Your prompt describes{" "}
								<strong className="text-blue-200">the event</strong> — how the
								character interacts with the product within the scene. No need
								to re-describe the visuals.
							</p>
						</div>
						<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
								Asset Resolver
							</div>
							<div className="mt-1">
								Selected product auto-resolves as the trusted product_reference.
								Product Reference stays bound to the approved product image
								while Character and Style / Mood from Creative Library complete
								the ingredient set.
							</div>
						</div>
						<div className="grid gap-4 md:grid-cols-2">
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Character / Creator
								</div>
								<select
									title="Character Creator"
									value={selectedCharacterAssetId}
									onChange={(e) => setSelectedCharacterAssetId(e.target.value)}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									<option value="">Select Character / Creator</option>
									{characterAssets.map((asset) => (
										<option key={asset.asset_id} value={asset.asset_id}>
											{asset.display_name}
										</option>
									))}
								</select>
							</div>
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Scene Context
								</div>
								<select
									title="Scene Context"
									value={selectedSceneContextAssetId}
									onChange={(e) =>
										setSelectedSceneContextAssetId(e.target.value)
									}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									<option value="">Select Scene Context</option>
									{sceneContextAssets.map((asset) => (
										<option key={asset.asset_id} value={asset.asset_id}>
											{asset.display_name}
										</option>
									))}
								</select>
							</div>
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Style / Mood
								</div>
								<select
									title="Style Mood"
									value={selectedStyleReferenceAssetId}
									onChange={(e) =>
										setSelectedStyleReferenceAssetId(e.target.value)
									}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									<option value="">Optional Style / Mood</option>
									{styleReferenceAssets.map((asset) => (
										<option key={asset.asset_id} value={asset.asset_id}>
											{asset.display_name}
										</option>
									))}
								</select>
							</div>
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Recipe
								</div>
								<select
									title="I2V Recipe"
									value={selectedRecipeId}
									onChange={(e) =>
										setSelectedRecipeId(e.target.value as I2VRecipeId)
									}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									{RECIPE_OPTIONS.map((recipe) => (
										<option key={recipe.id} value={recipe.id}>
											{recipe.label}
										</option>
									))}
								</select>
							</div>
						</div>
						<div
							className={`rounded-xl border px-3 py-3 text-[11px] ${resolverStatusTone}`}
						>
							<div className="text-[10px] font-bold uppercase tracking-[0.18em]">
								Resolver Status
							</div>
							<div className="mt-1">{resolvedRecipe?.description}</div>
							{resolverPreview ? (
								<div className="mt-2">
									{resolverPreview.compiler_context_summary}
								</div>
							) : resolverError ? (
								<div className="mt-2 text-red-200">{resolverError}</div>
							) : (
								<div className="mt-2">
									Resolver preview loads after the approved package baseline is
									ready.
								</div>
							)}
							{resolverBlockers.length > 0 ? (
								<div className="mt-2 space-y-1">
									{resolverBlockers.map((blocker) => (
										<div key={blocker}>Blocker: {blocker}</div>
									))}
								</div>
							) : null}
							{resolverPreview?.warnings.length ? (
								<div className="mt-2 space-y-1">
									{resolverPreview.warnings.map((warning) => (
										<div key={warning}>Warning: {warning}</div>
									))}
								</div>
							) : null}
						</div>
					</div>
				</section>

				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						2. Resolved Engine Slots
					</h3>
					<div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-3 text-[11px] text-slate-300">
						<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
							Resolver Transparency
						</div>
						<div className="mt-1">
							Subject / Scene / Style stay engine slots only. Semantic role
							selection above controls the actual business intent.
						</div>
						{Object.values(manualSlotOverrides).some(Boolean) ? (
							<div className="mt-2 text-amber-200">
								Manual slot upload override is active for this run only.
							</div>
						) : null}
					</div>
					<div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-3">
						<WorkspaceImageAssetSlot
							key={
								subjectAsset?.assetFingerprint ??
								subjectAsset?.previewUrl ??
								"subject-empty"
							}
							title="Subject"
							description={`Resolved from ${mappedSemanticRoleLabel(resolverPreview, "subject")}`}
							asset={subjectAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-blue-500/10 group-hover:text-blue-400"
							uploadTitle="Upload subject override"
							onFileChange={(e) => void handleFileChange("subject", e)}
						/>
						<WorkspaceImageAssetSlot
							key={
								sceneAsset?.assetFingerprint ??
								sceneAsset?.previewUrl ??
								"scene-empty"
							}
							title="Scene"
							description={`Resolved from ${mappedSemanticRoleLabel(resolverPreview, "scene")}`}
							asset={sceneAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-purple-500/10 group-hover:text-purple-400"
							uploadTitle="Upload scene override"
							onFileChange={(e) => void handleFileChange("scene", e)}
						/>
						<WorkspaceImageAssetSlot
							key={
								styleAsset?.assetFingerprint ??
								styleAsset?.previewUrl ??
								"style-empty"
							}
							title="Style"
							description={`Resolved from ${mappedSemanticRoleLabel(resolverPreview, "style")}`}
							asset={styleAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-pink-500/10 group-hover:text-pink-400"
							uploadTitle="Upload style override"
							onFileChange={(e) => void handleFileChange("style", e)}
						/>
					</div>
				</section>

				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						3. Prompt Injection
					</h3>
					<div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
						{workspacePackage ? (
							<div className="grid gap-3">
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
										Auto Package Baseline
									</div>
									<div className="mt-1">
										Approved package loaded. Product truth remains fixed while
										Creative Library selections refine the Ingredients semantic
										route.
									</div>
								</div>
								<div
									className={`rounded-xl border px-3 py-3 text-[11px] ${isManualOverride ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-slate-800 bg-slate-950/40 text-slate-300"}`}
								>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Manual Override
									</div>
									<div className="mt-1">
										Editing the prompt below overrides the package prompt for
										this run only.
									</div>
								</div>
							</div>
						) : (
							<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
									Manual Prompt Injection
								</div>
								<div className="mt-1">
									No approved package is loaded. The prompt below is 100%
									manual.
								</div>
							</div>
						)}
						{workspacePackage?.prompt_blocks &&
						workspacePackage.prompt_blocks.length > 1 ? (
							<div className="space-y-4">
								{workspacePackage.prompt_blocks.map((block) => (
									<PromptAuditCard
										key={block.block_index}
										label={`Block ${block.block_index} Audit`}
										text={block.engine_prompt_text}
										block={block}
									/>
								))}
								<div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
									EXTEND mode — copy each block separately into the video
									engine. Do NOT paste both blocks into one generation.
								</div>
							</div>
						) : (
							<div className="space-y-3">
								{workspacePackage && packagePromptText ? (
									<PromptAuditCard
										label="Approved Package Baseline"
										text={packagePromptText}
									/>
								) : null}
								<textarea
									className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
									placeholder="All 3 slots are reference images — the model sees them. Describe WHAT HAPPENS: e.g. 'The character picks up the product, holds it at eye level, smiles at camera. Product is clearly visible in her grip. Scene is the background environment.' Include product size anchor if needed."
									value={manualPrompt}
									onChange={(e) => {
										const next = e.target.value;
										setManualPrompt(next);
										setIsManualOverride(
											Boolean(workspacePackage?.prompt_text) &&
												next !== workspacePackage?.prompt_text,
										);
									}}
								/>
							</div>
						)}
					</div>
				</section>

				<div className="pt-4">
					{i2vImageCount < 2 && (
						<p className="mb-2 text-[11px] font-bold text-amber-300/80">
							I2V requires at least 2 reference images ({i2vImageCount}/2). Add
							a Scene or Style ingredient — the 3rd is optional.
						</p>
					)}
					<button
						type="button"
						onClick={() => void handleExecute()}
						disabled={
							isExecuting ||
							isUploading ||
							isRefreshingPackage ||
							!manualPrompt ||
							i2vImageCount < 2 ||
							executionBlocked
						}
						className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
					>
						{isUploading
							? "Uploading Assets..."
							: isRefreshingPackage
								? "Refreshing Semantic Package..."
								: isExecuting
									? "Sending to Flow Editor..."
									: "SEND TO FLOW EDITOR"}
						{!isExecuting && !isUploading && !isRefreshingPackage && (
							<ArrowRight size={18} />
						)}
					</button>
					<p className="mt-2 text-center text-xs text-slate-400">
						Uploads assets and inserts the prompt into the Flow editor, then
						stops — does not auto-generate, poll, or download.
					</p>
				</div>
			</div>

			<div
				className={`${compact ? "space-y-6 text-slate-300" : "space-y-6 text-slate-300 xl:sticky xl:top-4"}`}
			>
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						Flow Mirror Settings
					</h3>
					<div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
						<div className="space-y-3">
							<p className="text-xs font-bold text-slate-400">Aspect Ratio</p>
							<div className="grid grid-cols-2 gap-2">
								{["VERTICAL", "HORIZONTAL"].map((o) => (
									<button
										type="button"
										key={o}
										onClick={() => setOrientation(o as Orientation)}
										className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === o ? "bg-blue-600/20 border-blue-500 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{o === "VERTICAL" ? "9:16 (Vertical)" : "16:9 (Horizontal)"}
									</button>
								))}
							</div>
						</div>
						<div className="space-y-3">
							<ModelSelect
								models={videoModels}
								value={model}
								onChange={setModel}
							/>
							<p className="text-xs font-bold text-slate-400">Count</p>
							<div className="grid grid-cols-4 gap-2">
								{[1, 2, 3, 4].map((v) => (
									<button
										type="button"
										key={v}
										onClick={() => setCount(v)}
										className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${count === v ? "bg-purple-600/20 border-purple-500 text-purple-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{v}x
									</button>
								))}
							</div>
						</div>
					</div>
				</section>

				<section className="p-6 rounded-2xl border border-purple-500/10 bg-purple-500/5 space-y-3">
					<h4 className="text-[10px] font-bold text-purple-400 uppercase tracking-widest">
						I2V — Prompt Guide
					</h4>
					<div className="text-[10px] text-purple-300/55 leading-relaxed space-y-2">
						<p>
							<strong className="text-purple-300/80">Subject</strong> =
							avatar/character reference image. Model sees the person — describe
							their action, not their look.
						</p>
						<p>
							<strong className="text-purple-300/80">Scene</strong> = product
							reference image. Model sees the product — describe how it's
							handled/demonstrated.
						</p>
						<p>
							<strong className="text-purple-300/80">Style</strong> = scene
							context/environment reference. Model sees the environment —
							describe the mood/activity, not the background.
						</p>
						<p>
							<strong className="text-purple-300/80">Product size</strong> →
							always include a verbal scale anchor (e.g. "serum bottle, 30ml,
							fits in one hand").
						</p>
					</div>
				</section>
			</div>
		</div>
	);
}
