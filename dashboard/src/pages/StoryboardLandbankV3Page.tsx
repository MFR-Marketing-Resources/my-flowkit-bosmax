import { BookOpen, CheckCircle2, ChevronRight, ClipboardCheck, Eye, LockKeyhole, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
	approveV3Master,
	approveV3MasterBatch,
	executeV3Assistant,
	fetchV3AssistantPromptPreview,
	fetchV3CopyRegisterLandbank,
	fetchV3CopyRegisterProviderStatus,
	fetchV3ProductTruth,
	planV3Assistant,
	deleteV3Draft,
	regenerateV3Component,
	reviewV3Entity,
	setupV3Campaign,
	type V3AssistantMode,
	type V3AssistantPlan,
	type V3ApprovalChecklist,
	type V3LandbankItem,
	type V3ProviderStatus,
	type V3RecipePreset,
	type V3TruthFact,
} from "../api/storyboardLandbankV3Round2";

const RECIPE_PRESETS: V3RecipePreset[] = ["QUICK TEST", "FAST54", "MULTI-ANGLE", "SCALE", "CUSTOM"];
const FORMULA_OPTIONS = ["PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"];
import { Badge, FormField, HelperText, Section } from "../components/ui";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";
import { useProductCatalog } from "../hooks/useProductCatalog";

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
	if (!(error instanceof Error)) return "V3 Copy Register request failed.";
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

function statusTone(status: string): "success" | "warn" | "danger" | "neutral" {
	if (status === "APPROVED" || status === "VALIDATED" || status === "EXECUTED") return "success";
	if (status === "BLOCKED" || status === "FAILED") return "danger";
	return "warn";
}

function Checklist({ value, onChange }: { value: V3ApprovalChecklist; onChange: (next: V3ApprovalChecklist) => void }) {
	const labels: Array<[keyof V3ApprovalChecklist, string]> = [
		["semantic_reviewed", "Semantic review"],
		["product_truth_reviewed", "Product Truth"],
		["formula_reviewed", "Formula route"],
		["evidence_reviewed", "Evidence"],
		["bridge_reviewed", "Bridge continuity"],
		["safety_reviewed", "Claim safety"],
		["duration_reviewed", "8 / 16 / 24 WPS"],
	];
	return (
		<div className="grid gap-2 sm:grid-cols-2" data-testid="v3-approval-checklist">
			{labels.map(([key, label]) => (
				<label key={key} className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
					<input type="checkbox" checked={value[key]} onChange={(event) => onChange({ ...value, [key]: event.target.checked })} data-testid={`v3-check-${key}`} />
					{label}
				</label>
			))}
		</div>
	);
}

