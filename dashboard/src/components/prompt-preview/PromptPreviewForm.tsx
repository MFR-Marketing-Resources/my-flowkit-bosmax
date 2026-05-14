import { useMemo } from "react";
import type { PromptPreviewRequest } from "../../types";

type PromptPreviewDraft = PromptPreviewRequest & {
	asset_bindings_text: string;
	product_payload_text: string;
};

function parseJsonArray(input: string): unknown[] {
	if (!input.trim()) return [];
	const parsed = JSON.parse(input);
	return Array.isArray(parsed) ? parsed : [];
}

function parseJsonObject(input: string): Record<string, unknown> | null {
	if (!input.trim()) return null;
	const parsed = JSON.parse(input);
	return parsed && typeof parsed === "object" && !Array.isArray(parsed)
		? (parsed as Record<string, unknown>)
		: null;
}

export function buildPromptPreviewRequest(
	draft: PromptPreviewDraft,
): PromptPreviewRequest {
	return {
		source_route: draft.source_route,
		destination_mode: draft.destination_mode,
		output_type: draft.output_type,
		product_id: draft.product_id || undefined,
		product_payload:
			parseJsonObject(draft.product_payload_text) ||
			draft.product_payload ||
			undefined,
		avatar_id: draft.avatar_id || undefined,
		wardrobe_id: draft.wardrobe_id || undefined,
		headwear_style: draft.headwear_style || undefined,
		scene_context: draft.scene_context || undefined,
		camera_style: draft.camera_style || undefined,
		camera_behavior: draft.camera_behavior || undefined,
		trigger_id: draft.trigger_id || undefined,
		silo: draft.silo || undefined,
		formula: draft.formula || undefined,
		language: draft.language || undefined,
		platform: draft.platform || undefined,
		engine: draft.engine || undefined,
		requested_scene: draft.requested_scene || undefined,
		requested_character: draft.requested_character || undefined,
		requested_language: draft.requested_language || undefined,
		requested_platform: draft.requested_platform || undefined,
		requested_engine: draft.requested_engine || undefined,
		asset_bindings: parseJsonArray(draft.asset_bindings_text) as Record<
			string,
			unknown
		>[],
		target_duration_seconds: Number(draft.target_duration_seconds || 8),
		block_duration_seconds: Number(draft.block_duration_seconds || 8),
		extension_strategy: draft.extension_strategy || "NONE",
		include_temporal_plan: Boolean(draft.include_temporal_plan),
		strict_validation: Boolean(draft.strict_validation),
		dry_run_only: true,
	};
}

