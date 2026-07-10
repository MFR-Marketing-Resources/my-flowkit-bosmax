import {
	ArrowLeft,
	ArrowRight,
	Check,
	Loader2,
	RefreshCw,
	Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchProductCatalog } from "../../../api/products";
import {
	fetchPosterDeliverableByAsset,
	posterDeliverableOutputUrl,
} from "../../../api/posterCopySets";
import { usePosterRecipes } from "../../../api/posterRecipes";
import type { PosterDeliverableReconstruction } from "../../../types/posterCopySet";
import type { PosterRecipe } from "../../../types/posterRecipe";
import type { Product } from "../../../types";
import SearchableProductSelect from "../../workspace/SearchableProductSelect";
import {
	GUIDED_GOALS,
	GUIDED_STEPS,
	type GuidedStepId,
	bucketQaFindings,
	goalForArchetype,
	readinessBanner,
	stepIndex,
	truthLabel,
} from "../../../poster/guided/posterGuided";
import {
	type GuidedCopyFields,
	usePosterGuidedWorkflow,
} from "../../../poster/guided/usePosterGuidedWorkflow";

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
									active ? "bg-slate-950/20" : done ? "bg-emerald-500/30" : "bg-slate-700/60",
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
	const [reopened, setReopened] = useState<PosterDeliverableReconstruction | null>(null);
	const [reopenError, setReopenError] = useState("");

	useEffect(() => {
		void fetchProductCatalog(60)
			.then((res) => setProducts(res.items ?? []))
			.catch((e: Error) => setCatalogError(e.message || "Gagal memuatkan produk."));
	}, []);

	useEffect(() => {
		const asset = searchParams.get("reopen_asset");
		if (!asset) return;
		void fetchPosterDeliverableByAsset(asset)
			.then((d) => {
				setReopened(d);
				setReopenError("");
			})
			.catch((e: Error) => setReopenError(e.message || "Gagal membuka poster tersimpan."));
	}, [searchParams]);

	const recipeChoices = useMemo<PosterRecipe[]>(() => {
		if (!wf.goalArchetype) return recipes;
		const matching = recipes.filter((r) => r.archetype === wf.goalArchetype);
		return matching.length ? matching : recipes;
	}, [recipes, wf.goalArchetype]);

	const activeMeta = GUIDED_STEPS.find((s) => s.id === wf.step)!;
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

			{reopenError ? (
				<p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
					{reopenError}
				</p>
			) : null}
			{reopened ? (
				<ReopenCard reopened={reopened} />
			) : null}

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
							) : (
								<div className="mb-4">
									<ReadinessBanner status={wf.readiness?.poster_status} />
								</div>
							)}
							<GoalStep wf={wf} blocked={!readyBanner.canProceed} />
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

				<PosterSummary wf={wf} />
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
					{productThumb(selected) ? (
						<img
							src={productThumb(selected)!}
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
			<div className="grid gap-3 sm:grid-cols-2">
				{GUIDED_GOALS.map((g) => {
					const rec = wf.objectiveRecs.find((r) => r.archetype === g.archetype);
					const recommended = wf.recommendedArchetype === g.archetype;
					return (
						<SelectCard
							key={g.archetype}
							testid={`poster-goal-card-${g.archetype}`}
							selected={wf.goalArchetype === g.archetype}
							disabled={blocked}
							onClick={() => wf.selectGoal(g.archetype, rec?.recipe_id, rec?.objective)}
							badge={
								recommended ? (
									<span className="absolute right-3 top-3 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-200">
										Disyorkan ✦
									</span>
								) : undefined
							}
						>
							<p className="font-semibold text-slate-100">{g.title}</p>
							<p className="mt-1 text-xs text-slate-400">{g.description}</p>
							{rec?.reason ? (
								<p className="mt-2 text-[11px] text-emerald-300/80">{rec.reason}</p>
							) : null}
						</SelectCard>
					);
				})}
			</div>
		</div>
	);
}

