import {
	ArrowLeft,
	ChevronLeft,
	ChevronRight,
	Database,
	ExternalLink,
	RefreshCw,
	Save,
	Search,
	Trash2,
	X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
	deleteCopywritingLandbankDraft,
	fetchCopywritingLandbankMaintenance,
	fetchCopywritingLandbankMaintenanceDetail,
	saveCopywritingLandbankRevision,
	type MaintenanceDetail,
	type MaintenanceListResponse,
	type MaintenanceRecord,
	type MaintenanceStage,
} from "../api/copywritingLandbankMaintenance";
import { reviewV3Entity } from "../api/storyboardLandbankV3Round2";
import { Badge, ConfirmActionModal, Section, TechnicalDetails } from "../components/ui";
import type { BadgeTone } from "../components/ui";

const PAGE_SIZE = 25;
const INPUT_CLASS = "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500";
const BUTTON_CLASS = "inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-300 transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40";

type ModalAction = "reject" | "delete" | null;

function apiErrorMessage(error: unknown): string {
	const raw = error instanceof Error ? error.message : String(error);
	const payload = raw.replace(/^API\s+\d+:\s*/, "");
	try {
		const parsed = JSON.parse(payload) as { detail?: { message?: string; code?: string } | string };
		if (typeof parsed.detail === "object" && parsed.detail) {
			return parsed.detail.code ? `${parsed.detail.code}: ${parsed.detail.message || "Request failed."}` : parsed.detail.message || "Request failed.";
		}
		if (typeof parsed.detail === "string") return parsed.detail;
	} catch {
		// Keep the client error text when the server did not return JSON.
	}
	return raw || "Copywriting Landbank maintenance request failed.";
}

function statusTone(status: string): BadgeTone {
	switch (status.toUpperCase()) {
		case "APPROVED":
		case "FROZEN":
			return "success";
		case "REVIEW_REQUIRED":
		case "VALIDATED":
			return "info";
		case "REJECTED":
		case "BLOCKED":
		case "ARCHIVED":
		case "SUPERSEDED":
			return "danger";
		default:
			return "warn";
	}
}

function productionTone(status: string): BadgeTone {
	if (status === "MATERIALIZED") return "success";
	if (status === "STALE" || status === "BLOCKED" || status === "PARTIALLY_MATERIALIZED") return "warn";
	return "neutral";
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: number; tone?: BadgeTone }) {
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
			<div className="mt-1 text-2xl font-bold text-slate-100"><Badge tone={tone}>{value}</Badge></div>
		</div>
	);
}

function Preview({ text }: { text: string }) {
	return <span className="block max-w-[220px] truncate text-xs text-slate-300" title={text}>{text || "—"}</span>;
}

function productWorkflowPath(productId: string) {
	return productId ? `/creative/storyboard-landbank-v3?product_id=${encodeURIComponent(productId)}` : "/creative/storyboard-landbank-v3";
}

