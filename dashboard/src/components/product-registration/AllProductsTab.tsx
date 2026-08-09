import { useCallback, useEffect, useState } from "react";
import {
	fetchProductRegistry,
	fetchProductStrategyTypeRegistry,
} from "../../api/products";
import {
	cancelCanvaCutoutBulk,
	fetchCanvaCutoutBulkPreview,
	fetchProductVisualBulkPreview,
	bypassCanvaCutoutBulkItem,
	pauseCanvaCutoutBulk,
	queueCanvaCutoutBulk,
	queueProductVisualBulkPrepare,
	resumeCanvaCutoutBulk,
	type CanvaCapabilityStatus,
	type CanvaMethod,
	type CanvaCutoutBulkPreview,
	type CanvaCutoutBulkRun,
	type ProductVisualBulkPreview,
	type ProductVisualBulkRun,
} from "../../api/productVisualOnboarding";
import type { Product, ProductCatalogResponse } from "../../types";
import ProductVisualReadinessPanel from "./ProductVisualReadinessPanel";

const SOURCE_BADGE: Record<string, string> = {
	FASTMOSS: "bg-indigo-500/20 text-indigo-300",
	TIKTOKSHOP: "bg-pink-500/20 text-pink-300",
	MANUAL: "bg-emerald-500/20 text-emerald-300",
	IMPORTED: "bg-amber-500/20 text-amber-300",
};

const RISK_BADGE: Record<string, string> = {
	LOW: "bg-emerald-500/20 text-emerald-400",
	MEDIUM: "bg-amber-500/20 text-amber-400",
	HIGH: "bg-red-500/20 text-red-400",
	UNKNOWN: "bg-slate-500/20 text-slate-400",
};

const STATUS_BADGE: Record<string, string> = {
	ACTIVE: "bg-emerald-500/20 text-emerald-300",
	ARCHIVED: "bg-slate-600/30 text-slate-400",
	DELETED_TEST_ONLY: "bg-red-500/20 text-red-300",
};

const FRESHNESS_BADGE: Record<string, string> = {
	FRESH: "bg-emerald-500/20 text-emerald-300",
	STALE: "bg-indigo-500/20 text-indigo-300",
	UNKNOWN: "bg-slate-600/20 text-slate-500",
};

const DRAFT_BADGE: Record<string, string> = {
	NEEDS_HUMAN_REVIEW: "bg-amber-500/20 text-amber-300",
	BLOCKED: "bg-red-500/20 text-red-300",
	DRAFT: "bg-sky-500/20 text-sky-300",
};

// Filter option sets. "" = no filter. Status maps to lifecycle; the rest map 1:1
// to the server facet params.
const STATUS_OPTIONS = [
	{ value: "ACTIVE", label: "Active" },
	{ value: "ARCHIVED", label: "Archived" },
	{ value: "ALL", label: "All" },
];
const FRESHNESS_OPTIONS = ["FRESH", "STALE", "UNKNOWN"];
const RISK_OPTIONS = ["LOW", "MEDIUM", "HIGH"];
const IMAGE_OPTIONS = ["READY", "MISSING"];

const PAGE_SIZE = 50;

const getErrorMessage = (error: unknown, fallback: string) =>
	error instanceof Error && error.message ? error.message : fallback;

// image_url → rendered_img_src → image_analysis.image_url (same fail-open order the
// rest of the app uses). local_image_path is a server FS path, not browser-loadable.
const resolveThumb = (product: Product): string | null =>
	product.image_url ||
	product.rendered_img_src ||
	product.image_analysis?.image_url ||
	null;

const fmtMoney = (value: number | null | undefined): string =>
	value == null || Number.isNaN(Number(value))
		? "—"
		: `RM ${Number(value).toFixed(2)}`;

const fmtCount = (value: number | null | undefined): string =>
	value == null ? "—" : Number(value).toLocaleString();

