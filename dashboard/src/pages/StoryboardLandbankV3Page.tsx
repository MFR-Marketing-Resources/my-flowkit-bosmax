import { ArrowRight, BookOpen, CheckCircle2, ChevronRight, Film, PencilLine, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
	approveV3Master,
	approveV3MasterBatch,
	deleteV3Draft,
	executeV3Assistant,
	fetchV3AssistantPromptPreview,
	fetchV3CopyRegisterLandbank,
	fetchV3CopyRegisterProviderStatus,
	fetchV3ProductionCapacity,
	fetchV3ProductTruth,
	materializeV3Projection,
	materializeV3ProjectionsBulk,
	planV3Assistant,
	regenerateV3Component,
	reviewV3Entity,
	setupV3Campaign,
	type V3ApprovalChecklist,
	type V3AssistantPlan,
	type V3LandbankItem,
	type V3ProductionCapacity,
	type V3ProviderStatus,
	type V3RecipePreset,
	type V3TruthFact,
} from "../api/storyboardLandbankV3Round2";
import { fetchProductDetail } from "../api/products";
import { Badge, FormField, HelperText, Section, TechnicalDetails, type BadgeTone } from "../components/ui";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import { useProductCatalog } from "../hooks/useProductCatalog";
import type { Product } from "../types";
import {
	buildPreflightSummary,
	capacityLabels,
	CHECKLIST_GROUPS,
	inferAssistantMode,
	masterStatusToOperator,
	materializationToOperator,
	missingCopies,
	reconstructStep,
	resolveNextAction,
	resolvePrimaryTruthBlocker,
	reviewBuckets,
	STEP_META,
	toOperatorError,
	WIZARD_STEPS,
	type WizardStep,
	type WorkflowCounts,
} from "../utils/storyboardLandbankResolver";

// Operator-facing goal + formula + scale vocabulary. The technical presets stay
// as the underlying values (the recipe/WPS/mode are all resolved for the operator).
const GOAL_OPTIONS = ["conversion", "awareness", "consideration", "retention"];
const FORMULA_OPTIONS = ["PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"];
const SCALE_OPTIONS: Array<{ value: V3RecipePreset; label: string; hint: string }> = [
	{ value: "QUICK TEST", label: "Quick test", hint: "A few copies to sanity-check" },
	{ value: "FAST54", label: "Fast (54)", hint: "A full production batch" },
	{ value: "MULTI-ANGLE", label: "Multi-angle", hint: "Spread across angles" },
	{ value: "SCALE", label: "Scale", hint: "Large volume" },
	{ value: "CUSTOM", label: "Custom", hint: "Set your own target" },
];

const INPUT_CLASS = "mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200";

const EMPTY_CHECKLIST: V3ApprovalChecklist = {
	semantic_reviewed: false,
	product_truth_reviewed: false,
	formula_reviewed: false,
	evidence_reviewed: false,
	bridge_reviewed: false,
	safety_reviewed: false,
	duration_reviewed: false,
};

function errorMessage(error: unknown): string {
	if (!(error instanceof Error)) return "Copywriting Landbank request failed.";
	const start = error.message.indexOf("{");
	if (start < 0) return error.message;
	try {
		const payload = JSON.parse(error.message.slice(start));
		const detail = payload?.detail;
		if (detail?.code && detail?.message) return `${detail.code}: ${detail.message}`;
	} catch {
		// Keep the transport message when the server returned non-JSON text.
	}
	return error.message;
}

function productName(product: Product | null): string {
	if (!product) return "";
	return product.product_display_name || product.raw_product_title || product.id;
}

// Approved projections that still need preparation into production (clean or
// stale), receipt-bound. "Prepare All Clean" stays limited to genuinely-clean
// (NOT_MATERIALIZED) projections; this wider set only powers the summary count.
const PREPARE_BULK_LIMIT = 25;
function collectCleanPrepareTargets(items: readonly V3LandbankItem[]): Array<{ projectionId: string; receiptId: string }> {
	const targets: Array<{ projectionId: string; receiptId: string }> = [];
	for (const item of items) {
		const receiptId = typeof item.approval_receipt?.receipt_id === "string" ? item.approval_receipt.receipt_id : "";
		if (!receiptId) continue;
		for (const projection of item.projections) {
			if ((projection.materialization?.status ?? "NOT_MATERIALIZED") === "NOT_MATERIALIZED") {
				targets.push({ projectionId: projection.projection_id, receiptId });
			}
		}
	}
	return targets.slice(0, PREPARE_BULK_LIMIT);
}
function countNeedsPreparation(items: readonly V3LandbankItem[]): number {
	let count = 0;
	for (const item of items) {
		const hasReceipt = typeof item.approval_receipt?.receipt_id === "string";
		if (!hasReceipt) continue;
		for (const projection of item.projections) {
			const status = projection.materialization?.status ?? "NOT_MATERIALIZED";
			if (status === "NOT_MATERIALIZED" || status === "STALE") count += 1;
		}
	}
	return count;
}

// Plain-language quality warnings from the governed quality booleans, so a
// "needs attention" card explains itself without exposing raw issue codes.
function qualityWarnings(item: V3LandbankItem): string[] {
	const quality = item.quality;
	const warnings: string[] = [];
	if (!quality.formula_valid) warnings.push("Formula structure needs attention");
	if (!quality.evidence_valid) warnings.push("A claim needs supporting evidence");
	if (!quality.claim_safety_valid) warnings.push("A claim may be unsafe");
	if (!quality.bridge_valid) warnings.push("The flow between scenes needs attention");
	if (!quality.truth_current) warnings.push("Product Truth changed — needs revalidation");
	if (!quality.wps_valid) warnings.push("A duration version doesn't fit its time budget");
	return warnings;
}

function GroupedChecklist({ value, onChange }: { value: V3ApprovalChecklist; onChange: (next: V3ApprovalChecklist) => void }) {
	return (
		<div className="space-y-3" data-testid="v3-approval-checklist">
			{CHECKLIST_GROUPS.map((group) => (
				<div key={group.title} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
					<div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{group.title}</div>
					<div className="mt-2 grid gap-2 sm:grid-cols-2">
						{group.items.map((entry) => {
							const key = entry.key as keyof V3ApprovalChecklist;
							return (
								<label key={entry.key} className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs text-slate-300">
									<input type="checkbox" checked={value[key]} onChange={(event) => onChange({ ...value, [key]: event.target.checked })} data-testid={`v3-check-${entry.key}`} />
									{entry.label}
								</label>
							);
						})}
					</div>
				</div>
			))}
		</div>
	);
}

