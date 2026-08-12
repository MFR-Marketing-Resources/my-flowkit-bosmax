import {
	ArrowLeft,
	ArrowRight,
	Check,
	Loader2,
	RefreshCw,
	Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
	approveProductReferencePack,
	fetchImageArtifacts,
	fetchProductReferencePack,
	type ImageArtifact,
	type ProductReferencePackSummary,
} from "../../../api/imgFactory";
import {
	approveProductTruthLock,
	fetchProductTruthLock,
	productTruthCutoutPreviewUrl,
	type ProductTruthLockStatus,
} from "../../../api/productTruthLock";
import {
	fetchCompositionPlan,
	fetchPosterDeliverableByAsset,
	posterCampaignVariantOutputUrl,
	posterDeliverableOutputUrl,
} from "../../../api/posterCopySets";
import type { CompositionPlan } from "../../../types/posterCompositionPlan";
import CompositionPlanSummary from "../CompositionPlanSummary";
import { usePosterRecipes } from "../../../api/posterRecipes";
import { fetchProductCatalog } from "../../../api/products";
import {
	bucketQaFindings,
	GUIDED_GOALS,
	GUIDED_STEPS,
	type GuidedStepId,
	goalEvidence,
	goalForArchetype,
	readinessBanner,
	stepIndex,
	truthLabel,
} from "../../../poster/guided/posterGuided";
import {
	type GuidedCopyFields,
	usePosterGuidedWorkflow,
} from "../../../poster/guided/usePosterGuidedWorkflow";
import type { Product } from "../../../types";
import type { PosterDeliverableReconstruction } from "../../../types/posterCopySet";
import type { PosterRecipe } from "../../../types/posterRecipe";
import SearchableProductSelect from "../../workspace/SearchableProductSelect";
import VisualAssetPicker from "../../workspace/VisualAssetPicker";

function productThumb(p: Product | null): string | null {
	return p?.image_analysis?.image_url ?? null;
}

// ── Stepper ─────────────────────────────────────────────────────────────────
function Stepper({
	step,
	canGoTo,
	goTo,
}: {
	step: GuidedStepId;
	canGoTo: (s: GuidedStepId) => boolean;
	goTo: (s: GuidedStepId) => void;
}) {
	const activeIdx = stepIndex(step);
	return (
		<ol
			className="flex flex-wrap items-center gap-1.5 rounded-2xl border border-slate-800 bg-slate-950/40 p-2"
			data-testid="poster-guided-stepper"
		>
			{GUIDED_STEPS.map((s, i) => {
				const reached = canGoTo(s.id);
				const active = s.id === step;
				const done = reached && i < activeIdx;
				return (
					<li key={s.id}>
						<button
							type="button"
							data-testid={`poster-guided-step-${s.id}`}
							disabled={!reached}
							onClick={() => goTo(s.id)}
							className={[
								"flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-semibold transition",
								active
									? "bg-emerald-500 text-slate-950"
									: done
										? "bg-emerald-500/15 text-emerald-200"
										: reached
											? "bg-slate-800 text-slate-200"
											: "cursor-not-allowed text-slate-600",
							].join(" ")}
							aria-current={active ? "step" : undefined}
						>
							<span
								className={[
									"flex h-5 w-5 items-center justify-center rounded-full text-[10px]",
									active
										? "bg-slate-950/20"
										: done
											? "bg-emerald-500/30"
											: "bg-slate-700/60",
								].join(" ")}
							>
								{done ? <Check className="h-3 w-3" /> : i + 1}
							</span>
							{s.title}
						</button>
					</li>
				);
			})}
		</ol>
	);
}

// ── Readiness banner (friendly, one line) ───────────────────────────────────
function ReadinessBanner({ status }: { status: string | null | undefined }) {
	const b = readinessBanner(status);
	const tones: Record<string, string> = {
		ready: "border-emerald-600/40 bg-emerald-500/10 text-emerald-100",
		info: "border-slate-700 bg-slate-900/60 text-slate-300",
		review: "border-amber-500/40 bg-amber-500/10 text-amber-100",
		blocked: "border-rose-500/40 bg-rose-500/10 text-rose-100",
	};
	return (
		<div
			className={`rounded-xl border px-4 py-2.5 text-sm ${tones[b.tone]}`}
			data-testid="poster-readiness-banner"
			data-tone={b.tone}
		>
			<span className="font-semibold">{b.title}.</span> {b.message}
		</div>
	);
}

function ErrorNote({ testid, text }: { testid: string; text: string }) {
	if (!text) return null;
	return (
		<p
			className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100"
			data-testid={testid}
		>
			{text}
		</p>
	);
}

// ── Selectable card primitive ───────────────────────────────────────────────
function SelectCard({
	selected,
	onClick,
	testid,
	children,
	badge,
	disabled,
}: {
	selected: boolean;
	onClick: () => void;
	testid: string;
	children: React.ReactNode;
	badge?: React.ReactNode;
	disabled?: boolean;
}) {
	return (
		<button
			type="button"
			data-testid={testid}
			data-selected={selected}
			disabled={disabled}
			onClick={onClick}
			className={[
				"relative w-full rounded-2xl border p-4 text-left transition",
				disabled ? "cursor-not-allowed opacity-40" : "",
				selected
					? "border-emerald-500 bg-emerald-500/10 ring-1 ring-emerald-500/40"
					: "border-slate-800 bg-slate-950/40 hover:border-slate-600",
			].join(" ")}
		>
			{badge}
			{children}
			{selected ? (
				<span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-slate-950">
					<Check className="h-3 w-3" />
				</span>
			) : null}
		</button>
	);
}

function Busy({ label }: { label: string }) {
	return (
		<div className="flex items-center gap-2 text-sm text-slate-400">
			<Loader2 className="h-4 w-4 animate-spin" /> {label}
		</div>
	);
}

const FIELD_LABELS: { key: keyof GuidedCopyFields; label: string }[] = [
	{ key: "primary_message", label: "Primary Message" },
	{ key: "support_message", label: "Support Message" },
	{ key: "cta", label: "CTA" },
	{ key: "disclaimer", label: "Disclaimer" },
];

