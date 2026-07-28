import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { searchProducts } from "../../api/products";
import type { Product, WorkspacePackageReadinessItem } from "../../types";
import { VisualAssetPreview } from "./VisualAssetPicker";

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

function browserSafeRemoteImageUrl(product: Product): string | null {
	for (const candidate of [
		product.image_url,
		product.image_analysis?.image_url,
	]) {
		const value = String(candidate ?? "").trim();
		if (/^https?:\/\//i.test(value)) return value;
	}
	return null;
}

function productPreviewUrl(product: Product): string | null {
	if (product.image_readiness_status === "IMAGE_CACHE_READY") {
		return `/api/products/${encodeURIComponent(product.id)}/image`;
	}
	return browserSafeRemoteImageUrl(product);
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
	const [serverResults, setServerResults] = useState<Product[]>([]);
	const [isSearching, setIsSearching] = useState(false);
	const [searchError, setSearchError] = useState<string | null>(null);
	const containerRef = useRef<HTMLDivElement>(null);

	// Debounced server-side search. The `products` prop only holds the first
	// client-loaded page (the /api/products?limit=… window), so canonical
	// products that sort after it — e.g. MANUAL BOSMAX / Minyak Warisan rows —
	// are invisible to a pure client-side filter. Querying /api/products/search
	// keeps them discoverable by name without loading the entire catalog.
	useEffect(() => {
		const query = search.trim();
		setServerResults([]);
		setSearchError(null);
		if (query.length < 2) {
			setIsSearching(false);
			return;
		}
		let isActive = true;
		setIsSearching(true);
		const handle = window.setTimeout(() => {
			void searchProducts(query, 25, "GENERATION")
				.then((response) => {
					if (isActive) setServerResults(response.items ?? []);
				})
				.catch((error: unknown) => {
					if (isActive) {
						setServerResults([]);
						setSearchError(error instanceof Error ? error.message : "Product search failed.");
					}
				})
				.finally(() => {
					if (isActive) setIsSearching(false);
				});
		}, 250);
		return () => {
			isActive = false;
			window.clearTimeout(handle);
		};
	}, [search]);

	const searchLower = search.trim().toLowerCase();
	const clientFiltered = products.filter((product) =>
		product.raw_product_title.toLowerCase().includes(searchLower),
	);
	// Union the client-loaded matches with the server-side matches, keeping the
	// loaded catalog order stable and appending any server-only rows (deduped
	// by id) so results beyond the first page still appear.
	const seenIds = new Set(clientFiltered.map((product) => product.id));
	const filtered = [
		...clientFiltered,
		...serverResults.filter(
			(product) => product?.id && !seenIds.has(product.id),
		),
	];

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
	const isReferenceOnly = (product: Product) =>
		Boolean(product.reference_only) || product.id.startsWith("fastmoss-ref:");

	return (
		<div className="relative min-w-0" ref={containerRef}>
			<div className="flex min-h-16 items-center gap-2 rounded-xl border border-slate-800 bg-slate-950 p-2 transition-all hover:border-blue-500/50">
				{selectedProduct ? (
					<div className="w-16 shrink-0">
						<VisualAssetPreview
							previewUrl={productPreviewUrl(selectedProduct)}
							subtitle={selectedProduct.id}
							title={selectedProduct.raw_product_title}
						/>
					</div>
				) : null}
				<button
					type="button"
					onClick={() => setIsOpen(!isOpen)}
					className="group flex min-w-0 flex-1 cursor-pointer items-start justify-between gap-3 rounded-lg px-2 py-1 text-left"
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
									{isReferenceOnly(selectedProduct) ? (
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
								{readinessByProductId[selectedProduct.id]?.detail ? (
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
						className={`text-slate-500 transition-transform group-hover:text-blue-400 ${isOpen ? "rotate-180" : ""}`}
					/>
				</button>
			</div>
			{selectedProduct && isReferenceOnly(selectedProduct) ? (
				<div className="bosmax-wrap-safe mt-2 flex items-start justify-between gap-2 text-[10px] text-amber-200/80">
					<span>
						{selectedProduct.catalog_visibility_reason ||
							"FastMoss reference is review-only. Convert eligible references through Bulk FastMoss Convert before workspace generation."}
					</span>
					<a
						href="/product-registration?tab=bulk"
						className="shrink-0 whitespace-nowrap rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold text-amber-300 transition-colors hover:bg-amber-500/20"
					>
						Open Bulk FastMoss Convert
					</a>
				</div>
			) : null}

			{isOpen && (
				<div className="absolute z-50 mt-2 w-full min-w-0 overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl shadow-black/50 backdrop-blur-xl">
					<div className="p-3 border-bottom border-slate-800 bg-slate-950/50 flex items-center gap-2">
						<Search size={14} className="text-slate-500" />
						<input
							type="text"
							className="bg-transparent border-none outline-none text-xs text-slate-300 w-full"
							placeholder="Search all products by name..."
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
								const referenceOnly = isReferenceOnly(product);
								return (
									<div
										key={product.id}
										className={`flex items-center gap-2 border-b border-slate-800 px-3 py-2 text-[11px] ${referenceOnly ? "opacity-60" : ""} ${
											selectedProduct?.id === product.id
												? "bg-blue-600/20 text-blue-300"
												: "text-slate-400"
										}`}
									>
										<div className="w-16 shrink-0">
											<VisualAssetPreview
												previewUrl={productPreviewUrl(product)}
												subtitle={product.id}
												title={product.raw_product_title}
											/>
										</div>
										<button
											type="button"
											// RPA Round A: option keyed by the IMMUTABLE product id so a
											// UI-click operator selects by id, never by mutable title text.
											data-testid="product-option"
											data-product-id={product.id}
											data-readiness={status}
											data-reference-only={referenceOnly ? "true" : "false"}
											data-selected={
												selectedProduct?.id === product.id ? "true" : "false"
											}
											disabled={referenceOnly}
											onClick={() => {
												if (referenceOnly) return;
												onSelect(product);
												setIsOpen(false);
												setSearch("");
											}}
											className={`flex min-w-0 flex-1 items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left ${
												referenceOnly
													? "cursor-not-allowed"
													: "hover:bg-slate-800 hover:text-slate-200"
											}`}
										>
											<span className="min-w-0 flex-1">
												<span className="bosmax-wrap-safe block">
													{product.raw_product_title}
												</span>
												<span className="mt-1 flex flex-wrap items-center gap-1.5">
													<span className="inline-flex rounded-full border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.14em] text-blue-200">
														{sourceLaneLabel(product)}
													</span>
													{referenceOnly ? (
														<span className="inline-flex rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.14em] text-amber-100">
															Reference only
														</span>
													) : null}
													<span
														className={`inline-flex rounded-full border px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.14em] ${toneClass}`}
													>
														{status}
													</span>
												</span>
												{referenceOnly ? (
													<span className="bosmax-wrap-safe mt-1 block text-[9px] text-amber-300/70">
														REFERENCE_ONLY_PRODUCT — Convert/Register before
														generation.
													</span>
												) : readiness?.detail ? (
													<span className="bosmax-wrap-safe mt-1 block text-[9px] text-slate-500">
														{readiness.detail}
													</span>
												) : null}
											</span>
											<Check
												className={
													selectedProduct?.id === product.id
														? "text-blue-300"
														: "text-slate-500"
												}
												size={14}
											/>
										</button>
									</div>
								);
							})
						) : isSearching ? (
							<div className="px-4 py-6 text-center text-xs text-slate-500 italic">
								Searching all products…
							</div>
						) : (
							<div className="px-4 py-6 text-center text-xs text-slate-600 italic">
								No products match your search.
							</div>
						)}
						{searchError ? (
							<div className="px-4 py-3 text-center text-xs text-rose-300">
								{searchError}
							</div>
						) : null}
					</div>

					<div className="p-2 border-t border-slate-800 bg-slate-950/20 text-right">
						<span className="text-[9px] text-slate-600 uppercase tracking-widest font-bold pr-2">
							{`${filtered.length} visible${isSearching ? " — searching…" : ""}`}
						</span>
					</div>
				</div>
			)}
		</div>
	);
}