const fmtPercent = (value: string | null | undefined): string => {
	if (!value) return "—";
	const raw = String(value).trim();
	return raw.endsWith("%") ? raw : raw;
};

const SELECT_CLASS =
	"bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1.5 focus:outline-none focus:border-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed";
const LABEL_CLASS =
	"text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1";

interface Props {
	onOpenProduct?: (productId: string) => void;
}

export default function AllProductsTab({ onOpenProduct }: Props) {
	const [search, setSearch] = useState("");
	const [debouncedSearch, setDebouncedSearch] = useState("");
	const [status, setStatus] = useState("ACTIVE");
	const [freshness, setFreshness] = useState("");
	const [risk, setRisk] = useState("");
	const [image, setImage] = useState("");
	const [cluster, setCluster] = useState("");
	const [productType, setProductType] = useState("");
	const [offset, setOffset] = useState(0);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [data, setData] = useState<ProductCatalogResponse | null>(null);
	const [bulkPreview, setBulkPreview] = useState<ProductVisualBulkPreview | null>(null);
	const [bulkRun, setBulkRun] = useState<ProductVisualBulkRun | null>(null);
	const [bulkBusy, setBulkBusy] = useState(false);
	const [canvaBulkPreview, setCanvaBulkPreview] = useState<CanvaCutoutBulkPreview | null>(null);
	const [canvaBulkRun, setCanvaBulkRun] = useState<CanvaCutoutBulkRun | null>(null);
	const [canvaBulkBusy, setCanvaBulkBusy] = useState(false);
	const [canvaTransparentExport, setCanvaTransparentExport] = useState<CanvaCapabilityStatus>("UNKNOWN");
	const [canvaBulkMethod, setCanvaBulkMethod] = useState<CanvaMethod>("MAGIC_GRAB");

	// Cluster list + cluster → product_type_group map (dependent Product Type dropdown).
	const [clusters, setClusters] = useState<string[]>([]);
	const [clusterToTypes, setClusterToTypes] = useState<
		Record<string, string[]>
	>({});

	useEffect(() => {
		let cancelled = false;
		void (async () => {
			try {
				const registry = await fetchProductStrategyTypeRegistry();
				if (cancelled) return;
				const byCluster: Record<string, Set<string>> = {};
				for (const entry of registry.items) {
					(byCluster[entry.cluster] ??= new Set()).add(
						entry.product_type_group,
					);
				}
				const map: Record<string, string[]> = {};
				for (const [c, set] of Object.entries(byCluster))
					map[c] = Array.from(set).sort();
				setClusterToTypes(map);
				setClusters(
					(registry.clusters?.length ? registry.clusters : Object.keys(map))
						.slice()
						.sort(),
				);
			} catch {
				// Non-fatal — cluster/type dropdowns stay empty, rest still works.
			}
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	const productTypeOptions = cluster ? (clusterToTypes[cluster] ?? []) : [];

	const activeFilterCount =
		(status !== "ACTIVE" ? 1 : 0) +
		(freshness ? 1 : 0) +
		(risk ? 1 : 0) +
		(image ? 1 : 0) +
		(cluster ? 1 : 0) +
		(productType ? 1 : 0) +
		(debouncedSearch.trim() ? 1 : 0);

	const clearFilters = () => {
		setSearch("");
		setStatus("ACTIVE");
		setFreshness("");
		setRisk("");
		setImage("");
		setCluster("");
		setProductType("");
		setOffset(0);
	};

	useEffect(() => {
		const handle = setTimeout(() => {
			setDebouncedSearch(search);
			setOffset(0);
		}, 300);
		return () => clearTimeout(handle);
	}, [search]);

	const fetchRows = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const result = await fetchProductRegistry({
				// All Products = the committed catalog. Read-only FastMoss reference rows
				// have no product record (opening one 404s the detail panels), so keep
				// them out — they live in Import FastMoss until converted.
				excludeReference: true,
				q: debouncedSearch.trim() || undefined,
				cluster: cluster || undefined,
				productTypeGroup: productType || undefined,
				claimRiskLevel: risk || undefined,
				freshness: freshness || undefined,
				image: image || undefined,
				// Status = lifecycle. Active excludes archived (default); Archived shows
				// only archived; All shows both.
				includeArchived: status === "ALL",
				lifecycleStatus: status === "ARCHIVED" ? "ARCHIVED" : undefined,
				limit: PAGE_SIZE,
				offset,
			});
			setData(result);
		} catch (e: unknown) {
			setError(getErrorMessage(e, "Failed to load products"));
		} finally {
			setLoading(false);
		}
	}, [debouncedSearch, cluster, productType, risk, freshness, image, status, offset]);

	useEffect(() => {
		void fetchRows();
	}, [fetchRows]);

	const total = data?.total_count ?? 0;
	const rows = data?.items ?? [];
	const hasPrev = offset > 0;
	const hasNext = offset + PAGE_SIZE < total;
	const rangeStart = total === 0 ? 0 : offset + 1;
	const rangeEnd = Math.min(offset + PAGE_SIZE, total);

	const updateVisualReadiness = useCallback(
		(productId: string, visualReadiness: Product["visual_readiness"]) => {
			setData((previous) =>
				previous
					? {
							...previous,
							items: previous.items.map((item) =>
								item.id === productId
									? { ...item, visual_readiness: visualReadiness }
									: item,
							),
						}
					: previous,
			);
		},
		[],
	);

	async function openBulkPreview() {
		setBulkBusy(true);
		setError(null);
		try {
			setBulkRun(null);
			setBulkPreview(await fetchProductVisualBulkPreview(1000));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not preview missing cutouts"));
		} finally {
			setBulkBusy(false);
		}
	}

	async function confirmBulkPrepare() {
		if (!bulkPreview) return;
		const boundedBatch = bulkPreview.bounded_batch?.default_size ?? 5;
		if (!window.confirm(`Prepare a bounded batch of up to ${boundedBatch} of ${bulkPreview.counts.eligible} auto-cutout candidates for human review? No provider calls or approvals will occur.`)) return;
		setBulkBusy(true);
		setError(null);
		try {
			setBulkRun(await queueProductVisualBulkPrepare({ preview_digest: bulkPreview.preview_digest, batch_size: boundedBatch, max_products: boundedBatch }));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not queue cutout preparation"));
		} finally {
			setBulkBusy(false);
		}
	}

	async function openCanvaBulkPreview() {
		setCanvaBulkBusy(true);
		setError(null);
		try {
			setCanvaBulkRun(null);
			setCanvaBulkPreview(await fetchCanvaCutoutBulkPreview(1000));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not preview Canva cutouts"));
		} finally {
			setCanvaBulkBusy(false);
		}
	}

	async function confirmCanvaBulkPrepare() {
		if (!canvaBulkPreview) return;
		const bounded = canvaBulkPreview.bounded_batch?.default_size ?? 3;
		if (!window.confirm(`Prepare a resumable Canva operator queue for up to ${bounded} products? Canva editing remains user/browser-controller work; no provider calls or approvals will occur.`)) return;
		setCanvaBulkBusy(true);
		setError(null);
		try {
			setCanvaBulkRun(await queueCanvaCutoutBulk({
				preview_digest: canvaBulkPreview.preview_digest,
				max_products: bounded,
				preflight: {
					canva_method: canvaBulkMethod,
					login_status: "UNKNOWN",
					magic_grab_status: "UNKNOWN",
					background_remover_status: "UNKNOWN",
					magic_layers_status: "UNKNOWN",
					transparent_export_status: canvaTransparentExport,
				},
			}));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not queue Canva cutouts"));
		} finally {
			setCanvaBulkBusy(false);
		}
	}

	async function pauseCanvaBulk() {
		if (!canvaBulkRun) return;
		setCanvaBulkBusy(true);
		try {
			setCanvaBulkRun(await pauseCanvaCutoutBulk(canvaBulkRun.run_id));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not pause Canva queue"));
		} finally {
			setCanvaBulkBusy(false);
		}
	}

	async function resumeCanvaBulk() {
		if (!canvaBulkRun) return;
		if (!window.confirm("Confirm Canva login, at least one method, and transparent PNG export entitlement before resuming.")) return;
		setCanvaBulkBusy(true);
		try {
			setCanvaBulkRun(await resumeCanvaCutoutBulk(canvaBulkRun.run_id, {
				login_status: "READY",
				magic_grab_status: canvaBulkMethod === "MAGIC_GRAB" ? "READY" : "UNKNOWN",
				background_remover_status: canvaBulkMethod === "BACKGROUND_REMOVER" ? "READY" : "UNKNOWN",
				magic_layers_status: canvaBulkMethod === "MAGIC_LAYERS" ? "READY" : "UNKNOWN",
				transparent_export_status: "READY",
			}));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not resume Canva queue"));
		} finally {
			setCanvaBulkBusy(false);
		}
	}

	async function cancelCanvaBulk() {
		if (!canvaBulkRun || !window.confirm("Cancel the remaining Canva queue? Completed and pending-review products remain preserved.")) return;
		setCanvaBulkBusy(true);
		try {
			setCanvaBulkRun(await cancelCanvaCutoutBulk(canvaBulkRun.run_id));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not cancel Canva queue"));
		} finally {
			setCanvaBulkBusy(false);
		}
	}

	async function bypassCanvaBulkItem(productId: string) {
		if (!canvaBulkRun) return;
		const operator = window.prompt("Operator identity")?.trim() || "";
		const reason = window.prompt("Why bypass this product in the Canva queue?")?.trim() || "";
		if (!operator || !reason) return;
		setCanvaBulkBusy(true);
		setError(null);
		try {
			setCanvaBulkRun(await bypassCanvaCutoutBulkItem(canvaBulkRun.run_id, productId, operator, reason));
		} catch (err: unknown) {
			setError(getErrorMessage(err, "Could not bypass Canva queue item"));
		} finally {
			setCanvaBulkBusy(false);
		}
	}

	return (
		<div className="space-y-5">
			{/* Header */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<div>
						<h3 className="text-sm font-bold text-white">All Products</h3>
						<p className="text-[11px] text-slate-400 mt-0.5">
							Every committed product across all sources (Manual / TikTok /
							FastMoss) —{" "}
							<span className="font-semibold text-slate-200">
								{total.toLocaleString()}
							</span>{" "}
							matching the filters.
						</p>
					</div>
					<div className="flex items-center gap-2">
						<button type="button" onClick={() => void openCanvaBulkPreview()} disabled={canvaBulkBusy} className="rounded-lg bg-violet-600/90 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40" data-testid="prepare-canva-cutouts">
							{canvaBulkBusy ? "Loading Canva…" : "Prepare Canva Cutouts"}
						</button>
						<button type="button" onClick={() => void openBulkPreview()} disabled={bulkBusy} className="rounded-lg bg-indigo-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40" data-testid="prepare-missing-cutouts">
							{bulkBusy ? "Loading…" : "Prepare Bounded Auto Batch"}
						</button>
						<span className="px-2 py-0.5 rounded text-[9px] font-bold bg-slate-700/30 text-slate-400">
							Total: {total.toLocaleString()}
						</span>
					</div>
				</div>
			</div>

			{bulkPreview && (
				<div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4" data-testid="cutout-bulk-preview">
					<div className="flex flex-wrap items-center justify-between gap-3">
						<div>
							<div className="text-xs font-bold text-white">Cutout preparation preview</div>
							<div className="mt-1 text-[10px] text-slate-400">Preview only: archived, purged aliases, fixtures, approved locks, rejected candidates, and rows without trusted media are excluded. Execution is bounded and requires confirmation.</div>
						</div>
						<button type="button" onClick={() => void confirmBulkPrepare()} disabled={bulkBusy || bulkPreview.counts.eligible === 0} className="rounded-lg bg-emerald-600/80 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
							Confirm &amp; Queue
						</button>
					</div>
					<div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-slate-300 md:grid-cols-5">
						<div>Eligible <span className="font-bold text-white">{bulkPreview.counts.eligible}</span></div>
						<div>Approved <span className="font-bold text-emerald-300">{bulkPreview.counts.already_approved}</span></div>
						<div>Pending <span className="font-bold text-amber-300">{bulkPreview.counts.pending_review}</span></div>
						<div>Blocked <span className="font-bold text-red-300">{bulkPreview.counts.blocked}</span></div>
						<div>Skipped <span className="font-bold text-slate-400">{bulkPreview.counts.skipped}</span></div>
					</div>
					<div className="mt-3 text-[10px] text-slate-400">Batch limit <span className="font-bold text-white">{bulkPreview.bounded_batch?.default_size ?? 5}</span> (max {bulkPreview.bounded_batch?.max_size ?? 25}) · {bulkPreview.bounded_batch?.estimated_throughput ?? "Throughput measured from completed local runs"}</div>
					{bulkRun && <div className="mt-3 text-[10px] text-sky-200">Run {bulkRun.run_id}: {bulkRun.status} · {bulkRun.total_expected} queued · provider operations {bulkRun.provider_operations}</div>}
				</div>
			)}

			{canvaBulkPreview && (
				<div className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-4" data-testid="canva-bulk-preview">
					<div className="flex flex-wrap items-center justify-between gap-3">
						<div>
							<div className="text-xs font-bold text-white">Canva cutout queue preview</div>
							<div className="mt-1 text-[10px] text-slate-400">Preview only. The queue persists pause/resume/cancel state, but Canva editing remains operator/browser-controller work and every result enters PENDING_HUMAN_REVIEW.</div>
						</div>
						<button type="button" onClick={() => void confirmCanvaBulkPrepare()} disabled={canvaBulkBusy || canvaBulkPreview.counts.eligible === 0} className="rounded-lg bg-violet-600/80 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">Confirm &amp; Queue</button>
					</div>
					<div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-slate-300 md:grid-cols-7">
						<div>Eligible <span className="font-bold text-white">{canvaBulkPreview.counts.eligible}</span></div>
						<div>Approved <span className="font-bold text-emerald-300">{canvaBulkPreview.counts.already_approved}</span></div>
						<div>Pending <span className="font-bold text-amber-300">{canvaBulkPreview.counts.pending_review}</span></div>
						<div>Pro blocked <span className="font-bold text-red-300">{canvaBulkPreview.counts.canva_pro_required}</span></div>
						<div>Missing source <span className="font-bold text-red-300">{canvaBulkPreview.counts.missing_source}</span></div>
						<div>Blocked <span className="font-bold text-red-300">{canvaBulkPreview.counts.blocked}</span></div>
						<div>Remaining <span className="font-bold text-violet-200">{canvaBulkPreview.remaining}</span></div>
					</div>
					<div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
						<label>Transparent export preflight
							<select value={canvaTransparentExport} onChange={(event) => setCanvaTransparentExport(event.target.value as CanvaCapabilityStatus)} className="ml-2 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200">
								<option value="UNKNOWN">UNKNOWN</option>
								<option value="READY">READY</option>
								<option value="PRO_REQUIRED">PRO REQUIRED</option>
							</select>
						</label>
						<label>Queue method
							<select value={canvaBulkMethod} onChange={(event) => setCanvaBulkMethod(event.target.value as CanvaMethod)} className="ml-2 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200">
								<option value="MAGIC_GRAB">Magic Grab</option>
								<option value="BACKGROUND_REMOVER">Background Remover</option>
								<option value="MAGIC_LAYERS">Magic Layers</option>
							</select>
						</label>
						<span>Bounded batch {canvaBulkPreview.bounded_batch?.default_size ?? 3} (max {canvaBulkPreview.bounded_batch?.max_size ?? 25})</span>
					</div>
					{canvaBulkRun && <div className="mt-3 rounded border border-slate-700/70 bg-slate-900/50 p-3 text-[10px] text-sky-200">
						<div>Run {canvaBulkRun.run_id}: {canvaBulkRun.status} · processed {canvaBulkRun.total_processed}/{canvaBulkRun.total_expected} · pending review {canvaBulkRun.total_pending_review} · bypassed {canvaBulkRun.total_bypassed}</div>
						<div className="mt-2 flex flex-wrap gap-2">
							{!['COMPLETED', 'FAILED', 'CANCELLED'].includes(canvaBulkRun.status) && <>
								<button type="button" onClick={() => void pauseCanvaBulk()} disabled={canvaBulkBusy} className="rounded bg-slate-700 px-2 py-1 font-bold uppercase tracking-widest text-slate-200">Pause</button>
								<button type="button" onClick={() => void resumeCanvaBulk()} disabled={canvaBulkBusy} className="rounded bg-emerald-600/70 px-2 py-1 font-bold uppercase tracking-widest text-white">Resume</button>
								<button type="button" onClick={() => void cancelCanvaBulk()} disabled={canvaBulkBusy} className="rounded bg-red-500/30 px-2 py-1 font-bold uppercase tracking-widest text-red-200">Cancel</button>
							</>}
						</div>
						<div className="mt-2 text-slate-400">Per-product Canva Cutout remains available in each row and can bypass this queue safely.</div>
						{canvaBulkRun.items?.length > 0 && <div className="mt-3 space-y-1 border-t border-slate-800 pt-2">
							{canvaBulkRun.items.map((item) => {
								const terminal = ["APPROVED", "PENDING_HUMAN_REVIEW", "CANCELLED", "BYPASSED"].includes(item.current_stage);
								return <div key={item.item_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-slate-950/40 px-2 py-1.5 text-slate-300">
									<span>{item.product_id} · {item.current_stage}{item.priority === 0 ? " · priority" : ""}</span>
									{!terminal && <button type="button" onClick={() => void bypassCanvaBulkItem(item.product_id)} disabled={canvaBulkBusy} className="rounded bg-amber-500/20 px-2 py-1 font-bold uppercase tracking-widest text-amber-200 disabled:opacity-40">Bypass</button>}
								</div>;
							})}
						</div>}
					</div>}
				</div>
			)}

			{/* Error */}
			{error && (
				<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
					{error}
					<button
						type="button"
						onClick={() => setError(null)}
						className="ml-3 text-slate-500 hover:text-white"
					>
						✕
					</button>
				</div>
			)}

			{/* Filter bar */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="flex flex-wrap items-end gap-3">
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Status</span>
						<select
							value={status}
							onChange={(e) => {
								setStatus(e.target.value);
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-28`}
						>
							{STATUS_OPTIONS.map((o) => (
								<option key={o.value} value={o.value}>
									{o.label}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Freshness</span>
						<select
							value={freshness}
							onChange={(e) => {
								setFreshness(e.target.value);
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-28`}
						>
							<option value="">All</option>
							{FRESHNESS_OPTIONS.map((o) => (
								<option key={o} value={o}>
									{o}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Risk</span>
						<select
							value={risk}
							onChange={(e) => {
								setRisk(e.target.value);
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-24`}
						>
							<option value="">All</option>
							{RISK_OPTIONS.map((o) => (
								<option key={o} value={o}>
									{o}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Image</span>
						<select
							value={image}
							onChange={(e) => {
								setImage(e.target.value);
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-28`}
						>
							<option value="">All</option>
							{IMAGE_OPTIONS.map((o) => (
								<option key={o} value={o}>
									{o}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Cluster</span>
						<select
							value={cluster}
							onChange={(e) => {
								setCluster(e.target.value);
								setProductType(""); // dependent type resets with its cluster
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-44`}
						>
							<option value="">All</option>
							{clusters.map((c) => (
								<option key={c} value={c}>
									{c}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Product Type</span>
						<select
							value={productType}
							onChange={(e) => {
								setProductType(e.target.value);
								setOffset(0);
							}}
							disabled={!cluster}
							className={`${SELECT_CLASS} w-44`}
						>
							<option value="">{cluster ? "All" : "Pick a cluster first"}</option>
							{productTypeOptions.map((t) => (
								<option key={t} value={t}>
									{t}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Search</span>
						<input
							type="text"
							value={search}
							onChange={(e) => setSearch(e.target.value)}
							placeholder="product title…"
							className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1.5 w-48 focus:outline-none focus:border-indigo-500"
						/>
					</div>
					<button
						type="button"
						onClick={clearFilters}
						disabled={activeFilterCount === 0}
						className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed text-[10px] font-bold uppercase tracking-widest transition-colors"
					>
						Clear{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
					</button>
				</div>
			</div>

			{/* Table */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
				{loading ? (
					<div className="p-8 text-center text-slate-500 text-xs">Loading…</div>
				) : rows.length === 0 ? (
					<div className="p-8 text-center text-slate-500 text-xs">
						No products match these filters. Try widening the cluster / type /
						status, or clear the filters.
					</div>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full text-xs text-slate-300 whitespace-nowrap">
							<thead>
								<tr className="border-b border-slate-800 bg-slate-900/80 text-[9px] uppercase tracking-widest text-slate-400">
									<th className="px-3 py-2 text-left font-semibold">Product</th>
									<th className="px-3 py-2 text-left font-semibold">
										Cluster · Type
									</th>
									<th className="px-3 py-2 text-left font-semibold">Risk</th>
									<th className="px-3 py-2 text-left font-semibold">Image</th>
									<th className="px-3 py-2 text-right font-semibold">Sold</th>
									<th className="px-3 py-2 text-right font-semibold">
										Sell price
									</th>
									<th className="px-3 py-2 text-right font-semibold">Comm%</th>
									<th className="px-3 py-2 text-right font-semibold">Comm amt</th>
									<th className="px-3 py-2 text-right font-semibold">Image (u)</th>
									<th className="px-3 py-2 text-right font-semibold">Video (u)</th>
									<th className="px-3 py-2 text-left font-semibold">Status</th>
									<th className="px-3 py-2 text-left font-semibold">Visual</th>
									<th className="px-3 py-2 text-left font-semibold">Freshness</th>
									<th className="px-3 py-2 text-left font-semibold">Draft</th>
									<th className="px-3 py-2 text-left font-semibold">Actions</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((product) => {
									const thumb = resolveThumb(product);
									const riskLevel = (product.claim_risk_level || "").toUpperCase();
									const clusterType =
										[
											product.strategy_taxonomy?.cluster,
											product.strategy_taxonomy?.product_type_group,
										]
											.filter(Boolean)
											.join(" · ") || "—";
									const lifecycle = (product.lifecycle_status || "").toUpperCase();
									const fresh = (product.freshness || "").toUpperCase();
									const draft = product.open_review_draft;
									const sold =
										product.sold_count ?? product.product_sold_count ?? null;
									return (
										<tr
											key={product.id}
											onClick={() => onOpenProduct?.(product.id)}
											className={`border-b border-slate-800/50 transition-colors ${
												onOpenProduct
													? "cursor-pointer hover:bg-slate-800/40"
													: ""
											}`}
										>
											<td className="px-3 py-2 max-w-[220px]">
												<div className="font-medium text-white truncate max-w-[210px]">
													{product.product_display_name ||
														product.raw_product_title}
												</div>
												<div className="flex items-center gap-1.5 mt-0.5">
													<span
														className={`px-1 py-0.5 rounded text-[8px] font-bold ${
															SOURCE_BADGE[product.source || ""] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{product.source}
													</span>
													<span className="text-[8px] text-slate-600 font-mono truncate max-w-[120px]">
														{product.id.slice(0, 8)}
													</span>
												</div>
											</td>
											<td className="px-3 py-2 text-slate-300 max-w-[150px] truncate">
												{clusterType}
											</td>
											<td className="px-3 py-2">
												{riskLevel ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															RISK_BADGE[riskLevel] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{riskLevel}
													</span>
												) : (
													<span className="text-[9px] text-slate-600">—</span>
												)}
											</td>
											<td className="px-3 py-2">
												{thumb ? (
													<img
														src={thumb}
														alt=""
														className="w-8 h-8 rounded object-cover border border-slate-700"
														onError={(e) => {
															(e.target as HTMLImageElement).style.display =
																"none";
														}}
													/>
												) : (
													<div className="w-8 h-8 rounded bg-slate-800 border border-slate-700" />
												)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-slate-300">
												{fmtCount(sold)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-slate-300">
												{fmtMoney(product.price)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-slate-400">
												{fmtPercent(product.commission_rate)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-slate-300">
												{fmtMoney(product.commission_amount)}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-slate-400">
												{product.source_media_image_count ?? 0}
											</td>
											<td className="px-3 py-2 text-right tabular-nums text-slate-400">
												{product.source_media_video_count ?? 0}
											</td>
											<td className="px-3 py-2">
												{lifecycle ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															STATUS_BADGE[lifecycle] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{lifecycle.replace(/_/g, " ")}
													</span>
												) : (
														<span className="text-[9px] text-slate-600">—</span>
													)}
											</td>
											<td className="px-3 py-2" onClick={(event) => event.stopPropagation()}>
												<ProductVisualReadinessPanel
													productId={product.id}
													productSourceUrl={product.tiktok_product_url || product.source_url}
													readiness={product.visual_readiness}
													compact
													onOpenReview={() => onOpenProduct?.(product.id)}
													onChanged={(next) => updateVisualReadiness(product.id, next)}
												/>
											</td>
											<td className="px-3 py-2">
												{fresh ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															FRESHNESS_BADGE[fresh] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{fresh}
													</span>
												) : (
													<span className="text-[9px] text-slate-600">—</span>
												)}
											</td>
											<td className="px-3 py-2">
												{draft ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															DRAFT_BADGE[draft.review_status] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{draft.review_status.replace(/_/g, " ")}
													</span>
												) : (
													<span className="text-[9px] text-slate-600">—</span>
												)}
											</td>
											<td className="px-3 py-2">
												<button
													type="button"
													onClick={(e) => {
														e.stopPropagation();
														onOpenProduct?.(product.id);
													}}
													disabled={!onOpenProduct}
													className="px-2 py-1 rounded-lg bg-sky-600/20 hover:bg-sky-600/40 disabled:opacity-40 disabled:cursor-not-allowed text-sky-300 text-[9px] font-bold uppercase tracking-widest transition-all"
												>
													Open
												</button>
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				)}
			</div>

			{/* Pagination */}
			{total > PAGE_SIZE && (
				<div className="flex items-center justify-between px-1">
					<span className="text-[10px] text-slate-500">
						{rangeStart}–{rangeEnd} of {total.toLocaleString()}
					</span>
					<div className="flex gap-2">
						<button
							type="button"
							onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
							disabled={!hasPrev || loading}
							className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40 text-[10px] uppercase tracking-widest"
						>
							‹ Prev
						</button>
						<button
							type="button"
							onClick={() => setOffset((o) => o + PAGE_SIZE)}
							disabled={!hasNext || loading}
							className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40 text-[10px] uppercase tracking-widest"
						>
							Next ›
						</button>
					</div>
				</div>
			)}
		</div>
	);
}
