import type { PosterWorkingMode } from "../../types/posterCopyRecommendations";

const MODES: { id: PosterWorkingMode; title: string; hint: string }[] = [
	{
		id: "auto",
		title: "Auto / Quick Start",
		hint: "Minimum inputs — system recommends poster kits.",
	},
	{
		id: "guided",
		title: "Guided Build",
		hint: "Pick angle → hook → subhook → USP → CTA with suggestions.",
	},
	{
		id: "manual",
		title: "Manual Expert",
		hint: "Full control — all fields editable.",
	},
];

export default function PosterWorkingModeSelector({
	mode,
	onChange,
	disabled,
}: {
	mode: PosterWorkingMode;
	onChange: (mode: PosterWorkingMode) => void;
	disabled?: boolean;
}) {
	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid="poster-working-mode-selector"
		>
			<h3 className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
				Working mode
			</h3>
			<div className="mt-3 grid gap-2 md:grid-cols-3">
				{MODES.map((m) => (
					<button
						key={m.id}
						type="button"
						disabled={disabled}
						data-testid={`working-mode-${m.id}`}
						onClick={() => onChange(m.id)}
						className={`rounded-xl border px-3 py-3 text-left transition ${
							mode === m.id
								? "border-blue-500/60 bg-blue-600/15"
								: "border-slate-800 bg-slate-900/60 hover:border-slate-600"
						} disabled:opacity-40`}
					>
						<div className="text-xs font-bold text-slate-100">{m.title}</div>
						<div className="mt-1 text-[10px] text-slate-400">{m.hint}</div>
					</button>
				))}
			</div>
		</section>
	);
}