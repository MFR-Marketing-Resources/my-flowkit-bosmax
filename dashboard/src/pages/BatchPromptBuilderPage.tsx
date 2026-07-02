import {
	AlertTriangle,
	CheckCircle,
	Loader2,
	RefreshCw,
	Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchAPI } from "../api/client";
import { fetchCreativeAssets } from "../api/creativeAssets";
import { fetchProductCatalog } from "../api/products";
import type {
	BatchLogicalMode,
	BatchRunStatus,
	BatchVariationStrategy,
} from "../api/productionQueue";
import { getBatchRun, startBatchPrompts } from "../api/productionQueue";
import { ProductPicker } from "../components/batches/ProductPicker";
import type { CreativeAsset, Product } from "../types";

// BATCH PROMPT BUILDER — Prompt-generation only. Builds a batch of
// generation packages (prompts) into the Prompt Queue. NO video
// generation happens here and NO Google Flow credits are spent.
// Production execution lives in the Production Queue page.

const MODE_CARDS: Array<{
	id: BatchLogicalMode;
	label: string;
	description: string;
	activeClass: string;
}> = [
	{
		id: "T2V",
		label: "T2V",
		description: "Text-only video prompt — no image slots",
		activeClass: "border-blue-400/60 bg-blue-500/10",
	},
	{
		id: "HYBRID",
		label: "HYBRID",
		description: "Product image anchor + AI presenter from Avatar Registry",
		activeClass: "border-cyan-400/60 bg-cyan-500/10",
	},
	{
		id: "F2V",
		label: "F2V",
		description: "One finished frame is the single visual truth",
		activeClass: "border-purple-400/60 bg-purple-500/10",
	},
	{
		id: "I2V",
		label: "I2V",
		description: "Multiple image ingredients with explicit roles",
		activeClass: "border-amber-400/60 bg-amber-500/10",
	},
];

const STRATEGY_OPTIONS: Array<{
	id: BatchVariationStrategy;
	label: string;
}> = [
	{
		id: "SAME_SCRIPT_DIFF_VISUALS",
		label: "Same script + different visuals",
	},
	{
		id: "DIFF_SCRIPT_DIFF_VISUALS",
		label: "Different script + different visuals",
	},
	{
		id: "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
		label:
			"Same core angle + different dialogue + different visuals (recommended)",
	},
];

const TERMINAL_STATUSES = ["COMPLETED", "FAILED", "CANCELLED"];

interface AvatarPoolProfile {
	avatar_code: string;
	character_name: string;
	variant: string;
}

interface AvatarPoolResponse {
	avatars: AvatarPoolProfile[];
	count: number;
}

function extractApiDetail(e: unknown): string {
	const msg = e instanceof Error ? e.message : String(e);
	const idx = msg.indexOf(": ");
	const body = idx >= 0 ? msg.slice(idx + 2) : msg;
	try {
		const parsed = JSON.parse(body) as { detail?: unknown };
		if (parsed?.detail != null) {
			return typeof parsed.detail === "string"
				? parsed.detail
				: JSON.stringify(parsed.detail);
		}
	} catch {
		// keep raw message
	}
	return msg;
}

function splitLines(text: string): string[] {
	return text
		.split("\n")
		.map((line) => line.trim())
		.filter(Boolean);
}

function FieldLabel({ text }: { text: string }) {
	return (
		<label className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500 block mb-1">
			{text}
		</label>
	);
}

// ─── Asset multi/single select ────────────────────────────────

