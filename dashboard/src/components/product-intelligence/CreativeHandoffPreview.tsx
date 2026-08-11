import { useState } from "react";

import {
	getCreativeHandoffForProduct,
	type CreativeHandoff,
} from "../../api/creativeIntelligence";

/** Map fail-closed handoff errors to operator-facing guidance. */
export function handoffBlockedMessage(raw: string): string {
	const message = raw || "";
	if (message.includes("SELECTION_NOT_APPROVED")) {
		return "This creative plan is not approved yet. Save your changes, then approve the plan above before preparing a handoff.";
	}
	if (message.includes("SELECTION_NOT_FOUND")) {
		return "No saved creative plan for this product yet. Save and approve the plan above first.";
	}
	if (message.includes("PRODUCT_NOT_FOUND")) {
		return "Product not found — reselect a product.";
	}
	if (message.includes("INVALID_AVATAR_CODE")) {
		return "The selected avatar is no longer valid. Update and approve the creative plan again.";
	}
	if (message.includes("INVALID_SCENE_TEMPLATE_ID")) {
		return "The selected scene template is no longer valid. Update and approve the creative plan again.";
	}
	if (message.includes("INVALID_CAMERA_PRESET_CODE")) {
		return "The derived camera preset is no longer valid. Update and approve the creative plan again.";
	}
	return `Handoff blocked: ${message}`;
}

/** Read-only, explicit generation handoff preview. It never generates or charges. */
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
			className="rounded-2xl border border-indigo-500/25 bg-indigo-500/5 p-4"
		>
			<div className="flex flex-wrap items-start justify-between gap-2">
				<div>
					<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-300">
						Final check
					</p>
					<h3 className="mt-1 text-sm font-bold text-indigo-100">
						Generation handoff preview
					</h3>
				</div>
				<span className="rounded-full bg-amber-900/50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
					Preview only · no generation
				</span>
			</div>
			<p className="mt-2 max-w-3xl text-[11px] leading-relaxed text-slate-400">
				Check the approved plan with the product and avatar placeholders resolved. This
				button only reads the handoff; it does not queue work or spend credits.
			</p>

			<button
				type="button"
				data-testid="creative-handoff-prepare"
				disabled={busy}
				onClick={loadHandoff}
				className="mt-3 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
			>
				{busy ? "Preparing…" : "Preview approved plan"}
			</button>

			{error && (
				<p
					className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-200"
					role="alert"
					data-testid="creative-handoff-error"
				>
					{handoffBlockedMessage(error)}
				</p>
			)}

			{handoff && (
				<div
					data-testid="creative-handoff-payload"
					className="mt-4 border-t border-slate-800 pt-4"
				>
					<div
						className="rounded-lg bg-amber-950/40 px-3 py-2 text-[11px] text-amber-200"
						data-testid="creative-handoff-banner"
					>
						{handoff.handoff_status} · Preview only. Nothing is generated or charged.
					</div>
					<div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
						<HandoffValue label="Status" value={handoff.selection_status} />
						<HandoffValue
							label="Avatar"
							value={
								[handoff.avatar.avatar_code, handoff.avatar.character_name]
									.filter(Boolean)
									.join(" · ") || "—"
							}
						/>
						<HandoffValue
							label="Scene"
							value={
								[handoff.scene_template.template_id, handoff.scene_template.variant]
									.filter(Boolean)
									.join(" · ") || "—"
							}
						/>
						<HandoffValue
							label="Camera"
							value={
								[
									handoff.camera_preset.preset_code,
									handoff.camera_preset.shot_type,
									handoff.camera_preset.distance_angle,
									handoff.camera_preset.movement,
								]
									.filter(Boolean)
									.join(" · ") || "—"
							}
						/>
					</div>
					{handoff.resolved_prompt_preview && (
						<details className="mt-3 rounded-lg border border-slate-800 bg-slate-950/45 p-3">
							<summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-indigo-200 hover:text-indigo-100">
								View resolved prompt
							</summary>
							<p
								className="mt-2 break-words font-mono text-[10px] leading-relaxed text-slate-300"
								data-testid="creative-handoff-resolved-prompt"
							>
								{handoff.resolved_prompt_preview}
							</p>
						</details>
					)}
				</div>
			)}
		</div>
	);
}

function HandoffValue({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-lg bg-slate-950/45 px-3 py-2">
			<div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
			<div className="mt-1 break-words font-mono text-[11px] text-slate-200">{value}</div>
		</div>
	);
}