export default function PromptPreviewForm({
	draft,
	onChange,
	onSubmit,
	loading,
	error,
}: {
	draft: PromptPreviewDraft;
	onChange: (patch: Partial<PromptPreviewDraft>) => void;
	onSubmit: () => void;
	loading: boolean;
	error: string | null;
}) {
	const previewRequest = useMemo(() => {
		try {
			return buildPromptPreviewRequest(draft);
		} catch {
			return null;
		}
	}, [draft]);

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex items-start justify-between gap-3">
				<div>
					<div className="text-sm font-semibold text-slate-100">
						Offline Prompt Preview
					</div>
					<div className="mt-1 text-[11px] text-slate-400">
						Preview is offline-only. No Google Flow execution, no Chrome
						extension execution, and no batch execution are allowed here.
					</div>
				</div>
				<span className="inline-flex rounded-full border border-slate-600 bg-slate-950 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-200">
					dry_run_only=true
				</span>
			</div>

			<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
				{[
					["source_route", "Source Route"],
					["destination_mode", "Destination Mode"],
					["output_type", "Output Type"],
					["product_id", "Product ID"],
					["avatar_id", "Avatar ID"],
					["wardrobe_id", "Wardrobe ID"],
					["headwear_style", "Headwear Style"],
					["scene_context", "Scene Context"],
					["camera_style", "Camera Style"],
					["camera_behavior", "Camera Behavior"],
					["trigger_id", "Trigger ID"],
					["silo", "Silo"],
					["formula", "Formula"],
					["language", "Language"],
					["platform", "Platform"],
					["engine", "Engine Profile"],
					["requested_scene", "Requested Scene"],
					["requested_character", "Requested Character"],
				].map(([key, label]) => (
					<label
						key={key}
						className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3"
					>
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							{label}
						</div>
						{key === "source_route" ? (
							<select
								value={draft.source_route || "PRODUCT_DRIVEN_AUTO"}
								onChange={(event) =>
									onChange({ source_route: event.target.value })
								}
								className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="PRODUCT_DRIVEN_AUTO">PRODUCT_DRIVEN_AUTO</option>
								<option value="REGISTRY_DRIVEN_MANUAL_ASSISTED">
									REGISTRY_DRIVEN_MANUAL_ASSISTED
								</option>
							</select>
						) : key === "destination_mode" ? (
							<select
								value={draft.destination_mode || "IMAGE"}
								onChange={(event) =>
									onChange({ destination_mode: event.target.value })
								}
								className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="TEXT_TO_VIDEO">TEXT_TO_VIDEO</option>
								<option value="FRAMES">FRAMES</option>
								<option value="INGREDIENTS">INGREDIENTS</option>
								<option value="IMAGE">IMAGE</option>
							</select>
						) : key === "output_type" ? (
							<select
								value={draft.output_type || "IMAGE_PROMPT"}
								onChange={(event) =>
									onChange({ output_type: event.target.value })
								}
								className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="IMAGE_PROMPT">IMAGE_PROMPT</option>
								<option value="VIDEO_9_SECTION_PROMPT">
									VIDEO_9_SECTION_PROMPT
								</option>
								<option value="PROMPT_BLOCK_PLAN">PROMPT_BLOCK_PLAN</option>
							</select>
						) : (
							<input
								value={String(
									(draft as unknown as Record<string, unknown>)[key] || "",
								)}
								onChange={(event) =>
									onChange({
										[key]: event.target.value,
									} as Partial<PromptPreviewDraft>)
								}
								className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							/>
						)}
					</label>
				))}

				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Target Duration Seconds
					</div>
					<select
						value={draft.target_duration_seconds || 8}
						onChange={(event) =>
							onChange({ target_duration_seconds: Number(event.target.value) })
						}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value={8}>8</option>
						<option value={16}>16</option>
						<option value={24}>24</option>
						<option value={32}>32</option>
					</select>
				</label>

				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Block Duration Seconds
					</div>
					<select
						value={draft.block_duration_seconds || 8}
						onChange={(event) =>
							onChange({ block_duration_seconds: Number(event.target.value) })
						}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value={8}>8</option>
					</select>
				</label>

				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Extension Strategy
					</div>
					<select
						value={draft.extension_strategy || "NONE"}
						onChange={(event) =>
							onChange({ extension_strategy: event.target.value })
						}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="NONE">NONE</option>
						<option value="EXTEND_CONTINUITY">EXTEND_CONTINUITY</option>
						<option value="INSERT_JUMP_TO">INSERT_JUMP_TO</option>
						<option value="MIXED">MIXED</option>
					</select>
				</label>
			</div>

			<div className="mt-4 grid gap-4 lg:grid-cols-2">
				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Product Payload JSON
					</div>
					<textarea
						value={draft.product_payload_text}
						onChange={(event) =>
							onChange({ product_payload_text: event.target.value })
						}
						rows={8}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
						placeholder='{"id":"prod-001","product_display_name":"Atlas Bottle"}'
					/>
				</label>

				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Asset Bindings JSON Array
					</div>
					<textarea
						value={draft.asset_bindings_text}
						onChange={(event) =>
							onChange({ asset_bindings_text: event.target.value })
						}
						rows={8}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
						placeholder='[{"asset_role":"START_FRAME","asset_source":"UPLOAD","asset_id":"frame-001"}]'
					/>
				</label>
			</div>

			<div className="mt-4 flex flex-wrap items-center gap-4">
				<label className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs text-slate-200">
					<input
						type="checkbox"
						checked={Boolean(draft.include_temporal_plan)}
						onChange={(event) =>
							onChange({ include_temporal_plan: event.target.checked })
						}
					/>
					Include Temporal Plan
				</label>
				<label className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs text-slate-200">
					<input
						type="checkbox"
						checked={Boolean(draft.strict_validation)}
						onChange={(event) =>
							onChange({ strict_validation: event.target.checked })
						}
					/>
					Strict Validation
				</label>
			</div>

			<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
				Preview-only guardrails: no Google Flow execution, no Chrome extension
				execution, no batch execution, and dry-run remains hard-locked true.
			</div>

			{error ? (
				<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
					{error}
				</div>
			) : null}

			<div className="mt-4 flex items-center justify-between gap-4">
				<div className="text-[10px] text-slate-500">
					Request payload is validated locally before submit. Invalid JSON
					blocks submission.
				</div>
				<button
					type="button"
					onClick={onSubmit}
					disabled={loading || !previewRequest}
					className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-xs font-semibold text-blue-200 disabled:opacity-50"
				>
					{loading ? "Running Offline Preview..." : "Run Offline Preview"}
				</button>
			</div>
		</section>
	);
}
