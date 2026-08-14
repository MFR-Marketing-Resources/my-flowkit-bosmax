import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchAPI } from "../api/client";
import {
	bindingFallbackGenerateAsset,
	generateAssetHasTransport,
	packageSlotResolvedAsset,
	resolvedAssetToGenerateAsset,
} from "../faceless/facelessLane";
import { useCopywritingReadiness } from "../api/copywritingReadiness";
import { fetchCreativeAssetEligibilityAudit } from "../api/creativeAssets";
import {
	getCreativeSetupForProduct,
	getProductRecipes,
	type CreativeRecipe,
} from "../api/creativeIntelligence";
import { fetchProductCatalog } from "../api/products";
import { fetchProductVisualReadiness } from "../api/productVisualOnboarding";
import {
	avatarRegistryCode,
	avatarRegistryLabel,
	avatarRegistryPreviewUrl,
	fetchAvatarRegistryPool,
	filterRecipesToAvatarRegistry,
	resolveAvatarRegistryCode,
	type AvatarRegistryPoolRow,
} from "../api/avatarRegistry";
import {
	createF2VGenerationPackage,
	createI2VGenerationPackage,
} from "../api/workspaceGenerationPackages";
import {
	compileWorkspacePromptPreview,
	createWorkspaceExecutionPackage,
	fetchPromptCompilerRuntimeConfig,
	fetchWorkspacePackageReadiness,
} from "../api/workspacePackages";
import BackendVersionBanner from "../components/BackendVersionBanner";
import CopyArchitectureV2LaneCard from "../components/copywriting/CopyArchitectureV2LaneCard";
import CopywritingReadinessCard from "../components/copywriting/CopywritingReadinessCard";
import NativeExtendPanel from "../components/NativeExtendPanel";
import RequestReportPanel from "../components/reporting/RequestReportPanel";
import SocialCopyPackagePanel from "../components/SocialCopyPackagePanel";
import CanonicalReferenceBindingControls, {
	type CanonicalReferenceBinding,
	EMPTY_BINDING,
} from "../components/workspace/CanonicalReferenceBindingControls";
import CopySelectionPanel from "../components/workspace/CopySelectionPanel";
import CreativeDirectionSection, {
	type CreativeDirection,
	EMPTY_CREATIVE_DIRECTION,
} from "../components/workspace/CreativeDirectionSection";
import IMGModule from "../components/workspace/IMGModule";
import {
	ResolvedChip,
	StoryboardStrip,
	WorkflowStep,
} from "../components/workflow";
import type { WorkflowStepStatus } from "../components/workflow";
import SceneStrategySummary from "../components/workspace/SceneStrategySummary";
import ResultsSidebar, { type SessionResult } from "../components/workspace/ResultsSidebar";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import VisualAssetPicker from "../components/workspace/VisualAssetPicker";
import type {
	Product,
	ProductVisualReadiness,
	PromptCameraStyle,
	PromptCharacterPresence,
	PromptCompilerRuntimeConfig,
	PromptGenerationMode,
	PromptTargetLanguage,
	TelemetryRequest,
	TelemetryRequestDetail,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
	WorkspaceGenerationPackage,
	WorkspaceMode,
	WorkspacePackageReadinessItem,
	WorkspacePromptPreviewResult,
} from "../types";
import { resolvePromptRepresentationPresentation } from "../utils/promptRepresentationUi";
import {
	getEngine,
	modelsForSingle,
	defaultEngine as pickDefaultEngine,
	resolveDurationChange,
	resolveSingleSelection,
	singleDurations,
	type VideoCapabilityMatrix,
} from "../utils/videoCapability";

type OperatorNoticeTone = "idle" | "info" | "success" | "warning" | "error";

interface OperatorNotice {
	tone: OperatorNoticeTone;
	title: string;
	detail: string;
	requestId: string | null;
}

const CANONICAL_PROMPT_SECTIONS = [
	"SECTION 1 - ROLE & OBJECTIVE",
	"SECTION 2 - PRODUCT TRUTH LOCK",
	"SECTION 3 - CONTINUITY & STATE LOCK",
	"SECTION 4 - VISUAL STORY",
	"SECTION 5 - SHOT & CAMERA RULES",
	"SECTION 6 - SPOKEN DIALOGUE",
	"SECTION 7 - VOICE & DELIVERY",
	"SECTION 8 - CTA & END FRAME",
	"SECTION 9 - NO_OVERLAY",
] as const;

interface PromptAuditSection {
	heading: string;
	sectionNumber: number | null;
	title: string;
	body: string;
}

interface PromptAuditBlock {
	block_index?: number;
	block_role?: string;
	duration_seconds?: number;
	shot_count?: number;
	dialogue_word_budget?: number;
	engine_prompt_text?: string;
	compiled_prompt_text?: string;
	initial_generation_prompt_text?: string | null;
	independent_block_prompt_text?: string | null;
	flow_extend_prompt_text?: string | null;
	prompt_representation?: string | null;
	prompt_purpose?: string | null;
	previous_block_index?: number | null;
	continuation_source?: string | null;
	audio_seam_contract?: {
		voice_active_in_final_second?: boolean;
		audio_seam_out?: string;
		dialogue_continuation_policy?: string;
		[key: string]: unknown;
	} | null;
	exact_dialogue_slice?: string;
	allocation?: {
		start_s: number;
		end_s: number;
		is_final: boolean;
		assigned_story_beats: Array<{ beat_id: string; role: string }>;
		exact_dialogue_slice: string;
		seam_policy: string;
	} | null;
}

function parsePromptSections(text: string): PromptAuditSection[] {
	const normalized = (text ?? "").replace(/\r\n/g, "\n");
	const matches = [...normalized.matchAll(/^SECTION [1-9] - .+$/gm)];
	if (matches.length === 0) {
		return [];
	}

	return matches.map((match, index) => {
		const heading = match[0].trim();
		const start = (match.index ?? 0) + match[0].length;
		const end =
			index + 1 < matches.length
				? (matches[index + 1].index ?? normalized.length)
				: normalized.length;
		const sectionNumberMatch = heading.match(/^SECTION (\d+)/);
		return {
			heading,
			sectionNumber: sectionNumberMatch ? Number(sectionNumberMatch[1]) : null,
			title: heading.replace(/^SECTION \d+ - /, ""),
			body: normalized.slice(start, end).trim(),
		};
	});
}

function PromptAuditCard({
	label,
	block,
	fallbackText,
}: {
	label: string;
	block?: PromptAuditBlock | null;
	fallbackText?: string | null;
}) {
	const [copiedPrimary, setCopiedPrimary] = useState(false);
	const [copiedSecondary, setCopiedSecondary] = useState(false);
	const presentation = resolvePromptRepresentationPresentation(
		block,
		fallbackText,
	);
	const independentText = presentation.independentText;
	const extendText = presentation.extendText;
	const primaryText = presentation.primaryCopyText;
	const primaryLabel = presentation.primaryCopyLabel;
	const representationLabel = presentation.badgeLabel;
	const isExtendBlock = presentation.showExtendPrimary;
	const showExtendUnavailable = presentation.showExtendUnavailable;
	const showIndependentSecondary = presentation.showIndependentSecondary;
	const sections = parsePromptSections(
		isExtendBlock
			? independentText
			: presentation.initialText || independentText,
	);
	const allocation = block?.allocation;
	const presentHeadings = new Set(sections.map((section) => section.heading));
	const missingSections = CANONICAL_PROMPT_SECTIONS.filter(
		(heading) => !presentHeadings.has(heading),
	);
	const handleCopyPrimary = useCallback(() => {
		// Never silently copy independent text through a Copy Extend Prompt button.
		if (presentation.showExtendPrimary && !presentation.extendText) {
			return;
		}
		navigator.clipboard.writeText(primaryText || "").then(() => {
			setCopiedPrimary(true);
			window.setTimeout(() => setCopiedPrimary(false), 2200);
		});
	}, [primaryText, presentation.showExtendPrimary, presentation.extendText]);
	const handleCopyIndependent = useCallback(() => {
		navigator.clipboard.writeText(independentText || "").then(() => {
			setCopiedSecondary(true);
			window.setTimeout(() => setCopiedSecondary(false), 2200);
		});
	}, [independentText]);
	const metaChips = [
		block?.block_role ? `Role ${block.block_role}` : null,
		block?.duration_seconds ? `${block.duration_seconds}s` : null,
		block?.shot_count
			? `${block.shot_count} shot${block.shot_count > 1 ? "s" : ""}`
			: null,
		block?.dialogue_word_budget ? `${block.dialogue_word_budget} words` : null,
	].filter(Boolean) as string[];
	const audioSeam = block?.audio_seam_contract;

	return (
		<div
			className="rounded-xl border border-slate-800 bg-slate-950/70 overflow-hidden"
			data-testid="prompt-audit-card"
		>
			<div className="flex flex-col gap-3 border-b border-slate-800 px-4 py-3 md:flex-row md:items-start md:justify-between">
				<div className="space-y-2">
					<div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
						{label}
					</div>
					<div className="flex flex-wrap gap-2">
						<span
							className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-200"
							data-testid="prompt-representation-badge"
						>
							{representationLabel}
						</span>
						{!isExtendBlock ? (
							<span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
								{sections.length}/9 sections
							</span>
						) : (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-amber-200">
								Extension-native · manual research
							</span>
						)}
						{metaChips.map((chip) => (
							<span
								key={chip}
								className="rounded-full border border-slate-800 bg-slate-900/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
							>
								{chip}
							</span>
						))}
						{!isExtendBlock && missingSections.length === 0 ? (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
								Canonical 9-section structure
							</span>
						) : null}
						{!isExtendBlock && missingSections.length > 0 ? (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
								Missing{" "}
								{missingSections
									.map((heading) => heading.replace("SECTION ", "S"))
									.join(", ")}
							</span>
						) : null}
					</div>
				</div>
				<div className="flex flex-wrap gap-2">
					<button
						type="button"
						onClick={handleCopyPrimary}
						data-testid={presentation.primaryTestId}
						className={`rounded-lg border px-3 py-2 text-[11px] font-semibold transition-colors ${copiedPrimary ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-blue-500/30 bg-blue-500/10 text-blue-100 hover:bg-blue-500/20"}`}
					>
						{copiedPrimary ? "Copied" : primaryLabel}
					</button>
					{showIndependentSecondary ? (
						<button
							type="button"
							onClick={handleCopyIndependent}
							data-testid="copy-independent-block-prompt"
							className={`rounded-lg border px-3 py-2 text-[11px] font-semibold transition-colors ${copiedSecondary ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-slate-600 bg-slate-800/80 text-slate-200 hover:bg-slate-700"}`}
						>
							{copiedSecondary ? "Copied" : "Copy Independent Block Prompt"}
						</button>
					) : null}
				</div>
			</div>
			{presentation.helpText ? (
				<div
					className={`border-b border-slate-800 px-4 py-2 text-[11px] ${showExtendUnavailable ? "bg-amber-500/10 text-amber-100" : "bg-indigo-500/5 text-indigo-100"}`}
					data-testid={
						showExtendUnavailable
							? "extend-not-available"
							: "extend-prompt-help"
					}
				>
					{presentation.helpText}
				</div>
			) : null}
			{allocation ? (
				<div
					className="border-b border-slate-800 bg-slate-900/40 px-4 py-3 text-xs text-slate-300"
					data-testid="storyboard-allocation-summary"
				>
					<div className="font-semibold text-slate-200">
						Storyboard allocation · {allocation.start_s}–{allocation.end_s}s ·{" "}
						{allocation.is_final ? "Final closure" : "Continuation seam"}
					</div>
					<div className="mt-1 text-slate-400">
						Story beats:{" "}
						{allocation.assigned_story_beats
							.map((beat) => beat.role)
							.join(" → ")}
					</div>
					<div className="mt-1 text-slate-400">
						Exact dialogue:{" "}
						{allocation.exact_dialogue_slice ||
							block?.exact_dialogue_slice ||
							"(visual-only block)"}
					</div>
					{block?.previous_block_index ? (
						<div className="mt-1 text-slate-400">
							Previous block: {block.previous_block_index} · Continuation
							source: {block.continuation_source || "PREVIOUS_GENERATED_VIDEO"}
						</div>
					) : null}
					{audioSeam ? (
						<div
							className="mt-1 text-slate-400"
							data-testid="audio-seam-summary"
						>
							Audio seam: {String(audioSeam.audio_seam_out || "—")}
							{audioSeam.voice_active_in_final_second
								? " · voice active in final second"
								: ""}
							{allocation.is_final
								? " · final block (no next extension seam)"
								: ""}
						</div>
					) : null}
				</div>
			) : null}
			{isExtendBlock && extendText ? (
				<div
					className="border-b border-slate-800 px-4 py-3 text-sm leading-relaxed text-slate-200 whitespace-pre-wrap"
					data-testid="flow-extend-prompt-preview"
				>
					{extendText}
				</div>
			) : null}
			{sections.length > 0 ? (
				<div className="divide-y divide-slate-800">
					{sections.map((section) => (
						<details
							key={section.heading}
							open={
								section.sectionNumber === 4 ||
								section.sectionNumber === 6 ||
								section.sectionNumber === 8
							}
							className="group"
						>
							<summary className="cursor-pointer list-none px-4 py-3">
								<div className="flex items-center justify-between gap-3">
									<div className="flex items-center gap-2">
										<span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
											S{section.sectionNumber ?? "?"}
										</span>
										<span className="text-xs font-semibold text-slate-100">
											{section.title}
										</span>
									</div>
									<span className="text-[10px] uppercase tracking-[0.16em] text-slate-500 group-open:text-slate-300">
										Expand
									</span>
								</div>
							</summary>
							<pre className="border-t border-slate-800 px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
								{section.body || "(empty section)"}
							</pre>
						</details>
					))}
				</div>
			) : (
				<pre className="px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
					{independentText || "(no prompt text)"}
				</pre>
			)}
		</div>
	);
}

function humanizeWorkspaceMode(mode: WorkspaceMode) {
	if (mode === "HYBRID") return "Hybrid";
	if (mode === "F2V") return "Frames";
	if (mode === "I2V") return "Ingredients";
	if (mode === "IMG") return "Image";
	return "Text to Video";
}

function workspaceSurfaceLabel(mode: WorkspaceMode) {
	if (mode === "HYBRID") return "Hybrid (Product + AI Presenter)";
	if (mode === "F2V") return "Frames (Motion Delta)";
	if (mode === "I2V") return "Ingredients";
	if (mode === "IMG") return "Image Generation";
	return "Text to Video";
}

// ── V4 workflow shell helpers ──────────────────────────────────────────────
// Derive the backward-compatible CreativeDirection from a set of coherent
// recipes. Mirrors CreativeDirectionSection.directionFromRecipes so the
// presenter-first V4 flow produces the SAME payload shape (recipes[0] feeds
// scene_template_id + camera_preset_code) without importing its internals.
function buildCreativeDirectionFromRecipes(
	recipes: CreativeRecipe[],
): CreativeDirection {
	const uniq = (values: string[]) =>
		Array.from(new Set(values.filter(Boolean)));
	return {
		avatarCodes: uniq(recipes.map((r) => r.avatar_code)),
		sceneTemplateIds: uniq(recipes.map((r) => r.scene_template_id)),
		cameraPresetCodes: uniq(recipes.map((r) => r.camera_preset_code)),
		recipes,
	};
}

function v4GenderTag(code: string): string {
	if (code.includes("_F_")) return "♀";
	if (code.includes("_M_")) return "♂";
	return "";
}

function v4SceneText(recipe: CreativeRecipe): string {
	const variant = recipe.scene_variant
		.replace(/^Variation\s*\d+\s*[-:]\s*/i, "")
		.trim();
	const varTag = recipe.variation != null ? `Var${recipe.variation}` : "scene";
	return variant ? `${varTag} · ${variant}` : varTag;
}

// Canonical source-mode (ADR-008): PINNED by the operator surface — HYBRID and
// FRAMES are separate first-class pages, never an ambiguous toggle. Hoisted to a
// pure module-scope export so the mapping is unit-testable without rendering the
// page. Mapping is byte-identical to the prior in-component useCallback.
export function resolveOperatorSourceMode(
	m: string,
): "T2V" | "HYBRID" | "FRAMES" | "INGREDIENTS" | "IMAGES" {
	if (m === "HYBRID") return "HYBRID";
	if (m === "F2V") return "FRAMES";
	if (m === "I2V") return "INGREDIENTS";
	if (m === "IMG") return "IMAGES";
	return "T2V";
}

// Canonical per-mode reference-binding gate (pure + hoisted so the contract is
// unit-testable without rendering the page). Mirrors the SERVER contract:
// HYBRID needs NO manual pick (the approved package supplies the product anchor
// automatically; a pick is an override) · FRAMES requires an explicit start
// frame (end optional) · INGREDIENTS requires the default recipe's character +
// scene context roles (style optional) · T2V/IMAGES bind nothing.
export function referenceBindingBlocker(
	mode: string,
	binding: CanonicalReferenceBinding,
): string | null {
	if (mode === "F2V" && !binding.startFrameAssetId) {
		return "FRAMES requires an approved composite start frame reference (end frame optional).";
	}
	if (
		mode === "I2V" &&
		!(binding.characterReferenceAssetId && binding.sceneContextReferenceAssetId)
	) {
		return "INGREDIENTS requires the recipe's character and scene context references (style optional).";
	}
	return null;
}

// Owner Phase-1 (SEV-0 manual_faf40cf6): a HYBRID failure must never surface as a
// bare "F2V failed" — the SOURCE mode is the user-facing identity; the shared
// transport mode is a diagnostic detail. Pure + hoisted so the mapping is
// unit-testable without rendering the page. Presentation only: transport values
// and telemetry keys are unchanged.
export function noticeModeLabel(
	surfaceMode: string,
	transportMode: string,
): string {
	const source = resolveOperatorSourceMode(surfaceMode);
	if (source === "HYBRID") return `HYBRID (transport: ${transportMode})`;
	if (source === "FRAMES") return "Frames/F2V";
	if (source === "INGREDIENTS") return "Ingredients/I2V";
	return transportMode;
}

const OPERATOR_EXTEND_ROUTE = "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS";
const OPERATOR_EXTEND_PLAN_BY_TOTAL: Record<number, number[]> = {
	16: [8, 8],
	24: [8, 8, 8],
	32: [8, 8, 8, 8],
	48: [8, 8, 8, 8, 8, 8],
	56: [8, 8, 8, 8, 8, 8, 8],
};

type OperatorDurationAuthorityPayload =
	| {
			generation_mode: "SINGLE";
			duration_seconds: number;
			blocks: [];
	  }
	| {
			generation_mode: "EXTEND";
			engine_duration_target: "GOOGLE_FLOW";
			requested_total_duration_seconds: number;
	  };

export type OperatorDurationAuthority = {
	generationMode: PromptGenerationMode;
	route: string | null;
	plan: number[];
	timeline: Array<{ block_index: number; start_s: number; end_s: number }>;
	payload: OperatorDurationAuthorityPayload;
};

/**
 * The shared video-mode duration authority. SINGLE never carries continuation
 * state; EXTEND resolves its fixed, authorized Google Flow route from one total.
 */
