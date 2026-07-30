import { Check, ChevronDown, ImageOff, Minus, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
	CohortProduct,
	ProductVideoAllocation,
} from "../../api/creativeProduction";

interface ProductAllocationPickerProps {
	products: CohortProduct[];
	allocations: ProductVideoAllocation[];
	onChange: (allocations: ProductVideoAllocation[]) => void;
	blockersByProduct?: Record<string, string>;
	loading?: boolean;
	error?: string;
}

const MAX_VISIBLE_RESULTS = 40;

function previewUrl(product: CohortProduct): string | null {
	if (product.image_readiness_status === "IMAGE_CACHE_READY") {
		return `/api/products/${encodeURIComponent(product.product_id)}/image`;
	}
	const remote = product.image_url.trim();
	return /^https?:\/\//i.test(remote) ? remote : null;
}

function ProductThumbnail({ product }: { product: CohortProduct }) {
	const source = previewUrl(product);
	const [failedSource, setFailedSource] = useState<string | null>(null);
	const imageFailed = Boolean(source && failedSource === source);
	const fallbackLabel = imageFailed ? "Load failed" : "No image";
	const accessibleLabel = imageFailed
		? `Product image unavailable for ${product.product_name}`
		: source
			? `Product image for ${product.product_name}`
			: `No approved product image for ${product.product_name}`;
	return (
		<div
			role="img"
			aria-label={accessibleLabel}
			data-image-state={imageFailed ? "error" : source ? "ready" : "missing"}
			className="relative h-12 w-12 shrink-0 overflow-hidden rounded-lg border border-slate-700 bg-slate-900"
		>
			{source && !imageFailed ? (
				<img
					src={source}
					alt=""
					loading="lazy"
					onError={() => setFailedSource(source)}
					className="relative h-full w-full object-cover"
				/>
			) : (
				<div className="flex h-full w-full flex-col items-center justify-center gap-0.5 px-1 text-center text-[8px] leading-none text-slate-500">
					<ImageOff aria-hidden="true" size={14} />
					<span>{fallbackLabel}</span>
				</div>
			)}
		</div>
	);
}

