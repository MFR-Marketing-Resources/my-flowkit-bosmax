import { ArrowRight, Check, Copy, X, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchCreativeAssets } from "../../api/creativeAssets";
import { handleAssetUpload } from "../../api/assets";
import {
	PRODUCT_ASSET_GENERATOR_PRESETS,
	getProductAssetGeneratorPreset,
} from "../product-asset-generator/presets";
import type {
	CreativeAsset,
	Product,
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
	WorkspacePromptPreviewResult,
} from "../../types";
import WorkspaceImageAssetSlot from "./WorkspaceImageAssetSlot";

// ── Model options (mirrors Google Vertex AI / Flow interface) ──
const IMG_MODELS = [
	{ value: "Nano Banana 2", label: "Nano Banana 2" },
	{ value: "Nano Banana Pro", label: "Nano Banana Pro" },
	{ value: "Imagen 4", label: "Imagen 4" },
];

interface IMGModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
	previewPackage?: WorkspacePromptPreviewResult | null;
	selectedProduct?: Product | null;
}

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

function toProductSubjectAsset(
	product: Product | null | undefined,
): UploadedAsset | null {
	if (!product) return null;
	const previewUrl =
		product.image_url ||
		product.rendered_img_src ||
		product.image_analysis?.image_url ||
		null;
	if (!previewUrl) return null;
	return {
		mediaId: product.media_id ?? null,
		fileName: product.product_display_name || product.raw_product_title,
		label: "Product remote image URL",
		previewUrl,
		downloadUrl: previewUrl,
		assetId: undefined,
		assetFingerprint: `product:${product.id}:${previewUrl}`,
		assetSource: "PRODUCT_IMAGE_URL",
		isDefaultPackageAsset: true,
		previewRenderableStatus: "READY",
		previewErrorDetail: null,
		localImagePathPresent: Boolean(product.local_image_path),
		remoteImageUrlPresent: true,
	};
}

function creativeAssetToUploadedAsset(asset: CreativeAsset): UploadedAsset {
	return {
		mediaId: null,
		fileName: asset.display_name,
		label: asset.semantic_role,
		previewUrl: asset.preview_url || undefined,
		downloadUrl: asset.preview_url || undefined,
		assetId: asset.asset_id,
		assetFingerprint: `creative:${asset.asset_id}`,
		assetSource: "CREATIVE_LIBRARY",
		isDefaultPackageAsset: false,
		previewRenderableStatus: "READY",
		previewErrorDetail: null,
		localImagePathPresent: false,
		remoteImageUrlPresent: Boolean(asset.preview_url),
	};
}

// ── Small asset picker chip for Auto mode ──────────────────────
function CLAssetPicker({
	label,
	description,
	assets,
	selectedId,
	onSelect,
	badge,
	onImageClick,
}: {
	label: string;
	description: string;
	assets: CreativeAsset[];
	selectedId: string;
	onSelect: (id: string) => void;
	badge?: string;
	onImageClick?: (url: string) => void;
}) {
	const selected = assets.find((a) => a.asset_id === selectedId) ?? null;
	return (
		<div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
			<div className="mb-2 flex items-center gap-2">
				<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-300">
					{label}
				</span>
				{badge ? (
					<span className="rounded-full border border-slate-600 bg-slate-900 px-2 py-0.5 text-[9px] text-slate-400">
						{badge}
					</span>
				) : null}
			</div>
			{selected ? (
				<div className="mb-2 flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-2 py-1.5">
					{selected.preview_url ? (
						<img
							src={selected.preview_url}
							alt={selected.display_name}
							className={`h-8 w-8 flex-shrink-0 rounded-md border border-slate-700 object-cover ${onImageClick ? "cursor-zoom-in" : ""}`}
							onClick={() => selected.preview_url && onImageClick?.(selected.preview_url)}
						/>
					) : null}
					<div className="min-w-0 flex-1">
						<div className="truncate text-[11px] font-semibold text-slate-100">
							{selected.display_name}
						</div>
						{selected.description ? (
							<div className="line-clamp-1 text-[10px] text-slate-400">
								{selected.description}
							</div>
						) : null}
					</div>
					<button
						type="button"
						onClick={() => onSelect("")}
						className="text-[10px] text-slate-500 hover:text-red-300"
					>
						✕
					</button>
				</div>
			) : null}
			<select
				value={selectedId}
				onChange={(e) => onSelect(e.target.value)}
				className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-200"
			>
				<option value="">— {description} —</option>
				{assets.map((a) => (
					<option key={a.asset_id} value={a.asset_id}>
						{a.display_name}
					</option>
				))}
			</select>
			{assets.length === 0 ? (
				<div className="mt-1 text-[10px] text-slate-500">
					No assets yet — upload in Creative Library.
				</div>
			) : null}
		</div>
	);
}