export default function PosterGuidedShell() {
	const wf = usePosterGuidedWorkflow();
	const [products, setProducts] = useState<Product[]>([]);
	const [catalogError, setCatalogError] = useState("");
	const { recipes } = usePosterRecipes();
	const [searchParams] = useSearchParams();

	// Reopen a saved poster from the Creative Library.
	const [reopened, setReopened] =
		useState<PosterDeliverableReconstruction | null>(null);
	const [reopenError, setReopenError] = useState("");
	const restoredRef = useRef(false);

	// B-04: BACKEND-resolved composition plan for legacy/exact governed modes.
	// Creative Campaign has a separate canonical image compiler and must not
	// enter the deterministic compositor resolver, which intentionally rejects
	// provider-poster modes.
	const [compositionPlan, setCompositionPlan] = useState<CompositionPlan | null>(
		null,
	);
	const [planLoading, setPlanLoading] = useState(false);
	const [planError, setPlanError] = useState("");
	const planFetchRef = useRef(0);
	const productId = wf.product?.id ?? "";
	const approvedCopySetId = wf.approvedCopySet?.poster_copy_set_id ?? "";
	useEffect(() => {
		const fetchId = ++planFetchRef.current;
		if (
			!productId ||
			!wf.creativeMode ||
			wf.creativeMode === "CREATIVE_CAMPAIGN"
		) {
			setCompositionPlan(null);
			setPlanError("");
			setPlanLoading(false);
			return;
		}
		setPlanLoading(true);
		setPlanError("");
		void fetchCompositionPlan({
			product_id: productId,
			creative_mode: wf.creativeMode,
			recipe_id: wf.recipeId ?? "",
			poster_copy_set_id: approvedCopySetId,
		})
			.then((res) => {
				if (planFetchRef.current !== fetchId) return;
				setCompositionPlan(res.composition_plan ?? null);
			})
			.catch(() => {
				if (planFetchRef.current !== fetchId) return;
				setCompositionPlan(null);
				setPlanError(
					"Failed to load the composition plan from the backend. Try switching mode again.",
				);
			})
			.finally(() => {
				if (planFetchRef.current === fetchId) setPlanLoading(false);
			});
	}, [productId, wf.creativeMode, wf.recipeId, approvedCopySetId]);

	useEffect(() => {
		void fetchProductCatalog(60)
			.then((res) => setProducts(res.items ?? []))
			.catch((e: Error) =>
				setCatalogError(e.message || "Failed to load products."),
			);
	}, []);

	useEffect(() => {
		const asset = searchParams.get("reopen_asset");
		if (!asset) return;
		void fetchPosterDeliverableByAsset(asset)
			.then((d) => {
				setReopened(d);
				setReopenError("");
			})
			.catch(() =>
				setReopenError(
					"Failed to open the saved poster — the asset may have been deleted or is not a poster.",
				),
			);
	}, [searchParams]);

	// TRUE reopen restoration: once the reconstruction (and, when possible, the
	// catalog row) is in, restore the ENTIRE guided journey — the user must never
	// see an empty product-first wizard under the reopen card.
	// biome-ignore lint/correctness/useExhaustiveDependencies: one-shot restore guarded by restoredRef; wf identity churns every render
	useEffect(() => {
		if (!reopened || restoredRef.current) return;
		const pid = reopened.deliverable.product_id;
		const found = products.find((p) => p.id === pid) ?? null;
		// Wait for the catalog unless it already failed — then degrade gracefully.
		if (!found && products.length === 0 && !catalogError) return;
		restoredRef.current = true;
		const product =
			found ??
			({
				id: pid,
				product_display_name: "Product (reopened)",
			} as Product);
		wf.restoreFromReopen(reopened, product);
		// eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot restore
	}, [reopened, products, catalogError]);

	const recipeChoices = useMemo<PosterRecipe[]>(() => {
		if (!wf.goalArchetype) return recipes;
		const matching = recipes.filter((r) => r.archetype === wf.goalArchetype);
		return matching.length ? matching : recipes;
	}, [recipes, wf.goalArchetype]);

	const activeMeta =
		GUIDED_STEPS.find((s) => s.id === wf.step) ?? GUIDED_STEPS[0];
	const readyBanner = readinessBanner(wf.readiness?.poster_status);

	return (
		<section className="space-y-4" data-testid="poster-guided-shell">
			<header className="space-y-1">
				<h1 className="text-2xl font-bold text-slate-100">Poster Builder</h1>
				<p className="text-sm text-slate-400">
					Create product posters step by step — no technical terms
					required.
				</p>
			</header>

			<ErrorNote testid="poster-guided-reopen-error" text={reopenError} />
			{reopened ? <ReopenCard reopened={reopened} wf={wf} /> : null}

			<Stepper step={wf.step} canGoTo={wf.canGoTo} goTo={wf.goTo} />

			<div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
					<h2 className="mb-4 text-lg font-semibold text-slate-100">
						{activeMeta.heading}
					</h2>

					{wf.step === "product" ? (
						<ProductStep
							products={products}
							catalogError={catalogError}
							selected={wf.product}
							onSelect={wf.selectProduct}
						/>
					) : null}

					{wf.step === "goal" ? (
						<>
							{wf.readinessLoading ? (
								<Busy label="Checking product readiness…" />
							) : wf.readinessError ? (
								<div className="mb-4">
									<ErrorNote
										testid="poster-readiness-error"
										text={wf.readinessError}
									/>
								</div>
							) : (
								<div className="mb-4">
									<ReadinessBanner status={wf.readiness?.poster_status} />
								</div>
							)}
							<GoalStep
								wf={wf}
								blocked={!readyBanner.canProceed && !wf.readinessError}
							/>
						</>
					) : null}

					{wf.step === "angle" ? <AngleStep wf={wf} /> : null}
					{wf.step === "copy" ? <CopyStep wf={wf} /> : null}
					{wf.step === "approve" ? <ApproveStep wf={wf} /> : null}
					{wf.step === "visual" ? (
						<VisualStep wf={wf} recipes={recipeChoices} />
					) : null}
					{wf.step === "scene" ? <SceneStep wf={wf} /> : null}
					{wf.step === "compose" ? <ComposeStep wf={wf} /> : null}
					{wf.step === "save" ? <SaveStep wf={wf} /> : null}

					<StepNav wf={wf} />
				</div>

				<div className="space-y-4">
					<PosterSummary wf={wf} />
					<CompositionPlanSummary
						plan={compositionPlan}
						loading={planLoading}
						error={planError}
						compiledSignature={wf.deliverable?.composition_plan?.signature ?? ""}
					/>
				</div>
			</div>
		</section>
	);
}

// ── Steps ────────────────────────────────────────────────────────────────────

function ProductStep({
	products,
	catalogError,
	selected,
	onSelect,
}: {
	products: Product[];
	catalogError: string;
	selected: Product | null;
	onSelect: (p: Product | null) => void;
}) {
	const thumb = productThumb(selected);
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">Choose a product for this poster.</p>
			{catalogError ? (
				<p className="text-sm text-rose-300">{catalogError}</p>
			) : null}
			<SearchableProductSelect
				products={products}
				selectedProduct={selected}
				onSelect={onSelect}
			/>
			{selected ? (
				<div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3">
					{thumb ? (
						<img
							src={thumb}
							alt={selected.product_display_name}
							className="h-14 w-14 rounded-lg object-cover"
						/>
					) : (
						<div className="flex h-14 w-14 items-center justify-center rounded-lg bg-slate-800 text-slate-500">
							—
						</div>
					)}
					<div>
						<p className="text-sm font-semibold text-slate-100">
							{selected.product_display_name || selected.raw_product_title}
						</p>
						<p className="text-xs text-slate-500">
							{selected.category || selected.type_of_product || "Product"}
						</p>
					</div>
				</div>
			) : null}
		</div>
	);
}

type WF = ReturnType<typeof usePosterGuidedWorkflow>;

function GoalStep({ wf, blocked }: { wf: WF; blocked: boolean }) {
	// Goals whose claim lacks product evidence require an explicit confirmation
	// before selection ("requires product evidence").
	const [confirmArchetype, setConfirmArchetype] = useState<string | null>(null);
	return (
		<div className="space-y-4">
			<div className="flex items-center justify-between gap-2">
				<p className="text-sm text-slate-400">
					Choose the poster's main goal. We can suggest the best one.
				</p>
				<button
					type="button"
					data-testid="poster-goal-recommend"
					onClick={() => void wf.recommendGoals()}
					disabled={wf.goalsLoading}
					className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-100 disabled:opacity-50"
				>
					{wf.goalsLoading ? (
						<Loader2 className="h-3.5 w-3.5 animate-spin" />
					) : (
						<Sparkles className="h-3.5 w-3.5" />
					)}
					Suggest for me
				</button>
			</div>
			<ErrorNote testid="poster-goals-error" text={wf.goalsError} />
			<div className="grid gap-3 sm:grid-cols-2">
				{GUIDED_GOALS.map((g) => {
					const rec = wf.objectiveRecs.find((r) => r.archetype === g.archetype);
					const recommended = wf.recommendedArchetype === g.archetype;
					const evidence = goalEvidence(g.archetype, wf.product);
					const needsConfirm = !evidence.supported;
					const confirming = confirmArchetype === g.archetype;
					return (
						<SelectCard
							key={g.archetype}
							testid={`poster-goal-card-${g.archetype}`}
							selected={wf.goalArchetype === g.archetype}
							disabled={blocked}
							onClick={() => {
								if (needsConfirm && !confirming) {
									setConfirmArchetype(g.archetype);
									return;
								}
								setConfirmArchetype(null);
								wf.selectGoal(g.archetype, rec?.recipe_id, rec?.objective);
							}}
							badge={
								recommended ? (
									<span className="absolute right-3 top-3 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-200">
										Recommended ✦
									</span>
								) : needsConfirm ? (
									<span
										className="absolute right-3 top-3 rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-200"
										data-testid={`poster-goal-evidence-${g.archetype}`}
									>
										Needs product evidence
									</span>
								) : undefined
							}
						>
							<p className="font-semibold text-slate-100">{g.title}</p>
							<p className="mt-1 text-xs text-slate-400">{g.description}</p>
							{rec?.reason ? (
								<p className="mt-2 text-[11px] text-emerald-300/80">
									{rec.reason}
								</p>
							) : null}
							{confirming ? (
								<p
									className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-100"
									data-testid={`poster-goal-confirm-${g.archetype}`}
								>
									{evidence.requirement} Click again to proceed with human
									review.
								</p>
							) : null}
						</SelectCard>
					);
				})}
			</div>
		</div>
	);
}