function AssetSelectList({
	label,
	assets,
	loading,
	selectedIds,
	single,
	optional,
	onToggle,
}: {
	label: string;
	assets: CreativeAsset[];
	loading: boolean;
	selectedIds: string[];
	single?: boolean;
	optional?: boolean;
	onToggle: (assetId: string) => void;
}) {
	return (
		<div>
			<FieldLabel text={`${label}${optional ? " (optional)" : ""}`} />
			<div className="rounded-xl border border-slate-700 bg-slate-950 max-h-48 overflow-y-auto">
				{loading ? (
					<div className="p-4 text-center text-xs text-slate-500">
						Loading assets…
					</div>
				) : assets.length === 0 ? (
					<div className="p-4 text-center text-xs text-slate-500 italic">
						No matching creative assets found.
					</div>
				) : (
					assets.map((asset) => {
						const checked = selectedIds.includes(asset.asset_id);
						return (
							<button
								key={asset.asset_id}
								type="button"
								onClick={() => onToggle(asset.asset_id)}
								className={`w-full flex items-center gap-2 px-3 py-2 border-b border-slate-800 last:border-0 text-left transition-colors ${checked ? "bg-blue-500/10" : "hover:bg-slate-800/50"}`}
							>
								<span
									className={`w-3.5 h-3.5 flex-shrink-0 border ${single ? "rounded-full" : "rounded"} ${checked ? "border-blue-400 bg-blue-500" : "border-slate-600"}`}
								/>
								{asset.preview_url ? (
									<img
										src={asset.preview_url}
										alt={asset.display_name}
										className="w-8 h-8 rounded object-cover bg-slate-900 flex-shrink-0"
									/>
								) : (
									<span className="w-8 h-8 rounded bg-slate-900 flex-shrink-0" />
								)}
								<span className="min-w-0 flex-1">
									<span className="block text-xs text-slate-200 truncate">
										{asset.display_name}
									</span>
									<span className="block text-[10px] font-mono text-slate-500 truncate">
										{asset.asset_id}
									</span>
								</span>
							</button>
						);
					})
				)}
			</div>
		</div>
	);
}

// ─── Main page ────────────────────────────────────────────────

