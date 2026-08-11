import { useCallback, useEffect, useState } from "react";
import {
	fetchProductRegistry,
	fetchProductStrategyTypeRegistry,
} from "../../api/products";
import type { Product, ProductCatalogResponse } from "../../types";

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

const TABLE_VISUAL_BADGE = {
	ready: "bg-emerald-500/15 text-emerald-300",
	fallback: "bg-amber-500/15 text-amber-300",
	required: "bg-red-500/15 text-red-300",
	pending: "bg-sky-500/15 text-sky-300",
	canva: "bg-violet-500/15 text-violet-300",
} as const;

function getTableVisualStatus(
	readiness: Product["visual_readiness"],
): { label: string; className: string } {
	if (!readiness) {
		return { label: "CUTOUT REQUIRED", className: TABLE_VISUAL_BADGE.required };
	}

	const canvaStage =
		readiness.canva_cutout_workflow?.current_stage || readiness.canva_cutout_stage;
	if (canvaStage === "CANVA_PRO_REQUIRED") {
		return {
			label: "CANVA PRO REQUIRED",
			className: TABLE_VISUAL_BADGE.canva,
		};
	}

	if (
		readiness.cutout_status === "PENDING_REVIEW" ||
		readiness.cutout_review_status === "PENDING_REVIEW" ||
		readiness.can_review_cutout
	) {
		return { label: "PENDING REVIEW", className: TABLE_VISUAL_BADGE.pending };
	}

	if (
		readiness.cutout_status === "APPROVED" ||
		readiness.exact_commerce_status === "EXACT_COMMERCE_CUTOUT_READY"
	) {
		return { label: "READY", className: TABLE_VISUAL_BADGE.ready };
	}

	if (
		readiness.visual_grounding_status === "VISUAL_GROUNDING_READY_FALLBACK" ||
		readiness.active_visual_source === "SAME_PRODUCT_TRUSTED_SOURCE"
	) {
		return { label: "FALLBACK", className: TABLE_VISUAL_BADGE.fallback };
	}

	return { label: "CUTOUT REQUIRED", className: TABLE_VISUAL_BADGE.required };
}

