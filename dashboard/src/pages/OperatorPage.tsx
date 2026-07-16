import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchAPI } from "../api/client";
import { useCopywritingReadiness } from "../api/copywritingReadiness";
import { fetchProductCatalog } from "../api/products";
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
import CopywritingReadinessCard from "../components/copywriting/CopywritingReadinessCard";
import NativeExtendPanel from "../components/NativeExtendPanel";
import RequestReportPanel from "../components/reporting/RequestReportPanel";
import SocialCopyPackagePanel from "../components/SocialCopyPackagePanel";
import CanonicalReferenceBindingControls, {
	EMPTY_BINDING,
	type CanonicalReferenceBinding,
} from "../components/workspace/CanonicalReferenceBindingControls";
import CopySelectionPanel from "../components/workspace/CopySelectionPanel";
import IMGModule from "../components/workspace/IMGModule";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type {
	Product,
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

// Avatar Persona composer (Phase A) — pure + hoisted for unit tests. The id
// pattern MUST mirror agent/services/persona_variant_service.compose_persona_id;
// the server's normalize_creator_persona stays the only validity gate.
export type AvatarComposerVocab = NonNullable<
	PromptCompilerRuntimeConfig["persona_composer"]
>;

export function composeAvatarPersonaId(
	gender: string,
	ethnicity: string,
	age: string,
	bundle: string,
): string | null {
	if (!(gender && ethnicity && age && bundle)) return null;
	return `AVX_${gender}_${ethnicity}_${age}_${bundle}`.toUpperCase();
}

export function composeAvatarPersonaPreview(
	composer: AvatarComposerVocab,
	genderId: string,
	ethnicityId: string,
	ageId: string,
	bundleId: string,
): string | null {
	const gender = composer.genders.find((g) => g.id === genderId);
	const ethnicity = composer.ethnicities.find((e) => e.id === ethnicityId);
	const age = composer.age_ranges.find((a) => a.id === ageId);
	const bundle = composer.bundles.find((b) => b.id === bundleId);
	if (!(gender && ethnicity && age && bundle)) return null;
	if (!bundle.allowed_genders.includes(gender.id)) return null;
	const wardrobe =
		gender.id === "F"
			? bundle.wardrobe_f_en
			: gender.id === "F_HIJAB"
				? bundle.wardrobe_f_hijab_en
				: bundle.wardrobe_m_en;
	return composer.visual_template_en
		.replace("{ethnicity}", ethnicity.descriptor_en)
		.replace("{gender}", gender.descriptor_en)
		.replace("{age}", age.descriptor_en)
		.replace("{wardrobe}", wardrobe)
		.replace("{environment}", bundle.environment_en)
		.replace("{expression}", bundle.expression_en);
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
			return "This product has no approved claim-safe package yet. Complete claim-safe review before loading a generation package.";
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

interface OperatorPageProps {
	mode?: "T2V" | "HYBRID" | "F2V" | "I2V" | "IMG";
}

export default function OperatorPage({ mode: propMode }: OperatorPageProps) {
	const location = useLocation();
	const navigate = useNavigate();
	const statePackage = (
		location.state as {
			workspaceExecutionPackage?: WorkspaceExecutionPackage;
		} | null
	)?.workspaceExecutionPackage;
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
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [referenceBinding, setReferenceBinding] =
		useState<CanonicalReferenceBinding>(EMPTY_BINDING);
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
	// Explicit-Fallback-Confirmation V1: gate shown before Generate Final Prompt
	// runs with no approved Copy Set selected.
	const [showFallbackConfirm, setShowFallbackConfirm] = useState(false);
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
	const [creatorPersona, setCreatorPersona] = useState("DEFAULT_CREATOR");
	// Avatar Persona composer (Phase A): a complete valid selection resolves to
	// a composed persona id; the server's normalize_creator_persona remains the
	// only validity gate (unknown ids fail closed at compile time).
	const [avatarGender, setAvatarGender] = useState("");
	const [avatarEthnicity, setAvatarEthnicity] = useState("");
	const [avatarAge, setAvatarAge] = useState("");
	const [avatarBundle, setAvatarBundle] = useState("");
	const composedAvatarPreview =
		promptConfig?.persona_composer &&
		avatarGender &&
		avatarEthnicity &&
		avatarAge &&
		avatarBundle
			? composeAvatarPersonaPreview(
					promptConfig.persona_composer,
					avatarGender,
					avatarEthnicity,
					avatarAge,
					avatarBundle,
				)
			: null;
	useEffect(() => {
		if (!composedAvatarPreview) return;
		const composedId = composeAvatarPersonaId(
			avatarGender,
			avatarEthnicity,
			avatarAge,
			avatarBundle,
		);
		if (composedId) setCreatorPersona(composedId);
	}, [composedAvatarPreview, avatarGender, avatarEthnicity, avatarAge, avatarBundle]);
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
	// Stale-reference law: a mode or product switch invalidates every prior
	// reference selection (the server's WRONG_PRODUCT / per-mode contract checks
	// stay the authority; this keeps the UI from carrying another product's or
	// another mode's pick into the next package).
	// biome-ignore lint/correctness/useExhaustiveDependencies: reset-on-change effect
	useEffect(() => {
		setReferenceBinding(EMPTY_BINDING);
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
		setShowFallbackConfirm(false);
	}, [selectedProduct?.id]);

	useEffect(() => {
		void fetchPromptCompilerRuntimeConfig()
			.then((config) => {
				setPromptConfig(config);
				setGenerationMode(config.defaults.generation_mode);
				setTargetLanguage(config.defaults.target_language);
				setCameraStyle(config.defaults.camera_style);
				setCharacterPresence(config.defaults.character_presence);
				setCreatorPersona(config.defaults.creator_persona);
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
		if (workspacePackage.creator_persona) {
			setCreatorPersona(workspacePackage.creator_persona);
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
				if (status === "FAILED") {
					setNotice({
						tone: "error",
						title: `${noticeModeLabel(mode, data.mode)} failed`,
						detail: job.error || "Generation failed.",
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
					title: `${data.mode} running`,
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
					const sizeMatch = completedMsg.match(/size_mb=([\d.]+)/);
					if (mediaMatch) {
						setCompletedArtifact({
							mediaId: mediaMatch[1],
							url: `/api/flow/retrieved/${mediaMatch[1]}`,
							kind: "video",
							sizeMb: sizeMatch ? sizeMatch[1] : null,
						});
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
					title: `${data.mode} running — video sedang dijana (±3–8 min), biar page ini terbuka`,
					detail: `Stage: ${stageLabel}${stageMessage ? ` — ${stageMessage}` : ""} · Nota: tiada apa akan bergerak dalam tab Google Flow — penjanaan berjalan melalui API dan video muncul di sini bila siap.`,
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
					image_media_ids: refs,
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
				throw new Error(err.detail || `HTTP ${response.status}`);
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
					creator_persona: creatorPersona,
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
					creator_persona: creatorPersona,
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
		creatorPersona,
	]);

	// Step 3 — Load Package Preview (compile only, no DB save)
	const handleLoadPreview = async () => {
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
				creator_persona: creatorPersona,
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
	// runGeneratePackage does the actual save; fallbackConfirmed is forwarded to
	// the backend which fails closed when no Copy Set is selected and fallback is
	// not explicitly confirmed (Explicit-Fallback-Confirmation V1).
	const runGeneratePackage = async (fallbackConfirmed: boolean) => {
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
		setShowFallbackConfirm(false);
		setIsLoadingPackage(true);
		try {
			const pkg = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode: jobMode,
				source_mode: resolveSourceMode(mode),
				copy_set_id: selectedCopySetId,
				copy_fallback_confirmed: fallbackConfirmed,
				// Record the operator-selected video model on the package so the
				// runtime + reload use the same tuple (was previously unset → "").
				model: videoModel,
				...durationAuthority.payload,
				target_language: targetLanguage,
				camera_style: cameraStyle,
				character_presence: characterPresence,
				creator_persona: creatorPersona,
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

	// Click handler: an approved Copy Set generates immediately; NO selection
	// opens the explicit fallback-confirmation gate first (backend also enforces).
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
			setShowFallbackConfirm(true);
			return;
		}
		void runGeneratePackage(false);
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
				<BackendVersionBanner />
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

			{/* ── STEP 1: UGC Prompt Compiler Controls (video modes only) ── */}
			{mode !== "IMG" && (
				// RPA Round A: Step 1 is settings-only (no action). Its state reports
				// whether the EXTEND total-duration prerequisite still blocks Load /
				// Generate — derived from the existing `extendTotalRequired` gate.
				<div
					data-testid="workflow-step-1"
					data-state={extendTotalRequired ? "NOT_READY" : "READY"}
					className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
				>
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 1 — UGC Prompt Compiler Controls
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						Configure all generation parameters first. These settings are
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
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Creator Persona
							</div>
							<select
								id="operator-creator-persona"
								name="operator_creator_persona"
								title="Creator persona"
								value={creatorPersona}
								onChange={(e) => setCreatorPersona(e.target.value)}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{(promptConfig?.persona_registry ?? []).map((persona) => (
									<option key={persona.id} value={persona.id}>
										{persona.label}
									</option>
								))}
								{creatorPersona.startsWith("AVX_") ? (
									<option value={creatorPersona}>
										Composed: {creatorPersona}
									</option>
								) : null}
							</select>
						</div>
					</div>
					{promptConfig?.persona_composer?.bundles?.length ? (
						<div
							data-testid="avatar-persona-composer"
							className="mt-4 rounded-lg border border-fuchsia-500/25 bg-fuchsia-500/5 p-3"
						>
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-fuchsia-200">
								Avatar Persona Composer
							</div>
							<div className="mt-1 text-[11px] text-slate-300">
								Pilih jantina · bangsa · umur · wardrobe+suasana (bundle
								tervalidasi) — deskripsi presenter dimasukkan ke prompt sebagai
								teks. Tiada gambar reference terlibat.
							</div>
							{characterPresence === "FACELESS" ? (
								<div className="mt-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
									Mod FACELESS aktif — persona avatar tidak digunakan.
								</div>
							) : null}
							<div className="mt-3 grid gap-3 md:grid-cols-4">
								{(
									[
										["Jantina", avatarGender, setAvatarGender,
											promptConfig.persona_composer.genders.map((g) => ({
												id: g.id, label: g.label_ms,
											}))],
										["Bangsa", avatarEthnicity, setAvatarEthnicity,
											promptConfig.persona_composer.ethnicities.map((e) => ({
												id: e.id, label: e.label,
											}))],
										["Umur", avatarAge, setAvatarAge,
											promptConfig.persona_composer.age_ranges.map((a) => ({
												id: a.id, label: a.label,
											}))],
										["Wardrobe + Suasana", avatarBundle, setAvatarBundle,
											promptConfig.persona_composer.bundles
												.filter(
													(b) =>
														!avatarGender ||
														b.allowed_genders.includes(avatarGender),
												)
												.map((b) => ({ id: b.id, label: b.label }))],
									] as Array<[
										string,
										string,
										(v: string) => void,
										Array<{ id: string; label: string }>,
									]>
								).map(([label, value, setter, options]) => (
									<label key={label} className="space-y-1 text-xs text-slate-200">
										<span>{label}</span>
										<select
											value={value}
											onChange={(event) => setter(event.target.value)}
											className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
										>
											<option value="">— pilih —</option>
											{options.map((option) => (
												<option key={option.id} value={option.id}>
													{option.label}
												</option>
											))}
										</select>
									</label>
								))}
							</div>
							{composedAvatarPreview ? (
								<div className="mt-3 rounded border border-fuchsia-500/20 bg-slate-950/60 px-3 py-2">
									<div className="text-[10px] uppercase tracking-[0.18em] text-fuchsia-300">
										Persona digunakan: {creatorPersona}
									</div>
									<div className="mt-1 text-[11px] leading-relaxed text-slate-300">
										{composedAvatarPreview}
									</div>
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

			{/* ── STEP 2: Select Product ────────────────────────────────── */}
			<div
				data-testid="workflow-step-2"
				data-state={selectedProduct ? "COMPLETED" : "NOT_READY"}
				data-selected-product-id={selectedProduct?.id ?? ""}
				className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
			>
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
				<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Step 2 — Select Product
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
			{/* ── Copy Selection & Compiler Binding (video modes only) ─── */}
			{mode !== "IMG" && (
				<CopySelectionPanel
					productId={selectedProduct?.id ?? null}
					productName={selectedProduct?.product_display_name ?? null}
					selectedCopySetId={selectedCopySetId}
					onSelect={setSelectedCopySetId}
					disabled={isLoadingPreview || isLoadingPackage}
				/>
			)}

			{/* ── STEP 3: Load Package (video modes only) ──────────────── */}
			{mode !== "IMG" && (
				// RPA Round A: Step 3 state is DERIVED from the existing gates that
				// already drive the button's `disabled` expression below — no new state.
				<div
					data-testid="workflow-step-3"
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
						Step 3 — Load {mode} Package
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
							extendTotalRequired
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
			)}

			{/* ── STEP 4: Generate Final Prompt (video modes only) ─────── */}
			{mode !== "IMG" && (
				// RPA Round A: Step 4 state is DERIVED from the existing gates that already
				// drive the button's `disabled` expression below — no new state.
				// AWAITING_HUMAN_CONFIRMATION (G0 amendment O1) marks the fallback gate:
				// the RPA must STOP there, never click through it.
				<div
					data-testid="workflow-step-4"
					data-state={
						showFallbackConfirm
							? "AWAITING_HUMAN_CONFIRMATION"
							: isLoadingPackage
								? "RUNNING"
								: !previewPackage || extendTotalRequired
									? "NOT_READY"
									: "READY"
					}
					className="mb-6 rounded-2xl border border-blue-500/20 bg-slate-900/40 p-4"
				>
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 4 — Generate Final Prompt
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						After loading the package above, press this button to compile and
						save the final execution prompt to the workspace.
					</div>
					{/* Copy binding state (Explicit-Fallback-Confirmation V1) */}
					{selectedCopySetId ? (
						<div className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
							Approved Copy Set bound to final prompt generation.
						</div>
					) : (
						<div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
							No approved Copy Set selected. Generate Final Prompt requires
							fallback confirmation.
						</div>
					)}
					<button
						type="button"
						data-testid="action-generate-final-prompt"
						onClick={() => void handleGeneratePackage()}
						disabled={
							!previewPackage ||
							isLoadingPackage ||
							showFallbackConfirm ||
							extendTotalRequired
						}
						className="w-full rounded-xl border border-blue-500/40 bg-blue-500/15 px-4 py-3 text-sm font-bold text-blue-100 hover:bg-blue-500/25 disabled:opacity-50 disabled:grayscale transition-all"
					>
						{isLoadingPackage ? "Generating…" : generatePromptLabel}
					</button>
					{/* Explicit fallback confirmation gate — shown only when the operator
					    presses Generate with NO approved Copy Set selected. Backend also
					    enforces this (copy_fallback_confirmed); this UI is not the sole gate. */}
					{showFallbackConfirm ? (
						// RPA Round A: the fallback-confirmation gate is a Protected Area and a
						// hard STOP for any UI-click operator. It is tagged so the RPA can DETECT
						// it and halt — never to click through it (that would ship fallback copy).
						<div
							data-testid="workflow-fallback-confirm"
							data-state="AWAITING_HUMAN_CONFIRMATION"
							data-rpa-stop="true"
							className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-[12px] text-amber-100"
						>
							<div className="mb-2 font-bold uppercase tracking-[0.15em] text-amber-300">
								Confirm fallback copy
							</div>
							<p className="mb-1">No approved Copy Set selected.</p>
							<p className="mb-1">
								Generate Final Prompt will use fallback copy from product
								landbank / claim-safe angles.
							</p>
							<p className="mb-3 font-semibold">
								This fallback is not approved Copy Set copy. Continue with
								fallback?
							</p>
							<div className="flex flex-wrap gap-2">
								<button
									type="button"
									onClick={() => void runGeneratePackage(true)}
									disabled={isLoadingPackage}
									className="rounded-lg border border-amber-500/50 bg-amber-500/20 px-3 py-2 text-[11px] font-semibold text-amber-100 hover:bg-amber-500/30 disabled:opacity-50 transition-colors"
								>
									{isLoadingPackage
										? "Generating…"
										: "Confirm fallback and continue"}
								</button>
								<button
									type="button"
									onClick={() => setShowFallbackConfirm(false)}
									disabled={isLoadingPackage}
									className="rounded-lg border border-slate-600/40 bg-slate-700/30 px-3 py-2 text-[11px] font-semibold text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 transition-colors"
								>
									Cancel and select / approve Copy Set
								</button>
							</div>
						</div>
					) : null}
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
									disabled={isSavingPackage}
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
			)}

			{/* ── STEP 5: Generate Video (one full video, generated in parts) ──
			    Presentation-only relocation (2026-07-13 operator UX request): the
			    SAME NativeExtendPanel that previously rendered inside Step 1 now
			    sits after Step 4 so the page reads top-to-bottom — settings →
			    product → copy → load → final prompt → GENERATE VIDEO. Props,
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
								? "🎬 Video siap"
								: "🖼 Imej siap"}
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
