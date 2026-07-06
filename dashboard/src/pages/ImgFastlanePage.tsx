import { useCallback, useEffect, useMemo, useState } from "react";
import {
	archiveCreativeAsset,
	fetchCreativeAssets,
	updateCreativeAsset,
} from "../api/creativeAssets";
import {
	compileImgFastlanePromptPreview,
	type ImageArtifact,
	type ImgAssetLane,
	type ImgFastlaneIngredientRole,
	type ImgFastlanePreset,
	type ImgFastlanePromptPreview,
	type ImgGenerationJob,
	fetchImageArtifacts,
	fetchImgAssetLanes,
	fetchImgFastlanePresets,
	pollImgGenerationJob,
	saveImgOutputToLibrary,
	startImgGeneration,
} from "../api/imgFactory";
import { fetchProductCatalog } from "../api/products";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { CreativeAsset, Product } from "../types";
import {
	canApprove,
	isReusableAsset,
	resolveGenerationInputs,
} from "./imgCockpitLogic";

const GEN_NOT_FIRED = "NOT_FIRED_IN_SESSION";
const GEN_RUNTIME_UNVERIFIED = "EXTERNAL_RUNTIME_NOT_VERIFIED";
const ASPECT_OPTIONS = ["9:16", "1:1", "16:9", "4:3", "3:4"] as const;

type TruthStatus = "UNVERIFIED" | "PASS" | "FAIL";
type ReviewDecision = "PENDING_REVIEW" | "APPROVED" | "REJECTED";
type OutputMode = "artifact" | "upload";
type FastlaneTab = "frames" | "ingredients";

const INGREDIENT_ROLE_OPTIONS: ImgFastlaneIngredientRole[] = [
	"AVATAR_REFERENCE",
	"SCENE_REFERENCE",
	"STYLE_REFERENCE",
	"PRODUCT_REFERENCE",
];

function ingredientRoleLabel(role: ImgFastlaneIngredientRole) {
	switch (role) {
		case "AVATAR_REFERENCE":
			return "Subject / Avatar";
		case "SCENE_REFERENCE":
			return "Scene";
		case "STYLE_REFERENCE":
			return "Style";
		case "PRODUCT_REFERENCE":
			return "Product / Product Lock";
	}
}

function ingredientRoleHelp(role: ImgFastlaneIngredientRole) {
	switch (role) {
		case "AVATAR_REFERENCE":
			return "Creates a reusable character identity. Output role: CHARACTER_REFERENCE.";
		case "SCENE_REFERENCE":
			return "Creates a reusable scene context. Output role: SCENE_CONTEXT_REFERENCE.";
		case "STYLE_REFERENCE":
			return "Creates a reusable visual style reference. Output role: STYLE_REFERENCE.";
		case "PRODUCT_REFERENCE":
			return "Creates a reusable product lock or poster-safe product reference from the database product truth.";
	}
}

function fileToDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = reject;
		reader.readAsDataURL(file);
	});
}

function buildAssetPayload(asset: CreativeAsset | null): Record<string, any> | null {
	if (!asset) return null;
	return {
		mediaId: asset.media_id || null,
		localFilePath: asset.local_file_path || null,
		local_file_path: asset.local_file_path || null,
		downloadUrl: asset.download_url || asset.preview_url || asset.remote_source_url || null,
		image_url: asset.download_url || asset.preview_url || asset.remote_source_url || null,
	};
}

function buildProductAssetPayload(product: Product | null): Record<string, any> | null {
	if (!product) return null;
	return {
		mediaId: product.media_id || null,
		localFilePath: product.local_image_path || null,
		local_file_path: product.local_image_path || null,
		downloadUrl: product.image_url || null,
		image_url: product.image_url || null,
	};
}

function Section({
	step,
	title,
	children,
}: {
	step: string;
	title: string;
	children: React.ReactNode;
}) {
	// No `backdrop-blur` on the section: backdrop-filter creates a stacking
	// context, which traps an open dropdown (SearchableProductSelect, z-50)
	// inside this section so it paints BEHIND the following section instead of
	// overlaying it. The blur is imperceptible over the solid dark page bg.
	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 space-y-4 shadow-lg shadow-black/10">
			<h3 className="text-xs font-bold uppercase tracking-[0.16em] text-slate-300 flex items-center gap-2">
				<span className="rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-slate-300 font-mono text-[10px]">
					{step}
				</span>
				{title}
			</h3>
			{children}
		</section>
	);
}

function ReferenceField({
	label,
	noun,
	assets,
	value,
	onChange,
	emptyHint,
	requiredMissing,
	onApprove,
	approvingId,
}: {
	label: string;
	noun: string;
	assets: CreativeAsset[];
	value: string;
	onChange: (v: string) => void;
	emptyHint: string;
	requiredMissing: boolean;
	onApprove: (asset: CreativeAsset) => void;
	approvingId: string | null;
}) {
	const selected = assets.find((a) => a.asset_id === value) ?? null;
	const selectedApproved = selected ? isReusableAsset(selected) : false;
	return (
		<div className="space-y-1.5">
			<label className="block text-[11px] text-slate-300 space-y-1">
				<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
					{label}
				</span>
				<select
					value={value}
					onChange={(e) => onChange(e.target.value)}
					className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none animate-all"
				>
					<option value="">
						{assets.length === 0 ? emptyHint : "None (optional)"}
					</option>
					{assets.map((a) => (
						<option key={a.asset_id} value={a.asset_id}>
							{a.display_name}
							{isReusableAsset(a) ? "" : ` · ${a.review_status}`}
						</option>
					))}
				</select>
			</label>
			{selected && !selectedApproved ? (
				<div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[10px] text-amber-100 space-y-1.5">
					<div>
						“{selected.display_name}” is <strong>{selected.review_status}</strong> —
						only APPROVED references may be used for generation or lineage.
					</div>
					<button
						type="button"
						onClick={() => onApprove(selected)}
						disabled={approvingId === selected.asset_id}
						className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-50"
					>
						{approvingId === selected.asset_id
							? "Approving…"
							: "Approve for reuse"}
					</button>
				</div>
			) : null}
			{requiredMissing ? (
				<p className="text-[10px] text-amber-300/80">
					This lane requires an approved {noun}.
				</p>
			) : null}
		</div>
	);
}