export function buildOperatorDurationAuthority({
	generationMode,
	videoDurationSeconds,
	extendTotalDurationSeconds,
}: {
	generationMode: PromptGenerationMode;
	videoDurationSeconds: number;
	extendTotalDurationSeconds: number | null;
}): OperatorDurationAuthority {
	if (generationMode === "SINGLE") {
		return {
			generationMode,
			route: null,
			plan: [videoDurationSeconds],
			timeline: [{ block_index: 1, start_s: 0, end_s: videoDurationSeconds }],
			payload: {
				generation_mode: "SINGLE",
				duration_seconds: videoDurationSeconds,
				blocks: [],
			},
		};
	}

	if (extendTotalDurationSeconds === null) {
		throw new Error("EXTEND_TOTAL_DURATION_REQUIRED");
	}
	const plan = OPERATOR_EXTEND_PLAN_BY_TOTAL[extendTotalDurationSeconds];
	if (!plan) {
		throw new Error(
			`UNSUPPORTED_EXTEND_TOTAL_DURATION_${extendTotalDurationSeconds}`,
		);
	}
	let cursor = 0;
	const timeline = plan.map((durationSeconds, index) => {
		const start_s = cursor;
		cursor += durationSeconds;
		return { block_index: index + 1, start_s, end_s: cursor };
	});
	return {
		generationMode,
		route: OPERATOR_EXTEND_ROUTE,
		plan,
		timeline,
		payload: {
			generation_mode: "EXTEND",
			engine_duration_target: "GOOGLE_FLOW",
			requested_total_duration_seconds: extendTotalDurationSeconds,
		},
	};
}

export function transitionOperatorDurationAuthority(
	current: {
		generationMode: PromptGenerationMode;
		extendTotalDurationSeconds: number | null;
	},
	nextGenerationMode: PromptGenerationMode,
) {
	return {
		generationMode: nextGenerationMode,
		extendTotalDurationSeconds:
			nextGenerationMode === "SINGLE"
				? null
				: current.extendTotalDurationSeconds,
		clearCompiledArtifacts: current.generationMode !== nextGenerationMode,
	};
}

function parseWorkspaceBlocker(error: unknown): string | null {
	const message = error instanceof Error ? error.message : String(error || "");
	const match = message.match(
		/REFERENCE_ONLY_PRODUCT|CLAIM_SAFE_PACKAGE_NOT_READY|PRODUCTION_APPROVAL_REQUIRED|START_FRAME_REQUIRED|SUBJECT_REQUIRED|PRODUCT_ARCHIVED|UNSUPPORTED_MODE/,
	);
	return match?.[0] ?? null;
}

function blockerMessage(blocker: string | null, mode: WorkspaceMode) {
	switch (blocker) {
		case "REFERENCE_ONLY_PRODUCT":
			return "FastMoss reference products stay visible for review, but Smart Registration must convert them into product truth before package load.";
		case "CLAIM_SAFE_PACKAGE_NOT_READY":
			return "This product has no approved claim-safe package yet. Open the guided claim-safe review to see missing fields, prepare or fill a review draft explicitly, and approve the deterministic package.";
		case "PRODUCTION_APPROVAL_REQUIRED":
			return "This product is not production-approved for this mode yet.";
		case "START_FRAME_REQUIRED":
			return "F2V requires a product image as Start Frame.";
		case "SUBJECT_REQUIRED":
			return "This mode requires a product image or subject reference.";
		case "PRODUCT_ARCHIVED":
			return "Archived products cannot be loaded for generation.";
		case "UNSUPPORTED_MODE":
			return `${mode} is not supported by the approved package bridge.`;
		default:
			return "Failed to load approved package.";
	}
}

export function buildClaimSafeFixPath(
	productId: string,
	returnPath: string,
): string {
	const params = new URLSearchParams({
		tab: "INTELLIGENCE",
		product: productId,
		claimSafeFix: "1",
		returnTo: returnPath,
	});
	return `/products?${params.toString()}`;
}

interface OperatorPageProps {
	mode?: "T2V" | "HYBRID" | "F2V" | "I2V" | "IMG";
}

