/**
 * Copy-binding gate for the video "SEND TO FLOW EDITOR" path.
 *
 * Enforcement (not advisory): when the run is NOT bound to an approved Copy Set,
 * this renders a warning + an explicit fallback-confirmation checkbox. The host
 * module keeps SEND disabled until either the run is copy-bound or the operator
 * ticks this box — so generic / manual copy can never be sent silently.
 *
 * Renders nothing when the run is already copy-bound.
 */
export default function CopyBindingGate({
	copyBound,
	ready,
	fallbackConfirmed,
	onToggleFallback,
}: {
	copyBound: boolean;
	ready?: boolean;
	fallbackConfirmed: boolean;
	onToggleFallback: (next: boolean) => void;
}) {
	if (copyBound) return null;
	return (
		<div
			data-testid="copy-binding-gate"
			className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-3 text-[11px] text-amber-100 space-y-2"
		>
			<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200/90">
				Copywriting not bound
			</div>
			<p>
				No approved Copy Set is bound to this generation
				{ready ? "" : " and this product is not copywriting-ready"}. Sending now
				uses manual / non-approved copy. Bind an approved Copy Set (Steps 3–4) or
				explicitly confirm fallback below.
			</p>
			<label className="flex items-center gap-2 cursor-pointer">
				<input
					type="checkbox"
					data-testid="copy-fallback-confirm"
					checked={fallbackConfirmed}
					onChange={(e) => onToggleFallback(e.target.checked)}
				/>
				<span>I understand and confirm fallback copy usage for this run.</span>
			</label>
		</div>
	);
}