export default function ProductAllocationPicker({
	products,
	allocations,
	onChange,
	blockersByProduct = {},
	loading = false,
	error = "",
}: ProductAllocationPickerProps) {
	const [open, setOpen] = useState(false);
	const [search, setSearch] = useState("");
	const [activeIndex, setActiveIndex] = useState(0);
	const rootRef = useRef<HTMLDivElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const quantityInputRefs = useRef(new Map<string, HTMLInputElement>());

	const allocationByProduct = useMemo(
		() =>
			new Map(
				allocations.map((allocation) => [allocation.product_id, allocation]),
			),
		[allocations],
	);
	const productById = useMemo(
		() => new Map(products.map((product) => [product.product_id, product])),
		[products],
	);
	const selectedProducts = allocations
		.map((allocation) => ({
			allocation,
			product: productById.get(allocation.product_id),
		}))
		.filter(
			(
				entry,
			): entry is {
				allocation: ProductVideoAllocation;
				product: CohortProduct;
			} => Boolean(entry.product),
		);
	const totalVideoCount = allocations.reduce(
		(total, allocation) => total + allocation.video_count,
		0,
	);
	const normalizedSearch = search.trim().toLocaleLowerCase();
	const matchedProducts = useMemo(
		() =>
			products
				.filter((product) =>
					product.product_name.toLocaleLowerCase().includes(normalizedSearch),
				)
				.slice(0, MAX_VISIBLE_RESULTS),
		[normalizedSearch, products],
	);

	useEffect(() => {
		const closeOnOutsideClick = (event: MouseEvent) => {
			if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
				setOpen(false);
			}
		};
		document.addEventListener("mousedown", closeOnOutsideClick);
		return () => document.removeEventListener("mousedown", closeOnOutsideClick);
	}, []);

	const openPicker = () => {
		setOpen(true);
		window.setTimeout(() => inputRef.current?.focus(), 0);
	};

	const toggleProduct = (productId: string) => {
		if (allocationByProduct.has(productId)) {
			onChange(
				allocations.filter((allocation) => allocation.product_id !== productId),
			);
			return;
		}
		onChange([
			...allocations,
			{
				product_id: productId,
				video_count: 1,
			},
		]);
		setOpen(false);
		window.setTimeout(
			() => quantityInputRefs.current.get(productId)?.focus(),
			0,
		);
	};

	const updateQuantity = (productId: string, videoCount: number) => {
		const validCount = Number.isNaN(videoCount) ? 1 : Math.max(1, Math.min(200, videoCount));
		onChange(
			allocations.map((allocation) =>
				allocation.product_id === productId
					? { ...allocation, video_count: validCount }
					: allocation,
			),
		);
	};

	const clearAll = () => {
		if (
			allocations.length > 1 &&
			!window.confirm(
				`Remove all ${allocations.length} selected products from this plan?`,
			)
		) {
			return;
		}
		onChange([]);
	};

	const handleSearchKeyDown = (
		event: React.KeyboardEvent<HTMLInputElement>,
	) => {
		if (event.key === "Escape") {
			event.preventDefault();
			setOpen(false);
			triggerRef.current?.focus();
			return;
		}
		if (!matchedProducts.length) return;
		if (event.key === "ArrowDown") {
			event.preventDefault();
			setActiveIndex((current) =>
				Math.min(current + 1, matchedProducts.length - 1),
			);
		} else if (event.key === "ArrowUp") {
			event.preventDefault();
			setActiveIndex((current) => Math.max(current - 1, 0));
		} else if (event.key === "Enter") {
			event.preventDefault();
			toggleProduct(matchedProducts[activeIndex].product_id);
		}
	};

	return (
		<div ref={rootRef} className="space-y-3" data-testid="p6-product-picker">
			<div className="relative">
				<button
					ref={triggerRef}
					type="button"
					aria-haspopup="listbox"
					aria-expanded={open}
					aria-controls="p6-product-picker-options"
					onClick={() => (open ? setOpen(false) : openPicker())}
					className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-700 bg-slate-900 px-3 py-3 text-left transition hover:border-cyan-500/60"
				>
					<span>
						<span className="block text-sm font-semibold text-white">
							{allocations.length
								? `${allocations.length} product${allocations.length === 1 ? "" : "s"} selected`
								: "Choose products"}
						</span>
						<span className="mt-0.5 block text-[11px] text-slate-400">
							{allocations.length
								? "Add products or adjust each video quantity below"
								: "Select a product to set its video quantity"}
						</span>
					</span>
					<ChevronDown
						size={17}
						className={`shrink-0 text-slate-400 transition ${open ? "rotate-180" : ""}`}
					/>
				</button>

				{open ? (
					<div className="absolute z-50 mt-2 w-full overflow-hidden rounded-xl border border-slate-700 bg-slate-950 shadow-2xl">
						<div className="flex items-center gap-2 border-b border-slate-800 p-3">
							<Search aria-hidden="true" size={15} className="text-slate-500" />
							<input
								ref={inputRef}
								role="combobox"
								aria-label="Search governed products"
								aria-expanded="true"
								aria-controls="p6-product-picker-options"
								aria-activedescendant={
									matchedProducts[activeIndex]
										? `p6-product-${matchedProducts[activeIndex].product_id}`
										: undefined
								}
								value={search}
								onChange={(event) => {
									setSearch(event.target.value);
									setActiveIndex(0);
								}}
								onKeyDown={handleSearchKeyDown}
								placeholder="Search products by name"
								className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600"
							/>
							{search ? (
								<button
									type="button"
									aria-label="Clear product search"
									onClick={() => {
										setSearch("");
										setActiveIndex(0);
									}}
									className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white"
								>
									<X size={14} />
								</button>
							) : null}
						</div>
						<div
							id="p6-product-picker-options"
							role="listbox"
							aria-label="Governed product results"
							aria-multiselectable="true"
							className="max-h-80 overflow-y-auto p-2"
						>
							{loading ? (
								<div className="p-6 text-center text-xs text-slate-500">
									Loading governed products…
								</div>
							) : error ? (
								<div className="p-4 text-xs text-rose-200">
									Products could not be loaded. Retry the page refresh.
								</div>
							) : matchedProducts.length === 0 ? (
								<div className="p-6 text-center text-xs text-slate-500">
									No governed product matches “{search}”.
								</div>
							) : (
								matchedProducts.map((product, index) => {
									const selected = allocationByProduct.has(product.product_id);
									return (
										<button
											id={`p6-product-${product.product_id}`}
											key={product.product_id}
											type="button"
											role="option"
											aria-selected={selected}
											data-testid="p6-product-option"
											data-active={index === activeIndex}
											onMouseEnter={() => setActiveIndex(index)}
											onClick={() => toggleProduct(product.product_id)}
											className={`flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left ${
												index === activeIndex
													? "bg-slate-800"
													: "hover:bg-slate-900"
											}`}
										>
											<ProductThumbnail product={product} />
											<span className="min-w-0 flex-1">
												<span className="block truncate text-sm font-medium text-slate-100">
													{product.product_name}
												</span>
												<span className="mt-1 inline-flex rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[9px] font-semibold text-emerald-200">
													Production ready
												</span>
											</span>
											<span
												className={`flex min-w-16 items-center justify-center gap-1 rounded border px-2 py-1 text-[10px] font-semibold ${
													selected
														? "border-cyan-400 bg-cyan-500 text-slate-950"
														: "border-slate-600 text-slate-300"
												}`}
											>
												{selected ? (
													<Check aria-hidden="true" size={12} />
												) : null}
												{selected ? "Selected" : "Select"}
											</span>
										</button>
									);
								})
							)}
						</div>
						{products.length > MAX_VISIBLE_RESULTS ? (
							<div className="border-t border-slate-800 px-3 py-2 text-[10px] text-slate-500">
								Showing up to {MAX_VISIBLE_RESULTS} results. Refine the search
								to find another product.
							</div>
						) : null}
					</div>
				) : null}
			</div>

			{selectedProducts.length ? (
				<fieldset
					aria-label="Selected products and quantities"
					className="space-y-2"
				>
					<div className="flex items-end justify-between gap-3">
						<div>
							<div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Selected products
							</div>
							<div
								aria-live="polite"
								data-testid="p6-allocation-summary"
								className="mt-1 text-[11px] font-medium text-cyan-200"
							>
								{selectedProducts.length}{" "}
								{selectedProducts.length === 1 ? "product" : "products"} ·{" "}
								{totalVideoCount} total{" "}
								{totalVideoCount === 1 ? "video" : "videos"}
							</div>
						</div>
						<button
							type="button"
							onClick={clearAll}
							className="text-[10px] font-semibold text-rose-300 hover:text-rose-200"
						>
							Clear all
						</button>
					</div>
					{selectedProducts.map(({ product, allocation }) => {
						const blocker = blockersByProduct[product.product_id];
						return (
							<div
								key={product.product_id}
								data-testid="p6-selected-product"
								className="flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-2.5"
							>
								<div className="flex items-center gap-3 min-w-0 flex-1">
									<ProductThumbnail product={product} />
									<div className="min-w-0 flex-1">
										<div className="truncate text-xs font-semibold text-white" title={product.product_name}>
											{product.product_name}
										</div>
										<div
											className={`mt-0.5 text-[10px] ${
												blocker ? "text-amber-200" : "text-emerald-300"
											}`}
										>
											{blocker || "Ready for governed planning"}
										</div>
									</div>
								</div>
								<div className="flex items-center gap-2 shrink-0">
									<div className="flex flex-col items-end">
										<span className="text-[10px] text-slate-400">Video quantity</span>
										<div className="mt-1 flex items-center rounded-lg border border-slate-700 bg-slate-950 p-0.5">
											<button
												type="button"
												aria-label={`Decrease quantity for ${product.product_name}`}
												onClick={() =>
													updateQuantity(
														product.product_id,
														Math.max(1, allocation.video_count - 1),
													)
												}
												disabled={allocation.video_count <= 1}
												className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent"
											>
												<Minus size={13} />
											</button>
											<input
												ref={(node) => {
													if (node) {
														quantityInputRefs.current.set(product.product_id, node);
													} else {
														quantityInputRefs.current.delete(product.product_id);
													}
												}}
												aria-label={`Video quantity for ${product.product_name}`}
												type="number"
												min={1}
												max={200}
												value={allocation.video_count}
												onChange={(event) =>
													updateQuantity(
														product.product_id,
														Number(event.target.value),
													)
												}
												className="w-12 text-center text-xs font-semibold text-white bg-transparent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
											/>
											<button
												type="button"
												aria-label={`Increase quantity for ${product.product_name}`}
												onClick={() =>
													updateQuantity(
														product.product_id,
														Math.min(200, allocation.video_count + 1),
													)
												}
												disabled={allocation.video_count >= 200}
												className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent"
											>
												<Plus size={13} />
											</button>
										</div>
									</div>
									<button
										type="button"
										aria-label={`Remove ${product.product_name}`}
										onClick={() => toggleProduct(product.product_id)}
										className="rounded-lg p-2 text-slate-500 hover:bg-rose-950/40 hover:text-rose-300"
									>
										<Trash2 size={15} />
									</button>
								</div>
							</div>
						);
					})}
				</fieldset>
			) : null}
		</div>
	);
}