function AngleStep({ wf }: { wf: WF }) {
	useEffect(() => {
		if (wf.goalArchetype && wf.angles.length === 0 && !wf.anglesLoading && !wf.anglesError)
			void wf.loadAngles();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [wf.goalArchetype]);
	const [custom, setCustom] = useState("");
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Pilih sudut jualan untuk {goalForArchetype(wf.goalArchetype ?? "").title}.
			</p>
			{wf.anglesLoading ? <Busy label="Menjana sudut jualan…" /> : null}
			{wf.anglesError ? (
				<div className="flex items-center gap-3">
					<p className="text-sm text-rose-300">{wf.anglesError}</p>
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
						key={`${a.angle}-${i}`}
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
				<label className="text-xs font-semibold text-slate-300">
					Atau tulis sudut anda sendiri
				</label>
				<div className="mt-2 flex gap-2">
					<input
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
	useEffect(() => {
		if (
			wf.selectedAngle &&
			wf.directions.length === 0 &&
			!wf.directionsLoading &&
			!wf.directionsError
		)
			void wf.loadDirections();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [wf.selectedAngle]);
	return (
		<div className="space-y-4">
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
			{wf.directionsError ? (
				<p className="text-sm text-rose-300">{wf.directionsError}</p>
			) : null}
			<div className="grid gap-3 md:grid-cols-3">
				{wf.directions.map((d, i) => (
					<SelectCard
						key={i}
						testid={`poster-copy-direction-${i}`}
						selected={wf.selectedDirection === i}
						onClick={() => wf.selectDirection(i)}
					>
						<p className="text-sm font-bold text-slate-100">{d.primary_message}</p>
						<p className="mt-1 text-xs text-slate-400">{d.support_message}</p>
						{d.proof_points.length ? (
							<ul className="mt-2 space-y-0.5">
								{d.proof_points.map((p, j) => (
									<li key={j} className="text-[11px] text-emerald-300/80">
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
			{wf.selectedDirection !== null ? (
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
			{FIELD_LABELS.map(({ key, label }) => (
				<div key={key}>
					<div className="mb-1 flex items-center justify-between">
						<label className="text-xs font-semibold text-slate-300">{label}</label>
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
						data-testid={`poster-field-${key}`}
						value={wf.fields[key] as string}
						onChange={(e) => wf.updateField(key, e.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
					/>
				</div>
			))}
			<div>
				<label className="text-xs font-semibold text-slate-300">Proof Points</label>
				<input
					data-testid="poster-field-proof_points"
					value={wf.fields.proof_points.join(" | ")}
					onChange={(e) =>
						wf.updateField(
							"proof_points",
							e.target.value.split("|").map((s) => s.trim()).filter(Boolean),
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
			<div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-950/40 p-4 text-sm">
				<Review label="Primary Message" value={wf.fields.primary_message} />
				<Review label="Support Message" value={wf.fields.support_message} />
				<Review label="Proof Points" value={wf.fields.proof_points.join(", ") || "—"} />
				<Review label="CTA" value={wf.fields.cta} />
				{wf.fields.disclaimer ? (
					<Review label="Disclaimer" value={wf.fields.disclaimer} />
				) : null}
			</div>
			{wf.approveError ? (
				<p
					className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100"
					data-testid="poster-approve-error"
				>
					{wf.approveError}
				</p>
			) : null}
			<button
				type="button"
				data-testid="poster-approve-copy"
				onClick={() => void wf.approve()}
				disabled={wf.approveLoading || !wf.fields.primary_message}
				className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
			>
				{wf.approveLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
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

function VisualStep({ wf, recipes }: { wf: WF; recipes: PosterRecipe[] }) {
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">Pilih gaya visual poster.</p>
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
							<p className="font-semibold text-slate-100">{r.label}</p>
							<p className="mt-1 text-xs text-slate-400">{r.description}</p>
							{r.allowed_text_density?.length ? (
								<p className="mt-2 text-[11px] text-slate-500">
									Ketumpatan teks: {r.allowed_text_density.join(", ")}
								</p>
							) : null}
						</SelectCard>
					))}
				</div>
			)}
		</div>
	);
}

function SceneStep({ wf }: { wf: WF }) {
	return (
		<div className="space-y-3">
			<p className="text-sm text-slate-400">
				Pilih latar untuk poster. Gunakan scene sedia ada yang diluluskan
				(tanpa kredit).
			</p>
			<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
				Identiti produk adalah reference-conditioned — pastikan label & skala
				disemak sebelum diterbitkan.
			</div>
			<label className="text-xs font-semibold text-slate-300">
				ID scene / aset latar (pilihan)
			</label>
			<input
				data-testid="poster-scene-bg-input"
				value={wf.backgroundMediaId}
				onChange={(e) => wf.setBackgroundMediaId(e.target.value)}
				placeholder="media_id scene sedia ada"
				className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
			/>
			<p className="text-[11px] text-slate-500">
				Menjana scene baharu (berbayar) tersedia di bawah Advanced Diagnostics.
			</p>
		</div>
	);
}

function ComposeStep({ wf }: { wf: WF }) {
	const qa = bucketQaFindings(wf.deliverable?.qa_report);
	return (
		<div className="space-y-3">
			<button
				type="button"
				data-testid="poster-compose"
				onClick={() => void wf.compose()}
				disabled={wf.composeLoading}
				className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
			>
				{wf.composeLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
				{wf.deliverable ? "Hasilkan semula" : "Hasilkan poster"}
			</button>
			{wf.composeError ? (
				<p
					className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100"
					data-testid="poster-compose-error"
				>
					{wf.composeError}
				</p>
			) : null}
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
							<QaGroup testid="poster-qa-mustfix" tone="rose" title="Mesti Baiki" items={qa.mustFix} />
						) : null}
						{qa.review.length ? (
							<QaGroup testid="poster-qa-review" tone="amber" title="Semakan Disyorkan" items={qa.review} />
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
		<div className={`rounded-lg border px-3 py-2 text-sm ${cls}`} data-testid={testid}>
			<p className="font-semibold">{title}</p>
			<ul className="mt-1 space-y-0.5 text-xs">
				{items.map((m, i) => (
					<li key={i}>• {m}</li>
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
					{wf.saveError ? (
						<p className="text-sm text-rose-300" data-testid="poster-save-error">
							{wf.saveError}
						</p>
					) : null}
					<button
						type="button"
						data-testid="poster-save"
						onClick={() => void wf.save()}
						disabled={wf.saveLoading}
						className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
					>
						{wf.saveLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
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
		(wf.step === "copy" && wf.selectedDirection !== null) ||
		(wf.step === "approve" && wf.approvedCopySet !== null) ||
		(wf.step === "scene" && wf.recipeId !== null) ||
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
				<span className="text-xs text-slate-500">
					Pilih untuk meneruskan
				</span>
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
				value={wf.goalArchetype ? goalForArchetype(wf.goalArchetype).title : undefined}
			/>
			<SummaryRow label="Sudut" value={wf.selectedAngle || undefined} />
			<SummaryRow label="Teks utama" value={wf.fields.primary_message || undefined} />
			<SummaryRow
				label="Status teks"
				value={wf.approvedCopySet ? "Disahkan" : wf.fields.primary_message ? "Draf" : undefined}
			/>
			<SummaryRow
				label="Gaya visual"
				value={wf.recipeId ? goalForArchetype(wf.goalArchetype ?? "").title : undefined}
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
			<p className={value ? "text-slate-200" : "text-slate-600"}>{value || "—"}</p>
		</div>
	);
}

// ── Reopen (Creative Library round trip) ────────────────────────────────────
function ReopenCard({ reopened }: { reopened: PosterDeliverableReconstruction }) {
	const historical = reopened.poster_copy_set_historical;
	const status = reopened.poster_copy_set?.status ?? "";
	const badge = historical
		? { label: "Versi sejarah (kunci-baca)", cls: "bg-amber-500/20 text-amber-100" }
		: status === "POSTER_COPY_APPROVED"
			? { label: "Teks diluluskan semasa", cls: "bg-emerald-500/20 text-emerald-100" }
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
				<span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>
					{badge.label}
				</span>
			</div>
			<div className="flex flex-wrap gap-4">
				{reopened.output_available ? (
					<img
						src={posterDeliverableOutputUrl(reopened.deliverable.poster_deliverable_id)}
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
				</div>
			</div>
		</section>
	);
}
