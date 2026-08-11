import type { PosterCopyQualityReport } from "../../types/posterCopyQuality";

/** Expert poster-copy review surface. Runs the quality guard on the current
 * copy (headline / support / chips / CTA in POSTER language) and shows BLOCK /
 * WARN findings. BLOCK findings mean the poster is not e-commerce-ready. */
export default function PosterCopyQualityPanel({
	report,
	loading,
	stale = false,
	onCheck,
}: {
	report: PosterCopyQualityReport | null;
	loading: boolean;
	stale?: boolean;
	onCheck: () => void;
}) {
	return (
		<section
			className="rounded-2xl border border-amber-500/20 bg-amber-950/10 p-5"
			data-testid="poster-copy-quality-panel"
		>
			<div className="flex flex-wrap items-center justify-between gap-2">
				<h3 className="text-sm font-bold text-amber-100">Poster copy quality (expert review)</h3>
				<button
					type="button"
					data-testid="poster-quality-check"
					disabled={loading}
					onClick={onCheck}
					className="rounded-lg border border-amber-500/40 bg-amber-600/20 px-3 py-1.5 text-[10px] font-bold uppercase text-amber-100 disabled:opacity-40"
				>
					{loading ? "Checking…" : "Check poster quality"}
				</button>
			</div>
			<p className="mt-1 text-[11px] text-slate-400">
				A poster is not a video script: short headline (first-read), one support line,
				2–3 chips, one solid CTA, one core idea, safe language.
			</p>

			{stale ? (
				<p
					data-testid="poster-quality-stale"
					className="mt-3 text-[11px] text-amber-300"
				>
					⟳ Copy changed since the last check — re-check before generating.
				</p>
			) : null}

			{report ? (
				report.findings.length === 0 ? (
					<p
						data-testid="poster-quality-clean"
						className="mt-3 text-[11px] text-emerald-300"
					>
						✓ Poster copy passed the e-commerce expert check.
					</p>
				) : (
					<ul className="mt-3 space-y-1" data-testid="poster-quality-findings">
						{report.findings.map((f) => (
							<li
								key={`${f.code}-${f.field}`}
								data-testid={`poster-quality-${f.severity.toLowerCase()}`}
								className={`text-[11px] ${f.severity === "BLOCK" ? "text-rose-300" : "text-amber-300"}`}
							>
								<strong>{f.severity}</strong>{" "}
								<span className="uppercase text-slate-500">[{f.field}]</span> {f.message}
							</li>
						))}
					</ul>
				)
			) : (
				<p className="mt-3 text-[11px] text-slate-500">
					Press "Check poster quality" for an expert check (free, no
					generation).
				</p>
			)}
		</section>
	);
}
