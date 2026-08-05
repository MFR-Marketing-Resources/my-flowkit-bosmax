import { useCallback, useEffect, useState } from "react";
import { fetchProductRegistry } from "../../api/products";
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

interface Props {
	onOpenProduct?: (productId: string) => void;
}

export default function AllProductsTab({ onOpenProduct }: Props) {
	const [sourceFilter, setSourceFilter] = useState<SourceFilter>("ALL");
	const [search, setSearch] = useState("");
	const [debouncedSearch, setDebouncedSearch] = useState("");
	const [includeArchived, setIncludeArchived] = useState(false);
	const [offset, setOffset] = useState(0);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [data, setData] = useState<ProductCatalogResponse | null>(null);

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
				includeArchived,
				limit: PAGE_SIZE,
				offset,
			});
			setData(result);
		} catch (e: unknown) {
			setError(getErrorMessage(e, "Failed to load products"));
		} finally {
			setLoading(false);
		}
	}, [sourceFilter, debouncedSearch, includeArchived, offset]);

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
							produk · semua source: Manual / TikTok / FastMoss.
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
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
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
						className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1.5 w-52"
					/>
					<label className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-400 cursor-pointer">
						<input
							type="checkbox"
							checked={includeArchived}
							onChange={(e) => {
								setIncludeArchived(e.target.checked);
								setOffset(0);
							}}
							className="accent-indigo-500"
						/>
						Include archived
					</label>
				</div>
			</div>

			{/* Table */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
				{loading ? (
					<div className="p-8 text-center text-slate-500 text-xs">Loading…</div>
				) : rows.length === 0 ? (
					<div className="p-8 text-center text-slate-500 text-xs">
						No products found. Try adjusting the source filter or search.
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
									const risk = (product.claim_risk_level || "").toUpperCase();
									const cluster = product.strategy_taxonomy?.cluster;
									const productType =
										product.strategy_taxonomy?.product_type_group;
									const clusterType =
										[cluster, productType].filter(Boolean).join(" · ") || "—";
									const lifecycle = product.lifecycle_status || null;
									return (
										<tr
											key={product.id}
											className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
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
												{risk ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															RISK_BADGE[risk] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{risk}
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
												{lifecycle ? (
													<span
														className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
															LIFECYCLE_BADGE[lifecycle] ||
															"bg-slate-600/20 text-slate-400"
														}`}
													>
														{lifecycle.replace(/_/g, " ")}
													</span>
												) : (
													<span className="text-[9px] text-slate-600">—</span>
												)}
											</td>
											<td className="px-3 py-2">
												<button
													type="button"
													onClick={() => onOpenProduct?.(product.id)}
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