export default function CopywritingLandbankDatabasePage() {
	const navigate = useNavigate();
	const [searchParams, setSearchParams] = useSearchParams();
	const productId = searchParams.get("product_id") || "";
	const status = searchParams.get("status") || "";
	const formulaId = searchParams.get("formula_id") || "";
	const angleId = searchParams.get("angle_id") || "";
	const search = searchParams.get("search") || "";
	const productionFilter = searchParams.get("production_ready") || "";
	const staleFilter = searchParams.get("stale") || "";
	const offset = Math.max(0, Number(searchParams.get("offset") || 0));
	const masterId = searchParams.get("master_id") || "";
	const revision = Number(searchParams.get("revision") || 0);

	const [data, setData] = useState<MaintenanceListResponse | null>(null);
	const [detail, setDetail] = useState<MaintenanceDetail | null>(null);
	const [draftStages, setDraftStages] = useState<MaintenanceStage[]>([]);
	const [searchDraft, setSearchDraft] = useState(search);
	const [editing, setEditing] = useState(false);
	const [loading, setLoading] = useState(true);
	const [detailLoading, setDetailLoading] = useState(false);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [modal, setModal] = useState<ModalAction>(null);
	const [mutationBusy, setMutationBusy] = useState(false);
	const [reloadToken, setReloadToken] = useState(0);

	useEffect(() => {
		setSearchDraft(search);
	}, [search]);

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		fetchCopywritingLandbankMaintenance({
			product_id: productId || undefined,
			status: status || undefined,
			formula_id: formulaId || undefined,
			angle_id: angleId || undefined,
			search: search || undefined,
			production_ready: productionFilter === "" ? undefined : productionFilter === "true",
			stale: staleFilter === "" ? undefined : staleFilter === "true",
			limit: PAGE_SIZE,
			offset,
		})
			.then((response) => {
				if (active) setData(response);
			})
			.catch((requestError: unknown) => {
				if (active) setError(apiErrorMessage(requestError));
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId, status, formulaId, angleId, search, productionFilter, staleFilter, offset, reloadToken]);

	useEffect(() => {
		if (!masterId || !Number.isInteger(revision) || revision < 1) {
			setDetail(null);
			setDraftStages([]);
			setEditing(false);
			return;
		}
		let active = true;
		setDetailLoading(true);
		setError("");
		fetchCopywritingLandbankMaintenanceDetail(masterId, revision)
			.then((response) => {
				if (!active) return;
				setDetail(response);
				setDraftStages(response.stages.map((stage) => ({ ...stage })));
			})
			.catch((requestError: unknown) => {
				if (active) setError(apiErrorMessage(requestError));
			})
			.finally(() => {
				if (active) setDetailLoading(false);
			});
		return () => {
			active = false;
		};
	}, [masterId, revision, reloadToken]);

	function updateQuery(updates: Record<string, string | number | null | undefined>) {
		const next = new URLSearchParams(searchParams);
		for (const [key, value] of Object.entries(updates)) {
			if (value === null || value === undefined || value === "") next.delete(key);
			else next.set(key, String(value));
		}
		setSearchParams(next);
	}

	function updateFilter(key: string, value: string) {
		updateQuery({ [key]: value || null, offset: 0, master_id: null, revision: null });
		setSuccess("");
	}

	function openDetail(item: MaintenanceRecord) {
		updateQuery({ master_id: item.master_id, revision: item.revision });
		setSuccess("");
	}

	function clearDetail() {
		updateQuery({ master_id: null, revision: null });
		setDetail(null);
		setEditing(false);
	}

	async function saveRevision() {
		if (!detail) return;
		setMutationBusy(true);
		setError("");
		setSuccess("");
		try {
			const response = await saveCopywritingLandbankRevision({
				masterId: detail.master_id,
				sourceRevision: detail.revision,
				stages: draftStages.map((stage) => ({ stage_key: stage.stage_key, authored_text: stage.authored_text })),
				reason: "MANUAL_COPY_MAINTENANCE",
			});
			setEditing(false);
			setSuccess(`Saved as revision ${response.new_revision} · DRAFT · approval required`);
			setReloadToken((value) => value + 1);
			updateQuery({ master_id: detail.master_id, revision: response.new_revision });
		} catch (requestError) {
			setError(apiErrorMessage(requestError));
		} finally {
			setMutationBusy(false);
		}
	}

	async function rejectRevision(reason: string) {
		if (!detail) return;
		setMutationBusy(true);
		setError("");
		try {
			const response = await reviewV3Entity("reject", "MASTER_STORYBOARD", detail.master_id, detail.revision, reason);
			const result = response as { revision?: number; master_id?: string };
			const rejectedRevision = Number(result.revision || detail.revision + 1);
			setModal(null);
			setSuccess(`Rejected as revision ${rejectedRevision} · approval remains required for any new draft`);
			setReloadToken((value) => value + 1);
			updateQuery({ master_id: detail.master_id, revision: rejectedRevision });
		} catch (requestError) {
			setError(apiErrorMessage(requestError));
		} finally {
			setMutationBusy(false);
		}
	}

	async function deleteRevision() {
		if (!detail) return;
		setMutationBusy(true);
		setError("");
		try {
			const response = await deleteCopywritingLandbankDraft(detail.master_id, detail.revision);
			if (!response.deleted) throw new Error("The exact DRAFT was not deleted.");
			setModal(null);
			setSuccess(`Deleted DRAFT revision ${detail.revision}`);
			clearDetail();
			setReloadToken((value) => value + 1);
		} catch (requestError) {
			setError(apiErrorMessage(requestError));
		} finally {
			setMutationBusy(false);
		}
	}

	const summary = data?.summary;
	const firstRow = data && data.total > 0 ? data.offset + 1 : 0;
	const lastRow = data ? Math.min(data.offset + data.items.length, data.total) : 0;

	return (
		<div className="mx-auto max-w-[1600px] space-y-6 p-4 md:p-8" data-testid="copywriting-landbank-maintenance-page">
			<header className="flex flex-col gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-end md:justify-between">
				<div>
					<div className="flex items-center gap-2 text-cyan-300"><Database size={18} /><span className="text-[10px] font-bold uppercase tracking-[0.2em]">Reporting / Copy database</span></div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100">Copywriting Landbank Database</h1>
					<p className="mt-1 max-w-3xl text-sm text-slate-400">Authoritative V3 Master Storyboard revisions across every product. This is a maintenance and reporting layer; generation and approval authority remain canonical.</p>
				</div>
				<div className="flex flex-wrap gap-2">
					<button type="button" className={BUTTON_CLASS} onClick={() => navigate(productWorkflowPath(productId))} data-testid="maintenance-open-create-workflow"><ExternalLink size={14} />Open Create / Generate workflow</button>
					<button type="button" className={BUTTON_CLASS} onClick={() => setReloadToken((value) => value + 1)} disabled={loading} data-testid="maintenance-refresh"><RefreshCw size={14} />Refresh</button>
				</div>
			</header>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="maintenance-error">{error}</p> : null}
			{success ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="maintenance-success">{success}</p> : null}

			{summary ? (
				<Section title="Authoritative overview" helper="Counts are returned by the Reporting API from canonical V3 records; Master IDs and exact revisions are shown separately.">
					<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
						<Metric label="Products with copy" value={summary.products_with_copy} tone="success" />
						<Metric label="Products without copy" value={summary.products_without_copy} tone={summary.products_without_copy ? "warn" : "neutral"} />
						<Metric label="Master IDs" value={summary.total_copy_masters} tone="info" />
						<Metric label="Master revisions" value={summary.total_master_revisions} />
						<Metric label="Production ready" value={summary.production_ready} tone="success" />
						<Metric label="Draft" value={summary.draft} tone="warn" />
						<Metric label="Review required" value={summary.review_required} tone="info" />
						<Metric label="Validated" value={summary.validated} tone="info" />
						<Metric label="Approved" value={summary.approved} tone="success" />
						<Metric label="Stale" value={summary.stale} tone={summary.stale ? "warn" : "neutral"} />
					</div>
				</Section>
			) : null}

			<Section title="Product coverage" helper="All products are included, including products with no canonical V3 Master copy yet.">
				<div className="overflow-x-auto">
					<table className="w-full min-w-[900px] text-left text-xs" data-testid="maintenance-product-coverage">
						<thead className="border-b border-slate-800 text-[10px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="px-3 py-2">Product</th><th className="px-3 py-2">Copy sets</th><th className="px-3 py-2">Angles</th><th className="px-3 py-2">Hooks</th><th className="px-3 py-2">Body/Core</th><th className="px-3 py-2">CTA</th><th className="px-3 py-2">Approved</th><th className="px-3 py-2">Ready</th><th className="px-3 py-2">Stale</th></tr></thead>
						<tbody>{data?.product_coverage.map((product) => <tr key={product.product_id} className="border-b border-slate-900 hover:bg-slate-800/40"><td className="px-3 py-3"><button type="button" className="text-left font-semibold text-cyan-200 hover:text-cyan-100" onClick={() => updateFilter("product_id", product.product_id)}>{product.product_name}<span className="mt-0.5 block font-mono text-[10px] text-slate-600">{product.product_id}</span></button></td><td className="px-3 py-3 text-slate-300">{product.copy_sets}</td><td className="px-3 py-3 text-slate-300">{product.angles}</td><td className="px-3 py-3 text-slate-300">{product.hooks}</td><td className="px-3 py-3 text-slate-300">{product.body_core}</td><td className="px-3 py-3 text-slate-300">{product.cta}</td><td className="px-3 py-3"><Badge tone={product.approved ? "success" : "neutral"}>{product.approved}</Badge></td><td className="px-3 py-3"><Badge tone={product.production_ready ? "success" : "neutral"}>{product.production_ready}</Badge></td><td className="px-3 py-3"><Badge tone={product.stale ? "warn" : "neutral"}>{product.stale}</Badge></td></tr>)}</tbody>
					</table>
				</div>
			</Section>

			<Section title="Master Storyboard records" helper="Search, filters, and pagination are server-side. Each row is one exact canonical Master ID + revision.">
				<div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
					<label className="space-y-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><span>Product</span><select className={INPUT_CLASS} value={productId} onChange={(event) => updateFilter("product_id", event.target.value)} data-testid="maintenance-product-filter"><option value="">All products</option>{data?.product_coverage.map((product) => <option key={product.product_id} value={product.product_id}>{product.product_name}</option>)}</select></label>
					<label className="space-y-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><span>Status</span><select className={INPUT_CLASS} value={status} onChange={(event) => updateFilter("status", event.target.value)} data-testid="maintenance-status-filter"><option value="">All statuses</option><option value="DRAFT">DRAFT</option><option value="REVIEW_REQUIRED">REVIEW_REQUIRED</option><option value="VALIDATED">VALIDATED</option><option value="APPROVED">APPROVED</option><option value="REJECTED">REJECTED</option><option value="BLOCKED">BLOCKED</option></select></label>
					<label className="space-y-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><span>Formula</span><select className={INPUT_CLASS} value={formulaId} onChange={(event) => updateFilter("formula_id", event.target.value)} data-testid="maintenance-formula-filter"><option value="">All formulas</option>{data?.filter_options.formulas.map((formula) => <option key={formula} value={formula}>{formula}</option>)}</select></label>
					<label className="space-y-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><span>Angle</span><select className={INPUT_CLASS} value={angleId} onChange={(event) => updateFilter("angle_id", event.target.value)} data-testid="maintenance-angle-filter"><option value="">All angles</option>{data?.filter_options.angles.map((angle) => <option key={angle} value={angle}>{angle}</option>)}</select></label>
					<label className="space-y-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><span>Production</span><select className={INPUT_CLASS} value={productionFilter} onChange={(event) => updateFilter("production_ready", event.target.value)} data-testid="maintenance-production-filter"><option value="">All readiness</option><option value="true">Production ready</option><option value="false">Not production ready</option></select></label>
					<label className="space-y-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><span>Truth state</span><select className={INPUT_CLASS} value={staleFilter} onChange={(event) => updateFilter("stale", event.target.value)} data-testid="maintenance-stale-filter"><option value="">All truth states</option><option value="true">Stale / revalidation</option><option value="false">Current</option></select></label>
				</div>
				<div className="mt-3 flex flex-col gap-2 sm:flex-row"><label className="relative flex-1"><Search size={14} className="absolute left-3 top-2.5 text-slate-600" /><input className={`${INPUT_CLASS} pl-9`} value={searchDraft} onChange={(event) => { setSearchDraft(event.target.value); updateFilter("search", event.target.value); }} placeholder="Search product, Master ID, formula, angle, storyline, or authored text" data-testid="maintenance-search" /></label><button type="button" className={BUTTON_CLASS} onClick={() => { setSearchDraft(""); updateQuery({ search: null, offset: 0, master_id: null, revision: null }); }}><X size={14} />Clear filters</button></div>
				<div className="mt-4 overflow-x-auto">
					<table className="w-full min-w-[1500px] text-left text-xs" data-testid="maintenance-record-table">
						<thead className="border-b border-slate-800 text-[10px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="px-3 py-2">Product</th><th className="px-3 py-2">Master / rev</th><th className="px-3 py-2">Formula</th><th className="px-3 py-2">Angle</th><th className="px-3 py-2">Hook</th><th className="px-3 py-2">Body/Core</th><th className="px-3 py-2">CTA</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Quality</th><th className="px-3 py-2">Production</th><th className="px-3 py-2">Action</th></tr></thead>
						<tbody>
							{loading ? <tr><td colSpan={11} className="px-3 py-10 text-center text-slate-500">Loading authoritative records…</td></tr> : null}
							{!loading && data?.items.length === 0 ? <tr><td colSpan={11} className="px-3 py-10 text-center text-slate-500">No canonical Master revisions match these filters.</td></tr> : null}
							{!loading && data?.items.map((item) => <tr key={`${item.master_id}:${item.revision}`} className="cursor-pointer border-b border-slate-900 align-top hover:bg-slate-800/40" onClick={() => openDetail(item)} data-testid={`maintenance-row-${item.master_id}-${item.revision}`}><td className="px-3 py-3"><span className="font-semibold text-slate-200">{item.product.name}</span><span className="mt-0.5 block font-mono text-[10px] text-slate-600">{item.product.id}</span></td><td className="px-3 py-3"><span className="font-mono text-cyan-200">{item.master_id}</span><span className="mt-1 block"><Badge tone="neutral">REV {item.revision}</Badge></span></td><td className="px-3 py-3 text-slate-300">{item.formula.formula_id}</td><td className="px-3 py-3 font-mono text-slate-400">{item.angle.entity_id}</td><td className="px-3 py-3"><Preview text={item.previews.HOOK} /></td><td className="px-3 py-3"><Preview text={item.previews.BODY_CORE} /></td><td className="px-3 py-3"><Preview text={item.previews.CTA} /></td><td className="px-3 py-3"><Badge tone={statusTone(item.status)}>{item.status}</Badge>{item.stale ? <span className="mt-1 block"><Badge tone="warn">STALE</Badge></span> : null}</td><td className="px-3 py-3"><span className="font-semibold text-slate-200">{Math.round((item.quality.quality_score || 0) * 100)}%</span><span className="mt-1 block text-[10px] text-slate-500">{item.quality.hard_pass ? "hard pass" : "review gates"}</span></td><td className="px-3 py-3"><Badge tone={productionTone(item.production_ready ? "MATERIALIZED" : item.projection_status)}>{item.production_ready ? "MATERIALIZED" : item.projection_status}</Badge></td><td className="px-3 py-3"><button type="button" className="text-xs font-semibold text-cyan-200 hover:text-cyan-100" onClick={(event) => { event.stopPropagation(); openDetail(item); }}>Open exact</button></td></tr>)}
						</tbody>
					</table>
				</div>
				<div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-800 pt-3 text-xs text-slate-500"><span>{firstRow}–{lastRow} of {data?.total ?? 0} exact revisions</span><div className="flex gap-2"><button type="button" className={BUTTON_CLASS} disabled={offset === 0 || loading} onClick={() => updateQuery({ offset: Math.max(0, offset - PAGE_SIZE), master_id: null, revision: null })}><ChevronLeft size={14} />Previous</button><button type="button" className={BUTTON_CLASS} disabled={!data?.has_more || loading} onClick={() => updateQuery({ offset: offset + PAGE_SIZE, master_id: null, revision: null })}>Next<ChevronRight size={14} /></button></div></div>
			</Section>

			{detailLoading ? <Section title="Exact revision drilldown"><div className="text-sm text-slate-500">Loading the requested Master revision…</div></Section> : null}
			{detail ? (
				<Section title="Exact Master Storyboard drilldown" helper="This panel is bound to the Master ID and revision in the URL. It never falls back to the latest revision." action={<button type="button" className={BUTTON_CLASS} onClick={clearDetail}><ArrowLeft size={14} />Back to records</button>}>
					<div className="flex flex-col gap-3 border-b border-slate-800 pb-4 lg:flex-row lg:items-start lg:justify-between"><div><div className="text-sm font-semibold text-slate-100">{detail.product.name}</div><div className="mt-1 font-mono text-xs text-cyan-200">{detail.master_id} · revision {detail.revision}</div><div className="mt-2 flex flex-wrap gap-2"><Badge tone={statusTone(detail.status)}>{detail.status}</Badge><Badge tone="neutral">{detail.formula.formula_id}</Badge><Badge tone={productionTone(detail.production_ready ? "MATERIALIZED" : detail.projection_status)}>{detail.production_ready ? "MATERIALIZED" : detail.projection_status}</Badge>{detail.stale ? <Badge tone="warn">STALE · {detail.stale_reasons.join(", ")}</Badge> : null}</div></div><div className="flex flex-wrap gap-2"><button type="button" className={BUTTON_CLASS} onClick={() => navigate(productWorkflowPath(detail.product.id))}><ExternalLink size={14} />Create New Copy</button>{detail.actions.can_edit ? <button type="button" className={BUTTON_CLASS} onClick={() => { setEditing(true); setSuccess(""); }} data-testid="maintenance-edit-button">{detail.status === "APPROVED" ? "Edit → Create new draft revision" : "Edit stages"}</button> : null}{detail.actions.can_reject ? <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/20" onClick={() => setModal("reject")} data-testid="maintenance-reject-button">Reject</button> : null}{detail.actions.can_delete ? <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-200 hover:bg-red-500/20" onClick={() => setModal("delete")} data-testid="maintenance-delete-button"><Trash2 size={14} />Delete Draft</button> : null}</div></div>
					{!detail.actions.can_delete ? <p className="text-[11px] text-slate-500" data-testid="maintenance-delete-reason">Delete unavailable: {detail.actions.delete_reason}</p> : null}
					{editing ? <div className="space-y-4 rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4" data-testid="maintenance-edit-form"><div className="flex items-start justify-between gap-3"><div><h4 className="text-xs font-bold uppercase tracking-[0.14em] text-cyan-200">Manual formula-stage editing</h4><p className="mt-1 text-[11px] text-slate-400">Only authored text can change. Product, formula, stage keys, semantic roles, evidence, and lineage stay immutable.</p></div><button type="button" className="text-slate-500 hover:text-slate-200" onClick={() => { setEditing(false); setDraftStages(detail.stages.map((stage) => ({ ...stage }))); }} aria-label="Cancel editing"><X size={16} /></button></div>{draftStages.map((stage, index) => <label key={stage.stage_key} className="block space-y-1"><span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400"><Badge tone={stage.semantic_class === "HOOK" ? "info" : stage.semantic_class === "CTA" ? "success" : "neutral"}>{stage.semantic_class}</Badge>{stage.stage_key} · {stage.formula_stage_key}</span><textarea className={`${INPUT_CLASS} min-h-20`} value={stage.authored_text} onChange={(event) => setDraftStages((previous) => previous.map((current, currentIndex) => currentIndex === index ? { ...current, authored_text: event.target.value } : current))} data-testid={`maintenance-stage-${stage.stage_key}`} /></label>)}<div className="flex flex-wrap items-center justify-between gap-3 border-t border-cyan-500/20 pt-3"><span className="text-[11px] text-slate-500">Save creates revision {detail.revision + 1} as DRAFT; approval and production authority are not carried forward.</span><button type="button" className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40" disabled={mutationBusy || draftStages.some((stage) => !stage.authored_text.trim())} onClick={() => void saveRevision()} data-testid="maintenance-save-button"><Save size={14} />Save as new DRAFT revision</button></div></div> : null}
					<div className="grid gap-3 md:grid-cols-4"><Metric label="Revision" value={detail.revision} /><Metric label="Quality" value={Math.round((detail.quality.quality_score || 0) * 100)} tone={detail.quality.hard_pass ? "success" : "warn"} /><Metric label="Projections" value={detail.projection_count} /><Metric label="Production ready" value={detail.production_ready ? 1 : 0} tone={detail.production_ready ? "success" : "neutral"} /></div>
					<div className="grid gap-4 lg:grid-cols-3"><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><h4 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Governed lineage</h4><dl className="mt-3 space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-slate-500">Formula</dt><dd className="font-mono text-slate-300">{detail.formula.formula_id} · {detail.formula.formula_version}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">Angle</dt><dd className="font-mono text-slate-300">{detail.angle.entity_id} · rev {detail.angle.revision}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">Storyline</dt><dd className="font-mono text-slate-300">{detail.storyline_family.entity_id} · rev {detail.storyline_family.revision}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">Created</dt><dd className="text-right text-slate-300">{detail.created_at}</dd></div></dl></div><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><h4 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Quality and safety</h4><div className="mt-3 flex flex-wrap gap-2"><Badge tone={detail.quality.formula_valid ? "success" : "danger"}>Formula {detail.quality.formula_valid ? "valid" : "blocked"}</Badge><Badge tone={detail.quality.evidence_valid ? "success" : "danger"}>Evidence {detail.quality.evidence_valid ? "valid" : "blocked"}</Badge><Badge tone={detail.quality.truth_current ? "success" : "warn"}>Truth {detail.quality.truth_current ? "current" : "revalidate"}</Badge></div><p className="mt-3 text-xs text-slate-500">{detail.quality.issue_codes.length ? detail.quality.issue_codes.join(", ") : "No reported quality blockers."}</p></div><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><h4 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Approval and materialization</h4><p className="mt-3 text-xs text-slate-400">{detail.approval_receipt ? `Receipt ${String(detail.approval_receipt.receipt_id || "present")} is bound to this exact revision.` : "No approval receipt is bound to this exact revision."}</p><p className="mt-2 text-xs text-slate-400">{detail.production_ready ? "All exact projections are production-valid." : "No production authority is asserted by this page."}</p></div></div>
					<div className="space-y-3"><h4 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-300">Ordered formula stages</h4>{detail.stages.map((stage) => <div key={stage.stage_key} className="rounded-xl border border-slate-800 bg-slate-950/40 p-3"><div className="flex flex-wrap items-center gap-2"><Badge tone={stage.semantic_class === "HOOK" ? "info" : stage.semantic_class === "CTA" ? "success" : "neutral"}>{stage.semantic_class}</Badge><span className="font-mono text-[11px] text-slate-400">{stage.stage_key} · {stage.formula_stage_key}</span><span className="text-[10px] text-slate-600">order {stage.order}</span></div><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-200">{stage.authored_text}</p></div>)}</div>
					<TechnicalDetails title="Revision, truth, and governance evidence" testId="maintenance-technical-details"><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-[10px]">{JSON.stringify({ exact_revision: detail.exact_revision, integrity: detail.integrity, approval_receipt: detail.approval_receipt, review_events: detail.review_events, provider_calls: detail.provider_calls, mutations: detail.mutations }, null, 2)}</pre></TechnicalDetails>
				</Section>
			) : null}

			<ConfirmActionModal open={modal === "reject"} title="Reject this exact Master revision?" body="Reject creates a new immutable REJECTED revision through the existing V3 governance transition. It does not mutate the selected revision." requiredPhrase="REJECT" reasonLabel="Reason" reasonPlaceholder="Explain why this revision is rejected." confirmLabel="Reject revision" tone="danger" busy={mutationBusy} onConfirm={(reason) => void rejectRevision(reason)} onCancel={() => setModal(null)} />
			<ConfirmActionModal open={modal === "delete"} title="Delete this exact DRAFT revision?" body="This guarded delete is allowed only when no projection, superseding revision, materialization link, manifest item, or usage record references the DRAFT." requiredPhrase="DELETE" confirmLabel="Delete DRAFT" tone="danger" busy={mutationBusy} onConfirm={() => void deleteRevision()} onCancel={() => setModal(null)} />
		</div>
	);
}