function AngleStep({ wf }: { wf: WF }) {
	// biome-ignore lint/correctness/useExhaustiveDependencies: auto-load once per goal; wf identity churns every render
	useEffect(() => {
		if (
			wf.goalArchetype &&
			wf.angles.length === 0 &&
			!wf.anglesLoading &&
			!wf.anglesError
		)
			void wf.loadAngles();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [wf.goalArchetype]);
	const [custom, setCustom] = useState("");
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Choose a selling angle for{" "}
				{goalForArchetype(wf.goalArchetype ?? "").title}.
			</p>
			<label className="block text-xs text-slate-300">Creative Direction
				<select data-testid="poster-creative-mode" value={wf.creativeMode} onChange={(event) => wf.setCreativeMode(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2">
						<option value="">No governed mode (legacy)</option><option value="CREATIVE_CAMPAIGN">Creative Campaign (provider poster)</option><option value="PGC_CAMPAIGN">PGC Campaign</option><option value="UGC_AUTHENTIC">UGC Authentic</option><option value="MODEL_AMBASSADOR">Model Ambassador</option><option value="CLEAN_STUDIO_CATALOGUE">Clean Studio / Clean Catalogue</option><option value="LIFESTYLE_EDITORIAL">Lifestyle Editorial</option>
				</select>
			</label>
			{wf.anglesLoading ? <Busy label="Generating selling angles…" /> : null}
			{wf.anglesError ? (
				<div className="flex items-center gap-3">
					<ErrorNote testid="poster-angles-error" text={wf.anglesError} />
					<button
						type="button"
						onClick={() => void wf.loadAngles()}
						className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200"
					>
						Try again
					</button>
				</div>
			) : null}
			<div className="grid gap-3">
				{wf.angles.map((a, i) => (
					<SelectCard
						key={a.angle}
						testid={`poster-angle-card-${i}`}
						selected={wf.selectedAngle === a.angle}
						onClick={() => wf.selectAngle(a.angle)}
					>
						<p className="font-semibold text-slate-100">{a.angle}</p>
						{a.rationale ? (
							<p className="mt-1 text-xs text-slate-400">{a.rationale}</p>
						) : null}
					</SelectCard>
				))}
			</div>
			<div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-3">
				<label
					className="text-xs font-semibold text-slate-300"
					htmlFor="poster-angle-custom-input"
				>
					Or write your own angle
				</label>
				<div className="mt-2 flex gap-2">
					<input
						id="poster-angle-custom-input"
						data-testid="poster-angle-custom"
						value={custom}
						onChange={(e) => setCustom(e.target.value)}
						placeholder="e.g. great for special gifts"
						className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
					/>
					<button
						type="button"
						disabled={!custom.trim()}
						onClick={() => wf.selectAngle(custom.trim())}
						className="rounded-lg bg-slate-800 px-3 py-2 text-sm font-semibold text-slate-100 disabled:opacity-40"
					>
						Use
					</button>
				</div>
			</div>
		</div>
	);
}

function CopyStep({ wf }: { wf: WF }) {
	// biome-ignore lint/correctness/useExhaustiveDependencies: auto-load once per angle; wf identity churns every render
	useEffect(() => {
		if (
			wf.selectedAngle &&
			wf.directions.length === 0 &&
			!wf.directionsLoading &&
			!wf.directionsError &&
			// Version-edit / historical flows arrive with fields already loaded —
			// don't fire an unrequested directions call over them.
			!wf.editingCopySetId &&
			!wf.historicalCopySet
		)
			void wf.loadDirections();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [wf.selectedAngle]);

	// Historical (superseded) copy is read-only: show it + the fork action.
	if (wf.historicalCopySet) {
		return (
			<div className="space-y-3" data-testid="poster-copy-historical">
				<p className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
					This poster text is a HISTORICAL VERSION (superseded) and remains
					read-only. To edit, create an editable copy — the original record
					will not be changed.
				</p>
				<div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-950/40 p-4 text-sm">
					<Review label="Primary Message" value={wf.fields.primary_message} />
					<Review label="Support Message" value={wf.fields.support_message} />
					<Review
						label="Proof Points"
						value={wf.fields.proof_points.join(", ") || "—"}
					/>
					<Review label="CTA" value={wf.fields.cta} />
				</div>
				<ErrorNote testid="poster-fork-error" text={wf.forkError} />
				<button
					type="button"
					data-testid="poster-fork-historical"
					onClick={() => void wf.forkHistorical()}
					disabled={wf.forkLoading}
					className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
				>
					{wf.forkLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
					Create an editable copy
				</button>
			</div>
		);
	}
	const hasFallbackDirections =
		wf.directions.length > 0 &&
		wf.directionWarnings.some(
			(w) =>
				w.startsWith("AI directions unavailable:") ||
				w.startsWith("AI provider not configured"),
		);
	const visibleDirectionWarnings = wf.directionWarnings.filter(
		(w) =>
			!hasFallbackDirections ||
			(!w.startsWith("AI directions unavailable:") &&
				!w.startsWith("AI provider not configured")),
	);

	return (
		<div className="space-y-4">
			{wf.editingCopySetId ? (
				<p
					className="rounded-xl border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm text-sky-100"
					data-testid="poster-copy-editing-version"
				>
					You are editing a NEW VERSION of the approved text. Approve
					again when done — the old version stays on record.
				</p>
			) : null}
			<div className="flex items-center justify-between">
				<p className="text-sm text-slate-400">
					Compare three poster text directions and pick one.
				</p>
				<button
					type="button"
					data-testid="poster-copy-regen-all"
					onClick={() => void wf.loadDirections()}
					disabled={wf.directionsLoading}
					className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 disabled:opacity-50"
				>
					<RefreshCw className="h-3.5 w-3.5" /> Regenerate
				</button>
			</div>
			{wf.directionsLoading ? <Busy label="Generating text directions…" /> : null}
			<ErrorNote testid="poster-directions-error" text={wf.directionsError} />
			{wf.directionWarnings.length ? (
				<div
					className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100"
					data-testid="poster-direction-warnings"
				>
					{hasFallbackDirections ? (
						<p className="font-semibold" data-testid="poster-direction-fallback-note">
							AI is not available right now — safe suggestions are still available.
							Pick one to continue.
						</p>
					) : null}
					{visibleDirectionWarnings.length ? (
						<>
							<p className="mt-1 font-semibold">Notes while generating text:</p>
							<ul className="mt-1 space-y-0.5">
								{visibleDirectionWarnings.map((w) => (
							<li key={w}>• {w}</li>
									))}
							</ul>
						</>
					) : null}
				</div>
			) : null}
			<div className="grid gap-3 md:grid-cols-3">
				{wf.directions.map((d, i) => (
					<SelectCard
						key={`${d.primary_message}-${d.cta}`}
						testid={`poster-copy-direction-${i}`}
						selected={wf.selectedDirection === i}
						onClick={() => wf.selectDirection(i)}
					>
						<p className="text-sm font-bold text-slate-100">
							{d.primary_message}
						</p>
						<p className="mt-1 text-xs text-slate-400">{d.support_message}</p>
						{d.proof_points.length ? (
							<ul className="mt-2 space-y-0.5">
								{d.proof_points.map((p) => (
									<li key={p} className="text-[11px] text-emerald-300/80">
										• {p}
									</li>
								))}
							</ul>
						) : null}
						<p className="mt-2 text-xs font-semibold text-slate-300">{d.cta}</p>
						<p className="mt-1 text-[10px] uppercase tracking-wide text-slate-500">
							{d.tone}
						</p>
					</SelectCard>
				))}
			</div>
			{wf.selectedDirection !== null || wf.editingCopySetId ? (
				<CopyEditor wf={wf} />
			) : null}
		</div>
	);
}

function CopyEditor({ wf }: { wf: WF }) {
	return (
		<div
			className="space-y-3 rounded-2xl border border-slate-800 bg-slate-950/40 p-4"
			data-testid="poster-copy-editor"
		>
			<p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
				Edit the selected text
			</p>
			<ErrorNote testid="poster-regen-error" text={wf.fieldRegenError} />
			{FIELD_LABELS.map(({ key, label }) => (
				<div key={key}>
					<div className="mb-1 flex items-center justify-between">
						<label
							className="text-xs font-semibold text-slate-300"
							htmlFor={`poster-field-${key}`}
						>
							{label}
						</label>
						<button
							type="button"
							data-testid={`poster-regen-${key}`}
							onClick={() => void wf.regenField(key)}
							disabled={wf.fieldRegenLoading === key}
							className="flex items-center gap-1 text-[11px] text-emerald-300 disabled:opacity-40"
						>
							{wf.fieldRegenLoading === key ? (
								<Loader2 className="h-3 w-3 animate-spin" />
							) : (
								<RefreshCw className="h-3 w-3" />
							)}
							Regenerate
						</button>
					</div>
					<input
						id={`poster-field-${key}`}
						data-testid={`poster-field-${key}`}
						value={wf.fields[key] as string}
						onChange={(e) => wf.updateField(key, e.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
					/>
				</div>
			))}
			<div>
				<label
					className="text-xs font-semibold text-slate-300"
					htmlFor="poster-field-proof_points"
				>
					Proof Points
				</label>
				<input
					id="poster-field-proof_points"
					data-testid="poster-field-proof_points"
					value={wf.fields.proof_points.join(" | ")}
					onChange={(e) =>
						wf.updateField(
							"proof_points",
							e.target.value
								.split("|")
								.map((s) => s.trim())
								.filter(Boolean),
						)
					}
					placeholder="Separate with |"
					className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
				/>
			</div>
		</div>
	);
}

function ApproveStep({ wf }: { wf: WF }) {
	if (wf.approvedCopySet) {
		return (
			<div
				className="space-y-2 rounded-2xl border border-emerald-600/40 bg-emerald-500/10 p-4"
				data-testid="poster-copy-approved"
			>
				<p className="flex items-center gap-2 text-sm font-semibold text-emerald-100">
					<Check className="h-4 w-4" /> Poster text approved (version{" "}
					{wf.approvedCopySet.version})
				</p>
				<p className="text-xs text-emerald-200/80">
					The approved text is now read-only. To edit, the system will
					create a new version.
				</p>
				<button
					type="button"
					data-testid="poster-copy-edit-new-version"
					onClick={() => void wf.editApproved()}
					className="mt-1 rounded-lg border border-emerald-400/50 bg-emerald-500/20 px-3 py-1.5 text-xs font-semibold text-emerald-50"
				>
					Edit (create a new version)
				</button>
			</div>
		);
	}
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Review the final text. Once approved, the text becomes read-only.
			</p>
			{wf.editingCopySetId ? (
				<p
					className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs text-sky-100"
					data-testid="poster-approve-editing-version"
				>
					Approving will update the existing version draft — no duplicate text
					set will be created.
				</p>
			) : null}
			<div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-950/40 p-4 text-sm">
				<Review label="Primary Message" value={wf.fields.primary_message} />
				<Review label="Support Message" value={wf.fields.support_message} />
				<Review
					label="Proof Points"
					value={wf.fields.proof_points.join(", ") || "—"}
				/>
				<Review label="CTA" value={wf.fields.cta} />
				{wf.fields.disclaimer ? (
					<Review label="Disclaimer" value={wf.fields.disclaimer} />
				) : null}
			</div>
			<ErrorNote testid="poster-approve-error" text={wf.approveError} />
			<button
				type="button"
				data-testid="poster-approve-copy"
				onClick={() => void wf.approve()}
				disabled={wf.approveLoading || !wf.fields.primary_message}
				className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
			>
				{wf.approveLoading ? (
					<Loader2 className="h-4 w-4 animate-spin" />
				) : null}
				Approve poster text
			</button>
		</div>
	);
}

function Review({ label, value }: { label: string; value: string }) {
	return (
		<div>
			<span className="text-xs font-semibold text-slate-500">{label}: </span>
			<span className="text-slate-200">{value || "—"}</span>
		</div>
	);
}

// Mini layout diagram: the recipe zone map + product region drawn to scale so
// the operator SEES where text and product will sit (no recipe IDs shown).
function RecipeMiniDiagram({ recipe }: { recipe: PosterRecipe }) {
	return (
		<div
			className="relative h-40 w-24 shrink-0 overflow-hidden rounded-md border border-slate-700 bg-slate-800/60"
			data-testid={`poster-visual-diagram-${recipe.recipe_id}`}
			aria-hidden="true"
		>
			{(recipe.zones ?? []).map((z) => (
				<div
					key={z.zone_id}
					className={[
						"absolute rounded-[2px] border",
						z.role === "CTA"
							? "border-emerald-400/60 bg-emerald-400/30"
							: z.role === "CHIP"
								? "border-sky-400/50 bg-sky-400/20"
								: "border-slate-400/50 bg-slate-300/20",
					].join(" ")}
					style={{
						left: `${z.x}%`,
						top: `${z.y}%`,
						width: `${z.w}%`,
						height: `${z.h}%`,
					}}
				/>
			))}
		</div>
	);
}

// Friendly product-placement phrasing from the recipe contract (no jargon).
function placementLabel(recipe: PosterRecipe): string {
	const p = (recipe.product_placement || "").toLowerCase();
	if (p.includes("center") || p.includes("tengah")) return "Product centered";
	if (p.includes("bottom") || p.includes("bawah"))
		return "Product at the bottom";
	if (p.includes("hand") || p.includes("tangan")) return "Product held in hand";
	return recipe.product_placement || "Product as focus";
}

function VisualStep({ wf, recipes }: { wf: WF; recipes: PosterRecipe[] }) {
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Choose the poster's visual style. The small diagram shows the text layout
				(grey), chip (blue), CTA (green).
			</p>
			{recipes.length === 0 ? (
				<Busy label="Loading visual styles…" />
			) : (
				<div className="grid gap-3 sm:grid-cols-2">
					{recipes.map((r) => (
						<SelectCard
							key={r.recipe_id}
							testid={`poster-visual-card-${r.recipe_id}`}
							selected={wf.recipeId === r.recipe_id}
							onClick={() => wf.selectRecipe(r.recipe_id)}
						>
							<div className="flex gap-3">
								<RecipeMiniDiagram recipe={r} />
								<div className="min-w-0">
									<p className="font-semibold text-slate-100">{r.label}</p>
									<p className="mt-1 text-xs text-slate-400">{r.description}</p>
									<p className="mt-2 text-[11px] text-slate-300">
										<span className="text-slate-500">Best for: </span>
										{goalForArchetype(r.archetype).title}
									</p>
									<p className="text-[11px] text-slate-300">
										<span className="text-slate-500">Product placement: </span>
										{placementLabel(r)}
									</p>
									{r.allowed_text_density?.length ? (
										<p className="text-[11px] text-slate-300">
											<span className="text-slate-500">Text density: </span>
											{r.allowed_text_density.join(", ").toLowerCase()}
										</p>
									) : null}
								</div>
							</div>
						</SelectCard>
					))}
				</div>
			)}
		</div>
	);
}

// ── Poster visual source (native generation first; existing assets optional) ─
function SceneStep({ wf }: { wf: WF }) {
	const [artifacts, setArtifacts] = useState<ImageArtifact[] | null>(null);
	const [artifactsError, setArtifactsError] = useState("");
	const [loading, setLoading] = useState(false);
	const [existingOpen, setExistingOpen] = useState(false);
	const [creditConfirmOpen, setCreditConfirmOpen] = useState(false);
	const [creditConfirmed, setCreditConfirmed] = useState(false);
	const [truthLock, setTruthLock] = useState<ProductTruthLockStatus | null>(null);
	const [truthLoading, setTruthLoading] = useState(false);
	const [truthApproving, setTruthApproving] = useState(false);
	const [truthError, setTruthError] = useState("");
	const [referencePack, setReferencePack] = useState<ProductReferencePackSummary | null>(null);
	const [referencePackLoading, setReferencePackLoading] = useState(false);
	const [referencePackApproving, setReferencePackApproving] = useState(false);
	const [referencePackError, setReferencePackError] = useState("");
	const [reviewedBy, setReviewedBy] = useState("");
	const [confirmIdentity, setConfirmIdentity] = useState(false);
	const [confirmLabelLogo, setConfirmLabelLogo] = useState(false);
	const [confirmGeometryScale, setConfirmGeometryScale] = useState(false);
	const [confirmProductIsolation, setConfirmProductIsolation] = useState(false);

	useEffect(() => {
		let active = true;
		setReferencePack(null);
		setReferencePackError("");
		if (!wf.product || wf.creativeMode !== "CREATIVE_CAMPAIGN") {
			setReferencePackLoading(false);
			return () => {
				active = false;
			};
		}
		setReferencePackLoading(true);
		void fetchProductReferencePack(wf.product.id)
			.then((pack) => {
				if (active) setReferencePack(pack);
			})
			.catch((error) => {
				if (active) {
					setReferencePackError(
						error instanceof Error
							? error.message
							: "Failed to load the Product Reference Pack.",
					);
				}
			})
			.finally(() => {
				if (active) setReferencePackLoading(false);
			});
		return () => {
			active = false;
		};
	}, [wf.product, wf.creativeMode]);

	useEffect(() => {
		let active = true;
		setTruthLock(null);
		setTruthError("");
		setReviewedBy("");
		setConfirmIdentity(false);
		setConfirmLabelLogo(false);
		setConfirmGeometryScale(false);
		setConfirmProductIsolation(false);
		if (!wf.product || wf.creativeMode === "CREATIVE_CAMPAIGN") {
			return () => {
				active = false;
			};
		}
		setTruthLoading(true);
		void fetchProductTruthLock(wf.product.id)
			.then((status) => {
				if (active) setTruthLock(status);
			})
			.catch((error) => {
				if (active) {
					setTruthError(
						error instanceof Error
							? error.message
							: "Failed to check the product verification status.",
					);
				}
			})
			.finally(() => {
				if (active) setTruthLoading(false);
			});
		return () => {
			active = false;
		};
	}, [wf.product, wf.creativeMode]);

	const approveTruthLock = async () => {
		if (!wf.product) return;
		setTruthApproving(true);
		setTruthError("");
		try {
			const status = await approveProductTruthLock(wf.product.id, {
				reviewed_by: reviewedBy.trim(),
				review_note:
					"Operator reviewed the displayed cutout for identity, colour, label/logo, geometry, and scale.",
				confirm_identity: confirmIdentity,
				confirm_label_logo: confirmLabelLogo,
				confirm_geometry_scale: confirmGeometryScale,
				confirm_product_isolation: confirmProductIsolation,
			});
			setTruthLock(status);
		} catch (error) {
			setTruthError(
				error instanceof Error
					? error.message
					: "Failed to approve the product truth lock.",
			);
		} finally {
			setTruthApproving(false);
		}
	};

	const approveReferencePack = async () => {
		if (!wf.product || !reviewedBy.trim()) return;
		setReferencePackApproving(true);
		setReferencePackError("");
		try {
			const pack = await approveProductReferencePack(wf.product.id, {
				reviewed_by: reviewedBy.trim(),
				note: "Operator reviewed canonical, label/logo candidates and scale evidence before Creative Campaign generation.",
			});
			setReferencePack(pack);
		} catch (error) {
			setReferencePackError(
				error instanceof Error
					? error.message
					: "Failed to approve the Product Reference Pack.",
			);
		} finally {
			setReferencePackApproving(false);
		}
	};

	const truthPending = truthLock?.review_status === "PENDING_REVIEW";
	const truthConfirmed = truthLock?.exact_allowed === true;
	const allTruthConfirmed =
		reviewedBy.trim().length > 0 &&
		confirmIdentity &&
		confirmLabelLogo &&
		confirmGeometryScale &&
		confirmProductIsolation;

	const load = () => {
		setLoading(true);
		setArtifactsError("");
		void fetchImageArtifacts(30)
			.then((items) => setArtifacts(items))
			.catch(() =>
				setArtifactsError(
					"Failed to load the scene list. Check the agent connection and try again.",
				),
			)
			.finally(() => setLoading(false));
	};

	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Poster Builder will generate a new visual using the selected product,
				visual style and approved text. You don't need to pick an old image at
				this step.
			</p>
			<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
				Product identity is reference-conditioned — make sure the label & scale
				are reviewed before publishing.
			</div>
			{wf.creativeMode === "CREATIVE_CAMPAIGN" ? (
				<div
					className="space-y-3 rounded-xl border border-cyan-500/40 bg-cyan-500/10 p-4"
					data-testid="poster-reference-pack-review-panel"
				>
					<div>
						<p className="font-semibold text-cyan-100">Product Reference Pack</p>
						<p className="mt-1 text-xs text-cyan-100/80">
							Creative Campaign does not require a legacy scene asset. Review the canonical pack,
							label/logo candidates and scale evidence before the provider accepts the IMG job.
						</p>
					</div>
					{referencePackLoading ? <Busy label="Preparing the Product Reference Pack…" /> : null}
					{referencePack ? (
						<>
							<div className="grid gap-2 text-xs text-slate-100 sm:grid-cols-2">
								<div>Status: <strong>{referencePack.pack_status}</strong></div>
								<div>Machine QA: <strong>{referencePack.machine_qa_status}</strong></div>
								<div>
									Roles: <strong>{(referencePack.references || []).map((item) => `${item.role}${item.approved ? " ✓" : " · review"}`).join(", ") || "none"}</strong>
								</div>
								<div>
									Scale: <strong>{referencePack.physical_measurements?.scale_confidence || "UNVERIFIED"}</strong>
								</div>
							</div>
							{referencePack.pack_status !== "APPROVED" ? (
								<>
									<label className="grid gap-1 text-xs text-slate-100">
										<span className="font-semibold">Reviewer name</span>
										<input
											value={reviewedBy}
											onChange={(event) => setReviewedBy(event.target.value)}
											placeholder="Enter reviewer name"
											data-testid="poster-reference-pack-reviewed-by"
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
										/>
									</label>
									<p className="text-xs text-amber-100/80">
										Approval only approves the reference pack. Every generated poster remains
										machine-checked and separately human-reviewed.
									</p>
									<button
										type="button"
										onClick={() => void approveReferencePack()}
										disabled={!reviewedBy.trim() || referencePackApproving || referencePack.machine_qa_status === "FAIL"}
										data-testid="poster-reference-pack-approve"
										className="rounded-lg bg-cyan-400 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-50"
									>
										{referencePackApproving ? "Approving…" : "Approve Product Reference Pack"}
									</button>
								</>
							) : (
								<p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
									Reference pack approved. Generated output still requires independent human approval.
								</p>
							)}
						</>
					) : null}
					<ErrorNote testid="poster-reference-pack-error" text={referencePackError} />
				</div>
			) : null}

			{truthLoading ? <Busy label="Checking the product identity lock…" /> : null}
			{truthPending && wf.product && wf.creativeMode !== "CREATIVE_CAMPAIGN" ? (
				<div
					className="space-y-3 rounded-xl border border-amber-400/50 bg-amber-500/10 p-4"
					data-testid="poster-truth-review-panel"
				>
					<div>
						<p className="font-semibold text-amber-100">
							Product review required before generating the visual
						</p>
						<p className="mt-1 text-xs text-amber-100/80">
							Review the actual cutout below. Generation stays blocked and
							no IMG job is sent until every confirmation is made.
						</p>
					</div>
					<img
						src={productTruthCutoutPreviewUrl(wf.product.id)}
						alt={`Cutout for review of ${wf.product.product_display_name || "produk"}`}
						className="max-h-80 w-full rounded-lg border border-slate-700 bg-white/5 object-contain"
						data-testid="poster-truth-cutout-preview"
					/>
					<div className="grid gap-2 text-xs text-slate-100">
						<label className="grid gap-1">
							<span className="font-semibold">Reviewer name</span>
							<input
								type="text"
								value={reviewedBy}
								onChange={(event) => setReviewedBy(event.target.value)}
								placeholder="Enter reviewer name"
								data-testid="poster-truth-reviewed-by"
								className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
							/>
						</label>
						<label className="flex items-start gap-2">
							<input
								type="checkbox"
								checked={confirmIdentity}
								onChange={(event) => setConfirmIdentity(event.target.checked)}
								data-testid="poster-truth-confirm-identity"
							/>
							<span>Product identity and colour are accurate.</span>
						</label>
						<label className="flex items-start gap-2">
							<input
								type="checkbox"
								checked={confirmLabelLogo}
								onChange={(event) => setConfirmLabelLogo(event.target.checked)}
								data-testid="poster-truth-confirm-label-logo"
							/>
							<span>Label and logo are accurate and identifiable.</span>
						</label>
						<label className="flex items-start gap-2">
							<input
								type="checkbox"
								checked={confirmGeometryScale}
								onChange={(event) => setConfirmGeometryScale(event.target.checked)}
								data-testid="poster-truth-confirm-geometry-scale"
							/>
							<span>Cutout geometry and scale are accurate.</span>
						</label>
						<label className="flex items-start gap-2">
							<input
								type="checkbox"
								checked={confirmProductIsolation}
								onChange={(event) => setConfirmProductIsolation(event.target.checked)}
								data-testid="poster-truth-confirm-product-isolation"
							/>
							<span>Product only — no props, food, decorations, or other objects left behind.</span>
						</label>
					</div>
					<button
						type="button"
						onClick={() => void approveTruthLock()}
						disabled={!allTruthConfirmed || truthApproving}
						data-testid="poster-truth-approve"
						className="rounded-lg bg-amber-400 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-50"
					>
						{truthApproving ? "Approving…" : "Approve product review"}
					</button>
				</div>
			) : null}
			{truthConfirmed && wf.creativeMode !== "CREATIVE_CAMPAIGN" ? (
				<p
					className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100"
					data-testid="poster-truth-approved"
				>
					Product identity, label/logo, geometry and scale have been approved.
				</p>
			) : null}
			<ErrorNote testid="poster-truth-review-error" text={truthError} />

			<div
				className="space-y-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4"
				data-testid="poster-scene-generation-panel"
			>
				<div>
					<p className="font-semibold text-slate-100">Generate the poster visual</p>
					<p className="mt-1 text-xs text-slate-400">
						{wf.creativeMode === "CREATIVE_CAMPAIGN"
							? "Creative Campaign sends the nine-section prompt together with the Product Reference Pack to the provider. The provider produces the complete poster; an old scene is not required."
							: "A new visual uses the product reference locked by the system. Exact Commerce still uses the compositor as a fallback. "}
						This IMG does not use generation credits; Google Flow credits apply to
						video only. The confirmation below only confirms that one IMG operation will be sent.
					</p>
				</div>
				{wf.sceneGenerationLoading ? (
					<Busy
						label={
							{
								building_prompt: "Preparing visual instructions…",
								validating_product: "Validating product reference…",
						preparing_exact_scene: "Preparing the exact-product visual…",
						compiling_creative_prompt: "Compiling the Creative Campaign prompt…",
								generating_scene: "Sending the IMG job…",
								waiting_for_scene: "Waiting for the visual to finish…",
							}[wf.sceneGenerationStage] || "Processing the visual…"
						}
					/>
				) : null}
				<ErrorNote
					testid="poster-scene-generation-error"
					text={wf.sceneGenerationError}
				/>
				<button
					type="button"
					data-testid="poster-generate-scene"
						disabled={
							wf.sceneGenerationLoading ||
							(wf.creativeMode === "CREATIVE_CAMPAIGN" &&
								(referencePackLoading || referencePack?.pack_status !== "APPROVED")) ||
							(wf.creativeMode !== "CREATIVE_CAMPAIGN" &&
									(truthLoading || truthPending))
							}
					onClick={() => {
						setCreditConfirmed(false);
						setCreditConfirmOpen(true);
					}}
					className="rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-50"
				>
					{wf.generatedSceneMediaId ? "Regenerate visual" : "Generate the poster visual"}
				</button>
				{creditConfirmOpen ? (
					<div
						className="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3"
						data-testid="poster-generate-scene-confirm"
					>
						<p className="text-xs text-amber-100">
							Confirm once more to send one IMG job. This image operation
							does not use generation credits; no job is sent before
							this confirmation.
						</p>
						<label className="flex items-start gap-2 text-xs text-slate-200">
							<input
								type="checkbox"
								data-testid="poster-generate-scene-credit-checkbox"
								checked={creditConfirmed}
								onChange={(event) => setCreditConfirmed(event.target.checked)}
								className="mt-0.5"
							/>
							<span>
								I understand this action sends one IMG job with no generation-credit
								charge.
							</span>
						</label>
						<div className="flex gap-2">
							<button
								type="button"
								data-testid="poster-generate-scene-credit-cancel"
								onClick={() => setCreditConfirmOpen(false)}
								className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200"
							>
								Cancel
							</button>
							<button
								type="button"
								data-testid="poster-generate-scene-credit-confirm"
								disabled={!creditConfirmed || wf.sceneGenerationLoading}
								onClick={() => {
									setCreditConfirmOpen(false);
									void wf.generateScene();
								}}
								className="rounded-lg bg-amber-400 px-3 py-1.5 text-xs font-bold text-slate-950 disabled:opacity-50"
							>
								Continue generating
							</button>
						</div>
					</div>
				) : null}
				{wf.generatedSceneMediaId ? (
					<div className="space-y-2" data-testid="poster-generated-scene">
						<p className="text-xs font-semibold text-emerald-200">
							A new visual is ready and selected for the poster.
						</p>
						<img
							src={
								wf.generatedSceneUrl ||
								`/api/flow/retrieved/${encodeURIComponent(wf.generatedSceneMediaId)}`
							}
							alt="Generated poster visual"
							className="max-h-72 rounded-lg border border-slate-800 object-contain"
						/>
					</div>
				) : null}
			</div>

			<details
				className="rounded-xl border border-slate-800 bg-slate-950/40 p-3"
				data-testid="poster-existing-scene-options"
				onToggle={(event) => {
					const open = event.currentTarget.open;
					setExistingOpen(open);
					if (open && artifacts === null && !loading) load();
				}}
			>
				<summary className="cursor-pointer text-xs font-semibold text-slate-400">
					Use an existing visual (optional)
				</summary>
				<p className="mt-2 text-[11px] text-slate-500">
					This is not a prerequisite. Existing visuals may expire after 48 hours;
					generate a new visual above for new poster work.
				</p>
				{existingOpen && loading ? <Busy label="Loading existing visuals…" /> : null}
				{existingOpen && artifactsError ? (
					<div className="space-y-2" data-testid="poster-scene-error">
						<ErrorNote testid="poster-scene-error-text" text={artifactsError} />
						<button
							type="button"
							data-testid="poster-scene-retry"
							onClick={load}
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200"
						>
							Try again
						</button>
					</div>
				) : null}
				{existingOpen && !loading && !artifactsError && artifacts?.length === 0 ? (
					<div
						className="mt-3 rounded-lg border border-slate-800 px-3 py-3 text-xs text-slate-400"
						data-testid="poster-scene-empty"
					>
						No existing visuals. This does not prevent generating a new poster visual.
					</div>
				) : null}
				{existingOpen && artifacts && artifacts.length > 0 ? (
					<div className="mt-3" data-testid="poster-scene-grid">
						<VisualAssetPicker
							items={artifacts.map((artifact) => {
								const expiring =
									typeof (artifact as { expires_in_hours?: number | null })
										.expires_in_hours === "number" &&
									((artifact as { expires_in_hours?: number | null })
										.expires_in_hours ?? 99) < 6;
								return {
									value: artifact.media_id,
									title: (artifact.mode || "Visual").toUpperCase(),
									subtitle: artifact.created_at
										? `${artifact.media_id} · ${artifact.created_at.slice(0, 10)}`
										: artifact.media_id,
									previewUrl: `/api/flow/retrieved/${encodeURIComponent(
										artifact.media_id,
									)}`,
									status: expiring ? "Expiring soon" : "Ready to use",
								};
							})}
							label="Existing poster image"
							onChange={wf.setBackgroundMediaId}
							placeholder="Choose an existing visual"
							value={wf.backgroundMediaId}
						/>
					</div>
				) : null}
			</details>

			<details className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
				<summary className="cursor-pointer text-xs font-semibold text-slate-400">
					Advanced Diagnostics
				</summary>
				<label
					className="mt-2 block text-xs font-semibold text-slate-300"
					htmlFor="poster-scene-bg-input"
				>
					Scene media ID (technicians only)
				</label>
				<input
					id="poster-scene-bg-input"
					data-testid="poster-scene-bg-input"
					value={wf.backgroundMediaId}
					onChange={(e) => wf.setBackgroundMediaId(e.target.value)}
					placeholder="existing scene media_id"
					className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
				/>
			</details>
		</div>
	);
}

function ComposeStep({ wf }: { wf: WF }) {
	const [reviewer, setReviewer] = useState("operator");
	const [reviewScores, setReviewScores] = useState({
		product_identity: 0,
		product_integration_physics: 0,
		typography_copy_hierarchy: 0,
		malaysian_context_authenticity: 0,
		conversion_strength: 0,
	});
	const updateScore = (key: keyof typeof reviewScores, value: string) =>
		setReviewScores((current) => ({ ...current, [key]: Number(value) || 0 }));
	const submitReview = (decision: "APPROVED" | "REVISION_REQUIRED") => {
		void wf.reviewCampaign({
			decision,
			reviewer: reviewer.trim() || "operator",
			...reviewScores,
			rejection_reasons: decision === "REVISION_REQUIRED" ? ["OTHER"] : [],
			review_notes:
				decision === "REVISION_REQUIRED"
					? "Operator requested another review after the visual inspection."
					: "Operator approved the World-Class Poster Review rubric.",
		});
	};
	if (wf.creativeMode === "CREATIVE_CAMPAIGN") {
		const qaReport = wf.deliverable?.qa_report;
		const campaignQa = qaReport?.campaign_qa;
		const review = qaReport?.world_class_review;
		const deliverableId = wf.deliverable?.deliverable.poster_deliverable_id ?? "";
		return (
			<div className="space-y-3">
				{wf.generatedSceneMediaId ? (
					<div className="rounded-xl border border-sky-500/30 bg-sky-500/10 p-3">
						<p className="text-sm font-semibold text-sky-100">
							Clean key visual from Google Flow — lineage only
						</p>
						<img
							data-testid="poster-creative-campaign-key-visual"
							src={
								wf.generatedSceneUrl ||
								`/api/flow/retrieved/${encodeURIComponent(wf.generatedSceneMediaId)}`
							}
							alt="Clean key visual Creative Campaign"
							className="mt-2 max-h-72 rounded-xl border border-slate-800 object-contain"
						/>
						<p className="mt-2 text-xs text-amber-200/90">
							Not the final poster. Deterministic copy is added only after the KV succeeds.
						</p>
					</div>
				) : (
					<p className="text-xs text-amber-200/90" data-testid="poster-compose-need-scene">
						Generate the clean key visual first in the Visual/Background step.
					</p>
				)}
				<button
					type="button"
					data-testid="poster-compose"
					onClick={() => void wf.compose()}
					disabled={wf.composeLoading || !wf.backgroundMediaId}
					className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
				>
					{wf.composeLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
					{wf.deliverable ? "Recompose poster" : "Compose the final poster"}
				</button>
				<ErrorNote testid="poster-compose-error" text={wf.composeError} />
				{wf.deliverable ? (
					<div className="space-y-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3">
						<p className="text-sm font-semibold text-emerald-100">
							Final poster — deterministic copy + lineage KV
						</p>
						<img
							data-testid="poster-creative-campaign-preview"
							src={posterDeliverableOutputUrl(deliverableId)}
							alt="Final Creative Campaign poster"
							className="max-h-96 rounded-xl border border-slate-800 object-contain"
						/>
						<div className="grid gap-2 sm:grid-cols-2">
							<button type="button" data-testid="poster-copy-edit-action" onClick={() => void wf.editApproved()} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200">
								Change copy only
							</button>
							<button type="button" data-testid="poster-layout-action" onClick={() => void wf.loadCampaignVariants()} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200">
								Change layout only
							</button>
							<button type="button" data-testid="poster-route-action" onClick={() => void wf.loadCampaignVariants()} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200">
								Change design route
						</button>
							<button type="button" data-testid="poster-new-kv-action" onClick={() => void wf.generateScene()} className="rounded-lg border border-amber-500/40 px-3 py-2 text-xs text-amber-100">
								Generate a new KV
							</button>
						</div>
						{wf.campaignVariantsLoading ? <Busy label="Preparing three deterministic variants…" /> : null}
						<ErrorNote testid="poster-variants-error" text={wf.campaignVariantsError} />
						{wf.campaignVariants ? (
							<div className="space-y-2" data-testid="poster-campaign-variants">
								<div className="flex items-center justify-between">
									<p className="text-xs font-semibold text-slate-200">Three controlled variants · same KV · provider ops 0</p>
									<button type="button" data-testid="poster-compare-variants" onClick={() => void wf.loadCampaignVariants()} className="rounded-lg border border-sky-500/40 px-2 py-1 text-xs text-sky-100">Compare</button>
								</div>
								<div className="grid gap-2 sm:grid-cols-3">
									{wf.campaignVariants.variants.map((variant) => (
										<figure key={variant.variant_id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
											<img src={posterCampaignVariantOutputUrl(deliverableId, variant.variant_id)} alt={`Variant ${variant.variant_index}`} className="max-h-64 w-full rounded object-contain" />
											<figcaption className="mt-1 text-[10px] text-slate-400">{variant.layout_variant} · {variant.manifest_sha256.slice(0, 10)}</figcaption>
										</figure>
									))}
								</div>
							</div>
						) : null}
						<div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3" data-testid="poster-world-class-review">
							<p className="text-xs font-semibold text-amber-100">World-Class Poster Review · {review?.decision ?? campaignQa?.campaign_review_status ?? "PENDING_HUMAN_REVIEW"}</p>
							<p className="mt-1 text-[11px] text-slate-400">Identity, label, scale, typography and physical integration are not auto-approved.</p>
							<div className="mt-2 grid gap-2 sm:grid-cols-2">
								<input value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-label="Reviewer" placeholder="Reviewer" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100" />
								<input type="number" min="0" max="25" value={reviewScores.product_identity} onChange={(e) => updateScore("product_identity", e.target.value)} aria-label="Product identity score" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100" />
								<input type="number" min="0" max="25" value={reviewScores.product_integration_physics} onChange={(e) => updateScore("product_integration_physics", e.target.value)} aria-label="Integration score" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100" />
								<input type="number" min="0" max="20" value={reviewScores.typography_copy_hierarchy} onChange={(e) => updateScore("typography_copy_hierarchy", e.target.value)} aria-label="Typography score" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100" />
								<input type="number" min="0" max="15" value={reviewScores.malaysian_context_authenticity} onChange={(e) => updateScore("malaysian_context_authenticity", e.target.value)} aria-label="Malaysian context score" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100" />
								<input type="number" min="0" max="15" value={reviewScores.conversion_strength} onChange={(e) => updateScore("conversion_strength", e.target.value)} aria-label="Conversion score" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100" />
							</div>
							<div className="mt-2 flex flex-wrap gap-2">
								<button type="button" data-testid="poster-review-approve" onClick={() => submitReview("APPROVED")} disabled={wf.campaignReviewLoading} className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-slate-950 disabled:opacity-50">Approve</button>
								<button type="button" data-testid="poster-review-reject" onClick={() => submitReview("REVISION_REQUIRED")} disabled={wf.campaignReviewLoading} className="rounded-lg border border-rose-500/50 px-3 py-1.5 text-xs text-rose-100 disabled:opacity-50">Reject with reason</button>
							</div>
							<ErrorNote testid="poster-review-error" text={wf.campaignReviewError} />
						</div>
						{campaignQa?.findings?.length ? <QaGroup testid="poster-campaign-qa-findings" tone="amber" title="Campaign Review" items={campaignQa.findings} /> : null}
					</div>
				) : null}
			</div>
		);
	}
	const qa = bucketQaFindings(wf.deliverable?.qa_report);
	return (
		<div className="space-y-3">
			{!wf.backgroundMediaId ? (
				<p
					className="text-xs text-amber-200/90"
					data-testid="poster-compose-need-scene"
				>
					Generate or choose the poster visual first in the Background step.
				</p>
			) : null}
			<button
				type="button"
				data-testid="poster-compose"
				onClick={() => void wf.compose()}
				disabled={wf.composeLoading || !wf.backgroundMediaId}
				className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
			>
				{wf.composeLoading ? (
					<Loader2 className="h-4 w-4 animate-spin" />
				) : null}
				{wf.deliverable ? "Produce again" : "Produce poster"}
			</button>
			<ErrorNote testid="poster-compose-error" text={wf.composeError} />
			{wf.deliverable ? (
				<div className="space-y-3">
					<img
						data-testid="poster-preview"
						src={posterDeliverableOutputUrl(
							wf.deliverable.deliverable.poster_deliverable_id,
						)}
						alt="Poster preview"
						className="max-h-96 rounded-xl border border-slate-800 object-contain"
					/>
					<div className="space-y-2">
						{qa.mustFix.length ? (
							<QaGroup
								testid="poster-qa-mustfix"
								tone="rose"
								title="Must Fix"
								items={qa.mustFix}
							/>
						) : null}
						{qa.review.length ? (
							<QaGroup
								testid="poster-qa-review"
								tone="amber"
								title="Recommended Review"
								items={qa.review}
							/>
						) : null}
						{qa.passed ? (
							<p
								className="rounded-lg border border-emerald-600/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100"
								data-testid="poster-qa-passed"
							>
								✓ All checks passed.
							</p>
						) : null}
					</div>
				</div>
			) : null}
		</div>
	);
}

function QaGroup({
	testid,
	tone,
	title,
	items,
}: {
	testid: string;
	tone: "rose" | "amber";
	title: string;
	items: string[];
}) {
	const cls =
		tone === "rose"
			? "border-rose-500/30 bg-rose-500/10 text-rose-100"
			: "border-amber-500/30 bg-amber-500/10 text-amber-100";
	return (
		<div
			className={`rounded-lg border px-3 py-2 text-sm ${cls}`}
			data-testid={testid}
		>
			<p className="font-semibold">{title}</p>
			<ul className="mt-1 space-y-0.5 text-xs">
				{items.map((m) => (
					<li key={m}>• {m}</li>
				))}
			</ul>
		</div>
	);
}

function SaveStep({ wf }: { wf: WF }) {
	const creativeOutput = wf.creativeMode === "CREATIVE_CAMPAIGN";
	return (
		<div className="space-y-3">
			{!wf.deliverable ? (
				<p className="text-sm text-slate-400">Produce the poster first.</p>
			) : wf.savedAssetId ? (
				<div
					className="space-y-2 rounded-2xl border border-emerald-600/40 bg-emerald-500/10 p-4"
					data-testid="poster-saved"
				>
					<p className="flex items-center gap-2 text-sm font-semibold text-emerald-100">
						<Check className="h-4 w-4" /> Poster saved to the Creative Library.
					</p>
					<img
						src={posterDeliverableOutputUrl(
							wf.deliverable?.deliverable.poster_deliverable_id || "",
						)}
						alt="Saved poster"
						className="max-h-72 rounded-lg border border-slate-800 object-contain"
					/>
				</div>
			) : (
				<>
					<p className="text-sm text-slate-400">
						Save the poster to the Creative Library to reuse & download.
						{creativeOutput
							? " The provider output stays PENDING_REVIEW until human review is complete."
							: ""}
					</p>
					<ErrorNote testid="poster-save-error" text={wf.saveError} />
					<button
						type="button"
						data-testid="poster-save"
						onClick={() => void wf.save()}
						disabled={wf.saveLoading}
						className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
					>
						{wf.saveLoading ? (
							<Loader2 className="h-4 w-4 animate-spin" />
						) : null}
						Save to the Creative Library
					</button>
				</>
			)}
		</div>
	);
}

// ── Continue / Back navigation ───────────────────────────────────────────────
function StepNav({ wf }: { wf: WF }) {
	const idx = stepIndex(wf.step);
	const prev = idx > 0 ? GUIDED_STEPS[idx - 1].id : null;

	// Which steps require an explicit Continue (others auto-advance on select).
	const continueTarget: Partial<Record<GuidedStepId, GuidedStepId>> = {
		copy: "approve",
		approve: "visual",
		scene: "compose",
		compose: "save",
	};
	const target = continueTarget[wf.step];
	const canContinue =
		(wf.step === "copy" &&
			(wf.selectedDirection !== null || !!wf.editingCopySetId)) ||
		(wf.step === "approve" && wf.approvedCopySet !== null) ||
		(wf.step === "scene" &&
			wf.recipeId !== null &&
			(wf.creativeMode === "CREATIVE_CAMPAIGN"
				? !!wf.generatedSceneMediaId
				: !!wf.backgroundMediaId)) ||
		(wf.step === "compose" &&
			(wf.creativeMode === "CREATIVE_CAMPAIGN"
				? !!wf.generatedSceneMediaId
				: wf.deliverable !== null));

	return (
		<div className="mt-5 flex items-center justify-between border-t border-slate-800 pt-4">
			<button
				type="button"
				data-testid="poster-guided-back"
				disabled={!prev || !wf.canGoTo(prev)}
				onClick={() => prev && wf.goTo(prev)}
				className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-30"
			>
				<ArrowLeft className="h-4 w-4" /> Back
			</button>
			{target ? (
				<button
					type="button"
					data-testid="poster-guided-continue"
					disabled={!canContinue}
					onClick={() => {
						wf.reach(target);
					}}
					className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-1.5 text-sm font-bold text-slate-950 disabled:opacity-40"
				>
					Continue <ArrowRight className="h-4 w-4" />
				</button>
			) : (
				<span className="text-xs text-slate-500">Select to continue</span>
			)}
		</div>
	);
}

// ── Sticky summary ───────────────────────────────────────────────────────────
function PosterSummary({ wf }: { wf: WF }) {
	return (
		<aside
			className="h-fit space-y-3 rounded-2xl border border-slate-800 bg-slate-950/40 p-4 lg:sticky lg:top-4"
			data-testid="poster-guided-summary"
		>
			<p className="text-xs font-bold uppercase tracking-wide text-slate-500">
				Summary
			</p>
			<SummaryRow label="Product" value={wf.product?.product_display_name} />
			<SummaryRow
				label="Goal"
				value={
					wf.goalArchetype
						? goalForArchetype(wf.goalArchetype).title
						: undefined
				}
			/>
			<SummaryRow label="Angle" value={wf.selectedAngle || undefined} />
			<SummaryRow
				label="Main text"
				value={wf.fields.primary_message || undefined}
			/>
			<SummaryRow
				label="Text status"
				value={
					wf.approvedCopySet
						? "Approved"
						: wf.historicalCopySet
							? "Historical version (read-only)"
							: wf.editingCopySetId
								? "New version draft"
								: wf.fields.primary_message
									? "Draft"
									: undefined
				}
			/>
			<SummaryRow
				label="Visual style"
				value={
					wf.recipeId
						? goalForArchetype(wf.goalArchetype ?? "").title
						: undefined
				}
			/>
			{wf.deliverable ? (
				<SummaryRow
					label="Product authenticity"
					value={truthLabel(wf.deliverable.deliverable.composition_strategy)}
				/>
			) : null}
		</aside>
	);
}

function SummaryRow({ label, value }: { label: string; value?: string }) {
	return (
		<div className="text-xs">
			<span className="text-slate-500">{label}</span>
			<p className={value ? "text-slate-200" : "text-slate-600"}>
				{value || "—"}
			</p>
		</div>
	);
}

// ── Reopen (Creative Library round trip) ────────────────────────────────────
function ReopenCard({
	reopened,
	wf,
}: {
	reopened: PosterDeliverableReconstruction;
	wf: WF;
}) {
	const historical = !!wf.historicalCopySet;
	const approvedCurrent = !!wf.approvedCopySet;
	const status = reopened.poster_copy_set?.status ?? "";
	const badge = historical
		? {
				label: "Historical version (read-only)",
				cls: "bg-amber-500/20 text-amber-100",
			}
		: status === "POSTER_COPY_APPROVED"
			? {
					label: "Current approved text",
					cls: "bg-emerald-500/20 text-emerald-100",
				}
			: { label: "Draft", cls: "bg-slate-700 text-slate-200" };
	return (
		<section
			className="rounded-2xl border border-emerald-700/40 bg-emerald-950/20 p-4"
			data-testid="poster-guided-reopen"
		>
			<div className="mb-3 flex items-center gap-2">
				<p className="text-[10px] font-bold uppercase tracking-wide text-emerald-400">
					Reopened from the Creative Library
				</p>
				<span
					className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}
				>
					{badge.label}
				</span>
			</div>
			<div className="flex flex-wrap gap-4">
				{reopened.output_available ? (
					<img
						src={posterDeliverableOutputUrl(
							reopened.deliverable.poster_deliverable_id,
						)}
						alt="Original saved poster"
						className="h-48 rounded-lg border border-slate-800 object-contain"
						data-testid="poster-guided-reopen-output"
					/>
				) : (
					<p className="text-xs text-amber-300">
						The original output is not available in this runtime.
					</p>
				)}
				<div className="space-y-1 text-xs text-slate-300">
					<p>
						<span className="text-slate-500">Output source: </span>
						<span data-testid="poster-guided-reopen-source">
							{reopened.output_available
								? reopened.output_source === "CREATIVE_LIBRARY"
									? "Creative Library copy (durable)"
									: "Original deliverable file"
								: "None"}
						</span>
					</p>
					<p>
						<span className="text-slate-500">Text: </span>
						{reopened.poster_copy_set?.primary_message ?? "—"}
					</p>
					<p className="text-[11px] text-slate-500">
						The entire workflow has been restored — you can navigate
						each step below.
					</p>
				</div>
			</div>
			<div className="mt-3 flex flex-wrap gap-2">
				{approvedCurrent ? (
					<>
						<button
							type="button"
							data-testid="poster-reopen-use-same-copy"
							onClick={() => wf.reuseSameCopy()}
							className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-100"
						>
							Use same text
						</button>
						<button
							type="button"
							data-testid="poster-reopen-new-version"
							onClick={() => void wf.editApproved()}
							className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-100"
						>
							Create a new version
						</button>
					</>
				) : null}
				{historical ? (
					<button
						type="button"
						data-testid="poster-reopen-fork-historical"
						onClick={() => void wf.forkHistorical()}
						disabled={wf.forkLoading}
						className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-100 disabled:opacity-50"
					>
						{wf.forkLoading
							? "Creating a copy…"
							: "Copy & edit (historical version kept)"}
					</button>
				) : null}
				<button
					type="button"
					data-testid="poster-reopen-duplicate"
					onClick={() => wf.duplicatePoster()}
					className="rounded-lg border border-slate-600 bg-slate-800/60 px-3 py-1.5 text-xs font-semibold text-slate-200"
				>
					Duplicate poster
				</button>
			</div>
			<ErrorNote testid="poster-reopen-fork-error" text={wf.forkError} />
		</section>
	);
}
