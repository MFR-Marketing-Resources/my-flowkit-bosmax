import { useCallback, useEffect, useMemo, useState } from "react";
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

const LIFECYCLE_BADGE: Record<string, string> = {
	ACTIVE: "bg-emerald-500/20 text-emerald-300",
	ARCHIVED: "bg-slate-600/30 text-slate-400",
	DELETED_TEST_ONLY: "bg-red-500/20 text-red-300",
};

type SourceFilter = "ALL" | "MANUAL" | "TIKTOKSHOP" | "FASTMOSS";

const SOURCE_FILTERS: { value: SourceFilter; label: string }[] = [
	{ value: "ALL", label: "Semua" },
	{ value: "MANUAL", label: "Manual" },
	{ value: "TIKTOKSHOP", label: "TikTok Shop" },
	{ value: "FASTMOSS", label: "FastMoss" },
];

// PI state + risk are stable server enums; lifecycle maps to include-archived / a
// specific lifecycle_status (see fetchRows). Empty value = no filter.
const PI_STATUS_OPTIONS = ["READY", "NEEDS_REVIEW", "MISSING"];
const RISK_OPTIONS = ["LOW", "MEDIUM", "HIGH"];
type LifecycleFilter = "ACTIVE" | "ARCHIVED" | "ALL";

const PAGE_SIZE = 50;

const getErrorMessage = (error: unknown, fallback: string) => {
	if (error instanceof Error && error.message) {
		return error.message;
	}
	return fallback;
};

// Same fail-open resolver order the rest of the app uses for a product's
// reference image (image_url → rendered_img_src → image_analysis.image_url).
// local_image_path is a server FS path, not a browser-loadable URL, so it is
// not a thumbnail source here.
const resolveThumb = (product: Product): string | null =>
	product.image_url ||
	product.rendered_img_src ||
	product.image_analysis?.image_url ||
	null;

const SELECT_CLASS =
	"bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1.5 focus:outline-none focus:border-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed";
const LABEL_CLASS =
	"text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1";

interface Props {
	onOpenProduct?: (productId: string) => void;
}