export default function BatchPromptBuilderPage() {
	const navigate = useNavigate();

	// Step 1 — product
	const [products, setProducts] = useState<Product[]>([]);
	const [productsLoading, setProductsLoading] = useState(true);
	const [productId, setProductId] = useState("");

	// Step 2 — mode
	const [mode, setMode] = useState<BatchLogicalMode | null>(null);

	// Step 3 — shared fields
	const [quantity, setQuantity] = useState(10);
	const [strategy, setStrategy] = useState<BatchVariationStrategy>(
		"SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
	);
	const [sceneContextsText, setSceneContextsText] = useState("");
	const [hookAnglesText, setHookAnglesText] = useState("");
	const [durationSeconds, setDurationSeconds] = useState(8);
	const [targetLanguage, setTargetLanguage] = useState("BM_MS");

	// HYBRID — avatar codes
	const [avatarPool, setAvatarPool] = useState<AvatarPoolProfile[]>([]);
	const [avatarPoolLoading, setAvatarPoolLoading] = useState(false);
	const [avatarCodes, setAvatarCodes] = useState<string[]>([]);

	// F2V — finished frame
	const [frameAssets, setFrameAssets] = useState<CreativeAsset[]>([]);
	const [frameAssetsLoading, setFrameAssetsLoading] = useState(false);
	const [finishedFrameAssetId, setFinishedFrameAssetId] = useState<
		string | null
	>(null);

	// I2V — ingredient assets
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	const [styleAssets, setStyleAssets] = useState<CreativeAsset[]>([]);
	const [i2vAssetsLoading, setI2vAssetsLoading] = useState(false);
	const [characterAssetIds, setCharacterAssetIds] = useState<string[]>([]);
	const [sceneAssetIds, setSceneAssetIds] = useState<string[]>([]);
	const [styleAssetIds, setStyleAssetIds] = useState<string[]>([]);

	// Submission + polling
	const [submitting, setSubmitting] = useState(false);
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [batchRunId, setBatchRunId] = useState<string | null>(null);
	const [batchRun, setBatchRun] = useState<BatchRunStatus | null>(null);

	useEffect(() => {
		let cancelled = false;
		setProductsLoading(true);
		fetchProductCatalog(500)
			.then((resp) => {
				if (!cancelled) setProducts(resp.items ?? []);
			})
			.catch(() => {})
			.finally(() => {
				if (!cancelled) setProductsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, []);

	// Lazy-load mode-specific option pools
	useEffect(() => {
		if (mode !== "HYBRID" || avatarPool.length > 0 || avatarPoolLoading) {
			return;
		}
		let cancelled = false;
		setAvatarPoolLoading(true);
		fetchAPI<AvatarPoolResponse>("/api/workspace/avatar-registry/pool")
			.then((resp) => {
				if (!cancelled) setAvatarPool(resp.avatars ?? []);
			})
			.catch(() => {})
			.finally(() => {
				if (!cancelled) setAvatarPoolLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [mode, avatarPool.length, avatarPoolLoading]);

	useEffect(() => {
		if (mode !== "F2V" || frameAssets.length > 0 || frameAssetsLoading) {
			return;
		}
		let cancelled = false;
		setFrameAssetsLoading(true);
		fetchCreativeAssets({
			semantic_role: "COMPOSITE_FRAME_REFERENCE",
			status: "ACTIVE",
		})
			.then((resp) => {
				if (!cancelled) setFrameAssets(resp.items ?? []);
			})
			.catch(() => {})
			.finally(() => {
				if (!cancelled) setFrameAssetsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [mode, frameAssets.length, frameAssetsLoading]);

	useEffect(() => {
		if (mode !== "I2V" || characterAssets.length > 0 || i2vAssetsLoading) {
			return;
		}
		let cancelled = false;
		setI2vAssetsLoading(true);
		Promise.all([
			fetchCreativeAssets({
				semantic_role: "CHARACTER_REFERENCE",
				status: "ACTIVE",
			}),
			fetchCreativeAssets({
				semantic_role: "SCENE_CONTEXT_REFERENCE",
				status: "ACTIVE",
			}),
			fetchCreativeAssets({
				semantic_role: "STYLE_REFERENCE",
				status: "ACTIVE",
			}),
		])
			.then(([chars, scenes, styles]) => {
				if (cancelled) return;
				setCharacterAssets(chars.items ?? []);
				setSceneAssets(scenes.items ?? []);
				setStyleAssets(styles.items ?? []);
			})
			.catch(() => {})
			.finally(() => {
				if (!cancelled) setI2vAssetsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [mode, characterAssets.length, i2vAssetsLoading]);

	// Poll batch run status every 2s until terminal
	useEffect(() => {
		if (!batchRunId) return;
		let cancelled = false;
		let timer = 0;
		const tick = async () => {
			try {
				const run = await getBatchRun(batchRunId);
				if (cancelled) return;
				setBatchRun(run);
				if (TERMINAL_STATUSES.includes(run.status)) return;
			} catch {
				// transient poll failure — keep polling
			}
			if (!cancelled) {
				timer = window.setTimeout(() => void tick(), 2000);
			}
		};
		void tick();
		return () => {
			cancelled = true;
			window.clearTimeout(timer);
		};
	}, [batchRunId]);

	const toggleInList = useCallback(
		(setter: React.Dispatch<React.SetStateAction<string[]>>, value: string) => {
			setter((prev) =>
				prev.includes(value)
					? prev.filter((v) => v !== value)
					: [...prev, value],
			);
		},
		[],
	);

	const selectedProduct = products.find((p) => p.id === productId);

	const canSubmit =
		Boolean(productId) &&
		Boolean(mode) &&
		!submitting &&
		(mode !== "F2V" || Boolean(finishedFrameAssetId)) &&
		(mode !== "I2V" || characterAssetIds.length > 0);

	const handleSubmit = async () => {
		if (!productId || !mode) return;
		setSubmitting(true);
		setSubmitError(null);
		setBatchRunId(null);
		setBatchRun(null);
		try {
			const isTextLane = mode === "T2V" || mode === "HYBRID";
			const resp = await startBatchPrompts({
				product_id: productId,
				logical_mode: mode,
				quantity,
				variation_strategy: strategy,
				// Prompt generation is free — fixed small interval, not a
				// video-production pacing control.
				interval_seconds: 2,
				duration_seconds: durationSeconds,
				target_language: targetLanguage,
				avatar_codes: mode === "HYBRID" ? avatarCodes : [],
				character_asset_ids: mode === "I2V" ? characterAssetIds : [],
				scene_asset_ids: mode === "I2V" ? sceneAssetIds : [],
				style_asset_ids: mode === "I2V" ? styleAssetIds : [],
				scene_contexts: isTextLane ? splitLines(sceneContextsText) : [],
				hook_angles: splitLines(hookAnglesText),
				finished_frame_asset_id: mode === "F2V" ? finishedFrameAssetId : null,
			});
			setBatchRunId(resp.batch_run_id);
		} catch (e) {
			setSubmitError(extractApiDetail(e));
		} finally {
			setSubmitting(false);
		}
	};

	const runTerminal = batchRun && TERMINAL_STATUSES.includes(batchRun.status);
	const isTextMode = mode === "T2V" || mode === "HYBRID";

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			{/* Header */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
					Batch Prompt Builder
				</div>
				<div className="mt-1 text-xs text-slate-400">
					Prompt generation only — this builds a batch of prompts into the
					Prompt Queue. No video is generated and no Google Flow credits are
					spent here. Production execution happens later in the Production
					Queue.
				</div>
			</section>

			{/* Step 1 — Product */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5 space-y-3">
				<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
					Step 1 — Product
				</div>
				<ProductPicker
					products={products}
					selectedProductId={productId}
					onSelect={setProductId}
					loading={productsLoading}
				/>
			</section>

			{/* Step 2 — Mode */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5 space-y-3">
				<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
					Step 2 — Mode
				</div>
				<div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
					{MODE_CARDS.map((card) => (
						<button
							key={card.id}
							type="button"
							onClick={() => setMode(card.id)}
							className={`rounded-2xl border p-4 text-left transition-all ${mode === card.id ? card.activeClass : "border-slate-700 bg-slate-900/50 hover:border-slate-500"}`}
						>
							<div className="text-sm font-bold text-slate-100">
								{card.label}
							</div>
							<div className="mt-1 text-[11px] text-slate-400 leading-relaxed">
								{card.description}
							</div>
						</button>
					))}
				</div>
			</section>

			{/* Step 3 — Mode-specific form */}
			{mode && (
				<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5 space-y-4">
					<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
						Step 3 — {mode} Batch Configuration
					</div>

					{mode === "HYBRID" && (
						<div className="rounded-xl border border-cyan-500/30 bg-cyan-500/8 px-3 py-2 text-xs text-cyan-200">
							The product image is the visual anchor for every HYBRID prompt.
							The AI presenter is drawn from the Avatar Registry — leave the
							avatar selection empty to rotate the whole registry.
						</div>
					)}

					<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
						<div>
							<FieldLabel text="Quantity (1–100)" />
							<input
								type="number"
								min={1}
								max={100}
								value={quantity}
								onChange={(e) =>
									setQuantity(
										Math.max(1, Math.min(100, Number(e.target.value) || 1)),
									)
								}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-400/50"
							/>
						</div>
						{isTextMode && (
							<>
								<div>
									<FieldLabel text="Duration (seconds)" />
									<input
										type="number"
										min={1}
										value={durationSeconds}
										onChange={(e) =>
											setDurationSeconds(Number(e.target.value) || 8)
										}
										className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-400/50"
									/>
								</div>
								<div>
									<FieldLabel text="Target Language" />
									<select
										value={targetLanguage}
										onChange={(e) => setTargetLanguage(e.target.value)}
										className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-400/50"
									>
										<option value="BM_MS">BM_MS (Bahasa Malaysia)</option>
										<option value="EN_US">EN_US (English)</option>
									</select>
								</div>
							</>
						)}
					</div>

					{/* Variation strategy */}
					<div>
						<FieldLabel text="Variation Strategy" />
						<div className="space-y-1.5">
							{STRATEGY_OPTIONS.map((opt) => (
								<label
									key={opt.id}
									className={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 cursor-pointer transition-colors ${strategy === opt.id ? "border-blue-400/60 bg-blue-500/10" : "border-slate-700 bg-slate-900/50 hover:border-slate-500"}`}
								>
									<input
										type="radio"
										name="variation-strategy"
										checked={strategy === opt.id}
										onChange={() => setStrategy(opt.id)}
										className="accent-blue-500"
									/>
									<span className="text-xs text-slate-200">{opt.label}</span>
								</label>
							))}
						</div>
					</div>

					{/* Scene contexts — T2V / HYBRID only */}
					{isTextMode && (
						<div>
							<FieldLabel text="Scene Contexts (one per line)" />
							<textarea
								value={sceneContextsText}
								onChange={(e) => setSceneContextsText(e.target.value)}
								rows={4}
								placeholder={"kitchen morning routine\ncar dashboard commute\noffice desk unboxing"}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 resize-none outline-none focus:border-blue-400/50"
							/>
						</div>
					)}

					{/* Hook angles — all modes */}
					<div>
						<FieldLabel text="Hook Angles (one per line)" />
						<textarea
							value={hookAnglesText}
							onChange={(e) => setHookAnglesText(e.target.value)}
							rows={4}
							placeholder={"problem-agitate opener\nprice shock reveal\nbefore/after transformation"}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 resize-none outline-none focus:border-blue-400/50"
						/>
					</div>

					{/* HYBRID — avatar codes multi-select */}
					{mode === "HYBRID" && (
						<div>
							<FieldLabel text="Avatar Codes (optional — empty rotates the whole registry)" />
							<div className="rounded-xl border border-slate-700 bg-slate-950 max-h-48 overflow-y-auto">
								{avatarPoolLoading ? (
									<div className="p-4 text-center text-xs text-slate-500">
										Loading avatar pool…
									</div>
								) : avatarPool.length === 0 ? (
									<div className="p-4 text-center text-xs text-slate-500 italic">
										Avatar pool is empty.
									</div>
								) : (
									avatarPool.map((avatar) => {
										const checked = avatarCodes.includes(avatar.avatar_code);
										return (
											<button
												key={avatar.avatar_code}
												type="button"
												onClick={() =>
													toggleInList(setAvatarCodes, avatar.avatar_code)
												}
												className={`w-full flex items-center gap-2 px-3 py-2 border-b border-slate-800 last:border-0 text-left transition-colors ${checked ? "bg-cyan-500/10" : "hover:bg-slate-800/50"}`}
											>
												<span
													className={`w-3.5 h-3.5 flex-shrink-0 border rounded ${checked ? "border-cyan-400 bg-cyan-500" : "border-slate-600"}`}
												/>
												<span className="text-xs font-mono text-slate-200">
													{avatar.avatar_code}
												</span>
												<span className="text-xs text-slate-400 truncate">
													{avatar.character_name}
													{avatar.variant ? ` · ${avatar.variant}` : ""}
												</span>
											</button>
										);
									})
								)}
							</div>
							{avatarCodes.length > 0 && (
								<div className="mt-1 text-[11px] text-slate-500">
									{avatarCodes.length} avatar(s) selected:{" "}
									{avatarCodes.join(", ")}
								</div>
							)}
						</div>
					)}

					{/* F2V — single finished frame */}
					{mode === "F2V" && (
						<AssetSelectList
							label="Finished Frame (single visual truth)"
							assets={frameAssets}
							loading={frameAssetsLoading}
							selectedIds={finishedFrameAssetId ? [finishedFrameAssetId] : []}
							single
							onToggle={(assetId) =>
								setFinishedFrameAssetId((prev) =>
									prev === assetId ? null : assetId,
								)
							}
						/>
					)}

					{/* I2V — ingredient selectors + role map */}
					{mode === "I2V" && (
						<div className="space-y-4">
							<AssetSelectList
								label="Character References"
								assets={characterAssets}
								loading={i2vAssetsLoading}
								selectedIds={characterAssetIds}
								onToggle={(assetId) =>
									toggleInList(setCharacterAssetIds, assetId)
								}
							/>
							<AssetSelectList
								label="Scene Context References"
								assets={sceneAssets}
								loading={i2vAssetsLoading}
								selectedIds={sceneAssetIds}
								optional
								onToggle={(assetId) => toggleInList(setSceneAssetIds, assetId)}
							/>
							<AssetSelectList
								label="Style References"
								assets={styleAssets}
								loading={i2vAssetsLoading}
								selectedIds={styleAssetIds}
								optional
								onToggle={(assetId) => toggleInList(setStyleAssetIds, assetId)}
							/>
							<div className="rounded-xl border border-amber-500/30 bg-amber-500/8 p-3">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-300 mb-2">
									Role Map Preview
								</div>
								<ul className="space-y-1 text-[11px] text-amber-100 font-mono">
									<li>
										PRODUCT_REFERENCE →{" "}
										{selectedProduct
											? selectedProduct.product_short_name || selectedProduct.id
											: "(auto from selected product)"}
									</li>
									<li>
										AVATAR_REFERENCE →{" "}
										{characterAssetIds.length > 0
											? `${characterAssetIds.length} character reference(s)`
											: "(none selected)"}
									</li>
									<li>
										STYLE_SCENE_REFERENCE →{" "}
										{sceneAssetIds.length + styleAssetIds.length > 0
											? `${sceneAssetIds.length} scene + ${styleAssetIds.length} style reference(s)`
											: "(none — optional)"}
									</li>
								</ul>
							</div>
						</div>
					)}
				</section>
			)}

			{/* Submit + progress */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5 space-y-4">
				{submitError && (
					<div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3">
						<div className="flex items-center gap-2 mb-1">
							<AlertTriangle size={14} className="text-red-400" />
							<span className="text-xs font-bold text-red-300 uppercase tracking-widest">
								Batch Rejected
							</span>
						</div>
						<div className="text-xs text-red-200 font-mono whitespace-pre-wrap">
							{submitError}
						</div>
					</div>
				)}

				<div className="flex flex-wrap items-center gap-3">
					<button
						type="button"
						disabled={!canSubmit}
						onClick={() => void handleSubmit()}
						className="inline-flex items-center gap-2 rounded-xl border border-blue-500/40 bg-blue-500/15 px-5 py-2.5 text-sm font-semibold text-blue-100 hover:bg-blue-500/25 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
					>
						{submitting ? (
							<Loader2 size={15} className="animate-spin" />
						) : (
							<Sparkles size={15} />
						)}
						Generate Prompt Set
					</button>
					<span className="text-[11px] text-slate-500">
						Prompts only — free, no credits. Prompt spacing is fixed at a small
						interval (2s); video pacing controls live in the Production Queue.
					</span>
				</div>

				{batchRunId && (
					<div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-2">
						<div className="flex items-center gap-2">
							{runTerminal ? (
								batchRun?.status === "COMPLETED" ? (
									<CheckCircle size={14} className="text-emerald-400" />
								) : (
									<AlertTriangle size={14} className="text-red-400" />
								)
							) : (
								<RefreshCw size={14} className="text-blue-400 animate-spin" />
							)}
							<span className="text-xs font-bold text-slate-200 uppercase tracking-widest">
								Batch Run {batchRun?.status ?? "PENDING"}
							</span>
							<span className="text-[10px] font-mono text-slate-500">
								{batchRunId}
							</span>
						</div>
						<div className="text-xs text-slate-300">
							{batchRun
								? `${batchRun.total_completed} completed · ${batchRun.total_failed} failed · ${batchRun.total_expected} expected`
								: "Waiting for first status…"}
						</div>
						{runTerminal && (
							<button
								type="button"
								onClick={() => navigate("/workspace/generation-packages")}
								className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25 transition-colors"
							>
								→ Review in Prompt Queue
							</button>
						)}
					</div>
				)}
			</section>
		</div>
	);
}
