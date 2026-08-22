import { FileCheck2, ImageIcon, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { FinalPromptApprovalModal } from "../components/execution-approval/FinalPromptApprovalModal";
import StaffIdentityBar from "../components/StaffIdentityBar";
import type { PrepareDispatchRequest } from "../api/executionApproval";
import { pollImgGenerationJob, startImgGeneration } from "../api/imgFactory";
import { resolveExactGenerationGate } from "../api/exactProductOutput";
import { usePosterRecipes } from "../api/posterRecipes";
import {
	createPosterPromptDraft,
	formatPosterPromptDraftError,
} from "../api/posterPromptDraft";
import {
	composePosterV2,
	posterV2OutputUrl,
	type PosterV2ComposeResponse,
} from "../api/posterV2";
import CopyArchitectureV2LaneCard from "../components/copywriting/CopyArchitectureV2LaneCard";
import CopywritingSourceSelector from "../components/copywriting/CopywritingSourceSelector";
import PosterRecipeSelector from "../components/poster/PosterRecipeSelector";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";
import { useProductCatalog } from "../hooks/useProductCatalog";
import { useStaffIdentity } from "../hooks/useStaffIdentity";
import type { PosterPromptDraftResponse } from "../types/posterPromptDraft";
import {
	PRODUCT_REFERENCE_IMAGE_REQUIRED,
	productSubjectAsset,
} from "../utils/productSubjectAsset";

const V2_CONTEXT = {
	enabled: true,
	state: "ON",
	scope: "global",
	rollout_state: "ON",
};

function message(error: unknown, fallback: string): string {
	return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Poster Builder's production surface is deliberately V2-only. It cannot
 * author, select, approve, or submit a legacy poster Copy Set. Deterministic
 * composition is provider-free; an optional live IMG background action remains
 * behind its own explicit confirmation gate.
 */
export default function PosterBuilderPage() {
	const [searchParams, setSearchParams] = useSearchParams();
	const { products, isLoadingProducts, productsError } = useProductCatalog(50);
	const staffIdentity = useStaffIdentity();
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [selectedRecipeId, setSelectedRecipeId] = useState("");
	const [copyReady, setCopyReady] = useState(false);
	const [promptPackage, setPromptPackage] =
		useState<PosterPromptDraftResponse | null>(null);
	const [promptLoading, setPromptLoading] = useState(false);
	const [promptError, setPromptError] = useState("");
	const [backgroundMediaId, setBackgroundMediaId] = useState("");
	const [backgroundLocalPath, setBackgroundLocalPath] = useState("");
	const [composeLoading, setComposeLoading] = useState(false);
	const [composeError, setComposeError] = useState("");
	const [composeResult, setComposeResult] =
		useState<PosterV2ComposeResponse | null>(null);
	const [liveConfirmOpen, setLiveConfirmOpen] = useState(false);
	const [liveActionConfirmed, setLiveActionConfirmed] = useState(false);
	const [liveLoading, setLiveLoading] = useState(false);
	const [liveStage, setLiveStage] = useState("");
	const [liveError, setLiveError] = useState("");
	const [livePreviewUrl, setLivePreviewUrl] = useState("");
	const { recipes, error: recipesError } = usePosterRecipes();

	useEffect(() => {
		const productId = searchParams.get("product_id");
		if (!productId || products.length === 0) return;
		const match = products.find((product) => product.id === productId) ?? null;
		if (match && match.id !== selectedProduct?.id) setSelectedProduct(match);
	}, [products, searchParams, selectedProduct?.id]);

	useEffect(() => {
		if (!selectedRecipeId && recipes.length > 0) {
			setSelectedRecipeId(recipes[0].recipe_id);
		}
	}, [recipes, selectedRecipeId]);

	useEffect(() => {
		setPromptPackage(null);
		setPromptError("");
		setComposeResult(null);
		setComposeError("");
		setLiveConfirmOpen(false);
		setLiveActionConfirmed(false);
		setLiveError("");
		setLivePreviewUrl("");
	}, [selectedProduct?.id, selectedRecipeId]);

	const selectedRecipe = useMemo(
		() => recipes.find((recipe) => recipe.recipe_id === selectedRecipeId) ?? null,
		[recipes, selectedRecipeId],
	);

	const selectProduct = (product: Product | null) => {
		setSelectedProduct(product);
		setCopyReady(false);
		const next = new URLSearchParams(searchParams);
		if (product) next.set("product_id", product.id);
		else next.delete("product_id");
		setSearchParams(next, { replace: true });
	};

	const buildPromptDraft = async () => {
		if (!selectedProduct || !selectedRecipe || !copyReady) return;
		setPromptLoading(true);
		setPromptError("");
		setPromptPackage(null);
		try {
			const result = await createPosterPromptDraft({
				product_id: selectedProduct.id,
				poster_objective: "",
				poster_type: selectedRecipe.archetype,
				visual_route: selectedRecipe.background_scene,
				human_presence_mode: "No human / product-forward",
				frame_ratio: "9:16",
				language: "ms",
				text_density: selectedRecipe.allowed_text_density[0] ?? "medium",
				hook: "",
				subhook: "",
				usp_1: "",
				usp_2: "",
				usp_3: "",
				cta: "",
				operator_notes: "",
				poster_recipe_id: selectedRecipe.recipe_id,
				copy_v2_context: V2_CONTEXT,
			});
			setPromptPackage(result);
		} catch (error) {
			setPromptError(formatPosterPromptDraftError(error));
		} finally {
			setPromptLoading(false);
		}
	};

	const compose = async () => {
		if (!staffIdentity.hasStaff) {
			setComposeError("Select an active staff profile before composing a poster.");
			return;
		}
		if (!selectedProduct || !selectedRecipe || !copyReady || !promptPackage) return;
		setComposeLoading(true);
		setComposeError("");
		setComposeResult(null);
		try {
			const result = await composePosterV2({
				product_id: selectedProduct.id,
				staff_id: staffIdentity.staffId,
				recipe_id: selectedRecipe.recipe_id,
				background_media_id: backgroundMediaId.trim() || undefined,
				background_local_path: backgroundLocalPath.trim() || undefined,
				settings: { provider_calls: 0, copy_authority: "COPY_REGISTER_V2_ONLY" },
				copy_v2_context: V2_CONTEXT,
			});
			setComposeResult(result);
		} catch (error) {
			setComposeError(message(error, "Poster composition failed."));
		} finally {
			setComposeLoading(false);
		}
	};

	const [pendingApproval, setPendingApproval] = useState<PrepareDispatchRequest | null>(null);

	const generateLiveBackground = async (approved = false, approvedPrompt?: string) => {
		if (
			!staffIdentity.hasStaff ||
			(!approved && !liveActionConfirmed) ||
			!selectedProduct ||
			!promptPackage?.poster_prompt ||
			!copyReady
		) return;
		setLiveConfirmOpen(false);
		setLiveLoading(true);
		setLiveError("");
		setLivePreviewUrl("");
		try {
			const gate = await resolveExactGenerationGate(selectedProduct.id, undefined, {
				laneId: "POSTER_BUILDER",
				isPoster: true,
				isProductOnly: true,
			});
			if (gate.mode === "blocked") throw new Error(gate.message);
			const exact = gate.mode === "exact";
			const subjectAsset = productSubjectAsset(selectedProduct);
			if (!exact && !subjectAsset) {
				throw new Error(
					`${PRODUCT_REFERENCE_IMAGE_REQUIRED} — live poster background generation is blocked.`,
				);
			}
			// Final Prompt Approval Gate (IMG is ENFORCED — credit-free never means
			// approval-optional). The server grounds the RAW prompt (exact / product
			// truth) during review via /prepare, so the operator approves the FINAL
			// provider-ready prompt. On dispatch the approved text is sent VERBATIM
			// (final_prompt_pre_approved) — no post-approval re-grounding.
			if (!approved) {
				setLiveLoading(false);
				setLiveStage("");
				setPendingApproval({
					surface: "poster_builder",
					logical_mode: "IMG",
					prompt: promptPackage.poster_prompt,
					product_id: selectedProduct.id,
					visual_lane_id: "POSTER_BUILDER",
					aspect: "9:16",
					count: 1,
				});
				return;
			}
			const prompt = approvedPrompt ?? promptPackage.poster_prompt;
			setLiveStage("Submitting one confirmed IMG operation…");
			const { job_id } = await startImgGeneration({
				prompt,
				product_id: selectedProduct.id,
				staff_id: staffIdentity.staffId,
				visual_lane_id: "POSTER_BUILDER",
				aspect: "9:16",
				count: 1,
				final_prompt_pre_approved: true,
				...(subjectAsset && !exact ? { refs: { subjectAsset } } : {}),
				maximum_provider_operations: 1,
				max_retry_operations: 0,
			});
			setLiveStage("Waiting for the confirmed IMG operation…");
			const job = await pollImgGenerationJob(job_id);
			const mediaId = job.media_id ?? "";
			if (!new Set(["DONE", "COMPLETE", "COMPLETED"]).has(job.status) || !mediaId) {
				throw new Error(job.error || `Generation ended as ${job.status} with no image.`);
			}
			setBackgroundMediaId(mediaId);
			setBackgroundLocalPath("");
			setLivePreviewUrl(job.url ?? `/api/flow/retrieved/${mediaId}`);
			setLiveStage("Background ready. Complete the V2 deterministic compose below.");
		} catch (error) {
			setLiveError(message(error, "Live IMG background generation failed."));
			setLiveStage("");
		} finally {
			setLiveLoading(false);
			setLiveActionConfirmed(false);
		}
	};

	const hasBackground = Boolean(backgroundMediaId.trim() || backgroundLocalPath.trim());
	const canCompose =
		staffIdentity.hasStaff &&
		copyReady &&
		Boolean(promptPackage) &&
		promptPackage?.production_allowed === true &&
		hasBackground &&
		!composeLoading;

	return (
		<div
			className="min-h-full bg-slate-950 px-4 py-5 text-slate-100 md:px-8"
			data-testid="poster-builder-v2-only"
		>
			{pendingApproval && (
				<FinalPromptApprovalModal
					prepareRequest={pendingApproval}
					approvedBy={staffIdentity.selectedStaff?.display_name ?? ""}
					onApproved={(snap) => {
						setPendingApproval(null);
						void generateLiveBackground(true, snap.final_prompt_text);
					}}
					onCancel={() => setPendingApproval(null)}
				/>
			)}
			<header className="mb-5 rounded-2xl border border-violet-500/30 bg-gradient-to-br from-slate-950 to-violet-950/30 p-5">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div>
						<div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] text-violet-300">
							<ImageIcon size={15} /> Image Production
						</div>
						<h1 className="mt-2 text-2xl font-bold">Poster Builder</h1>
						<p className="mt-2 max-w-3xl text-sm text-slate-400">
							Formula-native copy comes only from the approved Copy Register V2 binding.
							 This page cannot select or write legacy Copy Sets.
						</p>
					</div>
					<nav className="flex flex-wrap items-center gap-2 text-[11px] font-semibold">
						<a
							href="/library/images"
							className="rounded-lg border border-v4-accent/30 bg-v4-accent/10 px-3 py-1.5 text-v4-accent-ink"
						>
							Image Library ↗
						</a>
						<a
							href="/creative/copy-registry"
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-300"
						>
							Copy Registry ↗
						</a>
					</nav>
				</div>
				<div className="mt-4 flex flex-wrap gap-2 text-[10px] uppercase tracking-wider text-slate-400">
					<span className="rounded border border-emerald-500/30 px-2 py-1">V2 only</span>
					<span className="rounded border border-emerald-500/30 px-2 py-1">Automatic provider calls: 0</span>
					<span className="rounded border border-emerald-500/30 px-2 py-1">Live IMG: explicit confirmation only</span>
				</div>
			</header>
			<StaffIdentityBar identity={staffIdentity} surface="POSTER_BUILDER" />

			<div className="space-y-5">
				<section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
					<h2 className="text-sm font-bold">1. Select product</h2>
					<div className="mt-3">
						<SearchableProductSelect
							products={products}
							selectedProduct={selectedProduct}
							onSelect={selectProduct}
							isLoadingProducts={isLoadingProducts}
							productsError={productsError}
						/>
					</div>
					{productsError ? <p className="mt-2 text-sm text-rose-300">{productsError}</p> : null}
				</section>

				<section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
					<h2 className="text-sm font-bold">2. Copywriting</h2>
					<p className="mt-1 text-xs text-slate-400">
						Select approved copy from Copy Register or generate with AI Copy Assistant.
					</p>
					<div className="mt-3 space-y-3">
						<CopywritingSourceSelector
							productId={selectedProduct?.id}
							productName={selectedProduct?.product_display_name || selectedProduct?.raw_product_title}
							lane="POSTER_BUILDER"
							onCopySelected={() => setPromptPackage(null)}
						/>
						<CopyArchitectureV2LaneCard
							lane="POSTER_BUILDER"
							productId={selectedProduct?.id ?? null}
							onReadyChange={setCopyReady}
						/>
					</div>
				</section>

				<section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
					<h2 className="text-sm font-bold">3. Poster recipe & layout</h2>
					<div className="mt-3">
						<PosterRecipeSelector
							recipes={recipes}
							selectedRecipeId={selectedRecipeId}
							onSelect={setSelectedRecipeId}
							error={recipesError}
						/>
					</div>
				</section>

				<section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
					<div className="flex items-start gap-3">
						<FileCheck2 className="mt-0.5 text-indigo-300" size={18} />
						<div>
							<h2 className="text-sm font-bold">4. Resolve prompt package</h2>
							<p className="mt-1 text-xs text-slate-400">
								The backend projects immutable approved blueprint text through
								 <code>/api/poster/prompt-draft</code>. Empty or manual copy is never submitted.
							</p>
						</div>
					</div>
					<button
						type="button"
						onClick={() => void buildPromptDraft()}
						disabled={!staffIdentity.hasStaff || !selectedProduct || !selectedRecipe || !copyReady || promptLoading}
						className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-40"
					>
						{promptLoading ? <Loader2 className="mr-2 inline animate-spin" size={15} /> : null}
						Resolve approved V2 copy
					</button>
					{promptError ? <p className="mt-3 text-sm text-rose-300">{promptError}</p> : null}
					{promptPackage ? (
						<div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4" data-testid="poster-v2-prompt-result">
							<div className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
								<ShieldCheck size={16} /> {promptPackage.prompt_package_status}
							</div>
							<dl className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
								<div><dt className="text-slate-500">Hook</dt><dd>{promptPackage.copy_layout.hook || "—"}</dd></div>
								<div><dt className="text-slate-500">Body</dt><dd>{promptPackage.copy_layout.subhook || promptPackage.copy_layout.usp.join(" · ") || "—"}</dd></div>
								<div><dt className="text-slate-500">CTA</dt><dd>{promptPackage.copy_layout.cta || "—"}</dd></div>
							</dl>
						</div>
					) : null}
				</section>

				<section className="rounded-2xl border border-amber-500/30 bg-amber-950/10 p-5">
					<h2 className="text-sm font-bold">5. Optional live background generation</h2>
					<p className="mt-1 text-xs text-slate-400">
						This is the only provider action on this page. It requires a separate
						explicit confirmation and produces a background artifact; final copy and
						lineage still bind through <code>/api/poster/compose</code>.
					</p>
					<button
						type="button"
						data-testid="poster-live-background-button"
						onClick={() => {
							setLiveActionConfirmed(false);
							setLiveConfirmOpen(true);
						}}
						disabled={
							!staffIdentity.hasStaff ||
							!copyReady ||
							!promptPackage?.production_allowed ||
							liveLoading
						}
						className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm font-semibold text-amber-100 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{liveLoading ? <Loader2 className="mr-2 inline animate-spin" size={15} /> : null}
						Generate one live IMG background
					</button>
					{liveStage ? <p className="mt-3 text-xs text-amber-100">{liveStage}</p> : null}
					{liveError ? <p className="mt-3 text-sm text-rose-300">{liveError}</p> : null}
					{livePreviewUrl ? (
						<img
							className="mt-3 max-h-80 rounded-xl border border-slate-700"
							src={livePreviewUrl}
							alt="Generated poster background awaiting V2 compose"
						/>
					) : null}
				</section>

				<section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
					<h2 className="text-sm font-bold">5. Deterministic V2 compose</h2>
					<p className="mt-1 text-xs text-slate-400">
						Provide an existing background artifact or local server path. This action calls
						 <code>/api/poster/compose</code> and never invokes an image provider.
					</p>
					<div className="mt-4 grid gap-3 md:grid-cols-2">
						<label className="text-xs text-slate-300">
							Background media ID
							<input
								value={backgroundMediaId}
								onChange={(event) => setBackgroundMediaId(event.target.value)}
								className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
								placeholder="Existing generated_artifact media_id"
							/>
						</label>
						<label className="text-xs text-slate-300">
							Background local path
							<input
								value={backgroundLocalPath}
								onChange={(event) => setBackgroundLocalPath(event.target.value)}
								className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
								placeholder="Existing server-side image path"
							/>
						</label>
					</div>
					<button
						type="button"
						onClick={() => void compose()}
						disabled={!canCompose}
						className="mt-4 rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-40"
					>
						{composeLoading ? <Loader2 className="mr-2 inline animate-spin" size={15} /> : null}
						Compose with V2 copy (zero provider calls)
					</button>
					{composeError ? <p className="mt-3 text-sm text-rose-300">{composeError}</p> : null}
					{composeResult ? (
						<div className="mt-4" data-testid="poster-v2-compose-result">
							<p className="text-xs text-emerald-200">
								Composed: {composeResult.deliverable.poster_deliverable_id}
							</p>
							<img
								className="mt-3 max-h-[42rem] rounded-xl border border-slate-700"
								src={posterV2OutputUrl(composeResult.deliverable.poster_deliverable_id)}
								alt="Composed poster output"
							/>
						</div>
					) : null}
				</section>
			</div>
			{liveConfirmOpen ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
					<div className="max-w-md space-y-3 rounded-2xl border border-amber-500/40 bg-slate-950 p-5">
						<div className="text-sm font-bold text-amber-100">
							Confirm one live IMG provider operation
						</div>
						<p className="text-[11px] text-slate-300">
							This submits exactly one image-generation job. It does not spend Google
							Flow video credits and it cannot run without this confirmation.
						</p>
						<label className="flex items-start gap-2 text-[11px] text-slate-200">
							<input
								type="checkbox"
								data-testid="poster-img-live-action-confirm-checkbox"
								checked={liveActionConfirmed}
								onChange={(event) => setLiveActionConfirmed(event.target.checked)}
								className="mt-0.5"
							/>
							<span>I authorize one live IMG provider operation for this background.</span>
						</label>
						<div className="flex justify-end gap-2">
							<button
								type="button"
								onClick={() => setLiveConfirmOpen(false)}
								className="rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] font-semibold text-slate-300"
							>
								Cancel
							</button>
							<button
								type="button"
								data-testid="poster-gen-confirm"
								disabled={!liveActionConfirmed}
								onClick={() => void generateLiveBackground()}
								className="rounded-lg border border-amber-500/40 bg-amber-500/20 px-3 py-1.5 text-[11px] font-bold text-amber-100 disabled:cursor-not-allowed disabled:opacity-40"
							>
								Confirm &amp; Generate
							</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}