export default function AllProductsTab({ onOpenProduct }: Props) {
	const [sourceFilter, setSourceFilter] = useState<SourceFilter>("ALL");
	const [search, setSearch] = useState("");
	const [debouncedSearch, setDebouncedSearch] = useState("");
	const [cluster, setCluster] = useState("");
	const [productType, setProductType] = useState("");
	const [intelligenceStatus, setIntelligenceStatus] = useState("");
	const [risk, setRisk] = useState("");
	const [lifecycle, setLifecycle] = useState<LifecycleFilter>("ACTIVE");
	const [offset, setOffset] = useState(0);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [data, setData] = useState<ProductCatalogResponse | null>(null);

	// Cluster list + the cluster → product_type_group map that powers the
	// dependent Product Type dropdown. Loaded once from the strategy-type registry.
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
				for (const [c, set] of Object.entries(byCluster)) {
					map[c] = Array.from(set).sort();
				}
				setClusterToTypes(map);
				setClusters(
					(registry.clusters?.length
						? registry.clusters
						: Object.keys(map)
					)
						.slice()
						.sort(),
				);
			} catch {
				// Non-fatal: the cluster/type dropdowns simply stay empty; the rest of
				// the catalog browser (source/search/status/risk) still works.
			}
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	// Product Type options depend on the selected cluster. With no cluster chosen,
	// offer every registered type (filter-by-type-alone stays possible).
	const productTypeOptions = useMemo(() => {
		if (cluster) return clusterToTypes[cluster] ?? [];
		const all = new Set<string>();
		for (const list of Object.values(clusterToTypes))
			for (const t of list) all.add(t);
		return Array.from(all).sort();
	}, [cluster, clusterToTypes]);

	const activeFilterCount =
		(sourceFilter !== "ALL" ? 1 : 0) +
		(cluster ? 1 : 0) +
		(productType ? 1 : 0) +
		(intelligenceStatus ? 1 : 0) +
		(risk ? 1 : 0) +
		(lifecycle !== "ACTIVE" ? 1 : 0) +
		(debouncedSearch.trim() ? 1 : 0);

	const resetFilters = () => {
		setSourceFilter("ALL");
		setSearch("");
		setCluster("");
		setProductType("");
		setIntelligenceStatus("");
		setRisk("");
		setLifecycle("ACTIVE");
		setOffset(0);
	};

	// Debounce the search box so typing does not fire a request per keystroke.
	// A new search always returns to the first page.
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
				source: sourceFilter === "ALL" ? undefined : sourceFilter,
				q: debouncedSearch.trim() || undefined,
				cluster: cluster || undefined,
				productTypeGroup: productType || undefined,
				intelligenceStatus: intelligenceStatus || undefined,
				claimRiskLevel: risk || undefined,
				// "Active" simply excludes archived (matches the old default); the other
				// two are explicit lifecycle views.
				includeArchived: lifecycle === "ALL",
				lifecycleStatus: lifecycle === "ARCHIVED" ? "ARCHIVED" : undefined,
				limit: PAGE_SIZE,
				offset,
			});
			setData(result);
		} catch (e: unknown) {
			setError(getErrorMessage(e, "Failed to load products"));
		} finally {
			setLoading(false);
		}
	}, [
		sourceFilter,
		debouncedSearch,
		cluster,
		productType,
		intelligenceStatus,
		risk,
		lifecycle,
		offset,
	]);

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
		<div className="space-y-5">
			{/* Header */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<div>
						<h3 className="text-sm font-bold text-white">Semua Produk</h3>
						<p className="text-[11px] text-slate-400 mt-0.5">
							Katalog produk yang sudah di-commit —{" "}
							<span className="font-semibold text-slate-200">
								{total.toLocaleString()}
							</span>{" "}
							produk (padan penapis) · semua source: Manual / TikTok / FastMoss.
						</p>
					</div>
					<span className="px-2 py-0.5 rounded text-[9px] font-bold bg-slate-700/30 text-slate-400">
						Total: {total.toLocaleString()}
					</span>
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

			{/* Filter row */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
				{/* Source pills + search + reset */}
				<div className="flex flex-wrap items-center gap-3">
					<div className="flex gap-1 rounded-xl bg-slate-900/60 border border-slate-800 p-1 w-fit">
						{SOURCE_FILTERS.map((option) => (
							<button
								key={option.value}
								type="button"
								onClick={() => {
									setSourceFilter(option.value);
									setOffset(0);
								}}
								className={`px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all ${
									sourceFilter === option.value
										? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/20"
										: "text-slate-400 hover:text-white"
								}`}
							>
								{option.label}
							</button>
						))}
					</div>
					<input
						type="text"
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						placeholder="cari nama produk…"
						className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1.5 w-52 focus:outline-none focus:border-indigo-500"
					/>
					{activeFilterCount > 0 && (
						<button
							type="button"
							onClick={resetFilters}
							className="px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 hover:text-white text-[10px] font-bold uppercase tracking-widest transition-colors"
						>
							Reset ({activeFilterCount})
						</button>
					)}
				</div>

				{/* Dropdown facets: cluster → dependent type, PI status, risk, lifecycle */}
				<div className="flex flex-wrap items-end gap-3">
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Cluster</span>
						<select
							value={cluster}
							onChange={(e) => {
								setCluster(e.target.value);
								setProductType(""); // dependency: type resets with its cluster
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-44`}
						>
							<option value="">Semua cluster</option>
							{clusters.map((c) => (
								<option key={c} value={c}>
									{c}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>
							Product Type{cluster ? ` · ${cluster}` : ""}
						</span>
						<select
							value={productType}
							onChange={(e) => {
								setProductType(e.target.value);
								setOffset(0);
							}}
							disabled={productTypeOptions.length === 0}
							className={`${SELECT_CLASS} w-44`}
						>
							<option value="">
								{cluster ? "Semua type (cluster ini)" : "Semua type"}
							</option>
							{productTypeOptions.map((t) => (
								<option key={t} value={t}>
									{t}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>PI Status</span>
						<select
							value={intelligenceStatus}
							onChange={(e) => {
								setIntelligenceStatus(e.target.value);
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-36`}
						>
							<option value="">Semua</option>
							{PI_STATUS_OPTIONS.map((s) => (
								<option key={s} value={s}>
									{s.replace(/_/g, " ")}
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
							className={`${SELECT_CLASS} w-28`}
						>
							<option value="">Semua</option>
							{RISK_OPTIONS.map((r) => (
								<option key={r} value={r}>
									{r}
								</option>
							))}
						</select>
					</div>
					<div className="flex flex-col">
						<span className={LABEL_CLASS}>Lifecycle</span>
						<select
							value={lifecycle}
							onChange={(e) => {
								setLifecycle(e.target.value as LifecycleFilter);
								setOffset(0);
							}}
							className={`${SELECT_CLASS} w-32`}
						>
							<option value="ACTIVE">Aktif</option>
							<option value="ARCHIVED">Arkib</option>
							<option value="ALL">Semua</option>
						</select>
					</div>
				</div>
			</div>

			{/* Table */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
				{loading ? (
					<div className="p-8 text-center text-slate-500 text-xs">Loading…</div>
				) : rows.length === 0 ? (
					<div className="p-8 text-center text-slate-500 text-xs">
						Tiada produk padan penapis. Cuba longgarkan cluster / type / status
						atau reset penapis.
					</div>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full text-xs text-slate-300">
							<thead>
								<tr className="border-b border-slate-800 bg-slate-900/80">
									<th className="px-3 py-2 w-12 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Img
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest w-64">
										Product
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Source
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Cluster · Type
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Risk
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										PI Status
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Lifecycle
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Actions
									</th>
								</tr>
							</thead>
							<tbody>
								{rows.map((product) => {
									const thumb = resolveThumb(product);
									const riskLevel = (product.claim_risk_level || "").toUpperCase();
									const rowCluster = product.strategy_taxonomy?.cluster;
									const rowType =
										product.strategy_taxonomy?.product_type_group;
									const clusterType =
										[rowCluster, rowType].filter(Boolean).join(" · ") || "—";
									const lifecycleStatus = product.lifecycle_status || null;
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
											<td className="px-3 py-2 w-64">
												<div className="font-medium text-white truncate max-w-[240px]">
													{product.product_display_name ||
														product.raw_product_title}
												</div>
												<div className="text-[9px] text-slate-500 font-mono truncate max-w-[240px] mt-0.5">
													{product.id.slice(0, 18)}…
												</div>
											</td>
											<td className="px-3 py-2">
												<span
													className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
														SOURCE_BADGE[product.source] ||
														"bg-slate-600/20 text-slate-400"
													}`}
												>
													{product.source}
												</span>
											</td>
											<td className="px-3 py-2 text-slate-300 truncate max-w-[150px]">
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
												{product.intelligence_status ? (
													<span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-slate-700/40 text-slate-300">
														{product.intelligence_status.replace(/_/g, " ")}
													</span>
												) : (
													<span className="text-[9px] text-slate-600">—</span>
												)}
											</td>
											<td className="px-3 py-2">
												{lifecycleStatus ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															LIFECYCLE_BADGE[lifecycleStatus] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{lifecycleStatus.replace(/_/g, " ")}
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
													Buka PI
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
