import { useMemo } from "react";
import type { ProductAssetGeneratorRequest } from "../../types";

type ProductAssetGeneratorDraft = ProductAssetGeneratorRequest & {
	product_payload_text: string;
};

function parseJsonObject(input: string): Record<string, unknown> | null {
	if (!input.trim()) return null;
	const parsed = JSON.parse(input);
	return parsed && typeof parsed === "object" && !Array.isArray(parsed)
		? (parsed as Record<string, unknown>)
		: null;
}

export function buildProductAssetGeneratorRequest(
	draft: ProductAssetGeneratorDraft,
): ProductAssetGeneratorRequest {
	return {
		product_id: draft.product_id || undefined,
		product_payload:
			parseJsonObject(draft.product_payload_text) ||
			draft.product_payload ||
			undefined,
		target_asset_intent: draft.target_asset_intent,
		gender: draft.gender || undefined,
		ethnicity: draft.ethnicity || undefined,
		age_range: draft.age_range || undefined,
		scene_context: draft.scene_context || undefined,
		platform: draft.platform || undefined,
		language: draft.language || undefined,
		camera_style: draft.camera_style || undefined,
		camera_behavior: draft.camera_behavior || undefined,
		wardrobe: draft.wardrobe || undefined,
		headwear: draft.headwear || undefined,
		include_product_in_hand: Boolean(draft.include_product_in_hand),
		target_destination_mode: draft.target_destination_mode || undefined,
		strict_validation: Boolean(draft.strict_validation),
		dry_run_only: true,
	};
}

export default function ProductAssetGeneratorForm({
	draft,
	onChange,
	onSubmit,
	loading,
	error,
}: {
	draft: ProductAssetGeneratorDraft;
	onChange: (patch: Partial<ProductAssetGeneratorDraft>) => void;
	onSubmit: () => void;
	loading: boolean;
	error: string | null;
}) {
	const previewRequest = useMemo(() => {
		try {
			return buildProductAssetGeneratorRequest(draft);
		} catch {
			return null;
		}
	}, [draft]);

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex items-start justify-between gap-3">
				<div>
					<div className="text-sm font-semibold text-slate-100">
						Product Asset Generator Preview
					</div>
					<div className="mt-1 text-[11px] text-slate-400">
						Preview-only generator. No real image generation, no upload, no
						Google Flow execution, no Chrome extension execution, and no batch
						execution.
					</div>
				</div>
				<span className="inline-flex rounded-full border border-slate-600 bg-slate-950 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-200">
					dry_run_only=true
				</span>
			</div>

			<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Target Asset Intent
					</div>
					<select
						value={draft.target_asset_intent}
						onChange={(event) =>
							onChange({ target_asset_intent: event.target.value })
						}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="CHARACTER_CONCEPT">CHARACTER_CONCEPT</option>
						<option value="CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT">
							CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT
						</option>
						<option value="PRODUCT_LIFESTYLE_IMAGE_PROMPT">
							PRODUCT_LIFESTYLE_IMAGE_PROMPT
						</option>
						<option value="SCENE_REFERENCE_PROMPT">
							SCENE_REFERENCE_PROMPT
						</option>
						<option value="STYLE_REFERENCE_PROMPT">
							STYLE_REFERENCE_PROMPT
						</option>
						<option value="INGREDIENTS_ASSET_BUNDLE">
							INGREDIENTS_ASSET_BUNDLE
						</option>
					</select>
				</label>

				<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Target Destination Mode
					</div>
					<select
						value={draft.target_destination_mode || "IMAGE"}
						onChange={(event) =>
							onChange({ target_destination_mode: event.target.value })
						}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="TEXT_TO_VIDEO">TEXT_TO_VIDEO</option>
						<option value="FRAMES">FRAMES</option>
						<option value="INGREDIENTS">INGREDIENTS</option>
						<option value="IMAGE">IMAGE</option>
					</select>
				</label>

				{[
					["product_id", "Product ID"],
					["gender", "Gender"],
					["ethnicity", "Ethnicity"],
					["age_range", "Age Range"],
					["scene_context", "Scene Context"],
					["language", "Language"],
					["platform", "Platform"],
					["camera_style", "Camera Style"],
					["camera_behavior", "Camera Behavior"],
					["wardrobe", "Wardrobe"],
					["headwear", "Headwear"],
				].map(([key, label]) => (
					<label
						key={key}
						className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3"
					>
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							{label}
						</div>
						<input
							value={String(
								(draft as unknown as Record<string, unknown>)[key] || "",
							)}
							onChange={(event) =>
								onChange({
									[key]: event.target.value,
								} as Partial<ProductAssetGeneratorDraft>)
							}
							className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
						/>
					</label>
				))}
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
						rows={10}
						className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
						placeholder='{"id":"prod-001","product_display_name":"Atlas Bottle"}'
					/>
				</label>

				<div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Guardrails
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3 text-[11px] text-slate-300">
						Derived suggestions are not canonical truth. NOT_VERIFIED and
						DERIVED_FROM_PRODUCT_DATA warnings remain visible.
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3 text-[11px] text-slate-300">
						This response is preview-only. No generated character image exists
						yet, and nothing is Google-Flow-ready or Chrome-extension-visible
						yet.
					</div>
					<label className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-200">
						<input
							type="checkbox"
							checked={Boolean(draft.include_product_in_hand)}
							onChange={(event) =>
								onChange({ include_product_in_hand: event.target.checked })
							}
						/>
						Include Product In Hand
					</label>
					<label className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-200">
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
					{loading ? "Running Preview Generator..." : "Run Preview Generator"}
				</button>
			</div>
		</section>
	);
}