function getTableVisualAction(
	readiness: Product["visual_readiness"],
): "Canva Cutout" | "Review" | "Upload Cutout" {
	if (readiness?.can_review_cutout) return "Review";
	if (
		readiness?.canonical_media_status === "AVAILABLE" &&
		readiness.can_start_canva_cutout === true
	) {
		return "Canva Cutout";
	}
	if (readiness?.can_upload_manual_cutout) return "Upload Cutout";
	return "Review";
}

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

	return (
		<div className="min-w-0 space-y-5">
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
						<span className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-400" data-testid="per-product-visual-workflow">
							Visual work is per product
						</span>
						<span className="px-2 py-0.5 rounded text-[9px] font-bold bg-slate-700/30 text-slate-400">
							Total: {total.toLocaleString()}
						</span>
					</div>
				</div>
			</div>

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
			<div className="min-w-0 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/40">
				{loading ? (
					<div className="p-8 text-center text-slate-500 text-xs">Loading…</div>
				) : rows.length === 0 ? (
					<div className="p-8 text-center text-slate-500 text-xs">
						No products match these filters. Try widening the cluster / type /
						status, or clear the filters.
					</div>
				) : (
					<div className="min-w-0 overflow-x-auto overscroll-x-contain">
						<table
							data-testid="product-registry-table"
							className="min-w-[1656px] w-full table-fixed text-xs text-slate-300 whitespace-normal"
						>
							<colgroup>
								<col className="w-[220px]" />
								<col className="w-[150px]" />
								<col className="w-[80px]" />
								<col className="w-[70px]" />
								<col className="w-[85px]" />
								<col className="w-[105px]" />
								<col className="w-[76px]" />
								<col className="w-[100px]" />
								<col className="w-[70px]" />
								<col className="w-[70px]" />
								<col className="w-[90px]" />
								<col className="w-[260px]" />
								<col className="w-[90px]" />
								<col className="w-[100px]" />
								<col className="w-[90px]" />
							</colgroup>
							<thead>
								<tr className="border-b border-slate-800 bg-slate-900/80 text-[9px] uppercase tracking-widest text-slate-400">
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Product</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">
										Cluster · Type
									</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Risk</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Image</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-semibold">Sold</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-semibold">
										Sell price
									</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-semibold">Comm%</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-semibold">Comm amt</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-semibold">Image (u)</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-semibold">Video (u)</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Status</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Visual</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Freshness</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Draft</th>
									<th scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold">Actions</th>
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
									const visualStatus = getTableVisualStatus(product.visual_readiness);
									const visualAction = getTableVisualAction(product.visual_readiness);
									const visualCanvasLabel =
										product.visual_readiness?.visual_canvas_label ||
										(product.visual_canvas_width && product.visual_canvas_height
											? `${product.visual_canvas_width}×${product.visual_canvas_height} px`
											: "1000×1000 px");
									const sold =
										product.sold_count ?? product.product_sold_count ?? null;
									return (
										<tr
											key={product.id}
											onClick={() => onOpenProduct?.(product.id)}
											className={`align-top border-b border-slate-800/50 transition-colors ${
												onOpenProduct
													? "cursor-pointer hover:bg-slate-800/40"
													: ""
											}`}
										>
											<td className="w-[220px] max-w-[220px] px-3 py-3 align-top">
												<div className="min-w-0 max-w-[210px] truncate font-medium text-white">
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
											<td className="w-[150px] max-w-[150px] break-words px-3 py-3 align-top text-slate-300">
												{clusterType}
											</td>
											<td className="whitespace-nowrap px-3 py-3 align-top">
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
											<td className="whitespace-nowrap px-3 py-3 align-top">
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
											<td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-300">
												{fmtCount(sold)}
											</td>
											<td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-300">
												{fmtMoney(product.price)}
											</td>
											<td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-400">
												{fmtPercent(product.commission_rate)}
											</td>
											<td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-300">
												{fmtMoney(product.commission_amount)}
											</td>
											<td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-400">
												{product.source_media_image_count ?? 0}
											</td>
											<td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-400">
												{product.source_media_video_count ?? 0}
											</td>
											<td className="whitespace-nowrap px-3 py-3 align-top">
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
											<td className="w-[260px] max-w-[260px] px-3 py-2 align-top">
												<div
													className="flex min-w-0 items-center gap-2"
													data-testid="table-visual-summary"
												>
													<div className="h-10 w-10 shrink-0 overflow-hidden rounded border border-slate-700 bg-white">
														{thumb ? (
															<img
																src={thumb}
																alt=""
																className="h-full w-full object-contain"
																onError={(event) => {
																	(event.target as HTMLImageElement).style.display =
																		"none";
																}}
															/>
														) : (
															<span className="flex h-full items-center justify-center text-[10px] text-slate-500">
																—
															</span>
														)}
													</div>
													<div className="min-w-0 flex-1">
														<span
															className={`inline-flex max-w-full truncate rounded px-1.5 py-0.5 text-[9px] font-bold ${visualStatus.className}`}
															title={visualStatus.label}
															data-testid="table-visual-status"
														>
															{visualStatus.label}
														</span>
														<button
															type="button"
															onClick={(event) => {
																event.stopPropagation();
																onOpenProduct?.(product.id);
															}}
															disabled={!onOpenProduct}
															className="mt-1 inline-flex max-w-full truncate rounded bg-violet-600/80 px-2 py-1 text-[9px] font-bold uppercase tracking-widest text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
															data-testid="table-visual-action"
														>
															{visualAction}
														</button>
														<div
															className="mt-1 text-[8px] font-semibold uppercase tracking-widest text-fuchsia-300/80"
															data-testid="table-visual-canvas-requirement"
															title={product.visual_readiness?.visual_canvas_requirement || product.visual_canvas_requirement || undefined}
														>
															Canvas {visualCanvasLabel}
														</div>
													</div>
												</div>
											</td>
											<td className="whitespace-nowrap px-3 py-3 align-top">
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
											<td className="whitespace-nowrap px-3 py-3 align-top">
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
											<td className="whitespace-nowrap px-3 py-3 align-top">
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
