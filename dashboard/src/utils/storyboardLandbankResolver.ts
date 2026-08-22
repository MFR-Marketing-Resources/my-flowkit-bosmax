// Storyboard Landbank operator-UX resolver.
//
// Pure, deterministic helpers that turn the V3 Copy Register's engineering-facing
// state into operator-language decisions. This module is the "internal default
// resolver" for the Copywriting Landbank wizard: it never calls the network and
// never mutates anything — every real authority decision (recipe creation, gap
// calculation, evidence ranking, approval, materialization) still happens
// server-side. The page composes the existing endpoints; this file decides what
// the operator sees and which single next action is recommended.
//
// Keeping this logic here (rather than inline in the page) makes it unit-testable
// in isolation and keeps the wizard component focused on rendering.

import type {
	V3AssistantMode,
	V3AssistantPlan,
	V3LandbankItem,
	V3ProductionCapacity,
} from "../api/storyboardLandbankV3Round2";
import type { BadgeTone } from "../components/ui";

export type WizardStep = "SETUP" | "GENERATE" | "REVIEW" | "PRODUCTION";

export const WIZARD_STEPS: readonly WizardStep[] = ["SETUP", "GENERATE", "REVIEW", "PRODUCTION"];

export const STEP_META: Record<WizardStep, { index: number; label: string; blurb: string }> = {
	SETUP: { index: 1, label: "Setup", blurb: "Product & campaign" },
	GENERATE: { index: 2, label: "Generate", blurb: "Create missing copy" },
	REVIEW: { index: 3, label: "Review", blurb: "Approve copy" },
	PRODUCTION: { index: 4, label: "Production Ready", blurb: "Prepare for production" },
};

function plural(count: number, one: string, many: string): string {
	return count === 1 ? one : many;
}

/**
 * Infer the assistant mode from current supply so the operator never picks it.
 * - No approved supply yet -> CREATE (author from scratch to meet the target).
 * - Some supply but below target -> FILL_CAPACITY (close the shortfall).
 * - At/above target -> EXPAND (bounded additional variants).
 */
export function inferAssistantMode(input: { existingApproved: number; target: number }): V3AssistantMode {
	const existing = Math.max(0, Math.floor(input.existingApproved || 0));
	const target = Math.max(0, Math.floor(input.target || 0));
	if (existing <= 0) return "CREATE";
	if (target > 0 && existing < target) return "FILL_CAPACITY";
	return "EXPAND";
}

export interface OperatorBlocker {
	code: string;
	message: string;
	actionLabel?: string;
	actionRoute?: string;
}

// Operator-language translations for the fail-closed reasons the backend can
// return. The raw code is always preserved (surfaced under Technical Details) so
// nothing is hidden — only reworded. Unknown codes fall through to a safe,
// non-alarming default that still points at Technical Details.
const BLOCKER_MAP: Record<string, Omit<OperatorBlocker, "code">> = {
	COPY_V3_EVIDENCE_AUTHORITY_MISMATCH: {
		message: "Copy generation is paused because the approved Product Truth changed. Review the current Product Truth before generating new copy.",
		actionLabel: "Review Product Truth",
		actionRoute: "/products",
	},
	COPY_V2_EVIDENCE_STALE: {
		message: "This copy is out of date because the approved Product Truth changed. Revalidate it before preparing it for production.",
		actionLabel: "Review Product Truth",
		actionRoute: "/products",
	},
	PRODUCT_TRUTH_ADVANCED: {
		message: "The approved Product Truth was updated, so existing copy needs revalidation before it can be prepared.",
		actionLabel: "Review Product Truth",
		actionRoute: "/products",
	},
	PRODUCT_TRUTH_NOT_FOUND: {
		message: "This product has no approved Product Truth yet. Approve Product Truth before generating copy.",
		actionLabel: "Set up Product Truth",
		actionRoute: "/products",
	},
	PRODUCT_TRUTH_NOT_CURRENT: {
		message: "The approved Product Truth changed. Review it before generating new copy.",
		actionLabel: "Review Product Truth",
		actionRoute: "/products",
	},
	NO_APPROVED_EVIDENCE: {
		message: "No approved evidence is available for this product yet. Approve product evidence before generating copy.",
		actionLabel: "Review Product Truth",
		actionRoute: "/products",
	},
	EVIDENCE_EMPTY: {
		message: "No approved evidence is available for this product yet. Approve product evidence before generating copy.",
		actionLabel: "Review Product Truth",
		actionRoute: "/products",
	},
	RECIPE_NOT_FOUND: {
		message: "The copy campaign is not set up yet. Set up the campaign first.",
		actionLabel: "Set Up Campaign",
	},
	PROVIDER_NOT_CONFIGURED: {
		message: "The AI copywriter is not connected, so live copy cannot be generated yet. Ask an administrator to connect the copy provider.",
	},
	// Operational (generation-time) codes — kept human, never a bare code dump.
	DUPLICATE_COMPONENT: {
		message: "This exact copy was already created. Try a smaller scale (Quick test) or generate a different variation.",
	},
	STORYBOARD_CAPACITY_SHORTFALL: {
		message: "The copywriter didn't produce a complete Hook / Body / CTA this time. Try generating again.",
	},
	MASTER_COMPILE_BLOCKED: {
		message: "This copy didn't pass the automatic structure check. Try generating again.",
	},
	PROJECTION_BLOCKED: {
		message: "A duration version couldn't be built for this copy. Try generating again.",
	},
};

