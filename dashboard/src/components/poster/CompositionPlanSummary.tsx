// WRNA Round 3 (B-04) — compact display of the BACKEND-resolved canonical
// composition plan. This component renders values verbatim from the resolver:
// it never duplicates backend profile definitions, never invents defaults and
// never dumps raw JSON. Shared by Poster Guided and the prompt-package preview
// so both surfaces show the SAME plan the compile preserves.
import type {
	CompositionPlan,
	CompositionPlanSuppression,
} from "../../types/posterCompositionPlan";

function Row({ label, value }: { label: string; value?: string }) {
	return (
		<div className="flex items-baseline justify-between gap-2 text-[11px]">
			<span className="shrink-0 text-slate-500">{label}</span>
			<span className={`text-right ${value ? "text-slate-200" : "text-slate-600"}`}>
				{value || "—"}
			</span>
		</div>
	);
}

function suppressionLine(s: CompositionPlanSuppression): string {
	return `${s.property}: ${s.mode_value || "—"} → ${s.resolved_value || "—"} (${s.reason})`;
}

export default function CompositionPlanSummary({
	plan,
	loading = false,
	error = "",
	compiledSignature = "",
}: {
	plan: CompositionPlan | null | undefined;
	loading?: boolean;
	error?: string;
	// Signature of the plan the LAST compile actually preserved (from the
	// compose response) — proves the displayed plan is the compiled plan.
	compiledSignature?: string;
}) {
	if (loading) {
		return (
			<p
				className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-[11px] text-slate-400"
				data-testid="poster-composition-plan-loading"
			>
				Menyusun pelan komposisi…
			</p>
		);
	}
	if (error) {
		return (
			<p
				className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-100"
				data-testid="poster-composition-plan-error"
			>
				{error}
			</p>
		);
	}
	if (!plan || !Object.keys(plan).length) return null;

	const locks = plan.provenance?.active_locks ?? [];
	const suppressions = plan.provenance?.suppressions ?? [];
	const warnings = plan.warnings ?? [];
	const blockers = plan.blockers ?? [];
	const signaturesComparable = !!compiledSignature && !!plan.signature;
	const compiledMatches = signaturesComparable && compiledSignature === plan.signature;

	return (
		<section
			className="space-y-2 rounded-2xl border border-sky-500/30 bg-sky-500/5 p-3"
			data-testid="poster-composition-plan"
			data-mode={plan.creative_mode ?? ""}
			data-signature={plan.signature ?? ""}
		>
			<p className="text-[10px] font-bold uppercase tracking-wide text-sky-300">
				Pelan Komposisi (backend)
			</p>
			<Row label="Mod" value={plan.creative_mode} />
			<Row label="Profil" value={plan.profile_id} />
			<Row label="Anchor produk" value={plan.product?.anchor} />
			<Row label="Dominasi" value={plan.product?.dominance} />
			<Row label="Susunan bacaan" value={(plan.reading_order ?? []).join(" → ")} />
			<Row label="Margin selamat" value={plan.canvas?.safe_margin} />
			<Row label="Nisbah bingkai" value={plan.canvas?.frame_ratio} />
			<Row label="Polisi manusia" value={plan.scene?.human_presence} />
			<Row label="Polisi identiti" value={plan.scene?.identity_policy} />
			<Row label="Zon muka selamat" value={plan.scene?.face_safe_rule} />
			<Row
				label="Zon hook"
				value={
					plan.copy?.hook_zone && plan.typography?.hook
						? `${plan.copy.hook_zone} · ${plan.typography.hook}`
						: plan.copy?.hook_zone
				}
			/>
			<Row
				label="Zon USP"
				value={
					plan.copy?.usp_zone && plan.typography?.usp
						? `${plan.copy.usp_zone} · ${plan.typography.usp}`
						: plan.copy?.usp_zone
				}
			/>
			<Row
				label="Zon CTA"
				value={
					plan.copy?.cta_zone && plan.typography?.cta
						? `${plan.copy.cta_zone} · ${plan.typography.cta}`
						: plan.copy?.cta_zone
				}
			/>
			<Row label="Latar" value={plan.scene?.background_complexity} />
			<Row label="Pencahayaan" value={plan.scene?.lighting} />

			{locks.length ? (
				<div
					className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5"
					data-testid="poster-composition-locks"
				>
					<p className="text-[10px] font-bold text-emerald-200">
						Kunci authority aktif
					</p>
					<p className="text-[11px] text-emerald-100">{locks.join(", ")}</p>
				</div>
			) : null}

			{suppressions.length ? (
				<div
					className="rounded-lg border border-slate-700 bg-slate-900/60 px-2 py-1.5"
					data-testid="poster-composition-suppressions"
				>
					<p className="text-[10px] font-bold text-slate-300">
						Sifat mod ditindas (authority lebih tinggi menang)
					</p>
					<ul className="mt-0.5 space-y-0.5 text-[11px] text-slate-300">
						{suppressions.map((s) => (
							<li key={`${s.property}-${s.reason}`}>• {suppressionLine(s)}</li>
						))}
					</ul>
				</div>
			) : null}

			{blockers.length ? (
				<div
					className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1.5"
					data-testid="poster-composition-blockers"
				>
					<p className="text-[10px] font-bold text-rose-200">Blocker</p>
					<ul className="mt-0.5 space-y-0.5 text-[11px] text-rose-100">
						{blockers.map((b) => (
							<li key={b}>• {b}</li>
						))}
					</ul>
				</div>
			) : null}

			{warnings.length ? (
				<div
					className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1.5"
					data-testid="poster-composition-warnings"
				>
					<p className="text-[10px] font-bold text-amber-200">Amaran komposisi</p>
					<ul className="mt-0.5 space-y-0.5 text-[11px] text-amber-100">
						{warnings.map((w) => (
							<li key={w}>• {w}</li>
						))}
					</ul>
				</div>
			) : null}

			{signaturesComparable ? (
				compiledMatches ? (
					<p
						className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-100"
						data-testid="poster-composition-plan-match"
					>
						✓ Kompilasi menggunakan pelan yang sama dipaparkan di sini.
					</p>
				) : (
					<p
						className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-100"
						data-testid="poster-composition-plan-mismatch"
					>
						Pelan telah berubah selepas kompilasi terakhir — hasilkan semula
						untuk padankan.
					</p>
				)
			) : null}
		</section>
	);
}
