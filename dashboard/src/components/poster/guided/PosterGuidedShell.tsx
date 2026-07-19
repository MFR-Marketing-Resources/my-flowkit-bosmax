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
	fetchImageArtifacts,
	type ImageArtifact,
} from "../../../api/imgFactory";
import {
	fetchCompositionPlan,
	fetchPosterDeliverableByAsset,
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

	// B-04: BACKEND-resolved composition plan for the selected governed mode.
	// Refetched whenever the mode / product / recipe / approved copy changes;
	// the UI never derives plan values locally.
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
		if (!productId || !wf.creativeMode) {
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
					"Gagal mendapatkan pelan komposisi dari backend. Cuba tukar mod semula.",
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
				setCatalogError(e.message || "Gagal memuatkan produk."),
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
					"Gagal membuka poster tersimpan — aset mungkin telah dipadam atau bukan poster.",
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
				product_display_name: "Produk (dibuka semula)",
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
					Cipta poster produk langkah demi langkah — tiada istilah teknikal
					diperlukan.
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
								<Busy label="Menyemak kesediaan produk…" />
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
			<p className="text-sm text-slate-400">Pilih produk untuk poster ini.</p>
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
							{selected.category || selected.type_of_product || "Produk"}
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
					Pilih tujuan utama poster. Kami boleh mencadangkan yang terbaik.
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
					Cadangkan untuk saya
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
										Disyorkan ✦
									</span>
								) : needsConfirm ? (
									<span
										className="absolute right-3 top-3 rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-200"
										data-testid={`poster-goal-evidence-${g.archetype}`}
									>
										Perlukan bukti produk
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
									{evidence.requirement} Klik sekali lagi untuk teruskan dengan
									semakan manusia.
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
				Pilih sudut jualan untuk{" "}
				{goalForArchetype(wf.goalArchetype ?? "").title}.
			</p>
			<label className="block text-xs text-slate-300">Creative Direction
				<select data-testid="poster-creative-mode" value={wf.creativeMode} onChange={(event) => wf.setCreativeMode(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2">
					<option value="">No governed mode (legacy)</option><option value="PGC_CAMPAIGN">PGC Campaign</option><option value="UGC_AUTHENTIC">UGC Authentic</option><option value="MODEL_AMBASSADOR">Model Ambassador</option><option value="CLEAN_STUDIO_CATALOGUE">Clean Studio / Clean Catalogue</option><option value="LIFESTYLE_EDITORIAL">Lifestyle Editorial</option>
				</select>
			</label>
			{wf.anglesLoading ? <Busy label="Menjana sudut jualan…" /> : null}
			{wf.anglesError ? (
				<div className="flex items-center gap-3">
					<ErrorNote testid="poster-angles-error" text={wf.anglesError} />
					<button
						type="button"
						onClick={() => void wf.loadAngles()}
						className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200"
					>
						Cuba lagi
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
					Atau tulis sudut anda sendiri
				</label>
				<div className="mt-2 flex gap-2">
					<input
						id="poster-angle-custom-input"
						data-testid="poster-angle-custom"
						value={custom}
						onChange={(e) => setCustom(e.target.value)}
						placeholder="Cth: sesuai untuk hadiah istimewa"
						className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
					/>
					<button
						type="button"
						disabled={!custom.trim()}
						onClick={() => wf.selectAngle(custom.trim())}
						className="rounded-lg bg-slate-800 px-3 py-2 text-sm font-semibold text-slate-100 disabled:opacity-40"
					>
						Guna
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
					Teks poster ini adalah VERSI SEJARAH (telah digantikan) dan kekal
					kunci-baca. Untuk menyunting, cipta salinan boleh-edit — rekod asal
					tidak akan diubah.
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
					Cipta salinan boleh-edit
				</button>
			</div>
		);
	}

	return (
		<div className="space-y-4">
			{wf.editingCopySetId ? (
				<p
					className="rounded-xl border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm text-sky-100"
					data-testid="poster-copy-editing-version"
				>
					Anda sedang menyunting VERSI BAHARU teks yang diluluskan. Sahkan
					semula selepas selesai — versi lama kekal dalam rekod.
				</p>
			) : null}
			<div className="flex items-center justify-between">
				<p className="text-sm text-slate-400">
					Bandingkan tiga arah teks poster dan pilih satu.
				</p>
				<button
					type="button"
					data-testid="poster-copy-regen-all"
					onClick={() => void wf.loadDirections()}
					disabled={wf.directionsLoading}
					className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 disabled:opacity-50"
				>
					<RefreshCw className="h-3.5 w-3.5" /> Jana semula
				</button>
			</div>
			{wf.directionsLoading ? <Busy label="Menjana arah teks…" /> : null}
			<ErrorNote testid="poster-directions-error" text={wf.directionsError} />
			{wf.directionWarnings.length ? (
				<div
					className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100"
					data-testid="poster-direction-warnings"
				>
					<p className="font-semibold">Nota semasa menjana teks:</p>
					<ul className="mt-1 space-y-0.5">
						{wf.directionWarnings.map((w) => (
							<li key={w}>• {w}</li>
						))}
					</ul>
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
				Sunting teks pilihan
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
							Jana semula
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
					placeholder="Pisahkan dengan |"
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
					<Check className="h-4 w-4" /> Teks poster telah disahkan (versi{" "}
					{wf.approvedCopySet.version})
				</p>
				<p className="text-xs text-emerald-200/80">
					Teks yang diluluskan kini kunci-baca. Untuk menyunting, sistem akan
					mencipta versi baharu.
				</p>
				<button
					type="button"
					data-testid="poster-copy-edit-new-version"
					onClick={() => void wf.editApproved()}
					className="mt-1 rounded-lg border border-emerald-400/50 bg-emerald-500/20 px-3 py-1.5 text-xs font-semibold text-emerald-50"
				>
					Sunting (cipta versi baharu)
				</button>
			</div>
		);
	}
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Semak teks akhir. Selepas disahkan, teks menjadi kunci-baca.
			</p>
			{wf.editingCopySetId ? (
				<p
					className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs text-sky-100"
					data-testid="poster-approve-editing-version"
				>
					Pengesahan akan mengemas kini draf versi sedia ada — tiada set teks
					pendua akan dicipta.
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
				Sahkan teks poster
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
	if (p.includes("center") || p.includes("tengah")) return "Produk di tengah";
	if (p.includes("bottom") || p.includes("bawah"))
		return "Produk di bahagian bawah";
	if (p.includes("hand") || p.includes("tangan")) return "Produk dipegang";
	return recipe.product_placement || "Produk sebagai fokus";
}

function VisualStep({ wf, recipes }: { wf: WF; recipes: PosterRecipe[] }) {
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Pilih gaya visual poster. Rajah kecil menunjukkan susun atur teks
				(kelabu), chip (biru), CTA (hijau).
			</p>
			{recipes.length === 0 ? (
				<Busy label="Memuatkan gaya visual…" />
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
										<span className="text-slate-500">Sesuai untuk: </span>
										{goalForArchetype(r.archetype).title}
									</p>
									<p className="text-[11px] text-slate-300">
										<span className="text-slate-500">Kedudukan produk: </span>
										{placementLabel(r)}
									</p>
									{r.allowed_text_density?.length ? (
										<p className="text-[11px] text-slate-300">
											<span className="text-slate-500">Ketumpatan teks: </span>
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

// ── Scene picker (approved existing assets — no raw media IDs) ──────────────
function SceneStep({ wf }: { wf: WF }) {
	const [artifacts, setArtifacts] = useState<ImageArtifact[] | null>(null);
	const [artifactsError, setArtifactsError] = useState("");
	const [loading, setLoading] = useState(false);

	const load = () => {
		setLoading(true);
		setArtifactsError("");
		void fetchImageArtifacts(30)
			.then((items) => setArtifacts(items))
			.catch(() =>
				setArtifactsError(
					"Gagal memuatkan senarai scene. Semak sambungan agen dan cuba lagi.",
				),
			)
			.finally(() => setLoading(false));
	};

	// eslint-disable-next-line react-hooks/exhaustive-deps -- load once on mount
	useEffect(load, []);

	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Pilih latar daripada scene sedia ada (tanpa kredit). Scene baharu boleh
				dijana dari langkah Hasilkan bila perlu.
			</p>
			<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
				Identiti produk adalah reference-conditioned — pastikan label & skala
				disemak sebelum diterbitkan.
			</div>

			{loading ? <Busy label="Memuatkan scene sedia ada…" /> : null}
			{artifactsError ? (
				<div className="space-y-2" data-testid="poster-scene-error">
					<ErrorNote testid="poster-scene-error-text" text={artifactsError} />
					<button
						type="button"
						data-testid="poster-scene-retry"
						onClick={load}
						className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200"
					>
						Cuba lagi
					</button>
				</div>
			) : null}

			{!loading && !artifactsError && artifacts && artifacts.length === 0 ? (
				<p
					className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-6 text-center text-sm text-slate-400"
					data-testid="poster-scene-empty"
				>
					Tiada scene tersedia buat masa ini (scene lama luput selepas 48 jam).
					Jana scene bersih baharu melalui butang penjanaan di modul IMG, atau
					teruskan — poster boleh dihasilkan selepas scene tersedia.
				</p>
			) : null}

			{artifacts && artifacts.length > 0 ? (
				<div
					className="grid grid-cols-2 gap-3 sm:grid-cols-3"
					data-testid="poster-scene-grid"
				>
					{artifacts.map((a) => {
						const selected = wf.backgroundMediaId === a.media_id;
						const expiring =
							typeof (a as { expires_in_hours?: number | null })
								.expires_in_hours === "number" &&
							((a as { expires_in_hours?: number | null }).expires_in_hours ??
								99) < 6;
						return (
							<SelectCard
								key={a.media_id}
								testid={`poster-scene-card-${a.media_id}`}
								selected={selected}
								onClick={() =>
									wf.setBackgroundMediaId(selected ? "" : a.media_id)
								}
								badge={
									<span
										className={[
											"absolute left-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-bold",
											expiring
												? "bg-amber-500/30 text-amber-100"
												: "bg-emerald-500/20 text-emerald-200",
										].join(" ")}
									>
										{expiring ? "Hampir luput" : "Sedia digunakan"}
									</span>
								}
							>
								<img
									src={`/api/flow/retrieved/${a.media_id}`}
									alt={a.mode ? `Scene ${a.mode}` : "Scene"}
									loading="lazy"
									className="h-32 w-full rounded-lg object-cover"
								/>
								<p className="mt-2 truncate text-[11px] text-slate-300">
									{(a.mode || "Scene").toUpperCase()}
									{a.created_at ? ` · ${a.created_at.slice(0, 10)}` : ""}
								</p>
							</SelectCard>
						);
					})}
				</div>
			) : null}

			<details className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
				<summary className="cursor-pointer text-xs font-semibold text-slate-400">
					Advanced Diagnostics
				</summary>
				<label
					className="mt-2 block text-xs font-semibold text-slate-300"
					htmlFor="poster-scene-bg-input"
				>
					ID media scene (untuk juruteknik sahaja)
				</label>
				<input
					id="poster-scene-bg-input"
					data-testid="poster-scene-bg-input"
					value={wf.backgroundMediaId}
					onChange={(e) => wf.setBackgroundMediaId(e.target.value)}
					placeholder="media_id scene sedia ada"
					className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
				/>
			</details>
		</div>
	);
}

function ComposeStep({ wf }: { wf: WF }) {
	const qa = bucketQaFindings(wf.deliverable?.qa_report);
	return (
		<div className="space-y-3">
			{!wf.backgroundMediaId ? (
				<p
					className="text-xs text-amber-200/90"
					data-testid="poster-compose-need-scene"
				>
					Pilih scene latar dahulu di langkah Latar.
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
				{wf.deliverable ? "Hasilkan semula" : "Hasilkan poster"}
			</button>
			<ErrorNote testid="poster-compose-error" text={wf.composeError} />
			{wf.deliverable ? (
				<div className="space-y-3">
					<img
						data-testid="poster-preview"
						src={posterDeliverableOutputUrl(
							wf.deliverable.deliverable.poster_deliverable_id,
						)}
						alt="Pratonton poster"
						className="max-h-96 rounded-xl border border-slate-800 object-contain"
					/>
					<div className="space-y-2">
						{qa.mustFix.length ? (
							<QaGroup
								testid="poster-qa-mustfix"
								tone="rose"
								title="Mesti Baiki"
								items={qa.mustFix}
							/>
						) : null}
						{qa.review.length ? (
							<QaGroup
								testid="poster-qa-review"
								tone="amber"
								title="Semakan Disyorkan"
								items={qa.review}
							/>
						) : null}
						{qa.passed ? (
							<p
								className="rounded-lg border border-emerald-600/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100"
								data-testid="poster-qa-passed"
							>
								✓ Semua semakan lulus.
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
	return (
		<div className="space-y-3">
			{!wf.deliverable ? (
				<p className="text-sm text-slate-400">Hasilkan poster dahulu.</p>
			) : wf.savedAssetId ? (
				<div
					className="space-y-2 rounded-2xl border border-emerald-600/40 bg-emerald-500/10 p-4"
					data-testid="poster-saved"
				>
					<p className="flex items-center gap-2 text-sm font-semibold text-emerald-100">
						<Check className="h-4 w-4" /> Poster disimpan ke Creative Library.
					</p>
					<img
						src={posterDeliverableOutputUrl(
							wf.deliverable.deliverable.poster_deliverable_id,
						)}
						alt="Poster tersimpan"
						className="max-h-72 rounded-lg border border-slate-800 object-contain"
					/>
				</div>
			) : (
				<>
					<p className="text-sm text-slate-400">
						Simpan poster ke Creative Library untuk guna semula & muat turun.
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
						Simpan ke Creative Library
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
		(wf.step === "scene" && wf.recipeId !== null && !!wf.backgroundMediaId) ||
		(wf.step === "compose" && wf.deliverable !== null);

	return (
		<div className="mt-5 flex items-center justify-between border-t border-slate-800 pt-4">
			<button
				type="button"
				data-testid="poster-guided-back"
				disabled={!prev || !wf.canGoTo(prev)}
				onClick={() => prev && wf.goTo(prev)}
				className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-30"
			>
				<ArrowLeft className="h-4 w-4" /> Kembali
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
					Teruskan <ArrowRight className="h-4 w-4" />
				</button>
			) : (
				<span className="text-xs text-slate-500">Pilih untuk meneruskan</span>
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
				Ringkasan
			</p>
			<SummaryRow label="Produk" value={wf.product?.product_display_name} />
			<SummaryRow
				label="Tujuan"
				value={
					wf.goalArchetype
						? goalForArchetype(wf.goalArchetype).title
						: undefined
				}
			/>
			<SummaryRow label="Sudut" value={wf.selectedAngle || undefined} />
			<SummaryRow
				label="Teks utama"
				value={wf.fields.primary_message || undefined}
			/>
			<SummaryRow
				label="Status teks"
				value={
					wf.approvedCopySet
						? "Disahkan"
						: wf.historicalCopySet
							? "Versi sejarah (kunci-baca)"
							: wf.editingCopySetId
								? "Draf versi baharu"
								: wf.fields.primary_message
									? "Draf"
									: undefined
				}
			/>
			<SummaryRow
				label="Gaya visual"
				value={
					wf.recipeId
						? goalForArchetype(wf.goalArchetype ?? "").title
						: undefined
				}
			/>
			{wf.deliverable ? (
				<SummaryRow
					label="Kesahihan produk"
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
				label: "Versi sejarah (kunci-baca)",
				cls: "bg-amber-500/20 text-amber-100",
			}
		: status === "POSTER_COPY_APPROVED"
			? {
					label: "Teks diluluskan semasa",
					cls: "bg-emerald-500/20 text-emerald-100",
				}
			: { label: "Draf", cls: "bg-slate-700 text-slate-200" };
	return (
		<section
			className="rounded-2xl border border-emerald-700/40 bg-emerald-950/20 p-4"
			data-testid="poster-guided-reopen"
		>
			<div className="mb-3 flex items-center gap-2">
				<p className="text-[10px] font-bold uppercase tracking-wide text-emerald-400">
					Dibuka semula dari Creative Library
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
						alt="Poster asal tersimpan"
						className="h-48 rounded-lg border border-slate-800 object-contain"
						data-testid="poster-guided-reopen-output"
					/>
				) : (
					<p className="text-xs text-amber-300">
						Output asal tiada di runtime ini.
					</p>
				)}
				<div className="space-y-1 text-xs text-slate-300">
					<p>
						<span className="text-slate-500">Sumber output: </span>
						<span data-testid="poster-guided-reopen-source">
							{reopened.output_available
								? reopened.output_source === "CREATIVE_LIBRARY"
									? "Salinan Creative Library (durable)"
									: "Fail deliverable asal"
								: "Tiada"}
						</span>
					</p>
					<p>
						<span className="text-slate-500">Teks: </span>
						{reopened.poster_copy_set?.primary_message ?? "—"}
					</p>
					<p className="text-[11px] text-slate-500">
						Keseluruhan aliran kerja telah dipulihkan — anda boleh menavigasi
						setiap langkah di bawah.
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
							Guna teks sama
						</button>
						<button
							type="button"
							data-testid="poster-reopen-new-version"
							onClick={() => void wf.editApproved()}
							className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-100"
						>
							Cipta versi baharu
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
							? "Mencipta salinan…"
							: "Salin & sunting (versi sejarah kekal)"}
					</button>
				) : null}
				<button
					type="button"
					data-testid="poster-reopen-duplicate"
					onClick={() => wf.duplicatePoster()}
					className="rounded-lg border border-slate-600 bg-slate-800/60 px-3 py-1.5 text-xs font-semibold text-slate-200"
				>
					Duplikat poster
				</button>
			</div>
			<ErrorNote testid="poster-reopen-fork-error" text={wf.forkError} />
		</section>
	);
}
