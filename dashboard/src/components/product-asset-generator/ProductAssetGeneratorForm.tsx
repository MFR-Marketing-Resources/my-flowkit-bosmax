import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchCreativeAssets } from "../../api/creativeAssets";
import type {
	BosmaxFieldProvenance,
	CreativeAsset,
	Product,
	ProductAssetGeneratorRequest,
	ProductAssetGeneratorResponse,
} from "../../types";
import { usePromptToolHydration } from "../prompt-tool/usePromptToolHydration";
import { PRODUCT_ASSET_GENERATOR_PRESETS } from "./presets";

type ProductAssetGeneratorDraft = ProductAssetGeneratorRequest & {
	product_payload_text: string;
};

type ProductReadinessStatus =
	| "RAW"
	| "ANALYZING"
	| "READY"
	| "NEEDS_REVIEW"
	| "FAILED"
	| "STALE";

type ProfileSourceStatus =
	| "NOT_ANALYZED"
	| "EPHEMERAL_PREVIEW"
	| "PRODUCT_ROW_DERIVED"
	| "PERSISTED_PROFILE";
type RecommendedMode = "TEXT_TO_VIDEO" | "FRAMES" | "INGREDIENTS" | "IMAGE";
type CopyReadinessStatus =
	| "COMMERCIAL_COPY_READY"
	| "FALLBACK_COPY_DRAFT"
	| "REVIEW_REQUIRED"
	| "COPY_MISSING"
type CharacterReadinessStatus =
	| "CHARACTER_CONCEPT_ONLY"
	| "CHARACTER_ASSET_READY"
	| "NOT_PROVIDED";
type AssetReadinessStatus =
	| "PROMPT_ONLY"
	| "NEEDS_ASSET"
	| "NEEDS_ASSET_BUNDLE";
type ExecutionReadinessStatus = "DRY_RUN_ONLY" | "NOT_GOOGLE_FLOW_READY";
type PersistenceTruthStatus = "NOT_PERSISTED" | "PERSISTED";

type ProfileCardRecord = {
	label: "UGC_IPHONE" | "CINEMATIC_PRO";
	character_strategy: string;
	wardrobe_strategy: string;
	headwear_strategy: string;
	group: string;
	sub_group: string;
	type_of_product: string;
	bosmax_product_family: string;
	package_form: string;
	physical_state: string;
	intelligence_confidence: string;
	scene_context: string;
	camera_style: string;
	camera_behavior: string;
	story_style_label: string;
	story_style: string;
	copy_quality_status: string;
	copy_route: string;
	copy_review_status: string;
	claim_gate: string;
	claim_tokens: string;
	hook: string;
	usp_1: string;
	usp_2: string;
	usp_3: string;
	cta: string;
	overlay_copy: string;
	dialogue_opening: string;
	dialogue_body: string;
	dialogue_cta: string;
	product_scale_prompt: string;
	scale_truth_status: string;
	scale_warning: string;
	camera_capture_mode: string;
	ugc_camera_lock_prompt: string;
	cinematic_camera_prompt: string;
	product_handling: string;
	product_physics: string;
	truth_warnings: string[];
	preview_warnings: string[];
	provenance: BosmaxFieldProvenance[];
};

type ModeReadinessRecord = {
	key: RecommendedMode;
	status: string;
	detail: string;
};

type ProfileTruthSummary = {
	profile_source_status: ProfileSourceStatus;
	product_mapping_status: "READY" | "NEEDS_REVIEW" | "MISSING";
	copy_quality_status: CopyReadinessStatus;
	copy_quality_detail: string;
	character_readiness_status: CharacterReadinessStatus;
	asset_readiness_status: AssetReadinessStatus;
	execution_readiness_status: ExecutionReadinessStatus;
	persistence_truth: PersistenceTruthStatus;
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
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div className="mt-2">{children}</div>
			{helper ? (
				<div className="mt-2 text-[10px] text-slate-500">{helper}</div>
			) : null}
		</div>
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
	return options.map((option) => ({
		value: option.value,
		label: option.label,
	}));
}

function outputTypeForMode(mode: RecommendedMode): string {
	if (mode === "IMAGE") {
		return "IMAGE_PROMPT";
	}
	if (mode === "TEXT_TO_VIDEO") {
		return "VIDEO_9_SECTION_PROMPT";
	}
	return "PROMPT_BLOCK_PLAN";
}

function hasReadableSignal(value: string | null | undefined): boolean {
	if (!value) {
		return false;
	}
	const normalized = value.trim();
	return Boolean(normalized) && normalized !== "NOT_FOUND";
}

function hasBadCopyPhrase(value: string | null | undefined): boolean {
	const normalized = value?.trim().toLowerCase() || "";
	if (!normalized) {
		return false;
	}
	return [
		"review the prompt package",
		"before any execution",
		"keep the demo grounded",
		"show the product clearly before",
		"not generated asset",
		"preview-only",
		"prompt package",
		"execution",
	].some((phrase) => normalized.includes(phrase));
}

function statusTone(
	status: ProductReadinessStatus | ProfileSourceStatus | string,
): string {
	if (status === "READY" || status === "PERSISTED_PROFILE") {
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
	}
	if (status === "ANALYZING") {
		return "border-blue-500/30 bg-blue-500/10 text-blue-200";
	}
	if (status === "FAILED") {
		return "border-red-500/30 bg-red-500/10 text-red-200";
	}
	if (status === "STALE") {
		return "border-orange-500/30 bg-orange-500/10 text-orange-200";
	}
	return "border-amber-500/30 bg-amber-500/10 text-amber-200";
}

function StatusBadge({
	label,
	value,
}: {
	label: string;
	value: ProductReadinessStatus | ProfileSourceStatus | string;
}) {
	return (
		<div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div
				className={`mt-2 inline-flex rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${statusTone(value)}`}
			>
				{value}
			</div>
		</div>
	);
}

function ProfileField({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div className="bosmax-pre-wrap-safe mt-2 text-[11px] text-slate-200">
				{value}
			</div>
		</div>
	);
}