export default function ImgFastlanePage() {
	const [activeTab, setActiveTab] = useState<FastlaneTab>("frames");
	const [ingSaveLaneId, setIngSaveLaneId] =
		useState<ImgFastlaneIngredientRole>("AVATAR_REFERENCE");
	const [ingCharacterAssetId, setIngCharacterAssetId] = useState("");
	const [ingSceneAssetId, setIngSceneAssetId] = useState("");
	const [ingStyleAssetId, setIngStyleAssetId] = useState("");
	const [ingProductReferenceAssetId, setIngProductReferenceAssetId] = useState("");

	const [lanes, setLanes] = useState<ImgAssetLane[]>([]);
	const [presets, setPresets] = useState<ImgFastlanePreset[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [products, setProducts] = useState<Product[]>([]);
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	const [styleAssets, setStyleAssets] = useState<CreativeAsset[]>([]);
	const [productReferenceAssets, setProductReferenceAssets] = useState<
		CreativeAsset[]
	>([]);

	const [characterAssetId, setCharacterAssetId] = useState("");
	const [sceneAssetId, setSceneAssetId] = useState("");
	const [styleAssetId, setStyleAssetId] = useState("");
	const [approvingId, setApprovingId] = useState<string | null>(null);
	const [refreshing, setRefreshing] = useState(false);
	const [framePresetId, setFramePresetId] = useState("");
	const [ingredientPresetId, setIngredientPresetId] = useState("");
	const [advancedOverrideNotes, setAdvancedOverrideNotes] = useState("");

	const [prompt, setPrompt] = useState("");
	const [compiledPreview, setCompiledPreview] =
		useState<ImgFastlanePromptPreview | null>(null);
	const [displayName, setDisplayName] = useState("");
	const [compiling, setCompiling] = useState(false);
	const [aspect, setAspect] = useState<string>("9:16");
	const [quantity, setQuantity] = useState<number>(1);

	// Gated live generation.
	const [showGenConfirm, setShowGenConfirm] = useState(false);
	const [generating, setGenerating] = useState(false);
	const [genJob, setGenJob] = useState<ImgGenerationJob | null>(null);

	// Register-output (credit-free).
	const [outputMode, setOutputMode] = useState<OutputMode>("artifact");
	const [artifacts, setArtifacts] = useState<ImageArtifact[]>([]);
	const [artifactMediaId, setArtifactMediaId] = useState("");
	const [uploadFile, setUploadFile] = useState<File | null>(null);

	// Scale & truth checklist states.
	const [checklistOversized, setChecklistOversized] = useState(false);
	const [checklistPreserved, setChecklistPreserved] = useState(false);
	const [checklistContext, setChecklistContext] = useState(false);
	const [checklistClaims, setChecklistClaims] = useState(false);
	const [checklistSuitable, setChecklistSuitable] = useState(false);

	const [identityStatus, setIdentityStatus] = useState<TruthStatus>("UNVERIFIED");
	const [scaleStatus, setScaleStatus] = useState<TruthStatus>("UNVERIFIED");
	const [claimStatus, setClaimStatus] = useState<TruthStatus>("UNVERIFIED");
	const [reviewDecision, setReviewDecision] = useState<ReviewDecision>("PENDING_REVIEW");

	const [saving, setSaving] = useState(false);
	const [savedAsset, setSavedAsset] = useState<CreativeAsset | null>(null);
	const [error, setError] = useState<string | null>(null);

	const loadReferences = useCallback(async () => {
		const results = await Promise.allSettled([
			fetchCreativeAssets({
				semantic_role: "CHARACTER_REFERENCE",
				status: "ACTIVE",
				limit: 100,
			}),
			fetchCreativeAssets({
				semantic_role: "SCENE_CONTEXT_REFERENCE",
				status: "ACTIVE",
				limit: 100,
			}),
			fetchCreativeAssets({
				semantic_role: "STYLE_REFERENCE",
				status: "ACTIVE",
				limit: 100,
			}),
			fetchCreativeAssets({
				semantic_role: "PRODUCT_REFERENCE",
				status: "ACTIVE",
				limit: 100,
			}),
			fetchImageArtifacts(50),
		]);
		const [chars, scenes, styles, productRefs, arts] = results;
		if (chars.status === "fulfilled") setCharacterAssets(chars.value.items);
		if (scenes.status === "fulfilled") setSceneAssets(scenes.value.items);
		if (styles.status === "fulfilled") setStyleAssets(styles.value.items);
		if (productRefs.status === "fulfilled")
			setProductReferenceAssets(productRefs.value.items);
		if (arts.status === "fulfilled") setArtifacts(arts.value);
		if (results.some((r) => r.status === "rejected")) {
			setError("Failed to load reference assets from Library.");
		}
	}, []);

	useEffect(() => {
		void fetchImgAssetLanes()
			.then((r) => setLanes(r.items))
			.catch(() => setError("Failed to load IMG lanes."));
		void fetchImgFastlanePresets()
			.then((r) => setPresets(r.items))
			.catch(() => setError("Failed to load IMG Fastlane presets."));
		void fetchProductCatalog(500)
			.then((r) => setProducts(r.items ?? []))
			.catch(() => setError("Failed to load product catalog."));
		void loadReferences();
	}, [loadReferences]);

	useEffect(() => {
		const onFocus = () => void loadReferences();
		window.addEventListener("focus", onFocus);
		return () => window.removeEventListener("focus", onFocus);
	}, [loadReferences]);

	// Automatically choose the correct lane based on selections and tab.
	const lane = useMemo(() => {
		if (compiledPreview?.lane_id) {
			return lanes.find((item) => item.lane_id === compiledPreview.lane_id) ?? null;
		}
		if (activeTab === "frames") {
			const laneId = sceneAssetId ? "AVATAR_PRODUCT_SCENE_COMPOSITE" : "AVATAR_PRODUCT_COMPOSITE";
			return lanes.find((l) => l.lane_id === laneId) ?? null;
		} else {
			return lanes.find((l) => l.lane_id === ingSaveLaneId) ?? null;
		}
	}, [lanes, compiledPreview?.lane_id, activeTab, sceneAssetId, ingSaveLaneId]);

	const selectedCharacter = useMemo(
		() => characterAssets.find((a) => a.asset_id === characterAssetId) ?? null,
		[characterAssets, characterAssetId],
	);
	const selectedScene = useMemo(
		() => sceneAssets.find((a) => a.asset_id === sceneAssetId) ?? null,
		[sceneAssets, sceneAssetId],
	);
	const selectedStyle = useMemo(
		() => styleAssets.find((a) => a.asset_id === styleAssetId) ?? null,
		[styleAssets, styleAssetId],
	);

	const approvedCharacter =
		selectedCharacter && isReusableAsset(selectedCharacter) ? selectedCharacter : null;
	const approvedScene =
		selectedScene && isReusableAsset(selectedScene) ? selectedScene : null;
	const approvedStyle =
		selectedStyle && isReusableAsset(selectedStyle) ? selectedStyle : null;

	// Ingredients selections
	const selectedIngCharacter = useMemo(
		() => characterAssets.find((a) => a.asset_id === ingCharacterAssetId) ?? null,
		[characterAssets, ingCharacterAssetId],
	);
	const selectedIngScene = useMemo(
		() => sceneAssets.find((a) => a.asset_id === ingSceneAssetId) ?? null,
		[sceneAssets, ingSceneAssetId],
	);
	const selectedIngStyle = useMemo(
		() => styleAssets.find((a) => a.asset_id === ingStyleAssetId) ?? null,
		[styleAssets, ingStyleAssetId],
	);
	const selectedIngProductReference = useMemo(
		() =>
			productReferenceAssets.find(
				(a) => a.asset_id === ingProductReferenceAssetId,
			) ?? null,
		[productReferenceAssets, ingProductReferenceAssetId],
	);

	const approvedIngCharacter =
		selectedIngCharacter && isReusableAsset(selectedIngCharacter) ? selectedIngCharacter : null;
	const approvedIngScene =
		selectedIngScene && isReusableAsset(selectedIngScene) ? selectedIngScene : null;
	const approvedIngStyle =
		selectedIngStyle && isReusableAsset(selectedIngStyle) ? selectedIngStyle : null;
	const approvedIngProductReference =
		selectedIngProductReference && isReusableAsset(selectedIngProductReference)
			? selectedIngProductReference
			: null;

	const framePresets = useMemo(
		() => presets.filter((preset) => preset.route === "FRAMES"),
		[presets],
	);
	const ingredientPresets = useMemo(
		() =>
			presets.filter(
				(preset) =>
					preset.route === "INGREDIENTS" &&
					preset.ingredient_role === ingSaveLaneId,
			),
		[presets, ingSaveLaneId],
	);

	useEffect(() => {
		if (!framePresets.length) return;
		setFramePresetId((current) =>
			current && framePresets.some((preset) => preset.preset_id === current)
				? current
				: framePresets[0]?.preset_id ?? "",
		);
	}, [framePresets]);

	useEffect(() => {
		if (!ingredientPresets.length) return;
		setIngredientPresetId((current) =>
			current &&
			ingredientPresets.some((preset) => preset.preset_id === current)
				? current
				: ingredientPresets[0]?.preset_id ?? "",
		);
	}, [ingredientPresets]);

	const resolvedRefsPayload = useMemo(() => {
		const refs: Record<string, any> = {};
		if (activeTab === "frames") {
			if (approvedCharacter) {
				refs.subjectAsset = buildAssetPayload(approvedCharacter);
			}
			if (approvedScene) {
				refs.sceneAsset = buildAssetPayload(approvedScene);
			}
			if (approvedStyle) {
				refs.styleAsset = buildAssetPayload(approvedStyle);
			}
			if (selectedProduct) {
				refs.imageAsset = buildProductAssetPayload(selectedProduct);
			}
		} else {
			if (approvedIngCharacter) {
				refs.subjectAsset = buildAssetPayload(approvedIngCharacter);
			}
			if (approvedIngScene) {
				refs.sceneAsset = buildAssetPayload(approvedIngScene);
			}
			if (approvedIngStyle) {
				refs.styleAsset = buildAssetPayload(approvedIngStyle);
			}
			if (approvedIngProductReference) {
				refs.imageAsset = buildAssetPayload(approvedIngProductReference);
			} else if (selectedProduct) {
				refs.imageAsset = buildProductAssetPayload(selectedProduct);
			}
		}
		return refs;
	}, [
		activeTab,
		approvedCharacter,
		approvedScene,
		approvedStyle,
		selectedProduct,
		approvedIngCharacter,
		approvedIngScene,
		approvedIngStyle,
		approvedIngProductReference,
	]);

	const genResolution = useMemo(
		() =>
			resolveGenerationInputs(lane, {
				product: selectedProduct,
				character: approvedCharacter,
				scene: approvedScene,
				style: approvedStyle,
			}),
		[lane, selectedProduct, approvedCharacter, approvedScene, approvedStyle],
	);

	// Validate product visual reference: media_id OR image_url OR local_image_path.
	const productResolvable = Boolean(
		selectedProduct &&
			(selectedProduct.media_id ||
				selectedProduct.image_url ||
				selectedProduct.local_image_path),
	);

	const productMissing = Boolean(activeTab === "frames" && lane?.requires_product_id && !selectedProduct);
	const productVisualReferenceMissing = Boolean(activeTab === "frames" && lane?.requires_product_id && selectedProduct && !productResolvable);

	const compiledBlockers = compiledPreview?.blockers ?? [];
	const characterMissing = compiledBlockers.includes("AVATAR_REFERENCE_REQUIRED");
	const sceneMissing =
		compiledBlockers.includes("SCENE_REFERENCE_REQUIRED") ||
		compiledBlockers.includes("SCENE_OR_STYLE_CONTEXT_REQUIRED");
	const styleMissing =
		compiledBlockers.includes("STYLE_REFERENCE_REQUIRED") ||
		compiledBlockers.includes("SCENE_OR_STYLE_CONTEXT_REQUIRED");

	// Generation is blocked if inputs are missing OR product has no visual reference.
	const generationBlocked =
		activeTab === "frames"
			? (productMissing ||
				productVisualReferenceMissing ||
				characterMissing ||
				sceneMissing ||
				styleMissing ||
				genResolution.blocked ||
				compiledBlockers.length > 0 ||
				!prompt.trim())
			: compiledBlockers.length > 0 || !prompt.trim();

	const hasRealOutput =
		outputMode === "artifact" ? Boolean(artifactMediaId) : Boolean(uploadFile);

	const isChecklistComplete =
		checklistOversized &&
		checklistPreserved &&
		checklistContext &&
		checklistClaims &&
		checklistSuitable;

	// Scale guard: Frames mode requires all checks and checklist to PASS before approval is allowed.
	const scaleGuardFailed =
		activeTab === "frames" && reviewDecision === "APPROVED" && !isChecklistComplete;

	const approvalBlocked =
		reviewDecision === "APPROVED" &&
		(!canApprove({
			identity: identityStatus,
			scale: scaleStatus,
			claim: claimStatus,
		}) ||
			scaleGuardFailed);

	const canSave = Boolean(
		lane &&
			displayName.trim() &&
			hasRealOutput &&
			prompt.trim() &&
			!generationBlocked &&
			!approvalBlocked &&
			!saving,
	);

	const handleRefresh = async () => {
		setRefreshing(true);
		setError(null);
		try {
			await loadReferences();
		} finally {
			setRefreshing(false);
		}
	};

	const handleApproveAsset = async (asset: CreativeAsset) => {
		setApprovingId(asset.asset_id);
		setError(null);
		try {
			await updateCreativeAsset(asset.asset_id, { review_status: "APPROVED" });
			await loadReferences();
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to approve the reference.",
			);
		} finally {
			setApprovingId(null);
		}
	};

	const compileFastlanePreview = useCallback(async () => {
		const presetId = activeTab === "frames" ? framePresetId : ingredientPresetId;
		if (!presetId) {
			setCompiledPreview(null);
			setPrompt("");
			return;
		}
		setCompiling(true);
		setError(null);
		try {
			const preview = await compileImgFastlanePromptPreview({
				preset_id: presetId,
				route: activeTab === "frames" ? "FRAMES" : "INGREDIENTS",
				ingredient_role:
					activeTab === "ingredients" ? ingSaveLaneId : undefined,
				product_id: selectedProduct?.id ?? null,
				character_reference_asset_id:
					activeTab === "frames"
						? characterAssetId || null
						: ingCharacterAssetId || null,
				scene_reference_asset_id:
					activeTab === "frames" ? sceneAssetId || null : ingSceneAssetId || null,
				style_reference_asset_id:
					activeTab === "frames" ? styleAssetId || null : ingStyleAssetId || null,
				product_reference_asset_id:
					activeTab === "ingredients" ? ingProductReferenceAssetId || null : null,
				advanced_override_notes: advancedOverrideNotes || null,
			});
			setCompiledPreview(preview);
			setPrompt(preview.prompt_text || "");
			setDisplayName((current) =>
				current.trim() ? current : preview.display_name_suggestion,
			);
		} catch (err) {
			setCompiledPreview(null);
			setPrompt("");
			setError(
				err instanceof Error
					? err.message
					: "Failed to compile Fastlane prompt preview.",
			);
		} finally {
			setCompiling(false);
		}
	}, [
		activeTab,
		framePresetId,
		ingredientPresetId,
		ingSaveLaneId,
		selectedProduct?.id,
		characterAssetId,
		sceneAssetId,
		styleAssetId,
		ingCharacterAssetId,
		ingSceneAssetId,
		ingStyleAssetId,
		ingProductReferenceAssetId,
		advancedOverrideNotes,
	]);

	useEffect(() => {
		const presetId = activeTab === "frames" ? framePresetId : ingredientPresetId;
		if (!presetId) {
			setCompiledPreview(null);
			setPrompt("");
			return;
		}
		const handle = window.setTimeout(() => {
			void compileFastlanePreview();
		}, 150);
		return () => window.clearTimeout(handle);
	}, [compileFastlanePreview, activeTab, framePresetId, ingredientPresetId]);

	const handleConfirmedGenerate = async () => {
		setShowGenConfirm(false);
		setGenerating(true);
		setError(null);
		try {
			const { job_id } = await startImgGeneration({
				prompt,
				image_media_ids: Object.values(resolvedRefsPayload)
					.map((asset) => asset.mediaId)
					.filter((id): id is string => Boolean(id)),
				refs: resolvedRefsPayload,
				aspect,
				count: quantity,
			});
			const job = await pollImgGenerationJob(job_id);
			setGenJob(job);
			if (job.status === "DONE" && job.media_id) {
				const mediaId = job.media_id;
				const sizeMb =
					typeof job.size_mb === "number" ? job.size_mb : null;
				setOutputMode("artifact");
				setArtifactMediaId(mediaId);
				setArtifacts((prev) =>
					prev.some((a) => a.media_id === mediaId)
						? prev
						: [
								{ media_id: mediaId, artifact_kind: "image", size_mb: sizeMb },
								...prev,
							],
				);
			}
		} catch (err) {
			setError(err instanceof Error ? err.message : "Generation call failed.");
		} finally {
			setGenerating(false);
		}
	};

	const resetOutputForm = () => {
		setDisplayName("");
		setArtifactMediaId("");
		setUploadFile(null);
		setOutputMode("artifact");
		setCompiledPreview(null);
		setPrompt("");
		setAdvancedOverrideNotes("");
		setChecklistOversized(false);
		setChecklistPreserved(false);
		setChecklistContext(false);
		setChecklistClaims(false);
		setChecklistSuitable(false);
		setIdentityStatus("UNVERIFIED");
		setScaleStatus("UNVERIFIED");
		setClaimStatus("UNVERIFIED");
		setReviewDecision("PENDING_REVIEW");
	};

	const handleSave = async () => {
		if (!lane) return;
		setSaving(true);
		setError(null);
		setSavedAsset(null);
		try {
			const base = {
				lane_id: lane.lane_id,
				display_name: displayName.trim(),
				description: prompt.trim() || null,
				product_id: selectedProduct?.id || null,
				source_character_asset_id: (activeTab === "frames" ? approvedCharacter : approvedIngCharacter)?.asset_id || null,
				source_scene_asset_id: (activeTab === "frames" ? approvedScene : approvedIngScene)?.asset_id || null,
				source_style_asset_id: (activeTab === "frames" ? approvedStyle : approvedIngStyle)?.asset_id || null,
				identity_lock_status: identityStatus,
				scale_truth_status: scaleStatus,
				claim_safety_status: claimStatus,
				review_status: reviewDecision,
			};
			const output =
				outputMode === "artifact"
					? { generated_artifact_media_id: artifactMediaId }
					: { image_base64: await fileToDataUrl(uploadFile as File), file_name: uploadFile?.name };

			const asset = await saveImgOutputToLibrary({ ...base, ...output });

			if (reviewDecision === "REJECTED") {
				await archiveCreativeAsset(asset.asset_id);
			}
			setSavedAsset(asset);
			await loadReferences();
			resetOutputForm();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to save to Creative Library.");
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6 max-w-6xl mx-auto">
			<header className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-xl shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
				<div>
					<h2 className="text-lg font-bold text-white tracking-wide">IMG Fastlane</h2>
					<p className="mt-1 text-xs text-slate-400">
						Fast generation and registration of clean F2V Start Frames or reusable Ingredients.
					</p>
				</div>
				<button
					type="button"
					onClick={() => void handleRefresh()}
					disabled={refreshing}
					className="rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 hover:border-slate-600 transition-all disabled:opacity-50 cursor-pointer"
				>
					{refreshing ? "Refreshing…" : "↻ Refresh library"}
				</button>
			</header>

			{error ? (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-200 shadow-md">
					{error}
				</div>
			) : null}

			{/* Navigation Tabs */}
			<div className="flex border-b border-slate-800">
				<button
					onClick={() => {
						setActiveTab("frames");
						resetOutputForm();
					}}
					className={`px-6 py-3 text-xs font-bold uppercase tracking-wider transition-all border-b-2 cursor-pointer ${
						activeTab === "frames"
							? "border-blue-500 text-blue-400 bg-blue-500/5"
							: "border-transparent text-slate-400 hover:text-slate-200"
					}`}
				>
					Frames Fastlane
				</button>
				<button
					onClick={() => {
						setActiveTab("ingredients");
						resetOutputForm();
					}}
					className={`px-6 py-3 text-xs font-bold uppercase tracking-wider transition-all border-b-2 cursor-pointer ${
						activeTab === "ingredients"
							? "border-blue-500 text-blue-400 bg-blue-500/5"
							: "border-transparent text-slate-400 hover:text-slate-200"
					}`}
				>
					Ingredients Fastlane
				</button>
			</div>

			<div className="grid gap-6 lg:grid-cols-12">
				{/* Left Column: Configurations */}
				<div className="lg:col-span-7 space-y-6">
					{activeTab === "frames" ? (
						<>
							<Section step="1" title="Select Product">
								<div className="space-y-2">
									<p className="text-[11px] text-slate-400">
										Required. Product truth is loaded from the product database and compiled automatically into the Fastlane preset.
									</p>
									<SearchableProductSelect
										products={products}
										selectedProduct={selectedProduct}
										onSelect={setSelectedProduct}
									/>
									{productMissing ? (
										<p className="text-[10px] text-amber-300/80">
											Frames Fastlane blocks generation until a database product is selected.
										</p>
									) : null}
									{selectedProduct && !productResolvable ? (
										<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200 space-y-1">
											<div>
												<strong>No Product Visual Reference:</strong>
											</div>
											<div>
												This product has no media_id, image_url, or local_image_path. Generation is blocked until the product row has a real image reference.
											</div>
										</div>
									) : null}
								</div>
							</Section>

							<Section step="2" title="Template Preset">
								<div className="space-y-3">
									<label className="block text-[11px] text-slate-300 space-y-1">
										<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
											Template Preset
										</span>
										<select
											value={framePresetId}
											onChange={(event) => setFramePresetId(event.target.value)}
											className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
										>
											<option value="">
												{framePresets.length
													? "Select a frame preset…"
													: "No frame presets available"}
											</option>
											{framePresets.map((preset) => (
												<option key={preset.preset_id} value={preset.preset_id}>
													{preset.label}
												</option>
											))}
										</select>
									</label>
									{framePresetId ? (
										<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-400 space-y-1">
											<div className="font-semibold text-slate-200">
												{
													framePresets.find((preset) => preset.preset_id === framePresetId)
														?.description
												}
											</div>
											<div>
												Required inputs:{" "}
												{(
													framePresets.find((preset) => preset.preset_id === framePresetId)
														?.required_inputs ?? []
												).join(" • ")}
											</div>
										</div>
									) : null}
								</div>
							</Section>

							<Section step="3" title="Select Existing References">
								<div className="grid gap-4 md:grid-cols-2">
									<ReferenceField
										label="Select Existing Reference — Avatar"
										noun="avatar"
										assets={characterAssets}
										value={characterAssetId}
										onChange={setCharacterAssetId}
										emptyHint="No references found — create one from preset"
										requiredMissing={characterMissing}
										onApprove={handleApproveAsset}
										approvingId={approvingId}
									/>
									<ReferenceField
										label="Select Existing Reference — Style"
										noun="style reference"
										assets={styleAssets}
										value={styleAssetId}
										onChange={setStyleAssetId}
										emptyHint="No references found — create one from preset"
										requiredMissing={styleMissing}
										onApprove={handleApproveAsset}
										approvingId={approvingId}
									/>
								</div>
								<div className="mt-2 flex gap-2">
									<a
										href="/assets/avatar-registry"
										target="_blank"
										rel="noopener noreferrer"
										className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-[10px] font-semibold text-blue-100 hover:bg-blue-500/20 text-center flex-1 transition-all"
									>
										Open Avatar Registry ↗
									</a>
									<a
										href="/assets/creative-library"
										target="_blank"
										rel="noopener noreferrer"
										className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[10px] font-semibold text-slate-200 hover:bg-slate-800 text-center flex-1 transition-all"
									>
										Open Creative Library ↗
									</a>
								</div>
							</Section>

							<Section step="4" title="Select Existing Reference — Scene">
								<div className="space-y-2">
									<ReferenceField
										label="Select Existing Reference"
										noun="scene reference"
										assets={sceneAssets}
										value={sceneAssetId}
										onChange={setSceneAssetId}
										emptyHint="No references found — create one from preset"
										requiredMissing={sceneMissing}
										onApprove={handleApproveAsset}
										approvingId={approvingId}
									/>
									<p className="text-[10px] text-slate-500">
										Optional for generic frames, but scene-aware presets will surface a blocker until context is selected.
									</p>
								</div>
							</Section>
						</>
					) : (
						<>
							<Section step="1" title="Select Target Ingredient Role">
								<div className="grid gap-2 md:grid-cols-2">
									{INGREDIENT_ROLE_OPTIONS.map((role) => (
										<button
											key={role}
											type="button"
											onClick={() => setIngSaveLaneId(role)}
											className={`rounded-xl border py-2.5 text-[10px] font-bold uppercase tracking-wider transition-all cursor-pointer ${
												ingSaveLaneId === role
													? "border-blue-500 bg-blue-600/10 text-blue-400"
													: "border-slate-800 bg-slate-950 text-slate-400 hover:border-slate-700 hover:text-slate-200"
											}`}
										>
											{ingredientRoleLabel(role)}
										</button>
									))}
								</div>
								<div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-3 text-[11px] text-slate-400">
									{ingredientRoleHelp(ingSaveLaneId)}
								</div>
							</Section>

							<Section step="2" title="Select Product / Context">
								<div className="space-y-3">
									<p className="text-[11px] text-slate-400">
										Product context is optional for generic avatar / scene / style presets, but required for product locks and product-truth poster presets.
									</p>
									<SearchableProductSelect
										products={products}
										selectedProduct={selectedProduct}
										onSelect={setSelectedProduct}
									/>
								</div>
							</Section>

							<Section step="3" title="Select Existing Reference Or Create From Preset">
								<div className="space-y-4">
									<label className="block text-[11px] text-slate-300 space-y-1">
										<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
											Template Preset
										</span>
										<select
											value={ingredientPresetId}
											onChange={(event) =>
												setIngredientPresetId(event.target.value)
											}
											className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
										>
											<option value="">
												{ingredientPresets.length
													? "Select a preset…"
													: "No presets available for this role"}
											</option>
											{ingredientPresets.map((preset) => (
												<option key={preset.preset_id} value={preset.preset_id}>
													{preset.label}
												</option>
											))}
										</select>
									</label>

									{ingSaveLaneId === "AVATAR_REFERENCE" ? (
										<ReferenceField
											label="Select Existing Reference"
											noun="avatar"
											assets={characterAssets}
											value={ingCharacterAssetId}
											onChange={setIngCharacterAssetId}
											emptyHint="No references found — create one from preset"
											requiredMissing={false}
											onApprove={handleApproveAsset}
											approvingId={approvingId}
										/>
									) : null}
									{ingSaveLaneId === "SCENE_REFERENCE" ? (
										<ReferenceField
											label="Select Existing Reference"
											noun="scene reference"
											assets={sceneAssets}
											value={ingSceneAssetId}
											onChange={setIngSceneAssetId}
											emptyHint="No references found — create one from preset"
											requiredMissing={false}
											onApprove={handleApproveAsset}
											approvingId={approvingId}
										/>
									) : null}
									{ingSaveLaneId === "STYLE_REFERENCE" ? (
										<ReferenceField
											label="Select Existing Reference"
											noun="style reference"
											assets={styleAssets}
											value={ingStyleAssetId}
											onChange={setIngStyleAssetId}
											emptyHint="No references found — create one from preset"
											requiredMissing={false}
											onApprove={handleApproveAsset}
											approvingId={approvingId}
										/>
									) : null}
									{ingSaveLaneId === "PRODUCT_REFERENCE" ? (
										<ReferenceField
											label="Select Existing Reference"
											noun="product reference"
											assets={productReferenceAssets}
											value={ingProductReferenceAssetId}
											onChange={setIngProductReferenceAssetId}
											emptyHint="No references found — create one from preset"
											requiredMissing={false}
											onApprove={handleApproveAsset}
											approvingId={approvingId}
										/>
									) : null}

									<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-400">
										<div className="font-semibold text-slate-200">
											Create From Preset
										</div>
										<div className="mt-1">
											No references found — create one from preset. Fastlane compiles the prompt automatically from the selected role, product context, preset, and existing lineage.
										</div>
									</div>
								</div>
							</Section>
						</>
					)}

					{/* Section 4: Prompt Creator */}
					<Section
						step={activeTab === "frames" ? "5" : "4"}
						title="Auto-built Prompt Preview"
					>
						<div className="grid gap-4 md:grid-cols-2">
							<label className="block text-[11px] text-slate-300 space-y-1">
								<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Advanced Override Notes optional
								</span>
								<textarea
									value={advancedOverrideNotes}
									onChange={(event) =>
										setAdvancedOverrideNotes(event.target.value)
									}
									className="h-24 w-full rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-none"
									placeholder="Optional notes only. Fastlane still builds the main prompt from product truth, preset rules, and selected references."
								/>
							</label>
							<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-400 space-y-2">
								<div className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Template State
								</div>
								<div>{compiling ? "Compiling preview…" : "Prompt preview auto-build is active."}</div>
								<div>
									Template Preset:{" "}
									<strong className="text-slate-200">
										{compiledPreview?.preset_id || "Not selected"}
									</strong>
								</div>
								<div>
									Output Spec:{" "}
									<strong className="text-slate-200">
										{compiledPreview?.output_spec || "Unavailable"}
									</strong>
								</div>
								<div>
									Target Lane:{" "}
									<strong className="text-slate-200">
										{compiledPreview?.lane_id || lane?.lane_id || "Unknown"}
									</strong>
								</div>
							</div>
						</div>
						<textarea
							value={prompt}
							readOnly
							className="h-28 w-full rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-none"
							placeholder="Auto-built prompt preview appears here after selecting a preset and any required database truth."
						/>
						{compiledPreview?.reference_map?.length ? (
							<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-400 space-y-1">
								<div className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Reference Map
								</div>
								{compiledPreview.reference_map.map((line) => (
									<div key={line}>{line}</div>
								))}
							</div>
						) : null}
						{compiledBlockers.length ? (
							<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] text-amber-100 space-y-1">
								<div className="font-semibold uppercase tracking-[0.14em] text-amber-200">
									Fastlane Blockers
								</div>
								{compiledBlockers.map((blocker) => (
									<div key={blocker}>{blocker}</div>
								))}
							</div>
						) : null}
						{compiledPreview?.warnings.length ? (
							<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-400 space-y-1">
								<div className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Warnings
								</div>
								{compiledPreview.warnings.map((warning) => (
									<div key={warning}>{warning}</div>
								))}
							</div>
						) : null}
					</Section>

					{/* Section 5: Generation configuration & confirm trigger */}
					<Section step={activeTab === "frames" ? "5" : "6"} title="Generate (Gated · Credit-spending)">
						<div className="grid gap-4 md:grid-cols-3">
							<label className="block text-[11px] text-slate-300 space-y-1">
								<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Aspect Ratio
								</span>
								<select
									value={aspect}
									onChange={(e) => setAspect(e.target.value)}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
								>
									{ASPECT_OPTIONS.map((a) => (
										<option key={a} value={a}>
											{a}
										</option>
									))}
								</select>
							</label>
							<label className="block text-[11px] text-slate-300 space-y-1">
								<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Quantity (Capped 1-4)
								</span>
								<input
									type="number"
									min="1"
									max="4"
									value={quantity}
									onChange={(e) => setQuantity(Math.max(1, Math.min(4, parseInt(e.target.value) || 1)))}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
								/>
							</label>
						</div>

						{/* Live Payload Preview */}
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-xs text-slate-300 space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
								Generate Payload Preview
							</div>
							<div>
								Aspect: <strong>{aspect}</strong> | Count: <strong>{quantity}</strong>
							</div>
							<div className="space-y-1">
								<span className="text-[10px] font-semibold text-slate-500 block">refs payload:</span>
								<pre className="max-h-40 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-2 font-mono text-[10px] text-slate-400">
									{JSON.stringify(resolvedRefsPayload, null, 2)}
								</pre>
							</div>
						</div>

						<button
							type="button"
							onClick={() => setShowGenConfirm(true)}
							disabled={!prompt.trim() || generating || generationBlocked}
							className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-5 py-2.5 text-xs font-bold text-rose-300 hover:bg-rose-500/20 disabled:opacity-40 transition-all w-full cursor-pointer"
						>
							{generating ? "Generating (live)…" : "Generate Live Image (Spends Credits)"}
						</button>
						{genJob && (
							<div className="text-xs text-slate-300 mt-2">
								Job Status: <strong>{genJob.status}</strong>
								{genJob.media_id ? ` | Media: ${genJob.media_id}` : ""}
							</div>
						)}
					</Section>
				</div>

				{/* Right Column: Registry, Checklist, Save */}
				<div className="lg:col-span-5 space-y-6">
					{/* Register Output Section */}
					<Section
						step={activeTab === "frames" ? "6" : "5"}
						title="Register Output (Credit-free)"
					>
						<div className="flex gap-1 rounded-xl border border-slate-700 bg-slate-950 p-0.5 text-[10px] font-bold uppercase tracking-wider">
							<button
								type="button"
								onClick={() => setOutputMode("artifact")}
								className={`flex-1 rounded-lg px-3 py-1.5 cursor-pointer ${
									outputMode === "artifact" ? "bg-blue-600 text-white" : "text-slate-400"
								}`}
							>
								Finished Artifact
							</button>
							<button
								type="button"
								onClick={() => setOutputMode("upload")}
								className={`flex-1 rounded-lg px-3 py-1.5 cursor-pointer ${
									outputMode === "upload" ? "bg-blue-600 text-white" : "text-slate-400"
								}`}
							>
								Upload File
							</button>
						</div>

						{outputMode === "artifact" ? (
							<div className="space-y-2">
								<select
									value={artifactMediaId}
									onChange={(e) => setArtifactMediaId(e.target.value)}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
								>
									<option value="">
										{artifacts.length === 0
											? "No finished image artifacts found — generate one first or use Upload File"
											: "Select a finished image artifact…"}
									</option>
									{artifacts.map((a) => (
										<option key={a.media_id} value={a.media_id}>
											{a.media_id} {a.size_mb ? `(${a.size_mb}MB)` : ""}
										</option>
									))}
								</select>
								<p className="text-[10px] text-slate-500">
									Finished Artifact reads from the real generated artifact records returned by <code>/api/flow/artifacts</code>.
								</p>
							</div>
						) : (
							<div className="space-y-2">
								<input
									type="file"
									accept="image/*"
									onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
									className="w-full text-xs text-slate-400 file:mr-3 file:rounded-xl file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-slate-200 file:cursor-pointer"
								/>
								<p className="text-[10px] text-slate-500">
									Upload File creates a finished artifact candidate for review and save-to-library without requiring a raw prompt rewrite.
								</p>
								{uploadFile ? (
									<div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-[10px] text-slate-300">
										Finished artifact candidate: <strong>{uploadFile.name}</strong>
									</div>
								) : null}
							</div>
						)}
					</Section>

					{/* Scale & Truth Checklist (Only for Frames mode when product is selected) */}
					{activeTab === "frames" && selectedProduct && (
						<Section step="7" title="Product Scale Truth Guard">
							<div className="space-y-3">
								<p className="text-[10px] text-slate-400">
									Checklist to ensure realistic product proportions and avoid misleading claims.
								</p>
								<div className="space-y-2">
									<label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
										<input
											type="checkbox"
											checked={checklistOversized}
											onChange={(e) => setChecklistOversized(e.target.checked)}
											className="mt-0.5 rounded border-slate-700 bg-slate-950 text-blue-600"
										/>
										<span>Product is realistic handheld/small scale (not oversized)</span>
									</label>
									<label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
										<input
											type="checkbox"
											checked={checklistPreserved}
											onChange={(e) => setChecklistPreserved(e.target.checked)}
											className="mt-0.5 rounded border-slate-700 bg-slate-950 text-blue-600"
										/>
										<span>Label, cap, and body are preserved truthfully</span>
									</label>
									<label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
										<input
											type="checkbox"
											checked={checklistContext}
											onChange={(e) => setChecklistContext(e.target.checked)}
											className="mt-0.5 rounded border-slate-700 bg-slate-950 text-blue-600"
										/>
										<span>Product scale matches hand/body context naturally</span>
									</label>
									<label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
										<input
											type="checkbox"
											checked={checklistClaims}
											onChange={(e) => setChecklistClaims(e.target.checked)}
											className="mt-0.5 rounded border-slate-700 bg-slate-950 text-blue-600"
										/>
										<span>No misleading claims or text added to image</span>
									</label>
									<label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
										<input
											type="checkbox"
											checked={checklistSuitable}
											onChange={(e) => setChecklistSuitable(e.target.checked)}
											className="mt-0.5 rounded border-slate-700 bg-slate-950 text-blue-600"
										/>
										<span>Suitable as clean F2V Start Frame (contains_rendered_text=false)</span>
									</label>
								</div>
							</div>
						</Section>
					)}

					{/* Review & Decision Panel */}
					<Section step={activeTab === "frames" && selectedProduct ? "8" : "7"} title="Review & Approval">
						<div className="grid gap-3 md:grid-cols-3">
							{(
								[
									["Identity lock", identityStatus, setIdentityStatus],
									["Scale truth", scaleStatus, setScaleStatus],
									["Claim safety", claimStatus, setClaimStatus],
								] as const
							).map(([label, val, set]) => (
								<label key={label} className="block text-[11px] text-slate-300 space-y-1">
									<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
										{label}
									</span>
									<select
										value={val}
										onChange={(e) => set(e.target.value as TruthStatus)}
										className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
									>
										<option value="UNVERIFIED">UNVERIFIED</option>
										<option value="PASS">PASS</option>
										<option value="FAIL">FAIL</option>
									</select>
								</label>
							))}
						</div>

						<div className="flex gap-2 mt-4">
							{(["PENDING_REVIEW", "APPROVED", "REJECTED"] as const).map((d) => (
								<button
									type="button"
									key={d}
									onClick={() => setReviewDecision(d)}
									className={`flex-1 rounded-xl border py-2 text-xs font-bold transition-all cursor-pointer ${
										reviewDecision === d
											? "border-blue-500 bg-blue-600/20 text-blue-100"
											: "border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"
									}`}
								>
									{d}
								</button>
							))}
						</div>

						{approvalBlocked && (
							<p className="text-[10px] text-amber-300/80 mt-2">
								{scaleGuardFailed
									? "APPROVED requires checking all items in the scale checklist first."
									: "APPROVED requires Identity, Scale, and Claim to ALL PASS (FAIL or UNVERIFIED blocks approval)."}
							</p>
						)}
					</Section>

					{/* Save Section */}
					<Section step={activeTab === "frames" && selectedProduct ? "9" : "8"} title="Save to Creative Library">
						<label className="block text-[11px] text-slate-300 space-y-1">
							<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
								Display Name
							</span>
							<input
								value={displayName}
								onChange={(e) => setDisplayName(e.target.value)}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
								placeholder="e.g. Minyak Warisan — Start Frame A"
							/>
						</label>

						<button
							type="button"
							onClick={() => void handleSave()}
							disabled={!canSave}
							className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 py-3 text-sm font-bold text-white hover:opacity-90 disabled:opacity-50 disabled:grayscale transition-all cursor-pointer"
						>
							{saving ? "Saving…" : "Save to Creative Library"}
						</button>

						{savedAsset && (
							<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-xs text-emerald-200 shadow-md">
								Saved <strong>{savedAsset.display_name}</strong> as{" "}
								<strong>{savedAsset.semantic_role}</strong> ({savedAsset.review_status})
								{savedAsset.allowed_modes.length > 0
									? ` | Reusable in: ${savedAsset.allowed_modes.join(", ")}`
									: ""}
							</div>
						)}
					</Section>
				</div>
			</div>

			{/* live confirmation modal */}
			{showGenConfirm && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-[2px]">
					<div className="max-w-md w-full rounded-2xl border border-rose-500/40 bg-slate-950 p-6 space-y-4 shadow-2xl">
						<div className="text-sm font-bold text-rose-300 uppercase tracking-wider">
							⚠️ Confirm Live Credit-spending Generation
						</div>
						<div className="text-xs text-slate-300 space-y-2">
							<p>
								This will trigger a real image generation on Google Flow and <strong>spends credits</strong>.
							</p>
							<p>
								Build status: <strong>{GEN_NOT_FIRED}</strong> | <strong>{GEN_RUNTIME_UNVERIFIED}</strong>.
							</p>
						</div>
						<div className="flex justify-end gap-3 pt-2">
							<button
								type="button"
								onClick={() => setShowGenConfirm(false)}
								className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 cursor-pointer"
							>
								Cancel
							</button>
							<button
								type="button"
								onClick={() => void handleConfirmedGenerate()}
								className="rounded-xl border border-rose-500/40 bg-rose-500/20 px-4 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/30 cursor-pointer"
							>
								Confirm &amp; Generate (live)
							</button>
						</div>
					</div>
				</div>
			)}
		</div>
	);
}
