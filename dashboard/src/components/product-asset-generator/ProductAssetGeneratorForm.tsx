import { useEffect, useMemo, useRef } from "react";
import { usePromptToolHydration } from "../prompt-tool/usePromptToolHydration";
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

function toSelectOptions(
	options: Array<{ value: string; label: string }>,
): Array<{ value: string; label: string }> {
	return options.map((option) => ({ value: option.value, label: option.label }));
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
	const hydration = usePromptToolHydration();
	const lastHydratedProductId = useRef<string | null>(null);
	const previewRequest = useMemo(() => {
		try {
			return buildProductAssetGeneratorRequest(draft);
		} catch {
			return null;
		}
	}, [draft]);
	const selectedProduct = draft.product_id
		? hydration.productById[draft.product_id]
		: null;
	const selectedAuthorityContext = hydration.getProductContext(draft.product_id);
	const selectedCopySignals = hydration.getCopySignals(draft.product_id);
	const selectedContextWarnings = hydration.getFieldWarnings(
		selectedAuthorityContext,
	);

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
			scene_context: selectedProduct.scene_context,
			camera_style: selectedProduct.camera_style,
			camera_behavior: selectedProduct.camera_behavior,
			formula: selectedProduct.formula,
			product_handling:
				selectedAuthorityContext?.visual.product_handling ||
				selectedProduct.handling_notes ||
				undefined,
			product_physics:
				selectedAuthorityContext?.visual.product_physics ||
				selectedProduct.section_5_product_physics_prompt ||
				undefined,
			overlay_hint: selectedAuthorityContext?.visual.overlay_hint || undefined,
		};
		onChange({
			product_payload: productPayload,
			product_payload_text: buildProductPayloadText(productPayload),
			scene_context: selectedProduct.scene_context || "",
			camera_style: selectedProduct.camera_style || "",
			camera_behavior: selectedProduct.camera_behavior || "",
		});
	}, [draft.product_id, onChange, selectedAuthorityContext, selectedProduct]);

	const productOptions = toSelectOptions(hydration.productOptions);
	const sceneContextOptions = toSelectOptions(hydration.sceneContextOptions);
	const languageOptions = toSelectOptions(hydration.languageOptions);
	const platformOptions = toSelectOptions(hydration.platformOptions);
	const cameraStyleOptions = toSelectOptions(hydration.cameraStyleOptions);
	const cameraBehaviorOptions = toSelectOptions(hydration.cameraBehaviorOptions);
	const headwearOptions = toSelectOptions(hydration.headwearOptions);

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

			{hydration.loading ? (
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-[11px] text-slate-400">
					Loading product, registry, and operator-pack dropdown sources...
				</div>
			) : null}
			{hydration.error ? (
				<div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
					{hydration.error}
				</div>
			) : null}

			<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
				<FieldShell label="Target Asset Intent">
					<SelectField
						value={draft.target_asset_intent}
						onChange={(value) => onChange({ target_asset_intent: value })}
						options={[
							{ value: "CHARACTER_CONCEPT", label: "CHARACTER_CONCEPT" },
							{
								value: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
								label: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
							},
							{
								value: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
								label: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
							},
							{
								value: "SCENE_REFERENCE_PROMPT",
								label: "SCENE_REFERENCE_PROMPT",
							},
							{
								value: "STYLE_REFERENCE_PROMPT",
								label: "STYLE_REFERENCE_PROMPT",
							},
							{
								value: "INGREDIENTS_ASSET_BUNDLE",
								label: "INGREDIENTS_ASSET_BUNDLE",
							},
						]}
						placeholder="Select a target asset intent"
					/>
				</FieldShell>

				<FieldShell label="Target Destination Mode">
					<SelectField
						value={draft.target_destination_mode || "IMAGE"}
						onChange={(value) => onChange({ target_destination_mode: value })}
						options={[
							{ value: "TEXT_TO_VIDEO", label: "TEXT_TO_VIDEO" },
							{ value: "FRAMES", label: "FRAMES" },
							{ value: "INGREDIENTS", label: "INGREDIENTS" },
							{ value: "IMAGE", label: "IMAGE" },
						]}
						placeholder="Select a target destination mode"
					/>
				</FieldShell>

				<FieldShell
					label="Product"
					helper="Selecting a product hydrates payload JSON plus scene, camera, product handling, and product physics fields from BOSMAX authority context."
				>
					<SelectField
						value={draft.product_id || ""}
						onChange={(value) => onChange({ product_id: value })}
						options={productOptions}
						placeholder="Select a product to hydrate"
					/>
				</FieldShell>

				<FieldShell label="Gender">
					<TextField
						value={draft.gender || ""}
						onChange={(value) => onChange({ gender: value })}
					/>
				</FieldShell>

				<FieldShell label="Ethnicity">
					<TextField
						value={draft.ethnicity || ""}
						onChange={(value) => onChange({ ethnicity: value })}
					/>
				</FieldShell>

				<FieldShell label="Age Range">
					<TextField
						value={draft.age_range || ""}
						onChange={(value) => onChange({ age_range: value })}
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

				<FieldShell
					label="Wardrobe"
					helper={`No repo-backed wardrobe registry exists in this checkout. Manual fallback remains required. ${hydration.wardrobeFallback.reason}`}
				>
					<TextField
						value={draft.wardrobe || ""}
						onChange={(value) => onChange({ wardrobe: value })}
					/>
				</FieldShell>

				<FieldShell
					label="Headwear"
					helper="Operator-pack headwear suggestions are not canonical registry truth. Headwear suggestions remain OPERATOR_PACK and non-canonical in the authority adapter."
				>
					<SelectField
						value={draft.headwear || ""}
						onChange={(value) => onChange({ headwear: value })}
						options={headwearOptions}
						placeholder="Select operator-pack headwear"
					/>
				</FieldShell>
			</div>

			{selectedProduct ? (
				<div className="mt-4 grid gap-4 lg:grid-cols-2">
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Authority Product Context
						</div>
						<div className="mt-3 grid gap-2 md:grid-cols-2">
							<div>Scene: {selectedProduct.scene_context || "NOT_PROVIDED"}</div>
							<div>Camera style: {selectedProduct.camera_style || "NOT_PROVIDED"}</div>
							<div>Camera behavior: {selectedProduct.camera_behavior || "NOT_PROVIDED"}</div>
							<div>Formula: {selectedProduct.formula || "NOT_PROVIDED"}</div>
							<div>Product handling: {selectedAuthorityContext?.visual.product_handling || "NOT_FOUND"}</div>
							<div>Product physics: {selectedAuthorityContext?.visual.product_physics || "NOT_FOUND"}</div>
							<div>Overlay hint: {selectedAuthorityContext?.visual.overlay_hint || "NOT_FOUND"}</div>
							<div>Style references: {hydration.styleReferenceOptions.slice(0, 3).map((item) => item.label).join(", ") || "NOT_FOUND"}</div>
						</div>
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Authority Copy Signals
						</div>
						<div className="mt-2 text-[10px] text-slate-500">
							Hook, USP, CTA, and authority source warnings now come from the BOSMAX authority adapter. Manual fallback still remains available.
						</div>
						<div className="mt-3 grid gap-2">
							<div>Hook: {selectedCopySignals.hook || "NOT_FOUND"}</div>
							<div>USP 1: {selectedCopySignals.usp_1 || "NOT_FOUND"}</div>
							<div>USP 2: {selectedCopySignals.usp_2 || "NOT_FOUND"}</div>
							<div>USP 3: {selectedCopySignals.usp_3 || "NOT_FOUND"}</div>
							<div>CTA: {selectedCopySignals.cta || "NOT_FOUND"}</div>
						</div>
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300 lg:col-span-2">
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Source Warnings
						</div>
						<div className="mt-2 grid gap-2 md:grid-cols-2">
							{selectedContextWarnings.length > 0 ? (
								selectedContextWarnings.map((warning) => (
									<div key={warning}>{warning}</div>
								))
							) : (
								<div>No selected-product source warnings.</div>
							)}
							{hydration.missingSources.slice(0, 4).map((item) => (
								<div key={item.label}>{item.label}: {item.source_status}</div>
							))}
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
