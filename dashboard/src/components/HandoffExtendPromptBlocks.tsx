import { useCallback, useState } from "react";
import { ClipboardCopy } from "lucide-react";
import { resolvePromptRepresentationPresentation } from "../utils/promptRepresentationUi";
import type { PromptRepresentationFields } from "../utils/promptRepresentationUi";

type HandoffAllocation = {
	assigned_story_beats: { role: string }[];
	exact_dialogue_slice?: string;
	continuation_instruction?: string;
	seam_policy?: string;
};

export type HandoffPromptBlock = PromptRepresentationFields & {
	block_index: number;
	duration_seconds?: number;
	start_s?: number | null;
	end_s?: number | null;
	is_final?: boolean | null;
	allocation?: HandoffAllocation | null;
	exact_dialogue_slice?: string | null;
	previous_block_index?: number | null;
	audio_seam_contract?: {
		audio_seam_out?: string | null;
		voice_active_in_final_second?: boolean;
	} | null;
};

function HandoffPromptCopyButton({
	text,
	label,
	testId,
}: {
	text: string;
	label: string;
	testId: string;
}) {
	const [copied, setCopied] = useState(false);
	const handleCopy = useCallback(() => {
		void navigator.clipboard.writeText(text || "").then(() => {
			setCopied(true);
			setTimeout(() => setCopied(false), 1500);
		});
	}, [text]);
	return (
		<button
			type="button"
			data-testid={testId}
			aria-label={label}
			onClick={handleCopy}
			className="flex items-center gap-1 text-xs font-bold px-2 py-1 rounded border border-indigo-500/40"
		>
			<ClipboardCopy size={12} />
			{copied ? "Copied!" : label}
		</button>
	);
}

export function HandoffExtendPromptBlocks({
	blocks,
	promptStepStart = 1,
}: {
	blocks: HandoffPromptBlock[];
	promptStepStart?: number;
}) {
	return (
		<div className="space-y-3" data-testid="handoff-extend-prompt-blocks">
			<div className="rounded-lg border border-amber-500/30 bg-amber-500/8 px-3 py-2 text-xs text-amber-200">
				EXTEND mode — {blocks.length} blocks. Copy and generate Block 1 first, then continue with Block 2.
			</div>
			{blocks.map((block, i) => {
				const presentation = resolvePromptRepresentationPresentation(block);
				const independent = presentation.independentText;
				const primary = presentation.primaryCopyText;
				return (
					<div
						key={block.block_index}
						className="space-y-2"
						data-testid={`handoff-block-${block.block_index}`}
					>
						<div
							className="text-[10px] font-bold uppercase tracking-widest text-indigo-300"
							data-testid={`handoff-rep-${block.block_index}`}
						>
							{presentation.badgeLabel}
						</div>
						{presentation.showExtendUnavailable ? (
							<div
								data-testid={`extend-not-available-${block.block_index}`}
								className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100"
							>
								Extend Not Available — no flow_extend_prompt_text on this package. Independent Block only.
							</div>
						) : null}
						{presentation.showExtendUnavailable && presentation.badgeLabel.includes("INVALID") ? (
							<div
								data-testid={`invalid-extend-${block.block_index}`}
								className="text-xs text-red-300"
							>
								{presentation.helpText}
							</div>
						) : null}
						<HandoffPromptCopyButton
							text={primary}
							label={`Block ${block.block_index} — ${presentation.primaryCopyLabel} (${block.duration_seconds}s${block.start_s != null && block.end_s != null ? ` · ${block.start_s}–${block.end_s}s` : ""})${block.is_final ? " · FINAL" : ""}`}
							testId={`handoff-copy-primary-${block.block_index}`}
						/>
						{presentation.showIndependentSecondary || presentation.showExtendPrimary ? (
							<HandoffPromptCopyButton
								text={independent}
								label={`Block ${block.block_index} — Copy Independent Block Prompt (standalone fallback)`}
								testId={`handoff-copy-independent-${block.block_index}`}
							/>
						) : null}
						{block.allocation ? (
							<div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-[11px] text-slate-400">
								<div>Allocated story: {block.allocation.assigned_story_beats.map((beat) => beat.role).join(" → ")}</div>
								<div className="mt-1">Allocated dialogue: {block.allocation.exact_dialogue_slice || block.exact_dialogue_slice || "(visual-only block)"}</div>
								<div className="mt-1">Seam: {block.allocation.seam_policy} · {block.allocation.continuation_instruction}</div>
								{block.previous_block_index ? (
									<div className="mt-1">Previous block: {block.previous_block_index}</div>
								) : null}
								{block.audio_seam_contract ? (
									<div className="mt-1">Audio seam: {block.audio_seam_contract.audio_seam_out || "—"}{block.audio_seam_contract.voice_active_in_final_second ? " · voice-active final second" : ""}</div>
								) : null}
							</div>
						) : null}
						<span data-testid={`handoff-step-${block.block_index}`} className="sr-only">
							{promptStepStart + i}
						</span>
					</div>
				);
			})}
		</div>
	);
}