export default function IMGModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
	previewPackage = null,
	selectedProduct = null,
}: IMGModuleProps) {
	// ── Settings ─────────────────────────────────────────────────
	const [aspectRatio, setAspectRatio] = useState("9:16");
	const [model, setModel] = useState("Nano Banana 2");
	const [count, setCount] = useState(1);

	// ── Input mode ───────────────────────────────────────────────
	const [inputMode, setInputMode] = useState<"AUTO" | "MANUAL">("AUTO");

	// ── Creative Library assets for Auto mode ────────────────────
	const [clSubjectAssets, setClSubjectAssets] = useState<CreativeAsset[]>([]);
	const [clSceneAssets, setClSceneAssets] = useState<CreativeAsset[]>([]);
	const [clStyleAssets, setClStyleAssets] = useState<CreativeAsset[]>([]);
	const [selectedSubjectId, setSelectedSubjectId] = useState("");
	const [selectedSceneId, setSelectedSceneId] = useState("");
	const [selectedStyleId, setSelectedStyleId] = useState("");

	// ── Image asset slots (resolved for both modes) ──────────────
	const [subjectAsset, setSubjectAsset] = useState<UploadedAsset | null>(null);
	const [sceneAsset, setSceneAsset] = useState<UploadedAsset | null>(null);
	const [styleAsset, setStyleAsset] = useState<UploadedAsset | null>(null);

	// ── Prompt & preset ─────────────────────────────────────────
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [isUploading, setIsUploading] = useState(false);
	const [copied, setCopied] = useState(false);
	const [selectedPresetId, setSelectedPresetId] = useState("");
	const activePreset = useMemo(
		() => getProductAssetGeneratorPreset(selectedPresetId || null),
		[selectedPresetId],
	);

	// ── Lightbox ─────────────────────────────────────────────────
	const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

	const packagePromptText =
		workspacePackage?.prompt_text ||
		previewPackage?.final_compiled_prompt_text ||
		"";
	const packagePromptBlocks =
		workspacePackage?.prompt_blocks || previewPackage?.prompt_blocks || [];
	const hasApprovedPackage = Boolean(workspacePackage || previewPackage);

	// ── Fetch Creative Library assets ────────────────────────────
	useEffect(() => {
		fetchCreativeAssets({ semantic_role: "CHARACTER_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setClSubjectAssets(r.items))
			.catch(() => {});
		fetchCreativeAssets({ semantic_role: "SCENE_CONTEXT_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setClSceneAssets(r.items))
			.catch(() => {});
		fetchCreativeAssets({ semantic_role: "STYLE_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setClStyleAssets(r.items))
			.catch(() => {});
	}, []);

	// ── Auto mode: sync CL selections → asset slots ──────────────
	useEffect(() => {
		if (inputMode !== "AUTO") return;
		const found = clSubjectAssets.find((a) => a.asset_id === selectedSubjectId);
		setSubjectAsset(found ? creativeAssetToUploadedAsset(found) : toProductSubjectAsset(selectedProduct));
	}, [selectedSubjectId, clSubjectAssets, inputMode, selectedProduct]);

	useEffect(() => {
		if (inputMode !== "AUTO") return;
		const found = clSceneAssets.find((a) => a.asset_id === selectedSceneId);
		setSceneAsset(found ? creativeAssetToUploadedAsset(found) : null);
	}, [selectedSceneId, clSceneAssets, inputMode]);

	useEffect(() => {
		if (inputMode !== "AUTO") return;
		const found = clStyleAssets.find((a) => a.asset_id === selectedStyleId);
		setStyleAsset(found ? creativeAssetToUploadedAsset(found) : null);
	}, [selectedStyleId, clStyleAssets, inputMode]);

	// ── Package loading effects (existing logic) ──────────────────
	useEffect(() => {
		if (!workspacePackage || workspacePackage.mode !== "IMG") return;
		setManualPrompt(workspacePackage.prompt_text);
		setAspectRatio(workspacePackage.aspect_ratio || "9:16");
		setSubjectAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find((a) => a.slot_key === "subject"),
			),
		);
		setSceneAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find((a) => a.slot_key === "scene"),
			),
		);
		setStyleAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find((a) => a.slot_key === "style"),
			),
		);
		setIsManualOverride(false);
	}, [workspacePackage]);

	useEffect(() => {
		if (workspacePackage || !previewPackage || previewPackage.mode !== "IMG") return;
		setManualPrompt(previewPackage.final_compiled_prompt_text);
		setSubjectAsset(toProductSubjectAsset(selectedProduct));
		setSceneAsset(null);
		setStyleAsset(null);
		setIsManualOverride(false);
	}, [previewPackage, selectedProduct, workspacePackage]);

	// ── Handlers ─────────────────────────────────────────────────
	const handleFileChange = async (
		type: "subject" | "scene" | "style",
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
			setIsManualOverride(hasApprovedPackage);
		} catch {
			alert("Upload failed. Check if local agent is running.");
		} finally {
			setIsUploading(false);
		}
	};

	const handleExecute = () => {
		onExecute({
			prompt: manualPrompt,
			aspectRatio,
			model,
			count,
			refs: { subjectAsset, sceneAsset, styleAsset },
			product_id: workspacePackage?.product_id ?? selectedProduct?.id,
			prompt_package_snapshot_id: workspacePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				workspacePackage?.workspace_execution_package_id,
			prompt_fingerprint:
				workspacePackage?.prompt_fingerprint ?? previewPackage?.prompt_fingerprint,
			asset_fingerprints:
				workspacePackage?.request_lineage_payload.asset_fingerprints ?? [],
			request_lineage_payload: workspacePackage?.request_lineage_payload,
			mode: "IMG",
		});
	};

	const handleCopyPrompt = () => {
		if (!manualPrompt) return;
		navigator.clipboard.writeText(manualPrompt).then(() => {
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		});
	};

	// ─────────────────────────────────────────────────────────────
	return (
		<div className={`space-y-5 ${compact ? "" : ""}`}>

			{/* ── SETTINGS: Model + Aspect Ratio + Count ─────────── */}
			<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<div className="mb-4 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
					Settings
				</div>
				<div className="space-y-4">
					{/* Model */}
					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Model
						</div>
						<div className="flex flex-wrap gap-2">
							{IMG_MODELS.map((m) => (
								<button
									key={m.value}
									type="button"
									onClick={() => setModel(m.value)}
									className={`rounded-lg border px-4 py-2 text-[11px] font-semibold transition-all ${
										model === m.value
											? "border-blue-500 bg-blue-600/20 text-blue-300"
											: "border-slate-700 bg-slate-950 text-slate-400 hover:border-slate-600 hover:text-slate-300"
									}`}
								>
									{m.label}
								</button>
							))}
						</div>
					</div>

					<div className="grid gap-4 sm:grid-cols-2">
						{/* Aspect Ratio */}
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Aspect Ratio
							</div>
							<div className="grid grid-cols-5 gap-1.5">
								{["16:9", "4:3", "1:1", "3:4", "9:16"].map((ratio) => (
									<button
										type="button"
										key={ratio}
										onClick={() => setAspectRatio(ratio)}
										className={`rounded-lg border py-2 text-[9px] font-bold transition-all ${
											aspectRatio === ratio
												? "border-blue-500 bg-blue-600/20 text-blue-400"
												: "border-slate-700 bg-slate-950 text-slate-500 hover:border-slate-600"
										}`}
									>
										{ratio}
									</button>
								))}
							</div>
						</div>

						{/* Count */}
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Count
							</div>
							<div className="grid grid-cols-4 gap-1.5">
								{[1, 2, 3, 4].map((v) => (
									<button
										type="button"
										key={v}
										onClick={() => setCount(v)}
										className={`rounded-lg border py-2 text-[10px] font-bold transition-all ${
											count === v
												? "border-purple-500 bg-purple-600/20 text-purple-400"
												: "border-slate-700 bg-slate-950 text-slate-500 hover:border-slate-600"
										}`}
									>
										{v}x
									</button>
								))}
							</div>
						</div>
					</div>
				</div>
			</section>

			{/* ── STEP 1: IMAGE INPUTS ───────────────────────────── */}
			<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<div className="mb-4 flex items-center justify-between gap-3">
					<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
						1. Image Inputs (Subject / Scene / Style)
					</div>
					{/* Auto / Manual toggle */}
					<div className="flex rounded-lg border border-slate-700 bg-slate-950 p-0.5">
						<button
							type="button"
							onClick={() => setInputMode("AUTO")}
							className={`rounded-md px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] transition-colors ${
								inputMode === "AUTO"
									? "bg-blue-600 text-white"
									: "text-slate-400 hover:text-slate-200"
							}`}
						>
							Auto
						</button>
						<button
							type="button"
							onClick={() => setInputMode("MANUAL")}
							className={`rounded-md px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] transition-colors ${
								inputMode === "MANUAL"
									? "bg-blue-600 text-white"
									: "text-slate-400 hover:text-slate-200"
							}`}
						>
							Manual
						</button>
					</div>
				</div>

				{inputMode === "AUTO" ? (
					<div className="space-y-3">
						<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-2 text-[10px] text-blue-200">
							Auto mode — pilih dari Creative Library. Subject = avatar/character, Scene = background/environment, Style = visual style reference.
						</div>
						<div className="grid gap-3 sm:grid-cols-3">
							<CLAssetPicker
								label="Subject"
								description="Pick avatar / character"
								assets={clSubjectAssets}
								selectedId={selectedSubjectId}
								onSelect={setSelectedSubjectId}
								badge="CHARACTER_REFERENCE"
								onImageClick={setLightboxUrl}
							/>
							<CLAssetPicker
								label="Scene"
								description="Pick scene / background"
								assets={clSceneAssets}
								selectedId={selectedSceneId}
								onSelect={setSelectedSceneId}
								badge="SCENE_CONTEXT_REFERENCE"
								onImageClick={setLightboxUrl}
							/>
							<CLAssetPicker
								label="Style"
								description="Pick style reference"
								assets={clStyleAssets}
								selectedId={selectedStyleId}
								onSelect={setSelectedStyleId}
								badge="STYLE_REFERENCE"
								onImageClick={setLightboxUrl}
							/>
						</div>
						{/* Preview of resolved slots */}
						{(subjectAsset || sceneAsset || styleAsset) ? (
							<div className="mt-3 grid grid-cols-3 gap-3">
								{[
									{ asset: subjectAsset, title: "Subject" },
									{ asset: sceneAsset, title: "Scene" },
									{ asset: styleAsset, title: "Style" },
								].map(({ asset, title }) =>
									asset ? (
										<div key={title} className="space-y-1">
											<div className="text-[9px] uppercase tracking-[0.14em] text-slate-500">{title}</div>
											{asset.previewUrl ? (
												<div className="group relative">
													<img
														src={asset.previewUrl}
														alt={title}
														className="h-20 w-full cursor-zoom-in rounded-xl border border-slate-700 object-cover transition-opacity group-hover:opacity-80"
														onClick={() => setLightboxUrl(asset.previewUrl!)}
													/>
													<div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
														<ZoomIn size={20} className="text-white drop-shadow" />
													</div>
												</div>
											) : (
												<div className="flex h-20 items-center justify-center rounded-xl border border-slate-700 bg-slate-900 text-[10px] text-slate-500">
													{asset.fileName}
												</div>
											)}
										</div>
									) : null,
								)}
							</div>
						) : null}
					</div>
				) : (
					<div className="space-y-3">
						<div className="rounded-xl border border-slate-700 bg-slate-950/40 px-3 py-2 text-[10px] text-slate-400">
							Manual mode — upload terus gambar untuk setiap slot.
						</div>
						{hasApprovedPackage ? (
							<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[10px] text-emerald-100">
								Package loaded — product image auto-resolved as subject. Replace below if needed.
							</div>
						) : null}
						<div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-3">
							<WorkspaceImageAssetSlot
								key={subjectAsset?.assetFingerprint ?? subjectAsset?.previewUrl ?? "subject-empty"}
								title="Subject"
								description="Upload subject / avatar image"
								asset={subjectAsset}
								isUploading={isUploading}
								accentClassName="group-hover:bg-blue-500/10 group-hover:text-blue-400"
								uploadTitle="Upload subject reference"
								onFileChange={(e) => handleFileChange("subject", e)}
								onImageClick={setLightboxUrl}
							/>
							<WorkspaceImageAssetSlot
								key={sceneAsset?.assetFingerprint ?? sceneAsset?.previewUrl ?? "scene-empty"}
								title="Scene"
								description="Upload scene / background reference"
								asset={sceneAsset}
								isUploading={isUploading}
								accentClassName="group-hover:bg-purple-500/10 group-hover:text-purple-400"
								uploadTitle="Upload scene reference"
								onFileChange={(e) => handleFileChange("scene", e)}
								onImageClick={setLightboxUrl}
							/>
							<WorkspaceImageAssetSlot
								key={styleAsset?.assetFingerprint ?? styleAsset?.previewUrl ?? "style-empty"}
								title="Style"
								description="Upload style reference"
								asset={styleAsset}
								isUploading={isUploading}
								accentClassName="group-hover:bg-pink-500/10 group-hover:text-pink-400"
								uploadTitle="Upload style reference"
								onFileChange={(e) => handleFileChange("style", e)}
								onImageClick={setLightboxUrl}
							/>
						</div>
					</div>
				)}
			</section>

			{/* ── STEP 2: PROMPT ─────────────────────────────────── */}
			<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<div className="mb-4 flex items-center justify-between gap-3">
					<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
						2. Prompt &amp; Preset
					</div>
					{/* Copy to Prompt Bank button */}
					{manualPrompt ? (
						<button
							type="button"
							onClick={handleCopyPrompt}
							className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[10px] font-semibold transition-all ${
								copied
									? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
									: "border-slate-700 bg-slate-950 text-slate-400 hover:border-slate-500 hover:text-slate-200"
							}`}
						>
							{copied ? <Check size={11} /> : <Copy size={11} />}
							{copied ? "Copied!" : "Copy to Prompt Bank"}
						</button>
					) : null}
				</div>

				{/* Preset selector */}
				<div className="mb-4">
					<div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
						Preset Setting
					</div>
					<select
						value={selectedPresetId}
						onChange={(e) => setSelectedPresetId(e.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] text-slate-200 focus:border-blue-500 focus:outline-none"
					>
						<option value="">— No preset · tulis prompt manual —</option>
						{(["PRODUCT_ONLY", "HUMAN_PLUS_PRODUCT", "PRODUCT_PLUS_SCENE", "CONSISTENT_CHARACTER"] as const).map((family) => {
							const items = PRODUCT_ASSET_GENERATOR_PRESETS.filter((p) => p.family === family);
							if (!items.length) return null;
							const familyLabel: Record<string, string> = {
								PRODUCT_ONLY: "Product Only",
								HUMAN_PLUS_PRODUCT: "Human + Product",
								PRODUCT_PLUS_SCENE: "Product + Scene",
								CONSISTENT_CHARACTER: "Consistent Character",
							};
							return (
								<optgroup key={family} label={familyLabel[family]}>
									{items.map((p) => (
										<option key={p.id} value={p.id}>
											{p.label}
										</option>
									))}
								</optgroup>
							);
						})}
					</select>
					{activePreset ? (
						<div className="mt-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2 text-[10px] text-blue-200">
							<span className="font-semibold">{activePreset.label}</span>
							{" — "}{activePreset.description}
							{activePreset.requiredInputs.length > 0 ? (
								<div className="mt-1 text-slate-400">
									Required: {activePreset.requiredInputs.join(", ")}
								</div>
							) : null}
						</div>
					) : null}
				</div>

				{hasApprovedPackage ? (
					<div className="mb-3 grid gap-2">
						<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[10px] text-emerald-100">
							<span className="font-bold uppercase tracking-[0.12em]">Auto Package Baseline</span>
							{" — "}Package prompt loaded. Edit below to override for this run only.
						</div>
						{isManualOverride ? (
							<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-100">
								Manual override active.
							</div>
						) : null}
					</div>
				) : (
					<div className="mb-3 rounded-xl border border-slate-700 bg-slate-950/40 px-3 py-2 text-[10px] text-slate-400">
						No package loaded — tulis prompt manual di bawah.
					</div>
				)}

				{packagePromptBlocks && packagePromptBlocks.length > 1 ? (
					<div className="space-y-3">
						{packagePromptBlocks.map((block) => (
							<div key={block.block_index} className="space-y-1">
								<div className="flex items-center gap-2">
									<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
										Block {block.block_index} — {block.block_role}
									</span>
									<span className="text-[10px] text-slate-500">
										{block.duration_seconds}s · {block.shot_count} shot(s)
									</span>
								</div>
								<textarea
									className="h-40 w-full resize-none rounded-xl border border-slate-700 bg-slate-950 p-4 font-mono text-sm text-slate-300 outline-none transition-all"
									readOnly
									value={block.engine_prompt_text}
									onClick={(e) => (e.target as HTMLTextAreaElement).select()}
								/>
							</div>
						))}
					</div>
				) : (
					<textarea
						className="h-40 w-full resize-none rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-sm text-slate-300 outline-none transition-all focus:border-blue-500"
						placeholder="Tulis prompt di sini, atau load package di atas untuk auto-populate..."
						value={manualPrompt}
						onChange={(e) => {
							const next = e.target.value;
							setManualPrompt(next);
							setIsManualOverride(
								Boolean(packagePromptText) && next !== packagePromptText,
							);
						}}
					/>
				)}

				{manualPrompt ? (
					<div className="mt-2 text-[10px] text-slate-500">
						Copy prompt di atas → paste ke{" "}
						<span className="font-semibold text-slate-400">Prompt Handoff Bank</span>{" "}
						untuk simpan atau hantar ke production.
					</div>
				) : null}
			</section>

			{/* ── STEP 3: GENERATE ───────────────────────────────── */}
			<div>
				<button
					type="button"
					onClick={handleExecute}
					disabled={isExecuting || isUploading || !manualPrompt || !subjectAsset}
					className="flex w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 py-4 text-sm font-bold text-white shadow-xl shadow-blue-500/20 transition-all hover:scale-[1.02] active:scale-95 disabled:grayscale disabled:opacity-50"
				>
					{isUploading
						? "Uploading Assets..."
						: isExecuting
							? "Generating Images..."
							: "GENERATE IMAGES"}
					{!isExecuting && !isUploading && <ArrowRight size={18} />}
				</button>
				{!subjectAsset && !isExecuting ? (
					<div className="mt-2 text-center text-[10px] text-slate-500">
						⚠ Subject image diperlukan sebelum generate.
					</div>
				) : null}
				{!manualPrompt && !isExecuting ? (
					<div className="mt-1 text-center text-[10px] text-slate-500">
						⚠ Prompt diperlukan — load package atau tulis manual.
					</div>
				) : null}
			</div>

			{/* ── LIGHTBOX ───────────────────────────────────────── */}
			{lightboxUrl ? (
				<div
					className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm"
					onClick={() => setLightboxUrl(null)}
					onKeyDown={(e) => e.key === "Escape" && setLightboxUrl(null)}
					role="dialog"
					aria-modal="true"
					tabIndex={-1}
				>
					<img
						src={lightboxUrl}
						alt="Preview"
						className="max-h-[90vh] max-w-[90vw] rounded-2xl border border-slate-700 object-contain shadow-2xl"
						onClick={(e) => e.stopPropagation()}
					/>
					<button
						type="button"
						className="absolute right-4 top-4 rounded-full border border-slate-600 bg-slate-900 p-2 text-slate-300 transition-colors hover:bg-slate-800 hover:text-white"
						onClick={() => setLightboxUrl(null)}
					>
						<X size={16} />
					</button>
				</div>
			) : null}
		</div>
	);
}