export default function OperatorPage({ mode: propMode }: OperatorPageProps) {
	const location = useLocation();
	const navigate = useNavigate();
	const statePackage = (
		location.state as {
			workspaceExecutionPackage?: WorkspaceExecutionPackage;
			claimSafeProduct?: Product;
		} | null
	)?.workspaceExecutionPackage;
	const stateClaimSafeProduct = (
		location.state as {
			claimSafeProduct?: Product;
		} | null
	)?.claimSafeProduct;
	const isPortalMode =
		new URLSearchParams(location.search).get("portal") === "side";
	const [isExecuting, setIsExecuting] = useState(false);
	const [isSavingPackage, setIsSavingPackage] = useState(false);
	const [savedGenPackage, setSavedGenPackage] =
		useState<WorkspaceGenerationPackage | null>(null);
	const [savePackageError, setSavePackageError] = useState<string | null>(null);
	const [modeRequests, setModeRequests] = useState<TelemetryRequest[]>([]);
	const [compactPane, setCompactPane] = useState<"workspace" | "jobs">(
		"workspace",
	);
	const [products, setProducts] = useState<Product[]>([]);
	const [productsError, setProductsError] = useState<string | null>(null);
	const [isLoadingProducts, setIsLoadingProducts] = useState(false);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(
		stateClaimSafeProduct ?? null,
	);
	const [referenceBinding, setReferenceBinding] =
		useState<CanonicalReferenceBinding>(EMPTY_BINDING);
	// HYBRID anchor clarity: the product's official image (approved cutout →
	// source → product image) is the automatic Hybrid anchor. We read its
	// readiness so the reference step can say "anchor set" vs. "prepare / set the
	// official image" instead of the old cryptic reference-resolution blocker.
	// Presentation only — never gates or changes generation/dispatch/credit logic.
	const [hybridVisualReadiness, setHybridVisualReadiness] =
		useState<ProductVisualReadiness | null>(null);
	const [packageReadiness, setPackageReadiness] = useState<
		Record<string, WorkspacePackageReadinessItem>
	>({});
	const [workspacePackage, setWorkspacePackage] =
		useState<WorkspaceExecutionPackage | null>(statePackage ?? null);
	const [previewPackage, setPreviewPackage] =
		useState<WorkspacePromptPreviewResult | null>(null);
	// Copy Selection & Compiler Binding V1: operator-selected approved Copy Set
	// bound into the preview/final prompt request payload for the selected product.
	const [selectedCopySetId, setSelectedCopySetId] = useState<string | null>(
		null,
	);
	const { readiness: copyReadiness, loading: copyReadinessLoading } =
		useCopywritingReadiness(selectedProduct?.id ?? null);
	// HYBRID anchor is auto-locked from the product's official image, so the
	// canonical reference picker is collapsed by default and only revealed when
	// the operator explicitly chooses to override the anchor.
	const [showHybridOverride, setShowHybridOverride] = useState(false);
	// Avatar + scene are auto-picked from the product-type mapping (shown as
	// locks). The override dropdowns stay hidden behind an "Advanced" disclosure
	// so the presenter/scene read as mapped defaults, not free-form picks.
	const [showPresenterOverride, setShowPresenterOverride] = useState(false);
	const [isLoadingPreview, setIsLoadingPreview] = useState(false);
	const [isLoadingPackage, setIsLoadingPackage] = useState(false);
	const [isLoadingReadiness, setIsLoadingReadiness] = useState(false);
	const [isLoadingSelectedReadiness, setIsLoadingSelectedReadiness] =
		useState(false);
	const [promptConfig, setPromptConfig] =
		useState<PromptCompilerRuntimeConfig | null>(null);
	const [generationMode, setGenerationMode] =
		useState<PromptGenerationMode>("SINGLE");
	const [targetLanguage, setTargetLanguage] =
		useState<PromptTargetLanguage>("BM_MS");
	const [cameraStyle, setCameraStyle] =
		useState<PromptCameraStyle>("UGC_IPHONE_RAW");
	const [characterPresence, setCharacterPresence] =
		useState<PromptCharacterPresence>("VISIBLE_CREATOR");
	// T2V/Hybrid presenter identity is always resolved from the approved Avatar
	// Registry; no persona-composer or legacy persona fallback reaches production.
	const [registryAvatarId, setRegistryAvatarId] = useState("");
	const [registrySceneCode, setRegistrySceneCode] = useState("");
	const [avatarRegistryPool, setAvatarRegistryPool] = useState<
		AvatarRegistryPoolRow[]
	>([]);
	const [sceneRegistryPool, setSceneRegistryPool] = useState<
		Array<{
			scene_code: string;
			scene_name?: string;
			generated_asset_id?: string | null;
			background_prompt?: string;
			image_generated?: boolean;
			primary_cluster?: string | null;
			compatible_clusters?: string[];
		}>
	>([]);
	const [registryPoolsLoading, setRegistryPoolsLoading] = useState(false);
	const [registryPreviewUrls, setRegistryPreviewUrls] = useState<Record<string, string>>({});
	const [backendRuntimeStale, setBackendRuntimeStale] = useState(false);
	// T2V descriptor-based creative direction (no image pickers). The primary
	// avatar drives the load-bearing `avatar_id` generation input via
	// `registryAvatarId`; scene-strategy / camera descriptors shape the prompt.
	const [creativeDirection, setCreativeDirection] = useState<CreativeDirection>(
		EMPTY_CREATIVE_DIRECTION,
	);
	const handleCreativeDirectionChange = useCallback(
		(next: CreativeDirection) => {
			const avatar = resolveAvatarRegistryCode(
				next.avatarCodes[0],
				avatarRegistryPool,
			);
			setCreativeDirection({
				...next,
				avatarCodes: avatar ? [avatar] : [],
			});
			// Keep the presenter authority in sync so T2V generation still resolves
			// an avatar (avatar_id) exactly as the old registry picker did.
			setRegistryAvatarId(avatar);
		},
		[avatarRegistryPool],
	);
	useEffect(() => {
		let cancelled = false;
		setRegistryPoolsLoading(true);
		Promise.all([
			fetchAvatarRegistryPool().catch(() => []),
			fetchAPI<{
				scenes?: typeof sceneRegistryPool;
				count?: number;
			}>("/api/workspace/scene-context-registry/pool").catch(() => ({ scenes: [] })),
		])
			.then(([avatarResp, sceneResp]) => {
				if (cancelled) return;
				setAvatarRegistryPool(avatarResp);
				setSceneRegistryPool(sceneResp.scenes ?? []);
			})
			.finally(() => {
				if (!cancelled) setRegistryPoolsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, []);
	useEffect(() => {
		if (!avatarRegistryPool.length || !registryAvatarId) return;
		if (resolveAvatarRegistryCode(registryAvatarId, avatarRegistryPool)) return;
		setRegistryAvatarId("");
		setCreativeDirection((current) => ({ ...current, avatarCodes: [] }));
	}, [avatarRegistryPool, registryAvatarId]);
	useEffect(() => { void Promise.all([fetchCreativeAssetEligibilityAudit({ surface: "I2V_CHARACTER_PICKER" }), fetchCreativeAssetEligibilityAudit({ surface: "I2V_SCENE_PICKER" })]).then((results) => setRegistryPreviewUrls(Object.fromEntries(results.flatMap((result) => result.eligible_assets.map((asset) => [asset.asset_id, asset.preview_url || asset.download_url || ""]))))).catch(() => setRegistryPreviewUrls({})); }, []);
	const selectedSceneBackground =
		sceneRegistryPool.find((s) => s.scene_code === registrySceneCode)?.background_prompt?.trim() ||
		"";
	const [videoDurationSeconds, setVideoDurationSeconds] = useState(8);
	// Canonical source-mode (ADR-008) — delegates to the hoisted pure export
	// resolveOperatorSourceMode; identity is stable across renders.
	const resolveSourceMode = resolveOperatorSourceMode;
	const [requestedTotalDuration, setRequestedTotalDuration] = useState<
		number | null
	>(null);
	const isExtendMode = generationMode === "EXTEND";
	const durationAuthority =
		isExtendMode && requestedTotalDuration === null
			? null
			: buildOperatorDurationAuthority({
					generationMode,
					videoDurationSeconds,
					extendTotalDurationSeconds: requestedTotalDuration,
				});
	const extendTotalRequired = isExtendMode && durationAuthority === null;
	// A total is mandatory in production EXTEND. Never let a stale preview survive
	// an incomplete duration choice.
	useEffect(() => {
		if (extendTotalRequired) setPreviewPackage(null);
	}, [extendTotalRequired]);
	const [notice, setNotice] = useState<OperatorNotice>({
		tone: "idle",
		title: "Idle",
		detail: "Submit a job to start Google Flow automation.",
		requestId: null,
	});
	// Finished artifact preview — rendered inline the moment a job completes so the
	// operator never has to back-button/reload to find out the video is ready.
	const [sessionResults, setSessionResults] = useState<SessionResult[]>([]);
	const [completedArtifact, setCompletedArtifact] = useState<{
		mediaId: string;
		url: string;
		kind: "video" | "image";
		sizeMb: string | null;
	} | null>(null);
	// Finished results live in the LIBRARY pages (/library/videos, /library/images)
	// with 48h retention — the workspace page stays a WORKPLACE. Only the
	// just-completed artifact preview (completedArtifact) renders here.
	const pollTimerRef = useRef<number | null>(null);
	// In-flight guard: block a second START GENERATION while one execution is
	// still pending (the button re-enables on fast failures, so without this a
	// quick re-click dispatches a duplicate job to the same editor).
	const executionInFlightRef = useRef(false);

	const pathMode = location.pathname.split("/").pop()?.toUpperCase();
	const mode =
		propMode ||
		(pathMode === "T2V" ||
		pathMode === "HYBRID" ||
		pathMode === "F2V" ||
		pathMode === "I2V" ||
		pathMode === "IMG"
			? pathMode
			: "F2V");
	// API/job boundary mapping (ADR-007): the HYBRID operator surface runs F2V
	// jobs/packages with source_mode="HYBRID". Everything backend-bound uses
	// jobMode; the surface identity stays HYBRID.
	const jobMode: "T2V" | "F2V" | "I2V" | "IMG" =
		mode === "HYBRID" ? "F2V" : mode;

	// ── V4 workflow shell (guided single-page redesign) ──────────────────────
	// V4 is the default for every OperatorPage lane. ?classic=1 always wins and
	// keeps the existing render reachable as the transitional rollback path.
	// Both paths reuse the same state + handlers, so Step-F payload wiring stays
	// intact while the classic branch remains available for recovery.
	const query = new URLSearchParams(location.search);
	const useV4 = query.get("classic") !== "1";
	const [v4Pool, setV4Pool] = useState<CreativeRecipe[]>([]);
	const [v4Pretick, setV4Pretick] = useState<CreativeRecipe[]>([]);
	const [v4RecipesLoading, setV4RecipesLoading] = useState(false);
	// Per-step manual open/collapse overrides; default = the active step is open.
	const [v4Open, setV4Open] = useState<Record<number, boolean>>({});
	const v4IsOpen = (index: number, status: WorkflowStepStatus) =>
		v4Open[index] ?? status === "active";
	const v4Toggle = (index: number, currentOpen: boolean) =>
		setV4Open((prev) => ({ ...prev, [index]: !currentOpen }));
	// Resolve the presenter AND its coherent scene→camera recipe together, so the
	// avatar (avatar_id) and the recipe (scene/camera) never disagree.
	const applyV4Presenter = useCallback(
		(avatar: string, pool: CreativeRecipe[], pretick: CreativeRecipe[]) => {
			const registryPool = filterRecipesToAvatarRegistry(pool, avatarRegistryPool);
			const registryPretick = filterRecipesToAvatarRegistry(pretick, avatarRegistryPool);
			// Single-select: ONE coherent recipe for the presenter (the knowledge
			// base's top pick) becomes recipes[0] → scene_template_id + camera_preset.
			const chosen =
				registryPretick.find((r) => r.avatar_code === avatar) ??
				registryPool.find((r) => r.avatar_code === avatar) ??
				null;
			handleCreativeDirectionChange(
				buildCreativeDirectionFromRecipes(chosen ? [chosen] : []),
			);
		},
		[avatarRegistryPool, handleCreativeDirectionChange],
	);
	// Load the product's coherent recipe pool for the V4 T2V lane; auto-pick a
	// default presenter from the knowledge base only when none is set yet.
	// biome-ignore lint/correctness/useExhaustiveDependencies: the pool loads on product changes; a manual registry pick must not refetch it
	useEffect(() => {
		if (!useV4 || mode === "IMG" || !selectedProduct?.id) return;
		let active = true;
		setV4RecipesLoading(true);
		void getProductRecipes(selectedProduct.id)
			.then((res) => {
				if (!active) return;
				const registryRecipes = filterRecipesToAvatarRegistry(
					res.recipes,
					avatarRegistryPool,
				);
				const registryPretick = filterRecipesToAvatarRegistry(
					res.recommended_pretick,
					avatarRegistryPool,
				);
				setV4Pool(registryRecipes);
				setV4Pretick(registryPretick);
				if (!registryAvatarId) {
					const autoAvatar =
						registryPretick[0]?.avatar_code ??
						registryRecipes[0]?.avatar_code ??
						"";
					if (autoAvatar)
						applyV4Presenter(autoAvatar, registryRecipes, registryPretick);
				}
			})
			.catch(() => {})
			.finally(() => {
				if (active) setV4RecipesLoading(false);
			});
		return () => {
			active = false;
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [useV4, mode, selectedProduct?.id, avatarRegistryPool]);
	// Keep the scene→camera recipe coherent with whoever set the presenter
	// (creative-setup seed, manual pick). Idempotent: no-op when already in sync,
	// when the avatar is not in this product's pool, or when the recipe is empty.
	useEffect(() => {
		if (!useV4 || mode === "IMG" || !registryAvatarId || v4Pool.length === 0)
			return;
		if (creativeDirection.recipes[0]?.avatar_code === registryAvatarId) return;
		if (!v4Pool.some((r) => r.avatar_code === registryAvatarId)) return;
		applyV4Presenter(registryAvatarId, v4Pool, v4Pretick);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [
		useV4,
		mode,
		registryAvatarId,
		v4Pool,
		v4Pretick,
		creativeDirection.recipes[0]?.avatar_code,
		applyV4Presenter,
	]);
	// Stale-reference law: a mode or product switch invalidates every prior
	// reference selection (the server's WRONG_PRODUCT / per-mode contract checks
	// stay the authority; this keeps the UI from carrying another product's or
	// another mode's pick into the next package).
	// biome-ignore lint/correctness/useExhaustiveDependencies: reset-on-change effect
	useEffect(() => {
		setReferenceBinding(EMPTY_BINDING);
	}, [mode, selectedProduct?.id]);
	// Official-image readiness for the HYBRID anchor. Guarded to HYBRID + a
	// selected product; any failure falls back to "not ready" copy. Never throws
	// and never gates generation — the backend still owns the real anchor.
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed on mode + product id
	useEffect(() => {
		if (mode !== "HYBRID" || !selectedProduct?.id) {
			setHybridVisualReadiness(null);
			return;
		}
		let active = true;
		const pid = selectedProduct.id;
		void Promise.resolve(fetchProductVisualReadiness(pid))
			.then((readiness) => {
				if (active) setHybridVisualReadiness(readiness ?? null);
			})
			.catch(() => {
				if (active) setHybridVisualReadiness(null);
			});
		return () => {
			active = false;
		};
	}, [mode, selectedProduct?.id]);
	const selectedReadiness = selectedProduct
		? (packageReadiness[selectedProduct.id] ?? null)
		: null;
	const selectedReadinessLoading = Boolean(
		selectedProduct &&
			!selectedProduct.reference_only &&
			!selectedReadiness &&
			(isLoadingReadiness || isLoadingSelectedReadiness),
	);
	const isLoadingAnyReadiness =
		isLoadingReadiness || isLoadingSelectedReadiness;

	useEffect(() => {
		setIsLoadingProducts(true);
		setProductsError(null);
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items ?? []))
			.catch((err: unknown) =>
				setProductsError(
					err instanceof Error ? err.message : "Failed to load product catalog",
				),
			)
			.finally(() => setIsLoadingProducts(false));
	}, []);

	// Clear any bound Copy Set when the product changes — a copy_set_id is only
	// valid for the product it belongs to (backend fails closed on mismatch).
	// biome-ignore lint/correctness/useExhaustiveDependencies: reset keyed on product id only
	useEffect(() => {
		setSelectedCopySetId(null);
		// Knowledge-driven pre-fill: seed the avatar picker from the product's creative
		// setup (gender/cluster-correct saved selection, else the smart default) so the
		// operator starts from the RIGHT avatar instead of free-picking a mismatched one.
		// Manual override stays free. Scene stays manual until the scene-template ->
		// scene-context mapping is wired (different registries).
		const pid = selectedProduct?.id;
		if (!pid) return;
		let active = true;
		void getCreativeSetupForProduct(pid)
			.then((setup) => {
				if (!active) return;
				const avatar =
					setup.saved_selection?.selected_avatar_codes?.[0] ||
					setup.default_selection?.selected_avatar_codes?.[0] ||
					"";
				const registryAvatar = resolveAvatarRegistryCode(
					avatar,
					avatarRegistryPool,
				);
				if (registryAvatar) setRegistryAvatarId(registryAvatar);
				// Scene pre-fill: the saved scene TEMPLATES (SCN-xxxx strategy) are a
				// different layer from the generation scene CONTEXTS (backgrounds), so
				// pick a cluster-appropriate scene context from the registry instead of
				// mapping template ids. No match (e.g. cluster has no scene yet) → leave
				// the operator's manual pick.
				const cluster = String(setup.cluster || "").trim().toLowerCase();
				if (cluster) {
					const match = sceneRegistryPool.find((s) => {
						const pc = String(s.primary_cluster || "").trim().toLowerCase();
						const compat = (s.compatible_clusters || []).map((c) =>
							String(c).trim().toLowerCase(),
						);
						return pc === cluster || compat.includes(cluster);
					});
					if (match?.scene_code) setRegistrySceneCode(match.scene_code);
				}
			})
			.catch(() => {});
		return () => {
			active = false;
		};
	}, [selectedProduct?.id, avatarRegistryPool]);

	useEffect(() => {
		void fetchPromptCompilerRuntimeConfig()
			.then((config) => {
				setPromptConfig(config);
				setGenerationMode(config.defaults.generation_mode);
				setTargetLanguage(config.defaults.target_language);
				setCameraStyle(config.defaults.camera_style);
				setCharacterPresence(config.defaults.character_presence);
				setVideoDurationSeconds(config.defaults.block_duration_seconds);
			})
			.catch(() => {});
	}, []);

	useEffect(() => {
		if (products.length === 0) {
			setPackageReadiness({});
			return;
		}
		setPackageReadiness({});
		setIsLoadingReadiness(true);
		void fetchWorkspacePackageReadiness({
			mode: jobMode as WorkspaceMode,
			source_mode: resolveSourceMode(mode),
			product_ids: products.map((item) => item.id),
		})
			.then((response) => {
				const mapped = Object.fromEntries(
					response.items.map((item) => [item.product_id, item]),
				);
				setPackageReadiness((current) => ({ ...current, ...mapped }));
			})
			.catch(() => {})
			.finally(() => setIsLoadingReadiness(false));
	}, [jobMode, mode, products]);

	useEffect(() => {
		if (
			!selectedProduct ||
			selectedProduct.reference_only ||
			packageReadiness[selectedProduct.id]
		) {
			setIsLoadingSelectedReadiness(false);
			return;
		}
		let isActive = true;
		setIsLoadingSelectedReadiness(true);
		void fetchWorkspacePackageReadiness({
			mode: jobMode as WorkspaceMode,
			source_mode: resolveSourceMode(mode),
			product_ids: [selectedProduct.id],
		})
			.then((response) => {
				if (!isActive) return;
				const item = response.items[0];
				if (!item) return;
				setPackageReadiness((current) => ({
					...current,
					[item.product_id]: item,
				}));
			})
			.catch(() => {})
			.finally(() => {
				if (isActive) {
					setIsLoadingSelectedReadiness(false);
				}
			});
		return () => {
			isActive = false;
		};
	}, [jobMode, mode, packageReadiness, selectedProduct]);

	useEffect(() => {
		if (!statePackage || statePackage.mode !== mode) return;
		setWorkspacePackage(statePackage);
	}, [mode, statePackage]);

	useEffect(() => {
		if (!workspacePackage || products.length === 0) return;
		const matched = products.find(
			(item) => item.id === workspacePackage.product_id,
		);
		if (matched) setSelectedProduct(matched);
	}, [products, workspacePackage]);

	useEffect(() => {
		if (!workspacePackage) return;
		if (workspacePackage.generation_mode) {
			setGenerationMode(workspacePackage.generation_mode);
		}
		if (workspacePackage.target_language) {
			setTargetLanguage(workspacePackage.target_language);
		}
		if (workspacePackage.camera_style) {
			setCameraStyle(workspacePackage.camera_style);
		}
		if (workspacePackage.character_presence) {
			setCharacterPresence(workspacePackage.character_presence);
		}
		if (workspacePackage.generation_mode === "EXTEND") {
			const total = workspacePackage.total_duration_seconds;
			setRequestedTotalDuration(
				total && OPERATOR_EXTEND_PLAN_BY_TOTAL[total] ? total : null,
			);
		} else {
			setRequestedTotalDuration(null);
			if (workspacePackage.prompt_blocks?.[0]?.duration_seconds) {
				setVideoDurationSeconds(
					workspacePackage.prompt_blocks[0].duration_seconds,
				);
			}
			if (workspacePackage.model) {
				// Hydrate the operator's model from the saved tuple WITHOUT
				// normalizing — an unsupported legacy combination must surface a
				// recompile warning (see legacyPackageWarning below), not be silently
				// repaired into a different model.
				setVideoModel(workspacePackage.model);
			}
		}
	}, [workspacePackage]);

	useEffect(() => {
		if (selectedProduct || workspacePackage || products.length === 0) return;
		const readyProduct = products.find(
			(item) => packageReadiness[item.id]?.readiness_status === "READY",
		);
		if (readyProduct) {
			setSelectedProduct(readyProduct);
		}
	}, [packageReadiness, products, selectedProduct, workspacePackage]);

	useEffect(() => {
		setCompactPane("workspace");
	}, []);

	useEffect(() => {
		return () => {
			if (pollTimerRef.current != null) {
				window.clearTimeout(pollTimerRef.current);
			}
		};
	}, []);

	// Canonical engine → model → SINGLE-duration capability authority. Every
	// Step-1 engine/model/duration option is derived from this one payload; the
	// operator UI keeps no parallel hard-coded list. selectedEngineId / videoModel
	// are the page-owned SINGLE selection (model was previously split across the
	// mode modules — that split-brain is removed).
	const [capabilityMatrix, setCapabilityMatrix] =
		useState<VideoCapabilityMatrix | null>(null);
	const [selectedEngineId, setSelectedEngineId] =
		useState<string>("GOOGLE_FLOW");
	const [videoModel, setVideoModel] = useState<string>("Veo 3.1 - Lite");
	const [modelAdjustmentNote, setModelAdjustmentNote] = useState<string | null>(
		null,
	);
	useEffect(() => {
		fetchAPI<VideoCapabilityMatrix>("/api/flow/video-capability-matrix")
			.then((matrix) => {
				if (!matrix || !Array.isArray(matrix.engines)) return;
				setCapabilityMatrix(matrix);
				const engine = pickDefaultEngine(matrix);
				if (!engine) return;
				setSelectedEngineId(engine.id);
				const sel = resolveSingleSelection(
					engine,
					null,
					engine.default_single_duration,
				);
				if (sel) {
					setVideoModel(sel.model);
					setVideoDurationSeconds(sel.durationSeconds);
				}
			})
			.catch(() => {});
	}, []);

	useEffect(() => {
		if (!isPortalMode) {
			setModeRequests([]);
			return;
		}

		let inFlight = false;
		// Telemetry rows are keyed by the backend job boundary mode (the HYBRID
		// surface runs F2V jobs), so the embedded-route sync reports that mode.
		const mode = jobMode;
		const loadModeRequests = () => {
			if (document.hidden || inFlight) {
				return;
			}
			inFlight = true;
			void fetchAPI<TelemetryRequest[]>(
				`/api/telemetry/requests?limit=60&request_type=MANUAL_FLOW_JOB&mode=${encodeURIComponent(mode)}`,
			)
				.then(setModeRequests)
				.catch(() => {})
				.finally(() => {
					inFlight = false;
				});
		};
		const handleVisibilityChange = () => {
			if (!document.hidden) {
				loadModeRequests();
			}
		};

		loadModeRequests();
		document.addEventListener("visibilitychange", handleVisibilityChange);
		const timer = window.setInterval(loadModeRequests, 15000);
		return () => {
			document.removeEventListener("visibilitychange", handleVisibilityChange);
			window.clearInterval(timer);
		};
	}, [isPortalMode, jobMode]);

	// IMG now flows through the SAME unified one-door /generate (mode:"IMG") + pollJob as the
	// video lanes — it saves to disk and returns a job (the legacy /generate-image-oneshot
	// endpoint is kept server-side but no longer called from the dashboard).
	const handleExecute = async (data: WorkspaceExecutePayload) => {
		if (backendRuntimeStale) {
			setNotice({
				tone: "warning",
				title: "Backend needs restart",
				detail:
					"Production is locked because the local backend is stale. Restart the local agent, then refresh the version check above.",
				requestId: null,
			});
			return;
		}
		if (executionInFlightRef.current) {
			console.log("[BOSMAX_DEBUG] DUPLICATE_EXECUTION_BLOCKED");
			return;
		}
		executionInFlightRef.current = true;
		setIsExecuting(true);
		setCompletedArtifact(null);
		console.log(
			"[BOSMAX_DEBUG] OPERATOR_EXECUTE_PAYLOAD",
			JSON.stringify(data, null, 2),
		);
		if (pollTimerRef.current != null) {
			window.clearTimeout(pollTimerRef.current);
			pollTimerRef.current = null;
		}

		const requestId = `manual_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
		setNotice({
			tone: "info",
			title: "Submitting to Flow",
			detail: "Request accepted. Runtime lane selection in progress.",
			requestId,
		});

		const pollJob = async (jobId: string) => {
			try {
				const response = await fetch(`/api/flow/generate-job/${jobId}`);
				if (!response.ok) {
					throw new Error(`Job HTTP ${response.status}`);
				}
				const job = await response.json();
				const status = job.status as string;

				if (status === "DONE") {
					const mediaId = job.media_id ?? job.video_media_id ?? "";
					// Surface the post-approve verification truth (Layer A). Handle BOTH result
					// shapes surgically: the generate-job lane carries the flags on top-level
					// job fields; the negotiate-job dry lane carries them under job.result.*.
					const r = job.result ?? {};
					const unverified = Boolean(
						job.model_unverified ||
							job.duration_unverified ||
							r.model_unverified ||
							r.duration_unverified ||
							job.model_ok === false ||
							job.duration_ok === false ||
							r.model_ok === false ||
							r.duration_ok === false,
					);
					const verifyNote = unverified
						? " — ⚠ verification: model/duration UNVERIFIED"
						: "";
					// IMG artifacts open in a new tab for a quick preview (one-door save still happens).
					if (job.artifact === "image" && job.url) {
						window.open(job.url, "_blank", "noopener");
					}
					if (mediaId) {
						setCompletedArtifact({
							mediaId,
							url: `/api/flow/retrieved/${mediaId}`,
							kind: job.artifact === "image" ? "image" : "video",
							sizeMb: job.size_mb != null ? String(job.size_mb) : null,
						});
						setSessionResults((prev) => [
							{
								media_id: mediaId,
								kind: job.artifact === "image" ? "image" : "video",
								size_mb: job.size_mb ?? null,
							},
							...prev.filter((r) => r.media_id !== mediaId),
						]);
					}
					setNotice({
						tone: "success",
						title: `${data.mode} done — saved`,
						detail: `Saved ${job.size_mb ?? "?"}MB → ${job.local_path} (media ${mediaId})${verifyNote}`,
						requestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}
				if (
					[
						"FAILED",
						"REJECTED",
						"RENDER_NOT_MATERIALIZED",
						"STALE_OR_FOREIGN_CANDIDATES_ONLY",
					].includes(status)
				) {
					setNotice({
						tone: "error",
						title: `${noticeModeLabel(mode, data.mode)} failed`,
						detail: job.error || job.original_error || status,
						requestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}
				// Terminal: the video was generated in Flow but the local harvest failed. NOT a
				// clean success (no local file) and NOT a plain generation failure — and it must
				// NOT auto-retry. Surface the recovery fields so the user can recover manually.
				if (status === "GENERATED_BUT_UNRETRIEVED") {
					setNotice({
						tone: "warning",
						title: `${noticeModeLabel(mode, data.mode)} generated in Flow — local retrieval failed`,
						detail:
							"Generated in Flow, but local retrieval failed. Manual recovery/download required." +
							(job.credit_spent_likely ? " A credit was likely spent." : "") +
							(job.recovery_hint ? ` ${job.recovery_hint}.` : "") +
							(job.original_error ? ` [${job.original_error}]` : ""),
						requestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}

				setNotice({
					tone: "info",
					title: `${mode} running`,
					detail: `Stage: ${job.stage ?? status}`,
					requestId,
				});
				pollTimerRef.current = window.setTimeout(() => {
					void pollJob(jobId);
				}, 3000);
			} catch (error: unknown) {
				const message =
					error instanceof Error ? error.message : "Failed to read job status.";
				setNotice({
					tone: "error",
					title: "Job status unavailable",
					detail: message,
					requestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
			}
		};

		const pollManualFlowRequest = async (manualRequestId: string) => {
			try {
				const response = await fetch(
					`/api/telemetry/requests/${encodeURIComponent(manualRequestId)}`,
				);
				if (response.status === 404) {
					pollTimerRef.current = window.setTimeout(() => {
						void pollManualFlowRequest(manualRequestId);
					}, 1500);
					return;
				}
				if (!response.ok) {
					throw new Error(`Telemetry HTTP ${response.status}`);
				}
				const detail = (await response.json()) as TelemetryRequestDetail;
				const telemetry = detail.telemetry;
				const stages = Array.isArray(detail.stages) ? detail.stages : [];
				const latestStage = stages.length ? stages[stages.length - 1] : null;
				const status = String(
					telemetry?.status || "WAITING_FLOW",
				).toUpperCase();
				const stageLabel =
					latestStage?.stage ||
					telemetry?.extension_stage ||
					telemetry?.google_flow_stage ||
					status;
				const stageMessage =
					latestStage?.message ||
					telemetry?.error_message ||
					"Waiting for extension telemetry.";

				if (status === "COMPLETED") {
					// The API lane's COMPLETED stage carries "media_id=<uuid> size_mb=<n>" —
					// surface the finished video inline so the operator sees it HERE, now.
					const completedStage = stages.find(
						(s) => String(s?.stage || "") === "COMPLETED",
					);
					const completedMsg = String(
						completedStage?.message || stageMessage || "",
					);
					const mediaMatch = completedMsg.match(
						/media_id=([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})/,
					);
					const allMediaMatch = completedMsg.match(
						/all_media_ids=([0-9a-fA-F-]+(?:,[0-9a-fA-F-]+)*)/,
					);
					const sizeMatch = completedMsg.match(/size_mb=([\d.]+)/);
					const mediaIds = Array.from(
						new Set(
							[
								...(allMediaMatch?.[1]?.split(",") ?? []),
								...(mediaMatch ? [mediaMatch[1]] : []),
							].filter((id) => /^[0-9a-fA-F-]{20,}$/.test(id)),
						),
					);
					const primaryMediaId = mediaIds[0] || mediaMatch?.[1] || "";
					if (primaryMediaId) {
						setCompletedArtifact({
							mediaId: primaryMediaId,
							url: `/api/flow/retrieved/${primaryMediaId}`,
							kind: "video",
							sizeMb: sizeMatch ? sizeMatch[1] : null,
						});
						setSessionResults((prev) => [
							...mediaIds.map((media_id) => ({
								media_id,
								kind: "video" as const,
								size_mb: media_id === primaryMediaId && sizeMatch
									? Number(sizeMatch[1])
									: null,
								url: `/api/flow/retrieved/${encodeURIComponent(media_id)}`,
							})),
							...prev.filter((r) => !mediaIds.includes(r.media_id)),
						]);
					}
					setNotice({
						tone: "success",
						title: `${data.mode} SIAP ✓ — video ready`,
						detail: `${stageLabel}${stageMessage ? ` — ${stageMessage}` : ""}`,
						requestId: manualRequestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}

				if (status === "FAILED") {
					setNotice({
						tone: "error",
						title: `${noticeModeLabel(mode, data.mode)} failed`,
						detail:
							telemetry?.error_message ||
							stageMessage ||
							"Manual Flow job failed.",
						requestId: manualRequestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}

				setNotice({
					tone: "info",
					title: `${mode} running — video is generating (±3–8 min), keep this page open`,
					detail: `Stage: ${stageLabel}${stageMessage ? ` — ${stageMessage}` : ""} · Note: nothing moves in the Google Flow tab — generation runs via API and the video appears here when it's ready.`,
					requestId: manualRequestId,
				});
				pollTimerRef.current = window.setTimeout(() => {
					void pollManualFlowRequest(manualRequestId);
				}, 3000);
			} catch (error: unknown) {
				const message =
					error instanceof Error
						? error.message
						: "Failed to read manual Flow job status.";
				setNotice({
					tone: "error",
					title: "Manual Flow status unavailable",
					detail: message,
					requestId: manualRequestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
			}
		};

		// F2V sends the Start/End frame as startAsset/endAsset; I2V/T2V use refs.*. Include ALL
		// of them so the one-door /generate always receives the reference image as
		// image_media_ids — otherwise F2V submits with an empty image and the backend rejects it
		// ("F2V needs a reference image").
		const refs = [
			data.startAsset?.mediaId,
			data.endAsset?.mediaId,
			data.refs?.subjectAsset?.mediaId,
			data.refs?.sceneAsset?.mediaId,
			data.refs?.styleAsset?.mediaId,
		].filter(Boolean) as string[];
		// The modules send `orientation` (VERTICAL/HORIZONTAL), not `aspectRatio`. Honour
		// aspectRatio if present, else fall back to orientation — otherwise HORIZONTAL was
		// silently dropped and every video came out 9:16.
		const aspect =
			data.aspectRatio === "16:9" || data.orientation === "HORIZONTAL"
				? "16:9"
				: "9:16";
		const isGfv2RuntimeLane =
			data.mode === "F2V" &&
			(data.gfv2 === true ||
				data.lane === "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE" ||
				data.upload_only === true);
		const isWorkspaceRuntimeLane =
			data.lane === "WORKSPACE_FLOW_EDITOR_RUNTIME";

		try {
			if (isGfv2RuntimeLane || isWorkspaceRuntimeLane) {
				const response = await fetch("/api/flow/execute-flow-job", {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						...data,
						request_id: requestId,
						aspectRatio: data.aspectRatio || aspect,
					}),
				});

				if (!response.ok) {
					const err = await response.json().catch(() => ({}));
					throw new Error(err.detail || `HTTP ${response.status}`);
				}

				await response.json();
				setNotice({
					tone: "info",
					title: `${data.mode} accepted`,
					detail: isGfv2RuntimeLane
						? `Manual Flow job ${requestId} submitted via GFV2 runtime lane.`
						: `Manual Flow job ${requestId} submitted via workspace runtime lane.`,
					requestId,
				});
				void pollManualFlowRequest(requestId);
				return;
			}
			// Unified one-door pipeline: agent → render → save (replaces the dead
			// execute-flow-job DOM automation against the retired Video/Frames UI).
			const response = await fetch("/api/flow/generate", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					mode: data.mode,
					prompt: data.prompt,
					product_id: data.product_id,
					visual_lane_id:
						data.mode === "IMG"
							? data.visual_lane_id ?? data.lane
							: undefined,
					source_mode: data.source_mode ?? resolveSourceMode(mode),
					image_media_ids: refs,
					// Forward resolvable asset OBJECTS (Faceless parity) so the backend
					// resolver can upload/materialize references that carry transport
					// (local/preview/download) but no live media_id yet.
					startAsset: data.startAsset,
					refs: data.refs,
					aspect,
					model: data.mode === "IMG" ? data.model : videoModel,
					// IMG image model (Nano Banana …) — separate from the video `model`.
					image_model: data.image_model,
					// Operator's EXPLICIT SINGLE video duration — NOT the model
					// default. This exact value is the parity anchor the compiler,
					// package, runtime request and extension payload must all match.
					// IMG carries no video duration (must not inherit video controls).
					duration_s: data.mode === "IMG" ? undefined : videoDurationSeconds,
					engine: data.mode === "IMG" ? undefined : selectedEngineId,
					generation_mode: data.mode === "IMG" ? undefined : generationMode,
					capability_matrix_version:
						data.mode === "IMG"
							? undefined
							: capabilityMatrix?.capability_matrix_version,
				}),
			});

			if (!response.ok) {
				const err = await response.json().catch(() => ({}));
				if (
					response.status === 409 &&
					err.detail === "VIDEO_JOB_IN_FLIGHT" &&
					err.active_job
				) {
					setNotice({
						tone: "info",
						title: "Existing video job resumed",
						detail: `The shared Flow lane is already running ${err.active_job}. This page is now following that job instead of submitting another paid generation.`,
						requestId,
					});
					void pollJob(String(err.active_job));
					return;
				}
				throw new Error(
					typeof err.detail === "string"
						? err.detail
						: err.error || `HTTP ${response.status}`,
				);
			}

			const result = await response.json();
			if (!result.job_id) {
				throw new Error("no job_id returned");
			}
			setNotice({
				tone: "info",
				title: `${data.mode} accepted`,
				detail: `Job ${result.job_id} started — agent → render → save.`,
				requestId,
			});
			void pollJob(result.job_id);
		} catch (error: unknown) {
			const message =
				error instanceof Error ? error.message : "Execution failed.";
			console.error("Execution error:", error);
			setNotice({
				tone: "error",
				title: "Execution error",
				detail: message,
				requestId,
			});
			setIsExecuting(false);
			executionInFlightRef.current = false;
		}
	};

	const clearDurationAuthorityArtifacts = () => {
		setPreviewPackage(null);
		setWorkspacePackage(null);
		setSavedGenPackage(null);
		setSavePackageError(null);
	};

	const handleGenerationModeChange = (
		nextGenerationMode: PromptGenerationMode,
	) => {
		const transition = transitionOperatorDurationAuthority(
			{
				generationMode,
				extendTotalDurationSeconds: requestedTotalDuration,
			},
			nextGenerationMode,
		);
		setGenerationMode(transition.generationMode);
		setRequestedTotalDuration(transition.extendTotalDurationSeconds);
		if (transition.clearCompiledArtifacts) {
			clearDurationAuthorityArtifacts();
		}
	};

	const handleExtendTotalDurationChange = (nextTotal: number | null) => {
		setRequestedTotalDuration(nextTotal);
		clearDurationAuthorityArtifacts();
	};

	// ENGINE change: resolve a valid (duration, model) for the new engine, clear
	// any incompatible model/duration + stale compiled artifacts.
	const handleEngineChange = (nextEngineId: string) => {
		setSelectedEngineId(nextEngineId);
		const engine = getEngine(capabilityMatrix, nextEngineId);
		const sel = resolveSingleSelection(
			engine,
			videoModel,
			videoDurationSeconds,
		);
		if (sel) {
			setVideoModel(sel.model);
			setVideoDurationSeconds(sel.durationSeconds);
			setModelAdjustmentNote(sel.adjusted ? sel.adjustmentReason : null);
		} else {
			setModelAdjustmentNote(null);
		}
		clearDurationAuthorityArtifacts();
	};

	// MODEL change: explicit operator choice — never overwrite it downstream.
	const handleVideoModelChange = (nextModel: string) => {
		setVideoModel(nextModel);
		setModelAdjustmentNote(null);
		clearDurationAuthorityArtifacts();
		// Snap the single-clip duration to the model's registry default (Veo 3.1
		// Lite → 8s, Omni Flash → 10s) so the per-model single target holds. The
		// operator may still pick another allowed duration afterwards.
		const engine = getEngine(capabilityMatrix, selectedEngineId);
		const modelDefault = engine?.models.find(
			(m) => m.ui_label === nextModel || m.key === nextModel,
		)?.default_duration_s;
		if (modelDefault && modelDefault !== videoDurationSeconds) {
			setVideoDurationSeconds(modelDefault);
		}
	};

	// DURATION change (SINGLE): filter models to the new duration; if the current
	// model is now incompatible pick the deterministic compatible default.
	const handleSingleDurationChange = (nextDuration: number) => {
		const engine = getEngine(capabilityMatrix, selectedEngineId);
		const sel = resolveDurationChange(engine, videoModel, nextDuration);
		setVideoDurationSeconds(nextDuration);
		if (sel) {
			setVideoModel(sel.model);
			setModelAdjustmentNote(sel.adjusted ? sel.adjustmentReason : null);
		} else {
			setModelAdjustmentNote(null);
		}
		clearDurationAuthorityArtifacts();
	};

	const handleSaveGenerationPackage = useCallback(async () => {
		if (backendRuntimeStale) {
			setSavePackageError("BACKEND_RESTART_REQUIRED");
			return;
		}
		if (!selectedProduct || !workspacePackage) return;
		if (!durationAuthority) {
			setSavePackageError("EXTEND_TOTAL_DURATION_REQUIRED");
			return;
		}
		if (selectedProduct.reference_only) {
			setSavePackageError(
				"REFERENCE_ONLY_PRODUCT — Convert/Register this product via Smart Registration before saving a generation package.",
			);
			return;
		}
		setIsSavingPackage(true);
		setSavePackageError(null);
		setSavedGenPackage(null);
		try {
			let pkg: WorkspaceGenerationPackage;
			if (mode === "HYBRID" || mode === "F2V") {
				pkg = await createF2VGenerationPackage({
					product_id: selectedProduct.id,
					workspace_execution_package_id:
						workspacePackage.workspace_execution_package_id,
					source_mode: resolveSourceMode(mode) as "HYBRID" | "FRAMES",
					...durationAuthority.payload,
					target_language: targetLanguage,
					camera_style: cameraStyle,
					character_presence: characterPresence,
					overlay_enabled: false, // NO_OVERLAY law (ADR-008): default off
					dialogue_enabled: true,
				});
			} else if (mode === "I2V") {
				pkg = await createI2VGenerationPackage({
					product_id: selectedProduct.id,
					workspace_execution_package_id:
						workspacePackage.workspace_execution_package_id,
					...durationAuthority.payload,
					target_language: targetLanguage,
					camera_style: cameraStyle,
					character_presence: characterPresence,
				});
			} else {
				throw new Error(
					`Generate / Save Package not supported for mode ${mode} yet.`,
				);
			}
			setSavedGenPackage(pkg);
		} catch (e) {
			setSavePackageError(String(e));
		} finally {
			setIsSavingPackage(false);
		}
	}, [
		selectedProduct,
		workspacePackage,
		mode,
		durationAuthority,
		targetLanguage,
		cameraStyle,
		characterPresence,
		backendRuntimeStale,
	]);

	// Step 3 — Load Package Preview (compile only, no DB save)
	const handleLoadPreview = async () => {
		if (backendRuntimeStale) {
			setNotice({
				tone: "warning",
				title: "Backend needs restart",
				detail:
					"Package loading is locked because the local backend is stale. Restart the local agent, then refresh the version check above.",
				requestId: null,
			});
			return;
		}
		if (!durationAuthority) {
			setNotice({
				tone: "warning",
				title: "Total Video Duration required",
				detail:
					"EXTEND compiles only from one authorized Total Video Duration. Select a total to derive the route and block plan.",
				requestId: null,
			});
			return;
		}
		if (!selectedProduct || selectedReadiness?.readiness_status !== "READY") {
			const blocker =
				selectedReadiness?.blocker ??
				selectedReadiness?.readiness_status ??
				null;
			setNotice({
				tone: "error",
				title: "Package not ready",
				detail: blockerMessage(blocker, mode as WorkspaceMode),
				requestId: null,
			});
			return;
		}
		const previewBindingBlocker = referenceBindingBlocker(
			mode,
			referenceBinding,
		);
		if (previewBindingBlocker) {
			setNotice({
				tone: "error",
				title: "Reference binding required",
				detail: previewBindingBlocker,
				requestId: null,
			});
			return;
		}
		setIsLoadingPreview(true);
		setPreviewPackage(null);
		setWorkspacePackage(null);
		try {
			const preview = await compileWorkspacePromptPreview({
				product_id: selectedProduct.id,
				mode: jobMode,
				source_mode: resolveSourceMode(mode),
				copy_set_id: selectedCopySetId,
				...durationAuthority.payload,
				target_language: targetLanguage,
				camera_style: cameraStyle,
				character_presence: characterPresence,
				avatar_id: registryAvatarId || null,
				scene_context_override: selectedSceneBackground || null,
			});
			setPreviewPackage(preview);
			setNotice({
				tone: "success",
				title: `${mode} Package Loaded`,
				detail: `Approved package compiled for ${selectedProduct.product_display_name}. Review the prompt preview then press Generate.`,
				requestId: null,
			});
		} catch (error: unknown) {
			const blocker = parseWorkspaceBlocker(error);
			const message = blocker
				? blockerMessage(blocker, mode as WorkspaceMode)
				: error instanceof Error
					? error.message
					: "Failed to load package.";
			setNotice({
				tone: "error",
				title: "Package load failed",
				detail: message,
				requestId: null,
			});
		} finally {
			setIsLoadingPreview(false);
		}
	};

	// Step 4 — Generate Final Prompt (compile + save to DB).
	// The backend rechecks the selected Copy Set's production validity.
	const runGeneratePackage = async () => {
		if (backendRuntimeStale) {
			setNotice({
				tone: "warning",
				title: "Backend needs restart",
				detail:
					"Final prompt generation is locked because the local backend is stale. Restart the local agent, then refresh the version check above.",
				requestId: null,
			});
			return;
		}
		if (!selectedProduct || !previewPackage) return;
		if (!durationAuthority) {
			setNotice({
				tone: "warning",
				title: "Total Video Duration required",
				detail:
					"EXTEND cannot generate from stale manual duration state. Select one Total Video Duration first.",
				requestId: null,
			});
			return;
		}
		const persistBindingBlocker = referenceBindingBlocker(
			mode,
			referenceBinding,
		);
		if (persistBindingBlocker) {
			setNotice({
				tone: "error",
				title: "Reference binding required",
				detail: persistBindingBlocker,
				requestId: null,
			});
			return;
		}
		setIsLoadingPackage(true);
		try {
			const pkg = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode: jobMode,
				source_mode: resolveSourceMode(mode),
				copy_set_id: selectedCopySetId,
				// Record the operator-selected video model on the package so the
				// runtime + reload use the same tuple (was previously unset → "").
				model: videoModel,
				...durationAuthority.payload,
				target_language: targetLanguage,
				camera_style: cameraStyle,
				character_presence: characterPresence,
				avatar_id: registryAvatarId || null,
				scene_context_override: selectedSceneBackground || null,
				scene_context_code: registrySceneCode || null,
				// Recipe descriptors (Step F): the primary selected recipe's scene template
				// + camera preset so the compiled prompt uses the coherent combination.
				// Only T2V populates recipes; other modes send null (compiler unchanged).
				scene_template_id: creativeDirection.recipes[0]?.scene_template_id ?? null,
				camera_preset_code: creativeDirection.recipes[0]?.camera_preset_code ?? null,
				// Per-mode reference payload hygiene: only the selected mode's
				// binding fields are ever sent — a stale pick from another mode
				// must never reach the server-side binding contract.
				product_reference_asset_id:
					mode === "HYBRID" ? referenceBinding.productReferenceAssetId : null,
				start_frame_asset_id:
					mode === "F2V" ? referenceBinding.startFrameAssetId : null,
				end_frame_asset_id:
					mode === "F2V" ? referenceBinding.endFrameAssetId : null,
				character_reference_asset_id:
					mode === "I2V" ? referenceBinding.characterReferenceAssetId : null,
				scene_context_reference_asset_id:
					mode === "I2V"
						? referenceBinding.sceneContextReferenceAssetId
						: null,
				style_reference_asset_id:
					mode === "I2V" ? referenceBinding.styleReferenceAssetId : null,
			});
			setWorkspacePackage(pkg);
			setPreviewPackage(null);
			setNotice({
				tone: "success",
				title: "Final Prompt Generated",
				detail:
					mode === "F2V"
						? `Workspace now uses compiled ${generationMode} ${mode} prompt from product truth.`
						: `Workspace now uses locked ${mode} payload from product truth.`,
				requestId: pkg.workspace_execution_package_id,
			});
		} catch (error: unknown) {
			const blocker = parseWorkspaceBlocker(error);
			const message = blocker
				? blockerMessage(blocker, mode as WorkspaceMode)
				: error instanceof Error
					? error.message
					: "Failed to generate final prompt.";
			setNotice({
				tone: "error",
				title: "Generation failed",
				detail: message,
				requestId: null,
			});
		} finally {
			setIsLoadingPackage(false);
		}
	};

	// Click handler: final prompt generation requires a selected production-valid
	// approved Copy Set. The backend repeats the same fail-closed check.
	const handleGeneratePackage = () => {
		if (extendTotalRequired) {
			setNotice({
				tone: "warning",
				title: "Total Video Duration required",
				detail:
					"Production EXTEND requires one Total Video Duration. The route and block plan are derived automatically.",
				requestId: null,
			});
			return;
		}
		if (!selectedCopySetId) {
			setNotice({
				tone: "warning",
				title: "Production-valid Copy Set required",
				detail:
					"Select a currently production-valid approved Copy Set in Copy Selection. Revalidate or submit semantic review there when the set is blocked.",
				requestId: null,
			});
			return;
		}
		void runGeneratePackage();
	};

	const allowedDurations = promptConfig?.allowed_block_durations_seconds ?? [
		6, 8, 10, 12, 15, 20, 25,
	];
	// SINGLE duration + model options come from the capability matrix (operator
	// policy ∩ model). EXTEND is untouched (route/block-plan authority). Until the
	// matrix loads, fall back to the compiler-config list so the control still
	// renders.
	const currentEngine = getEngine(capabilityMatrix, selectedEngineId);
	const engineSingleDurations = singleDurations(currentEngine);
	const singleDurationOptions =
		engineSingleDurations.length > 0 ? engineSingleDurations : allowedDurations;
	const singleModelOptions = modelsForSingle(
		currentEngine,
		videoDurationSeconds,
	);
	// EXTEND keeps all engine models (route/block authority owns durations);
	// SINGLE is filtered to the operator-policy ∩ model duration.
	const modelSelectOptions = isExtendMode
		? (currentEngine?.models ?? [])
		: singleModelOptions;
	const engineHelperText = currentEngine
		? `Single video supports ${engineSingleDurations
				.map((d) => `${d}s`)
				.join(" or ")}.`
		: null;
	// A SINGLE tuple is valid only when the selected model is offered for the
	// selected engine+duration. A loaded legacy package with an unsupported
	// combination surfaces a recompile warning rather than being normalized.
	const singleModelValid =
		!currentEngine ||
		isExtendMode ||
		singleModelOptions.some((m) => m.ui_label === videoModel);
	const legacyPackageWarning =
		workspacePackage && !isExtendMode && !singleModelValid
			? "This package contains an unsupported engine/model/duration combination and must be recompiled."
			: null;
	const languageOptions = Object.keys(
		promptConfig?.language_wps_policy ?? {
			BM_MS: {},
			EN_US: {},
		},
	) as PromptTargetLanguage[];
	const videoShotPolicy =
		promptConfig?.shot_count_policy[String(videoDurationSeconds)] ?? null;
	const extendAuthority =
		durationAuthority?.generationMode === "EXTEND" ? durationAuthority : null;
	const extendTotalOptions = Object.keys(OPERATOR_EXTEND_PLAN_BY_TOTAL).map(
		Number,
	);
	const automaticWps =
		promptConfig?.language_wps_policy[targetLanguage]?.body_wps ?? null;
	const packageBridgeFlowLabelByMode: Record<WorkspaceMode, string> = {
		T2V: "Load T2V Package + Generate Final Prompt",
		HYBRID: "Load HYBRID Package + Generate Final Prompt",
		F2V: "Load FRAMES Package + Generate Final Prompt",
		I2V: "Load I2V Package + Generate Final Prompt",
		IMG: "Load IMG Package + Generate Final Prompt",
	};
	const loadPackageLabel = previewPackage
		? `Reload ${mode} Package`
		: `Load ${mode} Package`;
	const generatePromptLabel = workspacePackage
		? "Regenerate Final Prompt"
		: "Generate Final Prompt";

	const renderModule = () => {
		if (mode !== "IMG") {
			// Canonical video production has one user control: the durable full-video
			// panel rendered above for an authorised EXTEND plan. The retired workspace
			// modules only insert prompts into Google Flow, which is a fail-closed DOM
			// lane and must never be exposed as a normal production action.
			return isExtendMode ? (
				<div
					data-testid="canonical-video-production-control"
					className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 px-3 py-2 text-xs text-slate-300"
				>
					Use the Full Video control above to plan and generate this canonical
					{` ${mode}`} production job.
				</div>
			) : (
				<div
					data-testid="canonical-video-production-requires-extend"
					className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-100"
				>
					Canonical video production requires EXTEND with an authorised total
					duration. Select EXTEND above to use the server-owned durable video
					job.
				</div>
			);
		}

		switch (mode) {
			case "IMG":
				return (
					<IMGModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
						previewPackage={previewPackage}
						selectedProduct={selectedProduct}
					/>
				);
			default:
				return (
					<div className="p-8 text-slate-400">
						Please select a workspace module from the sidebar.
					</div>
				);
		}
	};

	// ── V4 guided single-page shell (T2V reference + Bucket-1 lanes) ───────────
	if (
		useV4 &&
		(mode === "T2V" || mode === "F2V" || mode === "HYBRID" || mode === "I2V" || mode === "IMG")
	) {
		const isImageMode = mode === "IMG";
		const hasReferenceStep = !isImageMode && mode !== "T2V";
		const creativeStepIndex = hasReferenceStep ? 6 : 5;
		const storyboardStepIndex = hasReferenceStep ? 7 : 6;
		const generateStepIndex = hasReferenceStep ? 8 : 7;
		const laneTitle =
			mode === "T2V"
				? "Text to Video"
				: mode === "HYBRID"
					? "Hybrid"
					: mode === "F2V"
						? "Frames to Video"
						: mode === "I2V"
							? "Ingredients to Video"
							: "Image Generation";
		const laneDescription = isImageMode
			? "Choose a product or upload references, then shape the image before the operator gate."
			: "Pick a product, message and presenter — references and camera resolve by lane.";
		const productReady = selectedReadiness?.readiness_status === "READY";
		const registryV4Pool = filterRecipesToAvatarRegistry(
			v4Pool,
			avatarRegistryPool,
		);
		const v4Avatars = Array.from(
			new Set(registryV4Pool.map((r) => r.avatar_code)),
		).filter(Boolean);
		const primaryRecipe = creativeDirection.recipes[0] ?? null;
		// Single-select scene list for the chosen presenter (backend-configured
		// recipes only — nothing invented).
		const v4PresenterRecipes = registryAvatarId
			? registryV4Pool.filter((r) => r.avatar_code === registryAvatarId)
			: [];
		const applyV4Recipe = (recipe: CreativeRecipe) =>
			handleCreativeDirectionChange(
				buildCreativeDirectionFromRecipes([recipe]),
			);
		const avatarName = (code: string) =>
			avatarRegistryPool.find(
				(a) => avatarRegistryCode(a) === code,
			)?.character_name ||
			avatarRegistryPool.find((a) => avatarRegistryCode(a) === code)?.display_name ||
			code;
		const presenterLabel = registryAvatarId
			? `${avatarName(registryAvatarId)} ${v4GenderTag(registryAvatarId)}`.trim()
			: v4RecipesLoading
				? "Resolving…"
				: "Auto from knowledge base";
		const sceneCameraLabel = primaryRecipe
			? `${v4SceneText(primaryRecipe)} · 🎥 ${primaryRecipe.camera_preset_code || "—"}`
			: "Auto from knowledge base";
		const referenceBlocker = hasReferenceStep
			? referenceBindingBlocker(mode, referenceBinding)
			: null;
		const referenceLabel =
			mode === "F2V"
				? referenceBinding.startFrameAssetId
					? `Start frame bound${referenceBinding.endFrameAssetId ? " · end frame bound" : ""}`
					: "Start frame required"
				: mode === "I2V"
					? referenceBinding.characterReferenceAssetId &&
						referenceBinding.sceneContextReferenceAssetId
						? `Character + scene bound${referenceBinding.styleReferenceAssetId ? " · style bound" : ""}`
						: "Character + scene required"
					: "Product anchor auto · optional override";
		const lengthLabel = isExtendMode
			? `${requestedTotalDuration ?? "—"}s · Extended`
			: `${videoDurationSeconds}s · Single`;
		const copyBound = Boolean(selectedCopySetId);
		// APPROVED_COPY_STALE: approved copy exists for this product but none is
		// production-valid anymore (product truth moved on). Surface a direct
		// "fix copy" path to the product's Copy Registry so the operator can
		// revalidate before generating instead of silently shipping stale copy.
		const copyApprovedButStale =
			!!copyReadiness &&
			copyReadiness.copy_applicable !== false &&
			copyReadiness.approved_copy_set_count > 0 &&
			(copyReadiness.valid_approved_copy_set_count ?? 0) === 0;
		// SINGLE-clip generation: the compiled single-block prompt from the prepared
		// execution package. Fired through the LIVE one-door lane (/api/flow/generate),
		// the same proven lane IMG uses — NOT the retired DOM lane (ADR-007 compliant).
		const singleClipPrompt = workspacePackage?.prompt_text || "";
		// Single-clip reference bytes, resolved from the prepared package slots
		// (proven Faceless pattern) → operator-binding fallback → transport gate.
		// The backend /api/flow/generate resolver uploads assets that carry
		// transport (media_id / local / preview / download) but a bare asset_id
		// fails closed — so gating on real transport makes a broken fire impossible.
		const singleStartAsset =
			mode === "F2V" || mode === "HYBRID"
				? resolvedAssetToGenerateAsset(
						packageSlotResolvedAsset(workspacePackage, "start_frame"),
					) ||
					bindingFallbackGenerateAsset(
						referenceBinding.startFrameAssetId ||
							referenceBinding.productReferenceAssetId,
						"start_frame",
					)
				: null;
		const singleEndAsset =
			mode === "F2V"
				? resolvedAssetToGenerateAsset(
						packageSlotResolvedAsset(workspacePackage, "end_frame"),
					) ||
					bindingFallbackGenerateAsset(
						referenceBinding.endFrameAssetId,
						"end_frame",
					)
				: null;
		const singleSubjectAsset =
			mode === "I2V"
				? resolvedAssetToGenerateAsset(
						packageSlotResolvedAsset(workspacePackage, "subject"),
					) ||
					bindingFallbackGenerateAsset(
						referenceBinding.characterReferenceAssetId,
						"subject",
					)
				: null;
		const singleSceneAsset =
			mode === "I2V"
				? resolvedAssetToGenerateAsset(
						packageSlotResolvedAsset(workspacePackage, "scene"),
					) ||
					bindingFallbackGenerateAsset(
						referenceBinding.sceneContextReferenceAssetId,
						"scene",
					)
				: null;
		const singleStyleAsset =
			mode === "I2V"
				? resolvedAssetToGenerateAsset(
						packageSlotResolvedAsset(workspacePackage, "style"),
					) ||
					bindingFallbackGenerateAsset(
						referenceBinding.styleReferenceAssetId,
						"style",
					)
				: null;
		// Reference-required modes must have real transportable bytes, not just a
		// satisfied binding. HYBRID's product anchor lives in the start_frame slot.
		const singleClipRefsReady =
			mode === "T2V"
				? true
				: mode === "I2V"
					? generateAssetHasTransport(singleSubjectAsset) &&
						generateAssetHasTransport(singleSceneAsset)
					: generateAssetHasTransport(singleStartAsset);
		// HYBRID anchor = the product's official image, resolved server-side into
		// the start_frame slot. These booleans only drive reference-step copy and
		// the generate blocker text — they never gate or change dispatch.
		const hybridProductName =
			selectedProduct?.product_display_name || "this product";
		const hybridOfficialImageReady =
			hybridVisualReadiness?.visual_grounding_status ===
			"VISUAL_GROUNDING_READY";
		const hybridAnchorLocked =
			mode === "HYBRID" && generateAssetHasTransport(singleStartAsset);
		const storyboardShots = (previewPackage?.prompt_blocks ?? []).map(
			(block, i) => ({
				id: String(block.block_index ?? i),
				label: block.block_role
					? String(block.block_role)
					: `Block ${block.block_index ?? i + 1}`,
				sub: block.duration_seconds
					? `${block.duration_seconds}s`
					: undefined,
			}),
		);

		const s1: WorkflowStepStatus = selectedProduct
			? productReady
				? "done"
				: "active"
			: "active";
		const s2: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: copyBound
				? "done"
				: "active";
		const s3: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: registryAvatarId
				? "done"
				: "active";
		const s4: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: extendTotalRequired
				? "active"
				: "done";
		const s5: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: primaryRecipe
				? "done"
				: "active";
		const sReference: WorkflowStepStatus = !selectedProduct
			? "upcoming"
			: referenceBlocker
				? "active"
				: "done";
		const sStoryboard: WorkflowStepStatus = previewPackage ? "done" : "active";
		const sGenerate: WorkflowStepStatus =
			singleClipPrompt || (workspacePackage && extendAuthority)
				? "active"
				: "upcoming";

		const selectClass =
			"w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100";
		const labelClass =
			"text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500";

		return (
			<div
				data-testid="hybrid-workflow"
				data-variant="v4"
				data-mode={mode}
				className="flex h-full flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-6"
			>
				<div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
					<div>
						<div className="flex items-center gap-2">
							<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
								{laneTitle}
							</h2>
							<span className="rounded-full border border-v4-accent/40 bg-v4-accent/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-v4-accent-ink">
								V4
							</span>
						</div>
						<p className="text-sm text-slate-400">{laneDescription}</p>
					</div>
					<a
						href={`${location.pathname}?classic=1`}
						className="text-[11px] text-slate-500 underline decoration-dotted hover:text-slate-300"
					>
						Switch to classic view
					</a>
				</div>

				<div className="mb-4">
					<BackendVersionBanner onRuntimeStaleChange={setBackendRuntimeStale} />
				</div>
				{!isImageMode ? (
					<CopyArchitectureV2LaneCard
						lane={mode === "HYBRID" ? "HYBRID" : mode}
						productId={selectedProduct?.id}
						execution={workspacePackage?.copy_architecture_v2}
					/>
				) : null}

				<div className="flex min-h-0 flex-1 flex-col gap-5 lg:flex-row">
					<main className="min-w-0 space-y-3 pb-6 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:pr-1">
						{/* Step 1 — Product */}
						<WorkflowStep
							index={1}
							title="Product"
							status={s1}
							open={v4IsOpen(1, s1)}
							onToggleOpen={() => v4Toggle(1, v4IsOpen(1, s1))}
							summary={
								selectedProduct
									? `${selectedProduct.product_display_name}${productReady ? "" : " · not ready"}`
									: undefined
							}
							helper="Only READY products can generate."
						>
							<div className="space-y-3">
								<SearchableProductSelect
									products={products}
									selectedProduct={selectedProduct}
									onSelect={setSelectedProduct}
									readinessByProductId={packageReadiness}
									isLoadingReadiness={isLoadingAnyReadiness}
								/>
								{selectedReadiness && !productReady ? (
									<div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-100">
										{selectedReadiness.readiness_status} —{" "}
										{selectedReadiness.detail}
									</div>
								) : null}
							</div>
						</WorkflowStep>

						{isImageMode ? (
							<WorkflowStep
								index={2}
								title="Image setup"
								status="active"
								collapsible={false}
								helper="References, prompt and image settings stay together in the existing IMG lane."
							>
								<IMGModule
									onExecute={handleExecute}
									isExecuting={isExecuting}
									compact
									workspacePackage={workspacePackage}
									previewPackage={previewPackage}
									selectedProduct={selectedProduct}
								/>
							</WorkflowStep>
						) : (
							<>

						{/* Step 2 — Message & angle */}
						<WorkflowStep
							index={2}
							title="Message & angle"
							status={s2}
							open={v4IsOpen(2, s2)}
							onToggleOpen={() => v4Toggle(2, v4IsOpen(2, s2))}
							summary={copyBound ? "Production-valid copy set bound" : "Copy Set required"}
							helper="Bind a production-valid approved Copy Set before preparing the final video prompt."
						>
							<div className="space-y-3">
								<SceneStrategySummary
									hasProduct={Boolean(selectedProduct)}
									productName={selectedProduct?.product_display_name ?? null}
									taxonomy={selectedProduct?.strategy_taxonomy ?? null}
								/>
								<CopywritingReadinessCard
									readiness={copyReadiness}
									loading={copyReadinessLoading}
									onPrepare={() =>
										window.location.assign(
											selectedProduct
												? `/products?product_id=${encodeURIComponent(selectedProduct.id)}`
												: "/products",
										)
									}
									onOpenCopyRegistry={() =>
										window.location.assign(
											selectedProduct
												? `/creative/copy-registry?product_id=${encodeURIComponent(selectedProduct.id)}`
												: "/creative/copy-registry",
										)
									}
								/>
								{copyApprovedButStale ? (
									<button
										type="button"
										data-testid="copy-stale-fix-link"
										onClick={() =>
											window.location.assign(
												selectedProduct
													? `/creative/copy-registry?product_id=${encodeURIComponent(selectedProduct.id)}`
													: "/creative/copy-registry",
											)
										}
										className="inline-flex items-center gap-1 self-start rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-amber-100 transition-colors hover:bg-amber-500/20"
									>
										Fix copy for this product →
									</button>
								) : null}
								<CopySelectionPanel
									productId={selectedProduct?.id ?? null}
									productName={selectedProduct?.product_display_name ?? null}
									selectedCopySetId={selectedCopySetId}
									onSelect={setSelectedCopySetId}
									disabled={isLoadingPreview || isLoadingPackage}
								/>
							</div>
						</WorkflowStep>

						{/* Step 3 — Presenter */}
						<WorkflowStep
							index={3}
							title="Presenter"
							status={s3}
							open={v4IsOpen(3, s3)}
							onToggleOpen={() => v4Toggle(3, v4IsOpen(3, s3))}
							summary={presenterLabel}
							helper="The face in the video — auto-picked for the product; change it if you like."
						>
							<div className="space-y-2">
								<ResolvedChip
									label="Presenter"
									value={presenterLabel}
									icon="🎭"
									auto={!v4IsOpen(3, s3) || !registryAvatarId}
								/>
								<div
									data-testid="operator-presenter-source"
									className="text-[11px] text-cyan-200"
								>
									Avatar source: Avatar Registry
									{mode === "F2V"
										? " · F2V start/end slots remain frame references"
										: ""}
								</div>
								{mode === "HYBRID" ? (
									<div
										data-testid="operator-registry-authority"
										className="space-y-3 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-3"
									>
										<div>
											<div className="text-[10px] font-bold uppercase tracking-[0.16em] text-cyan-200">
												Registry authority
											</div>
											<p className="mt-1 text-[11px] text-slate-300">
												Hybrid keeps the approved Avatar Registry presenter and
												Scene Registry context together; the product image remains
												the automatic reference anchor.
											</p>
										</div>
										{registryPoolsLoading ? (
											<p className="text-[11px] text-slate-400">Loading registries…</p>
										) : null}
										{/* FASA 2c: avatar + scene are auto-picked from the product-type
										    mapping (the locks below). The override dropdowns are hidden
										    behind this Advanced disclosure so they read as mapped
										    defaults, not free-form picks. */}
										{registryAvatarId ? (
											<div className="text-[11px] text-cyan-100">
												Avatar lock: {registryAvatarId}
											</div>
										) : null}
										{registrySceneCode ? (
											<div className="text-[11px] text-cyan-100">
												Scene lock: {registrySceneCode}
											</div>
										) : null}
										<button
											type="button"
											data-testid="presenter-advanced-override-toggle"
											aria-expanded={showPresenterOverride}
											onClick={() => setShowPresenterOverride((v) => !v)}
											className="inline-flex items-center gap-1 self-start rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800/60"
										>
											{showPresenterOverride
												? "▾ Hide advanced"
												: "▸ Advanced — override presenter/scene"}
										</button>
										{showPresenterOverride ? (
											<>
										<label className="block space-y-1 text-xs text-slate-200">
											<span>Avatar registry</span>
											<select
												id="operator-avatar-registry"
												data-testid="operator-avatar-registry"
											value={registryAvatarId}
											onChange={(e) =>
												setRegistryAvatarId(
													resolveAvatarRegistryCode(e.target.value, avatarRegistryPool),
												)
											}
											className={selectClass}
											>
												<option value="">
													{avatarRegistryPool.length
														? "— product-seeded registry pick —"
														: "No avatar registry rows"}
												</option>
												{avatarRegistryPool.map((row) => {
													const code = String(
														row.avatar_code || row.AvatarCode || "",
													).trim();
													if (!code) return null;
													const label = avatarRegistryLabel(row);
													return (
														<option key={code} value={code}>
															{label} — {code}
														</option>
													);
												})}
											</select>
										</label>
										<VisualAssetPicker
											label="Avatar registry visual picker"
											value={registryAvatarId}
											onChange={(value) =>
												setRegistryAvatarId(
													resolveAvatarRegistryCode(value, avatarRegistryPool),
												)
											}
											items={avatarRegistryPool
												.map((row) => ({
													value: String(row.avatar_code || row.AvatarCode || ""),
													title: avatarRegistryLabel(row),
													subtitle: String(row.avatar_code || row.AvatarCode || ""),
													previewUrl: avatarRegistryPreviewUrl(
														row,
														registryPreviewUrls,
													),
													status: "APPROVED",
												}))
												.filter((row) => Boolean(row.value))}
										/>
										<label className="block space-y-1 text-xs text-slate-200">
											<span>Scene registry</span>
											<select
												id="operator-scene-registry"
												data-testid="operator-scene-registry"
												value={registrySceneCode}
												onChange={(e) => setRegistrySceneCode(e.target.value)}
												className={selectClass}
											>
												<option value="">
													{sceneRegistryPool.length
														? "— product package scene (no override) —"
														: "No scene registry rows"}
												</option>
												{sceneRegistryPool.map((row) => (
													<option key={row.scene_code} value={row.scene_code}>
														{row.scene_name || row.scene_code}
														{row.image_generated ? " · img" : ""}
													</option>
												))}
											</select>
										</label>
										<VisualAssetPicker
											label="Scene registry visual picker"
											value={registrySceneCode}
											onChange={setRegistrySceneCode}
											items={sceneRegistryPool.map((row) => ({
												value: row.scene_code,
												title: row.scene_name || row.scene_code,
												subtitle: row.scene_code,
												previewUrl:
													registryPreviewUrls[String(row.generated_asset_id || "")] || null,
												status: "APPROVED",
											}))}
										/>
										</>
										) : null}
									</div>
								) : v4RecipesLoading ? (
									<p className="text-[11px] text-slate-500">
										Resolving presenters…
									</p>
								) : v4Avatars.length ? (
									<div className="flex flex-wrap gap-2">
										{v4Avatars.map((code) => {
											const active = code === registryAvatarId;
											return (
												<button
													key={code}
													type="button"
													onClick={() =>
														applyV4Presenter(code, v4Pool, v4Pretick)
													}
													className={`rounded-xl border px-3 py-2 text-[11px] font-semibold transition-colors ${active ? "border-v4-accent bg-v4-accent/10 text-v4-accent-ink" : "border-slate-700 text-slate-300 hover:border-slate-500"}`}
												>
													{v4GenderTag(code)} {avatarName(code)}
												</button>
											);
										})}
									</div>
								) : (
									<p className="text-[11px] text-slate-500">
										Select a product to load presenters.
									</p>
								)}
							</div>
						</WorkflowStep>

						{/* Step 4 — Length */}
						<WorkflowStep
							index={4}
							title="Length"
							status={s4}
							open={v4IsOpen(4, s4)}
							onToggleOpen={() => v4Toggle(4, v4IsOpen(4, s4))}
							summary={lengthLabel}
							helper="How long the video runs."
						>
							<div className="space-y-3">
								<div className="grid gap-3 sm:grid-cols-2">
									<label className="space-y-1">
										<span className={labelClass}>Type</span>
										<select
											value={generationMode}
											onChange={(e) =>
												handleGenerationModeChange(
													e.target.value as PromptGenerationMode,
												)
											}
											className={selectClass}
											title="Generation type"
										>
											<option value="SINGLE">Single clip</option>
											<option value="EXTEND">Extended video</option>
										</select>
									</label>
									{isExtendMode ? (
										<label className="space-y-1">
											<span className={labelClass}>Total duration</span>
											<select
												value={
													requestedTotalDuration === null
														? ""
														: String(requestedTotalDuration)
												}
												onChange={(e) =>
													handleExtendTotalDurationChange(
														e.target.value === ""
															? null
															: Number(e.target.value),
													)
												}
												className={selectClass}
												title="Total video duration"
											>
												<option value="">Select total…</option>
												{extendTotalOptions.map((total) => (
													<option key={total} value={total}>
														{total}s
													</option>
												))}
											</select>
										</label>
									) : (
										<label className="space-y-1">
											<span className={labelClass}>Duration</span>
											<select
												value={String(videoDurationSeconds)}
												onChange={(e) =>
													handleSingleDurationChange(Number(e.target.value))
												}
												className={selectClass}
												title="Video duration"
											>
												{singleDurationOptions.map((duration) => (
													<option key={duration} value={duration}>
														{duration}s
													</option>
												))}
											</select>
										</label>
									)}
								</div>
								{extendTotalRequired ? (
									<p className="text-[11px] text-amber-200">
										Pick a total duration to enable compile.
									</p>
								) : null}
								<details className="rounded-xl border border-dashed border-slate-800">
									<summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-semibold text-slate-400">
										Advanced settings ▸{" "}
										<span className="text-slate-600">
											engine · model · language · look
										</span>
									</summary>
									<div className="grid gap-3 border-t border-slate-800 p-3 sm:grid-cols-2">
										<label className="space-y-1">
											<span className={labelClass}>Engine</span>
											<select
												value={selectedEngineId}
												onChange={(e) => handleEngineChange(e.target.value)}
												className={selectClass}
												title="Engine"
											>
												{(capabilityMatrix?.engines ?? []).map((engine) => (
													<option
														key={engine.id}
														value={engine.id}
														disabled={!engine.supported}
													>
														{engine.label}
													</option>
												))}
											</select>
										</label>
										<label className="space-y-1">
											<span className={labelClass}>Video model</span>
											<select
												value={videoModel}
												onChange={(e) => handleVideoModelChange(e.target.value)}
												className={selectClass}
												title="Video model"
											>
												{modelSelectOptions.map((m) => (
													<option key={m.key} value={m.ui_label}>
														{m.ui_label}
													</option>
												))}
												{!singleModelValid && !isExtendMode ? (
													<option value={videoModel}>
														{videoModel} (unsupported)
													</option>
												) : null}
											</select>
										</label>
										<label className="space-y-1">
											<span className={labelClass}>Language</span>
											<select
												value={targetLanguage}
												onChange={(e) =>
													setTargetLanguage(e.target.value as PromptTargetLanguage)
												}
												className={selectClass}
												title="Language"
											>
												{languageOptions.map((language) => (
													<option key={language} value={language}>
														{language}
													</option>
												))}
											</select>
										</label>
										<label className="space-y-1">
											<span className={labelClass}>Camera style</span>
											<select
												value={cameraStyle}
												onChange={(e) =>
													setCameraStyle(e.target.value as PromptCameraStyle)
												}
												className={selectClass}
												title="Camera style"
											>
												<option value="UGC_IPHONE_RAW">UGC iPhone Raw</option>
												<option value="CINEMATIC_PRO">Cinematic Pro</option>
											</select>
										</label>
										<label className="space-y-1">
											<span className={labelClass}>Character presence</span>
											<select
												value={characterPresence}
												onChange={(e) =>
													setCharacterPresence(
														e.target.value as PromptCharacterPresence,
													)
												}
												className={selectClass}
												title="Character presence"
											>
												<option value="VISIBLE_CREATOR">Visible Creator</option>
												<option value="FACELESS">Faceless</option>
											</select>
										</label>
									</div>
								</details>
								{modelAdjustmentNote ? (
									<p className="text-[11px] text-amber-200">
										{modelAdjustmentNote}
									</p>
								) : null}
								{legacyPackageWarning ? (
									<p className="text-[11px] text-amber-200">
										{legacyPackageWarning}
									</p>
								) : null}
							</div>
						</WorkflowStep>

						{hasReferenceStep ? (
							<WorkflowStep
								index={5}
								title="Reference"
								status={sReference}
								open={v4IsOpen(5, sReference)}
								onToggleOpen={() => v4Toggle(5, v4IsOpen(5, sReference))}
								summary={referenceLabel}
								helper="Bind only the references this lane accepts; empty optional slots stay automatic."
							>
								<div className="space-y-2">
									<ResolvedChip
										label="Reference binding"
										value={referenceLabel}
										icon="🧷"
										auto={!referenceBlocker}
									/>
									{mode === "HYBRID" ? (
										<div
											data-testid="operator-hybrid-anchor"
											className={`rounded-lg border px-3 py-2 text-[11px] ${
												hybridAnchorLocked
													? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
													: hybridOfficialImageReady
														? "border-amber-500/30 bg-amber-500/10 text-amber-100"
														: "border-slate-700 bg-slate-900/60 text-slate-300"
											}`}
										>
											{hybridAnchorLocked
												? `Anchor: ${hybridProductName}'s official image ✓ — locked into this Hybrid package.`
												: hybridOfficialImageReady
													? `Anchor ready: ${hybridProductName}'s official image. Click Prepare to lock it into this Hybrid package.`
													: `Set ${hybridProductName}'s official image in the Visual / Canva tab, then Prepare to lock it as the Hybrid anchor.`}
										</div>
									) : null}
									{mode === "F2V" ? (
										<p className="text-[11px] text-slate-400">
											F2V start/end selections are frame references; presenter identity
											comes from the Avatar Registry.
										</p>
									) : null}
									{mode === "HYBRID" ? (
										// FASA 2b: HYBRID's anchor is auto-locked from the product's
										// official image (banner above). Collapse the canonical picker
										// behind an explicit "Override anchor" disclosure so it no
										// longer reads as a free/generic reference choice.
										// F2V/I2V/T2V are unchanged.
										<div className="space-y-2">
											<button
												type="button"
												data-testid="hybrid-override-anchor-toggle"
												aria-expanded={showHybridOverride}
												onClick={() => setShowHybridOverride((v) => !v)}
												className="inline-flex items-center gap-1 self-start rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800/60"
											>
												{showHybridOverride
													? "▾ Hide anchor override"
													: "▸ Override anchor"}
											</button>
											{showHybridOverride ? (
												<CanonicalReferenceBindingControls
													mode={mode}
													productId={selectedProduct?.id ?? null}
													binding={referenceBinding}
													onChange={setReferenceBinding}
												/>
											) : null}
										</div>
									) : (
										<CanonicalReferenceBindingControls
											mode={mode}
											productId={selectedProduct?.id ?? null}
											binding={referenceBinding}
											onChange={setReferenceBinding}
										/>
									)}
								</div>
							</WorkflowStep>
						) : null}

						{/* Step 5 — Creative direction */}
						<WorkflowStep
							index={creativeStepIndex}
							title="Creative direction"
							status={s5}
							open={v4IsOpen(creativeStepIndex, s5)}
							onToggleOpen={() =>
								v4Toggle(creativeStepIndex, v4IsOpen(creativeStepIndex, s5))
							}
							summary={sceneCameraLabel}
							helper="Scene and camera follow the presenter automatically — tweak only if you want."
						>
							<div className="space-y-3">
								<ResolvedChip
									label="Scene → camera"
									value={sceneCameraLabel}
									icon="🎬"
									auto={!v4IsOpen(creativeStepIndex, s5) || !primaryRecipe}
								/>
								<div className="rounded-xl border border-slate-800 bg-slate-950/40 p-2">
									<p className="mb-2 px-1 text-[11px] text-slate-400">
										Pick one scene — the camera follows it automatically.
									</p>
									{v4RecipesLoading ? (
										<p className="px-1 text-[11px] text-slate-500">
											Loading scenes…
										</p>
									) : v4PresenterRecipes.length ? (
										<div className="space-y-1">
											{v4PresenterRecipes.map((recipe) => {
												const selected =
													primaryRecipe?.scene_template_id ===
													recipe.scene_template_id;
												return (
													<button
														key={recipe.scene_template_id}
														type="button"
														onClick={() => applyV4Recipe(recipe)}
														className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[12px] transition-colors ${selected ? "border-v4-accent bg-v4-accent/10" : "border-slate-800 hover:border-slate-600"}`}
													>
														<span
															className={`grid h-4 w-4 flex-none place-items-center rounded-full border ${selected ? "border-v4-accent" : "border-slate-600"}`}
														>
															{selected ? (
																<span className="h-2 w-2 rounded-full bg-v4-accent" />
															) : null}
														</span>
														<span className="flex-1 text-slate-200">
															{v4SceneText(recipe)}
														</span>
														<span className="text-[10px] text-v4-accent-ink">
															🎥 {recipe.camera_preset_code || "—"}
														</span>
													</button>
												);
											})}
										</div>
									) : (
										<p className="px-1 text-[11px] text-slate-500">
											No scenes configured for this presenter yet.
										</p>
									)}
								</div>
							</div>
						</WorkflowStep>

		{/* Storyboard */}
		<WorkflowStep
			index={storyboardStepIndex}
			title="Storyboard"
			status={sStoryboard}
							collapsible={false}
							helper="See the shots before you generate."
						>
							<div className="space-y-3">
								<StoryboardStrip shots={storyboardShots} />
								<button
									type="button"
									onClick={() => void handleLoadPreview()}
									disabled={
										!productReady ||
										isLoadingPreview ||
										extendTotalRequired ||
										backendRuntimeStale
									}
									className="rounded-xl border border-slate-700 bg-slate-800/40 px-4 py-2 text-[12px] font-semibold text-slate-100 hover:bg-slate-800/70 disabled:opacity-40"
								>
									{isLoadingPreview
										? "Compiling…"
										: previewPackage
											? "Reload preview"
											: "Compile preview"}
								</button>
							</div>
						</WorkflowStep>

		{/* Generate video (credit-bearing; unchanged gates) */}
		<WorkflowStep
			index={generateStepIndex}
			title="Generate video"
			status={sGenerate}
							collapsible={false}
							helper="Credits are spent only here."
						>
							{extendAuthority ? (
								<NativeExtendPanel
									backendRuntimeStale={backendRuntimeStale}
									totalDurationSeconds={requestedTotalDuration}
									productId={selectedProduct?.id ?? null}
									productName={selectedProduct?.product_display_name ?? null}
									executionPackageId={
										workspacePackage?.workspace_execution_package_id ?? null
									}
									plannedBlocks={extendAuthority.plan
										.slice(1)
										.map((_blockDuration, i) => ({
											block_index: i + 2,
											position: i + 1,
											prompt: `Native Extend continuation block ${i + 2}`,
											is_final: i === extendAuthority.plan.length - 2,
										}))}
								/>
							) : singleClipPrompt && !referenceBlocker && singleClipRefsReady ? (
								// SINGLE clip for EVERY mode (T2V/F2V/HYBRID/I2V) via the LIVE
								// one-door lane (/api/flow/generate). Reference-required modes are
								// gated on their own resolved-reference transport; the operator
								// presses this — it spends credits — never auto-fired.
								<div className="space-y-2">
									<button
										type="button"
										onClick={() =>
											void handleExecute({
												mode: jobMode,
												prompt: singleClipPrompt,
												aspectRatio: "9:16",
												product_id: selectedProduct?.id ?? null,
												workspace_execution_package_id:
													workspacePackage?.workspace_execution_package_id ??
													null,
												prompt_fingerprint:
													workspacePackage?.prompt_fingerprint ?? null,
												startAsset: singleStartAsset ?? undefined,
												endAsset: singleEndAsset ?? undefined,
												refs:
													mode === "I2V"
														? {
																subjectAsset: singleSubjectAsset ?? undefined,
																sceneAsset: singleSceneAsset ?? undefined,
																styleAsset: singleStyleAsset ?? undefined,
															}
														: undefined,
											})
										}
										disabled={isExecuting || backendRuntimeStale}
										className="w-full rounded-xl bg-gradient-to-br from-v4-accent to-v4-auto px-4 py-3 text-[13px] font-bold text-slate-950 shadow-lg shadow-v4-accent/20 transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
									>
										{isExecuting
											? "Generating…"
											: `▶ Generate 1 clip · ${videoDurationSeconds}s`}
									</button>
									<p className="text-[11px] text-slate-500">
										Fires one video through Google Flow — spends credits. Needs an
										open, warmed-up Flow editor tab. For a longer joined video,
										switch Length to “Extended video”.
									</p>
								</div>
							) : !referenceBlocker && previewPackage && !workspacePackage ? (
								// FASA 1: the guided-shell dead-end. previewPackage is compiled but
								// workspacePackage is still null, so the credit-bearing Generate
								// button above cannot appear. Give the operator the REAL "Prepare
								// final prompt" action — the SAME handler the classic view uses
								// (handleGeneratePackage → production-valid Copy Set gate →
								// runGeneratePackage). It builds workspacePackage; the Generate
								// button then appears automatically. Mode-agnostic (T2V/F2V/HYBRID/I2V).
								<div className="space-y-2">
									<button
										type="button"
										data-testid="action-prepare-final-prompt"
										onClick={() => void handleGeneratePackage()}
						disabled={
											isLoadingPackage ||
											!selectedCopySetId ||
											copyReadinessLoading ||
											copyReadiness?.ready_for_generation !== true ||
											extendTotalRequired ||
											backendRuntimeStale
										}
										className="w-full rounded-xl border border-blue-500/40 bg-blue-500/15 px-4 py-3 text-[13px] font-bold text-blue-100 transition-all hover:bg-blue-500/25 disabled:opacity-50 disabled:grayscale"
									>
										{isLoadingPackage ? "Preparing…" : "Prepare final prompt"}
									</button>
									<p className="text-[11px] text-slate-500">
										{mode === "HYBRID" && !hybridOfficialImageReady
											? "Locks this product's official image as the Hybrid anchor and compiles the final prompt — no credits spent yet. If Prepare reports it missing, set the official image in the Visual / Canva tab."
											: "Compiles the final prompt and resolves references into the package — no credits spent yet. Generate appears next."}
									</p>
								</div>
							) : (
								<div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-100">
									{referenceBlocker
										? referenceBlocker
										: !singleClipRefsReady
											? mode === "HYBRID"
												? hybridOfficialImageReady
													? "Click Prepare to lock this product's official image as the anchor."
													: "Set this product's official image in the Visual / Canva tab first, then Prepare to lock it as the Hybrid anchor."
												: `${mode} needs its reference image resolved into the prepared package — re-run Prepare, or bind an approved reference.`
											: "Compile preview → Prepare final prompt first, then Generate 1 clip appears here."}
								</div>
							)}
						</WorkflowStep>
							</>
						)}

						{/* Shared workflow notice */}
						<div
							data-testid="workflow-notice"
							data-notice-tone={notice.tone}
							className={`rounded-2xl border px-4 py-3 text-sm ${notice.tone === "error" ? "border-red-500/40 bg-red-500/10 text-red-200" : notice.tone === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : notice.tone === "info" ? "border-blue-500/40 bg-blue-500/10 text-blue-200" : notice.tone === "warning" ? "border-amber-500/40 bg-amber-500/10 text-amber-200" : "border-slate-800 bg-slate-900/40 text-slate-300"}`}
						>
							<div className="font-semibold tracking-wide">{notice.title}</div>
							<div className="mt-1 text-xs opacity-90">{notice.detail}</div>
						</div>

						{/* Caption authoring for the finished artifact (the video itself is
						    reviewed in the cockpit rail). */}
						{completedArtifact ? (
							<SocialCopyPackagePanel
								mediaId={completedArtifact.mediaId}
								sourceMode={mode}
								productName={selectedProduct?.product_display_name ?? null}
							/>
						) : null}
					</main>

					{/* Operator cockpit rail — also the video review screen once a job
					    completes (a quick look here without leaving for the Library). */}
					<div className="w-full lg:w-80 lg:flex-none lg:min-h-0 lg:overflow-y-auto">
						<div className="space-y-4">
							{completedArtifact ? (
								<div className="overflow-hidden rounded-2xl border border-emerald-500/40 bg-emerald-500/10 shadow-lg shadow-black/20">
									<div className="flex items-center justify-between gap-2 border-b border-emerald-500/20 px-3 py-2">
										<div className="text-[11px] font-bold uppercase tracking-[0.14em] text-emerald-200">
											{completedArtifact.kind === "video" ? "🎬 Review" : "🖼 Review"}
											{completedArtifact.sizeMb
												? ` · ${completedArtifact.sizeMb}MB`
												: ""}
										</div>
										<div className="flex items-center gap-2">
											<a
												href={completedArtifact.url}
												download={`${completedArtifact.mediaId}.${completedArtifact.kind === "video" ? "mp4" : "jpg"}`}
												className="rounded-md border border-emerald-500/40 px-2 py-0.5 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/20"
											>
												Download
											</a>
											<button
												type="button"
												onClick={() => setCompletedArtifact(null)}
												className="text-[12px] text-emerald-200/70 hover:text-emerald-200"
												title="Dismiss"
											>
												✕
											</button>
										</div>
									</div>
									<div className="p-2">
										{completedArtifact.kind === "video" ? (
											// biome-ignore lint/a11y/useMediaCaption: generated previews have no caption track
											<video
												src={completedArtifact.url}
												controls
												playsInline
												className="max-h-[60vh] w-full rounded-lg border border-emerald-500/20"
											/>
										) : (
											<img
												src={completedArtifact.url}
												alt="Generated artifact"
												className="max-h-[60vh] w-full rounded-lg border border-emerald-500/20"
											/>
										)}
									</div>
									<div className="border-t border-emerald-500/20 px-3 py-2 text-[10px] text-emerald-200/60">
										Also saved to the Video Library (48h) · media{" "}
										{completedArtifact.mediaId}
									</div>
								</div>
							) : null}
							<ResultsSidebar
								results={sessionResults}
								generating={isExecuting}
								mediaKind={isImageMode ? "image" : "video"}
								libraryHref={isImageMode ? "/library/images" : "/library/videos"}
								onRemoved={(mediaId) =>
									setSessionResults((prev) =>
										prev.filter((r) => r.media_id !== mediaId),
									)
								}
							/>
						</div>
					</div>
				</div>
			</div>
		);
	}

	return (
		// RPA Round A (selector/state normalization): stable root + mode marker so a
		// future UI-click operator can confirm it is on the intended workflow before
		// acting. Attributes only — no behavior change.
		<div
			data-testid="hybrid-workflow"
			data-mode={mode}
			className="flex h-full flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-8"
		>
			<div className="mb-6 flex flex-col gap-4 lg:mb-8 lg:flex-row lg:items-center lg:justify-between">
				<div>
					<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
						{humanizeWorkspaceMode(mode as WorkspaceMode)} Production Workspace
					</h2>
					<p className="text-sm italic text-slate-400">
						Automating Google Flow with BOSMAX V4 precision.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<div className="px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold uppercase tracking-widest">
						Mode: {workspaceSurfaceLabel(mode as WorkspaceMode)}
					</div>
				</div>
			</div>

			<div className="mb-4">
				<BackendVersionBanner onRuntimeStaleChange={setBackendRuntimeStale} />
			</div>

			{isPortalMode && (
				<div className="mb-4 grid grid-cols-2 gap-2 rounded-2xl border border-slate-800 bg-slate-900/40 p-2">
					<button
						type="button"
						onClick={() => setCompactPane("workspace")}
						className={`rounded-xl px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] transition ${compactPane === "workspace" ? "bg-blue-500/15 text-blue-200 shadow-inner shadow-blue-950/30" : "text-slate-400 hover:bg-slate-800/70 hover:text-slate-200"}`}
					>
						Workspace
					</button>
					<button
						type="button"
						onClick={() => setCompactPane("jobs")}
						className={`rounded-xl px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] transition ${compactPane === "jobs" ? "bg-blue-500/15 text-blue-200 shadow-inner shadow-blue-950/30" : "text-slate-400 hover:bg-slate-800/70 hover:text-slate-200"}`}
					>
						Jobs{" "}
						{modeRequests.length > 0
							? `(${Math.min(modeRequests.length, 99)})`
							: ""}
					</button>
				</div>
			)}

			{/* ── STEP 1: Select Product ────────────────────────────────── */}
			<div
				data-testid="workflow-step-1"
				data-state={selectedProduct ? "COMPLETED" : "NOT_READY"}
				data-selected-product-id={selectedProduct?.id ?? ""}
				className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
			>
				<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Step 1 — Select Product
				</div>
				<div className="mb-4 text-[11px] text-slate-400">
					Only READY products can generate a{" "}
					{humanizeWorkspaceMode(mode as WorkspaceMode)} package.
				</div>
				{isLoadingProducts && (
					<div className="mb-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-2 text-[11px] text-slate-400">
						Loading products...
					</div>
				)}
				{productsError && !isLoadingProducts && (
					<div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-[11px] text-rose-300">
						Product list failed to load: {productsError}
					</div>
				)}
				<SearchableProductSelect
					products={products}
					selectedProduct={selectedProduct}
					onSelect={setSelectedProduct}
					readinessByProductId={packageReadiness}
					isLoadingReadiness={isLoadingAnyReadiness}
				/>
				{/* Reference-only product blocker */}
				{selectedProduct?.reference_only && !selectedReadiness ? (
					<div className="mt-4 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
						<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-amber-400 mb-2">
							Reference-Only Product
						</div>
						<div className="text-xs text-amber-200 mb-3">
							REFERENCE_ONLY_PRODUCT —{" "}
							{selectedProduct.catalog_visibility_reason ||
								"FastMoss reference is visible for review only. Use Smart Registration to convert it into product truth before package load/generation."}
						</div>
						<div className="flex flex-wrap gap-2">
							<button
								type="button"
								onClick={() => navigate("/product-registration?tab=bulk")}
								title="Convert / Register Product"
								className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-[11px] font-semibold text-indigo-100"
							>
								Open Bulk FastMoss Convert
							</button>
						</div>
					</div>
				) : selectedReadiness ? (
					<div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
						<div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
							<div>
								<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-500">
									Package Eligibility
								</div>
								<div className="mt-2 flex flex-wrap items-center gap-2">
									<span
										className={`inline-flex rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] ${
											selectedReadiness.readiness_status === "READY"
												? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
												: selectedReadiness.readiness_status ===
														"PRODUCT_ARCHIVED"
													? "border-slate-500/30 bg-slate-500/10 text-slate-300"
													: "border-amber-500/30 bg-amber-500/10 text-amber-100"
										}`}
									>
										{selectedReadiness.readiness_status}
									</span>
									<span className="text-xs text-slate-300">
										{selectedReadiness.detail}
									</span>
								</div>
							</div>
							<div className="flex flex-wrap gap-2">
								<button
									type="button"
									onClick={() =>
										navigate(
											selectedReadiness.quick_actions.smart_registration_path,
										)
									}
									className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-[11px] font-semibold text-indigo-100"
								>
									Open Smart Registration / Complete Evidence
								</button>
								<button
									type="button"
									onClick={() =>
										navigate(
											selectedReadiness.quick_actions.approved_packages_path,
										)
									}
									className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-semibold text-slate-200"
								>
									Open Approved Packages
								</button>
								{selectedReadiness.readiness_status ===
								"CLAIM_SAFE_PACKAGE_NOT_READY" ? (
									<button
										type="button"
										data-testid="fix-claim-safe-package"
										onClick={() =>
											navigate(
												buildClaimSafeFixPath(
													selectedReadiness.product_id,
													location.pathname,
												),
											)
										}
										className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] font-semibold text-amber-100"
									>
										Fix Claim-Safe Package
									</button>
								) : null}
								{selectedReadiness.readiness_status ===
									"START_FRAME_REQUIRED" ||
								selectedReadiness.readiness_status === "SUBJECT_REQUIRED" ? (
									<button
										type="button"
										onClick={() =>
											navigate(selectedReadiness.quick_actions.products_path)
										}
										className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] font-semibold text-emerald-100"
									>
										Upload product image (Products page)
									</button>
								) : null}
							</div>
						</div>
						<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
							{selectedReadiness.checklist.map((entry) => (
								<div
									key={entry.key}
									className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3"
								>
									<div className="flex items-center justify-between gap-3">
										<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
											{entry.label}
										</div>
										<span
											className={`inline-flex rounded-full border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.16em] ${
												entry.ready
													? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
													: "border-amber-500/30 bg-amber-500/10 text-amber-100"
											}`}
										>
											{entry.ready ? "READY" : "BLOCKED"}
										</span>
									</div>
									<div className="mt-2 text-[11px] leading-relaxed text-slate-300">
										{entry.detail}
									</div>
								</div>
							))}
						</div>
						{selectedReadiness.readiness_status !== "READY" ? (
							<div className="mt-3 text-[11px] text-amber-200">
								No {humanizeWorkspaceMode(mode as WorkspaceMode)}-ready product
								will load until this checklist is satisfied.
							</div>
						) : null}
					</div>
				) : null}
				{!selectedProduct?.reference_only &&
				!selectedReadiness &&
				!selectedReadinessLoading ? (
					<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-xs text-slate-400">
						No {humanizeWorkspaceMode(mode as WorkspaceMode)}-ready products are
						auto-selected. Choose a product and review its readiness checklist
						first.
					</div>
				) : null}
			</div>

			{/* ── STEP 2: Creative Direction — Scene Strategy authority + Copy Set/Angle/Hook ── */}
			{/* Workflow Upgrade V1: copy selection moves INSIDE Creative Direction,
			    directly after product selection. The Scene Strategy summary renders
			    the product's EXISTING strategy_taxonomy (catalog-attached) — no new
			    fetches, no variant selector. */}
			<div
				data-testid="workflow-step-2"
				data-state={
					!selectedProduct
						? "NOT_READY"
						: selectedCopySetId
							? "COMPLETED"
							: "READY"
				}
				className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
			>
				<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Step 2 — Creative Direction
				</div>
				<div className="mb-4 text-[11px] text-slate-400">
					Review the selected product's Scene Strategy authority, then bind the
					approved Copy Set / Angle / Hook before configuring generation.
				</div>
				<div className="mb-4">
					<SceneStrategySummary
						hasProduct={Boolean(selectedProduct)}
						productName={selectedProduct?.product_display_name ?? null}
						taxonomy={selectedProduct?.strategy_taxonomy ?? null}
					/>
				</div>
			{/* ── Copywriting readiness (video modes only) ─── */}
			{mode !== "IMG" && (
				<div className="mb-4">
					<CopywritingReadinessCard
						readiness={copyReadiness}
						loading={copyReadinessLoading}
						onPrepare={() =>
							window.location.assign(
								selectedProduct
									? `/products?product_id=${encodeURIComponent(selectedProduct.id)}`
									: "/products",
							)
						}
						onOpenCopyRegistry={() =>
							window.location.assign(
								selectedProduct
									? `/creative/copy-registry?product_id=${encodeURIComponent(selectedProduct.id)}`
									: "/creative/copy-registry",
							)
						}
					/>
				</div>
			)}
			{/* ── Copy Selection & Compiler Binding ─── */}
			<CopySelectionPanel
				productId={selectedProduct?.id ?? null}
				productName={selectedProduct?.product_display_name ?? null}
				selectedCopySetId={selectedCopySetId}
				onSelect={setSelectedCopySetId}
				disabled={isLoadingPreview || isLoadingPackage}
			/>
			</div>

			{/* ── STEP 3: Generation Setup — UGC Prompt Compiler Controls (video modes only) ── */}
			{mode !== "IMG" && (
				// RPA Round A (renumbered by Workflow Upgrade V1): Step 3 is settings-only (no action). Its state reports
				// whether the EXTEND total-duration prerequisite still blocks Load /
				// Generate — derived from the existing `extendTotalRequired` gate.
				<div
					data-testid="workflow-step-3"
					data-state={extendTotalRequired ? "NOT_READY" : "READY"}
					className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
				>
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 3 — Generation Setup (UGC Prompt Compiler)
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						Configure all generation parameters for the selected product and
					creative direction. These settings are
						compiled into the final prompt when you press Generate.
					</div>
					<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Generation Mode
							</div>
							<select
								id="operator-generation-mode"
								name="operator_generation_mode"
								title="Generation mode"
								data-testid="setting-generation-mode"
								data-value={generationMode}
								value={generationMode}
								onChange={(e) =>
									handleGenerationModeChange(
										e.target.value as PromptGenerationMode,
									)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="SINGLE">Single</option>
								<option value="EXTEND">Extend</option>
							</select>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Engine
							</div>
							<select
								id="operator-engine"
								name="operator_engine"
								title="Engine"
								value={selectedEngineId}
								onChange={(e) => handleEngineChange(e.target.value)}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{(capabilityMatrix?.engines ?? []).map((engine) => (
									<option
										key={engine.id}
										value={engine.id}
										disabled={!engine.supported}
									>
										{engine.supported
											? `${engine.label} — ${engine.single_duration_policy
													.map((d) => `${d}s`)
													.join(" / ")}`
											: `${engine.label} — ${engine.unsupported_reason ?? "unavailable"}`}
									</option>
								))}
							</select>
							{engineHelperText ? (
								<div className="text-[11px] text-slate-400">
									{engineHelperText}
								</div>
							) : null}
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Video Model
							</div>
							<select
								id="operator-video-model"
								name="operator_video_model"
								title="Video model"
								data-testid="setting-video-model"
								data-value={videoModel}
								value={videoModel}
								onChange={(e) => handleVideoModelChange(e.target.value)}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{modelSelectOptions.map((m) => (
									<option key={m.key} value={m.ui_label}>
										{m.ui_label}
									</option>
								))}
								{!singleModelValid && !isExtendMode ? (
									<option value={videoModel}>{videoModel} (unsupported)</option>
								) : null}
							</select>
							{modelAdjustmentNote ? (
								<div className="text-[11px] text-amber-200">
									{modelAdjustmentNote}
								</div>
							) : null}
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Language
							</div>
							<select
								id="operator-target-language"
								name="operator_target_language"
								title="Target language"
								value={targetLanguage}
								onChange={(e) =>
									setTargetLanguage(e.target.value as PromptTargetLanguage)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{languageOptions.map((language) => (
									<option key={language} value={language}>
										{language}
									</option>
								))}
							</select>
						</div>
						{isExtendMode ? (
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Total Video Duration
								</div>
								<select
									id="operator-extend-total-duration"
									name="operator_extend_total_duration"
									title="Total video duration"
									data-testid="setting-total-duration"
									data-value={
										requestedTotalDuration === null
											? ""
											: String(requestedTotalDuration)
									}
									value={
										requestedTotalDuration === null
											? ""
											: String(requestedTotalDuration)
									}
									onChange={(e) =>
										handleExtendTotalDurationChange(
											e.target.value === "" ? null : Number(e.target.value),
										)
									}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									<option value="">Select total video duration</option>
									{extendTotalOptions.map((total) => (
										<option key={total} value={total}>
											{total}s
										</option>
									))}
								</select>
							</div>
						) : (
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Video Duration
								</div>
								<select
									id="operator-video-duration"
									name="operator_video_duration"
									title="Video duration"
									data-testid="setting-block-duration"
									data-value={String(videoDurationSeconds)}
									value={String(videoDurationSeconds)}
									onChange={(e) =>
										handleSingleDurationChange(Number(e.target.value))
									}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									{singleDurationOptions.map((duration) => (
										<option key={duration} value={duration}>
											{duration}s
										</option>
									))}
								</select>
								<div className="text-[11px] text-slate-400">
									One complete video · {videoShotPolicy?.recommended ?? "-"}{" "}
									recommended shot(s)
								</div>
							</div>
						)}
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Camera Style
							</div>
							<select
								id="operator-camera-style"
								name="operator_camera_style"
								title="Camera style"
								value={cameraStyle}
								onChange={(e) =>
									setCameraStyle(e.target.value as PromptCameraStyle)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="UGC_IPHONE_RAW">UGC iPhone Raw</option>
								<option value="CINEMATIC_PRO">Cinematic Pro</option>
							</select>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Character Presence
							</div>
							<select
								id="operator-character-presence"
								name="operator_character_presence"
								title="Character presence"
								value={characterPresence}
								onChange={(e) =>
									setCharacterPresence(
										e.target.value as PromptCharacterPresence,
									)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="VISIBLE_CREATOR">Visible Creator</option>
								<option value="FACELESS">Faceless</option>
							</select>
							{characterPresence === "FACELESS" ? (
								<div className="text-[11px] text-amber-200">
									Faceless is explicit-only and disables the visible creator
									default.
								</div>
							) : null}
						</div>
					</div>
					{mode === "T2V" ? (
						<div className="mt-4" data-testid="operator-creative-direction-t2v">
							<CreativeDirectionSection
								productId={selectedProduct?.id ?? null}
								value={creativeDirection}
								onChange={handleCreativeDirectionChange}
							/>
						</div>
					) : mode === "HYBRID" ? (
						<div
							data-testid="operator-registry-authority"
							className="mt-4 rounded-lg border border-cyan-500/25 bg-cyan-500/5 p-3"
						>
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-200">
								Registry Authority (Avatar + Scene)
							</div>
							<div className="mt-1 text-[11px] text-slate-300">
								Hybrid presenter identity and scene background resolve from the live
								approved Avatar Registry and Scene Registry. The Scene Registry
								Background is a visual override only — distinct from the product's
								Scene Strategy authority shown in Step 2. (T2V is text-only and uses
								the descriptor-based Creative Direction above — no image pickers.)
							</div>
							{registryPoolsLoading ? (
								<div className="mt-2 text-[11px] text-slate-400">Loading registries…</div>
							) : null}
							<div className="mt-3 space-y-4">
								<label className="space-y-1 text-xs text-slate-200">
									<span>Avatar registry</span>
									<select
										id="operator-avatar-registry"
										data-testid="operator-avatar-registry"
										value={registryAvatarId}
										onChange={(e) =>
											setRegistryAvatarId(
												resolveAvatarRegistryCode(e.target.value, avatarRegistryPool),
											)
										}
										className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
									>
										<option value="">
											{avatarRegistryPool.length
												? "— product-seeded registry pick —"
												: "No avatar registry rows"}
										</option>
										{avatarRegistryPool.map((row) => {
											const code = String(row.avatar_code || row.AvatarCode || "").trim();
											if (!code) return null;
											const label = avatarRegistryLabel(row);
											return (
												<option key={code} value={code}>
													{label} — {code}
												</option>
											);
										})}
									</select>
								</label>
								<VisualAssetPicker label="Avatar registry visual picker" value={registryAvatarId} onChange={(value) => setRegistryAvatarId(resolveAvatarRegistryCode(value, avatarRegistryPool))} items={avatarRegistryPool.map((row) => ({ value: String(row.avatar_code || row.AvatarCode || ""), title: avatarRegistryLabel(row), subtitle: String(row.avatar_code || row.AvatarCode || ""), previewUrl: avatarRegistryPreviewUrl(row, registryPreviewUrls), status: "APPROVED" })).filter((row) => Boolean(row.value))} />
								<label className="space-y-1 text-xs text-slate-200">
									<span>Scene registry</span>
									<select
										id="operator-scene-registry"
										data-testid="operator-scene-registry"
										value={registrySceneCode}
										onChange={(e) => setRegistrySceneCode(e.target.value)}
										className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
									>
										<option value="">
											{sceneRegistryPool.length
												? "— product package scene (no override) —"
												: "No scene registry rows"}
										</option>
										{sceneRegistryPool.map((row) => (
											<option key={row.scene_code} value={row.scene_code}>
												{row.scene_name || row.scene_code}
												{row.image_generated ? " · img" : ""}
											</option>
										))}
									</select>
								</label>
								<VisualAssetPicker label="Scene registry visual picker" value={registrySceneCode} onChange={setRegistrySceneCode} items={sceneRegistryPool.map((row) => ({ value: row.scene_code, title: row.scene_name || row.scene_code, subtitle: row.scene_code, previewUrl: registryPreviewUrls[String(row.generated_asset_id || "")] || null, status: "APPROVED" }))} />
							</div>
							{registryAvatarId ? (
								<div className="mt-2 text-[11px] text-cyan-100">
									Avatar lock: {registryAvatarId}
								</div>
							) : (
								<div className="mt-2 text-[11px] text-slate-400">
									Select an approved Avatar Registry avatar before generating.
								</div>
							)}
							{registrySceneCode ? (
								<div className="mt-1 text-[11px] text-cyan-100">
									Scene lock: {registrySceneCode}
								</div>
							) : null}
						</div>
					) : null}
					<CanonicalReferenceBindingControls
						mode={mode}
						productId={selectedProduct?.id ?? null}
						binding={referenceBinding}
						onChange={setReferenceBinding}
					/>
					{legacyPackageWarning ? (
						<div
							data-testid="operator-legacy-package-warning"
							className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200"
						>
							{legacyPackageWarning}
						</div>
					) : null}
					{!isExtendMode ? (
						<div
							data-testid="operator-resolved-capability"
							className="mt-4 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-[11px] text-slate-300"
						>
							<span className="font-semibold text-slate-200">
								Resolved capability
							</span>{" "}
							· Source {resolveSourceMode(mode)} · Engine{" "}
							{currentEngine?.label ?? selectedEngineId} · Model {videoModel} ·
							Duration {videoDurationSeconds}s · capability v
							{capabilityMatrix?.capability_matrix_version ?? "—"}
						</div>
					) : null}
					<div className="mt-4 grid gap-3 md:grid-cols-2">
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Source Mode (canonical)
							</div>
							<select
								title="Canonical source mode (fixed by this operator surface)"
								value={resolveSourceMode(mode)}
								disabled
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100 disabled:opacity-60"
							>
								<option value="HYBRID">
									HYBRID — product image anchor + AI presenter
								</option>
								<option value="FRAMES">
									FRAMES — ready frame, motion-delta only
								</option>
								<option value="T2V">T2V — text-driven</option>
								<option value="INGREDIENTS">
									INGREDIENTS — asset role map
								</option>
								<option value="IMAGES">IMAGES — still image</option>
							</select>
							<div className="text-[11px] text-slate-400">
								Fixed by this operator surface: HYBRID and FRAMES are separate
								pages under the canonical compiler contract.
							</div>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Duration Authority
							</div>
							<div
								className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-300"
								data-testid="operator-duration-authority-summary"
							>
								{extendTotalRequired ? (
									"Select one Total Video Duration to derive the authorized route, block plan, timeline, and automatic WPS budget."
								) : extendAuthority ? (
									<>
										<div title={extendAuthority.route ?? undefined}>
											Route:{" "}
											{extendAuthority.route ===
											"GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS"
												? "Uniform 8s block plan (executes via Native Flow Extend below)"
												: extendAuthority.route}{" "}
											· authorized · {extendAuthority.plan.length} blocks
										</div>
										<div className="mt-1">
											Plan:{" "}
											{extendAuthority.plan
												.map((duration) => `${duration}s`)
												.join(" + ")}{" "}
											· Timeline:{" "}
											{extendAuthority.timeline
												.map(
													(segment) => `${segment.start_s}–${segment.end_s}s`,
												)
												.join(" | ")}
										</div>
										<div className="mt-1">
											WPS: automatic{" "}
											{automaticWps === null
												? "from compiler policy"
												: `${automaticWps} body WPS`}
										</div>
									</>
								) : (
									"One complete video · WPS is applied automatically by the compiler policy."
								)}
							</div>
						</div>
					</div>
					<div className="mt-4 grid gap-3 md:grid-cols-2">
						<div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 text-[11px] text-slate-300">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Shot Plan
							</div>
							{extendAuthority ? (
								<div className="mt-2">
									{extendAuthority.timeline.map((segment) => {
										const duration = segment.end_s - segment.start_s;
										return (
											<div key={segment.block_index} className="mt-1">
												Block {segment.block_index}: {duration}s ·{" "}
												{promptConfig?.shot_count_policy[String(duration)]
													?.recommended ?? "-"}{" "}
												recommended shot(s)
											</div>
										);
									})}
								</div>
							) : (
								<div className="mt-2">
									Complete video: {videoShotPolicy?.recommended ?? "-"}{" "}
									recommended shot(s)
								</div>
							)}
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 text-[11px] text-slate-300">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Language Policy
							</div>
							<div className="mt-2">
								{targetLanguage} body WPS:{" "}
								{promptConfig?.language_wps_policy[targetLanguage]?.body_wps ??
									"-"}
							</div>
							<div className="mt-1">
								Absolute ceiling:{" "}
								{promptConfig?.language_wps_policy[targetLanguage]
									?.absolute_ceiling_wps ?? "-"}
							</div>
						</div>
					</div>
				</div>
			)}

			{/* ── STEP 4: Compile & Review (video modes only) ── */}
			{mode !== "IMG" && (
				// RPA Round A (renumbered by Workflow Upgrade V1): the container keeps the
				// generate-phase state machine that previously lived on workflow-step-4 —
				// DERIVED from the existing gates that already drive the buttons' `disabled`
				// expressions below; no new state. Copy selection remains a hard
				// prerequisite for saved video prompts. The load phase reports as
				// workflow-step-4-load.
				<div
					data-testid="workflow-step-4"
					data-state={
						isLoadingPackage
							? "RUNNING"
							: !previewPackage || extendTotalRequired
								? "NOT_READY"
								: "READY"
					}
					className="mb-6 rounded-2xl border border-blue-500/20 bg-slate-900/40 p-4"
				>
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 4 — Compile & Review
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						Load the approved package preview, review the compiled prompt, then
						generate and save the final execution prompt.
					</div>
					<div className="mb-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-3 py-3 text-[11px] text-indigo-100">
						<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-indigo-300">
							Approved Package Bridge
						</div>
						<div className="mt-1 text-indigo-100/80">
							{packageBridgeFlowLabelByMode[mode as WorkspaceMode]} stays a
							two-step bridge here so package preview and saved execution payload
							never get conflated.
						</div>
					</div>
					{/* Step 4a — Load Package preview (compile only, no DB save) */}
				{/* RPA Round A (renumbered by Workflow Upgrade V1): Step 4a load state is DERIVED from the existing gates that
				    already drive the button's `disabled` expression below — no new state. */}
				<div
					data-testid="workflow-step-4-load"
					data-state={
						isLoadingPreview
							? "RUNNING"
							: !selectedProduct ||
									selectedReadinessLoading ||
									selectedReadiness?.readiness_status !== "READY" ||
									extendTotalRequired
								? "NOT_READY"
								: previewPackage
									? "COMPLETED"
									: "READY"
					}
					className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
				>
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 4a — Load {mode} Package
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						Fetch and compile the approved package for the selected product
						using your configured settings above. Review the prompt preview
						before generating.
					</div>
					{!selectedCopySetId ? (
						<div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
							No approved Copy Set selected. Compiler may use fallback copy
							(product landbank / claim-safe angles).
						</div>
					) : null}
					{extendTotalRequired ? (
						<div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
							<strong>
								Production EXTEND requires one Total Video Duration.
							</strong>{" "}
							The authorized route, block plan, timeline, and WPS budget are
							derived automatically. Select a total above to enable Load /
							Generate.
						</div>
					) : null}
					<button
						type="button"
						data-testid="action-load-hybrid-package"
						onClick={() => void handleLoadPreview()}
						disabled={
							!selectedProduct ||
							isLoadingPreview ||
							selectedReadinessLoading ||
							selectedReadiness?.readiness_status !== "READY" ||
							extendTotalRequired ||
							backendRuntimeStale
						}
						className="w-full rounded-xl border border-slate-600/40 bg-slate-700/30 px-4 py-3 text-sm font-bold text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 disabled:grayscale transition-all"
					>
						{isLoadingPreview ? `Loading ${mode} Package…` : loadPackageLabel}
					</button>
					{/* Preview result */}
					{previewPackage ? (
						<div className="mt-4 space-y-3">
							<div className="grid gap-3 md:grid-cols-3">
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Mode / Duration
									</div>
									<div className="mt-1 text-xs font-semibold text-white">
										{previewPackage.generation_mode} ·{" "}
										{previewPackage.total_duration_seconds}s
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Prompt Fingerprint
									</div>
									<div className="mt-1 text-xs font-semibold text-white">
										{previewPackage.prompt_fingerprint}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Blocks
									</div>
									<div className="mt-1 text-xs font-semibold text-white">
										{previewPackage.prompt_blocks?.length ?? 0} block(s)
										compiled
									</div>
								</div>
							</div>
							{previewPackage.copy_binding ? (
								<div
									className={`rounded-xl border px-3 py-2 text-[11px] ${
										previewPackage.copy_binding.copy_binding_status === "BOUND"
											? "border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
											: "border-amber-500/30 bg-amber-500/5 text-amber-200"
									}`}
								>
									<span className="font-semibold">Copy binding: </span>
									{previewPackage.copy_binding.copy_binding_status === "BOUND"
										? `Approved Copy Set bound (${previewPackage.copy_binding.copy_set_angle ?? "selected"})`
										: "No Copy Set bound — fallback copy in use"}
								</div>
							) : null}
							{previewPackage.warnings?.length ? (
								<div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
									{previewPackage.warnings.join(" · ")}
								</div>
							) : null}
							{previewPackage.wps_chaining_enforced ? (
								<div className="rounded-xl border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-[11px] text-sky-200">
									<div className="font-semibold">
										WPS enforced ·{" "}
										{previewPackage.engine_duration_target ?? "—"}
									</div>
									<div className="mt-1">
										Chain: [
										{(previewPackage.resolved_block_chain ?? []).join(", ")}] ·
										Budget: [
										{previewPackage.dialogue_word_budget_per_block.join(", ")}]
									</div>
									<div className="mt-1">
										Actual: [
										{(
											previewPackage.actual_dialogue_word_count_per_block ?? []
										).join(", ")}
										] · Status: [
										{(previewPackage.wps_status_per_block ?? []).join(", ")}]
									</div>
								</div>
							) : null}
							{previewPackage.planner_result ? (
								<div
									className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 px-3 py-3 text-xs text-slate-300"
									data-testid="operator-storyboard-plan-summary"
								>
									<div className="font-bold uppercase tracking-[0.18em] text-indigo-300">
										Storyboard-first plan ·{" "}
										{previewPackage.planner_result.plan_version}
									</div>
									<div className="mt-2 text-slate-400">
										Route: {previewPackage.planner_result.route_id} · Total:{" "}
										{previewPackage.planner_result.total_duration_seconds}s ·
										Blocks: [
										{previewPackage.planner_result.resolved_block_plan.join(
											", ",
										)}
										]
									</div>
									<div className="mt-1 text-slate-400">
										Story:{" "}
										{
											previewPackage.planner_result.full_story_plan
												.story_summary
										}
									</div>
									<div className="mt-1 text-slate-400">
										Full dialogue:{" "}
										{previewPackage.planner_result.full_dialogue_plan
											.full_dialogue_text || "(visual-only preview)"}
									</div>
									{previewPackage.planner_result.full_dialogue_plan
										.compliance_metadata?.cta_fit ? (
										<div
											className="mt-1 text-slate-400"
											data-testid="operator-cta-fit-diagnostics"
										>
											CTA fit:{" "}
											{
												previewPackage.planner_result.full_dialogue_plan
													.compliance_metadata.cta_fit.fit_status
											}{" "}
											·{" "}
											{
												previewPackage.planner_result.full_dialogue_plan
													.compliance_metadata.cta_fit.original_word_count
											}{" "}
											→{" "}
											{
												previewPackage.planner_result.full_dialogue_plan
													.compliance_metadata.cta_fit.spoken_word_count
											}{" "}
											/ budget{" "}
											{
												previewPackage.planner_result.full_dialogue_plan
													.compliance_metadata.cta_fit.final_block_word_budget
											}{" "}
											·{" "}
											{
												previewPackage.planner_result.full_dialogue_plan
													.compliance_metadata.cta_fit.fit_method
											}
											{previewPackage.planner_result.full_dialogue_plan
												.compliance_metadata.cta_fit.was_compacted ? (
												<div className="mt-1 text-amber-200/90">
													Spoken CTA (compacted):{" "}
													{
														previewPackage.planner_result.full_dialogue_plan
															.compliance_metadata.cta_fit.spoken_cta_text
													}
												</div>
											) : null}
										</div>
									) : null}
								</div>
							) : null}
							<div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
								Package loaded. Review above then press Generate Final Prompt to
								save.
							</div>
							<div className="space-y-3">
								<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
									Compiled Prompt Audit
								</div>
								{(previewPackage.prompt_blocks ?? []).map((block) => (
									<PromptAuditCard
										key={block.block_id ?? block.block_index}
										label={`Preview Block ${block.block_index} — ${block.block_role}`}
										block={block}
									/>
								))}
							</div>
						</div>
					) : null}
				</div>
					{/* Step 4b — Generate Final Prompt (compile + save to DB) */}
				<div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 4b — Generate Final Prompt
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						After loading the package above, press this button to compile and
						save the final execution prompt to the workspace.
					</div>
					{/* Copy binding state: saved video prompts require production-valid copy. */}
					{selectedCopySetId ? (
						<div className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
							Approved Copy Set bound to final prompt generation.
						</div>
					) : (
						<div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
							No production-valid approved Copy Set selected. Revalidate or submit
							semantic review in Copy Selection before generating the final prompt.
						</div>
					)}
					<button
						type="button"
						data-testid="action-generate-final-prompt"
						onClick={() => void handleGeneratePackage()}
						disabled={
							!previewPackage ||
							isLoadingPackage ||
							!selectedCopySetId ||
							copyReadinessLoading ||
							copyReadiness?.ready_for_generation !== true ||
							extendTotalRequired ||
							backendRuntimeStale
						}
						className="w-full rounded-xl border border-blue-500/40 bg-blue-500/15 px-4 py-3 text-sm font-bold text-blue-100 hover:bg-blue-500/25 disabled:opacity-50 disabled:grayscale transition-all"
					>
						{isLoadingPackage ? "Generating…" : generatePromptLabel}
					</button>
					{workspacePackage ? (
						<div className="mt-4 space-y-3">
							{workspacePackage.copy_binding ? (
								<div
									className={`rounded-xl border px-3 py-2 text-[11px] ${
										workspacePackage.copy_binding.copy_binding_status ===
										"BOUND"
											? "border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
											: "border-amber-500/30 bg-amber-500/5 text-amber-200"
									}`}
								>
									<span className="font-semibold">Copy binding: </span>
									{workspacePackage.copy_binding.copy_binding_status === "BOUND"
										? `Approved Copy Set bound (${workspacePackage.copy_binding.copy_set_angle ?? "selected"})`
										: workspacePackage.copy_binding.copy_fallback_confirmed
											? "Fallback copy — operator-confirmed (COPY_SET_NOT_SELECTED)"
											: "Fallback copy (COPY_SET_NOT_SELECTED)"}
								</div>
							) : null}
							<div className="grid gap-3 md:grid-cols-3">
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Execution Package
									</div>
									<div className="mt-1 text-sm font-semibold text-white">
										{workspacePackage.workspace_execution_package_id}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Prompt Fingerprint
									</div>
									<div className="mt-1 text-sm font-semibold text-white">
										{workspacePackage.prompt_fingerprint}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Manual Fallback
									</div>
									<div className="mt-1 text-sm font-semibold text-white">
										{workspacePackage.manual_fallback.copy_prompt_available
											? "Copy prompt + image ready"
											: "Unavailable"}
									</div>
								</div>
							</div>
							<div className="space-y-3">
								<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
									Final Prompt Audit
								</div>
								{workspacePackage.prompt_blocks?.length ? (
									workspacePackage.prompt_blocks.map((block) => (
										<PromptAuditCard
											key={block.block_id ?? block.block_index}
											label={`Final Block ${block.block_index} — ${block.block_role}`}
											block={block}
										/>
									))
								) : (
									<PromptAuditCard
										label="Final Prompt"
										fallbackText={workspacePackage.prompt_text}
									/>
								)}
							</div>
						</div>
					) : null}
					{/* Generate / Save Package — F2V and I2V */}
					{workspacePackage &&
					(mode === "HYBRID" || mode === "F2V" || mode === "I2V") &&
					!selectedProduct?.reference_only ? (
						<div className="mt-4 rounded-2xl border border-indigo-500/30 bg-indigo-500/5 p-4">
							<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-indigo-400 mb-3">
								Prompt Handoff Bank
							</div>
							<div className="flex flex-wrap items-center gap-3">
								<button
									type="button"
									onClick={() => void handleSaveGenerationPackage()}
									disabled={isSavingPackage || backendRuntimeStale}
									className="rounded-xl border border-indigo-500/40 bg-indigo-500/15 px-4 py-2.5 text-sm font-semibold text-indigo-100 hover:bg-indigo-500/25 disabled:opacity-50 transition-colors"
								>
									{isSavingPackage
										? "Saving Package…"
										: "Generate / Save Package"}
								</button>
								{savedGenPackage && (
									<>
										<span className="text-xs text-emerald-300 font-mono">
											✓ Saved: {savedGenPackage.workspace_generation_package_id}
										</span>
										<button
											type="button"
											onClick={() => navigate(`/workspace/generation-packages`)}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-semibold text-slate-200 hover:bg-slate-800 transition-colors"
										>
											Open Prompt Handoff Bank
										</button>
									</>
								)}
								{savePackageError && (
									<span className="text-xs text-red-400">
										{savePackageError}
									</span>
								)}
							</div>
							<p className="mt-2 text-[11px] text-indigo-300/60">
								Saves a durable package with final prompt, selected assets,
								upload order, and DOM scaffold. DOM execution is not triggered.
								package_id is stored in Prompt Handoff Bank.
							</p>
						</div>
					) : null}
				</div>
				</div>
			)}

			{/* ── STEP 5: Generate Video (one full video, generated in parts) ──
			    Presentation-only relocation (2026-07-13 operator UX request): the
			    SAME NativeExtendPanel keeps rendering after Compile & Review so the
			    page reads top-to-bottom — product → creative direction →
			    generation setup → compile & review → GENERATE VIDEO. Props,
			    state, and behavior are unchanged. */}
			{mode !== "IMG" && (
				// RPA Round A: Step 5 is the LIVE, credit-bearing step. It is tagged for
				// DETECTION only, so an operator can prove it stopped before Step 5 — the
				// generate action itself lives in NativeExtendPanel and is deliberately
				// NOT tagged in Round A (Round B stops at Step 4; see G0 amendment B3 —
				// the action only renders when the EXTEND/duration prerequisite is met).
				<div
					data-testid="workflow-step-5"
					data-state={extendAuthority ? "READY" : "NOT_READY"}
					data-rpa-stop="true"
					className="mb-6 rounded-2xl border border-emerald-500/20 bg-slate-900/40 p-4"
				>
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 5 — Generate Video
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						After the final prompt is saved above, generate the one complete
						video here. The initial part, the Native Flow Extend continuation,
						and the final combined MP4 run automatically.
					</div>
					{extendAuthority ? (
						<NativeExtendPanel
							backendRuntimeStale={backendRuntimeStale}
							totalDurationSeconds={requestedTotalDuration}
							productId={selectedProduct?.id ?? null}
							productName={selectedProduct?.product_display_name ?? null}
							executionPackageId={
								workspacePackage?.workspace_execution_package_id ?? null
							}
							plannedBlocks={extendAuthority.plan
								.slice(1)
								.map((_blockDuration, i) => ({
									block_index: i + 2,
									position: i + 1,
									prompt: `Native Extend continuation block ${i + 2}`,
									is_final: i === extendAuthority.plan.length - 2,
								}))}
						/>
					) : (
						<div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-100">
							Select EXTEND with one Total Video Duration in Step 1 to enable
							video generation.
						</div>
					)}
				</div>
			)}


			{/* RPA Round A — G0 decision B1 option (a). This is the ONE global notice
			    shared by Steps 3/4/5; it carries no step attribution and no freshness
			    marker, so per-step error attribution is NOT derivable from existing
			    state. Rather than plumb new state (explicitly NOT authorized), the
			    notice is tagged as-is and any error tone is a GLOBAL STOP: a UI-click
			    operator must halt, and must not attribute the error to a step or treat
			    it as recoverable. Attributes only — tone/render logic unchanged. */}
			<div
				data-testid="workflow-notice"
				data-notice-tone={notice.tone}
				data-rpa-stop={notice.tone === "error" ? "true" : "false"}
				className={`mb-6 rounded-2xl border px-4 py-3 text-sm ${notice.tone === "error" ? "border-red-500/40 bg-red-500/10 text-red-200" : notice.tone === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : notice.tone === "info" ? "border-blue-500/40 bg-blue-500/10 text-blue-200" : notice.tone === "warning" ? "border-amber-500/40 bg-amber-500/10 text-amber-200" : "border-slate-800 bg-slate-900/40 text-slate-300"}`}
			>
				<div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
					<div>
						<div className="font-semibold tracking-wide">{notice.title}</div>
						<div className="text-xs opacity-90 mt-1">{notice.detail}</div>
					</div>
					<div className="text-[10px] uppercase tracking-[0.2em] opacity-70 md:text-right">
						{notice.requestId ? `req ${notice.requestId}` : "no active request"}
					</div>
				</div>
			</div>

			{completedArtifact && (
				<div className="mb-6 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4">
					<div className="mb-3 flex items-center justify-between">
						<div className="font-semibold tracking-wide text-emerald-200">
							{completedArtifact.kind === "video"
								? "🎬 Video ready"
								: "🖼 Image ready"}
							{completedArtifact.sizeMb
								? ` — ${completedArtifact.sizeMb}MB`
								: ""}
						</div>
						<div className="flex items-center gap-3">
							<a
								href={completedArtifact.url}
								download={`${completedArtifact.mediaId}.${completedArtifact.kind === "video" ? "mp4" : "jpg"}`}
								className="rounded-lg border border-emerald-500/40 px-3 py-1 text-xs text-emerald-200 hover:bg-emerald-500/20"
							>
								Download
							</a>
							<button
								type="button"
								onClick={() => setCompletedArtifact(null)}
								className="text-xs text-emerald-200/70 hover:text-emerald-200"
							>
								Tutup
							</button>
						</div>
					</div>
					{completedArtifact.kind === "video" ? (
						<>
							{/* biome-ignore lint/a11y/useMediaCaption: generated artifact previews do not ship with caption tracks */}
							<video
								src={completedArtifact.url}
								controls
								playsInline
								className="max-h-96 rounded-xl border border-emerald-500/20"
							/>
						</>
					) : (
						<img
							src={completedArtifact.url}
							alt="Generated artifact"
							className="max-h-96 rounded-xl border border-emerald-500/20"
						/>
					)}
					<div className="mt-2 text-[10px] uppercase tracking-[0.2em] text-emerald-200/60">
						media {completedArtifact.mediaId}
					</div>
				</div>
			)}

			{/* Social Copy Package — author platform-specific caption/comment copy
			    for the just-finished artifact; approved copy prefills Postiz. */}
			{completedArtifact && (
				<div className="mb-6">
					<SocialCopyPackagePanel
						mediaId={completedArtifact.mediaId}
						sourceMode={mode}
						productName={selectedProduct?.product_display_name ?? null}
					/>
				</div>
			)}

			<div className="flex flex-1 min-h-0 flex-col gap-6">
				{(!isPortalMode || compactPane === "workspace") && (
					<div className="min-h-0">{renderModule()}</div>
				)}

				{isPortalMode && compactPane === "jobs" && (
					<div className="min-h-0">
						<RequestReportPanel
							requests={modeRequests}
							title="Workspace Jobs"
							description="Portal mode can still inspect current workspace requests here without reopening the unified jobs page."
							emptyMessage="No jobs recorded for this workspace yet. New submissions from this page will appear here automatically."
							maxItems={18}
						/>
					</div>
				)}
			</div>
		</div>
	);
}