/**
 * Translate a backend error/blocker code into operator language. Always returns
 * the raw `code` too, so the page can keep it under Technical Details.
 */
export function blockerToOperator(code: string | null | undefined, fallbackMessage?: string): OperatorBlocker {
	const raw = (code ?? "").trim();
	const hit = raw ? BLOCKER_MAP[raw] : undefined;
	if (hit) return { code: raw, ...hit };
	return {
		code: raw || "UNKNOWN",
		message:
			fallbackMessage && fallbackMessage.trim()
				? fallbackMessage.trim()
				: "Something needs attention before you can continue. See Technical Details for the exact reason.",
	};
}

/**
 * Extract a stable `CODE` from an API error message of the shape
 * `CODE: human message` (the transport format the page's errorMessage produces).
 */
export function extractBlockerCode(message: string | null | undefined): string {
	const text = (message ?? "").trim();
	const match = /^([A-Z][A-Z0-9_]{2,})\s*:/.exec(text);
	return match ? match[1] : "";
}

/**
 * Operator-language error for a toast/banner. Translates a known code, otherwise
 * strips the bare `CODE:` prefix so the primary UI never leads with a raw code.
 */
export function toOperatorError(message: string | null | undefined): string {
	const text = (message ?? "").trim();
	if (!text) return "Something went wrong. Please try again.";
	const code = extractBlockerCode(text);
	if (code && BLOCKER_MAP[code]) return BLOCKER_MAP[code].message;
	const stripped = code ? text.replace(new RegExp(`^${code}\\s*:\\s*`), "").trim() : text;
	return stripped || "Something went wrong. Please try again.";
}

export interface WorkflowCounts {
	target: number;
	/** Approved master storyboards (capacity.semantic_capacity). */
	approved: number;
	/** Reviewable (generated, not yet approved) storyboards. */
	reviewable: number;
	/** Deployable executable copy (capacity.production_capacity). */
	productionReady: number;
	/** Approved projections still needing preparation into production. */
	needsPreparation: number;
	/** Prepared V2 copy that still needs exact standard-lane authority activation. */
	activationRequired?: number;
	/** Executable copy that went stale and needs revalidation. */
	needsRevalidation: number;
}

/** Missing = how many more approved copies are needed to reach the target. */
export function missingCopies(counts: Pick<WorkflowCounts, "target" | "approved">): number {
	return Math.max(0, Math.floor(counts.target || 0) - Math.max(0, Math.floor(counts.approved || 0)));
}

export interface NextAction {
	step: WizardStep;
	kind: "SELECT_PRODUCT" | "SETUP" | "GENERATE" | "REVIEW" | "PREPARE" | "ACTIVATE" | "OPEN_STUDIO" | "RESOLVE_BLOCKER" | "DONE";
	label: string;
	detail: string;
	count?: number;
	/** For RESOLVE_BLOCKER: where to send the operator to clear the blocker. */
	actionRoute?: string;
}

