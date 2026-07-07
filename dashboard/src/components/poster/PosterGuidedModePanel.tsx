import { useMemo, useState } from "react";
import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterCopyKit } from "../../types/posterCopyRecommendations";
import { kitToDraft } from "../../poster/posterKitToDraft";

export default function PosterGuidedModePanel({
	draft,
	kits,
	onDraftChange,
	onUseForPromptDraft,
	promptDraftLoading,
}: {
	draft: PosterBuilderDraft;
	kits: PosterCopyKit[];
	onDraftChange: (d: PosterBuilderDraft) => void;
	onUseForPromptDraft: () => void;
	promptDraftLoading: boolean;
}) {
	const angles = useMemo(
		() => [...new Set(kits.map((k) => k.angle).filter(Boolean))],
		[kits],
	);
	const [angle, setAngle] = useState("");
	const [hook, setHook] = useState("");

	const hooks = useMemo(
		() =>
			[...new Set(kits.filter((k) => !angle || k.angle === angle).map((k) => k.hook))],
		[kits, angle],
	);
	const subhooks = useMemo(
		() =>
			kits.filter(
				(k) =>
					(!angle || k.angle === angle) && (!hook || k.hook === hook),
			),
		[kits, angle, hook],
	);

	const applyKit = (kit: PosterCopyKit) => {
		onDraftChange(kitToDraft(kit, draft));
	};

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid="poster-guided-mode-panel"
		>
			<h3 className="text-sm font-bold text-slate-100">Guided Build</h3>
			<p className="mt-1 text-xs text-slate-400">
				Progressive picks from recommended kits — no blank typing required.
			</p>

			<label className="mt-4 block">
				<span className="text-[10px] font-bold uppercase text-slate-500">Angle</span>
				<select
					data-testid="guided-angle-select"
					className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm"
					value={angle}
					onChange={(e) => {
						setAngle(e.target.value);
						setHook("");
					}}
				>
					<option value="">Choose angle…</option>
					{angles.map((a) => (
						<option key={a} value={a}>
							{a}
						</option>
					))}
				</select>
			</label>

			<label className="mt-3 block">
				<span className="text-[10px] font-bold uppercase text-slate-500">Hook</span>
				<select
					data-testid="guided-hook-select"
					className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm"
					value={hook}
					onChange={(e) => setHook(e.target.value)}
					disabled={!angle}
				>
					<option value="">Choose hook…</option>
					{hooks.map((h) => (
						<option key={h} value={h}>
							{h}
						</option>
					))}
				</select>
			</label>

			<div className="mt-3">
				<span className="text-[10px] font-bold uppercase text-slate-500">Subhook & USP</span>
				<div className="mt-2 space-y-2">
					{subhooks.slice(0, 5).map((kit) => (
						<button
							key={kit.kit_id}
							type="button"
							data-testid={`guided-kit-${kit.kit_id}`}
							onClick={() => applyKit(kit)}
							className="block w-full rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-left text-xs text-slate-300 hover:border-blue-500/30"
						>
							<div>{kit.subhook}</div>
							<div className="text-slate-500">
								{[kit.usp_1, kit.usp_2, kit.usp_3].filter(Boolean).join(" · ")}
							</div>
							<div className="text-slate-400">CTA: {kit.cta}</div>
						</button>
					))}
				</div>
			</div>

			<button
				type="button"
				data-testid="guided-use-prompt-draft"
				disabled={promptDraftLoading || !draft.hook}
				onClick={onUseForPromptDraft}
				className="mt-4 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
			>
				Use selection for prompt draft
			</button>
		</section>
	);
}