import { useCallback, useEffect, useMemo, useState } from "react";
import {
	archiveCreativeAsset,
	fetchCreativeAssets,
	updateCreativeAsset,
} from "../api/creativeAssets";
import {
	type ImageArtifact,
	type ImgAssetLane,
	type ImgGenerationJob,
	fetchImageArtifacts,
	fetchImgAssetLanes,
	pollImgGenerationJob,
	saveImgOutputToLibrary,
	startImgGeneration,
} from "../api/imgFactory";
import { fetchProductCatalog } from "../api/products";
import { compileWorkspacePromptPreview } from "../api/workspacePackages";
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
type IngredientType = "subject" | "scene" | "style";

function fileToDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = reject;
		reader.readAsDataURL(file);
	});
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
	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 space-y-4 shadow-lg shadow-black/10 backdrop-blur-md">
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
	const [ingredientType, setIngredientType] = useState<IngredientType>("subject");

	const [lanes, setLanes] = useState<ImgAssetLane[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [products, setProducts] = useState<Product[]>([]);
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	const [styleAssets, setStyleAssets] = useState<CreativeAsset[]>([]);

	const [characterAssetId, setCharacterAssetId] = useState("");
	const [sceneAssetId, setSceneAssetId] = useState("");
	const [styleAssetId, setStyleAssetId] = useState("");
	const [approvingId, setApprovingId] = useState<string | null>(null);
	const [refreshing, setRefreshing] = useState(false);

	const [prompt, setPrompt] = useState("");
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
			fetchCreativeAssets({ semantic_role: "CHARACTER_REFERENCE", status: "ACTIVE", limit: 100 }),
			fetchCreativeAssets({ semantic_role: "SCENE_CONTEXT_REFERENCE", status: "ACTIVE", limit: 100 }),
			fetchCreativeAssets({ semantic_role: "STYLE_REFERENCE", status: "ACTIVE", limit: 100 }),
			fetchImageArtifacts(50),
		]);
		const [chars, scenes, styles, arts] = results;
		if (chars.status === "fulfilled") setCharacterAssets(chars.value.items);
		if (scenes.status === "fulfilled") setSceneAssets(scenes.value.items);
		if (styles.status === "fulfilled") setStyleAssets(styles.value.items);
		if (arts.status === "fulfilled") setArtifacts(arts.value);
		if (results.some((r) => r.status === "rejected")) {
			setError("Failed to load reference assets from Library.");
		}
	}, []);

	useEffect(() => {
		void fetchImgAssetLanes()
			.then((r) => setLanes(r.items))
			.catch(() => setError("Failed to load IMG lanes."));
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
		if (activeTab === "frames") {
			// If a scene is selected, use AVATAR_PRODUCT_SCENE_COMPOSITE. Otherwise, AVATAR_PRODUCT_COMPOSITE.
			const laneId = sceneAssetId ? "AVATAR_PRODUCT_SCENE_COMPOSITE" : "AVATAR_PRODUCT_COMPOSITE";
			return lanes.find((l) => l.lane_id === laneId) ?? null;
		} else {
			// Ingredients lanes based on sub-selector
			const laneId =
				ingredientType === "subject"
					? "AVATAR_REFERENCE"
					: ingredientType === "scene"
						? "SCENE_REFERENCE"
						: "STYLE_REFERENCE";
			return lanes.find((l) => l.lane_id === laneId) ?? null;
		}
	}, [lanes, activeTab, ingredientType, sceneAssetId]);

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

	const productMissing = Boolean(lane?.requires_product_id && !selectedProduct);
	const productVisualReferenceMissing = Boolean(lane?.requires_product_id && selectedProduct && !productResolvable);

	const characterMissing = Boolean(lane?.requires_character_reference && !approvedCharacter);
	const sceneMissing = Boolean(lane?.requires_scene_reference && !approvedScene);
	const styleMissing = Boolean(lane?.requires_style_reference && !approvedStyle);

	// Generation is blocked if inputs are missing OR product has no visual reference.
	const generationBlocked =
		productMissing ||
		productVisualReferenceMissing ||
		characterMissing ||
		sceneMissing ||
		styleMissing ||
		genResolution.blocked;

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

	const handleCompilePrompt = async () => {
		if (!selectedProduct) return;
		setCompiling(true);
		setError(null);
		try {
			const preview = await compileWorkspacePromptPreview({
				product_id: selectedProduct.id,
				mode: "IMG",
				source_mode: "IMAGES",
			});
			setPrompt(preview.final_compiled_prompt_text || prompt);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to compile suggested prompt.",
			);
		} finally {
			setCompiling(false);
		}
	};

	const handleConfirmedGenerate = async () => {
		setShowGenConfirm(false);
		setGenerating(true);
		setError(null);
		try {
			const { job_id } = await startImgGeneration({
				prompt,
				image_media_ids: genResolution.mediaIds,
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
				source_character_asset_id: approvedCharacter?.asset_id || null,
				source_scene_asset_id: approvedScene?.asset_id || null,
				source_style_asset_id: approvedStyle?.asset_id || null,
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
							{/* Section 1: Product Selection */}
							<Section step="1" title="Select Product">
								<div className="space-y-2">
									<p className="text-[11px] text-slate-400">
										Required. Selected product details will compile visual truth templates.
									</p>
									<SearchableProductSelect
										products={products}
										selectedProduct={selectedProduct}
										onSelect={setSelectedProduct}
									/>
									{productMissing ? (
										<p className="text-[10px] text-amber-300/80">
											Frames mode requires a product to ensure product truth.
										</p>
									) : null}
									{selectedProduct && !productResolvable ? (
										<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200 space-y-1">
											<div><strong>No Product Visual Reference:</strong></div>
											<div>This product has no media_id, image_url, or local_image_path. Generation is blocked. Please register product images in the Product Catalog first.</div>
										</div>
									) : null}
								</div>
							</Section>

							{/* Section 2: Character / Style References */}
							<Section step="2" title="Select Character & Style Reference">
								<div className="grid gap-4 md:grid-cols-2">
									<ReferenceField
										label="Avatar Reference (Required)"
										noun="avatar"
										assets={characterAssets}
										value={characterAssetId}
										onChange={setCharacterAssetId}
										emptyHint="No avatars in Library — create one in Avatar Registry"
										requiredMissing={characterMissing}
										onApprove={handleApproveAsset}
										approvingId={approvingId}
									/>
									<ReferenceField
										label="Style / Mood Reference (Required)"
										noun="style reference"
										assets={styleAssets}
										value={styleAssetId}
										onChange={setStyleAssetId}
										emptyHint="No style references in Library"
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
								</div>
							</Section>

							{/* Section 3: Optional Scene Reference */}
							<Section step="3" title="Select Scene Reference (Optional)">
								<ReferenceField
									label="Scene Context Reference"
									noun="scene reference"
									assets={sceneAssets}
									value={sceneAssetId}
									onChange={setSceneAssetId}
									emptyHint="No scene references in Library"
									requiredMissing={sceneMissing}
									onApprove={handleApproveAsset}
									approvingId={approvingId}
								/>
							</Section>
						</>
					) : (
						<>
							{/* Ingredients tab configuration */}
							<Section step="1" title="Select Ingredient Type">
								<div className="flex gap-2">
									{(["subject", "scene", "style"] as const).map((type) => (
										<button
											key={type}
											type="button"
											onClick={() => {
												setIngredientType(type);
												resetOutputForm();
											}}
											className={`flex-1 rounded-xl border py-2.5 text-xs font-bold uppercase tracking-wider transition-all cursor-pointer ${
												ingredientType === type
													? "border-blue-500 bg-blue-600/10 text-blue-400"
													: "border-slate-800 bg-slate-950 text-slate-400 hover:border-slate-700 hover:text-slate-200"
											}`}
										>
											{type === "subject" ? "Subject / Avatar" : type}
										</button>
									))}
								</div>
								<div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-3 text-[11px] text-slate-400">
									{ingredientType === "subject" && (
										<span>Creates a reusable avatar/character reference. Output role: <strong>CHARACTER_REFERENCE</strong>.</span>
									)}
									{ingredientType === "scene" && (
										<span>Creates a reusable scene/environment reference. Output role: <strong>SCENE_CONTEXT_REFERENCE</strong>.</span>
									)}
									{ingredientType === "style" && (
										<span>Creates a reusable visual style reference. Output role: <strong>STYLE_REFERENCE</strong>.</span>
									)}
								</div>
							</Section>
						</>
					)}

					{/* Section 4: Prompt Creator */}
					<Section step="4" title="Prompt Preview & Builder">
						<textarea
							value={prompt}
							onChange={(e) => setPrompt(e.target.value)}
							className="h-28 w-full rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-none"
							placeholder="Describe the image prompt here..."
						/>
						{activeTab === "frames" && (
							<button
								type="button"
								onClick={() => void handleCompilePrompt()}
								disabled={!selectedProduct || compiling}
								className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 transition-all disabled:opacity-40 cursor-pointer"
							>
								{compiling ? "Compiling…" : "⚡ Auto compile product prompt"}
							</button>
						)}
					</Section>

					{/* Section 5: Generation configuration & confirm trigger */}
					<Section step="5" title="Generate (Gated · Credit-spending)">
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
							<div>
								References Sent:{" "}
								<strong>
									{genResolution.mediaIds.length > 0
										? genResolution.mediaIds.join(", ")
										: "(none)"}
								</strong>
							</div>
							{genResolution.refs.length > 0 && (
								<ul className="list-disc pl-4 space-y-1 text-[11px] text-slate-400">
									{genResolution.refs.map((r, i) => (
										<li key={i}>
											{r.role}: {r.label} —{" "}
											{r.mediaId ? (
												<span className="text-emerald-400">Resolved ({r.mediaId})</span>
											) : (
												<span className="text-amber-400">No media ID (text reference only)</span>
											)}
										</li>
									))}
								</ul>
							)}
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
					<Section step="6" title="Register Output (Credit-free)">
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
							<select
								value={artifactMediaId}
								onChange={(e) => setArtifactMediaId(e.target.value)}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
							>
								<option value="">
									{artifacts.length === 0
										? "No finished image artifacts found"
										: "Select a finished image artifact…"}
								</option>
								{artifacts.map((a) => (
									<option key={a.media_id} value={a.media_id}>
										{a.media_id} {a.size_mb ? `(${a.size_mb}MB)` : ""}
									</option>
								))}
							</select>
						) : (
							<input
								type="file"
								accept="image/*"
								onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
								className="w-full text-xs text-slate-400 file:mr-3 file:rounded-xl file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-slate-200 file:cursor-pointer"
							/>
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