/**
 * The single deterministic "what should I do next" recommendation. The operator
 * should never have to study the page to decide the next step.
 */
export function resolveNextAction(state: {
	hasProduct: boolean;
	recipeReady: boolean;
	counts: WorkflowCounts;
	/** When set, generation is blocked and resolving it is the ONLY next action. */
	blocker?: OperatorBlocker | null;
}): NextAction {
	const { hasProduct, recipeReady, counts, blocker } = state;
	if (!hasProduct) {
		return { step: "SETUP", kind: "SELECT_PRODUCT", label: "Select a product", detail: "Choose the product you want copy variations for." };
	}
	// A current preflight blocker (e.g. no approved Product Truth / no usable
	// evidence) always wins: never recommend Generate while generation is blocked.
	if (blocker) {
		return {
			step: "GENERATE",
			kind: "RESOLVE_BLOCKER",
			label: blocker.actionLabel ?? "Resolve blocker",
			detail: blocker.message,
			actionRoute: blocker.actionRoute,
		};
	}
	if (!recipeReady) {
		return { step: "SETUP", kind: "SETUP", label: "Set Up Campaign", detail: "Choose the goal, copy formula, and production scale." };
	}
	if (counts.reviewable > 0) {
		return {
			step: "REVIEW",
			kind: "REVIEW",
			label: `Review ${counts.reviewable} ${plural(counts.reviewable, "copy", "copies")}`,
			detail: "New copy is waiting for your approval.",
			count: counts.reviewable,
		};
	}
	const missing = missingCopies(counts);
	if (missing > 0) {
		return {
			step: "GENERATE",
			kind: "GENERATE",
			label: `Generate ${missing} missing ${plural(missing, "copy", "copies")}`,
			detail: "Create the copy still needed to reach your target.",
			count: missing,
		};
	}
	if (counts.needsPreparation > 0) {
		return {
			step: "PRODUCTION",
			kind: "PREPARE",
			label: `Prepare ${counts.needsPreparation} for Production`,
			detail: "Approved copy still needs preparation before production.",
			count: counts.needsPreparation,
		};
	}
	if ((counts.activationRequired ?? 0) > 0) {
		const activationRequired = counts.activationRequired ?? 0;
		return {
			step: "PRODUCTION",
			kind: "ACTIVATE",
			label: `Activate ${activationRequired} prepared ${plural(activationRequired, "copy", "copies")}`,
			detail: "Bind the exact prepared copy to the required standard lanes, or review the exact handoff below.",
			count: activationRequired,
		};
	}
	if (counts.approved > 0) {
		return { step: "PRODUCTION", kind: "OPEN_STUDIO", label: "Open Production Studio", detail: "Your copy supply is ready to produce." };
	}
	return {
		step: "GENERATE",
		kind: "GENERATE",
		label: `Generate ${counts.target || 0} ${plural(counts.target || 0, "copy", "copies")}`,
		detail: "Start generating copy for this product.",
		count: counts.target || 0,
	};
}

/**
 * Reconstruct the active wizard step from backend state (or honor an explicit
 * URL step so a refresh never bounces the operator to an unrelated place).
 */
export function reconstructStep(input: {
	urlStep?: string | null;
	hasProduct: boolean;
	recipeReady: boolean;
	reviewableCount: number;
	approvedCount: number;
}): WizardStep {
	const url = (input.urlStep ?? "").toUpperCase();
	if ((WIZARD_STEPS as readonly string[]).includes(url)) return url as WizardStep;
	if (!input.hasProduct) return "SETUP";
	// Existing copy is proof the campaign was set up, even when the recipe id is
	// not in client state yet (e.g. a fresh deep-link/refresh).
	if (input.reviewableCount > 0) return "REVIEW";
	if (input.approvedCount > 0) return "PRODUCTION";
	if (!input.recipeReady) return "SETUP";
	return "GENERATE";
}

