import { useEffect, useMemo, useRef } from "react";
import { usePromptToolHydration } from "../prompt-tool/usePromptToolHydration";
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

function buildProductPayloadText(product: Record<string, unknown>): string {
	return JSON.stringify(product, null, 2);
}

function FieldShell({
	label,
	children,
	helper,
}: {
	label: string;
	children: React.ReactNode;
	helper?: string;
}) {
	return (
		<label className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div className="mt-2">{children}</div>
			{helper ? (
				<div className="mt-2 text-[10px] text-slate-500">{helper}</div>
			) : null}
		</label>
	);
}

function SelectField({
	value,
	onChange,
	options,
	placeholder = "Select an option",
}: {
	value: string;
	onChange: (value: string) => void;
	options: Array<{ value: string; label: string }>;
	placeholder?: string;
}) {
	return (
		<select
			value={value}
			onChange={(event) => onChange(event.target.value)}
			className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
		>
			<option value="">{placeholder}</option>
			{options.map((option) => (
				<option key={`${option.value}:${option.label}`} value={option.value}>
					{option.label}
				</option>
			))}
		</select>
	);
}

function TextField({
	value,
	onChange,
}: {
	value: string;
	onChange: (value: string) => void;
}) {
	return (
		<input
			value={value}
			onChange={(event) => onChange(event.target.value)}
			className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
		/>
	);
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
	const hydration = usePromptToolHydration();
	const lastHydratedProductId = useRef<string | null>(null);
	const previewRequest = useMemo(() => {
		try {
			return buildPromptPreviewRequest(draft);
		} catch {
			return null;
		}
	}, [draft]);
	const selectedProduct = draft.product_id
		? hydration.productById[draft.product_id]
		: null;
	const selectedOperatorProduct = hydration.getOperatorProductFor(draft.product_id);

	useEffect(() => {
		if (!draft.product_id) {
			lastHydratedProductId.current = null;
			return;
		}
		if (lastHydratedProductId.current === draft.product_id || !selectedProduct) {
			return;
		}
		lastHydratedProductId.current = draft.product_id;
		const productPayload = {
			id: selectedProduct.id,
			product_display_name: selectedProduct.product_display_name,
			raw_product_title: selectedProduct.raw_product_title,
			category: selectedProduct.category,
			subcategory: selectedProduct.subcategory,
			type: selectedProduct.type,
			scene_context: selectedProduct.scene_context,
			camera_style: selectedProduct.camera_style,
			camera_behavior: selectedProduct.camera_behavior,
			trigger_id: selectedProduct.trigger_id,
			silo: selectedProduct.silo,
			formula: selectedProduct.formula,
		};
		onChange({
			product_payload: productPayload,
			product_payload_text: buildProductPayloadText(productPayload),
			scene_context: selectedProduct.scene_context || "",
			camera_style: selectedProduct.camera_style || "",
			camera_behavior: selectedProduct.camera_behavior || "",
			trigger_id: selectedProduct.trigger_id || "",
			silo: selectedProduct.silo || "",
			formula: selectedProduct.formula || "",
			requested_scene: selectedProduct.scene_context || "",
			output_type:
				draft.source_route === "PRODUCT_DRIVEN_AUTO"
					? "VIDEO_9_SECTION_PROMPT"
					: draft.output_type,
		});
	}, [draft.output_type, draft.product_id, draft.source_route, onChange, selectedProduct]);

	const productOptions = hydration.products.map((product) => ({
		value: product.id,
		label: `${product.product_display_name} (${product.id})`,
	}));
	const avatarOptions = hydration.avatarOptions.map((value) => ({ value, label: value }));
	const requestedCharacterOptions = hydration.requestedCharacterOptions.map(
		(value) => ({ value, label: value }),
	);
	const sceneContextOptions = hydration.sceneContextOptions.map((value) => ({
		value,
		label: value,
	}));
	const cameraStyleOptions = hydration.cameraStyleOptions.map((value) => ({
		value,
		label: value,
	}));
	const cameraBehaviorOptions = hydration.cameraBehaviorOptions.map((value) => ({
		value,
		label: value,
	}));
	const triggerOptions = hydration.triggerOptions.map((value) => ({ value, label: value }));
	const siloOptions = hydration.siloOptions.map((value) => ({ value, label: value }));
	const formulaOptions = hydration.formulaOptions.map((value) => ({
		value,
		label: value,
	}));
	const languageOptions = hydration.languageOptions.map((value) => ({
		value,
		label: value,
	}));
	const platformOptions = hydration.platformOptions.map((value) => ({
		value,
		label: value,
	}));
	const engineOptions = hydration.engineOptions.map((value) => ({
		value,
		label: value,
	}));
	const headwearOptions = hydration.headwearOptions.map((value) => ({
		value,
		label: value,
	}));

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

			{hydration.loading ? (
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-[11px] text-slate-400">
					Loading registry-backed dropdowns and product intelligence...
				</div>
			) : null}
			{hydration.error ? (
				<div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
					{hydration.error}
				</div>
			) : null}

			<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
				<FieldShell label="Source Route">
					<SelectField
						value={draft.source_route || "PRODUCT_DRIVEN_AUTO"}
						onChange={(value) => onChange({ source_route: value })}
						options={[
							{
								value: "PRODUCT_DRIVEN_AUTO",
								label: "PRODUCT_DRIVEN_AUTO",
							},
							{
								value: "REGISTRY_DRIVEN_MANUAL_ASSISTED",
								label: "REGISTRY_DRIVEN_MANUAL_ASSISTED",
							},
						]}
						placeholder="Select a route"
					/>
				</FieldShell>

				<FieldShell label="Destination Mode">
					<SelectField
						value={draft.destination_mode || "IMAGE"}
						onChange={(value) => onChange({ destination_mode: value })}
						options={[
							{ value: "TEXT_TO_VIDEO", label: "TEXT_TO_VIDEO" },
							{ value: "FRAMES", label: "FRAMES" },
							{ value: "INGREDIENTS", label: "INGREDIENTS" },
							{ value: "IMAGE", label: "IMAGE" },
						]}
						placeholder="Select a destination mode"
					/>
				</FieldShell>

				<FieldShell
					label="Output Type"
					helper="Product-driven selection defaults to VIDEO_9_SECTION_PROMPT unless you explicitly switch away."
				>
					<SelectField
						value={draft.output_type || "VIDEO_9_SECTION_PROMPT"}
						onChange={(value) => onChange({ output_type: value })}
						options={[
							{ value: "IMAGE_PROMPT", label: "IMAGE_PROMPT" },
							{
								value: "VIDEO_9_SECTION_PROMPT",
								label: "VIDEO_9_SECTION_PROMPT",
							},
							{ value: "PROMPT_BLOCK_PLAN", label: "PROMPT_BLOCK_PLAN" },
						]}
						placeholder="Select an output type"
					/>
				</FieldShell>

				<FieldShell
					label="Product"
					helper="Selecting a product hydrates payload JSON plus scene, camera, trigger, silo, and formula fields."
				>
					<SelectField
						value={draft.product_id || ""}
						onChange={(value) => onChange({ product_id: value })}
						options={productOptions}
						placeholder="Select a product to hydrate"
					/>
				</FieldShell>

				<FieldShell
					label="Avatar ID"
					helper="Avatar IDs come from the operator pack. They are not character-row registry truth."
				>
					<SelectField
						value={draft.avatar_id || ""}
						onChange={(value) => onChange({ avatar_id: value })}
						options={avatarOptions}
						placeholder="Select an operator-pack avatar"
					/>
				</FieldShell>

				<FieldShell
					label="Wardrobe ID"
					helper="No repo-backed wardrobe registry exists in this checkout. Manual fallback remains required."
				>
					<TextField
						value={draft.wardrobe_id || ""}
						onChange={(value) => onChange({ wardrobe_id: value })}
					/>
				</FieldShell>

				<FieldShell
					label="Headwear Style"
					helper="Operator-pack headwear suggestions are not canonical registry truth."
				>
					<SelectField
						value={draft.headwear_style || ""}
						onChange={(value) => onChange({ headwear_style: value })}
						options={headwearOptions}
						placeholder="Select operator-pack headwear"
					/>
				</FieldShell>

				<FieldShell label="Scene Context">
					<SelectField
						value={draft.scene_context || ""}
						onChange={(value) => onChange({ scene_context: value })}
						options={sceneContextOptions}
						placeholder="Select scene context"
					/>
				</FieldShell>

				<FieldShell label="Camera Style">
					<SelectField
						value={draft.camera_style || ""}
						onChange={(value) => onChange({ camera_style: value })}
						options={cameraStyleOptions}
						placeholder="Select camera style"
					/>
				</FieldShell>

				<FieldShell label="Camera Behavior">
					<SelectField
						value={draft.camera_behavior || ""}
						onChange={(value) => onChange({ camera_behavior: value })}
						options={cameraBehaviorOptions}
						placeholder="Select camera behavior"
					/>
				</FieldShell>

				<FieldShell label="Trigger ID">
					<SelectField
						value={draft.trigger_id || ""}
						onChange={(value) => onChange({ trigger_id: value })}
						options={triggerOptions}
						placeholder="Select trigger"
					/>
				</FieldShell>

				<FieldShell label="Silo">
					<SelectField
						value={draft.silo || ""}
						onChange={(value) => onChange({ silo: value })}
						options={siloOptions}
						placeholder="Select silo"
					/>
				</FieldShell>

				<FieldShell label="Formula">
					<SelectField
						value={draft.formula || ""}
						onChange={(value) => onChange({ formula: value })}
						options={formulaOptions}
						placeholder="Select formula"
					/>
				</FieldShell>

				<FieldShell label="Language">
					<SelectField
						value={draft.language || ""}
						onChange={(value) => onChange({ language: value })}
						options={languageOptions}
						placeholder="Select language"
					/>
				</FieldShell>

				<FieldShell label="Platform">
					<SelectField
						value={draft.platform || ""}
						onChange={(value) => onChange({ platform: value })}
						options={platformOptions}
						placeholder="Select platform"
					/>
				</FieldShell>

				<FieldShell label="Engine Profile">
					<SelectField
						value={draft.engine || ""}
						onChange={(value) => onChange({ engine: value })}
						options={engineOptions}
						placeholder="Select engine profile"
					/>
				</FieldShell>

				<FieldShell label="Requested Scene">
					<SelectField
						value={draft.requested_scene || ""}
						onChange={(value) => onChange({ requested_scene: value })}
						options={sceneContextOptions}
						placeholder="Select requested scene"
					/>
				</FieldShell>

				<FieldShell
					label="Requested Character"
					helper="Character labels come from repo-backed character rows when present."
				>
					<SelectField
						value={draft.requested_character || ""}
						onChange={(value) => onChange({ requested_character: value })}
						options={requestedCharacterOptions}
						placeholder="Select requested character"
					/>
				</FieldShell>

				<FieldShell label="Target Duration Seconds">
					<SelectField
						value={String(draft.target_duration_seconds || 8)}
						onChange={(value) =>
							onChange({ target_duration_seconds: Number(value) })
						}
						options={[
							{ value: "8", label: "8" },
							{ value: "16", label: "16" },
							{ value: "24", label: "24" },
							{ value: "32", label: "32" },
						]}
					/>
				</FieldShell>

				<FieldShell label="Block Duration Seconds">
					<SelectField
						value={String(draft.block_duration_seconds || 8)}
						onChange={(value) =>
							onChange({ block_duration_seconds: Number(value) })
						}
						options={[{ value: "8", label: "8" }]}
					/>
				</FieldShell>

				<FieldShell label="Extension Strategy">
					<SelectField
						value={draft.extension_strategy || "NONE"}
						onChange={(value) => onChange({ extension_strategy: value })}
						options={[
							{ value: "NONE", label: "NONE" },
							{
								value: "EXTEND_CONTINUITY",
								label: "EXTEND_CONTINUITY",
							},
							{ value: "INSERT_JUMP_TO", label: "INSERT_JUMP_TO" },
							{ value: "MIXED", label: "MIXED" },
						]}
					/>
				</FieldShell>
			</div>

			{selectedProduct ? (
				<div className="mt-4 grid gap-4 lg:grid-cols-2">
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Product Autofill
						</div>
						<div className="mt-3 grid gap-2 md:grid-cols-2">
							<div>Scene: {selectedProduct.scene_context || "NOT_PROVIDED"}</div>
							<div>Camera style: {selectedProduct.camera_style || "NOT_PROVIDED"}</div>
							<div>Camera behavior: {selectedProduct.camera_behavior || "NOT_PROVIDED"}</div>
							<div>Trigger: {selectedProduct.trigger_id || "NOT_PROVIDED"}</div>
							<div>Silo: {selectedProduct.silo || "NOT_PROVIDED"}</div>
							<div>Formula: {selectedProduct.formula || "NOT_PROVIDED"}</div>
						</div>
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Operator Pack Copy Signals
						</div>
						<div className="mt-2 text-[10px] text-slate-500">
							Hook, USP, and CTA come from the operator workbook when a matching product exists. They are not canonical asset-registry truth.
						</div>
						<div className="mt-3 grid gap-2">
							<div>Hook: {selectedOperatorProduct?.hook || "NOT_FOUND"}</div>
							<div>USP 1: {selectedOperatorProduct?.usp_1 || "NOT_FOUND"}</div>
							<div>USP 2: {selectedOperatorProduct?.usp_2 || "NOT_FOUND"}</div>
							<div>USP 3: {selectedOperatorProduct?.usp_3 || "NOT_FOUND"}</div>
							<div>CTA: {selectedOperatorProduct?.cta || "NOT_FOUND"}</div>
						</div>
					</div>
				</div>
			) : null}

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