// A single copy, in operator language. The engineering identifiers (ids,
// revisions, digests, evidence fact ids, review verbs) live in the per-card
// Technical Details drawer.
function CopyCard({
	item,
	onApprove,
	onReview,
	onRegenerate,
	onDeleteDraft,
}: {
	item: V3LandbankItem;
	onApprove?: (item: V3LandbankItem) => void;
	onReview?: (action: "validate" | "submit" | "reject" | "archive", item: V3LandbankItem) => void;
	onRegenerate?: (ref: { entity_id: string; revision: number }, item: V3LandbankItem) => void;
	onDeleteDraft?: (item: V3LandbankItem) => void;
}) {
	const terminal = ["APPROVED", "ARCHIVED", "REJECTED", "SUPERSEDED", "FROZEN"].includes(item.master.status);
	const warnings = qualityWarnings(item);
	const statusChip = masterStatusToOperator(item.master.status);
	const componentRef = (item.master.resolved_component_refs ?? [])[0];
	return (
		<article className="rounded-xl border border-slate-800 bg-slate-950/70 p-4" data-testid="v3-copy-card">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div className="flex flex-wrap items-center gap-2">
					<Badge tone={statusChip.tone}>{statusChip.label}</Badge>
					<Badge tone={item.quality.hard_pass ? "success" : "warn"}>{item.quality.hard_pass ? "Passed checks" : "Needs attention"}</Badge>
					<span className="text-[11px] text-slate-500">{item.master.formula.formula_id} · {item.master.word_count} words</span>
				</div>
				<div className="text-right text-[11px] text-slate-500">Quality {Math.round(item.quality.quality_score * 100)}%</div>
			</div>

			<div className="mt-3 space-y-2" data-testid="v3-copy-body">
				{item.master.stages.map((stage, index) => (
					<div key={stage.stage_key} className="rounded-lg border border-slate-800 bg-slate-900/80 p-3">
						<div className="text-[10px] font-bold uppercase tracking-wide text-blue-200">{index + 1}. {stage.formula_stage_key}</div>
						<p className="mt-1 text-sm leading-6 text-slate-200">{stage.authored_text}</p>
					</div>
				))}
			</div>

			<div className="mt-3">
				<div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Duration versions</div>
				<div className="mt-2 grid gap-2 md:grid-cols-3" data-testid="v3-duration-versions">
					{item.projections.map((projection) => (
						<div key={projection.projection_id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
							<div className="text-[10px] font-bold uppercase text-emerald-200">{projection.target_duration_seconds}s version</div>
							<p className="mt-1 text-xs leading-5 text-slate-300">{projection.exact_resolved_dialogue}</p>
							{projection.stage_allocations?.some((allocation) => allocation.transform_mode === "COMPRESSED") ? (
								<div className="mt-2 text-[10px] font-bold uppercase text-amber-200">Shortened to fit — review recommended</div>
							) : null}
						</div>
					))}
				</div>
			</div>

			{warnings.length ? (
				<div className="mt-3 flex flex-wrap gap-2" data-testid="v3-copy-warnings">
					{warnings.map((warning) => (
						<span key={warning} className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] font-semibold text-amber-100">{warning}</span>
					))}
				</div>
			) : null}

			<div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3">
				<div className="flex flex-wrap gap-2">
					{onReview && !terminal ? (
						<button type="button" onClick={() => onReview("reject", item)} className="rounded-lg border border-amber-600/50 px-3 py-1.5 text-[11px] font-semibold text-amber-200" data-testid="v3-action-reject">Reject</button>
					) : null}
					{onRegenerate && !terminal && componentRef ? (
						<button type="button" onClick={() => onRegenerate(componentRef, item)} className="inline-flex items-center gap-1 rounded-lg border border-violet-600/50 px-3 py-1.5 text-[11px] font-semibold text-violet-200" data-testid="v3-action-regenerate"><PencilLine size={12} /> Edit / Regenerate</button>
					) : null}
					{onDeleteDraft && item.master.status === "DRAFT" ? (
						<button type="button" onClick={() => onDeleteDraft(item)} className="rounded-lg border border-rose-600/50 px-3 py-1.5 text-[11px] font-semibold text-rose-200" data-testid="v3-action-delete">Delete draft</button>
					) : null}
				</div>
				{onApprove && item.master.status !== "APPROVED" ? (
					<button type="button" onClick={() => onApprove(item)} className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-100" data-testid="v3-open-approval">Approve <ChevronRight size={14} /></button>
				) : item.master.status === "APPROVED" ? (
					<span className="inline-flex items-center gap-1 text-xs text-emerald-200" data-testid="v3-approved-badge"><CheckCircle2 size={14} /> Approved</span>
				) : null}
			</div>

			<TechnicalDetails className="mt-3" testId="v3-card-technical" title="Technical details">
				<div className="grid gap-1 text-[11px] text-slate-400 sm:grid-cols-2">
					<div>Master: <span className="font-mono">{item.master.master_id}</span> · rev {item.master.revision}</div>
					<div>Recipe: <span className="font-mono">{item.master.recipe?.entity_id || "—"}</span></div>
					<div>Novelty: {item.quality.novelty_signal}</div>
					<div>Content digest: <span className="font-mono">{item.master.exact_content_digest.slice(0, 12)}…</span></div>
					<div className="sm:col-span-2">Claim evidence: {item.master.stages.filter((stage) => stage.claim_bearing).flatMap((stage) => stage.evidence_fact_ids ?? []).join(", ") || "none required"}</div>
				</div>
				{onReview && !terminal ? (
					<div className="mt-2 flex flex-wrap gap-1" data-testid="v3-review-actions">
						<button type="button" onClick={() => onReview("validate", item)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300" data-testid="v3-action-validate">Validate</button>
						<button type="button" onClick={() => onReview("submit", item)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300" data-testid="v3-action-submit">Submit for review</button>
						<button type="button" onClick={() => onReview("archive", item)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400" data-testid="v3-action-archive">Archive</button>
					</div>
				) : null}
			</TechnicalDetails>
		</article>
	);
}

// Operator "Prepare for Production" panel (V2 materialization under the hood).
function PreparePanel({ item, busy, onPrepare }: { item: V3LandbankItem; busy: boolean; onPrepare: (projectionId: string, receiptId: string) => void }) {
	const receiptId = typeof item.approval_receipt?.receipt_id === "string" ? item.approval_receipt.receipt_id : "";
	const rollup = materializationToOperator(item.v2_materialization === "NOT_IN_ROUND2" ? "NOT_MATERIALIZED" : item.v2_materialization);
	return (
		<div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3" data-testid="v3-prepare-panel">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Production readiness</div>
				<span data-testid="v3-prepare-rollup"><Badge tone={rollup.tone}>{rollup.label}</Badge></span>
			</div>
			<div className="mt-2 space-y-2">
				{item.projections.map((projection) => {
					const status = projection.materialization?.status ?? "NOT_MATERIALIZED";
					const reason = projection.materialization?.reason;
					const label = materializationToOperator(status);
					const canPrepare = (status === "NOT_MATERIALIZED" || status === "STALE") && Boolean(receiptId);
					const hint = !receiptId
						? "Approve this copy before preparing it for production."
						: status === "MATERIALIZED"
							? "Already prepared for production."
							: status === "BLOCKED"
								? "Blocked — resolve the issue before preparing."
								: "Prepare this approved copy for production.";
					return (
						<div key={projection.projection_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
							<div className="flex flex-wrap items-center gap-2">
								<span className="text-[11px] font-bold uppercase text-slate-300">{projection.target_duration_seconds}s</span>
								<span title={reason ? `Reason: ${reason}` : undefined} data-testid={`v3-prepare-chip-${projection.projection_id}`}><Badge tone={label.tone}>{label.label}</Badge></span>
							</div>
							<button type="button" disabled={busy || !canPrepare} onClick={() => onPrepare(projection.projection_id, receiptId)} title={hint} className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] font-bold text-emerald-100 disabled:opacity-40" data-testid={`v3-prepare-${projection.projection_id}`}>Prepare for Production</button>
						</div>
					);
				})}
			</div>
			{!receiptId ? <HelperText className="mt-2">Approve this copy before it can be prepared for production.</HelperText> : null}
		</div>
	);
}

function SummaryTile({ label, value, tone = "neutral", testId }: { label: string; value: number | string; tone?: BadgeTone; testId?: string }) {
	const toneClass: Record<BadgeTone, string> = {
		neutral: "text-slate-100",
		info: "text-blue-200",
		success: "text-emerald-200",
		warn: "text-amber-200",
		danger: "text-rose-200",
	};
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3" data-testid={testId}>
			<div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
			<div className={`mt-1 text-2xl font-bold ${toneClass[tone]}`}>{value}</div>
		</div>
	);
}

export default function StoryboardLandbankV3Page() {
	const navigate = useNavigate();
	const [searchParams, setSearchParams] = useSearchParams();
	const { products, isLoadingProducts, productsError } = useProductCatalog(50);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [provider, setProvider] = useState<V3ProviderStatus | null>(null);

	// Operator business inputs.
	const [objectiveId, setObjectiveId] = useState("conversion");
	const [formulaId, setFormulaId] = useState("PAS");
	const [preset, setPreset] = useState<V3RecipePreset>("FAST54");
	const [targetCapacity, setTargetCapacity] = useState("54");
	const [durationMix, setDurationMix] = useState<Record<number, boolean>>({ 8: true, 16: true, 24: true });

	// Auto-resolved settings (surfaced only under Advanced).
	const [languageProfile, setLanguageProfile] = useState("Malay");
	const [wpsModeSel, setWpsModeSel] = useState<"SAFE" | "SWEET">("SWEET");
	const [recipeId, setRecipeId] = useState("");

	// Data.
	const [truthFacts, setTruthFacts] = useState<V3TruthFact[]>([]);
	const [truthApproved, setTruthApproved] = useState(false);
	const [capacity, setCapacity] = useState<V3ProductionCapacity | null>(null);
	const [items, setItems] = useState<V3LandbankItem[]>([]);
	const [landbankOffset, setLandbankOffset] = useState(0);
	const [landbankHasMore, setLandbankHasMore] = useState(false);

	// Generate / preflight.
	const [plan, setPlan] = useState<V3AssistantPlan | null>(null);
	const [planError, setPlanError] = useState("");
	const [promptDigest, setPromptDigest] = useState("");
	const [preflightBusy, setPreflightBusy] = useState(false);

	// Review filters (Advanced only).
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [durationFilter, setDurationFilter] = useState("ALL");
	const [searchFilter, setSearchFilter] = useState("");

	// Approval / delete.
	const [approvalItem, setApprovalItem] = useState<V3LandbankItem | null>(null);
	const [deleteItem, setDeleteItem] = useState<V3LandbankItem | null>(null);
	const [bulkApproval, setBulkApproval] = useState(false);
	const [checklist, setChecklist] = useState<V3ApprovalChecklist>(EMPTY_CHECKLIST);
	const [reviewer, setReviewer] = useState("operator");
	const [rationale, setRationale] = useState("Reviewed against the displayed Product Truth, formula, evidence, flow, safety, and duration versions.");

	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");

	useEffect(() => {
		void fetchV3CopyRegisterProviderStatus().then(setProvider).catch((reason) => setError(toOperatorError(errorMessage(reason))));
	}, []);

	// Deep-link resolution guard: at most one by-id fetch per product_id, and the
	// result is applied only while the URL still points at that product — so a
	// re-render (e.g. the catalog window refreshing) can never cancel an in-flight
	// resolve, and a stale resolve can never override a newer selection.
	const deepLinkResolveRef = useRef<string | null>(null);
	useEffect(() => {
		const productId = searchParams.get("product_id");
		if (!productId || selectedProduct?.id === productId) return;
		// Cheap path: the deep-linked product is already in the loaded first-page
		// catalog window (useProductCatalog(50)).
		const inWindow = products.find((item) => item.id === productId);
		if (inWindow) {
			setSelectedProduct(inWindow);
			return;
		}
		// Deep-link fallback: the product sorts outside the first-page window.
		// Resolve the EXACT product by id — a single deterministic fetch, never a
		// full-catalog load, and never a silent substitution of another product.
		// Wait for the window to finish loading first so the common in-window case
		// skips the network entirely.
		if (isLoadingProducts) return;
		if (deepLinkResolveRef.current === productId) return;
		deepLinkResolveRef.current = productId;
		void fetchProductDetail(productId)
			.then((product) => {
				if (deepLinkResolveRef.current === product.id) setSelectedProduct(product);
			})
			.catch((reason) => {
				if (deepLinkResolveRef.current !== productId) return;
				if ((reason as { name?: string })?.name === "AbortError") return;
				setError(
					`We couldn't open the copy landbank for that product link (${productId}). It may have been removed — pick a product to continue.`,
				);
			});
	}, [products, isLoadingProducts, searchParams, selectedProduct?.id]);

	useEffect(() => {
		if (!selectedProduct) {
			setTruthFacts([]);
			setTruthApproved(false);
			setCapacity(null);
			return;
		}
		void fetchV3ProductTruth(selectedProduct.id)
			.then((response) => {
				setTruthFacts(response.facts ?? []);
				// Product Truth approval is decided by the snapshot lineage status
				// from the SAME call — never inferred from the fact count.
				const status = (response.lineage as { snapshot_status?: unknown } | null)?.snapshot_status;
				setTruthApproved(String(status ?? "").toUpperCase() === "APPROVED");
			})
			.catch((reason) => setError(toOperatorError(errorMessage(reason))));
		void fetchV3ProductionCapacity(selectedProduct.id)
			.then(setCapacity)
			.catch((reason) => setError(toOperatorError(errorMessage(reason))));
	}, [selectedProduct?.id]);

	const loadLandbank = async (productId: string, offset = 0, append = false) => {
		const response = await fetchV3CopyRegisterLandbank(productId, {
			status: statusFilter !== "ALL" ? statusFilter : undefined,
			duration_seconds: durationFilter !== "ALL" ? Number(durationFilter) : undefined,
			search: searchFilter.trim() || undefined,
			offset,
		});
		setItems((previous) => (append ? [...previous, ...(response.items ?? [])] : response.items ?? []));
		setLandbankOffset(response.offset + (response.items?.length ?? 0));
		setLandbankHasMore(Boolean(response.has_more));
	};

	useEffect(() => {
		if (!selectedProduct) {
			setItems([]);
			setLandbankOffset(0);
			setLandbankHasMore(false);
			return;
		}
		setLandbankOffset(0);
		void loadLandbank(selectedProduct.id, 0, false).catch((reason) => setError(toOperatorError(errorMessage(reason))));
		// Filter changes intentionally re-read the bounded landbank.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [selectedProduct?.id, statusFilter, durationFilter, searchFilter]);

	const buckets = useMemo(() => reviewBuckets(items), [items]);
	const target = Number(targetCapacity) || 0;
	const approvedCount = capacity?.semantic_capacity ?? buckets.approved.length;
	const productionReadyCount = capacity?.production_capacity ?? 0;
	const missing = missingCopies({ target, approved: approvedCount });
	const cleanPrepareTargets = useMemo(() => collectCleanPrepareTargets(buckets.approved), [buckets.approved]);
	const needsPreparation = useMemo(() => countNeedsPreparation(buckets.approved), [buckets.approved]);

	const counts: WorkflowCounts = {
		target,
		approved: approvedCount,
		reviewable: buckets.reviewable,
		productionReady: productionReadyCount,
		needsPreparation,
		needsRevalidation: capacity?.stale_copy_count ?? 0,
	};

	// The primary Product Truth / evidence gate, decided from the snapshot approval
	// status (lineage) + current evidence availability — surfaced identically in the
	// preflight and the Next Action so they can never contradict each other.
	const primaryTruthBlocker = useMemo(
		() => (selectedProduct ? resolvePrimaryTruthBlocker({ truthApproved, truthFactCount: truthFacts.length }) : null),
		[selectedProduct, truthApproved, truthFacts.length],
	);

	const nextAction = useMemo(
		() => resolveNextAction({ hasProduct: Boolean(selectedProduct), recipeReady: Boolean(recipeId), counts, blocker: primaryTruthBlocker }),
		// counts is derived; depend on its scalar members to avoid a churn loop.
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[selectedProduct, recipeId, target, approvedCount, buckets.reviewable, productionReadyCount, needsPreparation, capacity?.stale_copy_count, primaryTruthBlocker],
	);

	const urlStep = searchParams.get("step");
	const step: WizardStep = useMemo(
		() =>
			reconstructStep({
				urlStep,
				hasProduct: Boolean(selectedProduct),
				recipeReady: Boolean(recipeId),
				reviewableCount: buckets.reviewable,
				approvedCount: buckets.approved.length,
			}),
		[urlStep, selectedProduct, recipeId, buckets.reviewable, buckets.approved.length],
	);

	const preflight = useMemo(
		() => buildPreflightSummary({ plan, capacity, target, truthApproved, truthFactCount: truthFacts.length, planError }),
		[plan, capacity, target, truthApproved, truthFacts.length, planError],
	);

	const goToStep = (next: WizardStep) => {
		const params: Record<string, string> = {};
		if (selectedProduct) params.product_id = selectedProduct.id;
		params.step = next;
		setSearchParams(params);
	};

	const selectProduct = (product: Product | null) => {
		setSelectedProduct(product);
		const params: Record<string, string> = {};
		if (product) params.product_id = product.id;
		setSearchParams(params);
		setRecipeId("");
		setPlan(null);
		setPlanError("");
		setApprovalItem(null);
		setBulkApproval(false);
		setTruthFacts([]);
		setTruthApproved(false);
		setSuccess("");
		setError("");
	};

	// Deterministic preflight: ensure the recipe exists (idempotent reuse), then
	// compute the gap plan. Provider-free — no copy is generated here.
	const runPreflight = async () => {
		if (!selectedProduct) return;
		setPreflightBusy(true);
		setPlanError("");
		try {
			let rid = recipeId;
			if (!rid) {
				const durations = Object.entries(durationMix).filter(([, on]) => on).map(([duration]) => Number(duration));
				const setup = await setupV3Campaign({
					product_id: selectedProduct.id,
					objective_id: objectiveId.trim() || "conversion",
					objective_definition: objectiveId.trim() || "conversion",
					formula_id: formulaId,
					preset,
					supported_durations_seconds: durations.length ? durations : [8, 16, 24],
					target_capacity: target || undefined,
					language_profile: languageProfile,
					wps_mode: wpsModeSel,
				});
				rid = setup.recipe_id;
				setRecipeId(rid);
			}
			const mode = inferAssistantMode({ existingApproved: approvedCount, target });
			const response = await planV3Assistant({ product_id: selectedProduct.id, recipe_id: rid, mode, target_capacity: target || undefined });
			setPlan(response.plan);
		} catch (reason) {
			setPlanError(errorMessage(reason));
		} finally {
			setPreflightBusy(false);
		}
	};

	// When the operator reaches Generate with a resolved campaign but no plan yet,
	// compute the preflight automatically (still no generation).
	useEffect(() => {
		if (step !== "GENERATE" || !selectedProduct) return;
		if (plan || planError || preflightBusy) return;
		void runPreflight();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [step, selectedProduct?.id, recipeId, plan, planError, preflightBusy]);

	const handleCreateCampaign = async () => {
		if (!selectedProduct) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const durations = Object.entries(durationMix).filter(([, on]) => on).map(([duration]) => Number(duration));
			const response = await setupV3Campaign({
				product_id: selectedProduct.id,
				objective_id: objectiveId.trim() || "conversion",
				objective_definition: objectiveId.trim() || "conversion",
				formula_id: formulaId,
				preset,
				supported_durations_seconds: durations.length ? durations : [8, 16, 24],
				target_capacity: target || undefined,
				language_profile: languageProfile,
				wps_mode: wpsModeSel,
			});
			setRecipeId(response.recipe_id);
			setPlan(null);
			setPlanError("");
			setSuccess(`Campaign ready. ${missing > 0 ? `You can now generate the ${missing} missing ${missing === 1 ? "copy" : "copies"}.` : "You can now review and prepare your copy."}`);
			goToStep("GENERATE");
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const refreshProductData = async (productId: string) => {
		await Promise.all([
			fetchV3ProductionCapacity(productId).then(setCapacity).catch(() => undefined),
			loadLandbank(productId).catch(() => undefined),
		]);
	};

	const generateLane: "LIVE_TEXT_ASSIST" | "FAKE_TEST" | null = provider?.configured
		? "LIVE_TEXT_ASSIST"
		: provider?.fake_provider_allowed
			? "FAKE_TEST"
			: null;

	const handleGenerate = async () => {
		if (!plan || !selectedProduct || !generateLane || !preflight.ready) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			await executeV3Assistant(plan.plan_id, generateLane);
			setSuccess(
				generateLane === "FAKE_TEST"
					? "Copy generated in test mode — review it in step 3. No credits were spent."
					: "Copy generated — review it in step 3.",
			);
			setPlan(null); // recompute the preflight for the next copy.
			await refreshProductData(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handlePreview = async () => {
		if (!plan) return;
		setBusy(true);
		setError("");
		try {
			const response = await fetchV3AssistantPromptPreview(plan.plan_id);
			setPromptDigest(response.preview.prompt_digest);
			setSuccess("Prompt preview loaded. Product Truth is shown as untrusted data; no provider call was made.");
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handleReview = async (action: "validate" | "submit" | "reject" | "archive", item: V3LandbankItem) => {
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			await reviewV3Entity(action, "MASTER_STORYBOARD", item.master.master_id, item.master.revision);
			setSuccess(`Copy ${action} recorded.`);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handleRegenerate = async (ref: { entity_id: string; revision: number }) => {
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const response = await regenerateV3Component(ref.entity_id, ref.revision, provider?.configured ? "LIVE_TEXT_ASSIST" : "FAKE_TEST");
			setSuccess(`Copy regenerated (version ${response.source_revision} → ${response.new_revision}). It stays unapproved until you approve it.`);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handleDeleteDraft = async () => {
		if (!deleteItem) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			await deleteV3Draft("MASTER_STORYBOARD", deleteItem.master.master_id, deleteItem.master.revision);
			setSuccess(`Draft ${deleteItem.master.master_id} deleted.`);
			setDeleteItem(null);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handleApprove = async () => {
		if (!approvalItem || !reviewer.trim() || !Object.values(checklist).every(Boolean)) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			if (bulkApproval) {
				const targets = buckets.passed.map((item) => ({
					master_id: item.master.master_id,
					projection_ids: item.projections.map((projection) => ({ entity_id: projection.projection_id, revision: projection.revision })),
				}));
				const response = await approveV3MasterBatch({ targets, approved_by: reviewer.trim(), rationale, checklist });
				setSuccess(`Approved ${response.approved_count} ${response.approved_count === 1 ? "copy" : "copies"}. They are ready to prepare for production.`);
			} else {
				await approveV3Master({
					master_id: approvalItem.master.master_id,
					projection_ids: approvalItem.projections.map((projection) => ({ entity_id: projection.projection_id, revision: projection.revision })),
					approved_by: reviewer.trim(),
					rationale,
					checklist,
				});
				setSuccess("Copy approved. It is ready to prepare for production.");
			}
			setApprovalItem(null);
			setBulkApproval(false);
			setChecklist(EMPTY_CHECKLIST);
			if (selectedProduct) await refreshProductData(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handlePrepare = async (projectionId: string, receiptId: string) => {
		if (!selectedProduct || !projectionId || !receiptId) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const result = await materializeV3Projection({ productId: selectedProduct.id, projectionId, receiptId });
			setSuccess(`Copy prepared for production${result.idempotent_reuse ? " (already prepared)" : ""}.`);
			await refreshProductData(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const handlePrepareAllClean = async () => {
		if (!selectedProduct || !cleanPrepareTargets.length) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const result = await materializeV3ProjectionsBulk({ items: cleanPrepareTargets });
			setSuccess(`Prepared ${result.materialized_count} for production${result.blocked_count ? `, ${result.blocked_count} still need attention` : ""}.`);
			await refreshProductData(selectedProduct.id);
		} catch (reason) {
			setError(toOperatorError(errorMessage(reason)));
		} finally {
			setBusy(false);
		}
	};

	const openProductionStudio = () => {
		navigate(selectedProduct ? `/production-studio?product_id=${encodeURIComponent(selectedProduct.id)}` : "/production-studio");
	};

	const handleNextAction = () => {
		if (nextAction.kind === "OPEN_STUDIO") {
			openProductionStudio();
			return;
		}
		// A blocker points at its own resolution route (e.g. approve Product Truth
		// in Products); carry the product context so the operator lands in place.
		if (nextAction.kind === "RESOLVE_BLOCKER" && nextAction.actionRoute) {
			navigate(selectedProduct ? `${nextAction.actionRoute}?product_id=${encodeURIComponent(selectedProduct.id)}` : nextAction.actionRoute);
			return;
		}
		goToStep(nextAction.step);
	};

	const allChecks = Object.values(checklist).every(Boolean);
	const capacityView = capacityLabels(capacity);

	return (
		<div className="mx-auto max-w-5xl space-y-6 p-4 md:p-8" data-testid="storyboard-landbank-v3-page">
			<header className="border-b border-slate-800 pb-5">
				<div className="flex items-center gap-2 text-violet-300"><Sparkles size={18} /><span className="text-[10px] font-bold uppercase tracking-[0.2em]">Copy supply</span></div>
				<h1 className="mt-1 text-2xl font-bold text-slate-100">Copywriting Landbank</h1>
				<p className="mt-1 text-sm text-slate-400" data-testid="v3-product-name">{selectedProduct ? productName(selectedProduct) : "Select a product to begin."}</p>
			</header>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="v3-error">{error}</p> : null}
			{success ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="v3-success">{success}</p> : null}

			{/* Real wizard progress: the active step dominates; visited steps are clickable. */}
			<ol className="grid gap-2 sm:grid-cols-4" data-testid="v3-wizard-progress">
				{WIZARD_STEPS.map((wizardStep) => {
					const meta = STEP_META[wizardStep];
					const active = step === wizardStep;
					const reachable = Boolean(selectedProduct);
					return (
						<li key={wizardStep}>
							<button
								type="button"
								disabled={!reachable}
								onClick={() => goToStep(wizardStep)}
								aria-current={active ? "step" : undefined}
								className={`w-full rounded-lg border px-3 py-2 text-left disabled:opacity-40 ${active ? "border-violet-500/60 bg-violet-500/10" : "border-slate-800 bg-slate-950/60"}`}
								data-testid={`v3-step-${wizardStep.toLowerCase()}`}
							>
								<span className={`text-[10px] font-bold uppercase ${active ? "text-violet-100" : "text-slate-500"}`}>{meta.index}. {meta.label}</span>
								<span className="mt-0.5 block text-xs text-slate-400">{meta.blurb}</span>
							</button>
						</li>
					);
				})}
			</ol>

			{selectedProduct ? (
				<div className="grid gap-2 sm:grid-cols-4" data-testid="v3-status-summary">
					<SummaryTile label="Target" value={target} testId="v3-summary-target" />
					<SummaryTile label="Approved" value={approvedCount} tone="success" testId="v3-summary-approved" />
					<SummaryTile label="Production Ready" value={productionReadyCount} tone="info" testId="v3-summary-production-ready" />
					<SummaryTile label="Missing" value={missing} tone={missing > 0 ? "warn" : "neutral"} testId="v3-summary-missing" />
				</div>
			) : null}

			{/* STEP 1 — SETUP */}
			{step === "SETUP" ? (
				<Section title="Setup" helper="Choose the product and what copy you want. Everything technical is configured for you.">
					<div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,320px)]">
						<div>
							<SearchableProductSelect products={products} selectedProduct={selectedProduct} onSelect={selectProduct} isLoadingProducts={isLoadingProducts} productsError={productsError} showReadinessBadge={false} />
							<div className="mt-4 grid gap-3 sm:grid-cols-2">
								<FormField label="Goal"><select className={INPUT_CLASS} value={objectiveId} onChange={(event) => setObjectiveId(event.target.value)} data-testid="v3-goal">{GOAL_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}</select></FormField>
								<FormField label="Copy formula"><select className={INPUT_CLASS} value={formulaId} onChange={(event) => setFormulaId(event.target.value)} data-testid="v3-formula">{FORMULA_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}</select></FormField>
								<FormField label="Production scale"><select className={INPUT_CLASS} value={preset} onChange={(event) => setPreset(event.target.value as V3RecipePreset)} data-testid="v3-scale">{SCALE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label} — {option.hint}</option>)}</select></FormField>
								<FormField label="Target copy count"><input className={INPUT_CLASS} value={targetCapacity} onChange={(event) => setTargetCapacity(event.target.value)} placeholder="54" data-testid="v3-target" inputMode="numeric" /></FormField>
								<FormField label="Duration mix"><div className="mt-1 flex gap-3">{[8, 16, 24].map((duration) => <label key={duration} className="flex items-center gap-1 text-xs text-slate-300"><input type="checkbox" checked={Boolean(durationMix[duration])} onChange={(event) => setDurationMix((previous) => ({ ...previous, [duration]: event.target.checked }))} data-testid={`v3-duration-${duration}`} />{duration}s</label>)}</div></FormField>
							</div>
							<HelperText className="mt-3">The copy recipe, evidence selection, writing style, and AI settings are all resolved for you. You only choose the business decisions above.</HelperText>
							<div className="mt-4 flex flex-wrap items-center gap-3">
								<button type="button" disabled={busy || !selectedProduct} onClick={() => void handleCreateCampaign()} className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-create-campaign">Create copy campaign <ChevronRight size={14} /></button>
								{recipeId ? <span className="inline-flex items-center gap-1 text-[11px] font-bold uppercase text-emerald-300" data-testid="v3-campaign-ready"><CheckCircle2 size={13} /> Campaign ready</span> : null}
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
							<div className="text-xs font-bold uppercase text-slate-300">Approved Product Truth</div>
							<HelperText className="mt-1">Copy is only built from approved Product Truth. It is shown for review and never edited here.</HelperText>
							<div className="mt-2 text-2xl font-bold text-emerald-200" data-testid="v3-truth-count">{truthFacts.length}</div>
							<div className="text-[10px] uppercase tracking-wide text-slate-500">approved facts available</div>
						</div>
					</div>

					<TechnicalDetails className="mt-4" testId="v3-setup-technical" title="Advanced / technical details">
						<div className="grid gap-3 sm:grid-cols-2">
							<FormField label="Recipe ID (override)"><input className={INPUT_CLASS} value={recipeId} onChange={(event) => setRecipeId(event.target.value)} placeholder="recipe_… (auto-resolved)" data-testid="v3-recipe-id" /></FormField>
							<FormField label="Language"><input className={INPUT_CLASS} value={languageProfile} onChange={(event) => setLanguageProfile(event.target.value)} data-testid="v3-language" /></FormField>
							<FormField label="WPS mode"><select className={INPUT_CLASS} value={wpsModeSel} onChange={(event) => setWpsModeSel(event.target.value as "SAFE" | "SWEET")} data-testid="v3-wps-mode"><option value="SAFE">SAFE</option><option value="SWEET">SWEET</option></select></FormField>
							<div className="text-[11px] text-slate-500">Assistant mode is inferred from current supply: {inferAssistantMode({ existingApproved: approvedCount, target })}.</div>
						</div>
						<HelperText className="mt-2">Recipe ID, language, WPS mode, evidence fact IDs, and V2/V3 authority live here. Normal operators never need them.</HelperText>
						<a href={`/creative/copy-registry${selectedProduct ? `?product_id=${encodeURIComponent(selectedProduct.id)}` : ""}`} className="mt-2 inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-200" data-testid="v3-open-v2-register"><BookOpen size={12} /> Open V2 production Copy Register (advanced)</a>
					</TechnicalDetails>
				</Section>
			) : null}

			{/* STEP 2 — GENERATE */}
			{step === "GENERATE" ? (
				<Section title="Generate" helper="One deterministic preflight, then a single explicit Generate. Nothing is generated until you press Generate.">
					{preflightBusy && !plan ? <div className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-400" data-testid="v3-preflight-loading">Checking readiness…</div> : null}
					{preflight.ready && plan ? (
						<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4" data-testid="v3-preflight-ready">
							<div className="text-xs font-bold uppercase tracking-wide text-emerald-200">Ready to generate</div>
							<div className="mt-3 grid gap-2 text-sm text-slate-200 sm:grid-cols-2">
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Product Truth <Badge tone="success">{preflight.productTruth}</Badge></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Evidence <Badge tone="success">{preflight.evidence}</Badge></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Formula <span className="font-semibold">{preflight.formula}</span></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Target <span className="font-semibold">{preflight.target}</span></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Approved so far <span className="font-semibold">{preflight.existingApproved}</span></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Still missing <span className="font-semibold text-amber-200">{preflight.missing}</span></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Durations <span className="font-semibold">{preflight.durations.map((duration) => `${duration}s`).join(" / ")}</span></div>
								<div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">Estimated AI calls <span className="font-semibold">{preflight.estimatedAiCalls}</span></div>
							</div>
							<div className="mt-4 flex flex-wrap items-center gap-3">
								<button type="button" disabled={busy || !generateLane} onClick={() => void handleGenerate()} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40" data-testid="v3-generate" title={generateLane ? undefined : "The AI copywriter is not connected yet."}><Wand2 size={15} /> {missing > 0 ? "Generate missing copy" : "Generate another copy"}</button>
								<HelperText>Each run adds one reviewable copy with {preflight.durations.map((duration) => `${duration}s`).join(" / ")} versions. {generateLane === "FAKE_TEST" ? "Test mode is active — zero credits." : missing > 0 ? `${missing} still missing.` : "Target reached."}</HelperText>
							</div>
						</div>
					) : null}
					{!preflight.ready && (plan || planError) ? (
						<div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4" data-testid="v3-preflight-blocked">
							<div className="text-xs font-bold uppercase tracking-wide text-amber-200">Action required</div>
							{preflight.blockers.map((blocker) => (
								<div key={blocker.code} className="mt-2">
									<p className="text-sm text-slate-200">{blocker.message}</p>
									{blocker.actionLabel ? (
										blocker.actionRoute ? (
											<button type="button" onClick={() => navigate(`${blocker.actionRoute}${selectedProduct ? `?product_id=${encodeURIComponent(selectedProduct.id)}` : ""}`)} className="mt-2 inline-flex items-center gap-1 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-1.5 text-xs font-bold text-amber-100" data-testid="v3-blocker-action">{blocker.actionLabel} <ChevronRight size={13} /></button>
										) : (
											<button type="button" onClick={() => goToStep("SETUP")} className="mt-2 inline-flex items-center gap-1 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-1.5 text-xs font-bold text-amber-100" data-testid="v3-blocker-action">{blocker.actionLabel} <ChevronRight size={13} /></button>
										)
									) : null}
									<TechnicalDetails className="mt-2" testId="v3-blocker-technical" title="Technical details">
										<div className="font-mono text-[11px] text-slate-400">{blocker.code}</div>
									</TechnicalDetails>
								</div>
							))}
						</div>
					) : null}

					<TechnicalDetails className="mt-4" testId="v3-generate-technical" title="Advanced / technical details">
						<div className="flex flex-wrap items-center gap-2">
							<button type="button" disabled={busy || !plan} onClick={() => void handlePreview()} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 disabled:opacity-40" data-testid="v3-prompt-preview">Preview AI prompt</button>
							<span className="text-[11px] text-slate-500">Provider: {provider?.configured ? `${provider.provider_id} · ${provider.model_id}` : provider?.fake_provider_allowed ? "test mode" : "not connected"} · calls {provider?.provider_calls ?? 0} · credit {provider?.credit_spend ?? 0}</span>
						</div>
						{plan ? <div className="mt-2 text-[11px] text-slate-500">Plan {plan.plan_id} · mode {plan.mode} · recipe {plan.recipe.entity_id} · WPS {plan.wps_mode} · evidence {plan.evidence_fact_ids?.length ?? 0} fact(s)</div> : null}
						{promptDigest ? <div className="mt-1 font-mono text-[10px] text-slate-500" data-testid="v3-prompt-digest">Prompt digest: {promptDigest}</div> : null}
					</TechnicalDetails>
				</Section>
			) : null}

			{/* STEP 3 — REVIEW */}
			{step === "REVIEW" ? (
				<Section title="Review" helper="Read each copy, then Approve, Edit, or Reject. Approval records a governed human sign-off.">
					<div className="mb-4 grid gap-2 sm:grid-cols-4" data-testid="v3-review-summary">
						<SummaryTile label="Generated" value={buckets.reviewable} testId="v3-review-generated" />
						<SummaryTile label="Passed checks" value={buckets.passed.length} tone="success" testId="v3-review-passed" />
						<SummaryTile label="Needs attention" value={buckets.needsAttention.length} tone={buckets.needsAttention.length ? "warn" : "neutral"} testId="v3-review-attention" />
						<SummaryTile label="Approved" value={buckets.approved.length} tone="info" testId="v3-review-approved" />
					</div>

					{buckets.passed.length ? (
						<div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3" data-testid="v3-bulk-approval-panel">
							<div>
								<div className="text-xs font-bold uppercase text-emerald-100">Approve passed copies together</div>
								<HelperText className="mt-1">{buckets.passed.length} {buckets.passed.length === 1 ? "copy" : "copies"} passed every check. Approve them with one governed sign-off.</HelperText>
							</div>
							<button type="button" disabled={busy || !buckets.passed.length} onClick={() => { setBulkApproval(true); setApprovalItem(buckets.passed[0]); }} className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-100 disabled:opacity-40" data-testid="v3-open-bulk-approval">Approve {buckets.passed.length}</button>
						</div>
					) : null}

					{buckets.reviewable ? (
						<div className="space-y-4">
							{[...buckets.passed, ...buckets.needsAttention].map((item) => (
								<CopyCard key={`${item.master.master_id}:${item.master.revision}`} item={item} onReview={handleReview} onApprove={(target) => { setBulkApproval(false); setApprovalItem(target); }} onRegenerate={(ref) => void handleRegenerate(ref)} onDeleteDraft={(target) => setDeleteItem(target)} />
							))}
							{landbankHasMore && selectedProduct ? <button type="button" disabled={busy} onClick={() => void loadLandbank(selectedProduct.id, landbankOffset, true)} className="w-full rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 disabled:opacity-40" data-testid="v3-load-more">Load more</button> : null}
						</div>
					) : (
						<div className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-500" data-testid="v3-empty-review">No copy is waiting for review. Generate copy in step 2, or check the Approved copies in step 4.</div>
					)}

					<TechnicalDetails className="mt-4" testId="v3-review-technical" title="Advanced / filters">
						<div className="grid gap-2 sm:grid-cols-3">
							<input className={INPUT_CLASS} value={searchFilter} onChange={(event) => setSearchFilter(event.target.value)} placeholder="Search copy" data-testid="v3-search-filter" />
							<select className={INPUT_CLASS} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} data-testid="v3-status-filter"><option value="ALL">All statuses</option><option value="DRAFT">Draft</option><option value="VALIDATED">Passed checks</option><option value="APPROVED">Approved</option></select>
							<select className={INPUT_CLASS} value={durationFilter} onChange={(event) => setDurationFilter(event.target.value)} data-testid="v3-duration-filter"><option value="ALL">All durations</option><option value="8">8s</option><option value="16">16s</option><option value="24">24s</option></select>
						</div>
					</TechnicalDetails>
				</Section>
			) : null}

			{/* STEP 4 — PRODUCTION READY */}
			{step === "PRODUCTION" ? (
				<Section title="Production Ready" helper="Prepare approved copy for production, then hand it to Production Studio.">
					<div className="mb-4 grid gap-2 sm:grid-cols-3" data-testid="v3-production-summary">
						<SummaryTile label="Approved" value={approvedCount} tone="success" testId="v3-production-approved" />
						<SummaryTile label="Production Ready" value={productionReadyCount} tone="info" testId="v3-production-ready" />
						<SummaryTile label="Needs preparation" value={needsPreparation} tone={needsPreparation ? "warn" : "neutral"} testId="v3-production-needs-prep" />
					</div>

					<div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
						<div>
							<div className="text-xs font-bold uppercase text-slate-300">Prepare approved copy</div>
							<HelperText className="mt-1">Preparing turns approved copy into production-ready supply. Nothing is prepared until you press the button.</HelperText>
						</div>
						<button type="button" disabled={busy || !cleanPrepareTargets.length} onClick={() => void handlePrepareAllClean()} className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-100 disabled:opacity-40" data-testid="v3-prepare-all">Prepare {cleanPrepareTargets.length} for Production</button>
					</div>

					{productionReadyCount > 0 ? (
						<div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-violet-500/30 bg-violet-500/5 p-4" data-testid="v3-supply-ready">
							<div>
								<div className="text-xs font-bold uppercase text-violet-200">Copy supply ready</div>
								<HelperText className="mt-1">{productionReadyCount} production-ready {productionReadyCount === 1 ? "copy is" : "copies are"} available for this product.</HelperText>
							</div>
							<button type="button" onClick={openProductionStudio} className="inline-flex items-center gap-1 rounded-lg bg-violet-600 px-4 py-2 text-xs font-bold text-white" data-testid="v3-open-production-studio"><Film size={14} /> Open Production Studio</button>
						</div>
					) : null}

					{buckets.approved.length ? (
						<div className="space-y-4">
							{buckets.approved.map((item) => (
								<div key={`approved:${item.master.master_id}:${item.master.revision}`} data-testid="v3-approved-item">
									<CopyCard item={item} />
									<PreparePanel item={item} busy={busy} onPrepare={handlePrepare} />
								</div>
							))}
						</div>
					) : (
						<div className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-500" data-testid="v3-empty-production">No approved copy yet. Approve copy in step 3 to prepare it for production.</div>
					)}

					<TechnicalDetails className="mt-4" testId="v3-production-technical" title="Advanced / capacity model">
						<div className="grid gap-1 text-[11px] text-slate-400 sm:grid-cols-2">
							<div>Copy Ideas (SEMANTIC): {capacityView.copyIdeas}</div>
							<div>Duration Versions (PROJECTION): {capacityView.durationVersions}</div>
							<div>Production Ready (EXECUTABLE_COPY): {capacityView.productionReady}</div>
							<div>Available for Production (PRODUCTION): {capacityView.availableForProduction}</div>
							<div>Needs Revalidation (STALE): {capacityView.needsRevalidation}</div>
						</div>
						{capacity?.production_capacity_note ? <HelperText className="mt-2">{capacity.production_capacity_note}</HelperText> : null}
					</TechnicalDetails>
				</Section>
			) : null}

			{/* Next Action appears AFTER the active step + preflight, so the operator
			    understands the current state before seeing the recommendation. */}
			{selectedProduct ? (
				<div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-violet-500/30 bg-violet-500/5 p-4" data-testid="v3-next-action">
					<div>
						<div className="text-[10px] font-bold uppercase tracking-wide text-violet-200">Next step</div>
						<div className="mt-1 text-base font-bold text-slate-100" data-testid="v3-next-action-label">{nextAction.label}</div>
						<p className="text-xs text-slate-400">{nextAction.detail}</p>
					</div>
					<button type="button" onClick={handleNextAction} className="inline-flex items-center gap-1 rounded-lg bg-violet-600 px-4 py-2 text-xs font-bold text-white" data-testid="v3-next-action-go">
						{nextAction.kind === "OPEN_STUDIO" ? <Film size={14} /> : <ArrowRight size={14} />} {nextAction.kind === "OPEN_STUDIO" ? "Open Production Studio" : "Go"}
					</button>
				</div>
			) : null}

			{/* Approval dialog — grouped checklist, all 7 governed checks preserved. */}
			{approvalItem ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" data-testid="v3-approval-dialog">
					<div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-emerald-500/30 bg-slate-950 p-6">
						<div className="flex items-start justify-between gap-4">
							<div>
								<div className="text-xs font-bold uppercase tracking-wide text-emerald-200">{bulkApproval ? "Approve copies" : "Approve copy"}</div>
								<h2 className="mt-1 text-lg font-bold text-slate-100">{bulkApproval ? `Approve ${buckets.passed.length} passed ${buckets.passed.length === 1 ? "copy" : "copies"}?` : "Approve this copy?"}</h2>
							</div>
							<button type="button" onClick={() => { setApprovalItem(null); setBulkApproval(false); }} className="text-slate-400" aria-label="Close approval">✕</button>
						</div>
						<p className="mt-3 text-xs leading-5 text-slate-400">Confirm every check below. Approval records a governed human sign-off; it does not spend any credits or start production.</p>
						<div className="mt-4 grid gap-3 sm:grid-cols-2">
							<FormField label="Reviewer"><input className={INPUT_CLASS} value={reviewer} onChange={(event) => setReviewer(event.target.value)} data-testid="v3-reviewer" /></FormField>
							<FormField label="Notes"><textarea className={`${INPUT_CLASS} min-h-20`} value={rationale} onChange={(event) => setRationale(event.target.value)} data-testid="v3-rationale" /></FormField>
						</div>
						<div className="mt-4"><GroupedChecklist value={checklist} onChange={setChecklist} /></div>
						<div className="mt-4 flex justify-end gap-2">
							<button type="button" onClick={() => { setApprovalItem(null); setBulkApproval(false); }} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">Cancel</button>
							<button type="button" disabled={busy || !allChecks || !reviewer.trim() || rationale.trim().length < 8} onClick={() => void handleApprove()} className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid={bulkApproval ? "v3-approve-batch" : "v3-approve-master"}>{bulkApproval ? "Approve all" : "Approve"}</button>
						</div>
					</div>
				</div>
			) : null}

			{/* Delete-draft confirmation. */}
			{deleteItem ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" data-testid="v3-delete-dialog">
					<div className="w-full max-w-md rounded-2xl border border-rose-500/30 bg-slate-950 p-6">
						<div className="text-xs font-bold uppercase tracking-wide text-rose-200">Delete draft</div>
						<h2 className="mt-1 text-lg font-bold text-slate-100">Delete this draft copy?</h2>
						<p className="mt-3 text-xs leading-5 text-slate-400">Only an unused draft can be removed. Approved or referenced copy is never deleted.</p>
						<div className="mt-4 flex justify-end gap-2">
							<button type="button" onClick={() => setDeleteItem(null)} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300" data-testid="v3-delete-cancel">Cancel</button>
							<button type="button" disabled={busy} onClick={() => void handleDeleteDraft()} className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-delete-confirm">Delete draft</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}