export type PreflightState = "READY" | "ACTION REQUIRED";

export interface PreflightSummary {
	ready: boolean;
	productTruth: PreflightState;
	evidence: PreflightState;
	formula: string;
	target: number;
	existingApproved: number;
	missing: number;
	durations: number[];
	estimatedAiCalls: number;
	/** Copies this bounded run will produce (never a fabricated bulk number). */
	batchEstimate: number;
	blockers: OperatorBlocker[];
}

/**
 * The single primary gate blocker for the Copywriting Landbank, decided from the
 * Product Truth approval status (lineage.snapshot_status) and the current evidence
 * availability — NEVER from a raw fact count masquerading as truth approval.
 * Returns null when both are satisfied.
 */
export function resolvePrimaryTruthBlocker(input: {
	truthApproved: boolean;
	truthFactCount: number;
}): OperatorBlocker | null {
	if (!input.truthApproved) return blockerToOperator("PRODUCT_TRUTH_NOT_FOUND");
	if (input.truthFactCount <= 0) return blockerToOperator("NO_APPROVED_EVIDENCE");
	return null;
}

/**
 * Compose a deterministic, operator-friendly preflight from the plan + capacity.
 * When something blocks generation, it fails closed: `ready` is false and the
 * blockers carry operator-language messages plus a CTA, with the raw codes kept.
 */
export function buildPreflightSummary(input: {
	plan: V3AssistantPlan | null;
	capacity: V3ProductionCapacity | null;
	target: number;
	/** Whether the current Product Truth SNAPSHOT is approved (lineage.snapshot_status),
	 *  NOT whether facts exist. Truth approval and evidence availability are distinct. */
	truthApproved: boolean;
	/** Current derived evidence fact count for the product (V3 read model). */
	truthFactCount: number;
	planError?: string | null;
}): PreflightSummary {
	const approved = Math.max(0, input.capacity?.semantic_capacity ?? 0);
	const target = Math.max(0, Math.floor(input.target || 0));
	const missing = Math.max(0, target - approved);
	const plan = input.plan;
	const durations = plan?.target_durations_seconds && plan.target_durations_seconds.length ? plan.target_durations_seconds : [8, 16, 24];
	const gapTotal = (plan?.gaps ?? []).reduce((sum, gap) => sum + Math.max(0, gap.gap_count || 0), 0);
	// A run produces a bounded batch — take the plan's own bound, never invent one.
	const batchEstimate = plan ? Math.max(0, plan.max_proposals ?? gapTotal) : 0;

	const blockers: OperatorBlocker[] = [];
	if (input.planError && input.planError.trim()) {
		blockers.push(blockerToOperator(extractBlockerCode(input.planError), input.planError));
	}
	// Product Truth approval is decided ONLY by the snapshot status; evidence
	// availability is a SEPARATE state (an approved snapshot can still lack usable
	// current evidence facts). The two are surfaced as distinct badges + blockers.
	const productTruth: PreflightState = input.truthApproved ? "READY" : "ACTION REQUIRED";
	const evidence: PreflightState = input.truthApproved && input.truthFactCount > 0 ? "READY" : "ACTION REQUIRED";
	const truthBlocker = resolvePrimaryTruthBlocker({ truthApproved: input.truthApproved, truthFactCount: input.truthFactCount });
	if (!blockers.length && truthBlocker) {
		blockers.push(truthBlocker);
	}
	const ready = blockers.length === 0 && Boolean(plan);
	return {
		ready,
		productTruth,
		evidence,
		formula: plan?.formula?.formula_id ?? "—",
		target,
		existingApproved: approved,
		missing,
		durations,
		estimatedAiCalls: plan?.estimated_provider_calls ?? 0,
		batchEstimate,
		blockers,
	};
}

export interface ReviewBuckets {
	reviewable: number;
	passed: V3LandbankItem[];
	needsAttention: V3LandbankItem[];
	approved: V3LandbankItem[];
}

/**
 * Split the landbank into operator-facing review buckets:
 * PASS (hard-pass, not yet approved) vs NEEDS ATTENTION (failed a check) vs
 * already APPROVED. Terminal-but-not-approved rows (rejected/archived) are
 * excluded from the reviewable buckets.
 */
