import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { archiveCreativeAsset, fetchCreativeAssets } from "../api/creativeAssets";
import { getCreativeSetupForProduct } from "../api/creativeIntelligence";
import {
	buildAvatarRegistryReferenceAssets,
	fetchAvatarRegistryPool,
	type AvatarRegistryPoolRow,
} from "../api/avatarRegistry";
import {
	compileImgFastlanePromptPreview,
	type ImageArtifact,
	type ImgAssetLane,
	type ImgFastlanePreset,
	type ImgFastlanePromptPreview,
	type ImgGenerationJob,
	deleteImageArtifact,
	fetchImageArtifacts,
	fetchImgAssetLanes,
	fetchImgFastlanePresets,
	pollImgGenerationJob,
	saveImgOutputToLibrary,
	startImgGeneration,
} from "../api/imgFactory";
import {
	buildExactSceneOnlyPrompt,
	composeExactFromPlate,
	resolveExactGenerationGate,
} from "../api/exactProductOutput";
import { useImageGenSettings } from "../api/imageGenSettings";
import {
	buildProviderProductReferenceAsset,
	fetchGroundedPayload,
	STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
} from "../api/productVisualGrounding";
import { fetchProductCatalog } from "../api/products";
import ApproveAssetModal from "../components/creative-library/ApproveAssetModal";
import {
	OperatorCockpit,
	QueueRow,
	ResolvedChip,
	WorkflowStep,
} from "../components/workflow";
import type { WorkflowStepStatus } from "../components/workflow";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import VisualAssetPicker from "../components/workspace/VisualAssetPicker";
import type { CreativeAsset, Product } from "../types";
import {
	buildFastlaneGenerationRequest,
	canApprove,
	isReusableAsset,
	resolveGenerationInputs,
} from "./imgCockpitLogic";

const GEN_NOT_FIRED = "NOT_FIRED_IN_SESSION";
const GEN_RUNTIME_UNVERIFIED = "EXTERNAL_RUNTIME_NOT_VERIFIED";
// Aspect ratios, counts and image models now come from the shared image-gen
// settings SSOT (useImageGenSettings) so every page holds the SAME options.

