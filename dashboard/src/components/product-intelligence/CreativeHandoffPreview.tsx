import { useState } from "react";

import {
	getCreativeHandoffForProduct,
	type CreativeHandoff,
} from "../../api/creativeIntelligence";

/**
 * Creative Generation Handoff PREVIEW (Creative Intelligence — Round 5).
 * On explicit user action, reads the product's APPROVED creative selection and
 * resolves [AVATAR]/[PRODUCT] at this boundary to show a generation-ready PREVIEW.
 * This NEVER generates, enqueues, or burns credits — it is a preview requiring
 * explicit confirmation and the existing credit-burn gate before any generation.
 * Blocked (fail-closed) for DRAFT / REJECTED / missing / invalid selections.
 */
export default function CreativeHandoffPreview({ productId }: { productId: string }) {
	const [handoff, setHandoff] = useState<CreativeHandoff | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");

	async function loadHandoff() {
		setBusy(true);
		setError("");
		setHandoff(null);
		try {
			setHandoff(await getCreativeHandoffForProduct(productId));
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Failed to prepare handoff.");
		} finally {
			setBusy(false);
		}
	}

	return (
		<div
			data-testid="creative-handoff-preview"
			className="rounded border border-indigo-500/30 bg-indigo-500/5 p-3"
		>
			<div className="flex items-center justify-between gap-2">
				<div className="text-sm font-bold text-indigo-100">Generation Handoff (Preview)</div>
				<span className="rounded bg-amber-900/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
					preview only · no generation
				</span>
			</div>
			<p className="mt-1 text-[10px] leading-relaxed text-slate-400">
				Reads this product's <span className="font-semibold text-emerald-300">APPROVED</span> creative
				selection and resolves <code className="text-indigo-200">[AVATAR]</code>/
				<code className="text-indigo-200">[PRODUCT]</code> into a generation-ready preview. Nothing is
				generated, queued, or charged here — explicit confirmation and the existing credit gate are
				required before any generation. Blocked for DRAFT / REJECTED selections.
			</p>

			<button
				type="button"
				data-testid="creative-handoff-prepare"
				disabled={busy}
				onClick={loadHandoff}
				className="mt-3 rounded bg-indigo-600 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
			>
				{busy ? "Preparing…" : "Prepare Handoff Preview"}
			</button>

			{error && (
				<p className="mt-3 text-xs font-medium text-red-300" role="alert" data-testid="creative-handoff-error">
					Handoff blocked: {error}
				</p>
			)}

			{handoff && (
				<div data-testid="creative-handoff-payload" className="mt-3 space-y-2 border-t border-slate-700/50 pt-2 text-[11px] text-slate-200">
					<div className="rounded bg-amber-950/40 p-2 text-[10px] text-amber-200" data-testid="creative-handoff-banner">
						{handoff.handoff_status} — {handoff.note}
					</div>
					<div>
						Status: <span className="font-mono text-emerald-300">{handoff.selection_status}</span>{" "}
						· cluster {handoff.cluster} · auto_generated: {String(handoff.auto_generated)}
					</div>
					<div>
						Avatar: <span className="font-mono text-indigo-200">{handoff.avatar.avatar_code || "—"}</span>{" "}
						{handoff.avatar.character_name ? `· ${handoff.avatar.character_name}` : ""}
					</div>
					<div>
						Scene: <span className="font-mono text-indigo-200">{handoff.scene_template.template_id || "—"}</span>{" "}
						{handoff.scene_template.variant ? `· ${handoff.scene_template.variant}` : ""}
					</div>
					<div>
						Camera: <span className="font-mono text-indigo-200">{handoff.camera_preset.preset_code || "—"}</span>{" "}
						{handoff.camera_preset.shot_type ? `· ${handoff.camera_preset.shot_type} · ${handoff.camera_preset.distance_angle ?? ""} · ${handoff.camera_preset.movement ?? ""}` : ""}
					</div>
					{handoff.resolved_prompt_preview && (
						<div>
							<div className="text-[10px] uppercase tracking-wide text-slate-500">Resolved prompt preview ([AVATAR]/[PRODUCT] resolved here only)</div>
							<p className="mt-1 rounded bg-slate-900/60 p-2 font-mono text-[10px] leading-relaxed text-slate-300" data-testid="creative-handoff-resolved-prompt">
								{handoff.resolved_prompt_preview}
							</p>
						</div>
					)}
				</div>
			)}
		</div>
	);
}