function WarningList({
	title,
	items,
	emptyLabel,
	tone,
}: {
	title: string;
	items: string[];
	emptyLabel: string;
	tone: "truth" | "preview";
}) {
	const toneClasses =
		tone === "truth"
			? "border-red-500/20 bg-red-500/10 text-red-100"
			: "border-amber-500/20 bg-amber-500/10 text-amber-100";
	const titleTone = tone === "truth" ? "text-red-200" : "text-amber-200";

	return (
		<div className={`min-w-0 rounded-xl border p-3 ${toneClasses}`}>
			<div
				className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${titleTone}`}
			>
				{title}
			</div>
			<div className="bosmax-warning-list mt-2">
				{items.length > 0 ? (
					items.map((item) => (
						<div
							key={`${title}:${item}`}
							className="bosmax-warning-chip rounded-lg border border-current/20 bg-black/10 px-3 py-2 text-[11px]"
							title={item}
						>
							{item}
						</div>
					))
				) : (
					<div className="bosmax-warning-chip rounded-lg border border-current/20 bg-black/10 px-3 py-2 text-[11px]">
						{emptyLabel}
					</div>
				)}
			</div>
		</div>
	);
}

function ProvenanceList({
	items,
}: {
	items: BosmaxFieldProvenance[];
}) {
	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-900/60 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				Provenance
			</div>
			<div className="bosmax-provenance-list mt-2">
				{items.length > 0 ? (
					items.map((item) => (
						<div
							key={`${item.field}:${item.source_status}:${item.source_file || "none"}`}
							className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2"
						>
							<div className="bosmax-kv-list">
								<div className="bosmax-kv-row">
									<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
										field
									</div>
									<div className="bosmax-kv-value text-[11px] text-slate-200">
										{item.field}
									</div>
								</div>
								<div className="bosmax-kv-row">
									<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
										source_status
									</div>
									<div className="bosmax-kv-value text-[11px] text-slate-300">
										{item.source_status}
									</div>
								</div>
								{item.source_origin ? (
									<div className="bosmax-kv-row">
										<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
											source_origin
										</div>
										<div className="bosmax-kv-value text-[11px] text-slate-300">
											{item.source_origin}
										</div>
									</div>
								) : null}
								{item.source_file ? (
									<div className="bosmax-kv-row">
										<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
											source_file
										</div>
										<div className="bosmax-kv-value text-[11px] text-slate-300">
											{item.source_file}
										</div>
									</div>
								) : null}
								{item.source_endpoint ? (
									<div className="bosmax-kv-row">
										<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
											source_endpoint
										</div>
										<div className="bosmax-kv-value text-[11px] text-slate-300">
											{item.source_endpoint}
										</div>
									</div>
								) : null}
								{item.warnings.length > 0 ? (
									<div className="bosmax-warning-list">
										{item.warnings.map((warning) => (
											<div
												key={`${item.field}:${warning}`}
												className="bosmax-warning-chip rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-[11px] text-slate-300"
												title={warning}
											>
												{warning}
											</div>
										))}
									</div>
								) : null}
							</div>
						</div>
					))
				) : (
					<div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-[11px] text-slate-300">
						No BOSMAX field provenance loaded yet.
					</div>
				)}
			</div>
		</div>
	);
}

export function buildProductAssetGeneratorRequest(
	draft: ProductAssetGeneratorDraft,
): ProductAssetGeneratorRequest {
	const inlinePayload = parseJsonObject(draft.product_payload_text);
	const manualOverridePayload = draft.product_id
		? undefined
		: inlinePayload || draft.product_payload || undefined;
	return {
		product_id: draft.product_id || undefined,
		product_payload: manualOverridePayload,
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

function buildReadinessStatus({
	loading,
	error,
	result,
	selectedProduct,
	currentSignature,
	analysisSignature,
}: {
	loading: boolean;
	error: string | null;
	result: ProductAssetGeneratorResponse | null;
	selectedProduct: Product | null;
	currentSignature: string | null;
	analysisSignature: string | null;
}): ProductReadinessStatus {
	if (loading) {
		return "ANALYZING";
	}
	if (error || result?.preview_status === "FAIL") {
		return "FAILED";
	}
	if (result && analysisSignature && currentSignature !== analysisSignature) {
		return "STALE";
	}
	if (!result) {
		return "RAW";
	}
	const truthWarnings = result.truth_warnings || [];
	const truthStatus = result.truth_status || {};
	if (
		selectedProduct?.prompt_readiness_status === "NEEDS_REVIEW" ||
		selectedProduct?.prompt_readiness_status === "MISSING_FIELDS" ||
		truthWarnings.length > 0 ||
		truthStatus.product_mapping_status === "NEEDS_REVIEW" ||
		truthStatus.text_to_video_readiness_status === "NEEDS_REVIEW" ||
		truthStatus.text_to_video_readiness_status === "COPY_MISSING" ||
		truthStatus.copy_quality_status === "FALLBACK_COPY_DRAFT" ||
		truthStatus.copy_quality_status === "REVIEW_REQUIRED" ||
		truthStatus.copy_quality_status === "COPY_MISSING"
	) {
		return "NEEDS_REVIEW";
	}
	return "READY";
}

function buildProfileSourceStatus({
	productId,
	productPayload,
	result,
	truthStatus,
}: {
	productId: string;
	productPayload: Record<string, unknown> | null;
	result: ProductAssetGeneratorResponse | null;
	truthStatus: Record<string, unknown> | null;
}): ProfileSourceStatus {
	if (!result && !productId && !productPayload) {
		return "NOT_ANALYZED";
	}
	if (
		truthStatus?.profile_source_status === "PERSISTED_PROFILE" ||
		truthStatus?.persistence_truth === "PERSISTED"
	) {
		return "PERSISTED_PROFILE";
	}
	if (result) {
		return "EPHEMERAL_PREVIEW";
	}
	if (productId || productPayload) {
		return "PRODUCT_ROW_DERIVED";
	}
	return "NOT_ANALYZED";
}

function buildProfileTruthWarnings({
	selectedProduct,
	result,
}: {
	selectedProduct: Product | null;
	result: ProductAssetGeneratorResponse | null;
}): string[] {
	const combined = new Set<string>();
	for (const warning of result?.truth_warnings || []) {
		combined.add(warning);
	}
	if (selectedProduct?.prompt_missing_fields?.length) {
		for (const item of selectedProduct.prompt_missing_fields) {
			combined.add(`PROMPT_MISSING:${item}`);
		}
	}
	return Array.from(combined);
}

function buildProfilePreviewWarnings({
	selectedContextWarnings,
	result,
}: {
	selectedContextWarnings: string[];
	result: ProductAssetGeneratorResponse | null;
}): string[] {
	const combined = new Set<string>();
	for (const warning of selectedContextWarnings) {
		combined.add(warning);
	}
	for (const warning of result?.preview_warnings || []) {
		combined.add(warning);
	}
	return Array.from(combined);
}

function buildCopyReadinessStatus(
	selectedCopySignals: Record<string, string | null | undefined>,
	result: ProductAssetGeneratorResponse | null,
): {
	status: CopyReadinessStatus;
	detail: string;
} {
	const backendStatus = result?.truth_status?.copy_readiness_status as
		| CopyReadinessStatus
		| undefined;
	const backendQualityStatus = result?.truth_status?.copy_quality_status as
		| CopyReadinessStatus
		| undefined;
	const resolvedBackendStatus = backendQualityStatus || backendStatus;
	if (resolvedBackendStatus === "COMMERCIAL_COPY_READY") {
		return {
			status: "COMMERCIAL_COPY_READY",
			detail: "Consumer-facing hook, USP, and CTA are ready for production planning.",
		};
	}
	if (resolvedBackendStatus === "FALLBACK_COPY_DRAFT") {
		return {
			status: "FALLBACK_COPY_DRAFT",
			detail:
				"This copy is a fallback draft and must be improved before production video output.",
		};
	}
	if (resolvedBackendStatus === "REVIEW_REQUIRED") {
		return {
			status: "REVIEW_REQUIRED",
			detail:
				"Copy exists but remains review-gated because the route is stealth or otherwise sensitive.",
		};
	}
	const signals = [
		[
			"hook",
			(result?.product_context.hook as string | undefined) ||
				selectedCopySignals.hook,
		],
		[
			"usp_1",
			(result?.product_context.usp_1 as string | undefined) ||
				selectedCopySignals.usp_1,
		],
		[
			"usp_2",
			(result?.product_context.usp_2 as string | undefined) ||
				selectedCopySignals.usp_2,
		],
		[
			"usp_3",
			(result?.product_context.usp_3 as string | undefined) ||
				selectedCopySignals.usp_3,
		],
		[
			"cta",
			(result?.product_context.cta as string | undefined) ||
				selectedCopySignals.cta,
		],
	] as const;
	const missing = signals
		.filter(([, value]) => !hasReadableSignal(value))
		.map(([label]) => label);
	if (missing.length === 0) {
		const hasFallbackPhrase = signals.some(([, value]) =>
			hasBadCopyPhrase(value),
		);
		if (hasFallbackPhrase) {
			return {
				status: "FALLBACK_COPY_DRAFT",
				detail:
					"This copy is a fallback draft and must be improved before production video output.",
			};
		}
		return {
			status: "COMMERCIAL_COPY_READY",
			detail: "Consumer-facing hook, USP, and CTA are ready for production planning.",
		};
	}
	return {
		status: "COPY_MISSING",
		detail: "COPY_MISSING — hook/USP/CTA must be generated before TEXT_TO_VIDEO can be READY.",
	};
}

function buildCharacterReadinessStatus({
	result,
	draft,
}: {
	result: ProductAssetGeneratorResponse | null;
	draft: ProductAssetGeneratorDraft;
}): CharacterReadinessStatus {
	if (
		result?.truth_status?.character_readiness_status === "CHARACTER_ASSET_READY"
	) {
		return "CHARACTER_ASSET_READY";
	}
	if (
		result ||
		draft.gender ||
		draft.ethnicity ||
		draft.age_range ||
		draft.wardrobe ||
		draft.headwear
	) {
		return "CHARACTER_CONCEPT_ONLY";
	}
	return "NOT_PROVIDED";
}

function buildProfileCard({
	variant,
	selectedProduct,
	selectedCopySignals,
	selectedAuthorityContextWarnings,
	selectedFieldProvenance,
	draft,
	result,
	hydrationWardrobeReason,
}: {
	variant: "UGC_IPHONE" | "CINEMATIC_PRO";
	selectedProduct: Product | null;
	selectedCopySignals: Record<string, string | null | undefined>;
	selectedAuthorityContextWarnings: string[];
	selectedFieldProvenance: BosmaxFieldProvenance[];
	draft: ProductAssetGeneratorDraft;
	result: ProductAssetGeneratorResponse | null;
	hydrationWardrobeReason: string;
}): ProfileCardRecord {
	const productName =
		selectedProduct?.product_display_name ||
		selectedProduct?.raw_product_title ||
		"Selected product";
	const sceneContext =
		draft.scene_context || selectedProduct?.scene_context || "NOT_PROVIDED";
	const cameraStyle =
		draft.camera_style || selectedProduct?.camera_style || "NOT_PROVIDED";
	const cameraBehavior =
		draft.camera_behavior || selectedProduct?.camera_behavior || "NOT_PROVIDED";
	const productHandling = result
		? (result?.product_context.product_handling as string | undefined) ||
			result?.handling_notes[0] ||
			"NOT_PROVIDED"
		: selectedProduct?.handling_notes || "NOT_PROVIDED";
	const productPhysics = result
		? (result?.product_context.product_physics as string | undefined) ||
			result?.physics_notes[0] ||
			"NOT_PROVIDED"
		: selectedProduct?.section_5_product_physics_prompt || "NOT_PROVIDED";
	const wardrobeStrategy = draft.wardrobe
		? `Manual override: ${draft.wardrobe}`
		: `Manual fallback remains required. ${hydrationWardrobeReason}`;
	const headwearStrategy = draft.headwear
		? `Operator-pack selection: ${draft.headwear}`
		: "Operator-pack/non-canonical fallback. Headwear remains optional.";
	const provenance = selectedFieldProvenance.slice(0, 6);
	const truthWarnings = buildProfileTruthWarnings({
		selectedProduct,
		result,
	});
	const previewWarnings = buildProfilePreviewWarnings({
		selectedContextWarnings: selectedAuthorityContextWarnings,
		result,
	});
	const copyQualityStatus =
		(result?.truth_status?.copy_quality_status as string | undefined) ||
		(result?.product_context.copy_quality_status as string | undefined) ||
		"COPY_MISSING";
	const copyRoute =
		(result?.product_context.copy_route as string | undefined) || "NOT_FOUND";
	const copyReviewStatus =
		(result?.product_context.copy_review_status as string | undefined) ||
		"NOT_FOUND";
	const hook =
		(result?.product_context.hook as string | undefined) ||
		selectedCopySignals.hook ||
		"NOT_FOUND";
	const usp1 =
		(result?.product_context.usp_1 as string | undefined) ||
		selectedCopySignals.usp_1 ||
		"NOT_FOUND";
	const usp2 =
		(result?.product_context.usp_2 as string | undefined) ||
		selectedCopySignals.usp_2 ||
		"NOT_FOUND";
	const usp3 =
		(result?.product_context.usp_3 as string | undefined) ||
		selectedCopySignals.usp_3 ||
		"NOT_FOUND";
	const cta =
		(result?.product_context.cta as string | undefined) ||
		selectedCopySignals.cta ||
		"NOT_FOUND";
	const overlayCopy =
		(result?.product_context.overlay_copy as string | undefined) || "NOT_FOUND";
	const dialogueOpening =
		(result?.product_context.dialogue_opening as string | undefined) ||
		"NOT_FOUND";
	const dialogueBody =
		(result?.product_context.dialogue_body as string | undefined) ||
		"NOT_FOUND";
	const dialogueCta =
		(result?.product_context.dialogue_cta as string | undefined) || "NOT_FOUND";
	const productScalePrompt =
		(result?.product_context.product_scale_prompt as string | undefined) ||
		"NOT_FOUND";
	const scaleTruthStatus =
		(result?.truth_status?.scale_truth_status as string | undefined) ||
		(result?.product_context.scale_truth_status as string | undefined) ||
		"SCALE_NOT_FOUND";
	const scaleWarning =
		(result?.product_context.scale_warning as string | undefined) || "NONE";
	const ugcCameraLockPrompt =
		(result?.product_context.ugc_camera_lock_prompt as string | undefined) ||
		"NOT_FOUND";
	const cinematicCameraPrompt =
		(result?.product_context.cinematic_camera_prompt as string | undefined) ||
		"NOT_FOUND";
	const cameraCaptureMode =
		variant === "UGC_IPHONE"
			? ((result?.product_context.camera_capture_mode as string | undefined) ||
				"UGC_IPHONE_RAW")
			: "CINEMATIC_PRO_CONTROLLED";

	if (variant === "UGC_IPHONE") {
		return {
			label: variant,
			character_strategy: `Relatable handheld presenter strategy for ${productName}. Keep the operator voice native, casual, and product-led.`,
			wardrobe_strategy: wardrobeStrategy,
			headwear_strategy: headwearStrategy,
			group:
				(result?.truth_status?.group as string | undefined) ||
				(result?.product_context.group as string | undefined) ||
				"UNKNOWN_REVIEW_REQUIRED",
			sub_group:
				(result?.truth_status?.sub_group as string | undefined) ||
				(result?.product_context.sub_group as string | undefined) ||
				"UNKNOWN_REVIEW_REQUIRED",
			type_of_product:
				(result?.truth_status?.type_of_product as string | undefined) ||
				(result?.product_context.type_of_product as string | undefined) ||
				"UNKNOWN_REVIEW_REQUIRED",
			bosmax_product_family:
				(result?.truth_status?.bosmax_product_family as string | undefined) ||
				(result?.product_context.bosmax_product_family as string | undefined) ||
				"NOT_CLASSIFIED",
			package_form:
				(result?.truth_status?.package_form as string | undefined) ||
				(result?.product_context.package_form as string | undefined) ||
				"unknown",
			physical_state:
				(result?.truth_status?.physical_state as string | undefined) ||
				(result?.product_context.physical_state as string | undefined) ||
				"unknown",
			intelligence_confidence:
				(result?.truth_status?.intelligence_confidence as string | undefined) ||
				(result?.product_context.intelligence_confidence as string | undefined) ||
				"LOW",
			scene_context: sceneContext,
			camera_style: cameraStyle,
			camera_behavior: cameraBehavior,
			story_style_label: "dialogue_style",
			story_style:
				"Short-form spoken hook, direct product demo language, and conversational CTA cadence.",
			copy_quality_status: copyQualityStatus,
			copy_route: copyRoute,
			copy_review_status: copyReviewStatus,
			claim_gate:
				(result?.truth_status?.claim_gate as string | undefined) ||
				(result?.product_context.claim_gate as string | undefined) ||
				"CLAIM_REVIEW_REQUIRED",
			claim_tokens: Array.isArray(result?.product_context.claim_tokens)
				? (result?.product_context.claim_tokens as string[]).join(", ")
				: "NOT_FOUND",
			hook,
			usp_1: usp1,
			usp_2: usp2,
			usp_3: usp3,
			cta,
			overlay_copy: overlayCopy,
			dialogue_opening: dialogueOpening,
			dialogue_body: dialogueBody,
			dialogue_cta: dialogueCta,
			product_scale_prompt: productScalePrompt,
			scale_truth_status: scaleTruthStatus,
			scale_warning: scaleWarning,
			camera_capture_mode: cameraCaptureMode,
			ugc_camera_lock_prompt: ugcCameraLockPrompt,
			cinematic_camera_prompt: cinematicCameraPrompt,
			product_handling: productHandling,
			product_physics: productPhysics,
			truth_warnings: truthWarnings,
			preview_warnings: previewWarnings,
			provenance,
		};
	}

	return {
		label: variant,
		character_strategy: `Polished cinematic presenter strategy for ${productName}. Keep the performer composed and hero-framed rather than casual-first.`,
		wardrobe_strategy: wardrobeStrategy,
		headwear_strategy: headwearStrategy,
		group:
			(result?.truth_status?.group as string | undefined) ||
			(result?.product_context.group as string | undefined) ||
			"UNKNOWN_REVIEW_REQUIRED",
		sub_group:
			(result?.truth_status?.sub_group as string | undefined) ||
			(result?.product_context.sub_group as string | undefined) ||
			"UNKNOWN_REVIEW_REQUIRED",
		type_of_product:
			(result?.truth_status?.type_of_product as string | undefined) ||
			(result?.product_context.type_of_product as string | undefined) ||
			"UNKNOWN_REVIEW_REQUIRED",
		bosmax_product_family:
			(result?.truth_status?.bosmax_product_family as string | undefined) ||
			(result?.product_context.bosmax_product_family as string | undefined) ||
			"NOT_CLASSIFIED",
		package_form:
			(result?.truth_status?.package_form as string | undefined) ||
			(result?.product_context.package_form as string | undefined) ||
			"unknown",
		physical_state:
			(result?.truth_status?.physical_state as string | undefined) ||
			(result?.product_context.physical_state as string | undefined) ||
			"unknown",
		intelligence_confidence:
			(result?.truth_status?.intelligence_confidence as string | undefined) ||
			(result?.product_context.intelligence_confidence as string | undefined) ||
			"LOW",
		scene_context: sceneContext,
		camera_style: cameraStyle,
		camera_behavior: cameraBehavior,
		story_style_label: "voiceover_style",
		story_style:
			"Measured premium voiceover rhythm with compositional pauses that support visual hero framing.",
		copy_quality_status: copyQualityStatus,
		copy_route: copyRoute,
		copy_review_status: copyReviewStatus,
		claim_gate:
			(result?.truth_status?.claim_gate as string | undefined) ||
			(result?.product_context.claim_gate as string | undefined) ||
			"CLAIM_REVIEW_REQUIRED",
		claim_tokens: Array.isArray(result?.product_context.claim_tokens)
			? (result?.product_context.claim_tokens as string[]).join(", ")
			: "NOT_FOUND",
		hook,
		usp_1: usp1,
		usp_2: usp2,
		usp_3: usp3,
		cta,
		overlay_copy: overlayCopy,
		dialogue_opening: dialogueOpening,
		dialogue_body: dialogueBody,
		dialogue_cta: dialogueCta,
		product_scale_prompt: productScalePrompt,
		scale_truth_status: scaleTruthStatus,
		scale_warning: scaleWarning,
		camera_capture_mode: cameraCaptureMode,
		ugc_camera_lock_prompt: ugcCameraLockPrompt,
		cinematic_camera_prompt: cinematicCameraPrompt,
		product_handling: productHandling,
		product_physics: productPhysics,
		truth_warnings: truthWarnings,
		preview_warnings: previewWarnings,
		provenance,
	};
}

function buildModeReadiness({
	selectedProduct,
	draft,
	inlinePayload,
	copyReadiness,
	result,
}: {
	selectedProduct: Product | null;
	draft: ProductAssetGeneratorDraft;
	inlinePayload: Record<string, unknown> | null;
	copyReadiness: CopyReadinessStatus;
	result: ProductAssetGeneratorResponse | null;
}): {
	records: ModeReadinessRecord[];
	recommended_first_mode: RecommendedMode;
} {
	const sceneReady = Boolean(
		draft.scene_context || selectedProduct?.scene_context,
	);
	const cameraReady = Boolean(
		(draft.camera_style || selectedProduct?.camera_style) &&
			(draft.camera_behavior || selectedProduct?.camera_behavior),
	);
	const hasProduct = Boolean(
		selectedProduct || inlinePayload || draft.product_payload,
	);
	const hasImage = Boolean(
		selectedProduct?.image_url ||
			selectedProduct?.local_image_path ||
			selectedProduct?.media_id,
	);
	const hasStyle = Boolean(draft.camera_style || selectedProduct?.camera_style);
	const textStatus =
		(result?.truth_status?.text_to_video_readiness_status as string | undefined) ||
		(hasProduct &&
		sceneReady &&
		cameraReady &&
		copyReadiness === "COMMERCIAL_COPY_READY"
			? "READY"
			: "NEEDS_REVIEW");
	const imageStatus =
		(result?.truth_status?.image_prompt_readiness_status as string | undefined) ||
		(hasProduct && sceneReady && hasStyle ? "READY_FOR_PROMPT" : "NEEDS_REVIEW");
	const framesStatus = hasImage ? "NEEDS_ASSET" : "NEEDS_ASSET";
	const ingredientsStatus =
		hasProduct && sceneReady && hasStyle
			? "NEEDS_ASSET_BUNDLE"
			: "NEEDS_ASSET_BUNDLE";
	const recommended_first_mode: RecommendedMode =
		textStatus === "READY"
			? "TEXT_TO_VIDEO"
			: imageStatus === "READY_FOR_PROMPT"
				? "IMAGE"
				: "FRAMES";

	return {
		records: [
			{
				key: "TEXT_TO_VIDEO",
				status: textStatus,
				detail:
					textStatus === "READY"
						? "READY only when product, scene, camera, product scale, camera lock, and copy signals are present."
						: "NEEDS_REVIEW while product scale, camera lock, or copy signals are missing or routed for review.",
			},
			{
				key: "FRAMES",
				status: framesStatus,
				detail:
					"Requires start/end image asset readiness. This cockpit does not create those assets.",
			},
			{
				key: "INGREDIENTS",
				status: ingredientsStatus,
				detail:
					"Requires a subject, scene, and style bundle. Missing bundle stays explicit.",
			},
			{
				key: "IMAGE",
				status: imageStatus,
				detail:
					"READY_FOR_PROMPT when product plus scene/style context exists. Prompt-ready only. No real image generation.",
			},
		],
		recommended_first_mode,
	};
}

function buildProfileTruthSummary({
	profileSourceStatus,
	selectedProduct,
	result,
	copyReadiness,
	characterReadinessStatus,
	assetReadinessStatus,
}: {
	profileSourceStatus: ProfileSourceStatus;
	selectedProduct: Product | null;
	result: ProductAssetGeneratorResponse | null;
	copyReadiness: {
		status: CopyReadinessStatus;
		detail: string;
	};
	characterReadinessStatus: CharacterReadinessStatus;
	assetReadinessStatus: AssetReadinessStatus;
}): ProfileTruthSummary {
	return {
		profile_source_status:
			(result?.truth_status?.profile_source_status as ProfileSourceStatus) ||
			profileSourceStatus,
		product_mapping_status:
			(result?.truth_status?.product_mapping_status as
				| "READY"
				| "NEEDS_REVIEW"
				| "MISSING") ||
			selectedProduct?.mapping_status ||
			(selectedProduct ? "NEEDS_REVIEW" : "MISSING"),
		copy_quality_status:
			(result?.truth_status?.copy_quality_status as CopyReadinessStatus) ||
			copyReadiness.status,
		copy_quality_detail:
			(result?.truth_status?.copy_quality_detail as string) ||
			copyReadiness.detail,
		character_readiness_status:
			(result?.truth_status
				?.character_readiness_status as CharacterReadinessStatus) ||
			characterReadinessStatus,
		asset_readiness_status:
			(result?.truth_status?.asset_readiness_status as AssetReadinessStatus) ||
			assetReadinessStatus,
		execution_readiness_status:
			(result?.truth_status
				?.execution_readiness_status as ExecutionReadinessStatus) ||
			"DRY_RUN_ONLY",
		persistence_truth:
			(result?.truth_status?.persistence_truth as PersistenceTruthStatus) ||
			"NOT_PERSISTED",
	};
}

function buildPromptPreviewHandoff({
	draft,
	selectedProduct,
	recommendedMode,
	inlinePayload,
	result,
}: {
	draft: ProductAssetGeneratorDraft;
	selectedProduct: Product | null;
	recommendedMode: RecommendedMode;
	inlinePayload: Record<string, unknown> | null;
	result: ProductAssetGeneratorResponse | null;
}) {
	const productPayload =
		inlinePayload ||
		draft.product_payload ||
		(selectedProduct
			? {
					id: selectedProduct.id,
					product_display_name: selectedProduct.product_display_name,
					raw_product_title: selectedProduct.raw_product_title,
					scene_context: draft.scene_context || selectedProduct.scene_context,
					camera_style: draft.camera_style || selectedProduct.camera_style,
					camera_behavior:
						draft.camera_behavior || selectedProduct.camera_behavior,
					product_scale_prompt:
						(result?.product_context.product_scale_prompt as string | undefined) ||
						undefined,
					ugc_camera_lock_prompt:
						(result?.product_context.ugc_camera_lock_prompt as string | undefined) ||
						undefined,
					cinematic_camera_prompt:
						(result?.product_context.cinematic_camera_prompt as string | undefined) ||
						undefined,
					group:
						(result?.truth_status?.group as string | undefined) ||
						(selectedProduct?.group as string | undefined) ||
						undefined,
					sub_group:
						(result?.truth_status?.sub_group as string | undefined) ||
						(selectedProduct?.sub_group as string | undefined) ||
						undefined,
					type_of_product:
						(result?.truth_status?.type_of_product as string | undefined) ||
						(selectedProduct?.type_of_product as string | undefined) ||
						undefined,
					bosmax_product_family:
						(result?.truth_status?.bosmax_product_family as string | undefined) ||
						(selectedProduct?.bosmax_product_family as string | undefined) ||
						undefined,
					package_form:
						(result?.truth_status?.package_form as string | undefined) ||
						(selectedProduct?.package_form as string | undefined) ||
						undefined,
					physical_state:
						(result?.truth_status?.physical_state as string | undefined) ||
						(selectedProduct?.physical_state as string | undefined) ||
						undefined,
					copy_route:
						(result?.product_context.copy_route as string | undefined) || undefined,
					claim_gate:
						(result?.truth_status?.claim_gate as string | undefined) ||
						(result?.product_context.claim_gate as string | undefined) ||
						undefined,
					claim_tokens:
						(Array.isArray(result?.truth_status?.claim_tokens)
							? result?.truth_status?.claim_tokens
							: Array.isArray(result?.product_context.claim_tokens)
								? result?.product_context.claim_tokens
								: undefined) || undefined,
					trigger_id: selectedProduct.trigger_id,
					silo: selectedProduct.silo,
					formula: selectedProduct.formula,
				}
			: undefined);

	return {
		productReadinessProfile: {
			source_route: "PRODUCT_DRIVEN_AUTO",
			destination_mode: recommendedMode,
			output_type: outputTypeForMode(recommendedMode),
			product_id: draft.product_id || "",
			product_payload: productPayload,
			product_payload_text: productPayload
				? buildProductPayloadText(productPayload)
				: "",
			scene_context:
				draft.scene_context || selectedProduct?.scene_context || "",
			camera_style: draft.camera_style || selectedProduct?.camera_style || "",
			camera_behavior:
				draft.camera_behavior || selectedProduct?.camera_behavior || "",
			trigger_id: selectedProduct?.trigger_id || "",
			silo: selectedProduct?.silo || "",
			formula: selectedProduct?.formula || "",
			language: draft.language || "Malay",
			platform: draft.platform || "TikTok",
			headwear_style: draft.headwear || "",
			wardrobe_id: draft.wardrobe || "",
			requested_scene:
				draft.scene_context || selectedProduct?.scene_context || "",
			include_temporal_plan: recommendedMode === "TEXT_TO_VIDEO",
			dry_run_only: true,
		},
	};
}

export default function ProductAssetGeneratorForm({
	draft,
	onChange,
	onSubmit,
	loading,
	error,
	result,
	analysisSignature,
	activePreset,
	selectedPresetId,
	onPresetChange,
	presetRequiresProductButMissing,
}: {
	draft: ProductAssetGeneratorDraft;
	onChange: (patch: Partial<ProductAssetGeneratorDraft>) => void;
	onSubmit: () => void;
	loading: boolean;
	error: string | null;
	result: ProductAssetGeneratorResponse | null;
	analysisSignature: string | null;
	activePreset: { id: string; label: string; description: string; requiresDatabaseProduct: boolean; requiresCharacterReference: boolean; requiresSceneContextReference: boolean; guidance: string } | null;
	selectedPresetId: string;
	onPresetChange: (presetId: string) => void;
	presetRequiresProductButMissing: boolean;
}) {
	const hydration = usePromptToolHydration();
	const navigate = useNavigate();
	const [advancedOpen, setAdvancedOpen] = useState(false);
	const [sceneContextOpen, setSceneContextOpen] = useState(false);

	// Creative Library assets for image reference pickers
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	useEffect(() => {
		fetchCreativeAssets({ semantic_role: "CHARACTER_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setCharacterAssets(r.items))
			.catch(() => {});
		fetchCreativeAssets({ semantic_role: "SCENE_CONTEXT_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setSceneAssets(r.items))
			.catch(() => {});
	}, []);
	const selectedCharacterAsset = characterAssets.find(
		(a) => a.asset_id === draft.character_reference_asset_id,
	) ?? null;
	const selectedSceneAsset = sceneAssets.find(
		(a) => a.asset_id === draft.scene_context_reference_asset_id,
	) ?? null;
	const lastHydratedProductId = useRef<string | null>(null);
	const previewRequest = useMemo(() => {
		try {
			return buildProductAssetGeneratorRequest(draft);
		} catch {
			return null;
		}
	}, [draft]);
	const inlinePayload = useMemo(() => {
		try {
			return parseJsonObject(draft.product_payload_text);
		} catch {
			return null;
		}
	}, [draft.product_payload_text]);
	const currentSignature = useMemo(() => {
		try {
			return JSON.stringify(buildProductAssetGeneratorRequest(draft));
		} catch {
			return null;
		}
	}, [draft]);
	const selectedProduct = draft.product_id
		? hydration.productById[draft.product_id]
		: null;
	const selectedAuthorityContext = hydration.getProductContext(
		draft.product_id,
	);
	const selectedCopySignals = hydration.getCopySignals(draft.product_id);
	const selectedContextWarnings = hydration.getFieldWarnings(
		selectedAuthorityContext,
	);
	const selectedFieldProvenance = hydration.getFieldProvenance(
		selectedAuthorityContext,
	);

	useEffect(() => {
		if (!draft.product_id) {
			lastHydratedProductId.current = null;
			return;
		}
		if (
			lastHydratedProductId.current === draft.product_id ||
			!selectedProduct
		) {
			return;
		}
		lastHydratedProductId.current = draft.product_id;
		onChange({
			product_payload: undefined,
			product_payload_text: "",
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
	const cameraBehaviorOptions = toSelectOptions(
		hydration.cameraBehaviorOptions,
	);
	const headwearOptions = toSelectOptions(hydration.headwearOptions);
	const readinessStatus = buildReadinessStatus({
		loading,
		error,
		result,
		selectedProduct,
		currentSignature,
		analysisSignature,
	});
	const profileSourceStatus = buildProfileSourceStatus({
		productId: draft.product_id || "",
		productPayload: inlinePayload || draft.product_payload || null,
		result,
		truthStatus:
			(result?.truth_status as Record<string, unknown> | null) || null,
	});
	const profileVisible = Boolean(
		selectedProduct || inlinePayload || draft.product_payload || result,
	);
	const copyReadiness = buildCopyReadinessStatus(selectedCopySignals, result);
	const { records: modeReadiness, recommended_first_mode } = buildModeReadiness(
		{
			selectedProduct,
			draft,
			inlinePayload,
			copyReadiness: copyReadiness.status,
			result,
		},
	);
	const assetReadinessStatus: AssetReadinessStatus =
		recommended_first_mode === "INGREDIENTS"
			? "NEEDS_ASSET_BUNDLE"
			: recommended_first_mode === "FRAMES"
				? "NEEDS_ASSET"
				: "PROMPT_ONLY";
	const characterReadinessStatus = buildCharacterReadinessStatus({
		result,
		draft,
	});
	const profileTruthSummary = buildProfileTruthSummary({
		profileSourceStatus,
		selectedProduct,
		result,
		copyReadiness,
		characterReadinessStatus,
		assetReadinessStatus,
	});
	const ugcProfile = buildProfileCard({
		variant: "UGC_IPHONE",
		selectedProduct,
		selectedCopySignals,
		selectedAuthorityContextWarnings: selectedContextWarnings,
		selectedFieldProvenance,
		draft,
		result,
		hydrationWardrobeReason: hydration.wardrobeFallback.reason,
	});
	const cinematicProfile = buildProfileCard({
		variant: "CINEMATIC_PRO",
		selectedProduct,
		selectedCopySignals,
		selectedAuthorityContextWarnings: selectedContextWarnings,
		selectedFieldProvenance,
		draft,
		result,
		hydrationWardrobeReason: hydration.wardrobeFallback.reason,
	});

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex items-start justify-between gap-3">
				<div>
					<div className="text-sm font-semibold text-slate-100">
						Product Readiness Profile
					</div>
					<div className="mt-1 text-[11px] text-slate-400">
						Product selection leads the workflow. Analyze Product builds a
						readiness profile first, then manual controls remain available in
						Advanced Manual Override. Analyze Product creates an offline
						preview-derived readiness profile. It is not persisted unless a
						persisted profile API is implemented.
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

			<div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
				<div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
					<div className="space-y-5">

						{/* ── STEP 1: IMAGE INPUTS ──────────────────────────── */}
						<div>
							<div className="mb-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-300">
								Step 1 — Image Inputs
							</div>

							{/* 1A: Avatar / Character Reference */}
							<div className="rounded-2xl border border-slate-700 bg-slate-950 p-3">
								<div className="flex items-center gap-2">
									<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-200">
										Avatar / Character
									</span>
									<span className="rounded-full border border-slate-600 bg-slate-900 px-2 py-0.5 text-[9px] text-slate-400">
										Required for avatar presets
									</span>
								</div>
								{selectedCharacterAsset ? (
									<div className="mt-2 flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
										{selectedCharacterAsset.preview_url ? (
											<img
												src={selectedCharacterAsset.preview_url}
												alt={selectedCharacterAsset.display_name}
												className="h-10 w-10 flex-shrink-0 rounded-lg border border-slate-700 object-cover"
											/>
										) : null}
										<div className="min-w-0 flex-1">
											<div className="truncate text-xs font-semibold text-slate-100">
												{selectedCharacterAsset.display_name}
											</div>
											<div className="text-[10px] text-slate-400">CHARACTER_REFERENCE</div>
										</div>
										<button
											type="button"
											onClick={() => onChange({ character_reference_asset_id: null })}
											className="text-[10px] text-slate-400 hover:text-red-300"
										>
											✕ Remove
										</button>
									</div>
								) : null}
								<select
									value={draft.character_reference_asset_id ?? ""}
									onChange={(e) =>
										onChange({ character_reference_asset_id: e.target.value || null })
									}
									className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
								>
									<option value="">— Pick avatar from Creative Library —</option>
									{characterAssets.map((a) => (
										<option key={a.asset_id} value={a.asset_id}>
											{a.display_name}
										</option>
									))}
								</select>
								{characterAssets.length === 0 ? (
									<div className="mt-1 text-[10px] text-slate-500">
										No avatar images yet. Upload first in Creative Library → CHARACTER_REFERENCE.
									</div>
								) : null}
							</div>

							{/* 1B: Product */}
							<div className="mt-3 rounded-2xl border border-slate-700 bg-slate-950 p-3">
								<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-200">
									Product
								</div>
								<FieldShell
									label="Database Product"
									helper="Selecting a product uses product_id authority — scale truth, product physics, and label-safe framing all come from the product row."
								>
									<SelectField
										value={draft.product_id || ""}
										onChange={(value) => onChange({ product_id: value })}
										options={productOptions}
										placeholder="Select a product"
									/>
								</FieldShell>
							</div>

							{/* 1C: Scene Context (Optional — character consistency) */}
							<div className="mt-3 rounded-2xl border border-slate-700 bg-slate-950 p-3">
								<button
									type="button"
									onClick={() => setSceneContextOpen((v) => !v)}
									className="flex w-full items-center justify-between text-left"
								>
									<div className="flex items-center gap-2">
										<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-200">
											Scene Context
										</span>
										<span className="rounded-full border border-slate-600 bg-slate-900 px-2 py-0.5 text-[9px] text-slate-400">
											Optional
										</span>
										{selectedSceneAsset ? (
											<span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[9px] font-semibold text-blue-200">
												{selectedSceneAsset.display_name}
											</span>
										) : null}
									</div>
									<span className="text-[10px] text-slate-500">
										{sceneContextOpen ? "▲ hide" : "▼ show"}
									</span>
								</button>
								{!sceneContextOpen ? (
									<div className="mt-1 text-[10px] text-slate-500">
										Use for character consistency — anchor the same character in a new outfit or environment.
									</div>
								) : null}
								{sceneContextOpen ? (
									<div className="mt-3 space-y-2">
										<div className="text-[10px] text-slate-400">
											Tujuan: Kekalkan konsistensi karakter (contoh: tukar outfit atau latar belakang
											untuk Vivvian, tapi muka dan badan kekal sama).
										</div>
										{selectedSceneAsset ? (
											<div className="flex items-center gap-3 rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-2">
												{selectedSceneAsset.preview_url ? (
													<img
														src={selectedSceneAsset.preview_url}
														alt={selectedSceneAsset.display_name}
														className="h-10 w-10 flex-shrink-0 rounded-lg border border-slate-700 object-cover"
													/>
												) : null}
												<div className="min-w-0 flex-1">
													<div className="truncate text-xs font-semibold text-slate-100">
														{selectedSceneAsset.display_name}
													</div>
													<div className="text-[10px] text-slate-400">SCENE_CONTEXT_REFERENCE</div>
												</div>
												<button
													type="button"
													onClick={() => onChange({ scene_context_reference_asset_id: null })}
													className="text-[10px] text-slate-400 hover:text-red-300"
												>
													✕ Remove
												</button>
											</div>
										) : null}
										<select
											value={draft.scene_context_reference_asset_id ?? ""}
											onChange={(e) =>
												onChange({
													scene_context_reference_asset_id: e.target.value || null,
												})
											}
											className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
										>
											<option value="">— Pick scene from Creative Library —</option>
											{sceneAssets.map((a) => (
												<option key={a.asset_id} value={a.asset_id}>
													{a.display_name}
												</option>
											))}
										</select>
										{sceneAssets.length === 0 ? (
											<div className="text-[10px] text-slate-500">
												No scene images yet. Upload in Creative Library → SCENE_CONTEXT_REFERENCE.
											</div>
										) : null}
									</div>
								) : null}
							</div>
						</div>

						{/* ── STEP 2: GENERATION PRESET ──────────────────────── */}
						<div>
							<div className="mb-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-300">
								Step 2 — Generation Preset
							</div>
							<select
								value={selectedPresetId}
								onChange={(e) => onPresetChange(e.target.value)}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="">(none / manual)</option>
								{PRODUCT_ASSET_GENERATOR_PRESETS.map((preset) => (
									<option key={preset.id} value={preset.id}>
										{preset.label} — {preset.description}
									</option>
								))}
							</select>

							{/* Active preset card */}
							{activePreset ? (
								<div className="mt-2 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
									<div className="flex flex-wrap gap-2">
										<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
											{activePreset.label}
										</span>
										{activePreset.requiresDatabaseProduct ? (
											<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-amber-100">
												Needs DB product
											</span>
										) : null}
										{activePreset.requiresCharacterReference ? (
											<span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-blue-200">
												Needs avatar image
											</span>
										) : null}
									</div>
									<div className="mt-2 text-[11px] text-slate-300">
										{activePreset.guidance}
									</div>
								</div>
							) : null}

							{/* Blocker warnings */}
							{presetRequiresProductButMissing ? (
								<div className="mt-2 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
									⚠ Preset ini memerlukan database product. Sila pilih produk di Step 1.
								</div>
							) : null}
							{activePreset?.requiresCharacterReference &&
							!draft.character_reference_asset_id ? (
								<div className="mt-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
									⚠ Preset ini memerlukan avatar image. Sila pilih karakter di Step 1.
								</div>
							) : null}
						</div>

						{/* ── STEP 3: SUBMIT ─────────────────────────────────── */}
						<div>
							<div className="mb-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-300">
								Step 3 — Analyze
							</div>
							<div className="flex flex-wrap gap-3">
								<button
									type="button"
									onClick={onSubmit}
									disabled={
										loading ||
										!previewRequest ||
										(!previewRequest.product_id &&
											!previewRequest.product_payload) ||
										presetRequiresProductButMissing ||
										Boolean(
											activePreset?.requiresCharacterReference &&
												!draft.character_reference_asset_id,
										)
									}
									className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-5 py-2.5 text-xs font-semibold text-blue-200 disabled:opacity-40"
								>
									{loading ? "Analyzing..." : "Analyze Product"}
								</button>
								<button
									type="button"
									onClick={() =>
										navigate("/prompt-preview", {
											state: buildPromptPreviewHandoff({
												draft,
												selectedProduct,
												recommendedMode: recommended_first_mode,
												inlinePayload,
												result,
											}),
										})
									}
									disabled={!profileVisible}
									className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-xs font-semibold text-emerald-200 disabled:opacity-40"
								>
									Use in Prompt Preview
								</button>
							</div>
						</div>
					</div>

					<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
						<StatusBadge label="Readiness Status" value={readinessStatus} />
						<StatusBadge
							label="Profile Source Status"
							value={profileSourceStatus}
						/>
					</div>
				</div>
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
							<div>Trigger: {selectedProduct.trigger_id || "NOT_PROVIDED"}</div>
							<div>Silo: {selectedProduct.silo || "NOT_PROVIDED"}</div>
							<div>Formula: {selectedProduct.formula || "NOT_PROVIDED"}</div>
							<div>Claim risk: {selectedAuthorityContext?.product.claim_risk_level || "NOT_PROVIDED"}</div>
							<div>Overlay hint: {selectedAuthorityContext?.visual.overlay_hint || "NOT_FOUND"}</div>
							<div>Product handling: {selectedAuthorityContext?.visual.product_handling || "NOT_FOUND"}</div>
							<div>Product physics: {selectedAuthorityContext?.visual.product_physics || "NOT_FOUND"}</div>
						</div>
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Authority Copy Signals
						</div>
						<div className="mt-2 text-[10px] text-slate-500">
							Hook, USP, CTA, product physics, and source warnings now come from the BOSMAX authority adapter. OPERATOR_PACK and NOT_FOUND signals remain explicit.
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
						</div>
					</div>
				</div>
			) : null}

			{profileVisible ? (
				<div className="mt-4 space-y-4">
					<div className="grid gap-4 xl:grid-cols-2">
						{[ugcProfile, cinematicProfile].map((profile) => (
							<section
								key={profile.label}
								className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4"
							>
								<div className="flex items-center justify-between gap-3">
									<div className="text-sm font-semibold text-slate-100">
										{profile.label}
									</div>
									<span className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300">
										Derived profile
									</span>
								</div>
								<div className="mt-4 grid gap-3 md:grid-cols-2">
									<ProfileField
										label="character_strategy"
										value={profile.character_strategy}
									/>
									<ProfileField
										label="wardrobe_strategy"
										value={profile.wardrobe_strategy}
									/>
									<ProfileField
										label="headwear_strategy"
										value={profile.headwear_strategy}
									/>
									<ProfileField label="Group" value={profile.group} />
									<ProfileField
										label="Sub Group"
										value={profile.sub_group}
									/>
									<ProfileField
										label="Type Of Product"
										value={profile.type_of_product}
									/>
									<ProfileField
										label="BOSMAX Product Family"
										value={profile.bosmax_product_family}
									/>
									<ProfileField
										label="Package Form"
										value={profile.package_form}
									/>
									<ProfileField
										label="Physical State"
										value={profile.physical_state}
									/>
									<ProfileField
										label="Intelligence Confidence"
										value={profile.intelligence_confidence}
									/>
									<ProfileField
										label="scene_context"
										value={profile.scene_context}
									/>
									<ProfileField
										label="camera_style"
										value={profile.camera_style}
									/>
									<ProfileField
										label="camera_behavior"
										value={profile.camera_behavior}
									/>
									<ProfileField
										label={profile.story_style_label}
										value={profile.story_style}
									/>
									<ProfileField
										label="Copy Quality Status"
										value={profile.copy_quality_status}
									/>
									<ProfileField
										label="Copy Route"
										value={profile.copy_route}
									/>
									<ProfileField
										label="Copy Review Status"
										value={profile.copy_review_status}
									/>
									<ProfileField
										label="Claim Gate"
										value={profile.claim_gate}
									/>
									<ProfileField
										label="Claim Tokens"
										value={profile.claim_tokens}
									/>
									<ProfileField label="hook" value={profile.hook} />
									<ProfileField label="USP 1" value={profile.usp_1} />
									<ProfileField label="USP 2" value={profile.usp_2} />
									<ProfileField label="USP 3" value={profile.usp_3} />
									<ProfileField label="CTA" value={profile.cta} />
									<ProfileField
										label="Overlay Copy"
										value={profile.overlay_copy}
									/>
									<ProfileField
										label="Dialogue Opening"
										value={profile.dialogue_opening}
									/>
									<ProfileField
										label="Dialogue Body"
										value={profile.dialogue_body}
									/>
									<ProfileField
										label="Dialogue CTA"
										value={profile.dialogue_cta}
									/>
									<ProfileField
										label="Product Scale Prompt"
										value={profile.product_scale_prompt}
									/>
									<ProfileField
										label="Scale Truth Status"
										value={profile.scale_truth_status}
									/>
									<ProfileField
										label="Camera Capture Mode"
										value={profile.camera_capture_mode}
									/>
									<ProfileField
										label="UGC iPhone Raw Camera Lock"
										value={profile.ugc_camera_lock_prompt}
									/>
									<ProfileField
										label="Cinematic Camera Prompt"
										value={profile.cinematic_camera_prompt}
									/>
									<ProfileField
										label="Scale Warning"
										value={profile.scale_warning}
									/>
									<ProfileField
										label="product_handling"
										value={profile.product_handling}
									/>
									<ProfileField
										label="product_physics"
										value={profile.product_physics}
									/>
								</div>
								{profile.copy_quality_status === "FALLBACK_COPY_DRAFT" ? (
									<div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-3 text-[11px] text-amber-100">
										This copy is a fallback draft and must be improved before production video output.
									</div>
								) : null}
								<div className="bosmax-auto-fit-grid mt-4">
									<WarningList
										title="Product Truth Warnings"
										items={profile.truth_warnings}
										emptyLabel="No product-truth blockers detected."
										tone="truth"
									/>
									<WarningList
										title="Preview Constraints"
										items={profile.preview_warnings}
										emptyLabel="No preview-only constraints loaded yet."
										tone="preview"
									/>
									<ProvenanceList items={profile.provenance} />
								</div>
							</section>
						))}
					</div>

					<section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<div>
								<div className="text-sm font-semibold text-slate-100">
									Profile Truth Summary
								</div>
								<div className="mt-1 text-[11px] text-slate-400">
									Analyze Product creates an offline preview-derived readiness
									profile. It is not persisted unless a persisted profile API is
									implemented.
								</div>
							</div>
							<div className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300">
								persistence_truth={profileTruthSummary.persistence_truth}
							</div>
						</div>
								<div className="bosmax-auto-fit-grid mt-4">
							<ProfileField
								label="profile_source_status"
								value={profileTruthSummary.profile_source_status}
							/>
							<ProfileField
								label="product_mapping_status"
								value={profileTruthSummary.product_mapping_status}
							/>
							<ProfileField
								label="mapping_review_status"
								value={
									(result?.truth_status?.mapping_review_status as string | undefined) ||
									"NOT_RECORDED"
								}
							/>
							<ProfileField
								label="product_type_id"
								value={
									(result?.truth_status?.product_type_id as string | undefined) ||
									(selectedProduct?.product_type_id as string | undefined) ||
									"MISSING"
								}
							/>
							<ProfileField
								label="group"
								value={
									(result?.truth_status?.group as string | undefined) ||
									(result?.product_context.group as string | undefined) ||
									"UNKNOWN_REVIEW_REQUIRED"
								}
							/>
							<ProfileField
								label="sub_group"
								value={
									(result?.truth_status?.sub_group as string | undefined) ||
									(result?.product_context.sub_group as string | undefined) ||
									"UNKNOWN_REVIEW_REQUIRED"
								}
							/>
							<ProfileField
								label="type_of_product"
								value={
									(result?.truth_status?.type_of_product as string | undefined) ||
									(result?.product_context.type_of_product as string | undefined) ||
									"UNKNOWN_REVIEW_REQUIRED"
								}
							/>
							<ProfileField
								label="bosmax_product_family"
								value={
									(result?.truth_status?.bosmax_product_family as string | undefined) ||
									(result?.product_context.bosmax_product_family as string | undefined) ||
									"NOT_CLASSIFIED"
								}
							/>
							<ProfileField
								label="package_form"
								value={
									(result?.truth_status?.package_form as string | undefined) ||
									(result?.product_context.package_form as string | undefined) ||
									"unknown"
								}
							/>
							<ProfileField
								label="physical_state"
								value={
									(result?.truth_status?.physical_state as string | undefined) ||
									(result?.product_context.physical_state as string | undefined) ||
									"unknown"
								}
							/>
							<ProfileField
								label="claim_gate"
								value={
									(result?.truth_status?.claim_gate as string | undefined) ||
									(result?.product_context.claim_gate as string | undefined) ||
									"CLAIM_REVIEW_REQUIRED"
								}
							/>
							<ProfileField
								label="claim_tokens"
								value={
									Array.isArray(result?.truth_status?.claim_tokens)
										? (result?.truth_status?.claim_tokens as string[]).join(", ")
										: Array.isArray(result?.product_context.claim_tokens)
											? (result?.product_context.claim_tokens as string[]).join(", ")
											: "NOT_FOUND"
								}
							/>
							<ProfileField
								label="intelligence_confidence"
								value={
									(result?.truth_status?.intelligence_confidence as string | undefined) ||
									(result?.product_context.intelligence_confidence as string | undefined) ||
									"LOW"
								}
							/>
							<ProfileField
								label="copy_quality_status"
								value={profileTruthSummary.copy_quality_status}
							/>
							<ProfileField
								label="character_readiness_status"
								value={profileTruthSummary.character_readiness_status}
							/>
							<ProfileField
								label="asset_readiness_status"
								value={profileTruthSummary.asset_readiness_status}
							/>
							<ProfileField
								label="execution_readiness_status"
								value={profileTruthSummary.execution_readiness_status}
							/>
							<ProfileField
								label="scale_truth_status"
								value={
									(result?.truth_status?.scale_truth_status as string | undefined) ||
									"SCALE_NOT_FOUND"
								}
							/>
							<ProfileField
								label="camera_truth_status"
								value={
									(result?.truth_status?.camera_truth_status as string | undefined) ||
									"CAMERA_LOCK_MISSING"
								}
							/>
							<ProfileField
								label="text_to_video_readiness_status"
								value={
									(result?.truth_status?.text_to_video_readiness_status as string | undefined) ||
									"NEEDS_REVIEW"
								}
							/>
							<ProfileField
								label="image_prompt_readiness_status"
								value={
									(result?.truth_status?.image_prompt_readiness_status as string | undefined) ||
									"NEEDS_REVIEW"
								}
							/>
							<ProfileField
								label="persistence_truth"
								value={profileTruthSummary.persistence_truth}
							/>
							<ProfileField
								label="copy_quality_detail"
								value={profileTruthSummary.copy_quality_detail}
							/>
						</div>
					</section>

					<section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
						<div className="flex flex-wrap items-center justify-between gap-3">
							<div>
								<div className="text-sm font-semibold text-slate-100">
									Video/Image Readiness
								</div>
								<div className="mt-1 text-[11px] text-slate-400">
									Mode readiness stays explicit. Missing assets stay visible and
									are not auto-generated from this panel.
								</div>
							</div>
							<div className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-200">
								recommended_first_mode={recommended_first_mode}
							</div>
						</div>
						<div className="bosmax-auto-fit-grid mt-4">
							{modeReadiness.map((item) => (
								<div
									key={item.key}
									className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"
								>
									<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
										{item.key}
									</div>
									<div
										className={`mt-2 inline-flex rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${statusTone(item.status)}`}
									>
										{item.status}
									</div>
									<div className="mt-3 text-[11px] text-slate-300">
										{item.detail}
									</div>
								</div>
							))}
						</div>
					</section>
				</div>
			) : (
				<div className="mt-4 rounded-2xl border border-dashed border-slate-700 bg-slate-950/50 p-4 text-[11px] text-slate-400">
					Select a product row or use Advanced Manual Override to paste an
					ephemeral product payload, then run Analyze Product to build the
					readiness profile.
				</div>
			)}

			<div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/70">
				<button
					type="button"
					onClick={() => setAdvancedOpen((current) => !current)}
					className="flex w-full items-center justify-between px-4 py-4 text-left"
				>
					<div>
						<div className="text-sm font-semibold text-slate-100">
							Advanced Manual Override
						</div>
						<div className="mt-1 text-[11px] text-slate-400">
							Manual fallback stays available. The old manual fields are still
							here, but they are no longer the primary top-level workflow.
						</div>
					</div>
					<span className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300">
						{advancedOpen ? "Expanded" : "Collapsed"}
					</span>
				</button>

				{advancedOpen ? (
					<div className="border-t border-slate-800 p-4">
						<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
									onChange={(value) =>
										onChange({ target_destination_mode: value })
									}
									options={[
										{ value: "TEXT_TO_VIDEO", label: "TEXT_TO_VIDEO" },
										{ value: "FRAMES", label: "FRAMES" },
										{ value: "INGREDIENTS", label: "INGREDIENTS" },
										{ value: "IMAGE", label: "IMAGE" },
									]}
									placeholder="Select a target destination mode"
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
									This response is preview-only. No generated character image
									exists yet, and nothing is Google-Flow-ready or
									Chrome-extension-visible yet.
								</div>
								<label className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-200">
									<input
										type="checkbox"
										checked={Boolean(draft.include_product_in_hand)}
										onChange={(event) =>
											onChange({
												include_product_in_hand: event.target.checked,
											})
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

						<div className="mt-4 text-[10px] text-slate-500">
							Request payload is validated locally before Analyze Product runs.
							Invalid JSON blocks submission.
						</div>
					</div>
				) : null}
			</div>

			{error ? (
				<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
					{error}
				</div>
			) : null}
		</section>
	);
}