type TruthStatus = "UNVERIFIED" | "PASS" | "FAIL";
type ReviewDecision = "PENDING_REVIEW" | "APPROVED" | "REJECTED";
type OutputMode = "artifact" | "upload";

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
	return (
		// NOTE: no `backdrop-blur` here. backdrop-filter creates a stacking context,
		// which traps an open dropdown (SearchableProductSelect, z-50) *inside* this
		// section so it paints BEHIND the next section instead of overlaying it. The
		// blur is imperceptible over the solid dark page bg, so dropping it is free.
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
			<VisualAssetPicker
				emptyMessage={emptyHint}
				items={assets.map((asset) => ({
					value: asset.asset_id,
					title: asset.display_name,
					subtitle: asset.asset_id,
					previewUrl:
						asset.preview_url ??
						asset.download_url ??
						asset.remote_source_url,
					status: asset.review_status,
				}))}
				label={label}
				onChange={onChange}
				placeholder={assets.length === 0 ? emptyHint : "Select visual reference"}
				value={value}
			/>
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
	const imgGen = useImageGenSettings();
	// Deep-link wiring (RPA Production Studio IMG card): /assets/img-fastlane?product_id=…
	// lands here with the Studio's product pre-selected — same proven flow, no re-picking.
	const [searchParams] = useSearchParams();

	const [lanes, setLanes] = useState<ImgAssetLane[]>([]);
	const [presets, setPresets] = useState<ImgFastlanePreset[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [products, setProducts] = useState<Product[]>([]);
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [avatarRegistryPool, setAvatarRegistryPool] = useState<
		AvatarRegistryPoolRow[]
	>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	const [styleAssets, setStyleAssets] = useState<CreativeAsset[]>([]);

	const [characterAssetId, setCharacterAssetId] = useState("");
	const [sceneAssetId, setSceneAssetId] = useState("");
	// Scene Context registry (20 seeded scenes). Pick any scene as background TEXT
	// immediately — even before a scene image is generated. If the chosen scene has
	// a generated image, bind it as the scene image reference too.
	const [sceneRegistry, setSceneRegistry] = useState<
		{
			scene_code: string;
			scene_name: string;
			image_generated: boolean;
			generated_asset_id?: string | null;
			primary_cluster?: string | null;
			compatible_clusters?: string[];
		}[]
	>([]);
	const [sceneContextCode, setSceneContextCode] = useState("");
	// Style is optional and has no Frames picker (no style library yet), so it
	// stays empty; kept for the compile payload / ingredients lineage.
	const [styleAssetId] = useState("");
	const [approveTarget, setApproveTarget] = useState<CreativeAsset | null>(null);
	const [refreshing, setRefreshing] = useState(false);
	const [framePresetId, setFramePresetId] = useState("");
	const [advancedOverrideNotes, setAdvancedOverrideNotes] = useState("");
	const [creativeMode, setCreativeMode] = useState("");

	const [prompt, setPrompt] = useState("");
	const [promptCopied, setPromptCopied] = useState(false);
	const [compiledPreview, setCompiledPreview] =
		useState<ImgFastlanePromptPreview | null>(null);
	const [displayName, setDisplayName] = useState("");
	const [compiling, setCompiling] = useState(false);
	const [aspect, setAspect] = useState<string>("9:16");
	const [quantity, setQuantity] = useState<number>(1);
	const [imageModel, setImageModel] = useState<string>("Nano Banana 2");

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
			fetchImageArtifacts(50),
			fetch("/api/workspace/scene-context-registry/pool").then((r) => r.json()),
			fetchAvatarRegistryPool(),
		]);
		const [chars, scenes, styles, arts, scenePool, avatarPool] = results;
		if (chars.status === "fulfilled") setCharacterAssets(chars.value.items);
		if (scenes.status === "fulfilled") setSceneAssets(scenes.value.items);
		if (styles.status === "fulfilled") setStyleAssets(styles.value.items);
		if (arts.status === "fulfilled") setArtifacts(arts.value);
		if (scenePool.status === "fulfilled")
			setSceneRegistry(scenePool.value?.scenes ?? []);
		if (avatarPool.status === "fulfilled") setAvatarRegistryPool(avatarPool.value);
		if (results.some((r) => r.status === "rejected")) {
			setError("Failed to load reference assets from Library.");
		}
	}, []);

	const handlePickSceneContext = (code: string) => {
		setSceneContextCode(code);
		// If the chosen scene already has a generated image, bind it as the scene
		// image reference too; otherwise text-only (its background is injected into
		// the prompt so the scene still drives the generation).
		const scene = sceneRegistry.find((s) => s.scene_code === code);
		setSceneAssetId(scene?.generated_asset_id ?? "");
	};

	// Knowledge-driven scene pre-fill: on product-select, seed a cluster-appropriate
	// scene context (background) from the creative setup so the operator starts from
	// the right scene instead of empty. No cluster match leaves the manual pick.
	useEffect(() => {
		const pid = selectedProduct?.id;
		if (!pid) return;
		let active = true;
		void getCreativeSetupForProduct(pid)
			.then((setup) => {
				if (!active) return;
				const cluster = String(setup.cluster || "").trim().toLowerCase();
				if (!cluster) return;
				const match = sceneRegistry.find((s) => {
					const pc = String(s.primary_cluster || "").trim().toLowerCase();
					const compat = (s.compatible_clusters || []).map((c) =>
						String(c).trim().toLowerCase(),
					);
					return pc === cluster || compat.includes(cluster);
				});
				if (match?.scene_code) handlePickSceneContext(match.scene_code);
			})
			.catch(() => {});
		return () => {
			active = false;
		};
	}, [selectedProduct?.id]);

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

	// Studio deep-link: once the catalog is loaded, pre-select the product the
	// Studio sent us with (?product_id=…). Never overrides a manual selection.
	useEffect(() => {
		const pid = searchParams.get("product_id");
		if (!pid || selectedProduct) return;
		const hit = products.find((p) => p.id === pid);
		if (hit) setSelectedProduct(hit);
	}, [products, searchParams, selectedProduct]);

	// Automatically choose the correct lane based on selections.
	const lane = useMemo(() => {
		if (compiledPreview?.lane_id) {
			return lanes.find((item) => item.lane_id === compiledPreview.lane_id) ?? null;
		}
		const laneId = sceneAssetId ? "AVATAR_PRODUCT_SCENE_COMPOSITE" : "AVATAR_PRODUCT_COMPOSITE";
		return lanes.find((l) => l.lane_id === laneId) ?? null;
	}, [lanes, compiledPreview?.lane_id, sceneAssetId]);
	const avatarRegistryAssets = useMemo(
		() => buildAvatarRegistryReferenceAssets(avatarRegistryPool, characterAssets),
		[avatarRegistryPool, characterAssets],
	);

	const selectedCharacter = useMemo(
		() =>
			avatarRegistryAssets.find((a) => a.asset_id === characterAssetId) ?? null,
		[avatarRegistryAssets, characterAssetId],
	);
	useEffect(() => {
		if (
			characterAssetId &&
			!avatarRegistryAssets.some((asset) => asset.asset_id === characterAssetId)
		) {
			setCharacterAssetId("");
		}
	}, [avatarRegistryAssets, characterAssetId]);
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

	const framePresets = useMemo(
		() => presets.filter((preset) => preset.route === "FRAMES"),
		[presets],
	);

	useEffect(() => {
		if (!framePresets.length) return;
		// Universal frames flow: ALWAYS use the generic database-driven merge preset
		// (scene-aware). Product-specific presets (BOSMAX / MWCB) are never forced —
		// the prompt is compiled from whatever product's DB truth is selected, so it
		// works for ALL products, not a hardcoded few.
		const wantId = sceneAssetId
			? "GENERIC_FRAMES_AVATAR_PRODUCT_SCENE"
			: "GENERIC_FRAMES_AVATAR_PRODUCT";
		const universal =
			framePresets.find((preset) => preset.preset_id === wantId) ??
			framePresets.find((preset) =>
				preset.preset_id.startsWith("GENERIC_FRAMES"),
			) ??
			framePresets[0];
		setFramePresetId(universal?.preset_id ?? "");
	}, [framePresets, sceneAssetId]);

	const resolvedRefsPayload = useMemo(() => {
		const refs: Record<string, any> = {};
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
			refs.productAsset = buildProductAssetPayload(selectedProduct);
		}
		return refs;
	}, [
		approvedCharacter,
		approvedScene,
		approvedStyle,
		selectedProduct,
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

	const productMissing = Boolean(lane?.requires_product_id && !selectedProduct);
	const productVisualReferenceMissing = Boolean(lane?.requires_product_id && selectedProduct && !productResolvable);

	const compiledBlockers = compiledPreview?.blockers ?? [];
	const characterMissing = compiledBlockers.includes("AVATAR_REFERENCE_REQUIRED");
	// Style and scene are OPTIONAL context for the universal avatar+product merge —
	// they must never block Generate nor be shown as "required".
	const sceneMissing = false;
	const OPTIONAL_BLOCKERS = new Set([
		"STYLE_REFERENCE_REQUIRED",
		"SCENE_REFERENCE_REQUIRED",
		"SCENE_OR_STYLE_CONTEXT_REQUIRED",
	]);
	// Only real, missing inputs (product truth, avatar, resolvable refs) block
	// generation. Optional style/scene advisories are filtered out.
	const hardBlockers = compiledBlockers.filter(
		(blocker) => !OPTIONAL_BLOCKERS.has(blocker),
	);

	// Generation needs only: product (+ its visual truth) + avatar + a compiled
	// prompt. Missing style/scene never blocks.
	const generationBlocked =
		productMissing ||
		productVisualReferenceMissing ||
		characterMissing ||
		genResolution.blocked ||
		hardBlockers.length > 0 ||
		!prompt.trim();

	const hasRealOutput =
		outputMode === "artifact" ? Boolean(artifactMediaId) : Boolean(uploadFile);

	const isChecklistComplete =
		checklistOversized &&
		checklistPreserved &&
		checklistContext &&
		checklistClaims &&
		checklistSuitable;

	// Scale guard: requires all checks and checklist to PASS before approval is allowed.
	const scaleGuardFailed =
		reviewDecision === "APPROVED" && !isChecklistComplete;

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

	// Approving a selected reference requires explicit truth/safety attestation
	// (ApproveAssetModal) — the backend enforces APPROVAL_REQUIRES_ALL_TRUTH_PASS, so
	// a bare review_status flip would be rejected as a governance bypass.
	const handleApproveAsset = (asset: CreativeAsset) => {
		setError(null);
		setApproveTarget(asset);
	};

	const compileFastlanePreview = useCallback(async () => {
		const presetId = framePresetId;
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
				route: "FRAMES",
				product_id: selectedProduct?.id ?? null,
				character_reference_asset_id: characterAssetId || null,
				scene_reference_asset_id: sceneAssetId || null,
				style_reference_asset_id: styleAssetId || null,
				advanced_override_notes: advancedOverrideNotes || null,
				scene_context_code: sceneContextCode || null,
				creative_mode: creativeMode || null,
			});
			setCompiledPreview(preview);
			// Send + display the CLEAN engine brief (no internal routing ids), which
			// is portable verbatim to Flow / ChatGPT Image / Grok. The labeled
			// prompt_text is kept as the operator breakdown below.
			setPrompt(preview.engine_prompt_text || "");
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
		framePresetId,
		selectedProduct?.id,
		characterAssetId,
		sceneAssetId,
		styleAssetId,
		advancedOverrideNotes,
		sceneContextCode,
		creativeMode,
	]);

	useEffect(() => {
		if (!framePresetId) {
			setCompiledPreview(null);
			setPrompt("");
			return;
		}
		const handle = window.setTimeout(() => {
			void compileFastlanePreview();
		}, 150);
		return () => window.clearTimeout(handle);
	}, [compileFastlanePreview, framePresetId]);

	const handleCopyPrompt = async () => {
		if (!prompt.trim()) return;
		try {
			await navigator.clipboard.writeText(prompt);
			setPromptCopied(true);
			window.setTimeout(() => setPromptCopied(false), 1500);
		} catch {
			setError("Clipboard copy was blocked by the browser.");
		}
	};

	const handleConfirmedGenerate = async () => {
		setShowGenConfirm(false);
		setGenerating(true);
		setError(null);
		try {
			const productId = selectedProduct?.id ?? "";
			const gate = await resolveExactGenerationGate(productId);
			if (gate.mode === "blocked") {
				throw new Error(gate.message);
			}

			const hasAvatar = Boolean(characterAssetId || sceneAssetId);
			const isProductOnly = !hasAvatar && Boolean(framePresetId?.includes("PRODUCT_ONLY") || framePresetId?.includes("HERO"));

			let scenePrompt = prompt;
			let groundedProdAsset: ReturnType<typeof buildProviderProductReferenceAsset> = null;
			let useExactComposite = false;

			if (productId) {
				const grounded = await fetchGroundedPayload(productId, {
					prompt,
					lane_id: framePresetId,
					has_avatar: hasAvatar,
					is_product_only: isProductOnly,
				});

				if (grounded.selected_strategy === STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE && gate.mode === "exact") {
					useExactComposite = true;
					const scene = await buildExactSceneOnlyPrompt(productId, prompt);
					scenePrompt = scene.prompt;
				} else {
					scenePrompt = grounded.full_prompt;
					groundedProdAsset = buildProviderProductReferenceAsset(grounded);
				}
			}

			const genInput = buildFastlaneGenerationRequest({
				prompt: scenePrompt,
				resolvedRefsPayload: useExactComposite ? {} : resolvedRefsPayload,
				groundedProdAsset: useExactComposite ? null : groundedProdAsset,
				aspect,
				quantity,
				imageModel,
			});

			const { job_id } = await startImgGeneration(genInput);
			const job = await pollImgGenerationJob(job_id);
			setGenJob(job);
			if (job.status === "DONE" && job.media_id) {
				let mediaId = job.media_id;
				let sizeMb =
					typeof job.size_mb === "number" ? job.size_mb : null;
				if (useExactComposite && productId) {
					const finalOut = await composeExactFromPlate({
						product_id: productId,
						background_media_id: mediaId,
						lane:
							framePresetId?.includes("HERO")
								? "product_only_hero"
								: "studio",
						job_id,
					});
					mediaId = finalOut.media_id;
					sizeMb =
						typeof finalOut.size_mb === "number" ? finalOut.size_mb : sizeMb;
					setGenJob({
						...job,
						media_id: mediaId,
						url: finalOut.url,
						size_mb: sizeMb,
					});
				}
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
				source_character_asset_id: approvedCharacter?.asset_id || null,
				source_scene_asset_id: approvedScene?.asset_id || null,
				source_style_asset_id: approvedStyle?.asset_id || null,
				identity_lock_status: identityStatus,
				scale_truth_status: scaleStatus,
				claim_safety_status: claimStatus,
				review_status: reviewDecision,
				creative_mode: creativeMode || null,
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

	// V4 is the default for this standalone IMG lane. ?classic=1 is the
	// explicit rollback path while the classic branch remains available.
	const useV4 = searchParams.get("classic") !== "1";

	if (useV4) {
		const productStatus: WorkflowStepStatus = selectedProduct
			? productResolvable
				? "done"
				: "active"
			: "active";
		const referenceCount = [approvedCharacter, approvedScene, approvedStyle].filter(
			(Boolean),
		).length;
		const referenceStatus: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: characterMissing
				? "active"
				: "done";
		const promptStatus: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: prompt.trim()
				? "done"
				: "active";
		const setupStatus: WorkflowStepStatus = prompt.trim() ? "active" : "upcoming";
		const generateStatus: WorkflowStepStatus = genJob?.status === "DONE"
			? "done"
			: !generationBlocked
				? "active"
				: "upcoming";
		const outputStatus: WorkflowStepStatus = hasRealOutput ? "done" : "upcoming";
		const reviewStatus: WorkflowStepStatus = savedAsset
			? "done"
			: hasRealOutput
				? "active"
				: "upcoming";
		const saveStatus: WorkflowStepStatus = savedAsset
			? "done"
			: canSave
				? "active"
				: "upcoming";
		const approvedAsset =
			savedAsset?.review_status === "APPROVED" ? savedAsset : null;

		return (
			<>
				<div
					data-testid="img-fastlane-workflow"
					data-variant="v4"
					className="flex min-h-full min-w-0 flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-6"
				>
					<div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
						<div>
							<div className="flex items-center gap-2">
								<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
									IMG Fastlane
								</h2>
								<span className="rounded-full border border-v4-accent/40 bg-v4-accent/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-v4-accent-ink">
									V4
								</span>
							</div>
							<p className="text-sm text-slate-400">
								Guided image setup for clean F2V start-frame assets.
							</p>
						</div>
						<a
							href={`${location.pathname}?classic=1`}
							className="text-[11px] text-slate-500 underline decoration-dotted hover:text-slate-300"
						>
							Switch to classic view
						</a>
					</div>

					{error ? (
						<div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-200">
							{error}
						</div>
					) : null}

					<div className="flex min-h-0 flex-1 flex-col gap-5 lg:flex-row">
						<main className="min-w-0 space-y-3 pb-6 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:pr-1">
							<WorkflowStep
								index={1}
								title="Product"
								status={productStatus}
								summary={
									selectedProduct
										? `${selectedProduct.product_display_name}${productResolvable ? "" : " · visual reference missing"}`
										: undefined
								}
								helper="Choose the database product that anchors the frame and its visual truth."
							>
								<div className="space-y-3">
									<SearchableProductSelect
										products={products}
										selectedProduct={selectedProduct}
										onSelect={setSelectedProduct}
									/>
									{productMissing ? (
										<p className="text-[11px] text-amber-300/80">
											A product is required before the image gate can open.
										</p>
									) : null}
									{selectedProduct && !productResolvable ? (
										<div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
											<strong>No Product Visual Reference.</strong> The selected row has
											no media_id, image_url, or local_image_path.
										</div>
									) : null}
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={2}
								title="References"
								status={referenceStatus}
								summary={`${referenceCount} approved reference${referenceCount === 1 ? "" : "s"}`}
								helper="Bind approved avatar and optional scene context; unresolved references stay visible."
							>
								<div className="space-y-4">
									<ResolvedChip
										label="Reference binding"
										value={`${referenceCount} approved · avatar ${approvedCharacter ? "ready" : "required"}`}
										icon="🧷"
										auto={referenceCount === 0}
									/>
									<ReferenceField
											label="Avatar Registry — Approved Presenter"
											noun="avatar"
											assets={avatarRegistryAssets}
										value={characterAssetId}
										onChange={setCharacterAssetId}
											emptyHint="No approved Avatar Registry presenter assets"
										requiredMissing={characterMissing}
										onApprove={handleApproveAsset}
										approvingId={approveTarget?.asset_id ?? null}
									/>
									<div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/40 p-3">
										<label className="block space-y-1 text-[11px] text-slate-300">
											<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
												Scene Context Library · {sceneRegistry.length} scenes
											</span>
											<select
												value={sceneContextCode}
												onChange={(e) => handlePickSceneContext(e.target.value)}
												className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200"
											>
												<option value="">None (optional)</option>
												{sceneRegistry.map((scene) => (
													<option key={scene.scene_code} value={scene.scene_code}>
														{scene.scene_name}
														{scene.image_generated ? " · image ready" : " · text"}
													</option>
												))}
											</select>
										</label>
										<ReferenceField
											label="Generated scene image (optional)"
											noun="scene reference"
											assets={sceneAssets}
											value={sceneAssetId}
											onChange={setSceneAssetId}
											emptyHint="No generated scene images yet — optional"
											requiredMissing={sceneMissing}
											onApprove={handleApproveAsset}
											approvingId={approveTarget?.asset_id ?? null}
										/>
										<p className="text-[10px] text-slate-500">
											Scene context is prompt input; it never silently blocks this
											universal avatar + product frame flow.
										</p>
									</div>
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={3}
								title="Prompt"
								status={promptStatus}
								summary={compiledPreview?.preset_id ?? (prompt.trim() ? "Compiled brief" : undefined)}
								helper="The governed Fastlane compiler produces the portable engine brief."
							>
								<div className="space-y-3">
									<div className="grid gap-3 md:grid-cols-2">
										<label className="space-y-1 text-[11px] text-slate-300">
											<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
												Creative direction
											</span>
											<select
												value={creativeMode}
												onChange={(e) => setCreativeMode(e.target.value)}
												className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200"
											>
												<option value="">No governed mode</option>
												<option value="PGC_CAMPAIGN">PGC Campaign</option>
												<option value="UGC_AUTHENTIC">UGC Authentic</option>
												<option value="MODEL_AMBASSADOR">Model Ambassador</option>
												<option value="CLEAN_STUDIO_CATALOGUE">Clean Studio / Catalogue</option>
												<option value="LIFESTYLE_EDITORIAL">Lifestyle Editorial</option>
											</select>
										</label>
										<label className="space-y-1 text-[11px] text-slate-300">
											<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
												Override notes
											</span>
											<textarea
												value={advancedOverrideNotes}
												onChange={(e) => setAdvancedOverrideNotes(e.target.value)}
												className="h-20 w-full rounded-lg border border-slate-800 bg-slate-900 p-2 text-xs text-slate-200"
												placeholder="Optional compiler notes"
											/>
										</label>
									</div>
									<div className="flex items-center justify-between gap-2">
										<span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
											{compiling ? "Compiling preview…" : "Prompt preview auto-build is active."}
										</span>
										<button
											type="button"
											onClick={handleCopyPrompt}
											disabled={!prompt.trim()}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] font-semibold text-slate-200 disabled:opacity-40"
										>
											{promptCopied ? "Copied ✓" : "Copy"}
										</button>
									</div>
									<textarea
										value={prompt}
										readOnly
										className="h-44 w-full rounded-xl border border-slate-800 bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200"
										placeholder="Select a product and references to compile the portable prompt."
									/>
									{compiledPreview?.prompt_text ? (
										<details className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-[11px] text-slate-400">
											<summary className="cursor-pointer font-semibold uppercase tracking-[0.14em] text-slate-500">
												Structured breakdown
											</summary>
											<pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-relaxed">
												{compiledPreview.prompt_text}
											</pre>
										</details>
									) : null}
									{compiledPreview?.reference_map?.length ? (
										<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-[11px] text-slate-400">
											<div className="mb-1 font-semibold uppercase tracking-[0.14em] text-slate-500">
												Reference map
											</div>
											{compiledPreview.reference_map.map((line) => (
												<div key={line}>{line}</div>
											))}
										</div>
									) : null}
									{hardBlockers.length ? (
										<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] text-amber-100">
											<strong>Fastlane blockers</strong>
											{hardBlockers.map((blocker) => (
												<div key={blocker}>{blocker}</div>
											))}
										</div>
									) : null}
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={4}
								title="Image setup"
								status={setupStatus}
								summary={`${aspect} · ${quantity} image${quantity === 1 ? "" : "s"} · ${imageModel}`}
								helper="Images use count; the selected aspect and model stay in the prepared payload."
							>
								<div className="space-y-3">
									<div className="grid gap-3 sm:grid-cols-3">
										<label className="space-y-1 text-[11px] text-slate-300">
											<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">Aspect</span>
											<select
												value={aspect}
												onChange={(e) => setAspect(e.target.value)}
												className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200"
											>
												{imgGen.aspect_options.map((option) => (
													<option key={option} value={option}>{option}</option>
												))}
											</select>
										</label>
										<label className="space-y-1 text-[11px] text-slate-300">
											<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">Count</span>
											<input
												type="number"
												min="1"
												max="4"
												value={quantity}
												onChange={(e) => setQuantity(Math.max(1, Math.min(4, parseInt(e.target.value) || 1)))}
												className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200"
											/>
										</label>
										<label className="space-y-1 text-[11px] text-slate-300">
											<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">Image model</span>
											<select
												value={imageModel}
												onChange={(e) => setImageModel(e.target.value)}
												className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200"
											>
												{imgGen.models.map((model) => (
													<option key={model.label} value={model.label}>
														{model.label}{model.pending ? " (id pending)" : ""}
													</option>
												))}
											</select>
										</label>
									</div>
									<details className="mt-2">
										<summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-300">
											Technical payload
										</summary>
										<pre className="mt-2 max-h-48 overflow-auto rounded-xl border border-slate-800 bg-slate-950/60 p-3 font-mono text-[10px] text-slate-400">
											{JSON.stringify({ aspect, count: quantity, image_model: imageModel, refs: resolvedRefsPayload }, null, 2)}
										</pre>
									</details>
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={5}
								title="Generate image"
								status={generateStatus}
								summary={genJob?.status ?? "Manual confirmation required"}
								helper="Image generation is credit-free (only video costs credits); it never fires without explicit confirmation."
							>
								<div className="space-y-3">
									<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
										Live generation is still behind the human confirmation gate. Build
										status: <strong>{GEN_NOT_FIRED}</strong> · <strong>{GEN_RUNTIME_UNVERIFIED}</strong>.
									</div>
									<button
										type="button"
										onClick={() => setShowGenConfirm(true)}
										disabled={!prompt.trim() || generating || generationBlocked}
										className="w-full rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-[12px] font-bold text-rose-100 disabled:opacity-40"
									>
										{generating ? "Generating image…" : "Generate image · gated"}
									</button>
									{genJob && genJob.status === "DONE" && genJob.media_id ? (
										<div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
											<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
												Hasil Terkini
											</div>
											<img
												src={`/api/flow/retrieved/${encodeURIComponent(genJob.media_id)}`}
												alt="Hasil generate terkini"
												loading="lazy"
												className="w-full max-w-[220px] rounded-lg border border-slate-800 bg-black object-contain"
											/>
											<p className="text-[10px] text-slate-500">
												Kualiti tak memuaskan? Regenerate untuk cuba lagi — imej PERCUMA (hanya video guna kredit) — atau padam imej ini.
											</p>
											<div className="flex flex-wrap gap-2">
												<button
													type="button"
													onClick={() => setShowGenConfirm(true)}
													disabled={generating || generationBlocked}
													className="rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-[11px] font-bold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
												>
													🔄 Regenerate
												</button>
												<button
													type="button"
													onClick={() => void handleSave()}
													disabled={!canSave}
													className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-bold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
												>
													💾 Simpan ke Library
												</button>
												<button
													type="button"
													onClick={async () => {
														const mid = genJob.media_id;
														if (!mid) return;
														if (
															!window.confirm(
																"Padam imej ini? Creative Asset yang sudah disimpan tidak terjejas.",
															)
														)
															return;
														try {
															await deleteImageArtifact(mid);
															setArtifacts((prev) =>
																prev.filter((a) => a.media_id !== mid),
															);
															setGenJob(null);
														} catch (err) {
															setError(
																err instanceof Error
																	? err.message
																	: "Gagal padam imej artifact",
															);
														}
													}}
													className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-[11px] font-bold text-rose-200 hover:bg-rose-500/20"
												>
													🗑 Padam
												</button>
											</div>
										</div>
									) : null}
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={6}
								title="Register output"
								status={outputStatus}
								summary={hasRealOutput ? "Output selected" : "No output selected"}
								helper="Attach a finished artifact or upload for review without firing generation."
							>
								<div className="space-y-3">
									<div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950 p-0.5 text-[10px] font-bold uppercase tracking-[0.14em]">
										<button type="button" onClick={() => setOutputMode("artifact")} className={`flex-1 rounded-lg px-3 py-1.5 ${outputMode === "artifact" ? "bg-v4-accent text-slate-950" : "text-slate-400"}`}>
											Finished artifact
										</button>
										<button type="button" onClick={() => setOutputMode("upload")} className={`flex-1 rounded-lg px-3 py-1.5 ${outputMode === "upload" ? "bg-v4-accent text-slate-950" : "text-slate-400"}`}>
											Upload file
										</button>
									</div>
									{outputMode === "artifact" ? (
										<div className="space-y-2">
											<select value={artifactMediaId} onChange={(e) => setArtifactMediaId(e.target.value)} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200">
												<option value="">{artifacts.length ? "Select a finished image artifact…" : "No finished image artifacts yet"}</option>
												{artifacts.map((artifact) => <option key={artifact.media_id} value={artifact.media_id}>{artifact.media_id}</option>)}
											</select>
											<VisualAssetPicker
												emptyMessage="No finished image artifacts yet."
												items={artifacts.map((artifact) => ({ value: artifact.media_id, title: artifact.mode || "Generated image", subtitle: artifact.media_id, previewUrl: `/api/flow/retrieved/${encodeURIComponent(artifact.media_id)}`, status: "FINISHED" }))}
												label="Finished artifact"
												onChange={setArtifactMediaId}
												placeholder="Select a finished image artifact"
												value={artifactMediaId}
											/>
										</div>
									) : (
										<input type="file" accept="image/*" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} className="w-full text-[11px] text-slate-400 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-slate-200" />
									)}
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={7}
								title="Review & approval"
								status={reviewStatus}
								summary={reviewDecision}
								helper="All truth checks and the scale guard must pass before APPROVED can be saved."
							>
								<div className="space-y-3">
									{selectedProduct ? (
										<div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/40 p-3">
											<div className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Product scale truth guard</div>
											{([
												["Product is realistic handheld/small scale", checklistOversized, setChecklistOversized],
												["Label, cap, and body are preserved", checklistPreserved, setChecklistPreserved],
												["Product scale matches hand/body context", checklistContext, setChecklistContext],
												["No misleading claims or text added", checklistClaims, setChecklistClaims],
												["Suitable as a clean F2V start frame", checklistSuitable, setChecklistSuitable],
											] as const).map(([label, checked, setChecked]) => (
												<label key={String(label)} className="flex items-start gap-2 text-[11px] text-slate-300">
													<input type="checkbox" checked={Boolean(checked)} onChange={(e) => (setChecked as (value: boolean) => void)(e.target.checked)} className="mt-0.5" />
													<span>{label}</span>
												</label>
											))}
										</div>
									) : null}
									<div className="grid gap-3 sm:grid-cols-3">
										{([["Identity", identityStatus, setIdentityStatus], ["Scale", scaleStatus, setScaleStatus], ["Claims", claimStatus, setClaimStatus]] as const).map(([label, value, setValue]) => (
											<label key={label} className="space-y-1 text-[11px] text-slate-300">
												<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</span>
												<select value={value} onChange={(e) => setValue(e.target.value as TruthStatus)} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-2 py-2 text-xs text-slate-200">
													<option value="UNVERIFIED">UNVERIFIED</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option>
												</select>
											</label>
										))}
									</div>
									<div className="flex flex-wrap gap-2">
										{(["PENDING_REVIEW", "APPROVED", "REJECTED"] as const).map((decision) => (
											<button key={decision} type="button" onClick={() => setReviewDecision(decision)} className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold ${reviewDecision === decision ? "border-v4-accent bg-v4-accent/10 text-v4-accent-ink" : "border-slate-700 text-slate-400"}`}>
												{decision}
											</button>
										))}
									</div>
									{approvalBlocked ? <p className="text-[11px] text-amber-300/80">APPROVED is blocked until all truth checks and the scale checklist pass.</p> : null}
								</div>
							</WorkflowStep>

							<WorkflowStep
								index={8}
								title="Save to Creative Library"
								status={saveStatus}
								summary={savedAsset?.display_name ?? (canSave ? "Ready to save" : "Waiting for approved output")}
								helper="Persist the reviewed asset and expose its approved reuse modes."
							>
								<div className="space-y-3">
									<input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200" placeholder="e.g. Product + Avatar · Start Frame A" />
									<button type="button" onClick={() => void handleSave()} disabled={!canSave} className="w-full rounded-xl bg-gradient-to-br from-v4-accent to-v4-auto px-4 py-3 text-[12px] font-bold text-slate-950 disabled:opacity-40">
										{saving ? "Saving…" : "Save approved asset"}
									</button>
									{savedAsset ? <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-100">Saved <strong>{savedAsset.display_name}</strong> · {savedAsset.review_status}</div> : null}
								</div>
							</WorkflowStep>
						</main>

						<aside className="w-full lg:w-80 lg:flex-none">
							<div className="lg:sticky lg:top-4">
								<OperatorCockpit
									laneLabel="IMG Fastlane · Composite Frames"
									status={{
										label: generating ? "Working" : approvedAsset ? "Approved" : selectedProduct ? "Ready" : "Idle",
										state: generating ? "running" : approvedAsset ? "done" : selectedProduct ? "online" : "idle",
									}}
									product={selectedProduct ? { name: selectedProduct.product_display_name, sub: selectedProduct.product_short_name } : undefined}
									plan={[
										{ k: "Mode", v: "IMG", mono: true },
										{ k: "Aspect", v: aspect, mono: true },
										{ k: "Count", v: quantity, mono: true },
										{ k: "References", v: `${referenceCount} approved`, tone: referenceCount ? "good" : "muted" },
										{ k: "Review", v: approvedAsset ? "Approved asset" : "Pending approval", tone: approvedAsset ? "good" : "muted" },
									]}
									queueTitle="Output queue"
									generate={{
										label: "Generate image · gated",
										disabled: !prompt.trim() || generating || generationBlocked,
										loading: generating,
										onClick: () => setShowGenConfirm(true),
										note: "manual confirmation required · no auto-fire",
									}}
									debugLabel="IMG Fastlane diagnostics"
									debug={<div className="space-y-1"><div>lane {lane?.lane_id ?? "—"}</div><div>refs {referenceCount} approved</div><div>{GEN_NOT_FIRED} · {GEN_RUNTIME_UNVERIFIED}</div></div>}
								>
									<QueueRow title="Image output" sub={`${quantity} image${quantity === 1 ? "" : "s"} · ${aspect}`} status={genJob?.status === "DONE" ? "done" : "queued"} />
									<QueueRow title="Approved asset" sub={approvedAsset?.display_name ?? "Review after registration"} status={approvedAsset ? "done" : "queued"} />
								</OperatorCockpit>
							</div>
						</aside>
					</div>
				</div>

				<ApproveAssetModal
					asset={approveTarget}
					open={approveTarget !== null}
					onCancel={() => setApproveTarget(null)}
					onApproved={() => {
						setApproveTarget(null);
						void loadReferences();
					}}
				/>

				{showGenConfirm ? (
					<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-[2px]">
						<div className="max-w-md w-full rounded-2xl border border-rose-500/40 bg-slate-950 p-6 space-y-4 shadow-2xl">
							<div className="text-sm font-bold text-rose-100 uppercase tracking-wider">Confirm Image Generation</div>
							<div className="text-xs text-slate-300 space-y-2"><p>This fires the real image generation lane. It stays behind this explicit confirmation and is not auto-fired.</p><p>Build status: <strong>{GEN_NOT_FIRED}</strong> · <strong>{GEN_RUNTIME_UNVERIFIED}</strong>.</p></div>
							<div className="flex justify-end gap-3 pt-2"><button type="button" onClick={() => setShowGenConfirm(false)} className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-300">Cancel</button><button type="button" onClick={() => void handleConfirmedGenerate()} className="rounded-xl border border-rose-500/40 bg-rose-500/20 px-4 py-2 text-xs font-bold text-rose-100">Confirm &amp; Generate</button></div>
						</div>
					</div>
				) : null}
			</>
		);
	}

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6 max-w-6xl mx-auto">
			<header className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-xl shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
				<div>
					<h2 className="text-lg font-bold text-white tracking-wide">IMG Fastlane</h2>
					<p className="mt-1 text-xs text-slate-400">
						Fast generation and registration of clean F2V Start Frames.
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

			{/* Single flow: Composite Frames (F2V) */}
			<div className="flex border-b border-slate-800">
				<div className="px-6 py-3 text-xs font-bold uppercase tracking-wider border-b-2 border-blue-500 text-blue-400 bg-blue-500/5">
					Composite Frames (F2V)
				</div>
			</div>

			<div className="grid gap-6 lg:grid-cols-12">
				{/* Left Column: Configurations */}
				<div className="lg:col-span-7 space-y-6">
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
											Composite Frames (F2V) blocks generation until a database product is selected.
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

							{/* Template Preset removed: the frames flow is universal. The prompt is
							    compiled from the selected product's DB truth + avatar via the generic
							    scale-lock merge preset (chosen automatically), so it works for ANY
							    product without picking a preset. */}

							<Section step="2" title="Select Avatar (required)">
								{/* Style reference field removed: there are no STYLE_REFERENCE
								    records and no way to create one in this flow, so the picker was
								    a dead/misleading field. Style stays optional and is simply not
								    surfaced until a real style library exists. */}
								<ReferenceField
									label="Avatar Registry — Approved Presenter"
									noun="avatar"
									assets={avatarRegistryAssets}
									value={characterAssetId}
									onChange={setCharacterAssetId}
									emptyHint="No approved Avatar Registry presenter assets"
									requiredMissing={characterMissing}
									onApprove={handleApproveAsset}
									approvingId={approveTarget?.asset_id ?? null}
								/>
								<div className="mt-2 flex gap-2">
									<a
										href="/assets/avatar-registry?from=/assets/img-fastlane"
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

							<Section step="3" title="Select Scene (optional)">
								<div className="space-y-2">
									{/* Scene Context Library — pick any of the 20 seeded scenes.
									    Its background is injected into the prompt immediately (text),
									    even before a scene image is generated. */}
									<label className="block text-[11px] text-slate-300 space-y-1">
										<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
											Scene Context Library — {sceneRegistry.length} scenes
										</span>
										<select
											value={sceneContextCode}
											onChange={(e) => handlePickSceneContext(e.target.value)}
											className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
										>
											<option value="">None (optional)</option>
											{sceneRegistry.map((s) => (
												<option key={s.scene_code} value={s.scene_code}>
													{s.scene_name}
													{s.image_generated ? " · image ready" : " · text"}
												</option>
											))}
										</select>
									</label>
									<VisualAssetPicker
										items={sceneRegistry.map((scene) => {
											const asset = sceneAssets.find(
												(candidate) =>
													candidate.asset_id === scene.generated_asset_id,
											);
											return {
												value: scene.scene_code,
												title: scene.scene_name,
												subtitle: scene.scene_code,
												previewUrl:
													asset?.preview_url ??
													asset?.download_url ??
													asset?.remote_source_url,
												status: scene.image_generated
													? "IMAGE READY"
													: "TEXT ONLY",
											};
										})}
										label="Scene Context Library"
										onChange={handlePickSceneContext}
										placeholder="Select scene context"
										value={sceneContextCode}
									/>
									<p className="text-[10px] text-slate-500">
										Pick any scene — its background is injected into the prompt
										immediately (no image needed). Scenes with a generated image
										are also bound as a scene reference. Generate images in the
										Scene Registry page. Never required to generate.
									</p>
									<ReferenceField
										label="Or pick a specific generated scene image"
										noun="scene reference"
										assets={sceneAssets}
										value={sceneAssetId}
										onChange={setSceneAssetId}
										emptyHint="No generated scene images yet — optional"
										requiredMissing={sceneMissing}
										onApprove={handleApproveAsset}
										approvingId={approveTarget?.asset_id ?? null}
									/>
								</div>
							</Section>

					{/* Section 4: Prompt Creator */}
					<Section step="4" title="Final Prompt → Google Flow">
						<div className="grid gap-4 md:grid-cols-2">
							<label className="block text-[11px] text-slate-300 space-y-1">
								<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Creative Direction optional
								</span>
								<select value={creativeMode} onChange={(event) => setCreativeMode(event.target.value)} className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-slate-200">
									<option value="">No governed mode (legacy)</option>
									<option value="PGC_CAMPAIGN">PGC Campaign</option>
									<option value="UGC_AUTHENTIC">UGC Authentic</option>
									<option value="MODEL_AMBASSADOR">Model Ambassador</option>
									<option value="CLEAN_STUDIO_CATALOGUE">Clean Studio / Clean Catalogue</option>
									<option value="LIFESTYLE_EDITORIAL">Lifestyle Editorial</option>
								</select>
							</label>
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
						<div className="flex items-center justify-between gap-2">
							<span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Final prompt → Flow / ChatGPT / Grok
								<span className="ml-2 normal-case tracking-normal text-slate-500">
									(portable brief — exact text sent on Generate; paste-ready for any image engine)
								</span>
							</span>
							<button
								type="button"
								onClick={handleCopyPrompt}
								disabled={!prompt.trim()}
								className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] font-semibold text-slate-200 hover:border-blue-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
							>
								{promptCopied ? "Copied ✓" : "Copy"}
							</button>
						</div>
						<textarea
							value={prompt}
							readOnly
							className="h-64 w-full rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 font-mono leading-relaxed focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-y overflow-auto"
							placeholder="The portable prompt sent to the image engine appears here after selecting a preset and any required database truth."
						/>
						{compiledPreview?.prompt_text ? (
							<details className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-400">
								<summary className="cursor-pointer font-semibold uppercase tracking-[0.14em] text-slate-500">
									Structured breakdown (operator reference — not sent to the engine)
								</summary>
								<pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-slate-400">
									{compiledPreview.prompt_text}
								</pre>
							</details>
						) : null}
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
						{hardBlockers.length ? (
							<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] text-amber-100 space-y-1">
								<div className="font-semibold uppercase tracking-[0.14em] text-amber-200">
									Fastlane Blockers
								</div>
								{hardBlockers.map((blocker) => (
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
					<Section step="5" title="Generate Image (Avatar + Product) · Credit-free">
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
									{imgGen.aspect_options.map((a) => (
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
							<label className="block text-[11px] text-slate-300 space-y-1">
								<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
									Image Model
								</span>
								<select
									value={imageModel}
									onChange={(e) => setImageModel(e.target.value)}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none"
								>
									{imgGen.models.map((m) => (
										<option key={m.label} value={m.label}>
											{m.label}
											{m.pending ? " (id pending)" : ""}
										</option>
									))}
								</select>
							</label>
						</div>
						{imgGen.models.find((m) => m.label === imageModel)?.pending ? (
							<p className="text-[10px] text-amber-300/80">
								{imageModel}: internal model id not configured yet — generation fails
								closed until it's set in models.json (never a wrong-model fallback).
							</p>
						) : null}

						{/* Live Payload Preview */}
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-xs text-slate-300 space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
								Generate Payload Preview
							</div>
							<div>
								Aspect: <strong>{aspect}</strong> | Count: <strong>{quantity}</strong>
							</div>
							<div className="space-y-1">
								<details>
									<summary className="cursor-pointer text-[10px] font-semibold text-slate-500 hover:text-slate-300">refs payload</summary>
									<pre className="mt-1 max-h-40 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-2 font-mono text-[10px] text-slate-400">
										{JSON.stringify(resolvedRefsPayload, null, 2)}
									</pre>
								</details>
							</div>
						</div>

						<button
							type="button"
							onClick={() => setShowGenConfirm(true)}
							disabled={!prompt.trim() || generating || generationBlocked}
							className="rounded-xl border border-blue-500/40 bg-blue-500/10 px-5 py-2.5 text-xs font-bold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40 transition-all w-full cursor-pointer"
						>
							{generating ? "Generating image…" : "Generate Image (Avatar + Product) — credit-free"}
						</button>
						{genJob && (
							<div className="mt-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3 space-y-3">
								<div className="text-xs text-slate-300">
									Job Status: <strong>{genJob.status}</strong>
									{genJob.media_id ? ` · ${genJob.media_id}` : ""}
								</div>
								{genJob.status === "DONE" && genJob.media_id ? (
									<div className="space-y-2">
										<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
											Hasil Terkini
										</div>
										<img
											src={`/api/flow/retrieved/${encodeURIComponent(genJob.media_id)}`}
											alt="Hasil generate terkini"
											loading="lazy"
											className="w-full max-w-[220px] rounded-lg border border-slate-800 bg-black object-contain"
										/>
										<p className="text-[10px] text-slate-500">
											Kualiti tak memuaskan? Regenerate untuk cuba lagi — imej PERCUMA (hanya video guna kredit) — atau padam imej ini.
										</p>
										<div className="flex flex-wrap gap-2">
											<button
												type="button"
												onClick={() => setShowGenConfirm(true)}
												disabled={generating || generationBlocked}
												className="rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-[11px] font-bold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
											>
												🔄 Regenerate
											</button>
											<button
												type="button"
												onClick={() => void handleSave()}
												disabled={!canSave}
												className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-bold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
											>
												💾 Simpan ke Library
											</button>
											<button
												type="button"
												onClick={async () => {
													const mid = genJob.media_id;
													if (!mid) return;
													if (
														!window.confirm(
															"Padam imej ini? Creative Asset yang sudah disimpan tidak terjejas.",
														)
													)
														return;
													try {
														await deleteImageArtifact(mid);
														setArtifacts((prev) =>
															prev.filter((a) => a.media_id !== mid),
														);
														setGenJob(null);
													} catch (err) {
														setError(
															err instanceof Error
																? err.message
																: "Gagal padam imej artifact",
														);
													}
												}}
												className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-[11px] font-bold text-rose-200 hover:bg-rose-500/20"
											>
												🗑 Padam
											</button>
										</div>
									</div>
								) : null}
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
									<VisualAssetPicker
										emptyMessage="No finished image artifacts found."
										items={artifacts.map((artifact) => ({
											value: artifact.media_id,
											title: artifact.mode || "Generated image",
											subtitle: artifact.media_id,
											previewUrl: `/api/flow/retrieved/${encodeURIComponent(
												artifact.media_id,
											)}`,
											status: artifact.size_mb
												? `${artifact.size_mb}MB`
												: "FINISHED",
										}))}
										label="Finished Artifact"
										onChange={setArtifactMediaId}
										placeholder="Select a finished image artifact"
										value={artifactMediaId}
									/>
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
					{selectedProduct && (
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
					<Section step={selectedProduct ? "8" : "7"} title="Review & Approval">
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
					<Section step={selectedProduct ? "9" : "8"} title="Save to Creative Library">
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

			<ApproveAssetModal
				asset={approveTarget}
				open={approveTarget !== null}
				onCancel={() => setApproveTarget(null)}
				onApproved={() => {
					setApproveTarget(null);
					void loadReferences();
				}}
			/>

			{/* live confirmation modal */}
			{showGenConfirm && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-[2px]">
					<div className="max-w-md w-full rounded-2xl border border-blue-500/40 bg-slate-950 p-6 space-y-4 shadow-2xl">
						<div className="text-sm font-bold text-blue-200 uppercase tracking-wider">
							Confirm Image Generation
						</div>
						<div className="text-xs text-slate-300 space-y-2">
							<p>
								This fires a real avatar + product image generation on Google Flow.{" "}
								<strong>Image generation is credit-free</strong> — only video
								generations consume credits.
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
								className="rounded-xl border border-blue-500/40 bg-blue-500/20 px-4 py-2 text-xs font-bold text-blue-100 hover:bg-blue-500/30 cursor-pointer"
							>
								Confirm &amp; Generate
							</button>
						</div>
					</div>
				</div>
			)}
		</div>
	);
}
