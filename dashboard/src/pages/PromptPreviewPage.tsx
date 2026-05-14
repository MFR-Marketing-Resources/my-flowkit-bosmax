import { useState } from "react";
import { runOfflinePromptPreview } from "../api/promptPreview";
import PromptPreviewForm, {
	buildPromptPreviewRequest,
} from "../components/prompt-preview/PromptPreviewForm";
import PromptPreviewResultPanel from "../components/prompt-preview/PromptPreviewResultPanel";
import type { PromptPreviewRequest, PromptPreviewResponse } from "../types";

type PromptPreviewDraft = PromptPreviewRequest & {
	asset_bindings_text: string;
	product_payload_text: string;
};

function createInitialDraft(): PromptPreviewDraft {
	return {
		source_route: "PRODUCT_DRIVEN_AUTO",
		destination_mode: "IMAGE",
		output_type: "IMAGE_PROMPT",
		product_id: "",
		asset_bindings: [],
		product_payload_text:
			'{\n  "id": "prod-001",\n  "product_display_name": "Atlas Bottle"\n}',
		asset_bindings_text: "[]",
		target_duration_seconds: 8,
		block_duration_seconds: 8,
		extension_strategy: "NONE",
		include_temporal_plan: false,
		strict_validation: false,
		dry_run_only: true,
		avatar_id: "",
		wardrobe_id: "",
		headwear_style: "",
		scene_context: "",
		camera_style: "",
		camera_behavior: "",
		trigger_id: "",
		silo: "",
		formula: "",
		language: "Malay",
		platform: "TikTok",
		engine: "VEO_3_1",
		requested_scene: "",
		requested_character: "",
	};
}

export default function PromptPreviewPage() {
	const [draft, setDraft] = useState<PromptPreviewDraft>(createInitialDraft);
	const [result, setResult] = useState<PromptPreviewResponse | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	async function handleSubmit() {
		setLoading(true);
		setError(null);
		try {
			const request = buildPromptPreviewRequest(draft);
			const preview = await runOfflinePromptPreview(request);
			setResult(preview);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to run offline prompt preview",
			);
		} finally {
			setLoading(false);
		}
	}

	return (
		<div className="flex flex-col gap-6 p-4 md:p-6">
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
					Offline Prompt Preview
				</div>
				<div className="mt-2 max-w-4xl text-sm text-slate-300">
					This UI is preview-only. It calls the offline prompt preview API and
					shows planner, adapter, composer, and temporal outputs without any
					Google Flow execution, Chrome extension execution, or batch execution.
				</div>
				<div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
					{[
						"Preview is offline-only",
						"No Google Flow execution",
						"No Chrome extension execution",
						"No batch execution",
					].map((item) => (
						<div
							key={item}
							className="rounded-2xl border border-slate-800 bg-slate-900/60 px-3 py-3 text-[11px] text-slate-300"
						>
							{item}
						</div>
					))}
				</div>
			</section>

			<div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
				<PromptPreviewForm
					draft={draft}
					onChange={(patch) =>
						setDraft((current) => ({
							...current,
							...patch,
							dry_run_only: true,
						}))
					}
					onSubmit={handleSubmit}
					loading={loading}
					error={error}
				/>
				<PromptPreviewResultPanel result={result} />
			</div>
		</div>
	);
}
