import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Product, WorkspacePackageReadinessItem } from "../../types";

interface SearchableProductSelectProps {
	products: Product[];
	selectedProduct: Product | null;
	onSelect: (product: Product | null) => void;
	readinessByProductId?: Record<string, WorkspacePackageReadinessItem>;
	isLoadingReadiness?: boolean;
}

/** Return the canonical readiness status for a product, respecting
 *  reference-only state so the badge never falsely shows READY while
 *  the API is still loading or when the product is reference-only. */
function resolveReadinessStatus(
	product: Product,
	readiness: WorkspacePackageReadinessItem | undefined,
	isLoading: boolean,
): string {
	if (product.reference_only) return "REFERENCE_ONLY_PRODUCT";
	if (readiness?.readiness_status) return readiness.readiness_status;
	if (isLoading) return "CHECKING…";
	return "UNKNOWN";
}

function readinessToneClass(status: string): string {
	if (status === "READY")
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
	if (status === "REFERENCE_ONLY_PRODUCT")
		return "border-amber-500/30 bg-amber-500/10 text-amber-100";
	if (status.startsWith("CHECKING"))
		return "border-slate-600/40 bg-slate-800/60 text-slate-400";
	return "border-rose-500/30 bg-rose-500/10 text-rose-200";
}

export default function SearchableProductSelect({
	products,
	selectedProduct,
	onSelect,
	readinessByProductId = {},
	isLoadingReadiness = false,
}: SearchableProductSelectProps) {
	const [isOpen, setIsOpen] = useState(false);
	const [search, setSearch] = useState("");
	const containerRef = useRef<HTMLDivElement>(null);

	const filtered = products.filter((product) =>
		product.raw_product_title.toLowerCase().includes(search.toLowerCase()),
	);

	useEffect(() => {
		const handleClickOutside = (event: MouseEvent) => {
			if (
				containerRef.current &&
				!containerRef.current.contains(event.target as Node)
			) {
				setIsOpen(false);
			}
		};
		document.addEventListener("mousedown", handleClickOutside);
		return () => document.removeEventListener("mousedown", handleClickOutside);
	}, []);

	const sourceLaneLabel = (product: Product) =>
		product.source_label || product.source_lane || product.source;

	return (
		<div className="relative min-w-0" ref={containerRef}>
			<button
				type="button"
				onClick={() => setIsOpen(!isOpen)}
				className="flex w-full min-w-0 items-start justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 transition-all group hover:border-blue-500/50 cursor-pointer"
			>
				<div className="min-w-0 flex-1">
					{selectedProduct ? (
						<>
							<span className="bosmax-wrap-safe block text-sm font-bold text-slate-200">
								{selectedProduct.raw_product_title}
							</span>
							<div className="mt-2 flex flex-wrap items-center gap-2">
								<span className="inline-flex rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] text-blue-200">
									{sourceLaneLabel(selectedProduct)}
								</span>
								{selectedProduct.reference_only ? (
									<span className="inline-flex rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] text-amber-100">
										Reference only
									</span>
								) : null}
								{(() => {
									const status = resolveReadinessStatus(
										selectedProduct,
										readinessByProductId[selectedProduct.id],
										isLoadingReadiness,
									);
									return (
										<span
											className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] ${readinessToneClass(status)}`}
										>
											{status}
										</span>
									);
								})()}
							</div>
							{/* Reference-only: show reason + Bulk FastMoss Convert CTA */}
							{selectedProduct.reference_only ? (
								<div className="bosmax-wrap-safe mt-2 text-[10px] text-amber-200/80 flex items-start justify-between gap-2">
									<span>
										{selectedProduct.catalog_visibility_reason ||
											"FastMoss reference is review-only. Convert eligible references through Bulk FastMoss Convert before workspace generation."}
									</span>
									<a
										href="/product-registration?tab=bulk"
										className="shrink-0 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold text-amber-300 hover:bg-amber-500/20 transition-colors whitespace-nowrap"
									>
										Open Bulk FastMoss Convert
									</a>
								</div>
							) : readinessByProductId[selectedProduct.id]?.detail ? (
								<div className="bosmax-wrap-safe mt-2 text-[10px] text-slate-400">
									{readinessByProductId[selectedProduct.id]?.detail}
								</div>
							) : null}
						</>
					) : (
						<span className="bosmax-wrap-safe block text-sm text-slate-500">
							Search and select product...
						</span>
					)}
				</div>
				<ChevronDown
					size={18}
					className={`text-slate-500 group-hover:text-blue-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
				/>
			</button>

			{isOpen && (
				<div className="absolute z-50 mt-2 w-full min-w-0 overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl shadow-black/50 backdrop-blur-xl">
					<div className="p-3 border-bottom border-slate-800 bg-slate-950/50 flex items-center gap-2">
						<Search size={14} className="text-slate-500" />
						<input
							type="text"
							className="bg-transparent border-none outline-none text-xs text-slate-300 w-full"
							placeholder="Search by name..."
							value={search}
							onChange={(event) => setSearch(event.target.value)}
							onClick={(event) => event.stopPropagation()}
						/>
					</div>

					<div className="max-h-64 overflow-y-auto py-2">
						{filtered.length > 0 ? (
							filtered.map((product) => {
								const readiness = readinessByProductId[product.id];
								const status = resolveReadinessStatus(
									product,
									readiness,
									isLoadingReadiness,
								);
								const toneClass = readinessToneClass(status);
								return (
									<button
										type="button"
										key={product.id}
										onClick={() => {
											onSelect(product);
											setIsOpen(false);
											setSearch("");
										}}
										className={`flex items-start justify-between gap-3 px-4 py-3 text-[11px] transition-colors cursor-pointer w-full text-left ${selectedProduct?.id === product.id ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`}
									>
										<div className="min-w-0 flex-1 pr-2">
											<span className="bosmax-wrap-safe block">
												{product.raw_product_title}
											</span>
											<div className="mt-2 flex flex-wrap items-center gap-2">
												<span className="inline-flex rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] text-blue-200">
													{sourceLaneLabel(product)}
												</span>
												{product.reference_only ? (
													<span className="inline-flex rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] text-amber-100">
														Reference only
													</span>
												) : null}
												<span
													className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] ${toneClass}`}
												>
													{status}
												</span>
											</div>
											{/* Reference-only: explicit REFERENCE_ONLY_PRODUCT reason */}
											{product.reference_only ? (
												<div className="bosmax-wrap-safe mt-1 text-[9px] text-amber-300/70">
													REFERENCE_ONLY_PRODUCT — Convert/Register this product
													before package load or generation.
												</div>
											) : readiness?.detail ? (
												<div className="bosmax-wrap-safe mt-2 text-[10px] text-slate-500">
													{readiness.detail}
												</div>
											) : null}
										</div>
										{selectedProduct?.id === product.id ? (
											<Check size={14} />
										) : null}
									</button>
								);
							})
						) : (
							<div className="px-4 py-6 text-center text-xs text-slate-600 italic">
								No products match your search.
							</div>
						)}
					</div>

					<div className="p-2 border-t border-slate-800 bg-slate-950/20 text-right">
						<span className="text-[9px] text-slate-600 uppercase tracking-widest font-bold pr-2">
							{filtered.length} visible
						</span>
					</div>
				</div>
			)}
		</div>
	);
}