export function reviewBuckets(items: readonly V3LandbankItem[]): ReviewBuckets {
	const approved: V3LandbankItem[] = [];
	const passed: V3LandbankItem[] = [];
	const needsAttention: V3LandbankItem[] = [];
	const terminalNonApproved = new Set(["ARCHIVED", "REJECTED", "SUPERSEDED"]);
	for (const item of items) {
		const status = item.master.status;
		if (status === "APPROVED") {
			approved.push(item);
			continue;
		}
		if (terminalNonApproved.has(status)) continue;
		if (item.quality.hard_pass) passed.push(item);
		else needsAttention.push(item);
	}
	return { reviewable: passed.length + needsAttention.length, passed, needsAttention, approved };
}

/** Operator-language translation of a V2 materialization status. */
export function materializationToOperator(status: string | undefined | null): { label: string; tone: BadgeTone } {
	switch (status) {
		case "MATERIALIZED":
			return { label: "Production Ready", tone: "success" };
		case "STALE":
			return { label: "Needs Revalidation", tone: "warn" };
		case "BLOCKED":
			return { label: "Action Required", tone: "danger" };
		case "PARTIALLY_MATERIALIZED":
			return { label: "Partly Ready", tone: "info" };
		case "NOT_MATERIALIZED":
		default:
			return { label: "Needs Preparation", tone: "neutral" };
	}
}

/** Operator-language translation of a master storyboard status. */
export function masterStatusToOperator(status: string): { label: string; tone: BadgeTone } {
	switch (status) {
		case "APPROVED":
			return { label: "Approved", tone: "success" };
		case "VALIDATED":
			return { label: "Passed checks", tone: "info" };
		case "DRAFT":
			return { label: "Draft", tone: "warn" };
		case "REJECTED":
			return { label: "Rejected", tone: "danger" };
		case "ARCHIVED":
			return { label: "Archived", tone: "neutral" };
		case "SUPERSEDED":
			return { label: "Superseded", tone: "neutral" };
		case "FROZEN":
			return { label: "Locked", tone: "neutral" };
		default:
			return { label: status, tone: "neutral" };
	}
}

// The 4-tier capacity model, in operator language (section 12 of the brief). The
// technical tier names remain available under Technical Details.
export interface CapacityLabels {
	copyIdeas: number;
	durationVersions: number;
	productionReady: number;
	availableForProduction: number;
	needsRevalidation: number;
}

export function capacityLabels(capacity: V3ProductionCapacity | null): CapacityLabels {
	return {
		copyIdeas: Math.max(0, capacity?.semantic_capacity ?? 0),
		durationVersions: Math.max(0, capacity?.projection_capacity ?? 0),
		productionReady: Math.max(0, capacity?.executable_copy_capacity ?? 0),
		availableForProduction: Math.max(0, capacity?.production_capacity ?? 0),
		needsRevalidation: Math.max(0, capacity?.stale_copy_count ?? 0),
	};
}

// Approval checklist grouped into operator-facing sections (Content / Product
// Safety / Production Fit). The underlying 7 governed checklist keys are
// unchanged — only their presentation is grouped and given plain-language labels.
export interface ChecklistGroup {
	title: string;
	items: Array<{ key: string; label: string }>;
}

export const CHECKLIST_GROUPS: readonly ChecklistGroup[] = [
	{
		title: "Content",
		items: [
			{ key: "semantic_reviewed", label: "Meaning is correct" },
			{ key: "formula_reviewed", label: "Formula structure is correct" },
		],
	},
	{
		title: "Product safety",
		items: [
			{ key: "product_truth_reviewed", label: "Matches Product Truth" },
			{ key: "evidence_reviewed", label: "Claims are supported" },
			{ key: "safety_reviewed", label: "Claim safety is respected" },
		],
	},
	{
		title: "Production fit",
		items: [
			{ key: "bridge_reviewed", label: "Flow / bridge is coherent" },
			{ key: "duration_reviewed", label: "8s / 16s / 24s versions fit" },
		],
	},
];