function StoryboardCard({ item, onApprove, onReview, onRegenerate, onDeleteDraft }: { item: V3LandbankItem; onApprove: (item: V3LandbankItem) => void; onReview?: (action: "validate" | "submit" | "reject" | "archive", item: V3LandbankItem) => void; onRegenerate?: (ref: { entity_id: string; revision: number }, item: V3LandbankItem) => void; onDeleteDraft?: (item: V3LandbankItem) => void }) {
	const terminal = ["APPROVED", "ARCHIVED", "REJECTED", "SUPERSEDED", "FROZEN"].includes(item.master.status);
	const [activeDuration, setActiveDuration] = useState<number | null>(null);
	const focusedProjection = activeDuration ? item.projections.find((projection) => projection.target_duration_seconds === activeDuration) : null;
	return (
		<article className="rounded-xl border border-slate-800 bg-slate-950/70 p-4" data-testid="v3-storyboard-card">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<div className="flex flex-wrap items-center gap-2">
						<span className="font-semibold text-sm text-slate-100">{item.master.master_id}</span>
						<Badge tone={statusTone(item.master.status)}>{item.master.status}</Badge>
						<Badge tone={item.quality.hard_pass ? "success" : "warn"}>{item.quality.novelty_signal}</Badge>
					</div>
					<p className="mt-1 text-xs text-slate-500">{item.master.formula.formula_id} · {item.master.word_count} words · {item.master.source}</p>
					<p className="mt-1 text-[10px] text-slate-500">Objective: {item.master.objective?.definition || "locked V3 objective"} · Recipe: {item.master.recipe?.entity_id || "—"}</p>
				</div>
				<div className="text-right text-[11px] text-slate-500">Quality {Math.round(item.quality.quality_score * 100)}%<br />{item.projections.length} projections</div>
			</div>

			<div className="mt-3 space-y-2" data-testid="v3-full-storyboard">
				{item.master.stages.map((stage, index) => (
					<div key={stage.stage_key} className="rounded-lg border border-slate-800 bg-slate-900/80 p-3">
						<div className="text-[10px] font-bold uppercase tracking-wide text-blue-200">{index + 1}. {stage.formula_stage_key} · {stage.semantic_class}</div>
						<p className="mt-1 text-sm leading-6 text-slate-200">{stage.authored_text}</p>
						<div className="mt-2 text-[10px] text-slate-500">{stage.claim_bearing ? `Claim evidence: ${(stage.evidence_fact_ids ?? []).join(", ") || "MISSING"}` : "Non-claim stage"}</div>
					</div>
				))}
			</div>

			<div className="mt-3 flex flex-wrap items-center gap-2" role="tablist" aria-label="Duration projections" data-testid="v3-projection-tabs">
				{[8, 16, 24].map((duration) => <button key={duration} type="button" role="tab" aria-selected={activeDuration === duration} onClick={() => setActiveDuration(activeDuration === duration ? null : duration)} className={`rounded-lg border px-3 py-1 text-[10px] font-bold uppercase ${activeDuration === duration ? "border-emerald-400/60 bg-emerald-500/10 text-emerald-100" : "border-slate-700 text-slate-400"}`}>{duration}s tab</button>)}
				{focusedProjection ? <span className="text-[10px] text-emerald-200">Focus: {focusedProjection.target_duration_seconds}s · {focusedProjection.wps_mode || "SAFE"} WPS</span> : <span className="text-[10px] text-slate-500">All projection authorities remain visible below.</span>}
			</div>
			<div className="mt-2 grid gap-2 md:grid-cols-3" data-testid="v3-projection-grid">
				{item.projections.map((projection) => (
					<div key={projection.projection_id} className={`rounded-lg border bg-slate-900/60 p-3 ${activeDuration === projection.target_duration_seconds ? "border-emerald-400/60" : "border-slate-800"}`}>
						<div className="flex items-center justify-between text-[10px] font-bold uppercase text-emerald-200"><span>{projection.target_duration_seconds}s projection</span><span>{projection.status}</span></div>
						<p className="mt-2 text-xs leading-5 text-slate-300">{projection.exact_resolved_dialogue}</p>
						<div className="mt-2 text-[10px] text-slate-500">{projection.derivation_source} · {projection.wps_mode || "SAFE"} WPS · budgets [{projection.per_block_word_budgets.join(", ")}]</div>
						{projection.stage_allocations?.some((allocation) => allocation.transform_mode === "COMPRESSED") ? <div className="mt-2 text-[10px] font-bold uppercase text-amber-200">Mechanical compression · human review required</div> : null}
					</div>
				))}
			</div>

			<div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3">
				{onReview && !terminal ? <div className="flex flex-wrap gap-1" data-testid="v3-review-actions"><button type="button" onClick={() => onReview("validate", item)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300" data-testid="v3-action-validate">Validate</button><button type="button" onClick={() => onReview("submit", item)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300" data-testid="v3-action-submit">Submit for review</button><button type="button" onClick={() => onReview("reject", item)} className="rounded border border-amber-600/50 px-2 py-1 text-[10px] text-amber-200" data-testid="v3-action-reject">Reject</button><button type="button" onClick={() => onReview("archive", item)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400" data-testid="v3-action-archive">Archive</button>{onRegenerate && (item.master.resolved_component_refs ?? []).length ? <button type="button" onClick={() => onRegenerate((item.master.resolved_component_refs ?? [])[0], item)} className="rounded border border-violet-600/50 px-2 py-1 text-[10px] text-violet-200" data-testid="v3-action-regenerate">Regenerate</button> : null}{onDeleteDraft && item.master.status === "DRAFT" ? <button type="button" onClick={() => onDeleteDraft(item)} className="rounded border border-rose-600/50 px-2 py-1 text-[10px] text-rose-200" data-testid="v3-action-delete">Delete Draft</button> : null}</div> : <div className="text-[11px] text-slate-500">Truth current: {item.current_truth ? "YES" : "NO"} · V2/P6: {item.v2_materialization}/{item.p6_status}</div>}
				{item.master.status !== "APPROVED" ? <button type="button" onClick={() => onApprove(item)} className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-100" data-testid="v3-open-approval">Open human approval <ChevronRight size={14} className="inline" /></button> : <span className="inline-flex items-center gap-1 text-xs text-emerald-200"><CheckCircle2 size={14} /> Receipt recorded</span>}
			</div>
		</article>
	);
}

export default function StoryboardLandbankV3Page() {
	const [searchParams, setSearchParams] = useSearchParams();
	const { products, isLoadingProducts, productsError } = useProductCatalog(50);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [provider, setProvider] = useState<V3ProviderStatus | null>(null);
	const [recipeId, setRecipeId] = useState("");
	const [objectiveId, setObjectiveId] = useState("conversion");
	const [formulaId, setFormulaId] = useState("PAS");
	const [preset, setPreset] = useState<V3RecipePreset>("FAST54");
	const [durationMix, setDurationMix] = useState<Record<number, boolean>>({ 8: true, 16: true, 24: true });
	const [targetCapacity, setTargetCapacity] = useState("54");
	const [languageProfile, setLanguageProfile] = useState("Malay");
	const [wpsModeSel, setWpsModeSel] = useState<"SAFE" | "SWEET">("SWEET");
	const [mode, setMode] = useState<V3AssistantMode>("CREATE");
	const [plan, setPlan] = useState<V3AssistantPlan | null>(null);
	const [promptDigest, setPromptDigest] = useState("");
	const [truthFacts, setTruthFacts] = useState<V3TruthFact[]>([]);
	const [evidenceSearch, setEvidenceSearch] = useState("");
	const [items, setItems] = useState<V3LandbankItem[]>([]);
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [durationFilter, setDurationFilter] = useState("ALL");
	const [formulaFilter, setFormulaFilter] = useState("");
	const [angleFilter, setAngleFilter] = useState("");
	const [storylineFilter, setStorylineFilter] = useState("");
	const [recipeFilter, setRecipeFilter] = useState("");
	const [searchFilter, setSearchFilter] = useState("");
	const [sourceFilter, setSourceFilter] = useState("ALL");
	const [qualityFilter, setQualityFilter] = useState("ALL");
	const [blockerFilter, setBlockerFilter] = useState("");
	const [landbankOffset, setLandbankOffset] = useState(0);
	const [landbankHasMore, setLandbankHasMore] = useState(false);
	const [activeJob, setActiveJob] = useState<"SETUP" | "BUILD" | "REVIEW" | "LANDBANK">("SETUP");
	const [approvalItem, setApprovalItem] = useState<V3LandbankItem | null>(null);
	const [deleteItem, setDeleteItem] = useState<V3LandbankItem | null>(null);
	const [bulkApproval, setBulkApproval] = useState(false);
	const [checklist, setChecklist] = useState<V3ApprovalChecklist>(EMPTY_CHECKLIST);
	const [reviewer, setReviewer] = useState("operator");
	const [rationale, setRationale] = useState("Reviewed against the displayed V3 Product Truth, formula, evidence, bridge, safety, and WPS projections.");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");

	useEffect(() => {
		void fetchV3CopyRegisterProviderStatus().then(setProvider).catch((reason) => setError(errorMessage(reason)));
	}, []);

	useEffect(() => {
		const productId = searchParams.get("product_id");
		if (!productId || !products.length) return;
		const product = products.find((item) => item.id === productId);
		if (product && product.id !== selectedProduct?.id) setSelectedProduct(product);
	}, [products, searchParams, selectedProduct?.id]);

	useEffect(() => {
		if (!selectedProduct) {
			setTruthFacts([]);
			return;
		}
		void fetchV3ProductTruth(selectedProduct.id)
			.then((response) => setTruthFacts(response.facts ?? []))
			.catch((reason) => setError(errorMessage(reason)));
	}, [selectedProduct?.id]);

	const loadLandbank = async (productId: string, offset = 0, append = false) => {
		const response = await fetchV3CopyRegisterLandbank(productId, {
			status: statusFilter !== "ALL" ? statusFilter : undefined,
			duration_seconds: durationFilter !== "ALL" ? Number(durationFilter) : undefined,
			formula_id: formulaFilter.trim() || undefined,
			angle_id: angleFilter.trim() || undefined,
			storyline_family_id: storylineFilter.trim() || undefined,
			recipe_id: recipeFilter.trim() || undefined,
			source: sourceFilter !== "ALL" ? sourceFilter : undefined,
			quality: qualityFilter !== "ALL" ? qualityFilter : undefined,
			blocker: blockerFilter.trim() || undefined,
			search: searchFilter.trim() || undefined,
			offset,
		});
		setItems((previous) => append ? [...previous, ...(response.items ?? [])] : (response.items ?? []));
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
		void loadLandbank(selectedProduct.id, 0, false).catch((reason) => setError(errorMessage(reason)));
		// Filter changes intentionally re-read the bounded V3 projection.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [selectedProduct?.id, statusFilter, durationFilter, formulaFilter, angleFilter, storylineFilter, recipeFilter, searchFilter, sourceFilter, qualityFilter, blockerFilter]);

	const selectProduct = (product: Product | null) => {
		setSelectedProduct(product);
		setSearchParams(product ? { product_id: product.id } : {});
		setPlan(null);
		setApprovalItem(null);
		setBulkApproval(false);
		setTruthFacts([]);
		setSuccess("");
		setError("");
	};

	const handlePlan = async () => {
		if (!selectedProduct || !recipeId.trim()) return;
		setBusy(true); setError(""); setSuccess("");
		try {
			const response = await planV3Assistant({ product_id: selectedProduct.id, recipe_id: recipeId.trim(), mode });
			setPlan(response.plan);
			setActiveJob("BUILD");
			setSuccess(`Plan ${response.plan.plan_id} created. Execution remains an explicit operator action.`);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleBuildCampaign = async () => {
		if (!selectedProduct) return;
		setBusy(true); setError(""); setSuccess("");
		try {
			const durations = Object.entries(durationMix).filter(([, on]) => on).map(([duration]) => Number(duration));
			const response = await setupV3Campaign({
				product_id: selectedProduct.id,
				objective_id: objectiveId.trim() || "conversion",
				objective_definition: objectiveId.trim() || "conversion",
				formula_id: formulaId,
				preset,
				supported_durations_seconds: durations.length ? durations : [8, 16, 24],
				target_capacity: Number(targetCapacity) || undefined,
				language_profile: languageProfile,
				wps_mode: wpsModeSel,
			});
			setRecipeId(response.recipe_id);
			setSuccess(`Recipe ${response.recipe_id} ${response.reused ? "reused" : "created"} from the ${response.preset} preset. Plan the assistant run next.`);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleReview = async (action: "validate" | "submit" | "reject" | "archive", item: V3LandbankItem) => {
		setBusy(true); setError(""); setSuccess("");
		try {
			await reviewV3Entity(action, "MASTER_STORYBOARD", item.master.master_id, item.master.revision);
			setSuccess(`Master ${item.master.master_id}: ${action} recorded. Immutable revisions are never edited in place.`);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleRegenerate = async (ref: { entity_id: string; revision: number }, _item: V3LandbankItem) => {
		setBusy(true); setError(""); setSuccess("");
		try {
			const response = await regenerateV3Component(ref.entity_id, ref.revision, provider?.configured ? "LIVE_TEXT_ASSIST" : "FAKE_TEST");
			setSuccess(`Component ${ref.entity_id} regenerated: revision ${response.source_revision} → ${response.new_revision}. Parent revision preserved; never auto-approved.`);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleDeleteDraft = async () => {
		if (!deleteItem) return;
		setBusy(true); setError(""); setSuccess("");
		try {
			await deleteV3Draft("MASTER_STORYBOARD", deleteItem.master.master_id, deleteItem.master.revision);
			setSuccess(`Draft ${deleteItem.master.master_id} safe-deleted. Referenced or non-DRAFT rows are blocked server-side.`);
			setDeleteItem(null);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handlePreview = async () => {
		if (!plan) return;
		setBusy(true); setError("");
		try {
			const response = await fetchV3AssistantPromptPreview(plan.plan_id);
			setPromptDigest(response.preview.prompt_digest);
			setSuccess("Prompt preview loaded. Product Truth is displayed as untrusted data; no provider call was made.");
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleExecute = async () => {
		if (!plan || !provider?.fake_provider_allowed) return;
		setBusy(true); setError(""); setSuccess("");
		try {
			await executeV3Assistant(plan.plan_id, "FAKE_TEST");
			setSuccess("Fake-provider run completed. Components, Master, and deterministic 8/16/24 projections are reviewable; provider calls and credit spend are zero.");
			setActiveJob("REVIEW");
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleGenerateLive = async () => {
		if (!plan || !provider?.configured) return;
		setBusy(true); setError(""); setSuccess("");
		try {
			await executeV3Assistant(plan.plan_id, "LIVE_TEXT_ASSIST");
			setSuccess("Live text_assist run completed. Components, Master, and deterministic 8/16/24 projections are reviewable; media credits remain zero.");
			setActiveJob("REVIEW");
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const handleApprove = async () => {
		if (!approvalItem || !reviewer.trim() || !Object.values(checklist).every(Boolean)) return;
		setBusy(true); setError(""); setSuccess("");
		try {
			if (bulkApproval) {
				const targets = visibleItems
					.filter((item) => item.master.status !== "APPROVED" && item.quality.hard_pass)
					.map((item) => ({
						master_id: item.master.master_id,
						projection_ids: item.projections.map((projection) => ({ entity_id: projection.projection_id, revision: projection.revision })),
					}));
				const response = await approveV3MasterBatch({ targets, approved_by: reviewer.trim(), rationale, checklist });
				setSuccess(`Human batch approval receipt recorded for ${response.approved_count} storyboard(s)${response.batch_digest ? ` · batch digest ${response.batch_digest.slice(0, 12)}…` : ""}. No V2 activation or materialization was performed.`);
			} else {
				await approveV3Master({
					master_id: approvalItem.master.master_id,
					projection_ids: approvalItem.projections.map((projection) => ({ entity_id: projection.projection_id, revision: projection.revision })),
					approved_by: reviewer.trim(), rationale, checklist,
				});
				setSuccess("Human approval receipt recorded. The V3 approved artifact remains separate from V2 activation/materialization.");
			}
			setApprovalItem(null);
			setBulkApproval(false);
			setChecklist(EMPTY_CHECKLIST);
			if (selectedProduct) await loadLandbank(selectedProduct.id);
		} catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
	};

	const visibleItems = useMemo(() => items, [items]);
	const bulkCandidates = useMemo(() => visibleItems.filter((item) => item.master.status !== "APPROVED" && item.quality.hard_pass), [visibleItems]);
	const bulkExceptions = useMemo(() => visibleItems.filter((item) => item.master.status !== "APPROVED" && !item.quality.hard_pass), [visibleItems]);
	const approvedItems = useMemo(() => items.filter((item) => item.master.status === "APPROVED"), [items]);
	const visibleTruthFacts = useMemo(() => {
		const query = evidenceSearch.trim().toLowerCase();
		if (!query) return truthFacts;
		return truthFacts.filter((fact) => `${fact.fact_id} ${fact.fact_kind} ${fact.text}`.toLowerCase().includes(query));
	}, [evidenceSearch, truthFacts]);
	const allChecks = Object.values(checklist).every(Boolean);

	return (
		<div className="mx-auto max-w-7xl space-y-6 p-4 md:p-8" data-testid="storyboard-landbank-v3-page">
			<header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-5">
				<div>
					<div className="flex items-center gap-2 text-violet-300"><Sparkles size={20} /><span className="text-[10px] font-bold uppercase tracking-[0.2em]">V3 Supply Plane</span></div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100">Storyboard Copy Register</h1>
					<p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">Formula-driven Copy Register V3: build bounded components, compile the complete Master first, derive deterministic duration projections, then record explicit human approval.</p>
					<div className="mt-2 flex flex-wrap gap-2 text-[10px] font-bold uppercase"><span className="rounded border border-violet-500/40 bg-violet-500/10 px-2 py-1 text-violet-200">V3 ACTIVE</span><span className="rounded border border-slate-700 px-2 py-1 text-slate-400">V2 production authority stays separate</span></div>
				</div>
				<a href={`/creative/copy-registry${selectedProduct ? `?product_id=${encodeURIComponent(selectedProduct.id)}` : ""}`} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:border-slate-500" data-testid="v3-open-v2-register"><BookOpen size={14} className="mr-1 inline" /> Open V2 Copy Register</a>
			</header>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="v3-error">{error}</p> : null}
			{success ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="v3-success">{success}</p> : null}

			<div className="grid gap-2 sm:grid-cols-4" data-testid="v3-operator-jobs">
				{(["SETUP", "BUILD", "REVIEW", "LANDBANK"] as const).map((job, index) => <button key={job} type="button" onClick={() => setActiveJob(job)} className={`rounded-lg border px-3 py-2 text-left ${activeJob === job ? "border-violet-500/60 bg-violet-500/10" : "border-slate-800 bg-slate-950/60"}`}><span className="text-[10px] font-bold uppercase text-violet-200">{index + 1}. {job}</span><span className="mt-1 block text-xs text-slate-400">{job === "SETUP" ? "Truth + recipe" : job === "BUILD" ? "Plan then execute" : job === "REVIEW" ? "Human queue" : "Approved landbank"}</span></button>)}
			</div>

			<Section title="1. Setup campaign" helper="Select a registered product and an existing V3 Copy Recipe. Product Truth is read-only here; this surface never seeds or mutates canonical Product Truth.">
				<div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
					<div>
						<SearchableProductSelect products={products} selectedProduct={selectedProduct} onSelect={selectProduct} isLoadingProducts={isLoadingProducts} productsError={productsError} showReadinessBadge={false} />
						<div className="mt-4 grid gap-3 sm:grid-cols-2">
							<FormField label="Objective"><input className={INPUT_CLASS} value={objectiveId} onChange={(event) => setObjectiveId(event.target.value)} placeholder="conversion" data-testid="v3-objective" /></FormField>
							<FormField label="Formula"><select className={INPUT_CLASS} value={formulaId} onChange={(event) => setFormulaId(event.target.value)} data-testid="v3-formula">{FORMULA_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}</select></FormField>
							<FormField label="Recipe preset"><select className={INPUT_CLASS} value={preset} onChange={(event) => setPreset(event.target.value as V3RecipePreset)} data-testid="v3-preset">{RECIPE_PRESETS.map((option) => <option key={option} value={option}>{option}</option>)}</select></FormField>
							<FormField label="Assistant mode"><select className={INPUT_CLASS} value={mode} onChange={(event) => setMode(event.target.value as V3AssistantMode)} data-testid="v3-assistant-mode"><option value="CREATE">CREATE · meet recipe target</option><option value="EXPAND">EXPAND · add bounded variants</option><option value="FILL_CAPACITY">FILL_CAPACITY · close capacity gaps</option></select></FormField>
							<FormField label="Target capacity"><input className={INPUT_CLASS} value={targetCapacity} onChange={(event) => setTargetCapacity(event.target.value)} placeholder="54" data-testid="v3-target-capacity" /></FormField>
							<FormField label="Language"><input className={INPUT_CLASS} value={languageProfile} onChange={(event) => setLanguageProfile(event.target.value)} data-testid="v3-language" /></FormField>
							<FormField label="WPS mode"><select className={INPUT_CLASS} value={wpsModeSel} onChange={(event) => setWpsModeSel(event.target.value as "SAFE" | "SWEET")} data-testid="v3-wps-mode"><option value="SAFE">SAFE</option><option value="SWEET">SWEET</option></select></FormField>
							<FormField label="Duration mix"><div className="mt-1 flex gap-3">{[8, 16, 24].map((duration) => <label key={duration} className="flex items-center gap-1 text-xs text-slate-300"><input type="checkbox" checked={Boolean(durationMix[duration])} onChange={(event) => setDurationMix((previous) => ({ ...previous, [duration]: event.target.checked }))} data-testid={`v3-duration-${duration}`} />{duration}s</label>)}</div></FormField>
						</div>
						<HelperText className="mt-3">Pick a Product, Objective, Formula, and Recipe preset. Building the campaign creates/reuses the governed V3 recipe behind the scenes — no raw recipe ID required in the normal path.</HelperText>
						<div className="mt-4 flex flex-wrap items-center gap-2">
							<button type="button" disabled={busy || !selectedProduct} onClick={() => void handleBuildCampaign()} className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-build-campaign">Build campaign recipe</button>
							<button type="button" disabled={busy || !selectedProduct || !recipeId.trim()} onClick={() => void handlePlan()} className="rounded-lg bg-violet-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-plan-assistant">Plan assistant run <ChevronRight size={14} className="inline" /></button>
							{recipeId ? <span className="text-[10px] font-bold uppercase text-emerald-300" data-testid="v3-active-recipe">Recipe ready</span> : null}
						</div>
						<details className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 p-3" data-testid="v3-technical-details">
							<summary className="cursor-pointer text-[10px] font-bold uppercase tracking-wide text-slate-500">Technical details · advanced</summary>
							<div className="mt-2"><FormField label="V3 Copy Recipe ID (advanced override)"><input className={INPUT_CLASS} value={recipeId} onChange={(event) => setRecipeId(event.target.value)} placeholder="recipe_…" data-testid="v3-recipe-id" /></FormField><HelperText className="mt-1">UUIDs, digests, and internal identifiers live here, out of the primary workflow.</HelperText></div>
						</details>
					</div>
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4" data-testid="v3-provider-status"><div className="flex items-center gap-2 text-xs font-bold uppercase text-slate-300"><LockKeyhole size={14} /> text_assist provider</div><div className="mt-3 flex items-center gap-2"><Badge tone={provider?.configured ? "success" : provider?.fake_provider_allowed ? "warn" : "neutral"}>{provider?.configured ? "READY" : provider?.fake_provider_allowed ? "FAKE TEST ENABLED" : "NOT CONFIGURED"}</Badge><span className="text-xs text-slate-500">{provider?.provider_id || "no provider selected"} · {provider?.model_id || "no model"}</span></div><HelperText className="mt-3">Planning, reads, prompt preview, validation, and approval are provider-free. Generate is never automatic.</HelperText><div className="mt-2 text-[10px] text-slate-500">Calls this page has made: {provider?.provider_calls ?? 0} · credit spend: {provider?.credit_spend ?? 0}</div></div>
				</div>
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4" data-testid="v3-evidence-drawer">
					<div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-xs font-bold uppercase text-slate-300">Evidence auto-selection</div><HelperText className="mt-1">Approved Product Truth evidence is visible for review and is never edited by the assistant.</HelperText></div><span className="text-[10px] font-bold uppercase text-emerald-200">{truthFacts.length} approved fact(s)</span></div>
					<input className={INPUT_CLASS} value={evidenceSearch} onChange={(event) => setEvidenceSearch(event.target.value)} placeholder="Search fact ID, kind, or evidence text" data-testid="v3-evidence-search" />
					<div className="mt-3 max-h-48 space-y-2 overflow-y-auto pr-1" data-testid="v3-evidence-list">
						{visibleTruthFacts.length ? visibleTruthFacts.map((fact) => <div key={fact.fact_id} className="rounded-lg border border-slate-800 bg-slate-900/70 p-3"><div className="flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase text-blue-200"><span>{fact.fact_kind}</span><span className="font-mono text-slate-500">{fact.fact_id}</span><span className="text-emerald-300">{fact.approved ? "APPROVED" : "UNAPPROVED"}</span></div><p className="mt-1 text-xs leading-5 text-slate-300">{fact.text}</p></div>) : <div className="rounded-lg border border-dashed border-slate-700 p-4 text-xs text-slate-500">No approved evidence matches this search.</div>}
					</div>
				</div>
			</Section>

			<Section title="2. Build landbank" helper="PLAN is a read-only gap calculation. EXECUTE is a separate explicit action and always produces reviewable V3 drafts; no approval is inferred.">
				{plan ? <div className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-4" data-testid="v3-assistant-plan"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-xs font-bold uppercase text-violet-200">Plan {plan.plan_id}</div><div className="mt-1 text-sm text-slate-200">{plan.mode} · {plan.max_proposals} bounded proposal(s) · {plan.target_durations_seconds.join(" / ")}s projections</div></div><Badge tone={plan.provider.configured || plan.provider.fake_provider_allowed ? "success" : "warn"}>{plan.provider.configured || plan.provider.fake_provider_allowed ? "EXECUTABLE AFTER OPERATOR ACTION" : "EXECUTION DISABLED"}</Badge></div><div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3" data-testid="v3-locked-contract"><div className="text-[10px] font-bold uppercase tracking-wide text-violet-200">Locked authoring contract</div><div className="mt-2 grid gap-2 text-xs text-slate-300 md:grid-cols-2"><div>Objective: {plan.objective?.definition || "—"}</div><div>Formula: {plan.formula?.formula_id || "—"} · {plan.formula?.formula_version || "—"}</div><div>Angle: {plan.angle?.entity_id || "—"} · Family: {plan.storyline_family?.entity_id || "—"}</div><div>Language/WPS: {plan.language_profile || "Malay"} · {plan.wps_mode}</div><div>Approved evidence IDs: {plan.evidence_fact_ids?.length ?? 0}</div><div>Capacity: {Object.entries(plan.current_capacity ?? {}).map(([key, value]) => `${key}=${value}`).join(" · ") || "—"}</div></div><div className="mt-2 text-[10px] text-slate-500">Budget: {plan.max_provider_calls} provider call · {plan.max_output_tokens} output tokens · {plan.max_cost} cost units · {plan.cost_status}</div>{plan.evidence_selection?.fact_ids ? <div className="mt-1 text-[10px] text-emerald-300" data-testid="v3-evidence-selection">{plan.evidence_selection.fact_ids.length} relevant approved fact(s) selected · {plan.evidence_selection.outcome ?? "ranked"}</div> : null}{plan.marginal_plan && Object.keys(plan.marginal_plan).length ? <div className="mt-1 text-[10px] text-amber-200" data-testid="v3-diversity-plan">Marginal unlock: {Object.entries(plan.marginal_plan).map(([key, value]) => `${key} +${value}`).join(" · ")}{plan.diversity_deficits?.length ? ` · deficits: ${plan.diversity_deficits.join(", ")}` : ""}</div> : null}</div><div className="mt-3 grid gap-2 md:grid-cols-3">{plan.gaps.map((gap) => <div key={gap.semantic_class} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3"><div className="text-[10px] font-bold uppercase text-slate-500">{gap.semantic_class}</div><div className="mt-1 text-lg font-semibold text-slate-100">{gap.current_count} → {gap.target_count}</div><div className="text-xs text-slate-400">Gap {gap.gap_count}</div></div>)}</div><div className="mt-3 flex flex-wrap gap-2"><button type="button" disabled={busy} onClick={() => void handlePreview()} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200" data-testid="v3-prompt-preview"><Eye size={14} className="mr-1 inline" /> Preview prompt</button><button type="button" disabled={busy || !provider?.fake_provider_allowed} onClick={() => void handleExecute()} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-execute-fake">Execute fake-provider test</button><button type="button" disabled={busy || !provider?.configured} onClick={() => void handleGenerateLive()} className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-generate-live" title={provider?.configured ? "Run the configured text_assist provider" : "Configure and enable text_assist before live generation"}>Generate with AI</button></div>{promptDigest ? <div className="mt-3 text-[10px] font-mono text-slate-500" data-testid="v3-prompt-digest">Prompt digest: {promptDigest}</div> : null}<HelperText className="mt-3">{provider?.fake_provider_allowed ? "Disposable fake-provider mode is enabled for UAT; it reports zero real provider calls and zero credits." : "Enable the disposable fake-provider runtime for browser UAT, or configure text_assist before any live execution."}</HelperText></div> : <div className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-500" data-testid="v3-no-plan">Create a plan to see capacity gaps and the explicit execution boundary.</div>}
			</Section>

			<Section title="3. Review queue" helper="Full storyboard first: Master stages, 8/16/24 projections, quality gates, novelty signal, and approval receipt context stay together.">
				<div className="mb-4 flex flex-wrap items-center gap-2"><ClipboardCheck size={16} className="text-violet-300" /><span className="text-xs font-semibold text-slate-200" data-testid="v3-review-queue-label">V3 Review Queue · {visibleItems.length} storyboard(s)</span><select className="ml-auto rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} data-testid="v3-status-filter"><option value="ALL">All statuses</option><option value="DRAFT">DRAFT</option><option value="VALIDATED">VALIDATED</option><option value="APPROVED">APPROVED</option></select><select className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300" value={durationFilter} onChange={(event) => setDurationFilter(event.target.value)} data-testid="v3-duration-filter"><option value="ALL">All durations</option><option value="8">8s</option><option value="16">16s</option><option value="24">24s</option></select></div>
				<div className="mb-4 grid gap-2 md:grid-cols-4" data-testid="v3-landbank-filters"><input className={INPUT_CLASS} value={searchFilter} onChange={(event) => setSearchFilter(event.target.value)} placeholder="Server search" data-testid="v3-search-filter" /><input className={INPUT_CLASS} value={formulaFilter} onChange={(event) => setFormulaFilter(event.target.value)} placeholder="Formula ID" data-testid="v3-formula-filter" /><input className={INPUT_CLASS} value={angleFilter} onChange={(event) => setAngleFilter(event.target.value)} placeholder="Angle ID" data-testid="v3-angle-filter" /><input className={INPUT_CLASS} value={storylineFilter} onChange={(event) => setStorylineFilter(event.target.value)} placeholder="Storyline family ID" data-testid="v3-storyline-filter" /><input className={INPUT_CLASS} value={recipeFilter} onChange={(event) => setRecipeFilter(event.target.value)} placeholder="Recipe ID" data-testid="v3-recipe-filter" /><select className={INPUT_CLASS} value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} data-testid="v3-source-filter"><option value="ALL">All sources</option><option value="ROUND2">ROUND2</option></select><select className={INPUT_CLASS} value={qualityFilter} onChange={(event) => setQualityFilter(event.target.value)} data-testid="v3-quality-filter"><option value="ALL">All quality</option><option value="HARD_PASS">HARD_PASS</option></select><input className={INPUT_CLASS} value={blockerFilter} onChange={(event) => setBlockerFilter(event.target.value)} placeholder="Blocker code" data-testid="v3-blocker-filter" /></div>
				<div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3" data-testid="v3-bulk-approval-panel"><div><div className="text-xs font-bold uppercase text-amber-100">Human batch approval</div><HelperText className="mt-1">{bulkCandidates.length} hard-pass candidate(s) are ready for one explicit review receipt. V3 never auto-approves.</HelperText></div><button type="button" disabled={busy || !bulkCandidates.length} onClick={() => { setBulkApproval(true); setApprovalItem(bulkCandidates[0]); setActiveJob("REVIEW"); }} className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs font-bold text-amber-100 disabled:opacity-40" data-testid="v3-open-bulk-approval">Open batch approval</button></div>
				{visibleItems.length ? <div className="space-y-4">{visibleItems.map((item) => <StoryboardCard key={`${item.master.master_id}:${item.master.revision}`} item={item} onReview={handleReview} onApprove={(target) => { setBulkApproval(false); setApprovalItem(target); setActiveJob("REVIEW"); }} onRegenerate={handleRegenerate} onDeleteDraft={(target) => setDeleteItem(target)} />)}{landbankHasMore && selectedProduct ? <button type="button" disabled={busy} onClick={() => void loadLandbank(selectedProduct.id, landbankOffset, true)} className="w-full rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 disabled:opacity-40" data-testid="v3-load-more">Load more bounded results</button> : null}</div> : <div className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-500" data-testid="v3-empty-review-queue">No V3 storyboard candidates in this bounded view. Execute an explicit plan or adjust the product/filters.</div>}
			</Section>

			<Section title="4. Approved storyboard landbank" helper="The V3 approved landbank is a supply-plane read model. Macro Round 3 owns V2 materialization, Production Supply Manifest, P6, and runtime pilot work.">
				<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4" data-testid="v3-approved-landbank"><div className="flex items-center gap-2 text-xs font-bold uppercase text-slate-300"><BookOpen size={14} /> Approved V3 Storyboard Landbank</div><div className="mt-2 text-sm text-slate-400">{approvedItems.length} approved storyboard(s) in the current bounded read.</div><HelperText className="mt-2">No V2 rows, activation pointers, materialization links, P6 manifests, media calls, or provider credits are created by this surface.</HelperText></div>
				{approvedItems.length ? <div className="mt-4 space-y-4">{approvedItems.map((item) => <StoryboardCard key={`approved:${item.master.master_id}:${item.master.revision}`} item={item} onApprove={() => undefined} />)}</div> : null}
			</Section>

			{approvalItem ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" data-testid="v3-approval-dialog"><div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-emerald-500/30 bg-slate-950 p-6"><div className="flex items-start justify-between gap-4"><div><div className="text-xs font-bold uppercase tracking-wide text-emerald-200">{bulkApproval ? "Human batch approval receipt" : "Human approval receipt"}</div><h2 className="mt-1 text-lg font-bold text-slate-100">{bulkApproval ? `Approve ${bulkCandidates.length} clean storyboard(s)?` : `Approve ${approvalItem.master.master_id}?`}</h2></div><button type="button" onClick={() => { setApprovalItem(null); setBulkApproval(false); }} className="text-slate-400" aria-label="Close approval">✕</button></div><p className="mt-3 text-xs leading-5 text-slate-400">{bulkApproval ? "This records one immutable batch receipt with each exact Master and projection revision. Every candidate still passes the same human checklist." : "This records an immutable v3_human_approval_receipt for the exact Master and selected projection revisions."} It does not activate or materialize V2.</p>{bulkApproval ? <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3" data-testid="v3-batch-scope"><div className="text-[10px] font-bold uppercase text-emerald-200">Machine-clean candidates ({bulkCandidates.length})</div><ul className="mt-1 max-h-28 space-y-1 overflow-y-auto text-[11px] text-slate-300">{bulkCandidates.map((item) => <li key={item.master.master_id} data-testid="v3-batch-clean-item">{item.master.master_id} · {item.master.formula.formula_id} · {item.projections.length} projection(s) · {item.projections.map((projection) => projection.target_duration_seconds).join("/")}s</li>)}</ul>{bulkExceptions.length ? <div className="mt-2"><div className="text-[10px] font-bold uppercase text-amber-300" data-testid="v3-batch-exceptions">Exceptions excluded from the batch ({bulkExceptions.length})</div><ul className="mt-1 max-h-20 space-y-1 overflow-y-auto text-[11px] text-amber-200">{bulkExceptions.map((item) => <li key={item.master.master_id}>{item.master.master_id} · {item.quality.issue_codes.join(", ") || "not hard-pass"}</li>)}</ul></div> : null}<div className="mt-2 text-[10px] text-slate-500">Only this exact machine-clean set receives the batch receipt; exceptions need individual review. The batch digest binds every target and is shown in Technical Details after approval.</div></div> : null}<div className="mt-4 grid gap-3 sm:grid-cols-2"><FormField label="Reviewer"><input className={INPUT_CLASS} value={reviewer} onChange={(event) => setReviewer(event.target.value)} data-testid="v3-reviewer" /></FormField><FormField label="Rationale"><textarea className={`${INPUT_CLASS} min-h-20`} value={rationale} onChange={(event) => setRationale(event.target.value)} data-testid="v3-rationale" /></FormField></div><div className="mt-4"><Checklist value={checklist} onChange={setChecklist} /></div><div className="mt-4 flex justify-end gap-2"><button type="button" onClick={() => { setApprovalItem(null); setBulkApproval(false); }} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">Cancel</button><button type="button" disabled={busy || !allChecks || !reviewer.trim() || rationale.trim().length < 8} onClick={() => void handleApprove()} className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid={bulkApproval ? "v3-approve-batch" : "v3-approve-master"}>{bulkApproval ? "Record batch approval receipt" : "Record approval receipt"}</button></div></div></div> : null}

			{deleteItem ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" data-testid="v3-delete-dialog"><div className="w-full max-w-md rounded-2xl border border-rose-500/30 bg-slate-950 p-6"><div className="text-xs font-bold uppercase tracking-wide text-rose-200">Safe delete draft</div><h2 className="mt-1 text-lg font-bold text-slate-100">Delete draft {deleteItem.master.master_id}?</h2><p className="mt-3 text-xs leading-5 text-slate-400">Only an unreferenced DRAFT master can be removed. The server fails closed when this master is referenced, approved, or otherwise terminal — no approved or historical revision is ever hard-deleted.</p><div className="mt-4 flex justify-end gap-2"><button type="button" onClick={() => setDeleteItem(null)} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300" data-testid="v3-delete-cancel">Cancel</button><button type="button" disabled={busy} onClick={() => void handleDeleteDraft()} className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="v3-delete-confirm">Delete draft</button></div></div></div> : null}
		</div>
	);
}
